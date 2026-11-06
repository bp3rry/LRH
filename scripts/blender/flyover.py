"""Aerial flyover test: render a smooth camera path as frames, then encode an MP4.

The path is a Catmull-Rom spline through camera and look-at keys (LRH local metres),
eased in and out. Frames are rendered one at a time (Cycles, persistent data so the
scene is built once), captioned (PLAN.md §7) and checked; the MP4 is assembled with
Blender's built-in FFmpeg encoder. Interrupted runs resume: existing frames are skipped.

Usage:
  Blender -b out/<date>/lrh_baseline.blend --python scripts/blender/flyover.py -- \
      [--variant test|full|oval|low] [--frames 0,120,240,359] [--encode-only] [--preview]
      [--4k] [--shard i/n] [--partial] [--profile] [--scene permit] [--step n]
      [--clip a:b]

Variant "low" (Phase 3a) reads its per-frame poses from out/derived/flight_low.json
(scripts/flight_path.py), shows the Lot 5 cabin and the walking path, at golden hour.
--preview renders the animatic: 960 x 540, 8 samples, every third frame, encoded at 10 fps.
--step n renders every n-th frame, encoded at 30/n fps (--preview --step 1: the smooth 30 fps
preview; it reuses the every-third frames already in the folder).
--clip a:b renders and encodes only frames a to b-1 (a review clip: flyover_<dir>_clip_a_b.mp4).
--4k renders 3840 x 2160 into <variant>_4k/. --shard i/n renders one GPU's share and
skips the encode (scripts/cloud/ runs one shard per GPU on a RunPod pod).
Output: out/<date>/video/frames/f_NNNN.png, flyover_test.mp4, flyover_test.json
"""

import hashlib
import json
import math
import subprocess
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
POST_WORKERS = 3
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
       "haze_km": 25, "cabins": [f"Lot {i}" for i in range(1, 11)],   # build-out (owner, 20 Oct)
       "collections": ["Terrain", "Water", "Roads", "Landmarks", "Vegetation", "Shoreline",
                       "Flooded_Timber_Dying", "Spanish_Moss", "Lake_Life", "Ground_Detail",
                       "Site_Works", "Planting", "Beach", "Docks"]}
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
    """The ski boat on its open-lake route (no gulls: their flocks are placed for the oval).
    Moved only on frames where it is within the camera's horizontal field of view (plus a
    margin): it stays 1-1.9 km off, and every move makes Cycles rebuild the scene BVH,
    which costs minutes a frame on a busy cloud host. Off-screen it simply waits."""

    MARGIN_DEG = 10.0

    def __init__(self, total, lens_mm, start=0):
        self.boat = bpy.data.objects.get("Ski_Boat")
        self.total = total
        self.start = start          # the boat's clock starts with the main flight (after the sign intro)
        self.half_fov = math.degrees(math.atan(18.0 / lens_mm)) + self.MARGIN_DEG  # 36 mm sensor
        self.placed = False

    def __call__(self, frame):
        if self.boat is None:
            return
        h = math.radians(BOAT_ROUTE["heading_deg"])
        x0, y0 = BOAT_ROUTE["start"]
        dist = BOAT_ROUTE["speed_ms"] * (frame - self.start) / FPS
        bx, by = x0 + math.sin(h) * dist, y0 + math.cos(h) * dist
        cam, look = pose(frame, self.total)
        view = math.atan2(look[0] - cam[0], look[1] - cam[1])

        def in_view(x, y):
            off = math.degrees(math.atan2(x - cam[0], y - cam[1]) - view)
            return abs((off + 180.0) % 360.0 - 180.0) <= self.half_fov
        # Place it on the first frame rendered; after that only while it, or the spot it
        # was left at, can be seen.
        if self.placed and not in_view(bx, by) and not in_view(*self.boat.location[:2]):
            return
        self.boat.location = (bx, by, lrh.POOL_M)
        self.boat.rotation_euler = (0.0, 0.0, math.pi / 2 - h)
        self.placed = True


class LotLineFade:
    """Wraps the per-frame scene life: the red lot lines (Lot_Line_Red) fade in over the
    8 s before each lot-line hover (H1 over the creek, S1 north-east of the property, P1
    at the point of beginning), hold to its second key (H2, S2, P2) and fade out over the
    next 4 s (after P2, as the drone comes down to the for-sale sign)."""

    def __init__(self, inner, bench):
        self.inner = inner
        self.node = bpy.data.materials["Lot_Line_Red"].node_tree.nodes["LRH_LotLine_Alpha"]
        self.windows = [(bench[f"{k}1"] - 8 * FPS, bench[f"{k}1"], bench[f"{k}2"], 4 * FPS)
                        for k in ("H", "S", "P") if f"{k}1" in bench]

    def alpha(self, f):
        s = lambda x: min(max(x, 0.0), 1.0) ** 2 * (3 - 2 * min(max(x, 0.0), 1.0))
        return max([s((f - a0) / (a1 - a0)) * (1 - s((f - b0) / fade))
                    for a0, a1, b0, fade in self.windows], default=0.0)

    def __call__(self, f):
        if self.inner is not None:
            self.inner(f)
        a = round(self.alpha(f), 3)
        if self.node.outputs[0].default_value != a:
            self.node.outputs[0].default_value = a


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    global KEYS, SECONDS, SAMPLES, POSES, SUN, HAZE_KM, COLLECTIONS, RES
    variant = argv[argv.index("--variant") + 1] if "--variant" in argv else "test"
    SECONDS, SAMPLES, KEYS = VARIANTS[variant]
    fps, step, exposure, cabins = FPS, 1, None, []
    if variant == "low":
        flight = json.loads(lrh.FLIGHT_JSON.read_text())
        if not flight["checks"]["passed"]:
            lrh.fail(f"flight_low.json failed its clearance checks: {flight['checks']}")
        POSES = flight["poses"]
        SECONDS = len(POSES) / FPS
        KEYS = flight["keys"]
        SUN, HAZE_KM, COLLECTIONS = LOW["sun"], LOW["haze_km"], LOW["collections"]
        exposure, cabins = LOW["exposure"], LOW["cabins"]
    total = len(POSES) if POSES is not None else FPS * SECONDS
    suffix = "_pairs" if "--layout" in argv and argv[argv.index("--layout") + 1] == "pairs" else ""
    # --scene permit (owner, 31 Oct 2026): fly the permit scene (lrh_permit.blend) - the
    # property as it stands, no structures; baled hay fields, the two meandering permit
    # paths and the denser UTRWD woods. Its frames get their own folder.
    # --scene permit5 (owner, 1 Nov 2026): the approved four 5 ac lots, their docks and
    # paths (lrh_permit5.blend); the red lot lines fade in while the drone faces north.
    scene_arg = argv[argv.index("--scene") + 1] if "--scene" in argv else None
    permit = scene_arg in ("permit", "permit5")
    if permit:
        if not bpy.data.filepath.endswith(f"lrh_{scene_arg}.blend"):
            lrh.fail(f"--scene {scene_arg} renders out/<date>/lrh_{scene_arg}.blend "
                     f"(build_baseline.py -- --scene {scene_arg})")
        suffix = f"_{scene_arg}"
    if "--preview" in argv:
        RES, SAMPLES, step, fps = (960, 540), 8, 3, FPS // 3
        variant_dir = f"{variant}{suffix}_preview"
    else:
        variant_dir = variant + suffix
    if "--step" in argv:
        step = int(argv[argv.index("--step") + 1])
        fps = FPS // step
    if "--4k" in argv:
        RES = (3840, 2160)
        variant_dir += "_4k"
    only = None
    if "--frames" in argv:
        only = [int(f) for f in argv[argv.index("--frames") + 1].split(",")]
    clip = range(0, total)
    if "--clip" in argv:
        a, b = (int(v) for v in argv[argv.index("--clip") + 1].split(":"))
        clip = range(a, min(b, total))
    # --shard i/n: this process renders every n-th frame from i (one process per cloud
    # GPU; interleaved so each gets its share of the heavy and light stretches). The
    # shards share one frames folder; encode afterwards with --encode-only.
    shard = None
    if "--shard" in argv:
        i, n = (int(v) for v in argv[argv.index("--shard") + 1].split("/"))
        shard = (i, n)
    # Write next to the .blend being rendered (out/<build date>/), not today's date: a long
    # render that resumes after midnight must keep filling the same folder.
    out = Path(bpy.data.filepath).parent / "video" / variant_dir if bpy.data.filepath \
        else lrh.out_dir() / "video" / variant_dir
    frames_dir = out / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    # Frames resume by number, so a folder must hold one flight only: record the path's
    # fingerprint and refuse to mix (the 25 Oct 2026 opening renumbered every frame).
    flight_id = hashlib.sha256(json.dumps([POSES, KEYS, SECONDS], default=str).encode()).hexdigest()[:16]
    stamp = frames_dir / "flight.id"
    if stamp.exists() and stamp.read_text().strip() != flight_id:
        lrh.fail(f"{frames_dir} holds frames of a different flight path ({stamp.read_text().strip()}, "
                 f"now {flight_id}); move them aside before rendering or encoding")
    if not stamp.exists():
        if any(frames_dir.glob("f_*.png")):
            lrh.fail(f"{frames_dir} has frames but no flight.id; move them aside or stamp them")
        stamp.write_text(flight_id + "\n")
    config = yaml.safe_load((lrh.ROOT / "shots.yaml").read_text())["render"]
    scene = bpy.context.scene
    if "--encode-only" not in argv:
        render.configure_device(scene)
        render.configure_sky(scene, SUN)
        if variant == "low":
            import sky
            sky.world_clouds(scene)
        bpy.data.materials["Ground_Site"].node_tree.nodes["LRH_Cleared_Grassed"].outputs[0].default_value = 1.0
        life = None
        if variant == "oval":
            render.apply_collections(scene, set(COLLECTIONS + LIFE_COLLECTIONS))
            life = Life(total)
        elif variant == "low" and permit:
            render.apply_collections(scene, set(COLLECTIONS) - {"Site_Works", "Planting", "Beach", "Docks", "Shoreline"}
                                     | {"Landmarks", "Permit_Paths", "Hay"}
                                     | ({"Lot_Lines", "Sale_Sign"} if scene_arg == "permit5" else set()))
            hay = bpy.data.materials["Ground_Site"].node_tree.nodes.get("LRH_Hay")
            if hay is None:
                lrh.fail("the permit .blend has no hay fields; rebuild it with --scene permit")
            hay.outputs[0].default_value = 1.0
            life = BoatOnly(total, LENS_MM, flight.get("main_start", 0))
            if scene_arg == "permit5":
                life = LotLineFade(life, flight["benchmarks"])
        elif variant == "low":
            render.apply_collections(scene, set(COLLECTIONS + ["Cabins"]))
            pads = []
            if "--layout" in argv and argv[argv.index("--layout") + 1] == "pairs":
                cabins, pads = render.layout_lots({"layout": "pairs"}, config)
            render.apply_cabins(cabins, pads)
            render.apply_screens(cabins if pads else [])
            render.apply_site_works(True)
            render.apply_beach(True, pads)
            life = BoatOnly(total, LENS_MM)
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
        if RES[0] > 2048:                      # one tile for 4K (tiles cost a full-buffer re-read)
            scene.cycles.use_auto_tile, scene.cycles.tile_size = True, 4096
        # The raw frame is temporary (captioned to f_NNNN.png, then deleted): 8-bit like the
        # caption output, uncompressed, on local disk (not the frames folder, which is a
        # network volume on a pod).
        scene.render.image_settings.color_depth = "8"
        scene.render.image_settings.compression = 0
        raw_dir = Path(tempfile.mkdtemp(prefix="lrh_raw_"))
        scene.view_settings.exposure = exposure if exposure is not None else config.get("exposure", -4.0)
        loc, look = pose(0, total)
        cam.location = Vector(loc)
        cam.rotation_euler = (Vector(look) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
        with tempfile.TemporaryDirectory() as scratch:
            render.configure_haze(scene, cam, HAZE_KM, scratch,  # horizon colour from frame 0
                                  all_azimuths=variant == "low")
        if "--profile" in argv:                # log each Cycles phase change with its time
            phase = {"name": None, "t": time.time()}

            def stats(text, *_):
                if not isinstance(text, str):
                    return
                name = text.split("|")[-1].strip().split(" ")[0:2]
                name = " ".join(name)
                if name != phase["name"]:
                    now = time.time()
                    print(f"PHASE {now - phase['t']:7.1f}s  {phase['name']} -> {text.strip()[:110]}", flush=True)
                    phase["name"], phase["t"] = name, now
            bpy.app.handlers.render_stats.append(stats)
        todo = only if only is not None else clip[::step]
        if shard is not None:
            todo = [f for k, f in enumerate(todo) if k % shard[1] == shard[0]]
        caption = config["caption"] + (" " + config["caption_cabins"] if cabins and config.get("caption_cabins") else "")
        started = time.time()
        # Post-processing (blank-frame check, caption) runs in up to POST_WORKERS separate
        # processes while the GPU renders the next frame: on a cloud pod's slow CPU it took
        # about two minutes a 4K frame. A blank frame still stops the render (CLAUDE.md).
        post, post_script = [], Path(__file__).resolve().parent / "frame_post.py"

        def reap(keep):
            while post and (len(post) > keep or post[0][1].poll() is not None):
                done_frame, proc = post.pop(0)
                if proc.wait() != 0:
                    lrh.fail(f"frame {done_frame}: post-processing failed (exit {proc.returncode})")
        for f in todo:
            path = frames_dir / f"f_{f:04d}.png"
            if path.exists() and only is None:
                continue
            loc, look = pose(f, total)
            cam.location = Vector(loc)
            cam.rotation_euler = (Vector(look) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
            if life is not None:
                life(f)
            raw = raw_dir / f"raw_{f:04d}.png"
            scene.render.filepath = str(raw)
            t0 = time.time()
            bpy.ops.render.render(write_still=True)
            post.append((f, subprocess.Popen([sys.executable, str(post_script), str(raw), str(path), caption])))
            reap(POST_WORKERS)
            print(f"FRAME {f} {time.time() - t0:.1f}s", flush=True)
        reap(0)
        print(f"RENDERED {len(list(todo))} frames in {time.time() - started:.0f}s")
    if only is not None or shard is not None:
        return
    # Encode with Blender's FFmpeg through the sequencer.
    missing = [f for f in clip[::step] if not (frames_dir / f"f_{f:04d}.png").exists()]
    name = f"flyover_{variant_dir}"
    # Frame order by number, never by file name: past f_9999 a name sort puts f_10000 after
    # f_1000 (the 6 Nov 2026 encode came out scrambled from 33 s and ended at frame 9999).
    files = [f"f_{f:04d}.png" for f in clip[::step]]
    if "--clip" in argv:
        name += f"_clip_{clip.start}_{clip.stop}"
    if missing and "--partial" in argv:      # review cut of a paused render: frames before the first gap
        files = [f"f_{f:04d}.png" for f in range(clip.start, missing[0], step)]
        name += f"_partial_{len(files)}"
    elif missing:
        lrh.fail(f"{len(missing)} frames missing, first {missing[0]}")
    enc = bpy.data.scenes.new("LRH_Encode")
    enc.render.resolution_x, enc.render.resolution_y = RES
    enc.render.resolution_percentage = 100
    enc.render.fps = fps
    enc.frame_start, enc.frame_end = 1, len(files)
    seq = enc.sequence_editor_create()
    strips = seq.strips if hasattr(seq, "strips") else seq.sequences
    strip = strips.new_image("frames", str(frames_dir / files[0]), 1, 1)
    for fname in files[1:]:
        strip.elements.append(fname)
    if hasattr(enc.render.image_settings, "media_type"):  # Blender 5: video is a media type
        enc.render.image_settings.media_type = "VIDEO"
    enc.render.image_settings.file_format = "FFMPEG"
    enc.render.ffmpeg.format = "MPEG4"
    enc.render.ffmpeg.codec = "H264"
    enc.render.ffmpeg.constant_rate_factor = "HIGH"
    enc.render.ffmpeg.ffmpeg_preset = "GOOD"
    enc.view_settings.view_transform = "Standard"  # frames are already display-referred
    enc.render.filepath = str(out / f"{name}.mp4")
    bpy.ops.render.render(animation=True, scene=enc.name)
    (out / f"{name}.json").write_text(json.dumps({"variant": variant_dir,
        "schema": "lrh.flyover/1", "rendered_utc": lrh.utc_now(), "git": lrh.git_commit(),
        "blend": bpy.data.filepath, "fps": fps, "seconds": SECONDS, "resolution": RES,
        "samples": SAMPLES, "lens_mm": LENS_MM, "sun": SUN, "haze_km": HAZE_KM,
        "collections": COLLECTIONS, "keys": KEYS, "caption": config["caption"]}, indent=1) + "\n")
    print("ENCODED", out / f"{name}.mp4")
    if "--clip" not in argv and "--partial" not in argv and step == 1:
        # Decode sample frames and match them to their PNGs (a scrambled encode fails here).
        check = subprocess.run([bpy.app.binary_path, "-b", "--python-exit-code", "1", "--python",
                                str(Path(__file__).resolve().parent / "check_video.py"), "--",
                                str(out / f"{name}.mp4"), str(frames_dir)], capture_output=True, text=True)
        print("\n".join(l for l in check.stdout.splitlines() if l.startswith(("CHECK", "VIDEO OK", "LRH"))))
        if check.returncode:
            lrh.fail(f"{name}.mp4 does not match its frames (scripts/blender/check_video.py)")


if __name__ == "__main__":
    main()
