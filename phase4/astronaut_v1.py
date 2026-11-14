"""
MARSWALK Phase 4 - simulated astronaut + suit model (Module 4).

SIMULATED: every number here is a configurable competition assumption. None of it is validated
astronaut physiology or spacesuit performance.

Units: m, s, kJ, kg, degrees for slopes, grade = rise/run (dimensionless, tan of slope angle).
"""
from dataclasses import dataclass, replace, asdict
import math

G_MARS, G_EARTH = 3.71, 9.81
RAD_RATE_UGY_H = 6.45          # RAD campaign mean, tissue-like; dose = rate x time outside (never mapped in space)


@dataclass(frozen=True)
class Profile:
    """SIMULATED walker profile (not validated physiology)."""
    name: str = "nominal"
    mass_kg: float = 150.0               # astronaut + suit + kit, total
    suit_mass_kg: float = 60.0           # included in mass_kg
    walk_speed_flat_mps: float = 0.9     # suited speed on flat ground (unsuited Tobler peak is ~1.67 m/s)
    max_slope_deg: float = 25.0          # hard limit on the steepest 1 m slope in a cell
    rough_max_m: float = 0.35            # hard limit on 5 m roughness
    valid_frac_min: float = 0.5          # hard limit on terrain data confidence
    eva_time_h: float = 8.0
    energy_budget_kj: float = 3000.0     # locomotion energy allowance (SIMULATED), not total metabolic
    return_reserve_frac: float = 0.25    # fraction of time/energy kept free beyond the return leg
    dose_budget_uGy: float = 250.0       # per-EVA configurable dose limit (SIMULATED limit)
    # fatigue: state f in [0,1]; rises with energy spent, recovers during rest
    fatigue_capacity_kj: float = 4000.0  # energy that would take f from 0 to 1 with no rest
    fatigue_speed_loss: float = 0.35     # speed multiplier = 1 - loss * f
    fatigue_recovery_per_h: float = 0.5  # f units recovered per hour of rest
    climb_weight: float = 3.0            # planner only: equivalent metres of cost per metre climbed
    cost_weights: tuple = (0.35, 0.15, 0.15, 0.15, 0.20)   # w_t, w_x, w_e, w_m, w_u (see costs.py)
    SIMULATED: bool = True


PRESETS = {
    "nominal": Profile(),
    "conservative": Profile(name="conservative", mass_kg=160.0, suit_mass_kg=65.0, walk_speed_flat_mps=0.75,
                            max_slope_deg=18.0, rough_max_m=0.25, eva_time_h=6.0, energy_budget_kj=2200.0,
                            return_reserve_frac=0.40, dose_budget_uGy=150.0,
                            cost_weights=(0.40, 0.15, 0.15, 0.10, 0.20)),
    "fatigued": Profile(name="fatigued", mass_kg=150.0, walk_speed_flat_mps=0.65, max_slope_deg=20.0,
                         rough_max_m=0.30, eva_time_h=4.0, energy_budget_kj=1500.0, return_reserve_frac=0.30,
                         fatigue_capacity_kj=1800.0, fatigue_speed_loss=0.5),
}


def get_profile(name="nominal") -> Profile:
    return PRESETS[name]


def _clip_grade(g):
    return max(-0.6, min(0.6, g))


def step_speed_mps(profile: Profile, grade: float, fatigue: float = 0.0) -> float:
    """Tobler's hiking function, v = 6 exp(-3.5 |g + 0.05|) km/h (Tobler 1993), rescaled so a flat
    grade gives profile.walk_speed_flat_mps, then slowed by fatigue. Floor 0.05 m/s."""
    g = _clip_grade(grade)
    rel = math.exp(-3.5 * abs(g + 0.05)) / math.exp(-3.5 * 0.05)
    return max(0.05, profile.walk_speed_flat_mps * rel * (1.0 - profile.fatigue_speed_loss * min(max(fatigue, 0.0), 1.0)))


def _minetti_walk_j_per_kg_m(i: float) -> float:
    # Minetti et al. 2002, J Appl Physiol 93:1039, cost of walking vs gradient i (Earth, 1 g), valid |i| <= 0.45
    i = max(-0.45, min(0.45, i))
    return 280.5 * i**5 - 58.7 * i**4 - 76.8 * i**3 + 51.9 * i**2 + 19.6 * i + 2.5


def step_energy_kj(profile: Profile, dist_m: float, grade: float) -> float:
    """Simplified metabolic energy for walking dist_m along a grade (SIMULATED).
    Minetti 2002 cost of walking (J/kg/m) x total mass (suit incl.) x dist, scaled by g_Mars/g_Earth
    (a crude assumption: real reduced-gravity walking cost does not scale fully linearly). Floor of
    0.25 J/kg/m (Earth) avoids unphysical near-zero/negative downhill cost."""
    c = max(0.25, _minetti_walk_j_per_kg_m(_clip_grade(grade)))
    return c * (G_MARS / G_EARTH) * profile.mass_kg * dist_m / 1000.0


def fatigue_update(profile: Profile, fatigue: float, energy_kj: float = 0.0, rest_s: float = 0.0) -> float:
    """f' = clip(f + energy/capacity - recovery_rate * rest_hours, 0, 1)."""
    f = fatigue + energy_kj / profile.fatigue_capacity_kj - profile.fatigue_recovery_per_h * rest_s / 3600.0
    return min(1.0, max(0.0, f))


def dose_uGy(time_s: float) -> float:
    return RAD_RATE_UGY_H * time_s / 3600.0


def route_resources(profile: Profile, dists, grades, with_fatigue=True):
    """Accumulate time (s), energy (kJ), dose (uGy), final fatigue along a list of (dist, grade) steps."""
    t = e = 0.0; f = 0.0
    for d, g in zip(dists, grades):
        v = step_speed_mps(profile, g, f if with_fatigue else 0.0)
        de = step_energy_kj(profile, d, g)
        t += d / v; e += de
        if with_fatigue: f = fatigue_update(profile, f, de)
    return dict(time_s=t, energy_kj=e, dose_uGy=dose_uGy(t), fatigue=f)
