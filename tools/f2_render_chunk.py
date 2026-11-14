"""Runs inside Blender: blender -b film/marswalk_scene.blend --python tools/f2_render_chunk.py -- <first> <last> <outdir> <w> <h> <spp>
Renders frames first..last as PNG (frame_%04d.png), skipping frames that already exist (restartable)."""
import os, sys, time, bpy
first, last, outdir, w, h, spp = sys.argv[sys.argv.index("--") + 1:][:6]
sc = bpy.context.scene
p = bpy.context.preferences.addons["cycles"].preferences; p.compute_device_type = "OPTIX"; p.get_devices()
for d in p.devices: d.use = d.type == "OPTIX"
sc.cycles.device = "GPU"; sc.cycles.samples = int(spp); sc.cycles.use_denoising = True; sc.cycles.denoiser = "OPTIX"
sc.render.resolution_x, sc.render.resolution_y, sc.render.resolution_percentage = int(w), int(h), 100
sc.render.image_settings.file_format = "PNG"; sc.render.image_settings.color_depth = "16"; os.makedirs(outdir, exist_ok=True)
for f in range(int(first), int(last) + 1):
    fn = os.path.join(outdir, "frame_%04d.png" % f)
    if os.path.exists(fn): continue
    t0 = time.time(); sc.frame_set(f); sc.render.filepath = fn; bpy.ops.render.render(write_still=True)
    print("FRAME %d done in %.1f s" % (f, time.time() - t0), flush=True)
