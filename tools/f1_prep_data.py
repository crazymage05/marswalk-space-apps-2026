#!/usr/bin/env python3
"""F1 step 1 (normal Python, needs rasterio): crop DTM + ortho, write film/f1_data/* for the Blender step.
Run from the repo root:  python tools/f1_prep_data.py"""
import base64, json, os, sys
import numpy as np, rasterio
from rasterio.windows import Window
from PIL import Image
Image.MAX_IMAGE_PIXELS = None
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); os.chdir(ROOT); sys.path.insert(0, ROOT)
# Optional route mode (tools/render_route.py): F1_ROUTE_FILE = film/routes/<name>/route.json, F1_OUT = its own data folder.
# Without F1_ROUTE_FILE nothing below changes and film/f1_data is written exactly as before.
RF = os.environ.get("F1_ROUTE_FILE"); RJ = json.load(open(RF)) if RF else None
R = "data/processed/roi"; OUT = os.environ.get("F1_OUT", "film/f1_data"); os.makedirs(OUT, exist_ok=True)
X0, Y0, S = -2371.534486494449, -283331.60, 1.0117467945795          # grid metres of the ROI top-left corner, pixel size
# exact origin from the file
with rasterio.open(f"{R}/elevation_m.tif") as r:
    X0, Y0, S = r.transform.c, r.transform.f, r.transform.a
C0, C1, R0, R1 = 336, 1344, 577, 1879                                  # walk corridor window (1 m pixels)
if RJ: C0, C1, R0, R1 = RJ["film"]["window_1m"]                        # route mode: window around the route (set by render_route.py)
Z0 = -3650.0                                                           # Blender z = elevation - Z0
E0, N0 = X0 + S * (C0 + C1) / 2, Y0 - S * (R0 + R1) / 2               # Blender origin = window centre
def px2en(col, row): return X0 + S * col, Y0 - S * row                 # edge coordinates -> east, north (grid m)

def tint(a, rng=None):                                                 # same warm tint as build_walk.py
    a = a.astype(np.float32); v = a[a > 0]; lo, hi = rng if rng else np.percentile(v, [0.5, 99.6])
    a = np.clip((a - lo) / (hi - lo), 0, 1)
    return np.stack([46 + a * 209, 26 + a * 178, 14 + a * 128], -1).clip(0, 255).astype(np.uint8)

with rasterio.open(f"{R}/elevation_m.tif") as r:
    z = r.read(1, window=Window(C0, R0, C1 - C0, R1 - R0)).astype(np.float32)
    zfull = r.read(1).astype(np.float32)
z = np.where(np.isfinite(z), z, np.nanmean(z)); zfull = np.where(np.isfinite(zfull), zfull, np.nanmean(zfull))
np.save(f"{OUT}/corridor_z.npy", z - Z0)
with rasterio.open(f"{R}/ortho_025m.tif") as o:
    a = o.read(1, window=Window(C0 * 4, R0 * 4, (C1 - C0) * 4, (R1 - R0) * 4))
    trng = None
    if RJ:                                                             # route mode: keep the film's brightness stretch (percentiles of the default window)
        v = o.read(1, window=Window(336 * 4, 577 * 4, (1344 - 336) * 4, (1879 - 577) * 4)).astype(np.float32); v = v[v > 0]
        trng = tuple(np.percentile(v, [0.5, 99.6])); del v
Image.fromarray(tint(a, trng)).save(f"{OUT}/corridor_tex.jpg", quality=92); print("corridor tex", a.shape)
# context: whole ROI, every 4th DTM pixel, 1 m ortho
step = 4
np.save(f"{OUT}/context_z.npy", (zfull[::step, ::step] - Z0).astype(np.float32))
with rasterio.open(f"{R}/ortho_1m.tif") as o: a = o.read(1)
Image.fromarray(tint(a)).save(f"{OUT}/context_tex.jpg", quality=90)


# ---- F2 look data: ground-type weights (blurred one-hot, 1 m pixels over the corridor), Navcam-texture means, rocks
from PIL import ImageFilter
TW = "demo/twin/tex"; tj = json.load(open(f"{TW}/textures.json"))
mj = json.load(open("demo/twin/material_4m.json"))
codes = np.frombuffer(base64.b64decode(mj["data"]), np.uint8).reshape(mj["height"], mj["width"])
if not RJ: assert mj["origin_col_1m"] == C0 and mj["origin_row_1m"] == R0, "material map origin differs from the corridor window"
k = mj["cells_1m"]; one = np.stack([(codes == i) for i in range(3)], -1).astype(np.float32)           # bedrock, sand, pebbly
one = np.repeat(np.repeat(one, k, 0), k, 1)                                                           # 1 m pixels
ny_c, nx_c = R1 - R0, C1 - C0
if RJ:   # route mode: the ground-type map covers one block of the ROI; outside it the three types are weighted equally (no data)
    cv = np.full((ny_c, nx_c, 3), 1 / 3, np.float32); oy, ox = mj["origin_row_1m"] - R0, mj["origin_col_1m"] - C0
    ya, xa = max(0, oy), max(0, ox); yb, xb = min(ny_c, oy + one.shape[0]), min(nx_c, ox + one.shape[1])
    if yb > ya and xb > xa: cv[ya:yb, xa:xb] = one[ya - oy:yb - oy, xa - ox:xb - ox]
    one = cv
else:
    one = np.pad(one, ((0, max(0, ny_c - one.shape[0])), (0, max(0, nx_c - one.shape[1])), (0, 0)), mode="edge")[:ny_c, :nx_c]
ch = [np.asarray(Image.fromarray((one[..., i] * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(5)), np.float32) + 1e-3 for i in range(3)]
wsum = sum(ch); wimg = np.stack([c / wsum for c in ch], -1)
Image.fromarray((wimg * 255 + 0.5).astype(np.uint8)).save(f"{OUT}/ground_weights.png"); np.save(f"{OUT}/ground_weights.npy", wimg.astype(np.float32))
print("ground-type share (bedrock, sand, pebbly):", wimg.reshape(-1, 3).mean(0).round(3))
texinfo = {}
for t in tj["textures"]:
    d = {"tile_m": t["tile_m"]}
    for kind in ("albedo", "normal", "rough"):
        fn = os.path.abspath(f"{TW}/{t['type']}_{kind}.jpg"); d[kind] = fn
        if kind == "albedo":
            d["mean"] = [float(x) for x in np.mean(np.power(np.asarray(Image.open(fn).convert("RGB"), np.float32) / 255, 2.2), (0, 1))]
    d["mtime"] = max(os.path.getmtime(d[x]) for x in ("albedo", "normal", "rough")); texinfo[t["type"]] = d
rocks = [{"col": r["col"], "row": r["row"], "d": r["d_m"], "h": r["h_m"]} for r in json.load(open("demo/twin/rocks.json"))["rocks"]]
if RJ: rocks = [r for r in rocks if C0 + 3 <= r["col"] < C1 - 3 and R0 + 3 <= r["row"] < R1 - 3]     # route mode: only rocks inside the window

# routes
rt = {x["id"]: x for x in json.load(open(f"{R}/routes_astar.json"))["routes"]}
def route_xy(rid):
    c = np.array(rt[rid]["route"]); col, row = c % 585, c // 585
    return [[X0 + S * (4 * cc + 1.5) - E0, Y0 - S * (4 * rr + 1.5) - N0] for cc, rr in zip(col, row)]
if RJ:   # route mode: the walked route is the planned cells from the twin; the red straight line and the no-go rings belong to the film story only
    cxy = lambda c: [X0 + S * (4 * (c % 585) + 1.5) - E0, Y0 - S * (4 * (c // 585) + 1.5) - N0]
    rt_cells = RJ["cells"]; route_xy = lambda rid: [cxy(c) for c in rt_cells]
    straight_xy = [cxy(rt_cells[0]), cxy(rt_cells[-1])]; nogo_xy = []; nogo_slopes = []
else:
    # v3 story: the walker follows MARSWALK's shortest safe route; the straight line start->goal is shown as rejected,
    # with the 4 m cells where it breaks the walker's 25 deg slope rule (phase4.safety_validator, CS-01) marked.
    from phase4 import costs as _costs, astronaut as _A, safety_validator as _SV
    _g = _costs.load_grid(); _W = _g["width"]
    _s, _t = rt["campaign"]["start_cell"], rt["campaign"]["goal_cell"]; (_r0, _c0), (_r1, _c1) = divmod(_s, _W), divmod(_t, _W)
    _cells = []
    for _u in np.linspace(0, 1, 4 * int(max(abs(_r1 - _r0), abs(_c1 - _c0))) + 2):
        _c = int(round(_r0 + (_r1 - _r0) * _u)) * _W + int(round(_c0 + (_c1 - _c0) * _u))
        if not _cells or _cells[-1] != _c: _cells.append(_c)
    _v = _SV.validate(_cells, _g, _A.get_profile("nominal"))
    _bad = sorted({x["cell"] for x in _v["violations"] if x["rule"] == "CS-01"})
    cxy = lambda c: [X0 + S * (4 * (c % 585) + 1.5) - E0, Y0 - S * (4 * (c // 585) + 1.5) - N0]
    straight_xy = [cxy(_s), cxy(_t)]; nogo_xy = [cxy(c) for c in _bad]
    nogo_slopes = [float(_g["slope_max_deg"][divmod(c, _W)]) for c in _bad]
    print("straight line: validator ok", _v["ok"], "| CS-01 cells", len(_bad), "max slope", max(nogo_slopes) if nogo_slopes else None)
# sun
from phase4.world import World
w = World.load(); sun = {}
for l in (9, 16):
    d = w.dynamic(RJ["sol"] if RJ else 4600, l); sun[f"lmst{l}"] = {"el": d["sun_el"], "az": d["sun_az"], "ls": d["ls"], "utc": d["utc_date"]}
meshes = []
for m in json.load(open("demo/twin/meshes/meshes.json"))["meshes"]:
    if RJ and not (C0 + m.get("radius_m", 25.0) <= (m["anchor_x_m"] - X0) / S <= C1 - m.get("radius_m", 25.0) and R0 + m.get("radius_m", 25.0) <= (Y0 - m["anchor_y_m"]) / S <= R1 - m.get("radius_m", 25.0)): continue   # route mode: scans fully inside the window only
    meshes.append({"file": m["file"], "sol": m["sol"], "e": m["anchor_x_m"] - E0, "n": m["anchor_y_m"] - N0, "z": m["anchor_elev_m"] - Z0, "radius": m.get("radius_m", 25.0)})
mp = os.path.join("demo/twin/models", "markIII_suit_walk.glb")
suit = mp if os.path.exists(mp) else "demo/twin/models/markIII_suit_plain.glb"
SJ = ({"E0": E0, "N0": N0, "Z0": Z0, "S": S, "corr": {"nx": C1 - C0, "ny": R1 - R0, "size_m": [(C1 - C0) * S, (R1 - R0) * S]},
           "ctx": {"step": step, "nx": zfull[::step, ::step].shape[1], "ny": zfull[::step, ::step].shape[0], "x0": X0 - E0, "y0": Y0 - N0, "px": S * step},
           "route_approved": route_xy("campaign"), "route_direct": straight_xy, "nogo": nogo_xy, "nogo_slopes": nogo_slopes,
           "route_note": "approved = MARSWALK A* route 'campaign' (shortest safe); direct = straight line start->goal, NO-GO (CS-01)", "sun": sun, "meshes": meshes,
           "suit": os.path.abspath(suit), "tex": texinfo, "rocks": rocks, "C0": C0, "R0": R0, "walk_glb": suit.endswith("walk.glb"), "corr_x0": X0 + S * C0 - E0, "corr_y0": Y0 - S * R0 - N0})
if RJ: SJ["film"] = RJ["film"]                                          # tells f1_blender_scene.py to build the route-mode shots
json.dump(SJ, open(f"{OUT}/scene.json", "w"))
print("suit:", suit, "sun:", sun, "E0,N0", E0, N0)
