import sys, json; import os as _os; sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))
import numpy as np, rasterio
from scipy.ndimage import map_coordinates
import marswalk_grid as g
dtm = rasterio.open("data/processed/roi/elevation_m.tif").read(1).astype(np.float64)
z = np.load("data/processed/roi/world/horizon_32_4m.npz")
hd = z["horizon_deg"].astype(np.float32)
filled = np.where(np.isfinite(dtm), dtm, -1e9)
def slow(r4, c4, k):
    r0, c0 = 4*r4+1.5, 4*c4+1.5
    z0 = map_coordinates(dtm, [[r0], [c0]], order=1, mode="nearest")[0] + 1.7
    az = np.radians(k*11.25); best = None
    for d in np.arange(1.0, 2000.01, 1.0):           # every 1 m (finer than the production step)
        r = r0 - d/g.RES*np.cos(az); c = c0 + d/g.RES*np.sin(az)
        if not (0 <= r <= dtm.shape[0]-1 and 0 <= c <= dtm.shape[1]-1): break
        zz = map_coordinates(filled, [[r], [c]], order=1)[0]
        if zz < -1e8: continue
        a = np.degrees(np.arctan2(zz - d*d/(2*g.R_MARS) - z0, d)); best = a if best is None else max(best, a)
    return 0.0 if best is None else best
rng = np.random.default_rng(3)
cells = [(366, 292), (100, 120), (600, 450), (250, 500), (500, 80)]
for (r4, c4) in cells:
    errs = []
    for k in range(0, 32, 4):
        errs.append(hd[k, r4, c4] - slow(r4, c4, k))
    print((r4, c4), "horizon N..:", np.round(hd[::4, r4, c4], 2), "max|diff| deg", np.abs(errs).max().round(3))
