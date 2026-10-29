"""Renders the photo-real yacht pictures from render-scene.blend (Cycles, sunset and night).

Open render-scene.blend in Blender, paste this into the Text Editor and press Run Script, or run:
    blender render-scene.blend --background --python render_shots.py -- [only=bow,side] [night] [samples=512]

The scene's world has two copies of the Poly Haven sunset photo: LightRot lights matte surfaces from the
camera's left, SeenRot is what the camera and reflections see (open water and the sun behind the yacht).
NightSky is a plain dark-blue sky used at night. Writes renders/<sunset|night>-<view>.jpg next to the .blend.
"""
import math
import os
import sys

import bpy
from mathutils import Vector

ARGS = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
OPT = dict(a.split("=", 1) if "=" in a else (a, "1") for a in ARGS)

SHOTS = {  # Blender space: bow +Y, starboard +X; (camera, target, lens mm)
    "bow": ((72, 90, 3.2), (0, 6, 8.5), 35),
    "side": ((128, -4, 3.0), (0, -1, 9.0), 35),
    "stern": ((34, -96, 3.4), (0, -38, 7.0), 35),
    "helipad": ((24, 64, 13.0), (0, 37.5, 10.5), 50),
}
EMIT = (("Glass", 0.35, 1.1), ("Port", 0.2, 1.2), ("LED", 0.5, 6.0), ("Bulb", 8.0, 25.0),  # (material, day, night)
        ("NavRed", 0.5, 15.0), ("NavGreen", 0.5, 15.0), ("NavWhite", 0.5, 15.0), ("Water", 0.0, 4.0))
SUN_AZ = -36.4  # the sun's azimuth in the unrotated photo (its brightest pixel)


def shot(name, night=False, res=(1920, 1080), samples=512, path=None):
    sc = bpy.context.scene
    cam = sc.camera
    p, t, lens = SHOTS[name]
    p, t = Vector(p), Vector(t)
    cam.location = p
    cam.rotation_euler = (t - p).to_track_quat("-Z", "Y").to_euler()
    cam.data.lens, cam.data.sensor_width = lens, 36
    cam.data.dof.use_dof, cam.data.dof.focus_distance, cam.data.dof.aperture_fstop = True, (t - p).length, 4.0
    view_az = math.degrees(math.atan2(t.y - p.y, t.x - p.x))
    nt = sc.world.node_tree
    nt.nodes["LightRot"].inputs["Rotation"].default_value[2] = math.radians(SUN_AZ - (view_az + 125))  # sun from camera-left
    nt.nodes["SeenRot"].inputs["Rotation"].default_value[2] = math.radians(SUN_AZ - (view_az + 22))  # sunset glow behind
    nt.nodes["LightRot_bg"].inputs["Strength"].default_value = 0.012 if night else 1.0  # at night: a faint fill only
    nt.nodes["SeenRot_bg"].inputs["Strength"].default_value = 0.0 if night else 1.0
    nt.nodes["NightSky"].inputs[1].default_value = 1.0 if night else 0.0
    me = bpy.data.objects["Boat"].data
    for n, day, nite in EMIT:
        m = next(mm for mm in me.materials if mm.name.split(".")[0] == n)
        b = next(x for x in m.node_tree.nodes if x.type == "BSDF_PRINCIPLED")
        b.inputs["Emission Strength"].default_value = nite if night else day
        if n == "Water":
            b.inputs["Emission Color"].default_value = (0.1, 0.7, 1.0, 1)
    bpy.data.objects["UnderwaterGlow"].hide_render = not night
    sc.view_settings.exposure = 0.3 if night else -0.45
    sc.render.resolution_x, sc.render.resolution_y = res
    sc.cycles.samples = samples
    sc.render.image_settings.file_format, sc.render.image_settings.quality = "JPEG", 90
    sc.render.filepath = path
    bpy.ops.render.render(write_still=True)


def use_gpu():
    prefs = bpy.context.preferences.addons["cycles"].preferences
    for kind in ("OPTIX", "CUDA", "HIP", "METAL", "ONEAPI"):
        try:
            prefs.compute_device_type = kind
        except TypeError:
            continue
        prefs.get_devices()
        if any(d.type == kind for d in prefs.devices):
            for d in prefs.devices:
                d.use = d.type == kind
            bpy.context.scene.cycles.device = "GPU"
            return kind
    bpy.context.scene.cycles.device = "CPU"
    return "CPU"


def main():
    print("render device:", use_gpu())
    out = os.path.join(bpy.path.abspath("//"), "renders")
    os.makedirs(out, exist_ok=True)
    night = "night" in OPT
    for name in OPT.get("only", ",".join(SHOTS)).split(","):
        path = os.path.join(out, "%s-%s.jpg" % ("night" if night else "sunset", name))
        shot(name, night, samples=int(OPT.get("samples", 512)), path=path)
        print("wrote", path)


main()
