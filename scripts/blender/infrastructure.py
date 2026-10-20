"""Roads on grade, the SH 34 bridges and the dam surface (PLAN.md Phase 2a).

All geometry is presentation-grade: it follows public centrelines (TxDOT, UTRWD Road
Plan) but widths, grades, bridge structure and the dam section are schematic.
"""

import json
import math

import bpy
import numpy as np

import lrh  # adds .blender-site to sys.path

import shapely  # noqa: E402
from shapely.geometry import LineString  # noqa: E402
from shapely.ops import linemerge, unary_union  # noqa: E402


def material(name, rgb, roughness=0.9, noise_scale=None, noise_mix=None):
    mat = bpy.data.materials.get(name)
    if mat:
        return mat
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    bsdf = nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (*rgb, 1)
    bsdf.inputs["Roughness"].default_value = roughness
    if noise_scale:
        coord = nodes.new("ShaderNodeTexCoord")
        noise = nodes.new("ShaderNodeTexVoronoi") if noise_mix == "rock" else nodes.new("ShaderNodeTexNoise")
        noise.inputs["Scale"].default_value = noise_scale
        links.new(coord.outputs["Object"], noise.inputs["Vector"])
        ramp = nodes.new("ShaderNodeValToRGB")
        ramp.color_ramp.elements[0].color = (rgb[0] * 0.55, rgb[1] * 0.55, rgb[2] * 0.55, 1)
        ramp.color_ramp.elements[1].color = (min(1, rgb[0] * 1.35), min(1, rgb[1] * 1.35),
                                             min(1, rgb[2] * 1.35), 1)
        out = noise.outputs["Distance"] if noise_mix == "rock" else noise.outputs["Fac"]
        links.new(out, ramp.inputs["Fac"])
        links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
        bump = nodes.new("ShaderNodeBump")
        bump.inputs["Strength"].default_value = 0.6 if noise_mix == "rock" else 0.2
        links.new(out, bump.inputs["Height"])
        links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    return mat


def resample(line_xy, step):
    line = LineString(line_xy)
    n = max(2, int(math.ceil(line.length / step)) + 1)
    pts = np.array([line.interpolate(d).coords[0] for d in np.linspace(0, line.length, n)])
    return pts, np.linspace(0, line.length, n)


def frames(pts):
    tangent = np.gradient(pts, axis=0)
    tangent /= np.linalg.norm(tangent, axis=1, keepdims=True)
    return tangent, np.column_stack([-tangent[:, 1], tangent[:, 0]])


def mesh_from_grid(name, verts, rows, cols, coll, mat, closed=False):
    faces = [(i * cols + j, i * cols + j + 1, (i + 1) * cols + j + 1, (i + 1) * cols + j)
             for i in range(rows - 1) for j in range(cols - 1)]
    if closed:
        faces += [(i * cols + cols - 1, i * cols, (i + 1) * cols, (i + 1) * cols + cols - 1)
                  for i in range(rows - 1)]
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata([tuple(v) for v in verts], [], faces)
    mesh.validate()
    obj = bpy.data.objects.new(name, mesh)
    obj.data.materials.append(mat)
    coll.objects.link(obj)
    return obj


def graded_road(name, line_xy, sampler, coll, width=7.0, shoulder=1.0, min_grade=None,
                smooth_m=40.0, lift=0.12, step=2.0):
    """Road on a smoothed grade with fill slopes (2:1) down to the terrain where the
    grade is above ground, e.g. causeways over the lake. Returns the centreline z."""
    pts, along = resample(line_xy, step)
    _, normal = frames(pts)
    ground = np.array([sampler(x, y) or np.nan for x, y in pts])
    if np.isnan(ground).any():
        lrh.fail(f"{name}: centreline leaves the terrain")
    grade = ground.copy()
    if min_grade is not None:
        grade = np.maximum(grade, min_grade)
    k = max(1, int(smooth_m / step))
    padded = np.pad(grade, k, mode="edge")
    smooth = np.convolve(padded, np.ones(2 * k + 1) / (2 * k + 1), mode="valid")
    grade = np.maximum(smooth, grade - 0.4) + lift
    half = width / 2
    offsets = [-half - shoulder, -half, -half / 2, 0, half / 2, half, half + shoulder]
    crown = [0.0, 0.0, 0.05, 0.08, 0.05, 0.0, 0.0]
    surface, slopes = [], []
    for p, n, z in zip(pts, normal, grade):
        for o, c in zip(offsets, crown):
            surface.append((*(p + n * o), z + c))
        # Fill slopes: from each shoulder edge out to where a 2:1 slope meets the ground.
        for side in (-1, 1):
            edge = p + n * side * (half + shoulder)
            g = sampler(*edge) or z
            drop = max(0.0, z - g)
            foot = p + n * side * (half + shoulder + 2.0 * drop + 0.5)
            gf = sampler(*foot)
            slopes.append([(*edge, z), (*foot, (gf if gf is not None else g) - 0.05)])
    road = mesh_from_grid(f"{name}_Surface", surface, len(pts), len(offsets), coll,
                          material("Road_Gravel", (0.40, 0.38, 0.34), 0.95, 0.5))
    left = [v for i, s in enumerate(slopes) if i % 2 == 0 for v in (s[1], s[0])]
    right = [v for i, s in enumerate(slopes) if i % 2 == 1 for v in s]
    grass = material("Embankment_Grass", (0.10, 0.14, 0.05), 1.0, 0.3)
    mesh_from_grid(f"{name}_Fill_L", left, len(pts), 2, coll, grass)
    mesh_from_grid(f"{name}_Fill_R", right, len(pts), 2, coll, grass)
    return pts, grade, along


def sweep(name, pts3d, section, coll, mat):
    """Extrude a closed 2D section (lateral offset, vertical offset) along a 3D path,
    with end caps."""
    _, normal = frames(pts3d[:, :2])
    verts = [(p[0] + n[0] * o, p[1] + n[1] * o, p[2] + h)
             for p, n in zip(pts3d, normal) for o, h in section]
    rows, cols = len(pts3d), len(section)
    faces = [(i * cols + j, i * cols + (j + 1) % cols, (i + 1) * cols + (j + 1) % cols,
              (i + 1) * cols + j) for i in range(rows - 1) for j in range(cols)]
    faces += [tuple(range(cols))[::-1], tuple(range((rows - 1) * cols, rows * cols))]
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    mesh.validate()
    obj = bpy.data.objects.new(name, mesh)
    obj.data.materials.append(mat)
    coll.objects.link(obj)
    return obj


def sh34_centreline():
    geo = json.loads((lrh.INPUTS / "geometry/txdot-fannin-sh34-roadway-inventory-epsg6344.geojson")
                     .read_text())
    lines = []
    for f in geo["features"]:
        c = np.array(f["geometry"]["coordinates"])[:, :2] - [lrh.ORIGIN_E, lrh.ORIGIN_N]
        if (np.abs(c[:, 0] + 2200) < 2500).all() and (c[:, 1] > -2400).all() and (c[:, 1] < 8100).all():
            lines.append(LineString(c))
    merged = linemerge(unary_union(lines))
    if merged.geom_type != "LineString":
        merged = max(merged.geoms, key=lambda g: g.length)
    if merged.coords[0][1] > merged.coords[-1][1]:
        merged = LineString(list(merged.coords)[::-1])  # south to north
    return merged


def build_sh34(coll, sampler, water, record):
    """SH 34 on grade, with twin bridges where it crosses the lake (draft LSMP: two new
    bridges with a 12 ft pedestrian path, ~30 ft clearance near the centre)."""
    line = sh34_centreline()
    crossing = line.intersection(water)
    spans = [crossing] if crossing.geom_type == "LineString" else list(crossing.geoms)
    main = max(spans, key=lambda g: g.length)
    s0 = line.project(shapely.Point(main.coords[0])) - 60.0
    s1 = line.project(shapely.Point(main.coords[-1])) + 60.0
    s0, s1 = sorted((s0, s1))

    def piece(a, b):
        return [line.interpolate(d).coords[0] for d in np.linspace(a, b, max(2, int((b - a) / 5)))]

    # Approaches on grade (with fill where the old valley dips), clipped to the terrain.
    for label, (a, b) in (("South", (0.0, s0)), ("North", (s1, line.length))):
        part = LineString(piece(a, b))
        ok = [sampler(*part.interpolate(d).coords[0]) is not None
              for d in np.linspace(0, part.length, 50)]
        if all(ok):
            graded_road(f"SH34_{label}", part.coords, sampler, coll, width=8.0, shoulder=3.0,
                        min_grade=lrh.POOL_M + 1.5)
    # Deck profile: parabola from the abutments to 30 ft clearance + structure depth.
    pts, along = resample(piece(s0, s1), 4.0)
    za = sampler(*pts[0]) or lrh.POOL_M + 2
    zb = sampler(*pts[-1]) or lrh.POOL_M + 2
    apex = lrh.POOL_M + 9.14 + 1.8
    t = along / along[-1]
    deck = za * (1 - t) + zb * t + (apex - (za + zb) / 2) * 4 * t * (1 - t)
    concrete = material("Bridge_Concrete", (0.60, 0.59, 0.56), 0.7, 0.8)
    rail = material("Bridge_Rail", (0.70, 0.70, 0.68), 0.5)
    _, normal = frames(pts)
    deck_w, gap = 13.0, 4.0
    for side, label in ((-1, "SB"), (1, "NB")):
        off = side * (deck_w + gap) / 2
        path = np.column_stack([pts + normal * off, deck])
        sweep(f"SH34_Bridge_{label}_Deck", path,
              [(-deck_w / 2, 0), (deck_w / 2, 0), (deck_w / 2 - 1.0, -1.8), (-deck_w / 2 + 1.0, -1.8)],
              coll, concrete)
        for edge in (-1, 1):
            sweep(f"SH34_Bridge_{label}_Parapet_{'L' if edge < 0 else 'R'}", path,
                  [(edge * deck_w / 2 - 0.4 * edge, 0), (edge * deck_w / 2, 0),
                   (edge * deck_w / 2, 0.9), (edge * deck_w / 2 - 0.4 * edge, 0.9)],
                  coll, rail)
    # Bents every 40 m: cap beam and two columns per deck, founded below the lake bed.
    bents = 0
    for d in np.arange(40.0, along[-1] - 20.0, 40.0):
        i = int(np.searchsorted(along, d))
        p, n, z = pts[i], normal[i], deck[i] - 1.8
        ground = sampler(*p)
        base = (ground if ground is not None else lrh.POOL_M - 3) - 1.0
        for side in (-1, 1):
            c = p + n * side * (deck_w + gap) / 2
            for col in (-3.5, 3.5):
                cx, cy = c + n * col
                bpy.ops.mesh.primitive_cylinder_add(radius=0.7, depth=z - base,
                                                    location=(cx, cy, (z + base) / 2), vertices=12)
                obj = bpy.context.active_object
                obj.name = f"SH34_Column_{bents:03d}"
                for u in list(obj.users_collection):
                    u.objects.unlink(obj)
                coll.objects.link(obj)
                obj.data.materials.append(concrete)
            bents += 1
    record("sh34_bridges", along[-1] > 500 and bents > 10, length_m=round(float(along[-1]), 1),
           apex_deck_m=round(apex, 2), clearance_ft=30, bents=bents,
           note="schematic twin decks on the TxDOT SH 34 centreline")


def build_cr3640(coll, sampler, record):
    """Relocated CR 3640: TxDOT western approach from SH 34 + UTRWD Road Plan New
    Alignment (composite route), on grade with a causeway over the creek arm."""
    geo = json.loads((lrh.INPUTS / "geometry/cr3640-composite-context-route-epsg6344.geojson")
                     .read_text())
    c = np.array(geo["features"][0]["geometry"]["coordinates"])[:, :2] - [lrh.ORIGIN_E, lrh.ORIGIN_N]
    pts, grade, along = graded_road("CR3640", c, sampler, coll, width=7.0, shoulder=1.0,
                                    min_grade=lrh.POOL_M + 1.2)
    build_cr3640.profile = (pts, grade)          # build_baseline carves the terrain to it
    record("cr3640_new_alignment", along[-1] > 2000, length_m=round(float(along[-1]), 1),
           min_grade_m=round(float(grade.min()), 2),
           source="TxDOT CR 3640 western approach + UTRWD Road Plan New Alignment")
    return c


def dam_materials(dam):
    """Grey rock riprap on the upstream (lake) face, gravel crest, grass downstream."""
    rock = material("Dam_Riprap", (0.42, 0.41, 0.39), 0.95, 1.4, "rock")
    crest = material("Road_Gravel", (0.40, 0.38, 0.34), 0.95, 0.5)
    grass = material("Embankment_Grass", (0.10, 0.14, 0.05), 1.0, 0.3)
    dam.data.materials.clear()
    for m in (rock, crest, grass):
        dam.data.materials.append(m)
    # build_dam's profile runs along the normal (-uy, ux), i.e. east to west for this
    # north-south axis: face 0 is the downstream (east) slope, 1 the crest, 2 the
    # upstream (lake, west) slope.
    for poly in dam.data.polygons:
        poly.material_index = {0: 2, 1: 1, 2: 0}.get(poly.index, 2)
