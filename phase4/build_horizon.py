"""Build data/processed/roi/world/horizon_32_4m.npz  (run from the repo root)."""
import sys, os, json, time
sys.path.insert(0, os.getcwd())
import numpy as np, rasterio
import marswalk_grid as g
from phase4.horizon import pick_device, horizon_angles, sky_factors, AZ_DEG, march_distances

dtm = rasterio.open("data/processed/roi/elevation_m.tif").read(1).astype(np.float64)
ng = json.load(open("data/processed/roi/nav_grid_4m.json")); W, H = ng["width"], ng["height"]
rr, cc = np.mgrid[0:H, 0:W]
rows = (4 * rr + 1.5).ravel(); cols = (4 * cc + 1.5).ravel()
t0 = time.time()
h, tr = horizon_angles(dtm, rows, cols, g.RES, eye=1.7, max_m=2000.0, chunk=12000, device=pick_device(os.environ.get("MARSWALK_DEVICE", "auto")))
print("GPU+copy total", time.time() - t0, "s")
h = h.reshape(32, H, W)
sv, ss = sky_factors(h)
# distance of each cell centre to the nearest ROI edge (m), flag < 300 m
dedge = np.minimum.reduce([rows, dtm.shape[0] - 1 - rows, cols, dtm.shape[1] - 1 - cols]).reshape(H, W) * g.RES
edge_flag = dedge < 300
trunc_frac = tr.reshape(32, H, W).mean(0).astype(np.float16)
meta = dict(method="ray march on 1 m DTM, bilinear, step=max(1 m, 1.2% of range), 1..2000 m, eye 1.7 m above bilinear ground at the "
            "4 m cell centre (base pixel 4c+1.5, 4r+1.5), Mars curvature drop d^2/(2R) R=3396190 m, max elevation angle; "
            "0 deg stored where no terrain is seen (ray off the ROI). sky_view=mean_az cos^2(max(h,0)); sky_solid=mean_az(1-sin(max(h,0))). "
            "Horizontal receiving surface, slope not included.",
            eye_height_m=1.7, max_distance_m=2000.0, azimuth_convention="clockwise from north; north=row decreasing, east=col increasing",
            edge_note="Rays leaving the ROI see no terrain beyond it, so horizons (and sky factors, which are then too high) are lower bounds "
                      "of obstruction for cells near the edge. edge_flag marks cells within 300 m of the ROI edge; trunc_frac is the share of the 32 rays "
                      "that left the ROI before 2 km.")
out = "data/processed/roi/world/horizon_32_4m.npz"
np.savez_compressed(out, horizon_deg=h.astype(np.float16), sky_view=sv, sky_solid=ss, azimuths=AZ_DEG.astype(np.float32),
                    edge_flag=edge_flag, edge_dist_m=dedge.astype(np.float32), trunc_frac=trunc_frac, meta=json.dumps(meta))
g.register("world_horizon", path=out, layers=["horizon_deg[32]", "sky_view", "sky_solid"], units="deg / 0-1", grid="4 m nav grid 585x732",
           source="elevation_m.tif (HiRISE 1 m DTM)", cls="derived", script="phase4/build_horizon.py", note=meta["edge_note"])
print("saved", out, os.path.getsize(out) / 1e6, "MB; edge-flagged cells", edge_flag.sum(), "of", edge_flag.size)
