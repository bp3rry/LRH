"""Import a drone capture (video and/or stills) into inputs/drone/ and pin it.

Copies the source files unchanged into inputs/drone/<date>_<site>/raw/ (the handover
layout in docs/DRONE-CAPTURE-PLAN.md §6.1), hashes every file into the committed
drone.lock.json, and reads what each file says about itself:

- video: codec, size, frame rate, frame count, duration, colour transfer (HLG / D-Log
  footage is flagged: it needs a grade before it is compared with renders), and the
  flight telemetry, from a DJI .SRT sidecar or from the MP4's embedded timed metadata
  (exiftool -ee). Telemetry is written per sample to
  out/derived/drone/<capture>/<clip>_telemetry.csv in origin.json local metres;
- stills: EXIF GPS and the DJI XMP altitude and gimbal angles, as kwik_ortho.py reads them.

Checks (a failure stops the import): every video decodes with a non-zero frame count;
every telemetry track and GPS still lies within 5 km of the site origin. Footage with no
telemetry is accepted and marked `pose: solve_from_imagery`.

Usage (Blender's Python, for PyYAML in .blender-site):
  /Applications/Blender.app/Contents/Resources/5.0/python/bin/python3.11 \
      scripts/import_drone_capture.py <source folder|files...> [--date YYYY-MM-DD] \
      [--site ladonia] [--note "text"] [--relock <capture dir>]
--date defaults to the earliest recording date found in the files.
--relock re-reads an already imported capture (no copy).
"""

import argparse
import csv
import hashlib
import json
import math
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT / ".blender-site"))

import yaml  # noqa: E402

DRONE = ROOT / "inputs/drone"
DERIVED = ROOT / "out/derived/drone"
LOCK = ROOT / "drone.lock.json"
ORIGIN = json.loads((ROOT / "inputs/terrain/origin.json").read_text())["origin"]
SITE_RADIUS_M = 5000.0

VIDEO = {".mp4", ".mov", ".m4v", ".mkv", ".avi", ".lrf"}
STILL = {".jpg", ".jpeg", ".dng", ".png", ".tif", ".tiff", ".heic"}
SIDECAR = {".srt"}
LOG = {".txt", ".csv", ".kml", ".kmz", ".dat", ".log"}
SKIP = {".ds_store"}


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def kind(path):
    ext = path.suffix.lower()
    if path.name.lower() in SKIP or path.name.startswith("._"):
        return None
    for name, exts in (("video", VIDEO), ("still", STILL), ("srt", SIDECAR), ("log", LOG)):
        if ext in exts:
            return name
    return "other"


def to_local(points):
    """[(lon, lat)] -> [(x, y)] in origin.json local metres (EPSG:6344)."""
    if not points:
        return []
    text = "".join(f"{lon} {lat}\n" for lon, lat in points)
    out = subprocess.run(["gdaltransform", "-s_srs", "EPSG:4326", "-t_srs", "EPSG:6344"],
                         input=text, capture_output=True, text=True, check=True).stdout
    res = []
    for line in out.strip().splitlines():
        e, n = map(float, line.split()[:2])
        res.append((e - ORIGIN["easting"], n - ORIGIN["northing"]))
    return res


# ---------------------------------------------------------------- video metadata

def probe(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-count_packets", "-show_entries",
         "stream=index,codec_type,codec_name,codec_tag_string,width,height,r_frame_rate,"
         "nb_frames,nb_read_packets,color_transfer,color_primaries,pix_fmt,bit_rate:"
         "stream_tags:format=duration,size:format_tags", "-of", "json", str(path)],
        capture_output=True, text=True)
    if out.returncode:
        raise SystemExit(f"FAIL {path.name}: ffprobe cannot read it\n{out.stderr[-400:]}")
    info = json.loads(out.stdout)
    video = [s for s in info["streams"] if s["codec_type"] == "video"]
    if not video:
        raise SystemExit(f"FAIL {path.name}: no video stream")
    v = video[0]
    num, den = map(int, v["r_frame_rate"].split("/"))
    frames = int(v.get("nb_read_packets") or v.get("nb_frames") or 0)
    if frames <= 0:
        raise SystemExit(f"FAIL {path.name}: zero decodable frames")
    transfer = v.get("color_transfer", "unknown")
    tags = {**info.get("format", {}).get("tags", {}), **v.get("tags", {})}
    return {
        "codec": v["codec_name"], "width": v["width"], "height": v["height"],
        "fps": round(num / den, 3), "frames": frames,
        "duration_s": round(float(info["format"]["duration"]), 3),
        "pix_fmt": v.get("pix_fmt"), "color_transfer": transfer,
        "color_primaries": v.get("color_primaries"),
        "needs_grade": transfer in ("arib-std-b67", "smpte2084") or "log" in transfer.lower(),
        "data_streams": [s.get("codec_tag_string") for s in info["streams"]
                         if s["codec_type"] == "data"],
        "creation_time": tags.get("creation_time"),
        "encoder": tags.get("encoder"),
    }


def exif_json(path, embedded=False):
    args = ["exiftool", "-j", "-n", "-G1", "-a"] + (["-ee3"] if embedded else []) + [str(path)]
    out = subprocess.run(args, capture_output=True, text=True)
    if out.returncode or not out.stdout.strip():
        return {}
    return json.loads(out.stdout)[0]


def first(tags, *patterns):
    for pat in patterns:
        for key, val in tags.items():
            if not re.search(pat, key, re.I):
                continue
            if isinstance(val, (int, float)):
                return float(val)
            if isinstance(val, str) and re.fullmatch(r"[+-]?\d+(\.\d+)?", val.strip()):
                return float(val)  # DJI XMP writes "+357.900"
    return None


# ---------------------------------------------------------------- telemetry

SRT_TIME = re.compile(r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->")
SRT_FIELDS = {
    "lat": r"latitude\s*[:=]\s*([+-]?[\d.]+)",
    "lon": r"longitude\s*[:=]\s*([+-]?[\d.]+)",
    "rel_alt": r"rel_alt\s*[:=]\s*([+-]?[\d.]+)",
    "abs_alt": r"abs_alt\s*[:=]\s*([+-]?[\d.]+)",
    "yaw": r"gb_yaw\s*[:=]\s*([+-]?[\d.]+)",
    "pitch": r"gb_pitch\s*[:=]\s*([+-]?[\d.]+)",
    "roll": r"gb_roll\s*[:=]\s*([+-]?[\d.]+)",
    "focal_len": r"focal_len\s*[:=]\s*([+-]?[\d.]+)",
    "iso": r"iso\s*[:=]\s*([\d.]+)",
    "shutter": r"shutter\s*[:=]\s*([\d/.]+)",
    "ev": r"\bev\s*[:=]\s*([+-]?[\d.]+)",
    "ct": r"\bct\s*[:=]\s*([\d.]+)",
}
SRT_GPS_OLD = re.compile(r"GPS\s*\(\s*([+-]?[\d.]+)\s*,\s*([+-]?[\d.]+)\s*,\s*([+-]?[\d.]+)")
SRT_H_OLD = re.compile(r"\bH\s*([+-]?[\d.]+)\s*m", re.I)


def parse_srt(path):
    """DJI SRT (Mini/Air/Mavic formats). Returns samples with t (s) and whatever fields exist."""
    samples = []
    for block in re.split(r"\n\s*\n", path.read_text(errors="replace")):
        tm = SRT_TIME.search(block)
        if not tm:
            continue
        h, m, s, ms = tm.groups()
        rec = {"t": int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 10 ** len(ms)}
        for name, pat in SRT_FIELDS.items():
            hit = re.search(pat, block, re.I)
            if hit:
                val = hit.group(1)
                rec[name] = (float(val.split("/")[0]) / float(val.split("/")[1])
                             if "/" in val else float(val))
        old = SRT_GPS_OLD.search(block)
        if old and "lat" not in rec:
            rec["lon"], rec["lat"] = float(old.group(1)), float(old.group(2))
            hh = SRT_H_OLD.search(block)
            if hh:
                rec["rel_alt"] = float(hh.group(1))
        if "lat" in rec and "lon" in rec and not (rec["lat"] == 0 and rec["lon"] == 0):
            samples.append(rec)
    return samples


def embedded_telemetry(path, duration_s):
    """Timed GPS/gimbal samples embedded in the MP4 (DJI djmd/dbgi), via exiftool -ee3."""
    out = subprocess.run(["exiftool", "-ee3", "-n", "-G3", "-a", "-s", "-j", str(path)],
                         capture_output=True, text=True)
    if out.returncode or not out.stdout.strip():
        return []
    tags = json.loads(out.stdout)[0]
    docs = {}
    for key, val in tags.items():
        hit = re.match(r"Doc(\d+):(.+)", key)
        if hit:
            docs.setdefault(int(hit.group(1)), {})[hit.group(2)] = val
    samples = []
    for _, doc in sorted(docs.items()):
        lat = first(doc, r"GPSLatitude$", r"Latitude$")
        lon = first(doc, r"GPSLongitude$", r"Longitude$")
        if lat is None or lon is None or (lat == 0 and lon == 0):
            continue
        rec = {"t": first(doc, r"SampleTime$"), "lat": lat, "lon": lon,
               "abs_alt": first(doc, r"AbsoluteAltitude", r"GPSAltitude$"),
               "rel_alt": first(doc, r"RelativeAltitude"),
               "yaw": first(doc, r"GimbalYaw"), "pitch": first(doc, r"GimbalPitch"),
               "roll": first(doc, r"GimbalRoll"),
               "drone_yaw": first(doc, r"DroneYaw|FlightYaw"),
               "focal_len": first(doc, r"FocalLength")}
        samples.append({k: v for k, v in rec.items() if v is not None})
    if samples and any("t" not in s for s in samples):  # spread evenly if untimed
        for i, s in enumerate(samples):
            s["t"] = duration_s * i / max(len(samples) - 1, 1)
    return samples


def write_telemetry(samples, fps, dest):
    xy = to_local([(s["lon"], s["lat"]) for s in samples])
    cols = ["frame", "t", "lat", "lon", "x", "y", "abs_alt", "rel_alt", "yaw", "pitch",
            "roll", "drone_yaw", "focal_len", "iso", "shutter", "ev", "ct"]
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("w", newline="") as fh:
        w = csv.DictWriter(fh, cols, extrasaction="ignore")
        w.writeheader()
        for s, (x, y) in zip(samples, xy):
            w.writerow({**s, "x": round(x, 3), "y": round(y, 3),
                        "frame": int(round(s["t"] * fps))})
    dist = [math.hypot(x, y) for x, y in xy]
    path_len = sum(math.dist(a, b) for a, b in zip(xy, xy[1:]))
    rel = [s["rel_alt"] for s in samples if "rel_alt" in s]
    return {
        "samples": len(samples), "csv": str(dest.relative_to(ROOT)),
        "has_gimbal": any("pitch" in s for s in samples),
        "start_local_m": [round(v, 1) for v in xy[0]], "end_local_m": [round(v, 1) for v in xy[-1]],
        "max_from_origin_m": round(max(dist), 1), "path_m": round(path_len, 1),
        "rel_alt_m": [round(min(rel), 1), round(max(rel), 1)] if rel else None,
    }


# ---------------------------------------------------------------- stills

def still_pose(path):
    tags = exif_json(path)
    # Composite:* carries the hemisphere sign; GPS:GPSLongitude is unsigned.
    lat = first(tags, r"^Composite:GPSLatitude$")
    lon = first(tags, r"^Composite:GPSLongitude$")
    rec = {"make": tags.get("IFD0:Make"), "model": tags.get("IFD0:Model"),
           "taken": tags.get("ExifIFD:DateTimeOriginal"),
           "width": first(tags, r"ImageWidth$", r"ExifImageWidth"),
           "height": first(tags, r"ImageHeight$", r"ExifImageHeight"),
           "focal_mm": first(tags, r"ExifIFD:FocalLength$"),
           "abs_alt": first(tags, r"AbsoluteAltitude"), "rel_alt": first(tags, r"RelativeAltitude"),
           "yaw": first(tags, r"GimbalYawDegree"), "pitch": first(tags, r"GimbalPitchDegree"),
           "roll": first(tags, r"GimbalRollDegree")}
    if lat is not None and lon is not None:
        (x, y), = to_local([(lon, lat)])
        rec.update(lat=lat, lon=lon, x=round(x, 2), y=round(y, 2))
    return {k: v for k, v in rec.items() if v is not None}


# ---------------------------------------------------------------- main

def recorded_date(paths):
    dates = []
    for p in paths:
        if kind(p) not in ("video", "still"):
            continue
        tags = exif_json(p)
        for key in ("ExifIFD:DateTimeOriginal", "QuickTime:CreateDate", "Keys:CreationDate"):
            val = tags.get(key)
            if isinstance(val, str) and re.match(r"\d{4}:\d\d:\d\d", val) and not val.startswith("0000"):
                dates.append(val[:10].replace(":", "-"))
                break
    return min(dates) if dates else None


def gather(sources):
    files = []
    for src in sources:
        src = Path(src).expanduser()
        if src.is_dir():
            files += [(p, p.relative_to(src)) for p in sorted(src.rglob("*")) if p.is_file()]
        elif src.is_file():
            files.append((src, Path(src.name)))
        else:
            raise SystemExit(f"FAIL source not found: {src}")
    return [(p, rel) for p, rel in files if kind(p)]


def copy_in(files, raw):
    for src, rel in files:
        dest = raw / rel
        if dest.exists():
            if dest.stat().st_size == src.stat().st_size and sha256(dest) == sha256(src):
                continue
            raise SystemExit(f"FAIL {dest} already exists with different content")
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)


def read_capture(cap, note=None):
    raw = cap / "raw"
    paths = sorted(p for p in raw.rglob("*") if p.is_file() and kind(p))
    if not paths:
        raise SystemExit(f"FAIL no files in {raw}")
    srts = {p.with_suffix("").name.lower(): p for p in paths if kind(p) == "srt"}
    entries, videos, stills = [], {}, {}
    for p in paths:
        rel = str(p.relative_to(ROOT))
        entries.append({"path": rel, "kind": kind(p), "bytes": p.stat().st_size, "sha256": sha256(p)})
        if kind(p) == "video" and p.suffix.lower() != ".lrf":
            meta = probe(p)
            tags = exif_json(p)
            meta["make"] = tags.get("QuickTime:Make") or tags.get("Keys:Make") or tags.get("UserData:Make")
            meta["model"] = (tags.get("QuickTime:Model") or tags.get("Keys:Model")
                             or tags.get("UserData:Model"))
            srt = srts.get(p.stem.lower())
            samples, source = (parse_srt(srt), "srt") if srt else ([], None)
            if not samples:
                samples, source = embedded_telemetry(p, meta["duration_s"]), "embedded"
            if samples:
                csv_path = DERIVED / cap.name / f"{p.stem}_telemetry.csv"
                meta["telemetry"] = {"source": source, **write_telemetry(samples, meta["fps"], csv_path)}
                meta["pose"] = "telemetry"
                if meta["telemetry"]["max_from_origin_m"] > SITE_RADIUS_M:
                    raise SystemExit(f"FAIL {p.name}: telemetry reaches "
                                     f"{meta['telemetry']['max_from_origin_m']:.0f} m from the site origin")
            else:
                meta["pose"] = "solve_from_imagery"
            videos[rel] = meta
        elif kind(p) == "still":
            pose = still_pose(p)
            if "x" in pose and math.hypot(pose["x"], pose["y"]) > SITE_RADIUS_M:
                raise SystemExit(f"FAIL {p.name}: GPS {math.hypot(pose['x'], pose['y']):.0f} m from site")
            stills[rel] = pose
    summary = {
        "videos": len(videos), "stills": len(stills),
        "video_seconds": round(sum(v["duration_s"] for v in videos.values()), 1),
        "videos_with_telemetry": sum(v["pose"] == "telemetry" for v in videos.values()),
        "stills_with_gps": sum("x" in s for s in stills.values()),
        "needs_grade": sorted(Path(k).name for k, v in videos.items() if v["needs_grade"]),
    }
    record = {"capture": cap.name, "imported_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
              "summary": summary, "videos": videos, "stills": stills, "files": entries}
    if note:
        record["note"] = note
    (DERIVED / cap.name).mkdir(parents=True, exist_ok=True)
    (DERIVED / cap.name / "capture.json").write_text(json.dumps(record, indent=1))

    manifest = cap / "capture_manifest.yaml"
    if not manifest.exists():
        models = sorted({str(v.get("model")) for v in videos.values() if v.get("model")}
                        | {str(s.get("model")) for s in stills.values() if s.get("model")})
        manifest.write_text(yaml.safe_dump({
            "date": cap.name[:10], "pilot": None, "aircraft_camera": ", ".join(models) or None,
            "source": note, "files": {"videos": len(videos), "stills": len(stills)},
            "notes": [], }, sort_keys=False))

    lock = json.loads(LOCK.read_text()) if LOCK.exists() else {"schema": "lrh.drone-lock/1", "captures": {}}
    lock["captures"][cap.name] = {
        "imported_utc": record["imported_utc"], "summary": summary,
        "files": {e["path"]: {"sha256": e["sha256"], "bytes": e["bytes"]} for e in entries},
    }
    LOCK.write_text(json.dumps(lock, indent=1, sort_keys=True) + "\n")
    return record


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("sources", nargs="*")
    ap.add_argument("--date")
    ap.add_argument("--site", default="ladonia")
    ap.add_argument("--note")
    ap.add_argument("--relock")
    a = ap.parse_args()
    if a.relock:
        cap = Path(a.relock).resolve()
    else:
        files = gather(a.sources)
        if not files:
            raise SystemExit("FAIL no importable files in the sources")
        date = a.date or recorded_date([p for p, _ in files])
        if not date:
            raise SystemExit("FAIL no recording date in the files; pass --date")
        cap = DRONE / f"{date}_{a.site}"
        copy_in(files, cap / "raw")
    rec = read_capture(cap, a.note)
    s = rec["summary"]
    print(f"{cap.name}: {s['videos']} videos ({s['video_seconds']} s, "
          f"{s['videos_with_telemetry']} with telemetry), {s['stills']} stills "
          f"({s['stills_with_gps']} with GPS)")
    for name, v in rec["videos"].items():
        t = v.get("telemetry")
        print(f"  {Path(name).name}: {v['width']}x{v['height']} {v['fps']} fps {v['frames']} fr "
              f"{v['duration_s']} s {v['color_transfer']}{' NEEDS GRADE' if v['needs_grade'] else ''} "
              f"pose={v['pose']}" + (f" ({t['source']}, {t['samples']} samples, path {t['path_m']} m, "
                                     f"rel alt {t['rel_alt_m']})" if t else ""))
    print(f"wrote {LOCK.relative_to(ROOT)} and out/derived/drone/{cap.name}/capture.json")


if __name__ == "__main__":
    main()
