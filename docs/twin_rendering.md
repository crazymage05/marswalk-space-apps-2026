# Twin rendering and the per-cell inspector

Files: `demo/twin/twin.html` (walk mode, inspector), `demo/export_world_cells.py` (builds `demo/twin/world_cells.json`).

## What changed in walk mode

Before, `buildWalk` made four tile meshes of the whole 1008 x 1302 m corridor at 1 m (about 1.3 M vertices, 2.6 M triangles), one instanced mesh of about 30 k pebbles, a single mesh for the 4 m far field, and a 4096 shadow map over +-320 m that redrew every frame. Each of the six Navcam scans also lowered the terrain by looping over all 1.3 M vertices and recomputing normals, which was most of the load time.

Now:

- **Chunks.** The corridor is cut into 352 chunks of about 64 m. A chunk never straddles two 25 cm image tiles, so each chunk keeps one of the four tile textures and the same `groundShader`. Every chunk has a coarse mesh (4 m, built at load, about 500 triangles) and a fine mesh (1 m, about 8 k triangles, built on demand).
- **Fine within reach.** A chunk is fine when it is within 300 m of the walker and either within 60 m of the planned route or within 100 m of the walker. Hysteresis keeps it fine until 340 m (80 m from the route, 120 m from the walker). Fine geometry is built at most six chunks per frame after the first frame, and disposed when the chunk is more than 500 m behind.
- **Cracks.** Each mesh has a skirt (1.5 m fine, 3 m coarse). Normals come from central differences of the global height grid, so chunk borders match.
- **Rover scans.** The 1.2 m dip under each Navcam scan is applied while a chunk is built, using the positions in `meshes_index.json`. Nothing is rebuilt when the scan GLBs arrive. A scan mesh (about 100 k triangles each) is drawn within 250 m and casts shadows within 80 m.
- **Props per chunk.** Boulders (112) and pebbles (30 k) are assigned to chunks at load. Their instanced meshes exist only for fine chunks: boulders within the frustum plus 25 m (for their shadows), pebbles within 150 m. r128's `InstancedMesh` has no instance bounding sphere (checked: `computeBoundingSphere` is undefined in this build), so these meshes set `frustumCulled = false` and the chunk code culls them. Pebbles are no longer placed inside a scan patch, where they used to float above the dipped terrain. Pebble positions differ from the old random draw but follow the same density by ground type.
- **Far field.** 8 m chunks of the 4 m area, frustum-culled; chunks wholly under the corridor are not built.
- **Shadows.** The map is 2048 over +-160 m, which keeps the 15.6 cm texel of the old 4096 over +-320 m. It is redrawn only when the walker has moved 2.5 m (0.4 m in the follow view, where the suit's shadow is visible), the sun direction changed, a chunk was built, the view changed or a scan or rover was placed.

Fixed in the same pass: `sunDir` now uses the equation of time and an orbit-model Ls (ported from `phase4/world.py`). For sol 4600 the geometric sunrise and sunset are 05:47 and 17:31 (rems_daily: 05:47, 17:30); the old formula gave 06:08 and 17:52. Sols 4500, 4700 and 4799 agree with rems_daily within 1 min (old formula 4 to 36 min late). The sun at 08:45 on sol 4600 is 40 deg instead of 35 deg.

## Measured (Intel UHD, ANGLE/D3D11, Chromium headless, 1280 x 720, route from the campaign demo)

`rAF` in headless is not tied to the GPU, so frame times were taken with a `readPixels` sync after each frame. Pose: 400 m along the route, first person.

| | before | after |
|---|---|---|
| walk built (click to playable) | 1.0 to 1.2 s | 0.96 s |
| until all 6 scans placed | 3.7 to 4.3 s | 2.4 s |
| JS heap after load | 184 to 206 MB | 115 MB |
| walking 5 s at 15x: frames/s (synced) | 12.1 | 55.5 |
| walking: median / p95 / worst frame | 38 / 73 / 2615 ms | 13 / 16 / 369 ms |
| still, first person, ms per frame | 34.6 | 12.0 (14.3 with a shadow redraw) |
| triangles, main + shadow pass | 7.82 M | 0.76 M |
| triangles, main pass | 4.49 M | 0.43 M |
| draw calls, main + shadow | 82 | 265 |
| draw calls, main | 50 | 190 |
| follow view, ms per frame | 38.7 | 13.7 |

Draw calls went up (one per visible chunk) while triangles dropped by a factor of 10; on this GPU the triangle and pixel cost dominated. The worst frame after is the first draw of a scan texture. Drawing 42 fine chunks of 8 k triangles is still 340 k triangles; a 2 m middle level would cut that further if a weaker GPU needs it.

## Inspector

`world_cells.json` holds 12 layers on the 585 x 732 grid: steepest slope, roughness, loose-ground index, rock fraction, ground type, hydration, sulfate, sky view, shielding factor, DTM uncertainty, distance to Curiosity's track, valid fraction. Each is quantised (`value = offset + code * scale`, code 255 or 65535 means no data), zlib-compressed and base64-coded; the page unpacks it with `DecompressionStream`. File size is 3.7 MB. Class labels come from `world_static_4m.json` (measured, derived); the shielding factor and the dose are labelled modelled.

Overview: hovering or clicking the terrain shows a card with every layer, its units and class, the elevation, the dose rate for the selected sol (RAD rate times shielding factor, modelled) and whether the cell is blocked at the current slope limit (twin slope grid, the same one the planner uses; a cell with no slope is reported as blocked). Walk mode: the "Ground here" button shows the same card for the cell under the walker. Ground temperature is not in the card: the model needs per-cell horizons (25 MB), which the page does not load.

## Rebuild

```
python demo/export_world_cells.py
```

Needs `data/processed/roi/world/world_static_4m.npz` and `.json`, `horizon_32_4m.npz`, `phase4/world.py` and `demo/twin/data.json`. It checks the grid size against the twin and prints the slope difference. Serve `demo/twin` over HTTP (the page fetches JSON).

## Checked

One headless pass: overview, three inspector cells, sol change, first-person walk with the card, follow view, Curiosity-track walk, science walk. No console errors, page errors, failed requests or HTTP errors.
