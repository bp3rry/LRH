"""Phase 2d build-site analysis: pad, grading, septic area and access per lot.

Owner parameters (19 Oct 2026): a 60 x 80 ft pad raised about 2 ft on balanced cut/fill,
in the road-side half of each lot, at least 100 ft from CR 3635 and 20 ft from side lot
lines. A two-storey "stilt" house: 3 BR / 1 BA upstairs, with a roughed-in 1 BR / 1 BA
apartment, boat storage and parking downstairs. Septic beside the house (not lakeward),
with a stub-out to a shared utility corridor along a north-south access road through the
lots' east-west midpoints. The main drive comes from CR 3635 to the front or side of the
house, and a second drive from the access road allows drive-through for a boat or RV.

Owner (19 Oct 2026, revised): every house is a lake-house / rustic cabin with 2 BR / 1 BA
upstairs and an optional 1 BR / 1 BA apartment on the ground floor, so septic is sized for
3 bedrooms. Lots that cannot take the standard 60 x 80 ft pad use a 60 x 40 ft pad. The
septic goes in front of the house (road side); a gravity check tests whether the pad gives
enough fall from a ground-floor bath to the tank, and reports any extra pad height needed.

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

sys.path.insert(0, str(ROOT / "scripts/blender"))
import grading  # noqa: E402

FT = 0.3048
PAD = (80 * FT, 60 * FT)          # east-west, north-south (m)
SMALL_PAD = (60 * FT, 40 * FT)    # 2 BR / 1 BA lake house for constrained lots
RAISE_M = 2 * FT
SLOPE = 4.0                        # 4:1 fill slopes
ROAD_SETBACK = 100 * FT
SIDE_SETBACK = 20 * FT
# 3 BR (2 up + optional 1 down) under 2,500 sq ft: about 240 gal/day (30 TAC 285); a drip
# field on clay at roughly the same loading as before needs about 4,000 sq ft.
SEPTIC = (80 * FT, 50 * FT)
PLAN = "2 BR / 1 BA up; optional 1 BR / 1 BA apartment down"
HOUSE_TYPES = [  # tried in order; the first that fits the lot is used
    {"name": "standard", "plan": PLAN, "pad": PAD, "septic": SEPTIC,
     "septic_sq_ft": 4000, "flow_gpd": 240},
    {"name": "small", "plan": PLAN, "pad": SMALL_PAD, "septic": (100 * FT, 40 * FT),  # same area, shallower
     "septic_sq_ft": 4000, "flow_gpd": 240},
]
# Gravity check, ground-floor bath to the tank (planning assumptions, for the designer):
# floor at pad top; building drain leaves 1 ft below the floor; the tank sits on undisturbed
# ground just past the 4:1 fill toe on the road side; the sewer falls 1/8 in per ft
# (minimum); a standard tank's inlet is no more than 3 ft below grade. Anything deeper is
# reported as extra pad height (or a deep-bury tank, or an ejector pump for that bath).
DRAIN_BELOW_FLOOR = 1.0 * FT
SEWER_SLOPE = 0.125 / 12
MAX_INLET_DEPTH = 3.0 * FT
TANK_OFF_PAD = RAISE_M * SLOPE + 1.0   # past the fill toe
DRIVE_W = 4.0
SECLUDED = {"Lot 1"}  # owner, 15 Oct 2026: the wooded build site, reached by its own drive
# Lot 10 is a corner lot between CR 3635 and relocated CR 3640: a 100 ft setback from
# both roads leaves ~57 ft of depth, under the standard pad's 60 ft, so it falls back to
# the small house (or the planned re-survey).
CORNER_LOTS = {"Lot 10"}
# Owner, 20 Oct 2026: Lot 10 gets a barndominium on its high corner (the old RV site of
# 1021 CR 3635), after barndominiumplans.com PL-60107 "Iris": 30 x 40 ft, one storey,
# 3 BR / 2 BA, 6:12 roof. The corner is only ~75 ft deep, so the 40 ft side runs east-west:
# covered patio on the west (lake) end, entry porch on the north side. The 100 ft road
# setbacks are waived for this lot (owner exception): 15 ft from the roads and 10 ft from
# the Lot 9 line are used here.
BARNDO_LOTS = {"Lot 10"}
BARNDO_SETBACK = 15 * FT
BARNDO_SIDE = 10 * FT
BARNDO_TYPE = {"name": "barndo", "plan": "Barndominium (Iris PL-60107) 30 x 40 ft, 3 BR / 2 BA, "
               "covered patio to the lake", "pad": (62 * FT, 36 * FT), "septic": (100 * FT, 40 * FT),
               "septic_sq_ft": 4000, "flow_gpd": 240}
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


def place_septic(poly, pad, cy, corridor=None, SEPTIC=SEPTIC, allow_west=False):
    """Septic (100 x 50 ft) beside the house on its road side, north half; else south or
    north of the pad. Returns (box, description) or (None, None)."""
    inner = poly.buffer(-SIDE_SETBACK / 2, join_style="mitre")
    lot_n = inner.bounds[3]
    # Keep clear of the covered parking slab and its drive apron (owner, 19 Oct 2026).
    carport = box(*grading.layout(pad.bounds)["carport"]).buffer(1.5)
    if corridor is None:
        corridor = carport
    else:
        corridor = corridor.union(carport)
    for sx in np.arange(pad.bounds[2] + 3.0 + SEPTIC[0] / 2, poly.bounds[2], 2.0):
        for sy in np.arange(lot_n - SEPTIC[1] / 2, pad.bounds[1], -1.0):
            cand = box(sx - SEPTIC[0] / 2, sy - SEPTIC[1] / 2, sx + SEPTIC[0] / 2, sy + SEPTIC[1] / 2)
            if inner.contains(cand) and cand.bounds[1] - pad.bounds[1] > DRIVE_W + 3.0 and \
                    (corridor is None or not cand.intersects(corridor)):
                return cand, "front (road side) of house"
    cx = pad.centroid.x
    for sy in (pad.bounds[1] - 3.0 - SEPTIC[1] / 2, pad.bounds[3] + 3.0 + SEPTIC[1] / 2):
        cand = box(cx - SEPTIC[0] / 2, sy - SEPTIC[1] / 2, cx + SEPTIC[0] / 2, sy + SEPTIC[1] / 2)
        if inner.contains(cand) and (corridor is None or not cand.intersects(corridor)):
            return cand, "beside house (front does not fit)"
    if allow_west:   # barndo on the high corner: downhill (west) of the house, gravity flow
        # Beyond the two lawn / garden terraces (2 x 9 m) and a 4 m buffer.
        for sx in np.arange(pad.bounds[0] - 22.0 - SEPTIC[0] / 2, poly.bounds[0], -2.0):
            for dy in (0.0, -6.0, 6.0, -12.0, 12.0):
                cand = box(sx - SEPTIC[0] / 2, cy + dy - SEPTIC[1] / 2, sx + SEPTIC[0] / 2, cy + dy + SEPTIC[1] / 2)
                if inner.contains(cand) and (corridor is None or not cand.intersects(corridor)):
                    return cand, "downhill (west) of house"
    return None, None


def garden_terraces(dtm, pad, T, corridor):
    """Garden / orchard terraces below the fire-pit terrace (owner, 20 Oct 2026), as far
    west as 2 m short of the access-road corridor (at most 18 m). Each step drops 1-2 ft
    toward the natural grade, so the stone walls stay low."""
    tf = grading.layout(pad.bounds)["terrace_flat"]
    ys = np.linspace(tf[1], tf[3], 9)
    east = -1e9
    for y in ys:
        hit = corridor.intersection(LineString([(-1e4, y), (1e4, y)]))
        if not hit.is_empty and hit.bounds[2] < tf[0]:
            east = max(east, hit.bounds[2])
    room = min(18.0, tf[0] - (east + 2.0)) if east > -1e8 else 18.0
    out, prev = [], T
    for b in grading.terrace_boxes(pad.bounds, room):
        gx, gy = np.meshgrid(np.linspace(b[0], b[2], 6), np.linspace(b[1], b[3], 6))
        nat = float(np.mean(dtm(gx.ravel(), gy.ravel())))
        level = float(np.clip(nat + 0.1, prev - 0.6, prev - 0.3))
        out.append([round(v, 3) for v in b] + [round(level, 3)])
        prev = level
    return out


def barndo_terraces(dtm, pad, top, corridor, n=2, width=9.0):
    """Owner, 20 Oct 2026: flat lawn terraces below the barndo's lake-side patio, like the
    cabins' - each ~30 ft east-west across the pad's north-south extent, stepping down
    toward natural grade (steps of 1-3 ft, as the corner falls steeply). The upper one is
    open lawn for recreation; the lower one a garden."""
    x0, y0, x1, y1 = pad.bounds
    ys = np.linspace(y0, y1, 9)
    east = -1e9
    for y in ys:
        hit = corridor.intersection(LineString([(-1e4, y), (1e4, y)]))
        if not hit.is_empty and hit.bounds[2] < x0:
            east = max(east, hit.bounds[2])
    out, prev = [], top
    for i in range(n):
        b = (x0 - (i + 1) * width, y0, x0 - i * width, y1)
        if b[0] < east + 2.0:
            break
        gx, gy = np.meshgrid(np.linspace(b[0], b[2], 6), np.linspace(b[1], b[3], 6))
        nat = float(np.mean(dtm(gx.ravel(), gy.ravel())))
        level = float(np.clip(nat + 0.1, prev - 0.9, prev - 0.3))
        out.append([round(v, 3) for v in b] + [round(level, 3)])
        prev = level
    return out


def flat_grade(x, y, ground, flats):
    """Finished grade for flat areas [(x0, y0, x1, y1, level)], 4:1 fill / 3:1 cut slopes."""
    best_d, edge = None, None
    for b0, b1, b2, b3, level in flats:
        d = np.hypot(x - np.clip(x, b0, b2), y - np.clip(y, b1, b3))
        if best_d is None:
            best_d, edge = d, np.full(np.shape(x), level)
        else:
            use = d < best_d
            edge = np.where(use, level, edge)
            best_d = np.minimum(d, best_d)
    out = np.where(ground > edge, np.minimum(ground, edge + best_d / grading.CUT_SLOPE),
                   np.maximum(ground, edge - best_d / grading.FILL_SLOPE))
    return np.where(best_d == 0, edge, out)


def walkout(dtm, pad, septic, corridor=None):
    """Partly buried terrace level (Hemlock walk-out) on this pad, with the gravity check
    from the downstairs bath to the septic tank.

    Terrace floor T is 6 in above the natural grade along the lake (west) wall; the road
    (east) end is backfilled BURY against a concrete back wall. With that much earth on
    the road side, a tank there would need its inlet BURY + about 1.5 ft deep, so the tank
    goes beside the house at the lake end of the south side yard, where finished grade is
    close to the floor. The bath drains to it by gravity; the tank's pump chamber doses the
    drip field in front of the house, as TCEQ drip systems require anyway. The depth a
    front tank would need is reported for comparison."""
    L = grading.layout(pad.bounds)
    ys = np.linspace(L["y0"], L["y1"], 12)
    g_w = float(np.mean(dtm(np.full(12, L["xw"]), ys)))
    g_e = float(np.mean(dtm(np.full(12, L["xe"]), ys)))
    T = g_w + 0.5 * FT
    E = T + grading.BURY
    terr = garden_terraces(dtm, pad, T, corridor) if corridor is not None else []
    bath = (L["xw"] + 4.5, L["y0"] + 2.0)

    def inlet_depth(tank):
        g = float(dtm(np.array([tank[0]]), np.array([tank[1]]))[0])
        ground = float(grading.design([tank[0]], [tank[1]], [g], pad.bounds, T, E, terr)[0])
        run = abs(tank[0] - bath[0]) + abs(tank[1] - bath[1])
        depth = max(ground - (T - DRAIN_BELOW_FLOOR - run * SEWER_SLOPE), 1.0 * FT)
        return depth, ground, run

    side = (L["xw"] + 1.5, L["ys"] - 1.6)                 # south side yard, lake end
    front = (L["xe"] + 1.5, min(max(septic.centroid.y, L["y0"] + 1.0), L["y1"] - 1.0))
    depth, ground, run = inlet_depth(side)
    front_depth, _, _ = inlet_depth(front)
    # Cut and fill against natural ground, 0.5 m grid over the pad and its slopes.
    x0, y0, x1, y1 = pad.buffer(25.0).bounds
    gx, gy = np.meshgrid(np.arange(x0, x1, 0.5), np.arange(y0, y1, 0.5))
    nat = dtm(gx.ravel(), gy.ravel())
    fin = grading.design(gx.ravel(), gy.ravel(), nat, pad.bounds, T, E, terr)
    fill = float(np.clip(fin - nat, 0, None).sum() * 0.25)
    cut = float(np.clip(nat - fin, 0, None).sum() * 0.25)
    extra = max(0.0, depth - MAX_INLET_DEPTH)
    return {
        "terrace_floor_m": round(T, 3), "terrace_floor_ft": round(T / FT, 1),
        "main_floor_ft": round((T + grading.GROUND_STOREY) / FT, 1),
        "back_grade_m": round(E, 3), "back_grade_ft": round(E / FT, 1),
        "natural_at_lake_wall_ft": round(g_w / FT, 1), "natural_at_back_wall_ft": round(g_e / FT, 1),
        "natural_fall_across_house_ft": round((g_e - g_w) / FT, 1),
        "back_wall_buried_ft": round(grading.BURY / FT, 1),
        "front_porch_above_back_yard_ft": round((T + grading.GROUND_STOREY - E) / FT, 1),
        "fill_cu_yd": round(fill / CU_YD), "cut_cu_yd": round(cut / CU_YD),
        "front_tank_inlet_depth_ft": round(front_depth / FT, 1),
        "terraces": terr,
        "terrace_levels_ft": [round(t[4] / FT, 1) for t in terr],
        "gravity": {"tank_local_m": [round(side[0], 1), round(side[1], 1)],
                    "tank_position": "beside the house, south side yard at the lake end; "
                                     "pump-dosed drip field in front",
                    "sewer_run_ft": round(run / FT),
                    "ground_at_tank_ft": round(ground / FT, 1),
                    "tank_inlet_depth_ft": round(depth / FT, 1),
                    "ground_floor_bath_ok": extra == 0.0,
                    "extra_pad_height_ft": round(extra / FT, 1)},
    }


EASEMENT_W = 20 * FT          # private utility easement, house to the lot's west edge
TRENCH_SEP = 10 * FT          # potable water kept 10 ft from effluent lines (two trenches)
REC_R = 20 * FT               # recreation / picnic / rough-camp site at the west edge
OSSF_LINE_SETBACK = 10 * FT   # drip field from lot lines, water lines and the rec site (planning)


def utrwd_edge(lots):
    """The parcel's lake-side boundary (UTRWD land beyond it): parcel exterior segments
    west of each lot's east-west midpoint."""
    ctx = json.loads((ROOT / "inputs/context/site-review-context-regional.json").read_text())
    parcel = shapely.union_all([Polygon(np.array(b["lines_local_m"][0])[:, :2])
                                for b in ctx["boundaries"] if b["kind"] == "owner_parcel_boundary"])
    west = shapely.union_all([box(p.bounds[0] - 50, p.bounds[1] - 1, midline_x(p, p.centroid.y) or
                                  p.centroid.x, p.bounds[3] + 1) for p in lots.values()])
    return parcel.exterior.intersection(west)


def lake_option(dtm, label, poly, pad, walk, corridor, edge):
    """Option B (owner, 19 Oct 2026): the drip field on the lake-side acre, and a private
    utility easement from the house to the lot's west edge with a recreation site there.

    - Easement: 20 ft wide, from the treatment tank (south side yard) south to the lot's
      south line, then west along it (centre 4 m inside) to the west edge, keeping the
      lake-side acre in one piece. Two trenches 10 ft apart: (1) the gravity effluent line from the
      treatment tank down to a pump (dose) tank beside the field, with the pump's power
      and alarm conduit; (2) PEX water, a power circuit and a spare conduit to a utility
      pedestal (frost-free hydrant, outlets) at the recreation site.
    - Recreation site: a 40 ft circle at the west edge (picnic, rough camping).
    - Drip field: 4,000 sq ft on the lowest ground of the lake-side acre that keeps 50 ft
      from UTRWD land (draft LSMP), 10 ft from lot lines, the easement and the rec site,
      and stays west of the access road corridor and clear of the house apron.
    Returns (features, row)."""
    tank = walk["gravity"]["tank_local_m"]

    def south_y(x):
        col = LineString([(x, -1e4), (x, 1e4)]).intersection(poly)
        return None if col.is_empty else col.bounds[1] + EASEMENT_W / 2 + 1.0

    pts = [tuple(tank)]
    x = tank[0]
    while True:
        y = south_y(x)
        if y is None or not poly.buffer(-1.0).contains(Point(x - 3.0, y)):
            break
        pts.append((x, y))
        x -= 5.0
    if len(pts) < 3:
        return [], {"possible": False, "reason": "no easement route to the west edge"}
    ped = pts[-1]
    easement_line = LineString(pts).simplify(0.5)
    easement = easement_line.buffer(EASEMENT_W / 2, cap_style="flat").intersection(poly)
    ty = ped[1]
    rec = Point(ped[0] + REC_R, ty + REC_R * 0.6)
    dpath = DERIVED / "drainage.json"                     # keep the rec site out of the pond
    if dpath.exists() and json.loads(dpath.read_text()).get("pond"):
        pond_poly = Polygon(json.loads(dpath.read_text())["pond"]["polygon"]).buffer(4.0)
        while rec.buffer(REC_R).intersects(pond_poly) and rec.x < poly.bounds[2]:
            rec = Point(rec.x + 2.0, rec.y)
    rec_area = rec.buffer(REC_R).intersection(poly)
    lake_edge = edge.intersection(poly.buffer(1.0))
    allowed = poly.buffer(-OSSF_LINE_SETBACK, join_style="mitre")
    if not lake_edge.is_empty:
        allowed = allowed.difference(lake_edge.buffer(50 * FT))
    mid = midline_x(poly, poly.centroid.y) or poly.centroid.x
    allowed = (allowed.intersection(box(poly.bounds[0] - 1, poly.bounds[1] - 1, mid, poly.bounds[3] + 1))
               .difference(corridor.buffer(OSSF_LINE_SETBACK))
               .difference(easement.buffer(OSSF_LINE_SETBACK))
               .difference(rec_area.buffer(OSSF_LINE_SETBACK))
               .difference(pad.buffer(9.0))
               .difference(shapely.union_all([box(*t[:4]) for t in walk.get("terraces", [])] or
                                             [Polygon()]).buffer(3.0)))
    # Keep drip fields out of the creek corridor and away from the pond (drainage.py).
    dpath = DERIVED / "drainage.json"
    if dpath.exists():
        dr = json.loads(dpath.read_text())
        if dr.get("creek"):
            allowed = allowed.difference(LineString(dr["creek"]).buffer(15.0))
        if dr.get("pond"):
            allowed = allowed.difference(Polygon(dr["pond"]["polygon"]).buffer(20.0))
    # Keep the lot number and acreage label (lotplan.build_redline: 18 m in from the west
    # line near the centroid latitude) readable on the plan.
    cy_l = poly.centroid.y
    row = LineString([(-1e4, cy_l), (1e4, cy_l)]).intersection(poly)
    if not row.is_empty:
        allowed = allowed.difference(box(row.bounds[0] + 6, cy_l - 16, row.bounds[0] + 32, cy_l + 10))
    W, D = SEPTIC
    best = None
    x0, y0, x1, y1 = allowed.bounds if not allowed.is_empty else (0, 0, 0, 0)
    for orient in ((W, D), (D, W)):
        for fx in np.arange(x0 + orient[0] / 2, x1 - orient[0] / 2 + 0.1, 2.0):
            for fy in np.arange(y0 + orient[1] / 2, y1 - orient[1] / 2 + 0.1, 2.0):
                f = box(fx - orient[0] / 2, fy - orient[1] / 2, fx + orient[0] / 2, fy + orient[1] / 2)
                if not allowed.contains(f):
                    continue
                gx, gy = np.meshgrid(np.linspace(f.bounds[0], f.bounds[2], 8),
                                     np.linspace(f.bounds[1], f.bounds[3], 6))
                z = dtm(gx.ravel(), gy.ravel())
                if best is None or z.max() < best[1]:
                    best = (f, float(z.max()), float(z.mean()))
    feats = [("easement", easement, {"width_ft": 20}),
             ("trench_effluent", easement_line.parallel_offset(TRENCH_SEP / 2, "left"), {}),
             ("trench_water_power", easement_line.parallel_offset(TRENCH_SEP / 2, "right"), {}),
             ("pedestal", Point(ped), {}), ("rec_site", rec_area, {})]
    row = {"possible": best is not None, "easement_ft": round(easement_line.length / FT),
           "pedestal_local_m": [round(ped[0], 1), round(ped[1], 1)]}
    if best is None:
        row["reason"] = "no 4,000 sq ft field fits the lake-side acre under the setbacks"
        return feats, row
    field, zmax, zmean = best
    # Dose tank on the field's side nearest the easement; the effluent line tees off there.
    near = shapely.ops.nearest_points(field, easement_line)
    dose = (near[0].x, near[0].y)
    tee = (near[1].x, near[1].y)
    outlet = walk["gravity"]["ground_at_tank_ft"] * FT - walk["gravity"]["tank_inlet_depth_ft"] * FT - 0.25 * FT
    run = easement_line.project(Point(tee)) + math.dist(tee, dose)
    fall = outlet - (float(dtm(np.array([dose[0]]), np.array([dose[1]]))[0]) - 3.0 * FT)
    feats += [("drip_lake", field, {}), ("dose_tank", Point(dose), {}),
              ("effluent_lateral", LineString([tee, dose]), {})]
    row.update({
        "field_ground_ft": {"mean": round(zmean / FT, 1), "high": round(zmax / FT, 1)},
        "treatment_tank_outlet_ft": round(outlet / FT, 1),
        "fall_tank_outlet_to_field_high_ft": round((outlet - zmax) / FT, 1),
        "gravity_to_dose_tank": bool(fall > run * SEWER_SLOPE),
        "effluent_line_ft": round(run / FT),
        "field_to_utrwd_ft": round(field.distance(lake_edge) / FT) if not lake_edge.is_empty else None,
    })
    return feats, row


TURN_R, TURN_LANE = 9.0, 4.0     # circle-drive centreline radius and lane width (60 ft loop)


def barndo_carport(pad):
    """Lot 10 covered parking (owner, 20 Oct 2026): 22 x 24 ft, east of the barndo's entry
    porch at pad level, where the drive arrives."""
    x0, y0, x1, y1 = pad.bounds
    cy = (y0 + y1) / 2
    return (x1 + 0.5, cy - 12 * FT, x1 + 0.5 + 22 * FT, cy + 12 * FT)


def turnaround(poly, drive, septic, pad, carport, corridor):
    """A gravel circle drive near the house (owner, 20 Oct 2026): a loop round a grass
    island on the drive, short of the carport, big enough to swing a pickup with a boat
    trailer round. Returns the loop's centre point, or None if no spot fits."""
    end = Point(drive.coords[-1])
    rev = LineString(list(drive.coords)[::-1])
    blocked = shapely.union_all([box(*carport).buffer(1.0), pad.buffer(1.0)] +
                                ([septic.buffer(2.0)] if septic is not None else []) +
                                [corridor])
    room = poly.buffer(-1.5)
    # Largest loop that fits: 60 ft, 50 ft, then 42 ft centreline diameter.
    for r in (TURN_R, 7.6, 6.4):
        for s in np.arange(r + 2.0, min(50.0, rev.length - r), 1.0):
            p = rev.interpolate(s)
            a, b = rev.interpolate(max(0, s - 1)), rev.interpolate(s + 1)
            nx, ny = -(b.y - a.y), b.x - a.x
            n = float(np.hypot(nx, ny)) or 1.0
            for off in (0.0, r * 0.6, -r * 0.6, r, -r):
                c = Point(p.x + nx / n * off, p.y + ny / n * off)
                ring = c.buffer(r + TURN_LANE / 2)
                if room.contains(ring) and not ring.intersects(blocked):
                    return c, r
    # Fallback: a semicircular gravel turning bulb off one side of the drive.
    for r in (9.0, 7.6, 6.4):
        for s in np.arange(r + 1.0, min(50.0, rev.length - r), 1.0):
            p = rev.interpolate(s)
            a, b = rev.interpolate(max(0, s - 1)), rev.interpolate(s + 1)
            ux, uy = (b.x - a.x), (b.y - a.y)
            n = float(np.hypot(ux, uy)) or 1.0
            ux, uy = ux / n, uy / n
            for side in (1, -1):
                nx, ny = -uy * side, ux * side
                half = Polygon([(p.x - ux * 30, p.y - uy * 30), (p.x + ux * 30, p.y + uy * 30),
                                (p.x + ux * 30 + nx * 30, p.y + uy * 30 + ny * 30),
                                (p.x - ux * 30 + nx * 30, p.y - uy * 30 + ny * 30)])
                bulb = p.buffer(r).intersection(half)
                if room.contains(bulb) and not bulb.intersects(blocked):
                    return bulb, -r
    return None, None


def analyse():
    dtm = Surface(DERIVED / "lidar_dtm_1m.tif")
    trees = np.load(DERIVED / "lidar_trees.npz")["trees"]
    lots, road = lots_and_road()
    features, rows = [], []
    access = access_road(lots)
    corridor = access.buffer(ACCESS_HALF_M + 3.0)  # road + utility corridor + clearance
    edge = utrwd_edge(lots)
    for label, poly in lots.items():
        envelope = poly.buffer(-SIDE_SETBACK, join_style="mitre")
        front = east_edge(poly)
        envelope = envelope.difference(front.buffer(ROAD_SETBACK, cap_style="flat"))
        if label in BARNDO_LOTS:
            envelope = poly.buffer(-BARNDO_SIDE, join_style="mitre").difference(
                front.buffer(BARNDO_SETBACK, cap_style="flat"))
            south = LineString([(x, y) for x, y in poly.exterior.coords if y < poly.bounds[1] + 12])
            envelope = envelope.difference(south.buffer(BARNDO_SETBACK, cap_style="flat"))
        elif label in CORNER_LOTS:
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
         for ht in ([BARNDO_TYPE] if label in BARNDO_LOTS else HOUSE_TYPES):
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
                if place_septic(poly, pad, cy, corridor, SEPTIC, label in BARNDO_LOTS)[0] is None:  # pad and septic together
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
        # The barndo keeps the oaks round its corner: trees weigh more there.
        tree_w = 2.0 if label in BARNDO_LOTS else 0.4
        off_w = 0.0 if label in BARNDO_LOTS else 0.03
        score = (zmean - zmean.max()) * 1.0 - relief * 0.6 - ntree * tree_w - off * off_w
        cx, cy, pad, z_mean, z_relief, n_tree = candidates[int(np.argmax(score))]
        top = z_mean + RAISE_M
        fill, cut_pad, fill_area = grade(dtm, pad, top)

        # Septic beside the house on its road side, in the north half of the lot; the main
        # drive passes it along the south half and reaches the house's side (owner: front
        # or side approach). Drive lies >=1.5 m inside the lot line; septic stays inside
        # the lot by half the side setback and clear of the drive by 2 m.
        septic, side = place_septic(poly, pad, cy, corridor if label != "Lot 1" else None, SEPTIC,
                                    label in BARNDO_LOTS)
        # Main drive: along y_d (south half, clear of septic), from CR 3635 to the pad.
        # Main drive ends at the covered parking slab's road-side face (owner, 19 Oct 2026).
        cp = grading.layout(pad.bounds)["carport"] if htype["name"] != "barndo" else \
            barndo_carport(pad)
        y_lo = poly.buffer(-1.5 - DRIVE_W / 2).bounds[1]
        y_d = max(y_lo, (cp[1] + cp[3]) / 2)
        if septic is not None and septic.bounds[0] > pad.bounds[2]:     # front field only
            y_d = min(y_d, septic.bounds[1] - 2.0 - DRIVE_W / 2)
        row_line = LineString([(cp[2], y_d), (poly.bounds[2] + 50, y_d)])
        hit = row_line.intersection(poly.exterior)
        exit_pt = min(getattr(hit, "geoms", [hit]), key=lambda g: g.distance(Point(cp[2], y_d)))
        on_road = road.interpolate(road.project(exit_pt))
        if on_road.distance(exit_pt) > 15.0:
            # The mapped CR 3635 centreline stops at the bend by Lot 2 (the road continues
            # north-west past Lot 1). Owner: individual drives, no connector along the road;
            # run a short apron straight out from the lot's own frontage instead.
            on_road = Point(exit_pt.x + 8.0, exit_pt.y)
        drive_front = LineString([on_road.coords[0], exit_pt.coords[0], (cp[2], y_d)])
        turn, turn_r = turnaround(poly, drive_front, septic, pad, cp, corridor)
        hit_access = LineString([(pad.bounds[0], cy), (pad.bounds[0] - 200, cy)]).intersection(access)
        drive_back = None
        if not hit_access.is_empty and label not in SECLUDED:
            hp = min(getattr(hit_access, "geoms", [hit_access]), key=lambda g: g.distance(Point(pad.bounds[0], cy)))
            drive_back = LineString([(pad.bounds[0], cy), hp.coords[0]])
        septic_conflict = septic is not None and drive_front.buffer(DRIVE_W / 2).intersects(septic)

        walk = walkout(dtm, pad, septic, corridor) if septic is not None and htype["name"] != "barndo" \
            else None
        barndo_terr, barndo_grading = [], None
        if htype["name"] == "barndo":
            barndo_terr = barndo_terraces(dtm, pad, top, corridor)
            flats = [list(pad.bounds) + [top]] + barndo_terr
            area = shapely.union_all([pad] + [box(*t[:4]) for t in barndo_terr]).buffer(25.0)
            gx, gy = np.meshgrid(np.arange(area.bounds[0], area.bounds[2], 0.5),
                                 np.arange(area.bounds[1], area.bounds[3], 0.5))
            nat = dtm(gx.ravel(), gy.ravel())
            fin = flat_grade(gx.ravel(), gy.ravel(), nat, flats)
            barndo_grading = {
                "pad_top_ft": round(top / FT, 1),
                "terraces": barndo_terr, "terrace_levels_ft": [round(t[4] / FT, 1) for t in barndo_terr],
                "terrace_uses": ["lawn (recreation)", "garden"][:len(barndo_terr)],
                "fill_cu_yd": round(float(np.clip(fin - nat, 0, None).sum() * 0.25) / CU_YD),
                "cut_cu_yd": round(float(np.clip(nat - fin, 0, None).sum() * 0.25) / CU_YD)}
        gravity = walk["gravity"] if walk else None
        option_b, lake = lake_option(dtm, label, poly, pad, walk, corridor, edge) if walk else ([], None)

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
            "gravity_ground_floor_bath": gravity,
            "walkout": {k: v for k, v in walk.items() if k != "gravity"} if walk else None,
            "barndo_grading": barndo_grading,
            "septic_fits": septic is not None, "septic_clear_of_drive": not septic_conflict,
            "front_drive_ft": round(drive_front.length / FT),
            "rear_drive_to_access_road_ft": round(drive_back.length / FT) if drive_back else None,
            "turnaround": None if turn is None else
                (f"circle drive {round(2 * turn_r / FT)} ft" if turn_r > 0 else
                 f"semicircular bulb {round(2 * -turn_r / FT)} ft"),
            "option_b_lake_field": lake,
        })
        props = {"lot": label}
        features.append({"type": "Feature", "properties": {**props, "kind": "pad", "house": htype["name"],
                                                         "top_m": round(top, 2),
                                                         **({"terrace_floor_m": walk["terrace_floor_m"],
                                                             "back_grade_m": walk["back_grade_m"],
                                                             "terraces": walk["terraces"]}
                                                            if walk else {}),
                                                         **({"terraces": barndo_terr} if barndo_terr else {})},
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
            if gravity is not None:
                features.append({"type": "Feature", "properties": {
                    **props, "kind": "septic_tank", "inlet_depth_ft": gravity["tank_inlet_depth_ft"]},
                    "geometry": mapping(Point(gravity["tank_local_m"]))})
        if turn is not None:
            features.append({"type": "Feature", "properties": {
                **props, "kind": "turnaround" if turn_r > 0 else "turn_bulb",
                "radius_m": abs(turn_r), "lane_m": TURN_LANE}, "geometry": mapping(turn)})
        if htype["name"] == "barndo":
            features.append({"type": "Feature", "properties": {**props, "kind": "carport"},
                             "geometry": mapping(box(*cp))})
        features.append({"type": "Feature", "properties": {**props, "kind": "drive_front"},
                         "geometry": mapping(drive_front)})
        if drive_back is not None:
            features.append({"type": "Feature", "properties": {**props, "kind": "drive_rear"},
                             "geometry": mapping(drive_back)})
        for kind, geom, extra in option_b:
            features.append({"type": "Feature", "properties": {**props, "kind": kind, "option": "B", **extra},
                             "geometry": mapping(geom)})

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
                             "septic_area_sq_ft": 4000, "septic_basis": "3 BR (2 up + optional 1 down), "
                             "~240 gal/day, drip on clay; placeholder pending soil evaluation",
                             "gravity": "drain 1 ft below floor, 1/8 in/ft, tank past fill toe, "
                             "max standard inlet depth 3 ft"},
              "access_road_length_ft": round(access.length / FT), "lots": rows}
    (DERIVED / "build_sites.json").write_text(json.dumps(report, indent=1) + "\n")
    return report


if __name__ == "__main__":
    r = analyse()
    print(f"access road {r['access_road_length_ft']} ft")
    for row in r["lots"]:
        print(row)
