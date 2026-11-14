"""Download the public PDS rock-chemistry data for the boxwork campaign (sols 4500-4799) into data/chem_b/.

Sources (all PDS Geosciences Node, no key; directory listings were checked by hand on 2026-11-13):
  ChemCam MOC  https://pds-geosciences.wustl.edu/msl/msl-m-chemcam-libs-4_5-rdr-v1/mslccm_1xxx/data/moc/
      moc_4489_4612.csv, moc_4613_4709.csv, moc_4710_4843.csv  (major-oxide composition per laser shot, with RMSEP)
  ChemCam obs  .../mslccm_1xxx/document/msl_ccam_obs.csv  (sol, target name, RMC site+drive, distance per observation)
  APXS RDR     https://pds-geosciences.wustl.edu/msl/msl-m-apxs-4_5-rdr-v1/mslapx_1xxx/data/solNNNNN/
      apb_*rwp*_p1.csv/.lbl  (oxide abundance + precision; the label holds sol, site, drive)
  Release page https://pds-geosciences.wustl.edu/missions/msl/index.htm  (which sols each MSL release covers)
  Waypoints    https://mars.nasa.gov/mmgis-maps/MSL/Layers/json/MSL_waypoints.json  (lon/lat per site+drive)
Everything is written under data/chem_b/ (never data/raw) with provenance.json. Re-running skips files already there.
"""
import hashlib, json, os, re, sys, time
from datetime import datetime, timezone

import requests

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
OUT = os.path.join(ROOT, "data", "chem_b")
UA = "marswalk-demo/1.0"
DELAY = 0.6
SOLS = (4500, 4799)
CCAM = "https://pds-geosciences.wustl.edu/msl/msl-m-chemcam-libs-4_5-rdr-v1/mslccm_1xxx/"
APXS = "https://pds-geosciences.wustl.edu/msl/msl-m-apxs-4_5-rdr-v1/mslapx_1xxx/"
RELEASE = "https://pds-geosciences.wustl.edu/missions/msl/index.htm"
WAYPOINTS = "https://mars.nasa.gov/mmgis-maps/MSL/Layers/json/MSL_waypoints.json"
MOC = ["moc_4489_4612", "moc_4613_4709", "moc_4710_4843"]
CREDIT = "NASA / PDS Geosciences Node (ChemCam: LANL/IRAP; APXS: Univ. of Guelph; waypoints: NASA/JPL MMGIS)"

_last = [0.0]
prov = {"files": []}


def get(url, tries=3):
    wait = DELAY - (time.time() - _last[0])
    if wait > 0:
        time.sleep(wait)
    err = None
    for i in range(tries):
        try:
            r = requests.get(url, headers={"User-Agent": UA}, timeout=120)
            _last[0] = time.time()
            if r.status_code == 200:
                return r.content
            err = RuntimeError("HTTP %d for %s" % (r.status_code, url))
            if r.status_code in (400, 401, 403, 404):
                break
        except requests.RequestException as e:
            err = e
        time.sleep(2 ** i)
    raise err


def save(rel, url):
    path = os.path.join(OUT, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path):
        body = open(path, "rb").read()
        fresh = False
    else:
        body = get(url)
        open(path, "wb").write(body)
        fresh = True
    prov["files"].append({"file": rel.replace("\\", "/"), "url": url, "sha256": hashlib.sha256(body).hexdigest(),
                          "bytes": len(body), "fetched_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                          if fresh else "earlier run", "credit": CREDIT})
    return body


def main():
    os.makedirs(OUT, exist_ok=True)
    rel = save("release_page.htm", RELEASE).decode("utf-8", "replace")
    txt = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", rel.replace("&nbsp;", " ")))
    m = re.search(r"MSL Release (\d+) includes new raw and derived data from sols (\d+)-(\d+)", txt)
    cov = {"release": int(m[1]), "first_sol": int(m[2]), "last_sol": int(m[3])} if m else None
    print("newest PDS release:", cov)
    for stem in MOC:
        for ext in ("csv", "lbl"):
            save("chemcam/%s.%s" % (stem, ext), "%sdata/moc/%s.%s" % (CCAM, stem, ext))
    save("chemcam/msl_ccam_obs.csv", CCAM + "document/msl_ccam_obs.csv")
    save("chemcam/msl_ccam_obs.lbl", CCAM + "document/msl_ccam_obs.lbl")
    listing = get(APXS + "data/").decode("utf-8", "replace")
    sols = sorted(int(s) for s in set(re.findall(r"data/sol(\d{5})/", listing)) if SOLS[0] <= int(s) <= SOLS[1])
    print("APXS sol folders in %d-%d: %d" % (SOLS[0], SOLS[1], len(sols)))
    nfile = 0
    for s in sols:
        d = get("%sdata/sol%05d/" % (APXS, s)).decode("utf-8", "replace")
        names = sorted(set(re.findall(r'HREF="[^"]*/(apb_[^"/]*rwp[^"/]*_p1)\.csv"', d, re.I)))
        for n in names:
            for ext in ("csv", "lbl"):
                save("apxs/sol%05d/%s.%s" % (s, n, ext), "%sdata/sol%05d/%s.%s" % (APXS, s, n, ext))
                nfile += 1
    print("APXS rwp products fetched:", nfile // 2)
    save("MSL_waypoints.json", WAYPOINTS)
    prov["coverage"] = {"newest_release": cov, "requested_sols": list(SOLS)}
    json.dump(prov, open(os.path.join(OUT, "provenance.json"), "w", encoding="utf-8"), indent=1)
    print("files recorded in provenance.json:", len(prov["files"]))


if __name__ == "__main__":
    sys.exit(main())
