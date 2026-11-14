"""Ground-level terrain occlusion on the 1 m walk corridor (W2), for the twin's terrain shading.

Writes data/processed/roi/world/skyview_1m_corridor.npz and demo/twin/walk_ao.json. Run from the repo root.
MARSWALK_DEVICE=auto|cuda|mps|cpu (default auto). About a minute on an Apple M5 Pro GPU.

Why a separate layer: the world model's sky_view (horizon_32_4m.npz) is for an eye 1.7 m above the 4 m cell centre (what
the astronaut sees; used for dose). Terrain shading needs the sky seen by the ground itself, at the scale of the boxwork
ridges (1-2 m high), so here the observer is 0.1 m above every 1 m corridor cell.

Per cell: horizon h(az) in 32 directions (phase4/horizon.horizon_angles, same ray march as the 4 m layer, to 2 km), and the
horizon the local plane alone would give, hp(az) = atan(max(0, uphill gradient along az)), gradient by central differences
on the 1 m DTM (as the page computes its terrain normals). The page's normals already darken plain slopes, so the stored
occlusion is the visible sky beyond the plane:
    ao = mean_az cos^2(max(h, hp)) / mean_az cos^2(hp)        (horizontal-surface cosine weighting, as sky_factors)
ao = 1 on a plane or a crest, < 1 in gullies, hollows and at the foot of ridges.
Corridor cell (i, j) is DTM pixel (col 336 + i, row 577 + j) (see demo/twin/walk.json: ox = 84, oy = 144.25 nav cells).
"""
import sys, os, json, time, base64, zlib
sys.path.insert(0, os.getcwd())
import numpy as np, rasterio
import marswalk_grid as g
from phase4.horizon import pick_device, horizon_angles, AZ_DEG

EYE = 0.1
walk = json.load(open("demo/twin/walk.json"))
CW, CH = walk["w"], walk["h"]
C0, R0 = int(round(4 * walk["ox"])), int(round(4 * walk["oy"] + 1.5 - 1.5))   # 336, 577
assert (C0, R0) == (336, 577), (C0, R0)
dtm = rasterio.open("data/processed/roi/elevation_m.tif").read(1).astype(np.float64)

jj, ii = np.mgrid[0:CH, 0:CW]
rows, cols = (R0 + jj).ravel().astype(np.float64), (C0 + ii).ravel().astype(np.float64)
t0 = time.time()
h, tr = horizon_angles(dtm, rows, cols, g.RES, eye=EYE, max_m=2000.0, chunk=12000,
                       device=pick_device(os.environ.get("MARSWALK_DEVICE", "auto")), verbose=False)
print(f"horizons for {len(rows)} cells in {time.time() - t0:.0f} s")
h = h.reshape(32, CH, CW)

# local plane: gradient on the (NaN-filled) DTM, central differences over +-1 pixel
d = dtm.copy()
if np.isnan(d).any():
    from scipy.ndimage import distance_transform_edt
    d = d[tuple(distance_transform_edt(np.isnan(d), return_distances=False, return_indices=True))]
sub = d[R0 - 1:R0 + CH + 1, C0 - 1:C0 + CW + 1]
gE = (sub[1:-1, 2:] - sub[1:-1, :-2]) / (2 * g.RES)          # dz/d(east)  (col +)
gN = -(sub[2:, 1:-1] - sub[:-2, 1:-1]) / (2 * g.RES)         # dz/d(north) (row -)
az = np.radians(AZ_DEG)[:, None, None]
hp = np.degrees(np.arctan(np.maximum(0.0, gE[None] * np.sin(az) + gN[None] * np.cos(az))))

c2 = lambda a: np.cos(np.radians(np.clip(a, 0, 90))) ** 2
sv_ground = c2(h).mean(0)
ao = (c2(np.maximum(h, hp)).mean(0) / c2(hp).mean(0)).clip(0, 1).astype(np.float32)
valid = np.isfinite(dtm[R0:R0 + CH, C0:C0 + CW])
print("ao: min %.3f  p1 %.3f  p5 %.3f  median %.3f  share<0.9 %.3f" % (ao.min(), *np.percentile(ao, [1, 5, 50]), (ao < 0.9).mean()))

meta = dict(method="ray march on the 1 m DTM (phase4/horizon.horizon_angles), 32 azimuths, 1..2000 m, observer 0.1 m above the "
                   "bilinear ground at each 1 m corridor pixel; ao = mean cos^2(max(h, plane)) / mean cos^2(plane), plane horizon from "
                   "central-difference gradients. Horizontal-surface cosine weighting.",
            eye_m=EYE, corridor_origin_dtm_colrow=[C0, R0], shape=[CH, CW], cell_m=g.RES,
            note="Ground-level occlusion beyond the local plane, for rendering. Not the astronaut's sky view (that is sky_view in "
                 "horizon_32_4m.npz, eye 1.7 m, used for dose). Rays leaving the ROI see no terrain, so ao is an upper bound there.")
out = "data/processed/roi/world/skyview_1m_corridor.npz"
np.savez_compressed(out, ao=ao, sky_view_ground=sv_ground.astype(np.float32), valid=valid,
                    trunc_frac=tr.reshape(32, CH, CW).mean(0).astype(np.float16), meta=json.dumps(meta))
g.register("world_ao_1m_corridor", path=out, layers=["ao", "sky_view_ground"], units="0-1", grid=f"1 m walk corridor {CW}x{CH}",
           source="elevation_m.tif (HiRISE 1 m DTM)", cls="derived", script="phase4/build_skyview_1m.py", note=meta["note"])

# page copy: code = round(ao * 254), 255 = no data; zlib + base64 (DecompressionStream("deflate") in the page)
q = np.where(valid, np.round(ao * 254), 255).astype(np.uint8)
blob = zlib.compress(q.tobytes(), 9)
json.dump({"w": CW, "h": CH, "scale": 1 / 254, "nodata": 255, "eye_m": EYE, "source": "phase4/build_skyview_1m.py",
           "note": meta["note"], "data": base64.b64encode(blob).decode()}, open("demo/twin/walk_ao.json", "w"))
print("saved", out, "and demo/twin/walk_ao.json", round(len(blob) / 1e6, 2), "MB compressed")
