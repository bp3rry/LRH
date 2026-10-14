"""Tree scatter from the imagery ground-cover masks (PLAN.md Phase 1 step 4).

Positions come from out/derived/ cover rasters: the 0.6 m site raster updated with the
2026 drone-photo clearing, and the 3 m regional raster beyond it. Heights are
species-random within each species' range (canopy source (c)) until a measured canopy
height source is available. Trees are instances on point clouds via Geometry Nodes.
"""

import json
import math
import subprocess
import tempfile
from pathlib import Path

import bpy
import numpy as np

import lrh
import trees

DERIVED = lrh.ROOT / "out/derived"
WOODS, PASTURE, CLEARED = 3, 2, 4
# (max distance from site centre m, grid spacing m, crown scale boost)
TIERS = [(1500.0, 4.5, 1.0), (5000.0, 8.0, 1.3)]
SITE_CENTRE = (0.0, 35.0)
WOODS_MIX = {"post_oak": 0.45, "cedar_elm": 0.30, "red_cedar": 0.15, "bois_darc": 0.10}
EDGE_MIX = {"post_oak": 0.25, "cedar_elm": 0.15, "red_cedar": 0.35, "bois_darc": 0.25}


def read_raster(path):
    """(array, geotransform in LRH local metres) for a single-band raster."""
    with tempfile.TemporaryDirectory() as scratch:
        raw = Path(scratch) / "r.bin"
        subprocess.run(["gdal_translate", "-q", "-of", "ENVI", str(path), str(raw)], check=True)
        info = json.loads(subprocess.run(["gdalinfo", "-json", str(path)], capture_output=True,
                                         text=True, check=True).stdout)
        width, height = info["size"]
        dtype = {"Byte": np.uint8, "Float32": "<f4"}[info["bands"][0]["type"]]
        array = np.fromfile(raw, dtype).reshape(height, width)
    gt = list(info["geoTransform"])
    gt[0] -= lrh.ORIGIN_E
    gt[3] -= lrh.ORIGIN_N
    return array, gt


class Raster:
    def __init__(self, path):
        self.array, self.gt = read_raster(path)

    def lookup(self, x, y):
        col = np.floor((x - self.gt[0]) / self.gt[1]).astype(int)
        row = np.floor((y - self.gt[3]) / self.gt[5]).astype(int)
        inside = (col >= 0) & (col < self.array.shape[1]) & (row >= 0) & (row < self.array.shape[0])
        values = np.zeros(len(x), self.array.dtype)
        values[inside] = self.array[row[inside], col[inside]]
        return values, inside


def instancer_tree():
    tree = bpy.data.node_groups.get("LRH_Instance_Trees")
    if tree:
        return tree
    tree = bpy.data.node_groups.new("LRH_Instance_Trees", "GeometryNodeTree")
    tree.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    tree.interface.new_socket("Prototype", in_out="INPUT", socket_type="NodeSocketObject")
    tree.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    nodes, links = tree.nodes, tree.links
    group_in = nodes.new("NodeGroupInput")
    group_out = nodes.new("NodeGroupOutput")
    info = nodes.new("GeometryNodeObjectInfo")
    info.transform_space = "ORIGINAL"
    scale = nodes.new("GeometryNodeInputNamedAttribute")
    scale.data_type = "FLOAT_VECTOR"
    scale.inputs["Name"].default_value = "tree_scale"
    rot = nodes.new("GeometryNodeInputNamedAttribute")
    rot.data_type = "FLOAT_VECTOR"
    rot.inputs["Name"].default_value = "tree_rotation"
    to_points = nodes.new("GeometryNodeMeshToPoints")
    inst = nodes.new("GeometryNodeInstanceOnPoints")
    links.new(group_in.outputs["Geometry"], to_points.inputs["Mesh"])
    links.new(group_in.outputs["Prototype"], info.inputs["Object"])
    links.new(to_points.outputs["Points"], inst.inputs["Points"])
    links.new(info.outputs["Geometry"], inst.inputs["Instance"])
    links.new(scale.outputs["Attribute"], inst.inputs["Scale"])
    links.new(rot.outputs["Attribute"], inst.inputs["Rotation"])
    links.new(inst.outputs["Instances"], group_out.inputs["Geometry"])
    return tree


def point_cloud(name, points, scales, rotations, prototype, coll):
    mesh = bpy.data.meshes.new(name)
    mesh.vertices.add(len(points))
    mesh.vertices.foreach_set("co", points.astype(np.float32).ravel())
    for attr, values in (("tree_scale", scales), ("tree_rotation", rotations)):
        a = mesh.attributes.new(attr, "FLOAT_VECTOR", "POINT")
        a.data.foreach_set("vector", values.astype(np.float32).ravel())
    obj = bpy.data.objects.new(name, mesh)
    coll.objects.link(obj)
    mod = obj.modifiers.new("Trees", "NODES")
    mod.node_group = instancer_tree()
    socket = next(s for s in mod.node_group.interface.items_tree
                  if getattr(s, "name", "") == "Prototype")
    mod[socket.identifier] = prototype
    return obj


def candidates(rng, extent):
    """Jittered-grid candidate points per distance tier inside the terrain extent."""
    xmin, ymin, xmax, ymax = extent
    out = []
    inner = 0.0
    for outer, spacing, boost in TIERS:
        xs = np.arange(max(xmin, SITE_CENTRE[0] - outer), min(xmax, SITE_CENTRE[0] + outer), spacing)
        ys = np.arange(max(ymin, SITE_CENTRE[1] - outer), min(ymax, SITE_CENTRE[1] + outer), spacing)
        gx, gy = np.meshgrid(xs, ys)
        pts = np.column_stack([gx.ravel(), gy.ravel()])
        pts += rng.uniform(-0.45, 0.45, pts.shape) * spacing
        d = np.hypot(pts[:, 0] - SITE_CENTRE[0], pts[:, 1] - SITE_CENTRE[1])
        keep = (d >= inner) & (d < outer)
        out.append((pts[keep], spacing, boost))
        inner = outer
    return out


def scatter(coll, site_grid, sampler, road_lines, zone, record):
    """Place trees; returns counts by species and records the vegetation checks."""
    import shapely  # from .blender-site via lrh

    rng = np.random.default_rng(20261014)
    site_cover = Raster(DERIVED / "cover_site_2026.tif")
    site_frac = Raster(DERIVED / "tree_fraction_site.tif")
    regional_cover = Raster(DERIVED / "cover_regional.tif")
    regional_frac = Raster(DERIVED / "tree_fraction_regional.tif")
    road_buffer = shapely.union_all([shapely.LineString(l).buffer(7.0) for l in road_lines])

    proto_coll = bpy.data.collections.new("Tree_Prototypes")
    coll.children.link(proto_coll)
    proto_coll.hide_render = True
    proto_coll.hide_viewport = True
    prototypes = trees.make_prototypes(proto_coll)

    regional_extent = (regional_cover.gt[0], regional_cover.gt[3] + regional_cover.gt[5] *
                       regional_cover.array.shape[0],
                       regional_cover.gt[0] + regional_cover.gt[1] * regional_cover.array.shape[1],
                       regional_cover.gt[3])
    placed = {s: [] for s in trees.SPECIES}
    stats = {"candidates": 0, "woods": 0, "pasture_cedars": 0, "underwater": 0, "on_road": 0,
             "no_terrain": 0}
    for pts, spacing, boost in candidates(rng, regional_extent):
        x, y = pts[:, 0], pts[:, 1]
        stats["candidates"] += len(pts)
        cls, in_site = site_cover.lookup(x, y)
        frac, _ = site_frac.lookup(x, y)
        rcls, _ = regional_cover.lookup(x, y)
        rfrac, _ = regional_frac.lookup(x, y)
        cls = np.where(in_site, cls, rcls)
        frac = np.where(in_site, frac, rfrac).astype(float) / 255
        woods = cls == WOODS
        # Scattered cedars in pasture near the site (drone photo), never in the clearing.
        cedar = (cls == PASTURE) & (spacing < 6) & (frac > 0.15) & (rng.random(len(x)) < 0.35)
        keep = woods | cedar
        x, y, frac, cedar = x[keep], y[keep], frac[keep], cedar[keep]
        on_road = shapely.contains_xy(road_buffer, x, y)
        stats["on_road"] += int(on_road.sum())
        x, y, frac, cedar = x[~on_road], y[~on_road], frac[~on_road], cedar[~on_road]
        z = site_grid.heights(x, y)
        far = np.isnan(z)
        z[far] = [sampler(a, b) or np.nan for a, b in zip(x[far], y[far])]
        stats["no_terrain"] += int(np.isnan(z).sum())
        dry = ~np.isnan(z) & (z > lrh.POOL_M + 0.3)
        stats["underwater"] += int((~np.isnan(z) & ~dry).sum())
        x, y, z, frac, cedar = x[dry], y[dry], z[dry], frac[dry], cedar[dry]
        stats["woods"] += int((~cedar).sum())
        stats["pasture_cedars"] += int(cedar.sum())
        for i in range(len(x)):
            if cedar[i]:
                species = "red_cedar"
            else:
                mix = EDGE_MIX if frac[i] < 0.6 else WOODS_MIX
                species = rng.choice(list(mix), p=list(mix.values()))
            placed[species].append((x[i], y[i], z[i], boost))

    counts = {}
    for species, rows in placed.items():
        if not rows:
            continue
        arr = np.array(rows)
        spec = trees.SPECIES[species]
        lo, hi = spec["heights"]
        heights = rng.uniform(lo, hi, len(arr))
        variant = rng.integers(0, trees.VARIANTS, len(arr))
        for v in range(trees.VARIANTS):
            sel = variant == v
            if not sel.any():
                continue
            s = heights[sel] / spec["height"]
            widen = arr[sel, 3] * rng.uniform(0.85, 1.15, sel.sum())
            scales = np.column_stack([s * widen, s * widen * rng.uniform(0.9, 1.1, sel.sum()), s])
            rotations = np.column_stack([np.zeros(sel.sum()), np.zeros(sel.sum()),
                                         rng.uniform(0, 2 * math.pi, sel.sum())])
            pts = np.column_stack([arr[sel, 0], arr[sel, 1], arr[sel, 2] - 0.15])
            point_cloud(f"Trees_{species}_{v}", pts, scales, rotations, prototypes[species][v], coll)
        counts[species] = len(arr)

    total = sum(counts.values())
    record("trees_placed", total > 1000, total=total, by_species=counts, **stats,
           height_source="species-random ranges (canopy source c); measured heights pending")
    # Preservation zone: trees present, and no zone cell was reclassified as cleared.
    x0, y0, x1, y1 = zone.bounds
    gx, gy = np.meshgrid(np.arange(x0, x1, 2.0), np.arange(y0, y1, 2.0))
    # 1 m inset: 0.6 m cover cells straddling the parcel line belong to the parcel.
    inside = shapely.contains_xy(zone.buffer(-1.0), gx.ravel(), gy.ravel())
    zx, zy = gx.ravel()[inside], gy.ravel()[inside]
    zone_cls, _ = site_cover.lookup(zx, zy)
    zone_trees = sum(int(shapely.contains_xy(zone, np.array([r[0] for r in rows]),
                                             np.array([r[1] for r in rows])).sum())
                     for rows in placed.values() if rows)
    record("preservation_zone_wooded", (zone_cls != CLEARED).all() and zone_trees > 100,
           zone_trees=zone_trees, zone_woods_share=round(float((zone_cls == WOODS).mean()), 3),
           zone_cleared_cells=int((zone_cls == CLEARED).sum()))
    return counts
