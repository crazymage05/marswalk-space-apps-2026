"""Rasterise the USGS Geologic Map of Mars (Tanaka et al. 2014, SIM 3292) onto the twin grid -> demo/twin/geology.json.

usage: python tools/export_geology_twin.py   (needs data/usgs_geology from tools/fetch_usgs_geology.py)
Grid mapping is the same proportional one as the other ROI rasters: cell (j,i) centre -> lon = west + (i+.5)/W * (east-west),
lat = north - (j+.5)/H * (north-south), with the ROI bounds in data.json "roi". Polygons are filled even-odd (holes handled).
Writes the unit code per cell (uint8 index into legend, base64), the legend (names, groups, epoch, colours and descriptions from the map's own
attribute table and renderer), the map citation and scale, and simplified outlines of the 0.8 x 0.8 degree window for a context inset.
"""
import base64, json, os, re, zlib
import numpy as np
from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "data", "usgs_geology"); OUT = os.path.join(ROOT, "demo", "twin", "geology.json")
# epoch from the unit code prefix (N = Noachian, H = Hesperian, A = Amazonian; combined prefixes span epochs). Absolute ages are the
# chronology given with the map (Hartmann/Neukum-Michael crater-model boundaries) and are approximate and model dependent.
EPOCH = {"N": "Noachian (older than about 3.7 Ga)", "H": "Hesperian (about 3.7 to 3.0 Ga)", "A": "Amazonian (younger than about 3.0 Ga)"}
AGE = {"AHi": "Hesperian to Amazonian (mapped as spanning both epochs)", "Htu": "Hesperian"}


def fix(s):
    if not s: return ""
    try: s = s.encode("cp1252").decode("utf-8")      # the service returns UTF-8 bytes read as cp1252 (e.g. degree sign)
    except Exception: pass
    s = re.sub(r"\s*\((lat [^)]*)\)?\s*$", "", s.replace("\r\n", " ")).strip()    # drop the type-locality coordinates elsewhere on Mars
    return s.rstrip(".") + "."


def dp(pts, eps):
    pts = np.asarray(pts)
    if len(pts) < 4: return pts
    a, b = pts[0], pts[-1]; ab = b - a; n = np.hypot(*ab)
    dist = np.abs(ab[0] * (pts[:, 1] - a[1]) - ab[1] * (pts[:, 0] - a[0])) / n if n else np.hypot(*(pts - a).T)
    i = int(dist.argmax())
    if dist[i] > eps: return np.vstack([dp(pts[:i + 1], eps)[:-1], dp(pts[i:], eps)])
    return np.vstack([a, b])


def main():
    D = json.load(open(os.path.join(ROOT, "demo", "twin", "data.json"))); G = D["grid"]; W, H = G["w"], G["h"]; R = D["roi"]
    poly = json.load(open(os.path.join(SRC, "polygons_window.json"), encoding="utf-8"))
    leg = {f["attributes"]["Unit"]: f["attributes"] for f in json.load(open(os.path.join(SRC, "legend_units.json"), encoding="utf-8"))["features"]}
    meta = json.load(open(os.path.join(SRC, "layer_metadata.json"), encoding="utf-8"))
    col = {u["value"]: u["symbol"]["color"][:3] for u in meta["drawingInfo"]["renderer"]["uniqueValueInfos"]}
    prov = json.load(open(os.path.join(SRC, "provenance.json")))
    units = sorted(leg); idx = {u: k for k, u in enumerate(units)}
    # even-odd fill per feature in cell coordinates
    lab = np.full((H, W), 255, np.uint8)
    def to_px(ring): return [((x - R["westernlon"]) / (R["easternlon"] - R["westernlon"]) * W, (R["maxlat"] - y) / (R["maxlat"] - R["minlat"]) * H) for x, y in ring]
    for f in poly["features"]:
        m = Image.new("1", (W, H), 0)
        for ring in f["geometry"]["rings"]:
            r = Image.new("1", (W, H), 0); ImageDraw.Draw(r).polygon(to_px(ring), fill=1)
            m = Image.fromarray(np.asarray(m) ^ np.asarray(r))
        lab[np.asarray(m)] = idx[f["attributes"]["Unit"]]
    assert (lab != 255).all(), "unassigned cells"
    cnt = {u: int((lab == idx[u]).sum()) for u in units}; print("cells per unit:", cnt, "of", W * H)
    legend = []
    for u in units:
        a = leg[u]
        legend.append({"code": u, "name": a["UnitDesc"], "group": a["UnitGroup"], "age": AGE.get(u, EPOCH.get(u[0], "")), "color": col[u],
                       "primary": fix(a["PrimaryCharacteristics"]), "additional": fix(a["AdditionalCharacteristics"]), "interpretation": fix(a["Interpretation"]),
                       "cells": cnt[u], "pct": round(100 * cnt[u] / (W * H), 1)})
    ctx = []
    for f in poly["features"]:
        rings = []
        for ring in f["geometry"]["rings"]:
            s = dp(np.round(np.array(ring), 5), 0.0004)     # ~25 m tolerance, far below the map's own accuracy
            rings.append([[round(float(x), 4), round(float(y), 4)] for x, y in s])
        ctx.append({"code": f["attributes"]["Unit"], "rings": rings})
    out = {"map": {"title": "Geologic Map of Mars", "citation": "Tanaka, K.L., Skinner, J.A., Jr., Dohm, J.M., Irwin, R.P., III, Kolb, E.J., Fortezzo, C.M., Platz, T., Michael, G.G., and Hare, T.M., 2014, Geologic map of Mars: U.S. Geological Survey Scientific Investigations Map 3292, scale 1:20,000,000.",
                    "sim": "SIM 3292", "scale": "1:20,000,000", "scale_denominator": 20000000,
                    "scale_note": "At 1:20,000,000 one millimetre is 20 km and boundaries are positioned to a few kilometres at best; the twin is 2.4 x 3.0 km, so what it shows is which unit the map assigns to this spot, not a boundary location.",
                    "no_larger_scale": "No larger-scale USGS geologic map of Gale crater exists in the USGS publications warehouse or the Planetary Geologic Mapping hub (Mars SIMs at 1:1M or larger cover Jezero, Shalbatana, Athabasca, Nepenthes, Ladon, Candor, Olympus Mons).",
                    "url": "https://pubs.usgs.gov/sim/3292/", "hub": "https://astrogeology-usgs.hub.arcgis.com/pages/interactive-maps-mars",
                    "service": "https://services.arcgis.com/v01gqwM5QqNysAAi/arcgis/rest/services/Tanaka_et_al_2014_Mars_Global_Map_Features/FeatureServer/3",
                    "credit": "USGS Astrogeology Science Center / USGS-NASA Planetary Geologic Mapping Program", "fetched_utc": prov["fetched_utc"]},
           "w": W, "h": H, "units": units, "data": base64.b64encode(zlib.compress(lab.tobytes(), 9)).decode(), "encoding": "zlib deflate, uint8 unit index per cell, row-major from the north-west cell", "legend": legend,
           "context": {"window": [WIN for WIN in (prov["window_deg"]["xmin"], prov["window_deg"]["xmax"], prov["window_deg"]["ymin"], prov["window_deg"]["ymax"])], "polygons": ctx}}
    json.dump(out, open(OUT, "w"), separators=(",", ":")); print("wrote", OUT, os.path.getsize(OUT), "bytes")


if __name__ == "__main__":
    main()
