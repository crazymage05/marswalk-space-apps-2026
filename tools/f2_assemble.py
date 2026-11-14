"""
Assemble the F2 film clip from rendered PNG frames with Blender's sequencer (no ffmpeg needed on B).

    python tools/f2_assemble.py [--out film/marswalk_f2.mp4] [--fps 24]

Frames 1-480 come from film/frames_orbital_v2 and 1121-1600 from film/frames_dust_v2 when complete
(re-rendered shots), else from film/frames, which supplies everything else. Every frame must exist;
the script lists any that are missing and stops rather than making a clip with holes. CPU only.
"""
import argparse, os, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ap = argparse.ArgumentParser(); ap.add_argument("--out", default="film/marswalk_f2.mp4")
ap.add_argument("--fps", type=int, default=24); ap.add_argument("--last", type=int, default=2100)
a = ap.parse_args()
MAIN, ORB = os.path.join(ROOT, "film/frames"), os.path.join(ROOT, "film/frames_orbital_v2")
DUST = os.path.join(ROOT, "film/frames_dust_v2")              # dust shot re-rendered from marswalk_scene_dustfix.blend
fn = lambda d, i: os.path.join(d, f"frame_{i:04d}.png")
use_orb = all(os.path.exists(fn(ORB, i)) for i in range(1, 481))
use_dust = all(os.path.exists(fn(DUST, i)) for i in range(1121, 1601))
src = lambda i: ORB if (use_orb and i <= 480) else DUST if (use_dust and 1121 <= i <= 1600) else MAIN
plan = [(src(i), i) for i in range(1, a.last + 1)]
missing = [p for p in (fn(d, i) for d, i in plan) if not os.path.exists(p)]
if missing:
    print(f"{len(missing)} frames missing, e.g. {missing[:5]}; not assembling"); sys.exit(1)
print("orbital v2 for 1-480:", use_orb, "| dust v2 for 1121-1600:", use_dust)
blender = open(os.path.join(ROOT, "tools/blender_path.txt")).read().strip()
out = os.path.join(ROOT, a.out).replace("\\", "/")
segs = []
for i in range(1, a.last + 1):                                  # contiguous runs of frames from the same folder
    if segs and segs[-1][0] == src(i): segs[-1][2] = i
    else: segs.append([src(i), i, i])
code = f"""
import bpy
sc = bpy.context.scene; sc.render.fps = {a.fps}; sc.frame_start = 1; sc.frame_end = {a.last}
sc.render.resolution_x, sc.render.resolution_y, sc.render.resolution_percentage = 1920, 1080, 100
se = sc.sequence_editor_create()
for k, (d, f0, f1) in enumerate({[(s[0].replace(chr(92), '/'), s[1], s[2]) for s in segs]!r}):
    st = se.strips.new_image(name=f"s{{k}}", filepath=f"{{d}}/frame_{{f0:04d}}.png", channel=1, frame_start=f0)
    for i in range(f0 + 1, f1 + 1): st.elements.append(f"frame_{{i:04d}}.png")
r = sc.render; r.image_settings.file_format = "FFMPEG"; r.ffmpeg.format = "MPEG4"; r.ffmpeg.codec = "H264"
r.ffmpeg.constant_rate_factor = "HIGH"; r.ffmpeg.ffmpeg_preset = "GOOD"; r.ffmpeg.audio_codec = "NONE"
r.use_sequencer = True; r.filepath = "{out}"; r.use_file_extension = False
bpy.ops.render.render(animation=True)
"""
tmp = os.path.join(ROOT, "film/_assemble_tmp.py"); open(tmp, "w").write(code)
rc = subprocess.run([blender, "-b", "--factory-startup", "--python", tmp]).returncode
os.remove(tmp); print("blender exit", rc, "->", out, os.path.exists(out) and f"{os.path.getsize(out) / 1e6:.1f} MB")
