"""Download the JPL Mars Trek tiles that cover the twin's ROI (plus a context window) -> data/marstrek/ (+ provenance.json).

usage: python tools/fetch_marstrek.py

Mars Trek serves OGC WMTS REST tiles in an equirectangular Mars 2000 sphere grid ("default028mm", 256 px tiles, level 0 = 2x1 tiles,
top-left corner -180/90; tile size at level z = 180/2^z degrees). Endpoints used (all public, no key):
  catalogue : https://trek.nasa.gov/mars/TrekServices/ws/index/eq/searchItems?start=0&rows=300   (layer ids, bbox, descriptions)
  capabilities: https://trek.nasa.gov/tiles/Mars/EQ/<layer>/1.0.0/WMTSCapabilities.xml
  tiles     : https://trek.nasa.gov/tiles/Mars/EQ/<layer>/1.0.0/default/default028mm/<z>/<row>/<col>.<ext>
Layers: Gale_CTX_BlockAdj_dd (MRO CTX Gale mosaic), Mars_MGS_MOLA_ClrShade_merge_global_463m (MOLA colour shaded relief),
SIM3292_Global_Geology (Trek's rendering of the USGS global geologic map; the vector data itself comes from fetch_usgs_geology.py).
Only tiles inside the windows below are requested, 1 s apart, generic User-Agent. Existing files are not re-downloaded.
"""
import datetime, hashlib, json, math, os, sys, time, urllib.request, urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "marstrek")
UA = {"User-Agent": "marswalk-demo/1.0"}
ROI = dict(minlat=-4.83, maxlat=-4.78, minlon=137.37, maxlon=137.41)
# (key, layer id, ext, zoom, window lon0, lon1, lat0, lat1, role)
JOBS = [
    ("ctx_roi", "Gale_CTX_BlockAdj_dd", "png", 12, 137.34, 137.44, -4.86, -4.75, "CTX at the ROI, native max level (about 10 m/px)"),
    ("ctx_ctx", "Gale_CTX_BlockAdj_dd", "png", 11, 137.15, 137.65, -5.05, -4.55, "CTX context window about 30 km"),
    ("mola", "Mars_MGS_MOLA_ClrShade_merge_global_463m", "jpg", 7, 136.6, 138.2, -5.6, -4.0, "MOLA colour shaded relief, regional window about 95 km"),
    ("geo", "SIM3292_Global_Geology", "png", 7, 136.6, 138.2, -5.6, -4.0, "Trek rendering of SIM 3292 geologic map, regional window"),
]
BASE = "https://trek.nasa.gov/tiles/Mars/EQ/%s/1.0.0/default/default028mm/%d/%d/%d.%s"
GEO = "https://trek.nasa.gov/mars/trekarcgis/rest/services/SIM3292_Global_Geology/MapServer/WMTS/tile/1.0.0/SIM3292_Global_Geology/default/default028mm/%d/%d/%d.png"
CAT = "https://trek.nasa.gov/mars/TrekServices/ws/index/eq/searchItems?start=0&rows=300"
CAPS = "https://trek.nasa.gov/tiles/Mars/EQ/%s/1.0.0/WMTSCapabilities.xml"


def get(url):
    for k in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404: return None
            time.sleep(3)
        except Exception:
            time.sleep(3)
    raise RuntimeError("failed " + url)


def sha(b): return hashlib.sha256(b).hexdigest()


def main():
    os.makedirs(OUT, exist_ok=True)
    prov = {"credit": "NASA/JPL-Caltech Mars Trek (trek.nasa.gov/mars)", "user_agent": UA["User-Agent"], "roi": ROI,
            "fetched_utc": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"), "files": [], "layers": {}}
    # catalogue + capabilities (small, kept for the record)
    for name, url in [("catalogue_searchItems.json", CAT)] + [("caps_%s.xml" % l, CAPS % l) for l in
                      sorted({j[1] for j in JOBS if j[1] != "SIM3292_Global_Geology"})]:
        p = os.path.join(OUT, name)
        if not os.path.exists(p):
            b = get(url); open(p, "wb").write(b); time.sleep(1)
        prov["files"].append({"file": name, "url": url, "sha256": sha(open(p, "rb").read())})
    cat = json.load(open(os.path.join(OUT, "catalogue_searchItems.json"), encoding="utf-8"))["response"]["docs"]
    meta = {d.get("productLabel"): d for d in cat}
    for key, layer, ext, z, lo0, lo1, la0, la1, role in JOBS:
        t = 180.0 / 2 ** z
        c0, c1 = int((lo0 + 180) // t), int((lo1 + 180) // t); r0, r1 = int((90 - la1) // t), int((90 - la0) // t)
        d = os.path.join(OUT, key); os.makedirs(d, exist_ok=True)
        m = meta.get(layer, {})
        prov["layers"][key] = {"layer_id": layer, "title": m.get("title"), "role": role, "zoom": z, "tile_deg": t,
                               "cols": [c0, c1], "rows": [r0, r1], "catalogue_description": (m.get("description") or "")[:600]}
        n = 0
        for r in range(r0, r1 + 1):
            for c in range(c0, c1 + 1):
                url = GEO % (z, r, c) if layer.startswith("SIM3292") else BASE % (layer, z, r, c, ext)
                fn = "%d_%d_%d.%s" % (z, r, c, ext); p = os.path.join(d, fn)
                if not os.path.exists(p):
                    b = get(url); time.sleep(1)
                    if b is None: print("missing", url); continue
                    open(p, "wb").write(b)
                prov["files"].append({"file": key + "/" + fn, "url": url, "layer_id": layer, "sha256": sha(open(p, "rb").read())}); n += 1
        print(key, layer, "z%d" % z, "tiles", n, "of", (r1 - r0 + 1) * (c1 - c0 + 1))
    json.dump(prov, open(os.path.join(OUT, "provenance.json"), "w"), indent=1)
    print("wrote", os.path.join(OUT, "provenance.json"))


if __name__ == "__main__":
    main()
