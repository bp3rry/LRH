"""For-sale sign at the CR 3635 / CR 3640 corner (owner, 2 Nov 2026; switchable: `Sale_Sign`).

A white post-and-arm real estate sign hanging three placards, white with black and red:
- top rider: FOR SALE;
- main placard: the listing agent's sign (Rose Perry Homes, G+A Real Estate), redrawn
  from the owner's photo (inputs/reference/sign.jpg, shot under warm light; the placard
  is white);
- bottom rider: 5 AC WATERFRONT LOTS.
The flyover starts and ends on it. It stands SIGN_INSET_M inside the property corner (the
camera crosses the fence well above it) and
faces SIGN_FACING_DEG (south-south-west: the low October evening sun is on its face and
the property is behind it from the camera).

Placard artwork: out/derived/sale_sign_<name>.png at 50 px per inch. layout() needs no
Blender: flight_path.py frames the sign with it.
"""

import math

import numpy as np

import lrh

IN = 0.0254
PX_PER_IN = 50
CORNER = (138.3, -197.3)        # Lot D's south-east corner (CR 3635 x CR 3640, inside the fence)
SIGN_INSET_M = 8.0
SIGN_FACING_DEG = 200.0         # azimuth the placards face
POST_H, POST_W = 2.10, 3.5 * IN    # 4x4 post, 7 ft
ARM_L = 0.95
WHITE, BLACK, RED = (255, 255, 255), (30, 28, 28), (178, 14, 22)   # red deeper than print: the evening light and AgX lift it
# (name, width in, height in): hung top to bottom from the arm, HOOK_GAP between.
PLACARDS = [("top", 24, 6), ("main", 24, 30), ("bottom", 24, 6)]
HOOK_GAP = 1.2 * IN
FONTS = "/System/Library/Fonts/Avenir Next.ttc"
# Avenir Next.ttc faces: 0 Bold, 2 Demi Bold, 7 Regular, 5 Medium.
BOLD, DEMI, MEDIUM, REGULAR = 0, 2, 5, 7


def font(size, face):
    from PIL import ImageFont
    return ImageFont.truetype(FONTS, size, index=face)


def text_centred(draw, cx, cy, text, f, fill, tracking=0):
    """Text centred on cx, its capitals centred on cy; tracking adds px between letters."""
    widths = [draw.textlength(c, font=f) for c in text]
    total = sum(widths) + tracking * (len(text) - 1)
    x = cx - total / 2
    _, top, _, bottom = f.getbbox("H")
    for c, w in zip(text, widths):
        draw.text((x, cy - (top + bottom) / 2), c, font=f, fill=fill)
        x += w + tracking


def fit(draw, text, face, width, tracking=0, start=400):
    size = start
    while size > 10:
        f = font(size, face)
        if sum(draw.textlength(c, font=f) for c in text) + tracking * (len(text) - 1) <= width:
            return f
        size -= 2
    return font(size, face)


def artwork(name, w_in, h_in):
    from PIL import Image, ImageDraw
    w, h = w_in * PX_PER_IN, h_in * PX_PER_IN
    im = Image.new("RGB", (w, h), WHITE)
    d = ImageDraw.Draw(im)
    if name == "top":
        d.rectangle([0, 0, w - 1, h - 1], outline=RED, width=14)
        f = fit(d, "FOR SALE", BOLD, w * 0.80, tracking=24)
        text_centred(d, w / 2, h / 2, "FOR SALE", f, RED, tracking=24)
    elif name == "bottom":
        d.rectangle([0, 0, w - 1, h - 1], outline=BLACK, width=14)
        f = fit(d, "5 AC WATERFRONT LOTS", BOLD, w * 0.86, tracking=6)
        text_centred(d, w / 2, h / 2, "5 AC WATERFRONT LOTS", f, BLACK, tracking=6)
    else:
        # Main placard, laid out from the photo (placard 1,200 x 1,500 px).
        s = w / 1200.0
        # The R mark: black stem and bowl (square left, round right), red leg apart below.
        x0, x1, y0, y1 = 360 * s, 485 * s, 150 * s, 752 * s           # stem
        bowl_r, bowl_bot, stroke = 882 * s, 557 * s, 125 * s
        d.rectangle([x0, y0, x1, y1], fill=BLACK)
        d.rounded_rectangle([x0, y0, bowl_r, bowl_bot], radius=(bowl_bot - y0) / 2 - 1, fill=BLACK,
                            corners=(False, True, True, False))
        d.rounded_rectangle([x1, y0 + stroke, bowl_r - stroke, bowl_bot - stroke],
                            radius=(bowl_bot - y0) / 2 - stroke - 1, fill=WHITE,
                            corners=(False, True, True, False))
        d.polygon([(617 * s, 587 * s), (743 * s, 587 * s), (844 * s, 752 * s), (731 * s, 752 * s)], fill=RED)
        f = fit(d, "ROSE PERRY", DEMI, 930 * s, tracking=16 * s)
        text_centred(d, w / 2, 870 * s, "ROSE PERRY", f, BLACK, tracking=16 * s)
        f = fit(d, "HOMES", REGULAR, 400 * s, tracking=34 * s)
        text_centred(d, w / 2, 965 * s, "HOMES", f, RED, tracking=34 * s)
        f = fit(d, "214.695.6191", DEMI, 900 * s)
        text_centred(d, w / 2, 1100 * s, "214.695.6191", f, BLACK)
        f = fit(d, "roseperryhomes.com", MEDIUM, 790 * s)
        d.text((w / 2, 1200 * s), "roseperryhomes.com", font=f, fill=BLACK, anchor="mm")
        # Brokerage: red square mark, then the name.
        bx, by, bs = 290 * s, 1310 * s, 115 * s
        d.rectangle([bx, by, bx + bs, by + bs], fill=RED)
        d.ellipse([bx + 22 * s, by + 22 * s, bx + bs - 22 * s, by + bs - 22 * s], outline=WHITE, width=max(2, int(5 * s)))
        d.text((bx + bs / 2, by + bs / 2), "G+A", font=font(int(22 * s), DEMI), fill=WHITE, anchor="mm")
        f = fit(d, "G+A REAL ESTATE", REGULAR, 470 * s, tracking=10 * s)
        x = bx + bs + 45 * s
        for c in "G+A REAL ESTATE":
            d.text((x, by + bs / 2), c, font=f, fill=BLACK, anchor="lm")
            x += d.textlength(c, font=f) + 10 * s
    path = lrh.ROOT / f"out/derived/sale_sign_{name}.png"
    im.save(path)
    return path


def placard_material(name, image_path):
    import bpy
    mat = bpy.data.materials.new(f"Sale_Sign_{name}")
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    bsdf = nodes["Principled BSDF"]
    bsdf.inputs["Roughness"].default_value = 0.45
    tex = nodes.new("ShaderNodeTexImage")
    tex.image = bpy.data.images.load(str(image_path), check_existing=False)
    tex.image.pack()
    tex.interpolation = "Cubic"
    links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    return mat


def box(name, centre, size, rot_z, mat, coll, uv=None):
    """Axis box (size x, y, z) turned rot_z about Z at centre. uv: faces +y and -y
    carry the full image (both read correctly from their side)."""
    import bpy
    sx, sy, sz = (s / 2 for s in size)
    v = [(x, y, z) for x in (-sx, sx) for y in (-sy, sy) for z in (-sz, sz)]
    faces = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(v, [], faces)
    mesh.validate()
    if uv:
        layer = mesh.uv_layers.new(name="UVMap")
        for poly in mesh.polygons:
            for li in poly.loop_indices:
                x, y, z = v[mesh.loops[li].vertex_index]
                u = 0.5 + x / (2 * sx)
                if poly.normal.y > 0.5:            # back face: mirror so it reads
                    u = 1 - u
                layer.data[li].uv = (u, 0.5 + z / (2 * sz)) if abs(poly.normal.y) > 0.5 else (0.01, 0.99)
    mesh.materials.append(mat)
    obj = bpy.data.objects.new(name, mesh)
    obj.location = centre
    obj.rotation_euler = (0.0, 0.0, rot_z)
    coll.objects.link(obj)
    return obj


def layout(ground):
    """Sign geometry in LRH local metres for ground height `ground` at its post."""
    face = math.radians(SIGN_FACING_DEG)
    out_dir = np.array([math.sin(face), math.cos(face)])         # the way the placards face
    inward = -np.array([1.0, -1.0]) / math.sqrt(2)               # into the property from its SE corner
    base = np.array(CORNER) + inward * SIGN_INSET_M
    along = np.array([out_dir[1], -out_dir[0]])                  # arm direction
    arm_z = ground + POST_H - 0.12
    top = arm_z - POST_W * 0.45
    bottom = top - sum(h * IN + HOOK_GAP for _, _, h in PLACARDS)
    hang = base + along * (ARM_L * 0.55)
    return {"base": base, "out": out_dir, "along": along, "rot": math.pi - face, "arm_z": arm_z,
            "top": top, "bottom": bottom, "hang": hang,
            "centre": np.array([*hang, (top + bottom) / 2])}


def build(coll, sampler, record):
    """Builds the sign (Blender)."""
    import bpy
    base0 = layout(0.0)["base"]
    ground = sampler(*base0) or lrh.POOL_M
    g = layout(ground)
    base, along, rot, hang = g["base"], g["along"], g["rot"], g["hang"]
    paint = bpy.data.materials.new("Sale_Sign_Post")
    paint.use_nodes = True
    paint.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.92, 0.92, 0.9, 1.0)
    paint.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.55
    box("Sale_Sign_Post", (*base, ground + POST_H / 2 - 0.4), (POST_W, POST_W, POST_H + 0.8), rot, paint, coll)
    arm_c = base + along * (ARM_L / 2)
    box("Sale_Sign_Arm", (*arm_c, g["arm_z"]), (ARM_L + POST_W, POST_W * 0.9, POST_W * 0.9), rot, paint, coll)
    steel = bpy.data.materials.new("Sale_Sign_Hooks")
    steel.use_nodes = True
    steel.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.35, 0.35, 0.35, 1.0)
    steel.node_tree.nodes["Principled BSDF"].inputs["Metallic"].default_value = 1.0
    z = g["top"]
    panels = {}
    for name, w_in, h_in in PLACARDS:
        w, h = w_in * IN, h_in * IN
        for side in (-0.36, 0.36):                                 # two S-hooks
            box(f"Sale_Sign_Hook_{name}_{'L' if side < 0 else 'R'}",
                (*(hang + along * side * w), z - HOOK_GAP / 2), (0.006, 0.006, HOOK_GAP), rot, steel, coll)
        z -= HOOK_GAP
        mat = placard_material(name, artwork(name, w_in, h_in))
        box(f"Sale_Sign_{name}", (*hang, z - h / 2), (w, 0.004, h), rot, mat, coll, uv=True)
        panels[name] = round(z - h / 2 - ground, 3)
        z -= h
    record("sale_sign", True, base=[round(float(c), 2) for c in base], ground_m=round(float(ground), 2),
           facing_deg=SIGN_FACING_DEG, placard_centres_above_ground_m=panels,
           centre=[round(float(c), 2) for c in g["centre"]])
