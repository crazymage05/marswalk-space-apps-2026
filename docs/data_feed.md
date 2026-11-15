# Data feed: how new data reaches the twin

The twin is built from archive data (PDS volumes released months after the fact). This pipeline adds the fast path: poll the public sources, save what came back with its provenance, and let the mission page and the twin pick it up as soon as it exists. You can also upload data by hand in the browser.

```
public NASA sources --> tools/ingest.py --> data/feeds/ (downloads + provenance)
                                        --> demo/twin/feed.json  --> mission.html (feed.js panel) --> twin.html
mission.html upload --> IndexedDB "marswalk-feed"/"records" + BroadcastChannel "marswalk-feed" --> open twin tab
```

## Run it

```
python tools/ingest.py --once              # poll every source once (default)
python tools/ingest.py --watch 30          # poll every 30 minutes
python tools/ingest.py --offline           # rebuild feed.json from disk, no network
python tools/ingest.py --source msl_raw    # one source only (repeatable)
python -m http.server 8782 --bind 127.0.0.1 -d demo/twin     # then open mission.html
```

Files written (never under `data/raw`):

| Path | Content |
|---|---|
| `data/feeds/<source_id>/<UTC date>/` | every downloaded file plus `provenance.json` (url, sha256, bytes, fetched_utc, licence, credit) |
| `data/feeds/state.json` | per-source state returned by `poll()` |
| `data/feeds/records.json` | every record ever ingested, by id |
| `data/feeds/sources.json` | last status of every source |
| `demo/twin/feed.json` | `{generated_utc, sources[], records[]}`, what the pages read |
| `demo/twin/feed/*.jpg` | resized photos referenced by photo records |

Records are de-duplicated by `id`. A source that raises an error shows status `error` and the others carry on.

## Adding a source

Put `tools/feeds/<name>.py` next to the others. Files starting with `_` are not sources (`_common.py` has `http_get` with retries, `save_download` with provenance, and `TwinGeo` for lon/lat to twin x,y). A module exposes:

```python
SOURCE = {"id", "name", "mission", "instrument", "kind", "typical_latency"}
def poll(state: dict) -> (records: list, new_state: dict, status: dict)
```

`status` may carry `newest_observed_utc`, `newest_available_utc`, `items_new`, `status` (`ok`, `no_new`, `error`), `note`, `extra`.

## Record schema

```
{ id, type: "rad"|"photo"|"weather"|"hazard", source, observed_utc, available_utc, ingested_utc, sol,
  label: "measured"|"modelled"|"simulated",
  rad: {uGy_h}, photo: {file, x, y, camera}, weather: {min_C, max_C, pressure_Pa},
  hazard: {kind: "dust_storm"|"cme"|"sep"|"obstacle", start_utc, end_utc|null, center: {lat, lon}|null, radius_km, affects_site, note},
  provenance: {url, sha256, method} }
```

Only the block that matches `type` is present. `photo.x, photo.y` are twin grid cells (585 x 732); `photo.file` is relative to `demo/twin`. Photos from the browser upload carry a `data:image/jpeg;base64,...` URL in `photo.file` instead, because the browser cannot write files; the receiving side has to accept both.

## Sources and measured latency

All requests send the User-Agent `marswalk-demo/1.0`, use timeouts, and retry at most twice with backoff. Every figure below was measured on 2026-11-13.

### msl_raw: Curiosity raw images (`tools/feeds/msl_raw.py`)

- Endpoint: `https://mars.nasa.gov/api/v1/raw_image_items/?condition_1=msl:mission&order=sol desc&per_page=100` (the call `rover_harvest.py` used for the archive), once for all cameras and once per Navcam with `condition_2=NAV_LEFT_B:instrument` / `NAV_RIGHT_B`. Rover position comes from `https://mars.nasa.gov/mmgis-maps/MSL/Layers/json/MSL_waypoints.json` (site + drive to lon/lat).
- Latency, measured from the data itself: `date_received - date_taken` on the newest 100 images (all cameras): median 16.4 h, min 9.8 h, max 17.1 h. On the newest 50 Navcam-left images the median was 11.5 h. The module recomputes this on every poll and puts it in the status line.
- Position: a Navcam image is placed using the waypoint with the same site and drive (or the last earlier one), converted to the twin grid with the same HiRISE projection and coregistration shift that built the twin's own photos (checked: it reproduces the x,y of the last three waypoints in `data.json` exactly).
- Result on 2026-11-13: the newest sol was 5072 at site 125, drive 2274, lon 137.389, lat -4.826. That is inside the twin's ROI box (the southern edge, lat -4.83 to -4.78). So Curiosity is currently still within the area the twin covers, and the 123 new Navcam frames of the first poll all fell inside it. Six were downloaded (spread across the new frames), resized to 720 px and emitted as `photo` records. Frames from outside the ROI would be counted and reported as "outside" and never emitted. Note the twin's terrain and campaign data cover sols 4500 to 4799; these photos are 270 sols later at the same place, so they are real, recent, and placed correctly, but they are not part of the 2025 boxwork campaign.

### pds_release: PDS archive release check (`tools/feeds/pds_release.py`)

- Endpoints: RAD `https://pds-ppi.igpp.ucla.edu/data/MSL-M-RAD-3-RDR-V1.0/DATA/`, REMS `https://atmos.nmsu.edu/PDS/data/mslrem_1001/DATA/`, Navcam `https://planetarydata.jpl.nasa.gov/img/data/msl/MSLNAV_0XXX/DATA/` and `MSLNAV_1XXX`, and the release log and schedule on `https://pds-geosciences.wustl.edu/missions/msl/index.htm`.
- Newest released sol on 2026-11-13: RAD 4843, REMS 4843, Navcam 4843, all from MSL Release 42 (sols 4710 to 4843, posted 3 Aug 2026; the RAD volume folder is dated 29 Jul 2026). The twin has RAD to sol 4801, REMS weather to 4850 (from the weather API, not PDS), Navcam XYZ to 4841.
- Latency evidence: the PDS Geosciences page lists release dates and sol ranges. From the last sol of a release to its public release: R37 131 d, R38 132 d, R39 131 d, R40 130 d, R41 132 d, R42 134 d (median 131 d, about 4.3 months). Sol dates are derived from the twin's REMS dates, so each figure is good to about one day. The page states data is "released by PDS three times a year" (March, August, December); the schedule table lists release 43 (sols 4844 to 4967) for 7 Dec 2026. The oldest sol in a release is about 9 months old when it appears, which is the "about six months" people usually quote; the figure for the newest sol of a release is 4.3 months.
- Records: none, by design. Records are emitted only when a release brings sols inside the campaign window (4500 to 4799) that the twin does not already have. The current release has sols newer than the twin's but outside the campaign.

### rems_weather: REMS daily weather (`tools/feeds/rems_weather.py`)

- Endpoint: `https://mars.nasa.gov/rss/api/?feed=weather&category=msl&feedtype=json` (source of `data/raw/curiosity/rems/nasa_weather_api/weather_msl.json`). One record per sol with min and max air temperature and pressure.
- Latency: the newest sol on 2026-11-13 was 4995 (2026-08-25), 80 days behind. The API gives no publication timestamp, so 80 days is a lower bound and `available_utc` is the time this poller first saw a sol.
- Records: sols after the twin's last weather sol (4850), newest 40 (sols 4956 to 4995), label `measured`.

### space_weather: DONKI (`tools/feeds/space_weather.py`)

Written separately (hazard records: CME arrivals at Mars from WSA-ENLIL, SEP events). It uses the same module interface and shows up in the panel; see its own header for endpoints and labels.

No near-real-time public source for Curiosity RAD dose rates exists: RAD data reaches the public only through PDS. The raw-image API is the only source here that is fast (about a day).

## What a new record changes in the twin

| Record | Effect |
|---|---|
| `rad` | Dose numbers and the GO/NO-GO verdict are recomputed with the new rate (CS-07). |
| `weather` | Temperature and pressure for that sol are replaced or added. |
| `photo` | A pin on the map and the photo in the walk view. |
| `hazard` with a centre inside the map | A red circle on the map. Its cells are blocked for the planner, and the validator fails any route that enters them (rule HZ-1). If the shown route crosses the zone, the twin re-plans it at once and the status line names the record. A start or end point inside a zone is refused. A zone whose `end_utc` has passed no longer blocks, and `end_utc: null` means no end known yet. |
| `hazard` with no centre, or outside the map | A banner only (for example a CME arriving at Mars). |

`obstacle` is for a new blockage seen on the ground or from orbit (rockfall, collapse, a new boulder field); a future rover or orbiter feed can send it with the same schema. `MWTwin.retract(id)` withdraws a zone, and the route is re-planned again. Test: `python tools/hazard_replan_check.py [port]` with `demo/twin` served on the port (17 checks).

New terrain is different. A new elevation model, orbital image or a site elsewhere on Mars goes through the Phase 2 scripts and the exports in `tools/` and `demo/`, which takes minutes to hours; it is not a browser upload.

## Upload in the browser

On `mission.html`, the Data feed panel takes files by drop or file picker. Parsing and validation happen in the browser; nothing is sent to a server.

| File | Format |
|---|---|
| RAD CSV | header `sol,uGy_h[,observed_utc]`; uGy_h between 0 and 1000 |
| REMS CSV | header `sol,min_C,max_C[,pressure_Pa]`; min_C <= max_C, -150 to 60 C, pressure 100 to 1500 Pa |
| Navcam image | JPG or PNG; fill in the form first: sol, camera, and either twin x,y or "near Curiosity's stop on sol N" (uses the last stop at or before N in `data.json`). Resized to 720 px, stored as a data URL |
| JSON | array of records (or `{"records": [...]}`) in the schema above; each record is validated per type |

Every problem is listed with its row or record number ("Row 3: min_C -60 is above max_C -80"). Valid rows are imported and bad rows skipped; if nothing is valid, nothing is imported. The label is `simulated` unless "this is real mission data" is ticked (a JSON record that says `measured` is downgraded and a warning is shown). Each record is saved in IndexedDB database `marswalk-feed`, store `records` (keyPath `id`, version 1), and posted on `BroadcastChannel("marswalk-feed")` as `{record}`. An open twin tab updates at once; a closed one reads the store when it loads. A twin tab may answer with `{ack: id | [ids]}`, which the panel shows as "confirmed by twin". Uploaded ids are `rad-upload-<sol>`, `weather-upload-<sol>`, `photo-upload-<hash>`, so uploading the same sol again replaces it. The panel's "Open twin" button opens `twin.html` in a new tab.

## Limits

- The twin's terrain, routes and rules cover Curiosity's 2025 boxwork campaign (sols 4500 to 4799). New photos and weather are real and recent but are not part of that campaign; the twin shows them as new data, it does not re-plan the 2025 campaign with them. Hazard zones are the exception: they re-plan the route shown.
- RAD and Navcam XYZ for new sols reach PDS about 4 months after the last sol of a release; nothing public is faster.
- The REMS weather summary has no publication timestamp, so its latency is a lower bound.
- Photo placement is the waypoint of the image's drive, not the exact stop; images from before a later drive in the same sol can be a few metres off.
- The Python validator (`phase4/safety_validator.py`) does not read live hazard records; HZ-1 is checked in the browser only.
- Browser uploads live in one browser profile. They are not shared between machines and are cleared by "Clear my uploads" or by clearing site data.
- If `feed.json` is missing the panel says so and uploads still work, but the browser itself logs a 404 line in the console for the failed request; no script error is raised. Running `ingest.py` once (even `--offline`) creates the file.
