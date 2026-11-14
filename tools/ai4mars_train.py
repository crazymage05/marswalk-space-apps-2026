"""
AI4Mars (MSL Navcam) -> SegFormer-B0 fine-tune. Classes: 0 soil, 1 bedrock, 2 sand, 3 big rock, 255 = ignore.

  python tools/ai4mars_train.py prep      # decode a train subset + test split to 512 px npy caches (CPU)
  python tools/ai4mars_train.py train     # GPU, inside gpu_lock("ai4mars"), wait_cool() between epochs, resumable
  python tools/ai4mars_train.py eval      # GPU, own lock; per-class IoU on the official test split -> metrics.json

Input layout (extracted from ai4mars-dataset-merged-0.6.zip): ROOT/msl/ncam/images/edr/*.JPG,
ROOT/msl/ncam/labels/train/*.png, ROOT/msl/ncam/labels/test/masked-gold-min{1,2,3}-100agree/*_merged.png.
"""
import glob, json, os, random, sys, time
import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
ROOT = os.path.join(HERE, "data", "raw", "ai4mars_extracted", "ai4mars-dataset-merged-0.6", "msl", "ncam")
CACHE = os.path.join(HERE, "data", "processed", "ai4mars_cache")
OUT = os.path.join(HERE, "models", "ai4mars_segformer_b0")
CLASSES = ["soil", "bedrock", "sand", "big rock"]
SIZE = 512
DEV = os.environ.get("DEV", "cuda")
import contextlib


def lock(name):
    if DEV == "cuda":
        from tools.gpu_lock import gpu_lock
        return gpu_lock(name)
    return contextlib.nullcontext()
N_TRAIN = int(os.environ.get("N_TRAIN", 4000))
TEST_SET = os.environ.get("TEST_SET", "masked-gold-min3-100agree")
MEAN = np.array([0.485, 0.456, 0.406], np.float32); STD = np.array([0.229, 0.224, 0.225], np.float32)


def find_image(stem):
    for sub in ("edr", ""):
        for ext in (".JPG", ".jpg", ".png"):
            p = os.path.join(ROOT, "images", sub, stem + ext)
            if os.path.exists(p): return p
    return None


def pairs(label_dir):
    out = []
    for lp in sorted(glob.glob(os.path.join(label_dir, "*.png"))):
        stem = os.path.basename(lp)[:-4]
        if stem.endswith("_merged"): stem = stem[:-7]
        ip = find_image(stem)
        if ip: out.append((ip, lp))
    return out


def load_pair(ip, lp, size=SIZE):
    im = Image.open(ip).convert("RGB").resize((size, size), Image.BILINEAR)
    lb = Image.open(lp); lb = lb.resize((size, size), Image.NEAREST)
    return np.asarray(im, np.uint8), np.asarray(lb, np.uint8)


def prep():
    os.makedirs(CACHE, exist_ok=True)
    random.seed(0)
    tr = pairs(os.path.join(ROOT, "labels", "train"))
    print("train pairs available:", len(tr))
    random.shuffle(tr); tr = tr[:N_TRAIN]
    for name, lst in (("train", tr),
                      ("test", pairs(os.path.join(ROOT, "labels", "test", TEST_SET)))):
        X = np.zeros((len(lst), SIZE, SIZE, 3), np.uint8); Y = np.zeros((len(lst), SIZE, SIZE), np.uint8)
        for i, (ip, lp) in enumerate(lst):
            X[i], Y[i] = load_pair(ip, lp)
        np.save(os.path.join(CACHE, f"{name}_x.npy"), X); np.save(os.path.join(CACHE, f"{name}_y.npy"), Y)
        json.dump([os.path.basename(a) for a, _ in lst], open(os.path.join(CACHE, f"{name}_files.json"), "w"))
        print(name, X.shape, "label values", np.unique(Y), flush=True)


def to_t(x):
    import torch
    x = (x.astype(np.float32) / 255 - MEAN) / STD
    return torch.from_numpy(x.transpose(0, 3, 1, 2).copy())


def make_model():
    from transformers import SegformerForSemanticSegmentation
    return SegformerForSemanticSegmentation.from_pretrained(
        "nvidia/segformer-b0-finetuned-ade-512-512", num_labels=4, ignore_mismatched_sizes=True,
        id2label={i: c for i, c in enumerate(CLASSES)}, label2id={c: i for i, c in enumerate(CLASSES)})


def train(epochs=int(os.environ.get("EPOCHS", 10)), bs=16):
    import torch, torch.nn.functional as F
    from tools.gpu_lock import gpu_lock, wait_cool
    X = np.load(os.path.join(CACHE, "train_x.npy"), mmap_mode="r"); Y = np.load(os.path.join(CACHE, "train_y.npy"))
    n = len(X)
    cnt = np.bincount(Y[Y != 255].ravel(), minlength=4).astype(np.float64)
    w = (cnt.sum() / cnt) ** 0.5; w = w / w.mean()
    print("train px share", (cnt / cnt.sum()).round(4), "weights", w.round(3))
    os.makedirs(OUT, exist_ok=True)
    ck = os.path.join(OUT, "ckpt.pt")
    dev = "cuda"
    model = make_model().to(dev)
    dec = [p for k, p in model.named_parameters() if k.startswith("decode_head")]
    enc = [p for k, p in model.named_parameters() if not k.startswith("decode_head")]
    opt = torch.optim.AdamW([{"params": enc, "lr": 1e-4}, {"params": dec, "lr": 1e-3}], weight_decay=0.01)
    steps_total = epochs * (n // bs)
    sched = torch.optim.lr_scheduler.LambdaLR(opt, lambda s: max(0.0, 1 - s / steps_total) ** 0.9)
    scaler = torch.amp.GradScaler()
    ep0, log = 0, []
    if os.path.exists(ck):
        s = torch.load(ck, map_location=dev)
        model.load_state_dict(s["model"]); opt.load_state_dict(s["opt"]); sched.load_state_dict(s["sched"]); ep0 = s["epoch"]; log = s["log"]
        print("resumed at epoch", ep0)
    cw = torch.tensor(w, dtype=torch.float32, device=dev)
    rng = np.random.default_rng(ep0)
    t_gpu = sum(l["sec"] for l in log)
    for ep in range(ep0, epochs):
        with gpu_lock("ai4mars"):
            wait_cool()
            model.train(); t0 = time.time(); perm = rng.permutation(n); tot = 0; k = 0
            for i in range(0, n - bs + 1, bs):
                idx = np.sort(perm[i:i + bs])
                xb = np.array(X[idx]); yb = Y[idx].copy()
                flip = rng.random(bs) < 0.5
                xb[flip] = xb[flip][:, :, ::-1]; yb[flip] = yb[flip][:, :, ::-1]
                x = to_t(xb)
                # photometric jitter (brightness/contrast) per image
                x = x * torch.from_numpy(rng.uniform(0.8, 1.2, (bs, 1, 1, 1)).astype(np.float32)) + \
                    torch.from_numpy(rng.uniform(-0.2, 0.2, (bs, 1, 1, 1)).astype(np.float32))
                x = x.to(dev, non_blocking=True); y = torch.from_numpy(yb.astype(np.int64)).to(dev)
                with torch.autocast("cuda", dtype=torch.float16):
                    lg = model(pixel_values=x).logits
                lg = F.interpolate(lg.float(), size=y.shape[-2:], mode="bilinear", align_corners=False)
                loss = F.cross_entropy(lg, y, weight=cw, ignore_index=255)
                opt.zero_grad(set_to_none=True); scaler.scale(loss).backward(); scaler.step(opt); scaler.update(); sched.step()
                tot += loss.item(); k += 1
                if k % 50 == 0:
                    tmp, _ = __import__("tools.gpu_lock", fromlist=["gpu_temp_c"]).gpu_temp_c()
                    print(f"  ep{ep} it{k} loss {tot / k:.4f} {tmp}C", flush=True)
                    if tmp and tmp >= 85: wait_cool()
            sec = time.time() - t0; t_gpu += sec
            log.append({"epoch": ep + 1, "loss": tot / k, "sec": sec})
            print(f"epoch {ep + 1}/{epochs} loss {tot / k:.4f} {sec:.0f}s (GPU total {t_gpu / 60:.1f} min)", flush=True)
            torch.save({"model": model.state_dict(), "opt": opt.state_dict(), "sched": sched.state_dict(), "epoch": ep + 1, "log": log}, ck)
        wait_cool()  # lock released between epochs so other jobs can interleave
    model.save_pretrained(OUT)
    json.dump({"train_log": log, "gpu_minutes": t_gpu / 60, "n_train": int(n), "class_weights": w.tolist(),
               "train_pixel_share": (cnt / cnt.sum()).tolist()}, open(os.path.join(OUT, "train_log.json"), "w"), indent=1)


def predict(model, x_np, size_out=None, dev="cuda"):
    """x_np: (B,512,512,3) uint8 -> softmax probs (B,4,h,w) at size_out (default 512), flip-free."""
    import torch, torch.nn.functional as F
    with torch.no_grad(), torch.autocast("cuda", dtype=torch.float16, enabled=DEV == "cuda"):
        lg = model(pixel_values=to_t(x_np).to(DEV)).logits
    lg = F.interpolate(lg.float(), size=size_out or x_np.shape[1:3], mode="bilinear", align_corners=False)
    return lg


def evaluate():
    import torch
    from transformers import SegformerForSemanticSegmentation
    from tools.gpu_lock import gpu_lock, wait_cool
    res = {}
    sets = sorted(d for d in os.listdir(os.path.join(ROOT, "labels", "test")) if os.path.isdir(os.path.join(ROOT, "labels", "test", d)))
    model = SegformerForSemanticSegmentation.from_pretrained(OUT).to(DEV).eval()
    with lock("ai4mars"):
        for ts in sets:
            lst = pairs(os.path.join(ROOT, "labels", "test", ts))
            conf = np.zeros((4, 4), np.int64)  # rows gt, cols pred
            for b in range(0, len(lst), 16):
                chunk = lst[b:b + 16]
                ims, lbs = [], []
                for ip, lp in chunk:
                    ims.append(np.asarray(Image.open(ip).convert("RGB").resize((SIZE, SIZE), Image.BILINEAR)))
                    lbs.append(np.asarray(Image.open(lp)))
                # evaluate at the label's native resolution (logits upsampled)
                for im, lb in zip(ims, lbs):
                    lg = predict(model, im[None], size_out=lb.shape)
                    pr = lg.argmax(1)[0].cpu().numpy()
                    m = lb != 255
                    conf += np.bincount(lb[m].astype(np.int64) * 4 + pr[m], minlength=16).reshape(4, 4)
                if DEV == "cuda": wait_cool()
            iou = [conf[i, i] / max(1, conf[i].sum() + conf[:, i].sum() - conf[i, i]) for i in range(4)]
            present = [i for i in range(4) if conf[i].sum() > 0]
            res[ts] = {"n_images": len(lst), "labelled_pixels": int(conf.sum()), "confusion_gt_rows_pred_cols": conf.tolist(),
                       "iou": dict(zip(CLASSES, [float(v) for v in iou])),
                       "miou": float(np.mean([iou[i] for i in present])), "pixel_acc": float(np.trace(conf) / max(1, conf.sum()))}
            print(ts, res[ts]["n_images"], "mIoU", res[ts]["miou"], res[ts]["iou"], flush=True)
    res["primary_test_set"] = TEST_SET
    json.dump(res, open(os.path.join(OUT, "metrics.json"), "w"), indent=1)


if __name__ == "__main__":
    {"prep": prep, "train": train, "eval": evaluate}[sys.argv[1]]()
