# Film clip for any route planned in the twin

```
python tools/render_route.py "<share link or #hash>" [--name NAME] [--preview | --final] [--seconds N] [--timelapse] [--tail N] [--raw-scans | --twin-scans] [--resume]
```

The link is what the twin's Share button copies (`demo/twin/share.js`: `s` sol, `r` route kind, `a`/`b` cells, `d` destinations, `m` slope limit, `kg`, `pair`, `rv`, ...).
`default` (or an empty hash) is the campaign route, the same as the "Campaign start -> end" button.
Everything lands in `film/routes/<name>/` (name defaults to `route_<hash of the link>`).

## What it does
1. **Route from the page.** It serves `demo/twin` on 127.0.0.1:8789, opens `twin.html?notour#<hash>` in headless Chrome (GPU flags as in `tools/twin_check.py`),
   waits until the route has not changed for 3 s and the flight-rule verdict is shown, and reads the planned cells with the existing hook `window.__routeCells()`,
   the sol, slope limit, crew state (`window.__crew.state()`), multi-stop state (`window.__multiState()`), planner weights, the verdict text and the Distance/Time/Climb/Steepest/Dose boxes.
   Written to `route.json` with the link, UTC time, git commit and the film parameters. No change to `twin.html` was needed.
2. **Scene.** `tools/f1_prep_data.py` runs in route mode (`F1_ROUTE_FILE`, `F1_OUT`): a 1 m terrain window around the filmed part of the route
   (300 m margin; the whole route plus 150 m in a time-lapse; at most 3 M pixels), the route cells as the walked route, the sun for the route's sol. Then `tools/f1_blender_scene.py` (`F1_DATA_DIR`, `F1_OUT_BLEND`) builds the
   scene, and `tools/f2_suitfix.py` adds the backpack. Result: `scene.blend`. Without these environment variables both scripts behave as before
   (the files written by `f1_prep_data.py` with no route variables are byte-identical to the previous version's; the default `f1_blender_scene.py` build has the same objects, vertex hashes, keyframes, markers and NLA strips as before).
3. **Clip.** Shot 1 is an aerial establishing crane (default 4 s): it starts high over the whole route, always at least 1.3 x its height away horizontally (never a top-down view), so the cyan line reads, and comes down behind the walker.
   Then the walk (`--seconds`, default 20) cuts between walk-level cameras that follow the suit, as in the film (Cam_2_walk, Cam_2b_close, Cam_2c_low; timeline markers):
   chase 30 %, close behind the shoulder 25 %, low beside the route 25 %, chase again 20 %.
   Real speed is 0.9 m/s (the walk cycle's own speed): 20 s covers 18 m. `--timelapse` walks the whole route in `--seconds` (speed-up = length / (0.9 x seconds), capped by `--max-speedup`, default 400): a follow-drone
   (pitch limited to about 31 degrees, always above the ground) for all but the last `--tail` seconds (default 8), then the walk slows to real speed for the end of the route and cuts low / close / chase so the suit is readable.
   The leg cycle in the time-lapse part is capped at 6x. Real-speed clips start so the walker crosses a Navcam scan if the route passes one (`--start-s` overrides).
   Scans are cleaned as in the twin (see below); `--raw-scans` shows the raw stereo meshes. The suit is the film's (w5b walk GLB, which already carries the PLSS backpack; `f2_suitfix.py` adds one only if the GLB has none, so route scenes do not get a second, coincident copy).
4. **Render.** `--preview` (default): Cycles 16 spp + OptiX denoise, 960x540, every 2nd frame, encoded at 12 fps (`--engine eevee`, `--step`, `--res`, `--spp`, `--first/--last` change this).
   `--final`: Cycles 64 spp, 1920x1080, every frame, 24 fps, `final.mp4`. Each render chunk (40 frames, one Blender process) runs under `gpu_lock("render_route-<name>")` with `wait_cool()` before it.
   Frames get a two-line caption (the twin's own sol, distance, walking time, climb, flight-rule GO/NO-GO and number of stops; data credits and render settings; text shrinks to fit) and are encoded to `preview.mp4` / `final.mp4` by Blender's sequencer (no ffmpeg here).
   `--build-only` stops after `scene.blend`; `--reuse-route` skips the browser and uses the existing `route.json`.

## Scan clean-up (the twin's `fitScan`, plus film tuning)
Raw Navcam stereo meshes have "curtain" triangles at depth gaps and drift from the HiRISE surface (from above they render as a spiky starburst). `f1_blender_scene.py` has an option (`F1_SCAN_CLEAN=1`, or `scan_clean` in the route's film parameters,
which `render_route.py` sets unless `--raw-scans`; default off, so the film is unchanged) that does what the twin does when a scan loads:
(1) residual r = scan - HiRISE per vertex, L = median of r per 1 m cell then median over 5 x 5 cells, vertex = HiRISE + clamp(r - L, -0.2, +0.4 m);
(2) drop triangles with an edge > 0.6 m, or near-vertical (|n.z| < 0.3) and longer than 0.15 m.
With exactly those limits (`--twin-scans`) the stereo patches that remain still look like floating paper flakes in a walk-level close-up, which is why the twin keeps its "3D scans" toggle off by default.
So route clips use tighter film settings by default (env `F1_SCAN_CLAMP=-0.1,0.15`, `F1_SCAN_EDGE=0.35`, `F1_SCAN_NZ=0.75` = also drop facets steeper than 41 degrees, `F1_SCAN_MINCOMP=1200` = also drop islands under 1200 triangles):
about 80-90 % of the triangles of a scan go, and what is left is a few small flakes. The build log prints the dropped and clamped counts per scan. The ground you see is mostly the HiRISE ortho and DTM.

## Real data, and what is illustrative
Real: the route (the twin's own A* cells and its verdict/numbers), terrain height (HiRISE DTM, 1 m) and colour (HiRISE ortho, 25 cm), the Curiosity Navcam 3D scans that fall inside the terrain window (placed at their measured anchors),
detected boulders (`demo/twin/rocks.json`: real positions and sizes inside the window), Navcam-derived ground textures by ground type (`material_4m.json`), the sun for the chosen sol (`phase4.world`: elevation, azimuth, Ls) and the climatological dust optical depth.
Illustrative: pebbles (random, at the twin's densities), boulder and pebble shapes, the polygonal fracture network and soft tonal patches in the ground, the Mark III suit and its walk cycle (a loop, no terrain-adapted feet), the backpack (not a specific NASA part), the sky colour.
Outside the 1 m window, terrain is the 4 m context mesh (HiRISE ortho, lowered 0.6 m), only seen in the overview and at the horizon.

## Limits
- The suit walks at 0.9 m/s whatever the twin's astronaut model computes; the twin's time, energy and dose are shown in the caption, not simulated in the clip.
- Carried load (`kg`) and the buddy pair (`pair`) are recorded in `route.json` but not drawn: one walker, no second suit, no load. The rover (`rv`) is drawn only when the safe-haven setting puts it on the route.
- Outside the ground-type map (one block of the ROI, 252 x 325 cells) the three ground types are weighted equally; outside the 1 m window of the film the ground has no Navcam detail.
- Boulders outside the window and scans not fully inside the window are left out.
- The route line is lifted 0.12 m above the ground; a 1 m DTM under a 4 m cell path can put it slightly off the steepest-descent line the planner meant.
- Preview quality (16 spp) is noisy in shadows. Time-lapse legs slide on the ground.
- Scans: after the clean-up most of each Navcam scan is removed (see above); the walk-level shots show the HiRISE ground with a few scan flakes, not a continuous Navcam surface.
- The establishing aerial starts as a high, wide crane: the route line is a few pixels wide at the first frames and only reads in the second half of the crane.
- The time-lapse cap (`--max-speedup`, default 400) lengthens the clip rather than leaving the route unfinished: a 3.2 km route at the default cap takes 8.75 s of time-lapse + the real-speed tail. Pass a higher cap for a shorter clip.

## Checks and timings (this machine, RTX laptop GPU, Cycles 16 spp OptiX denoise, 960x540)
- `f1_prep_data.py` without route variables writes byte-identical files to the previous version (7 of 7 compared); the default `f1_blender_scene.py` build has identical objects, vertex hashes, keyframes, markers and NLA strips (67 objects).
- Campaign route (215 cells, real speed, `--seconds 12 --overview 3 --step 3`, 120 frames): 1.9 s/frame.
- Three-destination "water" route (632 cells, 3.16 km, time-lapse with real-speed tail, `--max-speedup 900`): 2.9 s/frame; the whole-route window makes the scene heavier.
- Scene build 5-15 s including scan clean-up; the clean-up itself is a few seconds per scan.
