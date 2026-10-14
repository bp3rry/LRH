"""Digitize the Fish and Wildlife Habitat zone beside the lots from the draft LSMP map.

Source: UTRWD Lake & Shoreline Management Plan, comment draft of 16 Oct 2025,
Appendix A (PDF page 56, 1:50,000), copied into inputs/ by import_inputs.py. The map
is marked "For planning purposes only. Contact UTRWD for official shoreline
classifications", so this outline is an approximate, conceptual extent for an artist's
conception, not a boundary. UTRWD holds the official georeferenced map.

Method: render the page at 300 dpi; register it to LRH local metres with a similarity
transform fitted to three road points (UTRWD's official CR 3640 new alignment and the
TxDOT CR 3635 centreline; ~8 m residuals); take the checkered habitat fill in the creek
arm west of County Road 3635 (dark squares inside a window), merge it into one polygon
and transform it.

Writes out/derived/fwh_zone_lsmp.geojson (LRH local metres) and an overlay PNG.
Usage (Blender's Python): python3.11 scripts/digitize_fwh_zone.py
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT / ".blender-site"))

import numpy as np  # noqa: E402
import shapely  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402
from shapely.affinity import affine_transform  # noqa: E402

PDF = ROOT / "inputs/reference/lsmp-comment-draft-2025-10-16.pdf"
PAGE, DPI = 56, 300
OUT = ROOT / "out/derived"
# (page pixel x, y) -> LRH local metres. Pixel positions are road-pixel centroids.
CONTROL = [
    ((4012.3, 2100.7), (141.8, -204.8), "CR 3640 / CR 3635 junction (UTRWD CR 3640 east end)"),
    ((3602.0, 2111.6), (-1585.5, -144.9), "CR 3640 west bend (UTRWD CR 3640 west end)"),
    ((3993.1, 2014.5), (70.1, 152.8), "CR 3635 bend (TxDOT CR 3635 north end)"),
]
# Window around the creek arm west of CR 3635 (page pixels), above the CR 3640 road line.
WINDOW = (3830, 1880, 3960, 2093)


def fit_similarity():
    rows, rhs = [], []
    for (x, y), (X, Y), _ in CONTROL:
        rows += [[x, y, 1, 0], [-y, x, 0, 1]]
        rhs += [X, Y]
    a, b, tx, ty = np.linalg.lstsq(np.array(rows, float), np.array(rhs, float), rcond=None)[0]
    # local = [[a, b], [b, -a]] @ [x, y] + t  (page y points down; local y points north)
    matrix = [a, b, b, -a, tx, ty]
    residuals = [float(np.hypot(a * x + b * y + tx - X, b * x - a * y + ty - Y))
                 for (x, y), (X, Y), _ in CONTROL]
    return matrix, residuals, float(np.hypot(a, b))


def main():
    with tempfile.TemporaryDirectory() as scratch:
        stem = Path(scratch) / "page"
        subprocess.run(["pdftoppm", "-f", str(PAGE), "-l", str(PAGE), "-r", str(DPI), "-png",
                        str(PDF), str(stem)], check=True)
        page = Image.open(next(Path(scratch).glob("page*.png"))).convert("RGB")
    rgb = np.asarray(page).astype(int)
    x0, y0, x1, y1 = WINDOW
    window = rgb[y0:y1, x0:x1]
    neutral = (np.abs(window[:, :, 0] - window[:, :, 1]) < 18) & \
        (np.abs(window[:, :, 1] - window[:, :, 2]) < 18)
    dark = neutral & (window.mean(axis=2) < 90)  # checker squares and outline
    ys, xs = np.nonzero(dark)
    if len(xs) < 200:
        sys.exit(f"only {len(xs)} habitat pixels found; check WINDOW against the page")
    # Squares are ~6 px apart: merge them, then pull the edge back in.
    blobs = shapely.union_all([shapely.Point(x, y).buffer(4.5, quad_segs=2)
                               for x, y in zip(xs + x0 + 0.5, ys + y0 + 0.5)])
    zone_px = blobs.buffer(-2.0)
    if zone_px.geom_type == "MultiPolygon":
        zone_px = max(zone_px.geoms, key=lambda g: g.area)
    zone_px = shapely.Polygon(zone_px.exterior)  # fill internal gaps between squares

    matrix, residuals, scale = fit_similarity()
    zone = affine_transform(zone_px, matrix).simplify(2.0)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "fwh_zone_lsmp.geojson").write_text(json.dumps({
        "type": "FeatureCollection",
        "crs_note": "LRH local metres (origin.json); add origin to recover EPSG:6344",
        "features": [{"type": "Feature", "geometry": shapely.geometry.mapping(zone),
                      "properties": {
                          "name": "Fish and Wildlife Habitat (water surface classification)",
                          "source": f"UTRWD LSMP comment draft 2025-10-16, Appendix A, PDF page {PAGE}",
                          "status": "approximate; planning graphic, not an official boundary",
                          "registration_scale_m_per_px": round(scale, 3),
                          "registration_residuals_m": [round(r, 1) for r in residuals],
                          "control": [c[2] for c in CONTROL],
                          "area_acres": round(zone.area / 4046.8564224, 2)}}]}, indent=1) + "\n")
    overlay = page.crop((x0 - 150, y0 - 60, x1 + 120, y1 + 60))
    draw = ImageDraw.Draw(overlay)
    draw.line([(x - x0 + 150, y - y0 + 60) for x, y in zone_px.exterior.coords],
              fill=(255, 0, 0), width=2)
    overlay.resize((overlay.width * 3, overlay.height * 3)).save(OUT / "fwh_zone_lsmp_overlay.png")
    print(f"zone {zone.area / 4046.8564224:.1f} ac, bounds {np.round(zone.bounds, 0)}, "
          f"scale {scale:.3f} m/px, residuals {np.round(residuals, 1)} m")


if __name__ == "__main__":
    main()
