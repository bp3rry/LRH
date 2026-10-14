"""Classify NAIP imagery into ground-cover masks for the Blender build.

Classes (uint8): 0 water, 1 bare/road, 2 pasture/grass, 3 woods. Woods are dense, dark
canopy (high NDVI, low brightness), smoothed so single dark pixels do not become trees.
Also writes tree_fraction (0-255, woods share in a ~6 m window) and greenness
(NDVI scaled 0-255) for shading. Thresholds were set from sampled patches of known
cover in the 2022 site image (woods NDVI ~0.51 / brightness ~65, pasture ~0.24 / ~90,
ponds ~-0.64) and are recorded in each output's metadata.

Outputs go to out/derived/ (build products; regenerate any time).
Usage: python3 scripts/classify_ground_cover.py
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
LOCK = json.loads((ROOT / "imagery.lock.json").read_text())
OUT = ROOT / "out/derived"

# Per imagery year: radiometry differs between NAIP vintages. 2024 samples: woods NDVI
# 0.37-0.44 / brightness ~75, pasture 0.22-0.30 / 77-102, ponds ~-0.48.
THRESHOLDS = {
    2022: {"water_ndvi_max": -0.30, "water_nir_max": 60,
           "woods_ndvi_min": 0.40, "woods_brightness_max": 82,
           "bare_ndvi_max": 0.02, "bare_brightness_min": 100, "woods_majority": 0.5},
    2024: {"water_ndvi_max": -0.25, "water_nir_max": 70,
           "woods_ndvi_min": 0.34, "woods_brightness_max": 85,
           "bare_ndvi_max": 0.08, "bare_brightness_min": 105, "woods_majority": 0.5},
}


def read(path, scratch):
    raw = Path(scratch) / (path.stem + ".bin")
    subprocess.run(["gdal_translate", "-q", "-of", "ENVI", "-co", "INTERLEAVE=BSQ",
                    str(path), str(raw)], check=True)
    info = json.loads(subprocess.run(["gdalinfo", "-json", str(path)], capture_output=True,
                                     text=True, check=True).stdout)
    width, height = info["size"]
    bands = np.fromfile(raw, np.uint8).reshape(len(info["bands"]), height, width)
    return bands.astype(np.float32), info["geoTransform"]


def box_mean(image, radius):
    """Mean over a (2r+1)^2 window, edges handled by clamped padding."""
    padded = np.pad(image, radius + 1, mode="edge").astype(np.float64)
    c = padded.cumsum(0).cumsum(1)
    k = 2 * radius + 1
    total = c[k:, k:] - c[:-k, k:] - c[k:, :-k] + c[:-k, :-k]
    return (total / (k * k))[:image.shape[0], :image.shape[1]].astype(np.float32)


def write(array, like_gt, path, metadata, scratch):
    raw = Path(scratch) / (path.stem + ".raw")
    array.astype(np.uint8).tofile(raw)
    height, width = array.shape
    (raw.with_suffix(".hdr")).write_text(
        f"ENVI\nsamples = {width}\nlines = {height}\nbands = 1\nheader offset = 0\n"
        "file type = ENVI Standard\ndata type = 1\ninterleave = bsq\nbyte order = 0\n")
    gt = like_gt
    subprocess.run(["gdal_translate", "-q", "-of", "GTiff", "-co", "COMPRESS=DEFLATE",
                    "-a_srs", "EPSG:6344",
                    "-a_ullr", str(gt[0]), str(gt[3]), str(gt[0] + gt[1] * width),
                    str(gt[3] + gt[5] * height),
                    *[arg for k, v in metadata.items() for arg in ("-mo", f"{k}={v}")],
                    str(raw), str(path)], check=True)


def classify(name, product, scratch):
    bands, gt = read(ROOT / product["file"], scratch)
    red, green, blue, nir = bands
    ndvi = (nir - red) / (nir + red + 1e-6)
    brightness = (red + green + blue) / 3
    cell = product["cell_m"]
    year = product["source_scenes"][0]["year"]
    t = THRESHOLDS[year]

    woods_raw = ((ndvi > t["woods_ndvi_min"]) & (brightness < t["woods_brightness_max"]))
    smooth_r = max(1, round(1.8 / cell))  # ~3.6 m window: a small tree crown
    woods = box_mean(woods_raw.astype(np.float32), smooth_r) > t["woods_majority"]
    water = (ndvi < t["water_ndvi_max"]) & (nir < t["water_nir_max"])
    bare = (ndvi < t["bare_ndvi_max"]) & (brightness > t["bare_brightness_min"])
    classes = np.full(ndvi.shape, 2, np.uint8)
    classes[bare] = 1
    classes[woods] = 3
    classes[water] = 0
    tree_fraction = box_mean(woods.astype(np.float32), max(1, round(3.0 / cell)))
    greenness = np.clip((ndvi + 0.1) / 0.7, 0, 1)

    meta = {"source": product["file"], "thresholds": json.dumps(t),
            "classes": "0 water,1 bare/road,2 pasture/grass,3 woods"}
    OUT.mkdir(parents=True, exist_ok=True)
    write(classes, gt, OUT / f"cover_{name}.tif", meta, scratch)
    write(np.round(tree_fraction * 255), gt, OUT / f"tree_fraction_{name}.tif", meta, scratch)
    write(np.round(greenness * 255), gt, OUT / f"greenness_{name}.tif", meta, scratch)
    shares = {label: round(float((classes == value).mean()), 4) for value, label in
              enumerate(["water", "bare", "pasture", "woods"])}
    # Content check: both landscapes are mixed pasture and woodland.
    if not (0.1 < shares["woods"] < 0.8 and shares["pasture"] > 0.1):
        print(f"{name}: implausible class shares {shares}", file=sys.stderr)
        sys.exit(1)
    preview = np.array([[90, 140, 200], [200, 190, 160], [170, 190, 110], [30, 80, 30]],
                       np.uint8)[classes]
    return shares, preview, gt, year


def main():
    report = {}
    with tempfile.TemporaryDirectory() as scratch:
        for name, product_name in LOCK["use"].items():  # site / regional
            product = LOCK["products"][product_name]
            shares, preview, gt, year = classify(name, product, scratch)
            raw = Path(scratch) / f"preview_{name}.rgb"
            preview.tofile(raw)
            h, w, _ = preview.shape
            (raw.with_suffix(".hdr")).write_text(
                f"ENVI\nsamples = {w}\nlines = {h}\nbands = 3\nheader offset = 0\n"
                "file type = ENVI Standard\ndata type = 1\ninterleave = bip\nbyte order = 0\n")
            subprocess.run(["gdal_translate", "-q", "-of", "PNG", str(raw),
                            str(OUT / f"cover_{name}_preview.png")], check=True)
            # 3-band copy for Blender (it would read the NIR band as alpha).
            rgb = OUT / f"naip_{name}_rgb.{'png' if name == 'site' else 'jpg'}"
            subprocess.run(["gdal_translate", "-q", "-b", "1", "-b", "2", "-b", "3",
                            "-of", "PNG" if name == "site" else "JPEG",
                            *([] if name == "site" else ["-co", "QUALITY=93"]),
                            str(ROOT / product["file"]), str(rgb)], check=True)
            report[name] = {"shares": shares, "source": product["file"], "year": year,
                            "cell_m": product["cell_m"]}
            print(name, shares)
    (OUT / "ground_cover.json").write_text(json.dumps(
        {"thresholds": {str(k): v for k, v in THRESHOLDS.items()}, "products": report},
        indent=2) + "\n")


if __name__ == "__main__":
    main()
