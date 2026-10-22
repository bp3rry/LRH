"""Boat route from the Lot 1-2 dock west to the deep creek channel and on to the open
lake (owner, 21 Oct 2026; tree clearing assumed under the UTRWD one-time clearing event).

Least-cost path over the flooded arm on a 2 m grid from the StratMap lidar DTM:
- water at the 551 ft pool only (at least 1 m deep);
- step cost rises sharply in shallow water: dist x (1 + 12 / (1 + depth^2)), so the route
  reaches the old creek channel (10-11 m deep, x ~ -390) as soon as it can and follows
  it;
- the goal is the main lake: open water north of the mapped Fish and Wildlife Habitat
  (timber) zone.

Writes out/derived/boat_routes.json ({name: [[x, y], ...]}), which
lotplan.boat_channels clears 40 ft wide. Usage (Blender's Python): python3.11 scripts/boat_route.py
"""

import heapq
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT / ".blender-site"))
sys.path.insert(0, str(ROOT / "scripts"))

import numpy as np  # noqa: E402
import shapely  # noqa: E402
from shapely.geometry import LineString, Point  # noqa: E402

from kwik_ortho import Surface  # noqa: E402

DERIVED = ROOT / "out/derived"
POOL_M = 167.9448
CELL = 2.0
X0, X1, Y0, Y1 = -700.0, -100.0, 150.0, 1040.0
START = (-170.8, 252.9)              # Lot 1-2 dock base (lotplan.dock_layout)


def route(dtm, zone, start):
    xs = np.arange(X0, X1, CELL)
    ys = np.arange(Y0, Y1, CELL)
    gx, gy = np.meshgrid(xs, ys)
    depth = POOL_M - dtm(gx.ravel(), gy.ravel()).reshape(gx.shape)
    water = depth >= 1.0
    # The main lake opens north of the timbered arm (the zone ends at y ~ 680).
    goal = water & ~shapely.contains_xy(zone.buffer(10.0), gx.ravel(), gy.ravel()).reshape(gx.shape) \
        & (gy >= zone.bounds[3] - 10.0)
    si = int(np.argmin(np.abs(ys - start[1])))
    sj = int(np.argmin(np.abs(xs - start[0])))
    # nearest water cell to the dock base
    w = np.argwhere(water)
    k = np.argmin((w[:, 0] - si) ** 2 + (w[:, 1] - sj) ** 2)
    si, sj = map(int, w[k])
    h, wd = water.shape
    dist = np.full(water.shape, np.inf)
    prev = -np.ones(water.shape + (2,), int)
    dist[si, sj] = 0.0
    heap = [(0.0, si, sj)]
    steps = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]
    end = None
    while heap:
        c, i, j = heapq.heappop(heap)
        if c > dist[i, j]:
            continue
        if goal[i, j]:
            end = (i, j)
            break
        for di, dj in steps:
            a, b = i + di, j + dj
            if 0 <= a < h and 0 <= b < wd and water[a, b]:
                dd = CELL * (1.4142 if di and dj else 1.0)
                nc = c + dd * (1.0 + 12.0 / (1.0 + depth[a, b] ** 2))
                if nc < dist[a, b]:
                    dist[a, b] = nc
                    prev[a, b] = (i, j)
                    heapq.heappush(heap, (nc, a, b))
    if end is None:
        return None, None
    path, (i, j) = [], end
    while i >= 0:
        path.append((float(xs[j]), float(ys[i])))
        i, j = prev[i, j]
    path = path[::-1]
    line = LineString([start] + path).simplify(4.0)
    d_along = [float(POOL_M - dtm(np.array([p[0]]), np.array([p[1]]))[0]) for p in line.coords]
    return line, d_along


def main():
    dtm = Surface(DERIVED / "lidar_dtm_1m.tif")
    zone = shapely.geometry.shape(json.loads((DERIVED / "fwh_zone_lsmp.geojson").read_text())
                                  ["features"][0]["geometry"])
    line, depths = route(dtm, zone, START)
    if line is None:
        print("no route found")
        return
    out = {"lot_1_2_west": [[round(x, 1), round(y, 1)] for x, y in line.coords]}
    (DERIVED / "boat_routes.json").write_text(json.dumps(out, indent=1) + "\n")
    print(f"route {line.length:.0f} m, {len(line.coords)} vertices, ends at "
          f"({line.coords[-1][0]:.0f}, {line.coords[-1][1]:.0f}); depth along: "
          f"min {min(depths[1:]):.1f} m, max {max(depths):.1f} m")


if __name__ == "__main__":
    main()
