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
    bsdf.inputs["Base Color"].default_value = (0.22, 0.21, 0.19, 1)  # weathered grey
    bsdf.inputs["Roughness"].default_value = 0.95
    return mat


def make_snag(variant, collection, height=12.0):
    """A dead, leafless hardwood: trunk, scaffold limbs and a second order of branches.
    Permanently flooded post oak and elm die within a few seasons and stand as snags."""
    rng = random.Random(f"snag-{variant}")
    bm = bmesh.new()
    trunk_r = 0.035 * height
    trunk_top = height * rng.uniform(0.55, 0.7)
    bmesh.ops.create_cone(bm, cap_ends=True, segments=7, radius1=trunk_r, radius2=trunk_r * 0.45,
                          depth=trunk_top, matrix=Matrix.Translation((0, 0, trunk_top / 2)))
    for i in range(rng.randint(5, 7)):
        angle = i * 2 * math.pi / 6 + rng.uniform(-0.5, 0.5)
        tilt = rng.uniform(0.35, 1.0)
        length = height * rng.uniform(0.25, 0.45)
        start = trunk_top * rng.uniform(0.55, 1.0)
        rot = Matrix.Rotation(angle, 4, "Z") @ Matrix.Rotation(tilt, 4, "Y")
        bmesh.ops.create_cone(bm, cap_ends=True, segments=5, radius1=trunk_r * 0.4,
                              radius2=trunk_r * 0.08, depth=length,
                              matrix=Matrix.Translation((0, 0, start)) @ rot @
                              Matrix.Translation((0, 0, length / 2)))
        tip = Matrix.Translation((0, 0, start)) @ rot @ Vector((0, 0, length * 0.7))
        for _ in range(2):
            sub = Matrix.Rotation(angle + rng.uniform(-1, 1), 4, "Z") @ \
                Matrix.Rotation(rng.uniform(0.2, 0.9), 4, "Y")
            sub_len = length * rng.uniform(0.35, 0.55)
            bmesh.ops.create_cone(bm, cap_ends=True, segments=4, radius1=trunk_r * 0.12,
                                  radius2=trunk_r * 0.03, depth=sub_len,
                                  matrix=Matrix.Translation(tip) @ sub @
                                  Matrix.Translation((0, 0, sub_len / 2)))
    mesh = bpy.data.meshes.new(f"Snag_{variant}")
    bm.to_mesh(mesh)
    bm.free()
    mesh.materials.append(snag_material())
    obj = bpy.data.objects.new(mesh.name, mesh)
    collection.objects.link(obj)
    obj["prototype_height_m"] = height
    return obj


def make_prototypes(collection):
    return {species: [make_prototype(species, v, collection) for v in range(VARIANTS)]
            for species in SPECIES}
