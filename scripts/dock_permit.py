"""Dock permit analysis: every dock site on the creek arm checked against the draft LSMP.

Rules (UTRWD Lake & Shoreline Management Plan, comment draft 16 Oct 2025):
- boat docks only on Shoreline Management Zone shoreline (4.1.1); the arm's shores are
  Shoreline Management Zone on the Appendix A map, south of CR 3640 Tributary Protection;
- one dock per property under one owner, occupied residence, two slips at most (4.1.1 A);
- 300 ft from the nearest point of any other dock, also across the cove (6.2);
- 150 ft from the administrative property lines: the applicant's property boundary
  drawn through the UTRWD shoreline land to the 551 ft contour (6.2);
- 10-120 ft from the 551 ft shoreline including the gangway, and at most 1/3 of the
  cove width (6.3, Appendix D);
- Table 7: no boat dock in a cove under 300 ft wide; otherwise at most
  (width - 300 ft) / 2, which keeps a 300 ft open channel (6.3);
- slips at least 3 ft deep at 551 ft (6.3); slips at most 12 x 30 ft (Appendix D);
- gangway perpendicular to the shoreline, attached at 554 ft or higher, 20-60 ft long
  (6.1.1, App. D): the 554 ft contour must be within 56 ft of the shoreline;
- walkway 3-6 ft wide, deck 200-1,000 sq ft (Appendix D).

The dock tested at each shoreline point is a 6 ft walkway square to the shore with two
12 x 30 ft slips at its end, one each side, and 3 ft outer fingers; it is as short as
the 3 ft slip rule allows. Depths are lidar ground (StratMap 2025) below 551 ft.

Usage (Blender's Python): python3.11 scripts/dock_permit.py [out/<date>/dock permit]
Reads z.npy and geom.json from scripts/blender/dock_permit_geom.py; writes
dock_permit.json there.
"""

import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts/blender"))

import lrh  # noqa: E402  (adds .blender-site to sys.path)
import numpy as np  # noqa: E402
import shapely  # noqa: E402
from shapely.affinity import translate  # noqa: E402
from shapely.geometry import LineString, Point, Polygon, box, shape  # noqa: E402
from shapely.ops import linemerge, unary_union  # noqa: E402

FT = 0.3048
SEPARATION_FT = 300.0
ADMIN_FT = 150.0
MAX_LEN_FT, MIN_LEN_FT = 120.0, 10.0
SLIP_DEPTH_FT = 3.0
SLIP_W_FT, SLIP_L_FT, WALK_W_FT, FINGER_W_FT = 12.0, 30.0, 6.0, 3.0
GANGWAY_TOP_FT = 3.0          # attached at 554 ft, 3 ft above the 551 ft pool
GANGWAY_MIN_FT, GANGWAY_MAX_FT = 20.0, 60.0
GANGWAY_LAP_FT = 4.0          # the gangway's foot rests this far onto the float
HOLE_FILL_M2 = 400.0          # lidar cracks and single tree mounds are not islands
PARCELS = Path("/Users/bperry/Documents/Projects/Ladonia/Reference/Spatial-Control/"
               "fannin-cad-cr3640-bordering-parcels-epsg6344.geojson")
NEIGHBOURS = ("85552", "79383", "128327", "132120")
PROPOSED_NEAR = (-153.5, -15.8)    # owner dock: deepest compliant site by the parcel line
NORTH_ALT_NEAR = (-170.8, 206.2)
OPEN_LAKE = (-330.0, 480.0)        # the deep channel at the north-west edge of the lidar, toward the main lake   # north path end: the north parcel's own compliant site


class Site:
    def __init__(self, day_dir):
        g = json.loads((day_dir / "geom.json").read_text())
        self.z = np.load(day_dir / "z.npy").astype(float)
        self.x0, self.y0, self.pool = g["xmin"], g["ymin"], g["pool_m"]
        arm = shapely.from_wkt(g["arm_wkt"])
        self.water = Polygon(arm.exterior, [r for r in arm.interiors if Polygon(r).area > HOLE_FILL_M2])
        shapely.prepare(self.water)
        ny, nx = self.z.shape
        self.rect = box(self.x0, self.y0, self.x0 + nx - 1, self.y0 + ny - 1)

    def mainland(self, x, y):
        """True where (x, y) is on mainland: dry ground (6 in above 551 ft, with threads
        under 3 m wide removed) in an area of 0.5 ha or more (the lidar grid clips the far shore) - not a strip or island that a
        path from the lot would have to wade to."""
        if not hasattr(self, "_main"):
            from collections import deque
            dry = np.nan_to_num(self.z, nan=-1e9) >= self.pool + 0.15
            core = dry.copy()
            for da, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                core &= np.roll(np.roll(dry, da, 0), dc, 1)
            ny, nx = core.shape
            label = np.zeros(core.shape, np.int32)
            sizes, k = [0], 0
            for i0, j0 in zip(*np.nonzero(core)):
                if label[i0, j0]:
                    continue
                k += 1
                label[i0, j0] = k
                q, n = deque([(i0, j0)]), 0
                while q:
                    a, c = q.popleft()
                    n += 1
                    for da, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                        u, v = a + da, c + dc
                        if 0 <= u < ny and 0 <= v < nx and core[u, v] and not label[u, v]:
                            label[u, v] = k
                            q.append((u, v))
                sizes.append(n)
            big = np.array(sizes) >= 5000
            big[0] = False
            self._main = big[label]
        i = np.clip(np.round(np.atleast_1d(y) - self.y0).astype(int), 0, self._main.shape[0] - 1)
        j = np.clip(np.round(np.atleast_1d(x) - self.x0).astype(int), 0, self._main.shape[1] - 1)
        out = self._main[i, j]
        for di in (-1, 0, 1):                  # the shore edge itself: any mainland cell next to it
            for dj in (-1, 0, 1):
                out = out | self._main[np.clip(i + di, 0, self._main.shape[0] - 1),
                                       np.clip(j + dj, 0, self._main.shape[1] - 1)]
        return out

    def ground(self, x, y):
        fx, fy = np.atleast_1d(x) - self.x0, np.atleast_1d(y) - self.y0
        ny, nx = self.z.shape
        inside = (fx >= 0) & (fx <= nx - 1) & (fy >= 0) & (fy <= ny - 1)
        out = np.full(fx.shape, np.nan)
        cx = np.clip(np.floor(fx[inside]).astype(int), 0, nx - 2)
        cy = np.clip(np.floor(fy[inside]).astype(int), 0, ny - 2)
        tx, ty = fx[inside] - cx, fy[inside] - cy
        z = self.z
        out[inside] = (z[cy, cx] * (1 - tx) * (1 - ty) + z[cy, cx + 1] * tx * (1 - ty)
                       + z[cy + 1, cx] * (1 - tx) * ty + z[cy + 1, cx + 1] * tx * ty)
        return out

    def depth_ft(self, x, y):
        return (self.pool - self.ground(x, y)) / FT

    def wet(self, x, y):
        return shapely.contains_xy(self.water, np.atleast_1d(x), np.atleast_1d(y))

    def run_to_shore(self, base, d, limit=700.0):
        """Distance from a shore point along d until the water ends (inf if it never does)."""
        s = np.arange(1.0, limit, 1.0)
        wet = self.wet(base[0] + d[0] * s, base[1] + d[1] * s)
        dry = np.nonzero(~wet[2:])[0]          # skip the first metres at the shore edge
        return float(s[dry[0] + 2]) if len(dry) else math.inf


def rot(v, deg):
    a = math.radians(deg)
    return np.array([v[0] * math.cos(a) - v[1] * math.sin(a), v[0] * math.sin(a) + v[1] * math.cos(a)])


def load_properties(context):
    o = json.loads((ROOT / "inputs/terrain/origin.json").read_text())["origin"]
    cad = json.loads(PARCELS.read_text())
    props, lake = {}, []
    for f in cad["features"]:
        g = translate(shape(f["geometry"]), -o["easting"], -o["northing"])
        p = f["properties"]
        if "LAKE" in str(p["legal_desc"]):
            lake.append(g)
        elif p["prop_id_text"] in NEIGHBOURS:
            props[p["prop_id_text"]] = {"poly": g, "label": f"CAD {p['prop_id_text']}",
                                        "desc": p["legal_desc"], "owner": "neighbour"}
    own = {b["prop_id"]: Polygon(np.array(b["lines_local_m"][0])[:, :2])
           for b in context["boundaries"] if b["kind"] == "owner_parcel_boundary"}
    props["owner"] = {"poly": unary_union(list(own.values())).buffer(1.0, join_style="mitre").buffer(-1.0, join_style="mitre"), "label": "Owner property (CAD 116505 + 135089)",
                      "owner": "owner"}
    props["116505"] = {"poly": own["116505"], "label": "North parcel CAD 116505", "owner": "owner"}
    props["135089"] = {"poly": own["135089"], "label": "South parcel CAD 135089", "owner": "owner"}
    for lot in context["conceptual_lots"]["lots"]:
        props[lot["label"]] = {"poly": Polygon(lot["polygon_local_m"]), "label": lot["label"], "owner": "lot"}
    return props, unary_union(lake)


def frontage(site, prop, utrwd, near):
    """Contact with UTRWD land, the two administrative lines and the frontage wedge."""
    poly = prop["poly"]
    poly = max(poly.geoms, key=lambda g: g.area) if poly.geom_type == "MultiPolygon" else poly
    contact = poly.exterior.intersection(utrwd.buffer(1.0))
    if contact.is_empty or contact.length < 5:
        return None
    merged = linemerge(contact) if contact.geom_type == "MultiLineString" else contact
    parts = [list(p.coords) for p in getattr(merged, "geoms", [merged])]
    joined = True
    while joined:                      # close metre gaps where two CAD parcels meet
        joined = False
        for i in range(len(parts)):
            for j in range(len(parts)):
                if i != j and math.dist(parts[i][-1], parts[j][0]) < 3.0:
                    parts[i] += parts.pop(j)
                    joined = True
                    break
            if joined:
                break
    parts = [LineString(p) for p in parts if LineString(p).length > 5]
    line = min(parts, key=lambda p: p.distance(near))
    ring = np.array(poly.exterior.coords[:-1])
    ends = []
    for end in (np.array(line.coords[0]), np.array(line.coords[-1])):
        i = int(np.argmin(np.linalg.norm(ring - end, axis=1)))
        side = []
        for j in ((i - 1) % len(ring), (i + 1) % len(ring)):
            mid = (ring[i] + ring[j]) / 2
            side.append((utrwd.distance(Point(mid)), ring[j]))
        v = end - max(side, key=lambda t: t[0])[1]          # the inland side line, outward
        d = v / np.linalg.norm(v)
        hit = None
        for s in np.arange(1.0, 600.0, 1.0):
            if site.wet(*(end + d * s))[0]:
                hit = end + d * s
                break
        if hit is None:                                       # side line runs along the shore
            q = shapely.ops.nearest_points(site.water.exterior, Point(end))[0]
            hit = np.array(q.coords[0])
            d = (hit - end) / np.linalg.norm(hit - end)
        ends.append({"start": end, "end": hit, "dir": d})
    # The frontage shoreline: the stretch of the 551 ft contour between the two lines.
    ext = site.water.exterior
    sa, sb = sorted(ext.project(Point(e["end"])) for e in ends)
    if sb - sa > ext.length / 2:
        sa, sb = sb, sa + ext.length
    admin = [LineString([e["start"], e["end"]]) for e in ends]
    return {"contact": line, "admin": admin, "shore_range": (sa, sb), "frontage_m": line.length}


def shore_points(site, step=2.0):
    ext = site.water.exterior
    inner = site.rect.buffer(-4.0)
    pts = []
    for s in np.arange(0, ext.length, step):
        p = ext.interpolate(s)
        if inner.contains(p):
            t = np.array(ext.interpolate(s + 5).coords[0]) - np.array(ext.interpolate(s - 5).coords[0])
            n = np.array([-t[1], t[0]]) / (np.linalg.norm(t) or 1)
            b = np.array(p.coords[0])
            if not site.wet(*(b + n * 4))[0]:
                n = -n
            if site.wet(*(b + n * 4))[0]:
                pts.append((b, n, s))
    return pts


def rect(b, n, a0, a1, c0, c1):
    """Rectangle a0..a1 ft out from the shore point and c0..c1 ft along the shore."""
    t = np.array([-n[1], n[0]])
    return Polygon([b + (n * a + t * c) * FT for a, c in ((a0, c0), (a1, c0), (a1, c1), (a0, c1))])


def design(kind, L):
    """(deck parts, slip rectangles) in feet for a dock reaching L ft from the shoreline.
    T2: walkway straight out, a slip each side of its last 30 ft, outer fingers.
    P1 / P2: walkway straight out to a head parallel to the shore, with one or two
    12 x 30 ft slips outboard of the head (parallel design, LSMP 6.1.1) and a 3 ft
    outer walk."""
    hw = WALK_W_FT / 2
    if kind == "T2":
        a = L - SLIP_L_FT
        deck = [(0, L, -hw, hw), (a, L, hw + SLIP_W_FT, hw + SLIP_W_FT + FINGER_W_FT),
                (a, L, -hw - SLIP_W_FT - FINGER_W_FT, -hw - SLIP_W_FT)]
        slips = [(a, L, hw, hw + SLIP_W_FT), (a, L, -hw - SLIP_W_FT, -hw)]
    else:
        half = (SLIP_L_FT + FINGER_W_FT) * (1 if kind == "P1" else 2) / 2 + FINGER_W_FT / 2
        d = L - WALK_W_FT - SLIP_W_FT - FINGER_W_FT
        deck = [(0, d, -hw, hw), (d, d + WALK_W_FT, -half, half),
                (L - FINGER_W_FT, L, -half, half)]
        if kind == "P1":
            slips = [(d + WALK_W_FT, L - FINGER_W_FT, -SLIP_L_FT / 2, SLIP_L_FT / 2)]
        else:
            slips = [(d + WALK_W_FT, L - FINGER_W_FT, -half + FINGER_W_FT, -FINGER_W_FT / 2),
                     (d + WALK_W_FT, L - FINGER_W_FT, FINGER_W_FT / 2, half - FINGER_W_FT)]
    return deck, slips


DESIGNS = {"T2": "straight walkway, 2 slips at the end", "P2": "parallel head, 2 slips",
           "P1": "parallel head, 1 slip"}


def deck_sqft(deck):
    return sum((a1 - a0) * (c1 - c0) for a0, a1, c0, c1 in deck)


def slip_depth(site, b, n, slips):
    """Shallowest point (ft at 551) over the slips."""
    pts = []
    for a0, a1, c0, c1 in slips:
        r = rect(b, n, a0, a1, c0, c1)
        x0, y0, x1, y1 = r.bounds
        gx, gy = np.meshgrid(np.linspace(x0, x1, 12), np.linspace(y0, y1, 12))
        inside = shapely.contains_xy(r.buffer(0.01), gx.ravel(), gy.ravel())
        pts.append(np.c_[gx.ravel()[inside], gy.ravel()[inside]])
    pts = np.vstack(pts)
    return float(np.min(site.depth_ft(pts[:, 0], pts[:, 1])))


def evaluate(site, b, n, trees, admin=(), others=()):
    """The shortest dock square to the shore at b that meets the rules, or why none does."""
    cove_ft = min(site.run_to_shore(b, rot(n, a)) for a in range(-25, 30, 5)) / FT
    across_ft = site.run_to_shore(b, n) / FT
    rec = {"base": [round(float(v), 2) for v in b], "dir": [round(float(v), 4) for v in n],
           "azimuth_deg": round((90.0 - math.degrees(math.atan2(n[1], n[0]))) % 360.0),
           "cove_width_ft": round(cove_ft) if math.isfinite(cove_ft) else None,
           "straight_across_ft": round(across_ft) if math.isfinite(across_ft) else None, "fails": []}
    lmax_ft = MAX_LEN_FT if not math.isfinite(cove_ft) else min(MAX_LEN_FT, cove_ft / 3, (cove_ft - SEPARATION_FT) / 2)
    rec["max_length_ft"] = round(max(lmax_ft, 0.0), 1)
    if lmax_ft < MIN_LEN_FT:
        rec["fails"].append("cove under 320 ft (Table 7)")
        lmax_ft = min(MAX_LEN_FT, cove_ft / 3) if math.isfinite(cove_ft) else MAX_LEN_FT  # for reporting depth
    found = None
    for kind in DESIGNS:
        lo = SLIP_L_FT if kind == "T2" else WALK_W_FT + SLIP_W_FT + FINGER_W_FT + 2
        for L in np.arange(max(MIN_LEN_FT, lo), lmax_ft + 0.01, 1.0):
            deck, slips = design(kind, float(L))
            if deck_sqft(deck) <= 1000 and slip_depth(site, b, n, slips) >= SLIP_DEPTH_FT:
                if found is None or L < found[1] - 10:     # a 1-slip dock only if 10+ ft shorter
                    found = (kind, float(L))
                break
    if found is None:
        L = max(lmax_ft, WALK_W_FT + SLIP_W_FT + FINGER_W_FT + 2)
        found = ("P1", float(L))
        rec["fails"].append(f"slips under {SLIP_DEPTH_FT:.0f} ft deep within {L:.0f} ft")
        rec["slip_depth_ft_at_max"] = round(slip_depth(site, b, n, design("P1", L)[1]), 1)
    kind, length_ft = found
    deck, slips = design(kind, length_ft)
    rec.update(design=kind, design_label=DESIGNS[kind], slips=1 if kind == "P1" else 2,
               length_ft=round(length_ft, 1), deck_sqft=round(deck_sqft(deck)),
               deck_ft=[[round(v, 2) for v in r] for r in deck], slips_ft=[[round(v, 2) for v in r] for r in slips])
    rec["slip_min_depth_ft"] = round(slip_depth(site, b, n, slips), 1)
    L = length_ft * FT
    rec["end"] = [round(float(v), 2) for v in b + n * L]
    rec["end_depth_ft"] = round(float(site.depth_ft(*(b + n * L))[0]), 1)
    s = np.linspace(0, L + 30 * FT, 31)
    rec["profile_ft"] = [[round(float(v / FT), 1), round(float(d), 1)]
                         for v, d in zip(s, site.depth_ft(b[0] + n[0] * s, b[1] + n[1] * s))]
    parts = [rect(b, n, *r) for r in deck]
    slip_polys = [rect(b, n, *r) for r in slips]
    foot = unary_union(parts + slip_polys)
    if admin:
        da = min(foot.distance(a) for a in admin) / FT
        rec["admin_line_ft"] = round(da)
        if da < ADMIN_FT:
            rec["fails"].append(f"{da:.0f} ft from an administrative property line (150 ft)")
    if others:
        do = min(foot.distance(o) for o in others) / FT
        rec["nearest_dock_ft"] = round(do)
        if do < SEPARATION_FT:
            rec["fails"].append(f"{do:.0f} ft from another dock (300 ft)")
    # Gangway: from the 554 ft contour on land to the 551 ft shoreline.
    s = np.arange(0.0, 80.0, 0.5)
    z = site.ground(b[0] - n[0] * s, b[1] - n[1] * s)
    top = np.nonzero(z >= site.pool + GANGWAY_TOP_FT * FT)[0]
    rec["shore_to_554ft_ft"] = round(float(s[top[0]]) / FT) if len(top) else None
    if len(top):
        rec["gangway_top"] = [round(float(v), 2) for v in b - n * s[top[0]]]
        rec["gangway_ft"] = max(GANGWAY_MIN_FT, rec["shore_to_554ft_ft"] + GANGWAY_LAP_FT)
    if not len(top) or rec["gangway_ft"] > GANGWAY_MAX_FT:
        rec["fails"].append(f"gangway over {GANGWAY_MAX_FT:.0f} ft to the 554 ft contour")
    if not site.mainland(*(b - n * 4.0))[0]:
        rec["fails"].append("shore cut off from the lot by water")
    # Standing timber (lidar trees rooted below the pool) in the dock and a 30 ft apron,
    # and any measured trunk in the dock or under the gangway (none may be removed).
    timber = trees[trees[:, 2] < site.pool]
    apron = foot.union(LineString([b + n * L, b + n * (L + 30 * FT)]).buffer(15 * FT))
    rec["timber_in_dock_and_apron"] = int(shapely.contains_xy(apron, timber[:, 0], timber[:, 1]).sum())
    land = rec["shore_to_554ft_ft"] or 0
    gang = LineString([b - n * land * FT, b + n * GANGWAY_LAP_FT * FT]).buffer(2 * FT + 0.5)
    rec["trees_in_footprint"] = int(shapely.contains_xy(foot.buffer(0.5).union(gang), trees[:, 0], trees[:, 1]).sum())
    xy = lambda g: [[round(float(x), 2), round(float(y), 2)] for x, y in g.exterior.coords]
    rec["deck"] = [xy(p) for p in parts]
    rec["slip_areas"] = [xy(p) for p in slip_polys]
    rec["footprint"] = xy(foot.convex_hull)
    rec["ok"] = not rec["fails"]
    return rec, foot


def best_sites(site, pts, shore_range, admin, trees, others=()):
    """Every shore point in the frontage, evaluated."""
    out = []
    sa, sb = shore_range
    length = site.water.exterior.length
    for b, n, s in pts:
        if sa <= s <= sb or sa <= s + length <= sb:
            rec, foot = evaluate(site, b, n, trees, admin, others)
            out.append((rec, foot))
    return out


def summary(rows):
    ok = [r for r, _ in rows if r["ok"]]
    fails = {}
    for r, _ in rows:
        for f in r["fails"]:
            key = f.split(" (")[0] if "administrative" not in f and "another dock" not in f else \
                ("too close to an administrative property line" if "administrative" in f else "too close to another dock")
            if key.startswith("slips under"):
                key = "slips under 3 ft deep"
            fails[key] = fails.get(key, 0) + 1
    best = max(ok, key=lambda r: (r["slip_min_depth_ft"], -r["length_ft"])) if ok else None
    near = None
    if not ok and rows:
        near = max((r for r, _ in rows), key=lambda r: (-len(r["fails"]), r.get("slip_depth_ft_at_max", r["slip_min_depth_ft"])))
    return {"shore_points": len(rows), "compliant": len(ok), "fail_counts": fails, "best": best, "nearest_miss": near}


def route_depth(site, start, goal):
    """Deepest-possible boat route (max over routes of the shallowest point) in the grid."""
    d = (site.pool - site.z) / FT
    ny, nx = d.shape
    def gx(p):
        """The deepest grid cell within 15 m of p."""
        i, j = int(round(p[1] - site.y0)), int(round(p[0] - site.x0))
        win = np.nan_to_num(d[i - 15:i + 16, j - 15:j + 16], nan=-99)
        a, c = np.unravel_index(np.argmax(win), win.shape)
        return i - 15 + a, j - 15 + c
    s, g = gx(start), gx(goal)
    lo, hi = 0.0, 12.0
    from collections import deque

    def connected(t):
        ok = np.nan_to_num(d, nan=-1) >= t
        if not (ok[s] and ok[g]):
            return None
        prev = np.full(d.shape, -1, dtype=np.int64)
        seen = np.zeros(d.shape, bool)
        seen[s] = True
        q = deque([s])
        while q:
            i, j = q.popleft()
            if (i, j) == g:
                path, k = [], i * nx + j
                while k != -1:
                    path.append((site.x0 + k % nx, site.y0 + k // nx))
                    k = prev[k // nx, k % nx]
                return path[::-1]
            for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)):
                a, c = i + di, j + dj
                if 0 <= a < ny and 0 <= c < nx and ok[a, c] and not seen[a, c]:
                    seen[a, c] = True
                    prev[a, c] = i * nx + j
                    q.append((a, c))
        return None
    best = None
    for _ in range(12):
        mid = (lo + hi) / 2
        p = connected(mid)
        if p:
            lo, best = mid, p
        else:
            hi = mid
    path3 = connected(SLIP_DEPTH_FT)
    return {"max_min_depth_ft": round(lo, 1),
            "route_3ft_m": round(LineString(path3).length) if path3 else None,
            "route_3ft": [[float(x), float(y)] for x, y in path3[::10]] if path3 else None,
            "route_best": [[float(x), float(y)] for x, y in best[::10]] if best else None}


def bfs(ok, s, g, x0, y0):
    """Shortest 8-connected route over the True cells of ok, as [(x, y)], or None."""
    from collections import deque
    ny, nx = ok.shape
    if not (ok[s] and ok[g]):
        return None
    prev = np.full(ok.shape, -1, dtype=np.int64)
    seen = np.zeros(ok.shape, bool)
    seen[s] = True
    q = deque([s])
    while q:
        i, j = q.popleft()
        if (i, j) == g:
            path, k = [], i * nx + j
            while k != -1:
                path.append((x0 + k % nx, y0 + k // nx))
                k = prev[k // nx, k % nx]
            return path[::-1]
        for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)):
            a, c = i + di, j + dj
            if 0 <= a < ny and 0 <= c < nx and ok[a, c] and not seen[a, c]:
                seen[a, c] = True
                prev[a, c] = i * nx + j
                q.append((a, c))
    return None


def boat_route(site, start, goal, timber, lane_ft=20.0):
    """Boat access from a slip to the open main lake through the standing timber, which
    may not be removed: the widest lane (clearance either side of the route centre to the
    nearest measured trunk) over water at least 3 ft deep, and the shortest 3 ft route
    with the trunks within half a lane of it."""
    d = np.nan_to_num((site.pool - site.z) / FT, nan=-1)
    ny, nx = d.shape
    def cell(p, r=8):
        """The deepest cell within r m of p."""
        i, j = int(round(p[1] - site.y0)), int(round(p[0] - site.x0))
        win = d[max(i - r, 0):i + r + 1, max(j - r, 0):j + r + 1]
        a, c = np.unravel_index(np.argmax(win), win.shape)
        return max(i - r, 0) + a, max(j - r, 0) + c
    s, g = cell(start), cell(goal)
    deep = d >= SLIP_DEPTH_FT
    ti = np.round(timber[:, 1] - site.y0).astype(int)
    tj = np.round(timber[:, 0] - site.x0).astype(int)
    keep = (ti >= 0) & (ti < ny) & (tj >= 0) & (tj < nx)
    ti, tj = ti[keep], tj[keep]

    def blocked(r):
        m = np.zeros(d.shape, bool)
        for di in range(-r, r + 1):
            for dj in range(-r, r + 1):
                if di * di + dj * dj <= r * r:
                    a, c = np.clip(ti + di, 0, ny - 1), np.clip(tj + dj, 0, nx - 1)
                    m[a, c] = True
        m[max(s[0] - 3, 0):s[0] + 4, max(s[1] - 3, 0):s[1] + 4] = False   # the slip itself
        return m
    best_r, best = 0, None
    for r in range(1, 9):
        p = bfs(deep & ~blocked(r), s, g, site.x0, site.y0)
        if p is None:
            break
        best_r, best = r, p
    plain = bfs(deep, s, g, site.x0, site.y0)
    half = lane_ft * FT / 2
    in_way = 0
    if plain:
        line = LineString(plain)
        in_way = int(np.sum(shapely.distance(line, shapely.points(timber[:, :2])) < half))
    lane = bfs(deep & ~blocked(int(math.ceil(half))), s, g, site.x0, site.y0)
    # The lane route that removes the fewest trunks: each step costs its length plus a
    # heavy toll inside half a lane of a trunk; then count the trunks it would remove.
    import heapq
    near = blocked(int(math.ceil(half)))
    cost = np.full(d.shape, np.inf)
    prev = np.full(d.shape, -1, dtype=np.int64)
    cost[s] = 0.0
    heap = [(0.0, s)]
    while heap:
        c0, (i, j) = heapq.heappop(heap)
        if c0 > cost[i, j]:
            continue
        if (i, j) == g:
            break
        for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)):
            a, c = i + di, j + dj
            if 0 <= a < ny and 0 <= c < nx and deep[a, c]:
                c1 = c0 + math.hypot(di, dj) + (40.0 if near[a, c] else 0.0)
                if c1 < cost[a, c]:
                    cost[a, c] = c1
                    prev[a, c] = i * nx + j
                    heapq.heappush(heap, (c1, (a, c)))
    fewest, removals = None, None
    if np.isfinite(cost[g]):
        path, k = [], g[0] * nx + g[1]
        while k != -1:
            path.append((site.x0 + k % nx, site.y0 + k // nx))
            k = prev[k // nx, k % nx]
        fewest = LineString(path[::-1])
        removals = int(np.sum(shapely.distance(fewest, shapely.points(timber[:, :2])) < half))
    return {"widest_lane_ft": round(2 * best_r / FT) if best else 0,
            "widest_lane_route": [[float(x), float(y)] for x, y in best[::4]] if best else None,
            "widest_lane_route_m": round(LineString(best).length) if best else None,
            "lane_ft": lane_ft, "lane_clear_without_removal": lane is not None,
            "lane_route": [[float(x), float(y)] for x, y in lane[::4]] if lane else None,
            "shortest_3ft_route_m": round(LineString(plain).length) if plain else None,
            "shortest_3ft_route": [[float(x), float(y)] for x, y in plain[::4]] if plain else None,
            "trunks_within_half_lane_of_shortest": in_way,
            "fewest_removal_route": [[round(x, 1), round(y, 1)] for x, y in list(fewest.coords)[::4]] if fewest else None,
            "fewest_removal_route_m": round(fewest.length) if fewest else None,
            "trunks_to_remove_for_lane": removals}


# Five-acre layout (owner, 1 Nov 2026): the draft LSMP's Water Quality Protection
# Criteria bar OSSFs in subdivisions with lots under 5 acres, so each parcel is split into
# two lots at equal area; each lot keeps lake-side (UTRWD) and CR 3635 frontage and gets
# its own dock and path (plan_five_acre).
# Record acreage: 116505 by its CAD declaration (survey per PLAN 7.5); 135089 by the signed
# CBG survey of 12 Aug 2022 (1145 CR 3635, 451,123 sq ft, including the corner at the point
# of beginning; Ladonia/Survey). Lot areas are CAD areas scaled per parcel to these.
SURVEY_ACRES = {"116505": 10.221, "135089": 10.36}
MIN_LOT_ACRES = 5.10            # 5 ac (Water Quality Protection Criteria) plus 0.1 ac margin
CR3635 = ROOT / "inputs/geometry/txdot-fannin-cr-3635-epsg6344.geojson"
FISHING_W_FT, FISHING_L_FT = 10.0, 20.0     # App. D: 200 sq ft, 10-20 ft each way, fixed poles
OLD_LOT10_Y = (-228.5, -173.9)              # Lot D's dock is placed in front of old Lot 10 if it can be


def split_parcel(poly, w, theta):
    """Cut poly by the line through w (on its lake-side line) at angle theta (radians from
    east); returns (north piece, south piece) or None if either is not one polygon."""
    u = np.array([math.cos(theta), math.sin(theta)])
    v = np.array([-u[1], u[0]])
    w = np.array(w)
    half = Polygon([w - u * 3000, w + u * 3000, w + u * 3000 + v * 3000, w - u * 3000 + v * 3000])
    north, south = poly.intersection(half), poly.difference(half)
    if north.geom_type != "Polygon" or south.geom_type != "Polygon":
        return None
    return north, south


def equal_split(poly, w, lim=math.radians(40)):
    """The angle through w that halves the area (bisection), or None."""
    f = lambda t: (lambda r: None if r is None else r[0].area - poly.area / 2)(split_parcel(poly, w, t))
    lo, hi = -lim, lim
    flo, fhi = f(lo), f(hi)
    if flo is None or fhi is None or flo * fhi > 0:
        return None
    for _ in range(50):
        mid = (lo + hi) / 2
        fm = f(mid)
        if fm is None:
            return None
        if (fm > 0) == (flo > 0):
            lo, flo = mid, fm
        else:
            hi = mid
    return (lo + hi) / 2


def evaluate_fishing(site, b, n, trees, admin=()):
    """A fishing/patio dock (pedestrian only, fixed poles): 10 ft wide, 20 ft out from the
    shoreline (200 sq ft, App. D), at most 1/3 of the cove (6.3), 150 ft from the
    administrative lines (6.2), no measured trunk under it."""
    cove_ft = min(site.run_to_shore(b, rot(n, a)) for a in range(-25, 30, 5)) / FT
    rec = {"type": "fishing/patio", "base": [round(float(v), 2) for v in b], "dir": [round(float(v), 4) for v in n],
           "azimuth_deg": round((90.0 - math.degrees(math.atan2(n[1], n[0]))) % 360.0),
           "cove_width_ft": round(cove_ft) if math.isfinite(cove_ft) else None,
           "length_ft": FISHING_L_FT, "width_ft": FISHING_W_FT, "deck_sqft": round(FISHING_L_FT * FISHING_W_FT),
           "deck_ft": [[0.0, FISHING_L_FT, -FISHING_W_FT / 2, FISHING_W_FT / 2]], "fails": []}
    if math.isfinite(cove_ft) and FISHING_L_FT > cove_ft / 3:
        rec["fails"].append(f"cove {cove_ft:.0f} ft: 20 ft is over 1/3")
    foot = rect(b, n, 0.0, FISHING_L_FT, -FISHING_W_FT / 2, FISHING_W_FT / 2)
    if admin:
        da = min(foot.distance(a) for a in admin) / FT
        rec["admin_line_ft"] = round(da)
        if da < ADMIN_FT:
            rec["fails"].append(f"{da:.0f} ft from an administrative property line (150 ft)")
    L = FISHING_L_FT * FT
    rec["end"] = [round(float(v), 2) for v in b + n * L]
    rec["end_depth_ft"] = round(float(site.depth_ft(*(b + n * L))[0]), 1)
    s = np.linspace(0, L + 10 * FT, 16)
    rec["profile_ft"] = [[round(float(v / FT), 1), round(float(d), 1)]
                         for v, d in zip(s, site.depth_ft(b[0] + n[0] * s, b[1] + n[1] * s))]
    rec["trees_in_footprint"] = int(shapely.contains_xy(foot.buffer(0.5), trees[:, 0], trees[:, 1]).sum())
    if rec["trees_in_footprint"]:
        rec["fails"].append("measured trunk under the dock")
    if not site.mainland(*(b - n * 4.0))[0]:
        rec["fails"].append("shore cut off from the lot by water")
    rec["deck"] = [[[round(float(x), 2), round(float(y), 2)] for x, y in foot.exterior.coords]]
    rec["slip_areas"] = []
    rec["footprint"] = rec["deck"][0]
    rec["ok"] = not rec["fails"]
    return rec


def plan_five_acre(site, pts, own, utrwd, trees, neighbour):
    """Four lots of at least MIN_LOT_ACRES (by the record acreage) across the whole
    property, each reaching CR 3635 and the UTRWD shoreline, each with its own dock.
    Lot lines need not follow the old parcel line: each of the three dividing lines is a
    straight line from a point on the lake-side boundary, at up to 40 deg from east-west.
    Its extension through the UTRWD land to the 551 ft contour is the administrative line
    both neighbouring docks must clear by 150 ft (6.2). Docks: every shore point where a
    boat dock or, failing that, a fishing/patio dock meets the rules on its own; all four
    docks 300 ft apart, and 300 ft from the neighbour's best potential site if possible.
    Preference: most boat docks, fewest trunks under docks, deepest slips."""
    whole = unary_union(list(own.values())).buffer(0.5, join_style="mitre").buffer(-0.5, join_style="mitre")
    k = {pid: SURVEY_ACRES[pid] / (own[pid].area / 4046.8564) for pid in own}

    def acres(piece):
        return sum(piece.intersection(own[pid]).area / 4046.8564 * k[pid] for pid in own)
    total = acres(whole)
    f = frontage(site, {"poly": whole}, utrwd, Point(-200.0, 0.0))
    contact = f["contact"]
    if contact.coords[0][1] > contact.coords[-1][1]:
        contact = LineString(list(contact.coords)[::-1])            # south to north
    outer = sorted(f["admin"], key=lambda a: a.coords[0][1])       # south, north
    o = json.loads((ROOT / "inputs/terrain/origin.json").read_text())["origin"]
    road = translate(shape(json.loads(CR3635.read_text())["features"][0]["geometry"]), -o["easting"], -o["northing"])
    road_side = whole.exterior.intersection(road.buffer(25.0))
    length = site.water.exterior.length
    sa, sb = f["shore_range"]

    # Candidate docks along the whole frontage (no administrative lines yet).
    cands = []
    for b, n, s_ in pts[::2]:
        if not (sa <= s_ <= sb or sa <= s_ + length <= sb):
            continue
        r, foot = evaluate(site, b, n, trees)
        if r["ok"]:
            cands.append(r)
            continue
        fr = evaluate_fishing(site, b, n, trees)
        if fr["ok"]:
            cands.append(fr)
    cands.sort(key=lambda r: r["base"][1])
    feet = [Polygon(r["footprint"]) for r in cands]
    nbf = Polygon(neighbour["footprint"])
    print("CANDS", len(cands), sum(r.get("type") != "fishing/patio" for r in cands), "boat")

    # Candidate dividing lines: (west point, angle) -> south area, admin segment.
    lines = []
    for d in np.arange(4.0, contact.length - 4.0, 3.0):
        w = np.array(contact.interpolate(d).coords[0])
        for deg in range(-40, 41, 4):
            th = math.radians(deg)
            cut = split_parcel(whole, w, th)
            if cut is None:
                continue
            north, south = cut
            if north.intersection(road_side).length < 15 or south.intersection(road_side).length < 15:
                continue
            u = np.array([math.cos(th), math.sin(th)])
            hit = None
            for t in np.arange(1.0, 400.0, 1.0):
                if site.wet(*(w - u * t))[0]:
                    hit = w - u * t
                    break
            if hit is None:
                continue
            lines.append({"w": w, "deg": deg, "u": u, "south_ac": acres(south), "admin": LineString([w, hit])})
    print("LINES", len(lines))
    adm = [L["admin"] for L in lines]
    dist = np.array([[ft.distance(a) / FT for a in adm] for ft in feet])          # dock x line
    side = np.array([[np.sign(np.cross(L["u"], np.array(r["base"]) - L["w"])) for L in lines] for r in cands])
    # north of a line: cross(u, p - w) > 0 (u points east)
    ok_line = (dist >= ADMIN_FT)
    out_ok = np.array([min(ft.distance(outer[0]), ft.distance(outer[1])) / FT >= ADMIN_FT for ft in feet])
    sep = np.array([[a.distance(b) / FT for b in feet] for a in feet])
    nb_ok = np.array([ft.distance(nbf) / FT >= SEPARATION_FT for ft in feet])
    S = np.array([L["south_ac"] for L in lines])

    def gap_lines(i, j):
        """Lines with dock i south and dock j north, both 150 ft clear."""
        return np.nonzero(ok_line[i] & ok_line[j] & (side[i] < 0) & (side[j] > 0))[0]

    def place(quad):
        """Greedy south-to-north choice of lines meeting the acreage, or None."""
        chosen, floor = [], MIN_LOT_ACRES
        for i, j in zip(quad[:-1], quad[1:]):
            g = gap_lines(i, j)
            g = g[S[g] >= floor - 1e-9]
            # every dock must be on the right side of this line, not only the pair
            g = [x for x in g if all(side[q, x] < 0 for q in quad[:quad.index(i) + 1])
                 and all(side[q, x] > 0 for q in quad[quad.index(j):])]
            if not g:
                return None
            x = min(g, key=lambda x: S[x])
            chosen.append(x)
            floor = S[x] + MIN_LOT_ACRES
        if total - S[chosen[-1]] < MIN_LOT_ACRES:
            return None
        return chosen

    n = len(cands)
    order = range(n)
    best = None
    for keep_nb in (True, False):
        for a in order:
            if not out_ok[a] or (keep_nb and not nb_ok[a]):
                continue
            for b in range(a + 1, n):
                if sep[a, b] < SEPARATION_FT or (keep_nb and not nb_ok[b]) or not len(gap_lines(a, b)):
                    continue
                for c in range(b + 1, n):
                    if sep[a, c] < SEPARATION_FT or sep[b, c] < SEPARATION_FT or (keep_nb and not nb_ok[c]) \
                            or not len(gap_lines(b, c)):
                        continue
                    for d in range(c + 1, n):
                        if not out_ok[d] or min(sep[a, d], sep[b, d], sep[c, d]) < SEPARATION_FT \
                                or (keep_nb and not nb_ok[d]) or not len(gap_lines(c, d)):
                            continue
                        quad = [a, b, c, d]
                        recs = [cands[q] for q in quad]
                        score = (sum(r.get("type") != "fishing/patio" for r in recs),
                                 -sum(r.get("trees_in_footprint", 0) for r in recs),
                                 min(r.get("slip_min_depth_ft", 0) for r in recs if r.get("type") != "fishing/patio")
                                 if any(r.get("type") != "fishing/patio" for r in recs) else 0,
                                 sum(r.get("slip_min_depth_ft", r["end_depth_ft"]) for r in recs))
                        if best is not None and score <= best[0]:
                            continue
                        chosen = place(quad)
                        if chosen is not None:
                            best = (score, quad, chosen)
        if best:
            break
    if best is None:
        lrh.fail("no layout gives four lots of 5 ac or more a legal dock each")
    _, quad, chosen = best
    labels = ("Lot D", "Lot C", "Lot B", "Lot A")                  # south to north
    pieces, rest = [], whole
    for x in chosen:
        L = lines[x]
        north, south = split_parcel(rest, L["w"], math.radians(L["deg"]))
        pieces.append(south)
        rest = north
    pieces.append(rest)
    bounds = [outer[0]] + [lines[x]["admin"] for x in chosen] + [outer[1]]
    plan, counts = {}, {}
    for i, label in enumerate(labels):
        r = dict(cands[quad[i]])
        piece = pieces[i]
        if piece.geom_type != "Polygon":
            lrh.fail(f"{label} is not one polygon")
        adm_i = [bounds[i], bounds[i + 1]]
        r["admin_line_ft"] = round(min(Polygon(r["footprint"]).distance(a) for a in adm_i) / FT)
        others = [Polygon(cands[q]["footprint"]) for q in quad if q != quad[i]] + [nbf]
        r["nearest_dock_ft"] = round(min(Polygon(r["footprint"]).distance(o2) for o2 in others) / FT)
        keys = ["base", "end"] + (["gangway_top"] if "gangway_top" in r else [])
        latlon = lrh.lat_lon([r[kk] for kk in keys])
        r["wgs84"] = {kk: [round(a, 6), round(b, 6)] for kk, (a, b) in zip(keys, latlon)}
        plan[label] = r
        front = piece.exterior.intersection(utrwd.buffer(1.0)).length
        counts[label] = {
            "dock": True, "acres_record": round(acres(piece), 2), "acres_cad": round(piece.area / 4046.8564, 2),
            "acres_by_parcel": {pid: round(piece.intersection(own[pid]).area / 4046.8564 * k[pid], 2) for pid in own
                                if piece.intersection(own[pid]).area > 1.0},
            "frontage_ft": round(front / FT), "road_frontage_ft": round(piece.intersection(road_side).length / FT),
            "admin_lines": [[[round(float(v), 1) for v in a.coords[0]], [round(float(v), 1) for v in a.coords[-1]]]
                            for a in adm_i],
            "polygon": [[round(x, 2), round(y, 2)] for x, y in piece.exterior.coords]}
    result_lines = [{"west": [round(float(v), 2) for v in lines[x]["w"]], "angle_deg": lines[x]["deg"],
                     "between": [labels[i], labels[i + 1]]} for i, x in enumerate(chosen)]
    for label in labels:
        print("LOT", label, counts[label]["acres_record"], counts[label]["acres_by_parcel"], "road",
              counts[label]["road_frontage_ft"], "ft")
    keep = all(Polygon(cands[q]["footprint"]).distance(nbf) / FT >= SEPARATION_FT for q in quad)
    return plan, counts, keep, {"record_total_acres": round(total, 3), "dividing_lines": result_lines,
                                "min_lot_acres": MIN_LOT_ACRES, "candidates": len(cands), "lines_tested": len(lines)}


def main():
    day_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else sorted(ROOT.glob("out/*/dock permit/geom.json"))[-1].parent
    site = Site(day_dir)
    context = lrh.load_context()
    props, utrwd = load_properties(context)
    t = np.load(ROOT / "out/derived/lidar_trees.npz")
    cols = list(t["columns"])
    trees = t["trees"][:, [cols.index("x"), cols.index("y"), cols.index("ground_z")]]
    pts = shore_points(site)
    near = Point(-200.0, -60.0)
    result = {"schema": "lrh.dock-permit/1", "rules": "UTRWD LSMP comment draft 2025-10-16, 4.1.1, 6.1-6.3, Table 7, Appendix D",
              "dock_tested": "walkway 6 ft wide square to the shore; T2 = two 12 x 30 ft slips at its end, "
                             "P2 / P1 = a head parallel to the shore with two / one 12 x 30 ft slips outboard; "
                             "the shortest length whose slips are all >= 3 ft deep at 551 ft",
              "cove_width": "narrowest water width within 25 deg of square to the shore (conservative); "
                            "straight_across_ft also given",
              "properties": {}}
    fronts = {}
    for key, prop in props.items():
        f = frontage(site, prop, utrwd, near)
        if f is None:
            continue
        fronts[key] = f
        rows = best_sites(site, pts, f["shore_range"], f["admin"], trees)
        result["properties"][key] = {
            "label": prop["label"], "owner": prop["owner"], "frontage_ft": round(f["frontage_m"] / FT),
            "admin_lines": [[[round(float(v), 1) for v in a.coords[0]], [round(float(v), 1) for v in a.coords[-1]]]
                            for a in f["admin"]],
            "contact": [[round(x, 1), round(y, 1)] for x, y in f["contact"].coords],
            **summary(rows), "sites": [r for r, _ in rows if r["ok"]]}
        print(key, prop["label"], "frontage", round(f["frontage_m"] / FT), "ft",
              {k: result["properties"][key][k] for k in ("shore_points", "compliant", "fail_counts")})
    # Current plan docks, as built in the scenes (each checked as the owner's single dock).
    plan = {"Shared south dock (Lot 6, straight west)": ((-155.8, -20.0), (-1.0, 0.0)),
            "Permit scene north dock": ((-170.8, 218.2), (-1.0, 0.0))}
    result["plan_docks"] = {}
    own_admin = fronts["owner"]["admin"]
    for name, (b, n) in plan.items():
        b, n = np.array(b), np.array(n)
        rec, _ = evaluate(site, b, n, trees, own_admin)
        rec_s, _ = evaluate(site, b, n, trees, fronts["135089"]["admin"])
        rec["fails_if_south_parcel_alone"] = rec_s["fails"]
        result["plan_docks"][name] = rec
        print("PLAN", name, rec["length_ft"], rec["slip_min_depth_ft"], rec["cove_width_ft"], rec["fails"], "| south alone:", rec_s["fails"])
    # The proposal: one dock for the owner's property (both parcels, one owner), at the
    # deepest compliant site next to the south parcel; the north path's alternative site
    # (north parcel on its own); the neighbour's best potential site across the cove.
    def pick(key, near_xy, radius=25.0):
        sites = [r for r in result["properties"][key]["sites"]
                 if math.dist(r["base"], near_xy) <= radius]
        return max(sites, key=lambda r: (r["trees_in_footprint"] == 0, r["slip_min_depth_ft"], -r["length_ft"])) \
            if sites else None
    proposed = pick("owner", PROPOSED_NEAR)
    north_alt = pick("116505", NORTH_ALT_NEAR)
    neighbour = max(result["properties"]["85552"]["sites"],
                    key=lambda r: (r["trees_in_footprint"] == 0, r["slip_min_depth_ft"], -r["length_ft"]))
    if proposed is None or north_alt is None or neighbour is None:
        lrh.fail("no compliant proposed, north alternative or neighbour dock site")
    feet = {k: Polygon(r["footprint"]) for k, r in (("proposed", proposed), ("north_alt", north_alt),
                                                   ("neighbour", neighbour))}
    ext = site.water.exterior
    sa, sb = fronts["owner"]["shore_range"]
    centre = (sa + sb) / 2
    proposed["frontage_centre_offset_ft"] = round(abs(ext.project(Point(proposed["base"])) - centre) / FT)
    proposed["to_neighbour_dock_ft"] = round(feet["proposed"].distance(feet["neighbour"]) / FT)
    proposed["to_north_alt_ft"] = round(feet["proposed"].distance(feet["north_alt"]) / FT)
    for rec in (proposed, north_alt, neighbour):
        keys = ["base", "end"] + (["gangway_top"] if "gangway_top" in rec else [])
        ll = lrh.lat_lon([rec[k] for k in keys])
        rec["wgs84"] = {k: [round(a, 6), round(b, 6)] for k, (a, b) in zip(keys, ll)}
        rec["utm15n_nad83_2011"] = {k: [round(rec[k][0] + lrh.ORIGIN_E, 1), round(rec[k][1] + lrh.ORIGIN_N, 1)]
                                    for k in keys}
    result["proposed"] = {"owner_dock": proposed, "north_alternative": north_alt,
                          "neighbour_85552_potential": neighbour}
    for key in NEIGHBOURS:
        p = result["properties"].get(key)
        if not p:
            continue
        lost = [r for r in p["sites"] if Polygon(r["footprint"]).distance(feet["proposed"]) / FT < SEPARATION_FT]
        p["conflict_with_proposed"] = {"compliant_sites": len(p["sites"]), "ruled_out_by_proposed": len(lost)}
        print("CONFLICT", key, p["conflict_with_proposed"])
    ours_left = [r for r in result["properties"]["owner"]["sites"]
                 if Polygon(r["footprint"]).distance(feet["neighbour"]) / FT >= SEPARATION_FT]
    result["properties"]["owner"]["sites_left_if_neighbour_builds_first"] = len(ours_left)
    result["proposed_still_ok_if_neighbour_builds_first"] = proposed["to_neighbour_dock_ft"] >= SEPARATION_FT
    # South lots: the best slips each can reach under the length rules, ignoring the
    # 150 ft line (which no 2 ac lot meets), and what stops it.
    result["south_lots"] = {}
    for key in ("135089", "Lot 6", "Lot 7", "Lot 8", "Lot 9", "Lot 10"):
        rows = best_sites(site, pts, fronts[key]["shore_range"], (), trees)
        best = max((r for r, _ in rows), key=lambda r: (r["ok"], not any("Table 7" in f for f in r["fails"]),
                                                      r.get("slip_depth_ft_at_max", r["slip_min_depth_ft"])))
        reach = best.get("slip_depth_ft_at_max", best["slip_min_depth_ft"])
        own = result["properties"][key]
        result["south_lots"][key] = {
            "frontage_ft": own["frontage_ft"], "best_slip_depth_ft": reach, "best_site": best["base"],
            "cove_width_ft": best["cove_width_ft"], "max_length_ft": best["max_length_ft"],
            "fails_without_150ft_rule": best["fails"], "compliant_with_all_rules": own["compliant"],
            "fail_counts": own["fail_counts"]}
        print("LOT", key, result["south_lots"][key]["best_slip_depth_ft"], best["fails"], own["compliant"])
    print("PROPOSED", {k: proposed[k] for k in ("base", "azimuth_deg", "design", "length_ft", "slip_min_depth_ft",
                                                "cove_width_ft", "admin_line_ft", "to_neighbour_dock_ft", "wgs84")})
    print("NORTH_ALT", {k: north_alt[k] for k in ("base", "azimuth_deg", "design", "length_ft", "slip_min_depth_ft", "admin_line_ft")})
    print("NEIGHBOUR", {k: neighbour[k] for k in ("base", "azimuth_deg", "design", "length_ft", "slip_min_depth_ft", "admin_line_ft")})
    # The standing timber as built in the scenes: lidar trees below the pool in UTRWD's
    # mapped Fish and Wildlife Habitat zone (out/derived/fwh_zone_lsmp.geojson).
    fwh = shape(json.loads((ROOT / "out/derived/fwh_zone_lsmp.geojson").read_text())["features"][0]["geometry"])
    tim = trees[(trees[:, 2] < site.pool) & shapely.contains_xy(fwh, trees[:, 0], trees[:, 1])]
    result["timber_trunks_in_zone"] = len(tim)
    for key, rec in result["proposed"].items():
        if key == "north_alternative":
            continue
        out = np.array(rec["end"]) + np.array(rec["dir"]) * 6.0      # just off the slip
        rec["boat_route"] = boat_route(site, out, OPEN_LAKE, tim)
        print("BOAT", key, {k: v for k, v in rec["boat_route"].items() if "route" not in k or k.endswith("_m")})
    result["lot10_route"] = route_depth(site, (-226.0, -216.0), (-200.0, 300.0))
    print("ROUTE", {k: v for k, v in result["lot10_route"].items() if not k.startswith("route_")},
          result["lot10_route"]["route_3ft_m"])
    own_polys = {pid: props[pid]["poly"] for pid in ("116505", "135089")}
    plan5, counts5, kept, layout5 = plan_five_acre(site, pts, own_polys, utrwd, trees, neighbour)
    for label, r in plan5.items():
        out = np.array(r["end"]) + np.array(r["dir"]) * 6.0
        r["boat_route"] = boat_route(site, out, OPEN_LAKE, tim) if r.get("type") != "fishing/patio" else None
        print("5AC", label, r.get("type", "boat"), r["base"], r["azimuth_deg"], r["length_ft"],
              r.get("slip_min_depth_ft", r.get("end_depth_ft")), "trees", r.get("trees_in_footprint"),
              "nearest", r["nearest_dock_ft"], "admin", r.get("admin_line_ft"), counts5[label])
    # A lot with no dock site still gets a walking path to its own shoreline (an access
    # path is permitted without a dock): due west from the middle of its lake-side line to
    # the first water on mainland ground.
    access = {}
    for label, c in counts5.items():
        if c["dock"]:
            continue
        lot = Polygon(c["polygon"])
        mid_y = (min(a[0][1] for a in c["admin_lines"]) + max(a[0][1] for a in c["admin_lines"])) / 2
        row = LineString([(-1e4, mid_y), (1e4, mid_y)]).intersection(lot)
        x0 = row.bounds[0]
        for x in np.arange(x0, x0 - 300, -0.5):
            if site.depth_ft(x, mid_y)[0] > 0:
                access[label] = {"path_from": [round(x0, 2), round(mid_y, 2)], "path_to": [round(x + 1.0, 2), round(mid_y, 2)],
                                 "shore_depth_ft_10ft_out": round(float(site.depth_ft(x - 3.0, mid_y)[0]), 1),
                                 "why_no_dock": "its shoreline in front of old Lots 6-8 is a strip cut off by a slough "
                                                "at full pool, and the mainland bank faces water too narrow for any "
                                                "dock (1/3 of the cove)"}
                break
    result["five_acre"] = {"lots": counts5, "docks": plan5, "access_only": access, "neighbour_kept_300ft": kept,
                           "layout": layout5,
                           "fishing_dock": "fixed-pole fishing/patio dock, pedestrian only, 10 x 20 ft = 200 sq ft "
                                           "(App. D), at most 1/3 of the cove; no depth rule (no mooring)"}
    (day_dir / "dock_permit.json").write_text(json.dumps(result, indent=1))
    print(f"WROTE {day_dir / 'dock_permit.json'}")


if __name__ == "__main__":
    main()
