"""Two-objective (time vs risk) weighted-sum sweep on the campaign scenario, 8-connected lattice, same hard limits.
Edge objectives (per lattice edge): T_e = 3-D length / Tobler speed at the edge grade (no fatigue), Rk_e = planar length x mean cell risk,
cell risk R = (0.35 terrain + 0.20 uncertainty + 0.15 environment)/0.70 from costs.cell_terms (0..1; data-confidence and terrain hazard,
NOT radiation, which is time-based). Scalarised cost = (1-lam) T_e + lam * kappa * Rk_e, kappa = 1/v_flat s per risk-metre.
Weighted sums only reach the CONVEX hull of the Pareto front; non-supported solutions are not found (stated limitation).
Usage: python phase4/bench/run_pareto.py -> results/pareto_results.json"""
import sys, os, json, math
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from phase4.bench.core import *
from phase4.bench import planners as P
from phase4 import scenarios as S

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
LAMS = [0.0, 0.05, 0.1, 0.2, 0.3, 0.45, 0.6, 0.75, 0.9, 0.97, 0.995]


def main():
    grid = C.load_grid(); prof = A.get_profile("nominal"); ctx = Ctx(grid, prof); W, H, cm = ctx.W, ctx.H, ctx.cm
    sc = S.campaign_scenario(grid, prof); s, t = int(sc["start"]), int(sc["goal"])
    terms = C.cell_terms(grid, prof); w = prof.cost_weights
    risk = ((w[0] * terms["terrain"] + w[4] * terms["uncertainty"] + w[2] * terms["environment"]) / (w[0] + w[4] + w[2])).astype(np.float64)
    E = ctx.edge_arrays(P.N8)
    Pd = 3; el = np.pad(ctx.el2, Pd, mode="edge"); rk = np.pad(risk, Pd, mode="edge")
    sh = lambda a, dr, dc: a[Pd + dr:Pd + dr + H, Pd + dc:Pd + dc + W]
    v0 = prof.walk_speed_flat_mps
    Te, Re = [], []
    for (dr, dc), e in zip(P.N8, E):
        L = cm * math.hypot(dr, dc); dz = sh(el, dr, dc) - sh(el, 0, 0)
        gr = np.clip(dz / L, -0.6, 0.6); v = np.maximum(0.05, v0 * np.exp(-3.5 * np.abs(gr + 0.05)) / math.exp(-3.5 * 0.05))
        Te.append(np.hypot(L, dz) / v); Re.append(L * 0.5 * (sh(rk, 0, 0) + sh(rk, dr, dc)))
    # scalar check of the vectorised speed against astronaut.py
    assert abs(A.step_speed_mps(prof, 0.1) - v0 * math.exp(-3.5 * abs(0.15)) / math.exp(-3.5 * 0.05)) < 1e-12
    vmax = v0 * math.exp(3.5 * 0.05); kappa = 1.0 / v0
    pts = []
    def add(label, verts, lam=None):
        m = path_metrics(ctx, verts)
        # edge-level objectives along the path (lattice paths) / sampled for any-angle paths
        T = Rk = 0.0
        for a, b in zip(verts[:-1], verts[1:]):
            (ra, ca), (rb, cb) = divmod(a, W), divmod(b, W)
            n = max(1, math.ceil(math.hypot(rb - ra, cb - ca) - 1e-9))
            rr = np.linspace(ra, rb, n + 1); cc = np.linspace(ca, cb, n + 1)
            z = ndimage.map_coordinates(ctx.el2, [rr, cc], order=1); rv = ndimage.map_coordinates(risk, [rr, cc], order=1)
            Ls = cm * math.hypot(rb - ra, cb - ca) / n
            for k in range(n):
                dz = z[k + 1] - z[k]; gr = max(-0.6, min(0.6, dz / Ls))
                vv = max(0.05, v0 * math.exp(-3.5 * abs(gr + 0.05)) / math.exp(-3.5 * 0.05)); T += math.hypot(Ls, dz) / vv; Rk += Ls * 0.5 * (rv[k] + rv[k + 1])
        okv, failed = validate_path(ctx, verts); hard = check_path_hard(grid, prof, verts)
        pts.append(dict(label=label, lam=lam, time_nofatigue_s=T, risk_m=Rk, length_m=m["length_m"], time_s=m["time_s"], energy_kj=m["energy_kj"],
                        max_slope_deg=m["max_slope_deg"], model_cost=m["cost"], turns_gt30=m["turns_gt30"], validator_ok=okv, hard_block_samples=hard, vertices=verts))
        print(label, round(T, 1), round(Rk, 1), round(m["length_m"], 1), okv, hard, flush=True)
    for lam in LAMS:
        tabs = []
        for e, T_, R_ in zip(E, Te, Re):
            c = (1 - lam) * T_ + lam * kappa * R_; c[~np.isfinite(e)] = INF
            tabs.append(array_d(c))
        r = P.grid_astar(ctx, tabs, P.N8, s, t, "octile", hscale=(1 - lam) / vmax)
        add(f"lam={lam}", r["route"], lam)
    base = AS.plan(grid, s, t, prof, "astar"); add("A* 8-conn (model cost)", base["route"])
    add("Lazy Theta* (model cost)", P.lazy_theta(ctx, s, t)["route"])
    json.dump(dict(points=pts, kappa=kappa, lams=LAMS), open(os.path.join(OUT, "pareto_results.json"), "w"))


def array_d(a):
    from array import array
    return array("d", a.ravel().tolist())


if __name__ == "__main__":
    main()
