"""
MARSWALK Phase 4 - A* / Dijkstra on the 4 m grid, 8-connected (Module 5A).

Edge cost (equivalent metres) = planar_dist * 0.5*(m_a + m_b) + profile.climb_weight * max(dz, 0).
m >= 1 so the octile distance x cell size is an admissible and consistent heuristic; Dijkstra and A*
therefore return equal costs. Hard-blocked cells are never entered. A diagonal move is refused when either
of the two orthogonal neighbours is blocked (no corner cutting).
"""
import heapq, math, time
import numpy as np
try:
    from . import astronaut as A, costs as C
except ImportError:
    import astronaut as A, costs as C

_NB = [(-1, 0), (-1, 1), (0, 1), (1, 1), (1, 0), (1, -1), (0, -1), (-1, -1)]   # N NE E SE S SW W NW (plan action order)
_cache = {}


def _prep(grid, profile, allow_unknown_rough=False):
    # optional hazard overlay (phase5 dust event): grid["event_blocked"] (bool HxW) is added to the hard blocks and
    # grid["event_cost_mult"] (HxW, >= 1) multiplies the cell cost; grid["event_id"] keys the cache. Absent = unchanged.
    key = (id(grid), profile, allow_unknown_rough, grid.get("event_id"))
    if key not in _cache:
        if len(_cache) > 8: _cache.clear()
        blocked = C.hard_blocked(grid, profile, allow_unknown_rough)
        mult = C.cell_cost(grid, profile).astype(np.float64)
        if grid.get("event_blocked") is not None: blocked = blocked | grid["event_blocked"]
        if grid.get("event_cost_mult") is not None: mult = mult * grid["event_cost_mult"]
        _cache[key] = (blocked, mult, np.nan_to_num(grid["elevation_m"]).astype(np.float64),
                       blocked.ravel().tolist(), mult.ravel().tolist(), np.nan_to_num(grid["elevation_m"]).ravel().tolist())
    return _cache[key]


def route_metrics(grid, route, profile):
    """distance (3-D, m), time, energy, dose along a route of cell indices, with fatigue."""
    W, cm = grid["width"], grid["cell_m"]
    z = np.nan_to_num(grid["elevation_m"])
    dists, grades = [], []
    for a, b in zip(route[:-1], route[1:]):
        (ra, ca), (rb, cb) = divmod(a, W), divmod(b, W)
        pd = cm * math.hypot(ra - rb, ca - cb); dz = float(z[rb, cb] - z[ra, ca])
        dists.append(math.hypot(pd, dz)); grades.append(dz / pd)
    r = A.route_resources(profile, dists, grades)
    r["distance_m"] = float(sum(dists))
    return r


def plan(grid, start_cell, goal_cell, profile, algorithm="astar", allow_unknown_rough=False, smooth=False, risk_weight=0.0):
    """algorithm: 'astar' | 'dijkstra' (8-neighbour reference, unchanged) | 'astar16' (16-neighbour, phase4/recommended.py;
    smooth=True adds string pulling and a 'vertices' polyline; risk_weight adds weight x length x mean cell risk)."""
    if algorithm == "astar16":
        try: from . import recommended as R
        except ImportError: import recommended as R
        return R.plan_recommended(grid, start_cell, goal_cell, profile, smooth=smooth, risk_weight=risk_weight,
                                  allow_unknown_rough=allow_unknown_rough)
    t0 = time.perf_counter()
    blocked, _, _, bl, mu, el = _prep(grid, profile, allow_unknown_rough)
    H, W, cm = grid["height"], grid["width"], grid["cell_m"]
    fail = dict(route=[], cost=math.inf, distance_m=0.0, time_s=0.0, energy_kj=0.0, dose_uGy=0.0, expanded=0, success=False)
    if bl[start_cell] or bl[goal_cell]:
        fail["reason"] = "start or goal hard-blocked"; return fail
    gr, gc = divmod(goal_cell, W)
    astar = algorithm == "astar"
    clw = profile.climb_weight
    dist = {start_cell: 0.0}; parent = {start_cell: -1}; done = set()
    sr, sc = divmod(start_cell, W)
    S2 = math.sqrt(2) - 1
    def h(r, c):
        dr, dc = abs(r - gr), abs(c - gc)
        return cm * (max(dr, dc) + S2 * min(dr, dc))
    pq = [(h(sr, sc) if astar else 0.0, start_cell)]
    expanded = 0
    while pq:
        _, u = heapq.heappop(pq)
        if u in done: continue
        done.add(u); expanded += 1
        if u == goal_cell: break
        r, c = divmod(u, W); du = dist[u]
        for dr, dc in _NB:
            nr, nc = r + dr, c + dc
            if nr < 0 or nc < 0 or nr >= H or nc >= W: continue
            v = nr * W + nc
            if bl[v] or v in done: continue
            if dr and dc and (bl[r * W + nc] or bl[nr * W + c]): continue
            d = cm * (1.4142135623730951 if dr and dc else 1.0)
            nd = du + d * 0.5 * (mu[u] + mu[v]) + clw * max(el[v] - el[u], 0.0)
            if nd < dist.get(v, math.inf):
                dist[v] = nd; parent[v] = u
                heapq.heappush(pq, (nd + (h(nr, nc) if astar else 0.0), v))
    if goal_cell not in done:
        fail["expanded"] = expanded; fail["reason"] = "unreachable"; fail["runtime_s"] = time.perf_counter() - t0
        return fail
    route = []; u = goal_cell
    while u != -1: route.append(u); u = parent[u]
    route.reverse()
    m = route_metrics(grid, route, profile)
    return dict(route=route, cost=dist[goal_cell], distance_m=m["distance_m"], time_s=m["time_s"],
                energy_kj=m["energy_kj"], dose_uGy=m["dose_uGy"], expanded=expanded, success=True,
                algorithm=algorithm, runtime_s=time.perf_counter() - t0)


def plan_via(grid, cells_in_order, profile, algorithm="astar", allow_unknown_rough=False):
    """Chain legs through cells_in_order. A waypoint that is blocked or unreachable from the current
    position is skipped and reported; the walker continues from the last reached cell."""
    cur = cells_in_order[0]; route = [cur]; skipped = []; reached = [cur]
    cost = 0.0; expanded = 0
    for w in cells_in_order[1:]:
        if w == cur: continue
        leg = plan(grid, cur, w, profile, algorithm, allow_unknown_rough)
        expanded += leg["expanded"]
        if not leg["success"]:
            skipped.append(dict(cell=w, reason=leg.get("reason", "unreachable"))); continue
        route += leg["route"][1:]; cost += leg["cost"]; cur = w; reached.append(w)
    m = route_metrics(grid, route, profile) if len(route) > 1 else dict(distance_m=0.0, time_s=0.0, energy_kj=0.0, dose_uGy=0.0)
    return dict(route=route, cost=cost, distance_m=m["distance_m"], time_s=m["time_s"], energy_kj=m["energy_kj"],
                dose_uGy=m["dose_uGy"], expanded=expanded, reached=reached, skipped=skipped, success=len(route) > 1)
