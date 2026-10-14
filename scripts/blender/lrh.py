"""Shared paths, inputs and checks for the LRH Blender scripts.

Imported by build_baseline.py and render.py, which run inside Blender's bundled Python.
Extra packages (PyYAML, shapely) live in .blender-site/; see requirements.txt there.
"""

import hashlib
import json
import math
import re
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
INPUTS = ROOT / "inputs"
OUT_ROOT = ROOT / "out"
SITE_PACKAGES = ROOT / ".blender-site"
# Appended, not prepended, so Blender's own numpy always wins.
if str(SITE_PACKAGES) not in sys.path:
    sys.path.append(str(SITE_PACKAGES))

ORIGIN_JSON = json.loads((INPUTS / "terrain/origin.json").read_text())
ORIGIN_E = ORIGIN_JSON["origin"]["easting"]
ORIGIN_N = ORIGIN_JSON["origin"]["northing"]
POOL_M = 167.9448  # 551 ft conservation pool (UTRWD label; datum tie unverified)
SITE_LAT, SITE_LON = 33.4447, -95.9173  # centre of terrain_site.tif
LAKE_DAE = INPUTS / "geometry/lake-ralph-hall-50m-terrain-551ft-reference.dae"


class CheckFailed(RuntimeError):
    pass


def fail(message):
    print(f"LRH CHECK FAILED: {message}", file=sys.stderr)
    sys.exit(1)


def out_dir(day=None):
    path = OUT_ROOT / (day or date.today().isoformat())
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_context():
    return json.loads((INPUTS / "context/site-review-context-regional.json").read_text())


def git_commit():
    def git(*args):
        return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True,
                              text=True).stdout.strip()
    return {"head": git("rev-parse", "HEAD"), "dirty": bool(git("status", "--porcelain"))}


def file_sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def dae_geometry(geometry_id, text=None):
    """(coords, triangles) of one <geometry> in the PTM lake DAE, in local metres, Z-up."""
    text = text or LAKE_DAE.read_text()
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
    return coords, tris


def read_site_raster(scratch):
    """terrain_site.tif as (array, origin_x_local, origin_y_local, cell) via GDAL CLI."""
    target = Path(scratch) / "terrain_site.bin"
    subprocess.run(["gdal_translate", "-q", "-of", "ENVI", str(INPUTS / "terrain/terrain_site.tif"),
                    str(target)], check=True)
    info = json.loads(subprocess.run(["gdalinfo", "-json", str(INPUTS / "terrain/terrain_site.tif")],
                                     capture_output=True, text=True, check=True).stdout)
    width, height = info["size"]
    gt = info["geoTransform"]
    array = np.fromfile(target, dtype="<f4").reshape(height, width).astype(float)
    array[array == -9999] = np.nan
    return array, gt[0] - ORIGIN_E, gt[3] - ORIGIN_N, gt[1]


def solar_position(when_local, utc_offset_h, lat=SITE_LAT, lon=SITE_LON):
    """Sun (elevation_deg, azimuth_deg clockwise from north), NOAA approximation."""
    utc = when_local - timedelta(hours=utc_offset_h)
    day_of_year = utc.timetuple().tm_yday
    hour = utc.hour + utc.minute / 60 + utc.second / 3600
    gamma = 2 * math.pi / 365 * (day_of_year - 1 + (hour - 12) / 24)
    eqtime = 229.18 * (0.000075 + 0.001868 * math.cos(gamma) - 0.032077 * math.sin(gamma)
                       - 0.014615 * math.cos(2 * gamma) - 0.040849 * math.sin(2 * gamma))
    decl = (0.006918 - 0.399912 * math.cos(gamma) + 0.070257 * math.sin(gamma)
            - 0.006758 * math.cos(2 * gamma) + 0.000907 * math.sin(2 * gamma)
            - 0.002697 * math.cos(3 * gamma) + 0.00148 * math.sin(3 * gamma))
    true_solar_min = hour * 60 + eqtime + 4 * lon
    hour_angle = math.radians(true_solar_min / 4 - 180)
    phi = math.radians(lat)
    cos_zenith = (math.sin(phi) * math.sin(decl)
                  + math.cos(phi) * math.cos(decl) * math.cos(hour_angle))
    zenith = math.acos(max(-1.0, min(1.0, cos_zenith)))
    azimuth = math.degrees(math.atan2(
        math.sin(hour_angle),
        math.cos(hour_angle) * math.sin(phi) - math.tan(decl) * math.cos(phi))) + 180
    return 90 - math.degrees(zenith), azimuth % 360


def frame_stats(path):
    """Luminance statistics of a rendered frame; raises CheckFailed if it is blank."""
    import bpy
    image = bpy.data.images.load(str(path), check_existing=False)
    pixels = np.array(image.pixels[:], dtype=np.float64).reshape(-1, 4)[:, :3]
    bpy.data.images.remove(image)
    luminance = 0.2126 * pixels[:, 0] + 0.7152 * pixels[:, 1] + 0.0722 * pixels[:, 2]
    stats = {
        "mean": float(luminance.mean()),
        "std": float(luminance.std()),
        "clipped_fraction": float((luminance > 0.97).mean()),
        "black_fraction": float((luminance < 0.02).mean()),
    }
    print("frame luminance " + " ".join(f"{k}={v:.3f}" for k, v in stats.items()))
    if stats["std"] < 0.04:
        raise CheckFailed(f"{path.name} looks blank (luminance std {stats['std']:.4f})")
    if stats["clipped_fraction"] > 0.25 or stats["black_fraction"] > 0.25:
        raise CheckFailed(f"{path.name} is mostly clipped or black; check exposure")
    return stats


def utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
