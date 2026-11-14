"""Blender-side helper (run inside blender -b --python): enable Cycles OptiX on the NVIDIA GPU."""
import bpy

def enable_optix():
    prefs = bpy.context.preferences.addons['cycles'].preferences
    prefs.compute_device_type = 'OPTIX'
    prefs.get_devices()
    used = []
    for d in prefs.devices:
        d.use = (d.type == 'OPTIX')
        if d.use: used.append(d.name)
    bpy.context.scene.cycles.device = 'GPU'
    return used
