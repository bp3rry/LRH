"""Update the parcel clearing from the fall 2026 KwikImage gallery view (PLAN.md, "Updated
imagery"). The gallery's first view repeats the 2023 drone-match photo (LADONIA-18) from
almost the same position, so it is registered onto that photo and read through the 2023
photo's solved camera (shots.yaml check_drone_match).

1. Registration: SIFT matches (contrast-equalised luminance) between the 2026 view and
   the 2023 photo, homography by MAGSAC. Parallax between the two viewpoints is well
   under a metre at the parcels, so a plane-to-plane mapping suffices.
2. Each measured lidar tree inside the owner parcels is projected at 75% of its height
   into the 2023 photo, then into the 2026 view. The tree counts as cleared since 2023
   if at least SAND_MIN of its crown disc (60% of the lidar crown radius) in the 2026 view
   is freshly scraped ground: brighter than the dormant pasture by SAND_DL, warm
   (Lab b* > SAND_B), and smooth (3x3 luminance std < SAND_TEX). Leafless deciduous trees
   read as textured grey-brown and are kept; texture alone cannot tell them from cleared
   ground at screenshot resolution.

Writes out/derived/clearing_2026.json (rule, registration, removed trees),
clearing_2026.geojson (their crown footprints), cover_site_2026.tif (cover_site_drone.tif
with those footprints as cleared ground), ground_mask_2026.png (ground_mask_leveled.png
plus the footprints) and clearing_2026_check.jpg (removed red, kept green, on the 2026 view).
The build prefers the *_2026 products when present (lrh.site_cover_path, ground mask).

Usage (Blender's Python):
  python3.11 scripts/observed_clearing_2026.py [<2026 view image>]
"""

import glob
import json
import math
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT / ".blender-site"))
sys.path.insert(0, str(ROOT / "scripts"))

import cv2  # noqa: E402
import numpy as np  # noqa: E402
import shapely  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402
from shapely.geometry import Polygon, mapping  # noqa: E402

from observed_cover_drone import PHOTO, drone_camera, read_raster  # noqa: E402
from solve_drone_camera import SENSOR_MM  # noqa: E402

DERIVED = ROOT / "out/derived"
CAPTURE = ROOT / "inputs/drone/2026-11-24_kwik-gallery-screenshots/raw"
ORIGIN = json.loads((ROOT / "inputs/terrain/origin.json").read_text())["origin"]
CROWN_SAMPLE = 0.6
SAND_DL, SAND_B, SAND_TEX, SAND_MIN = 12.0, 14.0, 9.0, 0.6
MIN_INLIERS = 40


def register(view, ref):
    """Homography taking 2026-view pixels to 2023-photo pixels."""
    s = view.shape[1] / ref.shape[1]
    up = 1.5
    refs = cv2.resize(ref, None, fx=s * up, fy=s * up, interpolation=cv2.INTER_AREA)
    views = cv2.resize(view, None, fx=up, fy=up, interpolation=cv2.INTER_CUBIC)
    clahe = cv2.createCLAHE(3.0, (8, 8))
    prep = lambda im: clahe.apply(cv2.cvtColor(im, cv2.COLOR_BGR2GRAY))  # noqa: E731
    sift = cv2.SIFT_create(8000)
    k1, d1 = sift.detectAndCompute(prep(refs), None)
    k2, d2 = sift.detectAndCompute(prep(views), None)
    good = [a for a, b in cv2.BFMatcher().knnMatch(d2, d1, k=2) if a.distance < 0.8 * b.distance]
    p2 = np.float32([k2[a.queryIdx].pt for a in good]) / up
    p1 = np.float32([k1[a.trainIdx].pt for a in good]) / (s * up)
    H, inl = cv2.findHomography(p2, p1, cv2.USAC_MAGSAC, 4.0 / s)
    inl = inl.ravel().astype(bool)
    if H is None or inl.sum() < MIN_INLIERS:
        sys.exit(f"FAIL registration: {int(inl.sum()) if inl is not None else 0} inliers "
                 f"(need {MIN_INLIERS})")
    err = np.linalg.norm(cv2.perspectiveTransform(p2[inl].reshape(-1, 1, 2), H).reshape(-1, 2)
                         - p1[inl], axis=1) * s
    return H, {"matches": len(good), "inliers": int(inl.sum()),
               "rms_px_2026_view": round(float(np.sqrt((err ** 2).mean())), 2)}


def main():
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(glob.glob(str(CAPTURE / "*10.38.29*"))[0])
    view = cv2.imread(str(path))
    ref = cv2.imread(str(PHOTO))
    if view is None or ref is None:
        sys.exit("FAIL cannot read the 2026 view or the 2023 photo")
    H, reg = register(view, ref)
    Hi = np.linalg.inv(H)

    context = json.loads((ROOT / "inputs/context/site-review-context-regional.json").read_text())
    parcels = shapely.union_all([Polygon(np.array(b["lines_local_m"][0])[:, :2])
                                 for b in context["boundaries"] if b["kind"] == "owner_parcel_boundary"])
    trees = np.load(DERIVED / "lidar_trees.npz")["trees"]
    trees = trees[shapely.contains_xy(parcels, trees[:, 0], trees[:, 1])]
    if len(trees) == 0:
        sys.exit("FAIL no lidar trees inside the parcels")

    position, rot, lens = drone_camera()
    w, h = ref.shape[1], ref.shape[0]
    pts = np.column_stack([trees[:, 0], trees[:, 1], trees[:, 2] + 0.75 * trees[:, 3]])
    cam = (pts - position) @ rot.T
    scale = lens / SENSOR_MM * w
    uv = np.column_stack([w / 2 + scale * cam[:, 0] / cam[:, 2], h / 2 - scale * cam[:, 1] / cam[:, 2]])
    q = cv2.perspectiveTransform(uv.reshape(-1, 1, 2).astype(np.float64), Hi).reshape(-1, 2)
    rad = np.maximum(scale * trees[:, 4] / cam[:, 2] * (view.shape[1] / w) * CROWN_SAMPLE, 1.5)

    lab = cv2.cvtColor(view, cv2.COLOR_BGR2LAB).astype(np.float32)
    L, B = lab[..., 0], lab[..., 2] - 128
    mu = cv2.blur(L, (3, 3))
    tex = np.sqrt(np.maximum(cv2.blur(L * L, (3, 3)) - mu * mu, 0))
    # Dormant pasture brightness: median over the parcel footprint in the view.
    hull = cv2.convexHull(q.astype(np.float32)).astype(np.int32)
    pmask = np.zeros(L.shape, np.uint8)
    cv2.fillPoly(pmask, [hull], 1)
    pasture_l = float(np.median(L[pmask > 0]))
    sand = (L > pasture_l + SAND_DL) & (B > SAND_B) & (tex < SAND_TEX)

    frac = np.full(len(trees), np.nan)
    for i, ((x, y), r) in enumerate(zip(q, rad)):
        R, xi, yi = int(math.ceil(r)), int(round(x)), int(round(y))
        if R <= xi < view.shape[1] - R and R <= yi < view.shape[0] - R:
            frac[i] = sand[yi - R:yi + R + 1, xi - R:xi + R + 1].mean()
    seen = np.isfinite(frac)
    if seen.mean() < 0.95:
        sys.exit(f"FAIL only {seen.mean():.0%} of the parcel trees fall inside the 2026 view")
    removed = seen & (frac >= SAND_MIN)

    footprint = shapely.union_all([shapely.Point(t[0], t[1]).buffer(max(t[4], 2.0))
                                   for t in trees[removed]]).intersection(parcels)
    (DERIVED / "clearing_2026.geojson").write_text(json.dumps({
        "type": "FeatureCollection", "crs_note": "LRH local metres (origin.json)",
        "features": [{"type": "Feature", "geometry": mapping(footprint),
                      "properties": {"source": "KwikImage gallery, fall 2026", "trees": int(removed.sum())}}]},
        indent=1) + "\n")

    # Cover and ground mask with the footprints as cleared ground.
    with tempfile.TemporaryDirectory() as scratch:
        cover, gt = read_raster(DERIVED / "cover_site_drone.tif", np.uint8, scratch)
    rows, cols = np.indices(cover.shape)
    gx = gt[0] + (cols + 0.5) * gt[1] - ORIGIN["easting"]
    gy = gt[3] + (rows + 0.5) * gt[5] - ORIGIN["northing"]
    cells = shapely.contains_xy(footprint, gx, gy) if not footprint.is_empty else np.zeros(cover.shape, bool)
    updated = cover.copy()
    updated[cells] = 4
    raw = DERIVED / "cover_site_2026.raw"
    updated.tofile(raw)
    raw.with_suffix(".hdr").write_text(
        f"ENVI\nsamples = {cover.shape[1]}\nlines = {cover.shape[0]}\nbands = 1\nheader offset = 0\n"
        "file type = ENVI Standard\ndata type = 1\ninterleave = bsq\nbyte order = 0\n")
    hh, ww = cover.shape
    subprocess.run(["gdal_translate", "-q", "-co", "COMPRESS=DEFLATE", "-a_srs", "EPSG:6344",
                    "-a_ullr", str(gt[0]), str(gt[3]), str(gt[0] + gt[1] * ww), str(gt[3] + gt[5] * hh),
                    "-mo", "classes=0 water,1 bare/road,2 pasture/grass,3 woods,4 cleared "
                    "(drone photo Aug 2023 + KwikImage gallery fall 2026)",
                    str(raw), str(DERIVED / "cover_site_2026.tif")], check=True)
    raw.unlink()
    raw.with_suffix(".hdr").unlink()
    base = DERIVED / "ground_mask_leveled.png"
    mask = np.array(Image.open(base if base.is_file() else DERIVED / "cleared_drone_mask.png").convert("L"))
    if mask.shape != cover.shape:
        sys.exit("FAIL ground mask and cover grids differ")
    mask[cells] = 255
    Image.fromarray(mask).save(DERIVED / "ground_mask_2026.png")

    big = cv2.resize(view, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    for (x, y), r, gone in zip(q, rad, removed):
        cv2.circle(big, (int(x * 2), int(y * 2)), max(int(r * 2), 3), (0, 0, 255) if gone else (0, 200, 0), 2)
    cv2.imwrite(str(DERIVED / "clearing_2026_check.jpg"), big, [cv2.IMWRITE_JPEG_QUALITY, 90])

    record = {
        "view": str(path.relative_to(ROOT)), "reference": str(PHOTO.relative_to(ROOT)),
        "camera": "shots.yaml check_drone_match", "registration": reg,
        "rule": {"crown_sample": CROWN_SAMPLE, "sand_dl_over_pasture": SAND_DL, "sand_b_min": SAND_B,
                 "sand_tex_max": SAND_TEX, "sand_fraction_min": SAND_MIN, "pasture_l": round(pasture_l, 1)},
        "parcel_trees": len(trees), "removed": int(removed.sum()),
        "cleared_area_m2": round(footprint.area, 1), "cover_cells_set_cleared": int(cells.sum()),
        "removed_trees": [{"x": round(float(t[0]), 2), "y": round(float(t[1]), 2),
                           "height_m": round(float(t[3]), 1), "crown_m": round(float(t[4]), 1),
                           "sand_fraction": round(float(f), 2)} for t, f in zip(trees[removed], frac[removed])],
    }
    (DERIVED / "clearing_2026.json").write_text(json.dumps(record, indent=1) + "\n")
    print(f"registration {reg}; {int(removed.sum())} of {len(trees)} parcel trees cleared since 2023, "
          f"{footprint.area:.0f} m2")


if __name__ == "__main__":
    main()
