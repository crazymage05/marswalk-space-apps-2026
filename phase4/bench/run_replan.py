"""Replanning experiment: D* Lite vs A* from scratch. The walker follows the planned route; when it reaches 25% of the route a
40 m diameter hazard disc (hard-blocked, centred on the route at 55%) appears. D* Lite updates its search (move + block + compute);
the baseline re-runs phase4/astar.py plan() from the walker's cell on the modified grid (NaN slope in the disc -> hard-blocked).
Scenarios: campaign + first 7 random scenarios of make_scenarios(seed 0). Each timing repeated 3x, median taken.
Usage: python phase4/bench/run_replan.py -> results/replan_results.json"""
import sys, os, json, time, statistics, math
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from phase4.bench.core import *
from phase4.bench import planners as P
from phase4 import scenarios as S

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")


def med(f, reps=3):
    ts = []; out = None
    for i in range(reps):
        t0 = time.perf_counter(); r = f(); ts.append((time.perf_counter() - t0) * 1000)
        if i == 0: out = r
    return out, statistics.median(ts)


def main():
    grid = C.load_grid(); prof = A.get_profile("nominal"); ctx = Ctx(grid, prof); W = ctx.W; cm = ctx.cm
    bi = independent_blocked(grid, prof)
    scs = S.make_scenarios(grid, prof, n=20, seed=0, include_campaign=True)[:8]
    rows = []
    for sc in scs:
        s, t = int(sc["start"]), int(sc["goal"])
        base = AS.plan(grid, s, t, prof, "astar"); route = base["route"]; n = len(route)
        cur = route[int(0.25 * (n - 1))]; hz = route[int(0.55 * (n - 1))]
        hr, hc = divmod(hz, W); R = 20.0 / cm; k = int(math.ceil(R)) + 1
        disc = [r * W + c for r in range(max(0, hr - k), min(ctx.H, hr + k + 1)) for c in range(max(0, hc - k), min(W, hc + k + 1))
                if math.hypot(r - hr, c - hc) * cm <= 20.0]
        disc = [c for c in disc if c not in (cur, t) and not ctx.bl[c]]
        on_route_before = sum(1 for c in route[int(0.25 * (n - 1)):] if c in set(disc))
        # D* Lite: initial search, then (move, block, compute) timed; repeated 3x from scratch
        init_ms, upd_ms, upd_exp, init_exp, ds_final = [], [], [], [], None
        for rep in range(3):
            t0 = time.perf_counter(); ds = P.DStarLite(ctx, s, t); ds.compute(); init_ms.append((time.perf_counter() - t0) * 1000)
            init_exp.append(ds.expanded); e0 = ds.expanded
            t0 = time.perf_counter(); ds.move_to(cur); ds.block_cells(disc); ds.compute(); upd_ms.append((time.perf_counter() - t0) * 1000)
            upd_exp.append(ds.expanded - e0); ds_final = ds
        new = ds_final.path(); dstar_cost = ds_final.g.get(cur, INF)
        # A* from scratch on the modified grid, from the walker's cell
        g2 = dict(grid); sl = grid["slope_max_deg"].copy()
        for c in disc: sl[divmod(c, W)] = np.nan
        g2["slope_max_deg"] = sl
        AS.plan(g2, cur, cur, prof, "astar")   # warm cache for the modified grid (excluded)
        r2, a_ms = med(lambda: AS.plan(g2, cur, t, prof, "astar"))
        full = route[:int(0.25 * (n - 1))] + new
        bi2 = bi.copy()
        for c in disc: bi2[divmod(c, W)] = True
        hard = check_path_hard(grid, prof, full, bi2)
        okv, failed = validate_path(ctx, full)
        rows.append(dict(scenario=sc["id"], route_cells=n, disc_cells=len(disc), route_cells_in_disc=on_route_before,
                         dstar_initial_ms=statistics.median(init_ms), dstar_initial_expanded=init_exp[0],
                         dstar_replan_ms=statistics.median(upd_ms), dstar_replan_expanded=upd_exp[0],
                         astar_scratch_ms=a_ms, astar_scratch_expanded=r2["expanded"],
                         dstar_cost=dstar_cost, astar_cost=r2["cost"], costs_equal=abs(dstar_cost - r2["cost"]) <= 1e-6 * r2["cost"],
                         detour_pct=100 * (dstar_cost / (base["cost"] * (1 - 0) ) - 1) if False else None,
                         new_path_hits_disc=int(any(c in set(disc) for c in new)), hard_block_samples=hard, validator_ok=okv,
                         validator_failed=failed, speedup=a_ms / statistics.median(upd_ms), expanded_ratio=r2["expanded"] / max(1, upd_exp[0])))
        print({k: (round(v, 2) if isinstance(v, float) else v) for k, v in rows[-1].items()}, flush=True)
    json.dump(rows, open(os.path.join(OUT, "replan_results.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
