# AI4Mars ground-type model on Curiosity's own frames (tasks I1, I2, I3)

Label for everything below: **derived (rover camera, ML model)**. The model output is a prediction, not a measurement of the ground.

## Method

**Data.** AI4Mars (Swan et al., CVPR Workshops 2021), Zenodo record 15995036, CC-BY-4.0. Classes: 0 soil, 1 bedrock, 2 sand, 3 big rock, 255 unlabelled. Train labels are crowd-sourced (at least 3 labellers, 2/3 agreement per pixel); test labels are expert labels with 100% agreement, in three variants (`min1`, `min2`, `min3` = how many of the 3 experts had to agree for a pixel to be kept; `min3` is the sparsest). Distances beyond 30 m and the rover itself are already masked as 255 in the labels.

**Download.** `ai4mars-labels-unmerged.zip` (1.6 GB) was downloaded in full and its md5 matches the record. `ai4mars-dataset-merged-0.6.zip` (16.2 GB) was **not** downloaded in full: transfer speed was 0.4 to 1.5 MB/s, so I read the zip's central directory from the last 40 MB and fetched only the needed members by HTTP range request (MSL Navcam labels, 4,000 random train EDR frames, all 322 test frames), checking every member's CRC32. The whole-file md5 was therefore not verified. The unmerged labels zip was not used for training. Provenance files: `data/raw/ai4mars/provenance.json`, `data/raw/ai4mars_extracted/provenance.json`.

**Training** (`tools/ai4mars_train.py`). SegFormer-B0 initialised from `nvidia/segformer-b0-finetuned-ade-512-512` (new 4-class head), 4,000 random MSL Navcam train frames with at least 20% labelled pixels, 1024 px images resized to 512 px, 10 epochs, batch 16, AdamW (1e-4 encoder, 1e-3 decoder, polynomial decay), fp16, square-root inverse-frequency class weights, horizontal flip and brightness/contrast jitter. 21.3 GPU minutes in 10 chunks, each under `gpu_lock("ai4mars")` with `wait_cool()` (GPU stayed at or below 57 C). transformers 5.12.1, torch 2.11.0+cu128. Model: `models/ai4mars_segformer_b0/`.

## IoU on the official test split

MSL Navcam expert test set, 322 images (the 323rd entry in the zip is a note file), unlabelled pixels ignored. Evaluation ran on CPU in fp32; logits were upsampled to the 1024 px label size. Train and test frames are disjoint.

| Test variant | labelled px | soil | bedrock | sand | big rock | mIoU | pixel acc. |
|---|---|---|---|---|---|---|---|
| min3-100agree (headline) | 117.0 M | 0.978 | 0.945 | 0.961 | 0.360 | **0.811** | 0.982 |
| min2-100agree | 163.4 M | 0.958 | 0.886 | 0.928 | 0.102 | 0.718 | 0.961 |
| min1-100agree | 194.3 M | 0.915 | 0.814 | 0.858 | 0.103 | 0.673 | 0.926 |

Soil, bedrock and sand are strong. Big rock is weak: on min1, 1.4 M bedrock pixels are predicted as big rock, and the class is rare. The `min3` labels keep only pixels all three experts agree on, which are the easy ones, so the 0.81 is an optimistic figure; `min1` is the harder reference. Train and test frames come from the same rover and camera, and I did not check how far apart their sols are, so the test may not measure transfer to new terrain. Confusion matrices are in `metrics.json`.

## I2: the 2,130 campaign frames

`data/processed/roi/ai4mars_campaign_frames.json` holds, per frame, class shares for the lower half (near field) and the full frame. 128 px argmax maps for QA are in `ai4mars_pred_128.npz`. Cameras: 1,697 NAV_LEFT_B, 340 MAST_RIGHT, 93 MAST_LEFT.

Mean lower-half shares (soil / bedrock / sand / big rock): NAV_LEFT_B 0.26 / 0.64 / 0.05 / 0.04; MAST_LEFT 0.37 / 0.15 / 0.48 / 0.00; MAST_RIGHT 0.69 / 0.01 / 0.30 / 0.00.

Overlays of 30 random frames (seed 7; left raw, right overlay with soil brown, bedrock grey, sand yellow, big rock red; white line = half height): `figures/ai4mars_overlay_sheet_1.png`, `_2.png`, `_3.png` (ids in `ai4mars_overlay_ids.json`). I looked at all 30. Navcam terrain predictions look plausible: bedrock slabs come out as bedrock, loose patches as soil, track marks as soil. Failure cases:

- **Sky and horizon** are labelled sand (yellow band above the horizon) in several frames.
- **Rover hardware** (arm, wheels, deck, shadows of the mast) is labelled big rock, sand or bedrock. There is no rover mask for these frames.
- **Mastcam frames are unusable.** Many of the 30 samples are black, nearly black, or vignetted with a bright blob; the model calls them soil or sand (0.3 to 0.8 sand). That is why MAST_RIGHT and MAST_LEFT show 0.30 and 0.48 mean sand. AI4Mars has no Mastcam test set either.
- **Dark and low-sun Navcam frames** sometimes yield big-rock patches on flat ground.
- Big rock is the least trustworthy class.

## I3: ground evidence on the 4 m grid

Method (`tools/ai4mars_ground_evidence.py`): only NAV_LEFT_B frames (1,697) are used; Mastcam frames are excluded for the reasons above. Frames are grouped by registered position (76 distinct positions), averaged, and put in nav cell `row*585 + col` with `col = floor(col_reg/4)`, `row = floor(row_reg/4)`. Result: 68 occupied cells in `data/processed/roi/world/rover_ground_evidence_4m.json`, each with `sand_share_near`, the other class shares, `n_images` and sols. The layer is sparse (68 of 428,220 cells) and the cell is the rover's position, not the ground imaged up to ~30 m ahead.

Alignment: material map origin is col 336/4 = 84, row 577/4 = 144.25 on the 4 m grid, so the 0.25-cell row offset is handled by computing the material cell as `((row_reg-577)//4, (col_reg-336)//4)`. All 76 positions fall inside the 252 x 325 material map. I recomputed the per-cell means separately with pandas and they match the file.

Agreement with `demo/twin/material_4m.json` at the rover's own cell (counts of positions; AI class = dominant class of the lower half):

| material map \ AI | soil | bedrock | sand | big rock |
|---|---|---|---|---|
| bedrock (7) | 2 | 5 | 0 | 0 |
| sand (8) | 3 | 5 | 0 | 0 |
| pebbly (61) | 14 | 47 | 0 | 0 |

Same table in images: bedrock 42 / 106 / 0 / 0, sand 64 / 108 / 0 / 0, pebbly 318 / 1,059 / 0 / 0. Binary sand test (AI sand share at least 0.2 against material sand): both agree "not sand" at 66 positions, they disagree at 10, and no position has both flagging sand. Mean AI sand share is 0.040 on material bedrock, 0.044 on material sand and 0.056 on material pebbly; the Pearson correlation between the material sand fraction in a 3 x 3 neighbourhood and the AI sand share is -0.13. Across the 68 cells the sand share has median 0.04 and maximum 0.25.

So the two layers do not agree on sand: the model finds almost no sand along the drive, and the material map's 8 sand positions are not distinguished from the rest. Two caveats keep this from being read as an error in one of them. The material map is a rule on slope, roughness, texture and brightness from orbit-derived products, with no soil/bedrock distinction in the AI4Mars sense; its "pebbly" class has no direct AI4Mars equivalent (most pebbly positions are called bedrock or soil by the model). And the route crosses boxwork bedrock, where little sand is expected. The layer is therefore usable as a "no sand seen" note on the route, not as a map of sand elsewhere.

## Limitations

- Domain shift: training frames come from the AI4Mars release (Navcam EDR products from earlier in the mission; I did not tabulate their sols); campaign frames are from 2025 (sols about 4,500 to 4,800), at lower solar elevation and with a different terrain (boxwork). No labelled 2025 frames exist, so no accuracy number applies to them. The overlays are the only check.
- No rover or range mask on campaign frames; the lower half contains hardware and sometimes sky.
- `min3` mIoU is optimistic; big rock is weak.
- 4,000 training frames and 10 epochs were chosen for the time budget; larger subsets or longer training were not tried.
- Whole-zip md5 of the merged dataset not verified (see Download).
- Positions come from the registration table (`localization` approximate for many frames).
- One model, one seed.

## Files

`models/ai4mars_segformer_b0/` (model.safetensors, config.json, metrics.json, train_log.json; `ckpt.pt` is the optimiser checkpoint and can be dropped), `data/processed/roi/ai4mars_campaign_frames.json`, `data/processed/roi/ai4mars_pred_128.npz`, `data/processed/roi/world/rover_ground_evidence_4m.json`, `docs/figures/ai4mars_overlay_sheet_{1,2,3}.png`, scripts `tools/ai4mars_{fetch,train,infer,ground_evidence}.py`.
