"""Refuge (walk-back to a parked rover) tests: python phase4/tests_refuge.py (from the repo root).
validate(..., refuge_cell=None) must be unchanged; a long route that fails the walk back to the start must pass when a rover
(point of refuge) is parked near its far end; unreachable or blocked refuges are CS-05 violations."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
from phase4 import costs, astar, astronaut as A, safety_validator as SV

grid = costs.load_grid(); W = grid["width"]; results = []
def check(name, cond, info=""): results.append(("PASS" if cond else "FAIL", name, info))

PN, PF = A.get_profile("nominal"), A.get_profile("fatigued")
R = astar.plan(grid, 400 * W + 200, 100 * W + 500, PF)["route"]          # 2.26 km; the fatigued profile cannot walk it out and back
d0 = SV.validate(R, grid, PF); d1 = SV.validate(R, grid, PF, refuge_cell=None)
check("refuge_cell=None leaves validate() unchanged (same violations and summary)", d0["violations"] == d1["violations"] and d0["summary"] == d1["summary"])
check("default: long route fails the walk back to the start (CS-05/CS-06 energy)", (not d0["ok"]) and d0["summary"]["checks_failed"] == ["energy_budget_with_return"], str(d0["summary"]["checks_failed"]))
r = SV.validate(R, grid, PF, refuge_cell=R[-1])
check("rover parked at the far end: same route passes", r["ok"], str(r["summary"]["checks_failed"]))
check("rover at the far end: worst abort is about the one-way trip, well under the round trip",
      r["summary"]["roundtrip_energy_kj"] < 0.6 * d0["summary"]["roundtrip_energy_kj"],
      f"{r['summary']['roundtrip_energy_kj']:.0f} kJ vs {d0['summary']['roundtrip_energy_kj']:.0f} kJ round trip")
check("summary says the walk back is measured to the refuge", r["summary"].get("walkback_to") == "refuge" and r["summary"]["refuge_cell"] == R[-1])
rs = SV.validate(R, grid, PF, refuge_cell=R[0])
check("refuge at the start: not worse than retracing the route (shortest path back, same rules)",
      rs["summary"]["roundtrip_energy_kj"] <= d0["summary"]["roundtrip_energy_kj"] * 1.001 and rs["summary"]["roundtrip_time_s"] <= d0["summary"]["roundtrip_time_s"] * 1.05,
      f"{rs['summary']['roundtrip_energy_kj']:.0f} vs {d0['summary']['roundtrip_energy_kj']:.0f} kJ")
check("refuge at the start keeps failing the long route", not rs["ok"])
rm = SV.validate(R, grid, PF, refuge_cell=R[len(R) // 2])
check("rover parked mid-route also passes (nearer refuge, both halves short)", rm["ok"], str(rm["summary"]["checks_failed"]))
bad = np.flatnonzero((grid["slope_max_deg"] > PF.max_slope_deg).ravel())[0]
rb = SV.validate(R, grid, PF, refuge_cell=int(bad))
check("rover on a cell the walker may not enter: CS-05 no_refuge_path", "no_refuge_path" in rb["summary"]["checks_failed"] and not rb["ok"]
      and SV.flight_decision(rb, PF)["rule"] in ("CS-05",), str(rb["summary"]["checks_failed"]))
check("no_refuge_path maps to CS-05", SV.CHECK_TO_RULE["no_refuge_path"] == "CS-05")
# energy ordering: the sum of per-step energy along the same short route is unchanged by the refuge option
short = R[:40]
a, b = SV.validate(short, grid, PF), SV.validate(short, grid, PF, refuge_cell=short[0])
check("short route, refuge = start: numbers within 2 % of the retrace", abs(b["summary"]["roundtrip_energy_kj"] / a["summary"]["roundtrip_energy_kj"] - 1) < 0.02,
      f"{b['summary']['roundtrip_energy_kj']:.1f} vs {a['summary']['roundtrip_energy_kj']:.1f}")
for s, name, info in results: print(s, name, "" if s == "PASS" else "-- " + info)
print(f"{sum(r[0] == 'PASS' for r in results)}/{len(results)} passed")
sys.exit(0 if all(r[0] == "PASS" for r in results) else 1)
