"""Bake sun visibility and sky+bounce irradiance for the twin's 1 m walk corridor (runs INSIDE Blender, Cycles on the GPU).

    python tools/run_blender.py bake-ground tools/bake_ground.py --times 10 [--spp-shadow 128 --spp-irr 192 --texel 2 --test --calib]

Run one slot per call so the GPU lock is released between slots (tools/run_blender.py holds it for one process).
Needs runs/bake/page_facts.json (python tools/bake_poses.py: the page's own sunDir for sol 4600 and the walk poses).
Writes float16 .npy to runs/bake/raw/ (shadow_HHMM.npy HxW, irr_HHMM.npy HxWx3, sky_HHMM.npy 256x512x3, timings.json);
tools/bake_pack.py turns those into demo/twin/bake/* and bake.json.

Geometry = the twin's corridor, cell for cell: vertex (i,j) at the twin world position c2w(i,j) = toWorld(ox+(i-1.5)/4, oy+(j-1.5)/4),
height WZ[j*CW+i] - zMean (walk_z.json, data.json), padded by one cell. Blender axes from twin world (x, y up, z south): X = x, Y = -z, Z = y.
Texel grid: TEXEL texels per corridor cell (default 2 = 0.506 m); texture covers the cell-edge rectangle [-0.5, CW-0.5] x [-0.5, CH-0.5] cells,
image row 0 = north edge (smallest world z), so texel (r,c) centre in cells = ((c+0.5)/TEXEL - 0.5, (r+0.5)/TEXEL - 0.5) from cell (0,0).
"""
import base64, json, math, os, sys, time
import numpy as np
import bpy, bmesh

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__))) if "__file__" in globals() else os.getcwd()
sys.path.insert(0, os.path.join(ROOT, "tools"))
A = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
def opt(name, default, cast=str):
    return cast(A[A.index(name) + 1]) if name in A else default
TIMES = [float(t) for t in opt("--times", "10").split(",")]
TEXEL = opt("--texel", 2, int)                       # texels per corridor cell (2 = 0.5 m)
SPP_SH, SPP_IR = opt("--spp-shadow", 128, int), opt("--spp-irr", 192, int)
SPP_SKY = opt("--spp-sky", 128, int)
TEST, CALIB, NOSKY = "--test" in A, "--calib" in A, "--nosky" in A
RAW = os.path.join(ROOT, "runs", "bake", "raw" + ("_test" if TEST else "")); os.makedirs(RAW, exist_ok=True)
PF = json.load(open(os.path.join(ROOT, "runs", "bake", "page_facts.json")))
TW_DIR = os.path.join(ROOT, "demo", "twin")
SOL = 4600

def stamp(msg): print("[bake %s] %s" % (time.strftime("%H:%M:%S"), msg), flush=True)

# ------------------------------------------------------------------ twin data
def b64u16(s): return np.frombuffer(base64.b64decode(s), dtype="<u2")
Dj = json.load(open(os.path.join(TW_DIR, "data.json"))); G = Dj["grid"]; GW, GH, CELL = G["w"], G["h"], G["cell_m"]
Zc = (G["zmin"] + b64u16(Dj["z"]).astype(np.float64) * G["zscale"]).reshape(GH, GW); zMean = float(Zc.mean())
M = json.load(open(os.path.join(TW_DIR, "walk.json"))); CW, CH = M["w"], M["h"]
WZ = (M["zmin"] + b64u16(json.load(open(os.path.join(TW_DIR, "walk_z.json")))["z"]).astype(np.float64) * M["zscale"]).reshape(CH, CW)
SP = CELL / 4.0
def to_world(gx, gy): return (gx - (GW - 1) / 2) * CELL, (gy - (GH - 1) / 2) * CELL
def c2w(i, j): return to_world(M["ox"] + (i - 1.5) / 4, M["oy"] + (j - 1.5) / 4)
X0, Z0 = c2w(0, 0)
def ground_y(x, z):                                  # twin groundY inside the corridor
    i, j = (x - X0) / SP, (z - Z0) / SP
    i = min(max(i, 0), CW - 1.001); j = min(max(j, 0), CH - 1.001); i0, j0 = int(i), int(j); fx, fy = i - i0, j - j0
    return (WZ[j0, i0] * (1 - fx) * (1 - fy) + WZ[j0, i0 + 1] * fx * (1 - fy) + WZ[j0 + 1, i0] * (1 - fx) * fy + WZ[j0 + 1, i0 + 1] * fx * fy) - zMean
stamp("twin data: corridor %dx%d, cell %.4f m, world origin of cell (0,0) = (%.2f, %.2f), zMean %.2f" % (CW, CH, SP, X0, Z0, zMean))

# ------------------------------------------------------------------ scene
bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene; sc.name = "BAKE"
ALB_GROUND, ALB_ROCK, ALB_FAR = (0.28, 0.17, 0.10), (0.20, 0.135, 0.095), (0.20, 0.10, 0.05)   # linear; ground ~ Mars bright terrain, rock/far as the film

def diffuse_mat(name, rgb):
    m = bpy.data.materials.new(name); m.use_nodes = True; nt = m.node_tree; nt.nodes.clear()
    d = nt.nodes.new("ShaderNodeBsdfDiffuse"); d.inputs["Color"].default_value = (*rgb, 1); o = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(d.outputs[0], o.inputs["Surface"]); return m

def quad_mesh(name, V, nx, ny, uv=None, drop=None):
    """V: (ny*nx, 3) vertices, row-major; quads CCW seen from above (+Z). uv: (ny*nx, 2) or None."""
    jj, ii = np.mgrid[0:ny - 1, 0:nx - 1]; idx = np.arange(nx * ny).reshape(ny, nx)
    q = np.stack([idx[:-1, :-1], idx[1:, :-1], idx[1:, 1:], idx[:-1, 1:]], -1)
    # Blender Y = -world z: row j (world z increasing southwards) runs towards -Y, so (j, i) -> (j+1, i) -> (j+1, i+1) -> (j, i+1) is CCW from +Z
    if drop is not None: q = q[~drop]
    q = q.reshape(-1, 4)
    me = bpy.data.meshes.new(name)
    me.vertices.add(len(V)); me.vertices.foreach_set("co", V.astype(np.float32).ravel())
    me.loops.add(len(q) * 4); me.loops.foreach_set("vertex_index", q.ravel().astype(np.int32))
    me.polygons.add(len(q)); me.polygons.foreach_set("loop_start", (np.arange(len(q)) * 4).astype(np.int32))
    me.polygons.foreach_set("use_smooth", np.ones(len(q), dtype=bool)); me.update(calc_edges=True)
    if uv is not None:
        l = me.uv_layers.new(name="UV"); l.data.foreach_set("uv", uv.astype(np.float32)[q.ravel()].ravel())
    ob = bpy.data.objects.new(name, me); sc.collection.objects.link(ob); return ob

# corridor, padded by one cell on every side (heights clamped), so the texture rectangle [-0.5, CW-0.5] is fully covered
PAD = 1
if TEST:                                             # small crop for quick tests: cells [ci0, ci0+tw) x [cj0, cj0+th) around the middle pose
    _p = PF["poses"][1]["pos"]; ci0, cj0, tw, th = int((_p[0] - X0) / SP) - 80, int((_p[2] - Z0) / SP) - 80, 160, 160
else:
    ci0, cj0, tw, th = 0, 0, CW, CH
ii = np.arange(ci0 - PAD, ci0 + tw + PAD); jj = np.arange(cj0 - PAD, cj0 + th + PAD)
Zp = WZ[np.clip(jj, 0, CH - 1)[:, None], np.clip(ii, 0, CW - 1)[None, :]] - zMean
Ix, Jx = np.meshgrid(ii, jj)
V = np.stack([X0 + Ix * SP, -(Z0 + Jx * SP), Zp], -1).reshape(-1, 3)
uv = np.stack([(Ix - ci0 + 0.5) / tw, 1.0 - (Jx - cj0 + 0.5) / th], -1).reshape(-1, 2)   # texture rect = the cell-edge rectangle of the crop
terrain = quad_mesh("Terrain_corridor_1m", V, len(ii), len(jj), uv)
mat_t = diffuse_mat("mat_ground", ALB_GROUND); terrain.data.materials.append(mat_t)
stamp("corridor mesh %d x %d vertices" % (len(ii), len(jj)))

# 4 m context around the corridor (shadows and bounce from the surrounding terrain; lowered 0.6 m under the corridor like the film), cut where the corridor is
gx, gy = np.meshgrid(np.arange(GW), np.arange(GH)); cx, cz = to_world(gx, gy)
inside = (cx >= X0 + (ci0 - PAD) * SP) & (cx <= X0 + (ci0 + tw + PAD - 1) * SP) & (cz >= Z0 + (cj0 - PAD) * SP) & (cz <= Z0 + (cj0 + th + PAD - 1) * SP)
drop = inside[:-1, :-1] & inside[1:, :-1] & inside[1:, 1:] & inside[:-1, 1:]
if TEST:                                             # keep only a 1.5 km square around the crop in test mode
    near = (np.abs(cx - X0 - (ci0 + tw / 2) * SP) < 800) & (np.abs(cz - Z0 - (cj0 + th / 2) * SP) < 800)
    drop = drop | ~(near[:-1, :-1] & near[1:, :-1] & near[1:, 1:] & near[:-1, 1:])
ctx = quad_mesh("Terrain_context_4m", np.stack([cx, -cz, Zc - zMean - 0.6], -1).reshape(-1, 3), GW, GH, None, drop)
ctx.data.materials.append(mat_t)
bpy.ops.mesh.primitive_plane_add(size=300000, location=(0, 0, float(Zc.min() - zMean) - 2)); far = bpy.context.active_object; far.name = "Far_ground"
far.data.materials.append(diffuse_mat("mat_far", ALB_FAR))

# boulders from rocks.json, as the twin's instanced rocks (same size, position, spin, noise; 640-vertex icospheres instead of 252)
bm = bmesh.new(); bmesh.ops.create_icosphere(bm, subdivisions=3, radius=1.0)
UV_ = np.array([v.co[:] for v in bm.verts]); UF_ = np.array([[v.index for v in f.verts] for f in bm.faces]); bm.free()
RJ = json.load(open(os.path.join(TW_DIR, "rocks.json")))["rocks"]
def rock_geometry(k, rk):
    v = UV_.copy(); x, y, z = v[:, 0], v[:, 1], v[:, 2]    # the sphere's own (x, y, z) = twin three.js axes (y up)
    n = 0.8 + 0.18 * np.sin(x * 2.3 + z * 1.7) * np.cos(y * 2.9) + 0.07 * np.sin(x * 9.1 - y * 7.3 + z * 8.7) + 0.03 * np.sin(x * 23.0 + z * 19.0)
    p = np.stack([x * n, y * n * np.where(y < 0, 0.5, 1.0), z * n], 1)
    wx, wz = c2w(rk["col"] - 336 + 0.5, rk["row"] - 577 + 0.5); gy_ = ground_y(wx, wz) + rk["h_m"] * 0.25
    s = np.array([rk["d_m"] / 2, max(0.4, rk["h_m"] * 0.6), rk["d_m"] / 2 * (0.75 + (k % 5) * 0.08)]); p = p * s
    th_ = (k * 2.399) % 6.28; c, sn = math.cos(th_), math.sin(th_)
    p = np.stack([p[:, 0] * c + p[:, 2] * sn, p[:, 1], -p[:, 0] * sn + p[:, 2] * c], 1)         # three.js rotation.y = th
    return np.stack([wx + p[:, 0], -(wz + p[:, 2]), gy_ + p[:, 1]], 1)                           # -> Blender axes
Vr, Fr, off = [], [], 0; nrock = 0
for k, rk in enumerate(RJ):
    wx, wz = c2w(rk["col"] - 336 + 0.5, rk["row"] - 577 + 0.5)
    if TEST and not (abs(wx - X0 - (ci0 + tw / 2) * SP) < 400 and abs(wz - Z0 - (cj0 + th / 2) * SP) < 400): continue
    Vr.append(rock_geometry(k, rk)); Fr.append(UF_ + off); off += len(UV_); nrock += 1
rv = np.concatenate(Vr); rf = np.concatenate(Fr)
me = bpy.data.meshes.new("Boulders"); me.vertices.add(len(rv)); me.vertices.foreach_set("co", rv.astype(np.float32).ravel())
me.loops.add(len(rf) * 3); me.loops.foreach_set("vertex_index", rf.ravel().astype(np.int32))
me.polygons.add(len(rf)); me.polygons.foreach_set("loop_start", (np.arange(len(rf)) * 3).astype(np.int32)); me.update(calc_edges=True)
rocks = bpy.data.objects.new("Boulders", me); sc.collection.objects.link(rocks); me.materials.append(diffuse_mat("mat_rock", ALB_ROCK))
for p_ in me.polygons: p_.use_smooth = True
stamp("%d boulders" % nrock)

# ------------------------------------------------------------------ sky, sun (the film's model: tools/f1_blender_scene.py)
W = bpy.data.worlds.new("MarsSky"); sc.world = W; W.use_nodes = True
nt = W.node_tree; nt.nodes.clear(); L = nt.links
def N(t, **kw):
    n = nt.nodes.new(t)
    for k, v in kw.items(): setattr(n, k, v)
    return n
tc = N("ShaderNodeTexCoord"); nm = N("ShaderNodeVectorMath", operation="NORMALIZE"); L.new(tc.outputs["Generated"], nm.inputs[0])
sep = N("ShaderNodeSeparateXYZ"); L.new(nm.outputs[0], sep.inputs[0])
upr = N("ShaderNodeMapRange"); upr.inputs[1].default_value = -0.05; upr.inputs[2].default_value = 0.75; L.new(sep.outputs["Z"], upr.inputs[0])
cr = N("ShaderNodeValToRGB"); cr.color_ramp.elements[0].color = (0.62, 0.36, 0.17, 1); cr.color_ramp.elements[1].color = (0.30, 0.19, 0.12, 1); L.new(upr.outputs[0], cr.inputs[0])
sd = N("ShaderNodeCombineXYZ"); dot = N("ShaderNodeVectorMath", operation="DOT_PRODUCT"); L.new(nm.outputs[0], dot.inputs[0]); L.new(sd.outputs[0], dot.inputs[1])
gl = N("ShaderNodeMapRange", clamp=True); gl.inputs[1].default_value = 0.55; gl.inputs[2].default_value = 1.0; L.new(dot.outputs["Value"], gl.inputs[0])
pw = N("ShaderNodeMath", operation="POWER"); pw.inputs[1].default_value = 2.5; L.new(gl.outputs[0], pw.inputs[0])
bw = N("ShaderNodeValue"); mw = N("ShaderNodeMath", operation="MULTIPLY"); L.new(pw.outputs[0], mw.inputs[0]); L.new(bw.outputs[0], mw.inputs[1])
mix = N("ShaderNodeMix", data_type="RGBA"); mix.inputs[7].default_value = (0.38, 0.52, 0.80, 1); L.new(mw.outputs[0], mix.inputs[0]); L.new(cr.outputs[0], mix.inputs[6])
bg = N("ShaderNodeBackground"); L.new(mix.outputs[2], bg.inputs["Color"]); wo = N("ShaderNodeOutputWorld"); L.new(bg.outputs[0], wo.inputs["Surface"])

TAUJ = json.load(open(os.path.join(TW_DIR, "tau_climatology.json")))
def tau_at(ls):
    x = ((ls - 5.0) % 360.0) / 10.0; i0 = int(x) % 36; f = x - math.floor(x)
    return TAUJ["tau880"][i0] * (1 - f) + TAUJ["tau880"][(i0 + 1) % 36] * f
KS_B, K_DIFF, SKY_REF = 6.5, 0.65, 0.221 / 0.9           # as the film: sun strength at tau 0; sky term reference
def light_for(lmst):
    s = min(PF["sun"], key=lambda q: abs(q["lmst"] - lmst)); assert abs(s["lmst"] - lmst) < 1e-6, "run tools/bake_poses.py for this LMST"
    el, az, ls = s["el"], s["az"], s["ls"]; tau = tau_at(ls); se = math.sin(math.radians(el)); m = min(1.0 / max(se, 1e-3), 10.0); tr = math.exp(-tau * m)
    rau = 1.52368 * (1 - 0.0934 ** 2) / (1 + 0.0934 * math.cos(math.radians(ls - 251)))
    e, a = math.radians(el), math.radians(az)
    return dict(lmst=lmst, el=el, az=az, ls=ls, tau=tau, airmass=m, beam=tr, sun=KS_B * tr, sky=K_DIFF * (1 - tr) * se / SKY_REF, disc_deg=0.5332 / rau,
                vec=(math.cos(e) * math.sin(a), math.cos(e) * math.cos(a), math.sin(e)),
                blue=min(1.0, (0.35 + 0.5 * max(0.0, min(1.0, 1.0 - el / 45.0))) * math.sqrt(min(tau / 0.6, 2.0))))
ld = bpy.data.lights.new("Sun", "SUN"); ld.color = (1.0, 0.86, 0.72); sun = bpy.data.objects.new("Sun", ld); sc.collection.objects.link(sun)
def set_slot(Lt, sun_on=True, sky_on=True):
    v = Lt["vec"]
    for k in range(3): sd.inputs[k].default_value = v[k]
    bw.outputs[0].default_value = Lt["blue"]; bg.inputs["Strength"].default_value = 0.9 * Lt["sky"] if sky_on else 0.0
    ld.energy = Lt["sun"] if sun_on else 0.0; ld.angle = math.radians(Lt["disc_deg"])
    from mathutils import Vector
    sun.rotation_euler = (-Vector(v)).to_track_quat("-Z", "Y").to_euler()

# ------------------------------------------------------------------ cycles
sc.render.engine = "CYCLES"
import blender_gpu
try: stamp("GPU: %s" % blender_gpu.enable_optix())
except Exception as ex: stamp("OptiX not available (%s), CPU" % ex)
cy = sc.cycles; cy.use_denoising = False; cy.use_adaptive_sampling = False; cy.max_bounces = 3; cy.diffuse_bounces = 3; cy.glossy_bounces = 0
cy.transmission_bounces = 0; cy.volume_bounces = 0; cy.transparent_max_bounces = 0; cy.caustics_reflective = False; cy.caustics_refractive = False; cy.sample_clamp_indirect = 0.0
TWd, THd = tw * TEXEL, th * TEXEL
img = bpy.data.images.new("bake_img", TWd, THd, alpha=False, float_buffer=True); img.colorspace_settings.name = "Non-Color"
nodes = mat_t.node_tree.nodes; tn = nodes.new("ShaderNodeTexImage"); tn.image = img
for n in nodes: n.select = False
tn.select = True; nodes.active = tn
for o in bpy.context.view_layer.objects: o.select_set(False)
terrain.select_set(True); bpy.context.view_layer.objects.active = terrain
ctx.hide_render = False

def bake(kind, spp, pass_filter=None):
    cy.samples = spp; t0 = time.time()
    kw = dict(type=kind, margin=2, margin_type="EXTEND", use_clear=True)
    if pass_filter: kw["pass_filter"] = pass_filter
    bpy.ops.object.bake(**kw)
    buf = np.empty(TWd * THd * 4, np.float32); img.pixels.foreach_get(buf)
    return buf.reshape(THd, TWd, 4)[::-1, :, :3].copy(), time.time() - t0                  # row 0 = north

def save16(name, a): np.save(os.path.join(RAW, name + ".npy"), a.astype(np.float16))
TJ = os.path.join(RAW, "timings.json"); timings = json.load(open(TJ)) if os.path.exists(TJ) else {}

for lm in TIMES:
    tag = "%02d%02d" % (int(lm), round((lm % 1) * 60)); Lt = light_for(lm); T0 = time.time(); tm = {"texel_px": [TWd, THd], "spp_shadow": SPP_SH, "spp_irr": SPP_IR}
    stamp("slot %s: el %.2f az %.2f tau %.3f sun %.3f sky %.3f" % (tag, Lt["el"], Lt["az"], Lt["tau"], Lt["sun"], Lt["sky"]))
    # (a) sun visibility: only the sun lamp, SHADOW bake (1 = lit by the whole disc, 0 = fully in shadow; no cosine term)
    set_slot(Lt, sun_on=True, sky_on=False)
    sh, tm["shadow_s"] = bake("SHADOW", SPP_SH); stamp("shadow %.0f s, mean %.3f min %.3f max %.3f" % (tm["shadow_s"], sh[..., 0].mean(), sh[..., 0].min(), sh[..., 0].max()))
    save16("shadow_" + tag, sh[..., 0])
    # (b) sky + bounce: sky light with all its bounces (sun off) plus the bounces of the sun light alone (sky off, INDIRECT only)
    set_slot(Lt, sun_on=False, sky_on=True)
    ir_sky, tm["irr_sky_s"] = bake("DIFFUSE", SPP_IR, {"DIRECT", "INDIRECT"})
    set_slot(Lt, sun_on=True, sky_on=False)
    ir_sun, tm["irr_sunbounce_s"] = bake("DIFFUSE", SPP_IR, {"INDIRECT"})
    irr = ir_sky + ir_sun
    stamp("irradiance %.0f + %.0f s; sky mean %s, sun-bounce mean %s" % (tm["irr_sky_s"], tm["irr_sunbounce_s"], ir_sky.reshape(-1, 3).mean(0).round(4), ir_sun.reshape(-1, 3).mean(0).round(4)))
    save16("irr_" + tag, irr); save16("irr_sky_" + tag, ir_sky); save16("irr_sunbounce_" + tag, ir_sun)
    if CALIB:                                        # sun direct, world off: ratio to S * cos(incidence) fixes the unit of the sun term
        set_slot(Lt, sun_on=True, sky_on=False)
        sd_, _ = bake("DIFFUSE", 64, {"DIRECT"}); save16("sundirect_" + tag, sd_)
        zc = Zp  # normals from the padded height grid, texel -> cell
        gy_, gx_ = np.gradient(zc, SP)               # dz/d(row cells), dz/d(col): Blender Y = -z, so dz/dY = -dz/drow
        nx_, ny_, nz_ = -gx_, gy_, np.ones_like(gx_); nn = np.sqrt(nx_ ** 2 + ny_ ** 2 + nz_ ** 2); v = Lt["vec"]
        cosi = np.clip((nx_ * v[0] + ny_ * v[1] + nz_ * v[2]) / nn, 0, 1)[PAD:-PAD, PAD:-PAD]
        cosi_t = np.repeat(np.repeat(cosi, TEXEL, 0), TEXEL, 1); ok = (sh[..., 0] > 0.999) & (cosi_t > 0.3)
        ratio = sd_[..., 0][ok] / (Lt["sun"] * cosi_t[ok]); stamp("CALIB sun direct / (S cos) median %.4f p10 %.4f p90 %.4f (S=%.3f)" % (np.median(ratio), np.percentile(ratio, 10), np.percentile(ratio, 90), Lt["sun"]))
        tm["sun_unit_ratio"] = float(np.median(ratio))
    # sky environment for lighting the suit and rover: equirectangular from 1.7 m above the middle route pose, sun lamp on (invisible to the camera)
    if not NOSKY:
        set_slot(Lt, sun_on=True, sky_on=True)
        pm = PF["poses"][1]; px_, pz_ = pm["pos"][0], pm["pos"][2]
        cam = bpy.data.cameras.new("env"); cam.type = "PANO"
        try: cam.panorama_type = "EQUIRECTANGULAR"
        except Exception: cam.cycles.panorama_type = "EQUIRECTANGULAR"
        co = bpy.data.objects.new("env", cam); sc.collection.objects.link(co); sc.camera = co
        co.location = (px_, -pz_, ground_y(px_, pz_) + 1.7) if not TEST else (X0 + (ci0 + tw / 2) * SP, -(Z0 + (cj0 + th / 2) * SP), 0.0)
        if TEST: co.location[2] = ground_y(co.location[0], -co.location[1]) + 1.7
        co.rotation_euler = (math.radians(90), 0, 0)          # looks along +Y (north), image centre = north, right = east, top = zenith
        sc.render.resolution_x, sc.render.resolution_y, sc.render.resolution_percentage = 512, 256, 100
        cy.samples = SPP_SKY; cy.use_denoising = True; cy.denoiser = "OPTIX" if True else "OPENIMAGEDENOISE"
        sc.render.image_settings.file_format = "OPEN_EXR"; sc.render.image_settings.color_depth = "32"; ex = os.path.join(RAW, "sky_%s.exr" % tag); sc.render.filepath = ex
        t0 = time.time(); bpy.ops.render.render(write_still=True); tm["sky_s"] = time.time() - t0; cy.use_denoising = False
        im = bpy.data.images.load(ex); im.colorspace_settings.name = "Non-Color"; b = np.empty(512 * 256 * 4, np.float32); im.pixels.foreach_get(b)
        save16("sky_" + tag, b.reshape(256, 512, 4)[::-1, :, :3]); bpy.data.images.remove(im); os.remove(ex)
        bpy.data.objects.remove(co); bpy.data.cameras.remove(cam); sc.camera = None
    tm["total_s"] = time.time() - T0; timings[tag] = tm; json.dump(timings, open(TJ, "w"), indent=1)
    stamp("slot %s done in %.0f s" % (tag, tm["total_s"]))
