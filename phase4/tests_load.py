"""Carried-load tests for phase4/astronaut.py: python phase4/tests_load.py (from the repo root)."""
import sys, os
from dataclasses import replace
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from phase4 import astronaut as A

res = []
def check(name, cond, info=""):
    res.append(("PASS" if cond else "FAIL", name, info))

# 1. carried_kg = 0 reproduces the v2 outputs computed BEFORE the load change (exact floats, 10 m steps)
GR = (-0.3, -0.1, 0.0, 0.1, 0.2, 0.35)
BASE = {
 ("nominal", "mars"): [6.695928865298609, 5.604070760869564, 5.745978260869565, 7.178133016515068, 11.421522351537142, 19.12638467171492],
 ("nominal", "moon"): [6.935756365298608, 5.684013260869565, 5.745978260869565, 6.93472017247837, 8.349088291904113, 11.33765388043052],
 ("conservative", "mars"): [7.566384646044904, 6.360375416666666, 6.510166666666666, 7.928176820919088, 12.554511103741131, 21.03158726358099],
 ("conservative", "moon"): [7.819535896044904, 6.444759166666665, 6.510166666666666, 7.671241041102574, 9.311386263017383, 12.81014920611413],
 ("fatigued", "mars"): [7.604053884340582, 6.242080354251012, 6.383987854251013, 7.818077901409529, 12.329647370579114, 20.661532645588856],
 ("fatigued", "moon"): [7.843881384340582, 6.3220228542510135, 6.383987854251013, 7.574665057372831, 9.257213310946085, 12.872801854304452],
}
ok = True
for (n, b), vals in BASE.items():
    p = A.get_profile(n, b)
    got = [A.step_energy_kj(p, 10.0, g) for g in GR]
    got0 = [A.step_energy_kj(p, 10.0, g, carried_kg=0.0) for g in GR]
    ok &= got == vals and got0 == vals
check("carried_kg=0 reproduces pre-change step_energy_kj exactly (3 presets x 2 bodies x 6 grades)", ok)
check("step_speed_mps unchanged by load and by carried_kg=0", A.step_speed_mps(A.get_profile("nominal"), 0.1, 0.2) == 0.5898239310945631
      and A.step_speed_mps(A.with_load(A.get_profile("nominal"), 30), 0.1, 0.2) == 0.5898239310945631)
check("Profile default carried_kg is 0", A.Profile().carried_kg == 0.0 and A.Profile().total_mass_kg == 150.0)

# 2. monotonic in load, every grade, both bodies
mono = True
for body in ("mars", "moon"):
    for g in GR:
        prev = -1.0
        for L in (0, 5, 10, 20, 30, 50, 80):
            e = A.step_energy_kj(A.with_load(A.get_profile("nominal", body), L), 10.0, g)
            mono &= e > prev; prev = e
check("energy strictly increases with carried load (0..80 kg, grades -0.3..0.35, Mars and Moon)", mono)

# 3. published data point: Wickman & Luna 1995, 1.2 m/s level, no-load intercept and slope per unit load factor (kcal/kg/min)
for body, icpt, slope in (("mars", 0.060, 0.032), ("moon", 0.053, 0.017)):
    p = replace(A.get_profile("nominal", body), walk_speed_flat_mps=1.2)
    for F in (1.5, 2.0):
        L = (F - 1.0) * p.body_mass_kg
        ratio = A.step_energy_kj(A.with_load(p, L), 100.0, 0.0) / A.step_energy_kj(p, 100.0, 0.0)
        pub = (icpt + slope * (F - 1.0)) / icpt
        check(f"{body} level 1.2 m/s, load factor {F}: model/no-load ratio {ratio:.4f} vs Wickman&Luna {pub:.4f}", abs(ratio - pub) < 1e-9)
p1 = A.load_k(1.0)
check("Earth k (1.087) within 10 % of the Pandolf 1977 walking-term proportionality (k = 1)", abs(p1 - 1.0) < 0.10, f"k_earth={p1:.3f}")
check("k(g) increases with gravity (0.32 Moon < 0.53 Mars < 1.09 Earth)", A.load_k(A.PHI_MOON) < A.load_k(A.PHI_MARS) < A.load_k(1.0))

# 4. vertical work: climbing a load costs more in absolute terms than the level penalty alone
pm = A.get_profile("nominal")
up = A.step_energy_kj(A.with_load(pm, 20), 10, 0.2) - A.step_energy_kj(pm, 10, 0.2)
lv = A.step_energy_kj(A.with_load(pm, 20), 10, 0.0) - A.step_energy_kj(pm, 10, 0.0)
check("20 kg adds more energy per 10 m on a 20 % climb than on the flat", up > lv, f"{up:.3f} vs {lv:.3f} kJ")
check("route_resources picks the load up through the profile", A.route_resources(A.with_load(pm, 20), [10.0] * 5, [0.1] * 5)["energy_kj"]
      > A.route_resources(pm, [10.0] * 5, [0.1] * 5)["energy_kj"])

for r in res: print(*r)
print(f"{sum(r[0] == 'PASS' for r in res)}/{len(res)}")
sys.exit(0 if all(r[0] == "PASS" for r in res) else 1)
