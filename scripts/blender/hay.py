"""Hay fields, freshly cut and baled (owner, 31 Oct 2026; switchable: `Hay`).

- Fields: the parcels' open ground (pasture or cleared in the drone cover mask), less
  the lidar trees still standing (crown + 1.5 m: the mower stays out from under them),
  roads, a 3 m strip inside the fence, and slivers a baler cannot work (< 0.25 ac).
- Yield: one cutting of North Texas grass hay, 1,500 / 2,500 / 4,000 lb per acre
  (low: late or dry cutting; mid: unfertilised pasture, typical; high: fertilised
  improved bermudagrass). Bales: 5 x 6 ft net-wrapped rounds of about 1,000 lb. The
  scene shows the mid case.
- Bales: dropped along north-south windrows WINDROW_SPACING_M apart, evenly along the
  total windrow length with jitter, axis across the windrow (as a round baler ejects
  them).
- Ground: a per-vertex `hay_field` weight on the site terrain (0-1, soft over 3 m); the
  ground material turns it into cut stubble in swath stripes when render.py sets the
  `LRH_Hay` value.
"""

import math

import bmesh
import bpy
import numpy as np
from mathutils import Matrix

import lrh
import vegetation

import shapely  # noqa: E402
from shapely.geometry import LineString, Polygon, box  # noqa: E402
from shapely.ops import unary_union  # noqa: E402

FT = 0.3048
SQM_PER_ACRE = 4046.8564224
TREE_MARGIN_M = 1.5
FENCE_INSET_M = 3.0
MIN_FIELD_ACRES = 0.25
YIELD_LB_PER_ACRE = {"low": 1500, "mid": 2500, "high": 4000}
BALE_LB = 1000
BALE_WIDTH_M, BALE_DIAMETER_M = 5 * FT, 6 * FT
WINDROW_SPACING_M = 7.3     # two 12 ft swaths raked into one windrow
CELL_M = 2.0


def fields(context, road_lines, extra_open=None):
    """Hayable ground inside the owner parcels (a Polygon or MultiPolygon)."""
    parcels = unary_union([Polygon(np.array(b["lines_local_m"][0])[:, :2])
                           for b in context["boundaries"] if b["kind"] == "owner_parcel_boundary"])
    cover = vegetation.Raster(lrh.site_cover_path())
    x0, y0, x1, y1 = parcels.bounds
    gx, gy = np.meshgrid(np.arange(x0, x1, CELL_M), np.arange(y0, y1, CELL_M))
    gx, gy = gx.ravel(), gy.ravel()
    # Majority of 3 x 3 samples per cell.
    votes = np.zeros(len(gx))
    for dx in (0.33, 1.0, 1.67):
        for dy in (0.33, 1.0, 1.67):
            cls, _ = cover.lookup(gx + dx, gy + dy)
            votes += np.isin(cls, (vegetation.PASTURE, vegetation.CLEARED))
    keep = (votes >= 5) & shapely.contains_xy(parcels, gx + CELL_M / 2, gy + CELL_M / 2)
    open_ground = shapely.union_all(shapely.box(gx[keep], gy[keep], gx[keep] + CELL_M,
                                                gy[keep] + CELL_M))
    if extra_open is not None:
        open_ground = open_ground.union(extra_open)
    lidar = np.load(lrh.ROOT / "out/derived/lidar_trees.npz")["trees"]
    standing = (lidar[:, 3] >= 4.0) & shapely.contains_xy(parcels.buffer(15.0), lidar[:, 0], lidar[:, 1])
    trees = shapely.union_all(shapely.buffer(shapely.points(lidar[standing, :2]),
                                             lidar[standing, 4] + TREE_MARGIN_M, quad_segs=6))
    roads = shapely.union_all([LineString(l).buffer(7.0) for l in road_lines])
    field = shapely.make_valid(open_ground.difference(trees).difference(roads)
                               .intersection(parcels.buffer(-FENCE_INSET_M)))
    polys = [g for g in getattr(field, "geoms", [field]) if g.geom_type in ("Polygon", "MultiPolygon")]
    field = unary_union(polys).buffer(0.01).buffer(-2.01).buffer(2.0)
    parts = [g for g in getattr(field, "geoms", [field]) if g.area >= MIN_FIELD_ACRES * SQM_PER_ACRE]
    return unary_union(parts), parcels


def yield_table(acres):
    return {case: {"lb_per_acre": lb, "tons": round(acres * lb / 2000, 1),
                   "bales": int(round(acres * lb / BALE_LB))}
            for case, lb in YIELD_LB_PER_ACRE.items()}


def bale_positions(field, count, rng):
    """(x, y, heading) of `count` bales spread evenly along north-south windrows."""
    x0, y0, x1, y1 = field.bounds
    rows = []
    for x in np.arange(x0 + WINDROW_SPACING_M / 2, x1, WINDROW_SPACING_M):
        cut = field.intersection(LineString([(x, y0 - 1), (x, y1 + 1)]))
        rows += [g for g in getattr(cut, "geoms", [cut]) if g.geom_type == "LineString" and g.length > 4]
    total = sum(r.length for r in rows)
    if not rows or count <= 0:
        return np.zeros((0, 3))
    gap = total / count
    out, carry = [], rng.uniform(0.2, 0.8) * gap
    for i, r in enumerate(rows):   # boustrophedon, as the baler drives
        s = carry
        while s < r.length:
            t = s if i % 2 == 0 else r.length - s
            p = r.interpolate(min(max(t, 1.0), r.length - 1.0))
            out.append((p.x + rng.normal(0, 0.4), p.y, rng.normal(0, math.radians(8))))
            s += gap * rng.uniform(0.85, 1.15)
        carry = s - r.length
    return np.array(out[:count])


def bale_material():
    mat = bpy.data.materials.get("Hay_Bale")
    if mat:
        return mat
    mat = bpy.data.materials.new("Hay_Bale")
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    bsdf = nodes["Principled BSDF"]
    bsdf.inputs["Roughness"].default_value = 0.92
    coord = nodes.new("ShaderNodeTexCoord")
    # Rolled layers show as rings on the flat ends: rings about the bale axis (local x).
    axis = nodes.new("ShaderNodeMapping")
    axis.inputs["Scale"].default_value = (0.0, 1.0, 1.0)
    links.new(coord.outputs["Object"], axis.inputs["Vector"])
    rings = nodes.new("ShaderNodeTexWave")
    rings.wave_type = "RINGS"
    rings.inputs["Scale"].default_value = 2.2
    rings.inputs["Distortion"].default_value = 3.0
    rings.inputs["Detail"].default_value = 4.0
    links.new(axis.outputs["Vector"], rings.inputs["Vector"])
    straw = nodes.new("ShaderNodeTexNoise")
    straw.inputs["Scale"].default_value = 28.0
    straw.inputs["Detail"].default_value = 8.0
    links.new(coord.outputs["Object"], straw.inputs["Vector"])
    mix = nodes.new("ShaderNodeMath")
    mix.operation = "MULTIPLY_ADD"
    mix.inputs[1].default_value = 0.35
    links.new(rings.outputs["Fac"], mix.inputs[0])
    links.new(straw.outputs["Fac"], mix.inputs[2])
    ramp = nodes.new("ShaderNodeValToRGB")
    # Fresh grass hay: gold with a green cast, darker between layers (linear albedo).
    ramp.color_ramp.elements[0].color = (0.16, 0.13, 0.05, 1)
    ramp.color_ramp.elements[1].color = (0.36, 0.30, 0.12, 1)
    links.new(mix.outputs[0], ramp.inputs["Fac"])
    links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
    bump = nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.6
    bump.inputs["Distance"].default_value = 0.01
    links.new(straw.outputs["Fac"], bump.inputs["Height"])
    links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    return mat


def bale_prototype(coll):
    """A 5 x 6 ft round bale, axis along local x, slightly settled; origin on the ground."""
    r, w = BALE_DIAMETER_M / 2, BALE_WIDTH_M
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, segments=40, radius1=r, radius2=r, depth=w,
                          matrix=Matrix.Rotation(math.pi / 2, 4, "Y"))
    bmesh.ops.bevel(bm, geom=[e for e in bm.edges if abs(abs(e.verts[0].co.x) - w / 2) < 1e-4
                              and abs(abs(e.verts[1].co.x) - w / 2) < 1e-4 and
                              e.verts[0].co.length > r * 0.9],
                    offset=0.12, segments=3, affect="EDGES")
    for v in bm.verts:                      # settled: a little flatter, sunk into the stubble
        v.co.z = (v.co.z + r) * 0.93 - 0.06
    mesh = bpy.data.meshes.new("Hay_Bale_Proto")
    bm.to_mesh(mesh)
    bm.free()
    for poly in mesh.polygons:
        poly.use_smooth = True
    mesh.materials.append(bale_material())
    obj = bpy.data.objects.new("Hay_Bale_Proto", mesh)
    coll.objects.link(obj)
    return obj


def build(coll, terrain, sampler, field, record, seed=20261031):
    """Bales in `coll` and the terrain's `hay_field` weight. Returns (bale x/y/z, yield table)."""
    rng = np.random.default_rng(seed)
    acres = field.area / SQM_PER_ACRE
    table = yield_table(acres)
    count = table["mid"]["bales"]
    protos = bpy.data.collections.new("Hay_Prototypes")
    coll.children.link(protos)
    protos.hide_render = True
    protos.hide_viewport = True
    proto = bale_prototype(protos)
    bales = bale_positions(field, count, rng)
    z = np.array([sampler(x, y) or lrh.POOL_M for x, y in bales[:, :2]])
    pts = np.column_stack([bales[:, 0], bales[:, 1], z])
    rot = np.column_stack([np.zeros(len(pts)), np.zeros(len(pts)), bales[:, 2]])
    vegetation.point_cloud("Hay_Bales", pts, np.ones((len(pts), 3)), rot, proto, coll)
    co = np.empty(len(terrain.data.vertices) * 3)
    terrain.data.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)
    inside = shapely.contains_xy(field, co[:, 0], co[:, 1])
    weight = np.zeros(len(co))
    edge = field.boundary
    weight[inside] = np.clip(shapely.distance(edge, shapely.points(co[inside, :2])) / 3.0, 0.0, 1.0)
    attr = terrain.data.attributes.get("hay_field") or \
        terrain.data.attributes.new("hay_field", "FLOAT", "POINT")
    attr.data.foreach_set("value", weight.astype(np.float32))
    inside_field = shapely.contains_xy(field.buffer(0.5), pts[:, 0], pts[:, 1])
    record("hay_bales", len(pts) == count and inside_field.all(), field_acres=round(acres, 2),
           fields=len(getattr(field, "geoms", [field])), bales=len(pts), bale_lb=BALE_LB,
           bale_size_ft="5 x 6", yield_cases=table, shown="mid",
           windrow_spacing_m=WINDROW_SPACING_M)
    return pts, table
