"""Phase 3a R2: grass tufts near the low-altitude flight path (switchable: `Ground_Detail`).

The property is mown pasture (owner). From 15-40 m up, the 0.6 m imagery alone reads as
flat paint, so short grass tufts are scattered on the site terrain:
- a per-vertex density on the terrain (`grass_density`, 0-1): full within 60 m of the
  flight path (out/derived/flight_low.json), fading to 10% at 200 m; zero below pool,
  within 2.5 m of roads, drives, walks and shoreline paths, and on the cabins' mown lawn
  aprons (which have their own striped lawn material); a third under woods;
- a Geometry Nodes scatter object that reads the evaluated terrain (so it follows the
  cabins' grading shape keys), distributes up to MAX_DENSITY tufts per m2 with a fixed
  seed (no frame-to-frame flicker) and instances three mown-grass tufts and a sparse
  seed-head clump, randomly turned and scaled.
"""

import math
import random

import bpy
import numpy as np

import lrh

import shapely  # noqa: E402

MAX_DENSITY = 22.0          # tufts per m2 at full density (continuous cover up close)
NEAR_M, FAR_M = 40.0, 200.0


def blade_material():
    mat = bpy.data.materials.get("Grass_Blade")
    if mat:
        return mat
    mat = bpy.data.materials.new("Grass_Blade")
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    nodes.remove(nodes["Principled BSDF"])
    info = nodes.new("ShaderNodeObjectInfo")
    tc = nodes.new("ShaderNodeTexCoord")
    sep = nodes.new("ShaderNodeSeparateXYZ")
    links.new(tc.outputs["Generated"], sep.inputs["Vector"])
    ramp = nodes.new("ShaderNodeValToRGB")            # base -> tip within a tuft
    ramp.color_ramp.elements[0].color = (0.055, 0.10, 0.028, 1)
    ramp.color_ramp.elements[1].color = (0.13, 0.22, 0.06, 1)
    links.new(sep.outputs["Z"], ramp.inputs["Fac"])
    straw = nodes.new("ShaderNodeMix")                # some tufts drier (early fall)
    straw.data_type = "RGBA"
    straw.inputs["B"].default_value = (0.21, 0.17, 0.07, 1)
    m = nodes.new("ShaderNodeMath")
    m.operation = "MULTIPLY"
    m.inputs[1].default_value = 0.35
    links.new(info.outputs["Random"], m.inputs[0])
    links.new(m.outputs[0], straw.inputs["Factor"])
    links.new(ramp.outputs["Color"], straw.inputs["A"])
    diffuse = nodes.new("ShaderNodeBsdfDiffuse")
    trans = nodes.new("ShaderNodeBsdfTranslucent")
    links.new(straw.outputs["Result"], diffuse.inputs["Color"])
    links.new(straw.outputs["Result"], trans.inputs["Color"])
    mix = nodes.new("ShaderNodeMixShader")
    mix.inputs["Fac"].default_value = 0.3
    links.new(diffuse.outputs[0], mix.inputs[1])
    links.new(trans.outputs[0], mix.inputs[2])
    links.new(mix.outputs[0], nodes["Material Output"].inputs["Surface"])
    return mat


def tuft(name, blades, height, spread, coll, seed):
    """A clump of tapered blades (two triangles each) leaning outwards."""
    rng = random.Random(seed)
    verts, faces = [], []
    for _ in range(blades):
        a = rng.uniform(0, 2 * math.pi)
        r = rng.uniform(0, spread)
        bx, by = r * math.cos(a), r * math.sin(a)
        h = height * rng.uniform(0.6, 1.0)
        lean = rng.uniform(0.15, 0.45) * h
        la = a + rng.uniform(-0.6, 0.6)
        w = rng.uniform(0.006, 0.012)
        px, py = -math.sin(la) * w, math.cos(la) * w
        tx, ty = bx + math.cos(la) * lean, by + math.sin(la) * lean
        mx, my = bx + math.cos(la) * lean * 0.4, by + math.sin(la) * lean * 0.4
        i = len(verts)
        verts += [(bx - px, by - py, 0.0), (bx + px, by + py, 0.0),
                  (mx + px * 0.7, my + py * 0.7, h * 0.55), (mx - px * 0.7, my - py * 0.7, h * 0.55),
                  (tx, ty, h)]
        faces += [(i, i + 1, i + 2, i + 3), (i + 3, i + 2, i + 4)]
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    mesh.materials.append(blade_material())
    obj = bpy.data.objects.new(name, mesh)
    coll.objects.link(obj)
    return obj


def scatter_tree(terrain, protos, attribute="grass_density"):
    tree = bpy.data.node_groups.new(f"LRH_Grass_{attribute}", "GeometryNodeTree")
    tree.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    tree.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    n, l = tree.nodes, tree.links
    gout = n.new("NodeGroupOutput")
    info = n.new("GeometryNodeObjectInfo")
    info.transform_space = "RELATIVE"
    info.inputs["Object"].default_value = terrain
    attr = n.new("GeometryNodeInputNamedAttribute")
    attr.data_type = "FLOAT"
    attr.inputs["Name"].default_value = attribute
    dens = n.new("ShaderNodeMath")
    dens.operation = "MULTIPLY"
    dens.inputs[1].default_value = MAX_DENSITY
    l.new(attr.outputs["Attribute"], dens.inputs[0])
    dist = n.new("GeometryNodeDistributePointsOnFaces")
    dist.distribute_method = "RANDOM"
    dist.inputs["Seed"].default_value = 20261020
    l.new(info.outputs["Geometry"], dist.inputs["Mesh"])
    l.new(dens.outputs[0], dist.inputs["Density"])
    cinfo = n.new("GeometryNodeCollectionInfo")
    cinfo.inputs["Collection"].default_value = protos
    cinfo.inputs["Separate Children"].default_value = True
    cinfo.inputs["Reset Children"].default_value = True
    pick = n.new("FunctionNodeRandomValue")
    pick.data_type = "FLOAT"
    pick.inputs["Seed"].default_value = 7
    # Index into [tuft0, tuft1, tuft2, seedheads]: seed heads ~5%.
    idx = n.new("ShaderNodeMath")
    idx.operation = "FLOOR"
    m3 = n.new("ShaderNodeMath")
    m3.operation = "MULTIPLY"
    m3.inputs[1].default_value = 3.15
    l.new(pick.outputs["Value"], m3.inputs[0])
    l.new(m3.outputs[0], idx.inputs[0])
    inst = n.new("GeometryNodeInstanceOnPoints")
    inst.inputs["Pick Instance"].default_value = True
    l.new(dist.outputs["Points"], inst.inputs["Points"])
    l.new(cinfo.outputs["Instances"], inst.inputs["Instance"])
    l.new(idx.outputs[0], inst.inputs["Instance Index"])
    rot = n.new("FunctionNodeRandomValue")
    rot.data_type = "FLOAT_VECTOR"
    rot.inputs["Min"].default_value = (0, 0, 0)
    rot.inputs["Max"].default_value = (0.15, 0.15, 6.283)
    rot.inputs["Seed"].default_value = 11
    l.new(rot.outputs["Value"], inst.inputs["Rotation"])
    sc = n.new("FunctionNodeRandomValue")
    sc.data_type = "FLOAT"
    sc.inputs["Min"].default_value = 0.7
    sc.inputs["Max"].default_value = 1.35
    sc.inputs["Seed"].default_value = 13
    l.new(sc.outputs["Value"], inst.inputs["Scale"])
    l.new(inst.outputs["Instances"], gout.inputs["Geometry"])
    return tree


def build(coll, terrain, flight_path, no_grass, woods_mask, record, aprons=None):
    """coll: the `Ground_Detail` collection. flight_path: LineString (xy) or None.
    no_grass: geometry where no tuft may stand. woods_mask(x, y) -> bool array.
    aprons: {lot: polygon} - each lot's cabin lawn apron gets its own scatter in
    `Ground_Detail_BuildSite_<lot>`, which render.py hides when that lot's cabin shows."""
    co = np.empty(len(terrain.data.vertices) * 3)
    terrain.data.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)
    if flight_path is None:
        dens = np.zeros(len(co))
    else:
        d = shapely.distance(flight_path, shapely.points(co[:, 0], co[:, 1]))
        dens = np.clip(1.0 - (d - NEAR_M) / (FAR_M - NEAR_M), 0.0, 1.0) ** 1.5
        dens = np.maximum(dens, 0.12)
        dens[d > FAR_M + 50] = 0.0
    dens[co[:, 2] < lrh.POOL_M + 0.2] = 0.0
    if no_grass is not None and not no_grass.is_empty:
        dens[shapely.contains_xy(no_grass, co[:, 0], co[:, 1])] = 0.0
    if woods_mask is not None:
        dens[woods_mask(co[:, 0], co[:, 1])] *= 0.33
    aprons = aprons or {}
    apron_dens = {}
    for label, area in aprons.items():
        inside = shapely.contains_xy(area, co[:, 0], co[:, 1])
        apron_dens[label] = np.where(inside, dens, 0.0)
        dens = np.where(inside, 0.0, dens)

    def store(name, values):
        a = terrain.data.attributes.get(name) or terrain.data.attributes.new(name, "FLOAT", "POINT")
        a.data.foreach_set("value", values.astype(np.float32))

    store("grass_density", dens)
    protos = bpy.data.collections.new("Grass_Prototypes")
    coll.children.link(protos)
    protos.hide_render = True
    protos.hide_viewport = True
    for k in range(3):
        tuft(f"Grass_Tuft_{k}", 26, 0.11 + 0.025 * k, 0.12, protos, 100 + k)
    tuft("Grass_Z_Seedheads", 7, 0.38, 0.05, protos, 200)  # sorts last: index 3
    def scatter(name, attribute, target):
        obj = bpy.data.objects.new(name, bpy.data.meshes.new(name))
        target.objects.link(obj)
        mod = obj.modifiers.new("Grass", "NODES")
        mod.node_group = scatter_tree(terrain, protos, attribute)

    scatter("Grass_Scatter", "grass_density", coll)
    for label, values in apron_dens.items():
        if not values.any():
            continue
        key = label.replace(" ", "_")
        store(f"grass_apron_{key}", values)
        sub = bpy.data.collections.new(f"Ground_Detail_BuildSite_{key}")
        coll.children.link(sub)
        scatter(f"Grass_Apron_{key}", f"grass_apron_{key}", sub)
        dens = dens + values
    # Faces carry the density through the corners; estimate the tuft count from area.
    tri_area = 1.0  # the site mesh is a 1 m grid: ~1 m2 per vertex
    est = int(dens.sum() * tri_area * MAX_DENSITY)
    record("grass_tufts", est > 0, estimated_tufts=est, max_density_per_m2=MAX_DENSITY,
           full_within_m=NEAR_M, fade_to_m=FAR_M)
    return est
