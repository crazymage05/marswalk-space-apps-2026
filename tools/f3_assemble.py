"""
F3 final video: title card | F2 film (without its own end card) | live-demo clips from tools/f3_capture.py | end card.
H.264 1920x1080 24 fps through Blender's sequencer (no ffmpeg on B), same encoder settings as tools/f2_final.py.

    python tools/f3_assemble.py            # uses film/marswalk_f2_final.mp4 if present, else the draft
    python tools/f3_assemble.py --draft    # force the draft film

Trims (seconds into each capture) are in CLIPS below; picked from a contact sheet of the 1280x720 captures
(each twin clip starts with 2-3 s of loading screen). Capture frames (25 fps) are resampled by time to 24 fps and
scaled to 1080p. Writes film/frames_f3/*.jpg, film/frames_f3/edit_list.json and film/marswalk_f3[_draft].mp4.
"""
import json, os, shutil, subprocess, sys
import cv2
from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FPS, W, H = 24, 1920, 1080
FINAL = os.path.join(ROOT, "film/marswalk_f2_final.mp4")
DRAFT = "--draft" in sys.argv or not os.path.exists(FINAL)
FILM = os.path.join(ROOT, "film/marswalk_f2_draft.mp4") if DRAFT else FINAL
FILM_END_N = 96                                   # f2_final.py END_N: the film's own end card is replaced by ours
OUT = os.path.join(ROOT, "film/frames_f3"); MP4 = "film/marswalk_f3" + ("_draft" if DRAFT else "") + ".mp4"
CARD_N, TITLE_N, END_N = 36, 72, 120

# (clip, start s, end s, section card, label on the clip)
CLIPS = [("entry",   0.5, 14.0, "The website",            "Opens in any browser. Works offline."),
         ("tour",    3.5, 47.0, "Guided tour",            "Digital twin of Gale crater: real HiRISE terrain and rover data"),
         ("why",     3.0, 24.5, "Why this route",         "Every flight rule checked, cell by cell, against the straight line"),
         ("walk",    5.0, 26.5, "Walk the route",         "First person and follow view, Mars gait and suit limits"),
         ("mission", 0.5, 56.0, "Mission control",        "What Earth sees: suit health, light-time delay, simulated leak")]
END = ["MARSWALK", "Shortest safe walking routes on Mars, checked against flight rules",
       "Data: NASA/JPL-Caltech, University of Arizona (HiRISE), MSSS, MOLA team. Dust event and suit leak simulated.",
       "Backpack added to the NASA Mark III model for the film (illustrative)."]

fdir = "C:/Windows/Fonts"
fb = lambda s: ImageFont.truetype(os.path.join(fdir, "segoeuib.ttf"), s)
fr = lambda s: ImageFont.truetype(os.path.join(fdir, "segoeui.ttf"), s)
BG, CREAM, AMBER, GREY = (12, 9, 7), (246, 238, 228), (224, 164, 99), (200, 188, 172)


def ramp(k, n, edge=12): return max(0.0, min(1.0, k / edge, (n - 1 - k) / edge))


def card(lines, k, n):                            # lines: [(text, font, colour, y)]
    im = Image.new("RGB", (W, H), BG); d = ImageDraw.Draw(im); a = ramp(k, n)
    for t, f, c, y in lines:
        d.text((W // 2, y), t, font=f, fill=tuple(int(BG[i] + (c[i] - BG[i]) * a) for i in range(3)), anchor="mm")
    return im


BAR = 72                                          # demo clips are scaled to 1792x1008 under a 72 px label strip, so the label covers nothing


def label(im, title, sub, a):                     # page capture framed under a label strip
    out = Image.new("RGB", (W, H), BG); out.paste(im.resize((W - 2 * 64, H - BAR), Image.LANCZOS), (64, BAR))
    d = ImageDraw.Draw(out); c = lambda col: tuple(int(BG[i] + (col[i] - BG[i]) * a) for i in range(3))
    d.rectangle((64, 18, 69, BAR - 14), fill=c(AMBER))
    d.text((84, BAR // 2 - 2), "LIVE DEMO  " + title, font=fb(30), fill=c(CREAM), anchor="lm")
    d.text((W - 64, BAR // 2 - 2), sub, font=fr(22), fill=c((225, 210, 192)), anchor="rm")
    return out


def video_frames(path, t0=0.0, t1=None):          # resample any fps to 24 by time, scale to 1080p
    c = cv2.VideoCapture(path); src = c.get(cv2.CAP_PROP_FPS); n = int(c.get(cv2.CAP_PROP_FRAME_COUNT))
    t1 = n / src if t1 is None else min(t1, n / src); cur, fr_ = -1, None
    for k in range(int((t1 - t0) * FPS)):
        want = min(n - 1, int(round((t0 + k / FPS) * src)))
        while cur < want:
            ok, f = c.read()
            if not ok: break
            cur += 1; fr_ = f
        im = Image.fromarray(cv2.cvtColor(fr_, cv2.COLOR_BGR2RGB))
        yield im if im.size == (W, H) else im.resize((W, H), Image.LANCZOS)


if __name__ == "__main__":
    shutil.rmtree(OUT, ignore_errors=True); os.makedirs(OUT)
    idx = 0; edit = []

    def put(im):
        global idx
        idx += 1; im.save(os.path.join(OUT, f"frame_{idx:04d}.jpg"), quality=92)

    def mark(name): edit.append({"part": name, "from_frame": idx + 1})

    mark("title")
    for k in range(TITLE_N):
        put(card([("MARSWALK", fb(110), CREAM, 470), ("Finding the shortest safe walk across Mars", fr(40), AMBER, 580)], k, TITLE_N))
    mark("film " + os.path.basename(FILM))
    c = cv2.VideoCapture(FILM); film_n = int(c.get(cv2.CAP_PROP_FRAME_COUNT)); c.release()
    for k, im in enumerate(video_frames(FILM)):
        if k >= film_n - FILM_END_N: break
        put(im)
    for name, t0, t1, title, sub in CLIPS:
        mark("card " + name)
        for k in range(CARD_N): put(card([("LIVE DEMO", fb(30), AMBER, 480), (title, fb(72), CREAM, 550)], k, CARD_N))
        mark("clip " + name)
        n = int((t1 - t0) * FPS)
        for k, im in enumerate(video_frames(os.path.join(ROOT, "film/capture", name + ".webm"), t0, t1)):
            put(label(im, title, sub, min(1.0, k / 12) if k < n - 24 else ramp(k, n)))
    mark("end")
    for k in range(END_N):
        put(card([(END[0], fb(96), CREAM, 400), (END[1], fr(36), AMBER, 500), (END[2], fr(26), GREY, 640), (END[3], fr(22), (160, 150, 138), 690)], k, END_N))
    print("frames", idx, "=", round(idx / FPS, 1), "s")
    json.dump({"film": FILM, "clips": CLIPS, "end": END, "frames": idx, "parts": edit}, open(os.path.join(OUT, "edit_list.json"), "w"), indent=1)

    out = os.path.join(ROOT, MP4).replace("\\", "/"); src = OUT.replace("\\", "/")
    code = f"""
import bpy
sc = bpy.context.scene; sc.render.fps = {FPS}; sc.frame_start = 1; sc.frame_end = {idx}
sc.render.resolution_x, sc.render.resolution_y, sc.render.resolution_percentage = {W}, {H}, 100
se = sc.sequence_editor_create()
st = se.strips.new_image(name="f3", filepath="{src}/frame_0001.jpg", channel=1, frame_start=1)
for i in range(2, {idx} + 1): st.elements.append(f"frame_{{i:04d}}.jpg")
r = sc.render; r.image_settings.file_format = "FFMPEG"; r.ffmpeg.format = "MPEG4"; r.ffmpeg.codec = "H264"
r.ffmpeg.constant_rate_factor = "HIGH"; r.ffmpeg.ffmpeg_preset = "GOOD"; r.ffmpeg.audio_codec = "NONE"
r.use_sequencer = True; r.filepath = "{out}"; r.use_file_extension = False
bpy.ops.render.render(animation=True)
"""
    tmp = os.path.join(ROOT, "film/_f3_tmp.py"); open(tmp, "w").write(code)
    blender = open(os.path.join(ROOT, "tools/blender_path.txt")).read().strip()
    rc = subprocess.run([blender, "-b", "--factory-startup", "--python", tmp], capture_output=True).returncode; os.remove(tmp)
    print("blender exit", rc, "->", out, os.path.exists(out) and f"{os.path.getsize(out) / 1e6:.1f} MB")
