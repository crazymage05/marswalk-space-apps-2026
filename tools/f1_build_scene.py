#!/usr/bin/env python3
"""F1 driver: python tools/f1_build_scene.py  ->  film/marswalk_scene.blend  (see docs/f1_blender_scene.md)
   python tools/f1_build_scene.py --orbital  ->  film/marswalk_scene_orbital.blend (MOLA/Gale context + Gale-scale orbital descent; reuses film/f1_data, does not rewrite it,
   so it is safe while a render of the main scene is running)"""
import os, subprocess, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); os.chdir(ROOT)
blender = open("tools/blender_path.txt").read().strip()
if "--orbital" in sys.argv:
    subprocess.check_call([sys.executable, "tools/f1_prep_mola.py"])
    subprocess.check_call([blender, "-b", "--python", "tools/f1_blender_scene.py", "--", ROOT], env={**os.environ, "F1_ORBITAL": "1"})
else:
    subprocess.check_call([sys.executable, "tools/f1_prep_data.py"])
    subprocess.check_call([blender, "-b", "--python", "tools/f1_blender_scene.py", "--", ROOT])
