"""Space-weather hazard source for the MARSWALK feed: NASA DONKI (CCMC), api.nasa.gov, DEMO_KEY.

Endpoints (all GET https://api.nasa.gov/DONKI/<name>?startDate=YYYY-MM-DD&endDate=YYYY-MM-DD&api_key=DEMO_KEY):
  WSAEnlilSimulations  WSA-ENLIL+Cone runs. Each run has impactList[] with location (Earth-side planets, probes, "Mars"),
                       arrivalTime and isGlancingBlow. No uncertainty is published for the arrival time.
  SEP                  solar energetic particle events seen by instruments (GOES, SOHO COSTEP, STEREO A, and REleASE model rows).
  CME, CMEAnalysis     CME catalogue and the cone fits (speed, longitude, half angle) that feed WSA-ENLIL.
DONKI limits a request to 60 days. DEMO_KEY is rate limited (the response header X-Ratelimit-Limit was 10 per hour on
2026-11-13), so poll() makes 2 requests (3 with with_cme) and never retries in a loop.

Record label rules: a WSA-ENLIL Mars arrival is "modelled"; an SEP row from a real instrument is "measured" at that
instrument (near Earth or STEREO A, so it says nothing about Mars by itself); REleASE rows are model output, "modelled".
Skill check of the Mars arrival times: data/processed/hazards/cme_skill.json, docs/hazard_watch.md.

Standalone: python tools/feeds/space_weather.py --days 30 [--with-cme]
"""
import argparse, datetime as dt, hashlib, json, os, sys, urllib.error, urllib.parse, urllib.request

SOURCE = {"id": "space_weather", "name": "NASA DONKI space weather (WSA-ENLIL Mars impacts, SEP events)", "mission": "heliophysics (CCMC)",
          "instrument": "WSA-ENLIL+Cone model; SEP instruments listed per record", "kind": "hazard", "typical_latency": "hours (model runs follow a CME by about 4 to 24 h)"}
BASE = "https://api.nasa.gov/DONKI/"
UA = "marswalk-demo/1.0"
MAX_DAYS = 59   # DONKI rejects a range longer than 60 days; 59 days back from today is accepted
# Mars sol number from UTC. Reference: RAD label of RAD_RDR_2024_100_16_45_4151_V00.TXT gives START_OBS_UTC 2024-100 16:45:20
# at START_OBS_MARS "4151 0:31:37" (local mean solar time of the rover). Sol length 88775.244 s.
SOL_REF_UTC = dt.datetime(2024, 4, 9, 16, 45, 20)
SOL_REF = 4151 + (31 * 60 + 37) / 86400.0
SOL_S = 88775.244


def sol_of(t):
    return int(SOL_REF + (t - SOL_REF_UTC).total_seconds() / SOL_S)


def parse(s):
    if not s:
        return None
    for f in ("%Y-%m-%dT%H:%MZ", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return dt.datetime.strptime(s, f)
        except ValueError:
            pass
    return None


def iso(t):
    return t.strftime("%Y-%m-%dT%H:%M:%SZ") if t else None


def get(endpoint, start, end, key):
    q = urllib.parse.urlencode({"startDate": start, "endDate": end, "api_key": key})
    req = urllib.request.Request(BASE + endpoint + "?" + q, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=40) as r:
        body = r.read()
        return json.loads(body.decode("utf-8")), hashlib.sha256(body).hexdigest(), r.headers.get("X-Ratelimit-Remaining")


def enlil_records(rows, sha, now):
    """One record per CME whose WSA-ENLIL run lists Mars; several runs of the same CME are folded into one record."""
    by = {}
    for s in rows:
        mars = [i for i in (s.get("impactList") or []) if i.get("location") == "Mars"]
        if not mars:
            continue
        c = (s.get("cmeInputs") or [{}])[0]
        by.setdefault(c.get("CMEID") or s["simulationID"], []).append((s, c, mars[0]))
    out = []
    for cme, runs in by.items():
        runs.sort(key=lambda r: r[0]["modelCompletionTime"])
        s, c, imp = runs[-1]
        arr = parse(imp["arrivalTime"])
        arrs = sorted(parse(r[2]["arrivalTime"]) for r in runs)
        t0 = parse(c.get("cmeStartTime"))
        spread = (arrs[-1] - arrs[0]).total_seconds() / 3600
        note = ("WSA-ENLIL+Cone predicts this CME reaches Mars at %s UTC%s. DONKI states no uncertainty for this time; "
                "published arrival-time errors at Mars are many hours (SD 17-20 h, data/processed/hazards/cme_skill.json). "
                "CME speed %s km/s, longitude %s deg at 21.5 Rs. %d run(s); latest run %s%s. A Mars-wide arrival, not specific to Gale."
                % (imp["arrivalTime"], " (glancing blow)" if imp.get("isGlancingBlow") else "", c.get("speed"), c.get("longitude"), len(runs),
                   s["modelCompletionTime"], "; run spread %.1f h" % spread if len(runs) > 1 else ""))
        out.append({"id": "donki-enlil-mars-" + str(cme), "type": "hazard", "source": SOURCE["id"], "observed_utc": iso(t0), "available_utc": iso(parse(s["modelCompletionTime"])),
                    "ingested_utc": iso(now), "sol": sol_of(arr), "label": "modelled",
                    "hazard": {"kind": "cme", "start_utc": iso(arr), "end_utc": iso(arr), "center": None, "radius_km": None, "affects_site": True, "note": note},
                    "provenance": {"url": s.get("link"), "sha256": sha, "method": "DONKI WSAEnlilSimulations impactList location=Mars, latest run per CME"}})
    return out


def sep_records(rows, sha, now):
    """One record per linked CME / flare (several instruments see the same event)."""
    by = {}
    for e in rows:
        links = [l["activityID"] for l in (e.get("linkedEvents") or []) if "CME" in l["activityID"]] or [e["sepID"]]
        by.setdefault(links[0], []).append(e)
    out = []
    for key, evs in by.items():
        evs.sort(key=lambda e: e["eventTime"])
        names = [i["displayName"] for e in evs for i in e["instruments"]]
        real = [n for n in names if not n.startswith("MODEL")]
        label = "measured" if real else "modelled"
        t0 = parse(evs[0]["eventTime"])
        note = ("SEP onset seen by %s. Seen near Earth or at STEREO A, not at Mars: Mars is only affected if it is magnetically connected to the same "
                "solar longitude. DONKI gives no end time." % ", ".join(sorted(set(real or names))[:4]))
        out.append({"id": "donki-sep-" + key, "type": "hazard", "source": SOURCE["id"], "observed_utc": iso(t0), "available_utc": iso(parse(evs[0].get("submissionTime"))),
                    "ingested_utc": iso(now), "sol": sol_of(t0), "label": label,
                    "hazard": {"kind": "sep", "start_utc": iso(t0), "end_utc": None, "center": None, "radius_km": None, "affects_site": False, "note": note},
                    "provenance": {"url": evs[0].get("link"), "sha256": sha, "method": "DONKI SEP, grouped by linked CME"}})
    return out


def poll(state):
    state = dict(state or {})
    now = dt.datetime.utcnow()
    days = min(int(state.get("days", 30)), MAX_DAYS)
    key = os.environ.get("NASA_API_KEY", "DEMO_KEY")
    start, end = (now - dt.timedelta(days=days)).strftime("%Y-%m-%d"), now.strftime("%Y-%m-%d")
    recs, status, rem = [], {"ok": True, "requests": 0, "errors": [], "days": days}, None
    jobs = [("WSAEnlilSimulations", enlil_records), ("SEP", sep_records)]
    if state.get("with_cme"):
        jobs.append(("CME", None))
    for ep, fn in jobs:
        try:
            data, sha, rem = get(ep, start, end, key)
            status["requests"] += 1
            status["n_" + ep] = len(data)
            if fn:
                recs += fn(data, sha, now)
        except urllib.error.HTTPError as e:
            status["ok"] = False
            status["errors"].append("%s: HTTP %s%s" % (ep, e.code, " (rate limit; DEMO_KEY allows only a few requests per hour)" if e.code == 429 else ""))
        except Exception as e:  # network or JSON failure must not stop the ingest run
            status["ok"] = False
            status["errors"].append("%s: %s" % (ep, e))
    status["rate_limit_remaining"] = rem
    status["records"] = len(recs)
    # keys ingest.py understands
    status["status"] = "ok" if status["ok"] and recs else ("no_new" if status["ok"] else "error")
    status["items_new"] = len(recs)
    obs = sorted(r["observed_utc"] for r in recs if r.get("observed_utc"))
    avail = sorted(r["available_utc"] for r in recs if r.get("available_utc"))
    if obs:
        status["newest_observed_utc"] = obs[-1]
    if avail:
        status["newest_available_utc"] = avail[-1]
    status["note"] = ("%d WSA-ENLIL Mars arrival record(s), %d SEP record(s), last %d days. %s" % (
        sum(r["hazard"]["kind"] == "cme" for r in recs), sum(r["hazard"]["kind"] == "sep" for r in recs), days,
        "; ".join(status["errors"]) if status["errors"] else "DONKI states no uncertainty for Mars arrival times."))
    state["last_poll_utc"] = iso(now)
    return recs, state, status


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--with-cme", action="store_true", help="also query /CME (counts only)")
    a = ap.parse_args()
    if a.days > MAX_DAYS:
        print("DONKI allows at most %d days per request; using %d" % (MAX_DAYS, MAX_DAYS))
    recs, _, st = poll({"days": a.days, "with_cme": a.with_cme})
    print("status:", json.dumps(st))
    mars = [r for r in recs if r["hazard"]["kind"] == "cme"]
    sep = [r for r in recs if r["hazard"]["kind"] == "sep"]
    print("WSA-ENLIL runs listing Mars: %d CME(s) -> %d record(s) [modelled]" % (len(mars), len(mars)))
    for r in sorted(mars, key=lambda r: r["hazard"]["start_utc"]):
        print("  %s  Mars arrival %s  sol %s  %s" % (r["id"], r["hazard"]["start_utc"], r["sol"], "glancing" if "glancing" in r["hazard"]["note"] else ""))
    print("SEP events: %d record(s) [%s]" % (len(sep), ", ".join(sorted({r["label"] for r in sep})) or "none"))
    for r in sorted(sep, key=lambda r: r["hazard"]["start_utc"]):
        print("  %s  onset %s  %s" % (r["id"], r["hazard"]["start_utc"], r["label"]))
    print("No uncertainty is published by DONKI for the Mars arrival time; see data/processed/hazards/cme_skill.json for published errors.")
    return 0 if st["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
