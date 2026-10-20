"""Phase 2d cabins: graded walk-out sites, lake-house cabins, patios and fire pits
(switchable per shot).

Owner (19 Oct 2026): every lot gets a lake-house / rustic cabin, 2 BR / 1 BA on the main
floor (Hemlock: master and loft bedroom) with an optional 1 BR / 1 BA apartment, storage
and boat storage on the terrace level below. The cabin follows Satterwhite's Hemlock plan
(inputs/reference/hemlock-photo-04.jpg; satterwhite-log-homes.com/floor-plans/hemlock),
with the owner's reference renders (benchmark-cam02-sunset.jpg) for light and mood:
- 30 x 42 ft main floor in honey-tone logs, steep shingle roof, ridge east-west, board-
  and-batten gables; the glazed gable end faces the lake over an 8 x 30 ft gable porch
  with an exposed truss; 6 ft (south, three dormers above) and 4 ft (north) side porches,
  50 ft long; log posts with Y-brackets on concrete piers.
- Terrace level partly built into the slope (grading.py): walk-out at the lake end, a
  concrete back wall with 5 ft of earth against it on the road end, concrete side walls
  stepping down toward the lake with stone veneer where they show; a covered terrace
  porch under the gable porch; a boat / storage door on the north side.
- Hemlock-style stairs tucked against the house: a switchback with a landing from the
  gable porch down to the lake terrace, and a short run with a top landing from the
  front porch to the entry yard, both alongside the south porch.
- A flagstone patio with a stone fire pit, chairs and log benches on the lake terrace.

Per lot (from out/derived/build_sites.geojson, written by scripts/build_sites.py):
- `Pad_<lot>`: the finished-grade surface (lawn), laid just above the terrain; where the
  grading cuts, the terrain's `Grade_<lot>` shape key lowers it.
- `Cabin_<lot>`: the cabin, patio and lights. `Drive_<lot>`: the gravel front drive.

Each lot is its own child collection of `Cabins`; render.py includes the lots a shot
lists (`cabins: [Lot 5]` or `cabins: all`), turns on their shape keys and hides the trees
build_baseline set aside on their footprints (`Vegetation_BuildSite_<lot>`). Massing is
illustrative; foundations, piers and walls need a structural engineer (and, on the area's
expansive clay, a geotechnical report).
"""

import json
import math

import bmesh
import bpy
import numpy as np
from mathutils import Vector

import grading
import lrh

import shapely  # noqa: E402
from shapely.geometry import Point  # noqa: E402

FT = 0.3048
BODY = grading.BODY             # main floor E-W x N-S: 1,260 sq ft (Hemlock)
GROUND_STOREY = grading.GROUND_STOREY
WALL = 2.9                      # main-floor wall height to the eave
PITCH = 10 / 12                 # main roof (steep, as in the owner's reference photo)
PORCH_PITCH = 4 / 12
OVERHANG = 0.6
PATIO_R = 2.8
LIFT = 0.03                     # finished-grade surface above the terrain
RISER, TREAD, STAIR_W = 0.19, 0.27, 1.05
FITS = {"standard"}             # the Hemlock footprint does not fit Lot 10's 60 x 40 ft pad


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
    return {k: v for k, v in lots.items()
            if "pad" in v and v["pad"][0].get("house") in FITS and "terrace_floor_m" in v["pad"][0]}


def walk_line(label, pad):
    """Owner, 19 Oct 2026: a simple 5 ft gravel walking path from the lake stair down
    across the lake-side acre to the lot's shoreline access path (which starts at the
    lot's west line; lotplan.shoreline_layout). Later phases add the full site network."""
    sites = sorted(lrh.ROOT.glob("out/*/lot_sites.json"))
    if not sites:
        return None
    west = json.loads(sites[-1].read_text()).get(label, {}).get("west")
    if west is None:
        return None
    L = grading.layout(pad.bounds)
    start = (L["xp"] - 0.3, L["ys"] - 1.6)          # below the switchback stair
    mid = (start[0] - 12.0, start[1])
    return shapely.geometry.LineString([start, mid, tuple(west)])


def clearing(site, label=None):
    """Footprint where no tree may stand once the lot is built: the graded area, the
    patio and the front drive."""
    _, pad = site["pad"]
    parts = [pad.buffer(8.0, join_style="mitre"), patio_centre(pad).buffer(PATIO_R + 2)]
    if "drive_front" in site:
        parts.append(site["drive_front"][1].buffer(3.5))
    walk = walk_line(label, pad) if label else None
    if walk is not None:
        parts.append(walk.buffer(2.5))
    return shapely.union_all(parts)


def house_box(pad):
    L = grading.layout(pad.bounds)
    return L["xw"], L["y0"], L["xe"], L["y1"]


def patio_centre(pad):
    """On the lake terrace, west of the gable porch."""
    L = grading.layout(pad.bounds)
    return Point(L["xp"] - PATIO_R - 0.5, (L["y0"] + L["y1"]) / 2 + 0.8)


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




def concrete():
    mat, tree = _mat("Cabin_Concrete")
    if tree is None:
        return mat
    tc, _ = _coord(tree)
    noise = tree.nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 2.5
    tree.links.new(tc.outputs["Object"], noise.inputs["Vector"])
    _finish(tree, _ramp(tree, noise.outputs["Fac"], (0.30, 0.29, 0.27), (0.42, 0.41, 0.38)), 0.9)
    return mat


def sloped_wall(m, xa, xb, y0, y1, za_lo, za_hi, zb_lo, zb_hi, mat):
    """A wall slab from x = xa to xb, y0..y1 thick, with sloping bottom and top."""
    m.hexa([(xa, y0, za_lo), (xb, y0, zb_lo), (xb, y1, zb_lo), (xa, y1, za_lo),
            (xa, y0, za_hi), (xb, y0, zb_hi), (xb, y1, zb_hi), (xa, y1, za_hi)], mat)


def pier_post(m, x, y, z_grade, z_top, wood, conc):
    """A round log post on a concrete pier (pier 18 in above grade)."""
    m.box(x - 0.2, y - 0.2, z_grade - 0.3, x + 0.2, y + 0.2, z_grade + 0.45, conc)
    m.cylinder(x, y, z_grade + 0.45, z_top, 0.12, wood, n=12)


def stair_flight(m, x0, y0, y1, z_top, n, direction, wood, z_floor):
    """n treads in the lane y0..y1, starting at x0 at z_top and stepping down by RISER
    each TREAD in `direction` (+1 east, -1 west). Returns the x at the bottom."""
    for k in range(n):
        zt = z_top - (k + 1) * RISER
        xa = x0 + direction * k * TREAD
        xb = xa + direction * (TREAD + 0.03)
        m.box(min(xa, xb), y0, zt - 0.04, max(xa, xb), y1, zt, wood)
    x_end = x0 + direction * n * TREAD
    for y in (y0 + 0.03, y1 - 0.03):                               # stringers
        m.beam((x0, y, z_top - 0.15), (x_end, y, max(z_floor, z_top - n * RISER) + 0.05), 0.06, 0.28, wood)
    return x_end


def stair_rail(m, x0, x1, y, z0, z1, wood):
    """Sloping handrail with balusters from (x0, z0) to (x1, z1) along y."""
    m.beam((x0, y, z0 + 0.95), (x1, y, z1 + 0.95), 0.07, 0.07, wood)
    n = max(2, int(abs(x1 - x0) / 0.12))
    for k in range(1, n):
        t = k / n
        x, z = x0 + (x1 - x0) * t, z0 + (z1 - z0) * t
        m.box(x - 0.02, y - 0.02, z, x + 0.02, y + 0.02, z + 0.92, wood)


def log_bench(m, cx, cy, z, face_deg, wood):
    """A half-log bench on two log stumps (log accents round the fire)."""
    h = math.radians(face_deg)
    side = np.array([math.cos(h), -math.sin(h)])
    for s in (-0.6, 0.6):
        p = np.array([cx, cy]) + side * s
        m.cylinder(p[0], p[1], z, z + 0.38, 0.17, wood, n=10)
    a = np.array([cx, cy]) - side * 0.85
    b = np.array([cx, cy]) + side * 0.85
    m.beam((a[0], a[1], z + 0.45), (b[0], b[1], z + 0.45), 0.36, 0.14, wood)


def cabin(m, coll, pad, T, E, grade, name):
    """The Hemlock-style cabin on its walk-out site; `grade(x, y)` is finished grade."""
    logs, wood, dark, bb, rock = log_siding(), timber(), trim(), board_batten(), stone()
    roof, glow, conc = shingles(), window_glow(), concrete()
    L = grading.layout(pad.bounds)
    xw, xe, y0, y1, xp, ys, yn = (L[k] for k in ("xw", "xe", "y0", "y1", "xp", "ys", "yn"))
    cy = (y0 + y1) / 2
    F = T + GROUND_STOREY
    eave = F + WALL
    side_top = lambda x: T + (E - T) * (x - xw) / (xe - xw) + 0.45   # concrete above side grade
    door0, door1 = xw + grading.BOAT_DOOR[0], xw + grading.BOAT_DOOR[1]
    north_grade = lambda x: T if x <= door1 + 0.6 else T + (E - T) * (x - door1 - 0.6) / (xe - door1 - 0.6)

    # ---- Terrace level (walk-out): concrete back and side walls, logs above.
    m.box(xw, y0, T - 0.3, xe, y1, T + 0.02, conc)                       # slab
    m.box(xp, y0, T - 0.2, xw, y1, T + 0.02, conc)                       # covered terrace porch
    m.box(xe - 0.3, y0, T - 0.3, xe, y1, E + 0.45, conc)                 # back wall, buried 5 ft
    m.box(xe - 0.3, y0, E + 0.45, xe, y1, F - 0.35, logs)
    # South side wall: concrete stepping down to the lake, stone veneer where it shows.
    sloped_wall(m, xw, xe - 0.3, y0, y0 + 0.3, T - 0.3, side_top(xw), T - 0.3, side_top(xe), conc)
    sloped_wall(m, xw, xe, y0 - 0.08, y0, side_top(xw) - 0.5, side_top(xw), E - 0.05, side_top(xe), rock)
    sloped_wall(m, xw, xe - 0.3, y0, y0 + 0.3, side_top(xw), F - 0.35, side_top(xe), F - 0.35, logs)
    # North side wall, with the boat / storage door at the lake end.
    nt = lambda x: north_grade(x) + 0.45
    m.box(xw, y1 - 0.3, T - 0.3, door0, y1, nt(xw), conc)
    m.box(xw, y1 - 0.3, nt(xw), door0, y1, F - 0.35, logs)
    m.box(door0, y1 - 0.3, T + 2.5, door1, y1, F - 0.35, logs)
    m.box(door0 + 0.05, y1 - 0.05, T + 0.02, door1 - 0.05, y1 + 0.02, T + 2.45,
          plain("Cabin_Boat_Door", (0.30, 0.17, 0.07), 0.6))
    for xa, xb in ((door1, door1 + 0.6), (door1 + 0.6, xe - 0.3)):
        sloped_wall(m, xa, xb, y1 - 0.3, y1, T - 0.3, nt(xa), T - 0.3, nt(xb), conc)
        sloped_wall(m, xa, xb, y1, y1 + 0.08, north_grade(xa) - 0.05, nt(xa), north_grade(xb) - 0.05, nt(xb), rock)
        sloped_wall(m, xa, xb, y1 - 0.3, y1, nt(xa), F - 0.35, nt(xb), F - 0.35, logs)
    # Lake (west) wall: logs on a stem, rec room glass doors, bedroom window.
    m.box(xw, y0, T - 0.3, xw + 0.3, y1, T + 0.3, conc)
    m.box(xw, y0, T + 0.3, xw + 0.3, y1, F - 0.35, logs)
    window(m, xw, cy + 1.2, T + 0.05, 2.4, 2.1, "W", glow)          # sliding doors
    window(m, xw, y0 + 1.7, T + 0.9, 1.4, 1.3, "W", glow)           # bedroom
    window(m, xw, y1 - 1.2, T + 0.9, 1.2, 1.3, "W", glow)
    window(m, xw + 2.4, y0, T + 1.0, 1.2, 1.2, "S", glow)           # bedroom, south
    m.box(xw - 0.1, y0 - 0.1, F - 0.35, xe + 0.1, y1 + 0.1, F, wood)  # floor beams

    # ---- Main floor: logs with corner posts; windows and doors.
    m.box(xw, y0, F, xe, y1, eave, logs)
    for x in (xw, xe):
        for y in (y0, y1):
            m.box(x - 0.15, y - 0.15, F, x + 0.15, y + 0.15, eave, logs)
    for yy in (y0 + 1.6, y1 - 1.6):                                  # lake wall: big glass
        window(m, xw, yy, F + 0.5, 1.6, 1.9, "W", glow)
    window(m, xw, cy, F + 0.05, 1.8, 2.3, "W", glow)
    for xx in (xw + 2.0, xw + 5.0):
        window(m, xx, y0, F + 0.7, 1.4, 1.5, "S", glow)
    window(m, xw + 8.0, y0, F + 0.05, 1.0, 2.15, "S", glow)         # front door
    window(m, xe - 2.4, y0, F + 0.8, 1.2, 1.4, "S", glow)
    for xx in (xw + 3.0, xe - 4.5, xe - 1.6):
        window(m, xx, y1, F + 0.85, 1.0, 1.3, "N", glow)
    window(m, xe, cy, F + 0.85, 0.9, 1.3, "E", glow)

    # ---- Roof: ridge east-west, carried over the gable porch; truss; side porch roofs.
    rise = (BODY[1] / 2) * PITCH
    ridge = eave + rise
    for x in (xw, xe - 0.15):
        m.gable_x(y0, y1, x, eave, ridge, 0.15, bb)
    window(m, xw, cy, eave + 0.15, 1.5, rise - 1.0, "W", glow)
    for dy in (-1.75, 1.75):
        window(m, xw, cy + dy, eave + 0.15, 1.5, (rise - 1.0) * 0.55, "W", glow)
    window(m, xe, cy, eave + 0.4, 1.0, 1.1, "E", glow)
    th = 0.16
    drop = OVERHANG * PITCH
    xr0, xr1 = xp - 0.45, xe + OVERHANG
    for ya in (y0 - OVERHANG, y1 + OVERHANG):
        za = eave - drop
        lo = [(xr0, ya, za), (xr1, ya, za), (xr1, cy, ridge), (xr0, cy, ridge)]
        m.hexa(lo + [(x, y, z + th) for x, y, z in lo], roof)
    for x in (xr0, xr1 - 0.08):
        for ya in (y0 - OVERHANG, y1 + OVERHANG):
            m.beam((x + 0.04, ya, eave - drop), (x + 0.04, cy, ridge), 0.08, 0.26, dark)
    m.beam((xr0, cy, ridge + th), (xr1, cy, ridge + th), 0.2, 0.08, dark)
    xt = xp + 0.1
    m.beam((xt, y0 - 0.1, eave - 0.1), (xt, y1 + 0.1, eave - 0.1), 0.2, 0.3, wood)
    m.beam((xt, cy, eave - 0.1), (xt, cy, ridge - 0.2), 0.2, 0.2, wood)
    for ya in (y0, y1):
        m.beam((xt, ya, eave), (xt, cy, ridge - 0.15), 0.2, 0.22, wood)
        m.beam((xt, (ya + cy) / 2, eave - 0.1), (xt, cy, eave + rise * 0.55), 0.14, 0.14, wood)
    over = 0.4
    porch_z = {}
    for side, depth in (("S", grading.SOUTH_PORCH), ("N", grading.NORTH_PORCH)):
        z_lo = eave - drop - (depth - OVERHANG + over) * PORCH_PITCH
        porch_z[side] = z_lo - 0.05
        if side == "S":
            ya, yb = y0 - OVERHANG, ys - over
        else:
            ya, yb = y1 + OVERHANG, yn + over
        lo = [(xr0, ya, eave - drop), (xe + 0.3, ya, eave - drop), (xe + 0.3, yb, z_lo), (xr0, yb, z_lo)]
        m.hexa(lo + [(x, y, z + 0.12) for x, y, z in lo], roof)
    for k in range(3):
        dormer(m, xw + BODY[0] * (k + 1) / 4, y0 + 0.35, eave + 0.15, roof, bb, glow, dark)

    # ---- Porch decks on log posts and concrete piers, with Y-brackets.
    m.box(xp, y0, F - 0.25, xw, y1, F, wood)                        # gable porch 8 x 30
    m.box(xp, ys, F - 0.25, xe, y0, F, wood)                        # south porch 6 x 50
    m.box(xp, y1, F - 0.25, xe, yn, F, wood)                        # north porch 4 x 50
    xs = np.linspace(xp + 0.15, xe - 0.15, 8)
    for side, yy in (("S", ys + 0.15), ("N", yn - 0.15)):
        top = porch_z[side]
        for x in xs:
            pier_post(m, x, yy, grade(x, yy), top, wood, conc)
            y_braces(m, x, yy, top - 0.25, "x", wood)
        m.box(xp, yy - 0.15, top - 0.25, xe + 0.2, yy + 0.15, top, wood)
    for y in np.linspace(y0 + 0.5, y1 - 0.5, 4):                    # gable porch posts
        pier_post(m, xp + 0.15, y, T, eave - 0.4, wood, conc)
        y_braces(m, xp + 0.15, y, eave - 0.4, "y", wood)
        y_braces(m, xp + 0.15, y, F - 0.25, "y", wood)
    m.box(xp - 0.02, y0 - 0.3, eave - 0.4, xp + 0.3, y1 + 0.3, eave - 0.15, wood)
    for y in (cy - 2.0, cy + 2.0):
        point_light(f"{name}_Porch_{y:.0f}", (xp + 1.2, y, eave - 0.6), 40.0, (1.0, 0.7, 0.42), 0.08, coll)
        point_light(f"{name}_Terrace_{y:.0f}", (xp + 1.2, y, F - 0.5), 30.0, (1.0, 0.7, 0.42), 0.08, coll)

    # ---- Stairs, Hemlock style: tucked alongside the south porch.
    # Lake stair: top landing off the porch, a flight east along the porch, a mid landing,
    # and a flight back west down to the lake terrace.
    inner = (ys - 0.05 - STAIR_W, ys - 0.05)
    outer = (inner[0] - 0.05 - STAIR_W, inner[0] - 0.05)
    xl0 = xp + 0.1                                                  # top landing west edge
    xa0 = xl0 + STAIR_W
    g_bottom = grade(xl0 + 0.5, outer[0] + 0.5)
    risers = max(2, int(math.ceil((F - g_bottom) / RISER)))
    n1 = risers // 2
    m.box(xl0, inner[0], F - 0.25, xa0, inner[1], F, wood)          # top landing
    xa1 = stair_flight(m, xa0, inner[0], inner[1], F, n1, +1, wood, g_bottom)
    z_mid = F - n1 * RISER
    m.box(xa1, outer[0], z_mid - 0.25, xa1 + STAIR_W, inner[1], z_mid, wood)   # mid landing
    n2 = int(math.ceil((z_mid - g_bottom) / RISER))
    xb1 = stair_flight(m, xa1, outer[0], outer[1], z_mid, n2, -1, wood, g_bottom)
    for x, y, zt in ((xl0 + 0.1, inner[0] + 0.1, F - 0.25), (xa0 - 0.1, inner[0] + 0.1, F - 0.25),
                     (xa1 + 0.1, outer[0] + 0.1, z_mid - 0.25), (xa1 + STAIR_W - 0.1, outer[0] + 0.1, z_mid - 0.25),
                     (xa1 + STAIR_W - 0.1, inner[1] - 0.1, z_mid - 0.25)):
        pier_post(m, x, y, grade(x, y), zt + 1.2, wood, conc)
    stair_rail(m, xa1 + STAIR_W, xb1, outer[0] + 0.03, z_mid, g_bottom, wood)
    stair_rail(m, xa0, xa1, inner[0] - 0.02, F, z_mid, wood)
    railing(m, (xl0, inner[0] + 0.03), (xl0, inner[1]), F, wood, spacing=0.11)
    railing(m, (xa1 + STAIR_W - 0.03, outer[0]), (xa1 + STAIR_W - 0.03, inner[1]), z_mid, wood, spacing=0.11)
    # Front stair: a top landing at the porch's east end and a short run east to the yard.
    xf0 = xe - 3.7
    g_front = grade(xe + 0.3, inner[0] + 0.5)
    nf = max(2, int(math.ceil((F - g_front) / RISER)))
    m.box(xf0, inner[0], F - 0.25, xf0 + STAIR_W, inner[1], F, wood)
    xf1 = stair_flight(m, xf0 + STAIR_W, inner[0], inner[1], F, nf, +1, wood, g_front)
    stair_rail(m, xf0 + STAIR_W, xf1, inner[0] + 0.03, F, g_front, wood)
    railing(m, (xf0, inner[0] + 0.03), (xf0 + STAIR_W, inner[0] + 0.03), F, wood, spacing=0.11)
    for x in (xf0 + 0.1, xf0 + STAIR_W - 0.1):
        pier_post(m, x, inner[0] + 0.1, grade(x, inner[0] + 0.1), F - 0.25, wood, conc)

    # ---- Porch railings, with openings onto the two stair landings.
    yr = ys + 0.15
    for a, b in ((xp + 0.15, xl0), (xa0, xf0), (xf0 + STAIR_W, xe - 0.1)):
        if b - a > 0.2:
            railing(m, (a, yr), (b, yr), F, wood, spacing=0.11)
    railing(m, (xp + 0.15, ys + 0.15), (xp + 0.15, yn - 0.15), F, wood, spacing=0.11)
    railing(m, (xp + 0.15, yn - 0.15), (xe - 0.1, yn - 0.15), F, wood, spacing=0.11)
    for yy in (ys + 0.15, yn - 0.15):
        railing(m, (xe - 0.1, yy), (xe - 0.1, y0 if yy < y0 else y1), F, wood, spacing=0.11)
    m.box(xw + 8.7, y0 - 0.06, F + 1.6, xw + 8.9, y0, F + 1.9, emitter("Cabin_Sconce", (1.0, 0.62, 0.3), 4.0))
    return {"stair_bottom": (xb1, (outer[0] + outer[1]) / 2, g_bottom)}


def carport(m, coll, L, E, name):
    """Covered parking (owner, 19 Oct 2026) at the end of the drive, off the house's
    south-east corner: a concrete slab at entry-yard level, log posts on concrete piers
    with Y-brackets, and a pitched shingle roof with board-and-batten gables and an
    exposed king-post truss to match the house. Ridge east-west, open to the drive."""
    wood, bb, roof, conc, dark = timber(), board_batten(), shingles(), concrete(), trim()
    x0, y0, x1, y1 = L["carport"]
    z = E + LIFT
    m.box(x0, y0, z - 0.15, x1, y1, z + 0.1, conc)
    eave = z + 0.1 + 2.9
    ym = (y0 + y1) / 2
    for x in (x0 + 0.2, x1 - 0.2):
        for y in (y0 + 0.2, ym, y1 - 0.2):
            pier_post(m, x, y, z + 0.1, eave, wood, conc)
            y_braces(m, x, y, eave, "x", wood)
    for y in (y0 + 0.2, y1 - 0.2):
        m.box(x0, y - 0.13, eave - 0.05, x1, y + 0.13, eave + 0.22, wood)       # eave beams
    pitch, ov = 8 / 12, 0.45
    ridge = eave + 0.22 + (ym - y0) * pitch
    for ya in (y0 - ov, y1 + ov):
        za = eave + 0.22 - ov * pitch
        lo = [(x0 - ov, ya, za), (x1 + ov, ya, za), (x1 + ov, ym, ridge), (x0 - ov, ym, ridge)]
        m.hexa(lo + [(x, y, zz + 0.14) for x, y, zz in lo], roof)
    m.beam((x0 - ov, ym, ridge + 0.14), (x1 + ov, ym, ridge + 0.14), 0.18, 0.07, dark)
    for x in (x0 + 0.05, x1 - 0.2):
        m.gable_x(y0, y1, x, eave + 0.22, ridge - 0.05, 0.15, bb)             # gable infill
    for x in (x0 - ov + 0.05, x1 + ov - 0.1):                                   # rake boards
        for ya in (y0 - ov, y1 + ov):
            m.beam((x, ya, eave + 0.22 - ov * pitch), (x, ym, ridge), 0.07, 0.22, dark)
    # Open truss at the drive end (the gable infill sits only above the tie beam).
    xt = x1 - 0.2
    m.beam((xt, y0, eave + 0.1), (xt, y1, eave + 0.1), 0.18, 0.26, wood)
    m.beam((xt, ym, eave + 0.1), (xt, ym, ridge - 0.1), 0.16, 0.16, wood)
    point_light(f"{name}_Carport", (x0 + (x1 - x0) / 2, ym, eave - 0.2), 50.0, (1.0, 0.72, 0.45), 0.1, coll)


def walkways(L, info, E):
    """Concrete walks (owner, 19 Oct 2026): carport to the front stair (front door), and
    along the south side yard to the lake-side switchback stair."""
    x0, y0, x1, y1 = L["carport"]
    xe, ys, xp = L["xe"], L["ys"], L["xp"]
    lane = ys - 0.57                                                  # front stair lane
    yw = ys - 2.9                                                     # south side-yard walk
    sx, sy, _ = info["stair_bottom"]
    return [[(x0, lane), (xe - 0.2, lane)],
            [(xe + 0.6, lane), (xe + 0.6, yw), (sx - 0.3, yw), (sx - 0.3, sy)]]


def lawn():
    """Mown lawn on the graded site: fine colour variation and a little bump."""
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
    colour = _ramp(tree, big.outputs["Fac"], (0.038, 0.072, 0.018), (0.068, 0.108, 0.03), 0.3, 0.7)
    # Mowing stripes, 1.5 m wide, running east-west (Phase 3a R2).
    _, sep = _coord(tree)
    band = _math(tree, "LESS_THAN", _math(tree, "FRACT", _math(tree, "DIVIDE", sep.outputs["Y"], 3.0)), 0.5)
    shade = _math(tree, "ADD", _math(tree, "MULTIPLY", band, 0.16), 0.92)
    stripe = tree.nodes.new("ShaderNodeMix")
    stripe.data_type = "RGBA"
    stripe.blend_type = "MULTIPLY"
    stripe.inputs["Factor"].default_value = 1.0
    tree.links.new(colour, stripe.inputs["A"])
    comb = tree.nodes.new("ShaderNodeCombineColor")
    for k in ("Red", "Green", "Blue"):
        tree.links.new(shade, comb.inputs[k])
    tree.links.new(comb.outputs["Color"], stripe.inputs["B"])
    _finish(tree, stripe.outputs["Result"], 0.9, fine.outputs["Fac"], 0.02, 0.5)
    return mat


REGION = 12.0   # graded area reaches at most this far past the pad (5 ft berm at 4:1 = 6 m)
LAWN = 9.0      # mown lawn apron round the pad


def site_surface(name, pad, T, E, sampler, mat, coll):
    """Finished grade over the pad and its slopes, 0.5 m grid, just above the terrain."""
    x0, y0, x1, y1 = pad.buffer(REGION).bounds
    xs, ys = np.arange(x0, x1 + 0.01, 0.5), np.arange(y0, y1 + 0.01, 0.5)
    gx, gy = np.meshgrid(xs, ys)
    nat = np.array([sampler(x, y) if sampler(x, y) is not None else np.nan
                    for x, y in zip(gx.ravel(), gy.ravel())])
    fin = grading.design(gx.ravel(), gy.ravel(), np.nan_to_num(nat), pad.bounds, T, E)
    # A clean mown apron: everything within LAWN of the pad (covers the 4:1 / 3:1 slopes).
    keep = ~np.isnan(nat) & shapely.contains_xy(pad.buffer(LAWN), gx.ravel(), gy.ravel())
    idx = -np.ones(gx.size, int)
    idx[keep] = np.arange(keep.sum())
    # Feather the lift over the apron's outer metre so its edge meets the terrain.
    edge = shapely.distance(shapely.points(gx.ravel(), gy.ravel()), pad)
    lift = 0.004 + (LIFT - 0.004) * np.clip(LAWN - edge, 0.0, 1.0)
    verts = np.column_stack([gx.ravel(), gy.ravel(), fin + lift])[keep]
    nx = len(xs)
    faces = []
    for j in range(len(ys) - 1):
        for i in range(nx - 1):
            q = [j * nx + i, j * nx + i + 1, (j + 1) * nx + i + 1, (j + 1) * nx + i]
            if all(idx[k] >= 0 for k in q):
                faces.append(tuple(int(idx[k]) for k in q))
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts.tolist(), [], faces)
    for p in mesh.polygons:
        p.use_smooth = True
    mesh.materials.append(mat)
    obj = bpy.data.objects.new(name, mesh)
    coll.objects.link(obj)
    return obj


def grade_terrain(terrain, key, pad, T, E):
    """Shape key on the site terrain lowering it where the grading cuts (so the finished
    surface shows); render.py turns it on with the lot's cabin."""
    mesh = terrain.data
    co = np.empty(len(mesh.vertices) * 3, np.float32)
    mesh.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)
    x0, y0, x1, y1 = pad.buffer(REGION).bounds
    sel = (co[:, 0] > x0) & (co[:, 0] < x1) & (co[:, 1] > y0) & (co[:, 1] < y1)
    fin = grading.design(co[sel, 0], co[sel, 1], co[sel, 2], pad.bounds, T, E)
    lower = fin < co[sel, 2] - 0.01                      # cut only
    if not lower.any():
        return 0
    if mesh.shape_keys is None:
        terrain.shape_key_add(name="Basis", from_mix=False)
    sk = terrain.shape_key_add(name=f"Grade_{key}", from_mix=False)
    new = co.copy()
    z = new[sel, 2]
    z[lower] = fin[lower] - 0.06
    new[sel, 2] = z
    sk.data.foreach_set("co", new.ravel())
    sk.value = 0.0
    return int(lower.sum())


def build(root, sampler, ribbon, sampler_class, terrain, record):
    """All lots' graded sites, cabins, patios and drives, one child collection per lot."""
    sites = build_sites()
    gravel = plain("Cabin_Drive_Gravel", (0.24, 0.22, 0.19), 0.95)
    built = {}
    for label, site in sorted(sites.items(), key=lambda kv: int(kv[0].split()[-1])):
        props, pad = site["pad"]
        T, E = props["terrace_floor_m"], props["back_grade_m"]
        key = label.replace(" ", "_")
        coll = bpy.data.collections.new(f"Cabin_{key}")
        root.children.link(coll)
        surface = site_surface(f"Pad_{key}", pad, T, E, sampler, lawn(), coll)
        lowered = grade_terrain(terrain, key, pad, T, E)
        on_site = sampler_class([surface])

        def grade(x, y, on_site=on_site, pad=pad, T=T, E=E):
            z = on_site(x, y)
            if z is not None:
                return z - LIFT
            nat = sampler(x, y)
            return float(grading.design([x], [y], [nat or T], pad.bounds, T, E)[0])

        m = Mesh()
        info = cabin(m, coll, pad, T, E, grade, key)
        pc = patio_centre(pad)
        pz = grade(pc.x, pc.y) + LIFT
        m.cylinder(pc.x, pc.y, pz - 0.05, pz + 0.04, PATIO_R, flagstone(), n=40)
        fire_pit(m, coll, pc.x, pc.y, pz + 0.04, stone(), timber(),
                 emitter("Cabin_Fire", (1.0, 0.22, 0.02), 10.0), key)
        for a in (60, 300):                                         # chairs facing the fire
            cxy = (pc.x + 1.85 * math.sin(math.radians(a)), pc.y + 1.85 * math.cos(math.radians(a)))
            chair(m, cxy[0], cxy[1], pz + 0.04, (a + 180) % 360, timber())
        for a in (160, 220):                                        # log benches
            cxy = (pc.x + 1.9 * math.sin(math.radians(a)), pc.y + 1.9 * math.cos(math.radians(a)))
            log_bench(m, cxy[0], cxy[1], pz + 0.04, (a + 180) % 360, timber())
        Lc = grading.layout(pad.bounds)
        carport(m, coll, Lc, E, key)
        for k, line in enumerate(walkways(Lc, info, E)):
            ribbon(f"Walk_Concrete_{key}_{k}", line, 1.2,
                   lambda x, y, on_site=on_site: on_site(x, y) if on_site(x, y) is not None else sampler(x, y),
                   0.05, concrete(), coll)
        sx, sy, sz = info["stair_bottom"]
        lamp_post(m, coll, sx - 0.8, sy - 0.6, sz, plain("Cabin_Iron", (0.03, 0.03, 0.03), 0.4, 0.8),
                  emitter("Cabin_Lantern", (1.0, 0.62, 0.3), 4.0), key)
        m.object(f"Cabin_{key}", coll)
        if "drive_front" in site:
            line = list(site["drive_front"][1].coords)
            ribbon(f"Drive_{key}", line, 3.6,
                   lambda x, y, on_site=on_site: on_site(x, y) if on_site(x, y) is not None else sampler(x, y),
                   0.06, gravel, coll)
        walk = walk_line(label, pad)
        if walk is not None:
            path_mat = bpy.data.materials.get("Path_Gravel_Grey") or plain("Path_Gravel_Grey", (0.46, 0.46, 0.44), 0.95)
            ribbon(f"Walk_{key}", list(walk.coords), 5 * FT,
                   lambda x, y, on_site=on_site: on_site(x, y) if on_site(x, y) is not None else sampler(x, y),
                   0.08, path_mat, coll)
        built[label] = {"terrace_floor_m": T, "back_grade_m": E, "terrain_vertices_cut": lowered,
                        "patio": [round(pc.x, 1), round(pc.y, 1)]}
    skipped = sorted(set(f"Lot {i}" for i in range(1, 11)) - set(built))
    record("cabins_built", len(built) >= 9, lots=sorted(built), skipped=skipped,
           note="the Hemlock footprint does not fit Lot 10's 60 x 40 ft pad",
           basis="out/derived/build_sites.geojson")
    return built
