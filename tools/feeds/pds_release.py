"""PDS release check for the archive data the twin is built from (MSL RAD, REMS, Navcam).

Where it looks (all public, no key; directory listings and one HTML page):
  RAD RDR   https://pds-ppi.igpp.ucla.edu/data/MSL-M-RAD-3-RDR-V1.0/DATA/           (PDS Planetary Plasma Interactions node)
  REMS RDR  https://atmos.nmsu.edu/PDS/data/mslrem_1001/DATA/                         (PDS Atmospheres node)
  Navcam    https://planetarydata.jpl.nasa.gov/img/data/msl/MSLNAV_0XXX/DATA/ and MSLNAV_1XXX (PDS Imaging node)
  Release log + schedule  https://pds-geosciences.wustl.edu/missions/msl/index.htm   (PDS Geosciences node, "MSL Release N")
It compares the newest released sol with the newest sol in the twin (demo/twin/data.json, data/raw/.../navcam_xyz).
Records are emitted only if a release brings sols inside the twin's campaign window (sol 4500-4799) that are
newer than the twin's data. The archive is ahead of the twin on later sols only, so normally none.
"""
import json, os, re, statistics
from datetime import datetime, timedelta, timezone

from _common import ROOT, TWIN_DIR, http_get, iso, now, save_download

SOURCE = {
    "id": "pds_release",
    "name": "PDS release check",
    "mission": "MSL Curiosity",
    "instrument": "RAD, REMS, Navcam XYZ (archive volumes)",
    "kind": "archive",
    "typical_latency": "about 4 months after the last sol of a release; three releases a year (March, August, December) per the PDS Geosciences MSL page",
}

RAD_URL = "https://pds-ppi.igpp.ucla.edu/data/MSL-M-RAD-3-RDR-V1.0/DATA/"
REMS_URL = "https://atmos.nmsu.edu/PDS/data/mslrem_1001/DATA/"
NAV_URLS = ["https://planetarydata.jpl.nasa.gov/img/data/msl/MSLNAV_0XXX/DATA/",
            "https://planetarydata.jpl.nasa.gov/img/data/msl/MSLNAV_1XXX/DATA/"]
GEO_URL = "https://pds-geosciences.wustl.edu/missions/msl/index.htm"
CREDIT = "NASA Planetary Data System"
CAMPAIGN = (4500, 4799)
SOL_S = 88775.244   # mean Martian solar day in seconds


def _twin():
    d = json.load(open(os.path.join(TWIN_DIR, "data.json"), encoding="utf-8"))
    nav = 0
    nd = os.path.join(ROOT, "data", "raw", "curiosity", "navcam_xyz")
    if os.path.isdir(nd):
        nav = max([int(n[3:]) for n in os.listdir(nd) if re.fullmatch(r"SOL\d{5}", n)] or [0])
    w = d["weather"][-1]
    return {"rad": max(r["sol"] for r in d["rad"]), "weather": w["sol"], "photos": max(p["sol"] for p in d["photos"]),
            "navcam_xyz": nav, "anchor": (w["sol"], datetime.strptime(w["date"], "%Y-%m-%d").replace(tzinfo=timezone.utc))}


def _sol_date(sol, anchor):
    s0, d0 = anchor
    return d0 + timedelta(seconds=(sol - s0) * SOL_S)


def _volumes(html):
    """[(first_sol, last_sol, 'YYYY-MM-DD HH:MM')] from an Apache-style listing of SOL_xxxxx_yyyyy/ folders."""
    out = []
    for m in re.finditer(r'SOL_(\d{5})_(\d{5})/</a>.{0,80}?(\d{4}-\d\d-\d\d \d\d:\d\d)', html, re.S):
        out.append((int(m[1]), int(m[2]), m[3]))
    return sorted(out)


def _nav_latest(html):
    sols = [int(s) for s in re.findall(r'href="SOL(\d{5})/"', html)]
    return max(sols) if sols else None


def _schedule(html):
    txt = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " | ", html.replace("&nbsp;", " ")))
    rows = []
    for m in re.finditer(r"\|\s*(\d{2})\s*\|[\s|]*(\d{4})\s*-\s*(\d{4})\s*\|[\s|]*([A-Z][a-z]{2,8}\.?\s+\d{1,2},\s+\d{4})", txt):
        rows.append((int(m[1]), int(m[2]), int(m[3]), m[4].replace(".", "")))
    done = []
    for m in re.finditer(r"([A-Z][a-z]+ \d{1,2}, \d{4})\.\s*(?:\|[\s|]*)?MSL Release (\d+) includes new raw and derived data from sols\s*(\d{4})-(\d{4})", txt):
        done.append((int(m[2]), int(m[3]), int(m[4]), m[1]))
    return sorted(set(rows)), sorted(set(done))


def _pdate(s):
    for f in ("%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(s, f).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return None


def poll(state):
    state = dict(state or {})
    tw = _twin()
    pages = {}
    for key, url in (("rad", RAD_URL), ("rems", REMS_URL), ("nav0", NAV_URLS[0]), ("nav1", NAV_URLS[1]), ("geo", GEO_URL)):
        body = http_get(url, timeout=90).content
        pages[key] = body.decode("utf-8", "replace")
        if key in ("rad", "rems", "geo"):          # navcam listings are ~1 MB each: parsed, not stored
            save_download(SOURCE["id"], f"{key}_listing.html", body, url, CREDIT)

    rad_v, rems_v = _volumes(pages["rad"]), _volumes(pages["rems"])
    nav0, nav1 = _nav_latest(pages["nav0"]), _nav_latest(pages["nav1"])
    sched, done = _schedule(pages["geo"])
    rad_last = rad_v[-1][1] if rad_v else None
    rems_last = rems_v[-1][1] if rems_v else None

    # Lag evidence: PDS Geosciences release log (release date vs date of the last sol in that release)
    lags = []
    for n, a, b, ds in done[-6:]:
        d = _pdate(ds)
        if d:
            lags.append((n, (d - _sol_date(b, tw["anchor"])).days))
    med = statistics.median([l for _, l in lags]) if lags else None
    nxt = next((r for r in sched if _pdate(r[3]) and _pdate(r[3]) > now()), None)
    latest_rel = done[-1] if done else None

    newest_pub = max(x for x in (rad_last, rems_last, nav0, nav1) if x)
    mtime = rad_v[-1][2] if rad_v else None
    status = {
        "newest_observed_utc": iso(_sol_date(newest_pub, tw["anchor"])),
        "newest_available_utc": (mtime.replace(" ", "T") + ":00Z") if mtime else None,
        "items_new": 0,
    }
    prev = state.get("newest_pub_sol")
    new_rel = bool(prev) and newest_pub > prev
    inside_new = tw["rad"] < CAMPAIGN[1] and newest_pub > tw["rad"]
    note = f"Archive newest sol: RAD {rad_last}, REMS {rems_last}, Navcam {nav0}/{nav1}"
    if latest_rel:
        note += f" (MSL Release {latest_rel[0]}, sols {latest_rel[1]}-{latest_rel[2]}, {latest_rel[3]})"
    note += (f". Twin has RAD to sol {tw['rad']}, REMS weather to {tw['weather']}, "
             f"Navcam XYZ to {tw['navcam_xyz']}, photos to {tw['photos']}. ")
    if lags:
        note += ("Last sol of a release to public release (PDS Geosciences log; sol dates from the twin's REMS dates, +-1 day): median %d days (%s). "
                 % (med, ", ".join(f"R{n}={l}" for n, l in lags)))
    if nxt:
        note += f"Next scheduled: release {nxt[0]}, sols {nxt[1]}-{nxt[2]}, {nxt[3]}. "
    if new_rel:
        note += "New release since last check. "
    if not inside_new:
        note += "No records: sols newer than the twin's data are outside the 2025 campaign it covers."
    status.update({"status": "ok", "note": note.strip(),
                   "extra": {"rad_last_sol": rad_last, "rems_last_sol": rems_last, "navcam_last_sol": [nav0, nav1],
                             "twin_sols": {k: tw[k] for k in ("rad", "weather", "photos", "navcam_xyz")},
                             "lag_days_median": med, "lag_days_by_release": lags,
                             "next_release": list(nxt) if nxt else None}})
    state["newest_pub_sol"] = newest_pub
    return [], state, status
