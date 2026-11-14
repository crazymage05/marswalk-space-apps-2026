# Crew and support in the twin: carried load, buddy pair, rover as safe haven

This answers two lines of the challenge text: "Think about whether your mission might use rovers or other robotic systems to help transport the crew and their tools, or whether the astronauts might work in pairs", and the suited astronauts "possibly carrying scientific equipment and other supplies. Consider how this might impact their mobility". Code: `demo/twin/twin.html` (Plan a walk card, "Crew and support"), `demo/twin/share.js`, `demo/twin/why_route.js`, `phase4/safety_validator.py` (`refuge_cell`), tests `phase4/tests_refuge.py`. Everything is off by default; with the controls at 0 / unticked every route, verdict number and share link is unchanged (checked: the three route buttons give the same cell counts, hashes and distances as before).

## Carried load

The slider sets kg carried by each astronaut (0 to 80), on top of astronaut + suit + kit (150 kg). The page uses the JS port in `docs/astronaut_model.md` ("Carried load"): level cost x (1 + k(g) L / body mass), climbing and braking terms x (1 + L / system mass), k from Wickman & Luna 1995. Speed does not change with load because no source gives a relation. In the real page, `stepEnergy` at 0, 10, 30 and 80 kg over eight grades from -0.4 to 0.5 matches `phase4/astronaut.py` `step_energy_kj(carried_kg=...)`: the largest relative difference is 2.7e-16. On the campaign route (round trip) 0 kg gives 1416.5 kJ and 30 kg gives 1670.4 kJ (x1.179); the verdict stays GO. The load statement in the model document remains the authority for limits (unsuited water-immersion data, 6 subjects).

## Buddy pair

Source: NASA Human Exploration of Mars Design Reference Architecture 5.0 (NASA-SP-2009-566), section 5.2, PDF page 53: "Operationally, Mars surface EVAs would be conducted by a minimum of two people and a maximum of four. (This would always provide for a 'buddy system' while on an EVA but would also leave at least two people in the SHAB for contingency operations ...)".

Rule adopted: both astronauts walk the same route in identical suits, and each must pass CS-05 to CS-07 on their own numbers, so the decision equals the single-astronaut decision. The page shows per-person numbers and crew totals (2 x energy, 2 x O2). O2 is the metabolic oxygen implied by the model's own constant (20.1 J per ml O2, so litres = kJ / 20.1; 1.429 g/L at 0 C and 1 atm). It is not suit consumption: leakage and ventilation are not modelled. Dose is per person and is not summed. Not modelled: partner assistance after an incapacitation, split loads, unequal suits. These are limits, not rules we invented.

## Rover as safe haven

Sources. DRA 5.0 section 5.2 (PDF page 53) treats the unpressurized rover as "an extension of the EVA suit", with consumables possibly on both rover and suit, and says that with one unpressurized rover "the EVA team would be constrained to operate within rescue range of the surface base ... either the team has sufficient time to walk back to the surface base if the rover fails, or ... a rescue team ... [can] reach them"; with several identical rovers they are "mutually supporting". Section 2 (PDF page 20) uses an EVA walk-back distance of about 15 km for cache traverses. Apollo: the LRV range was bounded by the astronauts' ability to walk back to the LM if the rover failed (NASA OCHMO-TB-023, extraterrestrial surface transport vehicles; the Apollo 17 Lunar Surface Journal annotations give a 7.6 km limit and a 2.7 km/h walk-back assumption; read as search-result snippets, not opened in full, and no Apollo number is used in code).

Rule adopted. The user parks a rover cell (default: Curiosity's position on the chosen sol, because it is the only rover position in the data; the pin is labelled modelled support, a future crew rover, not Curiosity's capability). The point of refuge becomes that cell instead of the start:

1. One Dijkstra from the rover over cells the walker may enter (same tests as the planner and the rule mask: slope limit, roughness, unknown terrain, data confidence), edge cost = energy of the step towards the rover. Diagonals are refused when either orthogonal neighbour is blocked.
2. For every route cell k, walk-back time and energy are recomputed exactly along that path with the astronaut model and fresh fatigue, the convention already used for the walk back to the start.
3. CS-05 and CS-06 use the worst abort point: the maximum over k of (time or energy spent so far + walk to the rover). CS-07 dose uses the same time. A route cell with no allowed path to the rover is a CS-05 finding.

Not modelled: the rover's own drive time, power and consumables, and whether it can reach the cell. The green area on the map is a guide: ground from which the walk to the rover fits within half the reserve-adjusted limits (6 h / 2 and 6000 kJ / 2), so an out-and-back trip fits; on this 2.4 x 3.0 km terrain it covers most of the map, so the verdict on the real route is the test that matters.

`phase4/safety_validator.py` `validate(..., refuge_cell=None)` mirrors this. With `None` the result is identical to before. Its path search uses an energy table on a 0.0005 grade grid to choose the path; reported numbers come from the astronaut model along that path.

## Worked example (page and validator)

Page, 0 kg, route A* from cell (485, 214) to (45, 292), 4.42 km: walk back to the start gives 14341 s and 6558 kJ against limits 21600 s and 6000 kJ, so NO-GO on CS-06. With the rover parked at the far end the worst abort point is 6803 s and 2967 kJ: GO. With the rover at the start the same route stays NO-GO (6459 kJ). With 80 kg carried, 7 of 60 random long routes fail CS-06 on the walk back to the start and all 7 pass with the rover parked at their far end. Validator, fatigued profile, route (400,200) to (100,500) in the Python grid, 2.26 km: fails `energy_budget_with_return` to the start, passes with `refuge_cell` at the far end (tests in `phase4/tests_refuge.py`).

## Share links

New keys, written only when on: `kg=30`, `pair=1`, `rv=x,y`. A link restores them before the route, so the restored verdict includes them.
