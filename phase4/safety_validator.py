"""
MARSWALK Phase 4 - independent safety validator (Module 5C). Does not import astar.py or costs.py; it reads the
raw grid layers and the Profile limits. A route that fails is rejected and must be re-planned.

The walker is assumed to walk the route out and back along the same cells. Resource checks use the round trip
(out + reverse) and keep return_reserve_frac of the time and energy budget free. Time/energy/dose come from the
shared (SIMULATED) astronaut model.
"""
import math
try:
    from . import astronaut as A
except ImportError:
    import astronaut as A


def _isnan(x):
    return x != x


# ---------------- M1 flight rules ----------------
# MARSWALK's own rules, structured like NASA's EVA flight rules (crew safety first, then hardware/system, then science;
# GO / NO-GO before the walk, ABORT during it; nominal timeline plus a contingency reserve). Thresholds are MARSWALK's
# (Profile in astronaut.py, phase5/hazard_config.json), not NASA values. Each validator check maps to exactly one rule.
PRIORITY = {"CS": 0, "HZ": 1, "SY": 2, "SC": 3}           # crew safety, environmental hazard (to crew), system/hardware, science
# tiers follow NASA's stated EVA priorities (NTRS 20240005248, slide 8): 1 crew safety, 2 vehicle/suit/hardware, 3 mission
# success. The rule IDs, the ABORT definition and all thresholds are MARSWALK's own (NASA's public decks give none).
TIER = {"CS": 1, "HZ": 1, "SY": 2, "SC": 3}
RULES = {
    "CS-01": dict(cat="CS", when="plan", name="Terrain slope above the walker's limit", checks=["prohibited_slope"]),
    "CS-02": dict(cat="CS", when="plan", name="Obstacle roughness above the limit", checks=["prohibited_obstacle_roughness"]),
    "CS-03": dict(cat="CS", when="plan", name="Terrain unknown (no slope or roughness data)", checks=["unknown_cell"]),
    "CS-04": dict(cat="CS", when="plan", name="Terrain data confidence too low", checks=["low_data_confidence"]),
    "CS-05": dict(cat="CS", when="plan", name="EVA time with the walk back exceeds the limit minus the reserve", checks=["eva_time_with_return", "no_refuge_path"]),
    "CS-06": dict(cat="CS", when="plan", name="Walking energy with the walk back exceeds the budget minus the reserve", checks=["energy_budget_with_return"]),
    "CS-07": dict(cat="CS", when="plan", name="Radiation dose of the round trip exceeds the per-EVA limit", checks=["radiation_dose"]),
    "CS-08": dict(cat="CS", when="plan", name="Round trip does not fit in the daylight window", checks=["daylight_window"]),
    "HZ-1": dict(cat="HZ", when="plan", name="Route crosses the core of a dust event (tau >= HZ-1 threshold)", checks=["hazard_dust_core"]),
    "SY-01": dict(cat="SY", when="plan", name="Route is empty", checks=["empty_route"]),
    "SY-02": dict(cat="SY", when="plan", name="Route leaves the terrain grid", checks=["cell_out_of_grid"]),
    "SY-03": dict(cat="SY", when="plan", name="Route is not continuous (cells not 8-neighbours)", checks=["step_discontinuity"]),
    "SC-01": dict(cat="SC", when="advisory", name="Science stops not all reached (advisory, never a NO-GO)", checks=[]),
    "AB-01": dict(cat="CS", when="walk", name="Return margin below zero (time or energy to walk back, with reserve)", checks=[]),
    "AB-02": dict(cat="HZ", when="walk", name="Dust event core over the walker", checks=[]),
    "AB-03": dict(cat="CS", when="walk", name="Night: sun below the horizon at the walker", checks=[]),
    "AB-04": dict(cat="CS", when="walk", name="Solar particle event alert (space weather)", checks=[]),
}
CHECK_TO_RULE = {c: rid for rid, r in RULES.items() for c in r["checks"]}
_ORDER = {rid: k for k, rid in enumerate(RULES)}


def _rank(rid):
    return (PRIORITY[RULES[rid]["cat"]], _ORDER[rid])


def flight_decision(result, profile=None):
    """GO / NO-GO for a planned route from validate() or validate_polyline(); the deciding rule is the highest-priority
    failed one. Timeline bar: nominal out and back time, the contingency reserve, and the limit (seconds)."""
    failed = sorted({v["rule"] for v in result["violations"]}, key=_rank)
    sm = result.get("summary", {}); dec = "GO" if not failed else "NO-GO"
    bar = None
    if profile is not None and "roundtrip_time_s" in sm:
        lim = profile.eva_time_h * 3600.0
        bar = dict(nominal_roundtrip_s=sm["roundtrip_time_s"], contingency_reserve_s=lim * profile.return_reserve_frac,
                   limit_s=lim, nominal_plus_contingency_s=sm["roundtrip_time_s"] + lim * profile.return_reserve_frac)
    top = failed[0] if failed else None
    return dict(decision=dec, rule=top, rule_name=RULES[top]["name"] if top else None, tier=TIER[RULES[top]["cat"]] if top else None, rules_failed=failed,
                timeline=bar, text=("GO: all plan rules pass." if not failed else f"NO-GO: {top} {RULES[top]['name']}" +
                                    (f" (also {', '.join(failed[1:])})" if len(failed) > 1 else "")))


def walk_decision(return_margin_s=None, return_margin_kj=None, hazard_over_walker=False, sun_el_deg=None, sep_alert=False):
    """During a walk: ABORT on the highest-priority triggered rule, else GO (continue)."""
    trig = []
    if (return_margin_s is not None and return_margin_s < 0) or (return_margin_kj is not None and return_margin_kj < 0): trig.append("AB-01")
    if hazard_over_walker: trig.append("AB-02")
    if sun_el_deg is not None and sun_el_deg <= 0: trig.append("AB-03")
    if sep_alert: trig.append("AB-04")
    trig.sort(key=_rank); top = trig[0] if trig else None
    return dict(decision="ABORT" if trig else "GO", rule=top, rule_name=RULES[top]["name"] if top else None, rules_triggered=trig,
                text=f"ABORT: {top} {RULES[top]['name']}. Walk back now." if top else "GO: continue the walk.")


_GRADE_STEP = 0.0005


def _energy_table(profile):
    """Energy per metre of path (kJ/m) on a grade grid over [-0.6, 0.6]; step_energy_kj is linear in distance, so one table
    serves every step. Used only to choose the walk-back path; the reported numbers come from the astronaut model."""
    n = int(round(1.2 / _GRADE_STEP)) + 1
    return [A.step_energy_kj(profile, 1.0, -0.6 + i * _GRADE_STEP) for i in range(n)]


def _e_per_m(tab, g):
    x = (max(-0.6, min(0.6, g)) + 0.6) / _GRADE_STEP; i = min(int(x), len(tab) - 2); f = x - i
    return tab[i] + (tab[i + 1] - tab[i]) * f


def _refuge_tree(grid, profile, refuge, targets):
    """Dijkstra from the refuge cell over the cells the walker may enter (same hard limits as _blocked_independent), edge
    cost = energy to walk the step towards the refuge. Diagonal steps are refused when either orthogonal neighbour is
    blocked (as in the planner). Stops when every target cell is settled. Returns dict cell -> next cell towards the
    refuge (the refuge maps to itself); targets that were not reached are absent."""
    import heapq
    bad = _blocked_independent(grid, profile); W, nrow, cm = grid["width"], grid["height"], grid["cell_m"]
    z = grid["elevation_m"]; tab = _energy_table(profile)
    if not (0 <= refuge < W * nrow) or bad.flat[refuge]: return {}
    dist = {refuge: 0.0}; nxt = {refuge: refuge}; done = set(); todo = set(int(t) for t in targets); heap = [(0.0, refuge)]
    while heap and todo:
        d, c = heapq.heappop(heap)
        if c in done: continue
        done.add(c); todo.discard(c)
        r, col = divmod(c, W)
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                if not (dr or dc): continue
                rr, cc = r + dr, col + dc
                if not (0 <= rr < nrow and 0 <= cc < W) or bad[rr, cc]: continue
                if dr and dc and (bad[r, cc] or bad[rr, col]): continue
                n = rr * W + cc
                if n in done: continue
                pd = cm * math.hypot(dr, dc); dz = float(z[r, col] - z[rr, cc])        # walking n -> c
                nd = d + _e_per_m(tab, dz / pd) * math.hypot(pd, dz)
                if nd < dist.get(n, math.inf): dist[n] = nd; nxt[n] = c; heapq.heappush(heap, (nd, n))
    return {c: nxt[c] for c in done}


def _walkback_worst(route, grid, profile, tree):
    """Worst abort point along the route when the nearest refuge is a parked rover instead of the start. For each route cell
    k: time and energy spent so far (with fatigue) plus the walk from that cell to the refuge along the tree path (fresh
    fatigue, exactly as the walk back to the start is computed). Returns (T_max, E_max, indices with no path)."""
    W, cm = grid["width"], grid["cell_m"]; z = grid["elevation_m"]
    def steps(a, b):
        (ra, ca), (rb, cb) = divmod(a, W), divmod(b, W); pd = cm * math.hypot(ra - rb, ca - cb)
        dz = float(z[rb, cb] - z[ra, ca]); dz = 0.0 if _isnan(dz) else dz
        return (math.hypot(pd, dz), dz / pd) if pd else None
    tmax = emax = 0.0; lost = []; t = e = f = 0.0
    for k, c in enumerate(route):
        if k:
            st = steps(route[k - 1], c)
            if st:
                v = A.step_speed_mps(profile, st[1], f); de = A.step_energy_kj(profile, st[0], st[1])
                t += st[0] / v; e += de; f = A.fatigue_update(profile, f, de)
        if c not in tree: lost.append(k); continue
        ds, gs, cur = [], [], c
        while tree[cur] != cur:
            st = steps(cur, tree[cur]); cur = tree[cur]
            if st: ds.append(st[0]); gs.append(st[1])
        b = A.route_resources(profile, ds, gs) if ds else dict(time_s=0.0, energy_kj=0.0)
        tmax = max(tmax, t + b["time_s"]); emax = max(emax, e + b["energy_kj"])
    return tmax, emax, lost


def validate(route_cells, grid, profile, sol_daylight=None, round_trip=True, hazard_blocked=None, refuge_cell=None) -> dict:
    """sol_daylight: optional (start_h, end_h) allowed window in hours; the trip duration must fit in it.
    refuge_cell: optional flat cell index of a point of refuge (a parked rover, modelled support). When given, CS-05, CS-06
    and the dose use the worst abort point along the route, i.e. the largest (time or energy spent so far + the walk from
    there to the refuge on the cheapest allowed path), instead of out + the same way back to the start; a route cell with
    no allowed path to the refuge is a CS-05 violation (check no_refuge_path). None (default) keeps the behaviour above.
    Returns dict(ok, violations=[{check, cell_index_in_route, cell, value, limit}], summary)."""
    W, cm, nrow = grid["width"], grid["cell_m"], grid["height"]
    viol = []
    def add(check, i, cell, value, limit, reason=None):
        viol.append(dict(check=check, rule=CHECK_TO_RULE[check], cell_index_in_route=i, cell=None if cell is None else int(cell), value=value, limit=limit, **({"reason": reason} if reason else {})))
    route = [int(c) for c in route_cells]
    if not route:
        add("empty_route", None, None, 0, 1)
        return dict(ok=False, violations=viol, summary=dict(n_cells=0, n_violations=1))
    z = grid["elevation_m"]
    ncell = nrow * W
    boulder = _boulder_mask(grid) if getattr(profile, "avoid_boulders", True) else None
    for i, c in enumerate(route):
        if c < 0 or c >= ncell:
            add("cell_out_of_grid", i, c, c, ncell); continue
        r, col = divmod(c, W)
        s, ro, vf = float(grid["slope_max_deg"][r, col]), float(grid["rough_max_m"][r, col]), float(grid["valid_frac"][r, col])
        if _isnan(s): add("unknown_cell", i, c, "slope NaN", None)
        elif s > profile.max_slope_deg: add("prohibited_slope", i, c, s, profile.max_slope_deg)
        if _isnan(ro): add("unknown_cell", i, c, "roughness NaN", None)
        elif ro > profile.rough_max_m: add("prohibited_obstacle_roughness", i, c, ro, profile.rough_max_m, "roughness")
        if boulder is not None and boulder[r, col]: add("prohibited_obstacle_roughness", i, c, "boulder footprint", "outside boulder radius + margin", "boulder")
        if _isnan(vf) or vf < profile.valid_frac_min: add("low_data_confidence", i, c, vf, profile.valid_frac_min)
        if hazard_blocked is not None and bool(hazard_blocked[r, col]): add("hazard_dust_core", i, c, "in swept dust core", None)
        if i and 0 <= route[i - 1] < ncell:
            pr, pc = divmod(route[i - 1], W)
            step = max(abs(pr - r), abs(pc - col))
            if step != 1: add("step_discontinuity", i, c, step, 1)
    dists, grades = [], []
    for a, b in zip(route[:-1], route[1:]):
        if not (0 <= a < ncell and 0 <= b < ncell): continue
        (ra, ca), (rb, cb) = divmod(a, W), divmod(b, W)
        pd = cm * math.hypot(ra - rb, ca - cb)
        if pd == 0: continue
        dz = float(z[rb, cb] - z[ra, ca])
        if _isnan(dz): dz = 0.0
        dists.append(math.hypot(pd, dz)); grades.append(dz / pd)
    out = A.route_resources(profile, dists, grades)
    if refuge_cell is not None:
        bad_cells = {v["cell"] for v in viol if v["cell"] is not None}
        ok_cells = [c for c in route if 0 <= c < ncell and c not in bad_cells]
        tree = _refuge_tree(grid, profile, int(refuge_cell), ok_cells)
        T, E, lost = _walkback_worst(ok_cells, grid, profile, tree)
        for k in lost: add("no_refuge_path", k, ok_cells[k], "no allowed path to the refuge", None)
    elif round_trip:
        back = A.route_resources(profile, dists[::-1], [-g for g in grades[::-1]])
        T, E = out["time_s"] + back["time_s"], out["energy_kj"] + back["energy_kj"]
    else:
        T, E = out["time_s"], out["energy_kj"]
    D = A.dose_uGy(T)
    keep = 1.0 - profile.return_reserve_frac
    tlim, elim = profile.eva_time_h * 3600.0 * keep, profile.energy_budget_kj * keep
    if T > tlim: add("eva_time_with_return", None, None, T, tlim)
    if E > elim: add("energy_budget_with_return", None, None, E, elim)
    if D > profile.dose_budget_uGy: add("radiation_dose", None, None, D, profile.dose_budget_uGy)
    if sol_daylight is not None and T / 3600.0 > (sol_daylight[1] - sol_daylight[0]):
        add("daylight_window", None, None, T / 3600.0, sol_daylight[1] - sol_daylight[0])
    summary = dict(n_cells=len(route), distance_m=sum(dists), roundtrip_time_s=T, roundtrip_energy_kj=E,
                   roundtrip_dose_uGy=D, time_limit_s=tlim, energy_limit_kj=elim, dose_limit_uGy=profile.dose_budget_uGy,
                   n_violations=len(viol), checks_failed=sorted({v["check"] for v in viol}))
    if refuge_cell is not None: summary["walkback_to"] = "refuge"; summary["refuge_cell"] = int(refuge_cell)
    return dict(ok=not viol, violations=viol, summary=summary)


_BOULDERS = {}


def _boulder_mask(grid):
    """bool (H, W) mask of boulder-footprint cells from data/processed/roi/boulder_cells.json (read here, not via costs.py,
    so the validator stays independent of the planner); None when the file is absent or the grid is not 585 x 732."""
    import numpy as np, json, os
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "processed", "roi", "boulder_cells.json")
    if not os.path.exists(path) or (grid["height"], grid["width"]) != (732, 585):
        return None
    if path not in _BOULDERS:
        m = np.zeros((732, 585), bool); m.flat[np.array(json.load(open(path))["cells"], dtype=np.int64)] = True
        _BOULDERS[path] = m
    return _BOULDERS[path]


def _blocked_independent(grid, profile):
    import numpy as np
    sl, ro, vf = grid["slope_max_deg"], grid["rough_max_m"], grid["valid_frac"]
    b = np.isnan(sl) | np.isnan(ro) | np.isnan(vf) | np.isnan(grid["elevation_m"])
    with np.errstate(invalid="ignore"):
        b = b | (sl > profile.max_slope_deg) | (ro > profile.rough_max_m) | (vf < profile.valid_frac_min)
    if getattr(profile, "avoid_boulders", True):
        bm = _boulder_mask(grid)
        if bm is not None: b = b | bm
    return b


def validate_polyline(vertices, grid, profile, sol_daylight=None, round_trip=True, step=0.02) -> dict:
    """Validate a smoothed route: vertices = flat cell indices of the polyline (straight segments between cell centres).
    Every segment is sampled every `step` cell (each sample also nudged by +-1e-7 cell so a point on an edge or corner tests
    every adjoining cell); any sample inside a hard-limit cell is a violation. Resources are computed on sub-steps of <= 1
    cell on bilinear elevation, then the same round-trip / reserve / dose checks as validate(). Independent of astar.py,
    costs.py and recommended.py."""
    import numpy as np
    W, cm, nrow = grid["width"], grid["cell_m"], grid["height"]
    viol = []
    def add(check, i, cell, value, limit, reason=None):
        viol.append(dict(check=check, rule=CHECK_TO_RULE[check], cell_index_in_route=i, cell=None if cell is None else int(cell), value=value, limit=limit, **({"reason": reason} if reason else {})))
    vs = [int(v) for v in vertices]
    if not vs:
        add("empty_route", None, None, 0, 1)
        return dict(ok=False, violations=viol, summary=dict(n_cells=0, n_violations=1))
    if any(v < 0 or v >= nrow * W for v in vs):
        add("cell_out_of_grid", None, None, "vertex", nrow * W)
        return dict(ok=False, violations=viol, summary=dict(n_cells=len(vs), n_violations=1))
    boulder = _boulder_mask(grid) if getattr(profile, "avoid_boulders", True) else None
    bad = _blocked_independent(grid, profile); z = np.nan_to_num(grid["elevation_m"]).astype(float)
    pts = [divmod(v, W) for v in vs]
    seen = {}
    segs = list(zip(pts[:-1], pts[1:])) if len(pts) > 1 else [(pts[0], pts[0])]
    for k, ((r0, c0), (r1, c1)) in enumerate(segs):
        n = max(2, int(math.hypot(r1 - r0, c1 - c0) / step) + 1); t = np.linspace(0, 1, n)
        y = r0 + 0.5 + t * (r1 - r0); x = c0 + 0.5 + t * (c1 - c0)
        for ey in (0.0, 1e-7, -1e-7):
            for ex in (0.0, 1e-7, -1e-7):
                yi = np.floor(y + ey).astype(int); xi = np.floor(x + ex).astype(int)
                if (yi < 0).any() or (xi < 0).any() or (yi >= nrow).any() or (xi >= W).any():
                    add("cell_out_of_grid", k, None, "segment leaves grid", nrow * W); continue
                for q in np.flatnonzero(bad[yi, xi]):
                    cell = int(yi[q]) * W + int(xi[q])
                    if cell not in seen: seen[cell] = k
    for cell, k in seen.items():
        r, c = divmod(cell, W)
        s, ro, vf = float(grid["slope_max_deg"][r, c]), float(grid["rough_max_m"][r, c]), float(grid["valid_frac"][r, c])
        if _isnan(s) or _isnan(ro) or _isnan(float(grid["elevation_m"][r, c])): add("unknown_cell", k, cell, "NaN", None)
        elif s > profile.max_slope_deg: add("prohibited_slope", k, cell, s, profile.max_slope_deg)
        elif ro > profile.rough_max_m: add("prohibited_obstacle_roughness", k, cell, ro, profile.rough_max_m, "roughness")
        elif boulder is not None and boulder[r, c]: add("prohibited_obstacle_roughness", k, cell, "boulder footprint", "outside boulder radius + margin", "boulder")
        else: add("low_data_confidence", k, cell, vf, profile.valid_frac_min)
    dists, grades = [], []
    for (r0, c0), (r1, c1) in zip(pts[:-1], pts[1:]):
        L = math.hypot(r1 - r0, c1 - c0); n = max(1, math.ceil(L - 1e-9))
        rr = np.linspace(r0, r1, n + 1); cc = np.linspace(c0, c1, n + 1)
        i0 = np.minimum(np.floor(rr).astype(int), nrow - 2); j0 = np.minimum(np.floor(cc).astype(int), W - 2); fr, fc = rr - i0, cc - j0
        zz = (z[i0, j0] * (1 - fr) * (1 - fc) + z[i0 + 1, j0] * fr * (1 - fc) + z[i0, j0 + 1] * (1 - fr) * fc + z[i0 + 1, j0 + 1] * fr * fc)
        pd = cm * L / n
        for q in range(n):
            dz = float(zz[q + 1] - zz[q]); dists.append(math.hypot(pd, dz)); grades.append(dz / pd)
    out = A.route_resources(profile, dists, grades) if dists else dict(time_s=0.0, energy_kj=0.0)
    if round_trip and dists:
        back = A.route_resources(profile, dists[::-1], [-g for g in grades[::-1]])
        T, E = out["time_s"] + back["time_s"], out["energy_kj"] + back["energy_kj"]
    else:
        T, E = out["time_s"], out["energy_kj"]
    D = A.dose_uGy(T); keep = 1.0 - profile.return_reserve_frac
    tlim, elim = profile.eva_time_h * 3600.0 * keep, profile.energy_budget_kj * keep
    if T > tlim: add("eva_time_with_return", None, None, T, tlim)
    if E > elim: add("energy_budget_with_return", None, None, E, elim)
    if D > profile.dose_budget_uGy: add("radiation_dose", None, None, D, profile.dose_budget_uGy)
    if sol_daylight is not None and T / 3600.0 > (sol_daylight[1] - sol_daylight[0]):
        add("daylight_window", None, None, T / 3600.0, sol_daylight[1] - sol_daylight[0])
    summary = dict(n_cells=len(vs), n_segments=len(segs), distance_m=sum(dists), roundtrip_time_s=T, roundtrip_energy_kj=E,
                   roundtrip_dose_uGy=D, time_limit_s=tlim, energy_limit_kj=elim, dose_limit_uGy=profile.dose_budget_uGy,
                   n_violations=len(viol), checks_failed=sorted({v["check"] for v in viol}))
    return dict(ok=not viol, violations=viol, summary=summary)
