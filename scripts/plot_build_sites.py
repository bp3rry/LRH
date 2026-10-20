"""Draw the Phase 2d build-site plan over the north-up check_build_sites render.

Layers: setback envelopes (dashed), raised pads with the 4:1 graded footprint, a stilt
house footprint and an outbuilding on each pad (illustrative), septic drip areas with
sewer stub-outs, main and rear drives, and the north-south access road with its utility
corridor. Writes out/<date>/build_sites_plan.png and prints the per-lot table.

Option A (default): septic drip area in front of the house. Option B: the drip area on
the lake-side acre with a dose tank, fed by gravity along the private utility easement.
Both show the easement (house to west edge) and the recreation site.

Usage (Blender's Python): python3.11 scripts/plot_build_sites.py [--option B] [base.png]
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT / ".blender-site"))

import shapely  # noqa: E402

sys.path.insert(0, str(ROOT / "scripts/blender"))
import grading  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

FT = 0.3048
CENTRE, ORTHO_M = (0.0, 35.0), 600.0  # must match shots.yaml check_build_sites
HOUSE = (50 * FT, 40 * FT)            # illustrative stilt-house footprint (E-W, N-S)
SHOP = (30 * FT, 24 * FT)             # illustrative detached garage / outbuilding
SMALL_HOUSE = (36 * FT, 28 * FT)      # illustrative 2 BR / 1 BA lake house (constrained lots)


def main():
    args = sys.argv[1:]
    option = "A"
    if "--option" in args:
        option = args[args.index("--option") + 1].upper()
        del args[args.index("--option"):args.index("--option") + 2]
    base = Path(args[0]) if args else sorted(ROOT.glob("out/*/check_build_sites_draft.png"))[-1]
    im = Image.open(base).convert("RGB")
    w, h = im.size
    m_per_px = ORTHO_M / max(w, h)

    def px(x, y):
        return (w / 2 + (x - CENTRE[0]) / m_per_px, h / 2 - (y - CENTRE[1]) / m_per_px)

    def ring(g):
        return [px(*p) for p in g.exterior.coords]

    layer = Image.new("RGBA", im.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    data = json.loads((ROOT / "out/derived/build_sites.geojson").read_text())
    feats = [(f["properties"], shapely.geometry.shape(f["geometry"])) for f in data["features"]]
    by = lambda k: [(p, g) for p, g in feats if p["kind"] == k]
    for p, g in by("envelope"):
        geoms = getattr(g, "geoms", [g])
        for gg in geoms:
            pts = ring(gg)
            for a, b in zip(pts[:-1], pts[1:]):
                d.line([a, b], fill=(255, 255, 255, 140), width=1)
    for p, g in by("access_road"):
        line = [px(*c) for c in g.coords]
        d.line(line, fill=(150, 150, 150, 255), width=int(20 * FT / m_per_px))
        d.line(line, fill=(240, 200, 60, 200), width=2)  # utility corridor centre
    for kind, colour in (("drive_front", (170, 170, 165, 255)), ("drive_rear", (170, 170, 165, 255))):
        for p, g in by(kind):
            d.line([px(*c) for c in g.coords], fill=colour, width=int(14 * FT / m_per_px))
    for p, g in by("easement"):                                     # private utility easement
        for gg in getattr(g, "geoms", [g]):
            d.polygon(ring(gg), fill=(70, 170, 220, 55), outline=(70, 170, 220, 200))
    for p, g in by("rec_site"):
        for gg in getattr(g, "geoms", [g]):
            d.polygon(ring(gg), fill=(240, 220, 120, 70), outline=(240, 220, 120, 230))
    for p, g in by("trench_water_power"):
        d.line([px(*c) for c in g.coords], fill=(40, 120, 255, 255), width=2)
    for p, g in by("pedestal"):
        x, y = px(g.x, g.y)
        d.rectangle([x - 4, y - 4, x + 4, y + 4], fill=(40, 120, 255, 255), outline=(255, 255, 255, 255))
    if option == "B":
        for p, g in by("trench_effluent") + by("effluent_lateral"):
            d.line([px(*c) for c in g.coords], fill=(150, 95, 40, 255), width=2)
        for p, g in by("drip_lake"):
            d.polygon(ring(g), fill=(150, 95, 40, 120), outline=(120, 70, 25, 255))
        for p, g in by("dose_tank"):
            x, y = px(g.x, g.y)
            d.ellipse([x - 4, y - 4, x + 4, y + 4], fill=(70, 40, 15, 255), outline=(255, 255, 255, 255))
    for p, g in (by("septic") if option == "A" else []):
        d.polygon(ring(g), fill=(150, 95, 40, 120), outline=(120, 70, 25, 255))
    for p, g in (by("sewer_stub") if option == "A" else []):
        d.line([px(*c) for c in g.coords], fill=(120, 70, 25, 255), width=2)
    for p, g in by("septic_tank"):
        x, y = px(g.x, g.y)
        r = 5 * FT / m_per_px + 1
        d.ellipse([x - r, y - r, x + r, y + r], fill=(70, 40, 15, 255), outline=(255, 255, 255, 255))
    for p, g in by("pad"):
        d.polygon(ring(g.buffer(2 * FT * 4, join_style="mitre")), fill=(120, 160, 60, 70))  # 4:1 toe
        d.polygon(ring(g), fill=(205, 190, 150, 210), outline=(255, 255, 255, 255))
        cx, cy = g.centroid.x, g.centroid.y
        x0, y0, x1, y1 = g.bounds
        if p.get("house") == "small":
            continue                                                  # Hemlock does not fit
        if p.get("house") == "barndo":                                # Lot 10 barndominium
            xe = x1 - 0.6 - 6 * FT
            porch = shapely.box(xe - 52 * FT, cy - 15 * FT, xe + 6 * FT, cy + 15 * FT)
            d.polygon(ring(porch), fill=(215, 175, 110, 255), outline=(90, 60, 30, 255))
            d.polygon(ring(shapely.box(xe - 40 * FT, cy - 15 * FT, xe, cy + 15 * FT)),
                      fill=(240, 240, 235, 255), outline=(60, 60, 60, 255))
            continue
        L = grading.layout(g.bounds)
        porches = shapely.box(L["xp"], L["ys"], L["xe"], L["yn"])
        d.polygon(ring(porches), fill=(215, 175, 110, 255), outline=(90, 60, 30, 255))
        house = shapely.box(L["xw"], L["y0"], L["xe"], L["y1"])
        d.polygon(ring(house), fill=(240, 240, 235, 255), outline=(60, 60, 60, 255))
    im = Image.alpha_composite(im.convert("RGBA"), layer).convert("RGB")
    d = ImageDraw.Draw(im)
    font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 16)
    legend = [("Graded pad 60x80 ft (walk-out); Lot 10 barndo pad 62x36 ft", (205, 190, 150)), ("Fill / cut slopes", (120, 160, 60)),
              ("Hemlock cabin 30x42 ft; porches (tan); opt. apartment below", (240, 240, 235)),
              (("Septic tank + 4,000 sq ft drip area in front + sewer stub" if option == "A" else
                "Option B: drip area on lake-side acre, dose tank, gravity line"), (150, 95, 40)),
              ("Private utility easement 20 ft (PEX water, power, conduit)", (70, 170, 220)),
              ("Recreation / picnic / camp site + utility pedestal", (240, 220, 120)),
              ("Drives", (170, 170, 165)), ("N-S access road + utility corridor", (240, 200, 60)),
              ("Setback envelope (100 ft CR 3635, 20 ft sides)", (255, 255, 255))]
    y = 14
    d.rectangle([8, 8, 540, 14 + 22 * (len(legend) + 1)], fill=(0, 0, 0))
    d.text((16, 14 + 22 * len(legend)), f"Septic option {option}" + (
        " (lake-side field, gravity to dose tank)" if option == "B" else " (field in front)"),
        font=font, fill=(255, 220, 120))
    for text, colour in legend:
        d.rectangle([16, y + 3, 30, y + 15], fill=colour)
        d.text((38, y), text, font=font, fill=(255, 255, 255))
        y += 22
    d.text((14, h - 26), "Conceptual planning sketch. Not engineering; subject to survey, County and TCEQ/OSSF design.",
           font=font, fill=(255, 255, 255))
    out = base.parent / ("build_sites_plan.png" if option == "A" else "build_sites_plan_option_b.png")
    im.save(out)
    print(out)


if __name__ == "__main__":
    main()
