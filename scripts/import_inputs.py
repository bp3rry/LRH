"""Copy LRH source inputs from the sibling projects into inputs/ and pin them.

Writes inputs.lock.json with each file's source path, SHA-256 and size, plus the
source repositories' commit and dirty state. Fails if any input is missing, or if
the copied files disagree with the hashes recorded inside the PTM run outputs
(origin.json and the site-review context), so a mixed set of runs cannot be imported.

Usage: python3 scripts/import_inputs.py
"""

import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROJECTS = ROOT.parent
PTM = PROJECTS / "property-terrain-modeling-pipeline"
LADONIA = PROJECTS / "Ladonia"
INPUTS = ROOT / "inputs"
LOCK = ROOT / "inputs.lock.json"

# (destination relative to inputs/, source path)
FILES = [
    ("terrain/terrain_design.obj", PTM / "out/terrain_design.obj"),
    ("terrain/terrain_site.tif", PTM / "out/terrain_site.tif"),
    ("terrain/origin.json", PTM / "out/origin.json"),
    ("context/site-review-context-regional.json", PTM / "out/site-review-context-regional.json"),
    ("geometry/lake-ralph-hall-50m-terrain-551ft-reference.dae",
     PTM / "properties/ladonia/geometry/lake-ralph-hall-50m-terrain-551ft-reference.dae"),
    ("geometry/parcel.geojson", PTM / "properties/ladonia/geometry/parcel.geojson"),
    ("geometry/txdot-fannin-cr-3635-epsg6344.geojson",
     PTM / "properties/ladonia/geometry/txdot-fannin-cr-3635-epsg6344.geojson"),
    ("geometry/txdot-sh34-crossing-segment-epsg6344.geojson",
     PTM / "properties/ladonia/geometry/txdot-sh34-crossing-segment-epsg6344.geojson"),
    ("reference/drone-ladonia-arial-1.jpeg", PTM / "properties/ladonia/Sketchup/Ladonia Arial 1.jpeg"),
    ("reference/ptm-drone-photo-registration.png",
     PTM / "out/handoff/CURRENT-DRONE-PHOTO-PREVIEW.png"),
    ("reference/lsmp-comment-draft-2025-10-16.pdf",
     LADONIA / "Reference/Lake-Ralph-Hall/COMMENT-DRAFT_Lake-Ralph-Hall-LSMP_October-16-2025.pdf"),
    ("geometry/cr3640-composite-context-route-epsg6344.geojson",
     LADONIA / "Reference/Spatial-Control/cr3640-composite-context-route-epsg6344.geojson"),
    ("geometry/txdot-fannin-sh34-roadway-inventory-epsg6344.geojson",
     LADONIA / "Reference/Spatial-Control/txdot-fannin-sh34-roadway-inventory-epsg6344.geojson"),
    ("geometry/utrwd-road-plan-cr3640-new-alignment-epsg6344.geojson",
     LADONIA / "Reference/Spatial-Control/utrwd-road-plan-cr3640-new-alignment-epsg6344.geojson"),
    ("reference/benchmark-cam02-sunset.jpg",
     PTM / "properties/ladonia/Sketchup/444-perry_lakehouse_exterior_cam_02.jpg"),
    ("reference/benchmark-cam03-oblique.jpg",
     PTM / "properties/ladonia/Sketchup/444-perry_lakehouse_exterior_cam_03 (1).jpg"),
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def repo_state(path: Path) -> dict:
    def git(*args):
        return subprocess.run(["git", "-C", str(path), *args], capture_output=True,
                              text=True, check=True).stdout.strip()
    return {"path": str(path), "head": git("rev-parse", "HEAD"),
            "dirty": bool(git("status", "--porcelain"))}


def main() -> int:
    missing = [str(src) for _, src in FILES if not src.is_file()]
    if missing:
        print("Missing inputs:\n  " + "\n  ".join(missing), file=sys.stderr)
        return 1

    entries = {}
    for dest, src in FILES:
        target = INPUTS / dest
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, target)
        digest = sha256(target)
        if digest != sha256(src):
            print(f"Copy mismatch for {src}", file=sys.stderr)
            return 1
        entries[dest] = {"source": str(src), "sha256": digest, "bytes": target.stat().st_size}

    # The PTM run outputs record the hashes of their own siblings; they must agree.
    origin = json.loads((INPUTS / "terrain/origin.json").read_text())
    context = json.loads((INPUTS / "context/site-review-context-regional.json").read_text())
    checks = [
        ("origin.json → terrain_design.obj", origin["artifact_sha256"]["terrain_design.obj"],
         entries["terrain/terrain_design.obj"]["sha256"]),
        ("context → origin.json", context["source_sha256"]["origin.json"],
         entries["terrain/origin.json"]["sha256"]),
        ("context → terrain_site.tif", context["source_sha256"]["terrain_site.tif"],
         entries["terrain/terrain_site.tif"]["sha256"]),
    ]
    failures = [name for name, recorded, actual in checks if recorded != actual]
    for name, recorded, actual in checks:
        print(f"{'PASS' if recorded == actual else 'FAIL'}  {name}")
    if failures:
        print("Inputs come from different PTM runs; rerun PTM before importing.", file=sys.stderr)
        return 1

    lock = {
        "schema": "lrh.inputs-lock/1",
        "imported_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sources": {"ptm": repo_state(PTM), "ladonia": repo_state(LADONIA)},
        "consistency_checks": [name for name, _, _ in checks],
        "files": entries,
    }
    LOCK.write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")
    print(f"Imported {len(entries)} files; wrote {LOCK.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
