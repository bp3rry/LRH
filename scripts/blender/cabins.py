"""Phase 2d cabins: raised pads, lake-house cabins, patios and fire pits (switchable).

Owner (19 Oct 2026): every lot gets a lake-house / rustic cabin, 2 BR / 1 BA on a raised
upper floor with an optional 1 BR / 1 BA apartment, parking and boat storage at ground
level. Style follows the owner's reference renders (inputs/reference/benchmark-cam02-
sunset.jpg) for light and mood; the cabin itself follows Satterwhite's Hemlock plan
(inputs/reference/hemlock-photo-04.jpg and the plan's published renderings): honey-tone
logs, board-and-batten gables, a glazed lake gable over a deck on tall posts with
Y-brackets, a dormered front porch and a walk-out terrace level. A flagstone patio with
a stone fire pit sits on the lake side. All massing is illustrative.

Per lot (from out/derived/build_sites.geojson, written by scripts/build_sites.py):
- `Pad_<lot>`: the graded surface (flat top 2 ft above mean ground, 4:1 fill slopes),
  laid just above the terrain, with the site ground material.
- `Cabin_<lot>`: the cabin, patio, fire pit, chairs, lamp post and lights.
- `Drive_<lot>`: the gravel front drive from CR 3635 to the house.

Each lot is its own child collection of `Cabins`; render.py includes the lots a shot
lists (`cabins: [Lot 5]` or `cabins: all`) and hides the trees build_baseline set aside
on those lots' footprints (`Vegetation_BuildSite_<lot>`).
"""

import json
import math

import bmesh
import bpy
import numpy as np
from mathutils import Vector

import lrh

import shapely  # noqa: E402
from shapely.geometry import Point  # noqa: E402

FT = 0.3048
BODY = (42 * FT, 30 * FT)       # main floor E-W x N-S: 1,260 sq ft (Hemlock), 2 BR / 1 BA
PORCH_DEPTH = 10 * FT           # lake deck across the west (glazed gable) end
WRAP_DEPTH = 8 * FT             # front porch along the south side
# Porches: 10 x 38 ft lake deck + 8 x 42 ft front porch = 716 sq ft (Hemlock: 723).
GROUND_STOREY = 3.2             # pad top to upper floor (9.5 ft clear + framing)
WALL = 2.9                      # upper-floor wall height to the eave
PITCH = 10 / 12                 # main roof (steep, as in the owner's reference photo)
PORCH_PITCH = 4 / 12
OVERHANG = 0.6
EAST_MARGIN = 3.0               # house's east wall this far inside the pad's east edge
PATIO_R = 3.0
FILL_SKIRT = 2 * FT * 4         # 2 ft raise at 4:1
LIFT = 0.03                     # pad surface above the terrain


def build_sites():
    path = lrh.ROOT / "out/derived/build_sites.geojson"
    if not path.exists():
        lrh.fail("missing out/derived/build_sites.geojson; run scripts/build_sites.py")
    feats = json.loads(path.read_text())["features"]
    lots = {}
    for f in feats:
        p = f["properties"]
        if "lot" in p:
            lots.setdefault(p["lot"], {})[p["kind"]] = (p, shapely.geometry.shape(f["geometry"]))
    return {k: v for k, v in lots.items() if "pad" in v}


def clearing(site):
    """Footprint where no tree may stand once the lot is built: the graded pad, the
    patio and the front drive."""
    _, pad = site["pad"]
    parts = [pad.buffer(FILL_SKIRT + 1.5, join_style="mitre"), patio_centre(pad).buffer(PATIO_R + 2)]
    if "drive_front" in site:
        parts.append(site["drive_front"][1].buffer(3.5))
    return shapely.union_all(parts)


def house_box(pad):
    """Main-floor footprint: east wall EAST_MARGIN inside the pad, north wall 1 m inside,
    leaving the front porch and its stair room on the pad's south side."""
    x0, y0, x1, y1 = pad.bounds
    xe = x1 - EAST_MARGIN
    yn = min(y1 - 1.0, (y0 + y1) / 2 + BODY[1] / 2 + WRAP_DEPTH / 2)
    return xe - BODY[0], yn - BODY[1], xe, yn


def patio_centre(pad):
    """Below the lake deck, south of the deck stair's landing."""
    xw, y0, _, y1 = house_box(pad)
    return Point(xw - PORCH_DEPTH - PATIO_R - 1.2, (y0 + y1) / 2 - 1.8)


# --------------------------------------------------------------------------- materials

def _mat(name):
    mat = bpy.data.materials.get(name)
    if mat:
        return mat, None
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    return mat, mat.node_tree


def _coord(tree):
    nodes = tree.nodes
    tc = nodes.new("ShaderNodeTexCoord")
    sep = nodes.new("ShaderNodeSeparateXYZ")
    tree.links.new(tc.outputs["Object"], sep.inputs["Vector"])
    return tc, sep


def _math(tree, op, a, b=None):
    n = tree.nodes.new("ShaderNodeMath")
    n.operation = op
    for i, v in enumerate((a, b)):
        if v is None:
            continue
        if isinstance(v, (int, float)):
            n.inputs[i].default_value = v
        else:
            tree.links.new(v, n.inputs[i])
    return n.outputs[0]


def _ramp(tree, fac, c0, c1, p0=0.0, p1=1.0):
    r = tree.nodes.new("ShaderNodeValToRGB")
    r.color_ramp.elements[0].color = (*c0, 1)
    r.color_ramp.elements[1].color = (*c1, 1)
    r.color_ramp.elements[0].position = p0
    r.color_ramp.elements[1].position = p1
    tree.links.new(fac, r.inputs["Fac"])
    return r.outputs["Color"]


def _finish(tree, colour, rough, height=None, bump_dist=0.02, strength=1.0):
    bsdf = tree.nodes["Principled BSDF"]
    tree.links.new(colour, bsdf.inputs["Base Color"])
    bsdf.inputs["Roughness"].default_value = rough
    if height is not None:
        bump = tree.nodes.new("ShaderNodeBump")
        bump.inputs["Distance"].default_value = bump_dist
        bump.inputs["Strength"].default_value = strength
        tree.links.new(height, bump.inputs["Height"])
        tree.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])


def _grain(tree, tc, scale=(0.4, 0.4, 6.0), detail=6.0):
    """Noise stretched along one axis, for wood grain and weathering."""
    mapping = tree.nodes.new("ShaderNodeMapping")
    mapping.inputs["Scale"].default_value = scale
    tree.links.new(tc.outputs["Object"], mapping.inputs["Vector"])
    noise = tree.nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 3.0
    noise.inputs["Detail"].default_value = detail
    tree.links.new(mapping.outputs["Vector"], noise.inputs["Vector"])
    return noise.outputs["Fac"]


def log_siding():
    """Horizontal 8 in round logs, natural honey pine (owner reference photo)."""
    mat, tree = _mat("Cabin_Log_Siding")
    if tree is None:
        return mat
    tc, sep = _coord(tree)
    f = _math(tree, "FRACT", _math(tree, "DIVIDE", sep.outputs["Z"], 0.21))
    u = _math(tree, "SUBTRACT", _math(tree, "MULTIPLY", f, 2.0), 1.0)
    profile = _math(tree, "SQRT", _math(tree, "MAXIMUM", _math(tree, "SUBTRACT", 1.0,
                                                                 _math(tree, "POWER", u, 2.0)), 0.0))
    grain = _grain(tree, tc, scale=(0.15, 0.15, 4.0))
    wood = _ramp(tree, grain, (0.42, 0.22, 0.07), (0.60, 0.35, 0.12), 0.3, 0.7)
    seam = _ramp(tree, profile, (0.12, 0.1, 0.09), (1, 1, 1), 0.05, 0.5)
    mix = tree.nodes.new("ShaderNodeMix")
    mix.data_type = "RGBA"
    mix.blend_type = "MULTIPLY"
    mix.inputs["Factor"].default_value = 1.0
    tree.links.new(wood, mix.inputs["A"])
    tree.links.new(seam, mix.inputs["B"])
    _finish(tree, mix.outputs["Result"], 0.6, profile, 0.06, 1.0)
    return mat


def timber():
    mat, tree = _mat("Cabin_Timber")
    if tree is None:
        return mat
    tc, _ = _coord(tree)
    grain = _grain(tree, tc, scale=(1.0, 1.0, 8.0))
    _finish(tree, _ramp(tree, grain, (0.38, 0.19, 0.06), (0.55, 0.31, 0.11), 0.3, 0.75),
            0.55, grain, 0.004, 0.4)
    return mat


def trim():
    mat, tree = _mat("Cabin_Trim")
    if tree is None:
        return mat
    tc, _ = _coord(tree)
    grain = _grain(tree, tc, scale=(1.0, 1.0, 8.0))
    _finish(tree, _ramp(tree, grain, (0.16, 0.075, 0.025), (0.26, 0.13, 0.045)), 0.5)
    return mat


def board_batten():
    """Gable ends: vertical cedar boards with battens every 12 in."""
    mat, tree = _mat("Cabin_Board_Batten")
    if tree is None:
        return mat
    tc, sep = _coord(tree)
    along = _math(tree, "ADD", sep.outputs["X"], sep.outputs["Y"])
    f = _math(tree, "FRACT", _math(tree, "DIVIDE", along, 0.3048))
    batten = _math(tree, "LESS_THAN", _math(tree, "ABSOLUTE", _math(tree, "SUBTRACT", f, 0.5)), 0.08)
    grain = _grain(tree, tc, scale=(4.0, 4.0, 0.3))
    _finish(tree, _ramp(tree, grain, (0.40, 0.21, 0.07), (0.56, 0.32, 0.11), 0.3, 0.75), 0.6,
            batten, 0.015, 0.6)
    return mat


def stone():
    """Field-stone veneer: Voronoi stones with recessed mortar."""
    mat, tree = _mat("Cabin_Stone")
    if tree is None:
        return mat
    tc, _ = _coord(tree)
    mapping = tree.nodes.new("ShaderNodeMapping")
    mapping.inputs["Scale"].default_value = (1.0, 1.0, 1.6)  # stones wider than tall
    tree.links.new(tc.outputs["Object"], mapping.inputs["Vector"])
    edge = tree.nodes.new("ShaderNodeTexVoronoi")
    edge.feature = "DISTANCE_TO_EDGE"
    edge.inputs["Scale"].default_value = 4.5
    tree.links.new(mapping.outputs["Vector"], edge.inputs["Vector"])
    cell = tree.nodes.new("ShaderNodeTexVoronoi")
    cell.inputs["Scale"].default_value = 4.5
    tree.links.new(mapping.outputs["Vector"], cell.inputs["Vector"])
    tint = _ramp(tree, cell.outputs["Distance"], (0.16, 0.15, 0.14), (0.36, 0.32, 0.27))
    mortar = _math(tree, "GREATER_THAN", edge.outputs["Distance"], 0.035)
    mix = tree.nodes.new("ShaderNodeMix")
    mix.data_type = "RGBA"
    mix.inputs["A"].default_value = (0.38, 0.36, 0.33, 1)
    tree.links.new(mortar, mix.inputs["Factor"])
    tree.links.new(tint, mix.inputs["B"])
    _finish(tree, mix.outputs["Result"], 0.85, mortar, 0.03, 1.0)
    return mat


def shingles():
    """Brown-grey architectural shingles, courses running along the ridge (N-S)."""
    mat, tree = _mat("Cabin_Shingles")
    if tree is None:
        return mat
    tc, sep = _coord(tree)
    rows = _math(tree, "FRACT", _math(tree, "DIVIDE", sep.outputs["X"], 0.14))
    noise = tree.nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 9.0
    noise.inputs["Detail"].default_value = 4.0
    tree.links.new(tc.outputs["Object"], noise.inputs["Vector"])
    colour = _ramp(tree, noise.outputs["Fac"], (0.035, 0.028, 0.022), (0.075, 0.06, 0.047), 0.35, 0.7)
    _finish(tree, colour, 0.8, rows, 0.01, 0.7)
    return mat


def window_glow():
    """Dark reflective glass with a little warm interior light behind it."""
    mat, tree = _mat("Cabin_Window_Glow")
    if tree is None:
        return mat
    nodes, links = tree.nodes, tree.links
    nodes.remove(nodes["Principled BSDF"])
    emit = nodes.new("ShaderNodeEmission")
    emit.inputs["Color"].default_value = (1.0, 0.36, 0.09, 1)
    emit.inputs["Strength"].default_value = 0.35
    gloss = nodes.new("ShaderNodeBsdfGlossy")
    gloss.inputs["Roughness"].default_value = 0.04
    gloss.inputs["Color"].default_value = (0.9, 0.9, 0.9, 1)
    fres = nodes.new("ShaderNodeLayerWeight")
    fres.inputs["Blend"].default_value = 0.35
    mix = nodes.new("ShaderNodeMixShader")
    links.new(fres.outputs["Fresnel"], mix.inputs["Fac"])
    links.new(emit.outputs[0], mix.inputs[1])
    links.new(gloss.outputs[0], mix.inputs[2])
    links.new(mix.outputs[0], nodes["Material Output"].inputs["Surface"])
    return mat


def emitter(name, rgb, strength):
    mat, tree = _mat(name)
    if tree is None:
        return mat
    nodes = tree.nodes
    nodes.remove(nodes["Principled BSDF"])
    emit = nodes.new("ShaderNodeEmission")
    emit.inputs["Color"].default_value = (*rgb, 1)
    emit.inputs["Strength"].default_value = strength
    tree.links.new(emit.outputs[0], nodes["Material Output"].inputs["Surface"])
    return mat


def plain(name, rgb, rough=0.8, metallic=0.0):
    mat, tree = _mat(name)
    if tree is None:
        return mat
    bsdf = tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (*rgb, 1)
    bsdf.inputs["Roughness"].default_value = rough
    bsdf.inputs["Metallic"].default_value = metallic
    return mat


def flagstone():
    mat, tree = _mat("Cabin_Flagstone")
    if tree is None:
        return mat
    tc, _ = _coord(tree)
    edge = tree.nodes.new("ShaderNodeTexVoronoi")
    edge.feature = "DISTANCE_TO_EDGE"
    edge.inputs["Scale"].default_value = 1.6
    tree.links.new(tc.outputs["Object"], edge.inputs["Vector"])
    cell = tree.nodes.new("ShaderNodeTexVoronoi")
    cell.inputs["Scale"].default_value = 1.6
    tree.links.new(tc.outputs["Object"], cell.inputs["Vector"])
    tint = _ramp(tree, cell.outputs["Distance"], (0.26, 0.22, 0.17), (0.45, 0.38, 0.29))
    joint = _math(tree, "GREATER_THAN", edge.outputs["Distance"], 0.03)
    mix = tree.nodes.new("ShaderNodeMix")
    mix.data_type = "RGBA"
    mix.inputs["A"].default_value = (0.06, 0.08, 0.03, 1)  # grassy joints
    tree.links.new(joint, mix.inputs["Factor"])
    tree.links.new(tint, mix.inputs["B"])
    _finish(tree, mix.outputs["Result"], 0.8, joint, 0.02, 0.8)
    return mat


# --------------------------------------------------------------------------- geometry

class Mesh:
    """Accumulates world-space hexahedra and prisms per material, then one object."""

    def __init__(self):
        self.verts, self.faces, self.mats, self.slots = [], [], [], []

    def _slot(self, mat):
        if mat not in self.slots:
            self.slots.append(mat)
        return self.slots.index(mat)

    def hexa(self, c, mat):
        """c: 8 corners, bottom ring (0-3) then top ring (4-7), both counter-clockwise."""
        i = len(self.verts)
        self.verts.extend(tuple(p) for p in c)
        s = self._slot(mat)
        for f in ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)):
            self.faces.append(tuple(i + k for k in f))
            self.mats.append(s)

    def box(self, x0, y0, z0, x1, y1, z1, mat):
        self.hexa([(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
                   (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)], mat)

    def beam(self, a, b, w, h, mat):
        """A w x h member from point a to point b (any direction)."""
        a, b = Vector(a), Vector(b)
        axis = (b - a).normalized()
        up = Vector((0, 0, 1)) if abs(axis.z) < 0.95 else Vector((1, 0, 0))
        side = axis.cross(up).normalized() * (w / 2)
        top = side.cross(axis).normalized() * (h / 2)
        ring = lambda p: [p - side - top, p + side - top, p + side + top, p - side + top]
        r0, r1 = ring(a), ring(b)
        # bottom/top rings for hexa are the two ends here
        self.hexa([r0[0], r0[1], r0[2], r0[3], r1[0], r1[1], r1[2], r1[3]], mat)

    def prism(self, ring_xy, z0, z1, mat):
        """A vertical prism over a convex counter-clockwise polygon."""
        i = len(self.verts)
        n = len(ring_xy)
        self.verts.extend((x, y, z0) for x, y in ring_xy)
        self.verts.extend((x, y, z1) for x, y in ring_xy)
        s = self._slot(mat)
        self.faces.append(tuple(i + k for k in reversed(range(n))))
        self.mats.append(s)
        self.faces.append(tuple(i + n + k for k in range(n)))
        self.mats.append(s)
        for k in range(n):
            self.faces.append((i + k, i + (k + 1) % n, i + n + (k + 1) % n, i + n + k))
            self.mats.append(s)

    def cylinder(self, cx, cy, z0, z1, r, mat, n=16, r_top=None):
        if r_top is None:
            ring = [(cx + r * math.cos(2 * math.pi * k / n), cy + r * math.sin(2 * math.pi * k / n))
                    for k in range(n)]
            self.prism(ring, z0, z1, mat)
            return
        i = len(self.verts)
        for rr, z in ((r, z0), (r_top, z1)):
            self.verts.extend((cx + rr * math.cos(2 * math.pi * k / n),
                               cy + rr * math.sin(2 * math.pi * k / n), z) for k in range(n))
        s = self._slot(mat)
        self.faces.append(tuple(i + k for k in reversed(range(n))))
        self.mats.append(s)
        self.faces.append(tuple(i + n + k for k in range(n)))
        self.mats.append(s)
        for k in range(n):
            self.faces.append((i + k, i + (k + 1) % n, i + n + (k + 1) % n, i + n + k))
            self.mats.append(s)

    def gable(self, x0, x1, y, z_eave, z_ridge, depth, mat):
        """Triangular gable wall in the x-z plane at y, `depth` thick toward +y."""
        xm = (x0 + x1) / 2
        i = len(self.verts)
        for yy in (y, y + depth):
            self.verts.extend([(x0, yy, z_eave), (x1, yy, z_eave), (xm, yy, z_ridge)])
        s = self._slot(mat)
        for f in ((0, 1, 2), (5, 4, 3), (0, 3, 4, 1), (1, 4, 5, 2), (2, 5, 3, 0)):
            self.faces.append(tuple(i + k for k in f))
            self.mats.append(s)

    def gable_x(self, y0, y1, x, z_eave, z_ridge, depth, mat):
        """Triangular gable wall in the y-z plane at x, `depth` thick toward +x."""
        ym = (y0 + y1) / 2
        i = len(self.verts)
        for xx in (x, x + depth):
            self.verts.extend([(xx, y0, z_eave), (xx, y1, z_eave), (xx, ym, z_ridge)])
        s = self._slot(mat)
        for f in ((0, 1, 2), (5, 4, 3), (0, 3, 4, 1), (1, 4, 5, 2), (2, 5, 3, 0)):
            self.faces.append(tuple(i + k for k in f))
            self.mats.append(s)

    def object(self, name, coll):
        mesh = bpy.data.meshes.new(name)
        mesh.from_pydata(self.verts, [], self.faces)
        for m in self.slots:
            mesh.materials.append(m)
        mesh.polygons.foreach_set("material_index", self.mats)
        bm = bmesh.new()
        bm.from_mesh(mesh)
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        bm.to_mesh(mesh)
        bm.free()
        obj = bpy.data.objects.new(name, mesh)
        coll.objects.link(obj)
        return obj


def point_light(name, xyz, watts, rgb, radius, coll):
    light = bpy.data.lights.new(name, "POINT")
    light.energy = watts
    light.color = rgb
    light.shadow_soft_size = radius
    obj = bpy.data.objects.new(name, light)
    obj.location = xyz
    coll.objects.link(obj)
    return obj


def window_trim():
    """Dark green window trim, as on the Hemlock renderings."""
    return plain("Cabin_Window_Trim", (0.025, 0.06, 0.035), 0.5)


def window(m, x, y, z0, w, h, facing, glow, frame=None):
    """A window on a wall: facing is 'W', 'E', 'S' or 'N'; (x, y) on the wall face."""
    frame = window_trim()
    t = 0.05
    if facing in ("W", "E"):
        d = -t if facing == "W" else t
        m.box(min(x, x + d), y - w / 2, z0, max(x, x + d), y + w / 2, z0 + h, glow)
        for yy in (y - w / 2 - 0.06, y + w / 2):
            m.box(min(x, x + 2 * d), yy, z0 - 0.06, max(x, x + 2 * d), yy + 0.06, z0 + h + 0.06, frame)
        for zz in (z0 - 0.08, z0 + h):
            m.box(min(x, x + 2 * d), y - w / 2 - 0.06, zz, max(x, x + 2 * d), y + w / 2 + 0.06, zz + 0.08, frame)
        m.box(min(x, x + 2 * d), y - 0.025, z0, max(x, x + 2 * d), y + 0.025, z0 + h, frame)
    else:
        d = -t if facing == "S" else t
        m.box(x - w / 2, min(y, y + d), z0, x + w / 2, max(y, y + d), z0 + h, glow)
        for xx in (x - w / 2 - 0.06, x + w / 2):
            m.box(xx, min(y, y + 2 * d), z0 - 0.06, xx + 0.06, max(y, y + 2 * d), z0 + h + 0.06, frame)
        for zz in (z0 - 0.08, z0 + h):
            m.box(x - w / 2 - 0.06, min(y, y + 2 * d), zz, x + w / 2 + 0.06, max(y, y + 2 * d), zz + 0.08, frame)
        m.box(x - 0.025, min(y, y + 2 * d), z0, x + 0.025, max(y, y + 2 * d), z0 + h, frame)


def railing(m, a, b, z, wood, top=0.95, spacing=0.13):
    """Porch railing from a to b (xy) on a deck at z: top and bottom rails, balusters."""
    a, b = np.array(a, float), np.array(b, float)
    m.beam((*a, z + top), (*b, z + top), 0.09, 0.07, wood)
    m.beam((*a, z + 0.10), (*b, z + 0.10), 0.07, 0.07, wood)
    n = max(1, int(np.linalg.norm(b - a) / spacing))
    for k in range(1, n):
        p = a + (b - a) * k / n
        m.box(p[0] - 0.02, p[1] - 0.02, z + 0.12, p[0] + 0.02, p[1] + 0.02, z + top - 0.03, wood)


def chair(m, cx, cy, z, face_deg, wood):
    """A simple Adirondack chair facing `face_deg` (compass) toward the fire."""
    h = math.radians(face_deg)
    fwd = np.array([math.sin(h), math.cos(h)])
    side = np.array([fwd[1], -fwd[0]])
    c = np.array([cx, cy])

    def p(f, s, zz):
        q = c + fwd * f + side * s
        return (q[0], q[1], z + zz)

    for s in (-0.33, 0.33):  # legs/arms
        m.beam(p(0.30, s, 0.0), p(0.30, s, 0.62), 0.06, 0.06, wood)
        m.beam(p(-0.25, s, 0.0), p(-0.25, s, 0.55), 0.06, 0.06, wood)
        m.beam(p(0.38, s, 0.62), p(-0.35, s, 0.60), 0.13, 0.03, wood)
    m.beam(p(0.30, 0, 0.38), p(-0.20, 0, 0.30), 0.62, 0.04, wood)    # seat, sloping back
    m.beam(p(-0.20, 0, 0.30), p(-0.45, 0, 1.00), 0.58, 0.035, wood)  # tall slatted back


def fire_pit(m, coll, cx, cy, z, stone_mat, log_mat, fire_mat, name):
    n = 14
    for k in range(n):  # ring of rough stones
        a = 2 * math.pi * k / n
        r = 0.62
        x, y = cx + r * math.cos(a), cy + r * math.sin(a)
        m.box(x - 0.13, y - 0.13, z, x + 0.13, y + 0.13, z + 0.38 + 0.04 * (k % 3), stone_mat)
    m.cylinder(cx, cy, z, z + 0.05, 0.5, plain("Cabin_Ash", (0.05, 0.045, 0.04), 0.95))
    for k in range(4):  # logs in a teepee
        a = math.pi / 2 * k + 0.4
        m.beam((cx + 0.35 * math.cos(a), cy + 0.35 * math.sin(a), z + 0.08), (cx, cy, z + 0.55),
               0.09, 0.09, log_mat)
    for k, (dx, dy, hh, rr) in enumerate(((0, 0, 0.75, 0.16), (0.12, 0.05, 0.5, 0.1),
                                          (-0.1, 0.08, 0.55, 0.1), (0.02, -0.12, 0.45, 0.09))):
        m.cylinder(cx + dx, cy + dy, z + 0.12, z + 0.12 + hh, rr, fire_mat, n=8, r_top=0.01)
    point_light(f"{name}_Fire_Light", (cx, cy, z + 0.7), 600.0, (1.0, 0.42, 0.12), 0.25, coll)


def lamp_post(m, coll, x, y, z, iron, glow, name, h=2.2):
    m.cylinder(x, y, z, z + h, 0.045, iron, n=8)
    m.box(x - 0.12, y - 0.12, z + h, x + 0.12, y + 0.12, z + h + 0.3, glow)
    m.cylinder(x, y, z + h + 0.3, z + h + 0.42, 0.17, iron, n=8, r_top=0.02)
    point_light(f"{name}_Lamp", (x, y, z + h + 0.15), 60.0, (1.0, 0.7, 0.4), 0.1, coll)


def y_braces(m, x, y, top, along, wood, arm=0.55):
    """The Hemlock's Y-bracket: two short braces from a post up to the beam above it."""
    for d in (-arm, arm):
        a = (x, y, top - 0.6)
        b = (x + d, y, top - 0.02) if along == "x" else (x, y + d, top - 0.02)
        m.beam(a, b, 0.09, 0.09, wood)


def dormer(m, xc, y_face, z_sill, roof_mat, bb, glow, dark, w=1.9):
    """A small gable dormer facing south on the main roof, as on the Hemlock's front."""
    z_eave = z_sill + 1.35
    z_ridge = z_eave + (w / 2 + 0.15) * PITCH
    depth = 2.6
    m.box(xc - w / 2, y_face, z_sill - 0.4, xc + w / 2, y_face + depth, z_eave, bb)
    m.gable(xc - w / 2, xc + w / 2, y_face, z_eave, z_ridge, depth, bb)
    window(m, xc, y_face, z_sill + 0.15, 0.75, 0.95, "S", glow, dark)
    for sgn in (-1, 1):
        xa = xc + sgn * (w / 2 + 0.2)
        lo = [(xa, y_face - 0.25, z_eave - 0.15), (xc, y_face - 0.25, z_ridge),
              (xc, y_face + depth + 0.4, z_ridge), (xa, y_face + depth + 0.4, z_eave - 0.15)]
        m.hexa(lo + [(x, y, z + 0.1) for x, y, z in lo], roof_mat)
    for xa in (xc - w / 2 - 0.2, xc + w / 2 + 0.2):
        m.beam((xa, y_face - 0.2, z_eave - 0.15), (xc, y_face - 0.2, z_ridge), 0.06, 0.16, dark)


def cabin(m, coll, pad, top, name):
    """The 2 BR stilt cabin on its pad, after Satterwhite's Hemlock plan (owner reference:
    inputs/reference/hemlock-photo-04.jpg; satterwhite-log-homes.com/floor-plans/hemlock).

    Main floor 30 x 42 ft (1,260 sq ft, as the Hemlock) in honey-tone logs, ridge east-west
    so the glazed gable end faces the lake (west). The main roof is carried 10 ft further
    west over a full-width lake deck on tall posts with Y-brackets and an exposed timber
    truss. A full-length front porch along the south side, under a lower-pitch extension
    of the main roof with three gable dormers, wraps onto the lake deck. Below, the terrace
    level (optional 1 BR / 1 BA apartment toward the lake, boat storage and parking behind
    a garage door on the road end) in logs on a concrete stem wall. Stairs: the front
    porch down to the drive side, and the lake deck down to the patio."""
    logs, wood, dark, bb = log_siding(), timber(), trim(), board_batten()
    roof, glow = shingles(), window_glow()
    slab = plain("Cabin_Slab", (0.2, 0.19, 0.18), 0.9)
    xw, y0, xe, y1 = house_box(pad)
    cy = (y0 + y1) / 2
    z0 = top
    F = z0 + GROUND_STOREY
    eave = F + WALL
    xp = xw - PORCH_DEPTH          # lake deck outer line (west)
    ys = y0 - WRAP_DEPTH           # front porch outer line (south)

    # Terrace level: logs on a concrete stem wall; apartment toward the lake, storage east.
    m.box(xp - 0.3, ys - 0.3, z0 - 0.15, xe + 0.3, y1 + 0.3, z0 + 0.08, slab)
    m.box(xw, y0, z0, xe, y1, z0 + 0.35, slab)
    m.box(xw, y0, z0 + 0.35, xe, y1, F - 0.35, logs)
    window(m, xw, cy, z0 + 0.1, 1.6, 2.1, "W", glow, dark)          # apartment French doors
    for yy in (y0 + 1.6, y1 - 1.6):
        window(m, xw, yy, z0 + 0.9, 1.4, 1.4, "W", glow, dark)
    window(m, xw + 2.2, y0, z0 + 0.9, 1.2, 1.3, "S", glow, dark)
    m.box(xe, cy - 1.5, z0 + 0.08, xe + 0.05, cy + 1.5, z0 + 2.45,
          plain("Cabin_Garage_Door", (0.30, 0.17, 0.07), 0.6))      # boat / parking door
    m.box(xe + 0.05, cy - 1.6, z0 + 2.45, xe + 0.1, cy + 1.6, z0 + 2.6, dark)
    m.box(xw - 0.1, y0 - 0.1, F - 0.35, xe + 0.1, y1 + 0.1, F, wood)  # floor beams

    # Main floor: logs with corner posts.
    m.box(xw, y0, F, xe, y1, eave, logs)
    for x in (xw, xe):
        for y in (y0, y1):
            m.box(x - 0.15, y - 0.15, F, x + 0.15, y + 0.15, eave, logs)
    for yy in (y0 + 1.6, y1 - 1.6):                                  # lake wall: big glass
        window(m, xw, yy, F + 0.5, 1.6, 1.9, "W", glow, dark)
    window(m, xw, cy, F + 0.05, 1.8, 2.3, "W", glow, dark)
    for xx in (xw + 2.0, xe - 4.5):                                  # front (south) wall
        window(m, xx, y0, F + 0.7, 1.6, 1.5, "S", glow, dark)
    window(m, (xw + xe) / 2 + 0.6, y0, F + 0.05, 1.6, 2.15, "S", glow, dark)  # front door
    for xx in (xw + 3.0, (xw + xe) / 2, xe - 2.5):
        window(m, xx, y1, F + 0.85, 1.0, 1.3, "N", glow, dark)
    for yy in (cy - 2.2, cy + 2.2):
        window(m, xe, yy, F + 0.85, 0.9, 1.3, "E", glow, dark)

    # Main roof: ridge east-west, carried west over the lake deck; board-and-batten gables.
    rise = (BODY[1] / 2) * PITCH
    ridge = eave + rise
    for x, depth in ((xw, 0.15), (xe - 0.15, 0.15)):
        m.gable_x(y0, y1, x, eave, ridge, depth, bb)
    # Glazed lake gable: a tall centre window and stepped side windows (Hemlock back view).
    window(m, xw, cy, eave + 0.15, 1.5, rise - 1.0, "W", glow, dark)
    for dy in (-1.75, 1.75):
        window(m, xw, cy + dy, eave + 0.15, 1.5, (rise - 1.0) * 0.55, "W", glow, dark)
    window(m, xe, cy, eave + 0.4, 1.0, 1.1, "E", glow, dark)
    th = 0.16
    drop = OVERHANG * PITCH
    xr0, xr1 = xp - 0.45, xe + OVERHANG
    for ya in (y0 - OVERHANG, y1 + OVERHANG):
        za = eave - drop
        lo = [(xr0, ya, za), (xr1, ya, za), (xr1, cy, ridge), (xr0, cy, ridge)]
        m.hexa(lo + [(x, y, z + th) for x, y, z in lo], roof)
    for x in (xr0, xr1 - 0.08):                                     # rake boards
        for ya in (y0 - OVERHANG, y1 + OVERHANG):
            m.beam((x + 0.04, ya, eave - drop), (x + 0.04, cy, ridge), 0.08, 0.26, dark)
    m.beam((xr0, cy, ridge + th), (xr1, cy, ridge + th), 0.2, 0.08, dark)
    # Exposed timber truss at the outer end of the lake deck roof.
    xt = xp + 0.1
    m.beam((xt, y0 - 0.1, eave - 0.1), (xt, y1 + 0.1, eave - 0.1), 0.2, 0.3, wood)   # tie beam
    m.beam((xt, cy, eave - 0.1), (xt, cy, ridge - 0.2), 0.2, 0.2, wood)              # king post
    for ya in (y0, y1):
        m.beam((xt, ya, eave), (xt, cy, ridge - 0.15), 0.2, 0.22, wood)              # rafters
        m.beam((xt, (ya + cy) / 2, eave - 0.1), (xt, cy, eave + rise * 0.55), 0.14, 0.14, wood)

    # Front porch roof: a lower-pitch extension of the south slope; three dormers above.
    over = 0.4
    z_lo = eave - drop - (WRAP_DEPTH - OVERHANG + over) * PORCH_PITCH
    lo = [(xp - 0.45, y0 - OVERHANG, eave - drop), (xe + 0.3, y0 - OVERHANG, eave - drop),
          (xe + 0.3, ys - over, z_lo), (xp - 0.45, ys - over, z_lo)]
    m.hexa(lo + [(x, y, z + 0.12) for x, y, z in lo], roof)
    for k in range(3):
        xc = xw + BODY[0] * (k + 1) / 4
        dormer(m, xc, y0 + 0.35, eave + 0.15, roof, bb, glow, dark)

    # Decks on tall square posts (concrete footings) with Y-brackets.
    beam_z = z_lo - 0.05
    m.box(xp, ys, F - 0.25, xw, y1, F, wood)                        # lake deck
    m.box(xw, ys, F - 0.25, xe, y0, F, wood)                        # front porch
    lake_posts = [(xp + 0.15, y) for y in np.linspace(ys + 0.15, y1 - 0.15, 5)]
    front_posts = [(x, ys + 0.15) for x in np.linspace(xp + 0.15, xe - 0.15, 7)[1:]]
    lake_top = lambda y: eave - 0.4 if y > y0 - 0.6 else beam_z   # under the porch roof at the corner
    for (x, y), top_z in [(p, beam_z) for p in front_posts] + [(p, lake_top(p[1])) for p in lake_posts]:
        m.box(x - 0.22, y - 0.22, z0, x + 0.22, y + 0.22, z0 + 0.3, slab)
        m.box(x - 0.1, y - 0.1, z0 + 0.3, x + 0.1, y + 0.1, top_z, wood)
    m.box(xp - 0.02, y0 - 0.6, eave - 0.4, xp + 0.3, y1 + 0.2, eave - 0.15, wood)   # lake beam
    m.box(xp - 0.02, ys, beam_z - 0.25, xp + 0.3, y0 - 0.6, beam_z, wood)
    m.box(xp, ys - 0.02, beam_z - 0.25, xe + 0.2, ys + 0.3, beam_z, wood)     # front beam
    for x, y in lake_posts:
        y_braces(m, x, y, lake_top(y), "y", wood)
        y_braces(m, x, y, F - 0.25, "y", wood)                       # and under the deck
    for x, y in front_posts:
        y_braces(m, x, y, beam_z - 0.25, "x", wood)
        y_braces(m, x, y, F - 0.25, "x", wood)
    for y in (cy - 2.0, cy + 2.0):
        point_light(f"{name}_Deck_{y:.0f}", (xp + 1.5, y, eave - 0.6), 40.0, (1.0, 0.7, 0.42), 0.08, coll)
    m.box(xw + 4.0, y0 - 0.06, F + 1.6, xw + 4.2, y0, F + 1.9,
          emitter("Cabin_Sconce", (1.0, 0.62, 0.3), 4.0))

    # Railings (dense balusters) and the two stairs.
    stair_w = 1.1
    rise_total = F - z0
    steps = int(math.ceil(rise_total / 0.19))
    run = 0.27
    sy0, sy1 = y1 - 0.4 - stair_w, y1 - 0.4                          # lake stair, north end
    sx0, sx1 = xe - 0.4 - stair_w, xe - 0.4                          # front stair, east end
    railing(m, (xp + 0.15, ys + 0.15), (xp + 0.15, sy0), F, wood, spacing=0.11)
    railing(m, (xp + 0.15, sy1), (xp + 0.15, y1 - 0.1), F, wood, spacing=0.11)
    railing(m, (xp + 0.15, y1 - 0.1), (xw, y1 - 0.1), F, wood, spacing=0.11)
    railing(m, (xp + 0.15, ys + 0.15), (sx0, ys + 0.15), F, wood, spacing=0.11)
    railing(m, (sx1, ys + 0.15), (xe - 0.1, ys + 0.15), F, wood, spacing=0.11)
    railing(m, (xe - 0.1, ys + 0.15), (xe - 0.1, y0), F, wood, spacing=0.11)
    for axis, a0, a1, edge in (("x", sy0, sy1, xp), ("y", sx0, sx1, ys)):
        for k in range(steps):
            zt = F - (k + 1) * rise_total / steps
            d = edge - (k + 1) * run
            if axis == "x":
                m.box(d, a0, zt - 0.04, d + run + 0.03, a1, zt, wood)
            else:
                m.box(a0, d, zt - 0.04, a1, d + run + 0.03, zt, wood)
        end = edge - steps * run
        for a in (a0 + 0.03, a1 - 0.03):
            p = (lambda d, z: (d, a, z)) if axis == "x" else (lambda d, z: (a, d, z))
            m.beam(p(edge, F - 0.1), p(end, z0 + 0.1), 0.06, 0.28, wood)
            m.beam(p(edge, F + 0.95), p(end, z0 + 0.95), 0.07, 0.07, wood)
            for k in range(1, steps):
                q = p(edge - k * run, F - k * rise_total / steps)
                m.box(q[0] - 0.02, q[1] - 0.02, q[2], q[0] + 0.02, q[1] + 0.02, q[2] + 0.9, wood)
    return F


def lawn():
    """Mown lawn around the house: fine colour variation and a little bump."""
    mat, tree = _mat("Cabin_Lawn")
    if tree is None:
        return mat
    tc, _ = _coord(tree)
    big = tree.nodes.new("ShaderNodeTexNoise")
    big.inputs["Scale"].default_value = 0.35
    big.inputs["Detail"].default_value = 6.0
    tree.links.new(tc.outputs["Object"], big.inputs["Vector"])
    fine = tree.nodes.new("ShaderNodeTexNoise")
    fine.inputs["Scale"].default_value = 60.0
    fine.inputs["Detail"].default_value = 4.0
    tree.links.new(tc.outputs["Object"], fine.inputs["Vector"])
    colour = _ramp(tree, big.outputs["Fac"], (0.045, 0.085, 0.02), (0.085, 0.13, 0.035), 0.3, 0.7)
    _finish(tree, colour, 0.9, fine.outputs["Fac"], 0.02, 0.5)
    return mat


def pad_surface(name, pad, top, sampler, ground_mat, coll):
    """The graded pad: flat top, 4:1 slopes down to natural ground, 0.5 m grid."""
    region = pad.buffer(FILL_SKIRT + 2.0, join_style="mitre")
    x0, y0, x1, y1 = region.bounds
    xs = np.arange(x0, x1 + 0.01, 0.5)
    ys = np.arange(y0, y1 + 0.01, 0.5)
    verts, idx = [], {}
    for j, y in enumerate(ys):
        for i, x in enumerate(xs):
            g = sampler(x, y)
            if g is None:
                continue
            d = pad.distance(Point(x, y))
            z = max(top - d / 4.0, g) + LIFT
            idx[(i, j)] = len(verts)
            verts.append((x, y, z))
    faces = []
    for j in range(len(ys) - 1):
        for i in range(len(xs) - 1):
            q = [(i, j), (i + 1, j), (i + 1, j + 1), (i, j + 1)]
            if all(k in idx for k in q):
                faces.append(tuple(idx[k] for k in q))
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    for p in mesh.polygons:
        p.use_smooth = True
    mesh.materials.append(ground_mat)
    obj = bpy.data.objects.new(name, mesh)
    coll.objects.link(obj)
    return obj


def build(root, sampler, ribbon, sampler_class, ground_mat, record):
    """All lots' pads, cabins, patios and drives, one child collection per lot."""
    sites = build_sites()
    gravel = plain("Cabin_Drive_Gravel", (0.24, 0.22, 0.19), 0.95)
    built = {}
    for label, site in sorted(sites.items(), key=lambda kv: int(kv[0].split()[-1])):
        props, pad = site["pad"]
        top = props["top_m"]
        key = label.replace(" ", "_")
        coll = bpy.data.collections.new(f"Cabin_{key}")
        root.children.link(coll)
        surface = pad_surface(f"Pad_{key}", pad, top, sampler, lawn(), coll)
        m = Mesh()
        cabin(m, coll, pad, top + LIFT, key)
        pc = patio_centre(pad)
        on_pad = sampler_class([surface])
        pz = on_pad(pc.x, pc.y) or top
        m.cylinder(pc.x, pc.y, pz - 0.05, pz + 0.04, PATIO_R, flagstone(), n=40)
        fire_pit(m, coll, pc.x, pc.y, pz + 0.04, stone(), timber(),
                 emitter("Cabin_Fire", (1.0, 0.22, 0.02), 10.0), key)
        for k, a in enumerate((40, 130, 220, 310)):  # chairs around the fire, facing it
            r = 1.85
            cxy = (pc.x + r * math.sin(math.radians(a)), pc.y + r * math.cos(math.radians(a)))
            chair(m, cxy[0], cxy[1], pz + 0.04, (a + 180) % 360, timber())
        xw, y0, _, _ = house_box(pad)
        lamp_post(m, coll, pc.x + PATIO_R + 0.6, pc.y - PATIO_R + 0.4, pz, plain(
            "Cabin_Iron", (0.03, 0.03, 0.03), 0.4, 0.8), emitter("Cabin_Lantern", (1.0, 0.62, 0.3), 4.0), key)
        m.object(f"Cabin_{key}", coll)
        if "drive_front" in site:
            line = list(site["drive_front"][1].coords)
            ribbon(f"Drive_{key}", line, 3.6, lambda x, y: max(filter(None, (on_pad(x, y), sampler(x, y)))),
                   0.06, gravel, coll)
        built[label] = {"pad_top_m": top, "patio": [round(pc.x, 1), round(pc.y, 1)]}
    record("cabins_built", len(built) >= 9, lots=sorted(built), basis="out/derived/build_sites.geojson")
    return built
