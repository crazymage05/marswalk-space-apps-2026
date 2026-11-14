#!/usr/bin/env python3
"""F1 orbital-context prep (normal Python, rasterio + scipy): MOLA MEGDR (32 px/deg) -> wide context terrain around the 2.4 x 3 km HiRISE tile.
Writes film/f1_data/mola_ctx.npz (read by tools/f1_blender_scene.py when F1_ORBITAL=1). Does not touch any other file in film/f1_data.
  python tools/f1_prep_mola.py
Heights: MOLA areoid heights (m) + one constant offset so that the mean over the ROI equals the HiRISE DTM mean (about +27 m), plus a
correction field D that equals (tile - MOLA) on the tile edge and decays away from it (smooth part exp(-d/4 km), fine part exp(-d/80 m)),
so the tile edge is not a cliff. Two tiers: inner 50 m spacing (tile + 9 km), outer 1 km spacing (+-300 km), faded to a flat level at the rim.
Colour: vertex colours = tile palette mean x mild hillshade (sun of the LMST 9 shots) x slight elevation tint. No THEMIS (no mosaic on disk)."""
import json, os
import numpy as np, rasterio
from PIL import Image
from scipy.ndimage import map_coordinates, gaussian_filter, minimum_filter1d
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); os.chdir(ROOT)
D = "film/f1_data"; J = json.load(open(f"{D}/scene.json")); R = 3396190.0; LON0 = 137.41
E0, N0, Z0 = J["E0"], J["N0"], J["Z0"]
mola = rasterio.open("data/raw/mgs/mola/megt90n000fb/MEGT90N000FB.IMG").read(1).astype(np.float32)   # int16 metres above the areoid, 32 px/deg, lon 0..360
def M(x, y):                                   # Blender x, y (m) -> MOLA height (m), bicubic
    lon = LON0 + np.degrees((x + E0) / R); lat = np.degrees((y + N0) / R)
    return map_coordinates(mola, [2879.5 - lat * 32.0, lon * 32.0 - 0.5], order=3, mode="nearest")

# tile (the 4 m context mesh) geometry, as built by f1_blender_scene.py
X = J["ctx"]; zx = np.load(f"{D}/context_z.npy") - 0.6                         # Blender z of the tile surface
ny, nx = zx.shape; px = X["px"]
xv0, yv0 = X["x0"] + 0.125 * px, X["y0"] - 0.125 * px                           # first vertex (west, north)
xmin, xmax = xv0, xv0 + (nx - 1) * px; ymax, ymin = yv0, yv0 - (ny - 1) * px
# datum offset: mean over the ROI (HiRISE) minus mean of MOLA over the same points
jj, ii = np.mgrid[0:ny, 0:nx]
mt = M(xv0 + ii * px, yv0 - jj * px)
OFF = float(np.mean(zx + 0.6) - np.mean(mt))
print("tile extent x %.0f..%.0f y %.0f..%.0f ; HiRISE-MOLA mean offset %.1f m ; tile relief in MOLA %.0f..%.0f" % (xmin, xmax, ymin, ymax, OFF, mt.min() + OFF, mt.max() + OFF))
Dt = zx - (mt + OFF); Ds = gaussian_filter(Dt, 75, mode="nearest")            # tile minus MOLA; smoothed over ~300 m
def Dfield(x, y):
    cx, cy = np.clip(x, xmin, xmax), np.clip(y, ymin, ymax); d = np.hypot(x - cx, y - cy)
    c = [(yv0 - cy) / px, (cx - xv0) / px]
    raw = map_coordinates(Dt, c, order=1, mode="nearest"); sm = map_coordinates(Ds, c, order=1, mode="nearest")
    return sm * np.exp(-d / 4000.0) + (raw - sm) * np.exp(-d / 80.0), d
def height(x, y):
    dd, d = Dfield(x, y); return M(x, y) + OFF + dd, d

# ---- inner tier: lines every 50 m outside the tile and across it (hole = quads fully inside the tile), z on the tile edge from the tile itself
def lines(lo, hi, step, ext):
    n = int(np.ceil((hi - lo) / step)); inner = np.linspace(lo, hi, n + 1)
    return np.r_[lo - step * np.arange(ext, 0, -1), inner, hi + step * np.arange(1, ext + 1)]
IN_EXT = 180
xs, ys_up = lines(xmin, xmax, 50.0, IN_EXT), lines(ymin, ymax, 50.0, IN_EXT)
ys = ys_up[::-1]                                                              # north to south
gx, gy = np.meshgrid(xs, ys); zi, di = height(gx, gy)
onrect = (gx >= xmin - 1e-6) & (gx <= xmax + 1e-6) & (gy >= ymin - 1e-6) & (gy <= ymax + 1e-6)
edge = onrect & ((np.abs(gx - xmin) < 1e-6) | (np.abs(gx - xmax) < 1e-6) | (np.abs(gy - ymin) < 1e-6) | (np.abs(gy - ymax) < 1e-6))
def tile_z(x, y): return map_coordinates(zx, [(yv0 - y) / px, (x - xv0) / px], order=1, mode="nearest")
ztile = tile_z(gx, gy)
# boundary vertices: lowest tile vertex within +-30 m along the edge, minus 0.3 m (covers the 50 m chord over the 4 m relief)
fx = np.linspace(xmin, xmax, 4000); fy = np.linspace(ymin, ymax, 4000)
def edge_min(vals, coords, c):
    m = minimum_filter1d(vals, 15, mode="nearest"); return np.interp(c, coords, m)
topz, botz = tile_z(fx, np.full_like(fx, ymax)), tile_z(fx, np.full_like(fx, ymin))
lefz, rigz = tile_z(np.full_like(fy, xmin), fy), tile_z(np.full_like(fy, xmax), fy)
zi = np.where(edge & (np.abs(gy - ymax) < 1e-6), edge_min(topz, fx, gx), zi)
zi = np.where(edge & (np.abs(gy - ymin) < 1e-6), edge_min(botz, fx, gx), zi)
zi = np.where(edge & (np.abs(gx - xmin) < 1e-6) & (gy < ymax - 1e-6) & (gy > ymin + 1e-6), edge_min(lefz, fy, gy), zi)
zi = np.where(edge & (np.abs(gx - xmax) < 1e-6) & (gy < ymax - 1e-6) & (gy > ymin + 1e-6), edge_min(rigz, fy, gy), zi)
zi = np.where(edge, zi - 0.3, zi)
zi = np.where(onrect & ~edge, ztile - 30.0, zi)                                 # hole interior (never meshed; kept for the array shape)
# illustrative fractal relief on the inner tier (MOLA is 1.85 km/px, so without it the ring around the tile is a smooth sheet): fBm, std 2.2 m (lambda/100 m)^0.8,
# wavelengths 100 m - 3 km, ramped in from 0 at the tile edge over 400 m. NOT measured; the tile and the 1.85 km MOLA relief are the data.
rng = np.random.default_rng(7); fb = np.zeros(zi.shape, np.float64)
for sg in (2, 4, 8, 16, 32, 64):
    n_ = gaussian_filter(rng.standard_normal(zi.shape), sg, mode="wrap"); n_ /= n_.std(); fb += n_ * 2.2 * ((sg * 50.0) / 100.0) ** 0.8 / 1.6
ramp = np.clip(di / 400.0, 0, 1); ramp = ramp * ramp * (3 - 2 * ramp)
zi = np.where(onrect, zi, zi + fb * ramp)
alb = 1.0 + 0.16 * np.tanh(gaussian_filter(rng.standard_normal(zi.shape), 3, mode="wrap") / 0.06) * ramp
alb *= 1.0 + 0.22 * (0.5 + 0.5 * np.sin(2 * np.pi * zi / 55.0 + 4 * gaussian_filter(rng.standard_normal(zi.shape), 12, mode="wrap") / 0.03 / 40) - 0.5) * ramp   # faint strata banding
# ---- outer tier: 1 km, +-300 km, hole = inner tier extent less one cell, lowered 5 m, faded to a flat level over the last 40 km
OS, OEXT = 1000.0, 300000.0
ox = np.arange(-OEXT, OEXT + 1, OS); gxo, gyo = np.meshgrid(ox, ox[::-1]); zo, _ = height(gxo, gyo)
rr = np.maximum(np.abs(gxo), np.abs(gyo)); rim = rr >= OEXT - 1
FAR = float(np.mean(zo[rim]))
w = np.clip((rr - (OEXT - 40000.0)) / 40000.0, 0, 1); w = w * w * (3 - 2 * w)
zo = zo * (1 - w) + FAR * w - 5.0; zo[rim] = FAR                              # rim flush with the far ring (the 5 m is only under the inner tier)
print("outer: mola+offset range %.0f..%.0f, far level %.0f ; inner z range %.0f..%.0f" % (zo.min(), zo.max(), FAR, zi[~onrect].min(), zi.max()))

# ---- vertex colours: tile palette mean x mild hillshade x slight elevation tint
tex = np.asarray(Image.open(f"{D}/context_tex.jpg").convert("RGB"), np.float32) / 255
lin = np.power(tex, 2.2).mean((0, 1)) * 0.45 * 1.05                                 # image_mat multiplies the texture by 0.45
el, az = np.radians(42.1), np.radians(52.2); sun = np.array([np.cos(el) * np.sin(az), np.cos(el) * np.cos(az), np.sin(el)])
def colours(z, gx_, gy_):
    dzdy, dzdx = np.gradient(z, gy_[:, 0], gx_[0, :]) if gx_.ndim == 2 else (None, None)
    n = np.stack([-dzdx, -dzdy, np.ones_like(z)], -1); n /= np.linalg.norm(n, axis=-1, keepdims=True)
    shade = np.clip(n @ sun, 0, 1) / np.sin(el)                                # 1 on flat ground
    k = np.clip(1 + 0.9 * (shade - 1), 0.3, 1.6)
    t = np.clip((z + 950.0) / 5200.0, 0, 1)                                          # elevation -4600..+600 m (z = elevation + 3650)
    tint = np.stack([1 + 0.10 * t, 1 + 0.04 * t, 1 - 0.10 * t], -1)             # paler, less red up the mound
    return (lin[None, None, :] * k[..., None] * tint * (1.0 - 0.18 * (1 - t))[..., None]).astype(np.float32)
ci = colours(zi, gx, gy) * alb[..., None].astype(np.float32); co = colours(zo, gxo, gyo)
np.savez(f"{D}/mola_ctx.npz", xs=xs.astype(np.float32), ys=ys.astype(np.float32), zi=zi.astype(np.float32), ci=ci,
         xmin=xmin, xmax=xmax, ymin=ymin, ymax=ymax, ox=ox.astype(np.float32), zo=zo.astype(np.float32), co=co, far=FAR, farcol=co[0, :].mean(0), off=OFF, oext=OEXT, os_=OS)
# target heights used by the orbital camera path (Gale crater centre, Mount Sharp upper mound), Blender coordinates
def ll(lat, lon): return R * np.radians(lon - LON0) - E0, R * np.radians(lat) - N0
for nm, la, lo in (("sharp", -5.08, 137.85), ("gale", -5.4, 137.8)):
    x, y = ll(la, lo); print(nm, "x %.0f y %.0f z %.0f" % (x, y, float(height(np.array([x]), np.array([y]))[0][0])))
json.dump({"sharp": [float(v) for v in ll(-5.08, 137.85)] + [float(height(*[np.array([v]) for v in ll(-5.08, 137.85)])[0][0])],
           "gale": [float(v) for v in ll(-5.4, 137.8)] + [float(height(*[np.array([v]) for v in ll(-5.4, 137.8)])[0][0])], "far": FAR, "off": OFF},
          open(f"{D}/mola_ctx.json", "w"))
print("wrote film/f1_data/mola_ctx.npz  inner %s outer %s" % (zi.shape, zo.shape))
