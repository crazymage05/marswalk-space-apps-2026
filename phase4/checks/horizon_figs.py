import sys, csv; import os as _os; sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))
import numpy as np, rasterio, matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from phase4 import visibility as v
z = np.load("data/processed/roi/world/horizon_32_4m.npz")
hs = rasterio.open("data/processed/roi/hillshade.tif").read(1)
hs4 = hs[:732*4, :585*4].reshape(732,4,585,4).mean((1,3))
ext=[0,585*4.047,732*4.047,0]
fig, ax = plt.subplots(1, 3, figsize=(17, 7))
for a, (d, t, kw) in zip(ax, [(z["sky_view"], "sky_view (cosine-weighted)", dict(cmap="viridis", vmin=0.85, vmax=1)),
                              (z["horizon_deg"][16].astype(float), "horizon elevation looking south (deg)", dict(cmap="magma", vmin=-10, vmax=20)),
                              (z["sky_solid"], "sky_solid", dict(cmap="viridis", vmin=0.7, vmax=1))]):
    im = a.imshow(d, extent=ext, **kw); a.set_title(t); plt.colorbar(im, ax=a, shrink=0.7)
    a.contour(z["edge_dist_m"], levels=[300], colors="w", linewidths=0.6, extent=[0,585*4.047,0,732*4.047], origin="upper")
    a.set_xlabel("east (m)"); a.set_ylabel("south (m)")
fig.suptitle("white line: 300 m from ROI edge (inside it, rays leave the ROI)"); plt.tight_layout(); plt.savefig("docs/figures/horizon_sky_maps.png", dpi=90); plt.close()
print("sky_view min/mean/max", z["sky_view"].min(), z["sky_view"].mean(), z["sky_view"].max())
rows=[r for r in csv.DictReader(open("data/processed/roi/tables/waypoints_registered.csv")) if 4500<=int(float(r["sol"]))<=4799]
pts=[(int(float(r["row_reg"])//4), int(float(r["col_reg"])//4)) for r in rows]
pts=[p for p in pts if 0<=p[0]<732 and 0<=p[1]<585]; print(len(pts), pts[0], pts[-1])
sel=[pts[0], pts[len(pts)//2]]
fig, ax = plt.subplots(1, 2, figsize=(14, 8))
for a,(r,c) in zip(ax, sel):
    m = v.visible_from(r,c); a.imshow(hs4, cmap="gray", extent=ext)
    a.imshow(np.ma.masked_where(~m, m), cmap="autumn", alpha=0.45, extent=ext)
    a.plot((c+.5)*4.047,(r+.5)*4.047,"c*",ms=14); a.add_patch(plt.Circle(((c+.5)*4.047,(r+.5)*4.047),300,fill=False,color="c",lw=.8))
    a.set_title(f"viewshed 300 m, eye 1.7 m, cell ({r},{c}); visible {m.sum()} cells"); a.set_xlim(0,585*4.047); a.set_ylim(732*4.047,0)
plt.tight_layout(); plt.savefig("docs/figures/horizon_viewshed.png", dpi=90); plt.close()
