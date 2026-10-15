"""Aerial flyover test: render a smooth camera path as frames, then encode an MP4.

The path is a Catmull-Rom spline through camera and look-at keys (LRH local metres),
eased in and out. Frames are rendered one at a time (Cycles, persistent data so the
scene is built once), captioned (PLAN.md §7) and checked; the MP4 is assembled with
Blender's built-in FFmpeg encoder. Interrupted runs resume: existing frames are skipped.

Usage:
  Blender -b out/<date>/lrh_baseline.blend --python scripts/blender/flyover.py -- \
      [--frames 0,120,240,359] [--encode-only]
Output: out/<date>/video/frames/f_NNNN.png, flyover_test.mp4, flyover_test.json
"""

import json
import math
import sys
import tempfile
import time
from pathlib import Path

import bpy
import numpy as np
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lrh  # noqa: E402
import render  # noqa: E402
import yaml  # noqa: E402

FPS = 30
RES = (1920, 1080)
LENS_MM = 24.0
SUN = {"datetime": "2026-10-14T16:30", "utc_offset_h": -5}
HAZE_KM = 30
COLLECTIONS = ["Terrain", "Water", "Roads", "Landmarks", "Vegetation", "Driveways",
               "Shoreline", "Flooded_Timber_Dying", "Spanish_Moss"]
# (camera position, look-at) keys: high over CR 3635 south-east of the lots, across the
# turnarounds and the Lot 1 site, then rising over the flooded timber to the lake.
# Variants: name -> (seconds, samples, keys). "test" is the approved 12 s path.
TEST_KEYS = [((420.0, -560.0, 380.0), (-40.0, -20.0, 176.0)),
        ((250.0, -300.0, 340.0), (-110.0, 120.0, 174.0)),
        ((90.0, -40.0, 310.0), (-230.0, 330.0, 170.0)),
        ((-80.0, 200.0, 320.0), (-400.0, 800.0, 168.0)),
        ((-150.0, 330.0, 335.0), (-440.0, 780.0, 168.0))]
# Full version (owner, 15 Oct 2026): approach from far over CR 3635, over the lots and
# Lot 1, across the flooded timber, then arc west over the arm and turn to look back
# south-east across the timber at the lots.
FULL_KEYS = [((760.0, -980.0, 430.0), (40.0, -60.0, 176.0)),
             ((420.0, -560.0, 380.0), (-40.0, -20.0, 176.0)),
             ((230.0, -280.0, 345.0), (-110.0, 140.0, 174.0)),
             ((80.0, -20.0, 320.0), (-230.0, 340.0, 170.0)),
             ((-90.0, 210.0, 320.0), (-420.0, 780.0, 168.0)),
             ((-320.0, 480.0, 330.0), (-520.0, 1200.0, 168.0)),
             ((-560.0, 640.0, 320.0), (-200.0, 380.0, 170.0)),
             ((-660.0, 380.0, 300.0), (0.0, 40.0, 176.0))]
VARIANTS = {"test": (12, 32, TEST_KEYS), "full": (36, 64, FULL_KEYS)}
KEYS, SECONDS, SAMPLES = TEST_KEYS, 12, 32


def catmull_rom(points, t):
    """Point on a centripetal-free (uniform) Catmull-Rom spline through `points`, t in [0, 1]."""
    p = np.vstack([points[0], points, points[-1]])
    n = len(points) - 1
    s = min(t * n, n - 1e-9)
    i = int(s) + 1
    u = s - (i - 1)
    p0, p1, p2, p3 = p[i - 1], p[i], p[i + 1], p[i + 2]
    return 0.5 * ((2 * p1) + (-p0 + p2) * u + (2 * p0 - 5 * p1 + 4 * p2 - p3) * u ** 2
                  + (-p0 + 3 * p1 - 3 * p2 + p3) * u ** 3)


def ease(t):
    return t * t * (3 - 2 * t)


_ARC = {}


def pose(frame, total):
    """Constant ground speed along the camera spline (arc-length parametrised), eased
    in and out; the look-at point follows the same spline parameter."""
    cams = np.array([k[0] for k in KEYS])
    looks = np.array([k[1] for k in KEYS])
    key = id(KEYS)
    if key not in _ARC:
        u = np.linspace(0, 1, 4001)
        pts = np.array([catmull_rom(cams, x) for x in u])
        length = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(pts, axis=0), axis=1))])
        _ARC[key] = (u, length / length[-1])
    u, s = _ARC[key]
    t = float(np.interp(ease(frame / (total - 1)), s, u))
    return catmull_rom(cams, t), catmull_rom(looks, t)


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    global KEYS, SECONDS, SAMPLES
    variant = argv[argv.index("--variant") + 1] if "--variant" in argv else "test"
    SECONDS, SAMPLES, KEYS = VARIANTS[variant]
    total = FPS * SECONDS
    only = None
    if "--frames" in argv:
        only = [int(f) for f in argv[argv.index("--frames") + 1].split(",")]
    out = lrh.out_dir() / "video" / variant
    frames_dir = out / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    config = yaml.safe_load((lrh.ROOT / "shots.yaml").read_text())["render"]
    scene = bpy.context.scene
    if "--encode-only" not in argv:
        render.configure_device(scene)
        render.configure_sky(scene, SUN)
        bpy.data.materials["Ground_Site"].node_tree.nodes["LRH_Cleared_Grassed"].outputs[0].default_value = 1.0
        render.apply_collections(scene, set(COLLECTIONS))
        cam = bpy.data.objects.new("CAM_flyover", bpy.data.cameras.new("CAM_flyover"))
        scene.collection.objects.link(cam)
        cam.data.lens, cam.data.clip_start, cam.data.clip_end = LENS_MM, 1.0, 60000.0
        scene.camera = cam
        scene.render.resolution_x, scene.render.resolution_y = RES
        scene.render.resolution_percentage = 100
        scene.cycles.samples = SAMPLES
        scene.render.use_persistent_data = True
        scene.view_settings.exposure = config.get("exposure", -4.0)
        loc, look = pose(0, total)
        cam.location = Vector(loc)
        cam.rotation_euler = (Vector(look) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
        with tempfile.TemporaryDirectory() as scratch:
            render.configure_haze(scene, cam, HAZE_KM, scratch)  # horizon colour from frame 0
        todo = only if only is not None else range(total)
        started = time.time()
        for f in todo:
            path = frames_dir / f"f_{f:04d}.png"
            if path.exists() and only is None:
                continue
            loc, look = pose(f, total)
            cam.location = Vector(loc)
            cam.rotation_euler = (Vector(look) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
            raw = frames_dir / f"raw_{f:04d}.png"
            scene.render.filepath = str(raw)
            t0 = time.time()
            bpy.ops.render.render(write_still=True)
            if f % 30 == 0 or only is not None:
                try:
                    lrh.frame_stats(raw)
                except lrh.CheckFailed as error:
                    lrh.fail(f"frame {f}: {error}")
            render.caption(raw, path, config["caption"])
            raw.unlink()
            print(f"FRAME {f} {time.time() - t0:.1f}s", flush=True)
        print(f"RENDERED {len(list(todo))} frames in {time.time() - started:.0f}s")
    if only is not None:
        return
    # Encode with Blender's FFmpeg through the sequencer.
    missing = [f for f in range(total) if not (frames_dir / f"f_{f:04d}.png").exists()]
    if missing:
        lrh.fail(f"{len(missing)} frames missing, first {missing[0]}")
    enc = bpy.data.scenes.new("LRH_Encode")
    enc.render.resolution_x, enc.render.resolution_y = RES
    enc.render.resolution_percentage = 100
    enc.render.fps = FPS
    enc.frame_start, enc.frame_end = 1, total
    seq = enc.sequence_editor_create()
    files = sorted(p.name for p in frames_dir.glob("f_*.png"))
    strips = seq.strips if hasattr(seq, "strips") else seq.sequences
    strip = strips.new_image("frames", str(frames_dir / files[0]), 1, 1)
    for name in files[1:]:
        strip.elements.append(name)
    if hasattr(enc.render.image_settings, "media_type"):  # Blender 5: video is a media type
        enc.render.image_settings.media_type = "VIDEO"
    enc.render.image_settings.file_format = "FFMPEG"
    enc.render.ffmpeg.format = "MPEG4"
    enc.render.ffmpeg.codec = "H264"
    enc.render.ffmpeg.constant_rate_factor = "HIGH"
    enc.render.ffmpeg.ffmpeg_preset = "GOOD"
    enc.view_settings.view_transform = "Standard"  # frames are already display-referred
    enc.render.filepath = str(out / f"flyover_{variant}.mp4")
    bpy.ops.render.render(animation=True, scene=enc.name)
    (out / f"flyover_{variant}.json").write_text(json.dumps({"variant": variant,
        "schema": "lrh.flyover/1", "rendered_utc": lrh.utc_now(), "git": lrh.git_commit(),
        "blend": bpy.data.filepath, "fps": FPS, "seconds": SECONDS, "resolution": RES,
        "samples": SAMPLES, "lens_mm": LENS_MM, "sun": SUN, "haze_km": HAZE_KM,
        "collections": COLLECTIONS, "keys": KEYS, "caption": config["caption"]}, indent=1) + "\n")
    print("ENCODED", out / f"flyover_{variant}.mp4")


if __name__ == "__main__":
    main()
