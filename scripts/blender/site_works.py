"""Drainage site works in the model (switchable: `Site_Works`, terrain shape key
`Grade_SiteWorks`), from out/derived/drainage.json (scripts/drainage.py):
- the pond: basin excavated at 3:1 below its normal pool, a water surface at the pool, the
  dam / berm along its downstream side, and a rock spillway;
- the creek: a shallow defined channel (about 1 ft) from the CR 3640 corner to the lake,
  with rock check dams;
- diversion swales round each cabin site (about 10 in deep, 10 ft wide). Inside a shown
  cabin's lawn apron the swale is carved into the apron itself (cabins.py).
Trees standing in the pond and on its dam are set aside (`Vegetation_BuildSite_Site_Works`)
so the shot that shows the works also clears them.
"""

import json
import math
import random

import bpy
import numpy as np

import lrh

import shapely  # noqa: E402
from shapely.geometry import LineString, Point, Polygon  # noqa: E402

SWALE_DEPTH, SWALE_HALF = 0.25, 1.6
CREEK_DEPTH, CREEK_HALF = 0.35, 1.4


def plan():
    path = lrh.ROOT / "out/derived/drainage.json"
    return json.loads(path.read_text()) if path.is_file() else None


def clearing():
    """Where existing trees go when the works are built: the pond, its dam and rim."""
    d = plan()
    if not d:
        return None
    return shapely.union_all([Polygon(d["pond"]["polygon"]).buffer(6.0),
                              LineString(d["pond"]["dam"]).buffer(5.0)])


def swale_cut(x, y, d=None):
    """Depth (m) to cut at points (x, y) for the swales (parabolic cross-section)."""
    d = d or plan()
    if not d:
        return np.zeros(np.shape(x))
    lines = shapely.union_all([LineString(l) for ls in d["swales"].values() for l in ls])
    dist = shapely.distance(lines, shapely.points(np.asarray(x), np.asarray(y)))
    return SWALE_DEPTH * np.clip(1.0 - (dist / SWALE_HALF) ** 2, 0.0, 1.0)


def build(coll, terrain, record):
    d = plan()
    if not d:
        record("site_works", True, note="no drainage.json")
        return
    pond = Polygon(d["pond"]["polygon"])
    pool, bottom = d["pond"]["pool_m"], d["pond"]["bottom_m"]
    dam = LineString(d["pond"]["dam"])
    crest = d["pond"]["dam_crest_m"]
    creek = LineString(d["creek"])
    mesh = terrain.data
    co = np.empty(len(mesh.vertices) * 3, np.float32)
    mesh.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)
    new = co.copy()
    x, y, z = co[:, 0], co[:, 1], co[:, 2]
    pts = shapely.points(x, y)
    # Swales and creek channel.
    new[:, 2] -= swale_cut(x, y, d)
    dc = shapely.distance(creek, pts)
    in_pond = shapely.contains_xy(pond.buffer(2.0), x, y)
    if d.get("creek_swale"):          # the swale replaces the shallow channel above the pond
        in_pond = in_pond | (shapely.distance(LineString(d["creek_swale"]["line"]), pts) < 3.0)
    new[:, 2] -= np.where(in_pond, 0.0, CREEK_DEPTH * np.clip(1.0 - (dc / CREEK_HALF) ** 2, 0.0, 1.0))
    # Creek swale above the pond (trapezoid, cut only).
    if d.get("creek_swale"):
        import sys
        if str(lrh.ROOT / "scripts") not in sys.path:
            sys.path.insert(0, str(lrh.ROOT / "scripts"))
        import drainage
        new[:, 2] = np.minimum(new[:, 2], drainage.creek_swale_design(d["creek_swale"], x, y, new[:, 2]))
    # Pond basin: 3:1 side slopes from just below the pool down to the bottom.
    inside = shapely.contains_xy(pond, x, y)
    din = shapely.distance(pond.exterior, pts)
    basin = np.maximum(bottom, pool + 0.05 - din / 3.0)     # bank starts at the waterline
    new[:, 2] = np.where(inside, np.minimum(new[:, 2], basin), new[:, 2])
    # Dam / berm: crest 2 m wide, 3:1 faces.
    dd = shapely.distance(dam, pts)
    berm = crest - np.clip(dd - 1.0, 0.0, None) / 3.0
    near = (dd < 8.0) & ~inside
    new[:, 2] = np.where(near, np.maximum(new[:, 2], berm), new[:, 2])
    changed = int((np.abs(new[:, 2] - z) > 0.01).sum())
    if mesh.shape_keys is None:
        terrain.shape_key_add(name="Basis", from_mix=False)
    sk = terrain.shape_key_add(name="Grade_SiteWorks", from_mix=False)
    sk.data.foreach_set("co", new.ravel())
    sk.value = 0.0
    # Water surface at the normal pool.
    ring = list(pond.buffer(1.2).simplify(0.2).exterior.coords)[:-1]   # runs under the bank
    cx, cy = pond.centroid.x, pond.centroid.y
    verts = [(cx, cy, pool)] + [(px, py, pool) for px, py in ring]
    faces = [(0, k + 1, (k + 1) % len(ring) + 1) for k in range(len(ring))]
    wm = bpy.data.meshes.new("Pond_Water")
    wm.from_pydata(verts, [], faces)
    wm.materials.append(bpy.data.materials.get("Lake_Water"))
    wo = bpy.data.objects.new("Pond_Water", wm)
    coll.objects.link(wo)
    # Rock: spillway apron and creek check dams.
    import cabins
    m = cabins.Mesh()
    rock = cabins.stone()
    rng = random.Random(1020)

    def rocks(px, py, r, n):
        for _ in range(n):
            a, rr = rng.uniform(0, 2 * math.pi), rng.uniform(0, r)
            qx, qy = px + math.cos(a) * rr, py + math.sin(a) * rr
            g = float(new[np.argmin((x - qx) ** 2 + (y - qy) ** 2), 2])
            s = rng.uniform(0.18, 0.4)
            m.blob(qx, qy, g + s * 0.3, s, s * rng.uniform(0.7, 1.0), s * 0.6, rock, seg=7, rings=5, rng=rng)

    sx, sy = d["pond"]["spillway"]
    rocks(sx, sy, 2.5, 40)
    for s in np.arange(20.0, creek.length - 5.0, 35.0):
        p = creek.interpolate(s)
        if pond.buffer(6.0).contains(p):
            continue
        rocks(p.x, p.y, 1.4, 14)
    m.object("Site_Works_Rock", coll)
    record("site_works", True, pond_ac=d["pond"]["area_ac"], pool_ft=d["pond"]["pool_ft"],
           creek_m=round(creek.length), swales=sum(len(v) for v in d["swales"].values()),
           terrain_vertices_changed=changed)
