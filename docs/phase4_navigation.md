# Phase 4 navigation: costs, limits, astronaut model, validator

Code is in `phase4/` (`astronaut.py`, `costs.py`, `astar.py`, `safety_validator.py`, `scenarios.py`, `tests_nav.py`, `make_routes.py`). Routes are in `data/processed/roi/routes_astar.json`. Grid: `nav_grid_4m.npz`, 585 x 732 cells of 4.047 m, cell = row*585+col.

## Cell cost

`m(s) = 1 + 4 * C(s)`, `C(s) = w_t C_terrain + w_x C_exposure + w_e C_environment + w_m C_mobility + w_u C_uncertainty`. Every term is dimensionless on 0..1, so m is 1..5 (multiplier on the length of the step). m >= 1 keeps the octile-distance heuristic admissible. Edge cost = planar distance x mean of the two cell multipliers + 3 m-equivalent per metre climbed. Default weights (nominal): 0.35 / 0.15 / 0.15 / 0.15 / 0.20.

| Term | Source layer | Scale (0..1) | Weight | Missing data |
|---|---|---|---|---|
| terrain | `slope_max_deg`, `rough_max_m` | 0.6 (slope/limit)^2 + 0.4 (rough/limit), each clipped to 1 | 0.35 | NaN roughness counts as the limit (1.0); NaN slope counts as the limit |
| exposure | `slope_mean_deg` via Tobler speed | 1 - v(grade)/v(flat): extra time outside per metre. Radiation is time-based, so this is the only way space enters the dose | 0.15 | NaN slope -> limit slope |
| environment | `loose` (THEMIS dawn warmth, coarse ~100 m hint) | value as is | 0.15 | 0.5 |
| mobility | `slope_mean_deg` via metabolic model | (E(grade)/E(flat) - 1)/4, clipped | 0.15 | NaN slope -> limit slope |
| uncertainty | `valid_frac` | 1 - valid_frac | 0.20 | NaN roughness -> 1.0 |

Radiation is never mapped in space. Dose = 6.45 uGy/h (RAD campaign mean, tissue-like) x time outside.
`hydration`, `sulfate`, `science` are not in the cost (science targets are for the RL reward).

## Hard limits (never entered)

Steepest 1 m slope > `max_slope_deg` (25 nominal); roughness > `rough_max_m` (0.35); `valid_frac` < 0.5; NaN slope/elevation; NaN roughness (unknown; `allow_unknown_rough=True` lets A* use them with the uncertainty penalty only). Diagonal moves are refused when either orthogonal neighbour is blocked. Nominal profile blocks 25.2% of cells.

## Astronaut model (SIMULATED, not validated physiology or suit performance)

- Speed: Tobler hiking function `6 exp(-3.5|g+0.05|)` km/h, rescaled so flat = profile speed (0.9 m/s nominal for a suited walker, an assumption), slowed by up to 35% with fatigue.
- Energy: Minetti et al. 2002 cost of walking vs gradient, J/kg/m, x total mass incl. suit (150 kg nominal) x g_Mars/g_Earth (3.71/9.81). The linear gravity scaling is a crude assumption. Flat: about 142 kJ/km.
- Fatigue: f in 0..1, +energy/capacity, -0.5 per hour rest.
- Profiles: `nominal` (25 deg, 0.35 m, 8 h, 3000 kJ, 25% reserve, 250 uGy), `conservative` (18 deg, 0.25 m, 6 h, 2200 kJ, 40% reserve, 150 uGy), `fatigued` (20 deg, 0.30 m, 4 h, 1500 kJ, 30% reserve). The 250 uGy dose budget is a configurable placeholder.

## Validator checks (independent of `astar.py`)

Prohibited slope; prohibited roughness (obstacle); step continuity (adjacent cells only); low data confidence (`valid_frac` < 0.5); unknown (NaN) cells; EVA time with return; energy with return; dose budget; optional daylight window. Return assumes the walker retraces the route: round-trip time and energy must fit within budget x (1 - reserve). Not covered: thermal and life-support limits (no data), spatial radiation (none by design).

## Results (nominal profile, seed 0, A*)

| Route | Length | Time | Energy | Dose | Validator |
|---|---|---|---|---|---|
| Campaign direct (first to last campaign cell, 78 waypoints) | 1076.5 m | 1607 s (26.8 min) | 264 kJ | 2.88 uGy | pass |
| Campaign via all waypoints in sol order | 1693.5 m | 2517 s | 380 kJ | 4.51 uGy | pass |

20 random scenarios (straight-line 0.5 to 2 km): 20/20 pass for nominal and conservative; 11/20 pass for fatigued (9 fail EVA time with return, 6 fail energy with return, some both). Route lengths 0.77 to 3.63 km, A* time 0.07 to 1.6 s per route, up to 253k cells expanded. Dijkstra costs equal A* on all 20. Campaign cells are the sol 4500-4799 waypoints; the campaign route is a planner output, not Curiosity's actual path.


## Recommended planner (16-neighbour A* + string pulling + risk weight)

Code: `phase4/recommended.py` (`plan_recommended`, also `astar.plan(..., algorithm="astar16", smooth=True, risk_weight=w)`); validator: `safety_validator.validate_polyline`. The default `astar.plan` (8-neighbour) is unchanged and stays the reference for the RL comparison. Returns the usual dict plus `vertices` (the polyline), `model_cost` (same cost model as `astar.plan`, measured on the final path), `risk_m`; `route` is the Bresenham rasterisation (adjacent cells, accepted by the old `validate`). Distance, time, energy and dose are computed along the actual polyline in sub-steps of at most one cell on bilinear elevation.

- Neighbours: 8 compass moves plus 8 knight moves (+-1,+-2), 16 in all. Edge cost = length x integral of the cell multiplier along the straight segment (exact cell traversal) + climb_weight x sum of positive elevation steps between the crossed cells + `risk_weight` x length x mean cell risk. A segment is blocked if any crossed or corner-touched cell is hard-blocked or the source is blocked. For one-cell moves this equals `astar.py`, so with `risk_weight=0` astar16 is never costlier than astar8.
- Cell risk = (0.35 terrain + 0.20 uncertainty + 0.15 environment) / 0.70, 0..1 (no radiation, which is time-based).
- Heuristic: cell size x Euclidean distance (admissible, consistent; the risk term is >= 0).
- Smoothing: from vertex i jump to the farthest j (at most 150 vertices ahead) whose straight segment has exact line of sight and costs no more than the A* sub-path it replaces; repeat from j.
- **Default `risk_weight` = 6.0** (metre-equivalents per risk-metre), the knee of the time-versus-risk curve on the campaign scenario (`phase4/bench/run_knee.py`, point of maximum distance from the chord of the normalised curve; the sweep is in `bench/results/knee_results.json`). Against w = 0 it cuts campaign risk 59.2 to 50.9 risk-m (-14%) for +1.6% walking time. Weighted sums reach only the convex part of the front, one scenario, nominal profile only; re-measure for other profiles. This is a different scalarisation from `run_pareto.py` (there lambda weights time; here the weight is on top of the model cost), so the numbers are not interchangeable.

Measured on the 21 benchmark scenarios (nominal, medians against 8-neighbour A* measured the same way; `bench/run_recommended.py`):

| Planner | Length | Time | Risk-m | Planning time | Validator |
|---|---|---|---|---|---|
| astar16 + pulling, w = 0 | -4.44% | -2.54% | -0.0% | x1.33 | 21/21 |
| astar16 + pulling, w = 6 (default) | -2.21% | -1.51% | -4.64% | x1.53 | 21/21 |

Median planning time 526 ms (8-neighbour) against 781 ms (default) with the edge tables cached; building the 16 edge tables for a given risk weight takes about 0.5 s once per grid and weight. Tests: `python phase4/tests_nav.py`.

### Note for machine A: porting to the twin (JavaScript)

1. Precompute per cell: `blocked`, `mult` (1 + 4C), `risk`, `elev`. For each of the 16 offsets (dr,dc) walk the segment from cell centre to cell centre with an Amanatides-Woo traversal in integer arithmetic (T = 2*|dr|*|dc|, step times tmc=|dr|, tmr=|dc|, increments 2|dr|, 2|dc|; axis-aligned: T = 2*max, first crossing 1, step 2). Collect the cells with their length fraction; when both crossing times tie, step diagonally and also mark the two side cells as "corner touched". Segment blocked if any traversed or corner-touched cell is blocked. Cost = cm*hypot(dr,dc) * sum(fraction*(mult + w*risk)) + climbWeight * sum(max(dz,0) between consecutive traversed cells).
2. A*: key g + cm*hypot(dr_to_goal, dc_to_goal), binary heap, closed set, 16 neighbours from the table (inf = skip). Neighbour list order does not matter for cost.
3. Smoothing: `out=[v0]; i=0; while i<n-1 { nxt=i+1; for j=min(n-1,i+150) down to i+2 { (c,blk)=seg(v[i],v[j]); if !blk && c <= cum[j]-cum[i]+1e-9 { nxt=j; break } } out.push(v[nxt]); i=nxt }`, where `cum` is the cumulative planning cost of the A* path and `seg` is the same segment cost (including the risk term).
4. Walk the polyline in straight segments between cell centres (centre of cell (r,c) = (c+0.5, r+0.5) cells). Use the same `w` (6.0) and 4.047 m cells; check against `validate_polyline` outputs from Python for a few scenarios (e.g. the campaign: 1018.6 m, 22 vertices at w = 0; 1060.0 m, 25 vertices at w = 6).
5. Do not change the RL environment action set; keep 8-neighbour A* as the comparison route.
