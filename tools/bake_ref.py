"""Reference Cycles frames of the FILM scene at the bake's walk poses (runs INSIDE Blender, GPU):

    python tools/run_blender.py bake-ref tools/bake_ref.py --times 10,16 [--spp 48]

Opens film/marswalk_scene_v3.blend (the film's terrain with Navcam ground textures, HiRISE boulders, pebbles, haze), hides the suit, route
markers, rover and Navcam scans (the twin's walk view has the scans off by default), sets the sun and sky for the slot with the same model as
tools/bake_ground.py, puts a camera at each pose of runs/bake/page_facts.json (twin walk camera: eye 1.7 m, vertical fov 60, pitch -0.1 rad)
and renders 960x540 -> docs/figures/bake_ref_<HHMM>_<pose>.png. The film uses the same corridor (1008 x 1302 cells of 1.0117 m, same HiRISE window),
so a twin cell (i, j) is film cell (i, j): x = corr_x0 + (i+0.5) S, y = corr_y0 - (j+0.5) S, z from corridor_z.npy.
"""
import json, math, os, sys, time
import numpy as np
import bpy
from mathutils import Vector

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
A = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
def opt(n, d, c=str): return c(A[A.index(n) + 1]) if n in A else d
TIMES = [float(t) for t in opt("--times", "10,16").split(",")]; SPP = opt("--spp", 48, int)
PF = json.load(open(os.path.join(ROOT, "runs", "bake", "page_facts.json")))
FIG = os.path.join(ROOT, "docs", "figures"); os.makedirs(FIG, exist_ok=True)
SC = json.load(open(os.path.join(ROOT, "film", "f1_data", "scene.json"))); ZC = np.load(os.path.join(ROOT, "film", "f1_data", "corridor_z.npy")); S = SC["S"]

# twin geometry (same as bake_ground.py)
import base64
Dj = json.load(open(os.path.join(ROOT, "demo", "twin", "data.json"))); G = Dj["grid"]; GW, GH, CELL = G["w"], G["h"], G["cell_m"]
M = json.load(open(os.path.join(ROOT, "demo", "twin", "walk.json"))); SP = CELL / 4
to_world = lambda gx, gy: ((gx - (GW - 1) / 2) * CELL, (gy - (GH - 1) / 2) * CELL)
X0, Z0 = to_world(M["ox"] - 1.5 / 4, M["oy"] - 1.5 / 4)

bpy.ops.wm.open_mainfile(filepath=os.path.join(ROOT, "film", "marswalk_scene_v3.blend"))
sc = bpy.context.scene
def hide(o): o.hide_render = True; o.hide_viewport = True
for o in bpy.data.objects:
    if o.type == "CAMERA" or o.name.startswith(("Route_", "NoGo_", "PLSS", "MarkIII", "Armature", "Astronaut", "MSL", "Curiosity", "Mesh_0", "Cam_", "Scan_")): hide(o)
# static lighting: drop the shot keyframes, then drive the film's own nodes
for idb in list(bpy.data.lights) + list(bpy.data.worlds) + list(bpy.data.materials):
    nt = getattr(idb, "node_tree", None)
    if nt and nt.animation_data: nt.animation_data_clear()
    if idb.animation_data: idb.animation_data_clear()
W = bpy.data.worlds["MarsSky"]; nt = W.node_tree
sd, bw, bg = nt.nodes["SunDir"], nt.nodes["BlueW"], nt.nodes["SkyBG"]
dust = [m for m in bpy.data.materials if m.use_nodes and "Dust" in m.node_tree.nodes][0].node_tree.nodes["Dust"]
sun9, sun16 = bpy.data.objects["Sun_LMST09"], bpy.data.objects["Sun_LMST16"]; sun16.data.energy = 0.0

TAUJ = json.load(open(os.path.join(ROOT, "demo", "twin", "tau_climatology.json")))
def tau_at(ls):
    x = ((ls - 5.0) % 360.0) / 10.0; i0 = int(x) % 36; f = x - math.floor(x); return TAUJ["tau880"][i0] * (1 - f) + TAUJ["tau880"][(i0 + 1) % 36] * f
def set_light(lm):
    s = [q for q in PF["sun"] if abs(q["lmst"] - lm) < 1e-6][0]; el, az, ls = s["el"], s["az"], s["ls"]
    tau = tau_at(ls); se = math.sin(math.radians(el)); m = min(1 / max(se, 1e-3), 10); tr = math.exp(-tau * m); rau = 1.52368 * (1 - 0.0934 ** 2) / (1 + 0.0934 * math.cos(math.radians(ls - 251)))
    e, a = math.radians(el), math.radians(az); v = Vector((math.cos(e) * math.sin(a), math.cos(e) * math.cos(a), math.sin(e)))
    sun9.data.energy = 6.5 * tr; sun9.data.angle = math.radians(0.5332 / rau); sun9.rotation_euler = (-v).to_track_quat("-Z", "Y").to_euler()
    for k in range(3): sd.inputs[k].default_value = v[k]
    bw.outputs[0].default_value = min(1.0, (0.35 + 0.5 * max(0.0, min(1.0, 1.0 - el / 45.0))) * math.sqrt(min(tau / 0.6, 2.0)))
    bg.inputs["Strength"].default_value = 0.9 * 0.65 * (1 - tr) * se / (0.221 / 0.9) * 1.0 / 1.0 * (1.0)
    dust.inputs["Density"].default_value = tau / 11100.0
    return el, az

def film_xyz(wx, wz, up):
    i, j = (wx - X0) / SP, (wz - Z0) / SP
    fx = min(max(i, 0), ZC.shape[1] - 1.001); fy = min(max(j, 0), ZC.shape[0] - 1.001); i0, j0 = int(fx), int(fy); a, b = fx - i0, fy - j0
    z = (1 - a) * (1 - b) * ZC[j0, i0] + a * (1 - b) * ZC[j0, i0 + 1] + (1 - a) * b * ZC[j0 + 1, i0] + a * b * ZC[j0 + 1, i0 + 1]
    return Vector((SC["corr_x0"] + (i + 0.5) * S, SC["corr_y0"] - (j + 0.5) * S, float(z) + up))

import blender_gpu
print("GPU:", blender_gpu.enable_optix())
cy = sc.cycles; cy.samples = SPP; cy.use_denoising = True; cy.denoiser = "OPTIX"; cy.use_adaptive_sampling = False
sc.render.resolution_x, sc.render.resolution_y, sc.render.resolution_percentage = 960, 540, 100
sc.render.image_settings.file_format = "PNG"; sc.render.image_settings.color_mode = "RGB"; sc.render.use_motion_blur = False
cam = bpy.data.cameras.new("bake_ref"); cam.sensor_fit = "VERTICAL"; cam.sensor_height = 24.0
cam.lens = 12.0 / math.tan(math.radians(PF["fov"]) / 2); cam.clip_start = 0.1; cam.clip_end = 40000
co = bpy.data.objects.new("bake_ref", cam); sc.collection.objects.link(co); sc.camera = co
names = ["a_start", "b_mid", "c_late"]
for lm in TIMES:
    el, az = set_light(lm); tag = "%02d%02d" % (int(lm), round((lm % 1) * 60)); print("slot", tag, "el %.2f az %.2f" % (el, az))
    for n, p in zip(names, PF["poses"]):
        yaw, pitch = p["yaw"], PF["pitch_default"]
        co.location = film_xyz(p["pos"][0], p["pos"][2], 1.7)
        d = Vector((math.sin(yaw) * math.cos(pitch), math.cos(yaw) * math.cos(pitch), math.sin(pitch)))     # twin (sin yaw cp, sin p, -cos yaw cp) in Blender axes
        co.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
        sc.render.filepath = os.path.join(FIG, "bake_ref_%s_%s.png" % (tag, n)); t0 = time.time()
        bpy.ops.render.render(write_still=True); print("rendered", sc.render.filepath, "%.0f s" % (time.time() - t0), flush=True)
