#!/usr/bin/env python3
"""
MARSWALK Phase 2 - co-registration onto the reference terrain (DTM A = the grid's own frame).

Finds, by elevation matching, the horizontal offsets of
  (1) Curiosity's localized waypoints (MMGIS) relative to DTM A, and
  (2) DTM B relative to DTM A,
then writes registered copies: rover tables with col_reg/row_reg/x_reg/y_reg/lon_reg/lat_reg,
elevation_alt_aligned_m.tif and elevation_diff_aligned_m.tif. Nothing upstream is modified.

    python phase2/coregister.py
"""
import csv, json, os, sys
import numpy as np
import rasterio
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import marswalk_grid as g

ROI = g.OUT; T = os.path.join(ROI, "tables"); V = os.path.join(ROI, "vectors")
nmad = lambda d: 1.4826 * np.nanmedian(np.abs(d - np.nanmedian(d)))
A = rasterio.open(os.path.join(ROI, "elevation_m.tif")).read(1)
B = rasterio.open(os.path.join(ROI, "elevation_alt_m.tif")).read(1)
H, W = A.shape


def sample(Z, r, c):
    r = np.round(r).astype(int); c = np.round(c).astype(int)
    ok = (r >= 0) & (r < H) & (c >= 0) & (c < W)
    out = np.full(r.shape, np.nan); out[ok] = Z[r[ok], c[ok]]; return out


def search(cost, span, step):
    best = (np.inf, 0, 0)
    for dr in range(-span, span + 1, step):
        for dc in range(-span, span + 1, step):
            v = cost(dr, dc)
            if v < best[0]: best = (v, dr, dc)
    return best


# (1) waypoints -> DTM A
wp = list(csv.DictReader(open(os.path.join(T, "waypoints.csv"))))
wr = [w for w in wp if w.get("in_roi") in ("True", "true", "1")]
x, y = g.lonlat_to_xy(np.array([float(w["lon"]) for w in wr]), np.array([float(w["lat"]) for w in wr]))
c0, r0 = g.xy_to_pixel(x, y); r0 -= 0.5; c0 -= 0.5                       # pixel centres -> array index
ez = np.array([float(w["elev_geoid"]) for w in wr])
cost_w = lambda dr, dc: nmad(sample(A, r0 + dr, c0 + dc) - ez) if np.isfinite(sample(A, r0 + dr, c0 + dc)).sum() > 0.8 * len(ez) else np.inf
v0 = cost_w(0, 0)
_, dr, dc = search(cost_w, 160, 4); best_w = search(lambda a, b: cost_w(dr + a, dc + b), 4, 1)
wdr, wdc = dr + best_w[1], dc + best_w[2]
bias = float(np.nanmedian(sample(A, r0 + wdr, c0 + wdc) - ez))
# robustness: best shift using only the north half and only the south half of the points
half = r0 < np.median(r0); halves = []
for m in (half, ~half):
    f = lambda a, b, m=m: nmad(sample(A, r0[m] + a, c0[m] + b) - ez[m])
    halves.append(search(lambda a, b: f(wdr + a, wdc + b), 20, 2)[1:])
print(f"waypoints ({len(ez)}): NMAD {v0:.2f} m unshifted -> {best_w[0]:.2f} m at d_row={wdr}, d_col={wdc} "
      f"({wdr * g.RES:.0f} m south, {wdc * g.RES:.0f} m east); residual bias {bias:+.1f} m; half-sample residual shifts {halves}")

# (2) DTM B -> DTM A (decimated search, then full-res refine)
s = 8; Ad = A[::s, ::s]
def cost_b(dr, dc, Z=B):
    rr, cc = np.meshgrid(np.arange(0, H, s) + dr, np.arange(0, W, s) + dc, indexing="ij")
    return nmad(Ad - sample(Z, rr, cc))
vb0 = cost_b(0, 0); _, br, bc = search(cost_b, 160, 4)
best_b = search(lambda a, b: cost_b(br + a, bc + b), 4, 1); bdr, bdc = br + best_b[1], bc + best_b[2]
Bal = np.full_like(B, np.nan)
rs, re_ = max(0, -bdr), min(H, H - bdr); cs, ce = max(0, -bdc), min(W, W - bdc)
Bal[rs:re_, cs:ce] = B[rs + bdr:re_ + bdr, cs + bdc:ce + bdc]
diff = A - Bal
print(f"DTM B: NMAD {vb0:.2f} m -> {nmad(diff):.2f} m at d_row={bdr}, d_col={bdc}; median A-B {np.nanmedian(diff):+.2f} m; "
      f"valid {np.isfinite(diff).mean() * 100:.1f}%")
g.write_tif("elevation_alt_aligned_m", Bal.astype("float32"), tags={"shift_rows": bdr, "shift_cols": bdc})
g.write_tif("elevation_diff_aligned_m", diff.astype("float32"))

# registered rover tables: shift every localized position by the waypoint offset
def reg_rows(path, out):
    rows = list(csv.DictReader(open(path)))
    if not rows: return 0
    for r in rows:
        try: lon, lat = float(r["lon"]), float(r["lat"])
        except (KeyError, ValueError): continue
        xx, yy = g.lonlat_to_xy(lon, lat); cc, rr = g.xy_to_pixel(xx, yy)
        cc, rr = cc + wdc, rr + wdr
        xr, yr = g.X0 + cc * g.RES, g.Y0 - rr * g.RES
        r.update(col_reg=round(float(cc), 2), row_reg=round(float(rr), 2), x_reg=round(float(xr), 2), y_reg=round(float(yr), 2),
                 lon_reg=round(137.41 + np.degrees(xr / g.R_MARS), 7), lat_reg=round(float(np.degrees(yr / g.R_MARS)), 7))
    with open(out, "w", newline="") as f:
        wtr = csv.DictWriter(f, fieldnames=list(rows[0].keys()) + [k for k in ("col_reg", "row_reg", "x_reg", "y_reg", "lon_reg", "lat_reg") if k not in rows[0]])
        wtr.writeheader(); wtr.writerows(rows)
    return len(rows)
n1 = reg_rows(os.path.join(T, "waypoints.csv"), os.path.join(T, "waypoints_registered.csv"))
n2 = reg_rows(os.path.join(T, "images_index.csv"), os.path.join(T, "images_index_registered.csv"))
lines = json.load(open(os.path.join(V, "traverse_lines.geojson")))
for f in lines["features"]:
    def mv(c):
        xx, yy = g.lonlat_to_xy(c[0], c[1]); cc, rr = g.xy_to_pixel(xx, yy)
        xr, yr = g.X0 + (cc + wdc) * g.RES, g.Y0 - (rr + wdr) * g.RES
        return [round(137.41 + float(np.degrees(xr / g.R_MARS)), 7), round(float(np.degrees(yr / g.R_MARS)), 7)] + list(c[2:])
    geo = f["geometry"]
    geo["coordinates"] = [[mv(c) for c in ln] for ln in geo["coordinates"]] if geo["type"] == "MultiLineString" else [mv(c) for c in geo["coordinates"]]
json.dump(lines, open(os.path.join(V, "traverse_lines_registered.geojson"), "w"))

info = {"waypoints_to_dtmA": {"d_row": wdr, "d_col": wdc, "d_south_m": round(wdr * g.RES, 1), "d_east_m": round(wdc * g.RES, 1),
                              "nmad_before_m": round(float(v0), 2), "nmad_after_m": round(float(best_w[0]), 2),
                              "residual_vertical_bias_m": round(bias, 2), "n_points": int(len(ez)), "half_sample_residual_shifts": halves},
        "dtmB_to_dtmA": {"d_row": bdr, "d_col": bdc, "nmad_before_m": round(float(vb0), 2), "nmad_after_m": round(float(nmad(diff)), 2),
                         "median_diff_m": round(float(np.nanmedian(diff)), 2)}}
json.dump(info, open(os.path.join(ROI, "coregistration.json"), "w"), indent=1)
g.register("coregistration", file="data/processed/roi/coregistration.json", method="elevation matching (NMAD minimisation) on the 1 m grid",
           outputs=["elevation_alt_aligned_m.tif", "elevation_diff_aligned_m.tif", "tables/waypoints_registered.csv",
                    "tables/images_index_registered.csv", "vectors/traverse_lines_registered.geojson"], **info,
           limitations="Integer-pixel translation only; assumes one rigid offset over 2-3 km. Residual vertical bias is the geoid/areoid datum difference.")
print(f"registered {n1} waypoints, {n2} images, {len(lines['features'])} traverse lines")
