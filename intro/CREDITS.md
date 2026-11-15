# Intro film: image sources

Every image in `demo/twin/intro/` is real NASA data; none is AI-generated, and none carries an agency logo. Full provenance
(image URL, SHA-256, fetch time) is in `data/intro_assets/*/provenance.json`, written by the download scripts.

| File | What | Credit | Source |
|---|---|---|---|
| `mars_4k.jpg`, `mars_globe.jpg` | Viking MDIM 2.1 colour mosaic, global, via JPL Mars Trek WMTS (level 3 and 2) | NASA/JPL-Caltech/USGS | https://trek.nasa.gov (layer Mars_Viking_MDIM21_ClrMosaic_global_232m) |
| `mars_normal.png` | Normal map from the MOLA global DEM (463 m), 12x vertical exaggeration | NASA/GSFC/MOLA Science Team; USGS Astrogeology (CC0) | https://astrogeology.usgs.gov (Mars MGS MOLA DEM 463 m) |
| `stars_4k.jpg` | Deep Star Maps 2020, celestial coordinates | NASA/Goddard Space Flight Center Scientific Visualization Studio | https://svs.gsfc.nasa.gov/4851 |
| `gale_mount_sharp.jpg` | Mount Sharp Inside Gale Crater, Mars (PIA15292) | NASA/JPL-Caltech/ESA/DLR/FU Berlin/MSSS | https://photojournal.jpl.nasa.gov/catalog/PIA15292 |
| `hirise_boxwork.jpg` | HiRISE Views Mount Sharp's Boxwork (PIA26306) | NASA/JPL-Caltech/University of Arizona | https://science.nasa.gov/photojournal/hirise-views-mount-sharps-boxwork/ |
| `mastcam_boxwork.jpg` | Curiosity Surveys the Boxwork Region (PIA26693) | NASA/JPL-Caltech/MSSS | https://science.nasa.gov/photojournal/curiosity-surveys-the-boxwork-region/ |
| `mastcam_360.jpg` | Curiosity's First 360-Degree View of Boxwork Patterns (PIA26559) | NASA/JPL-Caltech/MSSS | https://science.nasa.gov/photojournal/curiositys-first-360-degree-view-of-boxwork-patterns/ |
| `hirise_strip.jpg` | HiRISE ESP_094058_1750, enhanced colour, study area outlined | NASA/JPL-Caltech/University of Arizona | PDS (our download, data/raw/mro/hirise) |
| `shot_*.jpg`, `demo30.mp4` | Screenshots and the 30 s demo of MARSWALK itself | MARSWALK team, built from the NASA data above | this repository |
