"""Workbench side renders of the walk cycle. args after --: blend_or_glb out_dir [action] [frames]
Body moves at 0.9 m/s over a tick-marked floor so planted feet stay on their marks."""
import bpy, sys, math, os
from mathutils import Vector
a = sys.argv[sys.argv.index('--') + 1:]
src, outd = a[0], a[1]; actname = a[2] if len(a) > 2 else "walk"; nfr = int(a[3]) if len(a) > 3 else 8
V = 0.9
if src.endswith(".blend"): bpy.ops.wm.open_mainfile(filepath=src)
else:
    bpy.ops.wm.read_factory_settings(use_empty=True); bpy.ops.import_scene.gltf(filepath=src)
sc = bpy.context.scene
arm = [o for o in bpy.data.objects if o.type == 'ARMATURE'][0]
act = bpy.data.actions[actname]; arm.animation_data.action = act
f0, f1 = int(act.frame_range[0]), int(act.frame_range[1]); n = f1 - f0
fps = sc.render.fps
sc.render.engine = 'BLENDER_WORKBENCH'
sc.display.shading.light = 'STUDIO'; sc.display.shading.color_type = 'MATERIAL'
sc.render.resolution_x = 640; sc.render.resolution_y = 420
sc.world = bpy.data.worlds.new("w"); sc.world.color = (0.85, 0.82, 0.8)
# floor marks
bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0.6, -0.01)); fl = bpy.context.object; fl.scale = (1.5, 4.5, 0.02)
for i in range(-6, 14):
    bpy.ops.mesh.primitive_cube_add(size=1, location=(0, i * 0.25, 0.001)); t = bpy.context.object
    t.location.z = 0.02; t.scale = (1.4, 0.014, 0.03)
cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam")); sc.collection.objects.link(cam); sc.camera = cam
cam.data.type = 'ORTHO'; cam.data.ortho_scale = 4.2
cam.location = (7, 0.5, 0.95); cam.rotation_euler = (math.radians(90), 0, math.radians(90))
os.makedirs(outd, exist_ok=True)
for k in range(nfr):
    fr = f0 + k * n / nfr
    sc.frame_set(int(fr), subframe=fr - int(fr))
    arm.location.y = V * (fr - f0) / fps if actname == "walk" else 0.0
    bpy.context.view_layer.update()
    sc.render.filepath = os.path.join(outd, f"{actname}_{k:02d}.png"); bpy.ops.render.render(write_still=True)
