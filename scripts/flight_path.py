"""Phase 3a low-altitude flight path: design, pacing, clearance checks, benchmark frames.

Keys are (camera xyz, look-at xyz, ground speed m/s) in LRH local metres. The camera and
look-at follow Catmull-Rom splines; the camera's ground speed follows the per-key speeds
(interpolated along arc length), so the run slows for the cabin reveal and speeds up over
open water. Every frame is checked:
- at least 15 m above max(lidar ground, 551 ft pool);
- at least 8 m above the lidar canopy surface (DSM) wherever the camera passes;
- heading turn rate at most 10 deg/s (gentle drone pan) and down-tilt at most 35 deg.
Benchmark frames B1-B7 (PLAN.md Phase 3a) are picked at named keys.

Owner, 2 Nov 2026: the video starts and ends on the for-sale sign at the CR 3635 /
CR 3640 corner (scripts/blender/sale_sign.py). The intro (close on the sign, then a low
glide to the takeoff point) and the outro (down from the last hover onto the sign) are
eased segments of their own either side of the main flight, so the main flight's frames
do not change when they do; near the sign the clearance minimums do not apply.

Writes out/derived/flight_low.json (LRH_FLIGHT overrides) (per-frame poses, checks, benchmark frames) and
out/derived/flight_low_plan.png (plan view over the NAIP site image).

Usage (Blender's Python): python3.11 scripts/flight_path.py
"""

import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT / ".blender-site"))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts/blender"))

import numpy as np  # noqa: E402

import lrh  # noqa: E402
import sale_sign  # noqa: E402
from kwik_ortho import Surface  # noqa: E402

FPS = 30
POOL_M = 167.9448
MIN_AGL, MIN_CANOPY = 15.0, 8.0
MAX_TURN_DEG_S, MAX_TILT_DEG = 10.0, 35.0   # pans at low altitude; oval was 4.3 deg/s
CABIN = (47.3, 12.9, 182.0)        # Lot 5 cabin (grading.layout), look-at height ~ main floor

# Owner, 19 Oct 2026: the survey's point of beginning on CR 3635 (signed survey, fitted to
# the TxDOT centreline: LRH (114.5, -46.7); the model's parcel corner is 10 m west).
POB = (114.5, -46.7)
SE_CORNER = (140.0, -210.0)        # CR 3635 x relocated CR 3640, ground 184.7 m
# Owner, 25 Oct 2026 (replaces the POB start and the cabin close-ups): take off at the SE
# corner; at the SW corner pan north to the cleared shoreline and run up it (docks and
# riprap ahead, lots on the right); out past the flooded timber to the open lake; a
# left-hand turn over the western open water. Owner, 2 Nov 2026 (replaces the 1 Nov
# north-facing climb and cove ending): the drone climbs looking west down relocated
# CR 3640, pivots north-west, and hovers over the creek arm looking north-east at the
# property (H1-H2: the proposed lot lines fade in, hold, fade out); pivots north up the
# shoreline as before; after the lake turn it flies east past the north end and hovers
# looking south-west (S1-S2: lot lines in and out); then flies south down CR 3635 to the
# point of beginning at the CR 3640 corner, pivots north-west and the lot lines fade in
# for the end (P1-P2, held to the last frame). (name, camera, look-at, ground speed m/s)
KEYS = [
    ("T0", (SE_CORNER[0], SE_CORNER[1], 187.0), (-300.0, -228.0, 180.0), 2.0),  # takeoff, facing west down CR 3640
    ("", (122.0, -214.0, 206.0), (-300.0, -236.0, 178.0), 5.5),       # climbing, facing west
    ("", (20.0, -224.0, 232.0), (-380.0, -150.0, 172.0), 12.0),        # west along CR 3640
    ("", (-140.0, -252.0, 258.0), (-420.0, 40.0, 170.0), 11.0),      # pivoting north-west
    ("", (-240.0, -266.0, 272.0), (-160.0, -80.0, 172.0), 6.5),       # over the creek, pivoting north-east
    ("H1", (-285.0, -274.0, 280.0), (-20.0, 20.0, 175.0), 2.0),       # whole property; lot lines in
    ("H2", (-291.0, -280.0, 281.0), (-20.0, 20.0, 175.0), 2.0),       # hold
    ("", (-250.0, -250.0, 245.0), (-170.0, -40.0, 170.0), 6.0),       # pivoting north
    ("B3", (-190.0, -180.0, 216.0), (-160.0, -50.0, 168.0), 7.5),     # lined up on the shore
    ("", (-182.0, -120.0, 210.0), (-140.0, 20.0, 172.0), 8.5),        # shoreline run: lots right
    ("B4", (-178.0, -20.0, 208.0), (-130.0, 110.0, 172.0), 8.5),      # beach and Lot 5-6 dock
    ("", (-170.0, 80.0, 206.0), (-130.0, 210.0, 172.0), 8.5),
    ("B5", (-182.0, 175.0, 206.0), (-160.0, 290.0, 170.0), 9.5),      # Lot 3-4 dock
    ("B6", (-195.0, 270.0, 206.0), (-235.0, 390.0, 168.5), 13.0),     # Lot 1-2 dock, timber
    ("", (-238.0, 390.0, 206.0), (-280.0, 600.0, 168.0), 15.0),       # out the boat channel
    ("", (-290.0, 480.0, 212.0), (-380.0, 640.0, 168.0), 13.0),       # open lake to the north-west
    ("", (-340.0, 555.0, 216.0), (-520.0, 520.0, 168.0), 10.0),       # left-hand turn begins
    ("", (-405.0, 520.0, 220.0), (-430.0, 300.0, 168.0), 9.0),        # over the western open water
    ("", (-370.0, 440.0, 232.0), (-120.0, 330.0, 172.0), 12.0),       # turning east
    ("", (-150.0, 455.0, 250.0), (200.0, 420.0, 178.0), 15.0),        # east past the north end
    ("", (60.0, 470.0, 268.0), (150.0, 120.0, 178.0), 10.0),         # pivoting south-west
    ("S1", (190.0, 420.0, 282.0), (-70.0, 30.0, 175.0), 2.0),         # whole property; lot lines in
    ("S2", (194.0, 412.0, 283.0), (-70.0, 30.0, 175.0), 2.0),         # hold
    ("", (222.0, 270.0, 262.0), (60.0, -150.0, 176.0), 15.0),         # south down CR 3635
    ("", (220.0, -120.0, 270.0), (-20.0, -150.0, 175.0), 11.0),      # nearing the corner, pivoting
    ("P1", (212.0, -285.0, 285.0), (-80.0, -10.0, 175.0), 2.0),       # point of beginning, facing north-west
    ("P2", (208.0, -292.0, 286.0), (-80.0, -10.0, 175.0), 2.0),       # end: lot lines held
]
# The takeoff is exempt from the clearance minimums (open road intersection, nothing
# overhead) for its first TAKEOFF_S seconds; everything after must meet them.
TAKEOFF_S = 10.0
TAKEOFF_MIN_AGL = 1.5
# Within SIGN_ZONE_M of the sign the camera is down at the placards: it only has to stay
# SIGN_MIN_AGL up. SIGN_DIST_M: camera to placards for the close-ups.
SIGN_ZONE_M, SIGN_MIN_AGL, SIGN_DIST_M = 30.0, 1.0, 2.4


def sign_keys(dtm):
    """Intro and outro keys around the for-sale sign."""
    base = sale_sign.layout(0.0)["base"]
    g = sale_sign.layout(float(dtm(np.array([base[0]]), np.array([base[1]]))[0]))
    c, o = g["centre"], np.append(g["out"], 0.0)
    at = lambda d, dz: tuple(float(v) for v in c + o * d + (0.0, 0.0, dz))

    def sign_key(name, d, dz, speed):
        # Look along the ray through the placards' centre, 300 m out: look-at points as far
        # as the main flight's interpolate as an even pan (a point 2 m away swings the view).
        cam = np.array(at(d, dz))
        ray = (c - cam) / np.linalg.norm(c - cam)
        return (name, tuple(cam), tuple(float(v) for v in cam + ray * 300.0), speed)
    intro = [
        sign_key("SIGN", SIGN_DIST_M, 0.1, 0.3),                         # close on the placards
        sign_key("", SIGN_DIST_M + 0.8, 0.15, 0.3),
        sign_key("", SIGN_DIST_M + 1.8, 0.3, 0.4),                       # easing back
        ("", at(6.5, 0.8), (5.0, 75.0, 186.0), 0.5),                           # turning toward the corner
        ("", (136.0, -203.0, 186.8), (-155.0, -133.0, 182.0), 0.6),         # gliding to the takeoff point
        ("", KEYS[0][1], KEYS[0][2], 2.0),                               # takeoff pose
    ]
    end = KEYS[-1]
    outro = [
        ("", end[1], end[2], end[3]),
        sign_key("", 150.0, 55.0, 9.0),                                  # swinging onto the sign's axis
        sign_key("", 60.0, 30.0, 6.0),                                   # down toward the sign
        sign_key("", 22.0, 15.0, 4.5),
        sign_key("", 10.0, 3.0, 3.0),
        sign_key("", SIGN_DIST_M + 1.2, 0.2, 0.8),
        sign_key("SIGN_END", SIGN_DIST_M, 0.1, 0.4),                     # end on the placards
    ]
    return intro, outro, g["base"]


def segment(keys):
    frames, _, key_u = poses(keys)
    frames = eased(frames)
    cams = np.array([f[0] for f in frames])
    looks = gimbal(cams, np.array([f[1] for f in frames]))
    us = np.array([f[2] for f in frames])
    bench = {k[0]: int(np.argmin(np.abs(us - key_u[i]))) for i, k in enumerate(keys) if k[0]}
    return cams, looks, bench


def catmull_rom(points, t):
    p = np.vstack([points[0], points, points[-1]])
    n = len(points) - 1
    s = min(t * n, n - 1e-9)
    i = int(s) + 1
    u = s - (i - 1)
    p0, p1, p2, p3 = p[i - 1], p[i], p[i + 1], p[i + 2]
    return 0.5 * ((2 * p1) + (-p0 + p2) * u + (2 * p0 - 5 * p1 + 4 * p2 - p3) * u ** 2
                  + (-p0 + 3 * p1 - 3 * p2 + p3) * u ** 3)


def poses(keys):
    cams = np.array([k[1] for k in keys])
    looks = np.array([k[2] for k in keys])
    speeds = np.array([k[3] for k in keys])
    u = np.linspace(0, 1, 20001)
    pts = np.array([catmull_rom(cams, x) for x in u])
    ds = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    s = np.concatenate([[0], np.cumsum(ds)])
    key_u = np.linspace(0, 1, len(keys))
    v = np.interp(u, key_u, speeds)
    v = np.maximum(v, 0.5)
    t = np.concatenate([[0], np.cumsum(ds / (0.5 * (v[1:] + v[:-1])))])
    total_s = t[-1]
    n = int(round(total_s * FPS))
    out = []
    for f in range(n):
        uf = float(np.interp(f / FPS, t, u))
        out.append((catmull_rom(cams, uf), catmull_rom(looks, uf), uf))
    return out, total_s, key_u


def eased(frames):
    """Re-time so the drone starts and stops smoothly: velocity ramps (smoothstep) over
    the first and last 2.5 s; the middle runs slightly faster to keep the duration."""
    n = len(frames)
    r = min(0.45, 2.5 * FPS / n)
    tau = np.linspace(0, 1, n)
    ramp = lambda x: np.clip(x, 0, 1) ** 2 * (3 - 2 * np.clip(x, 0, 1))
    v = np.minimum(ramp(tau / r), ramp((1 - tau) / r))
    w = np.concatenate([[0], np.cumsum(0.5 * (v[1:] + v[:-1]))])
    src = w / w[-1] * (n - 1)
    idx = np.arange(n, dtype=float)
    cams = np.array([f[0] for f in frames])
    looks = np.array([f[1] for f in frames])
    us = np.array([f[2] for f in frames])
    return [(np.array([np.interp(k, idx, cams[:, i]) for i in range(3)]),
             np.array([np.interp(k, idx, looks[:, i]) for i in range(3)]),
             float(np.interp(k, idx, us))) for k in src]


def gimbal(cams, looks, sigma_s=2.0):
    """Smooth the look direction like a drone gimbal: Gaussian over sigma_s seconds on the
    unit view vector (distance to the look-at point kept). 2 s reads as a slow, deliberate pan."""
    d = looks - cams
    dist = np.linalg.norm(d, axis=1, keepdims=True)
    u = d / dist
    sig = sigma_s * FPS
    k = np.arange(-int(3 * sig), int(3 * sig) + 1)
    w = np.exp(-0.5 * (k / sig) ** 2)
    w /= w.sum()
    pad = np.pad(u, ((len(k) // 2, len(k) // 2), (0, 0)), mode="edge")
    sm = np.column_stack([np.convolve(pad[:, i], w, mode="valid") for i in range(3)])
    sm /= np.linalg.norm(sm, axis=1, keepdims=True)
    return cams + sm * dist


def main():
    dtm = Surface(ROOT / "out/derived/lidar_dtm_1m.tif")
    dsm = Surface(ROOT / "out/derived/lidar_dsm_1m.tif")
    intro, outro, sign_base = sign_keys(dtm)
    parts = [segment(k) for k in (intro, KEYS, outro)]
    # The intro's last frame is the main flight's first and the outro's first its last;
    # the intro is padded at the start so the main flight begins on a multiple of 3 (the
    # preview renders every third frame and its frames can be reused).
    pad = (-(len(parts[0][0]) - 1)) % 3
    ic, il, ib = parts[0]
    # Each segment is gimballed on its own, so the look directions at the joins differ by
    # up to a degree: blend the intro's last and the outro's first 2 s onto the main flight's.
    ramp = np.linspace(0, 1, 2 * FPS)[:, None] ** 2 * (3 - 2 * np.linspace(0, 1, 2 * FPS)[:, None])
    il = il.copy()
    il[-len(ramp):] = il[-len(ramp):] * (1 - ramp) + parts[1][1][0] * ramp
    ol = parts[2][1].copy()
    ol[:len(ramp)] = ol[:len(ramp)] * ramp + parts[1][1][-1] * (1 - ramp)
    parts[2] = (parts[2][0], ol, parts[2][2])
    ic, il = np.concatenate([ic[:1]] * pad + [ic[:-1]]), np.concatenate([il[:1]] * pad + [il[:-1]])
    main_start = len(ic)
    cams = np.concatenate([ic, parts[1][0], parts[2][0][1:]])
    looks = np.concatenate([il, parts[1][1], parts[2][1][1:]])
    outro_start = main_start + len(parts[1][0]) - 1
    bench = {k: v + pad for k, v in ib.items()}
    bench.update({k: v + main_start for k, v in parts[1][2].items()})
    bench.update({k: v + outro_start for k, v in parts[2][2].items()})
    frames = list(zip(cams, looks))
    ground = np.maximum(dtm(cams[:, 0], cams[:, 1]), POOL_M)
    idx = np.arange(len(cams))
    takeoff = (idx >= main_start) & (idx < main_start + TAKEOFF_S * FPS)
    near_sign = np.hypot(cams[:, 0] - sign_base[0], cams[:, 1] - sign_base[1]) < SIGN_ZONE_M
    exempt = takeoff | near_sign
    canopy = np.maximum(dsm(cams[:, 0], cams[:, 1]), ground)
    agl = cams[:, 2] - ground
    above_canopy = cams[:, 2] - canopy
    # Clearance is checked away from the takeoff and the sign; those only have to stay
    # above TAKEOFF_MIN_AGL and SIGN_MIN_AGL.
    agl_flight, canopy_flight = agl[~exempt], above_canopy[~exempt]
    d = looks - cams
    heading = np.degrees(np.unwrap(np.arctan2(d[:, 0], d[:, 1])))
    turn = np.abs(np.gradient(heading)) * FPS
    tilt = np.degrees(np.arctan2(-d[:, 2], np.hypot(d[:, 0], d[:, 1])))
    speed = np.linalg.norm(np.gradient(cams, axis=0), axis=1) * FPS
    checks = {
        "min_agl_m": round(float(agl_flight.min()), 1),
        "min_agl_frame": int(idx[~exempt][agl_flight.argmin()]),
        "min_above_canopy_m": round(float(canopy_flight.min()), 1),
        "min_above_canopy_frame": int(idx[~exempt][canopy_flight.argmin()]),
        "takeoff_s": TAKEOFF_S, "takeoff_min_agl_m": round(float(agl[takeoff].min()), 1),
        "sign_min_agl_m": round(float(agl[near_sign].min()), 2),
        "max_turn_deg_s": round(float(turn.max()), 2), "max_turn_frame": int(turn.argmax()),
        "max_tilt_deg": round(float(tilt.max()), 1),
        "max_agl_ft": round(float(agl.max() / 0.3048)),
        "max_speed_ms": round(float(speed.max()), 1),
    }
    checks["passed"] = bool(agl_flight.min() >= MIN_AGL and canopy_flight.min() >= MIN_CANOPY
                            and agl[takeoff].min() >= TAKEOFF_MIN_AGL
                            and agl[near_sign].min() >= SIGN_MIN_AGL
                            and turn.max() <= MAX_TURN_DEG_S and tilt.max() <= MAX_TILT_DEG
                            and agl.max() < 400 * 0.3048)
    out = {"schema": "lrh.flight/1", "fps": FPS, "frames": len(frames),
           "seconds": round(len(frames) / FPS, 1), "keys": intro + KEYS + outro, "benchmarks": bench,
           "main_start": main_start,
           "checks": checks,
           "poses": [[[round(float(v), 3) for v in c], [round(float(v), 3) for v in lk]]
                     for c, lk in frames]}
    lrh.FLIGHT_JSON.write_text(json.dumps(out) + "\n")
    print(json.dumps({k: v for k, v in out.items() if k not in ("poses", "keys")}, indent=1))
    plot(cams, bench)


def plot(cams, bench):
    from PIL import Image, ImageDraw, ImageFont
    lock = json.loads((ROOT / "imagery.lock.json").read_text())
    prod = lock["products"][lock["use"]["site"]]
    xmin, ymin, xmax, ymax = prod["bbox_local_m"]
    im = Image.open(ROOT / "out/derived/naip_site_rgb.png").convert("RGB")
    sx, sy = im.width / (xmax - xmin), im.height / (ymax - ymin)
    pts = [((x - xmin) * sx, (ymax - y) * sy) for x, y in cams[:, :2]]
    x0 = max(0, int(min(p[0] for p in pts)) - 150)
    x1 = min(im.width, int(max(p[0] for p in pts)) + 150)
    y0 = max(0, int(min(p[1] for p in pts)) - 150)
    y1 = min(im.height, int(max(p[1] for p in pts)) + 150)
    d = ImageDraw.Draw(im)
    d.line(pts, fill=(255, 220, 60), width=4)
    font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 28)
    for name, f in bench.items():
        x, y = pts[f]
        d.ellipse([x - 9, y - 9, x + 9, y + 9], fill=(255, 80, 40))
        d.text((x + 12, y - 14), name, font=font, fill=(255, 255, 255))
    cx, cy = (CABIN[0] - xmin) * sx, (ymax - CABIN[1]) * sy
    d.rectangle([cx - 6, cy - 6, cx + 6, cy + 6], outline=(255, 255, 255), width=3)
    crop = im.crop((x0, y0, x1, y1))
    crop.thumbnail((1400, 1400))
    crop.save(ROOT / "out/derived/flight_low_plan.png")


if __name__ == "__main__":
    main()
