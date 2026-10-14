"""Decode NAIP 2024 (Fannin County MrSID mosaic) onto the same grids as the 2022 products.

The TxGIO county mosaic (NAD83 / UTM 14N, MrSID MG4, bands R, G, B, NIR, mask) is
downloaded by the owner into inputs/downloads/ (the host refuses scripted clients) and
decoded with LizardTech's MrSID Decode SDK `mrsiddecode` from the same folder. Each
product is decoded over a window covering the target, then warped to EPSG:6344 on the
exact grid of the matching naip_* product, so the two vintages are interchangeable.

Adds the products to imagery.lock.json and points "use" at them.
Usage: python3 scripts/decode_naip2024.py
"""

import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOWNLOADS = ROOT / "inputs/downloads"
ZIP = DOWNLOADS / "naip24-60cm_48147_nccir-ccm.zip"
SID = DOWNLOADS / "naip2024/naip24-nc-cir-60cm-fannin_48147.sid"
DECODER = DOWNLOADS / ("mrsid_sdk/MrSID_DSDK-9.5.5.5244-darwin22.universal.clang140/"
                       "Raster_DSDK/bin/mrsiddecode")
SOURCE_URL = ("https://data.geographic.texas.gov/7e795b90-d89d-42a0-8bc9-4a7ef9b99e93/"
              "resources/naip24-60cm_48147_nccir-ccm.zip")
LOCK = ROOT / "imagery.lock.json"
SID_CRS = "EPSG:26914"  # NAD83 / UTM 14N, per the mosaic's .aux
ACQUIRED = "2024-07-03"  # seamline IDATE at the site (naip24-60cm-seamlines_48)
# 2024 product: (2022 product whose grid it copies, MrSID scale: 0 = 0.6 m, 2 = 2.4 m)
PRODUCTS = {"naip2024_site_0p6m": ("naip_site_0p6m", 0),
            "naip2024_regional_3m": ("naip_regional_3m", 2)}


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 24), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run(*args):
    subprocess.run([str(a) for a in args], check=True)


def utm14_window(corners_6344, margin):
    out = subprocess.run(["gdaltransform", "-s_srs", "EPSG:6344", "-t_srs", SID_CRS],
                         input="\n".join(f"{x} {y}" for x, y in corners_6344),
                         capture_output=True, text=True, check=True).stdout.split("\n")
    pts = [tuple(map(float, line.split()[:2])) for line in out if line.strip()]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return min(xs) - margin, max(ys) + margin, max(xs) + margin, min(ys) - margin


def main():
    for path in (ZIP, SID, DECODER):
        if not path.is_file():
            print(f"missing {path}", file=sys.stderr)
            return 1
    lock = json.loads(LOCK.read_text())
    origin = json.loads((ROOT / "inputs/terrain/origin.json").read_text())["origin"]
    e0, n0 = origin["easting"], origin["northing"]
    zip_sha, sid_sha = sha256(ZIP), sha256(SID)

    with tempfile.TemporaryDirectory() as scratch:
        for name, (template, scale) in PRODUCTS.items():
            ref = lock["products"][template]
            xmin, _, _, ymax = ref["bbox_local_m"]
            cell = ref["cell_m"]
            width, height = ref["size_px"]
            te = (xmin + e0, ymax - height * cell + n0, xmin + width * cell + e0, ymax + n0)
            ulx, uly, lrx, lry = utm14_window(
                [(te[0], te[1]), (te[0], te[3]), (te[2], te[1]), (te[2], te[3])], 50.0)
            decoded = Path(scratch) / f"{name}_utm14.tif"
            run(DECODER, "-quiet", "-i", SID, "-o", decoded, "-of", "tifg", "-coord", "geo",
                "-ulxy", ulx, uly, "-lrxy", lrx, lry, "-s", scale)
            target = ROOT / "inputs/imagery" / f"{name}.tif"
            # Bands 1-4 are R, G, B, NIR; band 5 is the coverage mask.
            run("gdalwarp", "-q", "-overwrite", "-s_srs", SID_CRS, "-t_srs", "EPSG:6344",
                "-te", *te, "-ts", width, height, "-r", "cubic" if scale == 0 else "average",
                "-b", 1, "-b", 2, "-b", 3, "-b", 4, "-nosrcalpha",
                "-co", "COMPRESS=DEFLATE", "-co", "TILED=YES", decoded, target)
            mask = Path(scratch) / f"{name}_mask.tif"
            run("gdalwarp", "-q", "-overwrite", "-s_srs", SID_CRS, "-t_srs", "EPSG:6344",
                "-te", *te, "-ts", width, height, "-r", "near", "-b", 5, decoded, mask)
            stats = subprocess.run(["gdalinfo", "-stats", str(mask)], capture_output=True,
                                   text=True, check=True).stdout
            minimum = float(stats.split("STATISTICS_MINIMUM=")[1].split()[0])
            if minimum < 255:
                print(f"{name}: mosaic does not cover the whole window", file=sys.stderr)
                return 1
            lock["products"][name] = {
                "file": str(target.relative_to(ROOT)), "sha256": sha256(target),
                "bbox_local_m": ref["bbox_local_m"], "cell_m": cell, "size_px": [width, height],
                "bands": ["red", "green", "blue", "nir"],
                "source": {"url": SOURCE_URL, "zip_sha256": zip_sha,
                           "sid": SID.name, "sid_sha256": sid_sha, "crs": SID_CRS,
                           "decoder": "LizardTech MrSID Decode SDK 9.5.5.5244 mrsiddecode",
                           "mrsid_scale": scale},
                "source_scenes": [{"name": "naip24-nc-cir-60cm-fannin_48147",
                                   "year": 2024, "acquisition_date": ACQUIRED,
                                   "resolution_m": 0.6}],
            }
            print(f"{name}: {width}x{height} px from MrSID scale {scale}")
    lock["use"] = {"site": "naip2024_site_0p6m", "regional": "naip2024_regional_3m"}
    LOCK.write_text(json.dumps(lock, indent=2) + "\n")
    print(f"updated {LOCK.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
