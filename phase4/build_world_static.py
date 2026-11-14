#!/usr/bin/env python3
"""Build data/processed/roi/world/world_static_4m.npz + .json (see docs/world_design.md).
Light: block reductions in numpy. Horizon layers are merged in if horizon_32_4m.npz exists.
    python phase4/build_world_static.py"""
import json, os, sys, base64, warnings
import numpy as np, rasterio
from scipy import ndimage as ndi
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); os.chdir(ROOT); sys.path.insert(0, ROOT)
import marswalk_grid as g
warnings.filterwarnings("ignore")
P = g.OUT; K = 4; H, W = g.HEIGHT // K, g.WIDTH // K; CELL = g.RES * K
rd = lambda n: rasterio.open(os.path.join(P, n + ".tif")).read(1).astype(np.float64)
blk = lambda a: a[:H * K, :W * K].reshape(H, K, W, K)
nav = np.load(os.path.join(P, "nav_grid_4m.npz"))
L, META = {}, {}


def add(name, arr, units, source, native, cls, policy):
    L[name] = arr.astype(np.float32) if (arr.dtype != bool and arr.dtype.kind != "i") else arr
    META[name] = dict(units=units, source=source, native_resolution=native, cls=cls, missing_policy=policy)


def to_cells(a):   # aligned coarse raster (same origin) -> 4 m cells, nearest
    ri = np.minimum(((np.arange(H) + .5) / H * a.shape[0]).astype(int), a.shape[0] - 1)
    ci = np.minimum(((np.arange(W) + .5) / W * a.shape[1]).astype(int), a.shape[1] - 1)
    return a[np.ix_(ri, ci)]


SRC = {"elevation_m": "HiRISE DTM DTEEC_009149_1750_009294_1750_U01, mean of 4x4 1 m pixels",
       "slope_max_deg": "DTM slope (Horn), max of 4x4 1 m pixels", "slope_mean_deg": "DTM slope (Horn), mean of 4x4",
       "rough_max_m": "DTM 5 m plane-fit residual std, max of 4x4", "valid_frac": "share of valid 1 m terrain+roughness pixels"}
for n, u in (("elevation_m", "m"), ("slope_max_deg", "deg"), ("slope_mean_deg", "deg"), ("rough_max_m", "m"), ("valid_frac", "0-1")):
    add(n, nav[n], u, SRC[n], "1.01 m -> 4.05 m", "measured" if n == "elevation_m" else "derived",
        "NaN where DTM invalid; navigation treats NaN as hard-blocked (unknown)")
# aspect and plane slope from the mean gradient vector of the cell (avoids averaging angles)
sl, asp = np.radians(rd("slope_deg")), np.radians(rd("aspect_deg")); t = np.tan(sl)
ge = np.nanmean(blk(-t * np.sin(asp)), axis=(1, 3)); gn = np.nanmean(blk(-t * np.cos(asp)), axis=(1, 3))   # uphill gradient (E, N)
add("aspect_deg", np.degrees(np.arctan2(-ge, -gn)) % 360, "deg clockwise from north (downslope azimuth)", "DTM aspect, vector mean of 4x4 gradient", "1.01 m -> 4.05 m", "derived", "NaN where slope NaN")
add("slope_plane_deg", np.degrees(np.arctan(np.hypot(ge, gn))), "deg", "slope of the cell's mean gradient (insolation geometry)", "1.01 m -> 4.05 m", "derived", "NaN where slope NaN")
add("tri_max_m", np.nanmax(blk(rd("tri")), axis=(1, 3)), "m", "Riley terrain ruggedness index from DTM, max of 4x4", "1.01 m -> 4.05 m", "derived", "NaN where DTM invalid")
rb = blk(rd("rock_density")); rf = np.nanmean(rb, axis=(1, 3)); rf[np.isfinite(rb).mean(axis=(1, 3)) < 0.5] = np.nan
add("rock_frac", rf, "0-1 fractional rock area (shadow-detected rocks >~1 m, 10 m window)", "HiRISE 25 cm ortho shadow detection (rocks_detect.py), mean of 4x4", "0.25 m detection, 10 m window", "derived",
    "NaN outside the walk corridor (no detection run); costs treat NaN as unknown")
mj = json.load(open("demo/twin/material_4m.json"))
mat = np.frombuffer(base64.b64decode(mj["data"]), np.uint8).reshape(mj["height"], mj["width"])
r0, c0 = mj["origin_row_1m"], mj["origin_col_1m"]; gt = np.full((H, W), -1, np.int8)
rr = (r0 + K * np.arange(mj["height"]) + K // 2) // K; cc = (c0 + K * np.arange(mj["width"]) + K // 2) // K
assert len(set(rr)) == len(rr) and len(set(cc)) == len(cc)
ok_r, ok_c = (rr >= 0) & (rr < H), (cc >= 0) & (cc < W)
gt[np.ix_(rr[ok_r], cc[ok_c])] = mat[np.ix_(ok_r, ok_c)].astype(np.int8)
add("ground_type", gt, "code: 0 bedrock, 1 sand, 2 pebbly, -1 unknown", "rule from slope, roughness, ortho texture (demo/twin/material_4m.json, corridor 252x325 cells)",
    "4 m cells; origin 1 m px col 336 row 577", "derived", "-1 outside the corridor; the 0.25-cell row offset is resolved by cell centre (each material cell maps to exactly one nav cell)")
add("loose", nav["loose"], "0-1", "THEMIS dawn brightness temperature, median of 12 images (-z/2, clipped)", "~101 m -> 4.05 m (nearest)", "derived, coarse", "NaN where THEMIS missing")
add("dawn_warmth_z", nav["dawn_warmth_z"], "z-score", "THEMIS band 9 dawn brightness temperature, ROI z-score", "~101 m -> 4.05 m (nearest)", "derived, coarse", "NaN where THEMIS missing")
for n in ("hydration", "sulfate", "science"):
    src = {"hydration": "CRISM MTRDR BD1900_2 (median of 3 products)", "sulfate": "CRISM MTRDR SINDEX2", "science": "z(BD1900_2)+z(SINDEX2) over the ROI"}[n]
    add(n, nav[n], "CRISM index (unitless)" if n != "science" else "z-score sum", src, "~18 m -> 4.05 m (nearest); ~18 m georeference uncertainty",
        "measured" if n != "science" else "derived", "NaN where CRISM missing")
cr = rasterio.open(os.path.join(P, "crism_mineral_params.tif")); names = list(cr.descriptions)
add("ferric", to_cells(cr.read(names.index("BD530_2") + 1).astype(np.float64)), "CRISM index (unitless)", "CRISM MTRDR BD530_2 (ferric absorption)",
    "~18 m -> 4.05 m (nearest); ~18 m georeference uncertainty", "measured", "NaN where CRISM missing")
dif = rd("elevation_diff_aligned_m"); dif = dif - np.nanmedian(dif)          # remove the constant -7.35 m datum offset between the two DTMs
add("dtm_uncert_m", np.nanmean(np.abs(blk(dif)), axis=(1, 3)), "m",
    "|DTM A - DTM B aligned - median offset (-7.35 m)|, mean of 4x4; includes real change + residual co-registration error", "1.01 m -> 4.05 m", "derived", "NaN where second DTM absent")
# distance to rover track
gj = json.load(open(os.path.join(P, "vectors", "traverse_lines_registered.geojson"))); R = g.R_MARS
mask = np.zeros((H, W), bool)
for f in gj["features"]:
    if not f["properties"]["in_roi"]: continue
    geo = f["geometry"]; lines = geo["coordinates"] if geo["type"] == "MultiLineString" else [geo["coordinates"]]
    for ln in lines:
        a = np.array(ln)[:, :2]; x = np.radians(a[:, 0] - 137.41) * R; y = np.radians(a[:, 1]) * R
        px, py = (x - g.X0) / g.RES, (g.Y0 - y) / g.RES
        for i in range(len(px) - 1):
            n = int(max(abs(px[i + 1] - px[i]), abs(py[i + 1] - py[i]))) // 2 + 2
            u = np.linspace(0, 1, n); cx = ((px[i] + u * (px[i + 1] - px[i])) // K).astype(int); cy = ((py[i] + u * (py[i + 1] - py[i])) // K).astype(int)
            m = (cx >= 0) & (cx < W) & (cy >= 0) & (cy < H); mask[cy[m], cx[m]] = True
add("dist_to_rover_track_m", ndi.distance_transform_edt(~mask) * CELL, "m", "Curiosity registered traverse (all sols, segments in the ROI)", "vertex-level -> 4.05 m",
    "derived", "always defined; registration good to ~25 m north-south (phase 2)")
mi = json.load(open("demo/twin/meshes/meshes_index.json")); yy, xx = np.mgrid[0:H, 0:W]; sc = np.zeros((H, W), bool)
for m in mi: sc |= np.hypot((xx + .5) * K - m["col"], (yy + .5) * K - m["row"]) * g.RES <= 25.0
add("rover_scan", sc, "bool", "Curiosity Navcam 3D scan anchors (meshes_index.json), 25 m radius", "per scan", "measured", "false elsewhere (%d scans exist)" % len(mi))

hz = os.path.join(P, "world", "horizon_32_4m.npz")
if os.path.exists(hz):
    z = np.load(hz)
    add("horizon_deg", z["horizon_deg"].astype(np.float16), "deg elevation, 32 azimuths 0,11.25..348.75 clockwise from north (axis 0)", "horizon ray-march on the DTM (horizon_32_4m.npz)", "4.05 m", "derived", "see horizon_32_4m")
    add("sky_view", z["sky_view"], "0-1 cosine-weighted", "horizon_32_4m.npz", "4.05 m", "derived", "")
    add("sky_solid", z["sky_solid"], "0-1 solid-angle fraction", "horizon_32_4m.npz", "4.05 m", "derived", "")
    L["horizon_deg"] = L["horizon_deg"].astype(np.float16)

np.savez_compressed(os.path.join(P, "world", "world_static_4m.npz"), **L)
for k, v in L.items():
    fin = np.isfinite(v.astype(float)) if v.dtype.kind in "fc" else np.ones(v.shape, bool)
    if k == "ground_type": fin = v >= 0
    META[k].update(coverage_pct=round(float(fin.mean() * 100), 2), dtype=str(v.dtype), shape=list(v.shape))
    print(f"{k:22} {str(v.dtype):8} cov {META[k]['coverage_pct']:6.2f}%")
json.dump({"grid": {"width": W, "height": H, "cell_m": CELL, "index": "cell = row*585+col, row 0 north"}, "layers": META},
          open(os.path.join(P, "world", "world_static_4m.json"), "w"), indent=1)
