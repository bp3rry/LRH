"""Procedural tree prototypes for the LRH baseline (CC0 by construction: made here).

Each prototype is a trunk with a few scaffold branches and a crown of jittered leaf
clusters shaped per species. Foliage uses a noise alpha cut-out so crowns read as
leaf masses with gaps rather than solid blobs. Prototypes are hidden objects; the
scatter instances them (never realised geometry, PLAN.md §6).

Species palette from the drone photo: post oak, cedar elm, eastern red cedar, bois d'arc.
"""

import math
import random

import bmesh
import bpy
from mathutils import Matrix, Vector

# height_m and crown radius_m are the prototype's own size; instances scale from it.
SPECIES = {
    "post_oak": {"height": 12.0, "crown_radius": 6.0, "crown_base": 0.30, "shape": "round",
                 "clusters": 26, "leaf": (0.10, 0.17, 0.05), "heights": (9.0, 15.0)},
    "cedar_elm": {"height": 14.0, "crown_radius": 5.0, "crown_base": 0.35, "shape": "oval",
                  "clusters": 24, "leaf": (0.12, 0.19, 0.06), "heights": (10.0, 18.0)},
    "red_cedar": {"height": 8.0, "crown_radius": 2.2, "crown_base": 0.05, "shape": "cone",
                  "clusters": 18, "leaf": (0.05, 0.10, 0.06), "heights": (4.0, 10.0)},
    "bois_darc": {"height": 10.0, "crown_radius": 5.5, "crown_base": 0.30, "shape": "spread",
                  "clusters": 22, "leaf": (0.11, 0.18, 0.04), "heights": (7.0, 12.0)},
}
VARIANTS = 3


def bark_material():
    mat = bpy.data.materials.get("Tree_Bark")
    if mat:
        return mat
    mat = bpy.data.materials.new("Tree_Bark")
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (0.09, 0.07, 0.05, 1)
    bsdf.inputs["Roughness"].default_value = 0.9
    return mat


def foliage_material(species, rgb):
    name = f"Foliage_{species}"
    if name in bpy.data.materials:
        return bpy.data.materials[name]
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    nodes.remove(nodes["Principled BSDF"])
    out = nodes["Material Output"]
    info = nodes.new("ShaderNodeObjectInfo")
    # Per-instance hue/value variation.
    ramp = nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].color = (rgb[0] * 0.75, rgb[1] * 0.8, rgb[2] * 0.7, 1)
    ramp.color_ramp.elements[1].color = (rgb[0] * 1.35, rgb[1] * 1.25, rgb[2] * 1.2, 1)
    links.new(info.outputs["Random"], ramp.inputs["Fac"])
    diffuse = nodes.new("ShaderNodeBsdfDiffuse")
    translucent = nodes.new("ShaderNodeBsdfTranslucent")
    links.new(ramp.outputs["Color"], diffuse.inputs["Color"])
    links.new(ramp.outputs["Color"], translucent.inputs["Color"])
    leaf = nodes.new("ShaderNodeMixShader")
    leaf.inputs["Fac"].default_value = 0.25
    links.new(diffuse.outputs[0], leaf.inputs[1])
    links.new(translucent.outputs[0], leaf.inputs[2])
    # Leaf-mass cut-out: holes at ~0.3 m scale.
    coord = nodes.new("ShaderNodeTexCoord")
    noise = nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 2.2
    noise.inputs["Detail"].default_value = 4.0
    links.new(coord.outputs["Object"], noise.inputs["Vector"])
    cut = nodes.new("ShaderNodeMath")
    cut.operation = "GREATER_THAN"
    cut.inputs[1].default_value = 0.47
    links.new(noise.outputs["Fac"], cut.inputs[0])
    transparent = nodes.new("ShaderNodeBsdfTransparent")
    final = nodes.new("ShaderNodeMixShader")
    links.new(cut.outputs[0], final.inputs["Fac"])
    links.new(transparent.outputs[0], final.inputs[1])
    links.new(leaf.outputs[0], final.inputs[2])
    links.new(final.outputs[0], out.inputs["Surface"])
    return mat


def crown_point(shape, rng):
    """A point in the unit crown envelope (radius 1, height 0..1)."""
    while True:
        x, y, z = rng.uniform(-1, 1), rng.uniform(-1, 1), rng.uniform(0, 1)
        r = math.hypot(x, y)
        if shape == "round" and r * r + (2 * z - 1) ** 2 <= 1:
            return x, y, z
        if shape == "oval" and (r / 0.85) ** 2 + (2 * z - 1) ** 2 <= 1:
            return x, y, z
        if shape == "cone" and r <= (1 - z) * 1.05:
            return x, y, z
        if shape == "spread" and r * r + ((2 * z - 1) / 0.75) ** 2 <= 1:
            return x, y, z


def make_prototype(species, variant, collection):
    spec = SPECIES[species]
    rng = random.Random(f"{species}-{variant}")
    height, radius = spec["height"], spec["crown_radius"]
    base = spec["crown_base"] * height
    crown_h = height - base
    bm = bmesh.new()
    trunk_r = 0.035 * height
    trunk_top = base + crown_h * (0.25 if spec["shape"] != "cone" else 0.8)
    bmesh.ops.create_cone(bm, cap_ends=True, segments=8, radius1=trunk_r,
                          radius2=trunk_r * 0.55, depth=trunk_top,
                          matrix=Matrix.Translation((0, 0, trunk_top / 2)))
    trunk_faces = len(bm.faces)
    if spec["shape"] != "cone":
        for i in range(4):
            angle = i * math.pi / 2 + rng.uniform(-0.4, 0.4)
            tilt = rng.uniform(0.5, 0.9)
            length = crown_h * rng.uniform(0.45, 0.6)
            rot = Matrix.Rotation(angle, 4, "Z") @ Matrix.Rotation(tilt, 4, "Y")
            mat = Matrix.Translation((0, 0, trunk_top * 0.9)) @ rot @ \
                Matrix.Translation((0, 0, length / 2))
            bmesh.ops.create_cone(bm, cap_ends=True, segments=6, radius1=trunk_r * 0.5,
                                  radius2=trunk_r * 0.15, depth=length, matrix=mat)
    bark_faces = len(bm.faces)
    for _ in range(spec["clusters"]):
        x, y, z = crown_point(spec["shape"], rng)
        size = radius * rng.uniform(0.28, 0.42) * (0.6 if spec["shape"] == "cone" else 1.0)
        center = Vector((x * radius, y * radius, base + z * crown_h))
        geom = bmesh.ops.create_icosphere(bm, subdivisions=2, radius=size,
                                          matrix=Matrix.Translation(center))
        for v in geom["verts"]:
            v.co += Vector((rng.uniform(-1, 1), rng.uniform(-1, 1), rng.uniform(-1, 1))) * size * 0.18
    mesh = bpy.data.meshes.new(f"Tree_{species}_{variant}")
    bm.to_mesh(mesh)
    bm.free()
    mesh.materials.append(bark_material())
    mesh.materials.append(foliage_material(species, spec["leaf"]))
    for poly in mesh.polygons:
        poly.material_index = 0 if poly.index < bark_faces else 1
        poly.use_smooth = poly.index >= trunk_faces
    obj = bpy.data.objects.new(mesh.name, mesh)
    collection.objects.link(obj)
    obj["species"] = species
    obj["prototype_height_m"] = height
    return obj


def snag_material():
    mat = bpy.data.materials.get("Snag_Bark")
    if mat:
        return mat
    mat = bpy.data.materials.new("Snag_Bark")
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (0.24, 0.21, 0.21, 1)  # weathered mauve-grey
    bsdf.inputs["Roughness"].default_value = 0.95
    return mat


def make_snag(variant, collection, height=12.0):
    """A dead, leafless hardwood: trunk, scaffold limbs and a second order of branches.
    Permanently flooded post oak and elm die within a few seasons and stand as snags."""
    rng = random.Random(f"snag-{variant}")
    anchors = []  # points on the limbs where Spanish moss can hang
    bm = bmesh.new()
    trunk_r = 0.035 * height
    trunk_top = height * rng.uniform(0.45, 0.75)  # many drowned trees lose their tops
    bmesh.ops.create_cone(bm, cap_ends=True, segments=7, radius1=trunk_r, radius2=trunk_r * 0.45,
                          depth=trunk_top, matrix=Matrix.Translation((0, 0, trunk_top / 2)))
    for i in range(rng.randint(4, 7)):
        angle = i * 2 * math.pi / 6 + rng.uniform(-0.6, 0.6)
        tilt = rng.uniform(0.55, 1.3)  # spreading, near-horizontal limbs
        length = height * rng.uniform(0.15, 0.4) * (0.5 if rng.random() < 0.3 else 1.0)
        start = trunk_top * rng.uniform(0.55, 1.0)
        rot = Matrix.Rotation(angle, 4, "Z") @ Matrix.Rotation(tilt, 4, "Y")
        bmesh.ops.create_cone(bm, cap_ends=True, segments=5, radius1=trunk_r * 0.4,
                              radius2=trunk_r * 0.08, depth=length,
                              matrix=Matrix.Translation((0, 0, start)) @ rot @
                              Matrix.Translation((0, 0, length / 2)))
        tip = Matrix.Translation((0, 0, start)) @ rot @ Vector((0, 0, length * 0.7))
        anchors += [tuple(Matrix.Translation((0, 0, start)) @ rot @ Vector((0, 0, length * f)))
                    for f in (0.4, 0.7, 0.95)]
        for _ in range(2):
            sub = Matrix.Rotation(angle + rng.uniform(-1, 1), 4, "Z") @ \
                Matrix.Rotation(rng.uniform(0.2, 0.9), 4, "Y")
            sub_len = length * rng.uniform(0.35, 0.55)
            bmesh.ops.create_cone(bm, cap_ends=True, segments=4, radius1=trunk_r * 0.12,
                                  radius2=trunk_r * 0.03, depth=sub_len,
                                  matrix=Matrix.Translation(tip) @ sub @
                                  Matrix.Translation((0, 0, sub_len / 2)))
            anchors.append(tuple(Matrix.Translation(tip) @ sub @ Vector((0, 0, sub_len * 0.8))))
    mesh = bpy.data.meshes.new(f"Snag_{variant}")
    bm.to_mesh(mesh)
    bm.free()
    mesh.materials.append(snag_material())
    obj = bpy.data.objects.new(mesh.name, mesh)
    collection.objects.link(obj)
    obj["prototype_height_m"] = height
    obj["moss_anchors"] = [c for a in anchors for c in a]
    return obj


def moss_material():
    mat = bpy.data.materials.get("Spanish_Moss")
    if mat:
        return mat
    mat = bpy.data.materials.new("Spanish_Moss")
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    nodes.remove(nodes["Principled BSDF"])
    out = nodes["Material Output"]
    diffuse = nodes.new("ShaderNodeBsdfDiffuse")
    diffuse.inputs["Color"].default_value = (0.42, 0.44, 0.38, 1)  # silver grey-green
    translucent = nodes.new("ShaderNodeBsdfTranslucent")
    translucent.inputs["Color"].default_value = (0.40, 0.43, 0.32, 1)
    mix = nodes.new("ShaderNodeMixShader")
    mix.inputs["Fac"].default_value = 0.3
    links.new(diffuse.outputs[0], mix.inputs[1])
    links.new(translucent.outputs[0], mix.inputs[2])
    # Wispy strands: thin vertical bands cut out of each hanging card.
    coord = nodes.new("ShaderNodeTexCoord")
    wave = nodes.new("ShaderNodeTexWave")
    wave.inputs["Scale"].default_value = 9.0
    wave.inputs["Distortion"].default_value = 6.0
    links.new(coord.outputs["UV"], wave.inputs["Vector"])
    cut = nodes.new("ShaderNodeMath")
    cut.operation = "GREATER_THAN"
    cut.inputs[1].default_value = 0.3
    links.new(wave.outputs["Fac"], cut.inputs[0])
    # Ragged ends: strands stop at a noisy height, so cards do not end in straight edges.
    stretch = nodes.new("ShaderNodeMapping")
    stretch.inputs["Scale"].default_value = (14.0, 2.0, 1.0)
    links.new(coord.outputs["UV"], stretch.inputs["Vector"])
    ragged = nodes.new("ShaderNodeTexNoise")
    ragged.inputs["Scale"].default_value = 1.0
    links.new(stretch.outputs["Vector"], ragged.inputs["Vector"])
    v = nodes.new("ShaderNodeSeparateXYZ")
    links.new(coord.outputs["UV"], v.inputs["Vector"])
    reach = nodes.new("ShaderNodeMath")
    reach.operation = "MULTIPLY"
    reach.inputs[1].default_value = 0.9
    links.new(ragged.outputs["Fac"], reach.inputs[0])
    keep = nodes.new("ShaderNodeMath")
    keep.operation = "GREATER_THAN"
    links.new(v.outputs["Y"], keep.inputs[0])  # V = 1 at the limb, 0 at the tip
    links.new(reach.outputs[0], keep.inputs[1])
    both = nodes.new("ShaderNodeMath")
    both.operation = "MULTIPLY"
    links.new(cut.outputs[0], both.inputs[0])
    links.new(keep.outputs[0], both.inputs[1])
    cut = both
    transparent = nodes.new("ShaderNodeBsdfTransparent")
    final = nodes.new("ShaderNodeMixShader")
    links.new(cut.outputs[0], final.inputs["Fac"])
    links.new(transparent.outputs[0], final.inputs[1])
    links.new(mix.outputs[0], final.inputs[2])
    links.new(final.outputs[0], out.inputs["Surface"])
    return mat


def make_moss(snag, collection):
    """Spanish moss (Tillandsia usneoides) beards hanging from a snag's limbs, built in the
    snag's own space so it can be instanced with the same transforms."""
    rng = random.Random(f"moss-{snag.name}")
    a = snag["moss_anchors"]
    anchors = [Vector(a[i:i + 3]) for i in range(0, len(a), 3)]
    verts, faces, uvs = [], [], []
    for anchor in anchors:
        if rng.random() < 0.15:
            continue
        for _ in range(rng.randint(4, 7)):
            length = rng.uniform(1.0, 2.6)
            width = rng.uniform(0.3, 0.6)
            angle = rng.uniform(0, math.pi)
            dx, dy = math.cos(angle) * width / 2, math.sin(angle) * width / 2
            sway = Vector((rng.uniform(-0.15, 0.15), rng.uniform(-0.15, 0.15), 0))
            top = anchor + Vector((rng.uniform(-0.3, 0.3), rng.uniform(-0.3, 0.3), 0))
            base = len(verts)
            for k, f in enumerate((0.0, 0.5, 1.0)):
                c = top + Vector((0, 0, -length * f)) + sway * f
                taper = 1.0 - 0.6 * f
                verts += [c + Vector((-dx, -dy, 0)) * taper, c + Vector((dx, dy, 0)) * taper]
                uvs += [(0.0, 1 - f), (1.0, 1 - f)]
            faces += [(base, base + 1, base + 3, base + 2), (base + 2, base + 3, base + 5, base + 4)]
    mesh = bpy.data.meshes.new(f"Moss_{snag.name}")
    mesh.from_pydata([tuple(v) for v in verts], [], faces)
    uv = mesh.uv_layers.new(name="UVMap")
    for loop in mesh.loops:
        uv.data[loop.index].uv = uvs[loop.vertex_index]
    mesh.materials.append(moss_material())
    obj = bpy.data.objects.new(mesh.name, mesh)
    collection.objects.link(obj)
    return obj


# Flooded-timber colours from the owner's reference, Bois d'Arc Lake two seasons after
# impoundment (NAIP 2024, inputs/reference/bois_darc_creek_naip2024*.jpg): the dead
# interior is a twiggy mauve-grey canopy; a narrow fringe along the waterline is rust.
TIMBER_COLOURS = {"dying": ((0.16, 0.05, 0.025), (0.32, 0.11, 0.05), 0.6),  # rust fringe
                  "bare": ((0.19, 0.165, 0.175), (0.34, 0.30, 0.31), 0.62)}  # grey twigs


def _variant(prototype, collection, kind):
    lo, hi, cut_value = TIMBER_COLOURS[kind]
    name = f"Foliage_{kind}"
    mat = bpy.data.materials.get(name)
    if mat is None:
        mat = prototype.data.materials[1].copy()
        mat.name = name
        nodes = mat.node_tree.nodes
        ramp = next(n for n in nodes if n.bl_idname == "ShaderNodeValToRGB")
        ramp.color_ramp.elements[0].color = (*lo, 1)
        ramp.color_ramp.elements[1].color = (*hi, 1)
        cut = next(n for n in nodes if n.bl_idname == "ShaderNodeMath")
        cut.inputs[1].default_value = cut_value  # sparser crowns
    mesh = prototype.data.copy()
    mesh.name = f"{prototype.data.name}_{kind}"
    mesh.materials[1] = mat
    obj = bpy.data.objects.new(f"{prototype.name}_{kind}", mesh)
    collection.objects.link(obj)
    obj["prototype_height_m"] = prototype["prototype_height_m"]
    return obj


def make_dying(prototype, collection):
    """A prototype copy with thin rust-brown foliage: a flooded hardwood dying in the
    shallow fringe along the waterline."""
    return _variant(prototype, collection, "dying")


def make_bare(prototype, collection):
    """A prototype copy whose sparse 'foliage' reads as a twiggy grey crown of bare
    branches: a flooded hardwood dead a season or two."""
    return _variant(prototype, collection, "bare")


def make_prototypes(collection):
    return {species: [make_prototype(species, v, collection) for v in range(VARIANTS)]
            for species in SPECIES}
