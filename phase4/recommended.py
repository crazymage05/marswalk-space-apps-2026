"""
MARSWALK Phase 4 - recommended planner (docs/research/algorithm_recommendation.md):
16-neighbour A* + string pulling with exact line of sight against the hard limits + risk-weighted cost.

Same cost model and hard limits as astar.py (edge = length x mean cell multiplier + climb_weight x climb), extended to
straight segments by an exact cell traversal (Amanatides-Woo): the multiplier is integrated along the segment, every
crossed cell AND every corner-touched cell must be unblocked. For one-cell lattice moves this equals astar.py exactly,
so astar16 (risk_weight=0) can only be cheaper than astar8. The reference 8-neighbour astar.plan is not changed.

Risk term: edge cost += risk_weight x length x mean cell risk, cell risk = (w_t terrain + w_u uncertainty + w_e environment)
/ (w_t + w_u + w_e) in 0..1 (terrain hazard and data confidence; NOT radiation, which is time-based here).
Both terms are >= 0 so the Euclidean heuristic cm x hypot(dr, dc) stays admissible and consistent.
"""
import heapq, math, time
from array import array
import numpy as np
try:
    from . import astronaut as A, costs as C
except ImportError:
    import astronaut as A, costs as C

INF = float("inf")
N8 = [(-1, 0), (-1, 1), (0, 1), (1, 1), (1, 0), (1, -1), (0, -1), (-1, -1)]
KNIGHT = [(-2, -1), (-2, 1), (-1, 2), (1, 2), (2, 1), (2, -1), (1, -2), (-1, -2)]
N16 = N8 + KNIGHT
WINDOW = 150            # string pulling looks at most this many route vertices ahead
RISK_WEIGHT_DEFAULT = 6.0   # Pareto knee on the campaign scenario (bench/run_knee.py), see docs/phase4_navigation.md

_cells = {}
_tables = {}
_pat = {}


def cell_risk(grid, profile):
    t = C.cell_terms(grid, profile); w = profile.cost_weights
    return ((w[0] * t["terrain"] + w[4] * t["uncertainty"] + w[2] * t["environment"]) / (w[0] + w[4] + w[2])).astype(np.float64)


def _prep(grid, profile, allow_unknown_rough):
    key = (id(grid), profile, allow_unknown_rough)
    if key not in _cells:
        if len(_cells) > 4: _cells.clear(); _tables.clear()
        blocked = C.hard_blocked(grid, profile, allow_unknown_rough)
        mult = C.cell_cost(grid, profile).astype(np.float64)
        el = np.nan_to_num(grid["elevation_m"]).astype(np.float64)
        risk = cell_risk(grid, profile)
        _cells[key] = dict(blocked=blocked, mult=mult, el2=el, risk2=risk, bl=blocked.ravel().tolist(),
                           mu=mult.ravel().tolist(), el=el.ravel().tolist(), rk=risk.ravel().tolist())
    return _cells[key]


def pattern(dr, dc, W, cm):
    """Exact traversal of the segment between two cell centres: cells (flat offset, fraction of length, dr, dc), corner-touched
    cells, chain of visited cells in order, length in m. Integer arithmetic so ties are exact."""
    key = (dr, dc, W)
    if key in _pat: return _pat[key]
    ar, ac = abs(dr), abs(dc); sr = 1 if dr > 0 else -1; sc = 1 if dc > 0 else -1
    if ar == 0: T = 2 * ac; tmr = dlr = INF; tmc, dlc = 1, 2
    elif ac == 0: T = 2 * ar; tmc = dlc = INF; tmr, dlr = 1, 2
    else: T = 2 * ar * ac; tmc, dlc, tmr, dlr = ar, 2 * ar, ac, 2 * ac
    cur = (0, 0); tp = 0; cells = []; chain = [(0, 0, 0)]; sides = []
    while cur != (dr, dc):
        t = min(tmc, tmr); cells.append((cur[0] * W + cur[1], (t - tp) / T, cur[0], cur[1])); tp = t
        if tmc == tmr:
            for s in ((cur[0] + sr, cur[1]), (cur[0], cur[1] + sc)): sides.append((s[0] * W + s[1], s[0], s[1]))
            cur = (cur[0] + sr, cur[1] + sc); tmc += dlc; tmr += dlr
        elif tmc < tmr: cur = (cur[0], cur[1] + sc); tmc += dlc
        else: cur = (cur[0] + sr, cur[1]); tmr += dlr
        chain.append((cur[0] * W + cur[1], cur[0], cur[1]))
    cells.append((cur[0] * W + cur[1], (T - tp) / T, cur[0], cur[1]))
    res = (tuple(cells), tuple(sides), tuple(chain), cm * math.hypot(dr, dc))
    _pat[key] = res
    return res


def _edge_tables(grid, profile, allow_unknown_rough, risk_weight):
    key = (id(grid), profile, allow_unknown_rough, round(risk_weight, 9))
    if key in _tables: return _tables[key]
    d = _prep(grid, profile, allow_unknown_rough)
    H, W, cm = grid["height"], grid["width"], grid["cell_m"]
    P = 3
    mu = np.pad(d["mult"] + risk_weight * d["risk2"], P, constant_values=1.0)
    el = np.pad(d["el2"], P, mode="edge"); bl = np.pad(d["blocked"], P, constant_values=True)
    sh = lambda a, dr, dc: a[P + dr:P + dr + H, P + dc:P + dc + W]
    out = []
    for dr, dc in N16:
        cells, sides, chain, L = pattern(dr, dc, W, cm)
        s = np.zeros((H, W)); b = d["blocked"].copy()
        for _, fr, r, c in cells: s += fr * sh(mu, r, c); b |= sh(bl, r, c)
        for _, r, c in sides: b |= sh(bl, r, c)
        climb = np.zeros((H, W)); prev = sh(el, 0, 0)
        for _, r, c in chain[1:]:
            e = sh(el, r, c); climb += np.maximum(e - prev, 0); prev = e
        cost = L * s + profile.climb_weight * climb
        cost[b] = INF
        out.append(array("d", cost.ravel().tolist()))
    if len(_tables) > 3: _tables.clear()
    _tables[key] = out
    return out


def _seg(d, W, cm, clw, rw, a, b):
    """(cost, blocked) of the straight segment a->b with the planning cost (model + rw x risk)."""
    cells, sides, chain, L = pattern(b // W - a // W, b % W - a % W, W, cm)
    bl, mu, el, rk = d["bl"], d["mu"], d["el"], d["rk"]
    blk = False; s = 0.0
    for off, fr, _, _ in cells:
        i = a + off
        if bl[i]: blk = True
        s += fr * (mu[i] + rw * rk[i])
    if not blk:
        for off, _, _ in sides:
            if bl[a + off]: blk = True; break
    climb = 0.0; prev = el[a]
    for off, _, _ in chain[1:]:
        e = el[a + off]
        if e > prev: climb += e - prev
        prev = e
    return L * s + clw * climb, blk


def string_pull(grid, profile, route, risk_weight=0.0, allow_unknown_rough=False, window=WINDOW):
    """Cost-aware string pulling: from each vertex jump to the farthest later vertex (within `window` vertices) with exact
    line of sight whose straight-segment cost does not exceed the cost of the A* sub-path it replaces."""
    d = _prep(grid, profile, allow_unknown_rough); W, cm, clw = grid["width"], grid["cell_m"], profile.climb_weight
    seg = lambda a, b: _seg(d, W, cm, clw, risk_weight, a, b)
    n = len(route); cum = [0.0]
    for a, b in zip(route[:-1], route[1:]): cum.append(cum[-1] + seg(a, b)[0])
    out = [route[0]]; i = 0
    while i < n - 1:
        nxt = i + 1
        for j in range(min(n - 1, i + window), i + 1, -1):
            c, blk = seg(route[i], route[j])
            if not blk and c <= cum[j] - cum[i] + 1e-9: nxt = j; break
        out.append(route[nxt]); i = nxt
    return out


def rasterize(vertices, W):
    """Adjacent-cell (Chebyshev step 1) Bresenham rasterisation of a polyline (for the cell-list route / old validator)."""
    cells = []
    for a, b in zip(vertices[:-1], vertices[1:]):
        (r0, c0), (r1, c1) = divmod(a, W), divmod(b, W)
        dr, dc = abs(r1 - r0), abs(c1 - c0); sr = 1 if r1 > r0 else -1; sc = 1 if c1 > c0 else -1
        err = dc - dr; r, c = r0, c0; seg = []
        while True:
            seg.append(r * W + c)
            if r == r1 and c == c1: break
            e2 = 2 * err
            if e2 > -dr: err -= dr; c += sc
            if e2 < dc: err += dc; r += sr
        cells += seg if not cells else seg[1:]
    return cells if cells else list(vertices)


def _bilinear(z, rr, cc):
    H, W = z.shape
    r = np.clip(rr, 0, H - 1); c = np.clip(cc, 0, W - 1)
    r0 = np.minimum(np.floor(r).astype(int), H - 2); c0 = np.minimum(np.floor(c).astype(int), W - 2)
    fr, fc = r - r0, c - c0
    return (z[r0, c0] * (1 - fr) * (1 - fc) + z[r0 + 1, c0] * fr * (1 - fc) + z[r0, c0 + 1] * (1 - fr) * fc + z[r0 + 1, c0 + 1] * fr * fc)


def polyline_metrics(grid, vertices, profile, allow_unknown_rough=False):
    """Walk the polyline in sub-steps of <= 1 cell on bilinear elevation: distance (3-D), time, energy, dose (fatigue
    model), plus model_cost (exact segment integral, risk weight 0) and risk_m (risk-metres, exact traversal)."""
    d = _prep(grid, profile, allow_unknown_rough); W, cm, clw = grid["width"], grid["cell_m"], profile.climb_weight
    dists, grades = [], []; model = 0.0; riskm = 0.0
    for a, b in zip(vertices[:-1], vertices[1:]):
        c, _ = _seg(d, W, cm, clw, 0.0, a, b); model += c
        cells, _, _, L = pattern(b // W - a // W, b % W - a % W, W, cm)
        riskm += L * sum(fr * d["rk"][a + off] for off, fr, _, _ in cells)
        (ra, ca), (rb, cb) = divmod(a, W), divmod(b, W)
        Lc = math.hypot(rb - ra, cb - ca); n = max(1, math.ceil(Lc - 1e-9))
        z = _bilinear(d["el2"], np.linspace(ra, rb, n + 1), np.linspace(ca, cb, n + 1))
        pdn = cm * Lc / n
        for k in range(n):
            dz = float(z[k + 1] - z[k]); dists.append(math.hypot(pdn, dz)); grades.append(dz / pdn)
    if dists: r = A.route_resources(profile, dists, grades)
    else: r = dict(time_s=0.0, energy_kj=0.0, dose_uGy=0.0)
    return dict(distance_m=float(sum(dists)), time_s=r["time_s"], energy_kj=r["energy_kj"], dose_uGy=r["dose_uGy"],
                model_cost=model, risk_m=riskm)


def plan_recommended(grid, start_cell, goal_cell, profile, smooth=True, risk_weight=RISK_WEIGHT_DEFAULT,
                     allow_unknown_rough=False, neighbours=16):
    """16-neighbour A* (+ string pulling if smooth). Returns the astar.plan dict: route (adjacent cells, rasterised, valid
    input for the old validator), vertices (the polyline: knight moves / straight segments), cost (planning cost incl. the
    risk term), model_cost (same cost model as astar.plan, measured on the final path), distance_m/time_s/energy_kj/dose_uGy
    along the actual polyline, risk_m, expanded, runtime_s."""
    t0 = time.perf_counter()
    d = _prep(grid, profile, allow_unknown_rough)
    H, W, cm = grid["height"], grid["width"], grid["cell_m"]
    fail = dict(route=[], vertices=[], cost=INF, distance_m=0.0, time_s=0.0, energy_kj=0.0, dose_uGy=0.0, expanded=0, success=False)
    bl = d["bl"]
    if bl[start_cell] or bl[goal_cell]:
        fail["reason"] = "start or goal hard-blocked"; return fail
    offs = N16 if neighbours == 16 else N8
    tabs = _edge_tables(grid, profile, allow_unknown_rough, risk_weight)[:len(offs)]
    gr, gc = divmod(goal_cell, W)
    nbo = [(dr * W + dc, dr, dc, t) for (dr, dc), t in zip(offs, tabs)]
    sr, sc = divmod(start_cell, W)
    dist = {start_cell: 0.0}; parent = {start_cell: -1}; done = set()
    pq = [(cm * math.hypot(sr - gr, sc - gc), start_cell)]; expanded = 0; hyp = math.hypot
    while pq:
        _, u = heapq.heappop(pq)
        if u in done: continue
        done.add(u); expanded += 1
        if u == goal_cell: break
        du = dist[u]; r, c = divmod(u, W)
        for off, dr, dc, t in nbo:
            w = t[u]
            if w == INF: continue
            v = u + off
            if v in done: continue
            nd = du + w
            if nd < dist.get(v, INF):
                dist[v] = nd; parent[v] = u
                heapq.heappush(pq, (nd + cm * hyp(r + dr - gr, c + dc - gc), v))
    if goal_cell not in done:
        fail["expanded"] = expanded; fail["reason"] = "unreachable"; fail["runtime_s"] = time.perf_counter() - t0
        return fail
    verts = []; u = goal_cell
    while u != -1: verts.append(u); u = parent[u]
    verts.reverse()
    if smooth: verts = string_pull(grid, profile, verts, risk_weight, allow_unknown_rough)
    m = polyline_metrics(grid, verts, profile, allow_unknown_rough)
    planned = dist[goal_cell]
    if smooth:
        planned = sum(_seg(d, W, cm, profile.climb_weight, risk_weight, a, b)[0] for a, b in zip(verts[:-1], verts[1:]))
    return dict(route=rasterize(verts, W), vertices=verts, cost=planned, model_cost=m["model_cost"], risk_m=m["risk_m"],
                distance_m=m["distance_m"], time_s=m["time_s"], energy_kj=m["energy_kj"], dose_uGy=m["dose_uGy"],
                expanded=expanded, success=True, algorithm="astar16", smooth=bool(smooth), risk_weight=risk_weight,
                runtime_s=time.perf_counter() - t0)
