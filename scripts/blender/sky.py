"""Phase 3a R4: a cloud layer under the physical sky (switchable: `Clouds`).

Scattered fair-weather cumulus and some higher wisps for a golden-hour sky, as two large
planes (1.6 km and 4.5 km up, 60 km across) with a procedural cloud shader: layered noise
thresholded into soft cloud shapes, translucent white-grey so the low sun warms their
undersides. Cheap to render (no volumetrics) and the same in every frame (no flicker).
"""

import bpy

import lrh


def cloud_material(name, scale, cover, density, tint=(1.0, 1.0, 1.0)):
    mat = bpy.data.materials.get(name)
    if mat:
        return mat
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    nodes.remove(nodes["Principled BSDF"])
    out = nodes["Material Output"]
    tc = nodes.new("ShaderNodeTexCoord")
    big = nodes.new("ShaderNodeTexNoise")
    big.inputs["Scale"].default_value = scale
    big.inputs["Detail"].default_value = 8.0
    big.inputs["Roughness"].default_value = 0.62
    links.new(tc.outputs["Object"], big.inputs["Vector"])
    ramp = nodes.new("ShaderNodeValToRGB")                 # cover: where noise > threshold
    ramp.color_ramp.elements[0].position = cover
    ramp.color_ramp.elements[1].position = cover + 0.12
    ramp.color_ramp.elements[0].color = (0, 0, 0, 1)
    ramp.color_ramp.elements[1].color = (density, density, density, 1)
    links.new(big.outputs["Fac"], ramp.inputs["Fac"])
    diffuse = nodes.new("ShaderNodeBsdfTranslucent")
    diffuse.inputs["Color"].default_value = (*tint, 1)
    lit = nodes.new("ShaderNodeBsdfDiffuse")
    lit.inputs["Color"].default_value = (*tint, 1)
    body = nodes.new("ShaderNodeMixShader")
    body.inputs["Fac"].default_value = 0.5
    links.new(diffuse.outputs[0], body.inputs[1])
    links.new(lit.outputs[0], body.inputs[2])
    clear = nodes.new("ShaderNodeBsdfTransparent")
    mix = nodes.new("ShaderNodeMixShader")
    links.new(ramp.outputs["Color"], mix.inputs["Fac"])
    links.new(clear.outputs[0], mix.inputs[1])
    links.new(body.outputs[0], mix.inputs[2])
    links.new(mix.outputs[0], out.inputs["Surface"])
    return mat


def plane(name, z, size, mat, coll, shadows=False):
    h = size / 2
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata([(-h, -h, z), (h, -h, z), (h, h, z), (-h, h, z)], [], [(0, 1, 2, 3)])
    mesh.materials.append(mat)
    obj = bpy.data.objects.new(name, mesh)
    obj.visible_shadow = shadows               # cloud shadows would blotch the property
    coll.objects.link(obj)
    return obj


def build(coll, record):
    plane("Clouds_Cumulus", lrh.POOL_M + 1600.0, 60000.0,
          cloud_material("Cloud_Cumulus", 0.00045, 0.56, 0.95), coll)
    plane("Clouds_Cirrus", lrh.POOL_M + 4500.0, 90000.0,
          cloud_material("Cloud_Cirrus", 0.00012, 0.52, 0.55), coll)
    record("clouds", True, layers=["cumulus 1.6 km", "cirrus 4.5 km"], shadows=False)


def world_clouds(scene, cover=0.47, scale=0.45, strength=1.9):
    """Clouds painted into the world shader over the physical sky: noise on the view
    direction projected onto a cloud deck (x/z, y/z), faded toward the horizon. Being part
    of the world (no depth), they sit behind the compositor haze untouched, and cost
    nothing to render. Cloud colour is the sky's own brightness, desaturated and warmed,
    so it follows the sun position (golden at low sun)."""
    tree = scene.world.node_tree
    nodes, links = tree.nodes, tree.links
    if nodes.get("LRH_Clouds"):
        return
    sky = next(n for n in nodes if n.bl_idname == "ShaderNodeTexSky")
    bg = next(n for n in nodes if n.bl_idname == "ShaderNodeBackground")
    tc = nodes.new("ShaderNodeTexCoord")
    sep = nodes.new("ShaderNodeSeparateXYZ")
    links.new(tc.outputs["Generated"], sep.inputs["Vector"])

    def math(op, a, b=None):
        n = nodes.new("ShaderNodeMath")
        n.operation = op
        for i, v in enumerate((a, b)):
            if v is None:
                continue
            if isinstance(v, (int, float)):
                n.inputs[i].default_value = v
            else:
                links.new(v, n.inputs[i])
        return n.outputs[0]
    zc = math("MAXIMUM", sep.outputs["Z"], 0.02)
    comb = nodes.new("ShaderNodeCombineXYZ")
    links.new(math("DIVIDE", sep.outputs["X"], zc), comb.inputs["X"])
    links.new(math("DIVIDE", sep.outputs["Y"], zc), comb.inputs["Y"])
    noise = nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = scale
    noise.inputs["Detail"].default_value = 7.0
    noise.inputs["Roughness"].default_value = 0.6
    links.new(comb.outputs["Vector"], noise.inputs["Vector"])
    ramp = nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].position = cover
    ramp.color_ramp.elements[1].position = cover + 0.14
    links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
    horizon = nodes.new("ShaderNodeMapRange")                  # fade out near the horizon
    horizon.inputs["From Min"].default_value = 0.005
    horizon.inputs["From Max"].default_value = 0.06
    links.new(sep.outputs["Z"], horizon.inputs["Value"])
    fac = math("MULTIPLY", math("MULTIPLY", ramp.outputs["Color"], horizon.outputs["Result"]), 0.9)
    bw = nodes.new("ShaderNodeRGBToBW")
    links.new(sky.outputs["Color"], bw.inputs["Color"])
    luma = math("MULTIPLY", bw.outputs["Val"], strength)
    warm = nodes.new("ShaderNodeCombineColor")
    for ch, w in (("Red", 1.0), ("Green", 0.9), ("Blue", 0.8)):
        links.new(math("MULTIPLY", luma, w), warm.inputs[ch])
    mix = nodes.new("ShaderNodeMix")
    mix.name = "LRH_Clouds"
    mix.data_type = "RGBA"
    links.new(fac, mix.inputs["Factor"])
    links.new(sky.outputs["Color"], mix.inputs["A"])
    links.new(warm.outputs["Color"], mix.inputs["B"])
    links.new(mix.outputs["Result"], bg.inputs["Color"])
