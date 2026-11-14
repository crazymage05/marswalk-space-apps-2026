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

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # repo root
SRC = os.path.join(ROOT, "demo", "twin", "models", "markIII_suit_plain.glb")
OUT = os.path.join(ROOT, "demo", "twin", "models", "markIII_suit_walk.glb")
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

# ----------------------------------------------------------------------------- skinning: automatic weights, fallback nearest-bone
for o in bpy.data.objects: o.select_set(False)
mesh_obj.select_set(True); arm_obj.select_set(True)
bpy.context.view_layer.objects.active = arm_obj
WEIGHT_METHOD = "automatic (bone heat)"
try:
    bpy.ops.object.parent_set(type='ARMATURE_AUTO')
except Exception as e:
    print("AUTO WEIGHTS RAISED", e); WEIGHT_METHOD = "FAILED"
bone_names = set(arm_data.bones.keys())
vg_idx = {vg.index: vg.name for vg in mesh_obj.vertex_groups}


def unweighted_count():
    n = 0
    for v in mesh_obj.data.vertices:
        if sum(g.weight for g in v.groups if vg_idx.get(g.group) in bone_names) < 1e-4: n += 1
    return n


n_zero = unweighted_count() if WEIGHT_METHOD != "FAILED" else len(mesh_obj.data.vertices)
print("AUTO WEIGHTS: vertices with zero weight =", n_zero, "of", len(mesh_obj.data.vertices))
if n_zero > 0.002 * len(mesh_obj.data.vertices):
    # fallback: nearest-bone weights, smoothed by inverse-distance to the two closest bone segments
    WEIGHT_METHOD = "nearest-bone fallback (auto failed on %d vertices)" % n_zero
    mesh_obj.vertex_groups.clear()
    for n in ORDER: mesh_obj.vertex_groups.new(name=n)
    heads = {n: np.array(J[n][0]) for n in ORDER}; tails = {n: np.array(J[n][1]) for n in ORDER}

    def seg_dist(P, a, b):
        ab = b - a; t = np.clip(((P - a) @ ab) / (ab @ ab), 0, 1)
        return np.linalg.norm(P - (a + t[:, None] * ab), axis=1)
    D = np.stack([seg_dist(co, heads[n], tails[n]) for n in ORDER], 1)
    for k, n in enumerate(ORDER):                      # torso-side vertices must not be captured by the arm roots
        if n.startswith("upper_arm"):
            sx = -1.0 if n.endswith("L") else 1.0
            D[:, k] += 0.25 * np.clip((0.24 - sx * co[:, 0]) / 0.12, 0, 1) * (co[:, 2] < 1.80)
        if n.startswith(("upper_leg", "lower_leg")):    # keep the other leg's side from stealing across the midline
            sx = -1.0 if n.endswith("L") else 1.0
            D[:, k] += 0.10 * np.clip((sx * co[:, 0] * -1 - 0.0) / 0.08, 0, 1) * (co[:, 2] < 0.85)
    for i, v in enumerate(mesh_obj.data.vertices):
        idx = np.argsort(D[i])[:3]; w = 1.0 / (D[i, idx] + 0.035) ** 4; w /= w.sum()
        if co[i, 2] < 0.27 and abs(co[i, 0]) > 0.0:     # boots are rigid: foot bone only below the ankle, blend to the shin above it
            sd = "L" if co[i, 0] < 0 else "R"; wf = float(np.clip((0.27 - co[i, 2]) / 0.10, 0, 1))
            mesh_obj.vertex_groups[f"foot.{sd}"].add([i], wf, 'REPLACE')
            if wf < 1: mesh_obj.vertex_groups[f"lower_leg.{sd}"].add([i], 1 - wf, 'REPLACE')
            continue
        for k, ww in zip(idx, w): mesh_obj.vertex_groups[ORDER[k]].add([i], float(ww), 'REPLACE')
mods = [m for m in mesh_obj.modifiers if m.type == 'ARMATURE']
if not mods:
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
json.dump(gait, open(os.path.join(ROOT, "tools", "w5a_gait.json"), "w"), indent=1)
print("GAIT", json.dumps(gait))

if BLEND:
    bpy.ops.wm.save_as_mainfile(filepath=BLEND)

# ----------------------------------------------------------------------------- export
for o in bpy.data.objects: o.select_set(False)
mesh_obj.select_set(True); arm_obj.select_set(True)
bpy.ops.export_scene.gltf(filepath=OUT, export_format='GLB', use_selection=True, export_animations=True,
                          export_animation_mode='ACTIONS', export_skins=True, export_apply=False,
                          export_force_sampling=True, export_optimize_animation_size=False, export_yup=True)
print("EXPORTED", OUT, os.path.getsize(OUT))
