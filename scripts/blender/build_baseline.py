"""Phase 1 baseline: build out/<date>/lrh_baseline.blend from inputs/ and shots.yaml.

Builds terrain (1 m site mesh stitched into the 50 m regional mesh), the lake, roads,
the SH 34 bridge marker, review overlays, the creek preservation mask and the shot
cameras, then runs the automated Phase 1 checks and writes baseline_checks.json.
The script exits non-zero if any check fails, after saving the .blend for inspection.

Usage:
  /Applications/Blender.app/Contents/MacOS/Blender -b --python scripts/blender/build_baseline.py
"""

import json
import math
import sys
import tempfile
from pathlib import Path

import bmesh
import bpy
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from mathutils.geometry import delaunay_2d_cdt

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cabins  # noqa: E402
import infrastructure  # noqa: E402
import lotplan  # noqa: E402
import scene_life  # noqa: E402
import lrh  # noqa: E402
import vegetation  # noqa: E402

import shapely  # noqa: E402  (from .blender-site, added to sys.path by lrh)
import yaml  # noqa: E402
from shapely.geometry import LineString, Polygon, box, mapping  # noqa: E402
from shapely.ops import unary_union  # noqa: E402

SQM_PER_ACRE = 4046.8564224
WATER_MASK_BUFFER_M = 60.0  # mask edges must fall on ground above pool to stay hidden
NEAR_SITE_M = 1500.0  # exposure inside this distance of the site is held to a tighter limit
ROAD_LIFT_M = 0.12
OVERLAY_LIFT_M = 0.6

checks = {}


def record(name, passed, **details):
    checks[name] = {"passed": bool(passed), **details}
    print(f"{'PASS' if passed else 'FAIL'}  {name}  {json.dumps(details)}")


# --------------------------------------------------------------------------- scene

def clear_scene():
    # Not read_factory_settings(): it unloads importers (see CLAUDE.md).
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    for coll in list(bpy.data.collections):
        bpy.data.collections.remove(coll)
    for block in (bpy.data.meshes, bpy.data.curves, bpy.data.materials, bpy.data.cameras,
                  bpy.data.lights, bpy.data.worlds):
        for item in list(block):
            block.remove(item)


def collection(name, parent=None):
    coll = bpy.data.collections.new(name)
    (parent or bpy.context.scene.collection).children.link(coll)
    return coll


def mesh_object(name, coords, faces, coll):
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata([tuple(c) for c in coords], [], [tuple(f) for f in faces])
    mesh.validate()
    obj = bpy.data.objects.new(name, mesh)
    coll.objects.link(obj)
    if not mesh.polygons:
        lrh.fail(f"{name} has no faces")
    return obj


def mesh_vertices(obj):
    coords = np.empty(len(obj.data.vertices) * 3)
    obj.data.vertices.foreach_get("co", coords)
    return coords.reshape(-1, 3)


def mesh_triangles(obj):
    obj.data.calc_loop_triangles()
    tris = np.empty(len(obj.data.loop_triangles) * 3, dtype=np.int64)
    obj.data.loop_triangles.foreach_get("vertices", tris)
    return tris.reshape(-1, 3)


# --------------------------------------------------------------------------- materials

def principled(name, rgb, roughness=0.8, **inputs):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (*rgb, 1.0)
    bsdf.inputs["Roughness"].default_value = roughness
    for key, value in inputs.items():
        bsdf.inputs[key].default_value = value
    return mat


def imagery_ground_material(name, product, image_path, cleared_mask=None):
    """Ground albedo from NAIP, with the August 2023 drone-photo clearing and underwater ground overlaid."""
    xmin, _, _, ymax = product["bbox_local_m"]
    width = product["size_px"][0] * product["cell_m"]
    height = product["size_px"][1] * product["cell_m"]
    mat = principled(name, (0.3, 0.3, 0.2), roughness=0.95)
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    bsdf = nodes["Principled BSDF"]
    coord = nodes.new("ShaderNodeTexCoord")  # object space = world metres here
    to_uv = nodes.new("ShaderNodeMapping")
    to_uv.inputs["Scale"].default_value = (1 / width, 1 / height, 1)
    to_uv.inputs["Location"].default_value = (-xmin / width, -(ymax - height) / height, 0)
    links.new(coord.outputs["Object"], to_uv.inputs["Vector"])

    def image_node(path, colour):
        node = nodes.new("ShaderNodeTexImage")
        node.image = bpy.data.images.load(str(path))
        node.image.colorspace_settings.name = colour
        node.extension = "EXTEND"
        node.interpolation = "Cubic"
        links.new(to_uv.outputs["Vector"], node.inputs["Vector"])
        return node

    naip = image_node(image_path, "sRGB")
    # Grade toward the drone photo's yellow-green pasture: under strong sun AgX
    # desaturates NAIP's olive tones, so push hue slightly green and lift saturation.
    grade = nodes.new("ShaderNodeHueSaturation")
    grade.inputs["Hue"].default_value = 0.52
    grade.inputs["Saturation"].default_value = 1.55
    grade.inputs["Value"].default_value = 1.05
    links.new(naip.outputs["Color"], grade.inputs["Color"])
    colour = grade.outputs["Color"]
    if cleared_mask is not None:
        mask = image_node(cleared_mask, "Non-Color")
        soil = nodes.new("ShaderNodeTexNoise")
        soil.inputs["Scale"].default_value = 0.6
        soil.inputs["Detail"].default_value = 10.0
        links.new(coord.outputs["Object"], soil.inputs["Vector"])
        soil_ramp = nodes.new("ShaderNodeValToRGB")
        # Linear albedo: scraped clay-loam ~0.15-0.2, dry stubble ~0.25-0.3.
        soil_ramp.color_ramp.elements[0].color = (0.17, 0.12, 0.075, 1)
        soil_ramp.color_ramp.elements[1].color = (0.28, 0.22, 0.13, 1)
        links.new(soil.outputs["Fac"], soil_ramp.inputs["Fac"])
        # Marketing variant: the cleared ground grassed over (render.py sets this value).
        grass_ramp = nodes.new("ShaderNodeValToRGB")
        grass_ramp.color_ramp.elements[0].color = (0.055, 0.10, 0.025, 1)  # mown pasture
        grass_ramp.color_ramp.elements[1].color = (0.11, 0.16, 0.045, 1)
        links.new(soil.outputs["Fac"], grass_ramp.inputs["Fac"])
        grassed = nodes.new("ShaderNodeValue")
        grassed.name = "LRH_Cleared_Grassed"
        grassed.outputs[0].default_value = 0.0
        surface = nodes.new("ShaderNodeMix")
        surface.data_type = "RGBA"
        links.new(grassed.outputs[0], surface.inputs["Factor"])
        links.new(soil_ramp.outputs["Color"], surface.inputs["A"])
        links.new(grass_ramp.outputs["Color"], surface.inputs["B"])
        cleared = nodes.new("ShaderNodeMix")
        cleared.data_type = "RGBA"
        links.new(mask.outputs["Color"], cleared.inputs["Factor"])
        links.new(colour, cleared.inputs["A"])
        links.new(surface.outputs["Result"], cleared.inputs["B"])
        colour = cleared.outputs["Result"]
    # Ground below pool is lake bed: dark silt, blended over 0.5 m.
    position = nodes.new("ShaderNodeSeparateXYZ")
    links.new(coord.outputs["Object"], position.inputs["Vector"])
    below = nodes.new("ShaderNodeMapRange")
    below.inputs["From Min"].default_value = lrh.POOL_M
    below.inputs["From Max"].default_value = lrh.POOL_M - 0.5
    links.new(position.outputs["Z"], below.inputs["Value"])
    silt = nodes.new("ShaderNodeMix")
    silt.data_type = "RGBA"
    silt.inputs["B"].default_value = (0.10, 0.085, 0.06, 1)
    links.new(below.outputs["Result"], silt.inputs["Factor"])
    links.new(colour, silt.inputs["A"])
    links.new(silt.outputs["Result"], bsdf.inputs["Base Color"])
    return mat


def water_material():
    """Reservoir water: glossy dielectric with wind ripples at three scales (long swells,
    metre-scale chop, fine ripples), stretched across an assumed southerly breeze, so low
    sun produces a glitter path instead of a mirror (owner, 16 Oct 2026)."""
    mat = principled("Lake_Water", (0.02, 0.05, 0.05), roughness=0.06,
                     **{"Transmission Weight": 1.0, "IOR": 1.333})
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    bsdf = nodes["Principled BSDF"]
    coord = nodes.new("ShaderNodeTexCoord")
    height = None
    for scale, stretch, weight in ((0.03, 3.0, 0.35), (0.45, 2.0, 0.40), (3.0, 1.5, 0.25)):
        mp = nodes.new("ShaderNodeMapping")
        mp.inputs["Scale"].default_value = (1.0, stretch, 1.0)  # crests run east-west
        links.new(coord.outputs["Object"], mp.inputs["Vector"])
        noise = nodes.new("ShaderNodeTexNoise")
        noise.inputs["Scale"].default_value = scale
        noise.inputs["Detail"].default_value = 4.0
        links.new(mp.outputs["Vector"], noise.inputs["Vector"])
        mul = nodes.new("ShaderNodeMath")
        mul.operation = "MULTIPLY"
        mul.inputs[1].default_value = weight
        links.new(noise.outputs["Fac"], mul.inputs[0])
        if height is None:
            height = mul.outputs[0]
        else:
            add = nodes.new("ShaderNodeMath")
            add.operation = "ADD"
            links.new(height, add.inputs[0])
            links.new(mul.outputs[0], add.inputs[1])
            height = add.outputs[0]
    bump = nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.8
    bump.inputs["Distance"].default_value = 0.6
    links.new(height, bump.inputs["Height"])
    links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    # Turbid reservoir water: absorption only (scattering is costly at this scale).
    absorb = nodes.new("ShaderNodeVolumeAbsorption")
    absorb.inputs["Color"].default_value = (0.55, 0.68, 0.55, 1)
    absorb.inputs["Density"].default_value = 0.45
    links.new(absorb.outputs["Volume"], nodes["Material Output"].inputs["Volume"])
    return mat


def emission_material(name, rgb, strength=2.0):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    nodes.remove(nodes["Principled BSDF"])
    emit = nodes.new("ShaderNodeEmission")
    emit.inputs["Color"].default_value = (*rgb, 1)
    emit.inputs["Strength"].default_value = strength
    mat.node_tree.links.new(emit.outputs["Emission"], nodes["Material Output"].inputs["Surface"])
    return mat


# --------------------------------------------------------------------------- terrain

class SiteGrid:
    """The 1 m site mesh as a regular grid, for exact lookups and the raster check."""

    def __init__(self, coords):
        self.xmin, self.ymin = coords[:, 0].min(), coords[:, 1].min()
        gx = np.round(coords[:, 0] - self.xmin).astype(int)
        gy = np.round(coords[:, 1] - self.ymin).astype(int)
        if np.abs(coords[:, 0] - self.xmin - gx).max() > 1e-3 or \
                np.abs(coords[:, 1] - self.ymin - gy).max() > 1e-3:
            lrh.fail("site mesh is not on a 1 m grid")
        self.nx, self.ny = gx.max() + 1, gy.max() + 1
        if self.nx * self.ny != len(coords):
            lrh.fail(f"site grid {self.nx}x{self.ny} != {len(coords)} vertices")
        self.z = np.full((self.ny, self.nx), np.nan)
        self.z[gy, gx] = coords[:, 2]
        self.index = np.full((self.ny, self.nx), -1)
        self.index[gy, gx] = np.arange(len(coords))
        self.xmax, self.ymax = self.xmin + self.nx - 1, self.ymin + self.ny - 1
        self.rect = box(self.xmin, self.ymin, self.xmax, self.ymax)

    def heights(self, x, y):
        """Bilinear terrain heights at many points; NaN outside the site grid."""
        fx, fy = np.asarray(x) - self.xmin, np.asarray(y) - self.ymin
        inside = (fx >= 0) & (fx <= self.nx - 1) & (fy >= 0) & (fy <= self.ny - 1)
        out = np.full(len(fx), np.nan)
        cx = np.clip(np.floor(fx[inside]).astype(int), 0, self.nx - 2)
        cy = np.clip(np.floor(fy[inside]).astype(int), 0, self.ny - 2)
        tx, ty = fx[inside] - cx, fy[inside] - cy
        z = self.z
        out[inside] = (z[cy, cx] * (1 - tx) * (1 - ty) + z[cy, cx + 1] * tx * (1 - ty)
                       + z[cy + 1, cx] * (1 - tx) * ty + z[cy + 1, cx + 1] * tx * ty)
        return out

    def perimeter_indices(self):
        """Vertex indices around the grid boundary, counter-clockwise, no repeat."""
        idx = self.index
        south = idx[0, :]
        east = idx[1:, -1]
        north = idx[-1, -2::-1]
        west = idx[-2:0:-1, 0]
        return np.concatenate([south, east, north, west])


def import_site_terrain(coll):
    # PTM OBJ is Y-up with z = -northing; Blender's default OBJ axes map it to
    # X = easting offset, Y = northing offset, Z = elevation.
    bpy.ops.wm.obj_import(filepath=str(lrh.INPUTS / "terrain/terrain_design.obj"))
    terrain = bpy.context.selected_objects[0]
    terrain.name = "Site_Terrain_1m"
    for user in list(terrain.users_collection):
        user.objects.unlink(terrain)
    coll.objects.link(terrain)
    # Bake any import transform into the mesh so mesh coordinates are world coordinates.
    terrain.data.transform(terrain.matrix_world)
    terrain.matrix_world.identity()
    expected = lrh.ORIGIN_JSON["meshes"]["design"]["vertices"]
    record("site_terrain_vertex_count", len(terrain.data.vertices) == expected,
           vertices=len(terrain.data.vertices), expected=expected)
    for poly in terrain.data.polygons:
        poly.use_smooth = True
    return terrain


def check_terrain_against_raster(grid):
    """terrain_site.tif is the 3x3 block mean of the 1 m surface; compare to the scene mesh."""
    with tempfile.TemporaryDirectory() as scratch:
        raster, ox, oy, cell = lrh.read_site_raster(scratch)
    rows, cols = np.indices(raster.shape)
    cx = ox + (cols + 0.5) * cell
    cy = oy - (rows + 0.5) * cell
    gx = np.round(cx - grid.xmin).astype(int)
    gy = np.round(cy - grid.ymin).astype(int)
    inside = (gx >= 1) & (gx <= grid.nx - 2) & (gy >= 1) & (gy <= grid.ny - 2) & \
        ~np.isnan(raster)
    aligned = np.abs(cx - grid.xmin - gx).max() < 1e-3
    gx, gy, ref = gx[inside], gy[inside], raster[inside]
    block = np.mean([grid.z[gy + dy, gx + dx] for dy in (-1, 0, 1) for dx in (-1, 0, 1)], axis=0)
    error = np.abs(block - ref)
    target = lrh.ORIGIN_JSON["meshes"]["design"]["vertical_error"]["target_m"]
    record("terrain_vs_terrain_site_tif", aligned and error.max() <= target,
           samples=int(inside.sum()), max_abs_error_m=round(float(error.max()), 5),
           p95_abs_error_m=round(float(np.percentile(error, 95)), 5), target_m=target,
           method="3x3 block mean of scene 1 m vertices vs 3 m raster cell")


def stitch_regional_terrain(grid, site_coords, coll, margin_m=120.0):
    """Regional 50 m mesh with a constrained-Delaunay ring joining it to the site edge.

    Regional faces near the site are removed and the gap is re-triangulated between the
    remaining regional boundary and every 1 m site perimeter vertex, so the two meshes
    share an exact edge with no cracks and the site mesh itself is never altered.
    """
    coords, tris = lrh.dae_geometry("regional-terrain-50m")
    patch_box = grid.rect.buffer(margin_m, join_style="mitre")
    near = shapely.contains_xy(patch_box, coords[:, 0], coords[:, 1])
    removed = near[tris].any(axis=1)
    kept_tris, removed_tris = tris[~removed], tris[removed]
    removed_region = unary_union([Polygon(coords[t, :2]) for t in removed_tris])

    # Boundary of the removed region = edges shared by one removed and one kept face.
    def edge_set(faces):
        edges = np.sort(np.concatenate([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]]),
                        axis=1)
        return {tuple(e) for e in edges}
    outer_edges = edge_set(removed_tris) & edge_set(kept_tris)

    outer_ids = sorted({v for e in outer_edges for v in e} |
                       {v for v in np.unique(removed_tris)
                        if not shapely.contains_xy(grid.rect, *coords[v, :2])})
    perimeter = grid.perimeter_indices()
    points = np.vstack([coords[outer_ids], site_coords[perimeter]])
    local = {v: i for i, v in enumerate(outer_ids)}
    constraint = [(local[a], local[b]) for a, b in outer_edges]
    base = len(outer_ids)
    constraint += [(base + i, base + (i + 1) % len(perimeter)) for i in range(len(perimeter))]
    out_verts, _, out_faces, orig_verts, _, _ = delaunay_2d_cdt(
        [Vector(p[:2]) for p in points], constraint, [], 0, 1e-4, True)
    if len(out_verts) != len(points):
        lrh.fail("regional stitch created new vertices; constraints intersect")
    out_index = [ids[0] for ids in orig_verts]
    ring = []
    for face in out_faces:
        corners = [out_index[v] for v in face]
        centroid = points[corners, :2].mean(axis=0)
        if shapely.contains_xy(removed_region, *centroid) and \
                not shapely.contains_xy(grid.rect.buffer(-1e-6), *centroid):
            ring.append(corners)

    # Assemble: kept regional faces + stitch ring, with regional vertices first.
    all_coords = np.vstack([coords, site_coords[perimeter]])
    remap = np.array([outer_ids[i] if i < base else len(coords) + i - base
                      for i in range(len(points))])
    faces = np.vstack([kept_tris, remap[np.array(ring)]])
    used = np.unique(faces)
    compact = np.full(len(all_coords), -1)
    compact[used] = np.arange(len(used))
    obj = mesh_object("Regional_Terrain_50m", all_coords[used], compact[faces], coll)

    # Coverage: the stitched ring must fill exactly the removed area outside the site.
    ring_area = sum(Polygon(points[f, :2]).area for f in ring)
    expected = removed_region.difference(grid.rect).area
    record("regional_stitch_coverage", abs(ring_area - expected) < 1.0,
           ring_faces=len(ring), ring_area_m2=round(ring_area, 1),
           expected_area_m2=round(expected, 1), removed_regional_faces=int(removed.sum()))
    return obj


# --------------------------------------------------------------------------- sampling

class HeightSampler:
    def __init__(self, objects):
        depsgraph = bpy.context.evaluated_depsgraph_get()
        self.trees = [BVHTree.FromObject(o, depsgraph) for o in objects]

    def __call__(self, x, y):
        best = None
        for tree in self.trees:
            hit = tree.ray_cast(Vector((x, y, 3000.0)), Vector((0, 0, -1)))
            if hit[0] is not None and (best is None or hit[0].z > best):
                best = hit[0].z
        return best


def drape(points_xy, sampler, lift, fallback=None):
    out = []
    for x, y in points_xy:
        z = sampler(x, y)
        if z is None:
            if fallback is None:
                lrh.fail(f"no terrain under ({x:.1f}, {y:.1f})")
            z = fallback
        out.append((x, y, z + lift))
    return out


def densify(line_xy, step):
    line = LineString(line_xy)
    count = max(2, int(math.ceil(line.length / step)) + 1)
    return [line.interpolate(d).coords[0] for d in np.linspace(0, line.length, count)]


# --------------------------------------------------------------------------- water

def build_water(grid, context, coll, sampler):
    lake_coords, lake_tris = lrh.dae_geometry("official-lake-551ft")
    official = unary_union([Polygon(lake_coords[t, :2]) for t in lake_tris])
    connected = unary_union([Polygon(np.array(t)[:, :2])
                             for t in context["conceptual_water"]["triangles_local_m"]])
    # Official shoreline outside the site; inside it, the PTM terrain-connected pool
    # (seeded from the same official shoreline). The mask is then buffered so its edge
    # lies on ground above pool and the visible shoreline is the terrain contour.
    water = unary_union([official, connected]).buffer(WATER_MASK_BUFFER_M, quad_segs=4)
    # No water downstream of the dam axis (PTM: where the official polygon crosses the
    # dam station); the generalised polygon overruns it onto ground far below pool.
    (dx, dy0, _), (_, dy1, _) = context["conceptual_regional_landmarks"]["dam"]["line_local_m"]
    water = water.difference(box(dx, dy0 - 100, dx + 3000, dy1 + 100))
    water = shapely.simplify(water, 0.5)
    triangles = shapely.constrained_delaunay_triangles(water)
    verts, faces, lookup = [], [], {}
    for tri in triangles.geoms:
        face = []
        corners = list(tri.exterior.coords)[:3]
        if not shapely.Polygon(corners).exterior.is_ccw:
            corners.reverse()  # normals up, so Solidify extrudes the depth downward
        for x, y in corners:
            key = (round(x, 4), round(y, 4))
            if key not in lookup:
                lookup[key] = len(verts)
                verts.append((x, y, lrh.POOL_M))
            face.append(lookup[key])
        faces.append(face)
    obj = mesh_object("Lake_551ft", verts, faces, coll)
    obj.data.materials.append(water_material())
    solid = obj.modifiers.new("Depth", "SOLIDIFY")
    solid.thickness = 30.0
    solid.offset = -1.0
    solid.use_even_offset = False

    # Exposure: points on the mask edge where ground is below pool show a water "wall".
    # The published polygon is generalised (unbuffered, ~40% of its edge lies over
    # below-pool ground), so a few remote exposures remain; near the site there must be
    # almost none.
    edge = water.boundary
    near = grid.rect.buffer(NEAR_SITE_M)
    samples = [edge.interpolate(d) for d in np.arange(0, edge.length, 10.0)]
    valid = [(p, z) for p in samples if (z := sampler(p.x, p.y)) is not None]
    exposed = [p for p, z in valid if z < lrh.POOL_M - 0.05]
    near_valid = sum(1 for p, _ in valid if near.contains(p))
    near_exposed = [p for p in exposed if near.contains(p)]
    normals = np.array([p.normal.z for p in obj.data.polygons])
    record("water_normals_up", (normals > 0.99).all(), faces=len(normals))
    record("water_mask_edge_hidden",
           len(exposed) / len(valid) < 0.03 and len(near_exposed) / near_valid < 0.01,
           edge_samples=len(valid), exposed=len(exposed), near_site_samples=near_valid,
           near_site_exposed=len(near_exposed),
           near_site_exposed_at=[[round(p.x), round(p.y)] for p in near_exposed],
           mask_buffer_m=WATER_MASK_BUFFER_M,
           water_area_acres=round(water.area / SQM_PER_ACRE, 1),
           official_area_acres=round(official.area / SQM_PER_ACRE, 1))
    return obj, water, connected


# --------------------------------------------------------------------------- roads

def ribbon(name, line_xy, width, sampler, lift, material, coll, step=2.0, across=5,
           min_z=None):
    """A terrain-draped strip `width` wide along a polyline."""
    pts = np.array(densify(line_xy, step))
    tangent = np.gradient(pts, axis=0)
    tangent /= np.linalg.norm(tangent, axis=1, keepdims=True)
    normal = np.column_stack([-tangent[:, 1], tangent[:, 0]])
    offsets = np.linspace(-width / 2, width / 2, across)
    verts = []
    for p, n, zmin in zip(pts, normal, min_z if min_z is not None else [None] * len(pts)):
        for o in offsets:
            x, y = p + n * o
            z = sampler(x, y)
            if z is None:
                lrh.fail(f"{name}: no terrain under ({x:.1f}, {y:.1f})")
            if zmin is not None:
                z = max(z, zmin)
            verts.append((x, y, z + lift))
    faces = [(i * across + j, i * across + j + 1, (i + 1) * across + j + 1, (i + 1) * across + j)
             for i in range(len(pts) - 1) for j in range(across - 1)]
    obj = mesh_object(name, verts, faces, coll)
    obj.data.materials.append(material)
    return obj


def runs_on_terrain(line_xy, half_width, sampler, step=2.0, min_length=20.0):
    """Split a centreline into the runs whose full width lies on terrain."""
    pts = np.array(densify(line_xy, step))
    tangent = np.gradient(pts, axis=0)
    tangent /= np.linalg.norm(tangent, axis=1, keepdims=True)
    normal = np.column_stack([-tangent[:, 1], tangent[:, 0]])
    ok = [all(sampler(*(p + n * o)) is not None for o in (-half_width, 0, half_width))
          for p, n in zip(pts, normal)]
    runs, current = [], []
    for p, good in zip(pts, ok):
        if good:
            current.append(p)
        elif current:
            runs.append(current)
            current = []
    if current:
        runs.append(current)
    return [LineString(r) for r in runs if len(r) > 1 and LineString(r).length >= min_length]


def build_roads(context, coll, sampler):
    gravel = principled("Road_Gravel", (0.62, 0.58, 0.50), roughness=0.95)
    shoulder = principled("Road_Shoulder", (0.38, 0.35, 0.25), roughness=1.0)
    roads = {r["name"]: r for r in context["conceptual_county_roads"]["roads"]}

    # CR 3635: the full TxDOT centreline wherever terrain exists, not just the site part.
    geo = json.loads((lrh.INPUTS / "geometry/txdot-fannin-cr-3635-epsg6344.geojson").read_text())
    line = np.array(geo["features"][0]["geometry"]["coordinates"])[:, :2]
    line -= [lrh.ORIGIN_E, lrh.ORIGIN_N]
    spec = roads["CR 3635"]
    parts = runs_on_terrain(line, spec["shoulder_width_m"] / 2 + 1.0, sampler)
    made = []
    for i, part in enumerate(parts):
        made.append(ribbon(f"CR3635_Shoulder_{i}", part.coords, spec["shoulder_width_m"], sampler,
                           ROAD_LIFT_M - 0.04, shoulder, coll))
        made.append(ribbon(f"CR3635_Surface_{i}", part.coords, spec["road_width_m"], sampler,
                           ROAD_LIFT_M, gravel, coll))

    # Relocated CR 3640 (UTRWD Road Plan New Alignment, west to SH 34) is built by
    # infrastructure.build_cr3640 on grade, with a causeway over the creek arm.
    cr3640 = infrastructure.build_cr3640(coll, sampler, record)
    centrelines = [list(p.coords) for p in parts] + [cr3640.tolist()]
    record("roads_built", len(made) >= 2, objects=[o.name for o in made],
           cr3635_length_m=round(sum(p.length for p in parts), 1),
           cr3635_source_length_m=round(LineString(line).length, 1))
    return centrelines


def build_dam(context, coll):
    """Schematic Leon Hurse Dam embankment on the PTM dam marker. The regional terrain has
    no embankment (it is below pool along the axis), so without this the lake would end
    in a vertical water wall. Not engineering or as-built geometry."""
    spec = context["conceptual_regional_landmarks"]["dam"]
    (x0, y0, crest), (x1, y1, _) = spec["line_local_m"]
    half, toe_z, slope = spec["crest_width_m"] / 2, crest - 40.0, 3.0
    length = math.hypot(x1 - x0, y1 - y0)
    ux, uy = (x1 - x0) / length, (y1 - y0) / length
    nx, ny = -uy, ux
    profile = [(-half - slope * (crest - toe_z), toe_z), (-half, crest), (half, crest),
               (half + slope * (crest - toe_z), toe_z)]
    verts = [(x + nx * o, y + ny * o, z) for x, y in ((x0, y0), (x1, y1)) for o, z in profile]
    faces = [(0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (0, 4, 7, 3), (0, 3, 2, 1), (4, 5, 6, 7)]
    obj = mesh_object("Leon_Hurse_Dam_Schematic", verts, faces, coll)
    obj.data.materials.append(principled("Dam_Grass", (0.24, 0.28, 0.14), roughness=0.95))
    return obj


def build_far_ground(coll, regional):
    """A 60 km disc below the regional terrain so the horizon is land, not a terrain edge
    with sky beneath it. It sits 3 m under the lowest regional ground near the edges and
    is hidden wherever the regional mesh exists; haze blends the transition."""
    z = float(np.percentile(mesh_vertices(regional)[:, 2], 20)) - 3.0
    bpy.ops.mesh.primitive_circle_add(vertices=128, radius=30000.0, fill_type="TRIFAN",
                                      location=(-6000.0, 3000.0, z))
    disc = bpy.context.active_object
    disc.name = "Far_Ground"
    for user in list(disc.users_collection):
        user.objects.unlink(disc)
    coll.objects.link(disc)
    mat = principled("Far_Ground", (0.13, 0.15, 0.07), roughness=1.0)
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    coord = nodes.new("ShaderNodeTexCoord")
    noise = nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 0.0004
    noise.inputs["Detail"].default_value = 6.0
    links.new(coord.outputs["Object"], noise.inputs["Vector"])
    ramp = nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].color = (0.05, 0.08, 0.03, 1)  # woods
    ramp.color_ramp.elements[1].color = (0.20, 0.20, 0.09, 1)  # pasture
    links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
    links.new(ramp.outputs["Color"], nodes["Principled BSDF"].inputs["Base Color"])
    disc.data.materials.append(mat)
    return disc


# --------------------------------------------------------------------------- overlays

def polyline_curve(name, points, coll, material, bevel=0.35, closed=False):
    curve = bpy.data.curves.new(name, "CURVE")
    curve.dimensions = "3D"
    curve.bevel_depth = bevel
    spline = curve.splines.new("POLY")
    spline.points.add(len(points) - 1)
    for p, co in zip(spline.points, points):
        p.co = (*co, 1.0)
    spline.use_cyclic_u = closed
    obj = bpy.data.objects.new(name, curve)
    obj.data.materials.append(material)
    coll.objects.link(obj)
    return obj


def build_overlays(context, coll, sampler):
    parcel_mat = emission_material("Overlay_Parcel", (0.9, 0.08, 0.05))
    lot_mat = emission_material("Overlay_Lot", (1.0, 0.85, 0.2))
    label_mat = emission_material("Overlay_Label", (1.0, 1.0, 1.0), strength=3.0)
    for b in context["boundaries"]:
        if b["kind"] != "owner_parcel_boundary":
            continue
        pts = np.array(b["lines_local_m"][0])[:, :2]
        polyline_curve(f"Parcel_{b['prop_id']}", drape(pts, sampler, OVERLAY_LIFT_M), coll,
                       parcel_mat, bevel=0.6, closed=True)
    lots = []
    for lot in context["conceptual_lots"]["lots"]:
        ring = densify(np.vstack([lot["polygon_local_m"], lot["polygon_local_m"][:1]]), 3.0)[:-1]
        obj = polyline_curve(lot["label"].replace(" ", "_"), drape(ring, sampler, OVERLAY_LIFT_M),
                             coll, lot_mat, bevel=0.3, closed=True)
        obj["source_area_acres"] = lot["area_acres"]
        obj["vertex_polygon_local_m"] = [list(map(float, p[:2])) for p in lot["polygon_local_m"]]
        lots.append(obj)
        text = bpy.data.curves.new(f"{lot['label']}_Label", "FONT")
        text.body = lot["label"].split()[-1]
        text.size = 14.0
        text.align_x = "CENTER"
        text.align_y = "CENTER"
        label = bpy.data.objects.new(f"{lot['label'].replace(' ', '_')}_Label", text)
        cx, cy = Polygon(lot["polygon_local_m"]).representative_point().coords[0]
        label.location = (cx, cy, (sampler(cx, cy) or lrh.POOL_M) + 30.0)  # above canopy
        label.data.materials.append(label_mat)
        coll.objects.link(label)
    return lots


def check_lot_areas(lots):
    """Areas from the lot overlay geometry actually in the scene, against PTM values."""
    worst = 0.0
    rows = []
    for obj in lots:
        pts = np.array([p.co[:2] for p in obj.data.splines[0].points])
        x, y = pts[:, 0], pts[:, 1]
        area = 0.5 * abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))) / SQM_PER_ACRE
        diff = abs(area - obj["source_area_acres"])
        worst = max(worst, diff)
        rows.append({"lot": obj.name, "scene_acres": round(area, 4),
                     "ptm_acres": obj["source_area_acres"]})
    record("lot_areas_match_ptm", len(lots) == 10 and worst <= 0.01,
           lots=len(lots), worst_diff_acres=round(worst, 4), detail=rows)


# --------------------------------------------------------------------------- masks

def preservation_zone(context, grid, pooled, coll):
    """Owner-provided creek Fish and Wildlife preservation zone, west of the owner parcels
    within the site mesh. Returns (land, timber): the land part must stay fully wooded;
    the timber part also includes the water, where trees are not cleared before
    impoundment and stand as flooded timber. Owner-derived until an official FWPZ
    polygon exists."""
    parcels = unary_union([Polygon(np.array(b["lines_local_m"][0])[:, :2])
                           for b in context["boundaries"] if b["kind"] == "owner_parcel_boundary"])
    shift = np.array([-2000.0, 0.0])
    ring = np.array(parcels.exterior.coords)
    sweeps = [Polygon([a, b, b + shift, a + shift]) for a, b in zip(ring[:-1], ring[1:])]
    west = unary_union(sweeps + [parcels]).difference(parcels)
    timber = west.intersection(grid.rect)
    zone = timber.difference(pooled)
    if zone.geom_type == "MultiPolygon":
        zone = shapely.MultiPolygon([g for g in zone.geoms if g.area > 400])
    tris = shapely.constrained_delaunay_triangles(zone)
    verts, faces = [], []
    for tri in tris.geoms:
        base = len(verts)
        verts += [(x, y, lrh.POOL_M + 30) for x, y in list(tri.exterior.coords)[:3]]
        faces.append((base, base + 1, base + 2))
    obj = mesh_object("Mask_Creek_Preservation", verts, faces, coll)
    obj.hide_render = True
    obj.display_type = "WIRE"
    obj["basis"] = ("Owner-provided: land west of the owner parcels within the site mesh, "
                    "excluding lake. No official FWPZ polygon yet.")
    record("preservation_zone_defined", zone.area > 5 * SQM_PER_ACRE,
           land_area_acres=round(zone.area / SQM_PER_ACRE, 2),
           with_water_area_acres=round(timber.area / SQM_PER_ACRE, 2))
    return zone, timber


# --------------------------------------------------------------------------- cameras

def look_at(obj, target):
    direction = Vector(target) - obj.location
    obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def build_cameras(shots, coll):
    made = []
    for name, shot in shots.items():
        spec = shot["camera"]
        cam_data = bpy.data.cameras.new(f"CAM_{name}")
        cam_data.clip_start = spec.get("clip_start", 1.0)
        cam_data.clip_end = spec.get("clip_end", 60000.0)  # default 1000 m clips the scene
        cam_data.sensor_width = spec.get("sensor_width_mm", 36.0)
        cam = bpy.data.objects.new(f"CAM_{name}", cam_data)
        coll.objects.link(cam)
        if spec.get("type") == "ortho":
            cam_data.type = "ORTHO"
            cam_data.ortho_scale = spec["ortho_scale_m"]
            cx, cy = spec["center"]
            cam.location = (cx, cy, 2000.0)
            cam.rotation_euler = (0.0, 0.0, math.radians(spec.get("rotation_deg", 0.0)))
        else:
            cam_data.lens = spec["lens_mm"]
            cam.location = spec["position"]
            look_at(cam, spec["target"])
            if "roll_deg" in spec:
                cam.rotation_euler.rotate_axis("Z", math.radians(spec["roll_deg"]))
        if "shift" in spec:
            cam_data.shift_x, cam_data.shift_y = spec["shift"]
        made.append(cam)
    return made


# --------------------------------------------------------------------------- main

def default_world(scene):
    world = bpy.data.worlds.new("Sky")
    scene.world = world
    world.use_nodes = True
    sky = world.node_tree.nodes.new("ShaderNodeTexSky")
    sky.sky_type = "MULTIPLE_SCATTERING"
    sky.sun_disc = False
    world.node_tree.links.new(sky.outputs["Color"],
                              world.node_tree.nodes["Background"].inputs["Color"])
    sun = bpy.data.objects.new("Sun", bpy.data.lights.new("Sun", "SUN"))
    sun.data.angle = math.radians(0.53)
    scene.collection.objects.link(sun)


def main():
    out = lrh.out_dir()
    shots = yaml.safe_load((lrh.ROOT / "shots.yaml").read_text())["shots"]
    clear_scene()
    scene = bpy.context.scene
    scene.unit_settings.system = "METRIC"

    colls = {name: collection(name) for name in
             ("Terrain", "Water", "Roads", "Landmarks", "Vegetation", "Overlays_Review", "Masks",
              "Cameras")}

    terrain = import_site_terrain(colls["Terrain"])
    site_coords = mesh_vertices(terrain)
    grid = SiteGrid(site_coords)
    check_terrain_against_raster(grid)
    regional = stitch_regional_terrain(grid, site_coords, colls["Terrain"])
    lock = json.loads((lrh.ROOT / "imagery.lock.json").read_text())
    imagery = {role: lock["products"][name] for role, name in lock["use"].items()}
    derived = lrh.ROOT / "out/derived"
    for path in ("naip_site_rgb.png", "naip_regional_rgb.jpg", "cleared_drone_mask.png",
                 "cover_site_drone.tif", "cover_regional.tif", "lidar_trees.npz",
                 "lidar_coverage.json", "fwh_zone_lsmp.geojson"):
        if not (derived / path).is_file():
            lrh.fail(f"missing out/derived/{path}; run the imagery and lidar steps in "
                     "README first")
    terrain.data.materials.append(imagery_ground_material(
        "Ground_Site", imagery["site"], derived / "naip_site_rgb.png",
        cleared_mask=derived / "cleared_drone_mask.png"))
    regional.data.materials.append(imagery_ground_material(
        "Ground_Regional", imagery["regional"], derived / "naip_regional_rgb.jpg"))

    context = lrh.load_context()
    build_far_ground(colls["Terrain"], regional)
    dam = build_dam(context, colls["Landmarks"])
    infrastructure.dam_materials(dam)
    sampler = HeightSampler([terrain, regional, dam])
    _, water_mask, pooled = build_water(grid, context, colls["Water"], sampler)
    road_lines = build_roads(context, colls["Roads"], sampler)
    # The water mask is buffered 60 m past the shore; pull it back to find the crossing.
    infrastructure.build_sh34(colls["Landmarks"], sampler, water_mask.buffer(-55.0), record)
    lots = build_overlays(context, colls["Overlays_Review"], sampler)
    check_lot_areas(lots)
    zone, _ = preservation_zone(context, grid, pooled, colls["Masks"])
    # Flooded timber follows UTRWD's mapped Fish and Wildlife Habitat zone (draft LSMP
    # Appendix A, digitized by scripts/digitize_fwh_zone.py; approximate).
    fwh = json.loads((lrh.ROOT / "out/derived/fwh_zone_lsmp.geojson").read_text())
    timber_zone = shapely.geometry.shape(fwh["features"][0]["geometry"])
    record("fwh_zone_loaded", timber_zone.area > 10 * SQM_PER_ACRE,
           area_acres=round(timber_zone.area / SQM_PER_ACRE, 1),
           source=fwh["features"][0]["properties"]["source"],
           status=fwh["features"][0]["properties"]["status"])
    (out / "creek_preservation_zone.geojson").write_text(json.dumps({
        "type": "FeatureCollection",
        "crs_note": "LRH local metres (origin.json); add origin to recover EPSG:6344",
        "features": [{"type": "Feature", "properties": {"name": "Creek preservation zone",
                                                        "basis": "owner-provided, derived"},
                      "geometry": mapping(zone)}]}))
    colls["Masks"].hide_render = True
    # Phase 2b lot plan: redlines, driveways, docks and paths (switchable per shot).
    for name in ("Redline", "Driveways", "Shoreline", "Docks"):
        colls[name] = collection(name)
    lotplan.build_redline(context, sampler, colls["Redline"])
    drives = lotplan.driveway_lines(context, road_lines[:-1])
    drive_area, drive_lines = lotplan.build_driveways(drives, sampler, colls["Driveways"], context)
    # Owner, 15 Oct 2026: a mown shoreline path at 551 ft and, per lot, an access path and a
    # cleared circle at a possible dock site. Dock positions are undecided, so the paired
    # dock layout stays an optional layer that clears no trees.
    shore_path, shore_access = lotplan.shoreline_layout(context, pooled)
    shore_area, shore_open = lotplan.build_shoreline(shore_path, shore_access, sampler,
                                                     colls["Shoreline"])
    docks = lotplan.dock_layout(context, pooled, grid, sampler, record)
    lotplan.build_docks(docks, sampler, colls["Docks"])
    parcels = unary_union([Polygon(np.array(b["lines_local_m"][0])[:, :2])
                           for b in context["boundaries"] if b["kind"] == "owner_parcel_boundary"])
    # Phase 2d: trees on each lot's pad, patio and drive are set aside per lot, so a shot
    # that shows that lot's cabin (cabins.py) can remove them.
    sites = cabins.build_sites()
    vegetation.scatter(colls["Vegetation"], grid, sampler, road_lines, zone, timber_zone, record,
                       clear=unary_union([drive_area, shore_area]),
                       open_sky=(shapely.GeometryCollection([shore_open, drive_lines]),
                                 lotplan.MOWN_CORRIDOR_M / 2), scrub_zone=parcels,
                       build_sites={label: cabins.clearing(site) for label, site in sites.items()})
    colls["Cabins"] = collection("Cabins")
    cabins.build(colls["Cabins"], sampler, ribbon, HeightSampler, terrain, record)
    (out / "lot_sites.json").write_text(json.dumps(
        {label: {**site, "shore_circle": shore_access[label]["circle"]}
         for label, site in lotplan.house_sites(context).items()}, indent=1) + "\n")
    scene_life.build(record)
    build_cameras(shots, colls["Cameras"])
    default_world(scene)

    blend = out / "lrh_baseline.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(blend))
    passed = all(c["passed"] for c in checks.values())
    report = {
        "schema": "lrh.baseline-checks/1",
        "generated_utc": lrh.utc_now(),
        "git": lrh.git_commit(),
        "inputs_lock_sha256": lrh.file_sha256(lrh.ROOT / "inputs.lock.json"),
        "blend": str(blend),
        "passed": passed,
        "checks": checks,
    }
    (out / "baseline_checks.json").write_text(json.dumps(report, indent=2) + "\n")
    print(f"BASELINE {'PASSED' if passed else 'FAILED'}: {blend}")
    if not passed:
        sys.exit(1)


if __name__ == "__main__":
    main()
