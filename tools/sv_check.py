"""W2 check: the occlusion factor the GPU applies equals the stored layers (independent source: the npz files).

usage: python tools/sv_check.py [port] [n]
Serve the page first: python -m http.server 8765 --bind 127.0.0.1 -d demo/twin
Opens the walk, switches the terrain shader to output its occlusion factor, and for n random points (fractional
positions inside 4 m cells: 2/3 in the 1 m corridor, 1/3 in the far field) puts a camera 5 m above the ground looking
straight down, renders once and reads the centre pixel. Reference: bilinear interpolation of sky_view between cell
centres: inside the 1 m corridor `ao` from data/processed/roi/world/skyview_1m_corridor.npz (1 m cells), outside it
`sky_view` from data/processed/roi/world/world_static_4m.npz (4 m cells). Writes runs/twin_check/sv_check/sv_check.json.
"""
import json, os, sys
import numpy as np
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
n = int(sys.argv[2]) if len(sys.argv) > 2 else 30
OUT = os.path.join(ROOT, "runs", "twin_check", "sv_check"); os.makedirs(OUT, exist_ok=True)
sv = np.load(os.path.join(ROOT, "data/processed/roi/world/world_static_4m.npz"))["sky_view"].astype(np.float64)
H, W = sv.shape
cell = json.load(open(os.path.join(ROOT, "demo/twin/data.json")))["grid"]["cell_m"]
walk = json.load(open(os.path.join(ROOT, "demo/twin/walk.json")))
ao = np.load(os.path.join(ROOT, "data/processed/roi/world/skyview_1m_corridor.npz"))["ao"].astype(np.float64)

def bilin(gx, gy, A=None):
    A = sv if A is None else A; h, w = A.shape
    x0, y0 = int(np.floor(gx)), int(np.floor(gy)); fx, fy = gx - x0, gy - y0
    g = lambda i, j: A[min(max(j, 0), h - 1), min(max(i, 0), w - 1)]
    return g(x0, y0) * (1 - fx) * (1 - fy) + g(x0 + 1, y0) * fx * (1 - fy) + g(x0, y0 + 1) * (1 - fx) * fy + g(x0 + 1, y0 + 1) * fx * fy

rng = np.random.default_rng(7)
cx0, cy0 = walk["ox"], walk["oy"]; cx1, cy1 = cx0 + walk["w"] / 4, cy0 + walk["h"] / 4   # corridor extent in nav cells
pts = []
while len(pts) < n:
    inside = len(pts) < 2 * n // 3
    gx = rng.uniform(cx0 + 3, cx1 - 3) if inside else rng.uniform(2, W - 3)
    gy = rng.uniform(cy0 + 3, cy1 - 3) if inside else rng.uniform(2, H - 3)
    if not inside and cx0 - 4 < gx < cx1 + 4 and cy0 - 4 < gy < cy1 + 4: continue
    pts.append((gx, gy, "corridor" if inside else "far"))
# add the 10 lowest-sky-view cells near the corridor (gullies) at their centres
sub = sv[int(cy0) + 3:int(cy1) - 3, int(cx0) + 3:int(cx1) - 3]
for k in np.argsort(sub, axis=None)[:10]:
    r, c = np.unravel_index(k, sub.shape); pts.append((c + int(cx0) + 3.0, r + int(cy0) + 3.0, "gully"))

for k in np.argsort(ao, axis=None)[:10]:
    j, i = np.unravel_index(k, ao.shape); pts.append((walk["ox"] + (i - 1.5) / 4, walk["oy"] + (j - 1.5) / 4, "ao_min"))
errors, rows = [], []
with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True, args=["--enable-gpu", "--ignore-gpu-blocklist", "--use-angle=metal"])
    pg = b.new_page(viewport={"width": 1000, "height": 800})
    pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.goto(f"http://127.0.0.1:{port}/twin.html")
    pg.wait_for_function("document.getElementById('loading').hidden===true", timeout=180000)
    pg.click("#btnDemo"); pg.wait_for_timeout(1000)
    pg.click("#btnWalk"); pg.wait_for_function("window.__walk.on===true", timeout=240000)
    pg.wait_for_function("document.getElementById('loading').hidden===true", timeout=240000)
    pg.wait_for_timeout(2000); pg.keyboard.press("Space")
    for gx, gy, kind in pts:
        x, z = (gx - (W - 1) / 2) * cell, (gy - (H - 1) / 2) * cell
        v = pg.evaluate(f"""() => {{ const K = window.__walk, r = K.renderer, c = K.cam, gl = r.getContext();
            const up = c.up.clone(), y = K.groundY({x}, {z}); K.svDebug.value = 1;
            c.up.set(0, 0, -1); c.position.set({x}, y + 5, {z}); c.lookAt({x}, y, {z}); c.updateMatrixWorld();
            r.render(K.scene, c); const w = gl.drawingBufferWidth, h = gl.drawingBufferHeight, px = new Uint8Array(4);
            gl.readPixels(w >> 1, h >> 1, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, px);
            K.svDebug.value = 0; c.up.copy(up); return [px[0], px[1], px[2], K.skyViewAt({int(round(gx))}, {int(round(gy))})]; }}""")
        ci, cj = (gx - walk["ox"]) * 4 + 1.5, (gy - walk["oy"]) * 4 + 1.5      # corridor 1 m cell coordinates
        inside = -0.5 < ci < walk["w"] - 0.5 and -0.5 < cj < walk["h"] - 0.5
        got, ref = v[0] / 255, (bilin(ci, cj, ao) if inside else bilin(gx, gy))
        rows.append({"gx": round(gx, 3), "gy": round(gy, 3), "kind": kind, "layer": "ao_1m" if inside else "sky_view_4m", "gpu": round(got, 4), "npz_bilinear": round(ref, 4),
                     "diff": round(got - ref, 4), "rgb_equal": v[0] == v[1] == v[2]})
    b.close()
d = np.array([r["diff"] for r in rows])
res = {"n": len(rows), "max_abs_diff": float(np.abs(d).max()), "mean_abs_diff": float(np.abs(d).mean()),
       "pass": bool(np.abs(d).max() < 0.01), "n_ao_1m": sum(r["layer"] == "ao_1m" for r in rows),
       "console_errors": errors, "rows": rows}
json.dump(res, open(os.path.join(OUT, "sv_check.json"), "w"), indent=1)
for r in rows: print(r)
print({k: v for k, v in res.items() if k != "rows"})
