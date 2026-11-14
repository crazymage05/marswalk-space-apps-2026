# W5a: rigged Mark III suit with a Mars walk cycle and idle loop

Output: `demo/twin/models/markIII_suit_walk.glb` (+ `.glb.json` from `demo/pack_models.py`). One skinned mesh (14 material
primitives, 102k vertices), one armature `Armature` with 17 bones, two clips: `walk` (1.667 s, loops) and `idle` (4.0 s, loops).
Rebuild: `python tools/run_blender.py w5a tools/w5a_rig.py` (CPU only; the launcher holds the GPU lock anyway).
Blender 4.5.16 LTS at `D:\tools\blender\blender.exe` (SHA256 checked against the published file), path in `tools/blender_path.txt`.

## Model frame

Feet soles at y = 0 (glTF) , hips centred on the origin, the suit faces -Z in glTF (+Y in Blender, same as the source GLB).
The walk is **in place**: the page moves the model at the walking speed. Bones: `hips spine chest neck head`,
`upper_arm.L/R forearm.L/R hand.L/R`, `upper_leg.L/R lower_leg.L/R foot.L/R` (three.js strips the dots: `upper_legL`, `footL`...).
Clips key every frame (24 fps), linear, last key equals first (frames 0..40 and 0..96), so three.js `LoopRepeat` is seamless.

## Gait numbers

| quantity | value | basis |
|---|---|---|
| g (Mars) | 3.71 m/s^2 | given |
| leg length L | 0.88 m | hip-joint height of this mesh (measured from leg slices) |
| speed v | 0.9 m/s | planner flat speed |
| Froude number v^2/(gL) | 0.248 | derived; walk-run transition at Fr about 0.5, i.e. walking tops out near 1.28 m/s |
| Earth cadence at 0.9 m/s | 0.86 strides/s (about 103 steps/min) | assumed typical slow walk, not measured here |
| Mars / Earth cadence | 0.70 | plan range 0.6-0.7 (sqrt(g_M/g_E) = 0.615; Kram, Domingo, Ferris 1997; Minetti 2001) |
| stride frequency | 0.60 strides/s (cycle 40 frames = 1.667 s) | rounded to a whole number of frames |
| stride length | v / f = 1.50 m (step 0.75 m = 0.85 L) | derived, so planted feet do not slide |
| duty factor | 0.57 (double support 7% twice) | assumed, typical walking |
| stance ankle travel | v x duty x T = 0.855 m | ankle moves back relative to hips at exactly v |
| swing clearance | 0.13 m | assumed (a little higher than Earth) |
| pelvis height | 0.743 to 0.860 m | from leg-reach limit (13 cm bounce, larger than Earth walking: modelled, not measured) |
| arm swing | 15 deg, opposite to the same-side leg; pelvis yaw 4 deg, sway 2.2 cm | assumed |

Legs are solved with analytic two-bone IK each frame (knee pole forward), so every stance ankle is world-fixed by construction;
the pelvis is lowered only as far as needed to keep each stance leg within 0.705 m of hip-to-ankle reach.
Foot stays flat in stance, toe lifts up to 8 deg in late swing. Idle: breathing 4 s loop (chest 1.6 deg, tiny pelvis rise), arms hanging.
All gait values are SIMULATED/modelled choices; the Mars-vs-Earth cadence scaling is the plan's, not a measurement of a suited walk.

## Skinning (W5b, 2026-11-13; replaces the W5a nearest-bone fallback)

Bone-heat automatic weights still fail on this mesh (30 shells, overlapping, non-manifold). The W5a fallback (3 nearest bones,
inverse distance^4, hard top-3 cut) tore the cloth: neighbouring triangles, and different shells at the same place, landed on different
bones. Visible as shredded belt/hip rings, shards at the shoulder and sheared knees. Rebuilt by `tools/w5b/w5b_rig.py`
(`python tools/run_blender.py w5b-rig tools/w5b/w5b_rig.py`; same bones, same gait code, same clips; the old files are kept as
`markIII_suit_walk_v1.glb(.json)`). Instead of bone heat on a separate proxy body plus a Data Transfer, the proxy is implicit: the
weight of every vertex is a smooth function of its rest position only, taken from a capsule field of the bone segments.

1. Weld vertices (0.5 mm), find connected shells (30), and classify each by nearest-bone vote: 4 arm shells (2 sleeves, 2 gloves), 13 leg and
   hip-bearing shells (7 left, 6 right), 13 torso/helmet/ring shells. A limb shell is skinned only to its own limb bones plus the parent bone
   (chest for arms, hips for legs) with a share that falls from 92% to 0 between 3 and 22 cm from the joint. Torso-type shells never
   get arm bones; leg bones only fade in below the waist (ramp z 0.88 to 1.16 m).
2. Inside a shell group: w_k proportional to exp(-(d_k - d_min)/sigma), d_k = distance to bone segment k, sigma 6 cm for limbs and
   7 cm for the torso. Joint blends then widen with the limb radius.
3. Soles and boots stay rigid to the foot bone (full below z = 0.20 m, blending into the shin up to 0.40 m, smoothstep).
4. At most 4 influences, kept continuous by subtracting the 5th-largest weight before normalising.
5. Materials: W5a left metallic/roughness unset, which glTF reads as metallic 1 / roughness 1, so the fabric rendered as dull grey
   metal and went almost black with the sun behind. Now fabric is off-white (linear 0.80/0.78/0.73), metallic 0, roughness 0.75; rings
   and steel metallic 0.30-0.35, roughness 0.45; visor dark (linear 0.015) roughness 0.08, metallic 0.25; boots rubber.
6. PLSS backpack with the numbers of `tools/f2_suitfix.py` (0.60 x 0.28 x 0.82 m body, two steel bands, dark hose strap, bevelled
   and baked), parented to the `chest` bone; four non-skinned meshes, so they follow the chest. File size 5.9 MB glb, 7.9 MB `.glb.json`.

Edge-stretch test (`tools/w5b/measure_stretch.py`, Blender, evaluated armature modifier, every triangle edge over 3 mm at rest,
frames 0 to 40 of `walk`, 143,174 edges; JSON in `docs/verification/w5b_stretch_*.json`):

| metric | v1 (nearest bone) | W5b |
|---|---|---|
| max edge length ratio | 29.5 | 2.21 |
| 99.9th percentile ratio | 10.5 | 1.93 |
| 99th percentile ratio | 3.53 | 1.62 |
| edges stretched beyond 2x | 4,244 | 66 |
| edges stretched beyond 3x | 2,052 | 0 |
| largest absolute elongation | 17.3 cm | 6.2 cm |
| edges lengthened by more than 5 cm | 2,083 | 34 |

(The first W5a numbers on 1 mm edges gave a maximum of 54x; the table skips edges under 3 mm because their ratio is meaningless.)
Largest knee bend of the cycle is 75 degrees (frames 11/12 and 31/32); the four renders are `docs/figures/w5b_knee_*_before_after.png`
(EEVEE, side, back and front 3/4; top row v1, bottom row W5b). Clip lengths, 17 bone names and 170 f-curves per clip are unchanged,
and so is the foot drift (`docs/verification/w5b_blender_verify.json`): 0.35 cm per planted phase, sole 0.31 cm below ground.
Page check: `docs/figures/w5b_web_before_after.png` (twin walk view, sun 8:45 and 16:30, v1 left, W5b right).

## Verification (2026-11-12)

1. Re-import of the exported GLB in a fresh Blender run (`tools/w5a_verify.py`, `docs/verification/w5a_blender_verify.json`):
   1 armature, 17 bones, clips `walk` 0-40 frames = 1.667 s and `idle` 0-96 frames = 4.0 s, 170 f-curves each.
2. Foot drift (ankle bone world position, body translated at 0.9 m/s, 4 samples per frame over two cycles, contact = ankle at ground height):
   maximum **0.35 cm** forward drift per planted phase (about 0.9 s each), 0.03 cm sideways, both feet. Independent second measure
   through the skinned mesh (2,599 left-boot sole vertices after the armature modifier): sole-centroid drift **0.35 cm**, lowest sole point
   0.3 cm below the ground plane. Target was under 5 cm. (Before the foot was kept flat in stance and the boot made rigid, the
   mesh sole drifted 13.9 cm; that is why both are reported.)
3. three.js r128 `GLTFLoader.parse` of the packed `.glb.json` in Playwright Chromium (`tools/w5a_web/run_anim_test.py`,
   `docs/verification/w5a_three_test.json`): clips `idle` 4.0 s and `walk` 1.667 s, 51 tracks each, 14 SkinnedMesh, 17 bones,
   AnimationMixer plays both and the left ankle moves (walk) or stays (idle); 0 console, page, request and HTTP errors.
4. Looked at: `docs/figures/w5a_walk_00..07.png` (side view, Workbench, body moving over 0.25 m floor ticks, montage `w5a_walk_montage.png`)
   and `w5a_idle_00..03.png`. Feet land flat and stay put relative to the floor ticks; swing leg clears the ground.

## Limitations

- Mesh was posed arms-forward and asymmetric (right arm bent out). The rig lowers the arms to hang; sleeves are separate shells, so a
  seam opens at the shoulder (arm and torso shells that touched in the rest pose separate by up to about 30 cm, left and right
  trouser shells also separate at the crotch as the legs swing). No tearing within a shell, but the seams are not closed.
- Rigid suit rings do not bend like real hard-suit joints; knees/hips fold by skin blending only. No hand/finger, toe or head-look bones.
- Heel-toe roll is not modelled (flat foot in stance); the ankle point is the planted point.
- Pelvis bounce (13 cm) is a consequence of the long Mars stride at fixed leg length; no measured suited-walk data backs it.
- Gait speed scaling: to walk faster or slower the page should scale clip playback rate by speed/0.9 (cadence rises with speed, stride
  length stays v/f_clip); feet stay planted only at exactly 0.9 m/s of body translation times the playback rate.
- Textures come through unchanged (the source GLB's materials); `pack_models.py` leaves them as they are (already under 1024 px).
- Stray artefact: the first inspection render wrote 3 PNG files to `C:\docs\figures\_insp\` (relative path); harmless, not removed.
