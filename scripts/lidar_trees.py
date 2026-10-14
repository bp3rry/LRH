"""Individual trees from the StratMap 2025 classified point cloud (canopy source (a)).

For each LAZ tile in inputs/lidar/ (owner-downloaded, flown 9 Dec 2025, leaf-off):
  1. decode with .build/laz_dump (LASzip 3.5; laspy/lazrs cannot read these tiles);
  2. 1 m grids: ground = mean z of class 2, holes filled from neighbours; canopy = max z
     of classes 3-5 (vegetation); CHM = canopy - ground;
  3. tree tops = CHM local maxima >= 3 m, window radius growing with height;
  4. crown radius = mean distance, along 8 directions, to where CHM falls below half the
     top height;
  5. evergreen score = vegetation share of all returns inside the crown. The flight was
     leaf-off, so dense crowns are evergreen (eastern red cedar) and open ones deciduous.

Writes out/derived/lidar_trees.npz (LRH local metres) and lidar_coverage.json (tile
footprints with data). Usage (Blender's Python):
  /Applications/Blender.app/Contents/Resources/5.0/python/bin/python3.11 scripts/lidar_trees.py
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
LIDAR = ROOT / "inputs/lidar"
DUMP = ROOT / ".build/laz_dump"
OUT = ROOT / "out/derived"
ORIGIN = json.loads((ROOT / "inputs/terrain/origin.json").read_text())["origin"]
CELL = 1.0
MIN_HEIGHT_M = 3.0
VEGETATION = (3, 4, 5)
GROUND = 2
RECORD = np.dtype([("x", "<i4"), ("y", "<i4"), ("z", "<i4"), ("c", "u1"), ("r", "u1")])


def read_tile(laz, scratch):
    binary = Path(scratch) / (laz.stem + ".bin")
    subprocess.run([str(DUMP), str(laz), str(binary)], check=True, capture_output=True)
    head = np.fromfile(binary, "<f8", 8)
    points = np.fromfile(binary, RECORD, offset=64)
    binary.unlink()
    if len(points) != int(head[6]):
        sys.exit(f"{laz.name}: read {len(points)} of {int(head[6])} points")
    x = points["x"] * head[0] + head[3] - ORIGIN["easting"]
    y = points["y"] * head[1] + head[4] - ORIGIN["northing"]
    z = points["z"] * head[2] + head[5]
    return x, y, z, points["c"]


def grid_reduce(ix, iy, values, shape, how):
    flat = iy * shape[1] + ix
    out = np.full(shape[0] * shape[1], np.nan)
    if len(flat) == 0:
        return out.reshape(shape)
    order = np.argsort(flat, kind="stable")
    flat, values = flat[order], values[order]
    starts = np.flatnonzero(np.r_[True, flat[1:] != flat[:-1]])
    if how == "max":
        out[flat[starts]] = np.maximum.reduceat(values, starts)
    else:
        out[flat[starts]] = np.add.reduceat(values, starts) / np.diff(np.r_[starts, len(flat)])
    return out.reshape(shape)


def counts(ix, iy, shape):
    return np.bincount(iy * shape[1] + ix, minlength=shape[0] * shape[1]).reshape(shape)


def fill_holes(grid, passes=60):
    """Fill NaN cells from the mean of valid 8-neighbours, growing inward."""
    grid = grid.copy()
    for _ in range(passes):
        holes = np.isnan(grid)
        if not holes.any():
            break
        padded = np.pad(grid, 1, constant_values=np.nan)
        stack = np.stack([padded[1 + dy:1 + dy + grid.shape[0], 1 + dx:1 + dx + grid.shape[1]]
                          for dy in (-1, 0, 1) for dx in (-1, 0, 1) if dy or dx])
        valid = ~np.isnan(stack)
        mean = np.where(valid.any(0), np.nansum(stack, 0) / np.maximum(valid.sum(0), 1), np.nan)
        grid[holes] = mean[holes]
    return grid


def max_filter(grid, radius):
    padded = np.pad(grid, radius, constant_values=-np.inf)
    out = np.full(grid.shape, -np.inf)
    h, w = grid.shape
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            if dx * dx + dy * dy <= radius * radius:
                out = np.maximum(out, padded[radius + dy:radius + dy + h, radius + dx:radius + dx + w])
    return out


def box_mean(grid, radius):
    padded = np.pad(grid, radius, mode="edge")
    h, w = grid.shape
    return np.mean([padded[radius + dy:radius + dy + h, radius + dx:radius + dx + w]
                    for dy in range(-radius, radius + 1) for dx in range(-radius, radius + 1)], 0)


def process(laz, scratch):
    x, y, z, cls = read_tile(laz, scratch)
    x0, y0 = np.floor(x.min()), np.floor(y.min())
    shape = (int(np.ceil(y.max() - y0)) + 1, int(np.ceil(x.max() - x0)) + 1)
    ix, iy = ((x - x0) / CELL).astype(int), ((y - y0) / CELL).astype(int)
    g, v = cls == GROUND, np.isin(cls, VEGETATION)
    ground = fill_holes(grid_reduce(ix[g], iy[g], z[g], shape, "mean"))
    canopy = grid_reduce(ix[v], iy[v], z[v], shape, "max")
    chm = np.nan_to_num(canopy - ground, nan=0.0).clip(0, 45)
    veg_n, ground_n = counts(ix[v], iy[v], shape), counts(ix[g], iy[g], shape)

    smooth = box_mean(chm, 1)
    # Window radius 2 m below 8 m, 3 m to 15 m, 4 m above (crowns widen with height).
    peaks = np.zeros(chm.shape, bool)
    for radius, lo, hi in ((2, MIN_HEIGHT_M, 8.0), (3, 8.0, 15.0), (4, 15.0, 99.0)):
        band = (smooth >= lo) & (smooth < hi)
        peaks |= band & (smooth >= max_filter(smooth, radius)) & (chm >= MIN_HEIGHT_M)
    ty, tx = np.nonzero(peaks)
    height = chm[ty, tx]

    # Crown radius: 8 rays, first step where CHM < half the top height.
    angles = np.linspace(0, 2 * np.pi, 8, endpoint=False)
    steps = np.arange(1, 13)
    radii = np.full((len(tx), 8), float(steps[-1]))
    for a, angle in enumerate(angles):
        reached = np.zeros(len(tx), bool)
        for s in steps:
            sx = np.clip(np.round(tx + np.cos(angle) * s).astype(int), 0, chm.shape[1] - 1)
            sy = np.clip(np.round(ty + np.sin(angle) * s).astype(int), 0, chm.shape[0] - 1)
            below = (chm[sy, sx] < 0.5 * height) & ~reached
            radii[below, a] = s - 0.5
            reached |= below
    crown = radii.mean(1) * CELL

    # Evergreen score: vegetation share of returns within ~0.6 x crown radius.
    veg_box = box_mean(veg_n.astype(float), 2)
    ground_box = box_mean(ground_n.astype(float), 2)
    evergreen = veg_box[ty, tx] / np.maximum(veg_box[ty, tx] + ground_box[ty, tx], 1e-6)

    lx, ly = x0 + (tx + 0.5) * CELL, y0 + (ty + 0.5) * CELL
    footprint = [float(x.min()), float(y.min()), float(x.max()), float(y.max())]
    return np.column_stack([lx, ly, ground[ty, tx], height, crown, evergreen]), footprint


def main():
    if not DUMP.is_file():
        sys.exit("build .build/laz_dump first (see scripts/native/laz_dump.c)")
    tiles = sorted(LIDAR.glob("*.laz"))
    if not tiles:
        sys.exit("no LAZ tiles in inputs/lidar/")
    rows, footprints = [], {}
    with tempfile.TemporaryDirectory() as scratch:
        for laz in tiles:
            trees, footprint = process(laz, scratch)
            rows.append(trees)
            footprints[laz.stem] = footprint
            h = trees[:, 3]
            print(f"{laz.stem}: {len(trees)} trees, height p50 {np.median(h):.1f} m, "
                  f"p95 {np.percentile(h, 95):.1f} m")
    trees = np.vstack(rows)
    # Tiles overlap slightly at their edges: drop tops within 1.5 m of an earlier one.
    key = np.round(trees[:, :2] / 1.5).astype(np.int64)
    _, first = np.unique(key[:, 0] * 10_000_000 + key[:, 1], return_index=True)
    trees = trees[np.sort(first)]
    OUT.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(OUT / "lidar_trees.npz", trees=trees,
                        columns=np.array(["x", "y", "ground_z", "height", "crown_radius",
                                          "evergreen_score"]))
    (OUT / "lidar_coverage.json").write_text(json.dumps({
        "source": "StratMap 2025 Ralph Hall classified point cloud (flown 2025-12-09)",
        "tiles_local_m_bounds": footprints,
        "trees": int(len(trees)),
        "height_m_percentiles": dict(zip(["p10", "p50", "p90", "p99"], np.percentile(
            trees[:, 3], [10, 50, 90, 99]).round(2).tolist())),
        "evergreen_score_percentiles": dict(zip(["p10", "p50", "p90"], np.percentile(
            trees[:, 5], [10, 50, 90]).round(3).tolist())),
    }, indent=2) + "\n")
    print(f"{len(trees)} trees total")


if __name__ == "__main__":
    main()
