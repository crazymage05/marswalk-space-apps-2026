"""Main benchmark: campaign scenario + 20 random scenarios (make_scenarios seed 0, 0.5-2 km), nominal profile, CPU, single thread.
Protocol: each planner is run REPS=3 times per scenario; runtime = median of the 3; the route is from run 1 (all deterministic).
Usage: python phase4/bench/run_bench.py [--reps 3] [--n 20]      -> phase4/bench/results/bench_results.json (resumable)"""
import sys, os, json, time, platform, argparse, statistics
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from phase4.bench.core import *
from phase4.bench import planners as P
from phase4 import scenarios as S

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results"); os.makedirs(OUT, exist_ok=True)
RES = os.path.join(OUT, "bench_results.json")
ALGOS = ["astar8", "astar16", "lazy_theta", "astar8_smooth"]


def timed(fn, reps):
    ts = []; out = None
    for i in range(reps):
        t0 = time.perf_counter(); r = fn(); ts.append((time.perf_counter() - t0) * 1000)
        if i == 0: out = r
    return out, statistics.median(ts), ts


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--reps", type=int, default=3); ap.add_argument("--n", type=int, default=20)
    a = ap.parse_args()
    grid = C.load_grid(); prof = A.get_profile("nominal"); ctx = Ctx(grid, prof)
    bi = independent_blocked(grid, prof)
    assert (bi == ctx.blocked).all(), "independent mask != costs.hard_blocked"
    scs = S.make_scenarios(grid, prof, n=a.n, seed=0, min_km=0.5, max_km=2.0, include_campaign=True)
    t0 = time.perf_counter(); t16 = P.edge_tables(ctx, P.N16); build_ms = (time.perf_counter() - t0) * 1000
    print(f"16-neighbour edge tables built once in {build_ms:.0f} ms; blocked fraction {ctx.blocked.mean():.3f}", flush=True)
    AS.plan(grid, scs[0]["start"], scs[0]["start"], prof, "astar")   # warm the astar.py cache (excluded from timing)
    done = json.load(open(RES)) if os.path.exists(RES) else dict(rows=[])
    have = {(r["scenario"], r["algo"]) for r in done["rows"]}
    done["meta"] = dict(reps=a.reps, python=platform.python_version(), platform=platform.platform(), processor=platform.processor(),
                        cpu_count=os.cpu_count(), table_build_ms=build_ms, blocked_frac=float(ctx.blocked.mean()), cell_m=ctx.cm,
                        grid=[ctx.H, ctx.W], profile="nominal", n_random=a.n, seed=0)
    for sc in scs:
        s, t = int(sc["start"]), int(sc["goal"])
        runs = {
            "astar8": lambda: AS.plan(grid, s, t, prof, "astar"),
            "astar16": lambda: P.grid_astar(ctx, t16, P.N16, s, t, "euclid"),
            "lazy_theta": lambda: P.lazy_theta(ctx, s, t),
        }
        base_ms = None; base_route = None
        for name in ["astar8", "astar16", "lazy_theta", "astar8_smooth"]:
            if (sc["id"], name) in have: continue
            if name == "astar8_smooth":
                if base_route is None:
                    r0 = AS.plan(grid, s, t, prof, "astar"); base_route = r0["route"]; base_ms = None
                    base_ms = next((r["runtime_ms"] for r in done["rows"] if r["scenario"] == sc["id"] and r["algo"] == "astar8"), None)
                    base_exp = r0["expanded"]
                route, ms, ts = timed(lambda: P.smooth_path(ctx, base_route), a.reps)
                ms += base_ms; ts = [x + base_ms for x in ts]; exp = base_exp; cost_plan = None; verts = route
            else:
                r, ms, ts = timed(runs[name], a.reps)
                verts = r["route"]; exp = r["expanded"]; cost_plan = r["cost"]
                if name == "astar8": base_route = verts; base_exp = exp
            if name == "astar8": base_ms = ms
            m = path_metrics(ctx, verts)
            okv, failed = validate_path(ctx, verts)
            hard = check_path_hard(grid, prof, verts, bi)
            row = dict(scenario=sc["id"], kind=sc["kind"], straight_km=sc["distance_km"], algo=name, runtime_ms=ms, runtime_reps_ms=ts,
                       expanded=exp, planner_cost=cost_plan, validator_ok=okv, validator_failed=failed, hard_block_samples=hard,
                       vertices=verts, **m)
            done["rows"].append(row)
            print(f"{sc['id']:9s} {name:14s} len {m['length_m']:8.1f} cost {m['cost']:9.1f} t {ms:9.1f} ms exp {exp:7d} turns>30 {m['turns_gt30']:3d} val {okv} hard {hard}", flush=True)
            json.dump(done, open(RES, "w"))


if __name__ == "__main__":
    main()
