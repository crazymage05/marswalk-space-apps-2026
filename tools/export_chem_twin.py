"""data/chem_b/ (PDS ChemCam MOC + APXS oxide tables, rover waypoints) -> demo/twin/chem.json.

One record per ChemCam target (mean over its laser points) and per APXS oxide product, sols 4500-4799.
Position = MMGIS waypoint of the rover's (site, drive) when the observation was made, placed on the twin grid with
tools/feeds/_common.TwinGeo (same HiRISE coregistration as the photos). This is where the ROVER stood, not where the
target is: ChemCam targets are a few metres out, APXS is at the arm's reach.
Records outside the twin's terrain grid are dropped (and counted). Nothing is invented: a value missing in the PDS file is omitted.
"""
import csv, glob, json, os, re, statistics, sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "feeds"))
from _common import TwinGeo  # noqa: E402  (read-only reuse of the twin lon/lat -> grid mapping)

ROOT = os.path.abspath(os.path.join(HERE, ".."))
CH = os.path.join(ROOT, "data", "chem_b")
OUT = os.path.join(ROOT, "demo", "twin", "chem.json")
SOLS = (4500, 4799)
CC_OX = ["SiO2", "TiO2", "Al2O3", "FeOT", "MgO", "CaO", "Na2O", "K2O", "MnO"]
CC_URL = "https://pds-geosciences.wustl.edu/msl/msl-m-chemcam-libs-4_5-rdr-v1/mslccm_1xxx/"
AP_URL = "https://pds-geosciences.wustl.edu/msl/msl-m-apxs-4_5-rdr-v1/mslapx_1xxx/"

BOXWORK = {
    "summary": ("NASA's own description of the boxwork result is qualitative. These are the only chemistry statements "
                "taken from it; the layer does not add its own interpretation."),
    "quotes": [
        {"text": "The bedrock between the boxwork ridges has a different composition than other layers of Mount Sharp.",
         "source": "NASA, \"NASA's Curiosity Mars Rover Starts Unpacking Boxwork Formations\", 23 June 2025",
         "url": "https://www.nasa.gov/missions/mars-science-laboratory/curiosity-rover/nasas-curiosity-mars-rover-starts-unpacking-boxwork-formations"},
        {"text": "The bedrock below these ridges likely formed when groundwater trickling through the rock left behind minerals.",
         "source": "same release", "url": "https://www.nasa.gov/missions/mars-science-laboratory/curiosity-rover/nasas-curiosity-mars-rover-starts-unpacking-boxwork-formations"},
    ],
    "not_found": "No peer-reviewed paper with boxwork ridge-vs-hollow oxide numbers was found in this session, so none is cited.",
}


def num(s):
    try:
        return float(str(s).strip())
    except ValueError:
        return None


def waypoints():
    d = json.load(open(os.path.join(CH, "MSL_waypoints.json"), encoding="utf-8"))
    wp = sorted((f["properties"]["site"], f["properties"]["drive"], f["properties"]["lon"], f["properties"]["lat"])
                for f in d["features"])
    return wp, {(s, dr): (lo, la) for s, dr, lo, la in wp}


def locate(site, drive, wp, exact):
    if (site, drive) in exact:
        return exact[(site, drive)], "waypoint of this exact site/drive"
    prior = [w for w in wp if w[0] == site and w[1] <= drive]
    if prior:
        return prior[-1][2:], "last waypoint before this drive (drive %d) of site %d" % (prior[-1][1], site)
    return None, None


def chemcam(wp, exact, geo, stats):
    rows = list(csv.reader(open(os.path.join(CH, "chemcam", "msl_ccam_obs.csv"), encoding="utf-8", errors="replace")))
    ix = {n.strip(): i for i, n in enumerate(rows[0])}
    obs = {}
    for r in rows[1:]:
        if r[0].isdigit() and r[ix["Type of Product"]] == "1-D Single laser":
            obs[r[ix["Spacecraft Clock"]].strip()] = r
    groups = {}
    for f in sorted(glob.glob(os.path.join(CH, "chemcam", "moc_*.csv"))):
        rd = list(csv.reader(open(f, encoding="utf-8", errors="replace")))
        hdr = next(i for i, r in enumerate(rd) if r and r[0] == "File")
        h = rd[hdr]
        for r in rd[hdr + 1:]:
            if not r or not r[0].startswith("CL5"):
                continue
            o = obs.get(r[0].split("CCS")[0][4:])
            if not o:
                stats["cc_unmatched"] += 1
                continue
            sol = int(o[0])
            if not SOLS[0] <= sol <= SOLS[1]:
                continue
            row = dict(zip(h, r))
            key = (sol, o[ix["Target"]].strip(), int(o[ix["RMC Site"]]), int(o[ix["RMC Drive"]]))
            groups.setdefault(key, []).append((row, o))
    out = []
    for (sol, tgt, site, drive), pts in sorted(groups.items()):
        stats["cc_targets"] += 1
        pos, how = locate(site, drive, wp, exact)
        if pos is None:
            stats["cc_nopos"] += 1
            continue
        if not geo.inside(*pos):
            stats["cc_outside"] += 1
            continue
        x, y = geo.xy(*pos)
        ox = {}
        for o_ in CC_OX:
            v = [num(p[0].get(o_)) for p in pts if num(p[0].get(o_)) is not None]
            rm = [num(p[0].get(o_ + " RMSEP")) for p in pts if num(p[0].get(o_ + " RMSEP")) is not None]
            if not v:
                continue
            ox[o_] = {"wt": round(statistics.mean(v), 3)}
            if rm:
                ox[o_]["rmsep"] = round(statistics.mean(rm), 3)
            if len(v) > 1:
                ox[o_]["sd_points"] = round(statistics.stdev(v), 3)
        sm = [num(p[0].get("Sum of Oxides")) for p in pts if num(p[0].get("Sum of Oxides")) is not None]
        dist = [num(p[1][ix["Distance (m)"]]) for p in pts if num(p[1][ix["Distance (m)"]]) is not None]
        auto = tgt.lower().startswith("aegis")
        out.append({
            "name": tgt, "sol": sol, "instrument": "ChemCam LIBS", "x": x, "y": y, "label": "measured",
            "site": site, "drive": drive, "n_points": len(pts),
            "autonomous": auto,
            "distance_m": round(statistics.mean(dist), 2) if dist else None,
            "oxides": ox, "oxide_sum": round(statistics.mean(sm), 2) if sm else None,
            "uncertainty_note": "Per oxide: wt%% = mean of %d laser point(s); rmsep = instrument model error (RMSEP, from the PDS table); "
                                "sd_points = spread between points on this target." % len(pts),
            "position_note": "Rover position (%s), not the target: the target was %s m from the rover along the mast pointing. "
                             "Grid cells are 4 m wide, so expect an error of about 2 cells (8 m) or more."
                             % (how, "%.1f" % statistics.mean(dist) if dist else "a few"),
            "provenance": {"oxides": CC_URL + "data/moc/ (MOC tables, sols 4489-4843)",
                           "target_site_drive": CC_URL + "document/msl_ccam_obs.csv",
                           "position": "https://mars.nasa.gov/mmgis-maps/MSL/Layers/json/MSL_waypoints.json"},
        })
    return out


def apxs(wp, exact, geo, stats):
    out = []
    for f in sorted(glob.glob(os.path.join(CH, "apxs", "sol*", "*rwp*.csv"))):
        lbl = open(f[:-4] + ".lbl", encoding="utf-8", errors="replace").read()
        sol = int(re.search(r"PLANET_DAY_NUMBER\s*=\s*(\d+)", lbl)[1])
        if not SOLS[0] <= sol <= SOLS[1]:
            continue
        m = re.search(r"ROVER_MOTION_COUNTER\s*=\s*\((\d+),\s*(\d+)", lbl)
        site, drive = int(m[1]), int(m[2])
        st = re.search(r"START_TIME\s*=\s*(\S+)", lbl)[1]
        stats["apxs_products"] += 1
        pos, how = locate(site, drive, wp, exact)
        if pos is None:
            stats["apxs_nopos"] += 1
            continue
        if not geo.inside(*pos):
            stats["apxs_outside"] += 1
            continue
        x, y = geo.xy(*pos)
        ox = {}
        for r in list(csv.reader(open(f, encoding="utf-8")))[1:]:
            if len(r) >= 3 and num(r[1]) is not None:
                ox[r[0].strip()] = {"wt": num(r[1]), "stderr": num(r[2])}
        seq = re.search(r'SEQUENCE_ID\s*=\s*"?([^"\s]+)', lbl)
        name = "APXS sol %d" % sol
        out.append({
            "name": name, "sol": sol, "instrument": "APXS", "x": x, "y": y, "label": "measured",
            "site": site, "drive": drive, "start_utc": st, "sequence": seq[1] if seq else None,
            "oxides": ox, "oxide_sum": round(sum(v["wt"] for k, v in ox.items() if k not in ("Ni", "Zn", "Br")), 2),
            "uncertainty_note": "stderr = statistical uncertainty (precision) from the PDS table; it is not the accuracy. "
                                "Ni, Zn and Br are elements, listed in the file as weight percent.",
            "position_note": "Rover position (%s). The arm places APXS on a target within about 1 m of the rover; "
                             "the PDS product does not carry the target name." % how,
            "provenance": {"oxides": AP_URL + "data/sol%05d/" % sol + os.path.basename(f),
                           "site_drive": AP_URL + "data/sol%05d/" % sol + os.path.basename(f)[:-4] + ".lbl",
                           "position": "https://mars.nasa.gov/mmgis-maps/MSL/Layers/json/MSL_waypoints.json"},
        })
    return out


def main():
    geo = TwinGeo()
    wp, exact = waypoints()
    stats = {k: 0 for k in ("cc_unmatched", "cc_targets", "cc_nopos", "cc_outside", "apxs_products", "apxs_nopos", "apxs_outside")}
    cc = chemcam(wp, exact, geo, stats)
    ap = apxs(wp, exact, geo, stats)
    prov = json.load(open(os.path.join(CH, "provenance.json"), encoding="utf-8"))
    d = {
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "campaign_sols": list(SOLS),
        "grid": {"w": geo.W, "h": geo.H, "cell_m": 4.047},
        "coverage": prov.get("coverage"),
        "credit": "NASA / PDS Geosciences Node: ChemCam (LANL/IRAP), APXS (Univ. of Guelph); rover positions NASA/JPL MMGIS",
        "oxide_unit": "weight percent",
        "boxwork": BOXWORK,
        "counts": {"ChemCam LIBS": len(cc), "APXS": len(ap), "dropped": stats},
        "targets": sorted(cc + ap, key=lambda t: (t["sol"], t["instrument"], t["name"])),
    }
    json.dump(d, open(OUT, "w", encoding="utf-8"), indent=1)
    print("ChemCam targets in campaign sols:", stats["cc_targets"], "| placed on the twin:", len(cc))
    print("APXS oxide products in campaign sols:", stats["apxs_products"], "| placed on the twin:", len(ap))
    print("dropped:", stats)
    print("wrote", OUT, os.path.getsize(OUT), "bytes")


if __name__ == "__main__":
    main()
