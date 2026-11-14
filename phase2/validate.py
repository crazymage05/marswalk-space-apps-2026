#!/usr/bin/env python3
"""
MARSWALK Phase 2 - independent checks on everything in data/processed/roi.

Per raster: same CRS and origin as marswalk_grid, pixel size an exact factor of the base pixel,
valid fraction, value range within physical limits, and a registry entry.
Per table: row count, required columns, coordinates inside the ROI.
Cross-checks: slope recomputed from elevation, registered waypoints against the DTM, RAD dose.

    python phase2/validate.py        # exit code 1 if any check fails
"""
import csv, glob, json, os, sys
import numpy as np
import rasterio
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import marswalk_grid as g

ROI = g.OUT; fails, rows = [], []
def check(name, ok, detail):
    rows.append(("PASS" if ok else "FAIL", name, detail))
    if not ok: fails.append(name)

# physical ranges per layer name prefix: (min, max) for valid values
RANGE = {"elevation_m": (-4500, -2000), "elevation_alt": (-4500, -2000), "elevation_diff": (-200, 200), "slope_deg": (0, 90),
         "aspect_deg": (0, 360), "roughness_m": (0, 20), "tri": (0, 50), "hillshade": (0, 255), "ortho": (0, 255),
         "hirise2026_red": (0, 65535), "hirise2026_color": (0, 255), "themis": (120, 330), "mola": (-6000, -1000),
         "crism_mineral_params_count": (0, 3), "rock_density": (0, 1)}
# layers that legitimately cover only part of the ROI (rock_density: walk corridor, cols 336-1343, rows 577-1878 = 19.2%)
MIN_VALID = {"rock_density": 0.15}
reg = {os.path.splitext(os.path.basename(f))[0] for f in glob.glob(os.path.join(ROI, "registry", "*.json"))}
for f in glob.glob(os.path.join(ROI, "registry", "*.json")):          # files named inside another layer's entry
    txt = open(f).read(); reg |= {os.path.splitext(os.path.basename(m))[0] for m in __import__("re").findall(r"[\w./\\-]+\.tif", txt)}
for f in sorted(glob.glob(os.path.join(ROI, "*.tif"))):
    n = os.path.splitext(os.path.basename(f))[0]
    with rasterio.open(f) as d:
        t = d.transform; factor = g.RES / t.a
        same_crs = d.crs == g.CRS or d.crs.to_proj4().replace(" ", "") == g.CRS.to_proj4().replace(" ", "")
        exp = g.profile(factor)
        geo_ok = same_crs and abs(t.c - g.X0) < 1e-3 and abs(t.f - g.Y0) < 1e-3 and abs(t.e + t.a) < 1e-9 \
            and (d.width, d.height) == (exp["width"], exp["height"])
        check(f"{n}: grid", geo_ok, f"factor {factor:.4f} ({t.a:.3f} m), {d.width}x{d.height}, crs ok={same_crs}")
        a = d.read(1, out_shape=(min(d.height, 1500), min(d.width, 1200))).astype(np.float64)   # decimated read
        if d.nodata is not None and not np.isnan(d.nodata): a[a == d.nodata] = np.nan
        valid = np.isfinite(a).mean()
        lo_hi = next((v for k, v in RANGE.items() if n.startswith(k)), None)
        vmin, vmax = (np.nanmin(a), np.nanmax(a)) if valid else (np.nan, np.nan)
        rng_ok = lo_hi is None or (lo_hi[0] <= vmin and vmax <= lo_hi[1])
        check(f"{n}: values", valid > MIN_VALID.get(n, 0.9) and rng_ok, f"valid {valid * 100:.1f}%, range {vmin:.4g}..{vmax:.4g}" + (f" (limits {lo_hi})" if lo_hi else ""))
    if not (n in reg or any(n.startswith(r) for r in reg)):
        check(f"{n}: registry", False, "no registry entry")

# tables
T = os.path.join(ROI, "tables")
need = {"waypoints_registered.csv": ["sol", "lon_reg", "lat_reg", "col_reg", "row_reg"], "images_index_registered.csv": ["path", "sol", "col_reg", "row_reg"],
        "rad_observations.csv": ["sol"], "rad_per_sol.csv": ["sol"], "rems_daily.csv": ["sol"], "rems_rmd_campaign_hourly.csv": ["sol"]}
for fn, cols in need.items():
    p = os.path.join(T, fn)
    if not os.path.exists(p): check(f"table {fn}", False, "missing"); continue
    rd = list(csv.DictReader(open(p)))
    missing = [c for c in cols if c not in (rd[0] if rd else {})]
    check(f"table {fn}", bool(rd) and not missing, f"{len(rd)} rows; columns missing: {missing or 'none'}")
imgs = list(csv.DictReader(open(os.path.join(T, "images_index_registered.csv"))))
exist = sum(os.path.exists(r["path"]) for r in imgs)
inside = sum(0 <= float(r["col_reg"]) < g.WIDTH and 0 <= float(r["row_reg"]) < g.HEIGHT for r in imgs)
check("images: files exist", exist == len(imgs), f"{exist}/{len(imgs)} image files on disk")
check("images: inside ROI", inside / len(imgs) > 0.9, f"{inside}/{len(imgs)} localized inside the grid")

# cross-checks
E = rasterio.open(os.path.join(ROI, "elevation_m.tif")).read(1).astype(np.float64)
S = rasterio.open(os.path.join(ROI, "slope_deg.tif")).read(1).astype(np.float64)
w = E[1000:1400, 1000:1400]; gy, gx = np.gradient(w, g.RES)
s2 = np.degrees(np.arctan(np.hypot(gx, gy)))[2:-2, 2:-2]; s1 = S[1002:1398, 1002:1398]
check("slope vs elevation", np.nanmedian(np.abs(s1 - s2)) < 1.5, f"median |difference| {np.nanmedian(np.abs(s1 - s2)):.2f} deg (Horn vs central difference)")
wp = [r for r in csv.DictReader(open(os.path.join(T, "waypoints_registered.csv"))) if r.get("in_roi") in ("True", "true", "1")]
r_ = np.round([float(r["row_reg"]) - 0.5 for r in wp]).astype(int); c_ = np.round([float(r["col_reg"]) - 0.5 for r in wp]).astype(int)
ok = (r_ >= 0) & (r_ < g.HEIGHT) & (c_ >= 0) & (c_ < g.WIDTH)
d = E[r_[ok], c_[ok]] - np.array([float(r["elev_geoid"]) for r in wp])[ok]
nm = 1.4826 * np.median(np.abs(d - np.median(d)))
check("registered waypoints vs DTM", nm < 3, f"{ok.sum()} waypoints, NMAD {nm:.2f} m, bias {np.median(d):+.1f} m")
rad = list(csv.DictReader(open(os.path.join(T, "rad_per_sol.csv"))))
keyE = next(k for k in rad[0] if "E" in k and "mean" in k.lower())
camp = [float(r[keyE]) for r in rad if 4500 <= int(float(r["sol"])) <= 4799 and r[keyE] not in ("", "nan")]
check("RAD campaign dose rate", 3 < np.mean(camp) < 15, f"{len(camp)} sols, mean {np.mean(camp):.2f} uGy/h ({keyE})")
lay = json.load(open(os.path.join(ROI, "layers.json")))
check("layers.json", len(lay["layers"]) >= 25, f"{len(lay['layers'])} registry entries")

w1 = max(len(r[1]) for r in rows)
for s, n, dtl in rows: print(f"{s}  {n:<{w1}}  {dtl}")
print(f"\n{len(rows) - len(fails)}/{len(rows)} checks passed" + (f"; FAILED: {fails}" if fails else ""))
json.dump([{"status": s, "check": n, "detail": dtl} for s, n, dtl in rows], open(os.path.join(ROI, "validation_report.json"), "w"), indent=1)
sys.exit(1 if fails else 0)
