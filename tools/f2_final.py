"""
F2 final cut: edit list + data captions + end card, then H.264 through Blender's sequencer (no ffmpeg on B).

    python tools/f2_final.py --draft     # review cut from the low-res preview render (film/preview/) -> film/marswalk_f2_draft.mp4
    python tools/f2_final.py             # final cut from the full render (film/frames_orbital_v3, film/frames_v3)
    python tools/f2_final.py --stills    # 11 captioned sample frames only

Story (v3 scene, tools/f1_prep_data.py): the astronaut walks MARSWALK's shortest safe route; the crane shot shows the
straight line start->goal in red with the 4 m cells where it breaks the 25 deg walker slope rule (CS-01).
Edit list (24 fps): orbital 1-480 | dissolve | walk 501-1100 | dissolve | dust (SIMULATED) 1121-1600 | dissolve |
crane 1621-2100 | end card. Every number in a caption is computed here from the files in CAPTION_SOURCES.
"""
import json, os, subprocess, sys
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, ROOT)
from phase4 import costs, astar, astronaut as A, safety_validator as SV

PREVIEW = "--stills" in sys.argv                         # 11 sample frames only
DRAFT = "--draft" in sys.argv                             # low-res review cut from film/preview/ (upscaled to 1080p for captions)
OUT = os.path.join(ROOT, "film/frames_final" + ("_stills" if PREVIEW else "_draft" if DRAFT else ""))
MP4 = "film/marswalk_f2_draft.mp4" if DRAFT else "film/marswalk_f2_final.mp4"
F = lambda d, i: os.path.join(ROOT, d, f"frame_{i:04d}.png")
# v3 scene: walk on MARSWALK's shortest safe route, crane over the rejected straight line (tools/f1_prep_data.py)
SEG = ([("film/preview/orbital", 1, 480), ("film/preview/main", 501, 1100), ("film/preview/main", 1121, 1600), ("film/preview/main", 1621, 2100)] if DRAFT else
       [("film/frames_orbital_v3", 1, 480), ("film/frames_v3", 501, 1100), ("film/frames_v3", 1121, 1600), ("film/frames_v3", 1621, 2100)])
DISSOLVE, END_N = 12, 96

# ---------------------------------------------------------------- numbers for the captions, computed here
grid = costs.load_grid(); P = A.get_profile("nominal")
R = {r["id"]: r for r in json.load(open(os.path.join(ROOT, "data/processed/roi/routes_astar.json")))["routes"]}
def metr(rid):
    c = R[rid]["route"]; m = astar.route_metrics(grid, c, P); v = SV.validate(c, grid, P)
    return dict(km=m["distance_m"] / 1000, min=m["time_s"] / 60, kj=m["energy_kj"], dose=m["dose_uGy"], go=v["ok"])
DIR = metr("campaign")                                       # film v3: cyan = MARSWALK route 'campaign' (walked)
DIR_MAX = max(float(grid["slope_max_deg"][divmod(c, grid["width"])]) for c in R["campaign"]["route"])
SJ = json.load(open(os.path.join(ROOT, "film/f1_data/scene.json")))
_p = np.array(SJ["route_direct"]); STRAIGHT_KM = float(np.hypot(*(_p[1] - _p[0]))) / 1000
NOGO_N, NOGO_MAX = len(SJ["nogo"]), max(SJ["nogo_slopes"])
RP = json.load(open(os.path.join(ROOT, "demo/twin/replan.json")))
lt = {l.split(",")[0]: float(l.split(",")[1]) for l in open(os.path.join(ROOT, "data/processed/roi/tables/light_time_2025.csv")).read().splitlines()[1:]}
LT = lt["2025-07-15"]                                       # film sun = 2025-07-15 (film/f1_data/scene.json)
d_m = RP["after"]["distance_m"] - RP["before"]["distance_m"]; d_kj = RP["after"]["energy_kj"] - RP["before"]["energy_kj"]
CAPTION_SOURCES = {"routes": "data/processed/roi/routes_astar.json via phase4.astar.route_metrics + safety_validator (astronaut model v2)",
                   "straight_line": "film/f1_data/scene.json route_direct, nogo, nogo_slopes (tools/f1_prep_data.py, safety_validator CS-01)",
                   "replan": "demo/twin/replan.json (tools/export_replan.py)", "light_time": "data/processed/roi/tables/light_time_2025.csv"}
GO = lambda m: "validator GO" if m["go"] else "validator NO-GO"

# captions per segment: (segment index, first local frame, last local frame, title, subtitle)
CAP = [
    (0, 20, 200, "Gale Crater, Mars", "Terrain from orbit: MOLA and HiRISE stereo elevation (NASA/JPL/UArizona)"),
    (0, 215, 470, "Mount Sharp boxwork", "Where Curiosity drove in 2025, sols 4500 to 4799"),
    (1, 10, 190, "MARSWALK plans the shortest safe walk", f"{DIR['km']:.2f} km to the goal; every 4 m cell checked for slope, roughness and data confidence"),
    (1, 200, 390, f"{DIR['min']:.0f} min  |  {DIR['kj']:,.0f} kJ  |  {DIR['dose']:.1f} µGy", f"Suited walk model from NASA reduced-gravity walking data at Mars gravity  |  {GO(DIR)}"),
    (1, 400, 590, "Rocks and ground from the rover", "Curiosity Navcam 3D scans placed where they were taken"),
    (2, 15, 230, "Dust event (SIMULATED)", "Flight rule HZ-1: ground under a dust core (optical depth 2 or more) is closed"),
    (2, 245, 470, f"Earth is {LT:.1f} light-minutes away", f"Round trip {2 * LT:.0f} min: the crew re-plans on site and Earth confirms later"),
    (3, 15, 230, "The straight line is rejected", f"{NOGO_N} cells steeper than the walker's 25° limit, up to {NOGO_MAX:.1f}° (flight rule CS-01)  |  NO-GO"),
    (3, 245, 470, "MARSWALK walks around them", f"{DIR['km']:.2f} km against {STRAIGHT_KM:.2f} km straight ({100 * (DIR['km'] / STRAIGHT_KM - 1):.0f}% longer), steepest cell {DIR_MAX:.0f}°  |  {GO(DIR)}"),
]
END = ["MARSWALK", "A Mars walk planner and digital twin that runs in a web browser",
       "Data: NASA/JPL-Caltech, University of Arizona (HiRISE), MSSS, MOLA team. Dust event simulated.",
       "Backpack added to the NASA Mark III model for the film (illustrative)."]

fdir = "C:/Windows/Fonts"
fb = lambda s: ImageFont.truetype(os.path.join(fdir, "segoeuib.ttf"), s)
fr = lambda s: ImageFont.truetype(os.path.join(fdir, "segoeui.ttf"), s)
TITLE, SUB, MARK = fb(46), fr(29), fb(24)


def caption(im, title, sub, alpha):
    if alpha <= 0: return im
    ov = Image.new("RGBA", im.size, (0, 0, 0, 0)); d = ImageDraw.Draw(ov)
    x, y = 72, im.height - 190
    w = max(d.textlength(title, font=TITLE), d.textlength(sub, font=SUB)) + 56
    d.rounded_rectangle((x - 28, y - 22, x - 28 + w, y + 112), 10, fill=(14, 10, 8, int(170 * alpha)))
    d.rectangle((x - 28, y - 22, x - 22, y + 112), fill=(224, 164, 99, int(255 * alpha)))
    d.text((x, y), title, font=TITLE, fill=(246, 238, 228, int(255 * alpha)))
    d.text((x, y + 64), sub, font=SUB, fill=(225, 210, 192, int(255 * alpha)))
    return Image.alpha_composite(im, ov)


def mark(im):
    d = ImageDraw.Draw(im); d.text((44, 32), "MARSWALK", font=MARK, fill=(246, 238, 228, 200)); return im


def fade(k, a, b, n=12):                                    # caption alpha at local frame k for range [a, b]
    if k < a or k > b: return 0.0
    return min(1.0, (k - a) / n, (b - k) / n)


def load(p):                                                # every source frame is scaled to 1920x1080 before captions
    im = Image.open(p).convert("RGBA")
    return im if im.size == (1920, 1080) else im.resize((1920, 1080), Image.LANCZOS)


def end_card(k):
    im = Image.new("RGBA", (1920, 1080), (12, 9, 7, 255)); d = ImageDraw.Draw(im)
    a = min(1.0, k / 18) * min(1.0, (END_N - k) / 18)
    c = lambda r, g, b: (r, g, b, int(255 * a))
    d.text((960, 400), END[0], font=fb(96), fill=c(246, 238, 228), anchor="mm")
    d.text((960, 500), END[1], font=fr(36), fill=c(224, 164, 99), anchor="mm")
    d.text((960, 640), END[2], font=fr(26), fill=c(200, 188, 172), anchor="mm")
    d.text((960, 690), END[3], font=fr(22), fill=c(160, 150, 138), anchor="mm")
    return im


def frames():                                               # yields (image factory)
    for si, (d, f0, f1) in enumerate(SEG):
        for k, i in enumerate(range(f0, f1 + 1)):
            def mk(d=d, i=i, k=k, si=si):
                im = load(F(d, i))
                for (s, a, b, t, sub) in CAP:
                    if s == si: im = caption(im, t, sub, fade(k, a, b))
                return mark(im)
            yield mk
        if si + 1 < len(SEG):                               # dissolve into the next shot
            nd, n0, _ = SEG[si + 1]
            for j in range(1, DISSOLVE + 1):
                yield (lambda d=d, f1=f1, nd=nd, n0=n0, j=j: mark(Image.blend(load(F(d, f1)), load(F(nd, n0)), j / (DISSOLVE + 1))))
    for k in range(END_N): yield (lambda k=k: end_card(k))


if __name__ == "__main__":
    need = [F(d, i) for d, f0, f1 in SEG for i in range(f0, f1 + 1)]
    miss = [p for p in need if not os.path.exists(p)]
    if miss and not PREVIEW: print(len(miss), "frames missing, e.g.", miss[:3]); sys.exit(1)
    os.makedirs(OUT, exist_ok=True)
    print("numbers:", {"route": DIR, "route_max_slope": DIR_MAX, "straight_km": STRAIGHT_KM, "nogo": (NOGO_N, NOGO_MAX), "light_min": LT})
    fs = list(frames()); print("total frames", len(fs), "=", round(len(fs) / 24, 1), "s")
    picks = {100, 300, 520, 720, 900, 1100, 1350, 1580, 1800, 2000, len(fs) - 40} if PREVIEW else None
    n = 0
    for idx, mk in enumerate(fs, 1):
        if picks and idx not in picks: continue
        try: im = mk()
        except FileNotFoundError: continue
        im.convert("RGB").save(os.path.join(OUT, f"frame_{idx:04d}.jpg"), quality=94); n += 1
    print("wrote", n, "frames to", OUT)
    if PREVIEW: sys.exit(0)
    json.dump({"captions": CAP, "end": END, "sources": CAPTION_SOURCES, "segments": SEG, "frames": len(fs)},
              open(os.path.join(OUT, "edit_list.json"), "w"), indent=1)
    out = os.path.join(ROOT, MP4).replace("\\", "/"); src = OUT.replace("\\", "/")
    code = f"""
import bpy
sc = bpy.context.scene; sc.render.fps = 24; sc.frame_start = 1; sc.frame_end = {len(fs)}
sc.render.resolution_x, sc.render.resolution_y, sc.render.resolution_percentage = 1920, 1080, 100
se = sc.sequence_editor_create()
st = se.strips.new_image(name="final", filepath="{src}/frame_0001.jpg", channel=1, frame_start=1)
for i in range(2, {len(fs)} + 1): st.elements.append(f"frame_{{i:04d}}.jpg")
r = sc.render; r.image_settings.file_format = "FFMPEG"; r.ffmpeg.format = "MPEG4"; r.ffmpeg.codec = "H264"
r.ffmpeg.constant_rate_factor = "HIGH"; r.ffmpeg.ffmpeg_preset = "GOOD"; r.ffmpeg.audio_codec = "NONE"
r.use_sequencer = True; r.filepath = "{out}"; r.use_file_extension = False
bpy.ops.render.render(animation=True)
"""
    tmp = os.path.join(ROOT, "film/_final_tmp.py"); open(tmp, "w").write(code)
    blender = open(os.path.join(ROOT, "tools/blender_path.txt")).read().strip()
    rc = subprocess.run([blender, "-b", "--factory-startup", "--python", tmp]).returncode; os.remove(tmp)
    print("blender exit", rc, "->", out, os.path.exists(out) and f"{os.path.getsize(out) / 1e6:.1f} MB")
