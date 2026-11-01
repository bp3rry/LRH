"""Dock permit exhibit sheets (owner, 1 Nov 2026) for a UTRWD Shoreline Use Permit request.

Usage (Blender's Python): python3.11 scripts/plot_dock_permit.py [out/<date>]
Reads out/<date>/dock permit/dock_permit.json and z.npy (scripts/dock_permit.py), and the
check_dock_permit_* renders in out/<date> (shots.yaml, scene permit); writes the sheets
DP1-DP6 into out/<date>/dock permit/.
"""

import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import dock_permit as dp  # noqa: E402  (adds .blender-site to sys.path)
import numpy as np  # noqa: E402
import shapely  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402
from shapely.geometry import LineString, Point, Polygon  # noqa: E402
from shapely.ops import unary_union  # noqa: E402

FT = dp.FT
HELV = "/System/Library/Fonts/Helvetica.ttc"
F = {k: ImageFont.truetype(HELV, s) for k, s in (("h1", 34), ("h2", 24), ("b", 19), ("s", 16), ("xs", 14))}
PANEL_W = 820
WHITE, BLACK = (255, 255, 255, 255), (0, 0, 0, 255)
OWNER_C, NEIGH_C, ADMIN_C = (60, 220, 120), (255, 210, 60), (255, 120, 40)
DOCK_C, SHORE_C, ROUTE_C = (255, 255, 255), (80, 200, 255), (90, 150, 255)
SHOTS = {"overview": ((-150.0, -15.0), 520.0), "detail": ((-152.0, -3.0), 80.0)}
TITLE = "Proposed private boat dock - Shoreline Use Permit exhibit (draft)"
SUB = ("Owner property CAD 116505 + 135089, CR 3635, Fannin County TX. Lake Ralph Hall (UTRWD). "
       "Rules: UTRWD Lake & Shoreline Management Plan, comment draft 16 Oct 2025.")
NOTE = ("Depths are StratMap 2025 lidar ground below the 551 ft MSL conservation pool; parcel lines "
        "Fannin CAD; positions approximate, subject to survey (Texas RPLS, required with the application).")


class Sheet:
    """A base image on the left and a text panel on the right, in local metres."""

    def __init__(self, base, centre, scale_m):
        self.base = Image.open(base).convert("RGBA")
        self.w, self.h = self.base.size
        self.mpp = scale_m / max(self.w, self.h)
        self.c = centre
        self.layer = Image.new("RGBA", self.base.size, (0, 0, 0, 0))
        self.d = ImageDraw.Draw(self.layer)

    def px(self, x, y):
        return (self.w / 2 + (x - self.c[0]) / self.mpp, self.h / 2 - (y - self.c[1]) / self.mpp)

    def poly(self, g, fill=None, outline=None, width=2):
        for p in getattr(g, "geoms", [g]):
            if p.is_empty or p.geom_type != "Polygon":
                continue
            self.d.polygon([self.px(*q) for q in p.exterior.coords], fill=fill, outline=outline, width=width)

    def line(self, coords, fill, width=3, dash=None):
        pts = [self.px(*q) for q in coords]
        if not dash:
            self.d.line(pts, fill=fill, width=width, joint="curve")
            return
        on = True
        for a, b in zip(pts[:-1], pts[1:]):
            n = max(1, int(math.dist(a, b) / dash))
            for i in range(n):
                if on:
                    self.d.line([(a[0] + (b[0] - a[0]) * i / n, a[1] + (b[1] - a[1]) * i / n),
                                 (a[0] + (b[0] - a[0]) * (i + 1) / n, a[1] + (b[1] - a[1]) * (i + 1) / n)],
                                fill=fill, width=width)
                on = not on

    def label(self, xy, text, font="s", fill=WHITE, anchor="la", box=(0, 0, 0, 175), offset=(0, 0)):
        x, y = self.px(*xy) if not isinstance(xy[0], int) else xy
        x, y = x + offset[0], y + offset[1]
        bb = self.d.multiline_textbbox((x, y), text, font=F[font], anchor=anchor)
        self.d.rectangle([bb[0] - 5, bb[1] - 4, bb[2] + 5, bb[3] + 4], fill=box)
        self.d.multiline_text((x, y), text, fill=fill, font=F[font], anchor=anchor)

    def scale_bar(self, feet):
        x0, y0 = 30, self.h - 50
        L = feet * FT / self.mpp
        self.d.rectangle([x0 - 10, y0 - 34, x0 + L + 70, y0 + 22], fill=(0, 0, 0, 170))
        for i in range(4):
            self.d.rectangle([x0 + L * i / 4, y0, x0 + L * (i + 1) / 4, y0 + 10],
                             fill=WHITE if i % 2 == 0 else (60, 60, 60, 255), outline=WHITE)
        self.d.text((x0, y0 - 28), f"0      {feet // 2} ft      {feet} ft   (north up)", fill=WHITE, font=F["s"])
        nx, ny = self.w - 60, 70                                   # north arrow
        self.d.polygon([(nx, ny - 40), (nx - 16, ny + 10), (nx, ny), (nx + 16, ny + 10)], fill=WHITE, outline=BLACK)
        self.d.text((nx, ny + 16), "N", fill=WHITE, font=F["h2"], anchor="ma")

    def save(self, dst, panel_lines, title=TITLE):
        img = Image.alpha_composite(self.base, self.layer)
        sheet = Image.new("RGB", (self.w + PANEL_W, self.h), (250, 250, 247))
        sheet.paste(img.convert("RGB"), (0, 0))
        write_panel(ImageDraw.Draw(sheet), self.w + 30, panel_lines, title)
        sheet.save(dst)
        print(f"WROTE {dst}")


def write_panel(d, x, lines, title):
    y = 28
    for t in wrap(title, 40):
        d.text((x, y), t, fill=(20, 20, 20), font=F["h2"])
        y += 32
    for t in wrap(SUB, 78):
        d.text((x, y), t, fill=(70, 70, 70), font=F["xs"])
        y += 19
    y += 12
    for kind, text, *col in lines:
        if kind == "h":
            y += 8
            d.text((x, y), text, fill=(20, 20, 20), font=F["b"])
            y += 27
        elif kind == "row":                                    # rule | requirement | value | ok
            rule, req, val, ok = text
            mark, mc = ("PASS", (20, 130, 50)) if ok else ("FAIL", (190, 40, 30))
            if ok is None:
                mark, mc = ("NOTE", (150, 110, 0))
            d.text((x, y), rule, fill=(30, 30, 30), font=F["xs"])
            d.text((x + 250, y), req, fill=(60, 60, 60), font=F["xs"])
            d.text((x + 520, y), val, fill=(30, 30, 30), font=F["xs"])
            d.text((x + 720, y), mark, fill=mc, font=F["xs"])
            y += 21
        elif kind == "key":
            d.rectangle([x, y + 3, x + 26, y + 15], fill=col[0])
            d.text((x + 36, y), text, fill=(30, 30, 30), font=F["s"])
            y += 23
        else:
            for t in wrap(text, 92):
                d.text((x, y), t, fill=(40, 40, 40), font=F["xs"])
                y += 19
            y += 3
    y = max(y + 10, d.im.size[1] - 70)
    for t in wrap(NOTE, 92):
        d.text((x, y), t, fill=(110, 110, 110), font=F["xs"])
        y += 18


def wrap(text, n):
    out, cur = [], ""
    for w in text.split():
        if len(cur) + len(w) + 1 > n:
            out.append(cur)
            cur = w
        else:
            cur = (cur + " " + w).strip()
    return out + ([cur] if cur else [])


def ll(p):
    return f"{p[0]:.6f}, {p[1]:.6f}"


def dock_parts(rec):
    return [Polygon(p) for p in rec["deck"]], [Polygon(p) for p in rec["slip_areas"]]


def draw_dock(s, rec, colour, ring=True, gangway=True):
    deck, slips = dock_parts(rec)
    for p in slips:
        s.poly(p, fill=(*colour, 60), outline=(*colour, 255), width=2)
    for p in deck:
        s.poly(p, fill=(*colour, 255), outline=BLACK, width=1)
    if gangway and rec.get("gangway_top"):
        b, n = np.array(rec["base"]), np.array(rec["dir"])
        foot = b + n * dp.GANGWAY_LAP_FT * FT
        s.poly(LineString([rec["gangway_top"], foot]).buffer(2 * FT, cap_style="flat"),
               fill=(200, 200, 200, 255), outline=BLACK, width=1)
    if ring:
        s.poly(unary_union(deck + slips).buffer(dp.SEPARATION_FT * FT), outline=(*colour, 230), width=2)


def main():
    day = Path(sys.argv[1]) if len(sys.argv) > 1 else sorted(ROOT.glob("out/*/dock permit/dock_permit.json"))[-1].parent.parent
    pdir = day / "dock permit"
    data = json.loads((pdir / "dock_permit.json").read_text())
    site = dp.Site(pdir)
    props, utrwd = dp.load_properties(json.loads((ROOT / "inputs/context/site-review-context-regional.json").read_text()))
    own, alt, nb = (data["proposed"][k] for k in ("owner_dock", "north_alternative", "neighbour_85552_potential"))
    P = data["properties"]
    shore = site.water.exterior

    # ---------------------------------------------------------------- DP1 site plan
    (c, sc) = SHOTS["overview"]
    s = Sheet(day / "check_dock_permit_overview_draft.png", c, sc)
    for key, col in (("116505", (230, 40, 40)), ("135089", (230, 40, 40)), ("85552", (255, 170, 60))):
        s.poly(props[key]["poly"], outline=(*col, 255), width=4)
    for k in range(6, 11):
        s.poly(props[f"Lot {k}"]["poly"], outline=(255, 255, 255, 140), width=1)
        cpt = props[f"Lot {k}"]["poly"].representative_point()
        s.label((cpt.x, cpt.y), f"Lot {k}", font="xs", box=(0, 0, 0, 120))
    s.line(list(shore.coords), (*SHORE_C, 255), 2)
    view = Polygon([(c[0] - sc / 2, c[1] - sc / 2), (c[0] + sc / 2, c[1] - sc / 2),
                    (c[0] + sc / 2, c[1] + sc / 2), (c[0] - sc / 2, c[1] + sc / 2)])
    for key, col in (("owner", ADMIN_C), ("85552", NEIGH_C)):
        for a, b in P[key]["admin_lines"]:
            ln = LineString([a, b])
            s.poly(ln.buffer(dp.ADMIN_FT * FT).intersection(view), fill=(*col, 40))
            s.line([a, b], (*col, 255), 4)
    for a, b in P["135089"]["admin_lines"][1:] + P["116505"]["admin_lines"][:1]:
        s.line([a, b], (*ADMIN_C, 200), 2, dash=10)
    for key, col in (("owner", OWNER_C), ("85552", NEIGH_C)):
        for r in P[key]["sites"]:
            x, y = s.px(*r["base"])
            s.d.ellipse([x - 4, y - 4, x + 4, y + 4], fill=(*col, 255), outline=BLACK)
    rt = own["boat_route"]
    if rt["fewest_removal_route"]:
        s.line(rt["fewest_removal_route"], (*ROUTE_C, 255), 3, dash=12)
    draw_dock(s, own, DOCK_C)
    draw_dock(s, nb, NEIGH_C)
    b, n = np.array(own["base"]), np.array(own["dir"])
    far = b + n * own["straight_across_ft"] * FT
    s.label(own["end"], f"PROPOSED DOCK\n{own['length_ft']:.0f} ft, slip {own['slip_min_depth_ft']} ft deep",
            font="s", offset=(-30, -70), anchor="ra")
    s.label(nb["end"], f"Neighbour CAD 85552:\nbest potential dock\n{nb['length_ft']:.0f} ft, {own['to_neighbour_dock_ft']} ft away",
            font="xs", offset=(-20, 20), anchor="ra", fill=(*NEIGH_C, 255))
    for key in ("Lot 6", "Lot 7", "Lot 8", "Lot 9"):
        r = data["south_lots"][key]
        x, y = r["best_site"]
        s.label((x, y), f"{key}: best slip {r['best_slip_depth_ft']} ft", font="xs", offset=(8, 0),
                fill=(255, 190, 190, 255), box=(0, 0, 0, 150))
    s.label((-215.0, -228.0), "Lot 10 corner: creek channel\n(cove under 300 ft - no boat dock)", font="xs",
            offset=(-10, -46), anchor="ra")
    s.scale_bar(400)
    oc = P["owner"]
    lines = [
        ("h", "Site plan"),
        ("key", "Proposed dock (one per property, owner's property CAD 116505 + 135089)", (*DOCK_C, 255)),
        ("key", "300 ft separation from any other dock (LSMP 6.2)", (*DOCK_C, 255)),
        ("key", "Administrative property lines and the 150 ft band docks must clear", (*ADMIN_C, 255)),
        ("key", "Shore points where a dock meets every rule: owner property", (*OWNER_C, 255)),
        ("key", "Shore points where a dock meets every rule: neighbour CAD 85552", (*NEIGH_C, 255)),
        ("key", "551 ft conservation pool shoreline", (*SHORE_C, 255)),
        ("key", "Boat lane to the deep channel, 20 ft wide (fewest trunks removed)", (*ROUTE_C, 255)),
        ("h", "Findings"),
        ("t", f"Owner property (both parcels, one owner): {oc['compliant']} of {oc['shore_points']} shore points can "
              f"take a dock that meets every rule tested. The proposed site is the deepest of those next to "
              f"the south parcel, at the parcel line, with no measured tree under the dock or gangway."),
        ("t", f"South parcel CAD 135089 on its own, and each 2 ac lot (Lots 6-10) on its own: no site meets "
              f"every rule. Lot frontages ({', '.join(str(P[f'Lot {k}']['frontage_ft']) for k in range(6, 11))} ft) "
              f"cannot keep a dock 150 ft from both administrative lines, and in front of Lots 7-10 the cove "
              f"is too narrow (Table 7) or the slips are under 3 ft."),
        ("t", f"Lot 10: the creek channel at its south corner is 5-9 ft deep and connects to the main channel "
              f"at {data['lot10_route']['max_min_depth_ft']} ft or deeper, but the water there is under "
              f"300 ft wide, so Table 7 allows no boat dock."),
        ("t", f"Neighbour CAD 85552 (west shore, {P['85552']['frontage_ft']} ft of frontage): "
              f"{P['85552']['compliant']} compliant shore points. The proposed dock rules out "
              f"{P['85552']['conflict_with_proposed']['ruled_out_by_proposed']} of them (300 ft rule); its best "
              f"potential site is {own['to_neighbour_dock_ft']} ft from the proposed dock, so either can be built "
              f"first."),
        ("t", f"Standing timber (Fish and Wildlife Habitat zone, no-wake) fills the cove. A boat lane 20 ft wide "
              f"from the proposed slip to the deep channel needs {rt['trunks_to_remove_for_lane']} trunk removed "
              f"({rt['fewest_removal_route_m'] / FT:,.0f} ft); without removal the widest gap is about "
              f"{rt['widest_lane_ft']} ft."),
    ]
    s.save(pdir / "DP1_site_plan.png", lines)

    # ---------------------------------------------------------------- DP2 dock detail
    (c, sc) = SHOTS["detail"]
    s = Sheet(day / "check_dock_permit_detail_draft.png", c, sc)
    gx, gy = np.meshgrid(np.arange(s.w), np.arange(s.h))
    X = c[0] + (gx - s.w / 2) * s.mpp
    Y = c[1] - (gy - s.h / 2) * s.mpp
    depth = site.depth_ft(X.ravel(), Y.ravel()).reshape(X.shape)
    band = np.floor(np.clip(depth, -4, 12)).astype(int)
    rgba = np.zeros((s.h, s.w, 4), np.uint8)
    pal = {1: (200, 235, 255), 2: (150, 210, 250), 3: (90, 170, 240), 4: (50, 130, 220), 5: (30, 90, 200)}
    for k, col in pal.items():
        m = (band == k - 1) if k < 5 else (band >= 4)
        rgba[m & (depth > 0)] = (*col, 95)

    def contour(level):
        """Pixels where the depth crosses `level` ft (a one-pixel line)."""
        a = depth >= level
        e = np.zeros_like(a)
        e[:, :-1] |= a[:, :-1] != a[:, 1:]
        e[:-1, :] |= a[:-1, :] != a[1:, :]
        return e
    for level in (1, 2, 4, 5, 6):
        rgba[contour(level)] = (255, 255, 255, 140)
    for level, col in ((0, (*SHORE_C, 255)), (3, (255, 230, 0, 255)), (-3, (255, 120, 40, 255))):
        e = contour(level)
        e[1:, :] |= e[:-1, :]                                      # two pixels wide
        e[:, 1:] |= e[:, :-1]
        rgba[e] = col
    s.layer = Image.alpha_composite(s.layer, Image.fromarray(rgba))
    s.d = ImageDraw.Draw(s.layer)
    draw_dock(s, own, DOCK_C, ring=False)
    t = np.array([-n[1], n[0]])
    rip = [LineString([b + t * (side * (2 * FT)), b + t * (side * (2 * FT + 10 * FT))]).buffer(0.7)
           for side in (1, -1)]
    for p in rip:
        s.poly(p, fill=(140, 120, 100, 255), outline=BLACK, width=1)

    def dim(p0, p1, text, off=1.2, font="xs"):
        p0, p1 = np.array(p0), np.array(p1)
        u = (p1 - p0) / (np.linalg.norm(p1 - p0) or 1)
        o = np.array([-u[1], u[0]]) * off
        s.line([p0 + o, p1 + o], (255, 255, 255, 255), 2)
        for q in (p0, p1):
            s.line([q + o * 0.4, q + o * 1.6], (255, 255, 255, 255), 2)
        s.label(tuple((p0 + p1) / 2 + o * 2.2), text, font=font, anchor="mm")
    L = own["length_ft"] * FT
    dim(b, b + n * L, f"{own['length_ft']:.0f} ft from the 551 ft shoreline (Table 7 max {own['max_length_ft']:.0f})", off=7.0)
    a0, a1, c0, c1 = own["slips_ft"][0]
    h0, h1, hc0, hc1 = own["deck_ft"][1]
    s.label(tuple(b + n * (a0 + a1) / 2 * FT), "slip\n12 x 30 ft", font="xs", anchor="mm", box=(0, 60, 0, 170))
    dim(b + n * h0 * FT + t * hc1 * FT, b + n * h0 * FT + t * hc0 * FT, f"head 6 x {hc1 - hc0:.0f} ft", off=4.5)
    dim(np.array(own["gangway_top"]), b + n * dp.GANGWAY_LAP_FT * FT,
        f"gangway {own['gangway_ft']:.0f} ft x 4 ft, hinged at 554 ft", off=-3.2)
    dim(b + t * 2 * FT, b + t * 12 * FT, "riprap 10 ft", off=2.5)
    for k, txt in (("base", "Dock base (551 ft shoreline)"), ("end", "Dock end"), ("gangway_top", "Gangway landing (554 ft)")):
        s.label(tuple(own[k]), f"{txt}\n{ll(own['wgs84'][k])}", font="xs",
                offset=(18, 18) if k != "end" else (-60, -150), anchor="la" if k != "end" else "ra")
    s.scale_bar(40)
    lines = [
        ("h", "Dock detail"),
        ("t", f"Floating dock, {own['design_label']}: walkway 6 ft x {own['deck_ft'][0][1]:.0f} ft square to the "
              f"shore (bearing {own['azimuth_deg']} deg), head 6 x {hc1 - hc0:.0f} ft parallel to the shore, one "
              f"12 x 30 ft slip outboard of the head, 3 ft outer walk. Deck {own['deck_sqft']} sq ft. Galvanized "
              f"guide poles; composite decking in a muted natural colour; no roof, walls or mooring cables."),
        ("key", "Water 0-1 / 1-2 / 2-3 / 3-4 / 4+ ft deep at 551 ft (1 ft contours to 6 ft)", (90, 170, 240, 255)),
        ("key", "3 ft depth contour (548 ft)", (255, 230, 0, 255)),
        ("key", "554 ft contour (gangway landing)", (255, 120, 40, 255)),
        ("key", "551 ft shoreline (lidar contour)", (*SHORE_C, 255)),
        ("key", "Riprap, 10 ft each side of the gangway", (140, 120, 100, 255)),
        ("h", "Rule check (LSMP comment draft 16 Oct 2025)"),
        ("row", ("Shoreline zone (4.1.1)", "Shoreline Mgmt Zone", "SMZ on App. A map", None)),
        ("row", ("Length (6.3, App. D)", "10-120 ft", f"{own['length_ft']:.0f} ft", True)),
        ("row", ("Cove width (6.3)", "dock <= 1/3 width", f"{own['cove_width_ft']} ft", True)),
        ("row", ("Table 7 (6.3)", f"<= (W-300)/2 = {own['max_length_ft']:.0f} ft", f"{own['length_ft']:.0f} ft", True)),
        ("row", ("Slip depth (6.3)", ">= 3 ft at 551 ft", f"{own['slip_min_depth_ft']} ft min", own["slip_min_depth_ft"] >= 3)),
        ("row", ("Spacing (6.2)", ">= 300 ft any dock", f"{own['to_neighbour_dock_ft']} ft*", True)),
        ("row", ("Admin. lines (6.2)", ">= 150 ft", f"{own['admin_line_ft']} ft", True)),
        ("row", ("Gangway (6.1.1, App. D)", "20-60 ft, at 554 ft", f"{own['gangway_ft']:.0f} ft", True)),
        ("row", ("Gangway angle (App. D)", "square to shoreline", f"{own['azimuth_deg']} deg", True)),
        ("row", ("Walkway width (App. D)", "3-6 ft", "6 ft", True)),
        ("row", ("Deck area (App. D)", "200-1,000 sq ft", f"{own['deck_sqft']} sq ft", True)),
        ("row", ("Slips (4.1.1, App. D)", "<= 2, 12 x 30 ft", "1, 12 x 30 ft", True)),
        ("row", ("Float height (6.1.1)", ">= 12 in above water", "12 in +", True)),
        ("row", ("Riprap (4.1.3)", ">= 10 ft each side", "10 ft", True)),
        ("row", ("Timber (4.1.1)", "removal discouraged", f"{own['trees_in_footprint']} under dock", True)),
        ("row", ("Boat lane", "20 ft, to channel", f"{rt['trunks_to_remove_for_lane']} trunk to remove", None)),
        ("row", ("Residence (4.1.1 A)", "occupied residence", "owner to confirm", None)),
        ("t", "* to the neighbour's best potential site across the cove; no docks exist nearby."),
        ("t", f"Margins: slip depth {own['slip_min_depth_ft'] - 3:.1f} ft over the 3 ft minimum; gangway "
              f"{60 - own['gangway_ft']:.0f} ft under the 60 ft maximum; length "
              f"{own['max_length_ft'] - own['length_ft']:.0f} ft under the Table 7 limit."),
    ]
    s.save(pdir / "DP2_dock_detail.png", lines)

    # ---------------------------------------------------------------- DP3 depth profile
    W, H = 2400, 1200
    img = Image.new("RGB", (W, H), (250, 250, 247))
    d = ImageDraw.Draw(img)
    d.text((40, 24), "Depth profile along the dock axis (bearing %d deg)" % own["azimuth_deg"],
           fill=(20, 20, 20), font=F["h2"])
    xs = np.arange(-70.0, 100.0, 0.5)
    pts = b[None, :] + n[None, :] * (xs[:, None] * FT)
    gz = (site.ground(pts[:, 0], pts[:, 1]) / FT)
    pool_ft = site.pool / FT
    elev = gz - pool_ft + 551.0
    X0, X1, Y0, Y1 = 140, W - 80, 120, H - 160
    e_lo, e_hi = 542.0, 558.0
    fx = lambda v: X0 + (v - xs[0]) / (xs[-1] - xs[0]) * (X1 - X0)
    fy = lambda e: Y1 - (e - e_lo) / (e_hi - e_lo) * (Y1 - Y0)
    d.polygon([(fx(xs[0]), fy(e_lo))] + [(fx(v), fy(e)) for v, e in zip(xs, elev)] + [(fx(xs[-1]), fy(e_lo))],
              fill=(176, 150, 112))
    wet = elev < 551.0
    for v, e, w in zip(xs, elev, wet):
        if w:
            d.line([(fx(v), fy(e)), (fx(v), fy(551.0))], fill=(120, 185, 235), width=3)
    for e, lab, col in ((551.0, "551 ft MSL conservation pool", (30, 110, 200)), (548.0, "548 ft: 3 ft slip depth", (230, 170, 0)),
                        (554.0, "554 ft: gangway landing", (230, 100, 30))):
        d.line([(X0, fy(e)), (X1, fy(e))], fill=col, width=2)
        d.text((X1 - 10, fy(e) - 24), lab, fill=col, font=F["s"], anchor="ra")
    for e in range(int(e_lo), int(e_hi) + 1, 2):
        d.text((X0 - 12, fy(e)), f"{e}", fill=(60, 60, 60), font=F["xs"], anchor="rm")
    for v in range(-60, 101, 10):
        d.line([(fx(v), Y1), (fx(v), Y1 + 8)], fill=(60, 60, 60), width=1)
        d.text((fx(v), Y1 + 12), f"{v}", fill=(60, 60, 60), font=F["xs"], anchor="ma")
    d.text(((X0 + X1) / 2, Y1 + 40), "feet from the 551 ft shoreline (negative = landward)", fill=(40, 40, 40), font=F["s"], anchor="ma")
    d.text((40, (Y0 + Y1) / 2), "ft MSL", fill=(40, 40, 40), font=F["s"])
    deck_z = 551.0 + 1.5
    for a0, a1, c0, c1 in own["deck_ft"]:
        d.rectangle([fx(a0), fy(deck_z), fx(a1), fy(deck_z - 1.0)], fill=(90, 80, 70), outline=(0, 0, 0))
    sa0, sa1 = own["slips_ft"][0][:2]
    d.rectangle([fx(sa0), fy(551.0), fx(sa1), fy(548.0)], outline=(230, 170, 0), width=3)
    d.text(((fx(sa0) + fx(sa1)) / 2, fy(548.0) + 8), "slip (12 ft across\nthis section)", fill=(160, 110, 0), font=F["xs"], anchor="ma")
    land = -own["shore_to_554ft_ft"]
    ge = float(np.interp(land, xs, elev))
    d.line([(fx(land), fy(ge + 0.5)), (fx(dp.GANGWAY_LAP_FT), fy(deck_z))], fill=(120, 120, 120), width=6)
    d.text((fx(land / 2), fy(deck_z + 2.2)), f"hinged gangway {own['gangway_ft']:.0f} ft", fill=(60, 60, 60), font=F["s"], anchor="ma")
    for v, lab in ((0, "shoreline"), (own["length_ft"], f"dock end {own['length_ft']:.0f} ft")):
        d.line([(fx(v), Y0), (fx(v), Y1)], fill=(120, 120, 120), width=1)
        d.text((fx(v) + 6, Y0), lab, fill=(60, 60, 60), font=F["xs"])
    d.text((40, H - 70), "Vertical exaggeration about %.0f x. The float rides about 1.5 ft above the water; slip depth is "
                         "the lidar ground below 551 ft across the whole 12 x 30 ft slip (shallowest %.1f ft)." %
           (((Y1 - Y0) / (e_hi - e_lo)) / ((X1 - X0) / (xs[-1] - xs[0])), own["slip_min_depth_ft"]),
           fill=(80, 80, 80), font=F["s"])
    d.text((40, H - 44), NOTE, fill=(110, 110, 110), font=F["xs"])
    img.save(pdir / "DP3_depth_profile.png")
    print(f"WROTE {pdir / 'DP3_depth_profile.png'}")

    # ---------------------------------------------------------------- DP4 south lots table
    W, H = 2400, 1050
    img = Image.new("RGB", (W, H), (250, 250, 247))
    d = ImageDraw.Draw(img)
    d.text((40, 24), "South parcel (CAD 135089, Lots 6-10): can each 2 ac lot have its own boat dock?", fill=(20, 20, 20), font=F["h2"])
    d.text((40, 62), "Each lot tested on its own (one owner per lot) at every shoreline point in front of it, with the dock "
                     "shapes allowed by the LSMP (straight, or a head parallel to the shore).", fill=(70, 70, 70), font=F["s"])
    cols = [("Lot", 40), ("Frontage", 270), ("Cove width", 420), ("Table 7 max", 590),
            ("Best slip depth", 760), ("150 ft rule", 960), ("All rules", 1110), ("What stops it", 1250)]
    y = 120
    for name, x in cols:
        d.text((x, y), name, fill=(20, 20, 20), font=F["b"])
    y += 40
    for key in ("Lot 6", "Lot 7", "Lot 8", "Lot 9", "Lot 10", "135089"):
        r = data["south_lots"][key]
        admin_ok = P[key]["fail_counts"].get("too close to an administrative property line", 0) < P[key]["shore_points"]
        why = []
        if any("Table 7" in f for f in r["fails_without_150ft_rule"]) or not r["max_length_ft"]:
            why.append("cove < 320 ft")
        if any("slips" in f for f in r["fails_without_150ft_rule"]):
            why.append("slips < 3 ft deep")
        if any("gangway" in f for f in r["fails_without_150ft_rule"]):
            why.append("gangway > 60 ft")
        if not admin_ok:
            why.append("frontage too narrow (150 ft rule)")
        label = "South parcel (whole)" if key == "135089" else key
        vals = [label, f"{r['frontage_ft']} ft", f"{r['cove_width_ft']} ft" if r["cove_width_ft"] else "-",
                f"{r['max_length_ft']:.0f} ft" if r["max_length_ft"] >= 10 else "none (<320 ft)",
                f"{r['best_slip_depth_ft']} ft", "yes" if admin_ok else "no", "no" if not r["compliant_with_all_rules"] else "yes",
                "; ".join(why)]
        if key == "135089":
            y += 10
            d.line([(40, y - 6), (W - 40, y - 6)], fill=(180, 180, 180), width=1)
        for (name, x), v in zip(cols, vals):
            fill = (190, 40, 30) if v == "no" else (30, 30, 30)
            d.text((x, y), v, fill=fill, font=F["s"])
        y += 44
    y += 20
    notes = [
        f"Answer: none of Lots 6-10 can have its own boat dock under the draft rules, and neither can the south parcel on "
        f"its own. Lots 9 and 10 front water under 300 ft wide (no boat dock at any length); Lot 7 and Lot 8 reach "
        f"at most 0.2 and 2.8 ft of slip depth; Lot 6 reaches 2.9 ft. Every 2 ac lot is also too narrow to keep a "
        f"dock 150 ft from both of its administrative property lines.",
        f"3 ft is first reached at the north-west corner of the south parcel: the proposed dock, at the parcel "
        f"line, has {own['slip_min_depth_ft']} ft slips - as the single dock of the owner's whole property "
        f"(CAD 116505 + 135089 under one owner).",
        "Shared use: a dock shared by several lot owners is a community association dock (LSMP 4.1.1 B: up to 20 "
        "slips, on a lot dedicated for access, permit in the association's name). It must meet the Water Quality "
        "Protection Criteria (Section 8): no septic systems (OSSFs) and central sewer where lots are under 5 acres.",
        f"Lot 10's creek channel: 5-9 ft deep and connected to the main channel at {data['lot10_route']['max_min_depth_ft']} ft "
        f"or deeper ({data['lot10_route']['route_3ft_m'] / FT:,.0f} ft route), so a boat could reach it, but the "
        f"channel is under 300 ft wide at Lot 10, where Table 7 allows no boat dock; a fishing/patio dock (33 ft, "
        f"100 sq ft) is the type the LSMP allows in narrow tributary water.",
    ]
    for t in notes:
        for line in wrap(t, 200):
            d.text((40, y), line, fill=(40, 40, 40), font=F["s"])
            y += 24
        y += 10
    d.text((40, H - 44), NOTE, fill=(110, 110, 110), font=F["xs"])
    img.save(pdir / "DP4_south_lots.png")
    print(f"WROTE {pdir / 'DP4_south_lots.png'}")

    # ---------------------------------------------------------------- DP5 neighbour
    (c, sc) = SHOTS["overview"]
    s = Sheet(day / "check_dock_permit_overview_draft.png", c, sc)
    s.base = s.base.crop((0, 300, 1300, 1600)).resize((1600, 1600), Image.LANCZOS)
    s.w, s.h = s.base.size
    s.mpp = s.mpp * 1300 / 1600
    s.c = (c[0] + (650 - 800) * sc / 1600, c[1] - (950 - 800) * sc / 1600)
    s.layer = Image.new("RGBA", s.base.size, (0, 0, 0, 0))
    s.d = ImageDraw.Draw(s.layer)
    s.poly(props["85552"]["poly"], outline=(255, 170, 60, 255), width=4)
    for key in ("116505", "135089"):
        s.poly(props[key]["poly"], outline=(230, 40, 40, 255), width=4)
    s.line(list(shore.coords), (*SHORE_C, 255), 2)
    for a, bb in P["85552"]["admin_lines"]:
        s.poly(LineString([a, bb]).buffer(dp.ADMIN_FT * FT), fill=(*NEIGH_C, 40))
        s.line([a, bb], (*NEIGH_C, 255), 4)
    foot = unary_union(sum(dock_parts(own), []))
    for r in P["85552"]["sites"]:
        x, y = s.px(*r["base"])
        lost = Polygon(r["footprint"]).distance(foot) / FT < dp.SEPARATION_FT
        s.d.ellipse([x - 5, y - 5, x + 5, y + 5], fill=(230, 40, 40, 255) if lost else (*NEIGH_C, 255), outline=BLACK)
    draw_dock(s, own, DOCK_C)
    draw_dock(s, nb, NEIGH_C)
    s.line([nb["end"], own["end"]], (255, 255, 255, 255), 2, dash=8)
    mid = ((nb["end"][0] + own["end"][0]) / 2, (nb["end"][1] + own["end"][1]) / 2)
    s.label(mid, f"{own['to_neighbour_dock_ft']} ft", font="b", anchor="mm")
    nrt = nb["boat_route"]
    if nrt["fewest_removal_route"]:
        s.line(nrt["fewest_removal_route"], (*NEIGH_C, 255), 3, dash=12)
    if rt["fewest_removal_route"]:
        s.line(rt["fewest_removal_route"], (*ROUTE_C, 255), 3, dash=12)
    s.label(tuple(props["85552"]["poly"].representative_point().coords[0]), "CAD 85552\n5.562 ac\n(C WOODS abstract)",
            font="s", anchor="mm")
    s.scale_bar(300)
    pn = P["85552"]
    lines = [
        ("h", "Across the cove: CAD 85552"),
        ("key", "Neighbour's shore points where a dock meets every rule", (*NEIGH_C, 255)),
        ("key", "... ruled out by the proposed dock (within 300 ft)", (230, 40, 40, 255)),
        ("key", "Neighbour's administrative lines and 150 ft bands", (*NEIGH_C, 255)),
        ("key", "Proposed dock and its 300 ft ring", (*DOCK_C, 255)),
        ("key", "Boat lanes to the deep channel (fewest trunks removed)", (*ROUTE_C, 255)),
        ("h", "Where the neighbour could build"),
        ("t", f"CAD 85552 fronts the west shore of the cove for {pn['frontage_ft']} ft (UTRWD land between it and "
              f"the water). {pn['compliant']} of its {pn['shore_points']} shore points can take a dock that meets "
              f"every rule tested, in three stretches; the best (deepest, no trunk under it) is a {nb['length_ft']:.0f} ft "
              f"{nb['design_label']} with {nb['slip_min_depth_ft']} ft slips at {ll(nb['wgs84']['base'])}."),
        ("h", "Conflicts and how the proposal avoids them"),
        ("t", f"300 ft spacing (6.2, also across the cove): the proposed dock is {own['to_neighbour_dock_ft']} ft "
              f"from the neighbour's best site. It rules out {pn['conflict_with_proposed']['ruled_out_by_proposed']} "
              f"of their {pn['compliant']} compliant points (red), all at the north end of their frontage; their "
              f"best site and the rest stay available, and if they build first the proposed site still passes."),
        ("t", f"Open channel (Table 7): each dock is limited to (cove width - 300 ft) / 2, so two docks facing each "
              f"other always leave a 300 ft channel. Proposed {own['length_ft']:.0f} ft of {own['max_length_ft']:.0f} ft "
              f"allowed; neighbour's best {nb['length_ft']:.0f} ft of {nb['max_length_ft']:.0f} ft."),
        ("t", f"Standing timber: both docks reach the deep channel through the habitat timber. A 20 ft lane needs "
              f"{rt['trunks_to_remove_for_lane']} trunk removed for the proposed dock and "
              f"{nrt['trunks_to_remove_for_lane']} for the neighbour's best site; the lanes can share the main channel."),
        ("t", "One dock per property under one owner (4.1.1 A): the proposal uses the owner's one dock; a second dock "
              "on the north parcel would need it held by a different owner."),
        ("t", "Showing the neighbour's potential dock in the application shows that the proposal leaves the "
              "opposite owner a compliant site and a 300 ft open channel."),
    ]
    s.save(pdir / "DP5_neighbour_across_cove.png", lines, title="Potential docks across the cove and conflicts")

    # ---------------------------------------------------------------- DP6 3D view
    v = Image.open(day / "check_dock_permit_from_water_draft.png").convert("RGB")
    d = ImageDraw.Draw(v)
    d.rectangle([0, v.size[1] - 56, v.size[0], v.size[1]], fill=(0, 0, 0))
    d.text((24, v.size[1] - 44), f"Proposed dock from over the water to the north-west: {own['length_ft']:.0f} ft floating dock, "
                                 f"one slip, {own['gangway_ft']:.0f} ft hinged gangway to the 554 ft landing, riprap each side, "
                                 f"6 ft path. Conceptual rendering, lake at 551 ft.", fill=(255, 255, 255), font=F["s"])
    v.save(pdir / "DP6_view_from_water.png")
    print(f"WROTE {pdir / 'DP6_view_from_water.png'}")


FISH_C = (90, 230, 230)


def five_acre_sheets(day):
    """DP7 (the 5 ac lot plan) and DP8 (each lot's dock in plan) for owner review."""
    import yaml
    pdir = day / "dock permit"
    data = json.loads((pdir / "dock_permit.json").read_text())
    five = data["five_acre"]
    paths = {p["parcel"]: p for p in json.loads((day / "permit5_paths.json").read_text())["paths"]}
    shots = yaml.safe_load((ROOT / "shots.yaml").read_text())["shots"]
    site = dp.Site(pdir)
    shore = site.water.exterior
    nb = data["proposed"]["neighbour_85552_potential"]
    out = pdir / "5 ac lots"
    out.mkdir(exist_ok=True)
    kind = lambda r: "fishing/patio" if r.get("type") == "fishing/patio" else "boat"

    # ---------------------------------------------------------------- DP7 plan
    cam = shots["check_permit5_overview"]["camera"]
    s = Sheet(day / "check_permit5_overview_draft.png", tuple(cam["center"]), cam["ortho_scale_m"])
    s.line(list(shore.coords), (*SHORE_C, 255), 2)
    for label, lot in five["lots"].items():
        poly = Polygon(lot["polygon"])
        for a, b in lot["admin_lines"]:
            s.poly(LineString([a, b]).buffer(dp.ADMIN_FT * FT), fill=(*ADMIN_C, 28))
            s.line([a, b], (*ADMIN_C, 255), 3)
        s.poly(poly, outline=(255, 255, 255, 255), width=3)
    for label, r in five["docks"].items():
        draw_dock(s, r, DOCK_C if kind(r) == "boat" else FISH_C)
    for p in paths.values():
        s.line(p["line"], (60, 30, 0, 255), 7)
        s.line(p["line"], (235, 180, 110, 255), 4)
    draw_dock(s, nb, NEIGH_C)
    for label, lot in five["lots"].items():
        poly = Polygon(lot["polygon"])
        ac = lot["acres_survey_scaled"] or lot["acres_cad"]
        c = poly.representative_point()
        s.label((c.x + 20, c.y), f"{label}  {ac:.2f} ac", font="h2", anchor="mm", box=(0, 0, 0, 150))
        r = five["docks"].get(label)
        if r:
            depth = f"slip {r['slip_min_depth_ft']} ft deep" if kind(r) == "boat" else f"{r['end_depth_ft']} ft of water at the end"
            s.label(tuple(r["end"]), f"{label}: {kind(r)} dock\n{r['length_ft']:.0f} ft, {depth}",
                    font="xs", offset=(-16, 0), anchor="rm")
        else:
            s.label(tuple(five["access_only"][label]["path_to"]), f"{label}: path to the shore,\nno dock site",
                    font="xs", offset=(-16, 0), anchor="rm", fill=(255, 190, 190, 255))
    s.label(tuple(nb["end"]), "Neighbour CAD 85552:\nbest potential dock", font="xs", offset=(-16, 0), anchor="rm",
            fill=(*NEIGH_C, 255))
    s.scale_bar(400)
    L = five["lots"]
    lines = [
        ("h", "Four 5 ac lots: a dock and path where the rules allow"),
        ("key", "5 ac lot lines (equal halves of each parcel, east-west)", WHITE),
        ("key", "Boat dock (floating, gangway at 554 ft) and its 300 ft ring", (*DOCK_C, 255)),
        ("key", "Fishing/patio dock (fixed, pedestrian, 10 x 20 ft) and its 300 ft ring", (*FISH_C, 255)),
        ("key", "Administrative property lines and the 150 ft band", (*ADMIN_C, 255)),
        ("key", "6 ft decomposed granite path, no tree removed", (235, 180, 110, 255)),
        ("key", "Neighbour's best potential dock (CAD 85552)", (*NEIGH_C, 255)),
        ("h", "Lots and docks"),
    ]
    for label in L:
        lot = L[label]
        if label not in five["docks"]:
            a = five["access_only"][label]
            p = paths[label.replace(" ", "_")]
            lines.append(("t", f"{label} ({lot['acres_cad']:.2f} ac by CAD; {lot['frontage_ft']} ft on UTRWD land): no dock. "
                               f"A 6 ft path ({p['length_ft']} ft) reaches its mainland shoreline, {a['shore_depth_ft_10ft_out']} ft "
                               f"deep 10 ft out. Why: {a['why_no_dock']}."))
            continue
        r = five["docks"][label]
        ac = (f"{lot['acres_cad']:.2f} ac by CAD, {lot['acres_survey_scaled']:.2f} ac by the survey"
              if lot["acres_survey_scaled"] else f"{lot['acres_cad']:.2f} ac by CAD")
        p = paths[label.replace(" ", "_")]
        if kind(r) == "boat":
            what = (f"boat dock, {r['design_label']}, {r['length_ft']:.0f} ft (cove {r['cove_width_ft']} ft, Table 7 max "
                    f"{r['max_length_ft']:.0f} ft); slip {r['slip_min_depth_ft']} ft deep; gangway {r['gangway_ft']:.0f} ft"
                    + (f"; {r['trees_in_footprint']} measured trunk under it" if r["trees_in_footprint"] else "; no trunk under it"))
        else:
            what = (f"fishing/patio dock 10 x 20 ft (cove {r['cove_width_ft']} ft); {r['end_depth_ft']} ft of water at "
                    f"its end; no boat dock site meets the rules on this lot ({lot['boat_sites']} boat sites)")
        lines.append(("t", f"{label} ({ac}; {lot['frontage_ft']} ft on UTRWD land): {what}. {r['admin_line_ft']} ft from "
                           f"its administrative lines; {r['nearest_dock_ft']} ft to the nearest other dock; path "
                           f"{p['length_ft']} ft. Dock base {ll(r['wgs84']['base'])}."))
    lines += [
        ("h", "Notes"),
        ("t", "Why 5 ac: the Water Quality Protection Criteria (LSMP 4.1.1, Section 8) bar septic systems in "
              "subdivisions with lots under 5 acres. The north parcel's halves are 4.92 ac on the CAD outline, which "
              "is 0.39 ac smaller than the 10.221 ac survey; by the survey each is 5.11 ac. The plat should confirm "
              "both north lots at 5.00 ac or more."),
        ("t", "Lot lines: each dock must be 150 ft from its lot's lines drawn through the UTRWD land to the water. "
              "The dividing lines were searched along the lake-side line and at angles up to 40 deg for the most "
              f"docks; the best are east-west ({L['Lot A']['lot_line_angle_deg']:.1f} and "
              f"{L['Lot C']['lot_line_angle_deg']:.1f} deg)."),
        ("t", "South parcel: the only shore reachable over dry ground is in front of old Lots 9-10 (about 256 ft); "
              "two docks need 300 ft between them, so only one south lot can have a dock. Lot D takes it: a fishing/patio "
              "dock (pedestrian only, fixed poles, 200 sq ft, App. D) in front of old Lot 10; no boat dock site meets the "
              "rules on either south lot. In front of old Lots 6-8 a low swale in the lidar becomes a slough at full "
              "pool (1-4 ft deep, up to about 45 ft wide), cutting the shoreline strip off from the land."),
        ("t", f"Spacing: all four docks are at least {min(r['nearest_dock_ft'] for r in five['docks'].values())} ft "
              f"from each other or the neighbour's best site. Lot C's dock is "
              f"{five['docks']['Lot C']['nearest_dock_ft']} ft from that site, so if Lot C builds first the neighbour "
              f"would use another of its compliant sites." if not five["neighbour_kept_300ft"] else
              "Spacing: every dock is at least 300 ft from the others and from the neighbour's best site."),
    ]
    s.save(out / "DP7_5ac_lot_plan.png", lines, title="5 ac lots: docks and paths (for review)")

    # ---------------------------------------------------------------- DP8 docks in plan
    tiles = []
    for label in five["lots"]:
        r = five["docks"].get(label)
        cam = shots[f"check_permit5_detail_{label[-1].lower()}"]["camera"]
        t = Sheet(day / f"check_permit5_detail_{label[-1].lower()}_draft.png", tuple(cam["center"]), cam["ortho_scale_m"])
        cx, cy = cam["center"]
        gx, gy = np.meshgrid(np.arange(t.w), np.arange(t.h))
        X, Y = cx + (gx - t.w / 2) * t.mpp, cy - (gy - t.h / 2) * t.mpp
        depth = site.depth_ft(X.ravel(), Y.ravel()).reshape(X.shape)
        rgba = np.zeros((t.h, t.w, 4), np.uint8)
        for level, col in ((0, (*SHORE_C, 255)), (1, (255, 255, 255, 160)), (2, (255, 255, 255, 160)),
                           (3, (255, 230, 0, 255)), (4, (255, 255, 255, 160)), (-3, (255, 120, 40, 255))):
            a = depth >= level
            e = np.zeros_like(a)
            e[:, :-1] |= a[:, :-1] != a[:, 1:]
            e[:-1, :] |= a[:-1, :] != a[1:, :]
            rgba[e] = col
        t.layer = Image.alpha_composite(t.layer, Image.fromarray(rgba))
        t.d = ImageDraw.Draw(t.layer)
        p = paths[label.replace(" ", "_")]
        t.line(p["line"], (235, 180, 110, 255), 3, dash=6)
        if r:
            draw_dock(t, r, DOCK_C if kind(r) == "boat" else FISH_C, ring=False)
            info = (f"{label}: {kind(r)} dock, {r['length_ft']:.0f} ft, bearing {r['azimuth_deg']} deg\n"
                    + (f"slip {r['slip_min_depth_ft']} ft deep at 551 ft; gangway {r['gangway_ft']:.0f} ft"
                       if kind(r) == "boat" else f"10 x 20 ft deck; {r['end_depth_ft']} ft of water at the end")
                    + f"\nbase {ll(r['wgs84']['base'])}")
        else:
            info = (f"{label}: no dock site meets the rules\n6 ft path to the mainland shore (slough);\n"
                    f"the strip beyond is cut off at full pool")
        t.label((14, 14), info, font="s", box=(0, 0, 0, 190))
        t.scale_bar(40)
        tiles.append(Image.alpha_composite(t.base, t.layer).convert("RGB"))
    W = tiles[0].size[0]
    sheet = Image.new("RGB", (2 * W + 30, 2 * W + 120), (250, 250, 247))
    d = ImageDraw.Draw(sheet)
    d.text((10, 14), "5 ac lots: each dock in plan (north up). Contours: 551 ft shoreline (blue), 1 / 2 / 4 ft (white), "
                     "3 ft (yellow), 554 ft (orange).", fill=(20, 20, 20), font=F["h2"])
    for i, tile in enumerate(tiles):
        sheet.paste(tile, (10 + (i % 2) * (W + 10), 60 + (i // 2) * (W + 10)))
    d.text((10, 2 * W + 84), NOTE, fill=(110, 110, 110), font=F["xs"])
    sheet.save(out / "DP8_5ac_docks.png")
    print(f"WROTE {out / 'DP8_5ac_docks.png'}")
    for name in ("check_permit5_oblique", "check_permit5_dock_b", "check_permit5_dock_d"):
        Image.open(day / f"{name}_draft.png").convert("RGB").save(out / f"{name.replace('check_', '')}.png")


if __name__ == "__main__":
    main()
    day = Path(sys.argv[1]) if len(sys.argv) > 1 else sorted(ROOT.glob("out/*/dock permit/dock_permit.json"))[-1].parent.parent
    if (day / "permit5_paths.json").is_file():
        five_acre_sheets(day)
