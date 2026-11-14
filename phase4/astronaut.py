"""
MARSWALK Phase 4 - simulated astronaut + suit model, v2 (Module 4). Previous model: astronaut_v1.py.

SIMULATED: this is a data-anchored SIMULATION, not validated astronaut physiology or suit performance.
v2 replaces the v1 "Earth Minetti x g ratio" energy with a model fitted to published suited, reduced-gravity
treadmill data (NASA JSC Mark III suit on the Pogo offload rig). Every constant carries a source and a
confidence in PARAM_SOURCES (see also docs/astronaut_model.md). Values read off figures are DIGITISED by eye
from the PDF figures (about +/-2 ml/kg/min) and are labelled as such.

Units: m, s, kJ, kg, grade = rise/run (tan of slope angle), VO2 in ml O2 / kg body mass / min.
Public API is unchanged from v1: Profile, PRESETS, get_profile, step_speed_mps, step_energy_kj,
fatigue_update, dose_uGy, route_resources, RAD_RATE_UGY_H, G_MARS, G_EARTH. New: body="mars"|"moon".
"""
from dataclasses import dataclass, replace, asdict
from bisect import bisect_right
from functools import lru_cache
import math

G_MARS, G_EARTH, G_MOON = 3.71, 9.81, 1.62
BODIES = {"mars": G_MARS, "moon": G_MOON}
RAD_RATE_UGY_H = 6.45          # RAD campaign mean, tissue-like; dose = rate x time outside (never mapped in space)

# ---------------------------------------------------------------- published / digitised data tables
J_PER_ML_O2 = 20.1             # J per ml O2 (RER ~0.85). Checked against Walkback: 599 kcal/h at ~25.5 ml/kg/min x 81.4 kg
REST_VO2 = 3.5                 # ml/kg/min, "equivalent to resting metabolic rate" (IST-1, Gernhardt 2008, p.4)
SUBJECT_MASS_REF_KG = 81.4     # Walkback subject mean body mass (Norcross 2008 slide 4)
PHI_MOON, PHI_MARS = G_MOON / G_EARTH, G_MARS / G_EARTH

# Suited level-walking gross VO2 vs speed, 1/6 g, MKIII, n=6 (Norcross 2008 slide 11 "Moon, suited" curve).
# DIGITISED: (speed m/s, VO2 ml/kg/min). mph->m/s x0.44704. First point is the resting anchor.
_MOON_SUITED = ((0.0, REST_VO2), (0.76, 15.5), (0.89, 17.0), (1.12, 20.5), (1.34, 23.5), (1.56, 25.0),
                (1.79, 26.5), (2.24, 29.5), (2.68, 31.0))
_MOON_VMAX = 2.68              # highest suited speed tested at 1/6 g (6 mph)
# Suit-limited Mars-minus-Moon excess in suited level VO2 (Norcross 2008 slides 11 and 12, digitised).
# Zero below ~4 km/h (IST-1: weight effect not significant below 4.0 km/h, diff 2.85 < 3.5 ml/kg/min).
# Mars suited was only tested at 2.4-3.4 mph (1.07-1.52 m/s); "extremely limited on Mars" (slide 15).
_MARS_EXCESS = ((0.0, 0.0), (0.90, 0.0), (1.07, 2.3), (1.25, 3.5), (1.34, 5.5), (1.52, 16.0))
_MARS_VMAX = 1.52

# Incline: suited VO2 above level at the same gravity, vs grade (0, 10, 20, 30 %) at five gravity levels.
# Norcross et al. NASA/TP-2010-216125 (IST-2), Fig. 36 p.37, DIGITISED and tied to the text on p.37 (high-minus-low
# weight difference 1.9, 3.5, 8.7, 17.0 ml/kg/min at 0, 10, 20, 30 % grade). Tested at the subject's lowest walking
# speed (PTS - 0.7 m/s, 0.56-0.97 m/s, p.70), reference V_REF; suit pressure 29.6 kPa.
_INCL_GRADES = (0.0, 0.10, 0.20, 0.30)
_INCL_G = (0.12, 0.17, 0.22, 0.27, 0.32)
_INCL_DVO2 = {0.12: (0.0, 0.0, 1.0, 2.5), 0.17: (0.0, 1.5, 3.5, 6.0), 0.22: (0.0, 1.5, 4.5, 9.0),
              0.27: (0.0, 2.0, 6.0, 13.5), 0.32: (0.0, 2.0, 8.5, 17.5)}
V_REF = 0.80                   # m/s, centre of the 0.56-0.97 m/s test range
# The incline term is scaled by v/V_REF: the paper's own regression (Eq. 1, p.70) is linear in speed x grade.

# Downhill. No suited downhill data exist (Walkback slide 16: "No hills"; TP-2010-216125 tested inclines only).
# Anchor: Minetti et al. 2002 abstract (Earth, unsuited): Cw level 1.64, -0.10 -> 0.81, -0.45 -> 3.46 J/kg/m.
# Energy recovered per metre descended / mechanical work released = (1.64-0.81)/(9.81*0.10) = 0.85.
# Steep-slope braking cost = work absorbed / eccentric efficiency: 9.81*0.10/0.81 = 1.21 and 9.81*0.45/3.46 = 1.28 -> 1.25.
DOWNHILL_RECOVERY = 0.85
ECCENTRIC_EFF = 1.25
SUIT_DOWNHILL_DERATE = 0.5     # ASSUMPTION (no suited downhill data): only half the Earth recovery is credited

# Carried load (equipment, sample bags, tools) on top of astronaut + suit + kit. Default 0 kg leaves every v2 result unchanged.
# Level walking: energy per metre is scaled by (1 + k(g) * L / body_mass), the "load factor" F = (body + load) / body of
# Wickman & Luna 1995 (Aerospace Medical Assoc. annual meeting, Anaheim, "Locomotion While Load-Carrying in Reduced
# Gravities"; pooled results text and Figs 2-3). Their fitted lines at 1.2 m/s (kcal/kg/min per unit of load factor, and the
# no-load intercept): Moon 0.017 / 0.053, Mars 0.032 / 0.060, Earth 0.075 / 0.069. The ratio slope/intercept is k(g):
# the relative cost increase per unit of L / body mass. Unsuited subjects on an underwater treadmill (n=6, torso loads up to
# 80 % of body weight on Mars, 270 % on the Moon, 45 % at 1 g); applying the ratio to the SUITED cost is an ASSUMPTION.
_LOAD_PHI = (PHI_MOON, PHI_MARS, 1.0)
_LOAD_K = (0.017 / 0.053, 0.032 / 0.060, 0.075 / 0.069)   # 0.321, 0.533, 1.087
LOAD_TESTED_FRAC_MARS = 0.80   # largest carried / body weight tested at 3/8 g (Wickman & Luna 1995); beyond is extrapolation
# Climbing and descending work: vertical work is m g h for body and load alike, so the incline term (and the downhill recovery /
# braking terms) scale by (1 + L / M_sys), M_sys = mass_kg (astronaut + suit + kit), independent of g. Pandolf et al. 1977
# (J Appl Physiol 43:577) has the same structure: grade term eta (W+L)(1.5 V^2 + 0.35 V G), proportional to total mass.
# Using M_sys rather than body mass is an ASSUMPTION (the incline data of TP-2010 were measured with the suit on).
# No speed penalty with load: no suited or reduced-gravity source gives one (Wickman & Luna tested fixed speeds).

PARAM_SOURCES = {
    "suited_level_vo2_vs_speed_moon": dict(
        value="table _MOON_SUITED, 15.5 ml/kg/min at 0.76 m/s to 31 at 2.68 m/s", confidence="medium",
        evidence="Norcross et al. 2008, NTRS 20080014853, slide 11 (curve digitised, +/-2 ml/kg/min); n=6; checked against slide 14 (3.9 mph, 599 kcal/h)"),
    "suited_level_vo2_mars_excess": dict(
        value="table _MARS_EXCESS, +2.3 at 1.07 m/s to +16 at 1.52 m/s over the lunar curve", confidence="low-medium",
        evidence="NTRS 20080014853 slides 11-12 (digitised); Mars suited tested only 2.4-3.4 mph; below 4 km/h weight effect 'not significant' (Gernhardt 2008 IST-1, NTRS 20080013604, p.7)"),
    "gravity_interpolation": dict(
        value="linear in g/g_earth between 1/6 g (0.165) and 3/8 g (0.378) on the speed-dependent excess; 0 excess at slow speed",
        confidence="low", evidence="two gravity points only; level slow-speed VO2 is flat in g in TP-2010-216125 Fig. 36 (0 % grade, ~14-16)"),
    "incline_dvo2": dict(
        value="table _INCL_DVO2, 0.32 g: +2/+8.5/+17.5 ml/kg/min at 10/20/30 % grade", confidence="medium (<=0.32 g), low at 0.378 g (extrapolated)",
        evidence="Norcross et al. 2010, NASA/TP-2010-216125 (NTRS 20110003409), Fig. 36 p.37 + text p.37; n=6; speeds 0.56-0.97 m/s"),
    "incline_speed_scaling": dict(value="dVO2 proportional to v x grade", confidence="medium",
        evidence="TP-2010-216125 Eq. 1 p.70 (regression on V x G, pseudo-R2 0.668)"),
    "downhill_recovery_and_braking": dict(
        value="recovery 0.85, eccentric efficiency 1.25, suit derate 0.5", confidence="low",
        evidence="Minetti et al. 2002, J Appl Physiol 93:1039 (abstract numbers, Earth unsuited); derate is an assumption"),
    "carried_load_level_k": dict(
        value="level cost x (1 + k(g) L/body_mass); k = 0.321 (Moon), 0.533 (Mars), 1.087 (Earth), linear in g/g_earth between them",
        confidence="low-medium (Mars, unsuited, 1.2 m/s); low as applied to a suit",
        evidence="Wickman & Luna 1995, Aerospace Medical Assoc. meeting, pooled results (slopes 0.017/0.032/0.075 over intercepts 0.053/0.060/0.069 kcal/kg/min at 1.2 m/s); n=6 unsuited, underwater; suited application is an assumption"),
    "carried_load_vertical": dict(
        value="incline term and downhill recovery / braking terms x (1 + L/mass_kg)", confidence="medium (physics, Pandolf 1977 structure), low (choice of M_sys)",
        evidence="Pandolf, Givoni & Goldman 1977, J Appl Physiol 43:577: M = 1.5W + 2.0(W+L)(L/W)^2 + eta (W+L)(1.5V^2 + 0.35VG); grade term proportional to W+L"),
    "carried_load_speed": dict(value="no speed change with load", confidence="none", evidence="no sourced load-speed relation for suited or reduced-gravity walking; ASSUMPTION"),
    "j_per_ml_o2": dict(value=J_PER_ML_O2, confidence="high", evidence="standard RER~0.85 value; reproduces 599 kcal/h of Walkback slide 14"),
    "rest_vo2": dict(value=REST_VO2, confidence="high", evidence="NTRS 20080013604 p.4 (IST-1)"),
    "walk_speed_flat_mps": dict(value="0.9 nominal, 0.75 conservative, 0.65 fatigued", confidence="medium",
        evidence="Apollo 12/14 0.56-0.84 m/s; ARGOS suited 0.74-0.83 m/s (Schlotman 2023, via Pena-Asensio 2024); Artemis ConOps 2 km/h; docs/research/eva_traverse_planning.md"),
    "speed_vs_grade": dict(value="Tobler 1993 shape rescaled to profile speed, capped at tested suited maximum", confidence="low",
        evidence="Tobler 1993 (terrestrial hiking); Apollo speed-vs-slope fit has R2=0.03 so no better suited law exists"),
    "speed_cap_mps": dict(value="Mars 1.52 (3.4 mph), Moon 2.68 (6 mph)", confidence="medium",
        evidence="highest suited speeds tested, NTRS 20080014853 slides 11-12; Mars: 'extremely limited' (slide 15)"),
    "walk_run_transition": dict(value="Froude 0.5: v = sqrt(0.5 g L), L = 0.9 m -> 1.29 m/s Mars, 0.85 m/s Moon (cross-check only, not used)",
        confidence="medium (law), low (L)", evidence="Kram, Domingo & Ferris 1997, J Exp Biol 200:821 (abstract): transition at ~Fr 0.5 in reduced g. Suited Walkback walked 3.9 mph at 1/6 g, so suit/Pogo data exceed the Froude walk speed"),
    "suit_mass_kg": dict(value="60 nominal", confidence="medium",
        evidence="EMU-like 61 kg (NTRS 20080013604 p.2: PLSS mock-up 18 + gimbal 41 simulates 61 kg EMU); test MKIII used 121 kg weight/mass. Energy data are for the MKIII at 121 kg; suit mass only changes body mass here"),
    "eva_time_h": dict(value="8 nominal, 6 conservative, 4 fatigued", confidence="low-medium",
        evidence="Apollo 12 EVA 2 2 h 45 min (Pena-Asensio 2024 s.4.2); Walkback 95.8 min for 10 km (NTRS 20080014853 slide 14). Preset caps are assumptions"),
    "energy_budget_kj": dict(value="8000 nominal (8 h x 233 kcal/h Apollo mean = 7.8 MJ), 5800 conservative, 3900 fatigued", confidence="low",
        evidence="Apollo mean 233 kcal/h vs walkback 599 kcal/h (NTRS 20080014853 slide 14); budget is gross metabolic energy for walking, not total consumables"),
    "fatigue_params": dict(value="capacity 1.33 x budget, speed loss 0.35, recovery 0.5/h", confidence="none",
        evidence="unchanged v1 assumptions; no source. Walkback subjects held ~51 % VO2pk, RPE 12 for 96 min without stopping"),
    "rad_rate_uGy_h": dict(value=RAD_RATE_UGY_H, confidence="high (surface mean)", evidence="MSL RAD campaign mean as in v1"),
}


def _pl(x, xs, ys, extrap=False):
    """Piecewise-linear interpolation; clamps at the ends unless extrap (then extends the end segments)."""
    n = len(xs)
    if x <= xs[0]:
        if not extrap: return ys[0]
        i = 0
    elif x >= xs[-1]:
        if not extrap: return ys[-1]
        i = n - 2
    else:
        i = bisect_right(xs, x) - 1
    return ys[i] + (ys[i + 1] - ys[i]) * (x - xs[i]) / (xs[i + 1] - xs[i])


_MV = tuple(p[0] for p in _MOON_SUITED); _MY = tuple(p[1] for p in _MOON_SUITED)
_XV = tuple(p[0] for p in _MARS_EXCESS); _XY = tuple(p[1] for p in _MARS_EXCESS)


@dataclass(frozen=True)
class Profile:
    """SIMULATED walker profile (data-anchored, not validated physiology). See PARAM_SOURCES."""
    name: str = "nominal"
    body: str = "mars"                   # "mars" (3.71 m/s2) or "moon" (1.62 m/s2); sets gravity for energy/speed cap
    mass_kg: float = 150.0               # astronaut + suit + kit, total
    suit_mass_kg: float = 60.0           # included in mass_kg; body mass = mass_kg - suit_mass_kg scales energy
    walk_speed_flat_mps: float = 0.9     # suited speed on flat ground
    max_slope_deg: float = 25.0          # hard limit on the steepest 1 m slope in a cell
    rough_max_m: float = 0.35            # hard limit on 5 m roughness
    valid_frac_min: float = 0.5          # hard limit on terrain data confidence
    eva_time_h: float = 8.0
    energy_budget_kj: float = 8000.0     # gross metabolic energy allowance for the EVA (SIMULATED), see PARAM_SOURCES
    return_reserve_frac: float = 0.25    # fraction of time/energy kept free beyond the return leg
    dose_budget_uGy: float = 250.0       # per-EVA configurable dose limit (SIMULATED limit)
    fatigue_capacity_kj: float = 10700.0 # energy that would take f from 0 to 1 with no rest (1.33 x budget, as v1)
    fatigue_speed_loss: float = 0.35     # speed multiplier = 1 - loss * f
    fatigue_recovery_per_h: float = 0.5  # f units recovered per hour of rest
    climb_weight: float = 3.0            # planner only: equivalent metres of cost per metre climbed
    cost_weights: tuple = (0.35, 0.15, 0.15, 0.15, 0.20)   # w_t, w_x, w_e, w_m, w_u (see costs.py)
    suit_downhill_derate: float = SUIT_DOWNHILL_DERATE
    carried_kg: float = 0.0              # extra carried equipment / samples, NOT part of mass_kg; 0 = unchanged v2 results
    avoid_boulders: bool = True          # planner blocks and validator rejects (CS-02, reason boulder) cells near HiRISE-detected boulders; False = old behaviour
    SIMULATED: bool = True

    @property
    def gravity(self) -> float:
        return BODIES[self.body]

    @property
    def body_mass_kg(self) -> float:
        return max(40.0, self.mass_kg - self.suit_mass_kg)

    @property
    def total_mass_kg(self) -> float:
        return self.mass_kg + max(0.0, self.carried_kg)

    @property
    def speed_cap_mps(self) -> float:
        return _MARS_VMAX if self.gravity >= 0.5 * (G_MARS + G_MOON) else _MOON_VMAX

    @staticmethod
    def provenance() -> dict:
        return PARAM_SOURCES


PRESETS = {
    "nominal": Profile(),
    "conservative": Profile(name="conservative", mass_kg=160.0, suit_mass_kg=65.0, walk_speed_flat_mps=0.75,
                            max_slope_deg=18.0, rough_max_m=0.25, eva_time_h=6.0, energy_budget_kj=5800.0,
                            return_reserve_frac=0.40, dose_budget_uGy=150.0, fatigue_capacity_kj=7700.0,
                            cost_weights=(0.40, 0.15, 0.15, 0.10, 0.20)),
    "fatigued": Profile(name="fatigued", mass_kg=150.0, walk_speed_flat_mps=0.65, max_slope_deg=20.0,
                         rough_max_m=0.30, eva_time_h=4.0, energy_budget_kj=3900.0, return_reserve_frac=0.30,
                         fatigue_capacity_kj=4700.0, fatigue_speed_loss=0.5),
}


def get_profile(name="nominal", body=None) -> Profile:
    p = PRESETS[name]
    return replace(p, body=body) if body and body != p.body else p


def _clip_grade(g):
    return max(-0.6, min(0.6, g))


def with_load(profile: Profile, carried_kg: float) -> Profile:
    """Copy of the profile carrying carried_kg (kg of equipment / samples on top of astronaut + suit + kit)."""
    return replace(profile, carried_kg=max(0.0, float(carried_kg)))


def load_k(phi: float) -> float:
    """Relative level-walking cost increase per unit of L / body_mass at gravity fraction phi (Wickman & Luna 1995)."""
    return _pl(phi, _LOAD_PHI, _LOAD_K)


def step_speed_mps(profile: Profile, grade: float, fatigue: float = 0.0, carried_kg=None) -> float:
    """Tobler's hiking function, v = 6 exp(-3.5 |g + 0.05|) km/h (Tobler 1993), rescaled so a flat grade gives
    profile.walk_speed_flat_mps, capped at the highest suited speed tested for the body (Mars 1.52, Moon 2.68 m/s),
    then slowed by fatigue. Floor 0.05 m/s. Low confidence (see PARAM_SOURCES). carried_kg is accepted for API symmetry
    with step_energy_kj; it has NO effect on speed (no sourced load-speed relation, see PARAM_SOURCES)."""
    g = _clip_grade(grade)
    rel = math.exp(-3.5 * abs(g + 0.05)) / math.exp(-3.5 * 0.05)
    v = min(profile.walk_speed_flat_mps * rel, profile.speed_cap_mps)
    return max(0.05, v * (1.0 - profile.fatigue_speed_loss * min(max(fatigue, 0.0), 1.0)))


def suited_level_vo2(v: float, body: str = "mars") -> float:
    """Suited gross VO2 (ml/kg/min) for level walking at speed v (m/s) and the body's gravity. Interpolates the 1/6 g
    curve and the Mars excess linearly in g/g_earth (clamped between 1/6 g and 3/8 g)."""
    return _vo2_level(v, BODIES[body] / G_EARTH)


def _vo2_level(v, phi):
    base = _pl(v, _MV, _MY, extrap=True)
    w = min(max((phi - PHI_MOON) / (PHI_MARS - PHI_MOON), 0.0), 1.0)
    return base + w * _pl(v, _XV, _XY)


@lru_cache(maxsize=16)
def _incline_nodes(phi):
    """dVO2 (ml/kg/min above level, at V_REF) at grades _INCL_GRADES for gravity fraction phi (linear in g between the
    five tested levels, linear extrapolation beyond 0.32 g toward 3/8 g, floored at 0)."""
    gs = _INCL_G
    out = []
    for k in range(len(_INCL_GRADES)):
        ys = tuple(_INCL_DVO2[g][k] for g in gs)
        out.append(max(0.0, _pl(phi, gs, ys, extrap=True)))
    return tuple(out)


def incline_dvo2(grade: float, phi: float) -> float:
    """dVO2 above level for uphill grade (>=0) at V_REF; grades above 30 % extend the 20-30 % slope (no data)."""
    return max(0.0, _pl(min(grade, 0.6), _INCL_GRADES, _incline_nodes(phi), extrap=True))


def step_energy_kj(profile: Profile, dist_m: float, grade: float, carried_kg=None) -> float:
    """Gross metabolic energy (kJ) to walk dist_m along a grade, suited (SIMULATED, data-anchored).
    Level cost: suited VO2 at the speed the walker actually uses on that grade, gravity-interpolated between the 1/6 g
    and 3/8 g Mark III data. Uphill: + dVO2(grade, g) x v/V_REF (TP-2010-216125 Fig. 36). Downhill: level cost minus
    derated recovered work, floored by eccentric braking cost g|i|/1.25 and by resting cost (Minetti 2002 numbers).
    Energy = body mass x J/ml x VO2 / v per metre. Fatigue-free speed is used (the API has no fatigue argument).
    Carried load L (carried_kg, default profile.carried_kg): the level term is scaled by 1 + k(g) L / body_mass (Wickman &
    Luna 1995) and the incline / downhill work terms by 1 + L / mass_kg (Pandolf 1977 structure); L = 0 changes nothing."""
    L = max(0.0, profile.carried_kg if carried_kg is None else carried_kg)
    gr = _clip_grade(grade)
    v = step_speed_mps(profile, gr, 0.0)
    phi = profile.gravity / G_EARTH
    m_level = _vo2_level(v, phi)
    f_lev = 1.0 + load_k(phi) * L / profile.body_mass_kg      # level-walking load factor (Wickman & Luna 1995)
    f_vert = 1.0 + L / profile.mass_kg                        # vertical-work load factor (Pandolf 1977 structure)
    if gr >= 0.0:
        c = (m_level / v * f_lev + incline_dvo2(gr, phi) / V_REF * f_vert) * J_PER_ML_O2 / 60.0       # J/kg/m
    else:
        c0 = m_level / v * J_PER_ML_O2 / 60.0 * f_lev
        gi = profile.gravity * (-gr) * f_vert
        c = max(c0 - profile.suit_downhill_derate * DOWNHILL_RECOVERY * gi, gi / ECCENTRIC_EFF,
                REST_VO2 / v * J_PER_ML_O2 / 60.0)
    return c * profile.body_mass_kg * dist_m / 1000.0


def legacy_step_energy_kj(profile: Profile, dist_m: float, grade: float) -> float:
    """v1 model (Minetti 2002 Earth walking cost x total mass x g_ratio), kept only for before/after comparison."""
    i = max(-0.45, min(0.45, _clip_grade(grade)))
    c = max(0.25, 280.5 * i**5 - 58.7 * i**4 - 76.8 * i**3 + 51.9 * i**2 + 19.6 * i + 2.5)
    return c * (profile.gravity / G_EARTH) * profile.mass_kg * dist_m / 1000.0


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
