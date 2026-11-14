#!/usr/bin/env python3
"""F2 film render on machine B, restartable, GPU lock + temperature guard.
   python tools/f2_render.py [--first 1] [--last 2100] [--res 1920x1080] [--spp 96] [--chunk 60] [--out film/frames]
One Blender process per chunk of frames (wait_cool() before each chunk and every frame is skipped if its PNG exists)."""
import argparse, os, subprocess, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); os.chdir(ROOT); sys.path.insert(0, ROOT)
from tools.gpu_lock import gpu_lock, wait_cool
ap = argparse.ArgumentParser(); ap.add_argument("--first", type=int, default=1); ap.add_argument("--last", type=int, default=2100)
ap.add_argument("--res", default="1920x1080"); ap.add_argument("--spp", type=int, default=96); ap.add_argument("--chunk", type=int, default=60)
ap.add_argument("--out", default="film/frames"); ap.add_argument("--blend", default="film/marswalk_scene.blend")
ap.add_argument("--lock-name", default="f2-render"); ap.add_argument("--per-chunk-lock", action="store_true", help="take/release the GPU lock around every chunk (lets other jobs interleave)")
a = ap.parse_args(); w, h = a.res.split("x")
blender = open("tools/blender_path.txt").read().strip()
import contextlib
def run_chunk(f0):
    wait_cool()
    subprocess.check_call([blender, "-b", a.blend, "--python", "tools/f2_render_chunk.py", "--",
                           str(f0), str(min(f0 + a.chunk - 1, a.last)), os.path.join(ROOT, a.out), w, h, str(a.spp)])
if a.per_chunk_lock:
    for f0 in range(a.first, a.last + 1, a.chunk):
        with gpu_lock(a.lock_name): run_chunk(f0)
else:
    with gpu_lock(a.lock_name):
        for f0 in range(a.first, a.last + 1, a.chunk): run_chunk(f0)
