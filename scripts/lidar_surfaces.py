"""1 m lidar surface models over the site and creek arm, from the StratMap 2025 tiles.

DSM = highest non-noise return per cell (canopy top where there are trees; leaf-off, so
deciduous crowns read a little low); DTM = mean class-2 ground, holes filled. Both are
written as GeoTIFFs (EPSG:6344) to out/derived/ for draping photos (kwik_ortho.py) and
for canopy comparisons.

Usage (Blender's Python): python3.11 scripts/lidar_surfaces.py
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lidar_trees as L  # noqa: E402

AOI = (-1000.0, -650.0, 800.0, 1050.0)  # LRH local metres: xmin, ymin, xmax, ymax
CELL = 1.0
NOISE = (7, 18)


def write_tif(grid, path, x0, y1):
    with tempfile.TemporaryDirectory() as scratch:
        raw = Path(scratch) / "g.bin"
        grid.astype("<f4").tofile(raw)
        h, w = grid.shape
        raw.with_suffix(".hdr").write_text(
            f"ENVI\nsamples = {w}\nlines = {h}\nbands = 1\nheader offset = 0\n"
            "file type = ENVI Standard\ndata type = 4\ninterleave = bsq\nbyte order = 0\n")
        e, n = L.ORIGIN["easting"], L.ORIGIN["northing"]
        subprocess.run(["gdal_translate", "-q", "-co", "COMPRESS=DEFLATE", "-a_srs", "EPSG:6344",
                        "-a_nodata", "-9999", "-a_ullr", str(x0 + e), str(y1 + n),
                        str(x0 + w * CELL + e), str(y1 - h * CELL + n), str(raw), str(path)],
                       check=True)


def main():
    x0, y0, x1, y1 = AOI
    w, h = int((x1 - x0) / CELL), int((y1 - y0) / CELL)
    dsm = np.full((h, w), -np.inf)
    gsum, gcnt = np.zeros((h, w)), np.zeros((h, w))
    coverage = json.loads((L.OUT / "lidar_coverage.json").read_text())["tiles_local_m_bounds"]
    with tempfile.TemporaryDirectory() as scratch:
        for laz in sorted(L.LIDAR.glob("*.laz")):
            b = coverage.get(laz.stem)
            if b and (b[2] < x0 or b[0] > x1 or b[3] < y0 or b[1] > y1):
                continue
            x, y, z, c = L.read_tile(laz, scratch)
            col = ((x - x0) / CELL).astype(int)
            row = ((y1 - y) / CELL).astype(int)  # north-up rows
            ok = (col >= 0) & (col < w) & (row >= 0) & (row < h) & ~np.isin(c, NOISE)
            np.maximum.at(dsm, (row[ok], col[ok]), z[ok])
            g = ok & (c == L.GROUND)
            np.add.at(gsum, (row[g], col[g]), z[g])
            np.add.at(gcnt, (row[g], col[g]), 1)
            print(laz.stem, int(ok.sum()), "points in AOI")
    dtm = np.where(gcnt > 0, gsum / np.maximum(gcnt, 1), np.nan)
    dtm = L.fill_holes(dtm, passes=200)
    dsm[~np.isfinite(dsm)] = np.nan
    dsm = np.where(np.isnan(dsm), dtm, np.maximum(dsm, dtm))
    if np.isnan(dtm).mean() > 0.01:
        sys.exit(f"DTM has {np.isnan(dtm).mean():.1%} holes after filling")
    write_tif(dsm, L.OUT / "lidar_dsm_1m.tif", x0, y1)
    write_tif(dtm, L.OUT / "lidar_dtm_1m.tif", x0, y1)
    chm = dsm - dtm
    print(f"DSM/DTM {w}x{h} m; canopy > 3 m on {np.mean(chm > 3):.1%} of the AOI")


if __name__ == "__main__":
    main()
