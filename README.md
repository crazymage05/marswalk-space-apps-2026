# MARSWALK

MARSWALK plans the shortest walk a suited astronaut can do safely on Mars, checks it against flight rules, and lets you
walk it in first person. It covers the ground Curiosity crossed during its 2025 boxwork campaign on Mount Sharp, Gale
crater (sols 4500-4799), rebuilt from NASA data. Entry for the NASA Space Apps Challenge 2026, "Interplanetary Survival
Guide: Martian Map" ([challenge text](docs/challenge.md)).

- **Demo video (29 s):** [media/marswalk_demo30.mp4](media/marswalk_demo30.mp4)
- **Run the demo:** see [Run it](#run-it). It is a static web page; no server code, no accounts.

## What it does

- **Plan anywhere.** Click a start and an end on the 3D terrain. An A* planner finds the shortest route that never enters
  a cell the flight rules reject (slope above the limit, rough ground, unknown terrain, 112 HiRISE-detected boulders). If
  no safe route exists, it says so. Shift-click adds up to six stops, visited in the cheapest order.
- **GO or NO-GO, and why.** Every route is checked by an independent validator (rules CS-01 to CS-08: slope, roughness,
  data quality, time, energy, radiation dose, daylight). The "Why this route" panel shows each rule, the cost by term,
  and the straight line it rejected.
- **Find the science.** Search "water", "iron", "clay" and similar words: 11 CRISM mineral groups, ranked within the area,
  shown as numbered targets you can route to.
- **Zones.** The area is split into 200 m zones (A-L by 1-15). Tap one for its summary (walkable share, slopes, boulders,
  minerals, geologic unit, dose, reachable or not), then press "Start here" or "End here" to plan between zones without typing
  coordinates. Crew and mission control use the same names.
- **Walk it.** First person or follow view, Mars gravity and gait, suit model in the visor HUD (time, energy, dose,
  return margin), Curiosity's own photos and 3D scans where it stood.
- **Crew and support.** Carried load (Wickman and Luna 1995), two-person EVA and a rover as safe haven (NASA DRA 5.0).
- **Mission control.** What Earth sees, with the light-time delay: suit health, a simulated dust event and re-plan, live
  feeds (Curiosity and Perseverance raw images, NASA Worldview over the Deep Space Network sites), solar-storm arrivals
  at Mars from NASA DONKI.
- **New data updates the world.** Feeds (`tools/ingest.py`, one plug-in file per source, so a future rover is one new file)
  and uploads in mission control (RAD and REMS CSV, Navcam images, JSON records) reach an open twin at once. New radiation
  re-checks the GO verdict; a new hazard zone (dust storm or a new obstacle such as a rockfall) blocks its cells, fails
  rule HZ-1 and makes the twin re-plan the route around it. New terrain still needs the processing scripts re-run.
- **Render any route as film.** `tools/render_route.py` takes a share link from the page and renders that walk in Blender.

## NASA data and the challenge's Resources tab

| Kind | Data |
|---|---|
| Topographic | HiRISE stereo DTM, 1 m (MRO) |
| Optical | HiRISE 25 cm image, CTX (MRO); Curiosity Navcam photos and 3D scans |
| Spectral | CRISM summary parameters, 18 m (MRO) |
| Thermal | THEMIS dawn infrared (Mars Odyssey) |
| Radiation | Curiosity RAD dose rate; NASA DONKI solar-storm model runs |
| Atmospheric | Curiosity REMS weather; Mastcam dust optical depth |
| Chemical | Curiosity ChemCam (221 targets) and APXS (128 products) |

All five Resources-tab items are used: JPL Mars Trek, the USGS-NASA geologic map (SIM 3292), the Perseverance raw-image
gallery, NASA Worldview (GIBS) and NASA's Curiosity route map (PIA23179). Details and links:
[docs/resources_used.md](docs/resources_used.md).

## Accuracy

Measured against independent evidence by [tools/accuracy_metrics.py](tools/accuracy_metrics.py); numbers in
[results/accuracy_metrics.json](results/accuracy_metrics.json).

| Test | Result |
|---|---|
| Curiosity's real drive path through the area (1,844 cells) | 99.6% marked walkable by our rules |
| Map slope against Curiosity's tilt sensor (261 stops) | mean error 3.4 deg, bias -1.0 deg |
| 60 random start/end pairs, 300-1500 m apart | 88% have a safe route; every route found passes every rule; no boulder cell entered |

Curiosity is a rover, not a walker, so the first test checks the terrain layers, not walker physiology. The page offers an
optional safety margin that plans 3.4 deg below the slope limit to cover the measured map error.

## Run it

```
python -m http.server 8765 --bind 127.0.0.1 -d demo/twin
```

Then open http://127.0.0.1:8765/index.html in desktop Chrome or Edge. A first visit plays a short intro (`intro.html`: a 3D Mars globe from NASA maps, HiRISE and Curiosity images, the 30 s demo); `index.html?hub` skips it. Image credits: `demo/twin/intro/CREDITS.md`. The twin is `twin.html` and mission control is
`mission.html`. The first load is a little over 100 MB; the walk view needs a GPU.

## Repository layout

| Path | Contents |
|---|---|
| `demo/twin/` | The web pages and their prebuilt data (everything the demo loads) |
| `phase4/` | Planner (A*), flight-rule validator, astronaut energy model, tests |
| `phase5/` | Dust event and re-plan, weather anomaly detection |
| `phase2/` | Data engineering: terrain, co-registration, spectral and thermal layers |
| `tools/` | Data fetch and export scripts, live feeds (`tools/feeds/`), Blender film and route rendering, checks |
| `docs/` | Method notes |
| `results/` | Accuracy numbers |
| `media/` | The 30 s demo video |

Raw NASA data is not stored here (several GB). The fetch scripts in `tools/` and `phase2/` download it from the PDS and
NASA services. The demo runs from the prebuilt files in `demo/twin/`.

## How the route is chosen

A* plans the route, and an independent validator checks every 4 m of it against the flight rules. A reinforcement-learning
agent trained on the same human and suit limits is shown in the twin as a research comparison ("A* vs RL route"); it reaches
the goal on 41% of 101 test routes (63% with a stochastic policy), so it does not draw the route.

## Future work

- Pick a start and resources by zone, listing only targets the suit can reach and return from, with resources present on
  Mars but not at this site shown as unavailable.
- Suit consumables (oxygen, CO2 removal, battery) as planning rules, with a suit specification card. They are modelled
  today in mission control only.
- Retrain the RL agent on the current astronaut model and boulder map, starting from A* demonstrations.

## Limits

- The astronaut energy model is a model, about +/-25%, not validated suited physiology.
- Boulders smaller than about 1 m are not mapped; loose sand is a 100 m-scale hint.
- The dust event and suit leak are simulated scenarios and are labelled as such in the pages.
- Solar-storm arrival times at Mars carry the published model error of about 10-20 hours.

## Use of AI

The code was written with an AI coding assistant (Claude, by Anthropic). The film and renders are made in Blender from
NASA data; no AI-generated images, video or voice are used.

## Credits

Data: NASA/JPL-Caltech, University of Arizona (HiRISE), MSSS (CTX, Mastcam), ASU (THEMIS), JHUAPL (CRISM), LANL/CNES
(ChemCam), University of Guelph (APXS), MOLA science team, NASA CCMC (DONKI), NASA GIBS/Worldview, USGS Astrogeology.
3D models: NASA (Curiosity, Mark III suit); the backpack on the suit is our addition.
Page design: visual language adapted from the MIT-licensed "Lilac Meadow Landing" template (Kedhareswer Naidu).
