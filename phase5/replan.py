"""H3: replan a walk around a SIMULATED dust event (phase5/dust_event.py).

replan(grid, route, walker_index, event, t_now_h, profile) re-runs A* from the walker's current cell with the event's
swept rules applied (HZ-1 blocks, HZ-2 raises cost; phase4/astar.py's event overlay), checks the result with the
phase-4 validator (terrain and resources, independent of the planner) and with an event check written here (no cell of
the new remaining route lies in the HZ-1 swept core), and returns a route diff and a plain-text explanation that names
the rule. Special cases:
  - walker inside the HZ-1 core: egress first to the nearest non-core cell (breadth-first over terrain-passable cells),
    then plan from there; the egress cells are reported and exempt from the event check.
  - goal inside the HZ-1 core: the goal becomes the walk's start (return), stated in the explanation.
Dose uses the astronaut model (rate x time).
"""
import math
from collections import deque
import numpy as np

from phase4 import astar, costs, astronaut as A, safety_validator as SV
from phase5 import dust_event as DE


def _metrics(grid, cells, profile):
    if len(cells) < 2: return dict(distance_m=0.0, time_s=0.0, energy_kj=0.0, dose_uGy=0.0)
    m = astar.route_metrics(grid, cells, profile)
    return dict(distance_m=m["distance_m"], time_s=m["time_s"], energy_kj=m["energy_kj"], dose_uGy=m["dose_uGy"])


def _egress(grid, start, core, terrain_blocked):
    """Shortest 8-connected path (in steps) from start to the nearest cell outside the core over terrain-passable cells."""
    H, W = grid["height"], grid["width"]; prev = {start: -1}; q = deque([start])
    while q:
        u = q.popleft(); r, c = divmod(u, W)
        if not core[r, c]:
            path = [u]
            while prev[path[-1]] != -1: path.append(prev[path[-1]])
            return path[::-1]
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                nr, nc = r + dr, c + dc
                if (dr or dc) and 0 <= nr < H and 0 <= nc < W and not terrain_blocked[nr, nc]:
                    v = nr * W + nc
                    if v not in prev: prev[v] = u; q.append(v)
    return None


def event_check(cells, blocked, W, exempt=()):
    """Independent hazard check: indices of cells in the swept HZ-1 core (excluding exempt cells)."""
    ex = set(exempt)
    return [i for i, c in enumerate(cells) if c not in ex and blocked[c // W, c % W]]


def replan(grid, route, walker_index, event, t_now_h, profile=None, sol_daylight=None):
    profile = profile or A.get_profile("nominal"); W = grid["width"]
    route = [int(c) for c in route]; k = max(0, min(int(walker_index), len(route) - 1))
    here, goal = route[k], route[-1]
    blocked, mult, tmax = DE.overlay(event, t_now_h)
    old_rest = route[k:]; hit = event_check(old_rest, blocked, W)
    caution = [i for i, c in enumerate(old_rest) if mult[c // W, c % W] > 1.0]
    rule_hz1, rule_hz2 = event["rules"]["HZ-1"], event["rules"]["HZ-2"]
    window = f"{event['lookahead_h']:.1f} h"
    base = dict(event_id=event["id"], SIMULATED=True, walker_cell=here, walker_index=k, t_now_h=t_now_h,
                old_remaining_cells=old_rest, blocked_cells_on_old_route=[old_rest[i] for i in hit])
    if not hit and not caution:
        return dict(base, changed=False, new_route=route, rule=None, validator_ok=None, event_ok=True,
                    explanation=f"No change: the planned route does not enter the {event['label']} within the next {window}.")
    # planning grid with the event overlay (cache keyed by event id + time)
    g2 = dict(grid); g2["event_blocked"] = blocked; g2["event_cost_mult"] = mult; g2["event_id"] = f"{event['id']}@{t_now_h:.4f}"
    terrain_blocked = costs.hard_blocked(grid, profile)
    egress = []
    start = here
    if blocked[here // W, here % W]:
        egress = _egress(grid, here, blocked, terrain_blocked)
        if egress is None:
            return dict(base, changed=False, new_route=route, rule="HZ-1", validator_ok=False, event_ok=False,
                        explanation="ABORT: the walker is inside the dust core and no passable way out was found.")
        start = egress[-1]
    new_goal, goal_note = goal, ""
    if blocked[goal // W, goal % W]:
        new_goal = route[0]; goal_note = " The goal lies inside the dust core, so the walk returns to its start."
    plan = astar.plan(g2, start, new_goal, profile)
    if not plan["success"]:
        return dict(base, changed=False, new_route=route, rule="HZ-1", validator_ok=False, event_ok=False,
                    explanation=f"No route found around the dust event from the walker's cell ({plan.get('reason', 'search failed')}). Hold position or return.")
    new_rest = (egress[:-1] if egress else []) + plan["route"]
    new_route = route[:k] + new_rest
    hz_hits = event_check(new_rest, blocked, W, exempt=egress)
    val = SV.validate(new_route, grid, profile, sol_daylight=sol_daylight)
    mo, mn = _metrics(grid, old_rest, profile), _metrics(grid, new_rest, profile)
    diff = {q: mn[q] - mo[q] for q in mo}
    rule = "HZ-1" if hit else "HZ-2"
    why = (f"Rule {rule} ({rule_hz1['name']}: tau >= {rule_hz1['tau_ge']}): {len(hit)} cells of the planned route lie in the "
           f"{event['label']} within the next {window} (peak tau {event['tau_peak']:.1f}, moving {event['speed_mps']:.1f} m/s "
           f"towards {event['direction_deg']:.0f} deg)." if hit else
           f"Rule HZ-2 ({rule_hz2['name']}: tau >= {rule_hz2['tau_ge']}): {len(caution)} cells of the planned route lie in the dusty "
           f"edge of the {event['label']} within the next {window}; the planner looked for a cheaper way.")
    eg = f" First {len(egress) - 1} cells walk out of the dust core by the shortest way." if len(egress) > 1 else ""
    res = (f" Re-planned from the walker's cell: {diff['distance_m']:+.0f} m, {diff['time_s'] / 60:+.1f} min, "
           f"{diff['energy_kj']:+.0f} kJ, {diff['dose_uGy']:+.2f} uGy for the rest of the walk.")
    vtxt = " Validator: GO (all terrain and resource checks pass)." if val["ok"] else f" Validator: NO-GO ({', '.join(val['summary']['checks_failed'])})."
    if hz_hits: vtxt += f" Event check: {len(hz_hits)} cells still in the dust core."
    return dict(base, changed=new_route != route, new_route=new_route, new_remaining_cells=new_rest, egress_cells=egress,
                new_goal=new_goal, rule=rule, diff=diff, old_metrics=mo, new_metrics=mn, validator_ok=val["ok"],
                validator=val["summary"], event_ok=not hz_hits, event_hits=[new_rest[i] for i in hz_hits],
                explanation=why + eg + goal_note + res + vtxt)
