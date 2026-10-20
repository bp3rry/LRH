"""Brush piles inside the parcels, to be burned and levelled (owner, 20 Oct 2026).

The piles show in the lidar ground model as mounds 0.7-1.5 m above the surrounding
grade, and in NAIP 2024 as grey-lilac blotches on the pasture. They are found as
connected cells of the 1 m lidar DTM more than 0.6 m above its 31 m running mean, at
least 15 m2, inside the parcels (3 m in from the lines).

Writes:
- out/derived/brush_piles.geojson: one polygon per pile (cells grown by 2 m), with the
  level grade (median ground of a 3-8 m ring round it).
- out/derived/ground_mask_leveled.png: the drone-photo cleared mask (same grid as
  naip_site_rgb.png) with the pile footprints added, so the ground material grasses them
  over in "grassed" shots.

build_baseline.py flattens the site terrain to each pile's level grade (feathered over
3 m) and uses the new mask.

Usage (Blender's Python): python3.11 scripts/brush_piles.py
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT / ".blender-site"))
sys.path.insert(0, str(ROOT / "scripts"))

import numpy as np  # noqa: E402
import shapely  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402
from shapely.geometry import Polygon, box, mapping  # noqa: E402

from kwik_ortho import Surface  # noqa: E402

DERIVED = ROOT / "out/derived"
BUMP_M, MIN_CELLS, HALF = 0.6, 15, 15


def box_mean(z, k):
    n = 2 * k + 1
    s = np.pad(np.pad(z, k, mode="edge").cumsum(0).cumsum(1), ((1, 0), (1, 0)))
    h, w = z.shape
    return (s[n:n + h, n:n + w] - s[0:h, n:n + w] - s[n:n + h, 0:w] + s[0:h, 0:w]) / (n * n)


def main():
    dtm = Surface(DERIVED / "lidar_dtm_1m.tif")
    ctx = json.loads((ROOT / "inputs/context/site-review-context-regional.json").read_text())
    parcel = shapely.union_all([Polygon(np.array(b["lines_local_m"][0])[:, :2])
                                for b in ctx["boundaries"] if b["kind"] == "owner_parcel_boundary"])
    x0, y0, x1, y1 = parcel.bounds
    gx, gy = np.meshgrid(np.arange(x0 - 20, x1 + 20, 1.0), np.arange(y0 - 20, y1 + 20, 1.0))
    z = dtm(gx.ravel(), gy.ravel()).reshape(gx.shape)
    bump = z - box_mean(z, HALF)
    inside = shapely.contains_xy(parcel.buffer(-3.0), gx.ravel(), gy.ravel()).reshape(gx.shape)
    mask = inside & (bump > BUMP_M)
    seen = np.zeros(mask.shape, bool)
    piles = []
    for i, j in zip(*np.nonzero(mask)):
        if seen[i, j]:
            continue
        stack, cells = [(i, j)], []
        seen[i, j] = True
        while stack:
            a, b = stack.pop()
            cells.append((a, b))
            for da, db in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                q, r = a + da, b + db
                if 0 <= q < mask.shape[0] and 0 <= r < mask.shape[1] and mask[q, r] and not seen[q, r]:
                    seen[q, r] = True
                    stack.append((q, r))
        if len(cells) < MIN_CELLS:
            continue
        c = np.array(cells)
        poly = shapely.union_all([box(gx[a, b] - 0.5, gy[a, b] - 0.5, gx[a, b] + 0.5, gy[a, b] + 0.5)
                                  for a, b in c]).buffer(2.0).simplify(0.3)
        ring = poly.buffer(6.0).difference(poly.buffer(1.0))
        rx, ry = np.meshgrid(np.arange(*ring.bounds[0::2], 1.0), np.arange(*ring.bounds[1::2], 1.0))
        sel = shapely.contains_xy(ring, rx.ravel(), ry.ravel())
        level = float(np.median(dtm(rx.ravel()[sel], ry.ravel()[sel])))
        piles.append({"poly": poly, "level_m": level, "height_m": float(bump[c[:, 0], c[:, 1]].max()),
                      "area_m2": float(len(cells))})
    feats = [{"type": "Feature", "geometry": mapping(p["poly"]),
              "properties": {"id": k + 1, "level_m": round(p["level_m"], 3),
                             "mound_height_m": round(p["height_m"], 2), "area_m2": p["area_m2"]}}
             for k, p in enumerate(sorted(piles, key=lambda p: -p["poly"].centroid.y))]
    (DERIVED / "brush_piles.geojson").write_text(json.dumps(
        {"type": "FeatureCollection", "crs_note": "LRH local metres (origin.json)",
         "status": "to be burned and levelled (owner, 20 Oct 2026)", "features": feats}, indent=1) + "\n")
    # Ground mask: cleared photo mask plus the pile footprints.
    lock = json.loads((ROOT / "imagery.lock.json").read_text())
    prod = lock["products"][lock["use"]["site"]]
    xmin, _, _, ymax = prod["bbox_local_m"]
    cell = prod["cell_m"]
    m = Image.open(DERIVED / "cleared_drone_mask.png").convert("L")
    d = ImageDraw.Draw(m)
    for p in piles:
        d.polygon([((x - xmin) / cell, (ymax - y) / cell) for x, y in p["poly"].buffer(1.0).exterior.coords],
                  fill=255)
    m.save(DERIVED / "ground_mask_leveled.png")
    print(f"{len(piles)} brush piles; heights "
          f"{min(p['height_m'] for p in piles):.1f}-{max(p['height_m'] for p in piles):.1f} m")


if __name__ == "__main__":
    main()
