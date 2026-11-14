"""M1 flight-rule tests: python phase4/tests_rules.py (from the repo root).

Rebuilds the 16 adversarial routes of the Phase 4 verification (docs/verification/03_phase4_nav.md, row 3: set A of 6
mutations of an A* route, set B of 10 separately built bad routes) and checks each is NO-GO with the expected rule as the
deciding rule; good routes are GO; walk-time ABORT rules fire; every validator check maps to exactly one rule ID.
"""
import sys, os, re, math, time
from dataclasses import replace
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
from phase4 import costs, astar, astronaut as A, safety_validator as SV

grid = costs.load_grid(); P = A.get_profile("nominal"); W, H = grid["width"], grid["height"]
R1 = astar.plan(grid, 400 * W + 200, 300 * W + 300, P)["route"]          # 781 m
R2 = astar.plan(grid, 300 * W + 150, 200 * W + 250, P)["route"]           # 623 m
results = []


def check(name, cond, info=""):
    results.append(("PASS" if cond else "FAIL", name, info))


def decide(route, prof=P, **kw):
    v = SV.validate(route, grid, prof, **kw); return SV.flight_decision(v, prof), v


def neighbour_with(pred, near):
    """An 8-neighbour of cell `near` satisfying pred(row, col), or None."""
    r, c = divmod(near, W)
    for dr in (-1, 0, 1):
        for dc in (-1, 0, 1):
            if (dr or dc) and 0 <= r + dr < H and 0 <= c + dc < W and pred(r + dr, c + dc): return (r + dr) * W + c + dc
    return None


def find_cell(pred, route):
    """Index k and a neighbour cell n of route[k] with pred true (first found along the route), for a 1-cell detour."""
    for k in range(5, len(route) - 5):
        n = neighbour_with(pred, route[k])
        if n is not None and max(abs(n // W - route[k + 1] // W), abs(n % W - route[k + 1] % W)) <= 1: return k, n
    return None, None


S = grid["slope_max_deg"]; RO = grid["rough_max_m"]; VF = grid["valid_frac"]
expected = []   # (case name, route, profile, expected rule)

# ---- set A: mutations of an A* route ----
expected.append(("A1 teleport", R1[:60] + R1[90:], P, "SY-03"))
# steep cell: find any cell above 25 deg next to the route, detour through it
def steep(r, c): return np.isfinite(S[r, c]) and S[r, c] > P.max_slope_deg
k, n = find_cell(steep, R1)
if n is None:   # route avoids steep ground; build a route ending in a steep cell next to it via a neighbour path
    idx = np.argwhere(np.nan_to_num(S) > P.max_slope_deg)[0]; n = int(idx[0] * W + idx[1]); k = None
expected.append(("A2 steep cell", (R1[:k + 1] + [n] + R1[k + 1:]) if k is not None else [n], P, "CS-01"))
def nan_c(r, c): return not np.isfinite(S[r, c])
k3, n3 = find_cell(nan_c, R1)
if n3 is None:
    idx = np.argwhere(~np.isfinite(S))[0]; n3 = int(idx[0] * W + idx[1]); k3 = None
expected.append(("A3 NaN cell", (R1[:k3 + 1] + [n3] + R1[k3 + 1:]) if k3 is not None else [n3], P, "CS-03"))
expected.append(("A4 tiny EVA time", R1, replace(P, eva_time_h=0.2), "CS-05"))
expected.append(("A5 dose budget 0.5", R1, replace(P, dose_budget_uGy=0.5), "CS-07"))
expected.append(("A6 energy budget 50", R1, replace(P, energy_budget_kj=50.0), "CS-06"))
# ---- set B: separately built bad routes ----
expected.append(("B1 row jump", R2[:40] + [R2[40] + 3 * W] + R2[41:], P, "SY-03"))
expected.append(("B2 repeated cell", R2[:30] + [R2[30]] + R2[30:], P, "SY-03"))
def rough(r, c): return np.isfinite(RO[r, c]) and RO[r, c] > P.rough_max_m and np.isfinite(S[r, c]) and S[r, c] <= P.max_slope_deg
kb, nb = find_cell(rough, R2)
if nb is None: kb, nb = find_cell(rough, R1); base = R1
else: base = R2
if nb is None:
    cand = [i for i in np.argwhere(np.nan_to_num(RO) > P.rough_max_m) if rough(*i) and VF[i[0], i[1]] >= P.valid_frac_min]; rr = [int(cand[0][0] * W + cand[0][1])]
else: rr = base[:kb + 1] + [nb] + base[kb + 1:]
expected.append(("B3 roughness", rr, P, "CS-02"))
def lowvf(r, c): return VF[r, c] < P.valid_frac_min and np.isfinite(S[r, c]) and S[r, c] <= P.max_slope_deg and np.isfinite(RO[r, c]) and RO[r, c] <= P.rough_max_m
kv, nv = find_cell(lowvf, R2)
B4_prof = P
if nv is None:
    # in this grid every cell below valid_frac_min also lacks slope/roughness data (CS-03 decides), so isolate CS-04 by
    # raising the confidence threshold just above the route's lowest valid_frac
    vv = R2; B4_prof = replace(P, valid_frac_min=float(min(VF[c // W, c % W] for c in R2)) + 1e-3)
else: vv = R2[:kv + 1] + [nv] + R2[kv + 1:]
expected.append(("B4 low valid_frac", vv, B4_prof, "CS-04"))
expected.append(("B5 off-grid index", R2[:20] + [W * H + 5], P, "SY-02"))
expected.append(("B6 empty route", [], P, "SY-01"))
expected.append(("B7 energy", R2, replace(P, energy_budget_kj=30.0), "CS-06"))
expected.append(("B8 dose", R2, replace(P, dose_budget_uGy=0.3), "CS-07"))
long_route = R1 + R1[::-1][1:] + R1[1:] + R1[::-1][1:] + R1[1:] + R1[::-1][1:]          # 6 legs, fatigued walker
fat = replace(A.PRESETS["fatigued"], max_slope_deg=P.max_slope_deg)   # isolate time/energy: route R1 is planned for the nominal 25 deg limit
expected.append(("B9 long fatigued route (time)", long_route, replace(fat, energy_budget_kj=1e6), "CS-05"))
expected.append(("B10 long fatigued route (energy)", long_route, replace(fat, eva_time_h=100.0), "CS-06"))

assert len(expected) == 16
for name, route, prof, rule in expected:
    d, v = decide(route, prof)
    check(f"{name}: NO-GO by {rule}", d["decision"] == "NO-GO" and d["rule"] == rule,
          f"got {d['decision']} {d['rule']} failed={d['rules_failed']}")

# good routes are GO, with a timeline bar
for name, route in (("R1", R1), ("R2", R2)):
    d, v = decide(route); check(f"good route {name}: GO", d["decision"] == "GO" and d["rule"] is None and d["timeline"]["limit_s"] == 8 * 3600, d["text"])

# plan-time hazard rule
mask = np.zeros((H, W), bool); mask[R1[len(R1) // 2] // W, R1[len(R1) // 2] % W] = True
d, v = decide(R1, hazard_blocked=mask); check("route through a dust-core cell: NO-GO by HZ-1", d["decision"] == "NO-GO" and d["rule"] == "HZ-1", d["text"])
# priority: a steep cell (crew safety) and a teleport (system) in one route -> both fail, crew safety decides
steep_cell = next(c for c in expected[1][1] if steep(c // W, c % W))
both = R1[:50] + [steep_cell] + R1[50:]                     # steep cell is not next to R1[49]: also a discontinuity
d, v = decide(both)
check("crew-safety rule outranks a system rule (CS-01 decides over SY-03)",
      d["rule"] == "CS-01" and "SY-03" in d["rules_failed"] and d["tier"] == 1, f"{d['rule']} {d['rules_failed']}")

# walk-time ABORT
check("walk: all fine -> GO", SV.walk_decision(600, 500, False, 30.0, False)["decision"] == "GO")
check("walk: negative time margin -> ABORT AB-01", SV.walk_decision(-1, 500, False, 30.0)["rule"] == "AB-01")
check("walk: negative energy margin -> ABORT AB-01", SV.walk_decision(100, -5, False, 30.0)["rule"] == "AB-01")
check("walk: dust over walker -> ABORT AB-02", SV.walk_decision(600, 500, True, 30.0)["rule"] == "AB-02")
check("walk: night -> ABORT AB-03", SV.walk_decision(600, 500, False, -2.0)["rule"] == "AB-03")
check("walk: SEP alert -> ABORT AB-04", SV.walk_decision(600, 500, False, 30.0, True)["rule"] == "AB-04")
w = SV.walk_decision(-1, -1, True, -1.0, True)
check("walk: several -> highest priority first (crew safety AB-01)", w["rule"] == "AB-01" and w["rules_triggered"][0] == "AB-01", str(w["rules_triggered"]))

# every check in the validator source maps to exactly one rule, and every mapped check exists in the source
src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "safety_validator.py")).read()
used = set(re.findall(r'add\("([a-z_]+)"', src))
owners = {c: [rid for rid, r in SV.RULES.items() if c in r["checks"]] for c in used}
check("every validator check maps to exactly one rule ID", all(len(o) == 1 for o in owners.values()), str({c: o for c, o in owners.items() if len(o) != 1}))
check("every rule's checks exist in the validator", set(SV.CHECK_TO_RULE) <= used, str(set(SV.CHECK_TO_RULE) - used))
# polyline validator violations carry rule IDs too
pv = SV.validate_polyline([R1[0], R1[-1]], grid, P)
check("validate_polyline violations carry rule IDs", all("rule" in x for x in pv["violations"]), str(pv["violations"][:1]))

for s, name, info in results: print(s, name, "" if s == "PASS" else "-- " + info)
print(f"{sum(r[0] == 'PASS' for r in results)}/{len(results)} passed")
sys.exit(0 if all(r[0] == "PASS" for r in results) else 1)
