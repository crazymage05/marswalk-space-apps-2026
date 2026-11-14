"""Edge-stretch and shell-gap metrics of a rigged GLB across the walk cycle. blender -b --python this -- glb out.json
stretch ratio = deformed edge length / rest edge length (all mesh edges, evaluated with the armature modifier).
gap = for vertex pairs closer than 2 cm in rest (different vertices, sampled by KD-tree), the max pair distance during the cycle / rest distance."""
import bpy, sys, json
import numpy as np
from mathutils.kdtree import KDTree
glb, out = sys.argv[sys.argv.index('--')+1:][:2]
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=glb)
arm = [o for o in bpy.data.objects if o.type == 'ARMATURE'][0]
meshes = [o for o in bpy.data.objects if o.type == 'MESH' and any(m.type == 'ARMATURE' for m in o.modifiers)]
act = bpy.data.actions.get('walk'); arm.animation_data.action = act
dg = bpy.context.evaluated_depsgraph_get()
def coords(ob, frame):
    bpy.context.scene.frame_set(frame); dg = bpy.context.evaluated_depsgraph_get()
    e = ob.evaluated_get(dg); me = e.to_mesh(); a = np.empty(len(me.vertices)*3); me.vertices.foreach_get('co', a); e.to_mesh_clear()
    return a.reshape(-1, 3)
ob = max(meshes, key=lambda o: len(o.data.vertices))      # the suit body (backpack parts are rigid boxes)
arm.data.pose_position = 'REST'; bpy.context.view_layer.update()
rest = coords(ob, 0); arm.data.pose_position = 'POSE'
ed = np.empty(len(ob.data.edges)*2, dtype=np.int32); ob.data.edges.foreach_get('vertices', ed); ed = ed.reshape(-1, 2)
rl = np.linalg.norm(rest[ed[:,0]] - rest[ed[:,1]], axis=1); ok = rl > 3e-3        # ignore sub-3 mm slivers (ratio meaningless)
# cross-shell pairs
kd = KDTree(len(rest)); [kd.insert(tuple(p), i) for i, p in enumerate(rest)]; kd.balance()
rng = np.random.default_rng(1); samp = rng.choice(len(rest), 6000, replace=False); pairs = []
conn = set(map(tuple, np.sort(ed, 1)))
for i in samp:
    for (_, j, d) in kd.find_range(tuple(rest[i]), 0.02):
        if j != i and d > 1e-5 and (min(i, j), max(i, j)) not in conn: pairs.append((i, j)); break
pairs = np.array(pairs); pr = np.linalg.norm(rest[pairs[:,0]] - rest[pairs[:,1]], axis=1)
mx = np.zeros(len(ed)); el = np.zeros(len(ed)); gmax = np.zeros(len(pairs)); per_frame = []
for f in range(0, 41):
    c = coords(ob, f); l = np.linalg.norm(c[ed[:,0]] - c[ed[:,1]], axis=1)
    r = np.where(ok, l / np.maximum(rl, 1e-4), 1.0); mx = np.maximum(mx, r); per_frame.append(float(r.max())); el = np.maximum(el, np.where(ok, l - rl, 0))
    gmax = np.maximum(gmax, np.linalg.norm(c[pairs[:,0]] - c[pairs[:,1]], axis=1))
res = dict(glb=glb, max_abs_elongation_cm=float(el.max()*100), edges_elong_gt_5cm=int((el>0.05).sum()), edges_ok=int(ok.sum()), verts=len(rest), edges=len(ed), max_stretch=float(mx.max()), p99_9=float(np.percentile(mx, 99.9)), p99=float(np.percentile(mx, 99)),
           edges_gt_1_5=int((mx > 1.5).sum()), edges_gt_2=int((mx > 2).sum()), edges_gt_3=int((mx > 3).sum()),
           cross_shell_pairs=len(pairs), pair_gap_max_cm=float((gmax).max() * 100), pair_gap_p99_cm=float(np.percentile(gmax, 99) * 100),
           pair_gap_max_legs_cm=float(gmax[(rest[pairs[:,0]][:,2]<1.0)].max()*100), pair_gap_p99_legs_cm=float(np.percentile(gmax[(rest[pairs[:,0]][:,2]<1.0)],99)*100), pair_gap_legs_gt_5cm=int((gmax[(rest[pairs[:,0]][:,2]<1.0)]>0.05).sum()), pair_gaps_rest_max_cm=float(pr.max()*100), pair_gap_gt_5cm=int((gmax > 0.05).sum()), pair_gap_gt_10cm=int((gmax > 0.10).sum()), worst_frame=int(np.argmax(per_frame)))
# frames of greatest knee bend: angle between thigh and shank
import math
def kb(f):
    bpy.context.scene.frame_set(f); pb = arm.pose.bones
    best = 0
    for s in 'LR':
        a = pb['upper_leg.'+s]; b = pb['lower_leg.'+s]
        da = (a.tail - a.head).normalized(); db = (b.tail - b.head).normalized(); best = max(best, math.degrees(da.angle(db)))
    return best
bends = [(kb(f), f) for f in range(40)]; res['knee_bend_top4'] = [f for _, f in sorted(bends, reverse=True)[:4]]; res['knee_bend_max_deg'] = max(bends)[0]
json.dump(res, open(out, 'w'), indent=1); print("RESULT", json.dumps(res))
