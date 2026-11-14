"""Pack the raw float16 bakes of tools/bake_ground.py into the twin's assets (plain Python, no Blender).

    python tools/bake_pack.py            # reads runs/bake/raw, runs/bake/page_facts.json; writes demo/twin/bake/ and bake.json,
                                         # docs/figures/bake_preview_*.png

shadow_A.png / shadow_B.png  RGBA 8-bit PNG, 4 times per file (channel = time index mod 4), value/255 = sun visibility
irr_HHMM.jpg                 RGB JPEG (4:4:4, q92), value = 255 * sqrt(L / xmax); L = sky + bounce lighting in units of "radiance of a white diffuse surface"
sky_HHMM.json                512x256 float16 RGB equirectangular, deflate + base64 (same loader pattern as walk_ao.json)
"""
import base64, json, math, os, struct, sys, zlib
import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "runs", "bake", "raw"); OUT = os.path.join(ROOT, "demo", "twin", "bake"); FIG = os.path.join(ROOT, "docs", "figures")
os.makedirs(OUT, exist_ok=True); os.makedirs(FIG, exist_ok=True)
PF = json.load(open(os.path.join(ROOT, "runs", "bake", "page_facts.json")))
TIMING = json.load(open(os.path.join(RAW, "timings.json")))
M = json.load(open(os.path.join(ROOT, "demo", "twin", "walk.json"))); G = json.load(open(os.path.join(ROOT, "demo", "twin", "data.json")))["grid"]
CW, CH, CELL = M["w"], M["h"], G["cell_m"]; SP = CELL / 4
to_world = lambda gx, gy: ((gx - (G["w"] - 1) / 2) * CELL, (gy - (G["h"] - 1) / 2) * CELL)
X0, Z0 = to_world(M["ox"] - 1.5 / 4, M["oy"] - 1.5 / 4)
tag = lambda t: "%02d%02d" % (int(t), round((t % 1) * 60))
ld = lambda n: np.load(os.path.join(RAW, n + ".npy")).astype(np.float32)

slots = []; shadow_imgs = {}
for k, s in enumerate(PF["sun"]):
    t = tag(s["lmst"]); e = {"lmst": s["lmst"], "label": t[:2] + ":" + t[2:], "sun_az_deg": s["az"], "sun_el_deg": s["el"], "ls_deg": s["ls"], "baked": os.path.exists(os.path.join(RAW, "shadow_" + t + ".npy"))}
    if e["baked"]:
        sh = np.clip(ld("shadow_" + t), 0, 1); H, W = sh.shape
        g = k // 4; shadow_imgs.setdefault(g, np.zeros((H, W, 4), np.uint8))[..., k % 4] = np.round(sh * 255).astype(np.uint8)
        e["shadow"] = {"file": "shadow_%s.png" % "AB"[g], "channel": "rgba"[k % 4], "mean_visibility": float(sh.mean())}
        irr = ld("irr_" + t); xmax = float(np.percentile(irr, 99.99) * 1.05); enc = np.round(np.sqrt(np.clip(irr / xmax, 0, 1)) * 255).astype(np.uint8)
        Image.fromarray(enc, "RGB").save(os.path.join(OUT, "irr_%s.jpg" % t), quality=92, subsampling=0)
        e["irr"] = {"file": "irr_%s.jpg" % t, "xmax": xmax, "mean_rgb": [float(v) for v in irr.reshape(-1, 3).mean(0)]}
        if os.path.exists(os.path.join(RAW, "sky_" + t + ".npy")):
            sky = ld("sky_" + t); raw = zlib.compress(sky.astype("<f2").tobytes(), 9)
            json.dump({"w": 512, "h": 256, "encoding": "float16 little-endian RGB, rows from zenith (top) to nadir, deflate, base64", "data": base64.b64encode(raw).decode()}, open(os.path.join(OUT, "sky_%s.json" % t), "w"))
            e["sky"] = {"file": "sky_%s.json" % t, "max": float(sky.max()), "mean_rgb": [float(v) for v in sky.reshape(-1, 3).mean(0)]}
            prev = np.clip(sky / 1.5, 0, 1) ** (1 / 2.2); Image.fromarray((prev * 255).astype(np.uint8)).save(os.path.join(FIG, "bake_sky_%s.png" % t))
        tm = TIMING.get(t, {}); e["timing_s"] = {k_: round(v, 1) for k_, v in tm.items() if k_.endswith("_s")}
        # preview: shadow + irradiance, downsampled
        pv = np.concatenate([np.repeat(sh[..., None], 3, 2), np.clip(irr / xmax, 0, 1) ** 0.5], 1)
        Image.fromarray((pv * 255).astype(np.uint8)).resize((pv.shape[1] // 4, pv.shape[0] // 4), Image.LANCZOS).save(os.path.join(FIG, "bake_preview_%s.png" % t))
    slots.append(e)
for g, a in shadow_imgs.items(): Image.fromarray(a, "RGBA").save(os.path.join(OUT, "shadow_%s.png" % "AB"[g]), optimize=True)

# light model constants as the film (tools/f1_blender_scene.py): sun strength S at the slot, from the raw timing file's script run; recomputed here for the record
tau_j = json.load(open(os.path.join(ROOT, "demo", "twin", "tau_climatology.json")))
def tau_at(ls):
    x = ((ls - 5.0) % 360.0) / 10.0; i0 = int(x) % 36; f = x - math.floor(x); return tau_j["tau880"][i0] * (1 - f) + tau_j["tau880"][(i0 + 1) % 36] * f
for e in slots:
    se = math.sin(math.radians(e["sun_el_deg"])); m = min(1 / max(se, 1e-3), 10); tr = math.exp(-tau_at(e["ls_deg"]) * m)
    e.update(tau880=tau_at(e["ls_deg"]), beam_transmission=tr, sun_strength_blender=6.5 * tr, sky_strength_blender=0.9 * 0.65 * (1 - tr) * se / (0.221 / 0.9))

refs = {}
for p in os.listdir(FIG):
    if p.startswith("bake_ref_"): refs.setdefault(p.split("_")[2], []).append(p)
J = {
  "version": 1, "sol": 4600, "site": "Gale crater walk corridor (twin walk.json)",
  "what": "Cycles bake of sun visibility and sky+bounce lighting on the twin's 1 m corridor terrain with HiRISE boulders (rocks.json); see docs/bake_ground.md",
  "texture": {"size": [CW * 2, CH * 2], "texels_per_cell": 2, "texel_m": SP / 2, "cell_m": SP, "corridor_cells": [CW, CH],
              "rect_world": [X0 - SP / 2, Z0 - SP / 2, CW * SP, CH * SP],
              "rect_note": "world x, z, width, height of the texture rectangle (the cell-edge rectangle, same as aoRect in twin.html: c2w(-0.5,-0.5) and CW*CELL/4); u = (x - rect.x)/rect.w, v = (z - rect.z)/rect.h with flipY=false (image row 0 = north edge = smallest world z)",
              "filter": "linear; texels are centred at rect + (k + 0.5) * texel_m"},
  "units": {"lighting": "L = radiance leaving a WHITE diffuse surface (albedo 1) in Blender film units. Surface colour = albedo * (S/pi * max(n.l,0) * shadow + irr). S = sun_strength_blender of the slot (Blender sun strength, the film's value). Verified in Blender: sun direct bake = S * cos / pi (ratio 0.3183).",
            "sun_az": "degrees clockwise from north; twin sunDir(lmst, 4600) evaluated in the page (tools/bake_poses.py), el in degrees",
            "twin_sun_vector": "(cos el sin az, sin el, -cos el cos az) in twin world axes (x east, y up, z south)"},
  "encoding": {"shadow": "RGBA PNG, 4 times per file; channel = index of the time in `times` mod 4 (A: 08,10,12,14, B: 16 in R); visibility = value/255 (sun disc fraction visible, penumbra from the real disc size, no cosine)",
               "irr": "RGB JPEG; L = xmax * (value/255)^2 per channel; gamma 2 (sqrt) encoding; xmax per slot below",
               "sky": "JSON {w,h,data}: data = base64(deflate(float16 LE RGB)); equirectangular 512x256, column u: azimuth = (u - 0.5) * 360 deg from north, + towards east; row v from the top: elevation = 90 - 180 v; radiance L in the same units, sun disc not included (use the directional light)"},
  "times": slots,
  "poses": [{"name": n, "frac_of_route": p["frac"], "pos_world": p["pos"], "yaw_rad": p["yaw"], "pitch_rad": PF["pitch_default"], "eye_height_m": 1.7, "fov_deg_vertical": PF["fov"], "aspect": 16 / 9,
             "convention": "twin walk camera: position = route point + (0, 1.7, 0); lookAt(p + (sin yaw cos pitch, sin pitch, -cos yaw cos pitch) * 10); yaw = atan2(dx, -dz) of the route 10 m ahead; world x east, y up, z south; THREE.PerspectiveCamera fov = vertical"}
            for n, p in zip(["a_start", "b_mid", "c_late"], PF["poses"])],
  "reference_renders": {k: sorted(v) for k, v in refs.items()},
  "provenance": {"script": "tools/bake_ground.py (Blender Cycles), tools/bake_pack.py, tools/bake_poses.py, tools/bake_ref.py", "terrain": "demo/twin/walk.json + walk_z.json (heights minus the twin's zMean), 1 m corridor padded by one cell; 4 m context from data.json lowered 0.6 m and cut under the corridor; flat far plane",
                 "boulders": "112 from demo/twin/rocks.json: ellipsoids as in twin.html (d_m, h_m, same noise, spin and offset); pebbles and Navcam 3D scans are NOT baked",
                 "sky_sun_model": "the film's (tools/f1_blender_scene.py): sun strength 6.5*exp(-tau m), sky 0.9*0.65*(1-exp(-tau m))*sin(el)/(0.221/0.9), tau880 from tau_climatology.json at the slot's Ls, sun disc 0.5332/rAU deg, same sky gradient and blue aureole; no haze volume",
                 "ground_albedo_for_bounce": [0.28, 0.17, 0.10], "rock_albedo": [0.20, 0.135, 0.095], "far_albedo": [0.20, 0.10, 0.05],
                 "bounces": "diffuse 3", "timings_s": TIMING},
}
json.dump(J, open(os.path.join(OUT, "bake.json"), "w"), indent=1)
tot = sum(os.path.getsize(os.path.join(OUT, f)) for f in os.listdir(OUT))
for f in sorted(os.listdir(OUT)): print("%-20s %8.2f MB" % (f, os.path.getsize(os.path.join(OUT, f)) / 1e6))
print("total %.2f MB" % (tot / 1e6))
