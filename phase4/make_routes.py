"""Write data/processed/roi/routes_astar.json: A* routes (campaign + 20 random, seed 0) with validator results."""
import json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import costs, astar, safety_validator as sv, scenarios, astronaut as A

OUT = os.path.join(costs.ROOT, "data", "processed", "roi", "routes_astar.json")
grid = costs.load_grid(); P = A.get_profile("nominal")
def rec(s, r, kind):
    v = sv.validate(r["route"], grid, P) if r["route"] else dict(ok=False, violations=[], summary={})
    return dict(id=s["id"], kind=kind, start_cell=s["start"], goal_cell=s["goal"], straight_km=round(s["distance_km"], 3),
                success=r["success"], route=r["route"], cost=r["cost"] if r["success"] else None,
                distance_m=round(r["distance_m"], 1), time_s=round(r["time_s"], 1), energy_kj=round(r["energy_kj"], 1),
                dose_uGy=round(r["dose_uGy"], 3), expanded=r["expanded"], runtime_s=round(r.get("runtime_s", 0), 3),
                skipped_waypoints=r.get("skipped", []), validator=dict(ok=v["ok"], violations=v["violations"], summary=v["summary"]))
routes = []
c = scenarios.campaign_scenario(grid, P)
t = time.perf_counter(); r = astar.plan(grid, c["start"], c["goal"], P); r["runtime_s"] = time.perf_counter() - t
routes.append(rec(c, r, "campaign_direct"))
t = time.perf_counter(); r = astar.plan_via(grid, c["via"], P); r["runtime_s"] = time.perf_counter() - t
x = rec(dict(c, id="campaign_via"), r, "campaign_via_waypoints"); x["waypoints_reached"] = len(r["reached"]); x["waypoints_total"] = len(c["via"])
routes.append(x)
for s in scenarios.make_scenarios(grid, P, 20, 0, 0.5, 2.0):
    routes.append(rec(s, astar.plan(grid, s["start"], s["goal"], P), "random"))
doc = dict(note="SIMULATED astronaut profile; A* routes on nav_grid_4m (cell = row*585+col). Validator assumes out-and-back.",
           profile=A.asdict(P), grid=dict(width=grid["width"], height=grid["height"], cell_m=grid["cell_m"]), routes=routes)
json.dump(doc, open(OUT, "w"))
for x in routes:
    print(x["id"], x["success"], x["distance_m"], x["time_s"], x["energy_kj"], x["dose_uGy"], x["expanded"], x["runtime_s"], x["validator"]["ok"], x["validator"]["summary"].get("checks_failed"))
