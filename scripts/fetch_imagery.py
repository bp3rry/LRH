"""Fetch NAIP orthoimagery for the site and region into inputs/imagery/ and pin it.

Source: USGS The National Map NAIP ImageServer (public domain; 4-band R, G, B, NIR).
Writes imagery.lock.json (committed) with each request, the NAIP source scenes and
their acquisition dates, and the SHA-256 of every file written.

Usage: python3 scripts/fetch_imagery.py
"""

import hashlib
import json
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "inputs/imagery"
LOCK = ROOT / "imagery.lock.json"
SERVICE = "https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPImagery/ImageServer"
MAX_PX = 2000  # service maximum is 4000, but large resampled tiles time out (502)
ORIGIN = json.loads((ROOT / "inputs/terrain/origin.json").read_text())["origin"]
E0, N0 = ORIGIN["easting"], ORIGIN["northing"]

# name: (local bbox xmin, ymin, xmax, ymax in LRH metres, cell size m)
PRODUCTS = {
    "naip_site_0p6m": ((-390.0, -480.0, 390.0, 550.0), 0.6),
    "naip_regional_3m": ((-15690.0, -2316.0, 2826.0, 8046.0), 3.0),
}


def get(url, params, attempts=4):
    full = f"{url}?{urllib.parse.urlencode(params)}"
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(full, timeout=300) as response:
                return response.read(), full
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as error:
            if attempt == attempts - 1:
                raise
            print(f"  retry after {error}", file=sys.stderr)
            time.sleep(10 * (attempt + 1))


def source_scenes(bbox):
    xmin, ymin, xmax, ymax = bbox
    body, _ = get(f"{SERVICE}/query", {
        "where": "1=1", "geometry": f"{xmin + E0},{ymin + N0},{xmax + E0},{ymax + N0}",
        "geometryType": "esriGeometryEnvelope", "inSR": 6344,
        "spatialRel": "esriSpatialRelIntersects", "outFields": "*",
        "returnGeometry": "false", "f": "json"})
    scenes = []
    for feature in json.loads(body).get("features", []):
        a = feature["attributes"]
        if a.get("Category") == 1:
            scenes.append({"name": a["Name"], "year": a.get("Year"),
                           "acquisition_date": datetime.fromtimestamp(
                               a["acquisition_date"] / 1000, timezone.utc).date().isoformat()
                           if a.get("acquisition_date") else None,
                           "resolution_m": a.get("resolution_value")})
    return sorted(scenes, key=lambda s: s["name"])


def fetch(name, bbox, cell, scratch):
    xmin, ymin, xmax, ymax = bbox
    width, height = round((xmax - xmin) / cell), round((ymax - ymin) / cell)
    tiles, requests = [], []
    for row, y0 in enumerate(range(0, height, MAX_PX)):
        for col, x0 in enumerate(range(0, width, MAX_PX)):
            w, h = min(MAX_PX, width - x0), min(MAX_PX, height - y0)
            tx0 = xmin + x0 * cell
            ty1 = ymax - y0 * cell
            tbbox = (tx0 + E0, ty1 - h * cell + N0, tx0 + w * cell + E0, ty1 + N0)
            body, url = get(f"{SERVICE}/exportImage", {
                "bbox": ",".join(f"{v:.3f}" for v in tbbox), "bboxSR": 6344, "imageSR": 6344,
                "size": f"{w},{h}", "format": "tiff", "pixelType": "U8",
                "interpolation": "RSP_BilinearInterpolation", "bandIds": "0,1,2,3", "f": "image"})
            if not body.startswith((b"II*", b"MM\x00*")):
                raise RuntimeError(f"{name} tile {row},{col}: not a TIFF: {body[:200]!r}")
            tile = scratch / f"{name}_{row}_{col}.tif"
            tile.write_bytes(body)
            tiles.append(tile)
            requests.append(url)
    target = OUT / f"{name}.tif"
    vrt = scratch / f"{name}.vrt"
    subprocess.run(["gdalbuildvrt", "-q", "-a_srs", "EPSG:6344", str(vrt), *map(str, tiles)],
                   check=True)
    subprocess.run(["gdal_translate", "-q", "-co", "COMPRESS=DEFLATE", "-co", "TILED=YES",
                    str(vrt), str(target)], check=True)
    return target, requests, (width, height)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    scratch = OUT / ".tiles"
    scratch.mkdir(exist_ok=True)
    entries = {}
    for name, (bbox, cell) in PRODUCTS.items():
        target, requests, size = fetch(name, bbox, cell, scratch)
        scenes = source_scenes(bbox)
        if not scenes:
            print(f"{name}: no NAIP source scenes reported", file=sys.stderr)
            return 1
        entries[name] = {
            "file": str(target.relative_to(ROOT)),
            "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
            "bbox_local_m": bbox, "cell_m": cell, "size_px": size,
            "bands": ["red", "green", "blue", "nir"],
            "requests": requests, "source_scenes": scenes,
        }
        years = sorted({s["year"] for s in scenes})
        print(f"{name}: {size[0]}x{size[1]} px, {len(scenes)} scenes, years {years}")
    for tile in scratch.iterdir():
        tile.unlink()
    scratch.rmdir()
    LOCK.write_text(json.dumps({
        "schema": "lrh.imagery-lock/1",
        "retrieved_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "service": SERVICE,
        "licence": "Public domain (USDA NAIP via USGS The National Map)",
        "crs": "EPSG:6344; bbox_local_m is relative to inputs/terrain/origin.json",
        "products": entries,
    }, indent=2) + "\n")
    print(f"wrote {LOCK.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
