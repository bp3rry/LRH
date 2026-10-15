"""Solve KwikImage drone cameras and drape photos over the lidar surface (orthophoto).

For each requested photo (inputs/drone/2023-08-11_pilot-existing/raw/LADONIA-<n>.jpg):
  1. initial pose from EXIF/XMP: GPS position, DJI AbsoluteAltitude, gimbal yaw/pitch/roll,
     focal length (6.72 mm on the 1/1.3" sensor = 25.0 mm full-frame equivalent across
     the 4032 px width);
  2. refine the pose (Nelder-Mead) so isolated StratMap lidar trees (crowns at 80% of
     their height) land on tree pixels; position is held near the GPS fix by a penalty;
  3. for nadir photos, sample the photo onto a 0.25 m grid, each cell taking its height
     from the 1 m lidar DSM (removes relief displacement of tree crowns);
  4. compare the photo's tree canopy with the lidar canopy (CHM > 3 m) on the grid: the
     residual shift (phase correlation) and the canopy agreement (IoU), overall and in the
     Fish and Wildlife Habitat zone.

Writes out/derived/kwik_<n>_camera.json, kwik_<n>_ortho.tif (RGB) and kwik_<n>_canopy.tif
(photo tree mask), plus kwik_<n>_check.png (lidar crowns over the ortho).
Usage (Blender's Python): python3.11 scripts/kwik_ortho.py 24 [25 18 ...]
"""

import json
import math
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT / ".blender-site"))
sys.path.insert(0, str(ROOT / "scripts"))

import numpy as np  # noqa: E402
import shapely  # noqa: E402
from PIL import Image, ImageDraw, ImageFilter  # noqa: E402

from refine_drone_camera import nelder_mead  # noqa: E402
from solve_drone_camera import project, rotation  # noqa: E402

RAW = ROOT / "inputs/drone/2023-08-11_pilot-existing/raw"
DERIVED = ROOT / "out/derived"
ORIGIN = json.loads((ROOT / "inputs/terrain/origin.json").read_text())["origin"]
LENS_EQ_MM = 6.72 / 9.677 * 36.0  # 1/1.3" sensor, 2.4 um x 4032 px
ORTHO_CELL = 0.25
GPS_SIGMA_M = 15.0


def read_raster(path):
    with tempfile.TemporaryDirectory() as scratch:
        raw = Path(scratch) / "r.bin"
        subprocess.run(["gdal_translate", "-q", "-of", "ENVI", str(path), str(raw)], check=True)
        info = json.loads(subprocess.run(["gdalinfo", "-json", str(path)], capture_output=True,
                                         text=True, check=True).stdout)
        w, h = info["size"]
        arr = np.fromfile(raw, "<f4").reshape(h, w).astype(float)
    gt = info["geoTransform"]
    return arr, gt[0] - ORIGIN["easting"], gt[3] - ORIGIN["northing"], gt[1]


class Surface:
    def __init__(self, path):
        self.z, self.x0, self.y1, self.cell = read_raster(path)

    def __call__(self, x, y):
        col = (np.asarray(x) - self.x0) / self.cell - 0.5
        row = (self.y1 - np.asarray(y)) / self.cell - 0.5
        c0 = np.clip(np.floor(col).astype(int), 0, self.z.shape[1] - 2)
        r0 = np.clip(np.floor(row).astype(int), 0, self.z.shape[0] - 2)
        fc, fr = np.clip(col - c0, 0, 1), np.clip(row - r0, 0, 1)
        z = self.z
        return (z[r0, c0] * (1 - fc) * (1 - fr) + z[r0, c0 + 1] * fc * (1 - fr)
                + z[r0 + 1, c0] * (1 - fc) * fr + z[r0 + 1, c0 + 1] * fc * fr)


def exif_pose(n):
    path = RAW / f"LADONIA-{n}.jpg"
    im = Image.open(path)
    ex = im.getexif()
    gps = ex.get_ifd(0x8825)
    xmp = im.info.get("xmp") or b""
    xmp = xmp.encode() if isinstance(xmp, str) else xmp
    tags = {k.decode(): float(v) for k, v in re.findall(rb'drone-dji:(\w+)="([+-]?[\d.]+)"', xmp)}

    def dms(v, ref):
        d = float(v[0]) + float(v[1]) / 60 + float(v[2]) / 3600
        return -d if ref in ("S", "W") else d
    lat, lon = dms(gps[2], gps[1]), dms(gps[4], gps[3])
    out = subprocess.run(["gdaltransform", "-s_srs", "EPSG:4326", "-t_srs", "EPSG:6344"],
                         input=f"{lon} {lat}\n", capture_output=True, text=True, check=True).stdout
    e, nn = map(float, out.split()[:2])
    return im, {"x": e - ORIGIN["easting"], "y": nn - ORIGIN["northing"],
                "z": tags["AbsoluteAltitude"], "yaw": tags["GimbalYawDegree"],
                "pitch_down": -tags["GimbalPitchDegree"], "roll": tags["GimbalRollDegree"],
                "relative_altitude": tags["RelativeAltitude"], "lat": lat, "lon": lon}


def tree_mask(rgb):
    """Leaf-on tree canopy in an August photo: green and darker than sunlit pasture."""
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    return ((g - r) > 10) & (rgb.mean(axis=2) < 120) & (g > b)


def isolated_trees(trees, radius=12.0, min_h=5.0):
    t = trees[trees[:, 3] >= min_h]
    tree = shapely.STRtree(shapely.points(t[:, :2]))
    pairs = tree.query(shapely.points(t[:, :2]), predicate="dwithin", distance=radius)
    return t[np.bincount(pairs[0], minlength=len(t)) == 1]


def canopy_points(dsm, dtm, cx, cy, reach=1500.0, step=3.0):
    """Lidar canopy (CHM > 3 m) sampled on a 3 m grid within `reach` of the camera:
    points at the DSM surface and their 0/1 label, for the whole-image score."""
    gx = np.arange(max(dsm.x0, cx - reach), min(dsm.x0 + dsm.z.shape[1], cx + reach), step)
    gy = np.arange(max(dsm.y1 - dsm.z.shape[0], cy - reach), min(dsm.y1, cy + reach), step)
    X, Y = np.meshgrid(gx, gy)
    X, Y = X.ravel(), Y.ravel()
    top, ground = dsm(X, Y), dtm(X, Y)
    return np.column_stack([X, Y, top]), ((top - ground) > 3.0).astype(float)


def solve(n, trees, dsm, dtm):
    im, pose = exif_pose(n)
    rgb = np.asarray(im.convert("RGB")).astype(np.float32)
    H, W = rgb.shape[:2]
    small_w = 1344
    scale = small_w / W
    mask = tree_mask(np.asarray(im.convert("RGB").resize((small_w, round(H * scale)))).astype(float))
    blurred = np.asarray(Image.fromarray((mask * 255).astype(np.uint8)).filter(
        ImageFilter.BoxBlur(2))).astype(float) / 255
    h, w = blurred.shape
    start = np.array([pose["x"], pose["y"], pose["z"], pose["yaw"], pose["pitch_down"],
                      pose["roll"], LENS_EQ_MM])
    pts, label = canopy_points(dsm, dtm, pose["x"], pose["y"])

    def score(p):
        """Correlation between the projected lidar canopy and the photo canopy."""
        uv, depth = project(p, pts, w, h)
        ok = (depth > 1) & (uv[:, 0] >= 0) & (uv[:, 0] < w - 1) & (uv[:, 1] >= 0) & (uv[:, 1] < h - 1)
        if ok.sum() < 500:
            return -1.0, int(ok.sum())
        m = blurred[uv[ok, 1].astype(int), uv[ok, 0].astype(int)]
        lab = label[ok]
        if lab.std() == 0 or m.std() == 0:
            return -1.0, int(ok.sum())
        return float(np.corrcoef(m, lab)[0, 1]), int(ok.sum())

    def cost(p):
        s, _ = score(p)
        drift = math.hypot(p[0] - start[0], p[1] - start[1]) / GPS_SIGMA_M
        return -s + 0.02 * drift ** 2 + 0.02 * ((p[6] - LENS_EQ_MM) / 1.0) ** 2

    before = score(start)
    # Coarse search over heading and tilt first: at shallow pitches a degree of error
    # moves the ground by tens of metres and the local refinement can lock onto a
    # wrong alignment.
    best, best_cost = start, cost(start)
    for dh in np.arange(-6.0, 6.01, 1.0):
        for dp in np.arange(-4.0, 4.01, 1.0):
            for dz in (0.0,):
                p = start + np.array([0, 0, dz, dh, dp, 0, 0])
                c = cost(p)
                if c < best_cost:
                    best, best_cost = p, c
    steps = np.array([6.0, 6.0, 8.0, 1.0, 1.0, 1.0, 0.5])
    for _ in range(3):
        best, _ = nelder_mead(cost, best, steps)
        steps = steps * 0.4
    after = score(best)
    cam = {"photo": f"LADONIA-{n}.jpg", "exif": pose, "start": start.round(3).tolist(),
           "refined": {"x": best[0], "y": best[1], "z": best[2], "heading_deg": best[3],
                       "pitch_down_deg": best[4], "roll_deg": best[5], "lens_eq_mm": best[6]},
           "shift_from_gps_m": round(math.hypot(best[0] - start[0], best[1] - start[1]), 2),
           "z_change_m": round(best[2] - start[2], 2),
           "canopy_correlation": {"exif": round(before[0], 4), "refined": round(after[0], 4),
                                  "lidar_points_in_view": after[1]}}
    return im, rgb, best, cam


def ortho(n, rgb, params, dsm, dtm, fwh, trees, cam):
    H, W = rgb.shape[:2]
    # Footprint on the ground plane from the image corners.
    corners = []
    R = rotation(*params[3:6])
    f_px = params[6] / 36.0 * W
    zg = float(np.nanmedian(dtm.z))
    for u, v in ((0, 0), (W, 0), (W, H), (0, H)):
        ray = R.T @ np.array([(u - W / 2) / f_px, -(v - H / 2) / f_px, 1.0])
        t = (zg - params[2]) / ray[2]
        corners.append(params[:2] + ray[:2] * t)
    corners = np.array(corners)
    x0, y0 = corners.min(axis=0)
    x1, y1 = corners.max(axis=0)
    gx = np.arange(x0, x1, ORTHO_CELL) + ORTHO_CELL / 2
    gy = np.arange(y1, y0, -ORTHO_CELL) - ORTHO_CELL / 2
    X, Y = np.meshgrid(gx, gy)
    Z = dsm(X.ravel(), Y.ravel())
    uv, depth = project(params, np.column_stack([X.ravel(), Y.ravel(), Z]), W, H)
    ok = (depth > 1) & (uv[:, 0] >= 0) & (uv[:, 0] < W - 1) & (uv[:, 1] >= 0) & (uv[:, 1] < H - 1)
    out = np.zeros((X.size, 3), np.uint8)
    ui, vi = uv[ok, 0].astype(int), uv[ok, 1].astype(int)
    out[ok] = rgb[vi, ui].astype(np.uint8)
    img = out.reshape(X.shape + (3,))
    valid = ok.reshape(X.shape)
    photo_canopy = tree_mask(img.astype(float)) & valid
    # Smooth the photo canopy to crown scale (~1.5 m) before comparing.
    pc = np.asarray(Image.fromarray((photo_canopy * 255).astype(np.uint8)).filter(
        ImageFilter.BoxBlur(3))).astype(float) / 255 > 0.5
    chm = dsm(X.ravel(), Y.ravel()) - dtm(X.ravel(), Y.ravel())
    lidar_canopy = (chm.reshape(X.shape) > 3.0) & valid

    def agreement(sel):
        a, b = pc & sel, lidar_canopy & sel
        inter, union = (a & b).sum(), (a | b).sum()
        return {"photo_canopy_share": round(float(a.sum() / max(sel.sum(), 1)), 3),
                "lidar_canopy_share": round(float(b.sum() / max(sel.sum(), 1)), 3),
                "iou": round(float(inter / max(union, 1)), 3)}

    # Residual shift between the two canopy masks (phase correlation, 1 m blocks).
    k = int(1.0 / ORTHO_CELL)
    hh, ww = (pc.shape[0] // k) * k, (pc.shape[1] // k) * k
    A = pc[:hh, :ww].reshape(hh // k, k, ww // k, k).mean((1, 3)) - 0.5
    B = lidar_canopy[:hh, :ww].reshape(hh // k, k, ww // k, k).mean((1, 3)) - 0.5
    F = np.fft.fft2(A) * np.conj(np.fft.fft2(B))
    corr = np.fft.ifft2(F / (np.abs(F) + 1e-9)).real
    dy, dx = np.unravel_index(corr.argmax(), corr.shape)
    dy = dy - corr.shape[0] if dy > corr.shape[0] // 2 else dy
    dx = dx - corr.shape[1] if dx > corr.shape[1] // 2 else dx
    in_fwh = shapely.contains_xy(fwh, X, Y) & valid
    cam["ortho"] = {"bounds_local_m": [round(v, 1) for v in (x0, y0, x1, y1)],
                    "cell_m": ORTHO_CELL, "valid_share": round(float(valid.mean()), 3),
                    "canopy_shift_photo_minus_lidar_m": {"east": float(dx), "north": float(-dy)},
                    "canopy_all": agreement(valid),
                    "canopy_fwh_zone": agreement(in_fwh),
                    "fwh_zone_share_of_footprint": round(float(in_fwh.mean()), 3)}
    # Outputs.
    def write(arr, name, bands):
        with tempfile.TemporaryDirectory() as scratch:
            raw = Path(scratch) / "o.bin"
            np.ascontiguousarray(arr.reshape(arr.shape[0], arr.shape[1], bands).transpose(2, 0, 1)
                                 ).astype(np.uint8).tofile(raw)
            raw.with_suffix(".hdr").write_text(
                f"ENVI\nsamples = {arr.shape[1]}\nlines = {arr.shape[0]}\nbands = {bands}\n"
                "header offset = 0\nfile type = ENVI Standard\ndata type = 1\n"
                "interleave = bsq\nbyte order = 0\n")
            e, nn = ORIGIN["easting"], ORIGIN["northing"]
            subprocess.run(["gdal_translate", "-q", "-co", "COMPRESS=DEFLATE", "-a_srs", "EPSG:6344",
                            "-a_ullr", str(x0 + e), str(y1 + nn),
                            str(x0 + arr.shape[1] * ORTHO_CELL + e), str(y1 - arr.shape[0] * ORTHO_CELL + nn),
                            str(raw), str(DERIVED / name)], check=True)
    write(img, f"kwik_{n}_ortho.tif", 3)
    write((pc * 255).astype(np.uint8)[..., None], f"kwik_{n}_canopy.tif", 1)
    # Check image: lidar tree crowns (circles) over the ortho, FWH zone outline in cyan.
    view = Image.fromarray(img)
    d = ImageDraw.Draw(view)
    sel = (trees[:, 0] > x0) & (trees[:, 0] < x1) & (trees[:, 1] > y0) & (trees[:, 1] < y1)
    for x, y, _, hgt, r in trees[sel][:, :5]:
        u, v = (x - x0) / ORTHO_CELL, (y1 - y) / ORTHO_CELL
        rr = r / ORTHO_CELL
        d.ellipse((u - rr, v - rr, u + rr, v + rr), outline=(255, 40, 40), width=2)
    for ring in ([fwh.exterior] + list(fwh.interiors)) if fwh.geom_type == "Polygon" else \
            [g.exterior for g in fwh.geoms]:
        d.line([((x - x0) / ORTHO_CELL, (y1 - y) / ORTHO_CELL) for x, y in ring.coords],
               fill=(0, 230, 255), width=4)
    view.thumbnail((2400, 2400))
    view.save(DERIVED / f"kwik_{n}_check.jpg", quality=88)


def overlay(n, rgb, params, fwh, trees, dtm, cam):
    """Oblique check: lidar crowns (ellipses at crown height) and the FWH zone drawn on the
    photo; scores the share of in-zone crown centres that land on photo tree canopy."""
    H, W = rgb.shape[:2]
    view = Image.fromarray(rgb.astype(np.uint8))
    d = ImageDraw.Draw(view)
    f_px = params[6] / 36.0 * W
    tops = np.column_stack([trees[:, 0], trees[:, 1], trees[:, 2] + 0.7 * trees[:, 3]])
    uv, depth = project(params, tops, W, H)
    ok = (depth > 1) & (uv[:, 0] > 0) & (uv[:, 0] < W) & (uv[:, 1] > 0) & (uv[:, 1] < H) & (depth < 2000)
    inz = shapely.contains_xy(fwh, trees[:, 0], trees[:, 1])
    mask = tree_mask(rgb)
    hits = mask[uv[ok & inz, 1].astype(int), uv[ok & inz, 0].astype(int)]
    for (u, v), dep, r, z in zip(uv[ok], depth[ok], trees[ok, 4], inz[ok]):
        rr = max(2.0, r * f_px / dep)
        d.ellipse((u - rr, v - rr * 0.6, u + rr, v + rr * 0.6),
                  outline=(0, 230, 255) if z else (255, 40, 40), width=2)
    ring = fwh.exterior if fwh.geom_type == "Polygon" else max(fwh.geoms, key=lambda g: g.area).exterior
    pts = np.array(ring.coords)
    zr = dtm(pts[:, 0], pts[:, 1])
    ruv, rd = project(params, np.column_stack([pts, np.maximum(zr, 167.94)]), W, H)
    d.line([tuple(p) for p, dd in zip(ruv, rd) if dd > 1], fill=(255, 230, 0), width=4)
    cam["oblique_check"] = {"fwh_crowns_in_view": int((ok & inz).sum()),
                            "fwh_crown_centres_on_photo_canopy": round(float(hits.mean()), 3)
                            if len(hits) else None,
                            "photo_canopy_share_in_frame": round(float(mask.mean()), 3)}
    view.thumbnail((2016, 2016))
    view.save(DERIVED / f"kwik_{n}_check.jpg", quality=88)


def main():
    shots = [int(a) for a in sys.argv[1:]] or [24]
    trees = np.load(DERIVED / "lidar_trees.npz")["trees"]
    dsm, dtm = Surface(DERIVED / "lidar_dsm_1m.tif"), Surface(DERIVED / "lidar_dtm_1m.tif")
    fwh = shapely.geometry.shape(json.loads((DERIVED / "fwh_zone_lsmp.geojson").read_text())
                                 ["features"][0]["geometry"])
    for n in shots:
        im, rgb, params, cam = solve(n, trees, dsm, dtm)
        if cam["exif"]["pitch_down"] > 80:
            ortho(n, rgb, params, dsm, dtm, fwh, trees, cam)
        else:
            overlay(n, rgb, params, fwh, trees, dtm, cam)
        (DERIVED / f"kwik_{n}_camera.json").write_text(json.dumps(cam, indent=2, default=float) + "\n")
        print(json.dumps({k: cam[k] for k in cam if k not in ("exif", "start")}, indent=1, default=float))


if __name__ == "__main__":
    main()
