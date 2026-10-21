"""The conceptual planting plan in the model (switchable: `Planting`), from
out/derived/planting.json (scripts/planting_plan.py). Sizes are about five to seven
years after planting. Each species is one prototype mesh; plants are linked duplicates
with a random turn and scale.
"""

import json
import math
import random

import bpy

import cabins
import lrh


def _fol(name, rgb):
    import trees
    return trees.foliage_material(name, rgb)


def bamboo(m, rng):
    """Clumping bamboo: a dense clump of slender arching culms with fine leafy sprays
    along their upper two-thirds."""
    culm = cabins.plain("Plant_Bamboo_Culm", (0.20, 0.27, 0.07), 0.45)
    leaf = _fol("bamboo_leaf", (0.07, 0.15, 0.03))
    for _ in range(34):
        a, r = rng.uniform(0, 2 * math.pi), rng.uniform(0, 0.5)
        h = rng.uniform(5.0, 7.5)
        lean = rng.uniform(0.4, 1.4)
        base = (math.cos(a) * r, math.sin(a) * r, 0.0)
        mid = (base[0] + math.cos(a) * lean * 0.35, base[1] + math.sin(a) * lean * 0.35, h * 0.6)
        top = (base[0] + math.cos(a) * lean, base[1] + math.sin(a) * lean, h)
        m.beam(base, mid, 0.03, 0.03, culm)
        m.beam(mid, top, 0.02, 0.02, culm)
        for k in range(5):                                   # leaf sprays along the culm
            t = 0.45 + 0.55 * k / 4
            px = base[0] + (top[0] - base[0]) * t + rng.uniform(-0.25, 0.25)
            py = base[1] + (top[1] - base[1]) * t + rng.uniform(-0.25, 0.25)
            m.blob(px, py, h * t, 0.32, 0.32, 0.22, leaf, seg=6, rings=4, rng=rng)


def pine(m, rng):
    m.cylinder(0, 0, 0, 9.5, 0.17, cabins.plain("Plant_Pine_Bark", (0.12, 0.07, 0.045), 0.9), n=8, r_top=0.08)
    leaf = _fol("pine_needles", (0.025, 0.065, 0.025))
    for k in range(9):
        z = rng.uniform(5.0, 9.8)
        a, r = rng.uniform(0, 2 * math.pi), rng.uniform(0.2, 1.3) * (1.2 - (z - 5) / 6)
        m.blob(math.cos(a) * r, math.sin(a) * r, z, 1.4, 1.4, 0.9, leaf, rng=rng)


def broadleaf(m, rng, bark, leaf_rgb, name, trunk_h, crown_r, crown_z, spread, n=10, fall=None):
    m.cylinder(0, 0, 0, trunk_h, 0.2, cabins.plain(f"Plant_{name}_Bark", bark, 0.85), n=10, r_top=0.12)
    leaf = _fol(f"{name}_leaf", leaf_rgb)
    alt = _fol(f"{name}_fall", fall) if fall else None
    for _ in range(n):
        a, r = rng.uniform(0, 2 * math.pi), rng.uniform(0, spread)
        m.blob(math.cos(a) * r, math.sin(a) * r, rng.uniform(*crown_z), crown_r, crown_r, crown_r * 0.8,
               alt if alt and rng.random() < 0.35 else leaf, rng=rng)


def bald_cypress(m, rng):
    """A narrow cone of feathery foliage turning rust in fall, on a flared base."""
    bark = cabins.plain("Plant_Cypress_Bark", (0.20, 0.10, 0.06), 0.9)
    m.cylinder(0, 0, 0, 0.6, 0.45, bark, n=10, r_top=0.2)
    m.cylinder(0, 0, 0.6, 9.0, 0.2, bark, n=10, r_top=0.06)
    green, rust = _fol("cypress_leaf", (0.07, 0.10, 0.03)), _fol("cypress_fall", (0.26, 0.10, 0.03))
    for k in range(10):
        z = 2.2 + k * 0.75
        r = 1.7 * (1 - k / 11)
        m.blob(0, 0, z, r, r, 0.6, rust if k % 3 == 0 else green, rng=rng)


BUILDERS = {
    "bamboo": bamboo,
    "loblolly_pine": pine,
    "oak": lambda m, rng: broadleaf(m, rng, (0.08, 0.06, 0.05), (0.045, 0.085, 0.022), "oak", 2.4, 1.5,
                                    (3.0, 5.2), 2.2),
    "water_oak": lambda m, rng: broadleaf(m, rng, (0.09, 0.07, 0.05), (0.05, 0.10, 0.03), "water_oak", 2.6,
                                          1.4, (3.0, 6.0), 1.8),
    "pecan": lambda m, rng: broadleaf(m, rng, (0.10, 0.08, 0.06), (0.11, 0.14, 0.035), "pecan", 3.4, 1.5,
                                      (4.5, 8.5), 2.6, n=12, fall=(0.30, 0.24, 0.04)),
    "sycamore": lambda m, rng: broadleaf(m, rng, (0.55, 0.52, 0.46), (0.13, 0.15, 0.04), "sycamore", 3.6,
                                         1.6, (4.5, 8.0), 2.4, n=11, fall=(0.32, 0.22, 0.06)),
    "bald_cypress": bald_cypress,
    "crape_myrtle": lambda m, rng: cabins.crape_myrtle(m, 0, 0, 0, rng),
}


def build(coll, sampler, record):
    path = lrh.ROOT / "out/derived/planting.json"
    if not path.is_file():
        record("planting", True, note="no planting.json")
        return
    plan = json.loads(path.read_text())
    protos = bpy.data.collections.new("Planting_Prototypes")
    coll.children.link(protos)
    protos.hide_render = True
    protos.hide_viewport = True
    meshes = {}
    # Phase 3a R3: scanned CC0 models for the broadleaf trees (sizes ~5-7 years on).
    import trees
    photo = trees.load_photoreal(protos)
    PHOTO_FOR = {"oak": ("post_oak_young", 7.0), "water_oak": ("post_oak_young", 8.0),
                 "pecan": ("cedar_elm", 9.0), "sycamore": ("cedar_elm", 9.5)}
    photo_size = {}
    for species, (key, h) in PHOTO_FOR.items():
        if key in photo:
            obj, ph, pr = photo[key]
            meshes[species] = [obj.data]
            photo_size[species] = h / ph
    for species, fn in BUILDERS.items():
        if species in meshes:
            continue
        variants = []
        for v in range(3):
            m = cabins.Mesh()
            fn(m, random.Random(f"{species}-{v}"))
            variants.append(m.object(f"Plant_{species}_{v}", protos).data)
        meshes[species] = variants
    rng = random.Random(2026)
    placed = 0
    # Owner, 21 Oct 2026: beside a house lot, the lot-line bamboo can be swapped for
    # flowering pears (Bradford and Oriental pear, upright ovals ~25 ft at 5-7 years) at
    # every other bamboo position. Each lot line gets its own pair of collections; render.py
    # shows one (`Screen_<a>_<b>_Bamboo` or `_Pear`).
    pear_mesh, pear_scale = None, 1.0
    if "post_oak_young" in photo:
        obj0, ph, _ = photo["post_oak_young"]
        pear_mesh, pear_scale = obj0.data, 7.5 / ph
    screens, line_seen = {}, {}

    def screen(line, kind):
        key = "Screen_" + line.replace("Lot ", "").replace("|", "_") + "_" + kind
        if key not in screens:
            c = bpy.data.collections.new(key)
            coll.children.link(c)
            screens[key] = c
        return screens[key]

    for q in plan["plants"]:
        z = sampler(q["x"], q["y"])
        if z is None:
            continue
        target = coll
        if q["species"] == "bamboo" and q.get("line"):
            target = screen(q["line"], "Bamboo")
            n = line_seen.get(q["line"], 0)
            line_seen[q["line"]] = n + 1
            if pear_mesh is not None and n % 2 == 0:
                pear = bpy.data.objects.new("Plant_pear", pear_mesh)
                pear.location = (q["x"], q["y"], z - 0.05)
                pear.rotation_euler = (0, 0, rng.uniform(0, 2 * math.pi))
                s = pear_scale * rng.uniform(0.9, 1.1)
                pear.scale = (s * 0.8, s * 0.8, s)
                screen(q["line"], "Pear").objects.link(pear)
        obj = bpy.data.objects.new(f"Plant_{q['species']}", rng.choice(meshes[q["species"]]))
        obj.location = (q["x"], q["y"], z - 0.05)
        obj.rotation_euler = (0, 0, rng.uniform(0, 2 * math.pi))
        s = rng.uniform(0.85, 1.15) * photo_size.get(q["species"], 1.0)
        obj.scale = (s, s, s)
        target.objects.link(obj)
        placed += 1
    record("planting", placed > 0, placed=placed, counts=plan["counts"])
