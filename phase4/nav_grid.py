#!/usr/bin/env python3
"""
MARSWALK Phase 4 - the 4 m navigation grid shared by A*, the RL environment, the safety validator
and the twin page. One cell = 4 x 4 pixels of the 1 m ROI grid (marswalk_grid.py), so the grid is
585 x 732 cells of 4.047 m and cell index = row * 585 + col, the same indexing as the twin page.

Output: data/processed/roi/nav_grid_4m.npz (+ nav_grid_4m.json with layer meanings and units).

    python phase4/nav_grid.py
"""
import csv, json, os, sys
import numpy as np
import rasterio
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import marswalk_grid as g

K = 4; H, W = g.HEIGHT // K, g.WIDTH // K
P = g.OUT
rd = lambda n, b=1: rasterio.open(os.path.join(P, n + ".tif")).read(b).astype(np.float64)
blk = lambda a: a[:H * K, :W * K].reshape(H, K, W, K)
def coarse_to_cells(a):                              # aligned coarse raster (same origin) -> 4 m cells, nearest
    ri = np.minimum(((np.arange(H) + 0.5) / H * a.shape[0]).astype(int), a.shape[0] - 1)
    ci = np.minimum(((np.arange(W) + 0.5) / W * a.shape[1]).astype(int), a.shape[1] - 1)
    return a[np.ix_(ri, ci)]
zs = lambda a: (a - np.nanmean(a)) / np.nanstd(a)

elev = rd("elevation_m"); slope = rd("slope_deg"); rough = rd("roughness_m")
L = {"elevation_m": np.nanmean(blk(elev), axis=(1, 3)),
     "slope_max_deg": np.nanmax(blk(slope), axis=(1, 3)),          # steepest 1 m slope in the cell
     "slope_mean_deg": np.nanmean(blk(slope), axis=(1, 3)),
     "rough_max_m": np.nanmax(blk(rough), axis=(1, 3)),            # worst 5 m plane-fit residual std in the cell
     "valid_frac": np.isfinite(blk(elev)).mean(axis=(1, 3)) * np.isfinite(blk(rough)).mean(axis=(1, 3))}
crism = rasterio.open(os.path.join(P, "crism_mineral_params.tif")); names = list(crism.descriptions)
hyd, sul = (crism.read(names.index(n) + 1).astype(np.float64) for n in ("BD1900_2", "SINDEX2"))
L["hydration"] = coarse_to_cells(hyd); L["sulfate"] = coarse_to_cells(sul)
L["science"] = coarse_to_cells(zs(hyd) + zs(sul))                  # z-score sum; > 2 = strong orbital signal
dawn = []
for f in ("themis_day_bt_k", "themis_night_bt_k"):
    ds = rasterio.open(os.path.join(P, f + ".tif"))
    for b, d in enumerate(ds.descriptions, 1):
        if float(d.split("LST")[1]) < 9:
            a = ds.read(b).astype(np.float64); a[a <= 0] = np.nan
            if np.isfinite(a).mean() > 0.8: dawn.append(zs(a))
dawn_rel = np.nanmedian(np.stack(dawn), axis=0)
L["dawn_warmth_z"] = coarse_to_cells(dawn_rel)
L["loose"] = np.clip(-L["dawn_warmth_z"] / 2.0, 0, 1)               # 0 = warm at dawn (rock), 1 = cold (loose)
# Curiosity's campaign path (registered positions) as a cell mask: ground a rover crossed safely
camp = np.zeros((H, W), bool)
for r in csv.DictReader(open(os.path.join(P, "tables", "waypoints_registered.csv"))):
    if 4500 <= int(float(r["sol"])) <= 4799:
        rr, cc = int(float(r["row_reg"]) // K), int(float(r["col_reg"]) // K)
        if 0 <= rr < H and 0 <= cc < W: camp[rr, cc] = True
L["campaign_waypoint"] = camp

arrs = {k: (v.astype(np.float32) if v.dtype != bool else v) for k, v in L.items()}
np.savez_compressed(os.path.join(P, "nav_grid_4m.npz"), **arrs)
meta = {"width": W, "height": H, "cell_m": g.RES * K, "cells_per_base_pixel": K, "origin_xy_m": [g.X0, g.Y0], "crs": g.PROJ,
        "index": "cell = row * width + col; row 0 = north edge; same as the twin page grid",
        "layers": {"elevation_m": "mean DTM elevation, m (areoid)", "slope_max_deg": "max 1 m slope in cell, deg",
                   "slope_mean_deg": "mean 1 m slope, deg", "rough_max_m": "max 5 m roughness (plane-fit residual std), m",
                   "valid_frac": "fraction of valid 1 m terrain pixels (data confidence)",
                   "hydration": "CRISM BD1900_2 (unitless)", "sulfate": "CRISM SINDEX2 (unitless)",
                   "science": "z(BD1900_2)+z(SINDEX2) over the ROI; orbital hint only, ~18 m and ~18 m georeference uncertainty",
                   "dawn_warmth_z": f"THEMIS dawn brightness temperature z-score, median of {len(dawn)} images, ~101 m",
                   "loose": "0..1 likely loose material = clip(-dawn_warmth_z/2, 0, 1); coarse hint, not a calibrated thermal inertia",
                   "campaign_waypoint": "cells holding a registered Curiosity waypoint, sols 4500-4799"},
        "default_hard_limits": {"slope_max_deg": 25, "rough_max_m": 0.35, "valid_frac_min": 0.5},
        "radiation": "time-based only: dose = RAD campaign mean rate x time outside (6.45 uGy/h tissue-like E). Not mapped in space (plan Module 5A)."}
json.dump(meta, open(os.path.join(P, "nav_grid_4m.json"), "w"), indent=1)
for k, v in arrs.items():
    print(f"{k:18} {str(v.dtype):8} min {np.nanmin(v):10.4g}  max {np.nanmax(v):10.4g}  nan {np.isnan(v.astype(float)).mean() * 100:.2f}%")
print(f"-> nav_grid_4m.npz  {W} x {H} cells of {g.RES * K:.3f} m; campaign cells {camp.sum()}")
