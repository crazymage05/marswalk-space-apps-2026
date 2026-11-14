"""Effect of carried equipment on the campaign route: one-way time, energy and the safety-validator verdict.

    python tools/load_effect.py [preset]        (default nominal; also try conservative, fatigued)

Route: Python A* (phase4/astar.py, the chosen preset, no load) between the first and last campaign waypoints (sols 4500-4799)
of demo/twin/data.json, as in tools/export_replan.py. The same cells are then costed with carried_kg = 0, 10, 20, 30 kg
(phase4/astronaut.py, Wickman & Luna 1995 level factor + Pandolf-structure vertical factor) and judged by
phase4/safety_validator.validate (round trip, reserve) and flight_decision. Load does not change the route here: only the
cost and the verdict. Also prints the smallest load (0.5 kg steps) that turns GO into NO-GO, and the deciding rule.
SIMULATED: see docs/astronaut_model.md, section Carried load."""
import json, os, sys, base64
import numpy as np
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, ROOT)
from phase4 import costs, astar, astronaut as A, safety_validator as SV

preset = sys.argv[1] if len(sys.argv) > 1 else "nominal"
d = json.load(open(os.path.join(ROOT, "demo", "twin", "data.json")))
camp = [w for w in d["waypoints"] if 4500 <= w["sol"] <= 4799]
grid = costs.load_grid(); W, H = grid["width"], grid["height"]
slope = np.frombuffer(base64.b64decode(d["slope"]), np.uint8)


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
P0 = A.get_profile(preset)
route = [int(c) for c in astar.plan(grid, start, goal, P0)["route"]]   # planned for the preset's own limits, without load
if not route: raise SystemExit(f"no route for preset {preset} between the campaign waypoints")
print(f"route: {len(route)} cells, {astar.route_metrics(grid, route, P0)['distance_m']:.0f} m one way; profile {preset} "
      f"(body mass {P0.body_mass_kg:.0f} kg, suit {P0.suit_mass_kg:.0f} kg, kit+suit+astronaut {P0.mass_kg:.0f} kg); SIMULATED")


def row(L):
    p = A.with_load(P0, L)
    m = astar.route_metrics(grid, route, p)
    v = SV.validate(route, grid, p); fd = SV.flight_decision(v, p); s = v["summary"]
    return m, s, fd


print(f"{'carried':>8} {'one-way time':>13} {'one-way energy':>15} {'x no-load':>9} {'round-trip E / limit':>22} {'round-trip T / limit':>22}  verdict")
e0 = None
for L in (0, 10, 20, 30):
    m, s, fd = row(L)
    e0 = e0 or m["energy_kj"]
    print(f"{L:>5} kg {m['time_s'] / 60:>9.1f} min {m['energy_kj']:>11.1f} kJ {m['energy_kj'] / e0:>9.3f} "
          f"{s['roundtrip_energy_kj']:>10.0f} / {s['energy_limit_kj']:<9.0f} {s['roundtrip_time_s'] / 60:>9.1f} / {s['time_limit_s'] / 60:<8.0f}  {fd['decision']}"
          + (f" {fd['rule']} ({', '.join(fd['rules_failed'])})" if fd['rule'] else ""))
# smallest load that flips the verdict
L = 0.0
while L <= 400 and row(L)[2]["decision"] == "GO": L += 0.5
fd = row(L)[2]
print(f"smallest load that turns GO into NO-GO: {L:.1f} kg -> {fd['text']}" if fd["decision"] != "GO" else "no NO-GO up to 400 kg")
