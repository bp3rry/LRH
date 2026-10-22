"""Conceptual planting plan (owner, 20 Oct 2026): natural privacy screens and water-loving
trees, on a budget - fast-growing clumping bamboo does most of the screening.

- Bamboo screens along the interior lot lines in the house zone (from the house's lake
  end to 12 m short of CR 3635), clumps every 2.4 m, staggered.
- A mixed screen of loblolly pine, oak and pecan along the CR 3635 frontage (and CR 3640
  for Lot 10, and the parcel's north end), every 9 m, with crape myrtles flanking each
  drive entrance for colour.
- Water-loving trees in the low ground: bald cypress, water oak and sycamore round the
  pond and along the creek, and a pair at the lake-side corners of each lot (leaving the
  centre of the lake-side acre open for the view).

Everything keeps clear of drives, parking, septic areas (both options), the access-road
corridor, easements, recreation sites, the pond and the creek channel, existing lidar
trees and UTRWD land. Writes out/derived/planting.json.

Usage (Blender's Python): python3.11 scripts/planting_plan.py
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT / ".blender-site"))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts/blender"))

import numpy as np  # noqa: E402
import shapely  # noqa: E402
from shapely.geometry import LineString, Point, Polygon, box  # noqa: E402

import build_sites as bs  # noqa: E402
import grading  # noqa: E402

DERIVED = ROOT / "out/derived"
FRONT = ["loblolly_pine", "oak", "pecan", "loblolly_pine", "oak"]
LOWLAND = ["bald_cypress", "water_oak", "sycamore", "bald_cypress"]


SCREEN_MIX = ["bamboo", "crape_myrtle", "bamboo", "redbud"]
RECLAIM_N = 56                 # one new tree for each tree cleared for the boat channels
RECLAIM_H = 15 * 0.3048        # young nursery trees, ~15 ft


def reclamation(plants, lots, trees, keep_out):
    """Owner, 22 Oct 2026 ("reclamation"): native trees replanted along the shoreline in
    front of the lots, behind the docks and beaches - one for each of the 56 trees cleared
    for the boat channels. Young (~15 ft) trees in the band 10-35 m landward of the 551 ft
    shoreline, kept off the shoreline path (which runs ~4 m from the water), beaches,
    access paths, dock approaches and existing trees, spread evenly along the shore.
    Species by distance from the water: bald cypress and sycamore nearest, water oak in the
    middle, redbud on the higher edge."""
    from kwik_ortho import Surface
    POOL = 167.9448
    dtm = Surface(DERIVED / "lidar_dtm_1m.tif")
    y0 = min(p.bounds[1] for p in lots.values()) - 10
    y1 = max(p.bounds[3] for p in lots.values()) + 10
    xw = min(p.bounds[0] for p in lots.values())
    gx, gy = np.meshgrid(np.arange(xw - 160, xw + 60, 2.0), np.arange(y0, y1, 2.0))
    X, Y = gx.ravel(), gy.ravel()
    z = dtm(X, Y)
    water = z < POOL
    wx, wy = X[water], Y[water]
    land = (z >= POOL + 0.2) & (z < POOL + 6.0)
    cx, cy = X[land], Y[land]
    # Distance to water, from the water cells within 50 m (chunked).
    dist = np.full(len(cx), np.inf)
    for i in range(0, len(cx), 2000):
        a, b = cx[i:i + 2000, None], cy[i:i + 2000, None]
        near = (np.abs(wy[None, :] - b) < 50) & (np.abs(wx[None, :] - a) < 50)
        d = np.where(near, np.hypot(wx[None, :] - a, wy[None, :] - b), np.inf)
        dist[i:i + 2000] = d.min(axis=1)
    # Owner, 22 Oct 2026: on the shoreline, further north, views need not be kept clear;
    # only the boat routes and docks must stay open.
    south = lots["Lot 10"].bounds[1] + 25.0
    band = (dist >= 8.0) & (dist <= 45.0) & (cy >= south)
    cx, cy, dist = cx[band], cy[band], dist[band]
    sites = json.loads(sorted(ROOT.glob("out/*/lot_sites.json"))[-1].read_text())
    docks = json.loads(sorted(ROOT.glob("out/*/baseline_checks.json"))[-1].read_text())["checks"]["docks_lsmp"]["docks"]
    block = [Point(v["shore_circle"]).buffer(16.0) for v in sites.values()]
    block += [LineString([v["west"], v["shore_circle"]]).buffer(4.0) for v in sites.values()]
    block += [Point(d["base"]).buffer(20.0) for d in docks]
    # Dock gangways and the cleared boat routes stay open (with crown room).
    for d in docks:
        b = np.array(d["base"])
        u = np.array(d.get("dir") or [-1.0, 0.0])
        block.append(LineString([tuple(b), tuple(b + u * 40.0)]).buffer(12.0))
    routes = DERIVED / "boat_routes.json"
    if routes.is_file():
        block += [LineString(r).buffer(15.0) for r in json.loads(routes.read_text()).values()]
    block = shapely.union_all(block + [keep_out])
    ok = ~shapely.contains_xy(block, cx, cy)
    tr = np.min(np.hypot(trees[:, None, 0] - cx[None, ok], trees[:, None, 1] - cy[None, ok]) - trees[:, None, 4],
                axis=0) if ok.any() else np.array([])
    cx, cy, dist = cx[ok][tr > 2.5], cy[ok][tr > 2.5], dist[ok][tr > 2.5]
    # Even spread: farthest-point sampling, at least 7 m apart, from the south end.
    chosen = [int(np.argmin(cy))]
    dmin = np.hypot(cx - cx[chosen[0]], cy - cy[chosen[0]])
    while len(chosen) < RECLAIM_N and dmin.max() >= 7.0:
        k = int(np.argmax(dmin))
        chosen.append(k)
        dmin = np.minimum(dmin, np.hypot(cx - cx[k], cy - cy[k]))
    rng = np.random.default_rng(2210)
    for k in chosen:
        d = dist[k]
        if d < 18:
            sp = "bald_cypress" if rng.random() < 0.55 else "sycamore"
        elif d < 28:
            sp = "water_oak" if rng.random() < 0.7 else "sycamore"
        else:
            sp = "redbud" if rng.random() < 0.6 else "water_oak"
        plants.append({"species": sp, "x": round(float(cx[k]), 2), "y": round(float(cy[k]), 2),
                       "group": "reclamation", "h": round(RECLAIM_H, 2)})
    return len(chosen)


def main():
    lots, road = bs.lots_and_road()
    feats = json.loads((DERIVED / "build_sites.geojson").read_text())["features"]
    geo = lambda f: shapely.geometry.shape(f["geometry"])
    by = {}
    for f in feats:
        by.setdefault(f["properties"]["kind"], []).append((f["properties"], geo(f)))
    dr = json.loads((DERIVED / "drainage.json").read_text())
    creek = LineString(dr["creek"])
    pond = Polygon(dr["pond"]["polygon"])
    access = by["access_road"][0][1]
    keep_out = [access.buffer(bs.ACCESS_HALF_M + 3.0), creek.buffer(4.0), pond.buffer(4.0)]
    for kind, pad_m in (("drive_front", 4.0), ("drive_rear", 4.0), ("septic", 3.0), ("drip_lake", 3.0),
                        ("easement", 1.0), ("rec_site", 2.0), ("sewer_stub", 1.0)):
        keep_out += [g.buffer(pad_m) for _, g in by.get(kind, [])]
    for p, pad in by["pad"]:
        L = grading.layout(pad.bounds)
        keep_out.append(shapely.union_all([pad, box(*L["carport"])] +
                                          [box(*t[:4]) for t in p.get("terraces", [])]).buffer(4.0))
    # Nothing on or beside relocated CR 3640 (owner, 22 Oct 2026).
    origin = json.loads((ROOT / "inputs/terrain/origin.json").read_text())["origin"]
    c3640 = np.array(json.loads((ROOT / "inputs/geometry/cr3640-composite-context-route-epsg6344.geojson")
                                .read_text())["features"][0]["geometry"]["coordinates"])[:, :2]
    keep_out.append(LineString(c3640 - [origin["easting"], origin["northing"]]).buffer(14.0))
    keep_out = shapely.union_all(keep_out)
    parcel = shapely.union_all(list(lots.values()))
    inside = parcel.buffer(-1.5)
    trees = np.load(DERIVED / "lidar_trees.npz")["trees"]
    plants = []

    def place(species, x, y, group, clear=2.0, **extra):
        pt = Point(x, y)
        if not inside.contains(pt) or keep_out.contains(pt):
            return False
        d = np.hypot(trees[:, 0] - x, trees[:, 1] - y) - trees[:, 4]
        if d.min() < clear:
            return False
        if any(np.hypot(q["x"] - x, q["y"] - y) < (1.6 if species == "bamboo" else 4.0) for q in plants[-60:]):
            return False
        plants.append({"species": species, "x": round(x, 2), "y": round(y, 2), "group": group, **extra})
        return True

    labels = sorted(lots, key=lambda k: int(k.split()[-1]))
    pads = {p["lot"]: (p, g) for p, g in by["pad"]}
    tanks = {p["lot"]: g for p, g in by.get("septic_tank", [])}
    # 1. Bamboo along interior lot lines in the house zone.
    for a, b in zip(labels[:-1], labels[1:]):
        line = lots[a].intersection(lots[b])
        if line.is_empty or line.length < 20:
            continue
        line = shapely.ops.linemerge(line) if line.geom_type == "MultiLineString" else line
        east = max(bs.east_edge(lots[a]).bounds[0], bs.east_edge(lots[b]).bounds[0])
        # West end: just short of the access-road corridor, so patios and terraces are
        # screened too; east end 12 m short of CR 3635.
        yl = line.centroid.y
        hit = access.buffer(bs.ACCESS_HALF_M + 3.0).intersection(LineString([(-1e4, yl), (1e4, yl)]))
        west = (hit.bounds[2] + 3.0) if not hit.is_empty else \
            min([pads[k][1].bounds[0] - 6.0 for k in (a, b) if k in pads] or [line.bounds[0]])
        # Owner, 22 Oct 2026: screens thinned by 80% (one plant every 12 m instead of
        # every 2.4 m), alternating clumping bamboo, crape myrtle and redbud.
        for t, x in enumerate(np.arange(west, east - 12.0, 12.0)):
            hit = line.intersection(LineString([(x, -1e4), (x, 1e4)]))
            if hit.is_empty:
                continue
            y = hit.centroid.y
            sp = SCREEN_MIX[t % len(SCREEN_MIX)]
            # On the line; where the north lot's utility easement runs along it, step just
            # south of the line instead.
            for dy in (0.0, -1.5, 1.5, -3.0):
                if place(sp, x, y + dy, "lot-line screen", clear=1.0, line=f"{a}|{b}"):
                    break
    # 2. Frontage screen along CR 3635 (and CR 3640 / north end) with crape myrtles at drives.
    for label in labels:
        poly = lots[label]
        edge = bs.east_edge(poly)
        inner = edge.parallel_offset(10.0, "left") if edge.length > 0 else None
        if inner is None or inner.is_empty:
            continue
        if inner.centroid.x > edge.centroid.x:          # offset went the wrong way
            inner = edge.parallel_offset(10.0, "right")
        for k, s in enumerate(np.arange(4.0, inner.length - 2.0, 9.0)):
            pt = inner.interpolate(s)
            place(FRONT[k % len(FRONT)], pt.x, pt.y, "frontage screen")
    for p, drive in by.get("drive_front", []):
        coords = list(drive.coords)
        ax, ay = coords[1]                               # where the drive enters the lot
        bx, by_ = coords[2]
        ux, uy = bx - ax, by_ - ay
        n = np.hypot(ux, uy) or 1.0
        for side in (-1, 1):
            place("crape_myrtle", ax + ux / n * 6 - uy / n * 4.5 * side, ay + uy / n * 6 + ux / n * 4.5 * side,
                  "drive entrance")
    south = [s for s in (lots["Lot 10"].exterior,) if s is not None][0]
    for s in np.arange(0, south.length, 9.0):
        pt = south.interpolate(s)
        if pt.y < lots["Lot 10"].bounds[1] + 12:      # the CR 3640 side only
            q = Point(pt.x, pt.y + 8.0)
            place(FRONT[int(s // 9) % len(FRONT)], q.x, q.y, "CR 3640 screen")
    # 3. Water-loving trees: pond ring, creek banks, lake-side lot corners.
    ring = pond.buffer(9.0).exterior
    for k, s in enumerate(np.arange(0, ring.length, 13.0)):
        pt = ring.interpolate(s)
        place(LOWLAND[k % len(LOWLAND)], pt.x, pt.y, "pond")
    for k, s in enumerate(np.arange(10.0, creek.length, 14.0)):
        pt = creek.interpolate(s)
        a, b = creek.interpolate(max(0, s - 3)), creek.interpolate(min(creek.length, s + 3))
        nx, ny = -(b.y - a.y), b.x - a.x
        nn = np.hypot(nx, ny) or 1.0
        side = 1 if k % 2 else -1
        place(LOWLAND[(k + 1) % len(LOWLAND)], pt.x + nx / nn * 7 * side, pt.y + ny / nn * 7 * side, "creek")
    for label in labels:
        poly = lots[label]
        x0, y0, x1, y1 = poly.bounds
        for y in (y0 + 7.0, y1 - 7.0):
            row = LineString([(-1e4, y), (1e4, y)]).intersection(poly)
            if row.is_empty:
                continue
            place(LOWLAND[int(y) % len(LOWLAND)], row.bounds[0] + 9.0, y, "lake-side corners")
    reclamation(plants, lots, trees, keep_out)
    counts = {}
    for q in plants:
        counts[q["species"]] = counts.get(q["species"], 0) + 1
    (DERIVED / "planting.json").write_text(json.dumps({"schema": "lrh.planting/1", "counts": counts,
                                                         "plants": plants}, indent=0) + "\n")
    print(counts, "total", len(plants))


if __name__ == "__main__":
    main()
