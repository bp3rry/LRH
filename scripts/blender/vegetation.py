"""Trees for the baseline (PLAN.md Phase 1 step 4).

Inside the StratMap 2025 lidar coverage (canopy source (a)), every tree is a measured
one from scripts/lidar_trees.py: position, height and crown radius, with red cedar where
the leaf-off evergreen score is high. The drone photo (11 Aug 2023) predates the lidar
flight (9 Dec 2025), so a lidar object on ground the photo already shows cleared, far
from any woods, cannot be a standing tree: it is a brush pile and is omitted. Lidar
objects on roads or below pool are dropped too. Outside the coverage, trees are scattered
from the imagery cover masks with species-random heights (canopy source (c)).
Trees are instances on point clouds via Geometry Nodes, never realised geometry.
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
DECIDUOUS_MIX = {"post_oak": 0.53, "cedar_elm": 0.35, "bois_darc": 0.12}
EVERGREEN_SCORE_MIN = 0.8  # leaf-off lidar: dense crowns are red cedar


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


def flooded_timber(rng, lidar_rows, prototypes, snags, proto_coll, record):
    """Lidar trees below pool inside the Fish and Wildlife Habitat zone stay standing in
    the water. Three stages are built as separate top-level collections so shots can
    choose: leafy (first season after flooding), dying (a season or two: about half
    dead, the rest thin and browning) and snags (long term: permanently flooded oaks and
    elms die within a few seasons). Spanish moss on about a third of the dead trees is a
    fourth, optional collection; it lines up with the snags in both the dying and snags
    stages."""
    scene = bpy.context.scene
    made = {}
    for name in ("Flooded_Timber_Leafy", "Flooded_Timber_Dying", "Flooded_Timber_Snags",
                 "Spanish_Moss"):
        coll = bpy.data.collections.new(name)
        scene.collection.children.link(coll)
        made[name] = coll
    rows = np.array(lidar_rows) if lidar_rows else np.zeros((0, 6))
    if len(rows):
        x, y, z, height, crown, evergreen = rows.T
        n = len(x)
        rot = np.column_stack([np.zeros(n), np.zeros(n), rng.uniform(0, 2 * math.pi, n)])
        pts = np.column_stack([x, y, z - 0.15])
        cedar = evergreen >= EVERGREEN_SCORE_MIN
        variant = rng.integers(0, trees.VARIANTS, n)
        # Owner, 20 Oct 2026, after the Bois d'Arc Lake reference (two seasons flooded): the
        # interior is dead, a twiggy grey canopy on grey trunks; only a narrow fringe in
        # shallow water along the waterline keeps rust-brown dying foliage. Spanish moss on
        # about an eighth of the dead trees (cut by more than half: it takes years to grow).
        depth_m = lrh.POOL_M - z
        fringe = (depth_m < 1.2) & (rng.random(n) < 0.5)   # patchy, as in the reference
        dead_in_dying = ~fringe
        mossy = dead_in_dying & (rng.random(n) < 0.15)
        dying_protos = {sp: [trees.make_dying(p, proto_coll) for p in protos]
                        for sp, protos in prototypes.items() if sp in ("red_cedar", "post_oak")}
        bare_protos = {sp: [trees.make_bare(p, proto_coll) for p in protos]
                       for sp, protos in prototypes.items() if sp in ("red_cedar", "post_oak")}
        moss_protos = [trees.make_moss(s, proto_coll) for s in snags]

        def scales_for(sel, species):
            spec = trees.SPECIES[species]
            s = height[sel] / spec["height"]
            widen = np.clip(crown[sel] / spec["crown_radius"] / s, 0.5, 2.0)
            return np.column_stack([s * widen, s * widen, s])

        for v in range(trees.VARIANTS):
            in_v = variant == v
            for is_cedar, species in ((True, "red_cedar"), (False, "post_oak")):
                m = in_v & (cedar == is_cedar)
                if m.any():
                    point_cloud(f"Flooded_Leafy_{species}_{v}", pts[m], scales_for(m, species),
                                rot[m], prototypes[species][v], made["Flooded_Timber_Leafy"])
                m2 = m & ~dead_in_dying
                if m2.any():
                    point_cloud(f"Flooded_Dying_{species}_{v}", pts[m2], scales_for(m2, species),
                                rot[m2], dying_protos[species][v], made["Flooded_Timber_Dying"])
                m3 = m & dead_in_dying
                if m3.any():
                    point_cloud(f"Flooded_Bare_{species}_{v}", pts[m3], scales_for(m3, species),
                                rot[m3], bare_protos[species][v], made["Flooded_Timber_Dying"])
            snag_s = height / snags[v]["prototype_height_m"]
            snag_scale = np.column_stack([snag_s, snag_s, snag_s])
            for name, m in (("Flooded_Snags", in_v), ("Flooded_Dying_snags", in_v & dead_in_dying),
                            ("Flooded_Moss", in_v & mossy)):
                if not m.any():
                    continue
                proto = moss_protos[v] if name == "Flooded_Moss" else snags[v]
                coll = {"Flooded_Snags": "Flooded_Timber_Snags",
                        "Flooded_Dying_snags": "Flooded_Timber_Dying",
                        "Flooded_Moss": "Spanish_Moss"}[name]
                point_cloud(f"{name}_{v}", pts[m], snag_scale[m], rot[m], proto, made[coll])
    depth = lrh.POOL_M - rows[:, 2] if len(rows) else np.zeros(0)
    record("flooded_timber", len(rows) > 50, trees=len(rows),
           dead_in_dying_stage=int(dead_in_dying.sum()) if len(rows) else 0,
           rust_fringe=int((~dead_in_dying).sum()) if len(rows) else 0,
           with_spanish_moss=int(mossy.sum()) if len(rows) else 0,
           water_depth_m_p50=round(float(np.median(depth)), 2) if len(rows) else None,
           water_depth_m_max=round(float(depth.max()), 2) if len(rows) else None,
           basis="StratMap 2025 lidar trees below the 551 ft pool inside the mapped Fish and "
                 "Wildlife Habitat zone; crowns must clear the water by 1.5 m")


def scatter(coll, site_grid, sampler, road_lines, zone, timber_zone, record, clear=None,
            open_sky=None, scrub_zone=None, scrub_max_height=4.0, build_sites=None):
    """`clear`: footprints (driveways, dock paths and docks) where no tree may stand.
    `open_sky`: (lines, half width): no crown may overhang these corridors, so cleared
    dock paths read from the air (owner, 14 Oct 2026).
    `build_sites`: {lot label: footprint}. Trees there go into a child collection
    `Vegetation_BuildSite_<lot>`, so render.py can remove them when that lot's cabin is shown."""
    """Place trees; returns counts by species and records the vegetation checks."""
    import shapely  # from .blender-site via lrh

    rng = np.random.default_rng(20261014)
    site_cover = Raster(DERIVED / "cover_site_drone.tif")
    site_frac = Raster(DERIVED / "tree_fraction_site.tif")
    regional_cover = Raster(DERIVED / "cover_regional.tif")
    regional_frac = Raster(DERIVED / "tree_fraction_regional.tif")
    road_buffer = shapely.union_all([shapely.LineString(l).buffer(7.0) for l in road_lines])
    if clear is not None:
        road_buffer = road_buffer.union(clear)

    proto_coll = bpy.data.collections.new("Tree_Prototypes")
    coll.children.link(proto_coll)
    proto_coll.hide_render = True
    proto_coll.hide_viewport = True
    prototypes = trees.make_prototypes(proto_coll)
    snags = [trees.make_snag(v, proto_coll) for v in range(trees.VARIANTS)]

    regional_extent = (regional_cover.gt[0], regional_cover.gt[3] + regional_cover.gt[5] *
                       regional_cover.array.shape[0],
                       regional_cover.gt[0] + regional_cover.gt[1] * regional_cover.array.shape[1],
                       regional_cover.gt[3])
    placed = {s: [] for s in trees.SPECIES}  # rows: x, y, z, height or nan, crown or nan, boost
    coverage = shapely.union_all([shapely.box(*b) for b in json.loads(
        (DERIVED / "lidar_coverage.json").read_text())["tiles_local_m_bounds"].values()])
    lidar = np.load(DERIVED / "lidar_trees.npz")["trees"]
    x, y, height, crown, evergreen = lidar[:, 0], lidar[:, 1], lidar[:, 3], lidar[:, 4], lidar[:, 5]
    cls, in_site = site_cover.lookup(x, y)
    # The photo projection uses the GPS-anchored KwikImage camera (registered to ~2-3 m;
    # scripts/kwik_ortho.py), so an object counts as a brush pile only if the photo shows
    # no woods within 4 m; nearer ones are the photo's retained trees.
    near_woods = np.zeros(len(x), bool)
    for dx in np.arange(-4.0, 4.1, 1.0):
        for dy in np.arange(-4.0, 4.1, 1.0):
            if dx * dx + dy * dy <= 16:
                near_woods |= site_cover.lookup(x + dx, y + dy)[0] == WOODS
    brush_piles = in_site & (cls == CLEARED) & ~near_woods
    keep = ~brush_piles & ~shapely.contains_xy(road_buffer, x, y)
    # Owner, 15 Oct 2026: brush piles burned and scrub cleared inside the parcels.
    scrub = np.zeros(len(x), bool)
    if scrub_zone is not None:
        scrub = shapely.contains_xy(scrub_zone, x, y) & (height < scrub_max_height)
        keep &= ~scrub
    if open_sky is not None:
        lines, half = open_sky
        overhang = shapely.distance(shapely.points(x, y), lines) < half + 0.8 * crown
        lstats_overhang = int((keep & overhang).sum())
        keep &= ~overhang
    else:
        lstats_overhang = 0
    lstats = {"lidar_detected": len(lidar), "lidar_brush_piles_omitted": int(brush_piles.sum()),
              "lidar_scrub_cleared": int(scrub.sum()),
              "lidar_cleared_for_paths": lstats_overhang}
    x, y, height, crown, evergreen = (a[keep] for a in (x, y, height, crown, evergreen))
    z = site_grid.heights(x, y)
    far = np.isnan(z)
    z[far] = [sampler(a, b) or np.nan for a, b in zip(x[far], y[far])]
    dry = ~np.isnan(z) & (z > lrh.POOL_M + 0.3)
    lstats["lidar_below_pool"] = int((~dry).sum())
    # Below pool inside the Fish and Wildlife Habitat zone: standing flooded timber. Depth
    # uses the lidar's own ground (the 50 m regional mesh is too coarse in the side arm).
    lidar_ground = lidar[keep, 2]
    wet = shapely.contains_xy(timber_zone, x, y) & (lidar_ground < lrh.POOL_M - 0.3) & \
        (height > (lrh.POOL_M - lidar_ground) + 1.5)
    dry &= ~wet
    timber_rows = np.column_stack([x[wet], y[wet], lidar_ground[wet], height[wet], crown[wet],
                                   evergreen[wet]]).tolist()
    lstats["lidar_flooded_timber"] = int(wet.sum())
    for i in np.flatnonzero(dry):
        if evergreen[i] >= EVERGREEN_SCORE_MIN:
            species = "red_cedar"
        else:
            species = rng.choice(list(DECIDUOUS_MIX), p=list(DECIDUOUS_MIX.values()))
        placed[species].append((x[i], y[i], z[i], height[i], crown[i], 1.0))
    lstats["lidar_placed"] = int(dry.sum())

    stats = {"candidates": 0, "woods": 0, "pasture_cedars": 0, "underwater": 0, "on_road": 0,
             "no_terrain": 0}
    for pts, spacing, boost in candidates(rng, regional_extent):
        pts = pts[~shapely.contains_xy(coverage, pts[:, 0], pts[:, 1])]
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
        if open_sky is not None:  # scattered trees: assume a 4 m crown
            on_road |= shapely.distance(shapely.points(x, y), open_sky[0]) < open_sky[1] + 4.0
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
            placed[species].append((x[i], y[i], z[i], np.nan, np.nan, boost))

    counts, build_counts = {}, {}
    for species, rows in placed.items():
        if not rows:
            continue
        arr = np.array(rows)
        spec = trees.SPECIES[species]
        lo, hi = spec["heights"]
        measured = ~np.isnan(arr[:, 3])
        heights = np.where(measured, arr[:, 3], rng.uniform(lo, hi, len(arr)))
        variant = rng.integers(0, trees.VARIANTS, len(arr))
        for v in range(trees.VARIANTS):
            sel = variant == v
            if not sel.any():
                continue
            s = heights[sel] / spec["height"]
            # Measured crowns set the width directly; scattered trees keep the
            # prototype's proportions (widened by the distance-tier boost).
            widen = np.where(measured[sel],
                             np.clip(arr[sel, 4] / spec["crown_radius"] / s, 0.5, 2.0),
                             arr[sel, 5]) * rng.uniform(0.9, 1.1, sel.sum())
            scales = np.column_stack([s * widen, s * widen * rng.uniform(0.9, 1.1, sel.sum()), s])
            rotations = np.column_stack([np.zeros(sel.sum()), np.zeros(sel.sum()),
                                         rng.uniform(0, 2 * math.pi, sel.sum())])
            pts = np.column_stack([arr[sel, 0], arr[sel, 1], arr[sel, 2] - 0.15])
            rest = np.ones(len(pts), bool)
            for label, area in (build_sites or {}).items():
                on = rest & shapely.contains_xy(area, pts[:, 0], pts[:, 1])
                if on.any():
                    key = f"Vegetation_BuildSite_{label.replace(' ', '_')}"
                    sub = bpy.data.collections.get(key)
                    if sub is None:
                        sub = bpy.data.collections.new(key)
                        coll.children.link(sub)
                    point_cloud(f"Trees_{species}_{v}_{label.replace(' ', '_')}", pts[on], scales[on],
                                rotations[on], prototypes[species][v], sub)
                    build_counts[label] = build_counts.get(label, 0) + int(on.sum())
                    rest &= ~on
            point_cloud(f"Trees_{species}_{v}", pts[rest], scales[rest], rotations[rest],
                        prototypes[species][v], coll)
        counts[species] = len(arr)

    flooded_timber(rng, timber_rows, prototypes, snags, proto_coll, record)
    total = sum(counts.values())
    record("trees_placed", total > 1000 and lstats["lidar_placed"] > 10000, total=total,
           by_species=counts, **lstats, mask_scatter=stats, on_build_sites=build_counts,
           height_source="StratMap 2025 lidar inside its coverage (source a); "
                         "species-random ranges outside it (source c)")
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
