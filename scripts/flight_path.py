"""Phase 3a low-altitude flight path: design, pacing, clearance checks, benchmark frames.

Keys are (camera xyz, look-at xyz, ground speed m/s) in LRH local metres. The camera and
look-at follow Catmull-Rom splines; the camera's ground speed follows the per-key speeds
(interpolated along arc length), so the run slows for the cabin reveal and speeds up over
open water. Every frame is checked:
- at least 15 m above max(lidar ground, 551 ft pool);
- at least 8 m above the lidar canopy surface (DSM) wherever the camera passes;
- heading turn rate at most 10 deg/s (gentle drone pan) and down-tilt at most 35 deg.
Benchmark frames B1-B7 (PLAN.md Phase 3a) are picked at named keys.

Writes out/derived/flight_low.json (per-frame poses, checks, benchmark frames) and
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

import numpy as np  # noqa: E402

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
# corner and climb while heading west along the CR 3640 side; cross the pond; at the SW
# corner pan north to the cleared shoreline and run up it (beaches, docks and riprap
# ahead, lots and cabins on the right); out the boat channel past the flooded timber to
# the open lake; a left-hand turn over the western open water ending in a hover that looks back at the property
# in golden light. (name, camera, look-at, ground speed m/s)
KEYS = [
    ("T0", (SE_CORNER[0], SE_CORNER[1], 187.0), (-40.0, -60.0, 176.0), 2.5),   # takeoff, 2 m up, facing the lots
    ("", (134.0, -208.0, 206.0), (-70.0, -130.0, 174.0), 4.0),        # climbing, turning west
    ("", (100.0, -205.0, 226.0), (-100.0, -195.0, 171.0), 7.0),
    ("B1", (30.0, -198.0, 236.0), (-110.0, -192.0, 171.0), 8.0),      # pond ahead, Lot 10 right
    ("B2", (-46.0, -192.0, 236.0), (-170.0, -222.0, 168.0), 7.0),     # over the pond
    ("", (-130.0, -214.0, 226.0), (-195.0, -120.0, 168.0), 7.0),      # SW corner, pan north
    ("B3", (-178.0, -185.0, 216.0), (-160.0, -50.0, 168.0), 7.5),     # lined up on the shore
    ("", (-182.0, -120.0, 210.0), (-140.0, 20.0, 172.0), 8.5),        # shoreline run: lots right
    ("B4", (-178.0, -20.0, 208.0), (-130.0, 110.0, 172.0), 8.5),      # beach and Lot 5-6 dock
    ("", (-170.0, 80.0, 206.0), (-130.0, 210.0, 172.0), 8.5),
    ("B5", (-182.0, 175.0, 206.0), (-160.0, 290.0, 170.0), 9.5),      # Lot 3-4 dock
    ("B6", (-195.0, 270.0, 206.0), (-235.0, 390.0, 168.5), 13.0),     # Lot 1-2 dock, timber
    ("", (-238.0, 390.0, 206.0), (-280.0, 600.0, 168.0), 15.0),       # out the boat channel
    ("", (-290.0, 480.0, 212.0), (-380.0, 640.0, 168.0), 13.0),       # open lake to the north-west
    ("", (-340.0, 555.0, 216.0), (-520.0, 520.0, 168.0), 10.0),        # left-hand turn begins
    ("", (-405.0, 520.0, 220.0), (-430.0, 300.0, 168.0), 9.0),        # over the western open water
    ("", (-400.0, 430.0, 224.0), (-100.0, 250.0, 172.0), 8.0),        # swinging back to the property
    ("B7", (-315.0, 340.0, 230.0), (-20.0, 30.0, 176.0), 3.5),        # hover: shore, docks, cabins
]
# The takeoff is exempt from the clearance minimums (open road intersection, nothing
# overhead) for its first TAKEOFF_S seconds; everything after must meet them.
TAKEOFF_S = 10.0
TAKEOFF_MIN_AGL = 1.5


def catmull_rom(points, t):
    p = np.vstack([points[0], points, points[-1]])
    n = len(points) - 1
    s = min(t * n, n - 1e-9)
    i = int(s) + 1
    u = s - (i - 1)
    p0, p1, p2, p3 = p[i - 1], p[i], p[i + 1], p[i + 2]
    return 0.5 * ((2 * p1) + (-p0 + p2) * u + (2 * p0 - 5 * p1 + 4 * p2 - p3) * u ** 2
                  + (-p0 + 3 * p1 - 3 * p2 + p3) * u ** 3)


def poses():
    cams = np.array([k[1] for k in KEYS])
    looks = np.array([k[2] for k in KEYS])
    speeds = np.array([k[3] for k in KEYS])
    u = np.linspace(0, 1, 20001)
    pts = np.array([catmull_rom(cams, x) for x in u])
    ds = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    s = np.concatenate([[0], np.cumsum(ds)])
    key_u = np.linspace(0, 1, len(KEYS))
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
    frames, seconds, key_u = poses()
    frames = eased(frames)
    cams = np.array([f[0] for f in frames])
    looks = gimbal(cams, np.array([f[1] for f in frames]))
    frames = [(c, lk, f[2]) for c, lk, f in zip(cams, looks, frames)]
    ground = np.maximum(dtm(cams[:, 0], cams[:, 1]), POOL_M)
    takeoff = np.arange(len(cams)) < TAKEOFF_S * FPS
    canopy = np.maximum(dsm(cams[:, 0], cams[:, 1]), ground)
    agl = cams[:, 2] - ground
    above_canopy = cams[:, 2] - canopy
    # Clearance is checked after the takeoff; the takeoff itself only has to stay above
    # TAKEOFF_MIN_AGL.
    agl_flight, canopy_flight = agl[~takeoff], above_canopy[~takeoff]
    d = looks - cams
    heading = np.degrees(np.unwrap(np.arctan2(d[:, 0], d[:, 1])))
    turn = np.abs(np.gradient(heading)) * FPS
    tilt = np.degrees(np.arctan2(-d[:, 2], np.hypot(d[:, 0], d[:, 1])))
    speed = np.linalg.norm(np.gradient(cams, axis=0), axis=1) * FPS
    us = np.array([f[2] for f in frames])
    bench = {k[0]: int(np.argmin(np.abs(us - key_u[i]))) for i, k in enumerate(KEYS) if k[0]}
    checks = {
        "min_agl_m": round(float(agl_flight.min()), 1),
        "min_agl_frame": int(agl_flight.argmin()) + int(takeoff.sum()),
        "min_above_canopy_m": round(float(canopy_flight.min()), 1),
        "min_above_canopy_frame": int(canopy_flight.argmin()) + int(takeoff.sum()),
        "takeoff_s": TAKEOFF_S, "takeoff_min_agl_m": round(float(agl[takeoff].min()), 1),
        "max_turn_deg_s": round(float(turn.max()), 2), "max_turn_frame": int(turn.argmax()),
        "max_tilt_deg": round(float(tilt.max()), 1),
        "max_agl_ft": round(float(agl.max() / 0.3048)),
        "max_speed_ms": round(float(speed.max()), 1),
    }
    checks["passed"] = bool(agl_flight.min() >= MIN_AGL and canopy_flight.min() >= MIN_CANOPY
                            and agl[takeoff].min() >= TAKEOFF_MIN_AGL
                            and turn.max() <= MAX_TURN_DEG_S and tilt.max() <= MAX_TILT_DEG
                            and agl.max() < 400 * 0.3048)
    out = {"schema": "lrh.flight/1", "fps": FPS, "frames": len(frames),
           "seconds": round(len(frames) / FPS, 1), "keys": KEYS, "benchmarks": bench,
           "checks": checks,
           "poses": [[[round(float(v), 3) for v in c], [round(float(v), 3) for v in lk]]
                     for c, lk, _ in frames]}
    (ROOT / "out/derived/flight_low.json").write_text(json.dumps(out) + "\n")
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
