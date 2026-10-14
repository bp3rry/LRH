"""Phase 0 smoke test: load terrain, regional terrain and lake into Blender, render
one oblique frame, and fail loudly if the frame is blank or a mesh is missing.

Usage:
  /Applications/Blender.app/Contents/MacOS/Blender -b --python scripts/blender/smoke_test.py
"""

import json
import re
import sys
from datetime import date
from pathlib import Path

import bpy
import numpy as np
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[2]
INPUTS = ROOT / "inputs"
OUT = ROOT / "out" / date.today().isoformat()

ORIGIN = json.loads((INPUTS / "terrain/origin.json").read_text())
ORIGIN_E = ORIGIN["origin"]["easting"]
ORIGIN_N = ORIGIN["origin"]["northing"]
EXPECTED_TERRAIN_VERTICES = ORIGIN["meshes"]["design"]["vertices"]


def fail(message):
    print(f"SMOKE TEST FAILED: {message}", file=sys.stderr)
    sys.exit(1)


def clear_scene():
    # Not read_factory_settings(): it unloads importers (see CLAUDE.md).
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)


def material(name, rgb, roughness=0.8):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (*rgb, 1.0)
    bsdf.inputs["Roughness"].default_value = roughness
    return mat


def import_site_terrain():
    # PTM OBJ is Y-up with z = -northing; Blender's default OBJ axes map it to
    # X = easting offset, Y = northing offset, Z = elevation.
    bpy.ops.wm.obj_import(filepath=str(INPUTS / "terrain/terrain_design.obj"))
    terrain = bpy.context.selected_objects[0]
    terrain.name = "Site_Terrain_1m"
    if len(terrain.data.vertices) != EXPECTED_TERRAIN_VERTICES:
        fail(f"terrain has {len(terrain.data.vertices)} vertices, origin.json says "
             f"{EXPECTED_TERRAIN_VERTICES}")
    return terrain


def dae_mesh(text, geometry_id, name):
    """Build a mesh from one <geometry> of the PTM lake DAE (absolute EPSG:6344, Z-up)."""
    positions = re.search(
        rf'<float_array id="{geometry_id}-positions-array"[^>]*>([^<]*)', text).group(1)
    block = text[text.index(f'<geometry id="{geometry_id}"'):]
    block = block[:block.index("</geometry>")]
    triangles = re.search(r"<triangles[^>]*>(.*?)<p>([^<]*)</p>", block, re.S)
    if triangles.group(1).count("<input") != 1:
        fail(f"{geometry_id}: expected a single VERTEX input per triangle index")
    coords = np.array(positions.split(), dtype=float).reshape(-1, 3)
    coords[:, 0] -= ORIGIN_E
    coords[:, 1] -= ORIGIN_N
    tris = np.array(triangles.group(2).split(), dtype=int).reshape(-1, 3)
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(coords.tolist(), [], tris.tolist())
    mesh.validate()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    if not mesh.polygons:
        fail(f"{name} has no faces")
    return obj


def setup_render(scene):
    scene.render.engine = "CYCLES"
    prefs = bpy.context.preferences.addons["cycles"].preferences
    prefs.compute_device_type = "METAL"
    prefs.get_devices()
    for device in prefs.devices:
        device.use = True
    scene.cycles.device = "GPU"
    scene.cycles.samples = 32
    scene.cycles.use_denoising = True
    scene.render.resolution_x = 960
    scene.render.resolution_y = 540
    scene.render.image_settings.file_format = "PNG"

    world = bpy.data.worlds.new("Sky")
    scene.world = world
    world.use_nodes = True
    sky = world.node_tree.nodes.new("ShaderNodeTexSky")
    background = world.node_tree.nodes["Background"]
    world.node_tree.links.new(sky.outputs["Color"], background.inputs["Color"])
    background.inputs["Strength"].default_value = 0.15  # the sun lamp carries the key light

    sun = bpy.data.objects.new("Sun", bpy.data.lights.new("Sun", "SUN"))
    sun.data.energy = 4.0
    sun.rotation_euler = (0.9, 0.0, 2.4)
    scene.collection.objects.link(sun)


def add_camera(scene):
    cam = bpy.data.objects.new("Cam_Smoke", bpy.data.cameras.new("Cam_Smoke"))
    cam.data.lens = 28
    cam.data.clip_start = 1.0
    cam.data.clip_end = 50000.0  # default 1000 m clips everything at this scale
    cam.location = (900.0, -1100.0, 550.0)
    direction = Vector((-150.0, 150.0, 168.0)) - cam.location
    cam.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    scene.collection.objects.link(cam)
    scene.camera = cam


def check_frame(path):
    image = bpy.data.images.load(str(path))
    pixels = np.array(image.pixels[:], dtype=np.float64).reshape(-1, 4)[:, :3]
    luminance = (0.2126 * pixels[:, 0] + 0.7152 * pixels[:, 1] + 0.0722 * pixels[:, 2])
    stats = {
        "mean": float(luminance.mean()),
        "std": float(luminance.std()),
        "clipped_fraction": float((luminance > 0.97).mean()),
        "black_fraction": float((luminance < 0.02).mean()),
    }
    print("frame luminance " + " ".join(f"{k}={v:.3f}" for k, v in stats.items()))
    if stats["std"] < 0.05:
        fail(f"frame looks blank (luminance std {stats['std']:.4f})")
    if stats["clipped_fraction"] > 0.25 or stats["black_fraction"] > 0.25:
        fail("frame is mostly clipped or black; check exposure")
    return stats


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    clear_scene()
    scene = bpy.context.scene

    terrain = import_site_terrain()
    terrain.data.materials.append(material("Ground", (0.30, 0.36, 0.18)))

    dae = (INPUTS / "geometry/lake-ralph-hall-50m-terrain-551ft-reference.dae").read_text()
    regional = dae_mesh(dae, "regional-terrain-50m", "Regional_Terrain_50m")
    regional.data.materials.append(material("Regional", (0.28, 0.32, 0.20)))
    regional.location.z = -0.5  # sit just under the 1 m site mesh where they overlap
    lake = dae_mesh(dae, "official-lake-551ft", "Lake_551ft_UTRWD")
    lake.data.materials.append(material("Water", (0.05, 0.15, 0.22), roughness=0.05))

    setup_render(scene)
    add_camera(scene)

    frame = OUT / "smoke_test.png"
    scene.render.filepath = str(frame)
    bpy.ops.render.render(write_still=True)
    stats = check_frame(frame)
    bpy.ops.wm.save_as_mainfile(filepath=str(OUT / "lrh_smoke.blend"))

    summary = {
        "terrain_vertices": len(terrain.data.vertices),
        "regional_faces": len(regional.data.polygons),
        "lake_faces": len(lake.data.polygons),
        "frame": str(frame),
        "luminance": stats,
    }
    (OUT / "smoke_test.json").write_text(json.dumps(summary, indent=2) + "\n")
    print("SMOKE TEST PASSED", json.dumps(summary))


main()
