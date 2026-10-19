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


def layout(pad_bounds):
    """House lines in local metres from the pad rectangle (x0, y0, x1, y1)."""
    x0, y0, x1, y1 = pad_bounds
    xe = x1 - EAST_MARGIN
    xw = xe - BODY[0]
    ys = y0 + SOUTH_MARGIN
    yb0 = ys + SOUTH_PORCH
    yb1 = yb0 + BODY[1]
    return {"xw": xw, "xe": xe, "y0": yb0, "y1": yb1, "xp": xw - GABLE_PORCH,
            "ys": ys, "yn": yb1 + NORTH_PORCH}


def design(x, y, ground, pad_bounds, T, E):
    """Finished grade at points (x, y) given natural `ground` there (arrays)."""
    x, y, ground = (np.asarray(a, float) for a in (x, y, ground))
    L = layout(pad_bounds)
    x0, y0, x1, y1 = pad_bounds
    cx, cy = np.clip(x, x0, x1), np.clip(y, y0, y1)        # nearest point on the pad
    t = np.clip((cx - L["xw"]) / (L["xe"] - L["xw"]), 0.0, 1.0)
    edge = T + (E - T) * t                                  # lake terrace -> back yard
    # Boat-door ramp along the north side: level with the floor up to the door, then up.
    ramp = (cy > L["y1"]) & (cx < L["xe"])
    door_x = L["xw"] + BOAT_DOOR[1] + 0.6
    tr = np.clip((cx - door_x) / (L["xe"] - door_x), 0.0, 1.0)
    edge = np.where(ramp, T + (E - T) * tr, edge)
    house = (cx >= L["xw"]) & (cx <= L["xe"]) & (cy >= L["y0"]) & (cy <= L["y1"])
    edge = np.where(house, T, edge)                         # terrace slab
    d = np.hypot(x - cx, y - cy)
    out = np.where(ground > edge, np.minimum(ground, edge + d / CUT_SLOPE),
                   np.maximum(ground, edge - d / FILL_SLOPE))
    return np.where(d == 0, edge, out)
