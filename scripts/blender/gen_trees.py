"""Generate tree species with the Sapling Tree Gen add-on (free, GPL; installed from
extensions.blender.org, owner-approved 22 Oct 2026) and save them as reusable meshes in
assets/generated/sapling_trees.blend (git-ignored). Objects: Sap_<species>_<variant>,
origin at the base of the trunk, +Z up, real-world size (metres), bark and leaf materials
assigned. Crape myrtles get bloom clusters in four colours.

Usage: Blender -b --python-exit-code 1 --python scripts/blender/gen_trees.py
"""

import ast
import math
import random
import sys
from pathlib import Path

import addon_utils
import bpy
import bmesh
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "assets/generated/sapling_trees.blend"
PRESETS = Path(bpy.utils.user_resource("EXTENSIONS")) / "blender_org/sapling_tree_gen/presets"


def preset(name):
    text = (PRESETS / f"{name}.py").read_text()
    return ast.literal_eval(text[text.index("{"):])


# species: (base preset, overrides, target height m, bark rgb, leaf colours [(rgb, weight)])
SPECIES = {
    # Bald cypress in October: narrow spire, horizontal branches, fine feathery foliage,
    # an even soft rust-bronze; a flared, buttressed base.
    "bald_cypress": ("douglas_fir", {"scale": 14.0, "scaleV": 2.0, "rootFlare": 2.2,
                                     "leaves": 110, "leafScale": 0.12, "leafScaleX": 0.4,
                                     "leafShape": "rect", "showLeaves": True,
                                     "downAngle": (90.0, 95.0, 45.0, 45.0)}, 12.0,
                     (0.17, 0.11, 0.08),
                     [((0.36, 0.13, 0.04), 0.55), ((0.42, 0.20, 0.06), 0.30), ((0.20, 0.18, 0.06), 0.15)]),
    # Eastern redbud: low, often multi-stem, broad flat crown; heart leaves yellow in fall.
    "redbud": ("small_maple", {"scale": 6.0, "baseSplits": 2, "showLeaves": True, "leaves": 18,
                               "leafScale": 0.16}, 6.0, (0.11, 0.08, 0.07),
               [((0.42, 0.32, 0.05), 0.6), ((0.25, 0.25, 0.05), 0.4)]),
    # Crape myrtle: multi-trunk vase, smooth cinnamon bark; blooms added per colour.
    "crape_myrtle": ("japanese_maple", {"scale": 5.5, "baseSplits": 4, "showLeaves": True,
                                        "leaves": 40, "leafScale": 0.16, "leafScaleX": 0.6,
                                        "attractUp": (0.0, 0.25, 0.1, 0.0)}, 5.0,
                     (0.32, 0.18, 0.11),
                     [((0.07, 0.11, 0.035), 0.6), ((0.40, 0.12, 0.04), 0.4)]),
    # Red maple ('October Glory'-type) in full scarlet.
    "red_maple": ("small_maple", {"scale": 9.0, "showLeaves": True, "leaves": 22,
                                  "leafScale": 0.18}, 8.0, (0.17, 0.16, 0.15),
                  [((0.50, 0.035, 0.02), 0.7), ((0.56, 0.15, 0.02), 0.3)]),
    "japanese_maple": ("japanese_maple", {"showLeaves": True, "leaves": 35, "leafScale": 0.15}, 3.5, (0.13, 0.08, 0.07),
                       [((0.30, 0.015, 0.02), 0.85), ((0.45, 0.05, 0.03), 0.15)]),
    # Peach: short open vase, fall leaves yellow-orange.
    "peach": ("japanese_maple", {"scale": 4.0, "baseSplits": 3, "showLeaves": True,
                                 "leaves": 35, "leafScale": 0.15, "leafScaleX": 0.35}, 3.5, (0.08, 0.06, 0.05),
              [((0.50, 0.26, 0.04), 0.6), ((0.16, 0.18, 0.04), 0.4)]),
    # Mexican plum: small, often leaning, irregular crown; orange-red fall colour.
    "mexican_plum": ("small_maple", {"scale": 5.5, "baseSplits": 1, "showLeaves": True,
                                     "leaves": 16, "leafScale": 0.14, "curveV": (60.0, 80.0, 60.0, 0.0)},
                     5.5, (0.15, 0.12, 0.11),
                     [((0.48, 0.16, 0.03), 0.45), ((0.40, 0.30, 0.05), 0.35), ((0.15, 0.15, 0.04), 0.2)]),
}
BLOOMS = {"white": (0.78, 0.76, 0.74), "pink": (0.70, 0.20, 0.38), "watermelon": (0.62, 0.04, 0.14),
          "lavender": (0.40, 0.25, 0.55)}
VARIANTS = 3


def mat(name, rgb, rough=0.7):
    m = bpy.data.materials.get(name)
    if m:
        return m
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (*rgb, 1)
    b.inputs["Roughness"].default_value = rough
    return m


def leaf_mat(name, rgb):
    """Leaves: diffuse + translucency, per-face random value jitter."""
    m = bpy.data.materials.get(name)
    if m:
        return m
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nodes, links = m.node_tree.nodes, m.node_tree.links
    nodes.remove(nodes["Principled BSDF"])
    info = nodes.new("ShaderNodeObjectInfo")
    geo = nodes.new("ShaderNodeNewGeometry")
    ramp = nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].color = (rgb[0] * 0.7, rgb[1] * 0.7, rgb[2] * 0.7, 1)
    ramp.color_ramp.elements[1].color = (min(1, rgb[0] * 1.3), min(1, rgb[1] * 1.3), min(1, rgb[2] * 1.3), 1)
    add = nodes.new("ShaderNodeMath")
    add.operation = "FRACT"
    plus = nodes.new("ShaderNodeMath")
    links.new(info.outputs["Random"], plus.inputs[0])
    links.new(geo.outputs["Random Per Island"], plus.inputs[1])
    links.new(plus.outputs[0], add.inputs[0])
    links.new(add.outputs[0], ramp.inputs["Fac"])
    dif = nodes.new("ShaderNodeBsdfDiffuse")
    tr = nodes.new("ShaderNodeBsdfTranslucent")
    links.new(ramp.outputs["Color"], dif.inputs["Color"])
    links.new(ramp.outputs["Color"], tr.inputs["Color"])
    mix = nodes.new("ShaderNodeMixShader")
    mix.inputs["Fac"].default_value = 0.3
    links.new(dif.outputs[0], mix.inputs[1])
    links.new(tr.outputs[0], mix.inputs[2])
    links.new(mix.outputs[0], nodes["Material Output"].inputs["Surface"])
    return m


def generate(species, variant, bloom=None):
    base, over, height, bark, leaves = SPECIES[species]
    params = preset(base)
    params.update(over)
    params["seed"] = 1000 * variant + hash(species) % 997
    params["bevel"] = True
    params["makeMesh"] = False
    for k in list(params):
        if k not in {p.identifier for p in bpy.ops.curve.tree_add.get_rna_type().properties}:
            params.pop(k)
    before = set(bpy.data.objects)
    bpy.ops.curve.tree_add(**params)
    new = [o for o in bpy.data.objects if o not in before]
    trunk = next(o for o in new if o.type == "CURVE")
    leaf_objs = [o for o in new if o.type == "MESH"]
    # Curve -> mesh.
    bpy.ops.object.select_all(action="DESELECT")
    trunk.select_set(True)
    bpy.context.view_layer.objects.active = trunk
    trunk.data.bevel_resolution = 1
    trunk.data.resolution_u = 2
    bpy.ops.object.convert(target="MESH")
    trunk = bpy.context.view_layer.objects.active
    trunk.data.materials.clear()
    trunk.data.materials.append(mat(f"Sap_{species}_bark", bark, 0.85))
    rng = random.Random(f"{species}-{variant}")
    for lo in leaf_objs:
        lo.data.materials.clear()
        mats = [leaf_mat(f"Sap_{species}_leaf_{i}", c) for i, (c, _) in enumerate(leaves)]
        if bloom:
            mats.append(leaf_mat(f"Sap_bloom_{bloom}", BLOOMS[bloom]))
        for m in mats:
            lo.data.materials.append(m)
        weights = [w for _, w in leaves]
        for p in lo.data.polygons:
            if bloom and rng.random() < 0.38:
                p.material_index = len(mats) - 1
            else:
                p.material_index = rng.choices(range(len(leaves)), weights)[0]
    # Join, base at origin, scale to target height.
    bpy.ops.object.select_all(action="DESELECT")
    for o in [trunk] + leaf_objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = trunk
    bpy.ops.object.join()
    obj = bpy.context.view_layer.objects.active
    obj.data.transform(obj.matrix_world)
    obj.matrix_world.identity()
    co = np.array([v.co[:] for v in obj.data.vertices])
    zmin, zmax = co[:, 2].min(), co[:, 2].max()
    s = height / max(1e-6, zmax - zmin)
    from mathutils import Matrix
    obj.data.transform(Matrix.Translation((0, 0, -zmin)))
    obj.data.transform(Matrix.Scale(s, 4))
    obj.name = f"Sap_{species}{'_' + bloom if bloom else ''}_{variant}"
    obj.data.name = obj.name
    obj.location = (0, 0, 0)
    return obj, len(obj.data.polygons)


def main():
    addon_utils.enable("bl_ext.blender_org.sapling_tree_gen", default_set=True)
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)
    made = []
    for species in SPECIES:
        blooms = list(BLOOMS) if species == "crape_myrtle" else [None]
        for bloom in blooms:
            for v in range(VARIANTS if bloom is None else 2):
                obj, n = generate(species, v, bloom)
                obj.location = (len(made) * 12.0, 0, 0)
                made.append((obj.name, n))
                print("MADE", obj.name, n, "faces")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    for o in bpy.data.objects:
        o.location = (0, 0, 0)
    bpy.ops.wm.save_as_mainfile(filepath=str(OUT))
    print("SAVED", OUT, len(made), "trees")


if __name__ == "__main__":
    main()
