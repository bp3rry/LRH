"""Draw the Phase 2d build-site plan over the north-up check_build_sites render.

Layers: setback envelopes (dashed), raised pads with the 4:1 graded footprint, a stilt
house footprint and an outbuilding on each pad (illustrative), septic drip areas with
sewer stub-outs, main and rear drives, and the north-south access road with its utility
corridor. Writes out/<date>/build_sites_plan.png and prints the per-lot table.

Usage (Blender's Python): python3.11 scripts/plot_build_sites.py [out/<date>/check_build_sites_draft.png]
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT / ".blender-site"))

import shapely  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

FT = 0.3048
CENTRE, ORTHO_M = (0.0, 35.0), 600.0  # must match shots.yaml check_build_sites
HOUSE = (50 * FT, 40 * FT)            # illustrative stilt-house footprint (E-W, N-S)
SHOP = (30 * FT, 24 * FT)             # illustrative detached garage / outbuilding
SMALL_HOUSE = (36 * FT, 28 * FT)      # illustrative 2 BR / 1 BA lake house (constrained lots)


def main():
    base = Path(sys.argv[1]) if len(sys.argv) > 1 else \
        sorted(ROOT.glob("out/*/check_build_sites_draft.png"))[-1]
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
    for p, g in by("septic"):
        d.polygon(ring(g), fill=(150, 95, 40, 120), outline=(120, 70, 25, 255))
    for p, g in by("sewer_stub"):
        d.line([px(*c) for c in g.coords], fill=(120, 70, 25, 255), width=2)
    for p, g in by("pad"):
        d.polygon(ring(g.buffer(2 * FT * 4, join_style="mitre")), fill=(120, 160, 60, 70))  # 4:1 toe
        d.polygon(ring(g), fill=(205, 190, 150, 210), outline=(255, 255, 255, 255))
        cx, cy = g.centroid.x, g.centroid.y
        x0, y0, x1, y1 = g.bounds
        hw, hd = SMALL_HOUSE if p.get("house") == "small" else HOUSE
        house = shapely.box(x1 - 3 - hw, cy - hd / 2, x1 - 3, cy + hd / 2)
        d.polygon(ring(house), fill=(240, 240, 235, 255), outline=(60, 60, 60, 255))
        if p.get("house") != "small":
            shop = shapely.box(x0 + 3, y1 - 3 - SHOP[1], x0 + 3 + SHOP[0], y1 - 3)
            d.polygon(ring(shop), fill=(200, 200, 195, 255), outline=(60, 60, 60, 255))
    im = Image.alpha_composite(im.convert("RGBA"), layer).convert("RGB")
    d = ImageDraw.Draw(im)
    font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 16)
    legend = [("Raised pad 60x80 ft (+2 ft); Lot 10: 40x60 ft, 2 BR", (205, 190, 150)), ("4:1 fill slope", (120, 160, 60)),
              ("Lake-house cabin / outbuilding (illustrative)", (240, 240, 235)),
              ("Septic drip area (5,000 / 3,000 sq ft) + sewer stub", (150, 95, 40)),
              ("Drives", (170, 170, 165)), ("N-S access road + utility corridor", (240, 200, 60)),
              ("Setback envelope (100 ft CR 3635, 20 ft sides)", (255, 255, 255))]
    y = 14
    d.rectangle([8, 8, 440, 14 + 22 * len(legend)], fill=(0, 0, 0))
    for text, colour in legend:
        d.rectangle([16, y + 3, 30, y + 15], fill=colour)
        d.text((38, y), text, font=font, fill=(255, 255, 255))
        y += 22
    d.text((14, h - 26), "Conceptual planning sketch. Not engineering; subject to survey, County and TCEQ/OSSF design.",
           font=font, fill=(255, 255, 255))
    out = base.parent / "build_sites_plan.png"
    im.save(out)
    print(out)


if __name__ == "__main__":
    main()
