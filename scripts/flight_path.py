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

# (name, camera, look-at, speed m/s). Golden hour, sun from the west-south-west.
KEYS = [
    ("B1", (-280.0, 700.0, 212.0), (-285.0, 430.0, 172.0), 16.0),   # main lake, boat below
    ("", (-285.0, 560.0, 202.0), (-245.0, 330.0, 170.0), 16.0),
    ("B2", (-265.0, 430.0, 197.0), (-200.0, 230.0, 170.0), 15.0),   # over the flooded timber
    ("", (-232.0, 300.0, 196.0), (-150.0, 110.0, 172.0), 14.0),
    ("", (-190.0, 150.0, 194.0), (-100.0, 30.0, 172.0), 12.0),
    ("B3", (-155.0, 45.0, 190.0), (-60.0, 15.0, 176.0), 10.0),      # shoreline path, Lot 5 circle
    ("B4", (-95.0, 8.0, 192.0), (CABIN[0], CABIN[1], 180.0), 8.0),  # lake-side acre to the cabin
    ("", (-25.0, 0.0, 194.0), CABIN, 7.0),
    ("B5", (12.0, -8.0, 195.0), CABIN, 5.5),                        # cabin reveal, orbit starts
    ("", (33.0, -25.0, 196.0), CABIN, 5.5),
    ("", (61.0, -30.0, 198.0), CABIN, 4.0),
    ("", (80.0, -55.0, 202.0), (-20.0, -10.0, 177.0), 4.5),
    ("B6", (88.0, -100.0, 207.0), (-160.0, -120.0, 172.0), 8.0),    # south along the lots
    ("", (98.0, -165.0, 213.0), (-230.0, -160.0, 172.0), 11.0),
    ("B7", (135.0, -230.0, 224.0), (-320.0, -170.0, 172.0), 7.0),   # over CR 3635, west at sunset
]


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


def main():
    dtm = Surface(ROOT / "out/derived/lidar_dtm_1m.tif")
    dsm = Surface(ROOT / "out/derived/lidar_dsm_1m.tif")
    frames, seconds, key_u = poses()
    frames = eased(frames)
    cams = np.array([f[0] for f in frames])
    looks = np.array([f[1] for f in frames])
    ground = np.maximum(dtm(cams[:, 0], cams[:, 1]), POOL_M)
    canopy = np.maximum(dsm(cams[:, 0], cams[:, 1]), ground)
    agl = cams[:, 2] - ground
    above_canopy = cams[:, 2] - canopy
    d = looks - cams
    heading = np.degrees(np.unwrap(np.arctan2(d[:, 0], d[:, 1])))
    turn = np.abs(np.gradient(heading)) * FPS
    tilt = np.degrees(np.arctan2(-d[:, 2], np.hypot(d[:, 0], d[:, 1])))
    speed = np.linalg.norm(np.gradient(cams, axis=0), axis=1) * FPS
    us = np.array([f[2] for f in frames])
    bench = {k[0]: int(np.argmin(np.abs(us - key_u[i]))) for i, k in enumerate(KEYS) if k[0]}
    checks = {
        "min_agl_m": round(float(agl.min()), 1), "min_agl_frame": int(agl.argmin()),
        "min_above_canopy_m": round(float(above_canopy.min()), 1),
        "min_above_canopy_frame": int(above_canopy.argmin()),
        "max_turn_deg_s": round(float(turn.max()), 2), "max_turn_frame": int(turn.argmax()),
        "max_tilt_deg": round(float(tilt.max()), 1),
        "max_agl_ft": round(float(agl.max() / 0.3048)),
        "max_speed_ms": round(float(speed.max()), 1),
    }
    checks["passed"] = bool(agl.min() >= MIN_AGL and above_canopy.min() >= MIN_CANOPY
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
