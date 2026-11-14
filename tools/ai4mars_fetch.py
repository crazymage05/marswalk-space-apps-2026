"""
Targeted extraction from the remote Zenodo zip (HTTP range requests) using the central directory.
Every member is CRC32-checked. Usage:
  python tools/ai4mars_fetch.py labels   # unpack test+train labels from labels_region.bin (already downloaded)
  python tools/ai4mars_fetch.py images N # choose N train frames (>=MINLAB labelled share) + all test frames, fetch their EDR JPEGs
"""
import io, json, os, pickle, random, struct, sys, time, urllib.request, zlib
import numpy as np
from PIL import Image
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(HERE, "data", "raw", "ai4mars")
DST = os.path.join(HERE, "data", "raw", "ai4mars_extracted", "ai4mars-dataset-merged-0.6", "msl", "ncam")
URL = "https://zenodo.org/api/records/15995036/files/ai4mars-dataset-merged-0.6.zip/content"
ENTS = pickle.load(open(os.environ["TEMP"] + "/ents.pkl", "rb"))
BY = {e[0]: e for e in ENTS}
PFX = "ai4mars-dataset-merged-0.6/msl/ncam/"
REG0 = 16123664000


def inflate(raw, comp):
    return zlib.decompress(raw, -15) if comp == 8 else raw


def member_from_buf(buf, base, ent):
    name, lo, cs, us, comp, crc = ent
    o = lo - base
    nl, el = struct.unpack("<HH", buf[o + 26:o + 30])
    d = inflate(buf[o + 30 + nl + el:o + 30 + nl + el + cs], comp)
    assert zlib.crc32(d) & 0xffffffff == crc, name
    return d


import threading, requests
_tl = threading.local()


def fetch_member(ent, tries=8):
    name, lo, cs, us, comp, crc = ent
    for t in range(tries):
        try:
            if not hasattr(_tl, "s"): _tl.s = requests.Session()
            r = _tl.s.get(URL, headers={"Range": f"bytes={lo}-{lo + 30 + 300 + len(name) + cs}"}, timeout=60)
            return member_from_buf(r.content, lo, ent)
        except Exception as ex:
            _tl.s = requests.Session(); time.sleep(3 + 3 * t); err = ex
    raise err


def write(name, data):
    p = os.path.join(DST, name[len(PFX):]); os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, "wb").write(data)


def labels():
    buf = open(os.path.join(RAW, "labels_region.bin"), "rb").read()
    sel = [e for e in ENTS if e[0].startswith(PFX + "labels/") and not e[0].endswith("/")]
    for e in sel: write(e[0], member_from_buf(buf, REG0, e))
    print("labels written", len(sel))


def images(n_train, minlab=0.2):
    random.seed(0)
    lab_dir = os.path.join(DST, "labels")
    test = {}
    for d in os.listdir(os.path.join(lab_dir, "test")):
        if d.startswith("masked-gold-min3"):
            test = {f[:-11] for f in os.listdir(os.path.join(lab_dir, "test", d)) if f.endswith("_merged.png")}
    cand = []
    for f in sorted(os.listdir(os.path.join(lab_dir, "train"))):
        stem = f[:-4]
        if PFX + "images/edr/" + stem + ".JPG" not in BY or stem in test: continue
        a = np.asarray(Image.open(os.path.join(lab_dir, "train", f)))
        if (a != 255).mean() >= minlab: cand.append(stem)
    print("train candidates with >=", minlab, "labelled:", len(cand), " test frames:", len(test))
    random.shuffle(cand)
    stems = sorted(set(cand[:n_train]) | test)
    ents = [BY[PFX + "images/edr/" + s + ".JPG"] for s in stems]
    tot = sum(e[2] for e in ents); print(len(ents), "images,", tot / 1e6, "MB compressed", flush=True)
    todo = [e for e in ents if not os.path.exists(os.path.join(DST, e[0][len(PFX):]))]
    done = 0
    def job(e):
        write(e[0], fetch_member(e)); return 1
    with ThreadPoolExecutor(2) as ex:
        for _ in ex.map(job, todo):
            done += 1
            if done % 200 == 0: print(done, "/", len(todo), flush=True)
    json.dump({"train_stems": sorted(set(cand[:n_train])), "test_stems": sorted(test)}, open(os.path.join(DST, "..", "..", "..", "subset.json"), "w"))


if __name__ == "__main__":
    labels() if sys.argv[1] == "labels" else images(int(sys.argv[2]))
