"""Lake-view score per lot: how much of the lake-facing view is open water.

From each lot's conceptual house site (lot_sites.json from the build), at ground-floor
(1.7 m) and second-floor (5.0 m) eye height, rays are cast across the lake-facing sector
(azimuth 180-390 deg, i.e. south through west and north to NNE, 1 deg steps) at
depressions of 0.5-8 deg, through the built scene. Each first hit is classed as open
water, flooded timber (habitat-zone trees standing in the lake), woods/land trees, or
ground. The house clearing is assumed: hits within 25 m of the site are ignored.

Scores per lot, height and timber stage (dying = marketing default, snags = long term):
  open_water_share    share of all hits that are open water;
  open_azimuth_share  share of the 211 azimuths with at least one open-water sight line;
  timber_share        share of hits on flooded timber.
Optionally renders a 210-degree panorama per lot (5 m, dying) for the visual record.

Usage: Blender -b out/<date>/lrh_baseline.blend --python scripts/blender/lake_views.py [-- --panoramas]
"""

import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lrh  # noqa: E402
import render  # noqa: E402

EYE_HEIGHTS = {"ground_floor": 1.7, "second_floor": 5.0}
STAGES = {"dying": ["Flooded_Timber_Dying", "Spanish_Moss"],
          "snags": ["Flooded_Timber_Snags", "Spanish_Moss"]}
BASE = ["Terrain", "Water", "Roads", "Landmarks", "Vegetation", "Driveways", "Shoreline"]
AZIMUTHS = range(180, 391)
DEPRESSIONS = [0.5, 1.0, 1.5, 2.0, 3.0, 4.0, 6.0, 8.0]
CLEAR_RADIUS_M = 25.0


def classify(name):
    if name.startswith("Lake_"):
        return "water"
    if name.startswith("Flooded_"):
        return "timber"
    if name.startswith(("Trees_", "Tree_")):
        return "woods"
    return "ground"


def set_collections(wanted):
    for child in bpy.context.view_layer.layer_collection.children:
        child.exclude = child.name not in wanted


def cast(scene, dg, origin, direction):
    """First hit from the eye. Trees within the cleared house envelope are skipped by
    re-casting just beyond them; ground is never skipped."""
    start, travelled = origin, 0.0
    for _ in range(8):
        hit, loc, _, _, obj, _ = scene.ray_cast(dg, start, direction, distance=6000.0)
        if not hit:
            return None
        cls = classify(obj.name)
        travelled += (loc - start).length
        if cls == "woods" and travelled < CLEAR_RADIUS_M:
            start = loc + direction * 0.05
            continue
        return cls
    return None


def score(scene, sites):
    out = {}
    for stage, layers in STAGES.items():
        set_collections(BASE + layers)
        dg = bpy.context.evaluated_depsgraph_get()
        dg.update()
        for label, site in sites.items():
            x, y = site["house"]
            ground = scene.ray_cast(dg, Vector((x, y, 1000.0)), Vector((0, 0, -1)))[1].z
            for floor, eye in EYE_HEIGHTS.items():
                counts = {"water": 0, "timber": 0, "woods": 0, "ground": 0}
                blockers = {"timber": 0, "woods": 0, "ground": 0}
                open_az = 0
                for az in AZIMUTHS:
                    a = math.radians(az)
                    seen_water = False
                    for dep in DEPRESSIONS:
                        d = Vector((math.sin(a), math.cos(a), -math.tan(math.radians(dep)))).normalized()
                        cls = cast(scene, dg, Vector((x, y, ground + eye)), d)
                        if cls:
                            counts[cls] += 1
                            seen_water |= cls == "water"
                    open_az += seen_water
                    if not seen_water:
                        # What stops the most distant (shallowest) sight line here?
                        d = Vector((math.sin(a), math.cos(a), -math.tan(math.radians(DEPRESSIONS[0])))).normalized()
                        b = cast(scene, dg, Vector((x, y, ground + eye)), d)
                        if b in blockers:
                            blockers[b] += 1
                total = max(1, sum(counts.values()))
                out.setdefault(label, {}).setdefault(stage, {})[floor] = {
                    "open_water_share": round(counts["water"] / total, 3),
                    "open_azimuth_share": round(open_az / len(AZIMUTHS), 3),
                    "timber_share": round(counts["timber"] / total, 3),
                    "woods_share": round(counts["woods"] / total, 3),
                    "ground_share": round(counts["ground"] / total, 3),
                    "blocked_azimuths_by": {k: round(v / len(AZIMUTHS), 3) for k, v in blockers.items()}}
    return out


def panoramas(scene, sites, out_dir):
    set_collections(BASE + STAGES["dying"])
    render.configure_device(scene)
    render.configure_sky(scene, {"datetime": "2026-10-14T16:00", "utc_offset_h": -5})
    scene.render.use_compositing = False
    bpy.data.materials["Ground_Site"].node_tree.nodes["LRH_Cleared_Grassed"].outputs[0].default_value = 1.0
    cam = bpy.data.objects.new("LRH_LakeView", bpy.data.cameras.new("LRH_LakeView"))
    scene.collection.objects.link(cam)
    cam.data.type = "PANO"
    cam.data.panorama_type = "EQUIRECTANGULAR"
    cam.data.longitude_min, cam.data.longitude_max = math.radians(-105), math.radians(105)
    cam.data.latitude_min, cam.data.latitude_max = math.radians(-20), math.radians(12)
    cam.data.clip_end = 60000.0
    scene.camera = cam
    scene.render.resolution_x, scene.render.resolution_y = 2100, 320
    scene.cycles.samples = 48
    scene.view_settings.exposure = -4.0
    dg = bpy.context.evaluated_depsgraph_get()
    paths = []
    for label, site in sites.items():
        x, y = site["house"]
        ground = scene.ray_cast(dg, Vector((x, y, 1000.0)), Vector((0, 0, -1)))[1].z
        cam.location = (x, y, ground + EYE_HEIGHTS["second_floor"])
        # Equirect centre looks along -Z of the camera; aim the centre due west-north-west.
        heading = math.radians(285.0)
        cam.rotation_euler = (math.pi / 2, 0.0, -heading)  # centre of view = heading
        path = out_dir / f"lake_view_{label.replace(' ', '_')}.png"
        scene.render.filepath = str(path)
        bpy.ops.render.render(write_still=True)
        paths.append(path)
    return paths


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    out_dir = lrh.out_dir()
    sites = json.loads((Path(bpy.data.filepath).parent / "lot_sites.json").read_text())
    scene = bpy.context.scene
    if "--panoramas-only" in argv:
        for p in panoramas(scene, sites, out_dir):
            print("PANORAMA", p)
        return
    results = score(scene, sites)
    report = {"schema": "lrh.lake-views/1", "generated_utc": lrh.utc_now(), "git": lrh.git_commit(),
              "method": __doc__.split("\n\n")[1].replace("\n", " "), "lots": results}
    (out_dir / "lake_views.json").write_text(json.dumps(report, indent=1) + "\n")
    lines = ["| Lot | Open-water directions, 2nd floor (dying) | 2nd floor (snags) | Ground floor (dying) "
             "| Blocked by flooded timber | Blocked by shoreline woods | Blocked by ground |",
             "| --- | --- | --- | --- | --- | --- | --- |"]
    for label, r in results.items():
        s2, g = r["dying"]["second_floor"], r["dying"]["ground_floor"]
        b = s2["blocked_azimuths_by"]
        lines.append(f"| {label.split()[-1]} | {s2['open_azimuth_share']:.0%} "
                     f"| {r['snags']['second_floor']['open_azimuth_share']:.0%} "
                     f"| {g['open_azimuth_share']:.0%} | {b['timber']:.0%} | {b['woods']:.0%} "
                     f"| {b['ground']:.0%} |")
    (out_dir / "lake_views.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    if "--panoramas" in argv:
        for p in panoramas(scene, sites, out_dir):
            print("PANORAMA", p)


if __name__ == "__main__":
    main()
