# Baked ground lighting for the twin's walk view

Cycles bakes of sun visibility and sky + bounce light on the twin's 1 m corridor, for five local times on sol 4600, plus a sky environment per time and Cycles reference frames. The assets are in `demo/twin/bake/`; `bake.json` there is the manifest. The browser integration is not part of this work.

## Method
- **Terrain.** `tools/bake_ground.py` rebuilds the corridor from `walk.json` and `walk_z.json` cell for cell: vertex (i, j) sits at the twin's `c2w(i, j)`, height is `walk_z` minus the twin's `zMean` (from `data.json`), padded by one cell. Blender axes from twin world: X = x, Y = -z, Z = y. The 4 m grid of `data.json` is added around it (lowered 0.6 m and cut under the corridor, as the film does) with a flat far plane, so distant relief casts shadows and bounces light.
- **Boulders.** The 112 boulders of `rocks.json`, as in `twin.html`: same position, d_m and h_m scaling, spin, noise and 0.25 h offset (icosphere subdivision 3 instead of 4). Pebbles (30 k, illustrative) and the Navcam 3D scans are not in the bake.
- **Sun and sky.** The film's model (`tools/f1_blender_scene.py`): sun strength 6.5 exp(-tau m), sky strength 0.9 * 0.65 (1 - exp(-tau m)) sin(el) / (0.221/0.9), tau880 from `tau_climatology.json` at the slot's Ls, sun disc 0.5332 / rAU deg, same gradient sky with blue aureole. No haze volume in the bakes. Sun azimuth and elevation are the page's own `sunDir(lmst, 4600)`, read by `tools/bake_poses.py` (headless Chrome) into `runs/bake/page_facts.json`.
- **Bakes per time.** (a) `SHADOW` bake with only the sun lamp: fraction of the sun disc visible, no cosine. (b) `DIFFUSE` bake without colour, sun off: sky light with 3 diffuse bounces; plus sun off-sky, `INDIRECT` only: the bounces of the sun light. (a) 512 spp, (b) 512 spp each. Ground albedo for bounces is a flat (0.28, 0.17, 0.10), rock (0.20, 0.135, 0.095), far plane (0.20, 0.10, 0.05).
- **Texel grid.** 2 x 2 texels per corridor cell = 0.506 m, 2016 x 2604, a single texture (under the WebGL 4096 limit, no tiling needed). The texture rectangle is the cell-edge rectangle (same as `aoRect`); `bake.json` gives `rect_world`, u = (x - rect.x) / rect.w, v = (z - rect.z) / rect.h with `flipY = false` (row 0 is the north edge).
- **Packing.** `tools/bake_pack.py` turns the raw float16 arrays in `runs/bake/raw/` into the files below and writes `bake.json`.

## Files and sizes (total 2.6 MB of the 40 MB allowed)
| file | content | size |
|---|---|---|
| `shadow_A.png` | RGBA, R/G/B/A = 08:00, 10:00, 12:00, 14:00; visibility = value/255 | 0.07 MB |
| `shadow_B.png` | R = 16:00 (G, B, A empty) | 0.05 MB |
| `irr_HHMM.jpg` x5 | RGB JPEG (q92, 4:4:4), L = xmax (value/255)^2, xmax per slot in `bake.json` | 0.25 to 0.30 MB each |
| `sky_HHMM.json` x5 | 512 x 256 float16 RGB equirectangular, deflate + base64 (the `walk_ao.json` loader pattern), `{w, h, encoding, data}` | 0.22 to 0.24 MB each |
| `bake.json` | extent, texel size, times, sun az/el, tau, sun strength, encodings, poses, provenance, timings | 0.01 MB |

Previews: `docs/figures/bake_preview_HHMM.png` (shadow | irradiance), `docs/figures/bake_sky_HHMM.png` (tone mapped sky).

## Using the bake
Units: L is the radiance leaving a white diffuse surface in Blender film units (checked: a sun-only direct bake equals S cos / pi to 0.3183). Surface colour = albedo * (S / pi * max(n.l, 0) * shadow + irr), with S = `sun_strength_blender` of the slot (3.59 at 10:00, 1.68 at 16:00). Between slots interpolate shadow and irr in time. Sun az is clockwise from north; the twin vector is (cos el sin az, sin el, -cos el cos az).

Sky: column u gives azimuth (u - 0.5) * 360 deg from north, positive east (image centre = north); row v from the top gives elevation 90 - 180 v. The sun disc is not in the image (the directional light provides it). Rendered from 1.7 m above the middle pose with sun and ground included.

Shadow PNGs are RGBA with data in alpha for time slot 4 of A: browsers may premultiply alpha when decoding an image element. Upload with `premultiplyAlpha = false` (three.js default for non-premultiplied textures) and check one texel; if a browser misbehaves, decode with `createImageBitmap(..., {premultiplyAlpha: 'none'})`.

## Reference renders
`docs/figures/bake_ref_<HHMM>_<pose>.png` for 10:00 and 16:00, poses `a_start`, `b_mid`, `c_late` at 10 %, 50 % and 85 % of the campaign route (poses in `bake.json`: world position, yaw = atan2(dx, -dz) of the route 10 m ahead, pitch -0.1 rad, eye 1.7 m, vertical fov 60, 16:9). `tools/bake_ref.py` renders the film scene (`film/marswalk_scene_v3.blend`: Navcam ground textures, boulders, pebbles, haze) at 960 x 540, 48 spp, OptiX denoise, with the suit, route markers, rover and scans hidden. The film uses the same corridor window, so a twin cell is the same film cell (cell pitch 1.0117 m in both).

## Timings (RTX 5050 laptop, OptiX)
Per slot: shadow 51 s, sky irradiance 41 s, sun bounce 20 s, environment 1 s, mesh setup about 15 s: 112 to 116 s of bake, 115 to 145 s per process including start and cooling wait. All five slots were baked (about 10 minutes of GPU in total, one process per slot so the GPU lock was released in between; one slot waited about 4 min for another job's lock). Reference renders: 4 to 5 s per frame, 4.5 min for six with the 320 MB scene load. The GPU peaked at 60 C.

## Limits
- The shadow term is almost all boulders: mean visibility is 0.998 to 0.9995 on the 1 m terrain (the 1 m DTM has little self shadowing at these sun heights). Pebbles, the walker and scans cast no baked shadow; keep the page's shadow map for those.
- The `SHADOW` pass is a ratio and is unstable on grazing facets (3 % of texels exceed 1 at 16:00, a few reach 200); the packer clamps to [0, 1], which is correct there (not shadowed).
- Irradiance is smooth: it sees sky gradient, rocks and the 4 m relief; it does not see the haze, pebbles or scans. Ground albedo is a flat colour, not the HiRISE drape, so bounce colour near bright/dark patches is approximate.
- Heights: the film and the twin share the HiRISE corridor DTM; the 4 m context and far plane are a plain approximation of the horizon (no Mount Sharp beyond the data grid).
- The sky environment is rendered from one point (middle pose); using it along the whole 1 km route ignores local horizons.
- Times 08:00, 10:00, ..., 16:00 only; the sun az/el in `bake.json` are the page's values for sol 4600 (aerosol and Ls from the climatology, not a 2025 measurement).

## Rebuild
```
python tools/bake_poses.py                                  # page facts (needs playwright + Chrome)
for t in 8 10 12 14 16; do python tools/run_blender.py bake-ground tools/bake_ground.py --times $t --spp-shadow 512 --spp-irr 512 --spp-sky 256; done
python tools/bake_pack.py
python tools/run_blender.py bake-ref tools/bake_ref.py --times 10,16 --spp 48
```
`--test` bakes a 160 x 160 cell crop in seconds; `--calib` adds the sun-unit check.
