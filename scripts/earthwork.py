"""Earthwork balance (owner, 20 Oct 2026): no dirt is bought, so every cut on the property
is tracked as a source and allocated to the lots' fill, nearest first.

Sources (in-place cut, from the current plan):
- the pond excavation (scripts/drainage.py), less the fill in its own berm;
- the creek channel and the diversion swales (site_works.py cross-sections);
- dock and shoreline-path work: placeholders until the docks are designed (SOURCES_EXTRA).
Sinks: each lot's net fill (fill less the cut already balanced on that lot) from
build_sites.json - the walk-out grading for the cabins, the pad and terraces for Lot 10.

Cut shrinks when dug and compacted: usable fill = in-place cut x SHRINK. Allocation is
greedy by haul distance. Also sizes larger ponds, as the main lever to close a shortfall.

Writes out/derived/earthwork.json. Usage (Blender's Python): python3.11 scripts/earthwork.py
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT / ".blender-site"))
sys.path.insert(0, str(ROOT / "scripts"))

import numpy as np  # noqa: E402
import shapely  # noqa: E402
from shapely.geometry import LineString, Point, Polygon  # noqa: E402

from kwik_ortho import Surface  # noqa: E402
import drainage  # noqa: E402

DERIVED = ROOT / "out/derived"
CU_YD = 0.764555
SHRINK = 0.88                  # bank (in-place) cut to compacted fill
PRIORITY = ["Lot 10"]          # built first (owner: the barndominium); served before the rest
# Future sources, in-place cu yd, added as they are designed: {name: (cu yd, (x, y))}.
SOURCES_EXTRA = {"Dock and shoreline-path work (placeholder until docks are designed)": (0, (-150.0, 0.0))}


def pond_volumes(dtm, pond):
    P = pond["polygon"] if isinstance(pond["polygon"], Polygon) else Polygon(pond["polygon"])
    x0, y0, x1, y1 = P.bounds
    gx, gy = np.meshgrid(np.arange(x0, x1, 0.5), np.arange(y0, y1, 0.5))
    X, Y = gx.ravel(), gy.ravel()
    ins = shapely.contains_xy(P, X, Y)
    din = shapely.distance(P.exterior, shapely.points(X, Y))
    basin = np.maximum(pond["bottom_m"], pond["pool_m"] + 0.05 - din / 3.0)
    cut = float(np.clip(dtm(X, Y) - basin, 0, None)[ins].sum() * 0.25)
    dam = pond["dam"] if isinstance(pond["dam"], LineString) else LineString(pond["dam"])
    bx0, by0, bx1, by1 = dam.buffer(8.0).bounds
    gx, gy = np.meshgrid(np.arange(bx0, bx1, 0.5), np.arange(by0, by1, 0.5))
    X, Y = gx.ravel(), gy.ravel()
    dd = shapely.distance(dam, shapely.points(X, Y))
    berm = pond["dam_crest_m"] - np.clip(dd - 1.0, 0.0, None) / 3.0
    out = ~shapely.contains_xy(P, X, Y) & (dd < 8.0)
    fill = float(np.clip(berm - dtm(X, Y), 0, None)[out].sum() * 0.25)
    return cut / CU_YD, fill / CU_YD


def main():
    dtm = Surface(DERIVED / "lidar_dtm_1m.tif")
    dr = json.loads((DERIVED / "drainage.json").read_text())
    pond = dr["pond"]
    pond_cut, berm = pond_volumes(dtm, pond)
    P = Polygon(pond["polygon"])
    sources = {"Pond excavation, less its berm": (pond_cut - berm, (P.centroid.x, P.centroid.y))}
    creek = LineString(dr["creek"]).difference(P.buffer(2.0))
    sources["Creek channel"] = (creek.length * (2 / 3) * 0.35 * 2.8 / CU_YD,
                                (creek.centroid.x, creek.centroid.y))
    for lot, lines in dr["swales"].items():
        ls = [LineString(l) for l in lines]
        length = sum(l.length for l in ls)
        c = shapely.union_all(ls).centroid
        sources[f"{lot} swale"] = (length * (2 / 3) * 0.25 * 3.2 / CU_YD, (c.x, c.y))
    for name, (vol, xy) in SOURCES_EXTRA.items():
        sources[name] = (vol, xy)
    lots = json.loads((DERIVED / "build_sites.json").read_text())["lots"]
    sinks = {}
    for r in lots:
        g = r.get("walkout") or r.get("barndo_grading") or {}
        need = g.get("fill_cu_yd", 0) - g.get("cut_cu_yd", 0)
        if need > 0 and r.get("pad_centre_local_m"):
            sinks[r["lot"]] = [float(need), tuple(r["pad_centre_local_m"])]
    # Greedy nearest-first: repeatedly take the shortest source->sink haul with both open.
    avail = {k: v[0] * SHRINK for k, v in sources.items()}
    moves = []
    # Each lot's own swale dirt stays on that lot.
    for s in list(sources):
        lot = s[:-len(" swale")] if s.endswith(" swale") else None
        if lot in sinks and avail[s] >= 1:
            q = min(avail[s], sinks[lot][0])
            avail[s] -= q
            sinks[lot][0] -= q
            moves.append({"from": s, "to": lot, "cu_yd_compacted": round(q), "haul_ft": 0})
    # Shared sources (pond, creek, docks, any leftover swale dirt): priority lots first,
    # then nearest first.
    while True:
        best = None
        open_priority = [k for k in PRIORITY if k in sinks and sinks[k][0] >= 1 and
                         any(v >= 1 for v in avail.values())]
        for s, (vol, sxy) in sources.items():
            if avail[s] < 1:
                continue
            for k, (need, kxy) in sinks.items():
                if need < 1 or (open_priority and k not in open_priority):
                    continue
                d = float(np.hypot(sxy[0] - kxy[0], sxy[1] - kxy[1]))
                if best is None or d < best[0]:
                    best = (d, s, k)
        if best is None:
            break
        d, s, k = best
        q = min(avail[s], sinks[k][0])
        avail[s] -= q
        sinks[k][0] -= q
        moves.append({"from": s, "to": k, "cu_yd_compacted": round(q), "haul_ft": round(d / 0.3048)})
    need_total = sum((r.get("walkout") or r.get("barndo_grading") or {}).get("fill_cu_yd", 0) -
                     (r.get("walkout") or r.get("barndo_grading") or {}).get("cut_cu_yd", 0) for r in lots)
    supply_total = sum(v[0] for v in sources.values()) * SHRINK
    # Larger-pond options (same site, same depth): extra usable fill.
    options = []
    for scale in (1.4, 1.8, 2.2):
        p2 = drainage.pond_design(dtm, LineString(dr["creek"]), length=46.0 * scale, width=30.0 * scale)
        c2, b2 = pond_volumes(dtm, p2)
        options.append({"pond_ac": round(p2["area_ac"], 2), "pond_cut_cu_yd": round(c2),
                        "berm_cu_yd": round(b2),
                        "extra_usable_fill_cu_yd": round((c2 - b2 - (pond_cut - berm)) * SHRINK)})
    out = {"schema": "lrh.earthwork/1", "shrink_factor": SHRINK,
           "sources_in_place_cu_yd": {k: round(v[0]) for k, v in sources.items()},
           "pond": {"cut_cu_yd": round(pond_cut), "berm_cu_yd": round(berm)},
           "supply_usable_cu_yd": round(supply_total), "demand_net_fill_cu_yd": round(need_total),
           "shortfall_cu_yd": round(max(0.0, need_total - supply_total)),
           "moves": moves, "remaining_need_by_lot": {k: round(v[0]) for k, v in sinks.items()},
           "larger_pond_options": options}
    (DERIVED / "earthwork.json").write_text(json.dumps(out, indent=1) + "\n")
    print(json.dumps({k: out[k] for k in ("sources_in_place_cu_yd", "supply_usable_cu_yd",
                                          "demand_net_fill_cu_yd", "shortfall_cu_yd",
                                          "remaining_need_by_lot", "larger_pond_options")}, indent=1))
    for mv in moves:
        print(mv)


if __name__ == "__main__":
    main()
