"""
30-second demo (Space Apps limit: "The video pitch must be 30 seconds or less"; docs/submission_requirements.md).
Follows docs/video_script.md (machine A) beat by beat, with burned-in English captions and no voice (a voice-over can be
added later). One change from the script: 17.5-20.5 s shows the live mineral search with three destinations instead of
the dust film shot, because the mission-control clip right after it already carries the dust story.

    python tools/f3_cut30.py            # film shots from film/frames_orbital_v3 + film/frames_v3 if rendered, else the draft mp4

Live clips come from tools/f3_capture.py (F3_SIZE=1920x1080; clips entry, layers, why, find, mission_event).
Output film/marswalk_demo30.mp4 (1920x1080, 24 fps, H.264 via Blender's sequencer); the script checks it is <= 30.0 s.
"""
import json, os, shutil, subprocess, sys
import cv2
from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FPS, W, H = 24, 1920, 1080
OUT = os.path.join(ROOT, "film/frames_demo30"); MP4 = os.path.join(ROOT, "film/marswalk_demo30.mp4")
CAP = os.path.join(ROOT, "film/capture")
DRAFT = os.path.join(ROOT, "film/marswalk_f2_draft.mp4")
# film frame number -> draft mp4 frame index (draft = 4 segments joined by 12-frame dissolves, see tools/f2_final.py SEG)
SEG = [(1, 480, 0), (501, 1100, 492), (1121, 1600, 1104), (1621, 2100, 1596)]

# (kind, source, start, n_frames, title, subtitle). film: start = film frame number; live: start = seconds into the clip
EDL = [
    ("film", None, 1, 48, "MARSWALK", "A Mars walk planner built on NASA data"),
    ("film", None, 240, 72, "Interplanetary Survival Guide: Martian Map", "Curiosity's 2025 boxwork campaign, Mount Sharp, Gale crater"),
    ("live", "entry", 0.3, 72, "Plan it. Check it. Walk it.", "Runs in any web browser"),
    ("live", "layers", 3.5, 84, "Seven kinds of NASA data on one map", "HiRISE · CRISM · THEMIS · Navcam · RAD · REMS · ChemCam"),
    ("live", "why", 8.5, 60, "GO or NO-GO, and why", "Every route checked against flight rules, cell by cell"),
    ("film", None, 600, 84, "Walk it", "Suit limits in the visor, Mars gravity and gait"),
    ("live", "find", 5.5, 72, "Find water, plan the science", "Three CRISM targets, boulders avoided, back to start"),
    ("live", "mission_event", 1.5, 84, "Dust storm: the crew re-plans", "Earth's answer arrives 19 minutes later"),
    ("film", None, 1700, 72, "Real data, labelled honestly", "Every number marked measured, modelled or simulated"),
    ("film", None, 2052, 48, "MARSWALK", "NASA PDS · JPL Mars Trek · USGS geologic map · Perseverance raw images · NASA Worldview"),
]

fdir = "C:/Windows/Fonts"
fb = lambda s: ImageFont.truetype(os.path.join(fdir, "segoeuib.ttf"), s)
fr = lambda s: ImageFont.truetype(os.path.join(fdir, "segoeui.ttf"), s)
CREAM, AMBER, SUBC = (246, 238, 228), (224, 164, 99), (225, 210, 192)


def film_frame(f):
    for d in ("film/frames_orbital_v3", "film/frames_v3"):
        p = os.path.join(ROOT, d, f"frame_{f:04d}.png")
        if os.path.exists(p): return Image.open(p).convert("RGB")
    for a, b, off in SEG:
        if a <= f <= b:
            c = film_frame.cap = getattr(film_frame, "cap", None) or cv2.VideoCapture(DRAFT)
            c.set(cv2.CAP_PROP_POS_FRAMES, off + f - a); ok, im = c.read()
            if ok: return Image.fromarray(cv2.cvtColor(im, cv2.COLOR_BGR2RGB))
    raise FileNotFoundError(f"film frame {f}")


def live_frames(name, t0, n):
    c = cv2.VideoCapture(os.path.join(CAP, name + ".webm")); src = c.get(cv2.CAP_PROP_FPS) or 25
    total = int(c.get(cv2.CAP_PROP_FRAME_COUNT)); cur, last = -1, None
    for k in range(n):
        want = min(total - 1, int(round((t0 + k / FPS) * src)))
        while cur < want:
            ok, im = c.read()
            if not ok: break
            cur += 1; last = im
        if last is None: raise RuntimeError(f"clip {name} is empty")
        yield Image.fromarray(cv2.cvtColor(last, cv2.COLOR_BGR2RGB))


def caption(im, title, sub, a):
    im = im.resize((W, H), Image.LANCZOS) if im.size != (W, H) else im
    if a <= 0: return im
    im = im.convert("RGBA"); ov = Image.new("RGBA", im.size, (0, 0, 0, 0)); d = ImageDraw.Draw(ov)
    T, S = fb(48), fr(30); x, y = 72, H - 196
    w = max(d.textlength(title, font=T), d.textlength(sub, font=S)) + 60
    d.rounded_rectangle((x - 28, y - 22, x - 28 + w, y + 116), 10, fill=(14, 10, 8, int(185 * a)))
    d.rectangle((x - 28, y - 22, x - 22, y + 116), fill=AMBER + (int(255 * a),))
    d.text((x, y), title, font=T, fill=CREAM + (int(255 * a),))
    d.text((x, y + 66), sub, font=S, fill=SUBC + (int(255 * a),))
    return Image.alpha_composite(im, ov).convert("RGB")


if __name__ == "__main__":
    shutil.rmtree(OUT, ignore_errors=True); os.makedirs(OUT); idx = 0; parts = []
    total = sum(e[3] for e in EDL); assert total <= 30 * FPS, total
    for kind, src, start, n, title, sub in EDL:
        parts.append({"from_frame": idx + 1, "kind": kind, "src": src or "film", "start": start, "frames": n, "title": title})
        frames = (film_frame(start + k) for k in range(n)) if kind == "film" else live_frames(src, start, n)
        for k, im in enumerate(frames):
            a = min(1.0, (k + 1) / 6, (n - k) / 6)                         # captions ease in/out over 1/4 s per shot
            fade = min(1.0, (idx + 1) / 12, (total - idx) / 12)             # half-second fade from/to black at the ends
            fr_ = caption(im, title, sub, a)
            if fade < 1: fr_ = Image.blend(Image.new("RGB", (W, H)), fr_, fade)
            idx += 1; fr_.save(os.path.join(OUT, f"frame_{idx:04d}.jpg"), quality=93)
    json.dump({"fps": FPS, "frames": idx, "seconds": idx / FPS, "film_source": "final frames" if os.path.isdir(os.path.join(ROOT, "film/frames_v3")) else "draft mp4", "parts": parts},
              open(os.path.join(OUT, "edit_list.json"), "w"), indent=1)
    print("frames", idx, "=", idx / FPS, "s")
    out, src = MP4.replace("\\", "/"), OUT.replace("\\", "/")
    code = f"""
import bpy
sc = bpy.context.scene; sc.render.fps = {FPS}; sc.frame_start = 1; sc.frame_end = {idx}
sc.render.resolution_x, sc.render.resolution_y, sc.render.resolution_percentage = {W}, {H}, 100
st = sc.sequence_editor_create().strips.new_image(name="d30", filepath="{src}/frame_0001.jpg", channel=1, frame_start=1)
for i in range(2, {idx} + 1): st.elements.append(f"frame_{{i:04d}}.jpg")
r = sc.render; r.image_settings.file_format = "FFMPEG"; r.ffmpeg.format = "MPEG4"; r.ffmpeg.codec = "H264"
r.ffmpeg.constant_rate_factor = "HIGH"; r.ffmpeg.ffmpeg_preset = "GOOD"; r.ffmpeg.audio_codec = "NONE"
sc.view_settings.view_transform = "Standard"; sc.view_settings.look = "None"; sc.view_settings.exposure = 0; sc.view_settings.gamma = 1  # frames are display-ready sRGB: pass them through (AgX greyed them)
r.use_sequencer = True; r.filepath = "{out}"; r.use_file_extension = False
bpy.ops.render.render(animation=True)
"""
    tmp = os.path.join(ROOT, "film/_d30_tmp.py"); open(tmp, "w").write(code)
    blender = open(os.path.join(ROOT, "tools/blender_path.txt")).read().strip()
    rc = subprocess.run([blender, "-b", "--factory-startup", "--python", tmp], capture_output=True).returncode; os.remove(tmp)
    c = cv2.VideoCapture(MP4); n = int(c.get(cv2.CAP_PROP_FRAME_COUNT)); fps = c.get(cv2.CAP_PROP_FPS)
    print("blender exit", rc, "->", MP4, f"{n} frames at {fps} fps = {n / fps:.2f} s", "OK <= 30 s" if n / fps <= 30.0 else "TOO LONG")
