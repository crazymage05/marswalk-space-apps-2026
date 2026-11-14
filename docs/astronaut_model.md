# Astronaut model v2 (SIMULATED, data-anchored)

Code: `phase4/astronaut.py` (v2, also kept as `phase4/astronaut_v2.py` during the switch-over). Label stays SIMULATED: the numbers are fitted to a handful of published suited treadmill experiments, then extrapolated. Nothing here is validated Mars EVA physiology.

## Evidence labels

FULL = I downloaded the PDF and read the cited page or figure. DIGITISED = value read by eye off a figure in a FULL source (about +/-2 ml/kg/min). ABSTRACT = abstract only (Europe PMC / Crossref). MEMORY = not opened, not used for any number.

## Sources actually opened

| Short name | Reference | Read |
|---|---|---|
| Walkback | Norcross, Lee, De Witt, Klein, Wessel, Gernhardt, "Feasibility of Suited 10-km Ambulation Walkback on the Moon", Aerospace Medical Assoc. 2008, NTRS 20080014853 (slides) | FULL |
| IST-1 | Gernhardt, Norcross, Vos, "Integrated Suit Test 1", SAE/ICES paper, NTRS 20080013604 | FULL (text; figures not digitised) |
| IST-2 / TP-2010 | Norcross et al., "Metabolic Costs and Biomechanics of Inclined Ambulation and Exploration Tasks in a Planetary Suit", NASA/TP-2010-216125, NTRS 20110003409 | FULL |
| Kram 1997 | Kram, Domingo, Ferris, J Exp Biol 200:821-826 (PMID 9076966) | ABSTRACT |
| Minetti 2002 | Minetti, Moia, Roi, Susta, Ferretti, J Appl Physiol 93:1039-1046 (PMID 12183501) | ABSTRACT |
| Lessons learned | Norcross, Chappell, Gernhardt, NTRS 20100005154 | opened, not used for numbers |

Not found: Norcross 2010 "level ambulation in a planetary suit" as a separate full report (cited by others, not retrieved). The 3/8 g suited data come only from Walkback slide 12.

## Parameter table

VO2 is gross (includes resting 3.5 ml/kg/min), per kg of subject body mass, ml O2/kg/min. 1 ml O2 = 20.1 J (RER about 0.85, standard value). Check: Moon suited at 3.9 mph (1.74 m/s) reads 26.2 ml/kg/min on the digitised curve, times 81.4 kg subject mean gives 614 kcal/h; Walkback slide 14 reports 599 kcal/h (+2.5 %).

| Parameter | Value in model | Source, location | Evidence | Confidence |
|---|---|---|---|---|
| Suited level VO2 vs speed, 1/6 g | 15.5 (0.76 m/s), 17.0 (0.89), 20.5 (1.12), 23.5 (1.34), 25.0 (1.56), 26.5 (1.79), 29.5 (2.24), 31.0 (2.68); resting 3.5 at 0 | Walkback slide 11, "Moon, suited" curve | DIGITISED, n=6 | medium |
| Suited level VO2 vs speed, 3/8 g (Mars) | Moon curve plus excess: +0 up to 0.9 m/s, +2.3 (1.07), +3.5 (1.25), +5.5 (1.34), +16 (1.52) | Walkback slide 12 "Mars, suited" vs slide 11; "weight effect not significant below 4.0 km/h" IST-1 p.7 | DIGITISED | low-medium |
| Mars suited speed range tested | 2.4-3.4 mph (1.07-1.52 m/s); suit "extremely limited on Mars" | Walkback slides 12 and 15 | FULL | medium |
| Incline increment, suited | dVO2 above level at 10/20/30 % grade: 1/6 g (0.17) 1.5/3.5/6.0; 0.22 g 1.5/4.5/9.0; 0.27 g 2.0/6.0/13.5; 0.32 g 2.0/8.5/17.5 (0.12 g 0/1.0/2.5) | TP-2010 Fig. 36 p.37; text p.37 gives high-minus-low-weight differences 1.9, 3.5, 8.7, 17.0 at 0, 10, 20, 30 % | DIGITISED, tied to text | medium up to 0.32 g |
| Incline test speed | 0.56-0.97 m/s (PTS minus 0.7 m/s), grades 0-30 %, 29.6 kPa, n=6 | TP-2010 pp.5, 70 | FULL | high |
| Incline speed scaling | dVO2 proportional to v x grade | TP-2010 Eq. 1 p.70, pseudo-R2 0.668 | FULL | medium |
| Downhill | recovery 0.85 of released work; braking cost = work / 1.25; suit derate 0.5 | Minetti 2002 abstract: 1.64 J/kg/m level, 0.81 at -10 %, 3.46 at -45 % (9.81x0.10/0.81 = 1.21, 9.81x0.45/3.46 = 1.28) | ABSTRACT, derived | low (derate is an assumption) |
| Suited downhill data | none exist in the sources ("No hills", Walkback slide 16; TP-2010 inclines only) | | | none |
| Flat speed | 0.9 nominal, 0.75 conservative, 0.65 fatigued m/s | Apollo 12/14 0.56-0.84 m/s; ARGOS suited 0.74-0.83; Artemis ConOps 2 km/h (all via `docs/research/eva_traverse_planning.md`); Walkback sustained 3.9 mph on level treadmill | secondary | medium |
| Speed vs grade | Tobler shape, capped at highest tested suited speed (Mars 1.52, Moon 2.68 m/s) | Tobler 1993; Apollo speed-vs-slope R2 = 0.03 so no better law | | low |
| Walk-run transition | Fr = v^2/(gL) = 0.5, L = 0.9 m gives 1.29 m/s on Mars, 0.85 m/s on the Moon. Cross-check only, not used | Kram 1997 abstract (transition at about Fr 0.5 down to reduced g); L is my assumption | ABSTRACT | medium (law), low (L) |
| Suit mass | 60 kg (EMU-like, 61 kg); the tests used the Mark III at 121 kg weight and mass | IST-1 p.2 | FULL | medium |
| Subject mass | 81.4 +/- 7.8 kg, VO2pk 48.7 | Walkback slide 4 | FULL | high |
| Walkback totals | 10 km in 95.8 min, 51 % VO2pk, 599 kcal/h, 944 kcal; Apollo mean 233 kcal/h; O2 0.4 lb/h, cooling water 3.1 lb/h | Walkback slide 14 | FULL | high (lunar, level) |
| EVA time | 8 h nominal | Apollo EVAs hours long; presets are assumptions | | low |
| Energy budget | 8000 kJ nominal = 8 h x 233 kcal/h (Apollo mean, 7.8 MJ); 5800 conservative (6 h); 3900 fatigued (4 h) | Walkback slide 14 | derived | low |
| Fatigue | capacity 1.33 x budget, speed loss 0.35, recovery 0.5/h | unchanged v1 assumptions | none | none |
| Radiation rate | 6.45 uGy/h | RAD campaign mean (v1) | | high |

The same table is in code as `PARAM_SOURCES` in `phase4/astronaut.py`, and `Profile.provenance()` returns it.

## Method

1. Level cost. Interpolate the digitised 1/6 g suited curve over speed. Add the Mars excess weighted by `(g/g_earth - 0.165) / (0.378 - 0.165)`, clamped to 0..1. This is linear interpolation between the only two gravity levels measured at speed. The excess is zero below 0.9 m/s because IST-1 found no significant weight effect below 4 km/h.
2. Uphill. Add dVO2(grade, g) x v / 0.8 m/s. The dVO2 table is interpolated linearly over grade and over g between 0.12 and 0.32 g. For 3/8 g it is extrapolated linearly from the 0.27-0.32 g pair (+2.0, +11.4, +22.2 ml/kg/min at 10/20/30 %). Grades above 30 % extend the last segment.
3. Downhill. Cost = max(level - 0.5 x 0.85 x g|i|, g|i|/1.25, resting cost), in J/kg/m. Because Tobler slows the walker on steep slopes and gross cost includes standing metabolism, steep descents stay about as costly per metre as level ground. The model gives no big downhill saving.
4. Energy per metre = VO2 x 20.1 J/ml / (60 x v) x body mass, with body mass = mass_kg - suit_mass_kg (90 kg nominal). Speed is the fatigue-free speed (the API has no fatigue argument).
5. `body="moon"` uses 1.62 m/s2, the 1/6 g curve and the 2.68 m/s cap. `get_profile(name, body="moon")` returns the preset on the Moon.

## Mars adaptation

Mars is 3.71/9.81 = 0.378 g. The suited data at that gravity are one figure (Walkback slide 12), tested only at 1.07-1.52 m/s. Everything else at 3/8 g is interpolated or extrapolated from 1/6 g and 0.12-0.32 g data. Real Mars suits and boots, regolith and loads differ from a Mark III on a Pogo treadmill.

## Uncertainty

Digitising: +/-2 ml/kg/min, about 10-15 % of the level cost. Subject variation: n=6 male crew, no inference done in the sources. Mars excess above 1.3 m/s: the curve is steep (16 ml/kg/min over 0.2 m/s) and the planner never reaches it at 0.9 m/s nominal. Incline at 3/8 g: extrapolation beyond the tested 0.32 g, I would allow +/-30 % on the climbing increment. Downhill: unverified for a suit. Treat any route energy as +/-25 % at best.

## Before and after (A*, 8-neighbour, nominal profile, campaign cells)

| Route | v1 time | v1 energy | v2 time | v2 energy | Dose v1 / v2 (uGy) |
|---|---|---|---|---|---|
| Campaign direct (1076.5 m) | 1607 s | 264.0 kJ | 1609 s | 783.5 kJ | 2.879 / 2.883 |
| Campaign via waypoints (1693 m) | 2517 s | 380.0 kJ | 2525 s | 1238.2 kJ | 4.51 / 4.52 |

Energy per km on level ground, nominal: v1 142 kJ, v2 575 kJ (4.0 times). Time and dose barely change because the speed model is unchanged apart from the cap. v1 was a net Earth walking cost scaled by gravity on a 150 kg mass; v2 is gross suited cost, which the Walkback data show is much higher (2.4 times the unsuited weight-matched cost, slide 11) and includes resting metabolism.

Climbing is relatively cheaper in v2: at 20 % grade v2 costs 2.0 times flat, v1 3.1 times, so the `mobility` term in `costs.py` is weaker and routes may accept steeper climbs.

The energy budget had to be raised (3000 to 8000 kJ nominal) or every 1 km round trip would fail. The new budgets come from Apollo mean rate times EVA hours, not from tuning.

Random scenario pass rate (20 scenarios, 0.5-2 km, validator): nominal 20/20 (same), conservative 19/20 (was 20/20), fatigued 9/20 (was 11/20).

## Limits

- Gross VO2 on a treadmill with overhead offload. Pogo may give balance and, on slopes, artificial assistance (TP-2010 p.39).
- Male NASA crew, n=6, Mark III hard-torso suit, not xEMU or a Mars suit.
- No suited downhill data, no rough or loose ground, no thermal limit. Carried load comes only from an unsuited reduced-gravity study (see Carried load below). Walkback subjects named cooling as the limit.
- Speed vs grade is terrestrial. Apollo data show no slope trend.
- Fatigue parameters and the 1.33 capacity ratio have no source.
- Consumables (O2, cooling water) are not modelled; Walkback numbers are listed above for a later step.

## Carried load (equipment, sample bags, tools)

`Profile.carried_kg` (default 0, so every number above is unchanged) is mass carried on top of astronaut + suit + kit (`mass_kg`). It is read by `step_energy_kj`, therefore by `route_resources`, the A* metrics and the validator. `step_energy_kj(profile, d, grade, carried_kg=None)` and `step_speed_mps(..., carried_kg=None)` also take it as an argument; `with_load(profile, kg)` returns a loaded copy. Tests: `python phase4/tests_load.py`. Effect on the campaign route: `python tools/load_effect.py [preset]`.

### Mass versus weight in reduced gravity
A load L has mass L (inertia: it is accelerated and redirected every step) and weight L g (it is supported, and lifted on a climb). In reduced gravity the two separate: weight falls with g, inertia does not. Grabowski, Farley & Kram (J Appl Physiol 2005) combined reduced gravity with added mass to split walking cost into body-weight support and mass acceleration (my search saw about 28 % and 45 %; snippet level only, not opened, and no number from it is used in code). A pure weight model (cost proportional to g) would understate a load on the Moon, and a pure mass model (cost independent of g) would overstate it. I adopt the measured answer for level walking and physics for climbing:

1. Level walking, from data: Wickman & Luna 1995 measured walking cost against load at three gravities. Cost rises linearly with load factor F = (body + load) / body, and the rise per unit of F grows with gravity.
2. Climbing and descending, from physics: vertical work is m g h for body and load at the same g, so the load enters in proportion to mass, independent of g.

### Sources
| Short name | Reference | Read |
|---|---|---|
| Wickman & Luna 1995 | Wickman LA, Luna B, "Locomotion While Load-Carrying in Reduced Gravities", Aerospace Medical Association Annual Scientific Meeting, Anaheim 1995 (apu.edu/files/cris_reduced_gravities.pdf) | FULL text |
| Pandolf 1977 | Pandolf KB, Givoni B, Goldman RF, J Appl Physiol 43(4):577-581; equation as printed in Wikipedia and in Looney et al. 2018, Mil Med 183:e357 | secondary (equation only) |
| Santee downhill | Santee et al., USARIEM report T01-11 (2001), correction as quoted in Looney 2018, which notes a sign error in an earlier print | NOT USED |
| Grabowski 2005 | Grabowski A, Farley CT, Kram R, J Appl Physiol 98:579 | search snippet only, no numbers used |

Not found: an NTRS study of suited walking with added carried mass in partial gravity. The NASA suited data in this model (Walkback, IST-1, TP-2010) were all taken with the suit and no extra load, so the load term comes from Wickman & Luna. The 1971 NTRS cart/backpack report (19710011223) is a scan without a text layer; I could not read it and did not use it. Santee is not implemented: its printed form is uncertain and there is no suited downhill load data to check it against. Apollo energy data are not split by carried load, so they are no independent check.

### Coefficients
Wickman & Luna 1995, pooled results text and Figs 2 and 3: unsuited subjects, underwater treadmill with a rough 10 % immersion adjustment, n = 6, 1.2 m/s, energy in kcal/kg/min.

| Gravity | No-load intercept | Slope per unit of load factor | k = slope / intercept |
|---|---|---|---|
| Moon (1/6 g) | 0.053 | 0.017 | 0.321 |
| Mars (3/8 g) | 0.060 | 0.032 | 0.533 |
| Earth | 0.069 | 0.075 | 1.087 |

At 1.9 m/s the subjects mostly ran in reduced gravity: slopes 0.019, 0.042, 0.173 over intercepts 0.062, 0.090, 0.095. Not used. Loads tested: up to 270 % of body weight on the Moon, 80 % on Mars, 45 % at 1 g. Their walking regression (Eq. 1, R2 = 67 %) is E = 0.0788 V + 0.0025 G + 0.0569 F - 0.0006 B - 0.0100 L - 0.0687 (G in m/s2, F load factor, B body mass, L leg length). It is not used; the three per-gravity slopes are.

### Equations adopted
With body mass B = `mass_kg - suit_mass_kg` (90 kg), M_sys = `mass_kg` (150 kg), carried L, phi = g / 9.81:

- k(phi): piecewise linear through (0.165, 0.321), (0.378, 0.533), (1.0, 1.087).
- Level term (VO2 / v): multiplied by `f_lev = 1 + k(phi) L / B`.
- Incline term (dVO2 / 0.8): multiplied by `f_vert = 1 + L / M_sys`.
- Downhill: level part x f_lev; recovered-work and braking terms use g|i| x f_vert; the resting floor is unchanged.
- Energy per metre = body mass x that cost, as before. Speed does not change with load (no source).

Cross-check: the Pandolf equation M = 1.5W + 2.0(W+L)(L/W)^2 + eta (W+L)(1.5V^2 + 0.35VG) has walking and grade terms proportional to W + L, i.e. k = 1 on Earth; Wickman & Luna measured 1.087. `tests_load.py` checks that, and that the code reproduces the Wickman & Luna lines on Mars and the Moon. The second check only confirms the code implements the lines; it is not independent validation.

### What it gives (nominal, campaign route 1072 m, `tools/load_effect.py`)
| Carried | One-way time | One-way energy | Round trip energy / limit | Verdict |
|---|---|---|---|---|
| 0 kg | 26.7 min | 778.8 kJ | 1414 / 6000 kJ | GO |
| 10 kg | 26.7 min | 825.7 kJ (+6.0 %) | 1498 | GO |
| 20 kg | 26.7 min | 872.6 kJ (+12.0 %) | 1583 | GO |
| 30 kg | 26.7 min | 919.5 kJ (+18.1 %) | 1667 | GO |

Time barely moves (no speed penalty; only the fatigue slow-down grows). No load from 0 to 30 kg turns GO into NO-GO on this route for the nominal, conservative or fatigued profile (each planned with its own limits). The energy rule CS-06 would trip at about 216 kg (conservative) and 129 kg (fatigued), far outside the tested range (Mars tests stopped at 80 % of body weight, about 72 kg), so those figures are not predictions. Load does not change which cells are allowed: CS-01 depends on terrain slope only. In this model, at realistic loads, carried equipment costs energy and consumables, not route legality.

### Limits
- Wickman & Luna: 6 unsuited subjects in water, 6-minute tests, torso-mounted ballast, 1.2 and 1.9 m/s only, conference paper. The immersion correction is a rough 10 %.
- Applying the unsuited relative increase k to the suited cost is an assumption. The suit already adds mass and stiffness; the real increment per kg may differ.
- Using M_sys instead of B for the vertical factor is an assumption; B would raise the climbing penalty by a factor 150/90.
- No speed penalty (no source). Load placement (high back, low front) changed cost in the paper; not modelled. No terrain factor for soft ground (Pandolf eta); the model has no loose-ground term.
- Past 80 % of body weight on Mars (about 72 kg) the model is linear extrapolation.

### JS port for twin.html (for the coordinator; twin.html is not edited by this task)
Add `carried: 0` to `SUIT`, add two arrays to `V2`, and replace `stepEnergy`. The optional third argument overrides `SUIT.carried`. Checked against `phase4/astronaut.py` for 18 combinations (0, 10, 30 kg x six grades, nominal Mars): maximum difference 0.

```js
// 1) in const SUIT = { ... } add:  carried: 0
// 2) after PHI_MOON / PHI_MARS are defined (right after the V2 object):
V2.KPHI = [PHI_MOON, PHI_MARS, 1.0];                  // Wickman & Luna 1995: Moon, Mars, Earth
V2.K    = [0.017/0.053, 0.032/0.060, 0.075/0.069];    // slope / no-load intercept at 1.2 m/s
// 3) replace stepEnergy:
const stepEnergy = (d, g, carried) => {
  const L = Math.max(0, carried === undefined ? SUIT.carried : carried);
  const gr = clipG(g), v = stepSpeed(gr, 0), m = vo2Level(v), body = Math.max(40, SUIT.mass - SUIT.suitMass);
  const fLev = 1 + pl(PHI, V2.KPHI, V2.K, false) * L / body, fVert = 1 + L / SUIT.mass; let c;
  if (gr >= 0) c = (m / v * fLev + inclineDvo2(gr) / V2.VREF * fVert) * V2.J / 60;
  else { const c0 = m / v * fLev * V2.J / 60, gi = SUIT.gM * -gr * fVert;
         c = Math.max(c0 - V2.DERATE * V2.REC * gi, gi / V2.ECC, V2.REST / v * V2.J / 60); }
  return c * body * d / 1000; };
```
With `SUIT.carried = 0` the output equals the current `stepEnergy`; `stepSpeed` needs no change. Mission control's suit view (`demo/twin/suit.js`) has a Carried box that scales the logged metabolic rate by the level factor `1 + 0.533 L / 90`.
