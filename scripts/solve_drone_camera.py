"""Solve the drone-photo camera pose from PTM's survey-registered parcel outline.

PTM registered the owner-parcel perimeter onto the drone photo (red line, pinned to the
survey point of beginning behind the parked car). This fits a pinhole camera (position,
yaw, pitch, roll, focal length) so the 3D parcel boundary from the site-review context
projects onto that red outline, by iterated nearest-point least squares in both
directions. It prints the shots.yaml camera block and writes a residual report and an
overlay image to out/<date>/.

Usage (Blender's Python, for numpy + Pillow in .blender-site):
  /Applications/Blender.app/Contents/Resources/5.0/python/bin/python3.11 scripts/solve_drone_camera.py
"""

import json
import math
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT / ".blender-site"))

import numpy as np  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

SENSOR_MM = 36.0
REGISTRATION = ROOT / "inputs/reference/ptm-drone-photo-registration.png"
PHOTO = ROOT / "inputs/reference/drone-ladonia-arial-1.jpeg"
OUT = ROOT / "out" / date.today().isoformat()


def boundary_points(step=2.0):
    context = json.loads((ROOT / "inputs/context/site-review-context-regional.json").read_text())
    points = []
    for b in context["boundaries"]:
        if b["kind"] != "owner_parcel_boundary":
            continue
        line = np.array(b["lines_local_m"][0])
        for a, c in zip(line[:-1], line[1:]):
            n = max(1, int(np.linalg.norm(c[:2] - a[:2]) / step))
            points += [a + (c - a) * t for t in np.arange(n) / n]
    return np.array(points)


def red_outline(path):
    pixels = np.asarray(Image.open(path).convert("RGB")).astype(int)
    mask = (pixels[:, :, 0] > 175) & (pixels[:, :, 1] < 90) & (pixels[:, :, 2] < 90)
    ys, xs = np.nonzero(mask)
    return np.column_stack([xs, ys]).astype(float), pixels.shape[1], pixels.shape[0]


def rotation(yaw, pitch, roll):
    """World->camera rotation. yaw: compass heading of the view (deg, 0 = north),
    pitch: degrees below horizontal, roll: degrees about the view axis."""
    h, p, r = map(math.radians, (yaw, pitch, roll))
    forward = np.array([math.sin(h) * math.cos(p), math.cos(h) * math.cos(p), -math.sin(p)])
    right = np.array([math.cos(h), -math.sin(h), 0.0])
    up = np.cross(right, forward)
    right, up = (right * math.cos(r) + up * math.sin(r), -right * math.sin(r) + up * math.cos(r))
    return np.vstack([right, up, forward])


def project(params, points, width, height):
    x, y, z, yaw, pitch, roll, lens = params
    cam = (points - [x, y, z]) @ rotation(yaw, pitch, roll).T
    scale = lens / SENSOR_MM * width
    u = width / 2 + scale * cam[:, 0] / cam[:, 2]
    v = height / 2 - scale * cam[:, 1] / cam[:, 2]
    return np.column_stack([u, v]), cam[:, 2]


def residuals(params, model, target, width, height):
    uv, depth = project(params, model, width, height)
    if (depth <= 1).any():
        return np.full(2 * len(model) + 2 * len(target), 1e4)
    d_mt = ((uv[:, None, :] - target[None, :, :]) ** 2).sum(-1)
    nearest_t = target[d_mt.argmin(1)]
    nearest_m = uv[d_mt.argmin(0)]
    return np.concatenate([(uv - nearest_t).ravel(), (nearest_m - target).ravel()])


def solve(start, model, target, width, height, iterations=60):
    params = np.array(start, float)
    damping = 1e-2
    steps = np.array([0.5, 0.5, 0.5, 0.05, 0.05, 0.05, 0.05])
    cost = (residuals(params, model, target, width, height) ** 2).mean()
    for _ in range(iterations):
        r0 = residuals(params, model, target, width, height)
        jac = np.column_stack([(residuals(params + np.eye(7)[i] * steps[i], model, target,
                                          width, height) - r0) / steps[i] for i in range(7)])
        jtj, jtr = jac.T @ jac, jac.T @ r0
        while True:
            delta = np.linalg.solve(jtj + damping * np.diag(np.diag(jtj) + 1e-9), -jtr)
            trial = params + delta
            trial_cost = (residuals(trial, model, target, width, height) ** 2).mean()
            if trial_cost < cost:
                params, cost, damping = trial, trial_cost, max(damping / 3, 1e-6)
                break
            damping *= 4
            if damping > 1e6:
                return params, cost
    return params, cost


def main():
    model3d = boundary_points()
    target, width, height = red_outline(REGISTRATION)
    rng = np.random.default_rng(0)
    target_s = target[rng.choice(len(target), min(2500, len(target)), replace=False)]
    model_s = model3d[:: max(1, len(model3d) // 400)]

    best = None
    for heading in (270, 290, 310, 330):
        for distance in (500, 700):
            h = math.radians(heading + 180)
            start = [100 + distance * math.sin(h), -250 + distance * math.cos(h), 330.0,
                     heading, 25.0, 0.0, 24.0]
            params, cost = solve(start, model_s, target_s, width, height)
            print(f"start heading {heading} dist {distance}: rms {math.sqrt(cost):.2f} px")
            if best is None or cost < best[1]:
                best = (params, cost)
    params, _ = solve(best[0], model3d, target_s, width, height, iterations=40)

    uv, _ = project(params, model3d, width, height)
    d = np.sqrt(((uv[:, None, :] - target_s[None, :, :]) ** 2).sum(-1))
    model_to_red, red_to_model = d.min(1), d.min(0)
    x, y, z, yaw, pitch, roll, lens = params
    forward = rotation(yaw, pitch, roll)[2]
    t = (175.0 - z) / forward[2]  # aim point on the ground plane near the site
    target_pt = [x + forward[0] * t, y + forward[1] * t, 175.0]
    report = {
        "schema": "lrh.drone-camera-solve/1",
        "registration": str(REGISTRATION),
        "image_size": [width, height],
        "params": {"position": [round(x, 2), round(y, 2), round(z, 2)],
                   "heading_deg": round(yaw, 3), "pitch_down_deg": round(pitch, 3),
                   "roll_deg": round(roll, 3), "lens_mm": round(lens, 3),
                   "sensor_width_mm": SENSOR_MM},
        "target": [round(v, 2) for v in target_pt],
        "residual_px_at_registration_size": {
            "model_to_outline_rms": round(float(np.sqrt((model_to_red ** 2).mean())), 2),
            "model_to_outline_p95": round(float(np.percentile(model_to_red, 95)), 2),
            "outline_to_model_rms": round(float(np.sqrt((red_to_model ** 2).mean())), 2),
        },
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "drone_camera_solve.json").write_text(json.dumps(report, indent=2) + "\n")

    photo = Image.open(PHOTO).convert("RGB").resize((width, height))
    draw = ImageDraw.Draw(photo)
    for u, v in target_s:
        draw.point((u, v), fill=(255, 40, 40))
    for u, v in uv:
        draw.ellipse((u - 2, v - 2, u + 2, v + 2), fill=(40, 220, 255))
    photo.save(OUT / "drone_camera_solve_overlay.jpg", quality=90)

    print(json.dumps(report, indent=2))
    print("shots.yaml camera:")
    print(f"    camera: {{position: [{x:.2f}, {y:.2f}, {z:.2f}], "
          f"target: [{target_pt[0]:.2f}, {target_pt[1]:.2f}, {target_pt[2]:.2f}], "
          f"lens_mm: {lens:.3f}, roll_deg: {roll:.3f}}}")


if __name__ == "__main__":
    main()
