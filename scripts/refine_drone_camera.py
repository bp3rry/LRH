"""Refine the drone-photo camera against StratMap 2025 lidar trees.

solve_drone_camera.py fits PTM's hand-registered parcel outline (~30 px RMS at 2048 px).
This refines that pose with independent, sub-metre control: lidar tree crowns outside
the owner parcels (unchanged by the clearing) must land on tree pixels in the photo.
Score = mean of a blurred photo tree mask at each projected crown centre; the pose is
improved by Nelder-Mead from the current shots.yaml camera. Writes the refined camera
to out/<date>/drone_camera_refine.json with before/after scores and an overlay; copy
the printed camera line into shots.yaml.

Usage (Blender's Python):
  /Applications/Blender.app/Contents/Resources/5.0/python/bin/python3.11 scripts/refine_drone_camera.py
"""

import json
import math
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT / ".blender-site"))
sys.path.insert(0, str(ROOT / "scripts"))

import numpy as np  # noqa: E402
import shapely  # noqa: E402
import yaml  # noqa: E402
from PIL import Image, ImageDraw, ImageFilter  # noqa: E402
from shapely.geometry import Polygon  # noqa: E402
from shapely.ops import unary_union  # noqa: E402

from solve_drone_camera import project, rotation  # noqa: E402

PHOTO = ROOT / "inputs/reference/drone-ladonia-arial-1.jpeg"
WIDTH = 1344  # working resolution (photo is 4032 px wide)
OUT = ROOT / "out" / date.today().isoformat()


def tree_mask():
    photo = Image.open(PHOTO).convert("RGB")
    small = photo.resize((WIDTH, round(photo.height * WIDTH / photo.width)), Image.BILINEAR)
    rgb = np.asarray(small).astype(float)
    trees = ((rgb[:, :, 1] - rgb[:, :, 0]) > 12) & (rgb.mean(2) < 125)
    blurred = Image.fromarray((trees * 255).astype(np.uint8)).filter(ImageFilter.BoxBlur(3))
    return np.asarray(blurred).astype(float) / 255, small


def current_params():
    cam = yaml.safe_load((ROOT / "shots.yaml").read_text())["shots"]["check_drone_match"]["camera"]
    pos, tgt = np.array(cam["position"]), np.array(cam["target"])
    d = tgt - pos
    heading = math.degrees(math.atan2(d[0], d[1]))
    pitch = math.degrees(math.atan2(-d[2], math.hypot(d[0], d[1])))
    return np.array([*pos, heading, pitch, cam.get("roll_deg", 0.0), cam["lens_mm"]])


def control_points():
    context = json.loads((ROOT / "inputs/context/site-review-context-regional.json").read_text())
    parcels = unary_union([Polygon(np.array(b["lines_local_m"][0])[:, :2])
                           for b in context["boundaries"] if b["kind"] == "owner_parcel_boundary"])
    trees = np.load(ROOT / "out/derived/lidar_trees.npz")["trees"]
    keep = (trees[:, 3] >= 5) & ~shapely.contains_xy(parcels.buffer(30), trees[:, 0], trees[:, 1])
    t = trees[keep]
    # Isolated trees only (no other top within 15 m): in open pasture a wrong pose puts
    # them on grass, whereas in dense woods any pose scores well.
    tree = shapely.STRtree(shapely.points(t[:, :2]))
    pairs = tree.query(shapely.points(t[:, :2]), predicate="dwithin", distance=15.0)
    neighbours = np.bincount(pairs[0], minlength=len(t)) - 1
    t = t[neighbours == 0]
    # Crown centre: ~70% of tree height above ground.
    return np.column_stack([t[:, 0], t[:, 1], t[:, 2] + 0.7 * t[:, 3]])


def score(params, points, mask):
    h, w = mask.shape
    uv, depth = project(params, points, w, h)
    ok = (depth > 1) & (uv[:, 0] >= 0) & (uv[:, 0] < w - 1) & (uv[:, 1] >= 0) & (uv[:, 1] < h - 1)
    # Near points constrain the pose most; ignore those beyond 1.5 km.
    ok &= depth < 1500
    if ok.sum() < 50:
        return 0.0, int(ok.sum())
    u, v = uv[ok, 0].astype(int), uv[ok, 1].astype(int)
    return float(mask[v, u].mean()), int(ok.sum())


def nelder_mead(f, x0, steps, iterations=400):
    simplex = [x0] + [x0 + np.eye(len(x0))[i] * steps[i] for i in range(len(x0))]
    values = [f(x) for x in simplex]
    for _ in range(iterations):
        order = np.argsort(values)
        simplex, values = [simplex[i] for i in order], [values[i] for i in order]
        centroid = np.mean(simplex[:-1], axis=0)
        reflected = centroid + (centroid - simplex[-1])
        fr = f(reflected)
        if fr < values[0]:
            expanded = centroid + 2 * (centroid - simplex[-1])
            fe = f(expanded)
            simplex[-1], values[-1] = (expanded, fe) if fe < fr else (reflected, fr)
        elif fr < values[-2]:
            simplex[-1], values[-1] = reflected, fr
        else:
            contracted = centroid + 0.5 * (simplex[-1] - centroid)
            fc = f(contracted)
            if fc < values[-1]:
                simplex[-1], values[-1] = contracted, fc
            else:
                best = simplex[0]
                simplex = [best + 0.5 * (s - best) for s in simplex]
                values = [f(s) for s in simplex]
    best = int(np.argmin(values))
    return simplex[best], values[best]


def main():
    mask, small = tree_mask()
    points = control_points()
    start = current_params()
    before, n_before = score(start, points, mask)
    steps = np.array([8.0, 8.0, 8.0, 0.6, 0.6, 0.6, 0.8])
    best, value = start, -before
    for _ in range(3):  # restarts shrink the simplex around the best pose
        best, value = nelder_mead(lambda p: -score(p, points, mask)[0], best, steps)
        steps = steps * 0.4
    after, n_after = score(best, points, mask)
    x, y, z, yaw, pitch, roll, lens = best
    forward = rotation(yaw, pitch, roll)[2]
    t = (175.0 - z) / forward[2]
    target = [x + forward[0] * t, y + forward[1] * t, 175.0]
    report = {
        "schema": "lrh.drone-camera-refine/1",
        "control": "isolated StratMap 2025 lidar trees >= 5 m outside the parcels (+30 m)",
        "photo_tree_mask_score": {"before": round(before, 4), "after": round(after, 4)},
        "points_in_view": {"before": n_before, "after": n_after},
        "start": [round(float(v), 3) for v in start],
        "refined": {"position": [round(x, 2), round(y, 2), round(z, 2)],
                    "heading_deg": round(yaw, 3), "pitch_down_deg": round(pitch, 3),
                    "roll_deg": round(roll, 3), "lens_mm": round(lens, 3)},
        "target": [round(v, 2) for v in target],
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "drone_camera_refine.json").write_text(json.dumps(report, indent=2) + "\n")
    h, w = mask.shape
    uv, _ = project(best, points, w, h)
    draw = ImageDraw.Draw(small)
    for u, v in uv:
        if 0 <= u < w and 0 <= v < h:
            draw.ellipse((u - 2, v - 2, u + 2, v + 2), outline=(255, 40, 40))
    small.save(OUT / "drone_camera_refine_overlay.jpg", quality=88)
    print(json.dumps(report, indent=2))
    print("shots.yaml camera:")
    print(f"    camera: {{position: [{x:.2f}, {y:.2f}, {z:.2f}], target: [{target[0]:.2f}, "
          f"{target[1]:.2f}, {target[2]:.2f}], lens_mm: {lens:.3f}, roll_deg: {roll:.3f}}}")


if __name__ == "__main__":
    main()
