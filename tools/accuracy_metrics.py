"""
Accuracy numbers for MARSWALK, measured against independent evidence (for the slides and the submission).

  M1  Curiosity ground truth: the rover drove these cells, so they were passable. Share of its drive-path cells inside the
      twin that our walker rules mark walkable (and why the rest are blocked). Rover and suited walker differ, so this is
      a plausibility check of the terrain layers, not a test of the walker rules.
  M2  Terrain slope vs Curiosity's own tilt sensor at its stops: MAE, bias and correlation of the DTM slope (mean 1 m slope
      of the 4 m cell, and the plane slope over 3 x 3 cells ~ 12 m) against the rover tilt in the waypoint file.
  M3  Random-route stress test: N random walkable start/goal pairs 300-1500 m apart: route found, validator GO,
      length vs straight line, planner runtime.

    python tools/accuracy_metrics.py [--n 100] [--seed 0]
Writes data/processed/accuracy/metrics.json and prints a summary.
"""
import argparse, json, math, os, sys, time
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, ROOT)
from phase4 import costs, astar, astronaut as A, safety_validator as SV

ap = argparse.ArgumentParser(); ap.add_argument("--n", type=int, default=100); ap.add_argument("--seed", type=int, default=0)
args = ap.parse_args()
grid = costs.load_grid(); P = A.get_profile("nominal"); W, H, CM = grid["width"], grid["height"], grid["cell_m"]
blocked = costs.hard_blocked(grid, P); boulder = costs.boulder_blocked(grid)
D = json.load(open(os.path.join(ROOT, "demo/twin/data.json")))
cell = lambda x, y: int(round(y)) * W + int(round(x))
out = {"grid": {"w": W, "h": H, "cell_m": CM}, "profile": {"max_slope_deg": P.max_slope_deg, "rough_max_m": P.rough_max_m}}

# ---- M1: Curiosity's drive path through the twin area
cells = set()
for seg in D["paths"]:
    for (x0, y0), (x1, y1) in zip(seg[:-1], seg[1:]):
        n = max(1, int(math.ceil(4 * math.hypot(x1 - x0, y1 - y0))))
        for k in range(n + 1):
            x, y = x0 + (x1 - x0) * k / n, y0 + (y1 - y0) * k / n
            if 0 <= x < W - 0.5 and 0 <= y < H - 0.5: cells.add(cell(x, y))
cells = np.array(sorted(cells)); r, c = cells // W, cells % W
sl, ro, vf = grid["slope_max_deg"][r, c], grid["rough_max_m"][r, c], grid["valid_frac"][r, c]
with np.errstate(invalid="ignore"):
    why = {"slope_over_limit": int(np.sum(sl > P.max_slope_deg)), "rough_over_limit": int(np.sum(ro > P.rough_max_m)),
           "boulder_footprint": int(np.sum(boulder[r, c])), "low_data_or_unknown": int(np.sum((vf < P.valid_frac_min) | np.isnan(sl) | np.isnan(ro)))}
walk = ~blocked[r, c]
out["M1_curiosity_path"] = {"cells": int(len(cells)), "walkable": int(walk.sum()), "walkable_pct": round(100 * walk.mean(), 1),
                            "blocked_by": why, "slope_max_deg_on_path": {"median": round(float(np.nanmedian(sl)), 1), "p95": round(float(np.nanpercentile(sl, 95)), 1)}}

# ---- M2: DTM slope vs Curiosity tilt at its stops
z = grid["elevation_m"]; rows = []
for w in D["waypoints"]:
    if w.get("tilt") is None: continue
    x, y = w["x"], w["y"]
    if not (1 <= x < W - 2 and 1 <= y < H - 2): continue
    rr, cc = int(round(y)), int(round(x)); patch = z[rr - 1:rr + 2, cc - 1:cc + 2]
    if np.isnan(patch).any(): continue
    gy, gx = np.gradient(patch, CM)                          # plane slope over 3 x 3 cells (~12 m), close to the rover's footprint scale
    plane = math.degrees(math.atan(math.hypot(gx[1, 1], gy[1, 1])))
    rows.append((float(w["tilt"]), float(grid["slope_mean_deg"][rr, cc]), plane, w["sol"]))
if rows:
    t, m1, p3 = (np.array([q[i] for q in rows]) for i in range(3))
    stat = lambda a: {"mae_deg": round(float(np.mean(np.abs(a - t))), 2), "bias_deg": round(float(np.mean(a - t)), 2), "r": round(float(np.corrcoef(a, t)[0, 1]), 3)}
    out["M2_slope_vs_rover_tilt"] = {"stops": len(rows), "sols": [min(q[3] for q in rows), max(q[3] for q in rows)],
                                     "tilt_median_deg": round(float(np.median(t)), 1),
                                     "cell_mean_1m_slope": stat(m1), "plane_slope_3x3_cells": stat(p3)}

# ---- M3: random routes
rng = np.random.default_rng(args.seed); free = np.flatnonzero(~blocked.ravel()); res = []
while len(res) < args.n:
    a, b = rng.choice(free, 2)
    d = CM * math.hypot(a // W - b // W, a % W - b % W)
    if not 300 <= d <= 1500: continue
    t0 = time.perf_counter(); p = astar.plan(grid, int(a), int(b), P); dt = time.perf_counter() - t0
    if not p["success"]: res.append({"found": False, "straight_m": d}); continue
    v = SV.validate(p["route"], grid, P)
    res.append({"found": True, "go": bool(v["ok"]), "rules": sorted({x["rule"] for x in v["violations"]}), "straight_m": d,
                "route_m": p["distance_m"], "ratio": p["distance_m"] / d, "runtime_s": dt, "boulder_cells": int(boulder.ravel()[p["route"]].sum())})
fd = [q for q in res if q["found"]]; ratio = np.array([q["ratio"] for q in fd]); rt = np.array([q["runtime_s"] for q in fd])
spatial = {"CS-01", "CS-02", "CS-03", "CS-04"}
out["M3_random_routes"] = {"pairs": len(res), "found": len(fd), "found_pct": round(100 * len(fd) / len(res), 1),
                           "spatial_rules_pass_pct": round(100 * np.mean([not (set(q["rules"]) & spatial) for q in fd]), 1),
                           "full_go_pct": round(100 * np.mean([q["go"] for q in fd]), 1),
                           "failed_rules_seen": sorted({x for q in fd for x in q["rules"]}),
                           "boulder_cells_entered": int(sum(q["boulder_cells"] for q in fd)),
                           "length_vs_straight": {"median": round(float(np.median(ratio)), 3), "p90": round(float(np.percentile(ratio, 90)), 3), "max": round(float(ratio.max()), 3)},
                           "runtime_s": {"median": round(float(np.median(rt)), 3), "p90": round(float(np.percentile(rt, 90)), 3)},
                           "seed": args.seed, "distance_band_m": [300, 1500]}
os.makedirs(os.path.join(ROOT, "data/processed/accuracy"), exist_ok=True)
json.dump(out, open(os.path.join(ROOT, "data/processed/accuracy/metrics.json"), "w"), indent=1)
print(json.dumps(out, indent=1))
