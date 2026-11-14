"""MARSWALK phase 2: HiRISE ESP_094058_1750 (2026-08-20) RED + colour onto the shared grid.
Run from the repo root:  python phase2/hirise_recent.py
"""
import os, sys
import numpy as np
import rasterio
from rasterio.windows import Window, from_bounds
from rasterio.warp import reproject, Resampling
from rasterio.transform import Affine
sys.path.insert(0, os.getcwd())
import marswalk_grid as G

RAW = os.path.join("data", "raw", "mro", "hirise")
RED = os.path.join(RAW, "esp_094058_1750_red", "ESP_094058_1750_RED.JP2")
COL = os.path.join(RAW, "esp_094058_1750_color", "ESP_094058_1750_MRGB.JP2")  # 8-bit 3-band colour, 0.5 m
ORTHO_JP2 = os.path.join(RAW, "DTEEC_009149_1750_009294_1750_U01", "PSP_009149_1750_RED_C_01_ORTHO.JP2")
QL = os.path.join(G.OUT, "quicklook", "hirise2026.png")
LON0 = 137.41


def warp(path, factor, shift=(0.0, 0.0)):
    """Reproject source onto grid at `factor`. shift=(east_m, north_m) is the apparent displacement of the
    image content relative to the reference; the source georeferencing is moved by the opposite amount."""
    p = G.profile(factor)
    with rasterio.open(path) as s:
        t = Affine(s.transform.a, 0, s.transform.c - shift[0], 0, s.transform.e, s.transform.f - shift[1])
        off = G.R_MARS * np.radians(LON0 - 180.0)  # central-meridian offset between the two CRSs
        L, T = p["transform"].c + off, p["transform"].f
        Rr, B = L + p["width"] * p["transform"].a, T + p["height"] * p["transform"].e
        m = 30
        w = from_bounds(L - m, B - m, Rr + m, T + m, t).round_offsets().round_lengths()
        w = w.intersection(Window(0, 0, s.width, s.height))
        src = s.read(window=w)
        st = t * Affine.translation(w.col_off, w.row_off)
        dst = np.zeros((s.count, p["height"], p["width"]), s.dtypes[0])
        for i in range(s.count):
            reproject(src[i], dst[i], src_transform=st, src_crs=s.crs, dst_transform=p["transform"],
                      dst_crs=G.CRS, resampling=Resampling.bilinear, src_nodata=0, dst_nodata=0)
    return dst


def load_ref():
    f = os.path.join(G.OUT, "ortho_1m.tif")
    if os.path.exists(f):
        with rasterio.open(f) as d:
            return d.read(1).astype("float32"), "ortho_1m.tif"
    with rasterio.open(ORTHO_JP2) as d:
        a = d.read(1, window=Window(G.COL0, G.ROW0, G.WIDTH, G.HEIGHT)).astype("float32")
    return a, "PSP_009149_1750_RED_C_01_ORTHO.JP2 window"


def feat(a):
    a = a.astype("float64")
    k = np.ones(3) / 3
    for ax in (0, 1):
        a = np.apply_along_axis(lambda v: np.convolve(v, k, "same"), ax, a)
    gy, gx = np.gradient(a)
    g = np.hypot(gx, gy)
    return g - g.mean()


def phasecorr(a, b):
    """(dx, dy) px: content of a is displaced by (dx, dy) relative to b (x right, y down)."""
    n = a.shape[0]
    win = np.outer(np.hanning(n), np.hanning(n))
    R = np.fft.fft2(a * win) * np.conj(np.fft.fft2(b * win))
    R /= np.abs(R) + 1e-9
    c = np.fft.fftshift(np.real(np.fft.ifft2(R)))
    iy, ix = np.unravel_index(np.argmax(c), c.shape)
    dy, dx = iy - n // 2, ix - n // 2
    if 0 < ix < n - 1:
        dx += 0.5 * (c[iy, ix - 1] - c[iy, ix + 1]) / (c[iy, ix - 1] + c[iy, ix + 1] - 2 * c[iy, ix] - 1e-12)
    if 0 < iy < n - 1:
        dy += 0.5 * (c[iy - 1, ix] - c[iy + 1, ix]) / (c[iy - 1, ix] + c[iy + 1, ix] - 2 * c[iy, ix] - 1e-12)
    return dx, dy, c.max()


def measure(img, ref, tile=512):
    fi, fr = feat(img), feat(ref)
    H, W = img.shape
    out = []
    for r0 in np.linspace(0, H - tile, 3).astype(int):
        for c0 in np.linspace(0, W - tile, 3).astype(int):
            ti, tr = img[r0:r0 + tile, c0:c0 + tile], ref[r0:r0 + tile, c0:c0 + tile]
            if (ti == 0).mean() > 0.1 or (tr == 0).mean() > 0.1:
                out.append((r0, c0, np.nan, np.nan, 0))
                continue
            dx, dy, q = phasecorr(fi[r0:r0 + tile, c0:c0 + tile], fr[r0:r0 + tile, c0:c0 + tile])
            out.append((r0, c0, dx * G.RES, -dy * G.RES, q))  # east_m, north_m
    return np.array(out)


def report(tag, m):
    print(f"-- {tag}: tile(row,col)  east_m  north_m  peak")
    for r, c, e, n, q in m:
        print(f"   ({int(r):4d},{int(c):4d})  {e:6.2f}  {n:6.2f}  {q:.3f}")
    v = m[~np.isnan(m[:, 2])]
    med = (float(np.median(v[:, 2])), float(np.median(v[:, 3])))
    print(f"   median east {med[0]:.2f} m, north {med[1]:.2f} m; std {v[:, 2].std():.2f}/{v[:, 3].std():.2f}")
    return med


def main():
    with rasterio.open(RED) as s:
        print("RED src:", s.crs.to_proj4(), s.transform.to_gdal(), s.width, s.height, s.dtypes)
    ref, refname = load_ref()
    print("reference:", refname)
    img1 = warp(RED, 1)[0].astype("float32")
    med0 = report("before", measure(img1, ref))
    shift = (0.0, 0.0)
    if np.hypot(*med0) > 1.0:
        shift = med0
        img1c = warp(RED, 1, shift)[0].astype("float32")
        med1 = report(f"after shift {shift}", measure(img1c, ref))
    else:
        med1 = med0
        print("shift <= 1 m, not applied")
    red4 = warp(RED, 4, shift)[0]
    red1 = warp(RED, 1, shift)[0]
    col2 = warp(COL, 2, shift)
    cov_red = float((red1 > 0).mean() * 100)
    cov_col = float((col2.max(0) > 0).mean() * 100)
    print(f"coverage red 1m {cov_red:.1f}%, colour 0.5m {cov_col:.1f}%")
    tags = dict(source="ESP_094058_1750", acquired="2026-08-20", shift_east_m=shift[0], shift_north_m=shift[1])
    f1 = G.write_tif("hirise2026_red_025m", red4, 4, 0, tags)
    f2 = G.write_tif("hirise2026_red_1m", red1, 1, 0, tags)
    f3 = G.write_tif("hirise2026_color_05m", col2, 2, 0, tags, ["red", "green", "blue"])
    common = dict(method="rasterio.warp.reproject bilinear from lon_0=180 source window; translation registration vs DTM ortho",
                  registration_shift_applied_m=dict(east=shift[0], north=shift[1]),
                  residual_median_before_m=list(med0), residual_median_after_m=list(med1),
                  reference=refname, nodata=0,
                  limitations="Translation only; 2008 vs 2026 illumination differs; local residuals remain.")
    G.register("hirise2026_red_025m", file=f1, units="DN uint16", resolution_m=0.25,
               source="ESP_094058_1750_RED.JP2", coverage_pct=cov_red, **common)
    G.register("hirise2026_red_1m", file=f2, units="DN uint16", resolution_m=G.RES,
               source="ESP_094058_1750_RED.JP2", coverage_pct=cov_red, **common)
    G.register("hirise2026_color_05m", file=f3, units="DN uint8 (MRGB)", resolution_m=G.RES / 2,
               source="ESP_094058_1750_MRGB.JP2", coverage_pct=cov_col, **common)

    from PIL import Image

    def st(a):
        v = a[a > 0]
        lo, hi = np.percentile(v, [1, 99]) if v.size else (0, 1)
        return (np.clip((a - lo) / (hi - lo + 1e-9), 0, 1) * 255).astype("uint8")
    f = 3
    h, w = (red1.shape[0] // f) * f, (red1.shape[1] // f) * f
    ds = lambda a: a[:h, :w].reshape(h // f, f, w // f, f).mean((1, 3))
    A, B = st(ds(red1.astype("float32"))), st(ds(ref))
    yy, xx = np.mgrid[:A.shape[0], :A.shape[1]]
    chk = np.where(((yy // 40 + xx // 40) % 2) == 0, A, B).astype("uint8")
    os.makedirs(os.path.dirname(QL), exist_ok=True)
    Image.fromarray(np.hstack([A, B, chk])).save(QL)
    for p in (f1, f2, f3, QL):
        print(p, os.path.getsize(p) // 1024, "KB")


if __name__ == "__main__":
    main()
