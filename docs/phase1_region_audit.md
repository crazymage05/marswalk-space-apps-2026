# Phase 1: region selection and data audit

Status: closed on 2026-11-11. The study area is frozen as `gale_boxwork_roi_01` and every product
selected for it is on disk and checked against its archive listing (four CRISM products on
purpose as summary-parameter subsets, without the full I/F cubes).

## Decision

The study area is a 2.36 × 2.96 km box on the lower slopes of Mount Sharp, Gale Crater:
planetocentric latitude 4.83° S to 4.78° S, east longitude 137.37° to 137.41°
([roi.json](../data/metadata/roi.json)). It contains the ground Curiosity crossed during its 2025
boxwork campaign (sols 4500–4799, at roughly 4.809–4.793° S and 137.379–137.390° E), with margin
on all sides that also takes in the drive from about sol 4300 to sol 5069.

We chose it for two reasons. First, the challenge brief uses this campaign as its worked example.
Second, it is the only area in either crater where a 1 m terrain model, 25 cm imagery, mineral
maps, thermal images, a radiation record and a weather record all overlap a rover's actual path.

## Gale against Jezero

Both craters were catalogued through the Mars Orbital Data Explorer with the same method: a
bounding box around each rover's traverse, then every CTX, HiRISE, CRISM, THEMIS and MOLA
product whose footprint meets it (6,178 products in all). The numbers below come from
[coverage_report.json](../data/metadata/coverage_report.json) and
[roi_candidates.json](../data/metadata/roi_candidates.json).

| Criterion (plan 3.4) | Gale (Curiosity) | Jezero (Perseverance) |
|---|---|---|
| HiRISE stereo DTMs crossing the traverse | 6 of 15 | 3 of 6 |
| HiRISE images crossing the traverse (PDS3 + PDS4) | 144 | 123 |
| CRISM map-projected mineral products on the traverse | 11 | 5 |
| THEMIS IR brightness-temperature images on the traverse (IRPBT2 / IRPBT4 products) | 111 / 72 | 48 / 116 |
| 2 km windows on the traverse where DTM, HiRISE, CTX, CRISM and THEMIS all fully overlap | 42 of 54 | 19 of 42 |
| Rover localizations (waypoints) | 1,387 | 708 |
| Ionizing radiation measured on the surface | RAD, archived in PDS | none (Perseverance has no radiation detector) |
| Daily weather summaries from NASA's weather service | 4,745 sols | 7 sols |

Jezero has more recent HiRISE colour coverage (46 PDS4 products against 12), but it loses on
terrain models, mineral maps and, decisively, radiation: criterion 6 asks for radiation data or a
documented alternative, and only Curiosity carries a detector. Gale wins on every criterion that
the astronaut-safety layer depends on.

## Layers inside the study area

Coverage is the fraction of the study area inside each product's footprint. Resolutions were
checked against the product labels; three kinds of ODE catalogue value were wrong and are
corrected in the manifest (HiRISE PDS4 and THEMIS PDS4 list pixels per degree, and MOLA MEGDR lists
a placeholder).

| Layer | Product(s) | Resolution | Coverage | Limitations |
|---|---|---|---|---|
| Terrain | `DTEEC_009149_1750_009294_1750_U01` | 1.01 m | 100% | Stereo DTM; heights are relative to the Mars areoid and are smoothest on bland slopes. Built from 2008 images. |
| Terrain (second) | `DTEEC_019698_1750_019988_1750_U01` | 1.01 m | 99.4% by footprint (its data fills the whole grid) | Independent DTM from 2010 images, kept to cross-check the first. |
| Orthoimages | DTM orthos `PSP_009149_1750_RED_A_01_ORTHO` and others | 0.25 m and 1 m | 100% | Same grid as the DTM, so no reprojection is needed. Greyscale. |
| Recent image | `ESP_094058_1750` RED and colour | 0.25 m | 100% (colour 51%) | Taken 2026-08-20. On its own map grid, so it must be registered to the DTM in Phase 2. |
| Context images | CTX `W04_090551`, `W08_092120`, `W10_092766` | 5.3–5.4 m | 100% | Raw EDR: needs radiometric calibration and map projection before use. |
| Minerals | CRISM MTRDR `frt000058a3`, `frt0000b6f1`, `hrl0000baba` | 18 m (36 m for HRL) | 100% | Summary-parameter files only; the full I/F cubes (about 1 GB each) were not downloaded. Two more cubes (`frt0001bba1`, `frt0001ca91`) touch only 5–8% of the area. |
| Thermal | THEMIS IR, 30 images: 29 at 100 m and 1 at 400 m | 100–400 m | 100% | Coarse for a 2 km area: the 100 m set gives about 23 × 29 pixels across it. Day or night must be read from each label before thermal inertia work. |
| Regional elevation | MOLA MEGDR `megt90n000fb` | 1.85 km | 100% | Context only; one pixel is wider than half the study area. |
| Radiation | RAD RDR (`MSL-M-RAD-3-RDR-V1.0`) | per observation | campaign sols | Dose rate in µGy/h at the rover; every 50th sol of the mission plus every 10th campaign sol. |
| Weather | REMS MODRDR (RMD) and NASA daily summaries | per second; per sol | campaign sols | Detailed records for every fifth sol, 4500–4795, from two PDS releases (the second, of 2026-07-31, starts at sol 4710). Daily summaries contain sentinel values (−100 °C) that must be filtered. |
| Ground imagery | Navcam and Mastcam full frames | 1024 px | sols 4500–4799 | 2,130 raw JPEGs, not calibrated PDS products. Located by the rover's drive position, not per image. |
| Rover path | MMGIS traverse and waypoints | per drive | whole mission | Localizations as published by the rover team. |

## Gaps

Two gaps found during Phase 1 were closed on 2026-11-12 (details in `docs/gapfill_report.md`).
Space-weather notices from NASA DONKI were fetched through api.nasa.gov for 2025-04-01 to
2026-02-28 (845 notices, including X-class flares, solar energetic particle events and CMEs listed
as heading for Mars), together with 332 NOAA daily solar event reports. A newer REMS release
(2026-07-31) covers sols 4710–4843, and every fifth sol from 4710 to 4795 was added, so the
detailed weather records now span the whole campaign. RAD's surface measurements remain the
radiation layer; the notices add the timing of solar events.

Still unavailable: a published 2025 dust opacity table for Gale, and a recent published RAD dose
equivalent (the reference remains Hassler et al. 2014: 0.21 mGy and 0.64 mSv per day).

## Outputs

| File | Contents |
|---|---|
| `data/metadata/dataset_manifest.json` | 6,183 records in the plan's section 6.2 schema: 6,178 orbital products plus 5 rover datasets. Each orbital record says whether it meets the study area, how much of it, whether it was selected, and whether its files are on disk. |
| `data/metadata/roi_coverage.json` | Per-layer coverage of the study area and the validation result for each of the 43 selected products (44 records, because `megt90n000fb` is listed for both regions). |
| `data/metadata/coverage_report.json` | Coverage matrix for Gale and Jezero. |
| `data/metadata/roi_candidates.json` | Ranked 2 km windows along each traverse. |
| `data/metadata/footprints_gale.png`, `footprints_jezero.png`, `footprints_roi.png` | Footprint maps. |
| `data/metadata/deleted_files.jsonl` | Every file removed when the download was narrowed to the study area. |

To regenerate everything from the catalogue: `python region_audit.py`.
