# Suit view (demo/twin/suit.js)

NASA-side suit health panel on mission control (`mission.html`, one script tag). It reads the replay through `window.__mission` (log, step) and uses no new library and no fetch. Mars side = state at the conductor time t. Earth side = state at t minus the one-way light time (log value, about 9.7 min).

| Tile | Formula | Source / tag |
|---|---|---|
| Metabolic rate (W) | d(energy_kj)/dt over 5 log steps | model v2 gross metabolic energy (phase4/astronaut.py): modelled |
| O2 consumption (L/min) | P_met / 20.1 kJ per L x 60 | 20.1 J/ml from astronaut.py: modelled |
| O2 used (L) | energy_kj / 20.1 | modelled |
| O2 remaining (L, h) | capacity - used | capacity is ASSUMED: tank sized for 8 h at the nominal level-walking rate (here the mean power of the log, about 482 W, giving about 691 L). Not a NASA value: assumed |
| CO2 produced (L/min) | O2 rate x RQ 0.85 | RQ assumed |
| Heat load (W) | taken equal to metabolic power | modelled (simplification) |
| Suit pressure (kPa) | 29.6 nominal | 29.6 kPa is the test pressure in docs/astronaut_model.md; falls only in the leak scenario: SIMULATED |

Carried box: kg of equipment or samples (default 0, or `profile.carried_kg` from the log if present). It multiplies metabolic power and O2 used by `1 + 0.533 L / 90` (Wickman & Luna 1995, Mars level walking; SIMULATED). The tank size stays the unloaded one, so O2 hours fall. The extra cost of climbing with the load is not added in this view (see docs/astronaut_model.md).

Heart rate is left out: the repo has no cited relation. Nothing is "measured": there is no real suit telemetry.

Messages in flight (request, ground reply, leak alert) are drawn as dots on the Mars to Earth bar, from the log's comm_sent, comm_received_earth and ground_reply times. No live call is possible, and the page says so.

## Simulated leak
"Simulate suit leak" starts a slow leak at the current conductor time. All of it is SIMULATED and its parameters are assumed:
- Leak rate 0.02 kPa/s (pressure fall rate if nothing made up the loss). The regulator holds the suit at a floor of 24 kPa (assumed), so pressure dips from 29.6 kPa and holds.
- Make-up flow from the O2 supply = leak rate x V / (R T), expressed as L of O2 at 101.3 kPa and 293 K: 0.02 kPa/s x 0.03 m3 gives 0.36 L/min. Suit free volume 0.03 m3 and 293 K are assumptions (no NASA value in the repo). The make-up is added to O2 consumption and to O2 used, so O2 remaining and hours at this rate drop (example at one time: 7.55 h without leak, 6.02 h with it).
- SU-1 demo rule: end EVA and walk back when suit pressure is below 25 kPa, or when O2 time left at the current rate is below the walk-back time, whichever comes first. Walk-back time is the plan's nominal round trip (29.9 min) because the log's margin_time_s is a margin, not a duration. With these numbers the pressure rule trips first, 230 s after the leak starts.
- phase4/safety_validator.py has no suit-pressure rule (AB-01..AB-04 cover return margin, dust core, night, SPE), so SU-1 is a demo rule of this page.
- The Mars alert shows when the rule trips; Earth shows it one light time later. The replayed log and banner are not changed. Reset clears it.
