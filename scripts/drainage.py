"""Drainage analysis and conceptual drainage plan (owner, 20 Oct 2026).

1. Natural flow paths from the 1 m StratMap lidar DTM, resampled to 2 m: priority-flood
   depression filling, D8 flow directions, and upslope contributing area. Cells draining
   more than STREAM_M2 form the flow-path network (natural drains, road ditches).
2. Conceptual plan, all for review with a civil engineer:
   - a diversion swale round the uphill (road) side of each cabin's graded site, splitting
     at a high point and carrying runoff past both sides toward the lake;
   - a pond on the natural drain that collects the south side of the property (Lot 10 and
     the new CR 3640 ditch), with a spillway to the creek arm.

Writes out/derived/drainage.json (flow network, swales, pond) and
out/derived/drainage_acc.npy (contributing area grid) for plot_drainage.py.

Usage (Blender's Python): python3.11 scripts/drainage.py
"""

import heapq
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT / ".blender-site"))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts/blender"))

import numpy as np  # noqa: E402
import shapely  # noqa: E402
import shapely.ops  # noqa: E402
from shapely.geometry import LineString, Point, Polygon, box, mapping  # noqa: E402

from kwik_ortho import Surface  # noqa: E402
import grading  # noqa: E402

DERIVED = ROOT / "out/derived"
POOL_M = 167.9448
CELL = 2.0
X0, X1, Y0, Y1 = -320.0, 300.0, -420.0, 360.0      # covers the parcel and the land draining to it
STREAM_M2 = 2500.0                                   # ~0.6 ac contributing area
BARNDO = set()
D8 = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]


def flow(z):
    """Priority-flood fill from the edges and the lake (cells at or below pool), then D8."""
    h, w = z.shape
    filled = np.full(z.shape, np.inf)
    done = np.zeros(z.shape, bool)
    heap = []
    edge = np.zeros(z.shape, bool)
    edge[0, :] = edge[-1, :] = edge[:, 0] = edge[:, -1] = True
    edge |= z <= POOL_M
    for i, j in zip(*np.nonzero(edge)):
        filled[i, j] = z[i, j]
        done[i, j] = True
        heapq.heappush(heap, (z[i, j], i, j))
    while heap:
        e, i, j = heapq.heappop(heap)
        for di, dj in D8:
            a, b = i + di, j + dj
            if 0 <= a < h and 0 <= b < w and not done[a, b]:
                done[a, b] = True
                filled[a, b] = max(z[a, b], e + 1e-4)
                heapq.heappush(heap, (filled[a, b], a, b))
    # D8 steepest descent on the filled surface.
    pad = np.pad(filled, 1, constant_values=np.inf)
    best = np.zeros(z.shape)
    target = np.full(z.shape + (2,), -1, int)
    for di, dj in D8:
        nb = pad[1 + di:1 + di + h, 1 + dj:1 + dj + w]
        drop = (filled - nb) / (np.hypot(di, dj) * CELL)
        better = drop > best
        best = np.where(better, drop, best)
        ii, jj = np.mgrid[0:h, 0:w]
        target[..., 0] = np.where(better, ii + di, target[..., 0])
        target[..., 1] = np.where(better, jj + dj, target[..., 1])
    order = np.argsort(-filled, axis=None)
    acc = np.full(z.size, CELL * CELL)
    tflat = target.reshape(-1, 2)
    for k in order:
        ti, tj = tflat[k]
        if ti >= 0:
            acc[ti * w + tj] += acc[k]
    return filled, acc.reshape(z.shape), target


def network(acc, target, z, xs, ys):
    """Stream polylines: trace each channel head downstream until it joins a traced cell."""
    h, w = acc.shape
    stream = (acc >= STREAM_M2) & (z > POOL_M)
    seen = np.zeros(acc.shape, bool)
    heads = [(i, j) for i, j in zip(*np.nonzero(stream))]
    heads.sort(key=lambda c: acc[c])
    lines = []
    for i, j in heads:
        if seen[i, j]:
            continue
        pts = []
        while True:
            pts.append((float(xs[j]), float(ys[i]), float(acc[i, j])))
            if seen[i, j]:
                break
            seen[i, j] = True
            ti, tj = target[i, j]
            if ti < 0 or not stream[ti, tj]:
                if ti >= 0:
                    pts.append((float(xs[tj]), float(ys[ti]), float(acc[ti, tj])))
                break
            i, j = ti, tj
        if len(pts) >= 3:
            lines.append(pts)
    return lines


def trace(target, z, xs, ys, start_xy):
    """Downstream path from the cell nearest start_xy until it reaches the pool."""
    j = int(np.argmin(np.abs(xs - start_xy[0])))
    i = int(np.argmin(np.abs(ys - start_xy[1])))
    pts = []
    for _ in range(5000):
        pts.append((float(xs[j]), float(ys[i])))
        if z[i, j] <= POOL_M:
            break
        ti, tj = target[i, j]
        if ti < 0:
            break
        i, j = ti, tj
    return LineString(pts).simplify(1.0)


def pond_design(dtm, creek, centre_x=-70.0, length=46.0, width=30.0):
    """A pond on the creek (owner, 20 Oct 2026): an ellipse along the creek centred where
    it crosses x = centre_x, excavated about 6 ft below a normal pool set by the lowest
    natural ground round its upstream two-thirds; a low dam with a spillway closes the
    downstream end."""
    hit = creek.intersection(LineString([(centre_x, -1e4), (centre_x, 1e4)]))
    c = hit if hit.geom_type == "Point" else list(getattr(hit, "geoms", [hit]))[0]
    s = creek.project(c)
    a, b = creek.interpolate(max(0, s - 10)), creek.interpolate(min(creek.length, s + 10))
    ang = np.arctan2(b.y - a.y, b.x - a.x)
    t = np.linspace(0, 2 * np.pi, 72, endpoint=False)
    ex, ey = length / 2 * np.cos(t), width / 2 * np.sin(t)
    px = c.x + ex * np.cos(ang) - ey * np.sin(ang)
    py = c.y + ex * np.sin(ang) + ey * np.cos(ang)
    ring = dtm(px, py)
    upstream = np.cos(t) < 0.33                     # flow runs toward +x along the ellipse axis
    pool = float(np.percentile(ring[upstream], 15)) - 0.1
    down = ~upstream
    dam = LineString(list(zip(px[down], py[down])))
    return {"polygon": Polygon(list(zip(px, py))), "pool_m": pool, "bottom_m": pool - 1.8,
            "dam": dam, "dam_crest_m": pool + 0.6, "centre": (c.x, c.y),
            "spill": creek.interpolate(min(creek.length, s + length / 2 + 4)),
            "area_ac": Polygon(list(zip(px, py))).area / 4046.86}


POND_TARGET_AC = 0.87          # owner, 20 Oct 2026: the larger pond, for fill
POND_CENTRE_X = -72.0


def pond_fitted(dtm, creek, keep_in, avoid, target_ac=POND_TARGET_AC, centre_x=POND_CENTRE_X):
    """The pond grown along the creek (length : width 2 : 1) until, clipped to keep_in and
    clear of avoid, it covers target_ac. Pool from the upstream rim, dam on the
    downstream rim, as pond_design."""
    best = None
    for scale in np.arange(1.0, 4.01, 0.05):
        p = pond_design(dtm, creek, centre_x=centre_x, length=46.0 * scale * 1.1, width=30.0 * scale * 0.85)
        poly = p["polygon"].intersection(keep_in).difference(avoid)
        if poly.geom_type != "Polygon":
            poly = max(getattr(poly, "geoms", [poly]), key=lambda g: g.area)
        poly = poly.buffer(-8.0).buffer(8.0).simplify(0.3)          # round off clipped corners
        best = (p, poly)
        if poly.area / 4046.86 >= target_ac:
            break
    p, poly = best
    c = Point(p["centre"])
    s = creek.project(c)
    a, b = creek.interpolate(max(0, s - 10)), creek.interpolate(min(creek.length, s + 10))
    ux, uy = b.x - a.x, b.y - a.y
    n = np.hypot(ux, uy)
    ux, uy = ux / n, uy / n
    ring = np.array(poly.exterior.coords)[:-1]
    along = (ring[:, 0] - c.x) * ux + (ring[:, 1] - c.y) * uy
    half = along.max()
    up = along < 0.33 * half
    pool = float(np.percentile(dtm(ring[up, 0], ring[up, 1]), 15)) - 0.1
    down = ring[~up]
    order = np.argsort(np.arctan2(down[:, 1] - c.y, down[:, 0] - c.x))
    dam = LineString(down[order]) if len(down) > 1 else LineString(ring[:2])
    exit_s = max(creek.project(Point(q)) for q in ring)
    return {"polygon": poly, "pool_m": pool, "bottom_m": pool - 1.8, "dam": dam,
            "dam_crest_m": pool + 0.6, "centre": (c.x, c.y),
            "spill": creek.interpolate(min(creek.length, exit_s + 4)), "area_ac": poly.area / 4046.86}


SWALE_BOTTOM, SWALE_SIDE, SWALE_MAX_DEPTH = 6 * 0.3048, 4.0, 3 * 0.3048


def creek_swale(dtm, creek, pond, parcel):
    """Owner, 20 Oct 2026: grade the creek from where it enters the property down to the
    pond into an intentional grassed swale - trapezoid, 6 ft bottom, 4:1 sides, up to 3 ft
    deep - with an even invert falling to the pond's normal pool. Its cut is fill for the
    lots nearby (earthwork.py)."""
    inside = creek.intersection(parcel.buffer(-1.0))
    s_in = min(creek.project(Point(c)) for g in getattr(inside, "geoms", [inside]) for c in g.coords)
    s_pond = min(creek.project(Point(c)) for c in pond["polygon"].exterior.coords)
    reach = shapely.ops.substring(creek, s_in, s_pond)
    g0 = float(dtm(*reach.coords[0]))
    top_inv = g0 - SWALE_MAX_DEPTH
    end_inv = pond["pool_m"]
    pts = [(round(x, 1), round(y, 1)) for x, y in reach.coords]
    return {"line": pts, "invert_start_m": round(top_inv, 3), "invert_end_m": round(end_inv, 3),
            "bottom_m": SWALE_BOTTOM, "side_slope": SWALE_SIDE, "max_depth_m": SWALE_MAX_DEPTH,
            "length_m": round(reach.length, 1)}


def creek_swale_design(cs, x, y, ground):
    """Finished grade for the creek swale at points (x, y): the trapezoid cut, never fill."""
    line = LineString(cs["line"])
    pts = shapely.points(np.asarray(x), np.asarray(y))
    d = shapely.distance(line, pts)
    s = shapely.line_locate_point(line, pts) / max(line.length, 1e-6)
    inv = cs["invert_start_m"] + (cs["invert_end_m"] - cs["invert_start_m"]) * s
    inv = np.maximum(inv, np.asarray(ground) - cs["max_depth_m"])     # no deeper than 3 ft
    face = inv + np.clip(d - cs["bottom_m"] / 2, 0.0, None) / cs["side_slope"]
    return np.minimum(np.asarray(ground), face)


NAT_MIN_M2, NAT_BOTTOM, NAT_SIDE, NAT_DEPTH = 2500.0, 4 * 0.3048, 4.0, 1.5 * 0.3048


def natural_swales(dtm, flow_lines, parcel, keep_out, lots):
    """Owner, 20 Oct 2026: grade the property's natural drainage paths into shallow
    grassed swales for a little more fill - trapezoid, 4 ft bottom, 4:1 sides, 1.5 ft
    deep, the invert never rising downstream. Only paths draining more than about 1 ac,
    inside the property, clear of building sites, drives and septic areas."""
    out = []
    inner = parcel.buffer(-3.0)
    for l in flow_lines:
        pts = [(x, y) for x, y, a in l if a >= NAT_MIN_M2]
        if len(pts) < 4:
            continue
        line = LineString(pts).intersection(inner).difference(keep_out)
        for seg in getattr(line, "geoms", [line]):
            if seg.is_empty or seg.geom_type != "LineString" or seg.length < 12.0:
                continue
            seg = seg.simplify(0.8)
            xy = np.array(seg.coords)
            inv = dtm(xy[:, 0], xy[:, 1]) - NAT_DEPTH
            inv = np.minimum.accumulate(inv)                       # never rises downstream
            lot = next((k for k, poly in lots.items() if poly.contains(seg.centroid)), None)
            out.append({"line": [[round(x, 1), round(y, 1)] for x, y in xy],
                        "invert_m": [round(float(v), 3) for v in inv], "lot": lot,
                        "length_m": round(seg.length, 1)})
    return out


def natural_swale_design(sw, x, y, ground):
    """Finished grade with the natural swales cut in (cut only)."""
    x, y, ground = (np.asarray(a, float) for a in (x, y, ground))
    out = ground.copy()
    pts = shapely.points(x, y)
    for s in sw:
        line = LineString(s["line"])
        near = shapely.distance(line, pts)
        sel = near < NAT_BOTTOM / 2 + NAT_DEPTH * NAT_SIDE + 0.5
        if not sel.any():
            continue
        cum = np.concatenate([[0], np.cumsum(np.hypot(*np.diff(np.array(s["line"]), axis=0).T))])
        st = shapely.line_locate_point(line, pts[sel])
        inv = np.interp(st, cum, s["invert_m"])
        face = inv + np.clip(near[sel] - NAT_BOTTOM / 2, 0.0, None) / NAT_SIDE
        out[sel] = np.minimum(out[sel], face)
    return out


def swales(sites):
    """Diversion swale round the uphill (road) side of each cabin's graded area: from a
    high point east of it, along both sides to its lake-side end, 3 m outside the grading."""
    out = {}
    for label, (pad, terraces) in sites.items():
        extra = [] if label in BARNDO else [box(*grading.layout(pad.bounds)["carport"])]
        area = shapely.union_all([pad] + extra + [box(*t[:4]) for t in terraces])
        x0, y0, x1, y1 = area.bounds
        xe, xw, yn, ys = x1 + 3.0, x0, y1 + 3.0, y0 - 3.0
        ym = (y0 + y1) / 2
        out[label] = [LineString([(xe, ym), (xe, yn), (xw, yn)]),
                      LineString([(xe, ym), (xe, ys), (xw, ys)])]
    return out


def main():
    dtm = Surface(DERIVED / "lidar_dtm_1m.tif")
    xs = np.arange(X0, X1, CELL) + CELL / 2
    ys = np.arange(Y1, Y0, -CELL) - CELL / 2
    gx, gy = np.meshgrid(xs, ys)
    z = dtm(gx.ravel(), gy.ravel()).reshape(gx.shape)
    filled, acc, target = flow(z)
    lines = network(acc, target, z, xs, ys)
    np.save(DERIVED / "drainage_acc.npy", acc)
    ctx = json.loads((ROOT / "inputs/context/site-review-context-regional.json").read_text())
    parcel = shapely.union_all([Polygon(np.array(b["lines_local_m"][0])[:, :2])
                                for b in ctx["boundaries"] if b["kind"] == "owner_parcel_boundary"])
    on_parcel = [l for l in lines if LineString([p[:2] for p in l]).intersects(parcel.buffer(30))]
    out = {"schema": "lrh.drainage/1", "grid": {"x0": X0, "y1": Y1, "cell": CELL,
                                                 "shape": list(acc.shape)},
           "stream_threshold_m2": STREAM_M2,
           "flow_lines": [[[round(x, 1), round(y, 1), round(a)] for x, y, a in l] for l in on_parcel]}
    (DERIVED / "drainage.json").write_text(json.dumps(out) + "\n")
    # Conceptual plan.
    creek = trace(target, z, xs, ys, (79.0, -241.0))           # from the CR 3640 corner ditch
    sites = {}
    bs = json.loads((DERIVED / "build_sites.geojson").read_text())["features"]
    avoid = shapely.union_all([shapely.geometry.shape(f["geometry"]).buffer(3.0) for f in bs
                               if f["properties"]["kind"] in ("pad", "septic")
                               and f["properties"].get("lot") != "Lot 10"] or [Polygon()])
    pond = pond_fitted(dtm, creek, parcel.buffer(-6.0), avoid)
    access = [shapely.geometry.shape(f["geometry"]) for f in bs if f["properties"]["kind"] == "access_road"][0]
    drives = [shapely.geometry.shape(f["geometry"]) for f in bs if f["properties"]["kind"] == "drive_front"]
    for f in bs:
        p = f["properties"]
        if p["kind"] == "pad" and p.get("house") in ("standard", "barndo") and "terraces" in p:
            sites[p["lot"]] = (shapely.geometry.shape(f["geometry"]), p["terraces"])
            if p.get("house") == "barndo":
                BARNDO.add(p["lot"])
    sw = swales(sites)
    cs = creek_swale(dtm, creek, pond, parcel)
    import build_sites as _bs
    lot_polys, _ = _bs.lots_and_road()
    keep = [pond["polygon"].buffer(4.0), LineString(cs["line"]).buffer(6.0), access.buffer(6.0)]
    keep += [d.buffer(4.0) for d in drives]
    for f in bs:
        p = f["properties"]
        if p["kind"] in ("pad", "septic", "drip_lake", "rec_site"):
            g = shapely.geometry.shape(f["geometry"])
            if p["kind"] == "pad":
                g = shapely.union_all([g] + [box(*t[:4]) for t in p.get("terraces", [])])
            keep.append(g.buffer(4.0 if p["kind"] != "pad" else 6.0))
    nat = natural_swales(dtm, out["flow_lines"], parcel, shapely.union_all(keep), lot_polys)
    culverts = []
    for name, line in [("creek", creek)] + [(f"{k} swale", l) for k, ls in sw.items() for l in ls]:
        for other_name, other in [("access road", access)] + [("drive", d) for d in drives]:
            x = line.intersection(other)
            for pt in getattr(x, "geoms", [x]):
                if not pt.is_empty and pt.geom_type == "Point":
                    culverts.append({"at": [round(pt.x, 1), round(pt.y, 1)], "carries": name,
                                     "under": other_name})
    out["creek"] = [[round(x, 1), round(y, 1)] for x, y in creek.coords]
    out["pond"] = {"polygon": [[round(x, 1), round(y, 1)] for x, y in pond["polygon"].exterior.coords],
                   "pool_m": round(pond["pool_m"], 2), "pool_ft": round(pond["pool_m"] / 0.3048, 1),
                   "bottom_m": round(pond["bottom_m"], 2), "dam": [[round(x, 1), round(y, 1)] for x, y in pond["dam"].coords],
                   "dam_crest_m": round(pond["dam_crest_m"], 2), "area_ac": round(pond["area_ac"], 2),
                   "spillway": [round(pond["spill"].x, 1), round(pond["spill"].y, 1)]}
    out["creek_swale"] = cs
    out["natural_swales"] = nat
    out["swales"] = {k: [[[round(x, 1), round(y, 1)] for x, y in l.coords] for l in ls] for k, ls in sw.items()}
    out["culverts"] = culverts
    (DERIVED / "drainage.json").write_text(json.dumps(out) + "\n")
    print(f"natural swales {len(nat)} ({sum(n['length_m'] for n in nat):.0f} m); creek swale {cs['length_m']:.0f} m; creek {creek.length:.0f} m; pond {pond['area_ac']:.2f} ac, pool {pond['pool_m'] / 0.3048:.1f} ft; "
          f"{len(sw)} cabin swales; {len(culverts)} culverts")
    big = sorted(on_parcel, key=lambda l: -max(p[2] for p in l))[:12]
    for l in big:
        a = max(p[2] for p in l)
        print(f"flow line: {len(l)} cells, max area {a / 4046.86:.1f} ac, "
              f"from ({l[0][0]:.0f},{l[0][1]:.0f}) to ({l[-1][0]:.0f},{l[-1][1]:.0f})")


if __name__ == "__main__":
    main()
