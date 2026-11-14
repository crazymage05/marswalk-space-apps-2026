"""EEVEE renders of a rigged GLB at chosen walk frames from side / back / front-3/4. blender -b --python this -- glb outdir tag frames(comma)
Run through tools/run_blender.py (GPU lock).  Body stays in place (the clip is in place)."""
import bpy, sys, math, os
from mathutils import Vector
glb, outd, tag, frames = sys.argv[sys.argv.index('--')+1:][:4]
frames = [int(x) for x in frames.split(',')]
bpy.ops.wm.read_factory_settings(use_empty=True); bpy.ops.import_scene.gltf(filepath=glb)
sc = bpy.context.scene
arm = [o for o in bpy.data.objects if o.type == 'ARMATURE'][0]; arm.animation_data.action = bpy.data.actions['walk']
sc.render.engine = 'BLENDER_EEVEE_NEXT'; sc.render.resolution_x = 360; sc.render.resolution_y = 480
sc.eevee.taa_render_samples = 16
w = bpy.data.worlds.new("w"); w.use_nodes = True; w.node_tree.nodes["Background"].inputs[0].default_value = (0.55, 0.55, 0.6, 1); w.node_tree.nodes["Background"].inputs[1].default_value = 0.9; sc.world = w
sun = bpy.data.objects.new("sun", bpy.data.lights.new("sun", 'SUN')); sun.data.energy = 3.0; sun.rotation_euler = (math.radians(50), 0, math.radians(30)); sc.collection.objects.link(sun)
fill = bpy.data.objects.new("fill", bpy.data.lights.new("fill", 'SUN')); fill.data.energy = 1.5; fill.rotation_euler = (math.radians(60), 0, math.radians(210)); sc.collection.objects.link(fill)
bpy.ops.mesh.primitive_plane_add(size=6, location=(0, 0, -0.005)); bpy.context.object.data.materials.append(bpy.data.materials.new("floor")); bpy.context.object.active_material.diffuse_color = (0.35, 0.3, 0.27, 1)
cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam")); sc.collection.objects.link(cam); sc.camera = cam
cam.data.lens = 85
views = {"side": (4.6, 0.0, 1.0), "back": (0.0, -4.6, 1.0), "front34": (3.3, 3.3, 1.0)}
os.makedirs(outd, exist_ok=True)
for vn, loc in views.items():
    cam.location = loc
    d = Vector((0.0, 0.1, 0.95)) - Vector(loc); cam.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler()
    for f in frames:
        sc.frame_set(f); sc.render.filepath = os.path.join(outd, f"{tag}_{vn}_{f:02d}.png"); bpy.ops.render.render(write_still=True)
print("RENDERED", len(views) * len(frames))
