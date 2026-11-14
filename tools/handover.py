"""
Copy hand-over files between machine B and the USB drive (git carries code only).

    python tools/handover.py to-usb F:      # B -> USB: everything A needs from B (manifest below)
    python tools/handover.py from-usb F:    # USB -> B: what A left for B (USB:/marswalk_A_to_B/...)
    python tools/handover.py list           # show what would be copied to the USB and the sizes

Files keep their project-relative paths under USB:/marswalk_B_to_A/ (and USB:/marswalk_A_to_B/), so the
other machine copies the folder over its project root. Existing newer files are not overwritten on the
way in; a manifest with sizes and SHA-256 is written next to the files so the receiver can verify.
"""
import glob, hashlib, json, os, shutil, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# B -> A: hand-overs listed in PROGRESS.md / BUILD_PLAN.md (globs relative to the project root)
B_TO_A = [
    "docs/world_model.md", "docs/twin_rendering.md", "docs/research/*",                  # S1: docs A asked for
    "docs/w5a_walk_cycle.md", "docs/verification/w5a_*", "docs/figures/w5a_*",           # W5a
    "demo/twin/models/markIII_suit_walk.glb", "demo/twin/models/markIII_suit_walk.glb.json",
    "demo/twin/models/*.glb.json",                                                        # repacked by pack_models.py
    "docs/w7_texture_seam.md", "docs/figures/w7_*", "demo/twin/tex/*.jpg", "demo/twin/tex/textures.json",   # W7
    "docs/rover_meshes.md", "demo/twin/meshes/*.glb", "demo/twin/meshes/*.glb.json",     # W6
    "demo/twin/meshes/meshes.json", "demo/twin/meshes/meshes_index.json", "demo/twin/meshes/quicklook/*",
    "docs/f1_blender_scene.md", "film/test_*.png",                                        # F1
    "docs/ai4mars_results.md", "data/processed/roi/ai4mars_campaign_frames.json",           # I1-I3
    "data/processed/roi/world/rover_ground_evidence_4m.json", "models/ai4mars_segformer_b0/*",
    "docs/phase4_rl_run3.md", "models/ppo_world_v3*", "docs/verification/r1_eval/*",      # R1
    "docs/astronaut_model.md", "docs/competitive_scan.md", "docs/phase4_navigation.md",   # astronaut v2, scan, planner
    "film/marswalk_f2.mp4", "film/test_orb_*.png", "film/f2_compare_navcam.png",          # F2 clip
]
OUT_DIR, IN_DIR = "marswalk_B_to_A", "marswalk_A_to_B"


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""): h.update(b)
    return h.hexdigest()


def files():
    out = []
    for g in B_TO_A:
        for p in sorted(glob.glob(os.path.join(ROOT, g))):
            if os.path.isfile(p): out.append(os.path.relpath(p, ROOT).replace("\\", "/"))
    return sorted(set(out))


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "list"
    if cmd == "list":
        fs = files(); tot = sum(os.path.getsize(os.path.join(ROOT, f)) for f in fs)
        for f in fs: print(f"{os.path.getsize(os.path.join(ROOT, f)) / 1e6:9.2f} MB  {f}")
        print(f"{len(fs)} files, {tot / 1e9:.2f} GB"); return
    usb = sys.argv[2].rstrip("\\/") + os.sep
    if cmd == "to-usb":
        dst = os.path.join(usb, OUT_DIR); man = []
        for f in files():
            s, d = os.path.join(ROOT, f), os.path.join(dst, f); os.makedirs(os.path.dirname(d), exist_ok=True)
            shutil.copy2(s, d); man.append({"path": f, "bytes": os.path.getsize(s), "sha256": sha(s)})
            print("copied", f)
        json.dump({"from": "B", "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "files": man},
                  open(os.path.join(dst, "MANIFEST.json"), "w"), indent=1)
        shutil.copy2(os.path.join(ROOT, "tools/handover_README_B_to_A.txt"), os.path.join(dst, "README.txt"))   # steps for A
        bad = [m["path"] for m in man if sha(os.path.join(dst, m["path"])) != m["sha256"]]
        print(f"{len(man)} files copied to {dst}; verify failures: {bad or 'none'}")
    elif cmd == "from-usb":
        src = os.path.join(usb, IN_DIR); n = 0
        for d, _, fs in os.walk(src):
            for name in fs:
                s = os.path.join(d, name); rel = os.path.relpath(s, src); t = os.path.join(ROOT, rel)
                if rel == "MANIFEST.json": continue
                if os.path.exists(t) and os.path.getmtime(t) > os.path.getmtime(s):
                    print("kept newer local", rel); continue
                os.makedirs(os.path.dirname(t), exist_ok=True); shutil.copy2(s, t); n += 1; print("copied in", rel)
        print(f"{n} files copied from {src}")


if __name__ == "__main__":
    main()
