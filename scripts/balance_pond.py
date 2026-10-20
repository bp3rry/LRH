"""Size the pond to supply just the fill the lots need (owner, 20 Oct 2026: no dirt is
bought, and no more is dug than needed). Bisects the pond's target area until the
earthwork balance's usable supply covers demand with at most MARGIN to spare, then writes
out/derived/pond_target.json and re-runs build_sites, drainage, planting and earthwork.

Usage (Blender's Python): python3.11 scripts/balance_pond.py
"""

import contextlib
import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT / ".blender-site"))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts/blender"))

import build_sites  # noqa: E402
import drainage  # noqa: E402
import earthwork  # noqa: E402
import planting_plan  # noqa: E402

DERIVED = ROOT / "out/derived"
MARGIN = 0.03          # supply may exceed demand by at most 3% (shrink is an estimate)


def balance(target):
    drainage.POND_TARGET_AC = target
    with contextlib.redirect_stdout(io.StringIO()):
        drainage.main()
        earthwork.main()
    e = json.loads((DERIVED / "earthwork.json").read_text())
    return e["supply_usable_cu_yd"], e["demand_net_fill_cu_yd"], \
        json.loads((DERIVED / "drainage.json").read_text())["pond"]["area_ac"]


def main():
    lo, hi = 0.08, 0.9
    for _ in range(14):
        mid = (lo + hi) / 2
        supply, demand, area = balance(mid)
        print(f"target {mid:.3f} ac -> pond {area:.2f} ac, supply {supply}, demand {demand}")
        if supply < demand:
            lo = mid
        elif supply > demand * (1 + MARGIN):
            hi = mid
        else:
            break
    if supply < demand:
        mid = hi
    (DERIVED / "pond_target.json").write_text(json.dumps({"target_ac": round(mid, 4),
                                                          "margin": MARGIN}) + "\n")
    drainage.POND_TARGET_AC = mid
    with contextlib.redirect_stdout(io.StringIO()):
        build_sites.main() if hasattr(build_sites, "main") else build_sites.analyse()
        drainage.main()
        planting_plan.main()
        earthwork.main()
    supply, demand, area = (json.loads((DERIVED / "earthwork.json").read_text())["supply_usable_cu_yd"],
                            json.loads((DERIVED / "earthwork.json").read_text())["demand_net_fill_cu_yd"],
                            json.loads((DERIVED / "drainage.json").read_text())["pond"]["area_ac"])
    print(f"FINAL pond {area:.2f} ac: supply {supply} cu yd vs demand {demand} cu yd")


if __name__ == "__main__":
    main()
