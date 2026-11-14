# Hazard watch: can a disaster seen elsewhere be predicted for Gale?

Short answer: partly, and with large timing error. For radiation storms, NASA's DONKI service publishes WSA-ENLIL model runs that list a predicted arrival of a coronal mass ejection (CME) at Mars. The published arrival-time errors are many hours (standard deviation 17 to 20 hours). We could not measure that error ourselves with the Curiosity RAD files in this repo, and we say why below. For dust storms nobody publishes a machine-readable forecast, so the mission page has an operator tool: someone who sees a storm on an orbiter image types it in and the page does geometry. That is a scenario, not a prediction.

Nothing here is specific to the Gale boxwork. A CME arrival at Mars is Mars-wide. Site-specific shielding (rock overhang, terrain) is not modelled.

## What is measured, modelled, simulated

| Item | Label | Source |
| --- | --- | --- |
| Predicted CME arrival at Mars | modelled | DONKI WSA-ENLIL+Cone runs, `impactList` entries with `location` "Mars" |
| SEP onset at Earth or STEREO A | measured (at that instrument) | DONKI `SEP`; says nothing about Mars by itself |
| Curiosity RAD dose rate | measured | `data/raw/curiosity/rad` (read only) |
| Arrival-time error | published | von Forstner et al., see below |
| Dust storm entered by an operator | simulated | `demo/twin/hazard_watch.js`, stored as label "simulated" |
| Dust climatology (tau) | measured, climatological | `demo/twin/tau_climatology.json` (Mastcam, sols 33 to 3953), not a current reading |

## Endpoints (api.nasa.gov, DEMO_KEY, User-Agent `marswalk-demo/1.0`)

`GET https://api.nasa.gov/DONKI/<name>?startDate=YYYY-MM-DD&endDate=YYYY-MM-DD&api_key=DEMO_KEY`

- `WSAEnlilSimulations`: each run has `cmeInputs` (speed, longitude, half angle), `impactList` (location, `arrivalTime`, `isGlancingBlow`, `isMinorImpact`), and `estimatedShockArrivalTime` (Earth). No uncertainty field. Mars appears in `impactList` together with other planets and probes.
- `SEP`: solar energetic particle events by instrument (GOES, SOHO COSTEP, STEREO A, and REleASE model rows).
- `CME`, `CMEAnalysis`: catalogue and the cone fits behind the ENLIL runs (both answered on 2026-11-13).
- Limits seen on 2026-11-13: a range longer than 60 days returns HTTP 400; the response header `X-Ratelimit-Limit` was 10 requests per hour for DEMO_KEY. `tools/feeds/space_weather.py` therefore asks for at most 59 days and makes 2 requests per poll.

`python tools/feeds/space_weather.py --days 60` (capped to 59) printed 25 Mars-arrival records for 2026-09-29 to 2026-11-13, 9 of them not flagged as glancing blows. It found no SEP rows in that window.

## Skill check

Script: `tools/hazard_skill.py`. Output: `data/processed/hazards/cme_skill.json`. DONKI inputs: `data/processed/hazards/donki_enlil_mars_impacts.json` (241 Mars rows, May 2024 and 2025-03-01 to 2025-12-25, copied unchanged from the API).

### What our RAD data can and cannot show

- The repo RAD files hold one Mars sol each: about one per 50 sols in 2024 and one per 10 sols from sol 4500 (2025-04) on. 45 files for 2024 to early 2026.
- The May 2024 storm that Curiosity RAD measured is not in them. The nearest files are sol 4151 (2024-04-09) and sol 4201 (2024-06-01).
- 32 of the 241 DONKI Mars rows fall inside a RAD file's span (27 of them glancing blows). No file shows a sustained rise in dose rate at those times. Threshold: median plus 5 robust sigma of all B-detector readings (8.81 uGy/h), at least 3 readings in a row.
- Only one file passes that test: sol 4750 (2025-12-16, 19:05 to 20:18 UTC, B detector only, E detector flat). No DONKI Mars arrival is listed near that date. We do not explain it and do not call it a storm.
- Sol 4720 has one 21.2 uGy/h reading (2025-11-16 02:56 UTC), a single sample, treated as a spike.
- The large Earth-directed CMEs of 9 to 14 November 2025 had no DONKI Mars impact. Mars was far from the Sun-Earth line, and RAD sol 4720 (15 to 16 Nov) shows nothing. That agrees with the model, but it is one case.

So the arrival-time error was not measured here: there is no observed onset to subtract from a predicted one. We did not look for Forbush decreases, which need a proper baseline and denser sampling than one sol in ten.

DONKI also lists several runs for one CME. Across 77 CMEs with two or more runs the median spread of predicted Mars arrival is 0.0 h (identical re-runs) and the largest is 35.6 h. This is spread between runs, not error against an observation.

### Published errors used instead

1. J. L. von Forstner et al., *Using Forbush decreases to derive the transit time of ICMEs propagating from 1 AU to Mars*, arXiv:1712.07301 (DOI 10.1002/2017JA024700). 15 ICMEs. ENLIL transit time minus the Forbush-decrease transit time: mean -7 +/- 11 h (the +/- is the standard error of the mean), mean absolute difference about 10 h. When several ENLIL runs existed for an event, the run closest to the observed 1 AU arrival was used, so this flatters the model.
2. J. L. von Forstner et al., *Tracking and Validating ICMEs Propagating Toward Mars Using STEREO Heliospheric Imagers Combined With Forbush Decreases Detected by MSL/RAD*, arXiv:1904.10859 (DOI 10.1029/2018SW002138). 45 ICMEs matched to a Forbush decrease at MSL out of 149 tracked. Mean difference -11 to +5 h depending on method, standard deviation 17 to 20 h. These are heliospheric-imager methods, not ENLIL.

The page uses +/- 20 h around each predicted arrival (top of the 17 to 20 h standard deviation) and shows the 10 h ENLIL figure beside it. At 25 predicted arrivals in 59 days, a 40 h window is occupied most of the time; that is the honest consequence of the error size, and why glancing blows only raise a caution, not a no-go advisory.

## Dust storms

- Dust-storm season is roughly Ls 180 to 360 (Wolkenberg et al. 2018, arXiv:1802.02653, who show dust activity for Ls 180 to 360 in MY 27 to 32; Kass et al. 2016, GRL, classification of A, B and C storms). On 2026-11-13 Ls is about 21 (Allison and McEwen 2000 formula, checked against Ls 110.8 for sol 4600 in `docs/f1_blender_scene.md`), so it is outside the season.
- Machine-readable forecast: none found. MRO MARCI daily global maps are the source. Malin Space Science Systems' weekly Mars weather reports are HTML pages with a movie (mp4 and mov) and no data feed; the report index fetched on 2026-11-13 lists reports only up to 9 February 2022.
- Front speeds used for the one-sighting scenario: 6 to 26 m/s. Source: A. Sanchez-Lavega et al. 2025, *Martian atmospheric disturbances from orbital images and surface pressure at Jezero Crater, Mars, during Martian Year 36*, arXiv:2501.05337, which measured eastward translation of north-polar-edge storms at 6 to 18 m/s, a 15 m/s storm, expansion of regional storms at 19 to 25 m/s and 16 to 26 m/s, with 1 to 2 m/s measurement error. These are measurements from one Mars year, not a forecast distribution.
- Two sightings: speed is the great-circle distance between the centres divided by the time between sightings. The track is the great circle through both centres, assumed constant in speed, heading and radius. The window is the leading edge to the trailing edge passing Gale. No error bar is given because the position error of an operator's reading is unknown.
- Gale is taken as lat -4.8, lon 137.41 E (study-area centre in `phase4/world.py`); Mars mean radius 3389.5 km.

## On the mission page

`demo/twin/hazard_watch.js` adds a panel "Hazard watch" under the suit panel. Radiation items come from `feed.json` (no error if the file is missing; the page shows the reason). An EVA start and length (defaults: now, and the logged plan's nominal round trip plus contingency) are compared with each predicted arrival +/- 20 h. A non-glancing arrival inside the window gives "NO-GO advisory by radiation rule CS-07 (Radiation dose of the round trip exceeds the per-EVA limit)" and "stay near shelter". CS-07 itself is a dose-budget rule; the advisory is a precaution, because a CME arrival is not a dose forecast. Dust scenarios are written to IndexedDB `marswalk-feed`, store `records` (keyPath `id`), and broadcast on `BroadcastChannel("marswalk-feed")` as `{record}`.

## Limits

- Timing error was not measured by us.
- DONKI covers only CMEs an analyst modelled, and gives no uncertainty.
- Arrival at Mars of a CME does not tell you the dose at the surface; atmospheric and terrain shielding are not applied.
- The tool does not predict dust storms.
