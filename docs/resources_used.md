# Challenge resources used

The challenge's Resources tab lists: JPL Mars Trek; USGS-NASA Planetary Geologic Mapping Program; the Curiosity route-map animation for lower Mount Sharp; NASA Worldview; Mars Perseverance Raw Images Gallery. This file says how each one is used, where, and what it does not do.

## Mars Perseverance Raw Images Gallery

- **Used for:** a second live point-of-view source, and a measured latency comparison with Curiosity.
- **Endpoint:** `https://mars.nasa.gov/rss/api/?feed=raw_images&category=mars2020&feedtype=json&num=100&order=sol+desc` (no key). Camera filter: `&search=NAVCAM_LEFT`, `NAVCAM_RIGHT`, `MCZ_LEFT`, `MCZ_RIGHT`. The `raw_image_items` API that serves Curiosity returns nothing for `mars2020:mission`, so Perseverance needs this one.
- **Code:** `tools/feeds/m2020_raw.py` (same `SOURCE` / `poll` interface as `msl_raw.py`, run by `python tools/ingest.py --once`).
- **What it does each poll:** reads the newest 100 images, computes latency as `date_received` minus `date_taken_utc` (median, min, max), picks the newest Navcam and Mastcam-Z frames, saves them with provenance (URL, SHA-256, time, credit) under `data/feeds/m2020_raw/<UTC date>/`, and copies resized thumbnails to `demo/twin/feed/m2020/`.
- **Shown in:** mission control (`demo/twin/feed.js`), card "Perseverance (Jezero) today": newest sol, camera, taken time, per-image latency, median latency next to Curiosity's, credit NASA/JPL-Caltech, link to the gallery page.
- **Measured on 2026-11-13:** newest Perseverance frame sol 2031 (taken 2026-11-06); median exposure-to-public latency 106 h over the newest 100 images (min 3.6 h, max 114 h), against 16.5 h for Curiosity.
- **Limits:** Perseverance is in Jezero, so its frames are not placed on the Gale twin map and produce no twin records. The newest 100 images by sol are biased to the latest downlink batch, so the median is a snapshot, not a long-run figure.

## NASA Worldview / GIBS

- **Used for:** imagery of the Earth end of the Mars link, around the three Deep Space Network complexes.
- **Endpoint:** NASA GIBS WMS, `https://gibs.earthdata.nasa.gov/wms/epsg4326/best/wms.cgi` (WMS 1.1.1, EPSG:4326, no key). Layers: `VIIRS_NOAA21_CorrectedReflectance_TrueColor` (falls back to NOAA20, SNPP, MODIS Aqua, MODIS Terra, whichever covers the box best) with `IMERG_Precipitation_Rate` composited on top.
- **Sites (JPL DSN Radio Astronomy User Guide, Table 1.1):** Goldstone 35.281 N, 116.779 W; Madrid 40.429 N, 4.250 W; Canberra 35.402 S, 148.982 E. Each image covers 6 by 4 degrees (about 540 by 440 km).
- **Code:** `tools/feeds/gibs_dsn.py`. It uses one UTC date for all sites: the newest of the last four days for which GIBS already serves IMERG precipitation (GIBS returns a blank tile while a day is unpublished, so an all-dry day looks the same and falls back one day). Downloads and provenance go to `data/feeds/gibs_dsn/<UTC date>/`; thumbnails to `demo/twin/feed/gibs/`.
- **Shown in:** mission control, card "Earth side: DSN ground stations (NASA Worldview/GIBS)": three thumbnails with date, layers, share of pixels with rain, and a Worldview deep link per site, built as `https://worldview.earthdata.nasa.gov/?v=<west>,<south>,<east>,<north>&l=IMERG_Precipitation_Rate,<true colour layer>,Coastlines_15m&t=<date>-T12%3A00%3A00Z`.
- **Limits:** context only. Rain and cloud do degrade Ka- and X-band links, but MARSWALK does not compute link margins or attenuation. The "rain pixels" figure is the share of the box with any IMERG precipitation, not a rain rate at the antenna.

## Curiosity route map and animation for lower Mount Sharp

- **Source:** NASA Science, "Curiosity's Proposed Path up Mount Sharp" (PIA23179, 15 May 2019), credit NASA/JPL-Caltech/ESA/University of Arizona/JHUAPL/MSSS/USGS Astrogeology Science Center. Page: `https://science.nasa.gov/resource/curiositys-proposed-path-up-mount-sharp/`. Flyover video: "Video: Fly over Mount Sharp on Mars", `https://www.jpl.nasa.gov/news/video-fly-over-mount-sharp-on-mars/` (also `https://mars.nasa.gov/news/8437/video-fly-over-mount-sharp-on-mars`).
- **Downloaded:** the 1041 x 586 animated GIF (12 frames) and its first (route only) and last (annotated) frames, with provenance, in `data/nasa_route_map/`. The video is linked, not downloaded.
- **Shown in:** `demo/twin/index.html`, section "NASA's own route map vs MARSWALK", beside a screenshot of the twin's planned route.
- **Difference:** NASA's map labels the regions the science team wants to reach, at kilometre scale. MARSWALK plans a suited walk at 4 m cells and checks it against flight rules. The two cover the same mountain but not the same ground: NASA's map runs from the clay-bearing unit to Gediz Vallis, and the twin covers the later boxwork stretch.
- **Limits:** the map is a 2019 plan, not the route Curiosity actually drove.

## JPL Mars Trek

- **Used for:** a 10 m orbital image layer on the twin terrain, three context maps around the study area, and a deep link into Trek.
- **Endpoints (public, no key):** layer catalogue `https://trek.nasa.gov/mars/TrekServices/ws/index/eq/searchItems?start=0&rows=300`; WMTS REST tiles `https://trek.nasa.gov/tiles/Mars/EQ/<layer>/1.0.0/default/default028mm/<z>/<row>/<col>.<png|jpg>`; the geology layer is served from `https://trek.nasa.gov/mars/trekarcgis/rest/services/SIM3292_Global_Geology/MapServer/WMTS/...`. Grid: equirectangular Mars 2000 sphere, 256 px tiles, level 0 is 2 x 1 tiles, tile size 180/2^z degrees.
- **Layers:** `Gale_CTX_BlockAdj_dd` (MRO CTX Gale mosaic; level 12 is its finest, about 10 m/px), `Mars_MGS_MOLA_ClrShade_merge_global_463m`, `SIM3292_Global_Geology`. The catalogue also lists `curiosity_hirise_mosaic` and `curiosity_ctx_mosaic`; they were not used, because the twin already has the HiRISE image from the PDS and the Gale mosaic is the larger CTX product.
- **Code:** `tools/fetch_marstrek.py` (only the tiles inside the study-area and context windows, 1 s apart, `User-Agent: marswalk-demo/1.0`; 66 tiles, 4 MB; provenance with URLs, layer ids, SHA-256, fetch time and credit in `data/marstrek/provenance.json`), then `tools/export_marstrek_twin.py` -> `demo/twin/marstrek_ctx_roi.jpg`, `marstrek_ctx.jpg`, `marstrek_mola.jpg`, `marstrek_geo.jpg`, `marstrek.json`.
- **Shown in:** `demo/twin/twin.html`: Layers checkbox "Mars Trek: MRO CTX Gale mosaic (10 m)" (drawn over the HiRISE photo on the terrain); card "Context map" with CTX, MOLA relief, Trek geology and USGS unit views and the study area outlined; link "Open this spot in Mars Trek"; rows in the data table.
- **Deep link:** `https://trek.nasa.gov/mars/#v=0.1&x=<lon>&y=<lat>&z=12&p=urn%3Aogc%3Adef%3Acrs%3AEPSG%3A%3A104905&d=&l=Gale_CTX_BlockAdj_dd%2Ctrue%2C1&b=mars`. Trek has no documented URL format; this one was checked by loading it in Chrome, where Trek opened on the Gale CTX mosaic at the site.
- **Measured offset:** the Trek CTX mosaic shows the twin's HiRISE terrain about 900 m east and 46 m south of the nominal study-area longitude and latitude (band-passed normalised cross-correlation, peak 0.59, next peak 0.21). The exported CTX image is shifted by that amount so it lies on the HiRISE terrain, the link and the CTX context box use the shifted centre, and the offset is recorded in `marstrek.json`. The cause is not established: it could be the CTX mosaic's own registration or the DTM chain.
- **Limits:** CTX at 10 m is coarser than the 1 m HiRISE the twin is built on, so the layer is a cross-check and context, not new detail. Trek's geology tiles are a picture of the USGS map, not data; the unit polygons come from the USGS feature service below.

## USGS-NASA Planetary Geologic Mapping Program

- **Used for:** the geologic unit under every cell, a "Geologic units (USGS)" layer with legend, and a unit row in the cell card.
- **Source:** USGS Astrogeology feature service behind the program's hub, `https://services.arcgis.com/v01gqwM5QqNysAAi/arcgis/rest/services/Tanaka_et_al_2014_Mars_Global_Map_Features/FeatureServer/3` (Global_Geology polygons). Map: Tanaka et al. (2014), Geologic map of Mars, USGS SIM 3292, 1:20,000,000, `https://pubs.usgs.gov/sim/3292/`.
- **Larger scale:** searched the USGS publications warehouse and the hub. No larger-scale USGS geologic map of Gale crater exists; the 1:1M or larger Mars SIMs cover Jezero, Shalbatana, Athabasca, Nepenthes, Ladon, Candor and Olympus Mons. SIM 3292 is therefore the USGS product for this site.
- **Code:** `tools/fetch_usgs_geology.py` (layer metadata, polygons in a 0.8 degree window, legend text of the units in it; provenance in `data/usgs_geology/provenance.json`), then `tools/export_geology_twin.py` -> `demo/twin/geology.json` (unit index per 4 m cell, legend with name, group, epoch and the map's own colours and descriptions, citation, scale, simplified outlines for the context map).
- **Result:** the whole study area (428,220 cells) is one unit, Htu, "Hesperian transition undivided unit" (layered plateau material with hydrated sulfate signatures in places, interpreted as fine-grained eolian and pyroclastic deposits modified by fluvial and eolian erosion). The impact unit AHi, which is the Gale crater unit around the mound, lies to the west and north.
- **Limits:** at 1:20,000,000 one millimetre is 20 km. Unit boundaries are kilometres off at best, so the layer says which unit the map assigns to this spot, not where a contact lies, and it cannot separate the boxwork from the rock around it. The epoch is read from the unit code (H = Hesperian) and the absolute ages are the approximate crater-model boundaries given with the map. Text fields from the service arrive with a character-encoding fault (degree signs), repaired in the export, and type-locality coordinates from elsewhere on Mars are dropped from the descriptions.
