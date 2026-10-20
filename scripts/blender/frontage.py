"""CR 3635 frontage (owner, 20 Oct 2026): the existing barbed-wire fence along the
property line beside the road, with a gate at every driveway, and per drive a culvert
under the entry and a wide entry apron for a truck towing an RV or boat.

- Fence: cedar posts every 12 ft (a heavier H-brace each side of every gate and at the
  ends), four strands of barbed wire, along the parcel line wherever it runs within 14 m
  of the CR 3635 centreline. In the `Roads` collection, so it shows in every shot.
- Gates: a 20 ft clear opening per drive, two 10 ft galvanised 5-bar pipe gates, swung
  open inward. Also in `Roads`.
- Entry (in each lot's `Cabin_<lot>` collection, with its drive): the drive widened to
  24 ft at the road with flared returns, and an 18 in corrugated culvert under it at the
  roadside ditch, with pipe ends showing either side.
"""

import json
import math

import bpy
import numpy as np

import cabins
import lrh

import shapely  # noqa: E402
from shapely.geometry import LineString, Point, Polygon  # noqa: E402

FT = 0.3048
POST_SPACING = 12 * FT
GATE_OPEN = 20 * FT
APRON_W, APRON_L = 24 * FT, 9.0
CULVERT_R, CULVERT_L = 9 * 0.0254, 30 * FT


def frontage_line(parcel, road, max_d=14.0):
    ring = parcel.exterior
    keep = ring.intersection(road.buffer(max_d))
    parts = [g for g in getattr(keep, "geoms", [keep]) if g.geom_type == "LineString" and g.length > 5]
    return shapely.ops.linemerge(shapely.MultiLineString(parts)) if parts else None


def fence(m, line, gaps, sampler, wood, wire, steel):
    """Posts and four wire strands along `line`, leaving `gaps` (list of (s0, s1))."""
    runs, s = [], 0.0
    for g0, g1 in sorted(gaps):
        if g0 > s:
            runs.append((s, g0))
        s = g1
    if s < line.length:
        runs.append((s, line.length))
    posts = 0
    for a, b in runs:
        if b - a < 0.5:
            continue
        n = max(1, int(math.ceil((b - a) / POST_SPACING)))
        ss = np.linspace(a, b, n + 1)
        pts = []
        for k, t in enumerate(ss):
            p = line.interpolate(t)
            z = sampler(p.x, p.y) or lrh.POOL_M
            end = k in (0, n)
            r = 0.09 if end else 0.055
            m.cylinder(p.x, p.y, z - 0.3, z + (1.55 if end else 1.35), r, wood, n=8)
            pts.append((p.x, p.y, z))
            posts += 1
        for k in (0, n):                                       # H-brace at each run end
            j = 1 if k == 0 else n - 1
            if 0 <= j <= n and j != k:
                (x0, y0, z0), (x1, y1, z1) = pts[k], pts[j]
                m.beam((x0, y0, z0 + 1.1), (x1, y1, z1 + 1.1), 0.08, 0.08, wood)
                m.beam((x0, y0, z0 + 0.25), (x1, y1, z1 + 1.05), 0.012, 0.012, steel)
        for h in (0.35, 0.65, 0.95, 1.22):                     # barbed wire strands
            for (x0, y0, z0), (x1, y1, z1) in zip(pts[:-1], pts[1:]):
                m.beam((x0, y0, z0 + h), (x1, y1, z1 + h), 0.008, 0.008, wire)
    return posts


def gate(m, hinge, swing_dir, length, z, steel):
    """A 5-bar tube gate from `hinge` swung along unit vector swing_dir."""
    hx, hy = hinge
    ux, uy = swing_dir
    for h in (0.25, 0.47, 0.69, 0.91, 1.13):
        m.beam((hx, hy, z + h), (hx + ux * length, hy + uy * length, z + h), 0.04, 0.04, steel)
    for f in (0.0, 0.33, 0.66, 1.0):
        x, y = hx + ux * length * f, hy + uy * length * f
        m.beam((x, y, z + 0.2), (x, y, z + 1.18), 0.045, 0.045, steel)
    m.beam((hx, hy, z + 0.25), (hx + ux * length * 0.55, hy + uy * length * 0.55, z + 1.13), 0.03, 0.03, steel)


def draped(m, poly, sampler, mat, lift, cell=0.5):
    """A surface following the terrain over `poly` (grid cells touching it)."""
    x0, y0, x1, y1 = poly.bounds
    xs, ys = np.arange(x0, x1 + cell, cell), np.arange(y0, y1 + cell, cell)
    idx = {}
    slot = m._slot(mat)
    for j in range(len(ys) - 1):
        for i in range(len(xs) - 1):
            if not poly.intersects(shapely.box(xs[i], ys[j], xs[i + 1], ys[j + 1])):
                continue
            q = []
            for a, b in ((i, j), (i + 1, j), (i + 1, j + 1), (i, j + 1)):
                if (a, b) not in idx:
                    idx[(a, b)] = len(m.verts)
                    m.verts.append((float(xs[a]), float(ys[b]),
                                    (sampler(float(xs[a]), float(ys[b])) or lrh.POOL_M) + lift))
                q.append(idx[(a, b)])
            m.faces.append(tuple(q))
            m.mats.append(slot)


def entry(m, drive, road, sampler, line, gravel, conc, steel):
    """Entry apron and culvert for one drive; returns the drive's fence-crossing distance."""
    x = drive.intersection(line.buffer(0.01))
    cross = drive.interpolate(drive.project(x.centroid)) if not x.is_empty else Point(drive.coords[1])
    s_line = line.project(cross)
    a, b = line.interpolate(max(0, s_line - 1)), line.interpolate(min(line.length, s_line + 1))
    tx, ty = b.x - a.x, b.y - a.y
    tn = math.hypot(tx, ty) or 1.0
    tx, ty = tx / tn, ty / tn
    # Inward unit (along the drive, away from the road).
    d0 = drive.project(cross)
    p2 = drive.interpolate(min(drive.length, d0 + 3.0))
    ix, iy = p2.x - cross.x, p2.y - cross.y
    inn = math.hypot(ix, iy) or 1.0
    ix, iy = ix / inn, iy / inn
    # Apron: trapezoid from the road edge (24 ft + flares) to 9 m inside the line (24 ft).
    rp = road.interpolate(road.project(cross))
    ox, oy = rp.x - cross.x, rp.y - cross.y
    od = math.hypot(ox, oy)
    edge_back = max(0.0, od - 3.6)                               # road edge outward of the line
    out_x, out_y = cross.x - ix * edge_back, cross.y - iy * edge_back
    hw, flare = APRON_W / 2, APRON_W / 2 + 3.0
    poly = Polygon([(out_x + tx * flare, out_y + ty * flare), (out_x - tx * flare, out_y - ty * flare),
                    (cross.x - tx * hw + ix * APRON_L, cross.y - ty * hw + iy * APRON_L),
                    (cross.x + tx * hw + ix * APRON_L, cross.y + ty * hw + iy * APRON_L)])
    draped(m, poly, sampler, gravel, 0.09)
    # Culvert at the ditch, midway between the road edge and the fence line, along the road.
    cx, cy = cross.x - ix * edge_back * 0.5, cross.y - iy * edge_back * 0.5
    zc = (sampler(cx, cy) or lrh.POOL_M) - 0.05
    for sgn in (-1, 1):
        ex, ey = cx + tx * sgn * CULVERT_L / 2, cy + ty * sgn * CULVERT_L / 2
        m.beam((ex - tx * sgn * 0.5, ey - ty * sgn * 0.5, zc), (ex, ey, zc), CULVERT_R * 2, CULVERT_R * 2, steel)
        m.box(ex - 0.6, ey - 0.6, zc - 0.35, ex + 0.6, ey + 0.6, zc - 0.25, conc)   # splash pad
    return s_line, (tx, ty), (ix, iy), cross


def build(roads_coll, cabin_colls, parcel, roads, drives, sampler, record, gate_lines=()):
    """roads_coll: `Roads`. cabin_colls: {lot: collection}. roads: {name: centreline}; the
    fence runs along the property line beside each. drives: {lot: LineString} get gates,
    culverts and aprons; gate_lines (e.g. the shared access road) get gates only."""
    total = {"length_m": 0, "posts": 0, "gates": 0}
    for name, road in roads.items():
        line = frontage_line(parcel, road)
        if line is None or line.geom_type != "LineString":
            record(f"fence_{name}", False, note="no frontage line found")
            continue
        n = _build_one(roads_coll, cabin_colls, line, road, drives, sampler, gate_lines, name)
        for k in total:
            total[k] += n[k]
    record("frontage_fence", total["posts"] > 20, **total, gate_clear_opening_ft=20, entry_apron_ft=24)


def _build_one(roads_coll, cabin_colls, line, road, drives, sampler, gate_lines, name):
    wood = cabins.plain("Fence_Cedar_Post", (0.20, 0.15, 0.11), 0.9)
    wire = cabins.plain("Fence_Wire", (0.28, 0.27, 0.25), 0.4, 0.9)
    steel = cabins.plain("Fence_Galvanised", (0.55, 0.56, 0.57), 0.35, 0.9)
    conc = cabins.concrete()
    gravel = bpy.data.materials.get("Road_Gravel") or cabins.gravel()
    gaps, gates = [], []
    for lot, drive in drives.items():
        if drive.distance(line) > 2.0:
            continue
        em = cabins.Mesh()
        s_line, t, inward, cross = entry(em, drive, road, sampler, line, gravel, conc, steel)
        if lot in cabin_colls:
            em.object(f"Entry_{lot.replace(' ', '_')}", cabin_colls[lot])
        gaps.append((s_line - GATE_OPEN / 2, s_line + GATE_OPEN / 2))
        gates.append((s_line, t, inward))
    for gl in gate_lines:                                   # shared access road: gate only
        x = gl.intersection(line)
        if x.is_empty:
            continue
        pt = x if x.geom_type == "Point" else x.centroid
        s_line = line.project(pt)
        a, b = line.interpolate(max(0, s_line - 1)), line.interpolate(min(line.length, s_line + 1))
        tx, ty = b.x - a.x, b.y - a.y
        tn = math.hypot(tx, ty) or 1.0
        d0 = gl.project(pt)
        q = gl.interpolate(max(0.0, d0 - 3.0)) if d0 > 3.0 else gl.interpolate(d0 + 3.0)
        ix, iy = q.x - pt.x, q.y - pt.y
        inn = math.hypot(ix, iy) or 1.0
        if Point(pt.x + ix / inn, pt.y + iy / inn).distance(road) < pt.distance(road):
            ix, iy = -ix, -iy
        gaps.append((s_line - GATE_OPEN / 2, s_line + GATE_OPEN / 2))
        gates.append((s_line, (tx / tn, ty / tn), (ix / inn, iy / inn)))
    m = cabins.Mesh()
    posts = fence(m, line, gaps, sampler, wood, wire, steel)
    for s_line, (tx, ty), (ix, iy) in gates:
        for sgn in (-1, 1):
            h = line.interpolate(s_line + sgn * GATE_OPEN / 2)
            z = sampler(h.x, h.y) or lrh.POOL_M
            m.cylinder(h.x, h.y, z - 0.4, z + 1.6, 0.11, wood, n=10)          # gate posts
            ang = math.radians(12.0)                       # open, swung in, flared off the drive
            vx = ix * math.cos(ang) + tx * sgn * math.sin(ang)
            vy = iy * math.cos(ang) + ty * sgn * math.sin(ang)
            vn = math.hypot(vx, vy) or 1.0
            gate(m, (h.x, h.y), (vx / vn, vy / vn), GATE_OPEN / 2 - 0.15, z, steel)
    m.object(f"Fence_{name}", roads_coll)
    return {"length_m": round(line.length), "posts": posts, "gates": len(gates)}
