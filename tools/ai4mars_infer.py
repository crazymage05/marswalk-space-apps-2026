"""
I2: run the fine-tuned SegFormer-B0 on the 2,130 campaign frames; class shares (lower half, full frame) per image.
Output: data/processed/roi/ai4mars_campaign_frames.json (+ ai4mars_pred_128.npz, 128 px argmax maps for QA)
        docs/figures/ai4mars_overlay_sheet_*.png (30 random frames)
Label: derived (rover camera, ML model). Not measured ground truth.
"""
import json, os, sys, time
import numpy as np, pandas as pd
from PIL import Image
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
from tools.ai4mars_train import OUT, CLASSES, SIZE, to_t, DEV, lock
from tools.gpu_lock import gpu_lock, wait_cool, gpu_temp_c

CSV = os.path.join(HERE, "data/processed/roi/tables/images_index_registered.csv")
JSON_OUT = os.path.join(HERE, "data/processed/roi/ai4mars_campaign_frames.json")
NPZ = os.path.join(HERE, "data/processed/roi/ai4mars_pred_128.npz")
COL = np.array([[176, 140, 90], [90, 90, 100], [240, 210, 60], [220, 40, 40]], np.uint8)  # soil, bedrock, sand, big rock


def run():
    import torch, torch.nn.functional as F
    from transformers import SegformerForSemanticSegmentation
    df = pd.read_csv(CSV)
    model = SegformerForSemanticSegmentation.from_pretrained(OUT).to(DEV).eval()
    recs, maps = [], []
    with lock("ai4mars"):
        for b in range(0, len(df), 32):
            sub = df.iloc[b:b + 32]
            ims = [np.asarray(Image.open(os.path.join(HERE, p)).convert("RGB").resize((SIZE, SIZE), Image.BILINEAR)) for p in sub.path]
            with torch.no_grad(), torch.autocast("cuda", dtype=torch.float16, enabled=DEV == "cuda"):
                lg = model(pixel_values=to_t(np.stack(ims)).to(DEV)).logits
            lg = F.interpolate(lg.float(), size=(SIZE, SIZE), mode="bilinear", align_corners=False)
            pr = lg.argmax(1).cpu().numpy().astype(np.uint8)
            for (_, r), p in zip(sub.iterrows(), pr):
                low = p[SIZE // 2:]
                recs.append({"imageid": r.imageid, "path": r.path, "sol": int(r["sol"]), "camera": r.camera,
                             "col_reg": float(r.col_reg), "row_reg": float(r.row_reg),
                             "lower_half": {c: float((low == i).mean()) for i, c in enumerate(CLASSES)},
                             "full_frame": {c: float((p == i).mean()) for i, c in enumerate(CLASSES)}})
                maps.append(p[::4, ::4])
            if DEV == "cuda": wait_cool()
            if b % 320 == 0: print(b, gpu_temp_c(), flush=True)
    json.dump({"label": "derived (rover camera, ML model): SegFormer-B0 fine-tuned on AI4Mars; lower half of frame = near field; "
                        "no rover/range mask applied, so rover hardware and sky/horizon pixels are classified too",
               "classes": CLASSES, "n_images": len(recs), "frames": recs}, open(JSON_OUT, "w"))
    np.savez_compressed(NPZ, ids=np.array([r["imageid"] for r in recs]), maps=np.stack(maps))
    print("saved", len(recs))


def overlays():
    d = json.load(open(JSON_OUT)); z = np.load(NPZ)
    rng = np.random.default_rng(7)
    idx = rng.choice(len(d["frames"]), 30, replace=False)
    import torch, torch.nn.functional as F
    from transformers import SegformerForSemanticSegmentation
    model = SegformerForSemanticSegmentation.from_pretrained(OUT).to(DEV).eval()
    os.makedirs(os.path.join(HERE, "docs/figures"), exist_ok=True)
    tiles = []
    with lock("ai4mars"):
        for i in idx:
            f = d["frames"][i]
            im = Image.open(os.path.join(HERE, f["path"])).convert("RGB").resize((SIZE, SIZE), Image.BILINEAR)
            with torch.no_grad(), torch.autocast("cuda", dtype=torch.float16, enabled=DEV == "cuda"):
                lg = model(pixel_values=to_t(np.asarray(im)[None]).to(DEV)).logits
            p = F.interpolate(lg.float(), size=(SIZE, SIZE), mode="bilinear").argmax(1)[0].cpu().numpy()
            ov = (0.55 * np.asarray(im) + 0.45 * COL[p]).astype(np.uint8)
            t = np.concatenate([np.asarray(im), ov], 1)
            t[SIZE // 2, :, :] = [255, 255, 255]
            tiles.append((f, Image.fromarray(t).resize((384, 192))))
    from PIL import ImageDraw
    for s in range(0, 30, 10):
        sheet = Image.new("RGB", (384 * 2, 210 * 5), (20, 20, 20)); dr = ImageDraw.Draw(sheet)
        for k, (f, t) in enumerate(tiles[s:s + 10]):
            x, y = (k % 2) * 384, (k // 2) * 210
            sheet.paste(t, (x, y + 18))
            lh = f["lower_half"]
            dr.text((x + 2, y + 2), f'{f["camera"]} s{f["sol"]} {f["imageid"][-14:]} low: ' + " ".join(f"{c[:4]}{v:.2f}" for c, v in lh.items()), fill=(255, 255, 255))
        sheet.save(os.path.join(HERE, f"docs/figures/ai4mars_overlay_sheet_{s // 10 + 1}.png"))
    json.dump([d["frames"][i]["imageid"] for i in idx], open(os.path.join(HERE, "docs/figures/ai4mars_overlay_ids.json"), "w"))


if __name__ == "__main__":
    {"run": run, "overlays": overlays}[sys.argv[1]]()
