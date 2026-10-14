"""Render one or more shots from shots.yaml out of the baseline .blend.

Each frame is checked numerically (a blank, black or clipped frame fails) and gets a
JSON sidecar with the git commit, inputs.lock.json hash, camera, sun and render settings.
Marketing frames are refused if they include review overlays, and are captioned
(PLAN.md §7); the uncaptioned master is kept beside them for regrading only.

Usage:
  Blender -b --python scripts/blender/render.py -- --shot check_lake_oblique [--res draft]
  Blender -b --python scripts/blender/render.py -- --shot all --kind check
Options: --blend PATH (default: newest out/*/lrh_baseline.blend), --samples N.
"""

import argparse
import json
import math
import sys
import time
from datetime import datetime
from pathlib import Path

import bpy
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lrh  # noqa: E402
import yaml  # noqa: E402

MARKETING_FORBIDDEN = {"Overlays_Review", "Masks"}


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--shot", required=True, help="shot name, or 'all'")
    parser.add_argument("--kind", choices=["check", "marketing"], help="filter for --shot all")
    parser.add_argument("--res", choices=["draft", "final"], default="draft")
    parser.add_argument("--blend", type=Path)
    parser.add_argument("--samples", type=int)
    return parser.parse_args(argv)


def newest_blend():
    builds = sorted(lrh.OUT_ROOT.glob("*/lrh_baseline.blend"))
    if not builds:
        lrh.fail("no out/*/lrh_baseline.blend; run build_baseline.py first")
    return builds[-1]


def configure_device(scene):
    scene.render.engine = "CYCLES"
    prefs = bpy.context.preferences.addons["cycles"].preferences
    prefs.compute_device_type = "METAL"
    prefs.get_devices()
    for device in prefs.devices:
        device.use = True
    scene.cycles.device = "GPU"
    scene.cycles.use_denoising = True
    scene.cycles.denoiser = "OPENIMAGEDENOISE"
    scene.cycles.use_adaptive_sampling = True
    scene.view_settings.view_transform = "AgX"
    scene.view_settings.look = "AgX - Base Contrast"
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_depth = "16"


def configure_sky(scene, sun_spec):
    """Physical sky with its own sun disc as the single key light."""
    when = datetime.fromisoformat(sun_spec["datetime"])
    elevation, azimuth = lrh.solar_position(when, sun_spec["utc_offset_h"])
    sky = next(n for n in scene.world.node_tree.nodes if n.bl_idname == "ShaderNodeTexSky")
    sky.sky_type = "MULTIPLE_SCATTERING"
    sky.sun_disc = True
    sky.sun_elevation = math.radians(elevation)
    sky.sun_rotation = math.radians(azimuth)  # verified: compass azimuth, 0 = north (+Y)
    sky.altitude = sun_spec.get("observer_altitude_m", 200.0)
    sky.air_density = sun_spec.get("air_density", 1.0)
    sky.aerosol_density = sun_spec.get("aerosol_density", 1.0)
    for obj in list(bpy.data.objects):  # the build's placeholder lamp is not used
        if obj.type == "LIGHT" and obj.data.type == "SUN":
            bpy.data.objects.remove(obj, do_unlink=True)
    return {"datetime_local": sun_spec["datetime"], "utc_offset_h": sun_spec["utc_offset_h"],
            "elevation_deg": round(elevation, 2), "azimuth_deg": round(azimuth, 2)}


def apply_collections(scene, wanted):
    layer = bpy.context.view_layer.layer_collection
    known = {c.name for c in layer.children}
    missing = set(wanted) - known
    if missing:
        lrh.fail(f"shot lists unknown collections {sorted(missing)}")
    for child in layer.children:
        child.exclude = child.name not in wanted and child.name != "Cameras"


def caption(src, dst, text):
    from PIL import Image, ImageDraw, ImageFont  # from .blender-site
    image = Image.open(src).convert("RGB")
    draw = ImageDraw.Draw(image)
    size = max(14, image.height // 60)
    font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", size)
    margin = size
    x, y = margin, image.height - margin - size
    draw.text((x + max(1, size // 12), y + max(1, size // 12)), text, font=font, fill=(0, 0, 0))
    draw.text((x, y), text, font=font, fill=(245, 245, 240))
    image.save(dst)


def render_shot(name, shot, config, args, out):
    scene = bpy.context.scene
    kind = shot["kind"]
    wanted = set(shot["collections"])
    if kind == "marketing" and wanted & MARKETING_FORBIDDEN:
        lrh.fail(f"{name}: marketing shots may not show {sorted(wanted & MARKETING_FORBIDDEN)}")
    res = config[args.res]
    width, height = shot.get("resolution", res["resolution"]) if args.res == "draft" \
        else res["resolution"]
    scene.render.resolution_x, scene.render.resolution_y = width, height
    scene.render.resolution_percentage = 100
    scene.cycles.samples = args.samples or shot.get("samples", res["samples"])
    if "tile_size" in res:
        scene.cycles.use_auto_tile = True
        scene.cycles.tile_size = res["tile_size"]
    scene.view_settings.exposure = shot.get("exposure", config.get("exposure", 0.0))

    camera = bpy.data.objects.get(f"CAM_{name}")
    if camera is None:
        lrh.fail(f"{name}: no camera CAM_{name} in the .blend; rebuild the baseline")
    scene.camera = camera
    sun = configure_sky(scene, shot["sun"])
    apply_collections(scene, wanted)

    stem = f"{name}_{args.res}"
    master = out / (f"{stem}_master_uncaptioned.png" if kind == "marketing" else f"{stem}.png")
    scene.render.filepath = str(master)
    started = time.time()
    bpy.ops.render.render(write_still=True)
    seconds = time.time() - started
    try:
        stats = lrh.frame_stats(master)
    except lrh.CheckFailed as error:
        lrh.fail(str(error))
    deliverable = master
    if kind == "marketing":
        deliverable = out / f"{stem}.png"
        caption(master, deliverable, config["caption"])

    cam = camera.data
    sidecar = {
        "schema": "lrh.render-sidecar/1",
        "shot": name,
        "kind": kind,
        "rendered_utc": lrh.utc_now(),
        "git": lrh.git_commit(),
        "inputs_lock_sha256": lrh.file_sha256(lrh.ROOT / "inputs.lock.json"),
        "shots_yaml_sha256": lrh.file_sha256(lrh.ROOT / "shots.yaml"),
        "blend": str(args.blend),
        "image": str(deliverable),
        "caption": config["caption"] if kind == "marketing" else None,
        "camera": {
            "type": cam.type, "location": list(camera.location),
            "rotation_euler": list(camera.rotation_euler), "lens_mm": cam.lens,
            "sensor_width_mm": cam.sensor_width, "ortho_scale": cam.ortho_scale,
            "clip_end": cam.clip_end,
        },
        "sun": sun,
        "render": {"res": args.res, "resolution": [width, height], "samples": scene.cycles.samples,
                   "engine": scene.render.engine, "device": scene.cycles.device,
                   "exposure": scene.view_settings.exposure,
                   "view_transform": scene.view_settings.view_transform,
                   "seconds": round(seconds, 1)},
        "collections": sorted(wanted),
        "luminance": stats,
    }
    (out / f"{stem}.json").write_text(json.dumps(sidecar, indent=2) + "\n")
    print(f"RENDERED {name} in {seconds:.0f}s -> {deliverable}")


def main():
    args = parse_args()
    args.blend = args.blend or newest_blend()
    config_all = yaml.safe_load((lrh.ROOT / "shots.yaml").read_text())
    shots, config = config_all["shots"], config_all["render"]
    if args.shot == "all":
        names = [n for n, s in shots.items() if not args.kind or s["kind"] == args.kind]
    elif args.shot in shots:
        names = [args.shot]
    else:
        lrh.fail(f"unknown shot {args.shot}; known: {', '.join(shots)}")
    bpy.ops.wm.open_mainfile(filepath=str(args.blend))
    configure_device(bpy.context.scene)
    out = lrh.out_dir()
    for name in names:
        render_shot(name, shots[name], config, args, out)


if __name__ == "__main__":
    main()
