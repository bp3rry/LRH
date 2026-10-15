"""Update the site ground cover inside the owner parcels from the drone photo (KwikImage,
11 Aug 2023).

NAIP (July 2024) is newer but at 0.6 m reads the scraped ground as pasture, so the photo
defines the clearing inside the parcels. For every 0.6 m cover
cell inside the owner parcels, this projects the point 5 m above the ground (about
mid-canopy, which offsets the lean of tree crowns in an oblique view) into the photo
through the solved check_drone_match camera, and classifies the photo colour:
dark green -> woods (3), green -> pasture (2), tan/brown -> cleared ground (4).
Cells outside the parcels keep their NAIP class.

Writes out/derived/cover_site_drone.tif (+ preview) and observed_cover_drone.json.
Usage (Blender's Python for numpy, Pillow, shapely, PyYAML in .blender-site):
  /Applications/Blender.app/Contents/Resources/5.0/python/bin/python3.11 scripts/observed_cover_drone.py
"""

import json
import math
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT / ".blender-site"))

import numpy as np  # noqa: E402
import shapely  # noqa: E402
import yaml  # noqa: E402
from PIL import Image  # noqa: E402
from shapely.geometry import Polygon  # noqa: E402
from shapely.ops import unary_union  # noqa: E402

sys.path.insert(0, str(ROOT / "scripts"))
from solve_drone_camera import SENSOR_MM, rotation  # noqa: E402

DERIVED = ROOT / "out/derived"
PHOTO = ROOT / "inputs/reference/drone-ladonia-arial-1.jpeg"
CANOPY_SAMPLE_HEIGHT_M = 5.0
RULES = {"woods_green_minus_red_min": 12, "woods_brightness_max": 125,
         "cleared_green_minus_red_max": -5}
ORIGIN = json.loads((ROOT / "inputs/terrain/origin.json").read_text())["origin"]


def read_raster(path, dtype, scratch):
    raw = Path(scratch) / (Path(path).stem + ".bin")
    subprocess.run(["gdal_translate", "-q", "-of", "ENVI", str(path), str(raw)], check=True)
    info = json.loads(subprocess.run(["gdalinfo", "-json", str(path)], capture_output=True,
                                     text=True, check=True).stdout)
    w, h = info["size"]
    return np.fromfile(raw, dtype).reshape(h, w), info["geoTransform"]


def bilinear(grid, gt, x, y):
    col = (x - gt[0]) / gt[1] - 0.5
    row = (y - gt[3]) / gt[5] - 0.5
    c0 = np.clip(np.floor(col).astype(int), 0, grid.shape[1] - 2)
    r0 = np.clip(np.floor(row).astype(int), 0, grid.shape[0] - 2)
    fc, fr = np.clip(col - c0, 0, 1), np.clip(row - r0, 0, 1)
    return (grid[r0, c0] * (1 - fc) * (1 - fr) + grid[r0, c0 + 1] * fc * (1 - fr)
            + grid[r0 + 1, c0] * (1 - fc) * fr + grid[r0 + 1, c0 + 1] * fc * fr)


def drone_camera():
    cam = yaml.safe_load((ROOT / "shots.yaml").read_text())["shots"]["check_drone_match"]["camera"]
    pos, tgt = np.array(cam["position"]), np.array(cam["target"])
    d = tgt - pos
    heading = math.degrees(math.atan2(d[0], d[1]))
    pitch = math.degrees(math.atan2(-d[2], math.hypot(d[0], d[1])))
    return pos, rotation(heading, pitch, cam.get("roll_deg", 0.0)), cam["lens_mm"]


def main():
    with tempfile.TemporaryDirectory() as scratch:
        cover, gt = read_raster(DERIVED / "cover_site.tif", np.uint8, scratch)
        dem, dem_gt = read_raster(ROOT / "inputs/terrain/terrain_site.tif", "<f4", scratch)
    dem = dem.astype(float)
    dem[dem == -9999] = np.nan

    context = json.loads((ROOT / "inputs/context/site-review-context-regional.json").read_text())
    parcels = unary_union([Polygon(np.array(b["lines_local_m"][0])[:, :2] + [ORIGIN["easting"],
                                                                              ORIGIN["northing"]])
                           for b in context["boundaries"] if b["kind"] == "owner_parcel_boundary"])
    rows, cols = np.indices(cover.shape)
    x = gt[0] + (cols + 0.5) * gt[1]
    y = gt[3] + (rows + 0.5) * gt[5]
    inside = shapely.contains_xy(parcels, x, y)
    px, py = x[inside], y[inside]
    pz = bilinear(dem, dem_gt, px, py) + CANOPY_SAMPLE_HEIGHT_M
    if np.isnan(pz).any():
        sys.exit("terrain has voids inside the parcels")

    photo = np.asarray(Image.open(PHOTO).convert("RGB")).astype(np.float32)
    height, width, _ = photo.shape
    position, rot, lens = drone_camera()
    local = np.column_stack([px - ORIGIN["easting"], py - ORIGIN["northing"], pz])
    cam = (local - position) @ rot.T
    scale = lens / SENSOR_MM * width
    u = width / 2 + scale * cam[:, 0] / cam[:, 2]
    v = height / 2 - scale * cam[:, 1] / cam[:, 2]
    seen = (u >= 3) & (u < width - 3) & (v >= 3) & (v < height - 3)
    if seen.mean() < 0.99:
        sys.exit(f"only {seen.mean():.1%} of the parcels fall inside the drone photo")

    # 5x5 pixel mean colour at each projected point.
    ui, vi = np.round(u).astype(int), np.round(v).astype(int)
    rgb = np.mean([photo[vi + dv, ui + du] for dv in range(-2, 3) for du in range(-2, 3)], axis=0)
    green_minus_red = rgb[:, 1] - rgb[:, 0]
    brightness = rgb.mean(axis=1)
    observed = np.full(len(px), 2, np.uint8)
    observed[green_minus_red < RULES["cleared_green_minus_red_max"]] = 4
    observed[(green_minus_red > RULES["woods_green_minus_red_min"])
             & (brightness < RULES["woods_brightness_max"])] = 3

    updated = cover.copy()
    updated[inside] = observed
    shares = {}
    for label, grid in (("naip", cover[inside]), ("drone_2023", updated[inside])):
        shares[label] = {name: round(float((grid == value).mean()), 4) for value, name in
                         enumerate(["water", "bare", "pasture", "woods", "cleared"])}
    print(json.dumps(shares))
    if shares["drone_2023"]["cleared"] < 0.2:
        sys.exit("drone photo shows a large clearing, but under 20% classified as cleared")

    raw = DERIVED / "cover_site_drone.raw"
    updated.tofile(raw)
    raw.with_suffix(".hdr").write_text(
        f"ENVI\nsamples = {cover.shape[1]}\nlines = {cover.shape[0]}\nbands = 1\n"
        "header offset = 0\nfile type = ENVI Standard\ndata type = 1\ninterleave = bsq\n"
        "byte order = 0\n")
    h, w = cover.shape
    subprocess.run(["gdal_translate", "-q", "-co", "COMPRESS=DEFLATE", "-a_srs", "EPSG:6344",
                    "-a_ullr", str(gt[0]), str(gt[3]), str(gt[0] + gt[1] * w), str(gt[3] + gt[5] * h),
                    "-mo", "classes=0 water,1 bare/road,2 pasture/grass,3 woods,4 cleared (drone photo, Aug 2023)",
                    str(raw), str(DERIVED / "cover_site_drone.tif")], check=True)
    raw.unlink()
    raw.with_suffix(".hdr").unlink()
    palette = np.array([[90, 140, 200], [200, 190, 160], [170, 190, 110], [30, 80, 30],
                        [225, 185, 140]], np.uint8)
    Image.fromarray(palette[updated]).save(DERIVED / "cover_site_drone_preview.png")
    # Shader mask: 255 where the August 2023 drone photo shows cleared ground.
    Image.fromarray(np.where(updated == 4, 255, 0).astype(np.uint8)).save(
        DERIVED / "cleared_drone_mask.png")
    (DERIVED / "observed_cover_drone.json").write_text(json.dumps({
        "photo": str(PHOTO), "camera": "shots.yaml check_drone_match",
        "canopy_sample_height_m": CANOPY_SAMPLE_HEIGHT_M, "rules": RULES,
        "parcel_cells": int(inside.sum()), "shares_inside_parcels": shares}, indent=2) + "\n")


if __name__ == "__main__":
    main()
