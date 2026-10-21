"""Lake-front amenities (owner, 20 Oct 2026): each lot's shoreline circle becomes a small
sand beach with an umbrella, picnic table, chairs, a canoe and kayaks (`Beach`); the
paired boat docks get LSMP shoreline protection and moored boats (`Docks`).

Draft LSMP (16 Oct 2025) requirements applied to the docks (lotplan.dock_layout already
enforces length, spacing and cove width):
- boat docks 10-120 ft from the 551 ft shoreline, at most 1/3 of the cove width, 300 ft
  between docks, slips in at least 3 ft of water at conservation pool;
- walkway and fingers 3-6 ft wide; gangway perpendicular to the shoreline;
- composite or recycled-plastic decking, galvanised or aluminium framing, muted natural
  colours;
- at least 10 ft of permanent, non-vertical shoreline protection (riprap) on each side of
  every dock - modelled here as a riprap apron 10 ft past each side of the gangway, from
  just above to just below the waterline.
"""

import math
import random

import bpy
import numpy as np

import cabins
import frontage
import lrh

import shapely  # noqa: E402
from shapely.geometry import LineString, Point  # noqa: E402

FT = 0.3048
BEACH_R = 8.5


def sand():
    return cabins._speckled("Beach_Sand", (0.42, 0.34, 0.22), (0.62, 0.52, 0.36), 140.0, 0.003)


def to_water(c, water):
    """Unit vector from point c toward open water (mean of probe directions in water)."""
    acc = np.zeros(2)
    for a in np.linspace(0, 2 * math.pi, 48, endpoint=False):
        u = np.array([math.cos(a), math.sin(a)])
        if water.contains(Point(c[0] + u[0] * 14, c[1] + u[1] * 14)):
            acc += u
    n = np.linalg.norm(acc)
    return acc / n if n else np.array([-1.0, 0.0])


def umbrella(m, x, y, z, rng, colour):
    pole = cabins.plain("Beach_Pole", (0.6, 0.6, 0.6), 0.3, 0.8)
    m.cylinder(x, y, z, z + 2.3, 0.025, pole, n=8)
    canopy = cabins.plain(f"Beach_Umbrella_{colour[0]:.2f}", colour, 0.7)
    m.cylinder(x, y, z + 1.95, z + 2.4, 1.15, canopy, n=16, r_top=0.05)


def picnic_table(m, x, y, z, ang, wood):
    ux, uy = math.cos(ang), math.sin(ang)
    vx, vy = -uy, ux

    def plank(a0, a1, b, h, w=0.28, t=0.05):
        m.beam((x + ux * a0 + vx * b, y + uy * a0 + vy * b, z + h),
               (x + ux * a1 + vx * b, y + uy * a1 + vy * b, z + h), w, t, wood)
    for b in (-0.3, 0.0, 0.3):
        plank(-0.95, 0.95, b, 0.76)                                   # top
    for b in (-0.72, 0.72):
        plank(-0.95, 0.95, b, 0.45, 0.25)                             # benches
    for a in (-0.7, 0.7):
        for s in (-1, 1):
            m.beam((x + ux * a + vx * 0.7 * s, y + uy * a + vy * 0.7 * s, z),
                   (x + ux * a, y + uy * a, z + 0.76), 0.08, 0.08, wood)


def hull(m, x, y, z, ang, length, beam_w, depth, mat, deck_mat=None, taper=0.35):
    """A simple boat hull: tapered at the bow, flat stern; +u is the bow."""
    ux, uy = math.cos(ang), math.sin(ang)
    vx, vy = -uy, ux

    def p(a, b, h):
        return (x + ux * a + vx * b, y + uy * a + vy * b, z + h)
    L, W = length / 2, beam_w / 2
    m.hexa([p(-L, -W * 0.8, 0), p(L * 0.8, -W * taper, 0.05), p(L * 0.8, W * taper, 0.05), p(-L, W * 0.8, 0),
            p(-L, -W, depth), p(L, -0.05, depth + 0.1), p(L, 0.05, depth + 0.1), p(-L, W, depth)], mat)
    if deck_mat is not None:
        m.hexa([p(-L + 0.1, -W + 0.1, depth), p(L * 0.7, -W * 0.5, depth + 0.05), p(L * 0.7, W * 0.5, depth + 0.05),
                p(-L + 0.1, W - 0.1, depth), p(-L + 0.1, -W + 0.1, depth + 0.04),
                p(L * 0.7, -W * 0.5, depth + 0.09), p(L * 0.7, W * 0.5, depth + 0.09),
                p(-L + 0.1, W - 0.1, depth + 0.04)], deck_mat)


def ski_boat(m, x, y, z, ang):
    white = cabins.plain("Boat_Gelcoat", (0.75, 0.75, 0.73), 0.25)
    stripe = cabins.plain("Boat_Stripe_Navy", (0.03, 0.06, 0.15), 0.3)
    seat = cabins.plain("Boat_Upholstery", (0.55, 0.50, 0.42), 0.6)
    hull(m, x, y, z - 0.2, ang, 6.4, 2.4, 0.9, white, seat)
    ux, uy = math.cos(ang), math.sin(ang)
    vx, vy = -uy, ux
    for s in (-1, 1):
        m.beam((x - ux * 3.1 + vx * 1.21 * s, y - uy * 3.1 + vy * 1.21 * s, z + 0.45),
               (x + ux * 2.4 + vx * 0.6 * s, y + uy * 2.4 + vy * 0.6 * s, z + 0.5), 0.05, 0.22, stripe)
    glass = cabins.plain("Boat_Windscreen", (0.1, 0.12, 0.14), 0.05)
    m.beam((x + ux * 0.6 - vx * 1.0, y + uy * 0.6 - vy * 1.0, z + 0.95),
           (x + ux * 0.6 + vx * 1.0, y + uy * 0.6 + vy * 1.0, z + 0.95), 0.05, 0.35, glass)


def pontoon(m, x, y, z, ang):
    tube = cabins.plain("Pontoon_Tube", (0.62, 0.63, 0.64), 0.3, 0.9)
    deck = cabins.plain("Pontoon_Deck", (0.20, 0.18, 0.16), 0.8)
    fence = cabins.plain("Pontoon_Fence", (0.32, 0.33, 0.35), 0.4, 0.6)
    seat = cabins.plain("Boat_Upholstery", (0.55, 0.50, 0.42), 0.6)
    ux, uy = math.cos(ang), math.sin(ang)
    vx, vy = -uy, ux
    for s in (-0.9, 0.9):
        m.beam((x - ux * 3.2 + vx * s, y - uy * 3.2 + vy * s, z + 0.05),
               (x + ux * 3.2 + vx * s, y + uy * 3.2 + vy * s, z + 0.05), 0.55, 0.55, tube)
    m.beam((x - ux * 3.3, y - uy * 3.3, z + 0.45), (x + ux * 3.3, y + uy * 3.3, z + 0.45), 2.5, 0.08, deck)
    for s in (-1.2, 1.2):
        m.beam((x - ux * 3.2 + vx * s, y - uy * 3.2 + vy * s, z + 0.75),
               (x + ux * 2.6 + vx * s, y + uy * 2.6 + vy * s, z + 0.75), 0.06, 0.6, fence)
    for a in (-2.0, 0.6):
        m.beam((x + ux * a - vx * 0.9, y + uy * a - vy * 0.9, z + 0.75),
               (x + ux * a + vx * 0.9, y + uy * a + vy * 0.9, z + 0.75), 0.6, 0.45, seat)


def paddle_craft(m, x, y, z, ang, length, width, colour, name):
    mat = cabins.plain(name, colour, 0.35)
    ux, uy = math.cos(ang), math.sin(ang)
    n = 9
    for k in range(n):
        t0, t1 = -1 + 2 * k / n, -1 + 2 * (k + 1) / n
        w = width * math.cos(t0 * math.pi / 2.2) / 2
        a0, a1 = t0 * length / 2, t1 * length / 2
        m.beam((x + ux * a0, y + uy * a0, z + 0.12), (x + ux * a1, y + uy * a1, z + 0.12),
               max(0.08, 2 * w), 0.22, mat)


def beach(m, label, c, water, sampler, rng):
    u = to_water(c, water)
    v = np.array([-u[1], u[0]])
    poly = shapely.union_all([Point(c).buffer(BEACH_R),
                              LineString([tuple(c), tuple(np.array(c) + u * 18.0)]).buffer(7.0)])
    frontage.draped(m, poly, lambda x, y: sampler(x, y), sand(), 0.07)
    z = lambda p: (sampler(p[0], p[1]) or lrh.POOL_M) + 0.07
    ang = math.atan2(u[1], u[0])
    wood = cabins.timber()
    p_um = np.array(c) - u * 1.5 + v * 3.0
    umbrella(m, *p_um, z(p_um), rng, rng.choice([(0.55, 0.08, 0.05), (0.05, 0.25, 0.45), (0.85, 0.65, 0.2)]))
    for s in (-1, 1):                                                # chairs facing the lake
        q = np.array(c) + u * 0.5 + v * (2.4 + 0.9 * s)
        cabins.chair(m, *q, z(q), (90 - math.degrees(ang)) % 360, wood)
    p_t = np.array(c) - u * 4.0 - v * 2.5
    picnic_table(m, *p_t, z(p_t), ang + math.pi / 2, wood)
    p_c = np.array(c) + u * 2.5 - v * 4.2                            # canoe pulled up, two kayaks
    paddle_craft(m, *p_c, z(p_c), ang + 0.2, 4.9, 0.85, (0.45, 0.10, 0.06), "Canoe_Red")
    for k, col in enumerate(((0.85, 0.65, 0.05), (0.05, 0.35, 0.30))):
        p_k = np.array(c) + u * (1.2 - k * 1.1) - v * (6.0 + k * 0.4)
        paddle_craft(m, *p_k, z(p_k), ang + 0.35, 3.6, 0.65, col, f"Kayak_{k}")
    return poly


def riprap(m, base, d, sampler, rng, half_dock=1.0):
    """Riprap 10 ft past each side of the gangway, along the shoreline at the dock base."""
    rock = cabins.plain("Riprap_Stone", (0.40, 0.38, 0.35), 0.9)
    rock2 = cabins.stone()
    u = np.array(d)
    v = np.array([-u[1], u[0]])
    reach = half_dock + 10 * FT + 0.5
    for _ in range(170):
        a = rng.uniform(-reach, reach)
        b = rng.uniform(-1.5, 1.6)                                  # landward .. waterward
        p = np.array(base) + v * a + u * b
        g = sampler(*p) or lrh.POOL_M
        s = rng.uniform(0.18, 0.42)
        m.blob(p[0], p[1], max(g, lrh.POOL_M - 0.5) + s * 0.25, s, s * rng.uniform(0.7, 1.0), s * 0.6,
               rock if rng.random() < 0.6 else rock2, seg=7, rings=5, rng=rng)


def build(beach_coll, docks_coll, shore_access, docks, water, sampler, record):
    rng = random.Random(2010)
    areas = {}
    for label, a in sorted(shore_access.items()):
        c = np.array(a["circle"], float)
        for d in docks:                       # keep the beach clear of a dock's riprap
            off = c - np.array(d["base"])
            dist = float(np.linalg.norm(off))
            if dist < 17.0:
                u = to_water(c, water)
                v = np.array([-u[1], u[0]])
                side = 1.0 if float(np.dot(off, v)) >= 0 else -1.0
                c = c + v * side * (17.0 - dist + 1.0)
        m = cabins.Mesh()
        areas[label] = beach(m, label, tuple(c), water, sampler, rng)
        m.object(f"Beach_{label.replace(' ', '_')}", beach_coll)
    d_mesh = cabins.Mesh()
    boats = 0
    for i, d in enumerate(docks):
        riprap(d_mesh, d["base"], d["dir"], sampler, rng)
        ang = math.atan2(d["dir"][1], d["dir"][0])
        u = np.array(d["dir"])
        v = np.array([-u[1], u[0]])
        head = 10.0
        walk_end = max(4.0, d["length"] - head)
        slip_x = (walk_end + 1.2 + d["length"]) / 2
        for k, side in enumerate((-2.4, 2.4)):                     # one boat per slip
            p = np.array(d["base"]) + u * slip_x + v * side
            if (i + k) % 2 == 0:
                ski_boat(d_mesh, *p, lrh.POOL_M, ang)
            else:
                pontoon(d_mesh, *p, lrh.POOL_M, ang)
            boats += 1
        p = np.array(d["base"]) + u * (walk_end - 2.0) + v * 0.2     # kayak on the walkway
        paddle_craft(d_mesh, *p, lrh.POOL_M + 0.55, ang, 3.6, 0.65, (0.85, 0.65, 0.05), "Kayak_0")
    d_mesh.object("Dock_Riprap_Boats", docks_coll)
    record("beaches_docks", True, beaches=len(areas), docks=len(docks), moored_boats=boats,
           riprap_each_side_ft=10, basis="draft LSMP 16 Oct 2025, sec. 4.1.3, 6.2-6.3, App. D")
    return areas
