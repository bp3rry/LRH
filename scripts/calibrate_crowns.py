"""Calibrate lidar crown radii to the lidar canopy cover.

lidar_trees.py measures crown radius as the distance to where the canopy drops below half
the tree height. In closed woods it never drops, so crowns come out far wider than the
tree spacing (median 7.9 m radius at 5.8 m spacing in the creek arm). That over-closes
the canopy and hides gaps, which matters for lake views through the flooded timber.

Each radius becomes min(measured, k * nearest-neighbour distance), with k found by
bisection so the union of crowns covers the same share of ground as lidar canopy
(CHM > 3 m) over the lidar AOI. Isolated trees keep their measured crowns. The raw
radius is kept as column 6 of lidar_trees.npz.

Usage (Blender's Python): python3.11 scripts/calibrate_crowns.py
"""

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT / ".blender-site"))
sys.path.insert(0, str(ROOT / "scripts"))

import shapely  # noqa: E402

from kwik_ortho import Surface  # noqa: E402

DERIVED = ROOT / "out/derived"
CELL = 1.0


def coverage(trees, radii, x0, y1, shape):
    grid = np.zeros(shape, bool)
    h, w = shape
    for (x, y), r in zip(trees[:, :2], radii):
        c0, c1 = int((x - r - x0) / CELL), int((x + r - x0) / CELL) + 1
        r0, r1 = int((y1 - y - r) / CELL), int((y1 - y + r) / CELL) + 1
        c0, r0, c1, r1 = max(c0, 0), max(r0, 0), min(c1, w), min(r1, h)
        if c0 >= c1 or r0 >= r1:
            continue
        cx = x0 + (np.arange(c0, c1) + 0.5) * CELL
        cy = y1 - (np.arange(r0, r1) + 0.5) * CELL
        grid[r0:r1, c0:c1] |= (cx[None, :] - x) ** 2 + (cy[:, None] - y) ** 2 <= r * r
    return grid


def main():
    data = np.load(DERIVED / "lidar_trees.npz")
    trees, columns = data["trees"], list(data["columns"])
    raw = trees[:, 6] if trees.shape[1] > 6 else trees[:, 4].copy()
    dsm, dtm = Surface(DERIVED / "lidar_dsm_1m.tif"), Surface(DERIVED / "lidar_dtm_1m.tif")
    h, w = dsm.z.shape
    x0, y1 = dsm.x0, dsm.y1
    chm = dsm.z - dtm.z
    target = float(np.mean(chm > 3.0))
    inside = (trees[:, 0] > x0) & (trees[:, 0] < x0 + w * CELL) & \
             (trees[:, 1] < y1) & (trees[:, 1] > y1 - h * CELL)
    sub = trees[inside]
    tree = shapely.STRtree(shapely.points(trees[:, :2]))
    _, nn = tree.query_nearest(shapely.points(trees[:, :2]), exclusive=True, return_distance=True,
                               all_matches=False)
    if len(nn) != len(trees):
        sys.exit("nearest-neighbour query did not return one distance per tree")

    def share(k):
        r = np.minimum(raw[inside], k * nn[inside])
        return float(coverage(sub, r, x0, y1, (h, w)).mean())

    lo, hi = 0.3, 2.0
    for _ in range(14):
        mid = (lo + hi) / 2
        if share(mid) < target:
            lo = mid
        else:
            hi = mid
    k = (lo + hi) / 2
    radii = np.minimum(raw, k * nn)
    out = np.column_stack([trees[:, :6], raw]) if trees.shape[1] == 6 else trees.copy()
    out[:, 4] = radii
    if len(columns) == 6:
        columns.append("crown_radius_raw")
    np.savez_compressed(DERIVED / "lidar_trees.npz", trees=out, columns=np.array(columns))
    fwh = shapely.geometry.shape(json.loads((DERIVED / "fwh_zone_lsmp.geojson").read_text())
                                 ["features"][0]["geometry"])
    inz = shapely.contains_xy(fwh, out[:, 0], out[:, 1])
    report = {"k_times_nearest_neighbour": round(k, 3), "target_canopy_share": round(target, 3),
              "achieved_share": round(share(k), 3),
              "fwh_zone_radius_m_p50": {"raw": round(float(np.median(raw[inz])), 2),
                                        "calibrated": round(float(np.median(radii[inz])), 2)},
              "all_radius_m_p50": {"raw": round(float(np.median(raw)), 2),
                                   "calibrated": round(float(np.median(radii)), 2)}}
    (DERIVED / "crown_calibration.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
