"""Marketing cut of the permit5 flyover (owner, 24 Nov 2026): the main marketing video.

The owner approved the first 90 s of the low flight (the for-sale sign at the CR 3635 /
CR 3640 corner, the climb west along CR 3640, and the hover over the creek arm looking
north-east at the property with the lot lines in) as the main marketing video, focused on
the two listed lots: the southern 5 ac (Lot D, to be subdivided into two ~2.5 ac lots)
and the 5 ac lot next to it (Lot C). This cut ends in that hover:
- frames 0 to CUT-1 are out/derived/flight_low.json's poses unchanged;
- from CUT the camera and look-at keep their velocity at CUT, decaying with time constant
  TAU_S, so the drone eases to a near-stop with no jolt;
- the Lot D subdivision line draws in from the lake-side end over SPLIT_S seconds
  starting at SPLIT_START, then holds to the last frame (flyover.SplitReveal);
- the lot lines fade in as in the full flight (before H1) and hold to the last frame.

Writes out/derived/flight_marketing.json in flight_low.json's schema, with benchmarks
SIGN, T0, H1, H2 (= last frame: the lot lines hold to the end), SPLIT_START, SPLIT_END.
Render: LRH_FLIGHT=out/derived/flight_marketing.json, flyover.py -- --variant low
--scene permit5 --cut marketing [--preview].

Usage: python3 scripts/flight_marketing.py
"""

import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FPS = 30
CUT = 2700                     # 90.0 s: lot lines fully in (H1 at 2641)
TAU_S = 3.0
SPLIT_START, SPLIT_S = 2730, 4.0
END = 2970                     # 99.0 s: about 4 s held on the drawn split
MIN_AGL_M = 15.0
GROUND_MAX_M = 190.0           # highest ground under the hover (site ~185 m)


def main():
    src = json.loads((ROOT / "out/derived/flight_low.json").read_text())
    if not src["checks"]["passed"]:
        raise SystemExit("FAIL flight_low.json failed its checks")
    bench = src["benchmarks"]
    if not bench["H1"] < CUT < bench["H2"]:
        raise SystemExit(f"FAIL cut {CUT} is not inside the H1-H2 hover {bench['H1']}-{bench['H2']}")
    poses = [list(map(list, p)) for p in src["poses"][:CUT]]
    (c1, l1), (c0, l0) = src["poses"][CUT - 1], src["poses"][CUT - 2]
    vc = [a - b for a, b in zip(c1, c0)]
    vl = [a - b for a, b in zip(l1, l0)]
    cam, look = list(c1), list(l1)
    for k in range(1, END - CUT + 1):
        decay = math.exp(-k / (TAU_S * FPS))
        cam = [p + v * decay for p, v in zip(cam, vc)]
        look = [p + v * decay for p, v in zip(look, vl)]
        poses.append([cam, look])
    tail = poses[CUT:]
    low = min(c[2] for c, _ in tail)
    if low - GROUND_MAX_M < MIN_AGL_M:
        raise SystemExit(f"FAIL hover extension drops to {low:.1f} m")
    end_speed = math.dist(tail[-1][0], tail[-2][0]) * FPS
    checks = dict(src["checks"])
    checks.update({"marketing_cut_frame": CUT, "extension_min_z_m": round(low, 1),
                   "extension_end_speed_ms": round(end_speed, 3)})
    out = {"schema": src["schema"], "fps": FPS, "frames": len(poses), "seconds": len(poses) / FPS,
           "source": "out/derived/flight_low.json", "keys": src["keys"],
           "benchmarks": {"SIGN": bench["SIGN"], "T0": bench["T0"], "H1": bench["H1"], "H2": len(poses) - 1,
                          "SPLIT_START": SPLIT_START, "SPLIT_END": SPLIT_START + int(SPLIT_S * FPS)},
           "main_start": src["main_start"], "checks": checks, "poses": poses}
    (ROOT / "out/derived/flight_marketing.json").write_text(json.dumps(out))
    print(f"flight_marketing.json: {len(poses)} frames ({len(poses) / FPS:.1f} s), cut at {CUT}, "
          f"split {SPLIT_START}-{out['benchmarks']['SPLIT_END']}, end speed {end_speed:.2f} m/s")


if __name__ == "__main__":
    main()
