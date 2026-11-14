#!/usr/bin/env python3
"""Test stills (640x360, low samples) under the GPU lock.  python tools/f1_render_test.py [shot ...]"""
import os, subprocess, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); os.chdir(ROOT); sys.path.insert(0, ROOT)
from tools.gpu_lock import gpu_lock, wait_cool
blender = open("tools/blender_path.txt").read().strip()
SHOTS = {"orbital": (300, None), "walk": (800, None), "dust": (1450, None), "detour": (1850, None),
         "close1": (700, "Cam_2b_close"), "close2": (950, "Cam_2c_low")}      # close1/close2: walk-height stills
args = [a for a in sys.argv[1:] if not a.startswith("--")]; todo = args or list(SHOTS)
RES = os.environ.get("F1_TEST_RES", "640x360").split("x"); SPP = os.environ.get("F1_TEST_SPP", "32")
with gpu_lock("f1"):
    for n in todo:
        wait_cool()
        subprocess.check_call([blender, "-b", "film/marswalk_scene.blend", "--python", "tools/f1_render_still.py", "--",
                               str(SHOTS[n][0]), os.path.join(ROOT, "film", f"test_{n}.png"), RES[0], RES[1], SPP] + ([SHOTS[n][1]] if SHOTS[n][1] else []))
