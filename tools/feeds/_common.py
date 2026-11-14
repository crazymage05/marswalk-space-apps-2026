"""Shared helpers for the feed source modules (optional: a module may ignore this file).

Files starting with an underscore are never loaded as sources by tools/ingest.py.
Everything downloaded goes under data/feeds/<source_id>/<UTC date>/ with a provenance.json
next to it. Nothing here ever writes under data/raw.
"""
import hashlib, json, math, os, time
from datetime import datetime, timezone

import requests

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
FEEDS_DIR = os.path.join(ROOT, "data", "feeds")
TWIN_DIR = os.path.join(ROOT, "demo", "twin")
UA = "marswalk-demo/1.0"
ISO = "%Y-%m-%dT%H:%M:%SZ"


def now():
    return datetime.now(timezone.utc)


def iso(dt=None):
    return (dt or now()).strftime(ISO)


def parse_iso(s):
    """'2026-11-13T05:06:11.000Z' or '2026-11-13T05:06:11Z' -> aware datetime (None if empty)."""
    if not s:
        return None
    s = s.replace("Z", "+00:00")
    return datetime.fromisoformat(s).astimezone(timezone.utc)


def http_get(url, params=None, timeout=60, tries=3, stream=False):
    """GET with generic User-Agent, timeout and exponential backoff (1 s, 2 s). Raises on final failure."""
    last = None
    for i in range(tries):
        try:
            r = requests.get(url, params=params, timeout=timeout, headers={"User-Agent": UA}, stream=stream)
            if r.status_code == 200:
                return r
            last = RuntimeError(f"HTTP {r.status_code} for {r.url}")
            if r.status_code in (400, 401, 403, 404):
                break
        except requests.RequestException as e:
            last = e
        time.sleep(2 ** i)
    raise last


def save_download(source_id, name, content, url, credit, licence="NASA / PDS public data, no restrictions on use", extra=None):
    """Write bytes to data/feeds/<source_id>/<UTC date>/<name> and append to that day's provenance.json.
    Returns (path, sha256)."""
    day = now().strftime("%Y-%m-%d")
    folder = os.path.join(FEEDS_DIR, source_id, day)
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, name)
    with open(path, "wb") as fh:
        fh.write(content)
    sha = hashlib.sha256(content).hexdigest()
    pf = os.path.join(folder, "provenance.json")
    prov = {"files": []}
    if os.path.exists(pf):
        try:
            prov = json.load(open(pf, encoding="utf-8"))
        except Exception:
            pass
    prov["files"] = [f for f in prov.get("files", []) if f.get("file") != name]
    entry = {"file": name, "url": url, "sha256": sha, "bytes": len(content), "fetched_utc": iso(),
             "licence": licence, "credit": credit}
    if extra:
        entry.update(extra)
    prov["files"].append(entry)
    json.dump(prov, open(pf, "w", encoding="utf-8"), indent=1)
    return path, sha


# ---- twin georeference (same maths as build_twin_demo.py: DTM label projection + coregistration shift) ----
RAD_M, CLON, SCALE, LOFF, SOFF = 3396190.0, 137.41, 1.0117467945795, -273961.50000001, 3319.5000000001
STEP = 4


def _to_px(lon, lat):
    x = RAD_M * math.radians(lon - CLON)
    y = RAD_M * math.radians(lat)
    return x / SCALE + SOFF, LOFF - y / SCALE


class TwinGeo:
    """lon/lat -> twin grid x,y; inside() tests the ROI box the twin was built on."""

    def __init__(self):
        self.roi = json.load(open(os.path.join(ROOT, "data", "metadata", "roi.json"), encoding="utf-8"))["bbox"]
        self.co = json.load(open(os.path.join(ROOT, "data", "processed", "roi", "coregistration.json"),
                                 encoding="utf-8"))["waypoints_to_dtmA"]
        self.s0, self.l0 = map(int, _to_px(self.roi["westernlon"], self.roi["maxlat"]))
        d = json.load(open(os.path.join(TWIN_DIR, "data.json"), encoding="utf-8"))
        self.W, self.H = d["grid"]["w"], d["grid"]["h"]

    def inside(self, lon, lat):
        r = self.roi
        return r["westernlon"] <= lon <= r["easternlon"] and r["minlat"] <= lat <= r["maxlat"]

    def xy(self, lon, lat):
        s, l = _to_px(lon, lat)
        return round((s + self.co["d_col"] - self.s0) / STEP, 2), round((l + self.co["d_row"] - self.l0) / STEP, 2)
