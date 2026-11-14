"""Wired-in recommended planner vs the 8-neighbour reference on the 21 benchmark scenarios (20 random + campaign), nominal profile.
All paths measured with recommended.polyline_metrics; validated with safety_validator.validate_polyline.
Usage: python phase4/bench/run_recommended.py -> results/recommended_results.json"""
import sys, os, json, time, statistics
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from phase4 import costs as C, astronaut as A, scenarios as S, astar, recommended as R, safety_validator as SV

grid = C.load_grid(); prof = A.get_profile("nominal"); rows = []
R._edge_tables(grid, prof, False, 0.0); R._edge_tables(grid, prof, False, R.RISK_WEIGHT_DEFAULT)   # tables are cached: build outside timing
for sc in S.make_scenarios(grid, prof, n=20, seed=0, min_km=0.5, max_km=2.0, include_campaign=True):
    s, t = int(sc["start"]), int(sc["goal"])
    a8 = astar.plan(grid, s, t, prof); m8 = R.polyline_metrics(grid, a8["route"], prof)
    row = dict(scenario=sc["id"], a8_ms=a8["runtime_s"] * 1000, a8_len=m8["distance_m"], a8_time=m8["time_s"], a8_risk=m8["risk_m"])
    for tag, rw in (("rec0", 0.0), ("rec", R.RISK_WEIGHT_DEFAULT)):
        r = astar.plan(grid, s, t, prof, "astar16", smooth=True, risk_weight=rw)
        v = SV.validate_polyline(r["vertices"], grid, prof)
        row.update({f"{tag}_ms": r["runtime_s"] * 1000, f"{tag}_len": r["distance_m"], f"{tag}_time": r["time_s"], f"{tag}_risk": r["risk_m"],
                    f"{tag}_ok": v["ok"], f"{tag}_nv": len(r["vertices"]), f"{tag}_modelcost": r["model_cost"]})
    row["a8_modelcost"] = m8["model_cost"]; rows.append(row)
    print(sc["id"], f"len {row['a8_len']:.0f}->{row['rec_len']:.0f}  time {row['a8_time']:.0f}->{row['rec_time']:.0f}  risk {row['a8_risk']:.1f}->{row['rec_risk']:.1f}  ms {row['a8_ms']:.0f}->{row['rec_ms']:.0f}  ok {row['rec_ok']}", flush=True)
json.dump(rows, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "results", "recommended_results.json"), "w"), indent=1)
pc = lambda k, b: [(r[k] / r[b] - 1) * 100 for r in rows]
md = statistics.median
for tag in ("rec0", "rec"):
    print(tag, f"median len {md(pc(tag+'_len','a8_len')):+.2f}%  time {md(pc(tag+'_time','a8_time')):+.2f}%  risk {md(pc(tag+'_risk','a8_risk')):+.2f}%  "
          f"runtime x{md([r[tag+'_ms']/r['a8_ms'] for r in rows]):.2f}  valid {sum(r[tag+'_ok'] for r in rows)}/{len(rows)}  median vertices {md([r[tag+'_nv'] for r in rows])}")
print("median runtime ms: a8", round(md([r['a8_ms'] for r in rows])), "rec", round(md([r['rec_ms'] for r in rows])))
