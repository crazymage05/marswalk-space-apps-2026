"""Run blender headless under the GPU lock: python tools/run_blender.py <lockname> <script.py> [args...]"""
import os, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gpu_lock import gpu_lock, wait_cool, gpu_temp_c
exe = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "blender_path.txt")).read().strip()
name, script, rest = sys.argv[1], sys.argv[2], sys.argv[3:]
with gpu_lock(name):
    wait_cool()
    r = subprocess.run([exe, "-b", "--python", script, "--"] + rest)
    print("GPU temp after:", gpu_temp_c())
sys.exit(r.returncode)
