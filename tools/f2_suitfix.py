"""
F2 v3 look fixes on a copy of the film scene (the original .blend is not changed). Run inside Blender:
    blender -b film/marswalk_scene.blend --python tools/f2_suitfix.py
1. Life-support backpack (PLSS) on the Mark III suit, parented to the 'chest' bone. The NASA Mark III GLB
   has no backpack, and from behind its rear hatch and hip bearing read as a bulky body; every EVA suit
   carries one (EMU PLSS is about 0.6 x 0.25 x 0.8 m). Size here 0.60 x 0.28 x 0.82 m, rounded edges,
   suit-white, two steel bands and a dark hose strap; illustrative shape, not a specific NASA part.
2. Depth of field off on the walk cameras (Cam_2_walk, Cam_2b_close, Cam_2c_low) so the terrain is sharp.
Saves film/marswalk_scene_v3.blend.
"""
import bpy
from mathutils import Matrix, Vector

arm = [o for o in bpy.data.objects if o.type == "ARMATURE"][0]
suit = bpy.data.objects["MarkIII_suit"]
arm.data.pose_position = "REST"; bpy.context.view_layer.update()


def box(name, size, centre, mat, bevel):
    me = bpy.data.meshes.new(name); sx, sy, sz = (s / 2 for s in size)
    v = [(x, y, z) for x in (-sx, sx) for y in (-sy, sy) for z in (-sz, sz)]
    f = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    me.from_pydata(v, [], f); me.update(); ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob); me.materials.append(mat)
    if bevel:
        m = ob.modifiers.new("bevel", "BEVEL"); m.width = bevel; m.segments = 5
        ob.modifiers.new("smooth", "WEIGHTED_NORMAL")
        for p in me.polygons: p.use_smooth = True
    want = arm.matrix_world @ Matrix.Translation(Vector(centre))
    ob.parent = arm; ob.parent_type = "BONE"; ob.parent_bone = "chest"
    bpy.context.view_layer.update(); ob.matrix_world = want
    return ob


white = bpy.data.materials["MKIII:MarkIII_8sizedwithoutskeleton_markiiitorso_lambert2SG"]
steel = bpy.data.materials["MKIII:MarkIII_8sizedwithoutskeleton_steel2SG"]
dark = bpy.data.materials.new("plss_vent"); dark.use_nodes = True
bsdf = dark.node_tree.nodes.get("Principled BSDF"); bsdf.inputs["Base Color"].default_value = (0.05, 0.05, 0.055, 1); bsdf.inputs["Roughness"].default_value = 0.6

back_y = -0.33                                                       # suit back surface at chest height (measured)
import os
_have = [o for o in bpy.data.objects if o.type == "MESH" and o.name.startswith("PLSS")]
if _have:     # the w5b walk GLB already carries this same backpack (same size and place) in film and route mode; a second copy would only z-fight
    print("PLSS already in the suit GLB:", [o.name for o in _have], "- not adding another")
    arm.data.pose_position = "POSE"; bpy.context.view_layer.update(); parts = []
else:
  parts = [box("PLSS", (0.60, 0.28, 0.82), (0, back_y - 0.13, 1.22), white, 0.07),
           box("PLSS_band_top", (0.62, 0.22, 0.04), (0, back_y - 0.14, 1.50), steel, 0.012),
           box("PLSS_band_low", (0.62, 0.22, 0.04), (0, back_y - 0.14, 0.92), steel, 0.012),
           box("PLSS_hose", (0.40, 0.03, 0.03), (0, back_y - 0.285, 1.40), dark, 0.010)]
  arm.data.pose_position = "POSE"; bpy.context.view_layer.update()
for o in parts: o["note"] = "illustrative PLSS backpack (Mark III GLB has none)"
for c in ("Cam_2_walk", "Cam_2b_close", "Cam_2c_low"):
    if c in bpy.data.objects: bpy.data.objects[c].data.dof.use_dof = False
import os
bpy.ops.wm.save_as_mainfile(filepath=os.environ.get("F2_OUT_BLEND") or bpy.path.abspath("//marswalk_scene_v3.blend"), copy=True)   # F2_OUT_BLEND: route mode (tools/render_route.py)
print("saved v3 blend with", [o.name for o in parts])
