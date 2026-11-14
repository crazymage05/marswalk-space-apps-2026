# Verification summary, 2026-11-12

Everything built up to RL training was checked twice: once with the project's own tools and once
with independently written code or a different method, with every image opened and looked at.
Checks were kept light (sampled reads, no full rebuild, no training) to spare the laptop. The
detailed reports are `01_data_phase1.md`, `02_phase2.md`, `03_phase4_nav.md` and
`04_twin_browser.md` in this folder.

## Result

Everything up to training is built and works. What remains is to train the RL agent, run its
evaluation, and rebuild the twin data so the results appear in the A* vs RL view.

| Area | What was checked | Result |
|---|---|---|
| Data and Phase 1 | 43 selected products, 837 files opened (GDAL, PIL or parser), 2,130 Navcam/Mastcam JPEGs, 143 RAD files, 70 REMS tables against label row counts, deleted-file log, Gale vs Jezero numbers recomputed, ROI contains all 78 campaign waypoints | Pass, after one fix |
| Phase 2 layers | 26 rasters on the grid; elevation equals the raw DTM exactly; slope, roughness, CRISM median, CRISM and THEMIS reprojection recomputed independently; co-registration re-searched (91 m W, 28 m S against the stored 92 m W, 35 m S); RAD, REMS and image tables re-parsed from raw files; validator 64/64 | Pass, with two documented limits |
| Phase 4 navigation | Nav grid cells recomputed; A* against an independent Dijkstra; 16 adversarial routes against the safety validator; RL environment `check_env`, checkpoint load and inference on the GPU; step-log parser; hand calculation of the campaign route | Pass, after one fix |
| Twin page | Two headless Chromium passes on the real GPU (desktop and 400 px phone): all layers, click-planning, science walk, Curiosity's track, walk mode in both views, all 6 rover 3D scans, sun position, dose arithmetic, end of walk, exit; no console errors, no failed requests; final regression on the finished file | Pass, after two fixes |
| Gaps | Public sources searched; space-weather notices and the newer REMS release fetched and checked | Two gaps closed |

## Bugs found and fixed

1. `region_audit.py`: ODE swaps scale fields for THEMIS PDS4 products, so 887 manifest records gave
   pixels per degree as metres. Fixed and re-run.
2. `phase4/eval_rl.py`: RL routes were compared with A* routes for different start and goal cells,
   which made RL look 0.4–0.5 times as long. It now re-plans A* when the endpoints differ; the true
   ratios are 1.19–1.44.
3. `phase2/validate.py`: the rock-density layer covers only the walk corridor and failed a 90%
   coverage rule; per-layer minimums added. The earlier "62 of 62" in the Phase 2 report was wrong
   and is corrected to 64 of 64.
4. `twin.html`: no character-set declaration, so ° and µ were garbled on a plain local server.
5. `twin.html`: at some slope limits the science walk skipped a stop whose own cell sits in a
   pocket walled by steeper ground. It now tries nearby walkable cells; all three stops are reached
   at 15°, 20°, 25° and 30°.
6. `twin.html`: Curiosity's 3D scans sat level with the orbital terrain and showed as fragments;
   the orbital surface is now lowered beneath each scan, and A* routes rarely passed over a scan, so
   a "Walk Curiosity's track" route was added.

Seven statements in the Phase 1 and Phase 2 reports were corrected after being checked against
the data (study-area size 2.36 × 2.96 km, 43 not 49 products, THEMIS counts and resolutions, the
2026 image's east-west error, the meaning of the THEMIS file names, REMS and space-weather
coverage).

## Known limits (documented, not defects)

- The 2026 HiRISE image is good to 1–2 m north-south but about 13–17 m east-west; it is used for
  display only.
- CRISM positions carry about one pixel (18 m) of uncertainty; an image-correlation test was
  inconclusive.
- THEMIS has only dawn and dusk images at about 100 m, so the loose-ground layer is a coarse hint.
- The astronaut's speed, energy and dose budgets are simulated placeholders, labelled as such.
- 20 THEMIS folders contain a zero-byte `DSMAP_SNU.CAT` (a catalogue file, not data); 2 of 200
  sampled Mastcam frames are nearly black (raw images as published).

## Before training

`phase4/env.py` uses its own speed, energy and budget constants, while the planner and validator
use `phase4/astronaut.py`. They should share one source so A* and RL are judged on the same
astronaut. This was left for the training session, as instructed.

## After training

```
python phase4/train_ppo.py --timesteps 4000000 --n-envs 16 --name ppo_v1 --max-minutes 90
python phase4/eval_rl.py --model models/ppo_marswalk_latest.zip --n 20 --seed 0 --min-km 0.3 --max-km 1.5
python build_twin_demo.py          # imports routes_rl.json into the twin's A* vs RL view
```
