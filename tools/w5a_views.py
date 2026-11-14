"""Workbench orthographic views of a GLB (front/side/top) for inspection. args after --: glb out_prefix"""
import bpy, sys, math
from mathutils import Vector
glb, outp = sys.argv[sys.argv.index('--')+1:][:2]
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=glb)
sc = bpy.context.scene
sc.render.engine = 'BLENDER_WORKBENCH'
sc.display.shading.light = 'STUDIO'; sc.display.shading.color_type = 'TEXTURE'
sc.render.resolution_x = 500; sc.render.resolution_y = 600
cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam")); sc.collection.objects.link(cam); sc.camera = cam
cam.data.type = 'ORTHO'; cam.data.ortho_scale = 2.8
for name, loc, rot in (("front", (0.0, -6, 1.3), (90, 0, 0)), ("side", (6, 0.5, 1.3), (90, 0, 90)), ("top", (0, 0.5, 6), (0, 0, 0))):
    cam.location = loc; cam.rotation_euler = [math.radians(a) for a in rot]
    sc.render.filepath = f"{outp}_{name}.png"; bpy.ops.render.render(write_still=True)
