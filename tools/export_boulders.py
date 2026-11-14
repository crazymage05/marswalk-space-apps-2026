"""Export the planning cells blocked by HiRISE-detected boulders: data/processed/roi/boulder_cells.json.

Same rule as the browser twin (demo/twin/twin.html, ROCK block): a planning cell is blocked when its centre is within
(d_m/2 + sqrt(0.5)*CELL + 0.3 m) of a boulder centre, the boulder's position in planning-cell coordinates being
fx = ox + (col - 337)/4, fy = oy + (row - 578)/4 (ox, oy from demo/twin/walk.json; col, row = rocks.json 1 m ROI grid).
Cell index = row*585 + col (nav_grid_4m). Run from the repo root: python tools/export_boulders.py
"""
import json, math, os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CELL, W, H, MARGIN_M = 4.046987178318, 585, 732, 0.3
OUT = os.path.join(ROOT, "data", "processed", "roi", "boulder_cells.json")

def compute():
    M = json.load(open(os.path.join(ROOT, "demo", "twin", "walk.json")))
    RJ = json.load(open(os.path.join(ROOT, "demo", "twin", "rocks.json")))
    cells = set()
    for rk in RJ["rocks"]:
        fx = M["ox"] + (rk["col"] - 337) / 4; fy = M["oy"] + (rk["row"] - 578) / 4
        R = (rk["d_m"] / 2 + math.sqrt(0.5) * CELL + MARGIN_M) / CELL; n = math.ceil(R)
        cx, cy = math.floor(fx + 0.5), math.floor(fy + 0.5)        # JS Math.round
        for dy in range(-n, n + 1):
            for dx in range(-n, n + 1):
                gx, gy = cx + dx, cy + dy
                if 0 <= gx < W and 0 <= gy < H and math.hypot(gx - fx, gy - fy) < R:
                    cells.add(gy * W + gx)
    return sorted(cells), RJ, M

if __name__ == "__main__":
    cells, RJ, M = compute()
    doc = dict(provenance=dict(
        source="demo/twin/rocks.json (HiRISE PSP_009149_1750 shadow-detected boulders)", n_rocks=len(RJ["rocks"]),
        method=RJ.get("method"), max_d_m=max(r["d_m"] for r in RJ["rocks"]),
        rule="cell blocked if hypot(cell - boulder) * CELL < d_m/2 + sqrt(0.5)*CELL + 0.3 m; boulder at fx = ox + (col-337)/4, fy = oy + (row-578)/4",
        constants=dict(CELL_m=CELL, W=W, H=H, margin_m=MARGIN_M, ox=M["ox"], oy=M["oy"], col0=337, row0=578, rock_grid_per_cell=4),
        index="cell = row*585 + col (nav_grid_4m)", tool="tools/export_boulders.py"),
        n_cells=len(cells), cells=cells)
    json.dump(doc, open(OUT, "w"))
    print("boulders:", len(RJ["rocks"]), "blocked cells:", len(cells))
