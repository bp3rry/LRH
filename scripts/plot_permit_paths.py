"""Permit path plan sheet over the north-up check_permit_plan render.

Usage (Blender's Python): python3.11 scripts/plot_permit_paths.py [base.png]
Reads permit_paths.json beside the base image (build_baseline.py -- --scene permit) and
writes permit_path_plan.png there.
"""

import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT / ".blender-site"))

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

CENTRE, ORTHO_M = (0.0, 35.0), 600.0
FT = 0.3048


def rings(geom):
    """Exterior rings of a GeoJSON Polygon or MultiPolygon."""
    polys = [geom["coordinates"]] if geom["type"] == "Polygon" else geom["coordinates"]
    return [p[0] for p in polys]


def main():
    base = Path(sys.argv[1]) if len(sys.argv) > 1 else sorted(ROOT.glob("out/*/check_permit_plan_draft.png"))[-1]
    data = json.loads((base.parent / "permit_paths.json").read_text())
    font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 16)
    small = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 13)
    im = Image.open(base).convert("RGB")
    w, h = im.size
    mpp = ORTHO_M / max(w, h)
    px = lambda x, y: (w / 2 + (x - CENTRE[0]) / mpp, h / 2 - (y - CENTRE[1]) / mpp)
    layer = Image.new("RGBA", im.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for ring in rings(data["parcels"]):
        d.line([px(*p) for p in ring], fill=(230, 40, 40, 255), width=3)
    for ring in rings(data["hay"]["field"]):
        d.line([px(*p) for p in ring], fill=(250, 210, 60, 230), width=2)
    for x, y in data["hay"]["bales_xy"]:
        cx, cy = px(x, y)
        d.ellipse([cx - 3, cy - 3, cx + 3, cy + 3], fill=(250, 210, 60, 255), outline=(60, 40, 0, 255))
    for p in data["paths"]:
        line = [px(*q) for q in p["line"]]
        d.line(line, fill=(255, 140, 0, 255), width=5)
        for t in p["lidar_trees_removed"]:
            cx, cy = px(*t["xy"])
            d.line([cx - 5, cy - 5, cx + 5, cy + 5], fill=(255, 40, 40, 255), width=2)
            d.line([cx - 5, cy + 5, cx + 5, cy - 5], fill=(255, 40, 40, 255), width=2)
        b, e = px(*p["dock"]["base"]), px(*p["dock"]["end"])
        n = max(1, int(math.dist(b, e) / 6))
        for i in range(0, n, 2):                       # dashed dock axis
            d.line([b[0] + (e[0] - b[0]) * i / n, b[1] + (e[1] - b[1]) * i / n,
                    b[0] + (e[0] - b[0]) * (i + 1) / n, b[1] + (e[1] - b[1]) * (i + 1) / n],
                   fill=(60, 220, 255, 255), width=4)
        d.ellipse([e[0] - 5, e[1] - 5, e[0] + 5, e[1] + 5], outline=(60, 220, 255, 255), width=2)
        sx, sy = line[0]
        d.ellipse([sx - 6, sy - 6, sx + 6, sy + 6], fill=(255, 255, 255, 255), outline=(0, 0, 0, 255))
        text = (f"{p['parcel']} parcel: 6 ft path {p['length_m']:.0f} m ({p['length_m'] / FT:.0f} ft), "
                f"{len(p['lidar_trees_removed'])} tree{'' if len(p['lidar_trees_removed']) == 1 else 's'} out\n"
                f"dock site: up to {p['dock']['length_ft']} ft, {p['dock']['end_depth_m']:.1f} m deep at full pool")
        # At the left edge, level with the dock and below the path's start, clear of both.
        tx, ty = 8, max(e[1], b[1], sy) + 24
        bbox = d.multiline_textbbox((tx, ty), text, font=small)
        d.rectangle([bbox[0] - 4, bbox[1] - 3, bbox[2] + 4, bbox[3] + 3], fill=(0, 0, 0, 170))
        d.multiline_text((tx, ty), text, fill=(255, 255, 255, 255), font=small)
    hay = data["hay"]
    mid = hay["yield"]["mid"]
    legend = [("Owner parcels", (230, 40, 40)), ("6 ft walking path (permit)", (255, 140, 0)),
              ("Proposed dock site (axis, 120 ft max)", (60, 220, 255)),
              ("Lidar tree removed for the path", (255, 40, 40)),
              (f"Hay field {hay['field_acres']:.1f} ac; {hay['bales_shown']} round bales shown", (250, 210, 60))]
    x0, y0 = 14, 14
    d.rectangle([x0 - 6, y0 - 6, x0 + 470, y0 + 30 + 22 * len(legend) + 64], fill=(0, 0, 0, 175))
    d.text((x0, y0), "Permit path plan - draft for review", fill=(255, 255, 255, 255), font=font)
    for i, (label, col) in enumerate(legend):
        yy = y0 + 30 + 22 * i
        d.rectangle([x0, yy + 3, x0 + 22, yy + 13], fill=(*col, 255))
        d.text((x0 + 30, yy), label, fill=(255, 255, 255, 255), font=small)
    yy = y0 + 30 + 22 * len(legend) + 4
    lines = [f"Hay per cutting (5x6 ft, ~1,000 lb bales): low {hay['yield']['low']['bales']}, "
             f"mid {mid['bales']}, high {hay['yield']['high']['bales']}",
             f"Mid: {mid['lb_per_acre']:,} lb/ac = {mid['tons']} tons. North up; grid {mpp:.2f} m/px."]
    for i, s in enumerate(lines):
        d.text((x0, yy + 18 * i), s, fill=(220, 220, 220, 255), font=small)
    im = Image.alpha_composite(im.convert("RGBA"), layer).convert("RGB")
    dst = base.parent / "permit_path_plan.png"
    im.save(dst)
    print(f"WROTE {dst}")


if __name__ == "__main__":
    main()
