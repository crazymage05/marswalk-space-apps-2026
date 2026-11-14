"""16-connected A* followed by string pulling, on the same 21 scenarios as run_bench.py, compared pairwise
with the stored 8-connected A* and 8-connected A* + string pulling rows.
Usage: python phase4/bench/run_combo.py   -> phase4/bench/results/combo_results.json"""
import sys, os, json, time, statistics
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from phase4.bench.core import *
from phase4.bench import planners as P
from phase4 import scenarios as S

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
base = json.load(open(os.path.join(OUT, "bench_results.json")))["rows"]
ref = {(r["scenario"], r["algo"]): r for r in base}
grid = C.load_grid(); prof = A.get_profile("nominal"); ctx = Ctx(grid, prof); bi = independent_blocked(grid, prof)
t16 = P.edge_tables(ctx, P.N16)
rows = []
for sc in S.make_scenarios(grid, prof, n=20, seed=0, min_km=0.5, max_km=2.0, include_campaign=True):
    s, t = int(sc["start"]), int(sc["goal"])
    ts = []
    for _ in range(3):
        t0 = time.perf_counter(); r = P.grid_astar(ctx, t16, P.N16, s, t, "euclid"); v = P.smooth_path(ctx, r["route"]); ts.append((time.perf_counter() - t0) * 1000)
    m = path_metrics(ctx, v); ok, failed = validate_path(ctx, v); hard = check_path_hard(grid, prof, v, bi)
    a8, a8s = ref[(sc["id"], "astar8")], ref[(sc["id"], "astar8_smooth")]
    rows.append(dict(scenario=sc["id"], runtime_ms=statistics.median(ts), validator_ok=ok, hard_block_samples=hard, **m,
                     d_len_vs_a8=(m["length_m"] / a8["length_m"] - 1) * 100, d_time_vs_a8=(m["time_s"] / a8["time_s"] - 1) * 100,
                     d_len_vs_a8s=(m["length_m"] / a8s["length_m"] - 1) * 100, rt_ratio_vs_a8=statistics.median(ts) / a8["runtime_ms"]))
    x = rows[-1]; print(f"{x['scenario']:9s} len {x['length_m']:7.1f}  vs A*8 {x['d_len_vs_a8']:+5.1f}%  vs A*8+pull {x['d_len_vs_a8s']:+5.1f}%  turns>30 {x['turns_gt30']:2d}  val {ok} hard {hard}  {x['runtime_ms']:.0f} ms", flush=True)
json.dump(rows, open(os.path.join(OUT, "combo_results.json"), "w"), indent=1)
med = lambda k: statistics.median(r[k] for r in rows)
print(f"\nmedian: length vs A*8 {med('d_len_vs_a8'):+.2f}%, time vs A*8 {med('d_time_vs_a8'):+.2f}%, length vs A*8+pull {med('d_len_vs_a8s'):+.2f}%, "
      f"runtime x{med('rt_ratio_vs_a8'):.2f}, turns>30 median {med('turns_gt30')}, validator {sum(r['validator_ok'] for r in rows)}/{len(rows)}, "
      f"hard-block samples {sum(r['hard_block_samples'] for r in rows)}")
