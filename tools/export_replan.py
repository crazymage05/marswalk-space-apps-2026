"""Export a real dust-event replan for the twin page: demo/twin/replan.json (read by why_route.js and tour.js).

    python tools/export_replan.py

Route: Python A* (phase4/astar.py, nominal profile) between the first and last campaign waypoints (sols 4500-4799) of
demo/twin/data.json, i.e. the twin's "Campaign start -> end" route (each end nudged to the nearest cell under 25 deg, as
twin.html demo() does). Event: phase5/dust_event.make_event with the first seed from SEED that forces a detour to the same
goal and passes the validator and event check (same selection rule as phase6/mission_script.py), event detected at 30% of
the route. Replanned by phase5/replan.replan. Does not need the light-time table. Everything in the output comes from
those calls; provenance (script, seed, git hash, date) is recorded in the file."""
import json, os, subprocess, sys, time
import numpy as np
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, ROOT)
from phase4 import costs, astar, astronaut as A, safety_validator as SV
from phase5 import dust_event as DE, replan as RP

SOL, LMST0, SEED, FRAC = 4500, 9.0, 1, 0.30
d = json.load(open(os.path.join(ROOT, "demo", "twin", "data.json")))
camp = [w for w in d["waypoints"] if 4500 <= w["sol"] <= 4799]
grid = costs.load_grid(); P = A.get_profile("nominal"); W, H = grid["width"], grid["height"]
slope = np.frombuffer(__import__("base64").b64decode(d["slope"]), np.uint8)


def fit(w):
    c = round(w["y"]) * W + round(w["x"])
    if slope[c] <= 25: return c
    for r in range(1, 20):
        for dy in range(-r, r + 1):
            for dx in range(-r, r + 1):
                n = c + dy * W + dx
                if 0 <= n < W * H and slope[n] <= 25: return n
    return c


start, goal = fit(camp[0]), fit(camp[-1])
route = [int(c) for c in astar.plan(grid, start, goal, P)["route"]]
k = int(len(route) * FRAC)
chosen = None
for seed in range(SEED, SEED + 50):
    ev = DE.make_event(seed, grid, route, sol=SOL, lmst_start=LMST0, trigger={"kind": "button", "note": "export_replan"})
    rp = RP.replan(grid, route, k, ev, 0.0, P)
    if rp["changed"] and rp["validator_ok"] and rp["event_ok"] and rp["new_goal"] == goal: chosen = (seed, ev, rp); break
if not chosen: raise SystemExit("no seed in range gives a valid detour to the same goal")
seed, ev, rp = chosen
cm = grid["cell_m"]
def cxy(c): return [c % W, c // W]
out = dict(SIMULATED=True, label=ev["label"], rule=rp["rule"], explanation=rp["explanation"], diff=rp["diff"],
           validator_ok=rp["validator_ok"], event_ok=rp["event_ok"],
           before=dict(distance_m=rp["old_metrics"]["distance_m"], energy_kj=rp["old_metrics"]["energy_kj"], time_s=rp["old_metrics"]["time_s"]),
           after=dict(distance_m=rp["new_metrics"]["distance_m"], energy_kj=rp["new_metrics"]["energy_kj"], time_s=rp["new_metrics"]["time_s"]),
           event=dict(seed=seed, tau_peak=ev["tau_peak"], radius_m=ev["radius_m"], speed_mps=ev["speed_mps"]),
           route=dict(start_cell=start, goal_cell=goal, walker_index=k, n_cells=len(route), cell_m=cm, note="Python A*, nominal profile; remaining-route metrics are from the walker's cell onward"),
           provenance=dict(script="tools/export_replan.py", seed=seed, event_id=ev["id"], sol=SOL, lmst_start=LMST0, event_at_route_fraction=FRAC,
                           git_hash=subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip(),
                           generated=time.strftime("%Y-%m-%d"), modules=["phase5/dust_event.py", "phase5/replan.py", "phase4/astar.py", "phase4/safety_validator.py"]))
def clean(o):
    if isinstance(o, dict): return {str(a): clean(b) for a, b in o.items()}
    if isinstance(o, (list, tuple)): return [clean(x) for x in o]
    if isinstance(o, np.generic): return o.item()
    return o
json.dump(clean(out), open(os.path.join(ROOT, "demo", "twin", "replan.json"), "w"), indent=1)
print("wrote demo/twin/replan.json", "seed", seed, "rule", rp["rule"]); print(rp["explanation"][:400])
