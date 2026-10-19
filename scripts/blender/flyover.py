"""Aerial flyover test: render a smooth camera path as frames, then encode an MP4.

The path is a Catmull-Rom spline through camera and look-at keys (LRH local metres),
eased in and out. Frames are rendered one at a time (Cycles, persistent data so the
scene is built once), captioned (PLAN.md §7) and checked; the MP4 is assembled with
Blender's built-in FFmpeg encoder. Interrupted runs resume: existing frames are skipped.

Usage:
  Blender -b out/<date>/lrh_baseline.blend --python scripts/blender/flyover.py -- \
      [--variant test|full|oval|low] [--frames 0,120,240,359] [--encode-only] [--preview]

Variant "low" (Phase 3a) reads its per-frame poses from out/derived/flight_low.json
(scripts/flight_path.py), shows the Lot 5 cabin and the walking path, at golden hour.
--preview renders the animatic: 960 x 540, 8 samples, every third frame, encoded at 10 fps.
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


def oval_keys(n=40):
    """Owner, 15 Oct 2026: an oval orbit instead of the full path's sharp return turn.
    The camera runs clockwise (seen from above) round an ellipse centred on the lots and
    timber, from over CR 3635 south-east of the property, round the south and west over
    the timber, about 180 degrees, ending north-west over the water looking south-east
    across the flooded timber at the lots. It looks a third of the way out toward
    a spot ~40 degrees ahead on the orbit, around a point biased toward the lots, so the
    view leads gently into the turn and keeps the lots in frame."""
    cx, cy, a, b = -150.0, 170.0, 560.0, 470.0   # centre; semi-axes north-south, east-west
    keys = []
    lx, ly = -100.0, 120.0                         # look centre, biased toward the lots
    for th in np.linspace(math.radians(-50), math.radians(-232), n):
        alt = 335.0 + 25.0 * math.sin(th * 1.5)            # slow 310-360 m rise and fall
        cam = (cx + b * math.cos(th), cy + a * math.sin(th), alt)
        ahead = th - math.radians(40)
        look = (lx + 0.33 * b * math.cos(ahead), ly + 0.33 * a * math.sin(ahead), 170.0)
        keys.append((cam, look))
    return keys


OVAL_KEYS = oval_keys()
VARIANTS = {"test": (12, 32, TEST_KEYS), "full": (36, 64, FULL_KEYS),
            "oval": (60, 64, OVAL_KEYS), "low": (None, 64, None)}
# Phase 3a low-altitude flight (owner, 19 Oct 2026): golden hour, one illustrative cabin.
LOW = {"sun": {"datetime": "2026-10-14T18:10", "utc_offset_h": -5}, "exposure": -2.5,
       "haze_km": 25, "cabins": ["Lot 5"],
       "collections": ["Terrain", "Water", "Roads", "Landmarks", "Vegetation", "Shoreline",
                       "Flooded_Timber_Dying", "Spanish_Moss", "Lake_Life"]}
POSES = None
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
TILT_KNEE_DEG, TILT_WIDTH_DEG = 19.0, 4.0


def pose(frame, total):
    """Constant ground speed along the camera spline (arc-length parametrised), eased
    in and out; the look-at point follows the same spline parameter. The low variant
    uses the precomputed, clearance-checked poses."""
    if POSES is not None:
        cam, look = POSES[frame]
        return np.array(cam), np.array(look)
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
    cam, look = catmull_rom(cams, t), catmull_rom(looks, t)
    # Soft cap on down-tilt: during the return turn the look-at spline passes under the
    # camera and the view would tip ~40 deg down onto dark water. Below the knee the
    # pose is unchanged; above it the tilt saturates smoothly at knee + width.
    d = look - cam
    horiz = math.hypot(d[0], d[1])
    pitch = math.degrees(math.atan2(-d[2], horiz))
    if pitch > TILT_KNEE_DEG:
        capped = TILT_KNEE_DEG + TILT_WIDTH_DEG * math.tanh((pitch - TILT_KNEE_DEG) / TILT_WIDTH_DEG)
        dist = float(np.linalg.norm(d))
        hx, hy = d[0] / max(horiz, 1e-9), d[1] / max(horiz, 1e-9)
        r = math.radians(capped)
        look = cam + dist * np.array([hx * math.cos(r), hy * math.cos(r), -math.sin(r)])
    return cam, look


# Lake life in the oval flyover (owner, 16 Oct 2026). The boat runs ENE across the open
# main lake north-east of the property (>=247 m from shore and >=363 m from the habitat
# zone for the whole minute) at slalom speed. Two gull flocks are placed where the
# camera passes them, flying against the camera so they sweep through the frame.
BOAT_ROUTE = {"start": (150.0, 940.0), "heading_deg": 70.0, "speed_ms": 13.0}
GULL_FLOCKS = [{"frame": 360, "ahead_m": 42.0, "below_m": 14.0, "heading_off_deg": 170.0},
               {"frame": 1260, "ahead_m": 42.0, "below_m": 14.0, "heading_off_deg": 160.0}]
GULL_SPEED_MS, FLAP_HZ = 11.0, 2.6
LIFE_COLLECTIONS = ["Lake_Life", "Gulls"]


class Life:
    """Moves the boat and gulls each frame; gull wings cycle through three poses."""

    def __init__(self, total):
        import scene_life
        self.total = total
        self.boat = bpy.data.objects.get("Ski_Boat")
        self.poses = [bpy.data.meshes[f"Gull_Wings_{i}"] for i in range(3)]
        gulls = sorted((o for o in bpy.data.objects if o.name.startswith("Gull_") and o.name[5:].isdigit()),
                       key=lambda o: o.name)
        centre = Vector(scene_life.GULLS["centre"])
        offsets = [o.location - centre for o in gulls]
        rng = np.random.default_rng(1016)
        self.gulls = []
        half = len(gulls) // 2
        for k, (g, off) in enumerate(zip(gulls, offsets)):
            flock = GULL_FLOCKS[0] if k < half else GULL_FLOCKS[1]
            cam, look = pose(flock["frame"], total)
            d = (look - cam) / np.linalg.norm(look - cam)
            anchor = cam + d * flock["ahead_m"] - np.array([0, 0, flock["below_m"]])
            cam_heading = math.degrees(math.atan2(d[0], d[1]))
            heading = math.radians(cam_heading + flock["heading_off_deg"] + rng.uniform(-12, 12))
            self.gulls.append({"obj": g, "anchor": anchor, "frame": flock["frame"],
                               "offset": np.array(off) * 0.45, "heading": heading,
                               "phase": rng.uniform(0, 1), "bob": rng.uniform(0, 6.28)})

    def __call__(self, frame):
        t = frame / FPS
        if self.boat is not None:
            h = math.radians(BOAT_ROUTE["heading_deg"])
            x0, y0 = BOAT_ROUTE["start"]
            dist = BOAT_ROUTE["speed_ms"] * t
            self.boat.location = (x0 + math.sin(h) * dist, y0 + math.cos(h) * dist, lrh.POOL_M)
            self.boat.rotation_euler = (0.0, 0.0, math.pi / 2 - h)
        for g in self.gulls:
            dt = (frame - g["frame"]) / FPS
            vel = np.array([math.sin(g["heading"]), math.cos(g["heading"]), 0.0]) * GULL_SPEED_MS
            pos = g["anchor"] + g["offset"] + vel * dt
            pos[2] += 0.4 * math.sin(2 * math.pi * 0.5 * t + g["bob"])
            obj = g["obj"]
            obj.location = Vector(pos)
            obj.rotation_euler = (0.0, 0.0, math.pi / 2 - g["heading"])
            cycle = (t * FLAP_HZ + g["phase"]) % 1.0
            obj.data = self.poses[[0, 1, 2, 1][int(cycle * 4) % 4]]


class BoatOnly:
    """The ski boat on its open-lake route (no gulls: their flocks are placed for the oval)."""

    def __init__(self):
        self.boat = bpy.data.objects.get("Ski_Boat")

    def __call__(self, frame):
        if self.boat is None:
            return
        h = math.radians(BOAT_ROUTE["heading_deg"])
        x0, y0 = BOAT_ROUTE["start"]
        dist = BOAT_ROUTE["speed_ms"] * frame / FPS
        self.boat.location = (x0 + math.sin(h) * dist, y0 + math.cos(h) * dist, lrh.POOL_M)
        self.boat.rotation_euler = (0.0, 0.0, math.pi / 2 - h)


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    global KEYS, SECONDS, SAMPLES, POSES, SUN, HAZE_KM, COLLECTIONS, RES
    variant = argv[argv.index("--variant") + 1] if "--variant" in argv else "test"
    SECONDS, SAMPLES, KEYS = VARIANTS[variant]
    fps, step, exposure, cabins = FPS, 1, None, []
    if variant == "low":
        flight = json.loads((lrh.ROOT / "out/derived/flight_low.json").read_text())
        if not flight["checks"]["passed"]:
            lrh.fail(f"flight_low.json failed its clearance checks: {flight['checks']}")
        POSES = flight["poses"]
        SECONDS = len(POSES) / FPS
        KEYS = flight["keys"]
        SUN, HAZE_KM, COLLECTIONS = LOW["sun"], LOW["haze_km"], LOW["collections"]
        exposure, cabins = LOW["exposure"], LOW["cabins"]
    total = len(POSES) if POSES is not None else FPS * SECONDS
    if "--preview" in argv:
        RES, SAMPLES, step, fps = (960, 540), 8, 3, FPS // 3
        variant_dir = f"{variant}_preview"
    else:
        variant_dir = variant
    only = None
    if "--frames" in argv:
        only = [int(f) for f in argv[argv.index("--frames") + 1].split(",")]
    out = lrh.out_dir() / "video" / variant_dir
    frames_dir = out / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    config = yaml.safe_load((lrh.ROOT / "shots.yaml").read_text())["render"]
    scene = bpy.context.scene
    if "--encode-only" not in argv:
        render.configure_device(scene)
        render.configure_sky(scene, SUN)
        bpy.data.materials["Ground_Site"].node_tree.nodes["LRH_Cleared_Grassed"].outputs[0].default_value = 1.0
        life = None
        if variant == "oval":
            render.apply_collections(scene, set(COLLECTIONS + LIFE_COLLECTIONS))
            life = Life(total)
        elif variant == "low":
            render.apply_collections(scene, set(COLLECTIONS + ["Cabins"]))
            render.apply_cabins(cabins)
            life = BoatOnly()
        else:
            render.apply_collections(scene, set(COLLECTIONS))
        cam = bpy.data.objects.new("CAM_flyover", bpy.data.cameras.new("CAM_flyover"))
        scene.collection.objects.link(cam)
        cam.data.lens, cam.data.clip_start, cam.data.clip_end = LENS_MM, 1.0, 60000.0
        scene.camera = cam
        scene.render.resolution_x, scene.render.resolution_y = RES
        scene.render.resolution_percentage = 100
        scene.cycles.samples = SAMPLES
        scene.render.use_persistent_data = True
        scene.view_settings.exposure = exposure if exposure is not None else config.get("exposure", -4.0)
        loc, look = pose(0, total)
        cam.location = Vector(loc)
        cam.rotation_euler = (Vector(look) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
        with tempfile.TemporaryDirectory() as scratch:
            render.configure_haze(scene, cam, HAZE_KM, scratch,  # horizon colour from frame 0
                                  all_azimuths=variant == "low")
        todo = only if only is not None else range(0, total, step)
        caption = config["caption"] + (" " + config["caption_cabins"] if cabins and config.get("caption_cabins") else "")
        started = time.time()
        for f in todo:
            path = frames_dir / f"f_{f:04d}.png"
            if path.exists() and only is None:
                continue
            loc, look = pose(f, total)
            cam.location = Vector(loc)
            cam.rotation_euler = (Vector(look) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
            if life is not None:
                life(f)
            raw = frames_dir / f"raw_{f:04d}.png"
            scene.render.filepath = str(raw)
            t0 = time.time()
            bpy.ops.render.render(write_still=True)
            if True:  # every frame: a blank frame must fail (CLAUDE.md)
                try:
                    lrh.frame_stats(raw)
                except lrh.CheckFailed as error:
                    lrh.fail(f"frame {f}: {error}")
            render.caption(raw, path, caption)
            raw.unlink()
            print(f"FRAME {f} {time.time() - t0:.1f}s", flush=True)
        print(f"RENDERED {len(list(todo))} frames in {time.time() - started:.0f}s")
    if only is not None:
        return
    # Encode with Blender's FFmpeg through the sequencer.
    missing = [f for f in range(0, total, step) if not (frames_dir / f"f_{f:04d}.png").exists()]
    if missing:
        lrh.fail(f"{len(missing)} frames missing, first {missing[0]}")
    enc = bpy.data.scenes.new("LRH_Encode")
    enc.render.resolution_x, enc.render.resolution_y = RES
    enc.render.resolution_percentage = 100
    enc.render.fps = fps
    files = sorted(p.name for p in frames_dir.glob("f_*.png"))
    enc.frame_start, enc.frame_end = 1, len(files)
    seq = enc.sequence_editor_create()
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
    enc.render.filepath = str(out / f"flyover_{variant_dir}.mp4")
    bpy.ops.render.render(animation=True, scene=enc.name)
    (out / f"flyover_{variant_dir}.json").write_text(json.dumps({"variant": variant_dir,
        "schema": "lrh.flyover/1", "rendered_utc": lrh.utc_now(), "git": lrh.git_commit(),
        "blend": bpy.data.filepath, "fps": fps, "seconds": SECONDS, "resolution": RES,
        "samples": SAMPLES, "lens_mm": LENS_MM, "sun": SUN, "haze_km": HAZE_KM,
        "collections": COLLECTIONS, "keys": KEYS, "caption": config["caption"]}, indent=1) + "\n")
    print("ENCODED", out / f"flyover_{variant_dir}.mp4")


if __name__ == "__main__":
    main()
