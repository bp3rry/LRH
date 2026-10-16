"""Life on the lake (owner, 16 Oct 2026): a ski boat towing a skier, its wake, and gulls.

Everything is procedural (made here, no third-party assets) and sized for aerial views,
where a 6.5 m boat is ~15-20 px and its wake reads far larger. Placement rules:
- the boat runs on open main lake (Open Recreation), >100 m from shore (the draft LSMP
  makes all water within 200 ft of the shoreline no-wake) and far from the timbered
  creek arm, which is a no-wake Fish and Wildlife Habitat zone;
- gulls are ring-billed gulls, common on North Texas lakes October to March.
"""

import math
import random

import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Vector

import lrh

BOAT_XY = (679.0, 733.0)       # open lake, 259 m from shore, on the G_golden_hour sun line
BOAT_HEADING_DEG = 315.0       # compass heading, toward the north-west
ROPE_M = 22.0                  # slalom-length tow rope
WAKE_HALF_ANGLE_DEG = 19.47    # Kelvin wedge
WAKE_LENGTH_M = 160.0
# Gull flock: centre and spread (LRH local metres); the golden-hour view looks through it.
GULLS = {"centre": (1100.0, 868.0, 316.0), "spread": (16.0, 11.0, 4.0), "count": 14,
         "heading_deg": 160.0}


def material(name, rgb, roughness=0.5, metallic=0.0):
    mat = bpy.data.materials.get(name)
    if mat:
        return mat
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (*rgb, 1)
    bsdf.inputs["Roughness"].default_value = roughness
    bsdf.inputs["Metallic"].default_value = metallic
    return mat


def to_object(bm, name, coll, mats, face_mat=None):
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    for m in mats:
        mesh.materials.append(m)
    if face_mat:
        for poly in mesh.polygons:
            poly.material_index = face_mat(poly)
    obj = bpy.data.objects.new(name, mesh)
    coll.objects.link(obj)
    return obj


def box(bm, centre, size, rot=Matrix()):
    bmesh.ops.create_cube(bm, size=1.0, matrix=Matrix.Translation(centre) @ rot @
                          Matrix.Diagonal(Vector((*size, 1.0))))


def person(bm, base, lean_deg=0.0, height=1.75):
    """A simple standing figure (torso, head, legs) for scale at distance."""
    lean = Matrix.Rotation(math.radians(lean_deg), 4, "Y")
    leg_h, torso_h = 0.85 * height / 1.75, 0.6 * height / 1.75
    for side in (-0.12, 0.12):
        bmesh.ops.create_cone(bm, cap_ends=True, segments=6, radius1=0.08, radius2=0.07,
                              depth=leg_h, matrix=Matrix.Translation(base) @ lean @
                              Matrix.Translation((0, side, leg_h / 2)))
    bmesh.ops.create_cone(bm, cap_ends=True, segments=8, radius1=0.18, radius2=0.16,
                          depth=torso_h, matrix=Matrix.Translation(base) @ lean @
                          Matrix.Translation((0, 0, leg_h + torso_h / 2)))
    bmesh.ops.create_icosphere(bm, subdivisions=2, radius=0.12, matrix=Matrix.Translation(base) @ lean @
                               Matrix.Translation((0, 0, leg_h + torso_h + 0.14)))


def build_boat(coll):
    """Ski boat (6.6 m), driver and spotter, pylon, rope and skier; local +x is forward,
    origin at the waterline at the stern."""
    white = material("Boat_Gelcoat", (0.85, 0.86, 0.87), 0.25)
    navy = material("Boat_Stripe", (0.04, 0.08, 0.22), 0.3)
    glass = material("Boat_Glass", (0.10, 0.12, 0.14), 0.05)
    red = material("Life_Shirt_Red", (0.55, 0.06, 0.04), 0.7)
    yellow = material("Life_Vest_Yellow", (0.75, 0.55, 0.05), 0.7)
    rope = material("Boat_Rope", (0.8, 0.75, 0.2), 0.8)

    bm = bmesh.new()
    # Hull: lofted cross-sections from stern (x=0) to bow (x=6.6).
    sections = []
    for x, half_w, depth, top in ((0.0, 1.20, 0.55, 0.75), (2.0, 1.25, 0.60, 0.78),
                                  (4.2, 1.15, 0.55, 0.85), (5.6, 0.75, 0.40, 0.95),
                                  (6.6, 0.05, 0.10, 1.05)):
        ring = [(x, -half_w, top), (x, -half_w * 0.95, -depth * 0.3), (x, 0.0, -depth),
                (x, half_w * 0.95, -depth * 0.3), (x, half_w, top)]
        sections.append([bm.verts.new(v) for v in ring])
    for a, b in zip(sections[:-1], sections[1:]):
        for i in range(4):
            bm.faces.new((a[i], a[i + 1], b[i + 1], b[i]))
    bm.faces.new(sections[0][::-1])                      # transom
    deck = [s[0] for s in sections] + [s[4] for s in sections][::-1]
    bm.faces.new(deck)                                    # flat deck cap
    hull_faces = len(bm.faces)
    box(bm, (4.0, 0.0, 1.05), (0.25, 2.1, 0.5),
        Matrix.Rotation(math.radians(-35), 4, "Y"))     # windshield
    glass_faces = len(bm.faces)
    box(bm, (1.6, 0.0, 0.95), (0.08, 0.08, 1.4))        # tow pylon
    pylon_faces = len(bm.faces)
    person(bm, Vector((3.2, 0.45, 0.55)), height=1.2)   # seated driver (shortened)
    person(bm, Vector((1.0, -0.4, 0.55)), height=1.2)   # spotter facing aft
    crew_faces = len(bm.faces)

    def face_mat(poly):
        i = poly.index
        if i < hull_faces:
            return 1 if poly.center.z > 0.45 else 0      # navy topsides band
        if i < glass_faces:
            return 2
        if i < pylon_faces:
            return 0
        return 3
    boat = to_object(bm, "Ski_Boat", coll, [white, navy, glass, red], face_mat)

    # Rope from pylon top to skier handle, and the skier on two skis, leaning back.
    bm = bmesh.new()
    length = ROPE_M
    bmesh.ops.create_cone(bm, cap_ends=True, segments=4, radius1=0.015, radius2=0.015,
                          depth=length, matrix=Matrix.Translation((1.6 - length / 2, 0.0, 1.0)) @
                          Matrix.Rotation(math.radians(90), 4, "Y") @
                          Matrix.Rotation(math.radians(-2.0), 4, "X"))
    rope_obj = to_object(bm, "Ski_Rope", coll, [rope])
    bm = bmesh.new()
    skier_x = 1.6 - length - 0.6
    person(bm, Vector((skier_x, 0.0, 0.05)), lean_deg=-25.0)
    for side in (-0.13, 0.13):
        box(bm, (skier_x + 0.2, side, 0.02), (1.7, 0.16, 0.03))
    skier = to_object(bm, "Skier", coll, [yellow])
    for obj in (rope_obj, skier):
        obj.parent = boat
    return boat


def wake_material():
    """Foam: the two Kelvin arms widening and fading with distance, prop wash behind
    the stern, and a small skier spray V; transparent elsewhere. Object space: +x
    forward, wake extends to -x."""
    mat = bpy.data.materials.get("Wake_Foam")
    if mat:
        return mat
    mat = bpy.data.materials.new("Wake_Foam")
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    out = nodes["Material Output"]
    nodes.remove(nodes["Principled BSDF"])

    def m(op, a, b=None):
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

    coord = nodes.new("ShaderNodeTexCoord")
    xyz = nodes.new("ShaderNodeSeparateXYZ")
    links.new(coord.outputs["Object"], xyz.inputs["Vector"])
    d = m("MAXIMUM", m("MULTIPLY", xyz.outputs["X"], -1.0), 0.0)        # distance behind
    ay = m("ABSOLUTE", xyz.outputs["Y"])
    tan_a = math.tan(math.radians(WAKE_HALF_ANGLE_DEG))
    arm_off = m("ABSOLUTE", m("SUBTRACT", ay, m("MULTIPLY", d, tan_a)))
    arm_w = m("ADD", 0.5, m("MULTIPLY", d, 0.035))
    arm = m("MULTIPLY", m("EXPONENT", m("MULTIPLY", m("DIVIDE", arm_off, arm_w), -1.0)),
            m("EXPONENT", m("MULTIPLY", d, -1.0 / 70.0)))
    wash_w = m("ADD", 1.0, m("MULTIPLY", d, 0.03))
    wash = m("MULTIPLY", m("EXPONENT", m("MULTIPLY", m("DIVIDE", ay, wash_w), -1.0)),
             m("EXPONENT", m("MULTIPLY", d, -1.0 / 30.0)))
    foam = m("MAXIMUM", arm, wash)
    noise = nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 0.8
    noise.inputs["Detail"].default_value = 6.0
    links.new(coord.outputs["Object"], noise.inputs["Vector"])
    foam = m("MULTIPLY", foam, m("ADD", 0.35, m("MULTIPLY", noise.outputs["Fac"], 1.1)))
    alpha = m("MINIMUM", m("MULTIPLY", foam, 1.3), 1.0)
    white = nodes.new("ShaderNodeBsdfPrincipled")
    white.inputs["Base Color"].default_value = (0.92, 0.94, 0.95, 1)
    white.inputs["Roughness"].default_value = 0.6
    clear = nodes.new("ShaderNodeBsdfTransparent")
    mix = nodes.new("ShaderNodeMixShader")
    links.new(alpha, mix.inputs["Fac"])
    links.new(clear.outputs[0], mix.inputs[1])
    links.new(white.outputs[0], mix.inputs[2])
    links.new(mix.outputs[0], out.inputs["Surface"])
    return mat


def build_wake(coll, boat):
    half = WAKE_LENGTH_M * math.tan(math.radians(WAKE_HALF_ANGLE_DEG)) + 8.0
    bm = bmesh.new()
    nx, ny = 64, 24
    verts = [[bm.verts.new((0.5 - WAKE_LENGTH_M * i / nx, -half + 2 * half * j / ny, 0.03))
              for j in range(ny + 1)] for i in range(nx + 1)]
    for i in range(nx):
        for j in range(ny):
            bm.faces.new((verts[i][j], verts[i][j + 1], verts[i + 1][j + 1], verts[i + 1][j]))
    wake = to_object(bm, "Boat_Wake", coll, [wake_material()])
    wake.parent = boat
    # Skier spray: a small V behind the skier.
    bm = bmesh.new()
    sx = 1.6 - ROPE_M - 0.6
    verts = [[bm.verts.new((sx - 25.0 * i / 16, -6.0 + 12.0 * j / 8, 0.035)) for j in range(9)]
             for i in range(17)]
    for i in range(16):
        for j in range(8):
            bm.faces.new((verts[i][j], verts[i][j + 1], verts[i + 1][j + 1], verts[i + 1][j]))
    spray = to_object(bm, "Skier_Spray", coll, [wake_material()])
    spray.parent = boat
    spray.scale = (1.0, 0.45, 1.0)
    return wake


def gull_prototype(coll, wing_deg, name):
    """Ring-billed gull: 0.45 m body, 1.2 m span; grey mantle, black wingtips."""
    white = material("Gull_White", (0.88, 0.88, 0.86), 0.6)
    grey = material("Gull_Grey", (0.55, 0.57, 0.60), 0.6)
    black = material("Gull_Tip", (0.03, 0.03, 0.03), 0.6)
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=10, v_segments=6, radius=0.1,
                              matrix=Matrix.Diagonal(Vector((2.1, 0.62, 0.62, 1))))
    body_faces = len(bm.faces)
    up = math.radians(wing_deg)
    for side in (-1, 1):
        # Long, narrow, slightly swept-back wing: root chord 0.16 m, half-span 0.62 m,
        # bent at the wrist so the outer wing droops (gull "M" profile).
        root = [Vector((0.07, side * 0.05, 0.02)), Vector((-0.09, side * 0.05, 0.02))]
        wrist = [Vector((0.03, side * 0.30 * math.cos(up), 0.30 * math.sin(up) + 0.02)),
                 Vector((-0.08, side * 0.29 * math.cos(up), 0.29 * math.sin(up) + 0.02))]
        tip_up = up * 0.3 - math.radians(8)
        tip = Vector((-0.12, side * (0.30 * math.cos(up) + 0.32 * math.cos(tip_up)),
                      0.30 * math.sin(up) + 0.32 * math.sin(tip_up) + 0.02))
        v = [bm.verts.new(p) for p in root + wrist]
        t = bm.verts.new(tip)
        bm.faces.new((v[0], v[2], v[3], v[1]) if side > 0 else (v[1], v[3], v[2], v[0]))
        bm.faces.new((v[2], t, v[3]) if side > 0 else (v[3], t, v[2]))
    tail = [bm.verts.new(p) for p in ((-0.18, -0.05, 0.0), (-0.18, 0.05, 0.0), (-0.28, 0.06, 0.0),
                                       (-0.28, -0.06, 0.0))]
    bm.faces.new(tail)
    wing_faces = len(bm.faces)

    def face_mat(poly):
        if poly.index < body_faces:
            return 0
        k = poly.index - body_faces
        if k >= 4:
            return 0                      # white tail
        return 2 if k % 2 == 1 else 1     # black tip, grey inner wing
    return to_object(bm, name, coll, [white, grey, black], face_mat)


def build_gulls(coll):
    rng = random.Random(1016)
    protos_coll = bpy.data.collections.new("Gull_Prototypes")
    coll.children.link(protos_coll)
    protos_coll.hide_render = True
    protos = [gull_prototype(protos_coll, deg, f"Gull_Wings_{i}") for i, deg in
              enumerate((22.0, 6.0, -10.0))]
    cx, cy, cz = GULLS["centre"]
    sx, sy, sz = GULLS["spread"]
    for k in range(GULLS["count"]):
        g = bpy.data.objects.new(f"Gull_{k:02d}", protos[k % 3].data)  # linked duplicate
        g.location = (cx + rng.gauss(0, sx), cy + rng.gauss(0, sy), cz + rng.gauss(0, sz))
        heading = math.radians(GULLS["heading_deg"] + rng.uniform(-18, 18))
        g.rotation_euler = (math.radians(rng.uniform(-8, 8)), math.radians(rng.uniform(-6, 6)),
                            math.pi / 2 - heading)
        g.scale = (rng.uniform(0.95, 1.1),) * 3
        coll.objects.link(g)


def build(record):
    scene = bpy.context.scene
    life = bpy.data.collections.new("Lake_Life")
    scene.collection.children.link(life)
    boat = build_boat(life)
    boat.location = (*BOAT_XY, lrh.POOL_M)
    # No bow-up pitch: the wake and skier are children, and any tilt sinks the far wake.
    boat.rotation_euler = (0.0, 0.0, math.pi / 2 - math.radians(BOAT_HEADING_DEG))
    build_wake(life, boat)
    gulls = bpy.data.collections.new("Gulls")
    scene.collection.children.link(gulls)
    build_gulls(gulls)
    record("lake_life", True, boat_xy=BOAT_XY, boat_heading_deg=BOAT_HEADING_DEG,
           gulls=GULLS["count"],
           note="procedural boat, skier, wake and ring-billed gulls; boat on open lake >100 m "
                "from shore, outside the no-wake habitat zone")
