"""Quick self-tests: python phase4/tests_nav.py"""
import os, sys, time, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import costs, astar, safety_validator as sv, scenarios, astronaut as A, recommended as R

grid = costs.load_grid(); P = A.get_profile("nominal")
blocked = costs.hard_blocked(grid, P)
sc = scenarios.make_scenarios(grid, P, 20, 0, 0.5, 2.0)
assert len(sc) == 20


def test_never_blocked():
    for s in sc[:10]:
        r = astar.plan(grid, s["start"], s["goal"], P)
        assert r["success"], s
        assert not blocked.flat[r["route"]].any()


def test_validator_catches_broken():
    r = astar.plan(grid, sc[0]["start"], sc[0]["goal"], P)
    good = r["route"]
    assert not any(v["check"] in ("step_discontinuity", "prohibited_slope", "unknown_cell") for v in sv.validate(good, grid, P)["violations"])
    jump = good[:3] + good[-3:]
    assert any(v["check"] == "step_discontinuity" for v in sv.validate(jump, grid, P)["violations"])
    bad_cell = int(np.flatnonzero((grid["slope_max_deg"] > P.max_slope_deg).ravel())[0])
    assert any(v["check"] == "prohibited_slope" for v in sv.validate(good[:2] + [bad_cell], grid, P)["violations"])
    nan_cell = int(np.flatnonzero(np.isnan(grid["rough_max_m"]).ravel())[0])
    assert any(v["check"] == "unknown_cell" for v in sv.validate([nan_cell], grid, P)["violations"])
    tiny = A.Profile(eva_time_h=0.05)
    assert any(v["check"] == "eva_time_with_return" for v in sv.validate(good, grid, tiny)["violations"])


def test_dijkstra_equals_astar():
    for s in sc:
        a = astar.plan(grid, s["start"], s["goal"], P, "astar"); d = astar.plan(grid, s["start"], s["goal"], P, "dijkstra")
        assert a["success"] and d["success"]
        assert math.isclose(a["cost"], d["cost"], rel_tol=1e-9), (s, a["cost"], d["cost"])
        assert a["expanded"] <= d["expanded"]


def test_plan_via_skips():
    s = sc[0]; bad = int(np.flatnonzero(blocked.ravel())[0])
    r = astar.plan_via(grid, [s["start"], bad, s["goal"]], P)
    assert r["skipped"] and r["skipped"][0]["cell"] == bad and r["route"][-1] == s["goal"]


def _independent_blocked():
    sl, ro, vf = grid["slope_max_deg"], grid["rough_max_m"], grid["valid_frac"]
    return (np.nan_to_num(sl, nan=1e9) > P.max_slope_deg) | (np.nan_to_num(ro, nan=1e9) > P.rough_max_m) |            (np.nan_to_num(vf, nan=-1.0) < P.valid_frac_min) | np.isnan(grid["elevation_m"])


def test_astar16_not_costlier_than_astar8():
    """Measured identically: exact model cost (risk weight 0) of the final path, on every scenario."""
    for s in sc[:8]:
        a8 = astar.plan(grid, s["start"], s["goal"], P)
        a16 = astar.plan(grid, s["start"], s["goal"], P, "astar16")
        assert a16["success"] and a16["algorithm"] == "astar16" and a16["vertices"][0] == s["start"] and a16["vertices"][-1] == s["goal"]
        c8 = R.polyline_metrics(grid, a8["route"], P)["model_cost"]
        assert math.isclose(c8, a8["cost"], rel_tol=1e-9), (c8, a8["cost"])   # the measure reproduces astar.py's cost
        assert a16["model_cost"] <= c8 * (1 + 1e-9), (s, a16["model_cost"], c8)
        sm = astar.plan(grid, s["start"], s["goal"], P, "astar16", smooth=True)
        assert sm["model_cost"] <= a16["model_cost"] + 1e-6 and len(sm["vertices"]) <= len(a16["vertices"])


def test_smoothed_never_crosses_blocked():
    bi = _independent_blocked(); H, W = bi.shape
    for s in sc[:10]:
        for rw in (0.0, R.RISK_WEIGHT_DEFAULT):
            r = R.plan_recommended(grid, s["start"], s["goal"], P, smooth=True, risk_weight=rw)
            assert r["success"] and not blocked.flat[r["route"]].any()
            pts = [divmod(v, W) for v in r["vertices"]]
            for (r0, c0), (r1, c1) in zip(pts[:-1], pts[1:]):
                n = max(2, int(math.hypot(r1 - r0, c1 - c0) / 0.02) + 1); t = np.linspace(0, 1, n)
                y = r0 + 0.5 + t * (r1 - r0); x = c0 + 0.5 + t * (c1 - c0)
                for ey in (0.0, 1e-7, -1e-7):
                    for ex in (0.0, 1e-7, -1e-7):
                        assert not bi[np.floor(y + ey).astype(int), np.floor(x + ex).astype(int)].any(), (s, rw)


def test_validator_passes_recommended_20():
    for s in sc:
        r = R.plan_recommended(grid, s["start"], s["goal"], P)
        assert r["success"]
        v = sv.validate_polyline(r["vertices"], grid, P)
        assert v["ok"], (s, v["violations"][:3])
        assert sv.validate(r["route"], grid, P)["ok"]       # rasterised cells also pass the cell-list validator


def test_polyline_validator_catches_blocked_segment():
    s = sc[0]; r = R.plan_recommended(grid, s["start"], s["goal"], P)
    bad_cell = int(np.flatnonzero(blocked.ravel())[0])
    v = sv.validate_polyline([r["vertices"][0], bad_cell], grid, P)
    assert not v["ok"] and any(x["check"] in ("prohibited_slope", "prohibited_obstacle_roughness", "unknown_cell", "low_data_confidence") for x in v["violations"])
    assert not sv.validate_polyline([], grid, P)["ok"]
    assert any(x["check"] == "eva_time_with_return" for x in sv.validate_polyline(r["vertices"], grid, A.Profile(eva_time_h=0.05))["violations"])


def test_default_astar_unchanged_and_risk_weight_raises_risk_cost():
    s = sc[1]; a = astar.plan(grid, s["start"], s["goal"], P)
    assert "vertices" not in a and a["algorithm"] == "astar"
    lo = R.plan_recommended(grid, s["start"], s["goal"], P, risk_weight=0.0); hi = R.plan_recommended(grid, s["start"], s["goal"], P, risk_weight=40.0)
    assert hi["risk_m"] <= lo["risk_m"] + 1e-9 and hi["model_cost"] >= lo["model_cost"] - 1e-6


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            t = time.time(); f(); print("PASS", n, f"{time.time()-t:.1f}s")
