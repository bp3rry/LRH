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
import tempfile
import time
from datetime import datetime
from pathlib import Path

import bpy
import numpy as np
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
    parser.add_argument("--res", choices=["draft", "4k", "final"], default="draft")
    parser.add_argument("--blend", type=Path)
    parser.add_argument("--samples", type=int)
    parser.add_argument("--flooded-timber", choices=["leafy", "dying", "snags", "none"],
                        help="override the shot's flooded_timber")
    parser.add_argument("--cleared-ground", choices=["soil", "grassed"],
                        help="override the shot's cleared_ground")
    parser.add_argument("--spanish-moss", choices=["on", "off"],
                        help="override the shot's spanish_moss")
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


def horizon_colour(scene, camera, scratch, all_azimuths=False):
    """Scene-linear sky colour 4-10 degrees above the horizon, around the view heading,
    from a tiny world-only equirectangular render at the camera position."""
    layer = bpy.context.view_layer.layer_collection
    excluded = {c.name: c.exclude for c in layer.children}
    for child in layer.children:
        child.exclude = True
    saved = (scene.camera, scene.render.resolution_x, scene.render.resolution_y,
             scene.cycles.samples, scene.render.filepath,
             scene.render.image_settings.file_format, scene.cycles.use_denoising)
    pano = bpy.data.objects.new("LRH_Pano", bpy.data.cameras.new("LRH_Pano"))
    scene.collection.objects.link(pano)
    pano.data.type = "PANO"
    pano.data.panorama_type = "EQUIRECTANGULAR"
    forward = camera.matrix_world.to_quaternion() @ Vector((0, 0, -1))
    heading = math.atan2(forward.x, forward.y)
    pano.location = camera.location
    pano.rotation_euler = (math.pi / 2, 0, -heading)  # look horizontally along heading
    scene.camera = pano
    scene.render.resolution_x, scene.render.resolution_y = 360, 180
    scene.cycles.samples, scene.cycles.use_denoising = 16, False
    scene.render.image_settings.file_format = "OPEN_EXR"
    scene.render.filepath = str(Path(scratch) / "horizon.exr")
    bpy.ops.render.render(write_still=True)
    image = bpy.data.images.load(scene.render.filepath, check_existing=False)
    px = np.array(image.pixels[:]).reshape(180, 360, 4)[:, :, :3]  # row 0 = bottom
    bpy.data.images.remove(image)
    # Below ~3 degrees an elevated camera sees the sky model's dark ground.
    band = px[90 + 4:90 + 10, 180 - 40:180 + 40].reshape(-1, 3)
    if all_azimuths:  # into-the-sun views: the sun-side sky would bleach the haze white
        band = px[90 + 4:90 + 10, :].reshape(-1, 3)
    (scene.camera, scene.render.resolution_x, scene.render.resolution_y, scene.cycles.samples,
     scene.render.filepath, scene.render.image_settings.file_format,
     scene.cycles.use_denoising) = saved
    bpy.data.objects.remove(pano, do_unlink=True)
    for child in layer.children:
        child.exclude = excluded[child.name]
    colour = np.median(band, axis=0) if all_azimuths else band.mean(axis=0)
    if colour.max() < 0.01:
        lrh.fail(f"horizon sky colour measured as {colour}; haze would darken the horizon")
    return colour


def configure_haze(scene, camera, visibility_km, scratch, all_azimuths=False):
    """Aerial perspective in the compositor: each pixel fades toward the measured horizon
    sky colour by 1 - exp(-k d), with k from the meteorological visibility (contrast 2%
    at that range, Koschmieder). The sky itself (no depth) is left untouched."""
    # Measure the horizon first: the pano render must not pass through this compositor.
    scene.render.use_compositing = False
    colour = horizon_colour(scene, camera, scratch, all_azimuths) if visibility_km else None
    scene.render.use_compositing = True
    tree = bpy.data.node_groups.new("LRH_Haze", "CompositorNodeTree")
    scene.compositing_node_group = tree
    nodes, links = tree.nodes, tree.links
    layers = nodes.new("CompositorNodeRLayers")
    out = nodes.new("NodeGroupOutput")
    tree.interface.new_socket("Image", in_out="OUTPUT", socket_type="NodeSocketColor")
    if not visibility_km:
        links.new(layers.outputs["Image"], out.inputs[0])
        return None
    bpy.context.view_layer.use_pass_z = True
    k = 3.912 / (visibility_km * 1000.0)

    def math_node(op, a=None, b=None):
        node = nodes.new("ShaderNodeMath")
        node.operation = op
        for socket, value in ((0, a), (1, b)):
            if isinstance(value, (int, float)):
                node.inputs[socket].default_value = value
            elif value is not None:
                links.new(value, node.inputs[socket])
        return node.outputs[0]

    depth = layers.outputs["Depth"]
    transmit = math_node("EXPONENT", math_node("MULTIPLY", depth, -k))
    factor = math_node("SUBTRACT", 1.0, transmit)
    factor = math_node("MULTIPLY", factor, math_node("LESS_THAN", depth, 1.0e6))
    mix = nodes.new("ShaderNodeMix")
    mix.data_type = "RGBA"
    links.new(factor, mix.inputs["Factor"])
    links.new(layers.outputs["Image"], mix.inputs["A"])
    mix.inputs["B"].default_value = (*colour, 1.0)
    links.new(mix.outputs["Result"], out.inputs[0])
    return {"visibility_km": visibility_km, "extinction_per_m": k,
            "horizon_colour_linear": [round(float(c), 4) for c in colour]}


def place_life(shot):
    """Per-shot placement of the ski boat and gull flock (scene_life builds them at
    their defaults). shots.yaml: boat: {xy: [x, y], heading_deg: h}; gulls: [x, y, z]."""
    import scene_life
    boat = bpy.data.objects.get("Ski_Boat")
    if boat is not None:
        spec = shot.get("boat", {})
        x, y = spec.get("xy", scene_life.BOAT_XY)
        heading = spec.get("heading_deg", scene_life.BOAT_HEADING_DEG)
        boat.location = (x, y, lrh.POOL_M)
        boat.rotation_euler = (0.0, 0.0, math.pi / 2 - math.radians(heading))
    target = shot.get("gulls")
    gulls = [o for o in bpy.data.objects if o.name.startswith("Gull_") and o.name[5:].isdigit()]
    if gulls:
        base = getattr(place_life, "_base", None)
        if base is None:
            base = {o.name: o.location.copy() for o in gulls}
            place_life._base = base
        delta = Vector(target) - Vector(scene_life.GULLS["centre"]) if target else Vector()
        for o in gulls:
            o.location = base[o.name] + delta


def apply_collections(scene, wanted):
    layer = bpy.context.view_layer.layer_collection
    known = {c.name for c in layer.children}
    missing = set(wanted) - known
    if missing:
        lrh.fail(f"shot lists unknown collections {sorted(missing)}")
    for child in layer.children:
        child.exclude = child.name not in wanted and child.name != "Cameras"


def apply_cabins(lots):
    """Show the listed lots' cabins and remove the trees set aside on their footprints."""
    keys = {lot.replace(" ", "_") for lot in lots}
    layer = bpy.context.view_layer.layer_collection
    if "Cabins" in layer.children:
        for child in layer.children["Cabins"].children:
            child.exclude = child.name.removeprefix("Cabin_") not in keys
    if "Vegetation" in layer.children:
        for child in layer.children["Vegetation"].children:
            if child.name.startswith("Vegetation_BuildSite_"):
                child.exclude = child.name.removeprefix("Vegetation_BuildSite_") in keys
    terrain = bpy.data.objects.get("Site_Terrain_1m")
    if terrain is not None and terrain.data.shape_keys is not None:
        for block in terrain.data.shape_keys.key_blocks:
            if block.name.startswith("Grade_"):
                block.value = 1.0 if block.name.removeprefix("Grade_") in keys else 0.0


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
    timber = args.flooded_timber or shot.get("flooded_timber", config.get("flooded_timber", "snags"))
    if timber != "none":
        wanted.add({"snags": "Flooded_Timber_Snags", "leafy": "Flooded_Timber_Leafy",
                    "dying": "Flooded_Timber_Dying"}[timber])
    moss = (args.spanish_moss == "on") if args.spanish_moss else \
        bool(shot.get("spanish_moss", config.get("spanish_moss", False)))
    if moss and timber in ("dying", "snags"):
        wanted.add("Spanish_Moss")
    for layer in ("redline", "driveways", "shoreline", "docks"):
        if shot.get(layer, config.get(layer, False)):
            wanted.add(layer.capitalize())
    # Phase 2d cabins (cabins.py): `cabins: [Lot 5]` or `cabins: all`.
    cabin_lots = shot.get("cabins", config.get("cabins", []))
    if cabin_lots == "all":
        cabin_lots = [f"Lot {i}" for i in range(1, 11)]
    if cabin_lots:
        wanted.add("Cabins")
    cleared = args.cleared_ground or shot.get("cleared_ground", config.get("cleared_ground", "soil"))
    node = bpy.data.materials["Ground_Site"].node_tree.nodes["LRH_Cleared_Grassed"]
    node.outputs[0].default_value = 1.0 if cleared == "grassed" else 0.0
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
    place_life(shot)
    # Flat lot numbers read upright from this camera: text +Y along the view heading.
    forward = camera.matrix_world.to_quaternion() @ Vector((0, 0, -1))
    if abs(forward.x) + abs(forward.y) > 1e-3:
        for obj in bpy.data.objects:
            if obj.name.startswith("Redline_") and obj.name.endswith("_Number"):
                obj.rotation_euler = (0, 0, math.atan2(-forward.x, forward.y))
    sun = configure_sky(scene, shot["sun"])
    with tempfile.TemporaryDirectory() as scratch:
        haze = configure_haze(scene, camera, shot.get("haze_visibility_km",
                                                      config.get("haze_visibility_km")), scratch,
                              shot.get("haze_colour") == "all_azimuths")
    apply_collections(scene, wanted)
    apply_cabins(cabin_lots)

    stem = f"{name}_{args.res}"
    if args.flooded_timber or args.cleared_ground or args.spanish_moss:
        stem += f"_{timber}_{cleared}" + ("_moss" if moss else "")
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
    text = config["caption"]
    if "Docks" in wanted:
        text += " " + config["caption_docks"]
    if cabin_lots and config.get("caption_cabins"):
        text += " " + config["caption_cabins"]
    if kind == "marketing":
        deliverable = out / f"{stem}.png"
        caption(master, deliverable, text)

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
        "caption": text if kind == "marketing" else None,
        "camera": {
            "type": cam.type, "location": list(camera.location),
            "rotation_euler": list(camera.rotation_euler), "lens_mm": cam.lens,
            "sensor_width_mm": cam.sensor_width, "ortho_scale": cam.ortho_scale,
            "clip_end": cam.clip_end,
        },
        "sun": sun,
        "haze": haze,
        "render": {"res": args.res, "resolution": [width, height], "samples": scene.cycles.samples,
                   "engine": scene.render.engine, "device": scene.cycles.device,
                   "exposure": scene.view_settings.exposure,
                   "view_transform": scene.view_settings.view_transform,
                   "seconds": round(seconds, 1)},
        "collections": sorted(wanted),
        "flooded_timber": timber,
        "spanish_moss": moss,
        "cleared_ground": cleared,
        "cabins": cabin_lots,
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
    if args.res != "draft":  # 4K and final frames go in their own subfolder
        out = out / args.res
        out.mkdir(exist_ok=True)
    for name in names:
        render_shot(name, shots[name], config, args, out)


if __name__ == "__main__":
    main()
