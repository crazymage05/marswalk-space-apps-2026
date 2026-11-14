"""Runs inside Blender: blender -b film/marswalk_scene.blend --python tools/f1_render_still.py -- <frame> <out.png> <w> <h> <samples>"""
import sys, bpy
a = sys.argv[sys.argv.index("--") + 1:]; frame, out, w, h, spp = a[:5]; camname = a[5] if len(a) > 5 else None
sc = bpy.context.scene
p = bpy.context.preferences.addons["cycles"].preferences; p.compute_device_type = "OPTIX"; p.get_devices()
for d in p.devices: d.use = d.type == "OPTIX"
print("devices:", [(d.name, d.type, d.use) for d in p.devices])
sc.cycles.device = "GPU"; sc.cycles.samples = int(spp); sc.cycles.use_denoising = True; sc.cycles.denoiser = "OPTIX"
sc.render.resolution_x, sc.render.resolution_y, sc.render.resolution_percentage = int(w), int(h), 100
sc.frame_set(int(frame))
if camname:
    for mk in sc.timeline_markers: mk.camera = None
    sc.camera = bpy.data.objects[camname]          # after frame_set: timeline markers would otherwise rebind the camera
sc.render.filepath = out; sc.render.image_settings.file_format = "PNG"
import time; t0 = time.time(); bpy.ops.render.render(write_still=True); print("RENDER_SECONDS %.1f" % (time.time() - t0))
