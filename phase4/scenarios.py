"""
MARSWALK Phase 4 - start/goal scenarios on the 4 m grid.
Random pairs are drawn from the same connected component of the unblocked mask (4-connectivity, which is
exactly what the no-corner-cutting 8-connected planner can reach).
"""
import os
import numpy as np
from scipy import ndimage
try:
    from . import costs as C
except ImportError:
    import costs as C

WP_CSV = os.path.join(C.ROOT, "data", "processed", "roi", "tables", "waypoints_registered.csv")


def components(grid, profile, allow_unknown_rough=False):
    free = ~C.hard_blocked(grid, profile, allow_unknown_rough)
    lab, n = ndimage.label(free)
    return lab, n


def campaign_cells(grid, csv_path=None):
    """Campaign cells in sol order (consecutive duplicates removed). Registered 1 m pixels / 4 = cells."""
    import csv
    rows = []
    for r in csv.DictReader(open(csv_path or WP_CSV)):
        if r["campaign"] in ("True", "true", "1"):
            rows.append((int(r["sol"]), int(float(r["row_reg"]) // 4), int(float(r["col_reg"]) // 4)))
    rows.sort(key=lambda x: x[0])
    out = []
    for _, rr, cc in rows:
        if 0 <= rr < grid["height"] and 0 <= cc < grid["width"]:
            idx = rr * grid["width"] + cc
            if not out or out[-1] != idx: out.append(idx)
    return out


def campaign_scenario(grid, profile):
    cells = campaign_cells(grid)
    return dict(id="campaign", kind="campaign", start=cells[0], goal=cells[-1], via=cells,
                distance_km=_dist_km(grid, cells[0], cells[-1]))


def _dist_km(grid, a, b):
    W = grid["width"]; (ra, ca), (rb, cb) = divmod(a, W), divmod(b, W)
    return float(np.hypot(ra - rb, ca - cb) * grid["cell_m"] / 1000.0)


def make_scenarios(grid, profile, n=20, seed=0, min_km=0.5, max_km=2.0, include_campaign=False):
    """n random scenarios dict(id, kind, start, goal, distance_km) with straight-line separation in
    [min_km, max_km], both ends unblocked and connected. Optionally the campaign scenario first."""
    rng = np.random.default_rng(seed)
    lab, k = components(grid, profile)
    sizes = np.bincount(lab.ravel())[1:]
    comps = [i + 1 for i in np.argsort(sizes)[::-1] if sizes[i] >= 500]
    W, cm = grid["width"], grid["cell_m"]
    pools = {c: np.flatnonzero(lab.ravel() == c) for c in comps}
    w = np.array([len(pools[c]) for c in comps], float); w /= w.sum()
    out = [campaign_scenario(grid, profile)] if include_campaign else []
    tries = 0
    while len([s for s in out if s["kind"] == "random"]) < n and tries < 200000:
        tries += 1
        c = comps[rng.choice(len(comps), p=w)]
        a = int(rng.choice(pools[c])); b = int(rng.choice(pools[c]))
        d = _dist_km(grid, a, b)
        if min_km <= d <= max_km:
            out.append(dict(id=f"rand{len([s for s in out if s['kind']=='random']):02d}", kind="random", start=a, goal=b, distance_km=d))
    return out
