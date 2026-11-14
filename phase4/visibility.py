"""Viewshed on the 4 m nav grid, line of sight tested on the 1 m DTM.

visible_from(row, col, radius_m=300, eye_m=1.7) -> bool [732, 585]
visible_patch(row, col, half=7)                 -> bool [2*half+1, 2*half+1]

Method: the observer stands at the 4 m cell centre (base pixel 4c+1.5, 4r+1.5), so the sub-pixel offset of every
ray sample is the same for all observers. The ray geometry (sample pixel indices, bilinear weights, the 4 m cell each
sample falls in, whether it lies in the cell's central 2 x 2 m) is precomputed once per radius. A call then
gathers the DTM samples, computes elevation angle (with Mars curvature d^2/2R) and a running maximum along each ray;
a sample is visible if its angle is >= the maximum before it. A cell is visible if one of its central samples is.
"""
import os, json
import numpy as np
import rasterio

RES = 1.0117467945795
R_MARS = 3396190.0
K = 4
_dtm = None; _pre = {}


def _load():
    global _dtm, H4, W4
    if _dtm is None:
        a = rasterio.open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                       "data", "processed", "roi", "elevation_m.tif")).read(1)
        _dtm = a.astype(np.float32)
        H4, W4 = a.shape[0] // K, a.shape[1] // K
    return _dtm


def _precompute(radius_m):
    n = int(np.ceil(radius_m / RES))
    n_az = int(np.ceil(2 * np.pi * n * 0.9))            # ~1.1 pixel spacing at the rim
    az = np.arange(n_az) * 2 * np.pi / n_az
    d = np.arange(1.0, radius_m + 0.01, 1.0)              # 1 m steps
    dx = d[None, :] / RES * np.sin(az)[:, None]; dy = -d[None, :] / RES * np.cos(az)[:, None]
    # observer at index (1.5, 1.5) inside its cell; offsets relative to the observer pixel (floor of 1.5 = 1)
    fx = 1.5 + dx; fy = 1.5 + dy
    x0 = np.floor(fx); y0 = np.floor(fy); wx = (fx - x0); wy = (fy - y0)
    ox = (x0 - 1).astype(np.int32); oy = (y0 - 1).astype(np.int32)           # integer offsets from observer pixel
    # cell membership: cell-local coords relative to cell origin (observer cell origin is index 0 of base pixel block)
    cx = np.floor(fx / K).astype(np.int32); cy = np.floor(fy / K).astype(np.int32)   # cell offset (observer cell = 0)
    # central 2x2 m of the cell: index coordinate distance to the cell centre (2 -> in index coords centre 1.5 + K*cell)
    ccx = fx - (K * cx + 1.5); ccy = fy - (K * cy + 1.5)
    half = 1.0 / RES
    central = (np.abs(ccx) <= half) & (np.abs(ccy) <= half)
    keep = central                                                    # only central samples decide a cell
    # but the running max needs all samples: keep full arrays, store the mask
    p = dict(n=n, d=d.astype(np.float32), ox=ox, oy=oy, wx=wx.astype(np.float32), wy=wy.astype(np.float32),
             cx=cx, cy=cy, central=central, curv=(d ** 2 / (2 * R_MARS)).astype(np.float32))
    # flat index gather inside a padded window of size (2n+3)^2 centred on the observer pixel
    S = 2 * n + 4
    p["S"] = S
    base = (oy + n + 1) * S + (ox + n + 1)
    p["i00"] = base.astype(np.int32)
    p["w00"] = ((1 - wx) * (1 - wy)).astype(np.float32); p["w01"] = (wx * (1 - wy)).astype(np.float32)
    p["w10"] = ((1 - wx) * wy).astype(np.float32); p["w11"] = (wx * wy).astype(np.float32)
    # pre-select the centre samples for scatter
    ri, ki = np.nonzero(central)
    p["ri"], p["ki"] = ri, ki
    p["cell_dx"], p["cell_dy"] = cx[ri, ki], cy[ri, ki]
    return p


def visible_from(row, col, radius_m=300.0, eye_m=1.7):
    """Bool [732, 585]: 4 m cells whose centre surface point is visible from (row, col) at eye height eye_m."""
    dtm = _load()
    key = float(radius_m)
    if key not in _pre: _pre[key] = _precompute(radius_m)
    p = _pre[key]; n, S = p["n"], p["S"]
    r0, c0 = K * row + 1, K * col + 1                      # observer base pixel (centre is at index 4r+1.5 = pixel 4r+1 + 0.5)
    win = np.full((S, S), -1e9, np.float32)
    ya, yb = max(r0 - n - 1, 0), min(r0 + n + 3, dtm.shape[0]); xa, xb = max(c0 - n - 1, 0), min(c0 + n + 3, dtm.shape[1])
    win[ya - (r0 - n - 1): ya - (r0 - n - 1) + yb - ya, xa - (c0 - n - 1): xa - (c0 - n - 1) + xb - xa] = \
        np.nan_to_num(dtm[ya:yb, xa:xb], nan=-1e9)
    wf = win.ravel(); i = p["i00"]
    z = wf[i] * p["w00"] + wf[i + 1] * p["w01"] + wf[i + S] * p["w10"] + wf[i + S + 1] * p["w11"]
    z0 = (win[n + 1, n + 1] + win[n + 1, n + 2] + win[n + 2, n + 1] + win[n + 2, n + 2]) * 0.25    # bilinear at (1.5,1.5)
    zeye = z0 + eye_m
    bad = z < -1e8
    ang = (z - p["curv"] - zeye) / p["d"]                  # tan-like slope; monotonic in the angle, same ordering
    ang[bad] = -1e9
    cm = np.maximum.accumulate(ang, axis=1)
    vis = np.empty_like(ang, dtype=bool)
    vis[:, 0] = True
    vis[:, 1:] = ang[:, 1:] >= cm[:, :-1] - 1e-6
    vis &= ~bad
    out = np.zeros((H4, W4), bool)
    rr = row + p["cell_dy"]; cc = col + p["cell_dx"]
    v = vis[p["ri"], p["ki"]]
    ok = v & (rr >= 0) & (rr < H4) & (cc >= 0) & (cc < W4)
    out[rr[ok], cc[ok]] = True
    out[row, col] = True
    return out


def visible_patch(row, col, half=7, radius_m=300.0, eye_m=1.7):
    """Bool [2*half+1, 2*half+1] patch centred on (row, col); cells outside the grid are False."""
    m = visible_from(row, col, radius_m, eye_m)
    P = np.zeros((2 * half + 1, 2 * half + 1), bool)
    r0, r1 = max(row - half, 0), min(row + half + 1, m.shape[0]); c0, c1 = max(col - half, 0), min(col + half + 1, m.shape[1])
    P[r0 - (row - half): r1 - (row - half), c0 - (col - half): c1 - (col - half)] = m[r0:r1, c0:c1]
    return P
