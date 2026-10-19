"""Phase 2d build-site analysis: pad, grading, septic area and access per lot.

Owner parameters (19 Oct 2026): a 60 x 80 ft pad raised about 2 ft on balanced cut/fill,
in the road-side half of each lot, at least 100 ft from CR 3635 and 20 ft from side lot
lines. A two-storey "stilt" house: 3 BR / 1 BA upstairs, with a roughed-in 1 BR / 1 BA
apartment, boat storage and parking downstairs. Septic beside the house (not lakeward),
with a stub-out to a shared utility corridor along a north-south access road through the
lots' east-west midpoints. The main drive comes from CR 3635 to the front or side of the
house, and a second drive from the access road allows drive-through for a boat or RV.

Owner (19 Oct 2026): lots that cannot take the standard pad get a smaller lake house,
2 BR / 1 BA, on a 60 x 40 ft pad. All houses are lake-house / rustic-cabin style.

Septic sizing is a planning placeholder. Under TCEQ 30 TAC 285, 4 bedrooms (3 up + 1
down) with under 3,500 sq ft gives a design flow of about 300 gal/day. A drip field on the
area's clay soils needs roughly 4,500-5,000 sq ft; 5,000 sq ft (about 70 x 70 ft) is
reserved. The 2 BR house (about 180 gal/day) reserves 3,000 sq ft (75 x 40 ft). A licensed designer sets the real system from a soil evaluation.

Method per lot:
1. Candidate pads (long side east-west, 2 m grid) inside the setback envelope and the
   road-side half.
2. Score: higher natural ground, flatter ground (lower fill), fewer lidar trees under the
   pad, nearer the lot's centre line.
3. Pad top = mean natural ground under the pad + 0.61 m (2 ft); fill and cut on a 0.5 m
   grid with 4:1 side slopes. Cut is taken from the lot's own high spots, in the
   road-side half outside the pad, septic area and setbacks.
4. Septic area (21.3 x 21.3 m) beside the pad (north, south or east), inside the envelope.
5. Access road: the line through each lot's east-west midpoint (smoothed). Drives:
   CR 3635 to the pad front, and the pad to the access road (drive-through).

Writes out/derived/build_sites.geojson and build_sites.json (table).
Usage (Blender's Python): python3.11 scripts/build_sites.py
"""

import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT / ".blender-site"))
sys.path.insert(0, str(ROOT / "scripts"))

import numpy as np  # noqa: E402
import shapely  # noqa: E402
from shapely.geometry import LineString, Point, Polygon, box, mapping  # noqa: E402
from shapely.ops import unary_union  # noqa: E402

from kwik_ortho import Surface  # noqa: E402

FT = 0.3048
PAD = (80 * FT, 60 * FT)          # east-west, north-south (m)
SMALL_PAD = (60 * FT, 40 * FT)    # 2 BR / 1 BA lake house for constrained lots
RAISE_M = 2 * FT
SLOPE = 4.0                        # 4:1 fill slopes
ROAD_SETBACK = 100 * FT
SIDE_SETBACK = 20 * FT
SEPTIC = (100 * FT, 50 * FT)       # 5,000 sq ft drip field, long side east-west
SMALL_SEPTIC = (75 * FT, 40 * FT)  # 3,000 sq ft for 2 BR
HOUSE_TYPES = [  # tried in order; the first that fits the lot is used
    {"name": "standard", "plan": "3 BR / 1 BA up, 1 BR / 1 BA apartment + boat storage down",
     "pad": PAD, "septic": SEPTIC, "septic_sq_ft": 5000, "flow_gpd": 300},
    {"name": "small", "plan": "2 BR / 1 BA lake house",
     "pad": SMALL_PAD, "septic": SMALL_SEPTIC, "septic_sq_ft": 3000, "flow_gpd": 180},
]
DRIVE_W = 4.0
SECLUDED = {"Lot 1"}  # owner, 15 Oct 2026: the wooded build site, reached by its own drive
# Lot 10 is a corner lot between CR 3635 and relocated CR 3640: a 100 ft setback from
# both roads leaves ~57 ft of depth, under the standard pad's 60 ft, so it falls back to
# the small house (or the planned re-survey).
CORNER_LOTS = {"Lot 10"}
UTRWD_SETBACK = 50 * FT
DERIVED = ROOT / "out/derived"
CU_YD = 0.764555


def lots_and_road():
    ctx = json.loads((ROOT / "inputs/context/site-review-context-regional.json").read_text())
    lots = {l["label"]: Polygon(l["polygon_local_m"]) for l in ctx["conceptual_lots"]["lots"]}
    road = LineString(np.array([r for r in ctx["conceptual_county_roads"]["roads"]
                                if r["name"] == "CR 3635"][0]["line_local_m"])[:, :2])
    return lots, road


def east_edge(poly):
    """The lot's road-facing (east) boundary: CCW ring segments whose outward normal
    points east."""
    ring = np.array(shapely.geometry.polygon.orient(poly).exterior.coords)
    segs = [LineString([a, b]) for a, b in zip(ring[:-1], ring[1:])
            if np.hypot(*(b - a)) > 0 and (b - a)[1] / np.hypot(*(b - a)) > 0.5]
    merged = shapely.ops.linemerge(shapely.MultiLineString(segs))
    return max(merged.geoms, key=lambda g: g.length) if merged.geom_type != "LineString" else merged


def midline_x(poly, y):
    row = LineString([(-1e4, y), (1e4, y)]).intersection(poly)
    if row.is_empty:
        return None
    return (row.bounds[0] + row.bounds[2]) / 2


def grade(dtm, pad, top):
    """Fill/cut volumes (m3) for a flat pad at `top` with 4:1 slopes, on a 0.5 m grid."""
    cell = 0.5
    reach = (top - 160.0)  # generous bound; trimmed by the slope test below
    x0, y0, x1, y1 = pad.buffer(15.0).bounds
    gx, gy = np.meshgrid(np.arange(x0, x1, cell), np.arange(y0, y1, cell))
    X, Y = gx.ravel(), gy.ravel()
    ground = dtm(X, Y)
    d = shapely.distance(shapely.points(X, Y), pad)          # 0 inside the pad
    design = top - d / SLOPE                                 # sloping down away from the pad
    fill = np.clip(design - ground, 0, None)
    inside = d == 0
    cut_in_pad = np.clip(ground - top, 0, None) * inside      # high spots under the pad
    area = cell * cell
    return float(fill.sum() * area), float(cut_in_pad.sum() * area), \
        float((fill > 0.01).sum() * area)


ACCESS_HALF_M = (20 + 15) * FT / 2  # 20 ft gravel road + 15 ft utility corridor


def access_road(lots):
    """North-south access road for Lots 2-10 (Lot 1 keeps its private secluded drive).

    A gentle quadratic fitted through the east-west midpoints of Lots 2-9, then continued
    straight along its south tangent across Lot 10 to relocated CR 3640 for a second
    outlet. Owner, 19 Oct 2026: the midpoint rule is relaxed so the road stays straight and
    does not angle across the corner lot, which is wider than the others."""
    ys, xs = [], []
    for label in [f"Lot {i}" for i in range(2, 10)]:
        poly = lots[label]
        for y in np.arange(poly.bounds[1] + 4, poly.bounds[3] - 4, 4.0):
            x = midline_x(poly, y)
            if x is not None:
                ys.append(y)
                xs.append(x)
    coef = np.polyfit(ys, xs, 2)
    y_n, y_s = lots["Lot 2"].bounds[3] - 4.0, lots["Lot 9"].bounds[1]
    yy = np.arange(y_n, y_s - 0.1, -4.0)
    pts = [(float(np.polyval(coef, y)), float(y)) for y in yy]
    geo = json.loads((ROOT / "inputs/geometry/cr3640-composite-context-route-epsg6344.geojson").read_text())
    origin = json.loads((ROOT / "inputs/terrain/origin.json").read_text())["origin"]
    cr3640 = LineString(np.array(geo["features"][0]["geometry"]["coordinates"])[:, :2]
                        - [origin["easting"], origin["northing"]])
    slope = float(np.polyval(np.polyder(coef), y_s))  # dx/dy at the Lot 9/10 line
    ray = LineString([pts[-1], (pts[-1][0] - slope * 300.0, pts[-1][1] - 300.0)])
    hit = ray.intersection(cr3640)
    if hit.is_empty:
        end = cr3640.interpolate(cr3640.project(Point(pts[-1])))
    else:
        end = min(getattr(hit, "geoms", [hit]), key=lambda g: g.distance(Point(pts[-1])))
    return LineString(pts + [end.coords[0]])


def place_septic(poly, pad, cy, corridor=None, SEPTIC=SEPTIC):
    """Septic (100 x 50 ft) beside the house on its road side, north half; else south or
    north of the pad. Returns (box, description) or (None, None)."""
    inner = poly.buffer(-SIDE_SETBACK / 2, join_style="mitre")
    lot_n = inner.bounds[3]
    for sx in np.arange(pad.bounds[2] + 3.0 + SEPTIC[0] / 2, poly.bounds[2], 2.0):
        for sy in np.arange(lot_n - SEPTIC[1] / 2, cy - 1.0, -1.0):
            cand = box(sx - SEPTIC[0] / 2, sy - SEPTIC[1] / 2, sx + SEPTIC[0] / 2, sy + SEPTIC[1] / 2)
            if inner.contains(cand) and cand.bounds[1] - pad.bounds[1] > DRIVE_W + 3.0 and \
                    (corridor is None or not cand.intersects(corridor)):
                return cand, "road side of house, north half"
    cx = pad.centroid.x
    for sy in (pad.bounds[1] - 3.0 - SEPTIC[1] / 2, pad.bounds[3] + 3.0 + SEPTIC[1] / 2):
        cand = box(cx - SEPTIC[0] / 2, sy - SEPTIC[1] / 2, cx + SEPTIC[0] / 2, sy + SEPTIC[1] / 2)
        if inner.contains(cand) and (corridor is None or not cand.intersects(corridor)):
            return cand, "beside house"
    return None, None


def analyse():
    dtm = Surface(DERIVED / "lidar_dtm_1m.tif")
    trees = np.load(DERIVED / "lidar_trees.npz")["trees"]
    lots, road = lots_and_road()
    features, rows = [], []
    access = access_road(lots)
    corridor = access.buffer(ACCESS_HALF_M + 3.0)  # road + utility corridor + clearance
    for label, poly in lots.items():
        envelope = poly.buffer(-SIDE_SETBACK, join_style="mitre")
        front = east_edge(poly)
        envelope = envelope.difference(front.buffer(ROAD_SETBACK, cap_style="flat"))
        if label in CORNER_LOTS:
            south = LineString([(x, y) for x, y in poly.exterior.coords if y < poly.bounds[1] + 12])
            envelope = envelope.difference(south.buffer(ROAD_SETBACK, cap_style="flat"))
        y0, y1 = poly.bounds[1], poly.bounds[3]
        yc = (y0 + y1) / 2
        xm = midline_x(poly, yc)
        candidates, tier, htype = [], None, None
        # Tier 1: road-side half (owner preference). Tier 2: anywhere east of the access
        # road. Lot 1 (owner, 15 Oct): its secluded site in the tree clump is tier 3.
        tiers = [] if label in SECLUDED else \
            [("road-side half", 8.0), ("east of access road", 4.0), ("anywhere in envelope", None)]
        # Site tier first, then house type: a small house in the road-side half beats a
        # standard house pushed onto the low lake side.
        for tier_name, clear in tiers:
         if candidates:
            break
         for ht in HOUSE_TYPES:
          PAD, SEPTIC = ht["pad"], ht["septic"]
          htype = ht
          for cx in np.arange(poly.bounds[0], poly.bounds[2], 2.0):
            for cy in np.arange(y0, y1, 2.0):
                pad = box(cx - PAD[0] / 2, cy - PAD[1] / 2, cx + PAD[0] / 2, cy + PAD[1] / 2)
                if not envelope.contains(pad):
                    continue
                mid = midline_x(poly, cy) or xm
                if tier_name == "road-side half" and pad.bounds[0] < mid + clear:
                    continue
                if tier_name == "east of access road" and pad.bounds[0] < mid + clear:
                    continue
                if pad.intersects(corridor):
                    continue
                if place_septic(poly, pad, cy, corridor, SEPTIC)[0] is None:  # pad and septic together
                    continue
                gx, gy = np.meshgrid(np.linspace(pad.bounds[0], pad.bounds[2], 9),
                                     np.linspace(pad.bounds[1], pad.bounds[3], 7))
                z = dtm(gx.ravel(), gy.ravel())
                under = shapely.contains_xy(pad.buffer(3.0), trees[:, 0], trees[:, 1])
                candidates.append((cx, cy, pad, float(z.mean()), float(z.max() - z.min()),
                                   int(under.sum())))
          if candidates:
            tier = tier_name
            break
        if not candidates and label in SECLUDED:
            htype = HOUSE_TYPES[0]
            PAD, SEPTIC = htype["pad"], htype["septic"]
            sites = json.loads(sorted((ROOT / "out").glob("*/lot_sites.json"))[-1].read_text())
            hx, hy = sites["Lot 1"]["house"]
            for cx in np.arange(hx - 20, hx + 20.1, 2.0):
                for cy in np.arange(hy - 20, hy + 20.1, 2.0):
                    pad = box(cx - PAD[0] / 2, cy - PAD[1] / 2, cx + PAD[0] / 2, cy + PAD[1] / 2)
                    if poly.buffer(-SIDE_SETBACK, join_style="mitre").contains(pad):
                        gx, gy = np.meshgrid(np.linspace(pad.bounds[0], pad.bounds[2], 9),
                                             np.linspace(pad.bounds[1], pad.bounds[3], 7))
                        z = dtm(gx.ravel(), gy.ravel())
                        under = shapely.contains_xy(pad.buffer(3.0), trees[:, 0], trees[:, 1])
                        candidates.append((cx, cy, pad, float(z.mean()), float(z.max() - z.min()),
                                           int(under.sum())))
            tier = "secluded wooded site (inside road setback)" if candidates else None
        if not candidates:
            rows.append({"lot": label, "fits": False,
                         "reason": "corner lot: 100 ft setbacks from both CR 3635 and CR 3640 "
                                   "leave too little depth for either pad" if label in CORNER_LOTS
                                   else "no pad fits the setback envelope"})
            features.append({"type": "Feature", "properties": {"lot": label, "kind": "envelope"},
                             "geometry": mapping(envelope)})
            continue
        zmean = np.array([c[3] for c in candidates])
        relief = np.array([c[4] for c in candidates])
        ntree = np.array([c[5] for c in candidates])
        off = np.array([abs(c[1] - yc) for c in candidates])
        score = (zmean - zmean.max()) * 1.0 - relief * 0.6 - ntree * 0.4 - off * 0.03
        cx, cy, pad, z_mean, z_relief, n_tree = candidates[int(np.argmax(score))]
        top = z_mean + RAISE_M
        fill, cut_pad, fill_area = grade(dtm, pad, top)

        # Septic beside the house on its road side, in the north half of the lot; the main
        # drive passes it along the south half and reaches the house's side (owner: front
        # or side approach). Drive lies >=1.5 m inside the lot line; septic stays inside
        # the lot by half the side setback and clear of the drive by 2 m.
        septic, side = place_septic(poly, pad, cy, corridor if label != "Lot 1" else None, SEPTIC)
        # Main drive: along y_d (south half, clear of septic), from CR 3635 to the pad.
        y_lo = poly.buffer(-1.5 - DRIVE_W / 2).bounds[1]
        y_d = max(y_lo, pad.bounds[1] + DRIVE_W / 2 + 1.0)
        if septic is not None:
            y_d = min(y_d, septic.bounds[1] - 2.0 - DRIVE_W / 2)
        row_line = LineString([(pad.bounds[2], y_d), (poly.bounds[2] + 50, y_d)])
        hit = row_line.intersection(poly.exterior)
        exit_pt = min(getattr(hit, "geoms", [hit]), key=lambda g: g.distance(Point(pad.bounds[2], y_d)))
        on_road = road.interpolate(road.project(exit_pt))
        if on_road.distance(exit_pt) > 15.0:
            # The mapped CR 3635 centreline stops at the bend by Lot 2 (the road continues
            # north-west past Lot 1). Owner: individual drives, no connector along the road;
            # run a short apron straight out from the lot's own frontage instead.
            on_road = Point(exit_pt.x + 8.0, exit_pt.y)
        drive_front = LineString([on_road.coords[0], exit_pt.coords[0], (pad.bounds[2], y_d)])
        hit_access = LineString([(pad.bounds[0], cy), (pad.bounds[0] - 200, cy)]).intersection(access)
        drive_back = None
        if not hit_access.is_empty and label not in SECLUDED:
            hp = min(getattr(hit_access, "geoms", [hit_access]), key=lambda g: g.distance(Point(pad.bounds[0], cy)))
            drive_back = LineString([(pad.bounds[0], cy), hp.coords[0]])
        septic_conflict = septic is not None and drive_front.buffer(DRIVE_W / 2).intersects(septic)

        rows.append({
            "lot": label, "fits": True, "siting": tier,
            "house": htype["name"], "plan": htype["plan"],
            "pad_ft": [round(PAD[0] / FT), round(PAD[1] / FT)],
            "septic_sq_ft": htype["septic_sq_ft"], "design_flow_gpd": htype["flow_gpd"],
            "pad_centre_local_m": [round(cx, 1), round(cy, 1)],
            "natural_ground_ft": {"mean": round(z_mean / FT, 1), "relief": round(z_relief / FT, 1)},
            "pad_top_ft": round(top / FT, 1),
            "trees_on_pad": n_tree,
            "fill_cu_yd_in_place": round(fill / CU_YD), "fill_cu_yd_loose": round(fill / CU_YD * 1.15),
            "cut_on_pad_cu_yd": round(cut_pad / CU_YD),
            "graded_area_sq_ft": round(fill_area / (FT * FT)),
            "septic_placement": side,
            "septic_fits": septic is not None, "septic_clear_of_drive": not septic_conflict,
            "front_drive_ft": round(drive_front.length / FT),
            "rear_drive_to_access_road_ft": round(drive_back.length / FT) if drive_back else None,
        })
        props = {"lot": label}
        features.append({"type": "Feature", "properties": {**props, "kind": "pad", "house": htype["name"],
                                                         "top_m": round(top, 2)},
                         "geometry": mapping(pad)})
        features.append({"type": "Feature", "properties": {**props, "kind": "envelope"},
                         "geometry": mapping(envelope)})
        if septic is not None:
            features.append({"type": "Feature", "properties": {**props, "kind": "septic"},
                             "geometry": mapping(septic)})
            stub = LineString([septic.centroid.coords[0],
                               access.interpolate(access.project(septic.centroid)).coords[0]])
            features.append({"type": "Feature", "properties": {**props, "kind": "sewer_stub"},
                             "geometry": mapping(stub)})
        features.append({"type": "Feature", "properties": {**props, "kind": "drive_front"},
                         "geometry": mapping(drive_front)})
        if drive_back is not None:
            features.append({"type": "Feature", "properties": {**props, "kind": "drive_rear"},
                             "geometry": mapping(drive_back)})

    features.append({"type": "Feature", "properties": {"kind": "access_road",
                                                       "width_ft": 20, "utility_corridor_ft": 15},
                     "geometry": mapping(access)})
    DERIVED.mkdir(parents=True, exist_ok=True)
    (DERIVED / "build_sites.geojson").write_text(json.dumps(
        {"type": "FeatureCollection", "crs_note": "LRH local metres (origin.json)",
         "features": features}, indent=1) + "\n")
    report = {"parameters": {"pad_ft": [80, 60], "small_pad_ft": [60, 40], "raise_ft": 2, "fill_slope": "4:1",
                             "style": "lake house / rustic cabin (all lots)",
                             "setback_cr3635_ft": 100, "setback_sides_ft": 20,
                             "septic_area_sq_ft": 5000, "septic_basis": "4 BR (3 up + 1 down), "
                             "~300 gal/day, drip on clay; small house 2 BR ~180 gal/day, 3,000 sq ft; "
                             "placeholders pending soil evaluation"},
              "access_road_length_ft": round(access.length / FT), "lots": rows}
    (DERIVED / "build_sites.json").write_text(json.dumps(report, indent=1) + "\n")
    return report


if __name__ == "__main__":
    r = analyse()
    print(f"access road {r['access_road_length_ft']} ft")
    for row in r["lots"]:
        print(row)
