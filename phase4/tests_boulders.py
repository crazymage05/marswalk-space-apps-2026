"""Boulder-avoidance tests: python phase4/tests_boulders.py (from the repo root).
Boulder footprint cells (data/processed/roi/boulder_cells.json, tools/export_boulders.py) are planner hard limits and a
validator CS-02 finding with reason "boulder"; Profile.avoid_boulders=False restores the old behaviour."""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
from dataclasses import replace
from phase4 import costs, astar, scenarios, astronaut as A, safety_validator as SV

grid = costs.load_grid(); W = grid["width"]; results = []
def check(name, cond, info=""): results.append(("PASS" if cond else "FAIL", name, info))
P = A.get_profile("nominal"); P0 = replace(P, avoid_boulders=False)
cells = json.load(open(costs.BOULDER_JSON))["cells"]; B = costs.boulder_blocked(grid)

check("mask has exactly the exported cells", int(B.sum()) == len(set(cells)) == 470, f"{int(B.sum())}")
base = costs.hard_blocked(grid, P0)
check("hard_blocked with the flag off is the old mask; on = old | boulders", bool((costs.hard_blocked(grid, P) == (base | B)).all()))
free = [c for c in cells if not base.flat[c]]
check("boulder cells exist that only boulders block", len(free) > 100, f"{len(free)} of {len(cells)}")

cell = free[len(free) // 2]
v = SV.validate([cell], grid, P)
bv = [x for x in v["violations"] if x["rule"] == "CS-02"]
check("a route through a boulder cell fails CS-02 with reason boulder", (not v["ok"]) and bv and bv[0]["reason"] == "boulder" and bv[0]["cell"] == cell, str(v["violations"][:1]))
check("same cell passes CS-02 with avoid_boulders off", not [x for x in SV.validate([cell], grid, P0)["violations"] if x["rule"] == "CS-02"])
vp = SV.validate_polyline([cell], grid, P)
check("validate_polyline also flags the boulder cell as CS-02 boulder", any(x["rule"] == "CS-02" and x.get("reason") == "boulder" for x in vp["violations"]), str(vp["violations"][:1]))
rv = [x for x in SV.validate(list(np.flatnonzero((grid["rough_max_m"] > P.rough_max_m).ravel())[:1]), grid, P)["violations"] if x["rule"] == "CS-02"]
check("real roughness violations carry reason roughness", all(x.get("reason") == "roughness" for x in rv) and rv)

c = scenarios.campaign_scenario(grid, P)
old = astar.plan(grid, c["start"], c["goal"], P0); new = astar.plan(grid, c["start"], c["goal"], P)
check("campaign route planned without boulder avoidance crosses footprint cells", old["success"] and any(B.flat[x] for x in old["route"]), str(sum(bool(B.flat[x]) for x in old["route"])))
check("campaign route planned with avoidance never enters a boulder cell and passes the validator",
      new["success"] and not any(B.flat[x] for x in new["route"]) and SV.validate(new["route"], grid, P)["ok"])
bad = 0; n = 0
for s in scenarios.make_scenarios(grid, P, 12, 3, 0.5, 2.0):
    r = astar.plan(grid, s["start"], s["goal"], P)
    if r["success"]:
        n += 1; bad += sum(bool(B.flat[x]) for x in r["route"])
check("12 random planned routes: no boulder cell on any route", n > 0 and bad == 0, f"{n} routes, {bad} boulder cells")
check("the old route fails the new validator but passes with the flag off",
      (not SV.validate(old["route"], grid, P)["ok"]) and "CS-02" in {x["rule"] for x in SV.validate(old["route"], grid, P)["violations"]})

for st, n_, i in results: print(st, n_, i)
print(f"{sum(r[0] == 'PASS' for r in results)}/{len(results)} checks passed")
sys.exit(0 if all(r[0] == "PASS" for r in results) else 1)
