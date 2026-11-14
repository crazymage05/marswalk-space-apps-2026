"""
MARSWALK B-W5a: rig demo/twin/models/markIII_suit_plain.glb and build a Mars walk cycle + idle loop.

    python tools/run_blender.py w5a tools/w5a_rig.py            (holds the GPU lock; this script itself is CPU only)
    blender -b --python tools/w5a_rig.py

Output: demo/twin/models/markIII_suit_walk.glb  (armature "Armature", 17 bones, actions "walk" and "idle").
The rig frame: +Y is forward (the suit faces +Y), Z up, feet soles on z = 0, hips centred on x = y = 0.

Gait (all numbers printed at the end and written to tools/w5a_gait.json):
  g = 3.71 m/s^2, leg length L = 0.88 m (hip joint height of this mesh), design speed v = 0.9 m/s
  Froude number Fr = v^2/(g L) = 0.25   (walk-run transition at Fr ~ 0.5, so this is a normal walk)
  Earth reference cadence at 0.9 m/s: 0.86 strides/s; Mars = 0.70 x Earth (about sqrt(g_M/g_E) = 0.615 to 0.7)
  -> f = 0.60 strides/s (T = 40 frames at 24 fps = 1.667 s), stride = v/f = 1.50 m, step = 0.75 m
  duty factor beta = 0.57; stance foot moves back at exactly v, so ankle world position is constant in stance.
"""
import bpy, sys, os, json, math
import numpy as np
from mathutils import Matrix, Vector

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # repo root
SRC = os.path.join(ROOT, "demo", "twin", "models", "markIII_suit_plain.glb")
OUT = os.environ.get("W5B_OUT", os.path.join(ROOT, "demo", "twin", "models", "markIII_suit_walk.glb"))
BLEND = os.environ.get("W5A_BLEND", "")          # optional: save the rigged scene for inspection

FPS = 24
V = 0.9                    # m/s, planner flat speed
G_MARS = 3.71
F_EARTH = 0.86             # strides/s at 0.9 m/s on Earth
F_RATIO = 0.70
WALK_FRAMES = 40           # 1.667 s -> f = 0.60 strides/s
IDLE_FRAMES = 96           # 4.0 s breathing loop
BETA = 0.57                # duty factor
LIFT = 0.13                # swing foot clearance (m)
ARM_SWING = math.radians(15)
HIP_X = 0.145

# ----------------------------------------------------------------------------- scene + mesh
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=SRC)
mesh_obj = [o for o in bpy.data.objects if o.type == 'MESH'][0]
mesh_obj.name = "MarkIII_suit"
mw = mesh_obj.matrix_world.copy()
mesh_obj.data.transform(mw)
mesh_obj.matrix_world = Matrix.Identity(4)
co = np.array([tuple(v.co) for v in mesh_obj.data.vertices])
shift = Vector((0.06, -0.36, -co[:, 2].min()))      # hip centre (measured from leg slices) to origin, soles to z = 0
mesh_obj.data.transform(Matrix.Translation(shift))
co = np.array([tuple(v.co) for v in mesh_obj.data.vertices])
print("MESH bounds after shift", co.min(0).round(3), co.max(0).round(3), "verts", len(co))

# ----------------------------------------------------------------------------- armature (rest = the suit's own pose)
# joint positions measured from the mesh: leg slices (hip 0.88, knee 0.52, ankle 0.16), side and top views for arms.
J = dict(
    hips=((0, 0, 0.88), (0, 0, 1.10)),
    spine=((0, 0, 1.10), (0, 0, 1.32)),
    chest=((0, 0, 1.32), (0, 0, 1.58)),
    neck=((0, 0, 1.58), (0, 0.02, 1.68)),
    head=((0, 0.02, 1.68), (0, 0.02, 1.99)),
)
SH = {"L": (-0.29, 0.00, 1.47), "R": (0.28, 0.00, 1.47)}
EL = {"L": (-0.45, 0.30, 1.31), "R": (0.50, 0.21, 1.35)}
WR = {"L": (-0.27, 0.62, 1.08), "R": (0.53, 0.44, 1.08)}
HA = {"L": (-0.26, 0.74, 1.04), "R": (0.53, 0.54, 1.05)}
for s, sx in (("L", -1), ("R", 1)):
    J[f"upper_arm.{s}"] = (SH[s], EL[s]); J[f"forearm.{s}"] = (EL[s], WR[s]); J[f"hand.{s}"] = (WR[s], HA[s])
    hx = sx * HIP_X
    J[f"upper_leg.{s}"] = ((hx, 0, 0.88), (hx, 0, 0.52))
    J[f"lower_leg.{s}"] = ((hx, 0, 0.52), (hx, -0.02, 0.16))
    J[f"foot.{s}"] = ((hx, -0.02, 0.16), (hx, 0.37, 0.04))
PARENT = {"hips": None, "spine": "hips", "chest": "spine", "neck": "chest", "head": "neck"}
CONNECT = {"spine", "chest", "neck", "head"}
for s in "LR":
    PARENT.update({f"upper_arm.{s}": "chest", f"forearm.{s}": f"upper_arm.{s}", f"hand.{s}": f"forearm.{s}",
                   f"upper_leg.{s}": "hips", f"lower_leg.{s}": f"upper_leg.{s}", f"foot.{s}": f"lower_leg.{s}"})
    CONNECT |= {f"forearm.{s}", f"hand.{s}", f"lower_leg.{s}", f"foot.{s}"}
ORDER = ["hips", "spine", "chest", "neck", "head"] + [f"{p}.{s}" for s in "LR" for p in
         ("upper_arm", "forearm", "hand", "upper_leg", "lower_leg", "foot")]

arm_data = bpy.data.armatures.new("Armature")
arm_obj = bpy.data.objects.new("Armature", arm_data)
bpy.context.scene.collection.objects.link(arm_obj)
bpy.context.view_layer.objects.active = arm_obj
bpy.ops.object.mode_set(mode='EDIT')
for name in ORDER:
    eb = arm_data.edit_bones.new(name)
    eb.head, eb.tail = Vector(J[name][0]), Vector(J[name][1])
for name in ORDER:
    p = PARENT[name]
    if p:
        arm_data.edit_bones[name].parent = arm_data.edit_bones[p]
        arm_data.edit_bones[name].use_connect = name in CONNECT
bpy.ops.object.mode_set(mode='OBJECT')
RESTW = {b.name: np.array(b.matrix_local) for b in arm_data.bones}   # armature-space rest matrices
print("BONES", len(arm_data.bones))

# ----------------------------------------------------------------------------- skinning: smooth spatial weight field (W5b)
# W5a used the 3 nearest bones with a hard cut-off; neighbouring shells and neighbouring triangles could land on different
# bones, so the cloth tore at the knees, hips and shoulders (max edge stretch 54x). Here the weight of every vertex is a pure,
# smooth function of its REST POSITION (so overlapping shells at the same place move identically):
#   w_k  proportional to exp(-(d_k - d_min) / SIGMA),  d_k = distance to bone segment k (capsule field) + smooth side penalties
# Joint blends then widen with the limb radius (like a bone-heat solution on a capsule proxy of the body). Boots stay rigid to
# the foot bone; arm bones are only claimed within ~10-18 cm of the arm chain; at most 4 influences, with the 5th-largest
# weight subtracted before normalising so dropping the small ones is continuous.
for o in bpy.data.objects: o.select_set(False)
bone_names = set(arm_data.bones.keys())
SIGMA = float(os.environ.get("W5B_SIGMA", "0.06")); SIGMA_T = float(os.environ.get("W5B_SIGMA_T", "0.07"))
RAMP0, RAMP1 = float(os.environ.get("W5B_R0", "0.88")), float(os.environ.get("W5B_R1", "1.16"))
BOOT0, BOOT1 = float(os.environ.get("W5B_B0", "0.20")), float(os.environ.get("W5B_B1", "0.40"))
WEIGHT_METHOD = "smooth capsule-field softmax (sigma %.3f limb / %.3f torso m), shell-aware, 4 influences, rigid soles" % (SIGMA, SIGMA_T)
mesh_obj.vertex_groups.clear()
for n in ORDER: mesh_obj.vertex_groups.new(name=n)
heads = {n: np.array(J[n][0]) for n in ORDER}; tails = {n: np.array(J[n][1]) for n in ORDER}
sstep = lambda x, a, b: (lambda t: t * t * (3 - 2 * t))(np.clip((x - a) / (b - a), 0, 1))


def seg_dist(P, a, b):
    ab = b - a; t = np.clip(((P - a) @ ab) / (ab @ ab), 0, 1)
    return np.linalg.norm(P - (a + t[:, None] * ab), axis=1)


SKIN_BONES = [n for n in ORDER if not n.startswith("foot")]          # feet are handled by the boot rule below
D = {n: seg_dist(co, heads[n], tails[n]) for n in ORDER}
# --- shells: weld coincident vertices (0.5 mm), find connected shells, classify limb shells by nearest-bone vote.
# Sleeves and trouser legs are separate shells that touch the torso in the rest pose; letting the torso field claim them
# (or the arm field claim torso skin next to the sleeve) is what tore the cloth. A limb shell is skinned only to its own
# limb bones plus a smooth share of the parent bone near the joint.
mdata = mesh_obj.data
key = np.round(co * 2000).astype(np.int64)
_, winv = np.unique(key, axis=0, return_inverse=True); winv = winv.ravel()
eds = np.empty(len(mdata.edges) * 2, dtype=np.int32); mdata.edges.foreach_get("vertices", eds); eds = eds.reshape(-1, 2)
par = list(range(int(winv.max()) + 1))
def _f(a_):
    while par[a_] != a_: par[a_] = par[par[a_]]; a_ = par[a_]
    return a_
for a_, b_ in winv[eds]:
    ra, rb = _f(a_), _f(b_)
    if ra != rb: par[ra] = rb
shell = np.array([_f(i) for i in winv])
GROUPS = {"armL": ["upper_arm.L", "forearm.L", "hand.L"], "armR": ["upper_arm.R", "forearm.R", "hand.R"],
          "legL": ["upper_leg.L", "lower_leg.L", "foot.L"], "legR": ["upper_leg.R", "lower_leg.R", "foot.R"]}
ROOT_OF = {"armL": ("chest", np.array(SH["L"])), "armR": ("chest", np.array(SH["R"])),
           "legL": ("hips", np.array([-HIP_X, 0, 0.88])), "legR": ("hips", np.array([HIP_X, 0, 0.88]))}
bone_grp = {n: g for g, l in GROUPS.items() for n in l}
near = np.argmin(np.stack([D[n] for n in ORDER], 1), 1)
shell_grp = {}
for sid in np.unique(shell):
    m_ = shell == sid; votes = {}
    for k in near[m_]: votes[bone_grp.get(ORDER[k], "torso")] = votes.get(bone_grp.get(ORDER[k], "torso"), 0) + 1
    g, c_ = max(votes.items(), key=lambda kv: kv[1]); shell_grp[sid] = g if (g != "torso" and c_ >= 0.6 * m_.sum()) else "torso"
print("SHELLS", len(shell_grp), {g: sum(1 for v in shell_grp.values() if v == g) for g in ["torso"] + list(GROUPS)})
vgrp = np.array([shell_grp[x] for x in shell])
W = np.zeros((len(co), len(SKIN_BONES)))
idx = {n: i for i, n in enumerate(SKIN_BONES)}
# limb shells
for g, bones in GROUPS.items():
    m_ = vgrp == g
    if not m_.any(): continue
    lb = [n for n in bones if n in idx]; root, rp = ROOT_OF[g]
    dm_ = np.stack([D[n][m_] for n in lb], 1); Wl = np.exp(-(dm_ - dm_.min(1, keepdims=True)) / SIGMA); Wl /= Wl.sum(1, keepdims=True)
    c_ = 0.92 * (1 - sstep(np.linalg.norm(co[m_] - rp, axis=1), 0.03, 0.22))        # share of the parent bone near the joint
    for j, n in enumerate(lb): W[np.where(m_)[0], idx[n]] = Wl[:, j] * (1 - c_)
    W[np.where(m_)[0], idx[root]] = c_
# torso / head / rings: never the arm bones; leg bones only near the hip, fading in smoothly
m_ = vgrp == "torso"
if m_.any():
    allowed = [n for n in SKIN_BONES if bone_grp.get(n, "torso") in ("torso", "legL", "legR")]
    Dt = {n: D[n][m_].copy() for n in allowed}
    zt = co[m_, 2]; xt = co[m_, 0]
    for s_ in "LR":
        sx_ = -1.0 if s_ == "L" else 1.0
        side = sstep(-sx_ * xt, 0.0, 0.10) * (zt < 0.95)
        for pn in ("upper_leg", "lower_leg"): Dt[f"{pn}.{s_}"] += 0.06 * side + 0.20 * sstep(zt, RAMP0, RAMP1)
    dm_ = np.stack([Dt[n] for n in allowed], 1); Wt = np.exp(-(dm_ - dm_.min(1, keepdims=True)) / SIGMA_T); Wt /= Wt.sum(1, keepdims=True)
    for j, n in enumerate(allowed): W[np.where(m_)[0], idx[n]] = Wt[:, j]
# boots: rigid foot below the ankle, blended into the shin over 10 cm
sd = np.where(co[:, 0] < 0, 0, 1)
wf = 1 - sstep(co[:, 2], BOOT0, BOOT1)
# keep at most 4 influences, continuously (subtract the 5th largest weight)
def limit4(Wm):
    srt = -np.sort(-Wm, 1); cut = srt[:, 4:5] if Wm.shape[1] > 4 else 0
    Wm = np.maximum(Wm - cut, 0); return Wm / Wm.sum(1, keepdims=True)
# shin weights for the boot blend come from the same field but with the foot's share removed first
Wf = limit4(W)
for i in range(len(co)):
    items = {}
    for k, n in enumerate(SKIN_BONES):
        if Wf[i, k] * (1 - wf[i]) > 1e-4: items[n] = Wf[i, k] * (1 - wf[i])
    if wf[i] > 0: items["foot." + "LR"[sd[i]]] = items.get("foot." + "LR"[sd[i]], 0) + float(wf[i])
    tot = sum(items.values())
    if len(items) > 4:                                                     # boots: foot + up to 3 shin bones, drop the smallest
        items = dict(sorted(items.items(), key=lambda kv: -kv[1])[:4]); tot = sum(items.values())
    for n, w in items.items(): mesh_obj.vertex_groups[n].add([i], float(w / tot), 'REPLACE')
m = mesh_obj.modifiers.new("Armature", 'ARMATURE'); m.object = arm_obj; mesh_obj.parent = arm_obj
print("WEIGHT_METHOD:", WEIGHT_METHOD)

# ----------------------------------------------------------------------------- pose machinery
LEN = {n: float(np.linalg.norm(np.array(J[n][1]) - np.array(J[n][0]))) for n in ORDER}
REST_R = {n: RESTW[n][:3, :3] for n in ORDER}
REST_H = {n: RESTW[n][:3, 3] for n in ORDER}


def rot_axis(axis, ang):
    axis = axis / np.linalg.norm(axis); c, s = math.cos(ang), math.sin(ang); x, y, z = axis
    return np.array([[c + x*x*(1-c), x*y*(1-c) - z*s, x*z*(1-c) + y*s],
                     [y*x*(1-c) + z*s, c + y*y*(1-c), y*z*(1-c) - x*s],
                     [z*x*(1-c) - y*s, z*y*(1-c) + x*s, c + z*z*(1-c)]])


def rot_between(a, b):
    a = a / np.linalg.norm(a); b = b / np.linalg.norm(b); c = float(a @ b)
    if c > 0.999999: return np.eye(3)
    if c < -0.999999:
        ax = np.cross(a, [1, 0, 0]); ax = ax if np.linalg.norm(ax) > 1e-6 else np.cross(a, [0, 1, 0]); return rot_axis(ax, math.pi)
    return rot_axis(np.cross(a, b), math.acos(c))


RX = lambda a: rot_axis(np.array([1.0, 0, 0]), a)
RZ = lambda a: rot_axis(np.array([0, 0, 1.0]), a)


def rest_dir(n): return REST_R[n][:, 1]


def pose_frame(pelvis, torso, dirs):
    """pelvis: head position of hips. torso: {bone: 3x3 absolute orientation delta applied to the rest orientation}.
    dirs: {bone: world direction} for limb bones (swing from the rest orientation).  Returns {bone: 4x4 armature matrix}."""
    M = {}
    for n in ORDER:
        p = PARENT[n]
        if n == "hips":
            head = np.array(pelvis)
        elif n in CONNECT:
            head = M[p][:3, 3] + M[p][:3, 1] * LEN[p]
        else:
            Rp = M[p][:3, :3] @ REST_R[p].T
            head = M[p][:3, 3] + Rp @ (REST_H[n] - REST_H[p])
        if n in dirs:
            R = rot_between(rest_dir(n), dirs[n]) @ REST_R[n]
        else:
            R = torso.get(n, np.eye(3)) @ REST_R[n]
        m = np.eye(4); m[:3, :3] = R; m[:3, 3] = head; M[n] = m
    return M


def two_bone_ik(hip, ankle, l1, l2, pole=np.array([0, 1.0, 0])):
    d = np.linalg.norm(ankle - hip); d = min(d, (l1 + l2) * 0.9999); u = (ankle - hip) / np.linalg.norm(ankle - hip)
    ca = (l1 * l1 + d * d - l2 * l2) / (2 * l1 * d); sa = math.sqrt(max(0, 1 - ca * ca))
    n = pole - (pole @ u) * u; n /= np.linalg.norm(n)
    knee = hip + l1 * (ca * u + sa * n)
    return knee, hip + u * d


def apply_pose(M, frame, with_loc_for=("hips",)):
    for n in ORDER:
        pb = arm_obj.pose.bones[n]; pb.rotation_mode = 'QUATERNION'
        rest = Matrix(RESTW[n].tolist()); want = Matrix(M[n].tolist())
        if PARENT[n]:
            rel = Matrix(RESTW[PARENT[n]].tolist()).inverted() @ rest
            basis = (Matrix(M[PARENT[n]].tolist()) @ rel).inverted() @ want
        else:
            basis = rest.inverted() @ want
        loc, q, _ = basis.decompose()
        pb.rotation_quaternion = q
        pb.location = loc if n in with_loc_for else (0, 0, 0)
        pb.keyframe_insert("rotation_quaternion", frame=frame, group=n)
        if n in with_loc_for: pb.keyframe_insert("location", frame=frame, group=n)


# ----------------------------------------------------------------------------- gait generation
L_LEG = 0.88
T_WALK = WALK_FRAMES / FPS
F_WALK = 1.0 / T_WALK
STRIDE = V / F_WALK
S_STANCE = V * BETA * T_WALK          # ankle travel during stance (relative to hips) so the foot is world-fixed
ANKLE_Z = 0.16
REACH = 0.705                          # max hip-ankle distance used (leaves a little knee flex)
L1, L2 = LEN["upper_leg.L"], LEN["lower_leg.L"]
print("LEG LEN", L1, L2, "STANCE", S_STANCE, "STRIDE", STRIDE)


def foot_state(phi):
    """returns (y, lift, pitch, in_stance) of the ankle for a leg whose heel strike is at phi = 0."""
    phi %= 1.0
    if phi < BETA:
        u = phi / BETA
        return S_STANCE / 2 - S_STANCE * u, 0.0, 0.0, True
    u = (phi - BETA) / (1 - BETA)
    y = -S_STANCE / 2 + S_STANCE * (0.5 - 0.5 * math.cos(math.pi * u))
    # swing: toe lifts slightly before heel strike, flat again at touchdown (stance foot stays flat so the sole does not slide)
    pitch = math.radians(8) * math.sin(math.pi * min(max((u - 0.3) / 0.7, 0.0), 1.0))
    return y, LIFT * math.sin(math.pi * u) ** 1.3, pitch, False


def pelvis_height_curve(n=800):
    """Pelvis height so that every stance leg stays within REACH: min over stance legs, then circular smoothing."""
    ph = np.arange(n) / n; z = np.zeros(n)
    for i, p in enumerate(ph):
        zs = []
        for off in (0.0, 0.5):
            y, lift, _, st = foot_state(p + off)
            if st: zs.append(ANKLE_Z + math.sqrt(max(REACH ** 2 - y ** 2 - 0.0 ** 2, 0.01)))
        z[i] = min(zs) if zs else ANKLE_Z + REACH
    k = int(n * 0.06); ker = np.hanning(2 * k + 1); ker /= ker.sum()
    zz = np.convolve(np.concatenate([z[-k:], z, z[:k]]), ker, mode="same")[k:-k]
    return ph, zz - 0.004


PH_C, Z_C = pelvis_height_curve()
pelvis_z = lambda phi: float(np.interp(phi % 1.0, PH_C, Z_C, period=1.0))


def walk_pose(phi):
    zp = pelvis_z(phi)
    yaw = math.radians(4.0) * math.sin(2 * math.pi * phi + 0.0)          # pelvis yaw, + = left hip forward
    xp = -0.022 * math.sin(2 * math.pi * phi)                              # lateral sway toward the stance leg
    pelvis = np.array([xp, 0.0, zp])
    torso = {"hips": RZ(yaw), "spine": RZ(-0.5 * yaw) @ RX(math.radians(-3.0)),
             "chest": RZ(-1.4 * yaw) @ RX(math.radians(-3.0)), "neck": RZ(1.0 * yaw), "head": RZ(1.0 * yaw)}
    dirs = {}
    # hip points depend on the pelvis pose: compute a first pass for the torso/hip frame
    M0 = pose_frame(pelvis, torso, {})
    for s, sx, off in (("L", -1, 0.0), ("R", 1, 0.5)):
        hipp = M0[f"upper_leg.{s}"][:3, 3]
        y, lift, pitch, _ = foot_state(phi + off)
        ankle = np.array([sx * HIP_X, y - 0.02, ANKLE_Z + lift])
        knee, ank = two_bone_ik(hipp, ankle, L1, L2)
        dirs[f"upper_leg.{s}"] = knee - hipp; dirs[f"lower_leg.{s}"] = ank - knee
        fd = np.array([0, 0.37 - (-0.02), 0.04 - 0.16]); fd /= np.linalg.norm(fd)
        dirs[f"foot.{s}"] = RX(pitch) @ fd
        # arms: opposite swing to the same-side leg (L arm back when L leg is forward at phi = 0)
        sw = (-1 if s == "L" else 1) * ARM_SWING * math.cos(2 * math.pi * phi)
        ua = np.array([sx * 0.14, 0.10, -0.98]); ua /= np.linalg.norm(ua)
        ua_s = RX(sw) @ ua
        flex = math.radians(20) + math.radians(10) * (sw / ARM_SWING)
        fa = RX(flex) @ ua_s; ha = RX(math.radians(8)) @ fa
        dirs[f"upper_arm.{s}"], dirs[f"forearm.{s}"], dirs[f"hand.{s}"] = ua_s, fa, ha
    return pose_frame(pelvis, torso, dirs)


def idle_pose(phi):
    br = math.sin(2 * math.pi * phi)                                       # breathing
    zp = 0.872 + 0.002 * br
    pelvis = np.array([0.0, 0.0, zp])
    torso = {"spine": RX(math.radians(0.6) * br), "chest": RX(math.radians(1.6) * br), "neck": RX(math.radians(-0.8) * br),
             "head": RX(math.radians(0.5) * math.sin(2 * math.pi * phi + 1.0))}
    dirs = {}
    M0 = pose_frame(pelvis, torso, {})
    for s, sx in (("L", -1), ("R", 1)):
        hipp = M0[f"upper_leg.{s}"][:3, 3]
        ankle = np.array([sx * HIP_X, -0.02, ANKLE_Z])
        knee, ank = two_bone_ik(hipp, ankle, L1, L2)
        dirs[f"upper_leg.{s}"] = knee - hipp; dirs[f"lower_leg.{s}"] = ank - knee
        fd = np.array([0, 0.39, -0.12]); dirs[f"foot.{s}"] = fd
        ua = np.array([sx * 0.14, 0.06, -0.98]); ua /= np.linalg.norm(ua)
        ua_s = RX(math.radians(1.0) * br) @ ua
        fa = RX(math.radians(18)) @ ua_s; ha = RX(math.radians(8)) @ fa
        dirs[f"upper_arm.{s}"], dirs[f"forearm.{s}"], dirs[f"hand.{s}"] = ua_s, fa, ha
    return pose_frame(pelvis, torso, dirs)


def make_action(name, nframes, fn):
    act = bpy.data.actions.new(name); act.use_fake_user = True
    arm_obj.animation_data_create(); arm_obj.animation_data.action = act
    for f in range(nframes + 1):                                            # last key == first key: closed loop
        apply_pose(fn((f % nframes) / nframes), f)
    for fc in act.fcurves:
        for kp in fc.keyframe_points: kp.interpolation = 'LINEAR'
    act.use_frame_range = True; act.frame_start = 0; act.frame_end = nframes
    return act


for pb in arm_obj.pose.bones: pb.rotation_mode = 'QUATERNION'
act_walk = make_action("walk", WALK_FRAMES, walk_pose)
act_idle = make_action("idle", IDLE_FRAMES, idle_pose)
arm_obj.animation_data.action = act_walk
bpy.context.scene.render.fps = FPS
bpy.context.scene.frame_start = 0; bpy.context.scene.frame_end = WALK_FRAMES

gait = dict(g_mars=G_MARS, leg_length_m=L_LEG, speed_mps=V, froude=V ** 2 / (G_MARS * L_LEG),
            froude_transition=0.5, vmax_walk_mps=math.sqrt(0.5 * G_MARS * L_LEG),
            earth_strides_per_s=F_EARTH, mars_over_earth=F_RATIO, mars_strides_per_s=F_WALK,
            cycle_s=T_WALK, cycle_frames=WALK_FRAMES, fps=FPS, stride_m=STRIDE, step_m=STRIDE / 2,
            duty_factor=BETA, stance_ankle_travel_m=S_STANCE, swing_clearance_m=LIFT,
            pelvis_height_min_m=float(Z_C.min()), pelvis_height_max_m=float(Z_C.max()),
            arm_swing_deg=math.degrees(ARM_SWING), idle_cycle_s=IDLE_FRAMES / FPS,
            weights=WEIGHT_METHOD, bones=len(arm_data.bones))
json.dump(gait, open(os.path.join(ROOT, "tools", "w5b", "w5b_gait.json"), "w"), indent=1)
print("GAIT", json.dumps(gait))

if BLEND:
    bpy.ops.wm.save_as_mainfile(filepath=BLEND)


# ----------------------------------------------------------------------------- materials (W5b)
# W5a left metallic/roughness unset, which glTF reads as metallic 1 / roughness 1: every part rendered as dull grey metal.
MKEY = {"steel2SG": ("steel", (0.56, 0.56, 0.58), 0.30, 0.45), "blinn2SG": ("ring", (0.40, 0.40, 0.42), 0.35, 0.45),
        "bodyrings_blinn2SG": ("ring", (0.40, 0.40, 0.42), 0.35, 0.45), "bodyrings_steelholesSG": ("ring", (0.45, 0.45, 0.48), 0.40, 0.45),
        "blinn1SG": ("visor", (0.015, 0.018, 0.024), 0.25, 0.08), "lambert2SG": ("fabric", (0.80, 0.78, 0.73), 0.0, 0.75),
        "lambert5SG": ("tex", None, 0.0, 0.8), "lambert3SG": ("rubber", (0.12, 0.12, 0.12), 0.0, 0.85),
        "lambert4SG": ("sole", (0.30, 0.30, 0.30), 0.0, 0.85), "suitcolormappedlegsSG": ("fabric", (0.80, 0.78, 0.73), 0.0, 0.75),
        "bluesteelSG": ("blue", (0.14, 0.32, 0.83), 0.2, 0.5), "hand_lambert2SG": ("fabric", (0.80, 0.78, 0.73), 0.0, 0.75),
        "lambert6SG": ("fabric", (0.82, 0.80, 0.78), 0.0, 0.75), "markiiitorso_lambert2SG": ("fabric", (0.80, 0.78, 0.73), 0.0, 0.75)}


def style(mat, color, metal, rough):
    mat.use_nodes = True; b = mat.node_tree.nodes.get("Principled BSDF")
    if color is not None: b.inputs["Base Color"].default_value = (*color, 1)
    b.inputs["Metallic"].default_value = metal; b.inputs["Roughness"].default_value = rough
    mat.use_backface_culling = False


for mat in mesh_obj.data.materials:
    key = mat.name.split("_")[-1] if "bodyrings" not in mat.name else mat.name
    key = [k for k in MKEY if mat.name.endswith(k)][0]
    if mat.name.startswith("MKIII:bodyrings"): key = "bodyrings_blinn2SG" if "blinn" in mat.name else "bodyrings_steelholesSG"
    if mat.name.endswith("MarkIII_8sizedwithoutskeleton_blinn2SG") or mat.name.endswith("withoutskeleton_blinn2SG"): key = "blinn2SG"
    _, col, me_, ro = MKEY[key]; style(mat, col, me_, ro)

# ----------------------------------------------------------------------------- PLSS backpack (same numbers as tools/f2_suitfix.py)
arm_obj.data.pose_position = "REST"; bpy.context.view_layer.update()
mat_white = [m for m in mesh_obj.data.materials if m.name.endswith("markiiitorso_lambert2SG")][0]
mat_steel = [m for m in mesh_obj.data.materials if m.name.endswith("_steel2SG") and "steelholes" not in m.name][0]
mat_dark = bpy.data.materials.new("plss_vent"); mat_dark.use_nodes = True; style(mat_dark, (0.05, 0.05, 0.055), 0.0, 0.6)


def box(name, size, centre, mat, bevel):
    me = bpy.data.meshes.new(name); sx, sy, sz = (q / 2 for q in size)
    v = [(x, y, z) for x in (-sx, sx) for y in (-sy, sy) for z in (-sz, sz)]
    f = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    me.from_pydata(v, [], f); me.update(); ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob); me.materials.append(mat)
    for p_ in me.polygons: p_.use_smooth = True
    m_ = ob.modifiers.new("bevel", "BEVEL"); m_.width = bevel; m_.segments = 5
    ob.modifiers.new("smooth", "WEIGHTED_NORMAL")
    bpy.context.view_layer.update()
    me2 = bpy.data.meshes.new_from_object(ob.evaluated_get(bpy.context.evaluated_depsgraph_get()))   # bake the bevel
    ob.modifiers.clear(); ob.data = me2
    for p_ in me2.polygons: p_.use_smooth = True
    ob.parent = arm_obj; ob.parent_type = "BONE"; ob.parent_bone = "chest"
    bpy.context.view_layer.update(); ob.matrix_world = Matrix.Translation(Vector(centre))
    return ob


bk = co[(co[:, 2] > 1.2) & (co[:, 2] < 1.45) & (abs(co[:, 0]) < 0.2)]
print("BACK SURFACE y at chest height (min):", bk[:, 1].min())
back_y = -0.33
parts = [box("PLSS", (0.60, 0.28, 0.82), (0, back_y - 0.13, 1.22), mat_white, 0.07),
         box("PLSS_band_top", (0.62, 0.22, 0.04), (0, back_y - 0.14, 1.50), mat_steel, 0.012),
         box("PLSS_band_low", (0.62, 0.22, 0.04), (0, back_y - 0.14, 0.92), mat_steel, 0.012),
         box("PLSS_hose", (0.40, 0.03, 0.03), (0, back_y - 0.285, 1.40), mat_dark, 0.010)]
arm_obj.data.pose_position = "POSE"; bpy.context.view_layer.update()

# ----------------------------------------------------------------------------- export
for o in bpy.data.objects: o.select_set(False)
mesh_obj.select_set(True); arm_obj.select_set(True)
for o in parts: o.select_set(True)
bpy.ops.export_scene.gltf(filepath=OUT, export_format='GLB', use_selection=True, export_animations=True,
                          export_animation_mode='ACTIONS', export_skins=True, export_apply=False,
                          export_force_sampling=True, export_optimize_animation_size=False, export_yup=True)
print("EXPORTED", OUT, os.path.getsize(OUT))
