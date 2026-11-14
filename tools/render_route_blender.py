"""Runs inside Blender (called by tools/render_route.py):
   blender -b <scene.blend> --python tools/render_route_blender.py -- <first> <last> <step> <outdir> <w> <h> <engine cycles|eevee> <spp>
Renders frames first, first+step, ... <= last as 8-bit PNG (frame_%04d.png); frames that already exist are skipped (restartable)."""
import os, sys, time, bpy
first, last, step, outdir, w, h, engine, spp = sys.argv[sys.argv.index("--") + 1:][:8]
sc = bpy.context.scene
if engine == "cycles":
    sc.render.engine = "CYCLES"
    p = bpy.context.preferences.addons["cycles"].preferences; p.compute_device_type = "OPTIX"; p.get_devices()
    for d in p.devices: d.use = d.type == "OPTIX"
    sc.cycles.device = "GPU"; sc.cycles.samples = int(spp); sc.cycles.use_denoising = True; sc.cycles.denoiser = "OPTIX"
else:
    for name in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"):
        try: sc.render.engine = name; break
        except TypeError: pass
    sc.eevee.taa_render_samples = int(spp)
sc.render.resolution_x, sc.render.resolution_y, sc.render.resolution_percentage = int(w), int(h), 100
sc.render.image_settings.file_format = "PNG"; sc.render.image_settings.color_depth = "8"; os.makedirs(outdir, exist_ok=True)
for f in range(int(first), int(last) + 1, int(step)):
    fn = os.path.join(outdir, "frame_%04d.png" % f)
    if os.path.exists(fn): continue
    t0 = time.time(); sc.frame_set(f); sc.render.filepath = fn; bpy.ops.render.render(write_still=True)
    print("FRAME %d done in %.1f s (%s)" % (f, time.time() - t0, sc.render.engine), flush=True)
