"""F1 step 2 (runs INSIDE Blender, headless):
    blender.exe -b --python tools/f1_blender_scene.py -- <repo_root>
Reads film/f1_data/* (made by tools/f1_prep_data.py) and writes film/marswalk_scene.blend.
Blender units: metres. Origin: centre of the walk window. +X east, +Y north, +Z up (elevation - Z0).
"""
import json, math, os, sys
import numpy as np
import bpy
from mathutils import Vector

ROOT = sys.argv[sys.argv.index("--") + 1] if "--" in sys.argv else os.getcwd()
D = os.environ.get("F1_DATA_DIR") or os.path.join(ROOT, "film", "f1_data")      # F1_DATA_DIR: route mode (tools/render_route.py)
J = json.load(open(os.path.join(D, "scene.json")))
S = J["S"]
FILM = J.get("film")                                    # present only in route mode: a clip for any route planned in the twin
ROUTE = bool(FILM)

# shot timeline (24 fps): (name, first, last, lmst)
ORBITAL = os.environ.get("F1_ORBITAL") == "1"          # wide MOLA context + Gale-scale orbital descent -> film/marswalk_scene_orbital.blend (frames 1-480 only)
SHOTS = [("orbital", 1, 480, 9), ("walk", 501, 1100, 9), ("dust", 1121, 1600, 16), ("detour", 1621, 2100, 16)]
if ROUTE: SHOTS = [("overview", 1, FILM["ov_frames"], FILM["lmst"]), ("walk", FILM["ov_frames"] + 1, FILM["frames"], FILM["lmst"])]

bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene
sc.name = "MARSWALK"


# ------------------------------------------------------------------ helpers
def lerp(a, b, t): return a + (b - a) * t
def smooth(t): return t * t * (3 - 2 * t)

# ------------------------------------------------------------------ F2 look: node helpers
TEX = J["tex"]                                              # Navcam-derived textures, read from demo/twin/tex at every rebuild
def nd(nt, t, **kw):
    n = nt.nodes.new(t)
    for k, v in kw.items(): setattr(n, k, v)
    return n
def put(nt, sock, v):
    if isinstance(v, bpy.types.NodeSocket): nt.links.new(v, sock)
    else: sock.default_value = v
def vmath(nt, op, a, b=None, c=None):
    n = nd(nt, "ShaderNodeVectorMath", operation=op); put(nt, n.inputs[0], a)
    if b is not None: put(nt, n.inputs[3] if op == "SCALE" else n.inputs[1], b)
    if c is not None: put(nt, n.inputs[2], c)
    return n.outputs["Value"] if op in ("DOT_PRODUCT", "LENGTH", "DISTANCE") else n.outputs[0]
def mth(nt, op, a, b=None, clamp=False):
    n = nd(nt, "ShaderNodeMath", operation=op, use_clamp=clamp); put(nt, n.inputs[0], a)
    if b is not None: put(nt, n.inputs[1], b)
    return n.outputs[0]
def maprange(nt, v, a0, a1, b0=0.0, b1=1.0, clamp=True):
    n = nd(nt, "ShaderNodeMapRange", clamp=clamp); put(nt, n.inputs[0], v)
    for i, x in enumerate((a0, a1, b0, b1)): put(nt, n.inputs[i + 1], x)
    return n.outputs[0]
def mixcol(nt, fac, a, b, blend="MIX"):
    n = nd(nt, "ShaderNodeMix", data_type="RGBA", blend_type=blend); put(nt, n.inputs[0], fac)
    put(nt, n.inputs[6], a if isinstance(a, bpy.types.NodeSocket) else tuple(a) + (1,) * (4 - len(a)))
    put(nt, n.inputs[7], b if isinstance(b, bpy.types.NodeSocket) else tuple(b) + (1,) * (4 - len(b))); return n.outputs[2]
def load_img(path, nonc):
    im = bpy.data.images.load(path, check_existing=True); im.colorspace_settings.name = "Non-Color" if nonc else "sRGB"; return im
def world_tex(nt, path, tile_m, mul, off, nonc, co):
    """image sampled in world space (box projection) at tile_m * mul metres per repeat."""
    mp = nd(nt, "ShaderNodeMapping"); s = 1.0 / (tile_m * mul)
    mp.inputs["Scale"].default_value = (s, s, s); mp.inputs["Location"].default_value = (off, off * 0.7, 0)
    nt.links.new(co, mp.inputs[0])
    t = nd(nt, "ShaderNodeTexImage", image=load_img(path, nonc), projection="BOX", projection_blend=0.35, interpolation="Linear")
    nt.links.new(mp.outputs[0], t.inputs[0]); return t.outputs["Color"]
def noise(nt, co, scale, detail=2.0, rough=0.5):
    n = nd(nt, "ShaderNodeTexNoise", noise_dimensions="3D"); n.inputs["Scale"].default_value = scale
    n.inputs["Detail"].default_value = detail; n.inputs["Roughness"].default_value = rough
    nt.links.new(co, n.inputs[0]); return n

def image_mat(name, path, mult=0.45):
    m = bpy.data.materials.new(name); m.use_nodes = True
    nt = m.node_tree; nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial"); bs = nt.nodes.new("ShaderNodeBsdfPrincipled")
    tex = nt.nodes.new("ShaderNodeTexImage"); tex.image = bpy.data.images.load(path); tex.image.colorspace_settings.name = "sRGB"
    tex.interpolation = "Cubic"; tex.extension = "EXTEND"
    mx = nt.nodes.new("ShaderNodeMix"); mx.data_type = "RGBA"; mx.blend_type = "MULTIPLY"
    mx.inputs[0].default_value = 1.0; mx.inputs[7].default_value = (mult, mult, mult, 1)
    nt.links.new(tex.outputs["Color"], mx.inputs[6]); nt.links.new(mx.outputs[2], bs.inputs["Base Color"])
    bs.inputs["Roughness"].default_value = 0.95
    nt.links.new(bs.outputs["BSDF"], out.inputs["Surface"])
    return m

def ground_mat(drape_path, mult=0.45):
    """HiRISE drape = large-scale colour (measured); Curiosity-Navcam textures (bedrock/sand/pebbly) = detail, normal, roughness,
    blended by the ground-type map and mapped in world space; micro-relief bump; detail fades with camera distance."""
    m = bpy.data.materials.new("mat_corridor"); m.use_nodes = True; nt = m.node_tree; nt.nodes.clear()
    out = nd(nt, "ShaderNodeOutputMaterial"); bs = nd(nt, "ShaderNodeBsdfPrincipled")
    tc = nd(nt, "ShaderNodeTexCoord"); obj = tc.outputs["Object"]
    dr = nd(nt, "ShaderNodeTexImage", image=load_img(drape_path, False), interpolation="Cubic", extension="EXTEND"); nt.links.new(tc.outputs["UV"], dr.inputs[0])
    drape = mixcol(nt, 1.0, dr.outputs["Color"], (mult, mult, mult, 1), "MULTIPLY")
    # ground-type weights (R bedrock, G sand, B pebbly), domain-warped so the 4 m cells do not show
    warp = noise(nt, obj, 0.02, 2.0)
    uv = vmath(nt, "MULTIPLY_ADD", vmath(nt, "SUBTRACT", warp.outputs["Color"], (0.5, 0.5, 0.5)), (0.05, 0.05, 0.05), tc.outputs["UV"])
    wt = nd(nt, "ShaderNodeTexImage", image=load_img(os.path.join(D, "ground_weights.png"), True), interpolation="Linear", extension="EXTEND")
    nt.links.new(uv, wt.inputs[0]); sep = nd(nt, "ShaderNodeSeparateColor"); nt.links.new(wt.outputs["Color"], sep.inputs[0])
    W = [sep.outputs[0], sep.outputs[1], sep.outputs[2]]
    # anti-tiling: two scales of every texture, mixed by a low-frequency mask
    mask = maprange(nt, noise(nt, obj, 0.11, 1.0).outputs["Fac"], 0.35, 0.65)
    cd = nd(nt, "ShaderNodeCameraData"); near = maprange(nt, cd.outputs["View Distance"], 150.0, 700.0, 1.0, 0.0)
    acc = {"albedo": None, "normal": None, "rough": None}
    for i, t in enumerate(("bedrock", "sand", "pebbly")):
        T = TEX[t]
        for kind in acc:
            a = world_tex(nt, T[kind], T["tile_m"], 1.0, 0.0, kind != "albedo", obj)
            b = world_tex(nt, T[kind], T["tile_m"], 1.37, 3.1, kind != "albedo", obj)
            v = mixcol(nt, mask, a, b)
            if kind == "albedo": v = vmath(nt, "DIVIDE", v, tuple(T["mean"]))                    # ratio to the texture mean: keeps the HiRISE colour
            term = vmath(nt, "SCALE", v, W[i]); acc[kind] = term if acc[kind] is None else vmath(nt, "ADD", acc[kind], term)
    ratio = vmath(nt, "ADD", vmath(nt, "SCALE", vmath(nt, "SUBTRACT", acc["albedo"], (1, 1, 1)), mth(nt, "MULTIPLY", near, 1.5)), (1, 1, 1))
    ratio = vmath(nt, "MAXIMUM", vmath(nt, "MINIMUM", ratio, (2.2, 2.2, 2.2)), (0.2, 0.2, 0.2))
    # mid-scale relief (metres): polygonal fracture network in bedrock/pebbly ground (PROCEDURAL, illustrative) + soft tonal patches
    wc = vmath(nt, "ADD", obj, vmath(nt, "SCALE", vmath(nt, "SUBTRACT", warp2 := noise(nt, obj, 0.6, 2.0).outputs["Color"], (0.5, 0.5, 0.5)), 1.1))
    vo = nd(nt, "ShaderNodeTexVoronoi", voronoi_dimensions="3D", feature="DISTANCE_TO_EDGE"); vo.inputs["Scale"].default_value = 0.9; nt.links.new(wc, vo.inputs[0])
    edge = vo.outputs["Distance"]; near2 = maprange(nt, cd.outputs["View Distance"], 60.0, 400.0, 1.0, 0.0)
    crackw = mth(nt, "MULTIPLY", mth(nt, "ADD", W[0], mth(nt, "MULTIPLY", W[2], 1.0)), near2)
    dark = maprange(nt, edge, 0.0, 0.13, 0.08, 1.0)
    cfac = mth(nt, "SUBTRACT", 1.0, mth(nt, "MULTIPLY", crackw, mth(nt, "SUBTRACT", 1.0, dark)))
    vo2 = nd(nt, "ShaderNodeTexVoronoi", voronoi_dimensions="3D", feature="F1"); vo2.inputs["Scale"].default_value = 0.9; nt.links.new(wc, vo2.inputs[0])
    cellb = maprange(nt, vmath(nt, "DOT_PRODUCT", vo2.outputs["Color"], (1 / 3, 1 / 3, 1 / 3)), 0.25, 0.75, 0.72, 1.3)               # slab-to-slab brightness
    cfac = mth(nt, "MULTIPLY", cfac, mth(nt, "ADD", mth(nt, "MULTIPLY", crackw, cellb), mth(nt, "SUBTRACT", 1.0, crackw)))
    patch = maprange(nt, noise(nt, obj, 0.35, 3.0, 0.55).outputs["Fac"], 0.3, 0.7, 0.78, 1.22)
    col = vmath(nt, "MULTIPLY", vmath(nt, "MULTIPLY", drape, ratio), vmath(nt, "SCALE", (1, 1, 1), mth(nt, "MULTIPLY", cfac, patch)))
    nm = nd(nt, "ShaderNodeNormalMap", space="TANGENT"); nt.links.new(acc["normal"], nm.inputs["Color"]); put(nt, nm.inputs["Strength"], mth(nt, "MULTIPLY", near, 1.1))
    b1 = nd(nt, "ShaderNodeBump"); put(nt, b1.inputs["Height"], noise(nt, obj, 55.0, 5.0, 0.6).outputs["Fac"]); b1.inputs["Distance"].default_value = 0.03
    put(nt, b1.inputs["Strength"], mth(nt, "MULTIPLY", near, 0.35)); nt.links.new(nm.outputs[0], b1.inputs["Normal"])
    b2 = nd(nt, "ShaderNodeBump")
    h2 = mth(nt, "ADD", mth(nt, "MULTIPLY", noise(nt, obj, 2.4, 4.0, 0.55).outputs["Fac"], 0.5), mth(nt, "MULTIPLY", maprange(nt, edge, 0.0, 0.16), mth(nt, "MULTIPLY", crackw, 0.5)))
    put(nt, b2.inputs["Height"], h2); b2.inputs["Distance"].default_value = 0.14
    put(nt, b2.inputs["Strength"], mth(nt, "MULTIPLY", near2, 0.6)); nt.links.new(b1.outputs[0], b2.inputs["Normal"])
    rough = mth(nt, "MULTIPLY", vmath(nt, "DOT_PRODUCT", acc["rough"], (1 / 3, 1 / 3, 1 / 3)), 1.12, clamp=True)
    rough = mth(nt, "ADD", mth(nt, "MULTIPLY", rough, near), mth(nt, "MULTIPLY", mth(nt, "SUBTRACT", 1.0, near), 0.9), clamp=True)
    nt.links.new(col, bs.inputs["Base Color"]); put(nt, bs.inputs["Roughness"], rough); nt.links.new(b2.outputs[0], bs.inputs["Normal"])
    bs.inputs["Specular IOR Level"].default_value = 0.25
    nt.links.new(bs.outputs["BSDF"], out.inputs["Surface"]); return m

def rock_mat():
    """boulders and pebbles: bedrock Navcam texture (world space), dust on up-facing surfaces, bump from texture luminance."""
    m = bpy.data.materials.new("mat_rock"); m.use_nodes = True; nt = m.node_tree; nt.nodes.clear()
    out = nd(nt, "ShaderNodeOutputMaterial"); bs = nd(nt, "ShaderNodeBsdfPrincipled"); tc = nd(nt, "ShaderNodeTexCoord"); obj = tc.outputs["Object"]
    T = TEX["bedrock"]
    alb = world_tex(nt, T["albedo"], T["tile_m"], 0.5, 0.0, False, obj)
    base = vmath(nt, "MULTIPLY", vmath(nt, "DIVIDE", alb, tuple(T["mean"])), (0.20, 0.135, 0.095))      # linear albedo of dark rock
    sepn = nd(nt, "ShaderNodeSeparateXYZ"); nt.links.new(nd(nt, "ShaderNodeNewGeometry").outputs["Normal"], sepn.inputs[0])
    dust = maprange(nt, sepn.outputs["Z"], 0.35, 0.95, 0.0, 0.55)
    col = mixcol(nt, dust, base, (0.33, 0.21, 0.13, 1))
    lum = vmath(nt, "DOT_PRODUCT", alb, (0.3, 0.5, 0.2))
    bp = nd(nt, "ShaderNodeBump"); put(nt, bp.inputs["Height"], lum); bp.inputs["Strength"].default_value = 0.7; bp.inputs["Distance"].default_value = 0.02
    b2 = nd(nt, "ShaderNodeBump"); put(nt, b2.inputs["Height"], noise(nt, obj, 7.0, 5.0, 0.6).outputs["Fac"]); b2.inputs["Strength"].default_value = 0.5; b2.inputs["Distance"].default_value = 0.06
    nt.links.new(bp.outputs[0], b2.inputs["Normal"])
    nt.links.new(col, bs.inputs["Base Color"]); bs.inputs["Roughness"].default_value = 0.88; nt.links.new(b2.outputs[0], bs.inputs["Normal"])
    nt.links.new(bs.outputs[0], out.inputs[0]); return m

def tri_mesh(name, V, F, mat, smooth=False):
    """V (n,3) float, F (m,3) int -> object linked to the scene."""
    me = bpy.data.meshes.new(name)
    me.vertices.add(len(V)); me.vertices.foreach_set("co", V.astype(np.float32).ravel())
    me.loops.add(len(F) * 3); me.loops.foreach_set("vertex_index", F.astype(np.int32).ravel())
    me.polygons.add(len(F)); me.polygons.foreach_set("loop_start", (np.arange(len(F)) * 3).astype(np.int32))
    me.polygons.foreach_set("use_smooth", np.full(len(F), smooth, dtype=bool)); me.update(calc_edges=True)
    ob = bpy.data.objects.new(name, me); sc.collection.objects.link(ob); me.materials.append(mat); return ob

def grid_mesh(name, z, x0, y0, px, mask=None, uv_scale=(1.0, 1.0), uv_off=(0.5, 0.5), uv_mul=1.0, mat=None, dz=0.0):
    ny, nx = z.shape
    jj, ii = np.mgrid[0:ny, 0:nx]
    co = np.stack([x0 + (ii + 0.5) * px, y0 - (jj + 0.5) * px, z + dz], -1).reshape(-1, 3).astype(np.float32)
    idx = (jj * nx + ii)
    q = np.stack([idx[:-1, :-1], idx[1:, :-1], idx[1:, 1:], idx[:-1, 1:]], -1).reshape(-1, 4)    # counter-clockwise seen from above
    if mask is not None: q = q[mask[:-1, :-1].reshape(-1)]
    me = bpy.data.meshes.new(name)
    me.vertices.add(len(co)); me.vertices.foreach_set("co", co.ravel())
    me.loops.add(len(q) * 4); me.loops.foreach_set("vertex_index", q.ravel().astype(np.int32))
    me.polygons.add(len(q)); me.polygons.foreach_set("loop_start", (np.arange(len(q)) * 4).astype(np.int32))
    me.polygons.foreach_set("use_smooth", np.ones(len(q), dtype=bool))
    me.update(calc_edges=True)
    uvl = me.uv_layers.new(name="UV")
    u = (ii.reshape(-1) * uv_mul + uv_off[0]) / uv_scale[0]; v = 1.0 - (jj.reshape(-1) * uv_mul + uv_off[1]) / uv_scale[1]
    uv = np.stack([u, v], -1).astype(np.float32)[q.ravel()]
    uvl.data.foreach_set("uv", uv.ravel())
    ob = bpy.data.objects.new(name, me); sc.collection.objects.link(ob)
    if mat: me.materials.append(mat)
    return ob

# ------------------------------------------------------------------ terrain
zc = np.load(os.path.join(D, "corridor_z.npy")); C = J["corr"]
terrain = grid_mesh("Terrain_corridor_1m", zc, J["corr_x0"], J["corr_y0"], S, uv_scale=(C["nx"], C["ny"]),
                    mat=ground_mat(os.path.join(D, "corridor_tex.jpg")))
zx = np.load(os.path.join(D, "context_z.npy")); X = J["ctx"]
jj, ii = np.mgrid[0:zx.shape[0], 0:zx.shape[1]]
cx = X["x0"] + (ii + 0.5) * X["px"]; cy = X["y0"] - (jj + 0.5) * X["px"]
cx1, cx2 = J["corr_x0"] + 6, J["corr_x0"] + C["nx"] * S - 6
cy2, cy1 = J["corr_y0"] - C["ny"] * S + 6, J["corr_y0"] - 6
inside = (cx > cx1 - X["px"]) & (cx < cx2 + X["px"]) & (cy < cy1 + X["px"]) & (cy > cy2 - X["px"])
keep = ~(inside[:-1, :-1] & inside[1:, 1:] & inside[:-1, 1:] & inside[1:, :-1])
mask = np.ones(zx.shape, bool); mask[:-1, :-1] = keep
ctx = grid_mesh("Terrain_context_4m", zx, X["x0"] - 0.375 * X["px"], X["y0"] + 0.375 * X["px"], X["px"], mask=mask,
                uv_scale=(zx.shape[1] * X["step"], zx.shape[0] * X["step"]), uv_off=(0.5, 0.5), uv_mul=X["step"],
                mat=image_mat("mat_context", os.path.join(D, "context_tex.jpg")), dz=-0.6)
# horizon plane so the far field is not a black void
bpy.ops.mesh.primitive_plane_add(size=300000, location=(0, 0, float(zx.min()) - 2))
far = bpy.context.active_object; far.name = "Far_ground"
fm = bpy.data.materials.new("mat_far"); fm.use_nodes = True
fm.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.20, 0.10, 0.05, 1)
fm.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 1.0
far.data.materials.append(fm)

if ORBITAL:
    # ---- wide MOLA context (tools/f1_prep_mola.py): inner tier 50 m around the tile, outer tier 1 km to +-300 km, flat far ring beyond
    MZ = np.load(os.path.join(D, "mola_ctx.npz")); MJ = json.load(open(os.path.join(D, "mola_ctx.json")))
    bpy.data.objects.remove(far, do_unlink=True)
    def vc_mat():
        m = bpy.data.materials.new("mat_mola"); m.use_nodes = True; nt_ = m.node_tree; nt_.nodes.clear()
        at = nd(nt_, "ShaderNodeAttribute", attribute_name="Col", attribute_type="GEOMETRY"); bs = nd(nt_, "ShaderNodeBsdfPrincipled"); o_ = nd(nt_, "ShaderNodeOutputMaterial")
        nt_.links.new(at.outputs["Color"], bs.inputs["Base Color"]); bs.inputs["Roughness"].default_value = 1.0; bs.inputs["Specular IOR Level"].default_value = 0.25
        nt_.links.new(bs.outputs[0], o_.inputs[0]); return m
    MMAT = vc_mat()
    def tier(name, gx, gy, gz, col, keepq):
        ny_, nx_ = gz.shape; jj_, ii_ = np.mgrid[0:ny_, 0:nx_]
        co_ = np.stack([gx, gy, gz], -1).reshape(-1, 3).astype(np.float32); idx = jj_ * nx_ + ii_
        q = np.stack([idx[:-1, :-1], idx[1:, :-1], idx[1:, 1:], idx[:-1, 1:]], -1)
        q = q[keepq].reshape(-1, 4)
        me = bpy.data.meshes.new(name); me.vertices.add(len(co_)); me.vertices.foreach_set("co", co_.ravel())
        me.loops.add(len(q) * 4); me.loops.foreach_set("vertex_index", q.ravel().astype(np.int32))
        me.polygons.add(len(q)); me.polygons.foreach_set("loop_start", (np.arange(len(q)) * 4).astype(np.int32)); me.polygons.foreach_set("use_smooth", np.ones(len(q), dtype=bool))
        me.update(calc_edges=True)
        ca = me.color_attributes.new("Col", "FLOAT_COLOR", "POINT"); rgba = np.concatenate([col.reshape(-1, 3), np.ones((len(co_), 1), np.float32)], 1)
        ca.data.foreach_set("color", rgba.ravel()); me.materials.append(MMAT)
        ob = bpy.data.objects.new(name, me); sc.collection.objects.link(ob); return ob
    xs_, ys_, zi_ = MZ["xs"], MZ["ys"], MZ["zi"]; gxi, gyi = np.meshgrid(xs_, ys_)
    tx0, tx1, ty0, ty1 = float(MZ["xmin"]), float(MZ["xmax"]), float(MZ["ymin"]), float(MZ["ymax"])
    insd = (gxi >= tx0 - 1e-3) & (gxi <= tx1 + 1e-3) & (gyi >= ty0 - 1e-3) & (gyi <= ty1 + 1e-3)
    keep_i = ~(insd[:-1, :-1] & insd[1:, :-1] & insd[1:, 1:] & insd[:-1, 1:])
    tier("Terrain_MOLA_inner_50m", gxi, gyi, zi_, MZ["ci"], keep_i)
    ox_ = MZ["ox"]; gxo, gyo = np.meshgrid(ox_, ox_[::-1]); OS_ = float(MZ["os_"])
    ex = max(abs(float(xs_[0])), abs(float(xs_[-1])), abs(float(ys_[0])), abs(float(ys_[-1]))) - OS_
    ino = (np.abs(gxo) <= ex) & (np.abs(gyo) <= ex)
    keep_o = ~(ino[:-1, :-1] & ino[1:, :-1] & ino[1:, 1:] & ino[:-1, 1:])
    tier("Terrain_MOLA_outer_1km", gxo, gyo, MZ["zo"], MZ["co"], keep_o)
    # flat far ring from the +-300 km rim out to +-3000 km (rim vertices are at the same level, so no crack)
    EO, EF, zf = float(MZ["oext"]), 3.0e6, float(MZ["far"])
    fv = np.array([[-EO, -EO], [EO, -EO], [EO, EO], [-EO, EO], [-EF, -EF], [EF, -EF], [EF, EF], [-EF, EF]], np.float32)
    fv = np.c_[fv, np.full(8, zf, np.float32)]
    ff = np.array([[0, 1, 5], [0, 5, 4], [1, 2, 6], [1, 6, 5], [2, 3, 7], [2, 7, 6], [3, 0, 4], [3, 4, 7]])
    fm_ = bpy.data.materials.new("mat_far"); fm_.use_nodes = True
    fm_.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = tuple(float(v) for v in MZ["farcol"]) + (1.0,); fm_.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 1.0
    far = tri_mesh("Far_ring", fv, ff, fm_)
    print("MOLA context built: inner %s outer %s, datum offset %.1f m" % (zi_.shape, MZ["zo"].shape, float(MZ["off"])))

def height_at(x, y):
    """bilinear terrain height (Blender z) at Blender x,y from the 1 m corridor grid (nearest valid if outside)."""
    if ROUTE and not (J["corr_x0"] <= x <= J["corr_x0"] + C["nx"] * S and J["corr_y0"] - C["ny"] * S <= y <= J["corr_y0"]):   # outside the window: the 4 m context mesh (lowered 0.6 m)
        px_ = X["px"]; gx = min(max((x - (X["x0"] - 0.375 * px_)) / px_ - 0.5, 0), zx.shape[1] - 1.001); gy = min(max((X["y0"] + 0.375 * px_ - y) / px_ - 0.5, 0), zx.shape[0] - 1.001)
        i, j = int(gx), int(gy); a, b = gx - i, gy - j
        return float((1 - a) * (1 - b) * zx[j, i] + a * (1 - b) * zx[j, i + 1] + (1 - a) * b * zx[j + 1, i] + a * b * zx[j + 1, i + 1]) - 0.6
    fx = (x - J["corr_x0"]) / S - 0.5; fy = (J["corr_y0"] - y) / S - 0.5
    fx = min(max(fx, 0), zc.shape[1] - 1.001); fy = min(max(fy, 0), zc.shape[0] - 1.001)
    i, j = int(fx), int(fy); a, b = fx - i, fy - j
    return float((1 - a) * (1 - b) * zc[j, i] + a * (1 - b) * zc[j, i + 1] + (1 - a) * b * zc[j + 1, i] + a * b * zc[j + 1, i + 1])

# ------------------------------------------------------------------ glTF imports
def import_glb(path, name):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=path)
    new = [o for o in bpy.data.objects if o not in before]
    root = bpy.data.objects.new(name, None); sc.collection.objects.link(root)
    for o in new:
        if o.parent is None: o.parent = root
    return root, new

def vcol_mat():
    m = bpy.data.materials.new("mat_scan_vcol"); m.use_nodes = True; nt = m.node_tree; nt.nodes.clear()
    at = nt.nodes.new("ShaderNodeAttribute"); at.attribute_name = "Col"; at.attribute_type = "GEOMETRY"
    mu = nt.nodes.new("ShaderNodeMix"); mu.data_type = "RGBA"; mu.blend_type = "MULTIPLY"
    mu.inputs[0].default_value = 1.0; mu.inputs[7].default_value = (0.62, 0.40, 0.25, 1)      # warm Mars tint on the grey scan colours
    bs = nt.nodes.new("ShaderNodeBsdfPrincipled"); bs.inputs["Roughness"].default_value = 1.0
    o = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(at.outputs["Color"], mu.inputs[6]); nt.links.new(mu.outputs[2], bs.inputs["Base Color"]); nt.links.new(bs.outputs[0], o.inputs[0])
    return m, at

SCAN_MAT, SCAN_ATTR = vcol_mat()
scan_roots = []; scan_info = []
for m in J["meshes"]:
    root, objs = import_glb(os.path.join(ROOT, "demo", "twin", "meshes", m["file"]), "Scan_sol%d" % m["sol"])
    for o in objs:
        if o.type == "MESH":
            names = [c.name for c in o.data.color_attributes]
            if names: SCAN_ATTR.attribute_name = names[0]
            o.data.materials.clear(); o.data.materials.append(SCAN_MAT)
    # glTF importer already maps (x=E, y=Up, z=-N) -> Blender (x=E, y=N, z=Up)
    root.location = (m["e"], m["n"], m["z"])
    scan_roots.append(root); scan_info.append((m["e"], m["n"], m.get("radius", 25.0), [o for o in objs if o.type == "MESH"]))
print("scan colour attribute:", SCAN_ATTR.attribute_name)

# Optional scan clean-up (F1_SCAN_CLEAN=1, or "scan_clean" in the route film parameters; default OFF so the film is unchanged).
# Same as the browser twin's fitScan (demo/twin/twin.html): (1) high-pass merge onto the HiRISE surface: residual r = scan - HiRISE
# per vertex, L = median of r per 1 m cell then median over 5 x 5 cells, vertex = HiRISE + clamp(r - L, -0.2, +0.4);
# (2) drop stereo "curtain" triangles: any edge > 0.6 m, or near-vertical (|n.z| < 0.3) and longer than 0.15 m.
SCAN_CLEAN = os.environ.get("F1_SCAN_CLEAN") == "1" or bool((FILM or {}).get("scan_clean"))
SC_LO, SC_HI = (float(x) for x in os.environ.get("F1_SCAN_CLAMP", "-0.2,0.4").split(","))     # the twin's values; options for the film
SC_EDGE = float(os.environ.get("F1_SCAN_EDGE", "0.6")); SC_MINCOMP = int(os.environ.get("F1_SCAN_MINCOMP", "0")); SC_NZ = float(os.environ.get("F1_SCAN_NZ", "0"))     # SC_NZ: also drop facets steeper than acos(nz) (film option)
def clean_scan(o):
    import bmesh
    me = o.data; nv = len(me.vertices)
    co = np.empty(nv * 3, np.float32); me.vertices.foreach_get("co", co); co = co.reshape(-1, 3).astype(np.float64)
    M = np.array(o.matrix_world); R, T = M[:3, :3], M[:3, 3]; Mi = np.linalg.inv(M)
    w = co @ R.T + T
    g = np.array([height_at(x, y) for x, y in w[:, :2]]); r = w[:, 2] - g
    ci = np.rint(w[:, 0]).astype(np.int64); cj = np.rint(w[:, 1]).astype(np.int64)
    key = (ci + 20000) * 40001 + (cj + 20000); order = np.argsort(key, kind="stable"); ks = key[order]; cut = np.r_[0, np.where(np.diff(ks) != 0)[0] + 1, nv]
    cell_med = {}
    for a, b in zip(cut[:-1], cut[1:]): cell_med[int(ks[a])] = float(np.median(r[order[a:b]]))
    Lc = {}
    for kk in cell_med:
        i, j = divmod(kk, 40001)
        q = [cell_med[(i + di) * 40001 + (j + dj)] for di in range(-2, 3) for dj in range(-2, 3) if (i + di) * 40001 + (j + dj) in cell_med]
        Lc[kk] = float(np.median(q))
    L = np.array([Lc[int(k)] for k in key]); d0 = r - L; d = np.clip(d0, SC_LO, SC_HI)
    w[:, 2] = g + d; loc = (w - T) @ np.linalg.inv(R).T
    me.vertices.foreach_set("co", loc.astype(np.float32).ravel()); me.update()
    pc = len(me.polygons)
    if len(me.loops) != 3 * pc: print("scan clean: non-triangle mesh, triangle cut skipped"); return 0, pc, float(np.mean(d != d0))
    tri = np.empty(pc * 3, np.int32); me.polygons.foreach_get("vertices", tri); tri = tri.reshape(-1, 3)
    a, b, c = w[tri[:, 0]], w[tri[:, 1]], w[tri[:, 2]]
    m = np.max([np.linalg.norm(a - b, axis=1), np.linalg.norm(b - c, axis=1), np.linalg.norm(c - a, axis=1)], axis=0)
    n = np.cross(b - a, c - a); nz = np.abs(n[:, 2]) / (np.linalg.norm(n, axis=1) + 1e-12)
    bad = (m > SC_EDGE) | ((nz < 0.3) & (m > 0.15)) | (nz < SC_NZ)
    if SC_MINCOMP > 0:                                  # film option: also drop small islands of triangles (floating flakes)
        t_ = tri[~bad]; lab = np.arange(nv)                  # connected components of the kept triangles (numpy label propagation + pointer jumping)
        ea = np.r_[t_[:, 0], t_[:, 1], t_[:, 2]]; eb = np.r_[t_[:, 1], t_[:, 2], t_[:, 0]]
        while True:
            m_ = np.minimum(lab[ea], lab[eb]); old_ = lab.copy()
            np.minimum.at(lab, ea, m_); np.minimum.at(lab, eb, m_)
            lab = lab[lab]
            if np.array_equal(lab, old_): break
        cnt = np.bincount(lab[t_[:, 0]], minlength=nv)
        small = np.zeros(pc, bool); small[np.where(~bad)[0]] = cnt[lab[t_[:, 0]]] < SC_MINCOMP; bad = bad | small
    drop = np.where(bad)[0]
    bm = bmesh.new(); bm.from_mesh(me); bm.faces.ensure_lookup_table()
    bmesh.ops.delete(bm, geom=[bm.faces[int(i)] for i in drop], context="FACES")
    bm.to_mesh(me); bm.free(); me.update(); me.calc_loop_triangles()
    return len(drop), pc, float(np.mean(d != d0))
if SCAN_CLEAN:
    bpy.context.view_layer.update()
    for (se, sn, rad, objs) in scan_info:
        for o in objs:
            ndrop, ntot, fr_ = clean_scan(o); print(f"scan clean ({se:.0f},{sn:.0f}): dropped {ndrop} of {ntot} triangles, {100 * fr_:.0f}% of vertices clamped")
    bpy.context.view_layer.update()

# F2: scans are the measured surface. Lower the 1 m terrain only inside each scan's own radius, to 8 cm under the scan surface where a ray hits the scan.
bpy.context.view_layer.update()
def scan_z(x, y, margin=0.0):
    """z of the scan surface at x,y (top-most hit over all scan meshes within the scan's radius), or None."""
    best = None
    for (se, sn, rad, objs) in scan_info:
        if math.hypot(x - se, y - sn) > rad + margin: continue
        for o in objs:
            inv = o.matrix_world.inverted(); o0 = inv @ Vector((x, y, 300.0)); d = (inv.to_3x3() @ Vector((0, 0, -1))).normalized()
            hit, loc, nrm, idx = o.ray_cast(o0, d)
            if hit:
                z = (o.matrix_world @ loc).z
                if best is None or z > best: best = z
    return best
# v3: the Navcam scans' own anchor heights can be metres off the HiRISE DTM, and lowering the DTM to them cut pits and
# walls up to 2.5 m deep into the walk (none of which exist in the DTM). Shift each scan vertically so its median
# surface matches the DTM over its footprint, then lower the terrain by at most 0.3 m.
for (se, sn, rad, objs), root in zip(scan_info, scan_roots):
    dz = []
    for ang in np.linspace(0, 2 * np.pi, 24, endpoint=False):
        for rr in (0.15, 0.35, 0.55):
            x, y = se + rr * rad * math.cos(ang), sn + rr * rad * math.sin(ang); z_ = scan_z(x, y)
            if z_ is not None: dz.append(height_at(x, y) - z_)
    if dz:
        root.location.z += float(np.median(dz)); bpy.context.view_layer.update()
        print(f"scan at ({se:.0f},{sn:.0f}) shifted {np.median(dz):+.2f} m onto the DTM ({len(dz)} samples)")
MAX_CUT = 0.3
terr_co = np.empty(len(terrain.data.vertices) * 3, np.float32); terrain.data.vertices.foreach_get("co", terr_co); terr_co = terr_co.reshape(-1, 3)
nlow = 0
for (se, sn, rad, objs) in scan_info:
    near = np.where(np.hypot(terr_co[:, 0] - se, terr_co[:, 1] - sn) <= rad)[0]
    for vi in near:
        zs = scan_z(float(terr_co[vi, 0]), float(terr_co[vi, 1]))
        if zs is not None and terr_co[vi, 2] - MAX_CUT <= zs - 0.08 < terr_co[vi, 2]: terr_co[vi, 2] = zs - 0.08; nlow += 1
terrain.data.vertices.foreach_set("co", terr_co.ravel()); terrain.data.update()
print("terrain vertices lowered under scans:", nlow)
def surf_z(x, y):
    """walking surface: DTM, or the scan surface (mean of 5 hits over a 0.3 m footprint) inside a scan."""
    zd = height_at(x, y); zs = [scan_z(x + dx, y + dy) for dx, dy in ((0, 0), (0.15, 0), (-0.15, 0), (0, 0.15), (0, -0.15))]
    zs = [z for z in zs if z is not None]
    return float(np.mean(zs)) if zs and abs(np.mean(zs) - zd) < 0.15 else zd      # v3: feet stay on the DTM unless the scan agrees

# ------------------------------------------------------------------ routes
def resample(poly, step=2.0, win=5):
    p = np.array(poly, float)
    d = np.r_[0, np.cumsum(np.hypot(*np.diff(p, axis=0).T))]
    s = np.arange(0, d[-1], step); q = np.stack([np.interp(s, d, p[:, 0]), np.interp(s, d, p[:, 1])], -1)
    k = np.ones(win) / win; pad = win // 2
    qp = np.pad(q, ((pad, pad), (0, 0)), mode="edge")
    q = np.stack([np.convolve(qp[:, 0], k, "valid"), np.convolve(qp[:, 1], k, "valid")], -1)
    q[0], q[-1] = p[0], p[-1]
    return q

SHOTS_OPACITY = [(f0, f1) for (_, f0, f1, _) in SHOTS]
def route_ribbon(name, q, color, strength, lift=0.12, w_thin=0.1, w_wide=40.0):
    """Thin (0.4 m) semi-transparent emissive line just above the ground. Shape key 'wide' (40 m) is keyed per shot so the line stays
    readable from the orbit (width ~0.6 % of the camera altitude) and from the detour crane, and is 0.4 m at walking height."""
    t = np.gradient(q, axis=0); t /= np.linalg.norm(t, axis=1)[:, None]
    nrm = np.stack([-t[:, 1], t[:, 0]], -1); n = len(q)
    s_m = np.r_[0, np.cumsum(np.hypot(*np.diff(q, axis=0).T))]
    def verts(w, lf):
        L, R = q + nrm * w / 2, q - nrm * w / 2
        return [(x, y, max(height_at(x, y), surf_z(x, y)) + lf) for x, y in L] + [(x, y, max(height_at(x, y), surf_z(x, y)) + lf) for x, y in R]
    faces = [(i, i + 1, n + i + 1, n + i) for i in range(n - 1)]
    me = bpy.data.meshes.new(name); me.from_pydata(verts(w_thin, lift), [], faces); me.update()
    uvl = me.uv_layers.new(name="UV"); uvs = np.zeros((len(me.loops), 2), np.float32)       # u across 0..1, v = metres along the route
    for li, lp in enumerate(me.loops):
        vi = lp.vertex_index; uvs[li] = (0.0 if vi < n else 1.0, s_m[vi % n])
    uvl.data.foreach_set("uv", uvs.ravel())
    ob = bpy.data.objects.new(name, me); sc.collection.objects.link(ob)
    ob.shape_key_add(name="Basis"); sk = ob.shape_key_add(name="wide")
    for i, v in enumerate(verts(w_wide, 3.0)): sk.data[i].co = v
    ob["w_thin_m"], ob["w_wide_m"], ob["length_m"] = w_thin, w_wide, float(s_m[-1])
    m = bpy.data.materials.new("mat_" + name); m.use_nodes = True; nt = m.node_tree; nt.nodes.clear()
    uv = nd(nt, "ShaderNodeUVMap", uv_map="UV"); sp = nd(nt, "ShaderNodeSeparateXYZ"); nt.links.new(uv.outputs[0], sp.inputs[0])
    prof = mth(nt, "SUBTRACT", 1.0, mth(nt, "POWER", mth(nt, "ABSOLUTE", mth(nt, "SUBTRACT", mth(nt, "MULTIPLY", sp.outputs["X"], 2.0), 1.0)), 2.0))   # soft across-profile
    fin = maprange(nt, sp.outputs["Y"], 0.0, 25.0); fout = maprange(nt, mth(nt, "SUBTRACT", float(s_m[-1]), sp.outputs["Y"]), 0.0, 25.0)   # fade at both ends
    op = nd(nt, "ShaderNodeValue", name="Opacity"); op.outputs[0].default_value = 0.0
    fac = mth(nt, "MULTIPLY", mth(nt, "MULTIPLY", prof, mth(nt, "MULTIPLY", fin, fout)), mth(nt, "MULTIPLY", op.outputs[0], 0.6))
    em = nd(nt, "ShaderNodeEmission"); em.inputs["Color"].default_value = color; em.inputs["Strength"].default_value = strength
    tr = nd(nt, "ShaderNodeBsdfTransparent"); mx = nd(nt, "ShaderNodeMixShader")
    nt.links.new(fac, mx.inputs[0]); nt.links.new(tr.outputs[0], mx.inputs[1]); nt.links.new(em.outputs[0], mx.inputs[2])
    o = nd(nt, "ShaderNodeOutputMaterial"); nt.links.new(mx.outputs[0], o.inputs[0]); me.materials.append(m)
    ob.visible_shadow = False; ob.visible_glossy = False
    # fade in and out at the start and end of every shot (global opacity)
    for (f0, f1) in SHOTS_OPACITY:
        for f, v in [(f0 - 1, 0.0), (f0, 0.0), (f0 + 24, 1.0), (f1 - 24, 1.0), (f1, 0.0)]:
            op.outputs[0].default_value = v; op.outputs[0].keyframe_insert("default_value", frame=f)
    for fc in nt.animation_data.action.fcurves:
        for kp in fc.keyframe_points: kp.interpolation = "LINEAR"
    return ob, sk

QA = resample(J["route_approved"]); QD = None if ROUTE else resample(J["route_direct"])
ROUTE_A, SK_A = route_ribbon("Route_approved", QA, (0.10, 0.80, 1.00, 1), 2.2)                   # approved: cyan
if not ROUTE: ROUTE_D, SK_D = route_ribbon("Route_straight_nogo", QD, (1.00, 0.10, 0.06, 1), 2.6, lift=0.17)      # v3: straight line start->goal, rejected: red
SKS = (SK_A,) if ROUTE else (SK_A, SK_D)
# v3: the 4 m cells where the straight line breaks the 25 deg walker slope rule (CS-01): red rings on the ground
_ring_m = bpy.data.materials.new("mat_nogo"); _ring_m.use_nodes = True; _nt = _ring_m.node_tree; _nt.nodes.clear()
_em = _nt.nodes.new("ShaderNodeEmission"); _em.inputs["Color"].default_value = (1.0, 0.08, 0.05, 1); _em.inputs["Strength"].default_value = 4.0
_o = _nt.nodes.new("ShaderNodeOutputMaterial"); _nt.links.new(_em.outputs[0], _o.inputs[0])
for _i, (_x, _y) in enumerate(J.get("nogo", [])):
    bpy.ops.mesh.primitive_torus_add(major_radius=4.0, minor_radius=0.35, location=(_x, _y, height_at(_x, _y) + 0.4))
    _r = bpy.context.active_object; _r.name = f"NoGo_cell_{_i}"; _r.data.materials.append(_ring_m)
    _r["slope_deg"] = J["nogo_slopes"][_i]; _r["rule"] = "CS-01 walker slope limit 25 deg"; _r.visible_shadow = False
print("no-go rings:", len(J.get("nogo", [])))


# ------------------------------------------------------------------ boulders (HiRISE-detected, real) and pebbles (illustrative)
import bmesh
def ico_unit(sub):
    bm = bmesh.new(); bmesh.ops.create_icosphere(bm, subdivisions=sub, radius=1.0)
    V = np.array([v.co[:] for v in bm.verts], np.float64); ix = {v: i for i, v in enumerate(bm.verts)}
    F = np.array([[ix[v] for v in f.verts] for f in bm.faces]); bm.free(); return V, F

def blob_mesh(name, cen, rxyz, yaw, rng, sub, mat, jitter):
    """irregular angular rocks: unit icosphere, 3 random harmonics + per-vertex jitter, anisotropic scale, bottom flattened, flat shaded."""
    V0, F0 = ico_unit(sub); n, nv = len(cen), len(V0)
    dirs = rng.normal(size=(n, 3, 3)); dirs /= np.linalg.norm(dirs, axis=2, keepdims=True)
    fr = rng.uniform(1.5, 4.0, (n, 3)); ph = rng.uniform(0, 6.283, (n, 3)); amp = np.array([0.24, 0.16, 0.09])
    proj = np.einsum("vc,nkc->nvk", V0, dirs) * fr[:, None, :] + ph[:, None, :]
    r = 1.0 + (amp * np.sin(proj)).sum(-1) + jitter * rng.uniform(-1, 1, (n, nv))
    P = V0[None] * r[..., None] * rxyz[:, None, :]
    P[..., 2] = np.maximum(P[..., 2], -0.55 * rxyz[:, None, 2])                               # flat-ish base
    c, s_ = np.cos(yaw)[:, None], np.sin(yaw)[:, None]
    X = P[..., 0] * c - P[..., 1] * s_; Y = P[..., 0] * s_ + P[..., 1] * c
    P = np.stack([X, Y, P[..., 2]], -1) + cen[:, None, :]
    F = (F0[None] + (np.arange(n) * nv)[:, None, None]).reshape(-1, 3)
    return tri_mesh(name, P.reshape(-1, 3), F, mat, smooth=False)

def heights_at(xs, ys): return np.array([height_at(x, y) for x, y in zip(xs, ys)])
ROCKMAT = rock_mat()
rng = np.random.default_rng(1234)
rk = J["rocks"]; cx_ = np.array([J["corr_x0"] + S * (r["col"] - J["C0"]) for r in rk]); cy_ = np.array([J["corr_y0"] - S * (r["row"] - J["R0"]) for r in rk])
_keep = [i for i in range(len(rk)) if all(math.hypot(cx_[i] - se, cy_[i] - sn) > rad for (se, sn, rad, _o) in scan_info)]
rk = [rk[i] for i in _keep]; cx_ = cx_[_keep]; cy_ = cy_[_keep]
dd = np.array([r["d"] for r in rk]); hh = np.array([r["h"] for r in rk]); nb = len(rk)
rxyz = np.stack([dd / 2 * rng.uniform(0.85, 1.15, nb), dd / 2 * rng.uniform(0.7, 1.1, nb), np.maximum(hh, 0.3 * dd) / 2], -1)
zg = np.array([min(height_at(x + dx, y + dy) for dx, dy in ((0, 0), (d / 2, 0), (-d / 2, 0), (0, d / 2), (0, -d / 2))) for x, y, d in zip(cx_, cy_, dd)])
boulders = blob_mesh("Boulders_HiRISE_detected", np.stack([cx_, cy_, zg + 0.45 * rxyz[:, 2]], -1), rxyz, rng.uniform(0, 6.283, nb), rng, 2, ROCKMAT, 0.14)
boulders["note"] = "%d boulders from demo/twin/rocks.json (HiRISE shadow detection, real positions and sizes); the mesh shape is illustrative" % nb

# pebbles: ILLUSTRATIVE (not detected), density per ground type like the twin, only near the camera paths of the walk and dust shots
PEB_RHO = np.array([0.012, 0.002, 0.035]) * float(os.environ.get("F1_PEBBLE_SCALE", "1")); PEB_R = float(os.environ.get("F1_PEBBLE_RADIUS_M", "250"))
GW = np.load(os.path.join(D, "ground_weights.npy"))
dpath = np.r_[0, np.cumsum(np.hypot(*np.diff(QA, axis=0).T))]
def _s_of(sol):
    m_ = [m for m in J["meshes"] if m["sol"] == sol][0]; return float(dpath[int(np.argmin(np.hypot(QA[:, 0] - m_["e"], QA[:, 1] - m_["n"])))])
if ROUTE:    # pebbles only near the walked stretch (and the whole route in a time-lapse)
    focus = [QA[k] for k in range(0, len(QA)) if FILM["start_s"] - 30 <= dpath[k] <= FILM["start_s"] + FILM["walk_m"] + 40][::3]
    PEB_R = float(os.environ.get("F1_PEBBLE_RADIUS_M", "250" if FILM["speedup"] <= 1.5 else "90"))
else:
    S_WALK, S_DUST = _s_of(int(os.environ.get("F1_WALK_SCAN", "4544"))), _s_of(4598)
    walk_end = S_WALK + 0.9 * 25 + 40
    focus = [QA[k] for k in range(0, len(QA)) if dpath[k] <= walk_end][::5] + [np.array([np.interp(S_DUST, dpath, QA[:, 0]), np.interp(S_DUST, dpath, QA[:, 1])])]
focus = np.array(focus)
lo, hi = focus.min(0) - PEB_R, focus.max(0) + PEB_R
nc = int(np.prod(hi - lo) * PEB_RHO.max())
cand = rng.uniform(lo, hi, (nc, 2))
x0c, y0c = J["corr_x0"], J["corr_y0"]
ok = (cand[:, 0] > x0c) & (cand[:, 0] < x0c + C["nx"] * S) & (cand[:, 1] < y0c) & (cand[:, 1] > y0c - C["ny"] * S)
cand = cand[ok]
for (se, sn, rad, _o) in scan_info: cand = cand[np.hypot(cand[:, 0] - se, cand[:, 1] - sn) > rad]          # the measured scan shows there, no invented pebbles
near_focus = np.min(np.hypot(cand[:, None, 0] - focus[None, :, 0], cand[:, None, 1] - focus[None, :, 1]), 1) < PEB_R
cand = cand[near_focus]
wi = np.clip(((cand[:, 0] - x0c) / S).astype(int), 0, GW.shape[1] - 1); wj = np.clip(((y0c - cand[:, 1]) / S).astype(int), 0, GW.shape[0] - 1)
rho = (GW[wj, wi] * PEB_RHO[None]).sum(1)
cand = cand[rng.uniform(0, PEB_RHO.max(), len(cand)) < rho]
npb = len(cand); dp = np.clip(rng.lognormal(np.log(0.15), 0.6, npb), 0.05, 0.60)
rx = np.stack([dp / 2, dp / 2 * rng.uniform(0.6, 1.0, npb), dp / 2 * rng.uniform(0.45, 0.8, npb)], -1)
zp = heights_at(cand[:, 0], cand[:, 1]) + 0.2 * rx[:, 2]
pebbles = blob_mesh("Pebbles_illustrative", np.c_[cand, zp], rx, rng.uniform(0, 6.283, npb), rng, 1, ROCKMAT, 0.18)
pebbles["note"] = "ILLUSTRATIVE pebbles (not detected): %d scattered with density bedrock/sand/pebbly = 0.012/0.002/0.035 per m2 within %.0f m of the walk and dust camera paths" % (npb, PEB_R)
print("boulders", nb, "pebbles", npb, "focus pts", len(focus))


# Curiosity at a campaign waypoint (route 35 %), astronaut on the route
def route_pt(q, f):
    i = min(int(f * (len(q) - 1)), len(q) - 2); return q[i], q[i + 1] - q[i]
if ROUTE and FILM.get("rover_xy"):                   # route mode: Curiosity only where the twin parks the rover (safe-haven setting)
    (pc, dc) = (np.array(FILM["rover_xy"]) - np.array([6.0, 6.0]), None)
elif not ROUTE: (pc, dc) = route_pt(QA, 0.5)
if not ROUTE or FILM.get("rover_xy"):
    msl, mo = import_glb(os.path.join(ROOT, "demo", "twin", "models", "curiosity_msl_nasa.glb"), "Curiosity_MSL (NASA/JPL-Caltech)")
    msl.location = (pc[0] + 6, pc[1] + 6, height_at(pc[0] + 6, pc[1] + 6)); msl.rotation_euler[2] = math.radians(35)
else: msl = None

astro, ao = import_glb(J["suit"], "Astronaut")
for o in list(ao):                                   # the walk GLB carries a stray 2 m unmaterialled icosphere: drop it
    if o.type == "MESH" and o.name.startswith("Icosphere") and not o.data.materials:
        bpy.data.objects.remove(o, do_unlink=True); ao.remove(o)
ARMS = [o for o in ao if o.type == "ARMATURE"]
SUIT_KIND = {"steel2SG": "metal", "blinn2SG": "joint", "bodyrings_blinn2SG": "metal", "bodyrings_steelholesSG": "metal", "blinn1SG": "visor",
             "lambert2SG": "fabric", "hand_lambert2SG": "fabric", "suitcolormappedlegsSG": "fabric", "markiiitorso_lambert2SG": "fabric",
             "lambert6SG": "fabric", "lambert5SG": "fabric", "lambert3SG": "rubber", "lambert4SG": "rubber", "bluesteelSG": "paint"}
def style_suit(mat):
    """off-white fabric with weave normal/roughness and dust on the lower legs; darker joints/rubber; gold mirror visor (material blinn1SG)."""
    kind = next((v for k, v in SUIT_KIND.items() if mat.name.endswith(k)), "fabric")
    if mat.name.endswith("bodyrings_blinn2SG"): kind = "metal"
    nt = mat.node_tree; bs = nt.nodes["Principled BSDF"]; I = bs.inputs
    old = I["Base Color"].default_value[:]; logo = [n for n in nt.nodes if n.type == "TEX_IMAGE"]
    tcn = nd(nt, "ShaderNodeTexCoord"); obj = tcn.outputs["Object"]
    I["Metallic"].default_value = 0.0
    if kind == "fabric":
        base = (0.62, 0.585, 0.54, 1)
        if logo: nt.links.new(logo[0].outputs["Color"], I["Base Color"])
        else:
            sz = nd(nt, "ShaderNodeSeparateXYZ"); nt.links.new(obj, sz.inputs[0])
            dfac = maprange(nt, sz.outputs["Z"], 0.05, 0.75, 0.55, 0.0)                              # lower legs and boots carry more dust
            fb = nd(nt, "ShaderNodeTexNoise", noise_dimensions="3D"); fb.inputs["Scale"].default_value = 9.0; nt.links.new(obj, fb.inputs[0])
            dfac = mth(nt, "MULTIPLY", dfac, maprange(nt, fb.outputs["Fac"], 0.3, 0.8, 0.3, 1.0))
            I["Base Color"].default_value = base
            nt.links.new(mixcol(nt, dfac, base, (0.34, 0.20, 0.11, 1)), I["Base Color"])
        # weave: two stretched noises as bump height
        wv = nd(nt, "ShaderNodeTexNoise", noise_dimensions="3D"); wv.inputs["Scale"].default_value = 260.0; wv.inputs["Detail"].default_value = 3.0
        nt.links.new(obj, wv.inputs[0])
        bp = nd(nt, "ShaderNodeBump"); nt.links.new(wv.outputs["Fac"], bp.inputs["Height"]); bp.inputs["Strength"].default_value = 0.25; bp.inputs["Distance"].default_value = 0.002
        nt.links.new(bp.outputs[0], I["Normal"])
        rn = nd(nt, "ShaderNodeMapRange"); nt.links.new(wv.outputs["Fac"], rn.inputs[0]); rn.inputs[3].default_value = 0.78; rn.inputs[4].default_value = 0.93
        nt.links.new(rn.outputs[0], I["Roughness"]); I["Specular IOR Level"].default_value = 0.3
    elif kind == "joint": I["Base Color"].default_value = (0.10, 0.10, 0.11, 1); I["Roughness"].default_value = 0.6
    elif kind == "rubber": I["Base Color"].default_value = (0.045, 0.043, 0.042, 1); I["Roughness"].default_value = 0.8
    elif kind == "metal": I["Base Color"].default_value = (0.45, 0.45, 0.47, 1); I["Metallic"].default_value = 0.85; I["Roughness"].default_value = 0.4
    elif kind == "paint": I["Base Color"].default_value = (0.05, 0.12, 0.30, 1); I["Roughness"].default_value = 0.5; I["Specular IOR Level"].default_value = 0.5
    elif kind == "visor": I["Base Color"].default_value = (0.85, 0.60, 0.22, 1); I["Metallic"].default_value = 1.0; I["Roughness"].default_value = 0.06
    return kind
suit_kinds = {}
for o in ao:
    if o.type == "MESH":
        for ms in o.material_slots:
            if ms.material and ms.material.name not in suit_kinds: suit_kinds[ms.material.name] = style_suit(ms.material)
print("suit materials:", suit_kinds)
astro.location = (QA[0][0], QA[0][1], height_at(*QA[0]))
bpy.context.view_layer.update()
mins, maxs = Vector((1e9,) * 3), Vector((-1e9,) * 3)
for o in ao:
    if o.type == "MESH":
        for c in o.bound_box:
            w = o.matrix_world @ Vector(c)
            mins = Vector(map(min, mins, w)); maxs = Vector(map(max, maxs, w))
print("astronaut bbox (m):", tuple(maxs - mins), "min z", mins.z)
H = (maxs - mins).z
SC = 1.75 / H if not (1.5 < H < 2.1) else 1.0
astro.scale = (SC, SC, SC)
ASTRO_YAW = float(os.environ.get("F1_ASTRO_YAW", "0"))     # model forward offset (radians); the walk GLB faces +Y (checked)

# ------------------------------------------------------------------ sky, sun, dust
W = bpy.data.worlds.new("MarsSky"); sc.world = W; W.use_nodes = True
nt = W.node_tree; nt.nodes.clear(); L = nt.links
tc = nt.nodes.new("ShaderNodeTexCoord"); nm = nt.nodes.new("ShaderNodeVectorMath"); nm.operation = "NORMALIZE"
L.new(tc.outputs["Generated"], nm.inputs[0])
sep = nt.nodes.new("ShaderNodeSeparateXYZ"); L.new(nm.outputs[0], sep.inputs[0])
upr = nt.nodes.new("ShaderNodeMapRange"); upr.inputs[1].default_value = -0.05; upr.inputs[2].default_value = 0.75
L.new(sep.outputs["Z"], upr.inputs[0])
cr = nt.nodes.new("ShaderNodeValToRGB"); cr.color_ramp.elements[0].color = (0.62, 0.36, 0.17, 1); cr.color_ramp.elements[1].color = (0.30, 0.19, 0.12, 1)
L.new(upr.outputs[0], cr.inputs[0])
sd = nt.nodes.new("ShaderNodeCombineXYZ"); sd.name = "SunDir"
dot = nt.nodes.new("ShaderNodeVectorMath"); dot.operation = "DOT_PRODUCT"; L.new(nm.outputs[0], dot.inputs[0]); L.new(sd.outputs[0], dot.inputs[1])
gl = nt.nodes.new("ShaderNodeMapRange"); gl.inputs[1].default_value = 0.55; gl.inputs[2].default_value = 1.0; gl.clamp = True
L.new(dot.outputs["Value"], gl.inputs[0])
pw = nt.nodes.new("ShaderNodeMath"); pw.operation = "POWER"; pw.inputs[1].default_value = 2.5; L.new(gl.outputs[0], pw.inputs[0])
bw = nt.nodes.new("ShaderNodeValue"); bw.name = "BlueW"; bw.outputs[0].default_value = 1.0
mw = nt.nodes.new("ShaderNodeMath"); mw.operation = "MULTIPLY"; L.new(pw.outputs[0], mw.inputs[0]); L.new(bw.outputs[0], mw.inputs[1])
mix = nt.nodes.new("ShaderNodeMix"); mix.data_type = "RGBA"; mix.inputs[7].default_value = (0.38, 0.52, 0.80, 1)
L.new(mw.outputs[0], mix.inputs[0]); L.new(cr.outputs[0], mix.inputs[6])
bg = nt.nodes.new("ShaderNodeBackground"); bg.name = "SkyBG"; bg.inputs["Strength"].default_value = 0.9
L.new(mix.outputs[2], bg.inputs["Color"])
# Dust: a homogeneous scattering box around the whole scene (a world volume never terminates, which blacks the render).
wo = nt.nodes.new("ShaderNodeOutputWorld"); L.new(bg.outputs[0], wo.inputs["Surface"])
bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, 0)); box = bpy.context.active_object; box.name = "Dust_haze_box"
box.scale = (16000, 16000, 7000); box.location = (0, 0, 2000); box.display_type = "WIRE"
if ORBITAL:                                    # homogeneous slab over the whole MOLA patch: z -3000..+11100 (11.1 km scale height of the haze)
    box.scale = (700000, 700000, 14100); box.location = (0, 0, 4050)
box.visible_shadow = False
dm = bpy.data.materials.new("mat_dust"); dm.use_nodes = True; dnt = dm.node_tree; dnt.nodes.clear()
vol = dnt.nodes.new("ShaderNodeVolumeScatter"); vol.name = "Dust"; vol.inputs["Color"].default_value = (0.92, 0.90, 0.88, 1)
vol.inputs["Density"].default_value = 4.3e-5; vol.inputs["Anisotropy"].default_value = 0.35
do = dnt.nodes.new("ShaderNodeOutputMaterial"); dnt.links.new(vol.outputs[0], do.inputs["Volume"]); box.data.materials.append(dm)

def sun_vec(el, az):
    e, a = math.radians(el), math.radians(az)          # azimuth clockwise from north: x=E=sin az, y=N=cos az
    return Vector((math.cos(e) * math.sin(a), math.cos(e) * math.cos(a), math.sin(e)))

# Lighting matched to the twin (handoff/A_to_B_README.md section 4, demo/twin/twin.html): tau880 from the Mastcam climatology at the sol's Ls
# (climatological, not a 2025 measurement); direct sun Ks*exp(-tau m), m = min(1/sin el, 10); sky light 0.65*(1-exp(-tau m))*sin(el) of the same flux;
# haze extinction tau/11.1 km; sun disc diameter 0.5332/r_AU deg (0.32-0.38 over the year); blue aureole stronger with a low sun.
TAUJ = json.load(open(os.path.join(ROOT, "demo", "twin", "tau_climatology.json")))
def tau_at(ls):
    x = ((ls - 5.0) % 360.0) / 10.0; i0 = int(x) % 36; f = x - math.floor(x)
    return TAUJ["tau880"][i0] * (1 - f) + TAUJ["tau880"][(i0 + 1) % 36] * f
KS_B, K_DIFF, SKY_REF = 6.5, 0.65, 0.221 / 0.9       # KS_B: Blender sun strength at tau 0 (3.2 at el 42 deg, tau 0.47: the approved exposure); SKY_REF: flat-ground sky term at that same noon -> world strength 0.9
suns = {}; LIGHT = {}
for l in (9, 16):
    s = J["sun"]["lmst%d" % l]; v = sun_vec(s["el"], s["az"])
    tau = tau_at(s["ls"]); se = math.sin(math.radians(s["el"])); m = min(1.0 / max(se, 1e-3), 10.0); tr = math.exp(-tau * m)
    rau = 1.52368 * (1 - 0.0934 ** 2) / (1 + 0.0934 * math.cos(math.radians(s["ls"] - 251)))
    LIGHT[l] = dict(tau=tau, airmass=m, beam=tr, sun=KS_B * tr, sky=K_DIFF * (1 - tr) * se / SKY_REF, disc_deg=0.5332 / rau, rAU=rau)
    ld = bpy.data.lights.new("Sun_LMST%02d" % l, "SUN"); ld.energy = LIGHT[l]["sun"]; ld.angle = math.radians(LIGHT[l]["disc_deg"]); ld.color = (1.0, 0.86, 0.72)
    ob = bpy.data.objects.new("Sun_LMST%02d" % l, ld); sc.collection.objects.link(ob)
    ob.rotation_euler = (-v).to_track_quat("-Z", "Y").to_euler()          # light shines along -Z local, towards -v
    ob["sun_el_deg"] = s["el"]; ob["sun_az_deg_cw_from_north"] = s["az"]; ob["sol"] = FILM["sol"] if ROUTE else 4600; ob["lmst"] = l
    ob["tau880_climatology"] = tau; ob["beam_transmission"] = tr; ob["sun_disc_deg"] = LIGHT[l]["disc_deg"]
    suns[l] = (ob, ld, v, s)
    print("light LMST%d: el %.1f ls %.1f tau %.3f m %.2f beam %.3f sun %.2f sky %.3f disc %.3f deg" % (l, s["el"], s["ls"], tau, m, tr, LIGHT[l]["sun"], LIGHT[l]["sky"], LIGHT[l]["disc_deg"]))

dust_density = vol.inputs["Density"]
BASE_D, EVENT_D = LIGHT[9]["tau"] / 11100.0, 2.2e-3            # base haze = tau / 11.1 km (Smith et al. 2019); the dust event density is SIMULATED
if ORBITAL: BASE_D *= 0.4                                       # thin the haze over the 600 km patch (clearer orbital view)
dust_density.default_value = BASE_D
def key_const(fcurves):
    for fc in fcurves:
        for kp in fc.keyframe_points: kp.interpolation = "CONSTANT"
for name, f0, f1, lmst in SHOTS:
    for l, (ob, ld, v, s_) in suns.items():
        ld.energy = LIGHT[l]["sun"] if l == lmst else 0.0; ld.keyframe_insert("energy", frame=f0)
        if ld.animation_data: key_const(ld.animation_data.action.fcurves)
    for k, c in enumerate("xyz"):
        sd.inputs[k].default_value = suns[lmst][2][k]; sd.inputs[k].keyframe_insert("default_value", frame=f0)
    low = max(0.0, min(1.0, 1.0 - suns[lmst][3]["el"] / 45.0))
    bw.outputs[0].default_value = min(1.0, (0.35 + 0.5 * low) * math.sqrt(min(LIGHT[lmst]["tau"] / 0.6, 2.0)))      # blue aureole: stronger at low sun (twin sky shader)
    bw.outputs[0].keyframe_insert("default_value", frame=f0)
    bg.inputs["Strength"].default_value = 0.9 * LIGHT[lmst]["sky"]; bg.inputs["Strength"].keyframe_insert("default_value", frame=f0)
for _nt in (sd.id_data, bg.id_data):
    if _nt.animation_data: key_const(_nt.animation_data.action.fcurves)
for tree_fc in [sd.id_data.animation_data.action.fcurves] if sd.id_data.animation_data else []: key_const(tree_fc)
# dust event ramp in the dust shot
if not ROUTE:                                                   # (route mode: constant climatological haze, no simulated dust event)
    dn, df0, df1, _ = SHOTS[2]
    for f, d in [(df0 - 1, BASE_D), (df0 + 120, BASE_D), (df0 + 300, EVENT_D), (df1, EVENT_D * 0.9), (SHOTS[3][1] - 1, EVENT_D * 0.9), (SHOTS[3][1], BASE_D)]:
        dust_density.default_value = d; dust_density.keyframe_insert("default_value", frame=f)
    for fc in [x for x in vol.id_data.animation_data.action.fcurves if "Dust" in x.data_path]:
        for kp in fc.keyframe_points: kp.interpolation = "LINEAR"

# ------------------------------------------------------------------ cameras
def make_cam(name, lens):
    cd = bpy.data.cameras.new(name); cd.lens = lens; cd.clip_start = 0.1; cd.clip_end = 100000
    ob = bpy.data.objects.new(name, cd); sc.collection.objects.link(ob)
    tg = bpy.data.objects.new(name + "_target", None); sc.collection.objects.link(tg)
    c = ob.constraints.new("TRACK_TO"); c.target = tg; c.track_axis = "TRACK_NEGATIVE_Z"; c.up_axis = "UP_Y"
    return ob, tg

def key(ob, f, loc):
    ob.location = loc; ob.keyframe_insert("location", frame=f)

def route_idx(q, s_m):
    d = np.r_[0, np.cumsum(np.hypot(*np.diff(q, axis=0).T))]
    s_m = min(max(s_m, 0), d[-1]); return np.array([np.interp(s_m, d, q[:, 0]), np.interp(s_m, d, q[:, 1])])
def pt3(p, up=0.0): return (float(p[0]), float(p[1]), surf_z(p[0], p[1]) + up)
RLEN = float(np.sum(np.hypot(*np.diff(QA, axis=0).T)))

# 1 orbital descent
cam1, tg1 = make_cam("Cam_1_orbital", 28); ORB = []
f0, f1 = SHOTS[0][1], SHOTS[0][2]; start = route_idx(QA, 0); look_end = route_idx(QA, 60)
if ROUTE:
    # route mode: a crane that starts high over the whole route (so the cyan line reads) and comes down behind the walker
    ctr = (QA.min(0) + QA.max(0)) / 2; ext = float(max(np.ptp(QA[:, 0]), np.ptp(QA[:, 1]), 120.0)); n = 16
    s0_ = FILM["start_s"]; p0_ = route_idx(QA, s0_); p1_ = route_idx(QA, s0_ + 1.0); d0_ = (p1_ - p0_) / (np.linalg.norm(p1_ - p0_) + 1e-9)
    cend = p0_ - d0_ * 7.0 + np.array([-d0_[1], d0_[0]]) * 3.2; aend = 1.7
    for k in range(n + 1):
        t = k / n; e = smooth(t); alt = math.exp(lerp(math.log(0.85 * ext + 80.0), math.log(aend + 4.0), e ** 0.8)) - 4.0
        c = (ctr + np.array([0.0, -max(0.9 * ext, 1.3 * (0.85 * ext + 80.0))])) * (1 - e) + cend * e        # horizontal offset >= 1.3 x height: never a top-down view
        f = int(lerp(f0, f1, t)); key(cam1, f, (float(c[0]), float(c[1]), max(alt, aend) + height_at(c[0], c[1]))); ORB.append((f, alt))
        key(tg1, f, pt3(ctr * (1 - e) + (p0_ + d0_ * 1.5) * e, 1.2 * e))
elif not ORBITAL:
    # from 4.5 km above the context patch, swooping down onto the route start
    n = 24
    for k in range(n + 1):
        t = k / n; e = smooth(t); ang = math.radians(215 - 150 * e)
        rad = lerp(3800, 55, e ** 0.9); alt = lerp(4300, 14, e ** 1.6)
        c = start + np.array([math.cos(ang), math.sin(ang)]) * rad
        f = int(lerp(f0, f1, t)); key(cam1, f, (float(c[0]), float(c[1]), alt + height_at(c[0], c[1]))); ORB.append((f, alt))
        tgt = start * (1 - e) + look_end * e
        key(tg1, f, pt3(tgt, 2.0))
else:
    # Gale-scale -> corridor: log-spaced range and height (constant zoom rate), from 90 km above, 110 km NW of the route start, looking south at Mount Sharp, ending on the route start.
    # The aim point slides from the Mount Sharp mound to the route start over the first half of the move; 80 keys, Bezier.
    tS = np.array(MJ["sharp"]); n = 80
    for k in range(n + 1):
        t = k / n; e = smooth(t); ang = math.radians(135 - 60 * smooth(min(1.0, e * 1.15)))
        rad = math.exp(lerp(math.log(110000.0), math.log(55.0), e)); alt = math.exp(lerp(math.log(90000.0), math.log(14.0), e))
        c = start + np.array([math.cos(ang), math.sin(ang)]) * rad
        w_ = smooth(min(1.0, e / 0.38)); g_ = start * (1 - e) + look_end * e
        aim_xy = np.array(tS[:2]) * (1 - w_) + g_ * w_
        aim_z = tS[2] * (1 - w_) + (surf_z(g_[0], g_[1]) + 2.0) * w_
        f = int(lerp(f0, f1, t)); key(cam1, f, (float(c[0]), float(c[1]), alt + height_at(c[0], c[1]))); ORB.append((f, alt))
        key(tg1, f, (float(aim_xy[0]), float(aim_xy[1]), float(aim_z)))
    cam1.data.clip_end = 1.0e6

# 2 walk-along: astronaut walks the approved route at 0.9 m/s (the walk cycle is 40 frames = 1.5 m stride = 0.9 m/s), camera trails beside/behind
cam2, tg2 = make_cam("Cam_2_walk", 35)
cam2b, tg2b = make_cam("Cam_2b_close", 32)          # extra walk-height cameras (not on the timeline markers): close behind the shoulder
cam2c, tg2c = make_cam("Cam_2c_low", 35)            # and low, beside the route
f0, f1 = SHOTS[1][1], SHOTS[1][2]; n = 120
# walk through the measured sol-4544 scan: start 11 m (half the 0.9 m/s x 25 s walk) before the point of the route nearest the scan anchor
_dd = np.r_[0, np.cumsum(np.hypot(*np.diff(QA, axis=0).T))]
VWALK = 0.9                                                                   # m/s, the walk cycle's own speed
if ROUTE:
    s0 = FILM["start_s"]; VWALK = 0.9 * FILM["speedup"]; n = int(min(1500, max(120, (f1 - f0) * VWALK / 24.0 / 2.0)))      # one key every ~2 m
    print("route mode: walk starts at route s = %.1f m of %.1f, speed x%.1f" % (s0, RLEN, FILM["speedup"]))
else:
    _m44 = [m for m in J["meshes"] if m["sol"] == int(os.environ.get("F1_WALK_SCAN", "4544"))][0]
    s0 = max(0.0, float(_dd[int(np.argmin(np.hypot(QA[:, 0] - _m44["e"], QA[:, 1] - _m44["n"])))]) - 0.5 * 0.9 * (f1 - f0) / 24.0)
    print("walk starts at route s = %.1f m of %.1f (scan sol %d)" % (s0, RLEN, _m44["sol"]))
astro.animation_data_clear()
hd = []
TL = 0                                                                        # frames of time-lapse at the start of the walk (route mode); the rest is real speed
if ROUTE:
    TL = int(FILM.get("tl_frames", 0)); TAIL_S0 = float(FILM.get("tail_s0", s0))
    if TL: TAIL_S0 = min(TAIL_S0, RLEN - 0.9 * (f1 - f0 - TL + 1) / 24.0 - 1.5)         # the smoothed, resampled route is a little shorter than the cell polyline
    KEYS = [(0.0, f) for f in sorted(set([int(round(lerp(f0, f0 + TL - 1, k / n))) for k in range(n + 1)] if TL else []) | set(range(f0 + TL, f1 + 1, 4)) | {f1})]
    def S_OF(f): return s0 + (TAIL_S0 - s0) * (f - f0) / TL if f - f0 < TL else min(TAIL_S0 + 0.9 * (f - f0 - TL) / 24.0, RLEN - 1.2)
else:
    KEYS = [(k / n, int(lerp(f0, f1, k / n))) for k in range(n + 1)]
    def S_OF(f): return s0 + VWALK * (f - f0) / 24.0
KEYS = [((f - f0) / max(1, f1 - f0), f) for _, f in KEYS] if ROUTE else KEYS
for t, f in KEYS:
    s = S_OF(f)
    p = route_idx(QA, s); p2 = route_idx(QA, s + 1.0); d = p2 - p; d /= (np.linalg.norm(d) + 1e-9)
    hd.append(math.atan2(d[1], d[0]) - math.pi / 2 + ASTRO_YAW)
hd = np.unwrap(hd)
def drone_cam(p, d, side, kz):
    """time-lapse follow-drone: back and up scaled with the speed-up; pitch limited to ~31 deg (no top-down views), always above the ground"""
    cx = p - d * 22.0 * kz + side * 9.0 * kz; zt = surf_z(p[0], p[1]) + 1.0; hz = float(np.hypot(*(cx - p)))
    zc = max(min(surf_z(cx[0], cx[1]) + 6.0 * kz, zt + 0.6 * hz), height_at(cx[0], cx[1]) + 3.0)
    return (float(cx[0]), float(cx[1]), zc), pt3(p + d * 6.0 * kz, 1.0)
for k, (t, f) in enumerate(KEYS):
    s = S_OF(f)
    p = route_idx(QA, s); p2 = route_idx(QA, s + 1.0); d = p2 - p; d /= (np.linalg.norm(d) + 1e-9)
    key(astro, f, pt3(p, 0.0)); astro.rotation_euler = (0, 0, float(hd[k]))
    astro.keyframe_insert("rotation_euler", frame=f)
    side = np.array([-d[1], d[0]]); back = p - d * 7.0 + side * (3.2 - 2.0 * smooth(t))
    if ROUTE and f - f0 < TL:                                                                                                # time-lapse part: follow-drone, scaled with the speed-up
        kz = min(12.0, max(1.0, FILM["speedup"] / 30.0)); cl_, tl_ = drone_cam(p, d, side, kz); key(cam2, f, cl_); key(tg2, f, tl_)
    else: key(cam2, f, pt3(back, 1.7)); key(tg2, f, pt3(p + d * 1.5, 1.2))
    key(cam2b, f, pt3(p - d * 3.4 + side * 1.1, 1.55)); key(tg2b, f, pt3(p + d * 3.0, 0.9))
    key(cam2c, f, pt3(p + d * 2.0 - side * 5.2, 0.8)); key(tg2c, f, pt3(p + d * 0.3, 0.95))
for ob in (astro, cam2, tg2, cam2b, tg2b, cam2c, tg2c):
    if ob.animation_data:
        for fc in ob.animation_data.action.fcurves:
            for kp in fc.keyframe_points: kp.interpolation = "LINEAR"
for cm, fs in ((cam2, 5.6), (cam2b, 4.0), (cam2c, 4.0)):                     # slight depth of field, focus on the astronaut
    cm.data.dof.use_dof = True; cm.data.dof.focus_object = astro; cm.data.dof.aperture_fstop = fs
if ARMS:                                                                      # walk cycle looped over the whole walk shot
    arm = ARMS[0]; act = bpy.data.actions.get("walk")
    arm.animation_data_create(); arm.animation_data.action = None
    for t_ in list(arm.animation_data.nla_tracks): arm.animation_data.nla_tracks.remove(t_)
    if act is not None:
        tr = arm.animation_data.nla_tracks.new(); st = tr.strips.new("walk_cycle", f0, act)
        st.action_frame_start, st.action_frame_end = 1, 41
        if ROUTE and TL: st.scale = 1.0 / min(FILM["speedup"], 6.0)           # legs run faster in a time-lapse, capped at 6x so they stay readable
        st.repeat = math.ceil((f1 - f0 + 1) / (40.0 * st.scale)) + 1; st.extrapolation = "HOLD_FORWARD"
        print("walk cycle strip", st.frame_start, st.frame_end, "repeat", st.repeat)
        if ROUTE and TL:                                                      # real-speed tail: a second track overrides from frame f0 + TL, one stride per 40 frames
            tr2 = arm.animation_data.nla_tracks.new(); st2 = tr2.strips.new("walk_cycle_real", f0 + TL, act)
            st2.action_frame_start, st2.action_frame_end = 1, 41; st2.repeat = math.ceil((f1 - f0 - TL + 1) / 40.0) + 1; st2.extrapolation = "HOLD_FORWARD"
            st.extrapolation = "NOTHING"; st.repeat = math.ceil(TL / (40.0 * st.scale)); st.blend_type = "REPLACE"

# 3 dust event: low camera, west towards the low sun, dust wall builds
cam3, tg3 = make_cam("Cam_3_dust", 24)
if not ROUTE:
    f0, f1 = SHOTS[2][1], SHOTS[2][2]; n = 16
    base = route_idx(QA, float(_dd[int(np.argmin(np.hypot(QA[:, 0] - [m for m in J["meshes"] if m["sol"] == 4598][0]["e"], QA[:, 1] - [m for m in J["meshes"] if m["sol"] == 4598][0]["n"])))]))   # dust shot starts at the sol-4598 scan
    for k in range(n + 1):
        t = k / n; f = int(lerp(f0, f1, t))
        c = base + np.array([-3.0 * t, 1.0 * t]); az = math.radians(lerp(285, 305, t))
        cb = c - np.array([math.sin(az), math.cos(az)]) * 20.0; key(cam3, f, pt3(cb, 10.0))   # v3: back 20 m, up 10 m (was 1.9 m over a scan edge)
        tgt = c + np.array([math.sin(az), math.cos(az)]) * 400
        key(tg3, f, (float(tgt[0]), float(tgt[1]), height_at(*c) + lerp(14, 40, t)))

# 4 detour: oblique crane over the point where the direct route and the approved route part
if not ROUTE:
    d_all = [np.min(np.hypot(*(QA - p).T)) for p in QD]; kmax = int(np.argmax(d_all))
    div = QD[kmax]; mid = (div + QA[int(np.argmin(np.hypot(*(QA - div).T)))]) / 2
    if J.get("nogo"):                                           # v3: frame the rejected cells and the safe route next to them
        ng = np.mean(np.array(J["nogo"]), 0); mid = (ng + QA[int(np.argmin(np.hypot(*(QA - ng).T)))]) / 2
    cam4, tg4 = make_cam("Cam_4_detour", 24)
    f0, f1 = SHOTS[3][1], SHOTS[3][2]; n = 16
    print("detour divergence point", div, "separation m", max(d_all))
    for k in range(n + 1):
        t = k / n; f = int(lerp(f0, f1, t)); ang = math.radians(250 + 80 * t)
        c = mid + np.array([math.cos(ang), math.sin(ang)]) * lerp(280, 210, t)
        key(cam4, f, (float(c[0]), float(c[1]), height_at(*mid) + lerp(190, 120, t)))
        key(tg4, f, pt3(mid, 0.0))
for ob in ((cam1, tg1) if ROUTE else (cam1, tg1, cam3, tg3, cam4, tg4)):
    if ob.animation_data:
        for fc in ob.animation_data.action.fcurves:
            for kp in fc.keyframe_points: kp.interpolation = "BEZIER"

# route line width: 0.4 m at walking height, ~0.4 % of altitude from the orbit, 1.5 m from the detour crane (shape key 'wide' = 40 m)
def key_width(w, f):
    for sk in SKS:
        sk.value = min(max((w - 0.1) / (40.0 - 0.1), 0.0), 1.0); sk.keyframe_insert("value", frame=f)
for f, alt in ORB: key_width(max(0.1, 0.004 * alt), f)
for nm_, w in (("walk", 0.1), ("dust", 0.1), ("detour", 1.5)):
    sh = [x for x in SHOTS if x[0] == nm_]
    if sh: key_width(w, sh[0][1] - 1); key_width(w, sh[0][2])
for sk in SKS:
    for fc in sk.id_data.animation_data.action.fcurves:
        for kp in fc.keyframe_points: kp.interpolation = "LINEAR"

if ROUTE:
    # overview crane, then the walk cut between walk-level cameras that follow the walker (the time-lapse drone first, if any):
    # real speed: chase 30 %, close behind the shoulder 25 %, low beside the route 25 %, chase again 20 %; time-lapse tail: low, close, chase
    (_, o0, o1, _), (_, w0, w1, _) = SHOTS; cuts = [(o0, cam1, "overview")]
    if TL: cuts.append((w0, cam2, "drone_timelapse")); tw0 = w0 + TL
    else: tw0 = w0
    plan_ = [(0.30, cam2, "chase"), (0.25, cam2b, "close"), (0.25, cam2c, "low"), (0.20, cam2, "chase2")] if not TL else [(0.30, cam2c, "low"), (0.30, cam2b, "close"), (0.40, cam2, "chase")]
    acc = 0.0
    for frac, cm_, nm_ in plan_: cuts.append((tw0 + int(round(acc * (w1 + 1 - tw0))), cm_, nm_)); acc += frac
    for fr_, cm_, nm_ in cuts:
        mk = sc.timeline_markers.new("shot_" + nm_, frame=fr_); mk.camera = cm_; cm_["shot"] = nm_
    cam1["frames"] = "%d-%d" % (o0, o1); print("route camera cuts:", [(f_, n_) for f_, _, n_ in cuts])
else:
    for (name, f0, f1, _), cam in zip(SHOTS, (cam1, cam2, cam3, cam4)):
        mk = sc.timeline_markers.new("shot_" + name, frame=f0); mk.camera = cam
        cam["shot"] = name; cam["frames"] = "%d-%d" % (f0, f1)
sc.camera = cam1; sc.frame_start = 1; sc.frame_end = SHOTS[-1][2]; sc.frame_set(1 if ROUTE else 250)

# ------------------------------------------------------------------ render settings
sc.render.engine = "CYCLES"; sc.render.fps = 24
sc.render.resolution_x, sc.render.resolution_y = 1920, 1080          # F2 default; the test launcher overrides
cy = sc.cycles; cy.samples = 128; cy.use_denoising = True; cy.denoiser = "OPTIX"; cy.device = "GPU"
cy.volume_step_rate = 1.0; cy.volume_max_steps = 256; cy.max_bounces = 4; cy.volume_bounces = 1
VT = os.environ.get("F1_VIEW", "AgX"); sc.view_settings.view_transform = VT
try: sc.view_settings.look = os.environ.get("F1_LOOK", "AgX - Medium High Contrast")
except TypeError: sc.view_settings.look = "None"
sc.view_settings.exposure = float(os.environ.get("F1_EXPOSURE", "-0.3")); sc.view_settings.gamma = 1.0
bpy.data.objects["Terrain_corridor_1m"]["credit"] = "HiRISE DTM/ortho: NASA/JPL/UArizona; Curiosity Navcam meshes and model: NASA/JPL-Caltech"
if msl is not None: msl["credit"] = "Curiosity model: NASA/JPL-Caltech (Mars Science Laboratory)"
sc["note"] = "Shots on one timeline (24 fps): " + str(SHOTS) + ". Timeline markers bind the cameras. Dust event is SIMULATED."
out = os.environ.get("F1_OUT_BLEND") or os.path.join(ROOT, "film", "marswalk_scene_orbital.blend" if ORBITAL else "marswalk_scene.blend")
bpy.ops.wm.save_as_mainfile(filepath=out)
print("saved", out)
