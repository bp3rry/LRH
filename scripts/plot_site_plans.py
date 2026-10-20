"""Drainage plan and planting plan sheets over the north-up check_build_sites render.

Usage (Blender's Python): python3.11 scripts/plot_site_plans.py [base.png]
Writes <base dir>/drainage_plan.png and planting_plan.png.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT / ".blender-site"))
sys.path.insert(0, str(ROOT / "scripts/blender"))

import shapely  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

import grading  # noqa: E402

CENTRE, ORTHO_M = (0.0, 35.0), 600.0
SPECIES = {"bamboo": ((120, 200, 70), 4), "loblolly_pine": ((20, 90, 40), 7), "oak": ((60, 120, 40), 8),
           "pecan": ((150, 160, 60), 8), "crape_myrtle": ((235, 80, 160), 6),
           "bald_cypress": ((200, 110, 50), 7), "water_oak": ((40, 140, 120), 8),
           "sycamore": ((230, 230, 200), 8)}


def main():
    base = Path(sys.argv[1]) if len(sys.argv) > 1 else sorted(ROOT.glob("out/*/check_build_sites_draft.png"))[-1]
    font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 16)
    small = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 13)
    dr = json.loads((ROOT / "out/derived/drainage.json").read_text())
    bs = json.loads((ROOT / "out/derived/build_sites.geojson").read_text())["features"]
    pl = json.loads((ROOT / "out/derived/planting.json").read_text())

    def sheet(title, draw_layers, legend):
        im = Image.open(base).convert("RGB")
        w, h = im.size
        mpp = ORTHO_M / max(w, h)
        px = lambda x, y: (w / 2 + (x - CENTRE[0]) / mpp, h / 2 - (y - CENTRE[1]) / mpp)
        layer = Image.new("RGBA", im.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        for f in bs:                                                 # cabins for reference
            p = f["properties"]
            if p["kind"] == "pad" and p.get("house") == "standard":
                L = grading.layout(shapely.geometry.shape(f["geometry"]).bounds)
                for b, col in ((L["carport"], (200, 200, 200, 230)),
                               ((L["xp"], L["ys"], L["xe"], L["yn"]), (215, 175, 110, 255)),
                               ((L["xw"], L["y0"], L["xe"], L["y1"]), (240, 240, 235, 255))):
                    d.rectangle([px(b[0], b[3]), px(b[2], b[1])], fill=col)
                for t in p.get("terraces", []):
                    d.rectangle([px(t[0], t[3]), px(t[2], t[1])], outline=(255, 255, 255, 160), width=1)
        draw_layers(d, px, mpp)
        im = Image.alpha_composite(im.convert("RGBA"), layer).convert("RGB")
        d = ImageDraw.Draw(im)
        d.rectangle([8, 8, 470, 40 + 22 * len(legend)], fill=(0, 0, 0))
        d.text((16, 12), title, font=font, fill=(255, 220, 120))
        y = 38
        for text, colour in legend:
            d.rectangle([16, y + 3, 30, y + 15], fill=colour)
            d.text((38, y), text, font=font, fill=(255, 255, 255))
            y += 22
        d.text((14, h - 26), "Conceptual planning sketch. Not engineering.", font=font, fill=(255, 255, 255))
        return im

    def drainage(d, px, mpp):
        for l in dr["flow_lines"]:
            a = max(p[2] for p in l)
            d.line([px(p[0], p[1]) for p in l], fill=(60, 170, 255, 170), width=2 if a < 10000 else 4)
        d.line([px(*p) for p in dr["creek"]], fill=(0, 90, 255, 255), width=7)
        d.polygon([px(*p) for p in dr["pond"]["polygon"]], fill=(30, 110, 200, 230), outline=(255, 255, 255, 255))
        d.line([px(*p) for p in dr["pond"]["dam"]], fill=(120, 90, 50, 255), width=6)
        for ls in dr["swales"].values():
            for l in ls:
                pts = [px(*p) for p in l]
                for a, b in zip(pts[:-1], pts[1:]):                  # dashed
                    n = int(max(abs(b[0] - a[0]), abs(b[1] - a[1])) // 8)
                    for k in range(0, n, 2):
                        t0, t1 = k / max(n, 1), min(1, (k + 1) / max(n, 1))
                        d.line([(a[0] + (b[0] - a[0]) * t0, a[1] + (b[1] - a[1]) * t0),
                                (a[0] + (b[0] - a[0]) * t1, a[1] + (b[1] - a[1]) * t1)],
                               fill=(0, 230, 230, 255), width=3)
                x, y = pts[-1]
                d.ellipse([x - 4, y - 4, x + 4, y + 4], fill=(0, 230, 230, 255))
        for c in dr["culverts"]:
            x, y = px(*c["at"])
            d.rectangle([x - 6, y - 3, x + 6, y + 3], fill=(20, 20, 20, 255), outline=(255, 255, 255, 255))
        x, y = px(*dr["pond"]["spillway"])
        d.polygon([(x, y - 7), (x - 7, y + 6), (x + 7, y + 6)], fill=(255, 255, 255, 255))

    def planting(d, px, mpp):
        for q in pl["plants"]:
            col, r = SPECIES[q["species"]]
            x, y = px(q["x"], q["y"])
            d.ellipse([x - r, y - r, x + r, y + r], fill=col + (235,), outline=(0, 0, 0, 200))
        d.polygon([px(*p) for p in dr["pond"]["polygon"]], fill=(30, 110, 200, 200))
        d.line([px(*p) for p in dr["creek"]], fill=(0, 90, 255, 200), width=4)

    pond = dr["pond"]
    out = base.parent
    sheet("Drainage plan (concept)", drainage, [
        ("Natural flow paths (lidar), wider = more area", (60, 170, 255)),
        ("Creek to keep and emphasise (CR 3640 ditch to lake)", (0, 90, 255)),
        (f"Pond ~{pond['area_ac']} ac, pool {pond['pool_ft']} ft, spillway (triangle)", (30, 110, 200)),
        ("Pond dam / berm", (120, 90, 50)),
        ("Diversion swale round each cabin site, outlet dot", (0, 230, 230)),
        ("Culvert under drive / access road", (20, 20, 20))]).save(out / "drainage_plan.png")
    counts = pl["counts"]
    sheet("Planting plan (concept)", planting, [
        (f"Clumping bamboo screen ({counts.get('bamboo', 0)} clumps)", SPECIES["bamboo"][0]),
        (f"Loblolly pine ({counts.get('loblolly_pine', 0)})", SPECIES["loblolly_pine"][0]),
        (f"Oak ({counts.get('oak', 0)})", SPECIES["oak"][0]),
        (f"Pecan ({counts.get('pecan', 0)})", SPECIES["pecan"][0]),
        (f"Crape myrtle at drives ({counts.get('crape_myrtle', 0)})", SPECIES["crape_myrtle"][0]),
        (f"Bald cypress ({counts.get('bald_cypress', 0)})", SPECIES["bald_cypress"][0]),
        (f"Water oak ({counts.get('water_oak', 0)})", SPECIES["water_oak"][0]),
        (f"Sycamore ({counts.get('sycamore', 0)})", SPECIES["sycamore"][0])]).save(out / "planting_plan.png")
    print(out / "drainage_plan.png", out / "planting_plan.png")


if __name__ == "__main__":
    main()
