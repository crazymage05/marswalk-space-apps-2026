"""Correctness checks on small synthetic grids (known optimum) run BEFORE any comparison.
Run:  python phase4/bench/tests_synth.py   (writes phase4/bench/results/synthetic_checks.json)"""
import sys, os, json, math, random
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import dijkstra as sp_dijkstra
from phase4.bench.core import *
from phase4.bench import planners as P

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")


def synth(seed, H=45, W=55, block_frac=0.18, uniform=False):
    rng = np.random.default_rng(seed)
    z = ndimage.gaussian_filter(rng.normal(0, 1, (H, W)), 4) * 12
    sl = np.degrees(np.arctan(np.hypot(*np.gradient(z, 4.0)))) * 1.0
    rough = ndimage.gaussian_filter(rng.random((H, W)), 2); rough = (rough - rough.min()) / np.ptp(rough) * 0.5
    blob = ndimage.gaussian_filter(rng.normal(0, 1, (H, W)), 2.5); thr = np.quantile(blob, 1 - block_frac)
    sl = np.where(blob > thr, 40.0, np.minimum(sl, 20.0))
    vf = np.ones((H, W)) - 0.3 * ndimage.gaussian_filter(rng.random((H, W)), 3) / 0.3 * 0.5
    g = dict(elevation_m=z, slope_max_deg=sl, slope_mean_deg=sl * 0.6, rough_max_m=rough * 0.6, valid_frac=np.clip(vf, 0.6, 1),
             loose=rng.random((H, W)), height=H, width=W, cell_m=4.047)
    if uniform:
        g["elevation_m"] = np.zeros((H, W)); g["slope_max_deg"] = np.where(blob > thr, 40.0, 0.0)
        g["slope_mean_deg"] = np.zeros((H, W)); g["rough_max_m"] = np.zeros((H, W)); g["valid_frac"] = np.ones((H, W))
        g["loose"] = np.zeros((H, W))
    return g


def ref_dijkstra(ctx, tables, offsets, s, t):
    """Independent optimum: scipy sparse Dijkstra over the same edge tables."""
    N = ctx.H * ctx.W; rows = []; cols = []; w = []
    for (dr, dc), tab in zip(offsets, tables):
        a = np.frombuffer(tab, dtype=np.float64).copy() if not isinstance(tab, np.ndarray) else tab
        idx = np.flatnonzero(np.isfinite(a)); rr, cc = np.divmod(idx, ctx.W)
        ok = (rr + dr >= 0) & (rr + dr < ctx.H) & (cc + dc >= 0) & (cc + dc < ctx.W)
        idx = idx[ok]; rows.append(idx); cols.append(idx + dr * ctx.W + dc); w.append(a[idx])
    M = coo_matrix((np.concatenate(w), (np.concatenate(rows), np.concatenate(cols))), shape=(N, N)).tocsr()
    return sp_dijkstra(M, indices=s)[t]


def main():
    prof = A.get_profile("nominal"); res = dict(checks=[]); fails = 0
    def ok(name, cond, detail=""):
        nonlocal fails
        res["checks"].append(dict(name=name, ok=bool(cond), detail=str(detail)))
        if not cond: fails += 1
        print(("PASS " if cond else "FAIL ") + name, detail)
    n_sc = 0; viol = dict(astar_dij=0, mine8=0, ref=0, a16le8=0, a16ref=0, theta_len=0, theta_u_len=0, smooth=0, hard=0, dstar=0, theta_cost=0)
    stats = dict(theta_cost_ratio=[], theta_len_ratio=[])
    rng = random.Random(0)
    for seed in range(12):
        uniform = seed % 3 == 0
        g = synth(seed, uniform=uniform); ctx = Ctx(g, prof)
        free = np.flatnonzero(~ctx.blocked.ravel())
        lab, _ = ndimage.label(~ctx.blocked); labf = lab.ravel()
        t8 = P.edge_tables(ctx, P.N8); t16 = P.edge_tables(ctx, P.N16)
        bi = independent_blocked(g, prof)
        assert (bi == ctx.blocked).all(), "independent blocked mask differs from costs.hard_blocked"
        for k in range(4):
            for _try in range(200):
                s, t = rng.choice(list(free)), rng.choice(list(free))
                if labf[s] == labf[t] and math.hypot(*[a - b for a, b in zip(divmod(s, ctx.W), divmod(t, ctx.W))]) > 15: break
            else: continue
            n_sc += 1; s, t = int(s), int(t); ctx = Ctx(g, prof); t8 = P.edge_tables(ctx, P.N8); t16 = P.edge_tables(ctx, P.N16)
            base = AS.plan(g, s, t, prof, "astar"); dij = AS.plan(g, s, t, prof, "dijkstra")
            if abs(base["cost"] - dij["cost"]) > 1e-6 * dij["cost"]: viol["astar_dij"] += 1
            mine8 = P.grid_astar(ctx, t8, P.N8, s, t, "octile");
            if abs(mine8["cost"] - base["cost"]) > 1e-6 * base["cost"]: viol["mine8"] += 1
            ref8 = ref_dijkstra(ctx, t8, P.N8, s, t)
            if abs(ref8 - base["cost"]) > 1e-6 * ref8: viol["ref"] += 1
            a16 = P.grid_astar(ctx, t16, P.N16, s, t, "euclid"); ref16 = ref_dijkstra(ctx, t16, P.N16, s, t)
            if abs(a16["cost"] - ref16) > 1e-6 * ref16: viol["a16ref"] += 1
            if a16["cost"] > base["cost"] * (1 + 1e-9): viol["a16le8"] += 1
            th = P.lazy_theta(ctx, s, t); sm = P.smooth_path(ctx, base["route"])
            m8 = path_metrics(ctx, base["route"]); mt = path_metrics(ctx, th["route"]); ms = path_metrics(ctx, sm)
            if uniform:
                if mt["planar_m"] > m8["planar_m"] * (1 + 1e-9): viol["theta_u_len"] += 1
            stats["theta_len_ratio"].append(mt["planar_m"] / m8["planar_m"]); stats["theta_cost_ratio"].append(mt["cost"] / m8["cost"])
            if mt["cost"] > m8["cost"] * (1 + 1e-9): viol["theta_cost"] += 1
            if ms["cost"] > m8["cost"] * (1 + 1e-9): viol["smooth"] += 1
            for r in (base["route"], a16["route"], th["route"], sm):
                if check_path_hard(g, prof, r, bi) > 0: viol["hard"] += 1
            # D* Lite: initial plan, then 3 rounds of (move along path, block a random disc ahead, replan) vs A* from scratch
            ds = P.DStarLite(ctx, s, t); ds.compute(); route = ds.path()
            if abs(ds.g[s] - base["cost"]) > 1e-6 * base["cost"]: viol["dstar"] += 1
            cur = s
            for rnd in range(3):
                route = ds.path()
                if len(route) < 8: break
                i = len(route) // 4; cur = route[i]; ds.move_to(cur)
                j = min(len(route) - 2, i + max(3, len(route) // 4)); cr, cc = divmod(route[j], ctx.W)
                cells = [r * ctx.W + c for r in range(max(0, cr - 2), min(ctx.H, cr + 3)) for c in range(max(0, cc - 2), min(ctx.W, cc + 3))
                         if (r - cr) ** 2 + (c - cc) ** 2 <= 5 and r * ctx.W + c not in (cur, t)]
                ds.block_cells(cells); ds.compute()
                bl2 = ctx.blocked.copy();
                for c in cells: bl2[divmod(c, ctx.W)] = True
                ctx2 = Ctx(g, prof, blocked=bl2, mult=ctx.mult)
                t8b = P.edge_tables(ctx2, P.N8); ref = P.grid_astar(ctx2, t8b, P.N8, cur, t, "octile")
                gs = ds.g.get(cur, INF)
                if not (gs == ref["cost"] or abs(gs - ref["cost"]) <= 1e-6 * ref["cost"]): viol["dstar"] += 1; print("DSTAR MISMATCH seed", seed, "round", rnd, gs, ref["cost"])
                ctx.bl = bl2.ravel().tolist(); ctx.blocked = bl2   # keep ctx consistent with the disc for later rounds
                t8 = t8b
    ok("synthetic scenarios run", n_sc >= 40, f"{n_sc} start/goal pairs on 12 synthetic grids (4 uniform-cost, 8 varied)")
    ok("A* == Dijkstra (astar.py, both algorithms)", viol["astar_dij"] == 0, f"violations {viol['astar_dij']}")
    ok("bench lattice A* == astar.py cost", viol["mine8"] == 0, f"violations {viol['mine8']}")
    ok("astar.py cost == independent scipy Dijkstra optimum", viol["ref"] == 0, f"violations {viol['ref']}")
    ok("16-connected A* == independent Dijkstra optimum (16 nb)", viol["a16ref"] == 0, f"violations {viol['a16ref']}")
    ok("16-connected cost <= 8-connected cost", viol["a16le8"] == 0, f"violations {viol['a16le8']}")
    ok("uniform-cost grids: Lazy Theta* length <= 8-connected A* length", viol["theta_u_len"] == 0, f"violations {viol['theta_u_len']}")
    ok("Lazy Theta* model cost <= 8-connected optimum (all grids)", viol["theta_cost"] == 0,
       f"violations {viol['theta_cost']}; mean cost ratio {np.mean(stats['theta_cost_ratio']):.4f}, mean length ratio {np.mean(stats['theta_len_ratio']):.4f}")
    ok("cost-aware smoothing never raises model cost", viol["smooth"] == 0, f"violations {viol['smooth']}")
    ok("independent dense-sampling checker: no path touches a hard-blocked cell", viol["hard"] == 0, f"violations {viol['hard']}")
    ok("D* Lite == A* after each replan (cost-to-go equal)", viol["dstar"] == 0, f"violations {viol['dstar']}")
    # open uniform grid: any-angle must give the straight line, grid path the octile length
    g = synth(99, H=60, W=60, block_frac=0.0, uniform=True); g["slope_max_deg"][:] = 0; ctx = Ctx(g, prof)
    s, t = 5 * 60 + 5, 50 * 60 + 33
    th = P.lazy_theta(ctx, s, t); mt = path_metrics(ctx, th["route"])
    ok("open grid: Lazy Theta* is the straight line", len(th["route"]) == 2 and abs(mt["planar_m"] - 4.047 * math.hypot(45, 28)) < 1e-6, f"vertices {len(th['route'])}")
    base = AS.plan(g, s, t, prof, "astar"); m8 = path_metrics(ctx, base["route"])
    ok("open grid: 8-connected A* length = octile length", abs(m8["planar_m"] - 4.047 * (17 + math.sqrt(2) * 28)) < 1e-6 * m8["planar_m"], f"{m8['planar_m']:.2f} m vs straight {mt['planar_m']:.2f} m")
    res["failed"] = fails; res["n_pairs"] = n_sc; res["stats"] = {k: dict(mean=float(np.mean(v)), max=float(np.max(v))) for k, v in stats.items()}
    os.makedirs(OUT, exist_ok=True); json.dump(res, open(os.path.join(OUT, "synthetic_checks.json"), "w"), indent=1)
    print("FAILED CHECKS:", fails)
    return fails


if __name__ == "__main__":
    sys.exit(1 if main() else 0)
