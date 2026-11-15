"""Download a low-resolution global Mars colour map for the intro globe (demo/twin/intro.html).

Source: JPL Mars Trek WMTS, layer Mars_Viking_MDIM21_ClrMosaic_global_232m (Viking MDIM 2.1 colour mosaic, NASA/JPL/USGS).
Level 2 = 8 x 4 tiles of 256 px = 2048 x 1024 equirectangular, west edge at -180 deg. Tiles 1 s apart, generic User-Agent.
Writes data/marstrek_globe/ (tiles + provenance.json) and demo/twin/intro/mars_globe.jpg (east-positive, -180..180).
    python tools/fetch_marstrek_globe.py
"""
import hashlib, io, json, os, time, urllib.request
from datetime import datetime, timezone
from PIL import Image
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LAYER = "Mars_Viking_MDIM21_ClrMosaic_global_232m"; Z = 2; NC, NR = 8, 4
URL = "https://trek.nasa.gov/tiles/Mars/EQ/%s/1.0.0/default/default028mm/%d/%d/%d.jpg"
OUT = os.path.join(ROOT, "data/marstrek_globe"); os.makedirs(OUT, exist_ok=True)
prov = {"layer": LAYER, "level": Z, "service": "JPL Mars Trek WMTS (https://trek.nasa.gov)", "credit": "NASA/JPL/USGS (Viking MDIM 2.1 colour mosaic) via JPL Mars Trek",
        "fetched_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "tiles": []}
img = Image.new("RGB", (NC * 256, NR * 256))
for r in range(NR):
    for c in range(NC):
        fn = os.path.join(OUT, f"{Z}_{r}_{c}.jpg"); url = URL % (LAYER, Z, r, c)
        if not os.path.exists(fn):
            data = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "marswalk-demo/1.0"}), timeout=60).read()
            open(fn, "wb").write(data); time.sleep(1)
        data = open(fn, "rb").read(); prov["tiles"].append({"url": url, "file": os.path.basename(fn), "sha256": hashlib.sha256(data).hexdigest()})
        img.paste(Image.open(io.BytesIO(data)).convert("RGB"), (c * 256, r * 256))
json.dump(prov, open(os.path.join(OUT, "provenance.json"), "w"), indent=1)
os.makedirs(os.path.join(ROOT, "demo/twin/intro"), exist_ok=True)
img.save(os.path.join(ROOT, "demo/twin/intro/mars_globe.jpg"), quality=88); print("ok", img.size)
