"""Lot plan features (PLAN.md Phase 2b): redlines, driveways, docks and shoreline paths.

Owner direction (14 Oct 2026): one dock per pair of lots (each pair sold as one ~4 ac
property), with the Lots 1-2 dock reached by a path from the parcels' northernmost point
east across UTRWD land to the deepest nearby water of the main lake. Dock placement is
checked against the draft LSMP (16 Oct 2025): 300 ft between docks, at most 120 ft long
and at most 1/3 of the cove width, 5 ft paths. Everything here is conceptual and subject
to a UTRWD Shoreline Use Permit; the owner must also have an occupied residence.
"""

import json
import math

import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Vector

import lrh

import shapely  # noqa: E402
from shapely.geometry import LineString, Point, Polygon  # noqa: E402
import shapely.ops  # noqa: E402
from shapely.ops import unary_union  # noqa: E402

FT = 0.3048
DRIVEWAY_TO_CENTRE = {"Lot 1", "Lot 2"}  # owner, 14-15 Oct 2026
# Lot 1 (owner, 15 Oct 2026): a secluded build site inside its tree clump. The turnaround
# sits at the centre of the lot's measured trees and the house site just west of it.
SECLUDED_LOTS = {"Lot 1"}
# Proposed east-west boundary between parcels 116505 and 135089 (owner considering a
# re-survey): y chosen so each parcel keeps its CAD acreage; lots 5 and 6 keep their areas.
PROPOSED_PARCEL_LINE_Y = -9.6
DOCK_SEPARATION_M = 300 * FT
DOCK_MAX_LENGTH_M = 120 * FT
PATH_WIDTH_M = 5 * FT
MIN_END_DEPTH_M = 1.0  # at full pool; shallow-draft boats
MIN_COVE_WIDTH_M = 60.0  # so the 1/3-width rule still allows a 20 m dock
PAIRS = [("Lot 1", "Lot 2"), ("Lot 3", "Lot 4"), ("Lot 5", "Lot 6"), ("Lot 7", "Lot 8"),
         ("Lot 9", "Lot 10")]


def material(name, rgb, roughness=0.8, emission=0.0):
    mat = bpy.data.materials.get(name)
    if mat:
        return mat
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (*rgb, 1)
    bsdf.inputs["Roughness"].default_value = roughness
    if emission:
        bsdf.inputs["Emission Color"].default_value = (*rgb, 1)
        bsdf.inputs["Emission Strength"].default_value = emission
    return mat


def strip(name, line_xy, width, sampler, lift, mat, coll, step=1.5):
    """A flat strip draped on the terrain (no fill slopes): lines, paths, driveways."""
    line = LineString(line_xy)
    n = max(2, int(math.ceil(line.length / step)) + 1)
    pts = np.array([line.interpolate(d).coords[0] for d in np.linspace(0, line.length, n)])
    tangent = np.gradient(pts, axis=0)
    tangent /= np.linalg.norm(tangent, axis=1, keepdims=True)
    normal = np.column_stack([-tangent[:, 1], tangent[:, 0]])
    verts = []
    for p, nrm in zip(pts, normal):
        for o in (-width / 2, width / 2):
            x, y = p + nrm * o
            verts.append((x, y, (sampler(x, y) or lrh.POOL_M) + lift))
    faces = [(2 * i, 2 * i + 1, 2 * i + 3, 2 * i + 2) for i in range(n - 1)]
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    obj = bpy.data.objects.new(name, mesh)
    obj.data.materials.append(mat)
    coll.objects.link(obj)
    return obj


def lots_by_label(context):
    return {lot["label"]: Polygon(lot["polygon_local_m"]) for lot in context["conceptual_lots"]["lots"]}


# --------------------------------------------------------------------------- redline

def number_material(opacity=0.45):
    """Lot numbers: white at 45% opacity, so the ground reads through (owner, 15 Oct).
    The small acreage notes use a higher opacity so they stay legible."""
    name = "Redline_Number" if opacity == 0.45 else f"Redline_Number_{round(opacity * 100)}"
    mat = bpy.data.materials.get(name)
    if mat:
        return mat
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    nodes.remove(nodes["Principled BSDF"])
    emit = nodes.new("ShaderNodeEmission")
    emit.inputs["Color"].default_value = (1, 1, 1, 1)
    emit.inputs["Strength"].default_value = 1.2
    clear = nodes.new("ShaderNodeBsdfTransparent")
    mix = nodes.new("ShaderNodeMixShader")
    mix.inputs["Fac"].default_value = opacity
    links.new(clear.outputs[0], mix.inputs[1])
    links.new(emit.outputs[0], mix.inputs[2])
    links.new(mix.outputs[0], nodes["Material Output"].inputs["Surface"])
    return mat


def build_redline(context, sampler, coll):
    red = material("Redline_Parcel", (0.85, 0.05, 0.03), 0.5, emission=1.5)
    white = material("Redline_Lot", (0.95, 0.95, 0.92), 0.5, emission=1.0)
    # Each parcel's own outline, so the shared 116505/135089 line (Lots 5/6) is drawn too.
    for b in context["boundaries"]:
        if b["kind"] == "owner_parcel_boundary":
            strip(f"Redline_Parcel_{b['prop_id']}", np.array(b["lines_local_m"][0])[:, :2], 1.6,
                  sampler, 0.35, red, coll)
    # Proposed east-west parcel boundary, dashed (6 m dash, 4 m gap).
    union = unary_union([Polygon(np.array(b["lines_local_m"][0])[:, :2])
                         for b in context["boundaries"] if b["kind"] == "owner_parcel_boundary"])
    across = LineString([(-1000, PROPOSED_PARCEL_LINE_Y), (1000, PROPOSED_PARCEL_LINE_Y)]).intersection(union)
    parts = [across] if across.geom_type == "LineString" else list(across.geoms)
    k = 0
    for part in parts:
        for d0 in np.arange(0, part.length, 10.0):
            seg = shapely.ops.substring(part, d0, min(part.length, d0 + 6.0))
            strip(f"Redline_Proposed_{k:03d}", list(seg.coords), 1.2, sampler, 0.36, red, coll)
            k += 1
    for i, line in enumerate(context["conceptual_lots"]["division_lines_local_m"]):
        strip(f"Redline_LotLine_{i}", np.array(line)[:, :2], 0.9, sampler, 0.3, white, coll)
    trees = np.load(lrh.ROOT / "out/derived/lidar_trees.npz")["trees"][:, :2]
    pads_path = lrh.ROOT / "out/derived/build_sites.geojson"  # Phase 2d plan, if present
    pads = unary_union([shapely.geometry.shape(f["geometry"]) for f in
                        json.loads(pads_path.read_text())["features"]
                        if f["properties"]["kind"] in ("pad", "septic")]) \
        if pads_path.exists() else Polygon()
    for label, poly in lots_by_label(context).items():
        # Owner (19 Oct 2026): numbers in a uniform spot at the far west (lake-side) edge,
        # a fixed distance in from the west line near the lot's centroid latitude, with the
        # lot's acreage in small type beneath. The spot may slide up to 20 m north or south
        # to clear canopy and the Phase 2d pads.
        best = None
        for dy in np.arange(-20.0, 20.1, 2.0):
            y = poly.centroid.y + dy
            row = LineString([(-1e4, y), (1e4, y)]).intersection(poly)
            if row.is_empty:
                continue
            x = row.bounds[0] + 18.0
            spots = np.array([(x, y), (x, y - 11.0)])
            if not all(poly.buffer(-3.0).contains(Point(p)) for p in spots):
                continue
            if any(pads.buffer(8.0).contains(Point(p)) for p in spots):
                continue
            clear = np.min(np.hypot(trees[:, 0, None] - spots[:, 0], trees[:, 1, None] - spots[:, 1]))
            score = min(clear, 12.0) - 0.05 * abs(dy)
            if best is None or score > best[0]:
                best = (score, x, y)
        if best is None:
            cy = poly.centroid.y
            row = LineString([(-1e4, cy), (1e4, cy)]).intersection(poly)
            best = (0, row.bounds[0] + 18.0, cy)
        _, cx, cy = best
        text = bpy.data.curves.new(f"Redline_{label}", "FONT")
        text.body = label.split()[-1]
        text.size = 16.0
        text.align_x, text.align_y = "CENTER", "CENTER"
        obj = bpy.data.objects.new(f"Redline_{label.replace(' ', '_')}_Number", text)
        obj.location = (cx, cy, (sampler(cx, cy) or lrh.POOL_M) + 0.6)
        obj.data.materials.append(number_material())
        coll.objects.link(obj)
        acres = poly.area / 4046.8564  # EPSG:6344 metres; grid-scale error is negligible here
        note = bpy.data.curves.new(f"Redline_{label}_Acres", "FONT")
        note.body = f"{acres:.2f} ac"
        note.size = 4.5
        note.align_x, note.align_y = "CENTER", "CENTER"
        nobj = bpy.data.objects.new(f"Redline_{label.replace(' ', '_')}_Acres", note)
        ay = cy - 11.0
        nobj.location = (cx, ay, (sampler(cx, ay) or lrh.POOL_M) + 0.6)
        nobj.data.materials.append(number_material(0.8))
        coll.objects.link(nobj)


# --------------------------------------------------------------------------- driveways

HOUSE_SETBACK_M = 35.0   # house site this far east of the lot's west (lake-side) line
TURN_OFFSET_M = 28.0     # turnaround centre this far east of the house site
TURN_RADIUS_M = 10.0     # gravel circle, with a grass island
ISLAND_RADIUS_M = 4.0


def house_sites(context):
    """Per lot: a conceptual house site near the lake side and a turnaround east of it,
    both on the lot's east-west centre line."""
    out = {}
    for label, poly in lots_by_label(context).items():
        yc = poly.centroid.y
        across = LineString([(-1e4, yc), (1e4, yc)]).intersection(poly)
        x0, x1 = across.bounds[0], across.bounds[2]
        house = (min(x0 + HOUSE_SETBACK_M, (x0 + x1) / 2), yc)
        turn = (min(house[0] + TURN_OFFSET_M, x1 - TURN_RADIUS_M - 5.0), yc)
        if label in SECLUDED_LOTS:
            t = np.load(lrh.ROOT / "out/derived/lidar_trees.npz")["trees"]
            inside = shapely.contains_xy(poly, t[:, 0], t[:, 1]) & (t[:, 3] > 6.0)
            cx, cy = t[inside, :2].mean(axis=0)
            turn, house = (float(cx), float(cy)), (float(cx) - 18.0, float(cy))
        out[label] = {"west": (x0, yc), "house": house, "turn": turn}
    return out


def driveway_lines(context, cr3635_lines, depth_m=32.0):
    """One driveway per lot: from the CR 3635 edge, square to the road, into the lot."""
    road = unary_union([LineString(l) for l in cr3635_lines])
    lines = {}
    for label, poly in lots_by_label(context).items():
        frontage = poly.exterior.intersection(road.buffer(25.0))
        if frontage.is_empty and label not in DRIVEWAY_TO_CENTRE:
            # Lot 1: the TxDOT centreline stops at the bend south of it (UTRWD maps show
            # the road continuing north-west); run the driveway from the mapped road end
            # to the lot's nearest point.
            near_road = road.interpolate(road.project(poly.centroid))
            corner = poly.exterior.interpolate(poly.exterior.project(near_road))
            inward = np.array(poly.centroid.coords[0]) - np.array(corner.coords[0])
            inward /= np.linalg.norm(inward)
            lines[label] = [near_road.coords[0], corner.coords[0],
                            tuple(np.array(corner.coords[0]) + inward * depth_m)]
            continue
        if label in DRIVEWAY_TO_CENTRE:
            # Owner: enter at the middle of the lot's east (road-facing) frontage, then head
            # for the lot's centre. Lot 2's frontage runs past the mapped road end, so the
            # driveway angles there from the nearest point of the road.
            ring = np.array(shapely.geometry.polygon.orient(poly).exterior.coords)
            segs = [LineString([p0, p1]) for p0, p1 in zip(ring[:-1], ring[1:])
                    if np.hypot(*(p1 - p0)) > 0 and (p1 - p0)[1] / np.hypot(*(p1 - p0)) > 0.5]
            east = shapely.ops.linemerge(shapely.MultiLineString(segs))  # CCW: faces east
            if east.geom_type != "LineString":
                east = max(east.geoms, key=lambda g: g.length)
            entry = east.interpolate(0.5, normalized=True)
            on_road = road.interpolate(road.project(entry))
            if label in SECLUDED_LOTS:
                # Follow the road's continuation along the outside of the lot's road-facing
                # edge (6 m out), then turn in through the trees to the turnaround.
                d_entry = east.project(entry)
                ahead = []
                for d in np.arange(0.0, d_entry, 4.0):
                    p0 = np.array(east.interpolate(d).coords[0])
                    p1 = np.array(east.interpolate(min(east.length, d + 1.0)).coords[0])
                    t = (p1 - p0) / max(np.hypot(*(p1 - p0)), 1e-9)
                    ahead.append(tuple(p0 + np.array([t[1], -t[0]]) * 6.0))  # outward (CCW)
                lines[label] = [road.interpolate(road.project(Point(ahead[0]))).coords[0],
                                *ahead, entry.coords[0]]
                continue
            toward = np.array(poly.representative_point().coords[0]) - np.array(entry.coords[0])
            toward /= np.linalg.norm(toward)
            lines[label] = [on_road.coords[0], entry.coords[0],
                            tuple(np.array(entry.coords[0]) + toward * (depth_m - 8.0))]
            continue
        mid = frontage.interpolate(0.5, normalized=True) if frontage.geom_type == "LineString" \
            else frontage.centroid
        on_road = road.interpolate(road.project(mid))
        inward = np.array(mid.coords[0]) - np.array(on_road.coords[0])
        inward /= np.linalg.norm(inward)
        start = np.array(on_road.coords[0]) + inward * 4.0  # road half-width + shoulder
        end = start + inward * depth_m
        lines[label] = [tuple(start), tuple(end)]
    # Every driveway continues to its lot's turnaround (owner, 15 Oct 2026).
    sites = house_sites(context)
    for label in lines:
        lines[label] = list(lines[label]) + [sites[label]["turn"]]
    return lines


def disc(name, centre, r_out, r_in, sampler, lift, mat, coll, segments=72):
    """A terrain-draped disc (r_in = 0) or ring, about 1 m between rings so it follows
    the 1 m terrain without the ground poking through."""
    cx, cy = centre
    n = max(3, int(math.ceil((r_out - r_in) / 1.0)) + 1)
    rings = list(np.linspace(max(r_in, 0.05), r_out, n))
    verts = []
    for r in rings:
        for k in range(segments):
            a = 2 * math.pi * k / segments
            x, y = cx + r * math.cos(a), cy + r * math.sin(a)
            verts.append((x, y, (sampler(x, y) or lrh.POOL_M) + lift))
    faces = [(i * segments + k, i * segments + (k + 1) % segments,
              (i + 1) * segments + (k + 1) % segments, (i + 1) * segments + k)
             for i in range(len(rings) - 1) for k in range(segments)]
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    mesh.validate()
    obj = bpy.data.objects.new(name, mesh)
    obj.data.materials.append(mat)
    coll.objects.link(obj)
    return obj


def build_driveways(lines, sampler, coll, context):
    """Driveways to a circular gravel turnaround with a mown island, per lot."""
    gravel = material("Driveway_Gravel", (0.55, 0.52, 0.45), 0.95)
    mown = material("Path_Mown_Grass", (0.09, 0.15, 0.04), 1.0)
    footprint = []
    for label, line in lines.items():
        key = label.replace(" ", "_")
        turn = line[-1]
        # Stop the drive at the turnaround's inner edge so it does not cover the island.
        last = np.array(line[-2])
        stop = np.array(turn) - (np.array(turn) - last) / np.linalg.norm(np.array(turn) - last) \
            * (ISLAND_RADIUS_M + 1.0)
        strip(f"Driveway_{key}", list(line[:-1]) + [tuple(stop)], 4.0, sampler, 0.14, gravel, coll)
        disc(f"Turnaround_{key}", turn, TURN_RADIUS_M, ISLAND_RADIUS_M, sampler, 0.15, gravel, coll)
        disc(f"Turnaround_{key}_Island", turn, ISLAND_RADIUS_M + 0.2, 0.0, sampler, 0.18, mown, coll)
        footprint += [LineString(line).buffer(3.0), Point(turn).buffer(TURN_RADIUS_M + 2.0)]
    # Open sky over drives and turnarounds; secluded lots also get a cleared house pad
    # inside the trees, so the build site reads from the air.
    open_geoms = [LineString(l) for l in lines.values()]
    sites = house_sites(context)
    for label, line in lines.items():
        open_geoms.append(Point(line[-1]).buffer(TURN_RADIUS_M - 2.0))
        if label in SECLUDED_LOTS:
            pad = Point(sites[label]["house"]).buffer(14.0)
            footprint.append(pad.buffer(1.0))
            open_geoms.append(pad)
            disc(f"House_Pad_{label.replace(' ', '_')}", sites[label]["house"], 10.0, 0.0,
                 sampler, 0.05, mown, coll)
    return unary_union(footprint), shapely.GeometryCollection(open_geoms)


# --------------------------------------------------------------------------- shoreline

SHORE_PATH_INSET_M = 4.0     # path centre this far landward of the 551 ft shoreline
SHORE_CIRCLE_RADIUS_M = 9.0  # cleared, mown circle at each lot's possible dock site


def shoreline_layout(context, water):
    """The 551 ft shoreline in front of the lots (east shore of the creek arm), a path
    just landward of it, and per lot a circle on the path and an access path from the
    lot's west line (owner, 15 Oct 2026: one-time riparian clearing agreed with UTRWD)."""
    arm = max(water.geoms, key=lambda g: g.area) if water.geom_type == "MultiPolygon" else water
    parcels = unary_union(list(lots_by_label(context).values()))
    y0, y1 = parcels.bounds[1] - 10.0, parcels.bounds[3] + 10.0
    pts = []
    for y in np.arange(y0, y1, 2.0):
        across = LineString([(-1e4, y), (1e4, y)])
        west = across.intersection(parcels)
        if west.is_empty:
            continue
        wx = west.bounds[0]
        hit = across.intersection(arm)
        xs = [g.bounds[2] for g in getattr(hit, "geoms", [hit]) if not g.is_empty and g.bounds[2] < wx]
        if xs:
            pts.append((max(xs) + SHORE_PATH_INSET_M, y))
    if len(pts) < 20:
        lrh.fail("could not trace the shoreline in front of the lots")
    pts = np.array(pts)
    k = 5  # smooth the trace over ~20 m
    pad = np.pad(pts[:, 0], k, mode="edge")
    pts[:, 0] = np.convolve(pad, np.ones(2 * k + 1) / (2 * k + 1), mode="valid")
    path = LineString(pts)
    access = {}
    for label, site in house_sites(context).items():
        yc = site["west"][1]
        centre = path.interpolate(path.project(Point(path.bounds[0], yc)))
        # nearest path point at the lot's centre-line latitude
        cand = [path.interpolate(d) for d in np.arange(0, path.length, 1.0)]
        centre = min(cand, key=lambda p: abs(p.y - yc))
        access[label] = {"circle": (centre.x, centre.y), "path": [site["west"], (centre.x, centre.y)]}
    return path, access


def build_shoreline(path, access, sampler, coll):
    mown = material("Path_Mown_Grass", (0.09, 0.15, 0.04), 1.0)
    gravel = material("Path_Gravel_Grey", (0.46, 0.46, 0.44), 0.95)
    light = material("Shore_Circle_Mown", (0.20, 0.27, 0.09), 1.0)  # fresh-mown, lighter
    strip("Shoreline_Path_Mown", list(path.coords), MOWN_CORRIDOR_M, sampler, 0.06, mown, coll)
    strip("Shoreline_Path_Gravel", list(path.coords), PATH_WIDTH_M, sampler, 0.10, gravel, coll)
    footprint, open_lines = [path.buffer(MOWN_CORRIDOR_M / 2 + 1.0)], [path]
    for label, a in access.items():
        key = label.replace(" ", "_")
        strip(f"Shore_Access_{key}_Mown", a["path"], MOWN_CORRIDOR_M, sampler, 0.06, mown, coll)
        strip(f"Shore_Access_{key}_Gravel", a["path"], PATH_WIDTH_M, sampler, 0.10, gravel, coll)
        disc(f"Shore_Circle_{key}", a["circle"], SHORE_CIRCLE_RADIUS_M, 3.0, sampler, 0.11, light, coll)
        disc(f"Shore_Circle_{key}_Pad", a["circle"], 3.2, 0.0, sampler, 0.12, gravel, coll)
        footprint += [LineString(a["path"]).buffer(MOWN_CORRIDOR_M / 2 + 1.0),
                      Point(a["circle"]).buffer(SHORE_CIRCLE_RADIUS_M + 1.0)]
        open_lines += [LineString(a["path"]), Point(a["circle"]).buffer(SHORE_CIRCLE_RADIUS_M)]
    return unary_union(footprint), shapely.GeometryCollection(open_lines)


# --------------------------------------------------------------------------- docks

def water_depth(grid, sampler, x, y):
    z = grid.heights(np.array([x]), np.array([y]))[0]
    if np.isnan(z):
        z = sampler(x, y)
    return lrh.POOL_M - z if z is not None else 0.0


def dock_candidate(base, water, grid, sampler, prefer=None):
    """Dock axis from a shoreline point into the water: toward `prefer` (a target point)
    or straight out from the shore; length capped at 120 ft and 1/3 of the cove width."""
    bx, by = base
    if prefer is not None:
        d = np.array(prefer) - np.array(base)
    else:
        probes = [(math.cos(a), math.sin(a)) for a in np.linspace(0, 2 * math.pi, 36, endpoint=False)]
        d = np.sum([np.array(p) for p in probes
                    if water.contains(Point(bx + p[0] * 15, by + p[1] * 15))], axis=0)
        if not np.any(d):
            return None
    d = d / np.linalg.norm(d)
    # Cove width along the axis: distance to the far shore.
    far = 0.0
    for s in np.arange(2.0, 600.0, 2.0):
        if not water.contains(Point(bx + d[0] * s, by + d[1] * s)):
            far = s
            break
    length = min(DOCK_MAX_LENGTH_M, far / 3.0) if far else DOCK_MAX_LENGTH_M
    end = (bx + d[0] * length, by + d[1] * length)
    return {"base": base, "dir": tuple(d), "length": length, "end": end,
            "cove_width_m": far, "end_depth_m": water_depth(grid, sampler, *end)}


def dock_layout(context, water, grid, sampler, record):
    lots = lots_by_label(context)
    parcels = unary_union([Polygon(np.array(b["lines_local_m"][0])[:, :2])
                           for b in context["boundaries"] if b["kind"] == "owner_parcel_boundary"])
    arm = max(water.geoms, key=lambda g: g.area) if water.geom_type == "MultiPolygon" else water
    # The water polygon is clipped to the 1 m site mesh; its edge there is not shoreline.
    real_shore = grid.rect.buffer(-4.0)
    shore = arm.exterior
    shore_pts = [p for p in (shore.interpolate(d).coords[0] for d in np.arange(0, shore.length, 2.0))
                 if real_shore.contains(Point(p))]
    docks = []

    # Pairs on the creek arm: candidates on the shoreline between the pair's projected
    # side lines (its north and south extent, projected west), within 120 m of the pair.
    arm_pairs = PAIRS[1:]
    cands, infeasible = [], []
    for pair in arm_pairs:
        poly = unary_union([lots[p] for p in pair])
        y0, y1 = poly.bounds[1] + 4, poly.bounds[3] - 4
        options, seen = [], []
        for x, y in shore_pts:
            if y0 <= y <= y1 and x < poly.bounds[0] and poly.distance(Point(x, y)) < 120:
                c = dock_candidate((x, y), arm, grid, sampler)
                if c:
                    seen.append(c)
                if c and c["end_depth_m"] >= MIN_END_DEPTH_M and \
                        c["cove_width_m"] >= MIN_COVE_WIDTH_M:
                    c["pair"] = pair
                    c["path_from"] = poly.exterior.interpolate(poly.exterior.project(Point(x, y))).coords[0]
                    options.append(c)
        if not options:
            infeasible.append({
                "pair": "-".join(p.split()[-1] for p in pair),
                "reason": f"no shoreline in front of the pair with a cove >= {MIN_COVE_WIDTH_M:.0f} m "
                          f"wide and >= {MIN_END_DEPTH_M} m depth at the dock end",
                "widest_cove_m": round(max((c["cove_width_m"] for c in seen), default=0.0), 1),
                "deepest_end_m": round(max((float(c["end_depth_m"]) for c in seen), default=0.0), 2)})
            continue
        cands.append(options)
    # Lots 1-2 (owner, 14 Oct 2026, second revision): the path may start anywhere east of
    # the middle of Lot 1's north-west-facing edge on its north-facing boundary, leaves
    # square to the boundary and curves (quadratic Bezier) to the shore; the dock aims at
    # the deepest water within 150 m. Best = deepest dock end, then shortest path, keeping
    # 300 ft from the reviewed Lots 3-4 site.
    lot1 = shapely.geometry.polygon.orient(lots["Lot 1"])  # counter-clockwise
    others = unary_union([poly for label, poly in lots.items() if label != "Lot 1"])
    ring = LineString(lot1.exterior.coords)
    ref = shapely.geometry.polygon.orient(lots["Lot 1"]).exterior
    nw_mid_x = -98.6  # middle of the north-west-facing edge (previous start)
    starts = []
    for d in np.arange(0, ring.length, 3.0):
        p0 = np.array(ring.interpolate(d).coords[0])
        p1 = np.array(ring.interpolate(min(ring.length, d + 1.0)).coords[0])
        t = p1 - p0
        if not np.any(t):
            continue
        n = np.array([t[1], -t[0]]) / np.linalg.norm(t)  # outward
        if n[1] > 0.2 and p0[0] >= nw_mid_x and p0[0] < 0:
            starts.append((p0, n))
    reviewed_34 = LineString([(-152.8, 136.2), (-152.8 - DOCK_MAX_LENGTH_M, 136.2)]).buffer(5.0)
    targets = {}

    def deepest_near(pt):
        key = (round(pt[0]), round(pt[1]))
        if key not in targets:
            best_t, depth = None, -1.0
            for a in np.linspace(0, 2 * math.pi, 36, endpoint=False):
                for r in (40, 80, 120, 150):
                    q = (pt[0] + math.cos(a) * r, pt[1] + math.sin(a) * r)
                    if arm.contains(Point(q)):
                        dd = water_depth(grid, sampler, *q)
                        if dd > depth:
                            best_t, depth = q, dd
            targets[key] = best_t
        return targets[key]

    best = None
    for p0, n0 in starts:
        for sx, sy in shore_pts:
            dist = math.hypot(sx - p0[0], sy - p0[1])
            if dist > 280 or sy < 150:
                continue
            ctrl = p0 + n0 * min(40.0, 0.45 * dist)
            ts = np.linspace(0, 1, 30)[:, None]
            curve = (1 - ts) ** 2 * p0 + 2 * (1 - ts) * ts * ctrl + ts ** 2 * np.array([sx, sy])
            line = LineString(curve)
            if any(arm.contains(Point(q)) for q in curve[:-2]) or line.crosses(others) or \
                    line.within(lot1):
                continue
            aim = deepest_near((sx, sy))
            if aim is None:
                continue
            c = dock_candidate((sx, sy), arm, grid, sampler, prefer=aim)
            if c is None or c["end_depth_m"] < MIN_END_DEPTH_M:
                continue
            if LineString([c["base"], c["end"]]).buffer(5.0).distance(reviewed_34) < DOCK_SEPARATION_M:
                continue
            score = float(c["end_depth_m"]) - 0.004 * line.length
            if best is None or score > best[0]:
                c["pair"], c["path_from"], c["path_line"] = PAIRS[0], tuple(p0), [tuple(q) for q in curve]
                best = (score, c)
    if best is None:
        lrh.fail("no curved Lots 1-2 dock path found")
    first = best[1]
    docks.append(first)

    # Arm pairs: search every combination of candidate sites for one that keeps 300 ft
    # between all docks, preferring the sites closest to the owner-reviewed layout.
    approved_y = {"3-4": 136.2, "5-6": 6.0, "7-8": -124.1}  # reviewed 14 Oct 2026
    shapes = [[LineString([c["base"], c["end"]]).buffer(5.0) for c in options] for options in cands]
    first_shape = LineString([first["base"], first["end"]]).buffer(5.0)
    keys = ["-".join(p.split()[-1] for p in options[0]["pair"]) for options in cands]
    order = [sorted(range(len(options)),
                    key=lambda i, o=options, k=k: abs(o[i]["base"][1] - approved_y.get(k, o[i]["base"][1])))
             for options, k in zip(cands, keys)]
    best, best_cost = None, float("inf")

    SKIP_COST = 10000.0  # leaving a pair without a dock is the last resort

    def search(level, chosen, cost):
        nonlocal best, best_cost
        if cost >= best_cost:
            return
        if level == len(cands):
            best, best_cost = list(chosen), cost
            return
        for i in order[level]:
            shape = shapes[level][i]
            if shape.distance(first_shape) < DOCK_SEPARATION_M or any(
                    j is not None and shape.distance(shapes[lv][j]) < DOCK_SEPARATION_M
                    for lv, j in enumerate(chosen)):
                continue
            c = cands[level][i]
            search(level + 1, chosen + [i],
                   cost + abs(c["base"][1] - approved_y.get(keys[level], c["base"][1])))
        search(level + 1, chosen + [None], cost + SKIP_COST)

    search(0, [], 0.0)
    for level, i in enumerate(best):
        if i is None:
            infeasible.append({"pair": keys[level],
                               "reason": "no site keeps 300 ft from the Lots 1-2 dock and the "
                                         "other docks"})
        else:
            docks.append(cands[level][i])

    # LSMP checks.
    segs = [LineString([d["base"], d["end"]]).buffer(5.0) for d in docks]  # incl. slip head
    spacing = [[round(segs[i].distance(segs[j]), 1) for j in range(len(docks))]
               for i in range(len(docks))]
    nearest = [min(v for j, v in enumerate(row) if j != i) for i, row in enumerate(spacing)]
    rows = []
    for d, near in zip(docks, nearest):
        rows.append({"pair": "-".join(p.split()[-1] for p in d["pair"]),
                     "base": [round(float(v), 1) for v in d["base"]],
                     "length_m": round(float(d["length"]), 1),
                     "length_ft": round(float(d["length"]) / FT),
                     "cove_width_m": round(float(d["cove_width_m"]), 1),
                     "end_depth_m": round(float(d["end_depth_m"]), 2),
                     "path_length_m": round(float(LineString(d.get("path_line", [d["path_from"], d["base"]])).length), 1),
                     "nearest_dock_m": float(near), "nearest_dock_ft": round(float(near) / FT),
                     "meets_300ft": bool(near >= DOCK_SEPARATION_M),
                     "meets_length": bool(d["length"] <= DOCK_MAX_LENGTH_M + 0.01 and
                                          (not d["cove_width_m"] or
                                           d["length"] <= d["cove_width_m"] / 3 + 0.01))})
    record("docks_lsmp", all(r["meets_300ft"] and r["meets_length"] for r in rows),
           docks=rows, pairs_without_boat_dock=infeasible, rule_source="UTRWD LSMP comment draft 2025-10-16, sections 4.1.1, 6.2, 6.3",
           not_checked="Shoreline Management Zone classification at each site (draft map "
                       "shows the arm's east shore and the north shore as SMZ); occupied-"
                       "residence requirement; UTRWD permit")
    return docks


def dock_mesh(name, length, coll, wood, roof):
    """Floating boat dock: walkway, a two-slip U head and a gabled metal roof. Local
    frame: +x from the shoreline out along the dock, z = 0 at the pool surface."""
    bm = bmesh.new()

    def box(x0, x1, y0, y1, z0, z1):
        bmesh.ops.create_cube(bm, size=1.0, matrix=Matrix.Translation(
            ((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2)) @ Matrix.Diagonal(
            Vector((x1 - x0, y1 - y0, z1 - z0, 1.0))))

    head = 10.0
    walk_end = max(4.0, length - head)
    box(0, walk_end, -0.9, 0.9, 0.35, 0.55)  # walkway
    box(walk_end, walk_end + 1.2, -5.2, 5.2, 0.35, 0.55)  # head cross-walk
    for y in (-5.2, -0.4, 4.4):  # three fingers around two slips
        box(walk_end + 1.2, length, y, y + 0.8, 0.35, 0.55)
    for x in (walk_end + 0.3, length - 0.3):  # roof posts
        for y in (-5.0, 5.0):
            box(x - 0.12, x + 0.12, y - 0.12, y + 0.12, 0.55, 3.4)
    wood_faces = len(bm.faces)
    # Gabled roof over the slips.
    xs, xe = walk_end - 0.3, length + 0.3
    v = [bm.verts.new(p) for p in ((xs, -5.8, 3.4), (xe, -5.8, 3.4), (xe, 0, 4.6), (xs, 0, 4.6),
                                   (xs, 5.8, 3.4), (xe, 5.8, 3.4))]
    bm.faces.new((v[0], v[1], v[2], v[3]))
    bm.faces.new((v[3], v[2], v[5], v[4]))
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    mesh.materials.append(wood)
    mesh.materials.append(roof)
    for poly in mesh.polygons:
        poly.material_index = 0 if poly.index < wood_faces else 1
    obj = bpy.data.objects.new(name, mesh)
    coll.objects.link(obj)
    return obj


def boat_channels(docks, water, timber_zone, width=40 * FT, basin=10.0):
    """Owner, 21 Oct 2026 (UTRWD one-time clearing event): one cleared boat channel,
    40 ft wide, linking every dock head along the arm and running on to the main lake's
    open water (the largest body of water outside the timbered habitat zone), plus a
    cleared basin round each dock and its slips. Returns (union polygon, [lines])."""
    if not docks:
        return Polygon(), []
    open_water = water.difference(timber_zone.buffer(5.0))
    parts = list(getattr(open_water, "geoms", [open_water]))
    lake = max(parts, key=lambda g: g.area) if parts else None
    heads = sorted((Point(d["end"]) for d in docks), key=lambda p: p.distance(lake) if lake else 0,
                   reverse=True)
    pts = [h.coords[0] for h in heads]
    if lake is not None and not lake.contains(heads[-1]):
        t = shapely.ops.nearest_points(heads[-1], lake)[1]
        # Carry the channel 25 m into the open lake.
        v = np.array(t.coords[0]) - np.array(heads[-1].coords[0])
        n = float(np.linalg.norm(v)) or 1.0
        pts += [t.coords[0], tuple(np.array(t.coords[0]) + v / n * 25.0)]
    line = LineString(pts)
    polys = [line.buffer(width / 2)] + [LineString([d["base"], d["end"]]).buffer(basin) for d in docks]
    return unary_union(polys), [line]


MOWN_CORRIDOR_M = 4.0
LOT1_DOCK_AZIMUTH_DEG = 315.0  # owner: north-west from Lot 1's north-west-facing edge


def build_docks(docks, sampler, coll):
    """Docks plus access paths: a mown-grass corridor cleared of trees, with a 5 ft grey
    gravel trail down its centre (owner, 14 Oct 2026; the LSMP allows 5 ft paths and
    6 ft vegetation trimming by permit). Returns the footprint where trees are removed."""
    wood = material("Dock_Wood", (0.21, 0.18, 0.15), 0.8)   # muted composite decking (LSMP)
    roof = material("Dock_Roof", (0.42, 0.45, 0.43), 0.45)
    mown = material("Path_Mown_Grass", (0.09, 0.15, 0.04), 1.0)
    gravel = material("Path_Gravel_Grey", (0.46, 0.46, 0.44), 0.95)
    footprints, paths = [], []
    for i, d in enumerate(docks):
        name = f"Dock_Lots_{'_'.join(p.split()[-1] for p in d['pair'])}"
        obj = dock_mesh(name, d["length"], coll, wood, roof)
        obj.location = (d["base"][0], d["base"][1], lrh.POOL_M)
        obj.rotation_euler = (0, 0, math.atan2(d["dir"][1], d["dir"][0]))
        label = "_".join(p.split()[-1] for p in d["pair"])
        line = d.get("path_line", [d["path_from"], d["base"]])
        strip(f"Path_Lots_{label}_Mown", line, MOWN_CORRIDOR_M, sampler, 0.06, mown, coll)
        strip(f"Path_Lots_{label}_Gravel", line, PATH_WIDTH_M, sampler, 0.10, gravel, coll)
        footprints.append(LineString([d["base"], d["end"]]).buffer(6.5))
        footprints.append(LineString(line).buffer(MOWN_CORRIDOR_M / 2 + 1.0))
        paths.append(LineString(line))
    # Paths are also returned so the scatter can keep crowns from closing over them.
    return unary_union(footprints), unary_union(paths)
