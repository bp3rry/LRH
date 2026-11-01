"""Terrain and water for the dock permit analysis (scripts/dock_permit.py).

Builds the site terrain, the regional stitch and the 551 ft water exactly as
build_baseline.py does, and writes the 1 m site grid and the water polygons to
out/<date>/dock permit/: z.npy (grid heights, m NAVD88) and geom.json.

Usage: Blender -b --python scripts/blender/dock_permit_geom.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import lrh  # noqa: E402  (adds .blender-site to sys.path)
import numpy as np  # noqa: E402
import shapely  # noqa: E402

import build_baseline as bb  # noqa: E402

OUT = lrh.out_dir() / "dock permit"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    bb.clear_scene()
    colls = {n: bb.collection(n) for n in ("Terrain", "Water", "Landmarks")}
    terrain = bb.import_site_terrain(colls["Terrain"])
    grid = bb.SiteGrid(bb.mesh_vertices(terrain))
    if bb.level_brush_piles(terrain):
        grid = bb.SiteGrid(bb.mesh_vertices(terrain))
    regional = bb.stitch_regional_terrain(grid, bb.mesh_vertices(terrain), colls["Terrain"])
    context = lrh.load_context()
    dam = bb.build_dam(context, colls["Landmarks"])
    sampler = bb.HeightSampler([terrain, regional, dam])
    _, _, pooled = bb.build_water(grid, context, colls["Water"], sampler)
    arm = max(pooled.geoms, key=lambda g: g.area) if pooled.geom_type == "MultiPolygon" else pooled
    np.save(OUT / "z.npy", grid.z.astype(np.float32))
    (OUT / "geom.json").write_text(json.dumps({
        "xmin": float(grid.xmin), "ymin": float(grid.ymin), "pool_m": lrh.POOL_M,
        "arm_wkt": shapely.to_wkt(arm, rounding_precision=2), "commit": lrh.git_commit()}))
    print(f"WROTE {OUT}")


main()
