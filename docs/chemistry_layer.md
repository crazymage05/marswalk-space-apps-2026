# Rock chemistry layer (ChemCam LIBS, APXS)

The challenge lists chemical data as one of the layer types. This layer shows what Curiosity measured in the rock itself at the boxwork campaign targets, sols 4500-4799, on the twin's terrain.

## Sources (all public, fetched 2026-11-13 by `tools/fetch_chem.py` into `data/chem_b/`, hashes in `data/chem_b/provenance.json`)

| What | URL |
|---|---|
| ChemCam major-oxide tables (MOC), sols 4489-4843 | https://pds-geosciences.wustl.edu/msl/msl-m-chemcam-libs-4_5-rdr-v1/mslccm_1xxx/data/moc/ (`moc_4489_4612`, `moc_4613_4709`, `moc_4710_4843`) |
| ChemCam observation table (sol, target name, rover site and drive, distance) | .../mslccm_1xxx/document/msl_ccam_obs.csv |
| APXS oxide tables (`*rwp*.csv`) and labels (sol, site, drive) | https://pds-geosciences.wustl.edu/msl/msl-m-apxs-4_5-rdr-v1/mslapx_1xxx/data/solNNNNN/ |
| PDS release page (what each release covers) | https://pds-geosciences.wustl.edu/missions/msl/index.htm |
| Rover positions per site and drive | https://mars.nasa.gov/mmgis-maps/MSL/Layers/json/MSL_waypoints.json |

Credit: NASA / PDS Geosciences Node. ChemCam: Los Alamos National Laboratory and IRAP. APXS: University of Guelph. Positions: NASA/JPL MMGIS.

## Coverage

The newest release on the PDS page is MSL Release 42 (sols 4710-4843), so the whole campaign window is archived.

- ChemCam: 221 targets on 214 sols (4500-4799). 42 are AEGIS autonomous targets (names start `aegis_post_`). Every record in the MOC tables was matched to the observation table.
- APXS: 128 oxide products on 80 sols (4500-4791).
- All 349 sit inside the twin's terrain grid. For all 349 the rover's exact (site, drive) was in the waypoint file.
- The APXS archive ships a separate derived-data supplement only up to sol 3712, so the target names for APXS are not in the PDS product. APXS markers are named by sol.

## Method

1. ChemCam: each MOC row is one laser point. Rows are joined to the observation table by spacecraft clock, which gives sol, target name, site and drive. Points of one target are averaged. The card shows the mean wt% of SiO2, TiO2, Al2O3, FeOT, MgO, CaO, Na2O, K2O, MnO, the instrument's model error (RMSEP, averaged over points) and the point-to-point spread in the JSON.
2. APXS: the label gives sol, site and drive; the csv gives wt% and the statistical precision for Na2O, MgO, Al2O3, SiO2, P2O5, SO3, Cl, K2O, CaO, TiO2, Cr2O3, MnO, FeO plus Ni, Zn, Br (elements, listed as weight percent in the file).
3. Position: the MMGIS waypoint for the rover's (site, drive), converted to a twin grid cell with the same projection and HiRISE coregistration as the Navcam photos (`TwinGeo` in `tools/feeds/_common.py`, reused read-only).
4. `tools/export_chem_twin.py` writes `demo/twin/chem.json`. `demo/twin/chem.js` (one script tag) adds the layer toggle, draws markers on its own canvas using the page's camera and terrain, and opens a card with oxide bars on hover or click. Pink circles are ChemCam, green diamonds APXS. Targets that share a waypoint are fanned out on a small ring so each can be clicked.

## What NASA says about boxwork chemistry

Only qualitative statements were found and the layer adds none of its own. NASA, 23 June 2025, "NASA's Curiosity Mars Rover Starts Unpacking Boxwork Formations" (https://www.nasa.gov/missions/mars-science-laboratory/curiosity-rover/nasas-curiosity-mars-rover-starts-unpacking-boxwork-formations): "The bedrock between the boxwork ridges has a different composition than other layers of Mount Sharp." and "The bedrock below these ridges likely formed when groundwater trickling through the rock left behind minerals." No paper with ridge-versus-hollow oxide numbers was found, so none is cited. Comparing ridge and hollow targets from this layer is left to the reader; the layer does not classify targets as ridge or hollow.

## Limits

- Position is the rover's waypoint, not the target. ChemCam targets were about 2 to 7 m away (distance is in the JSON); APXS is placed within arm reach. One grid cell is 4 m, so expect an error of about 2 cells or more. Nearly all targets of one drive share a point.
- ChemCam LIBS oxide values are model estimates with RMSEP errors of several wt% for the major oxides; one target's mean is of about 5 points. FeOT is all iron as FeO. Sums of oxides are not forced to 100%.
- APXS errors shown are statistical precision, not accuracy.
- The layer does not filter by rock type or tell ridge targets from hollow ones, and the PDS tables do not say which a target is.
- Tag is "measured" (PDS data); nothing on the layer is modelled.
- Coverage ends at the PDS archive: later sols appear only after the next release.
