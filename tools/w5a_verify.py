"""Fresh-Blender check of the exported GLB: armature, bones, clips, foot drift in stance.  args after --: glb out_json"""
import bpy, sys, math, json
import numpy as np
glb, outj = sys.argv[sys.argv.index('--') + 1:][:2]
bpy.ops.wm.read_factory_settings(use_empty=True); bpy.ops.import_scene.gltf(filepath=glb)
sc = bpy.context.scene
arms = [o for o in bpy.data.objects if o.type == 'ARMATURE']; meshes = [o for o in bpy.data.objects if o.type == 'MESH']
rep = dict(armatures=[a.name for a in arms], bones=[len(a.data.bones) for a in arms], bone_names=[b.name for b in arms[0].data.bones],
           meshes=[(m.name, len(m.data.vertices), [vg.name for vg in m.vertex_groups][:3]) for m in meshes], clips={})
fps = sc.render.fps
V = 0.9; ANKLE_Z = 0.16
arm = arms[0]
for act in bpy.data.actions:
    f0, f1 = act.frame_range
    rep["clips"][act.name] = dict(frames=[f0, f1], seconds=(f1 - f0) / fps, fps=fps, fcurves=len(act.fcurves))
print("REPORT", json.dumps({k: v for k, v in rep.items() if k != "bone_names"}))
walk = bpy.data.actions.get("walk")
if arm.animation_data is None: arm.animation_data_create()
arm.animation_data.action = walk
f0, f1 = walk.frame_range; n = int(round(f1 - f0)); SUB = 4
drift = {}
for side in "LR":
    ts, P = [], []
    for k in range(2 * n * SUB + 1):                      # two cycles, 4 samples per frame (subframe interpolation)
        fr = f0 + (k / SUB) % n if k < n * SUB else f0 + ((k / SUB) - n)
        sc.frame_set(int(fr), subframe=fr - int(fr))
        h = arm.matrix_world @ arm.pose.bones[f"foot.{side}"].head
        t = (k / SUB) / fps
        ts.append(t); P.append((h.x, h.y + V * t, h.z))
    P = np.array(P); ts = np.array(ts)
    contact = P[:, 2] <= ANKLE_Z + 0.004
    segs, i = [], 0
    while i < len(P):
        if contact[i]:
            j = i
            while j + 1 < len(P) and contact[j + 1]: j += 1
            if i > 0 and j < len(P) - 1: segs.append((i, j))
            i = j + 1
        else: i += 1
    res = []
    for i, j in segs:
        q = P[i:j + 1]; c = q.mean(0)
        res.append(dict(t0=float(ts[i]), t1=float(ts[j]), dur_s=float(ts[j] - ts[i]), drift_horiz_m=float(np.max(np.linalg.norm(q[:, :2] - c[:2], axis=1)) * 2 if False else np.ptp(q[:, 1])),
                        drift_x_m=float(np.ptp(q[:, 0])), drift_z_m=float(np.ptp(q[:, 2]))))
    drift[side] = res
    print("FOOT", side, "planted segments:", [(round(r['t0'], 2), round(r['t1'], 2), round(r['drift_horiz_m'] * 100, 2)) for r in res])
rep["foot_drift"] = drift
allv = [r["drift_horiz_m"] for s in drift.values() for r in s]
rep["max_drift_forward_cm"] = max(allv) * 100
rep["max_drift_x_cm"] = max(r["drift_x_m"] for s in drift.values() for r in s) * 100
print("MAX_FOOT_DRIFT_FWD_CM", rep["max_drift_forward_cm"], "MAX_X_CM", rep["max_drift_x_cm"])
json.dump(rep, open(outj, "w"), indent=1)

# ---- independent check 2: skinned mesh. Left-boot sole vertices (rest z < 0.03, x < 0) through the armature modifier
mesh = [m for m in meshes if m.name.startswith("MarkIII")][0]
dg = bpy.context.evaluated_depsgraph_get()
rest = np.array([tuple(mesh.matrix_world @ v.co) for v in mesh.data.vertices])
sole = np.where((rest[:, 2] < 0.03) & (rest[:, 0] < -0.02))[0]
print("SOLE verts", len(sole))
res = {}
arm.animation_data.action = walk
for k in range(2 * n * 2 + 1):
    fr = f0 + (k / 2) % n; sc.frame_set(int(fr), subframe=fr - int(fr))
    ev = mesh.evaluated_get(dg); me = ev.to_mesh()
    # evaluated vertex order is preserved for armature-only modifiers
    P = np.array([tuple(ev.matrix_world @ me.vertices[i].co) for i in sole]); ev.to_mesh_clear()
    t = k / 2 / fps; ank = (arm.matrix_world @ arm.pose.bones["foot.L"].head).z
    res[k] = (t, P[:, 1].mean() + V * t, P[:, 2].min(), ank)
arr = np.array(list(res.values()))
contact = arr[:, 3] <= ANKLE_Z + 0.004
segs, i = [], 0
while i < len(arr):
    if contact[i]:
        j = i
        while j + 1 < len(arr) and contact[j + 1]: j += 1
        if i > 0 and j < len(arr) - 1: segs.append((i, j))
        i = j + 1
    else: i += 1
sole_res = [dict(t0=float(arr[i, 0]), t1=float(arr[j, 0]), sole_centroid_drift_cm=float(np.ptp(arr[i:j + 1, 1]) * 100),
                 min_sole_z_cm=float(arr[i:j + 1, 2].min() * 100)) for i, j in segs]
print("SOLE_DRIFT", json.dumps(sole_res)); print("SOLE min z over cycle (cm)", arr[:, 2].min() * 100, "max", arr[:, 2].max() * 100)
rep["sole_mesh_drift"] = sole_res; rep["sole_min_z_cm"] = float(arr[:, 2].min() * 100)
json.dump(rep, open(outj, "w"), indent=1)
