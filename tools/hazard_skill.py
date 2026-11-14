"""Skill check for DONKI WSA-ENLIL Mars arrival predictions against Curiosity RAD (read only on data/raw).

Inputs : data/processed/hazards/donki_enlil_mars_impacts.json (DONKI rows, extracted verbatim)
         data/raw/curiosity/rad/DATA/*/RAD_RDR_*.TXT           (read only; one sol per file, years 2024-2026)
Output : data/processed/hazards/cme_skill.json
Run    : python tools/hazard_skill.py
It asks whether any RAD file contains a dose-rate enhancement and whether a DONKI Mars arrival falls inside a RAD
file. It does not invent an arrival-time error: if the data hold no observed onset, the timing error comes from the
published studies (cited in the output) and is marked as published, not measured here.
"""
import glob, hashlib, json, os, re, statistics as st, datetime as dt
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAD = os.path.join(ROOT, "data", "raw", "curiosity", "rad", "DATA")
OUT = os.path.join(ROOT, "data", "processed", "hazards")
D = dt.datetime


def utc(s):
    a, t = s.split()
    y, d = a.split("-")
    return D(int(y), 1, 1) + dt.timedelta(days=int(d) - 1, hours=int(t[:2]), minutes=int(t[3:5]), seconds=int(t[6:8]))


def read_file(f):
    obs = []
    cur = None
    mode = None
    for line in open(f, errors="ignore"):
        if line.startswith("START_OBS_UTC="):
            cur = utc(line.split('"')[1])
        elif line.startswith("[DOSIMETRY_TOTAL_DOSE_B"):
            mode = "B"
        elif line.startswith("[DOSIMETRY_TOTAL_DOSE_E"):
            mode = "E"
        elif mode and line.strip() and not line.startswith("["):
            try:
                v = float(line.split()[0])
            except ValueError:
                v = None
            obs.append((cur, mode, v))
            mode = None
        elif line.startswith("["):
            mode = None
    return obs


def main():
    files = sorted(f for f in glob.glob(os.path.join(RAD, "*", "RAD_RDR_20*.TXT")) if re.search(r"RDR_(2024|2025|2026)_", f))
    sols = []
    for f in files:
        o = read_file(f)
        b = [(t, v) for t, m, v in o if m == "B" and v and v > 0]
        e = [(t, v) for t, m, v in o if m == "E" and v and v > 0]
        if not b:
            continue
        sols.append({"sol": int(re.search(r"_(\d{4})_V", f).group(1)), "file": os.path.basename(f),
                     "start": b[0][0], "end": b[-1][0] + dt.timedelta(seconds=961), "B": b, "E": e})
    allB = [v for s in sols for _, v in s["B"]]
    med = st.median(allB)
    mad = st.median(abs(v - med) for v in allB) * 1.4826
    thr = med + 5 * mad
    per_sol = []
    for s in sols:
        run = best = 0
        best_t = cur_t = None
        for t, v in s["B"]:
            if v > thr:
                run += 1
                if run == 1:
                    cur_t = t
                if run > best:
                    best, best_t = run, cur_t
            else:
                run = 0
        mx = max(s["B"], key=lambda x: x[1])
        per_sol.append({"sol": s["sol"], "start_utc": s["start"].isoformat() + "Z", "end_utc": s["end"].isoformat() + "Z",
                        "n_obs": len(s["B"]), "B_median": round(st.median(v for _, v in s["B"]), 3),
                        "E_median": round(st.median(v for _, v in s["E"]), 3) if s["E"] else None,
                        "B_max": round(mx[1], 3), "B_max_utc": mx[0].isoformat() + "Z",
                        "longest_run_above_threshold": best, "run_start_utc": best_t.isoformat() + "Z" if best_t else None})
    sustained = [p for p in per_sol if p["longest_run_above_threshold"] >= 3]
    single_spikes = [p for p in per_sol if p["B_max"] > thr and p["longest_run_above_threshold"] < 3]
    src = os.path.join(OUT, "donki_enlil_mars_impacts.json")
    rows = json.load(open(src))["rows"]
    inside = []
    for r in rows:
        a = D.strptime(r["arrivalTime"], "%Y-%m-%dT%H:%MZ")
        for s in sols:
            if s["start"] <= a <= s["end"]:
                inside.append({"simulationID": r["simulationID"], "arrival": r["arrivalTime"], "glancing": r["isGlancingBlow"], "sol": s["sol"]})
    may = [p for p in per_sol if "2024-05-08" <= p["start_utc"][:10] <= "2024-05-28"]
    by_cme = {}
    for r in rows:
        if r["cmeID"]:
            by_cme.setdefault(r["cmeID"], []).append(D.strptime(r["arrivalTime"], "%Y-%m-%dT%H:%MZ"))
    spreads = [(max(v) - min(v)).total_seconds() / 3600 for v in by_cme.values() if len(v) >= 2]
    res = {
        "provenance": {"script": "tools/hazard_skill.py", "generated_utc": D.utcnow().isoformat(timespec="seconds") + "Z",
                       "donki_rows": "data/processed/hazards/donki_enlil_mars_impacts.json, sha256 " + hashlib.sha256(open(src, "rb").read()).hexdigest(),
                       "rad_source": "data/raw/curiosity/rad/DATA/*/RAD_RDR_*.TXT, DOSIMETRY_TOTAL_DOSE_B (silicon detector, uGy/h), read only",
                       "label": "measured (RAD) vs modelled (WSA-ENLIL)"},
        "rad_coverage": {"files_2024_2026": len(per_sol), "first_start_utc": per_sol[0]["start_utc"], "last_end_utc": per_sol[-1]["end_utc"],
                         "sampling": "one Mars sol (about 24.7 h) per file; one file per 10 sols in 2025, about one per 50 sols in 2024",
                         "may_2024_storm_covered": bool(may), "files_between_2024_05_08_and_2024_05_28": may,
                         "nearest_files_to_may_2024": [p for p in per_sol if p["sol"] in (4151, 4201)]},
        "detection_threshold": {"statistic": "median + 5 x MAD-sigma of all RAD B observations 2024-2026", "median_uGy_h": round(med, 3),
                                "sigma_mad_uGy_h": round(mad, 3), "threshold_uGy_h": round(thr, 3), "sustained_means_consecutive_obs": 3},
        "rad_files_with_sustained_enhancement": sustained,
        "rad_files_with_single_sample_spike_only": single_spikes,
        "donki_mars_impacts": {"rows_total": len(rows), "windows": "2024-05 and 2025-03-01..2025-12-25", "rows_inside_a_rad_file": len(inside),
                               "inside": inside, "rows_inside_that_are_glancing": sum(1 for i in inside if i["glancing"]),
                               "run_to_run_spread_hours_same_CME": {
                                   "n_cmes_with_2plus_runs": len(spreads), "median": round(st.median(spreads), 1) if spreads else None,
                                   "max": round(max(spreads), 1) if spreads else None,
                                   "note": "different cone inputs for one CME; spread between model runs, not error versus observation"}},
        "own_timing_error": {"computed": False,
                             "reason": "No RAD file shows a sustained enhancement or a Forbush decrease tied to a DONKI Mars arrival, and RAD files cover one sol in ten or fewer, so there is no observed onset to difference against. The May 2024 storm that Curiosity RAD measured is not in the repo RAD files (sols 4151 and 4201 bracket it)."},
        "published_timing_error": [
            {"study": "von Forstner et al., Using Forbush decreases to derive the transit time of ICMEs propagating from 1 AU to Mars",
             "ref": "arXiv:1712.07301, DOI 10.1002/2017JA024700 (as listed on the arXiv page)", "n_events": 15,
             "result": "ENLIL minus Forbush-decrease cross-correlation transit time: mean -7 +/- 11 h (standard error of the mean); mean absolute difference about 10 h",
             "caveat": "Where several ENLIL runs existed the run closest to the observed 1 AU arrival was chosen, so this is optimistic for an operational forecast. It is a 1 AU to Mars transit time, not a blind forecast."},
            {"study": "von Forstner et al., Tracking and Validating ICMEs Propagating Toward Mars Using STEREO Heliospheric Imagers Combined With Forbush Decreases Detected by MSL/RAD",
             "ref": "arXiv:1904.10859, DOI 10.1029/2018SW002138 (as listed on the arXiv page)", "n_events": 45,
             "result": "Arrival at Mars from heliospheric-imager methods versus RAD Forbush decrease: mean difference -11 to +5 h depending on method, standard deviation 17 to 20 h",
             "caveat": "Heliospheric-imager methods, not WSA-ENLIL. 45 of 149 ICMEs could be linked to a Forbush decrease."}],
        "value_used_by_hazard_watch": {"typical_timing_error_h": 20,
                                       "basis": "upper end of the published standard deviation (17-20 h); the ENLIL-specific mean absolute difference (about 10 h) is shown beside it",
                                       "label": "published, not measured here"},
        "limits": ["RAD dose rate is a coarse detector of CME arrival; only a large SEP or Forbush decrease stands out.",
                   "DONKI gives no uncertainty on the Mars arrival time.",
                   "In Nov 2025 Mars was far from the Sun-Earth line: the large Earth-directed CMEs of 9-14 Nov 2025 had no DONKI Mars impact, and RAD sol 4720 (15-16 Nov) shows no sustained enhancement. Consistent, but one case."]
    }
    json.dump(res, open(os.path.join(OUT, "cme_skill.json"), "w"), indent=1)
    print("rad files", len(per_sol), "threshold %.2f uGy/h" % thr, "sustained", [(p["sol"], p["run_start_utc"], p["longest_run_above_threshold"]) for p in sustained],
          "spikes", [(p["sol"], p["B_max_utc"], p["B_max"]) for p in single_spikes])
    print("DONKI Mars rows", len(rows), "inside RAD files", len(inside), "of which glancing", res["donki_mars_impacts"]["rows_inside_that_are_glancing"], "May2024 covered", bool(may))
    print("run-to-run spread h", res["donki_mars_impacts"]["run_to_run_spread_hours_same_CME"])


main()
