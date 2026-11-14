"""
Move Cam_3_dust back from the sol-4598 Navcam scan (it sat 1.9 m above the scan's edge, whose sheets and walls
filled the foreground). Run inside Blender:  blender -b film/marswalk_scene.blend --python tools/f2_dustfix.py -- BACK_M UP_M
Shifts every Cam_3_dust location key BACK_M metres opposite its view direction, re-seats it UP_M above the ground
(ray cast down), and saves film/marswalk_scene_dustfix.blend. Target keys are unchanged (they are 400 m away).
"""
import bpy, sys, math
from mathutils import Vector
a = sys.argv[sys.argv.index("--") + 1:]; BACK, UP = float(a[0]), float(a[1])
sc = bpy.context.scene; cam = bpy.data.objects["Cam_3_dust"]
tgt = [o for o in bpy.data.objects if o.name.startswith("Cam_3_dust") and o is not cam]
tgt = tgt[0] if tgt else None
fc = {i: cam.animation_data.action.fcurves.find("location", index=i) for i in range(3)}
dg = bpy.context.evaluated_depsgraph_get()
for k in range(len(fc[0].keyframe_points)):
    f = fc[0].keyframe_points[k].co[0]; sc.frame_set(int(f))
    p = Vector([fc[i].keyframe_points[k].co[1] for i in range(3)])
    t = tgt.matrix_world.translation if tgt else p + Vector((0, 1, 0))
    d = Vector((t.x - p.x, t.y - p.y, 0)).normalized()
    q = p - d * BACK
    hit, loc, *_ = sc.ray_cast(dg, Vector((q.x, q.y, q.z + 500)), Vector((0, 0, -1)))
    z = (loc.z if hit else p.z) + UP
    for i, v in enumerate((q.x, q.y, z)):
        kp = fc[i].keyframe_points[k]; dv = v - kp.co[1]; kp.co[1] = v; kp.handle_left[1] += dv; kp.handle_right[1] += dv
    print(f"key f{int(f)}: moved {BACK} m back, ground hit {hit}, z {p.z:.1f} -> {z:.1f}")
bpy.ops.wm.save_as_mainfile(filepath=bpy.path.abspath("//marswalk_scene_dustfix.blend"), copy=True)
print("saved dustfix blend; target object:", tgt.name if tgt else None)
