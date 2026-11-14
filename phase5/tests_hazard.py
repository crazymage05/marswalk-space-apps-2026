"""H2/H3 tests: python phase5/tests_hazard.py   (from the repo root)"""
import sys, os, json, time, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
from phase4 import costs, astar, astronaut as A, safety_validator as SV
from phase5 import dust_event as DE, replan as RP

grid = costs.load_grid(); P = A.get_profile("nominal"); W = grid["width"]
ROUTE = astar.plan(grid, 400 * W + 200, 300 * W + 300, P)["route"]
results = []


def test(fn):
    t = time.time()
    try: fn(); results.append(("PASS", fn.__name__, time.time() - t))
    except AssertionError as e: results.append(("FAIL", fn.__name__ + ": " + str(e), time.time() - t))
    return fn


def core_cells(ev, t0):
    """Swept HZ-1 core recomputed here from tau_field (not via replan's overlay call)."""
    tmax = None
    for k in range(121):
        f = DE.tau_field(ev, t0 + ev["lookahead_h"] * k / 120); tmax = f if tmax is None else np.maximum(tmax, f)
    return tmax >= ev["rules"]["HZ-1"]["tau_ge"]


@test
def test_event_reproducible_from_seed_and_json_round_trip():
    a, b = DE.make_event(11, grid, ROUTE), DE.make_event(11, grid, ROUTE)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True), "same seed gives a different event"
    assert json.dumps(a) != json.dumps(DE.make_event(12, grid, ROUTE)), "different seeds give the same event"
    p = DE.save(a, os.path.join(tempfile.mkdtemp(), "ev.json")); assert DE.load(p) == a, "JSON round trip changed the event"
    assert a["SIMULATED"] is True and "SIMULATED" in a["label"]


@test
def test_replan_avoids_every_blocked_cell_and_passes_validator():
    n = 0
    for seed in range(1, 9):
        ev = DE.make_event(seed, grid, ROUTE); k = int(len(ROUTE) * 0.3)
        out = RP.replan(grid, ROUTE, k, ev, 0.0, P)
        core = core_cells(ev, 0.0)
        old_hits = [c for c in ROUTE[k:] if core[c // W, c % W]]
        if not old_hits: continue
        n += 1
        rest = out["new_route"][k:]
        bad = [c for c in rest if core[c // W, c % W] and c not in out.get("egress_cells", [])]
        assert out["changed"], f"seed {seed}: route not changed"
        assert not bad, f"seed {seed}: {len(bad)} new-route cells in the swept core"
        assert out["new_route"][:k] == ROUTE[:k], f"seed {seed}: walked part changed"
        assert out["new_route"][-1] == ROUTE[-1] or out["new_route"][-1] == ROUTE[0], f"seed {seed}: wrong destination"
        v = SV.validate(out["new_route"], grid, P); assert v["ok"], f"seed {seed}: validator {v['summary']['checks_failed']}"
        assert "HZ-1" in out["explanation"] and out["rule"] == "HZ-1", f"seed {seed}: explanation does not name the rule"
        assert all(k in out["diff"] for k in ("distance_m", "time_s", "energy_kj", "dose_uGy"))
    assert n >= 5, f"only {n} seeds blocked the route"


@test
def test_no_change_when_event_is_far():
    ev = DE.make_event(3, grid, ROUTE, centre_xy_m=[50 * grid["cell_m"], 700 * grid["cell_m"]], speed_mps=0.0)
    out = RP.replan(grid, ROUTE, 10, ev, 0.0, P)
    assert out["changed"] is False and out["new_route"] == ROUTE and "No change" in out["explanation"]


@test
def test_goal_inside_core_returns_to_start():
    gr, gc = divmod(ROUTE[-1], W); cm = grid["cell_m"]
    ev = DE.make_event(5, grid, ROUTE, centre_xy_m=[gc * cm, gr * cm], speed_mps=0.0, radius_m=120.0, tau_peak=3.0)
    out = RP.replan(grid, ROUTE, int(len(ROUTE) * 0.2), ev, 0.0, P)
    assert out["new_goal"] == ROUTE[0] and out["new_route"][-1] == ROUTE[0], "goal in the core did not turn the walk back"
    assert "returns to its start" in out["explanation"]
    assert SV.validate(out["new_route"], grid, P)["ok"]


@test
def test_walker_inside_core_walks_out_first():
    k = int(len(ROUTE) * 0.5); r, c = divmod(ROUTE[k], W); cm = grid["cell_m"]
    ev = DE.make_event(6, grid, ROUTE, centre_xy_m=[c * cm, r * cm], speed_mps=0.0, radius_m=100.0, tau_peak=3.0)
    out = RP.replan(grid, ROUTE, k, ev, 0.0, P)
    core = core_cells(ev, 0.0)
    eg = out.get("egress_cells") or []
    assert eg and eg[0] == ROUTE[k] and not core[eg[-1] // W, eg[-1] % W], "no egress out of the core"
    after = out["new_route"][k + len(eg) - 1:]
    assert not [x for x in after if core[x // W, x % W]], "route after the egress re-enters the core"
    assert "walk out of the dust core" in out["explanation"]


@test
def test_planner_unchanged_without_event():
    ev = DE.make_event(1, grid, ROUTE); RP.replan(grid, ROUTE, 30, ev, 0.0, P)
    again = astar.plan(grid, 400 * W + 200, 300 * W + 300, P)["route"]
    assert again == ROUTE, "planner output changed after an event replan (cache leak)"


@test
def test_h1_anomaly_triggers_reproducible_weak_event():
    an = {"anomaly": True, "sol": 4525, "lmst_hour": 5, "variable": "pressure_Pa", "value": 700.0, "expected": 720.0, "method": "baseline"}
    a, b = DE.event_from_anomaly(an, grid, ROUTE), DE.event_from_anomaly(an, grid, ROUTE)
    assert a == b and a["trigger"]["kind"] == "h1_anomaly" and a["trigger"]["strength"] == "weak" and a["sol"] == 4525


for s, name, dt in results: print(f"{s} {name} {dt:.1f}s")
print(f"{sum(r[0] == 'PASS' for r in results)}/{len(results)} passed")
sys.exit(0 if all(r[0] == "PASS" for r in results) else 1)
