"""Phase 2d house layout and finished-grade surface, shared by scripts/build_sites.py
(analysis) and scripts/blender/cabins.py (model). Pure numpy; no Blender.

The house follows Satterwhite's Hemlock plan (owner, 19 Oct 2026): a 30 x 42 ft main
floor, ridge east-west, the gable end facing the lake (west), an 8 x 30 ft gable porch,
a 6 ft porch along the south side and a 4 ft porch along the north, both 50 ft long. The
terrace level below is partly built into the slope: its floor T is at the lake end's
natural grade (walk-out), and the road (east) end is backfilled BURY against a concrete
back wall. The side grades run from T at the lake end to T + BURY at the back wall, and
the yard east of the house stays at T + BURY (the front entry level). Outside the pad,
fill slopes are 4:1 and cut slopes 3:1 back to natural ground.
"""

import numpy as np

FT = 0.3048
BODY = (42 * FT, 30 * FT)          # main floor E-W x N-S (Hemlock)
GABLE_PORCH = 8 * FT               # across the lake (west) gable end
SOUTH_PORCH = 6 * FT               # front porch, 50 ft long
NORTH_PORCH = 4 * FT               # side porch, 50 ft long
GROUND_STOREY = 3.2                # terrace floor to main floor (9.5 ft clear + framing)
BURY = 5 * FT                      # earth against the back wall
EAST_MARGIN = 3.0                  # back wall to the pad's east edge (entry yard)
SOUTH_MARGIN = 2.3                 # pad's south edge to the south porch line (stair room)
FILL_SLOPE, CUT_SLOPE = 4.0, 3.0
BOAT_DOOR = (0.6, 3.6)             # boat / storage door on the north wall, metres from the lake wall
CARPORT = (22 * FT, 24 * FT)       # covered parking (owner, 19 Oct 2026), E-W x N-S
CARPORT_GAP = 1.2                  # back wall to the carport's west edge (walkway)
PATIO_EXT = 2.4                    # concrete patio beyond the gable porch line (owner, 20 Oct 2026)
FIREPIT_R = 3.0                    # decomposed-granite fire-pit circle beyond the patio


def layout(pad_bounds):
    """House lines in local metres from the pad rectangle (x0, y0, x1, y1)."""
    x0, y0, x1, y1 = pad_bounds
    xe = x1 - EAST_MARGIN
    xw = xe - BODY[0]
    ys = y0 + SOUTH_MARGIN
    yb0 = ys + SOUTH_PORCH
    yb1 = yb0 + BODY[1]
    cx0 = xe + CARPORT_GAP
    cy0 = ys - 0.8
    xp = xw - GABLE_PORCH
    cyb = (yb0 + yb1) / 2
    fire = (xp - PATIO_EXT - FIREPIT_R + 0.4, cyb + 0.6)
    return {"xw": xw, "xe": xe, "y0": yb0, "y1": yb1, "xp": xp,
            "ys": ys, "yn": yb1 + NORTH_PORCH,
            "carport": (cx0, cy0, cx0 + CARPORT[0], cy0 + CARPORT[1]),
            # Walk-out patio: concrete from the lake wall to PATIO_EXT past the gable
            # porch, wrapping under the south porch's lake end where the stair lands.
            "patio": (xp - PATIO_EXT, ys - 0.4, xw, yb1),
            "firepit": fire,
            # Flat (terrace-level) area for the patio and the fire-pit circle.
            "terrace_flat": (fire[0] - FIREPIT_R - 0.6, ys - 0.6, xp, yb1 + 0.4)}


def nearest_flat(x, y, pad_bounds):
    """Nearest point on the graded flat area - the pad, the carport slab (entry-yard
    level) or the walk-out patio and fire-pit terrace - and the distance to it."""
    L = layout(pad_bounds)
    boxes = [pad_bounds, (L["carport"][0] - 0.5, L["carport"][1] - 0.5, L["carport"][2] + 0.5,
                          L["carport"][3] + 0.5), L["terrace_flat"]]
    best = None
    for b0, b1, b2, b3 in boxes:
        qx, qy = np.clip(x, b0, b2), np.clip(y, b1, b3)
        dq = np.hypot(x - qx, y - qy)
        if best is None:
            best = [qx, qy, dq]
        else:
            use = dq < best[2]
            best = [np.where(use, qx, best[0]), np.where(use, qy, best[1]), np.minimum(dq, best[2])]
    return best[0], best[1], best[2]


def terrace_boxes(pad_bounds, room_m, n_max=3, width=6.0):
    """Garden / orchard terraces stepping down toward the lake below the fire-pit terrace
    (owner, 20 Oct 2026): up to n_max boxes, each about `width` m east-west, across the
    terrace's north-south extent. Levels are set by the caller from the natural grade."""
    tf = layout(pad_bounds)["terrace_flat"]
    n = int(min(n_max, room_m // 5.0))
    if n < 1:
        return []
    w = min(width, room_m / n)
    return [(tf[0] - (i + 1) * w, tf[1], tf[0] - i * w, tf[3]) for i in range(n)]


def design(x, y, ground, pad_bounds, T, E, terraces=()):
    """Finished grade at points (x, y) given natural `ground` there (arrays). `terraces`:
    [(x0, y0, x1, y1, level)] flat steps below the walk-out terrace."""
    x, y, ground = (np.asarray(a, float) for a in (x, y, ground))
    L = layout(pad_bounds)
    cx, cy, d = nearest_flat(x, y, pad_bounds)             # nearest point on the graded area
    t = np.clip((cx - L["xw"]) / (L["xe"] - L["xw"]), 0.0, 1.0)
    edge = T + (E - T) * t                                  # lake terrace -> back yard
    # Boat-door ramp along the north side: level with the floor up to the door, then up.
    ramp = (cy > L["y1"]) & (cx < L["xe"])
    door_x = L["xw"] + BOAT_DOOR[1] + 0.6
    tr = np.clip((cx - door_x) / (L["xe"] - door_x), 0.0, 1.0)
    edge = np.where(ramp, T + (E - T) * tr, edge)
    house = (cx >= L["xw"]) & (cx <= L["xe"]) & (cy >= L["y0"]) & (cy <= L["y1"])
    edge = np.where(house, T, edge)                         # terrace slab
    for b0, b1, b2, b3, level in terraces or ():           # garden / orchard terraces
        qx, qy = np.clip(x, b0, b2), np.clip(y, b1, b3)
        dq = np.hypot(x - qx, y - qy)
        use = dq < d
        edge = np.where(use, level, edge)
        d = np.where(use, dq, d)
    out = np.where(ground > edge, np.minimum(ground, edge + d / CUT_SLOPE),
                   np.maximum(ground, edge - d / FILL_SLOPE))
    return np.where(d == 0, edge, out)
