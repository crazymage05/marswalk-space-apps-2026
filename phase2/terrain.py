"""MARSWALK Phase 2 - terrain layers. Run from e:\\nasa:  python phase2/terrain.py"""
import os, sys, json
sys.path.insert(0, os.getcwd())
import numpy as np, rasterio
from rasterio.windows import Window
from rasterio.warp import reproject, Resampling
from scipy.ndimage import uniform_filter, uniform_filter1d, correlate1d, map_coordinates
import marswalk_grid as G

HI = "data/raw/mro/hirise/"
DA = HI + "DTEEC_009149_1750_009294_1750_U01/"
DB = HI + "DTEEC_019698_1750_019988_1750_U01/DTEEC_019698_1750_019988_1750_U01.IMG"
PA = "DTEEC_009149_1750_009294_1750_U01 (HiRISE PSP_009149_1750 / PSP_009294_1750 stereo)"
PB = "DTEEC_019698_1750_019988_1750_U01"
M = 3  # derivative margin (px)
W, H, C0, R0 = G.WIDTH, G.HEIGHT, G.COL0, G.ROW0
os.makedirs(os.path.join(G.OUT, "quicklook"), exist_ok=True)
V = {}  # validation numbers


def nmad(x):
    x = x[np.isfinite(x)]
    return float(1.4826 * np.median(np.abs(x - np.median(x))))


def pct(a):
    return float(100 * np.isfinite(a).mean())


# ---------- DTM A ----------
src = rasterio.open(DA + "DTEEC_009149_1750_009294_1750_U01.IMG")
assert abs(src.transform.c - G.DTM_LEFT) < 1e-3 and abs(src.transform.f - G.DTM_TOP) < 1e-3 and abs(src.transform.a - G.RES) < 1e-9
z = src.read(1, window=Window(C0 - M, R0 - M, W + 2 * M, H + 2 * M)).astype("float64")
z[z < -1e30] = np.nan
inner = (slice(M, -M), slice(M, -M))
elev = z[inner].astype("float32")

# ---------- DTM B ----------
sb = rasterio.open(DB)
V["dtm_b_crs"] = sb.crs.to_proj4()
zb = np.full((H + 2 * M, W + 2 * M), np.nan, "float32")
tf = G.TRANSFORM * G.TRANSFORM.translation(-M, -M)
reproject(rasterio.band(sb, 1), zb, src_nodata=sb.nodata, dst_nodata=np.nan, dst_transform=tf,
          dst_crs=G.CRS, resampling=Resampling.bilinear)
zb[zb < -1e30] = np.nan
alt = zb[inner].copy()
diff = (elev - alt).astype("float32")
both = np.isfinite(diff)
V["valid_pct_A"], V["valid_pct_B"] = pct(elev), pct(alt)
V["overlap_pct"] = float(100 * both.mean())
V["diff_median_m"], V["diff_nmad_m"] = float(np.median(diff[both])), nmad(diff)
V["diff_mean_m"] = float(diff[both].mean())
V["diff_p1_p99_m"] = [float(v) for v in np.percentile(diff[both], [1, 99])]

# ---------- derivatives on the 1 m DTM ----------
res = G.RES


def sh(a, dy, dx):  # a[y+dy, x+dx]
    return np.roll(np.roll(a, -dy, 0), -dx, 1)


a_, b_, c_ = sh(z, -1, -1), sh(z, -1, 0), sh(z, -1, 1)
d_, f_ = sh(z, 0, -1), sh(z, 0, 1)
g_, h_, i_ = sh(z, 1, -1), sh(z, 1, 0), sh(z, 1, 1)
dzdx = ((c_ + 2 * f_ + i_) - (a_ + 2 * d_ + g_)) / (8 * res)   # per metre, east
dzdy = ((g_ + 2 * h_ + i_) - (a_ + 2 * b_ + c_)) / (8 * res)   # per metre, towards south (rows increase)
grad = np.hypot(dzdx, dzdy)
slope = np.degrees(np.arctan(grad))
asp_r = np.arctan2(-dzdx, dzdy)                 # azimuth of downslope direction (E=-dzdx, N=+dzdy)
aspect = np.degrees(asp_r) % 360.0
aspect[grad < 1e-9] = np.nan
tri = np.sqrt(sum((n - z) ** 2 for n in (a_, b_, c_, d_, f_, g_, h_, i_)))   # Riley 1999
# roughness: std of residual after a least-squares local plane over 5x5 (~5 m)
k = 5
ax = np.arange(k) - k // 2
vx = float((ax ** 2).mean())
m1, m2 = uniform_filter(z, k), uniform_filter(z * z, k)
cov_x = correlate1d(uniform_filter1d(z, k, axis=0), ax[::-1].astype(float) / k, axis=1)
cov_y = correlate1d(uniform_filter1d(z, k, axis=1), ax[::-1].astype(float) / k, axis=0)
rough = np.sqrt(np.clip((m2 - m1 ** 2) - (cov_x ** 2 + cov_y ** 2) / vx, 0, None))
# hillshade az 315, el 30
azr, elr = np.radians(315), np.radians(30)
sl_r = np.radians(slope)
hs = np.sin(elr) * np.cos(sl_r) + np.cos(elr) * np.sin(sl_r) * np.cos(azr - asp_r)
hs8 = np.where(np.isfinite(hs), np.clip(np.round(1 + 254 * np.clip(hs, 0, 1)), 1, 255), 0).astype("uint8")[inner]


def crop(a):
    return a[inner].astype("float32")


slope_o, aspect_o, tri_o, rough_o = crop(slope), crop(aspect), crop(tri), crop(rough)
sv = slope_o[np.isfinite(slope_o)]
V["slope_valid_pct"] = pct(slope_o)
V["slope_median_deg"] = float(np.median(sv))
for t in (15, 25, 30):
    V[f"slope_gt{t}_pct"] = float(100 * (sv > t).mean())
V["slope_p99_deg"] = float(np.percentile(sv, 99))
V["roughness_median_m"], V["tri_median_m"] = float(np.nanmedian(rough_o)), float(np.nanmedian(tri_o))

# ---------- Curiosity waypoints ----------
wp = json.load(open("data/raw/curiosity/traverse/MSL_waypoints.json"))["features"]
lon = np.array([f["properties"]["lon"] for f in wp])
lat = np.array([f["properties"]["lat"] for f in wp])
ez = np.array([f["properties"]["elev_geoid"] for f in wp], float)
sol = np.array([f["properties"]["sol"] for f in wp])
cc, rr = G.xy_to_pixel(*G.lonlat_to_xy(lon, lat))
ins = (cc >= 0.5) & (cc < W - 0.5) & (rr >= 0.5) & (rr < H - 0.5)
v = map_coordinates(np.nan_to_num(elev.astype("float64"), nan=-9999), [rr[ins] - 0.5, cc[ins] - 0.5], order=1)
ok = v > -9000
bias = v[ok] - ez[ins][ok]
V["waypoints_total"], V["waypoints_in_roi"], V["waypoints_used"] = len(wp), int(ins.sum()), int(ok.sum())
if ok.sum():
    V["waypoint_bias_median_m"], V["waypoint_bias_nmad_m"] = float(np.median(bias)), nmad(bias)
    V["waypoint_bias_minmax_m"] = [float(bias.min()), float(bias.max())]
    V["waypoint_sol_range"] = [int(sol[ins].min()), int(sol[ins].max())]

# ---------- registration diagnostics (horizontal shift search; informational, nothing is shifted) ----------
def wp_shift(Z):
    Zf = np.nan_to_num(Z.astype("float64"), nan=-9999)
    s = (cc > 130) & (cc < W - 130) & (rr > 130) & (rr < H - 130)
    best = None
    for dy in range(-120, 121, 6):
        for dx in range(-120, 121, 6):
            d = map_coordinates(Zf, [rr[s] - .5 + dy, cc[s] - .5 + dx], order=1) - ez[s]
            n = 1.4826 * np.median(np.abs(d - np.median(d)))
            if best is None or n < best[0]:
                best = (float(n), dy, dx, float(np.median(d)))
    return {"n_waypoints": int(s.sum()), "best_nmad_m": best[0], "dRow_px": best[1], "dCol_px": best[2], "median_bias_at_best_m": best[3]}


V["waypoint_shift_search_A"] = wp_shift(elev)
V["waypoint_shift_search_B"] = wp_shift(alt)
_s = (slice(300, -300, 3), slice(300, -300, 3))
_Bf = np.nan_to_num(alt, nan=float(np.nanmedian(alt)))
_best = None
for dy in range(-120, 121, 8):
    for dx in range(-120, 121, 8):
        d = (elev - np.roll(np.roll(_Bf, dy, 0), dx, 1))[_s]
        n = float(np.nanmedian(np.abs(d - np.nanmedian(d))) * 1.4826)
        if _best is None or n < _best[0]:
            _best = (n, dy, dx, float(np.nanmedian(d)))
V["dtm_A_vs_B_shift_search"] = {"best_nmad_m": _best[0], "B_rolled_rows_px": _best[1], "B_rolled_cols_px": _best[2], "median_diff_at_best_m": _best[3],
                                "note": "NMAD collapses from ~12 m to this when B is rolled: A and B are horizontally misregistered by tens of metres"}

# ---------- orthoimages (PDS-label alignment: C == DTM grid, A == 4x DTM grid) ----------
oc = rasterio.open(DA + "PSP_009149_1750_RED_C_01_ORTHO.JP2")
oa = rasterio.open(DA + "PSP_009149_1750_RED_A_01_ORTHO.JP2")
ortho1 = oc.read(1, window=Window(C0, R0, W, H))
ortho025 = oa.read(1, window=Window(4 * C0, 4 * R0, 4 * W, 4 * H))
V["ortho_1m_zero_pct"], V["ortho_025m_zero_pct"] = float(100 * (ortho1 == 0).mean()), float(100 * (ortho025 == 0).mean())
V["ortho_gdal_georef_note"] = ("GDAL's JP2 georeferencing is offset ~1.5 px from the PDS label/DTM grid; label offsets "
                               "(= DTM grid) used, since ortho A block-mean vs ortho C correlates best at zero shift")
a4 = ortho025.reshape(H, 4, W, 4).astype("float32").mean((1, 3))
V["ortho_A_vs_C_corr"] = float(np.corrcoef(a4.ravel(), ortho1.ravel())[0, 1])


def gm(x):
    gy, gx = np.gradient(x.astype("float32"))
    return np.hypot(gx, gy)


vm = (ortho1 > 0) & (hs8 > 0)
V["ortho_vs_hillshade_gradmag_corr"] = float(np.corrcoef(gm(ortho1)[vm], gm(hs8)[vm])[0, 1])
V["ortho_vs_hillshade_intensity_corr"] = float(np.corrcoef(ortho1[vm].astype("f4"), hs8[vm].astype("f4"))[0, 1])


# ---------- write ----------
def out(name, arr, units, method, src_ids, factor=1, nodata=np.nan, val=None, lim=""):
    p = G.write_tif(name, arr, factor=factor, nodata=nodata, tags={"units": units, "source": src_ids, "method": method})
    vp = pct(arr) if arr.dtype.kind == "f" else float(100 * (arr != nodata).mean())
    G.register(name, file=p.replace("\\", "/"), units=units, resolution_m=G.RES / factor, shape=list(arr.shape),
               dtype=str(arr.dtype), nodata=("NaN" if isinstance(nodata, float) else nodata), source_products=src_ids,
               method=method, valid_pct=vp, validation=val or {}, limitations=lim)
    print(f"{p}  {os.path.getsize(p) / 1e6:.1f} MB")


def vk(*ks):
    return {k: V[k] for k in ks if k in V}


out("elevation_m", elev, "m (HiRISE DTM height above Mars areoid)", "Direct crop of DTM A window cols 976:3316 rows 6081:9009; nodata<-1e30 -> NaN", PA,
    val=vk("valid_pct_A", "waypoint_shift_search_A", "waypoints_used", "waypoints_in_roi", "waypoint_bias_median_m", "waypoint_bias_nmad_m", "waypoint_bias_minmax_m"),
    lim="Waypoint bias includes rover-position error and vertical datum/control offsets. Stereo DTM noise and artefacts on steep faces.")
out("elevation_alt_m", alt, "m", "DTM B reprojected (rasterio.warp, bilinear) from eqc lon_0=137.38 to the shared grid (lon_0=137.41)", PB,
    val=vk("valid_pct_B", "dtm_b_crs", "waypoint_shift_search_B"), lim="Covers about 99% of ROI; resampled, so slightly smoother than A.")
out("elevation_diff_m", diff, "m (A - B)", "elevation_m minus elevation_alt_m", PA + " minus " + PB,
    val=vk("overlap_pct", "dtm_A_vs_B_shift_search", "diff_median_m", "diff_nmad_m", "diff_mean_m", "diff_p1_p99_m"),
    lim="A nonzero median means independent vertical control/datum offset between the two stereo DTMs, not terrain change. NMAD = relative noise + registration residual + resampling.")
out("slope_deg", slope_o, "degrees", "Horn 3x3 gradient on 1.0117 m DTM A; 3 px margin read so ROI edges are valid", PA,
    val=vk("slope_valid_pct", "slope_median_deg", "slope_gt15_pct", "slope_gt25_pct", "slope_gt30_pct", "slope_p99_deg"),
    lim="1 m baseline; DTM noise inflates slope on flat ground, cliffs are smoothed.")
out("aspect_deg", aspect_o, "degrees, direction the slope faces (downslope azimuth), 0=N clockwise", "Horn gradient; NaN where gradient < 1e-9", PA)
out("roughness_m", rough_o, "m", "Std of residual after removing a least-squares local plane in a 5x5 window (~5.06 m) of 1 m DTM A", PA,
    val=vk("roughness_median_m"), lim="Includes DTM noise; sub-metre rocks not resolved.")
out("tri", tri_o, "m", "Riley (1999) TRI: sqrt(sum of squared differences to the 8 neighbours), 1 m DTM A", PA, val=vk("tri_median_m"))
out("hillshade", hs8, "0..255 (1..255 valid, 0 nodata)", "Horn slope/aspect, sun az 315 el 30, no vertical exaggeration", PA, nodata=0)
ov = vk("ortho_1m_zero_pct", "ortho_025m_zero_pct", "ortho_A_vs_C_corr", "ortho_vs_hillshade_gradmag_corr", "ortho_vs_hillshade_intensity_corr", "ortho_gdal_georef_note")
out("ortho_025m", ortho025, "DN (8-bit RED, 0.25 m)", "Window read from JP2 using PDS-label alignment (4x DTM grid)", "PSP_009149_1750_RED_A_01_ORTHO",
    factor=4, nodata=0, val=ov, lim="0 = nodata. Illumination baked in (differs from hillshade sun).")
out("ortho_1m", ortho1, "DN (8-bit RED, 1 m)", "Window read from JP2 using PDS-label alignment (= DTM grid)", "PSP_009149_1750_RED_C_01_ORTHO",
    nodata=0, val=ov)

# ---------- quicklook ----------
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
fig, axs = plt.subplots(1, 2, figsize=(14, 9.5))
axs[0].imshow(np.ma.masked_equal(hs8, 0), cmap="gray", interpolation="nearest")
axs[0].set_title("Hillshade (az 315, el 30)")
im = axs[1].imshow(np.ma.masked_invalid(slope_o), cmap="magma", vmin=0, vmax=45, interpolation="nearest")
axs[1].set_title("Slope (deg)")
plt.colorbar(im, ax=axs[1], shrink=0.7)
for a in axs:
    a.set_xticks([]); a.set_yticks([])
fig.suptitle("MARSWALK ROI terrain (HiRISE DTM A, 1.01 m)")
fig.tight_layout()
fig.savefig(os.path.join(G.OUT, "quicklook", "terrain.png"), dpi=90)
plt.close(fig)

json.dump(V, open(os.path.join(G.REGISTRY, "terrain_validation.json"), "w"), indent=1)
print(json.dumps(V, indent=1))
