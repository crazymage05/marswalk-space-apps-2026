# Phase 2: data engineering

Status: closed on 2026-11-11. Every layer for the study area `gale_boxwork_roi_01` is on one map
grid in `data/processed/roi/` (420 MB), and `python run_phase2.py` rebuilds all of it from
`data/raw` in about 15 minutes.

## The grid

All rasters share the native grid of HiRISE DTM `DTEEC_009149_1750_009294_1750_U01`, cropped to
the study area: equirectangular on a 3,396.19 km sphere, central meridian 137.41° E, 2,340 × 2,928
pixels of 1.0117 m. Finer and coarser layers use the same origin with an integer factor (0.25 m
for HiRISE images, about 18 m for CRISM, about 101 m for THEMIS). The definition lives in
[marswalk_grid.py](../marswalk_grid.py); every layer also has a JSON record in
`data/processed/roi/registry/`, merged into `layers.json`.

## Layers

| Group | Files | Resolution | Notes |
|---|---|---|---|
| Terrain | `elevation_m`, `slope_deg`, `aspect_deg`, `roughness_m`, `tri`, `hillshade` | 1 m | Slope and aspect from Horn's 3 × 3 method. Roughness is the standard deviation left after fitting a plane over 5 × 5 m. Median slope 11.1°; 15.7% of the area is steeper than 25° and 9.7% steeper than 30°. |
| Second terrain model | `elevation_alt_aligned_m`, `elevation_diff_aligned_m` | 1 m | DTM `DTEEC_019698_1750_019988_1750_U01`, moved onto the first (see co-registration). |
| Orthoimages | `ortho_025m`, `ortho_1m` | 0.25 m, 1 m | From the DTM's own orthos, so they share its geometry exactly. |
| Recent image | `hirise2026_red_025m`, `hirise2026_red_1m`, `hirise2026_color_05m` | 0.25 m, 0.5 m | `ESP_094058_1750`, taken 2026-08-20; 99.4% coverage (colour 99.9%). |
| Minerals | `crism_su_<product>` (60 parameters each), `crism_mineral_params` (15) | ~18 m | Per-pixel median of three CRISM MTRDR products, all covering the whole area. |
| Thermal | `themis_day_*`, `themis_night_*` | ~101 m | 27 usable images, band 9 (12.57 µm), brightness temperature in K. |
| Regional elevation | `mola_context_m` | ~101 m (source 1.85 km) | Context only. |
| Rover path | `vectors/traverse_*.geojson`, `tables/waypoints*.csv` | per drive | 1,387 waypoints, 262 inside the area. |
| Radiation | `tables/rad_observations.csv`, `rad_per_sol.csv` | per observation | 21,990 observations; 11,441 carry dose values. |
| Weather | `tables/rems_rmd_campaign_hourly.csv`, `rems_daily.csv` | hourly; daily | 1.35 million REMS records reduced to 1,014 sol-hours; 4,745 daily summaries. |
| Rover photos | `tables/images_index*.csv` | per image | 2,130 images with positions; 1,548 matched to their exact drive, 582 to the last drive before them. |

## What the checks found

**Curiosity's positions are offset from the terrain model.** Comparing the elevation Curiosity
recorded at its 262 stops in the area with the DTM at the same coordinates gave a scatter (NMAD)
of 9.1 m. Moving the rover positions 92 m west and 35 m south brings it to 2.2 m, so the published
rover localizations and the DTM do not share the same horizontal control. Repeating the search on
each half of the route gives 65–92 m west and 0–35 m south, so the east-west correction is well
determined while the north-south one is good to about ±25 m. The registered tables
(`*_registered.csv`, `traverse_lines_registered.geojson`) carry the corrected positions; the
originals are unchanged. A vertical difference of about +10 m remains, which is the difference
between the rover's geoid heights and the DTM's areoid heights.

**The two DTMs are offset from each other by about 98 m east and 15 m south.** After moving the
second DTM onto the first, their elevations agree to an NMAD of 2.35 m (12.1 m before), with a
median difference of −7.4 m.

**The 2026 HiRISE image was 148.5 m out in north-south.** Single HiRISE images are placed from the
spacecraft's pointing alone, while the DTM is tied to the MOLA laser altimeter, so an offset of
this size is expected. After correction the north-south error is 1–2 m. East-west alignment is
poorer: an independent check on tiles not used for the fit found per-tile offsets from 0.5 to 32 m,
with a median of about 13–17 m, because the 2008 and 2026 images are lit very differently and
correlate weakly. Use this image for display only; distances and slopes come from the DTM, and the
twin's walk uses the 2008 orthoimage, which shares the DTM's geometry exactly.

**CRISM has about one pixel (18 m) of position uncertainty**, because the label and the ENVI header
of each product place it 18 m apart. We used the label.

**THEMIS cannot give a clean sand-versus-rock map.** Every usable image was taken within about 1.5
hours of sunrise or sunset (local times 5.9–7.4 h and 17.7–19.4 h). There is no afternoon or
pre-dawn image, and at about 101 m per pixel the study area is only 23 × 29 cells. The dawn images
can still flag ground that held heat overnight (rock) against ground that did not (loose material),
but only as a coarse hint. Note that the files named `themis_day_*` and `themis_night_*` split
the images at 6 h and 18 h local time, so each mixes dawn and dusk images; the navigation grid and
the twin select the 12 images taken before 9 h instead.

**MOLA sits 28 m below the HiRISE DTM on average**, which is within the expected difference
between the two products.

## Data problems recorded

- 1,049 RAD observations have no Mars time (`START_OBS_MARS="N/A"`) and were skipped.
- REMS detailed records first stopped at sol 4706, where the PDS release then ended. A newer
  release (2026-07-31) added sols 4710–4843; every fifth sol up to 4795 is now included, and the
  hourly table covers sols 4500–4796 (1,414 sol-hours from 1.91 million records, 70 files, all
  matching their labels' row counts).
- 4 malformed lines in the REMS file for sol 4660 were dropped. The file matches its label's row
  count, so the lines are malformed at the source.
- 10 daily minimum air temperatures and 69 daily minimum ground temperatures were sentinel values
  (−100 °C or lower) and were removed.
- CTX images were not processed: the raw EDR products need ISIS camera models and SPICE kernels
  for calibration and map projection, and HiRISE already covers the area at 20 times finer
  resolution.

## Rebuild

A full rebuild on 2026-11-11 reproduced all 36 output rasters and tables byte for byte, and
`phase2/validate.py` passes 64 of 64 checks (grid alignment, value ranges, registry entries, slope
recomputed from elevation, registered waypoints against the DTM, RAD dose rate); the results are in
`data/processed/roi/validation_report.json`. An earlier count of "62 of 62" was wrong: the rock
density layer, added later and covering only the walk corridor, failed the 90% coverage rule until
the validator was given per-layer minimums. The validator samples rasters at reduced resolution, so
its value ranges are approximate; an independent full-resolution check is in
`docs/verification/02_phase2.md`.

```
python run_phase2.py                  # five build steps, validation, then layers.json
python run_phase2.py coregister       # one step
```

Steps: `phase2/terrain.py`, `phase2/hirise_recent.py`, `phase2/spectral_thermal.py`,
`phase2/rover_tables.py`, `phase2/coregister.py`, then `phase2/validate.py`.
