"""Pull still frames from an imported drone capture's videos, each with its pose.

For every video in out/derived/drone/<capture>/capture.json (written by
import_drone_capture.py), extracts full-resolution frames to
out/derived/drone/<capture>/frames/<clip>/f_<frame>.jpg, chosen either
  --every-m D  : one frame each D metres of flight (needs telemetry; default 5 m), or
  --fps F      : F frames per second (footage without telemetry; default 1).
Each frame's telemetry (position in origin.json local metres, altitudes, gimbal angles)
is interpolated to the frame time and written to frames/<clip>/frames.json, the
starting pose for camera solves (kwik_ortho.py-style refinement) and matched renders.
A contact sheet per clip goes to frames/<clip>_sheet.jpg.

Checks: each extracted frame is non-blank (pixel standard deviation > 4), and the frame
count matches the request.

Usage (Blender's Python):
  python3.11 scripts/extract_drone_frames.py <capture dir name> [--every-m 5] [--fps 1]
      [--clip DJI_0001] [--quality 2]
"""

import argparse
import bisect
import csv
import json
import math
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT / ".blender-site"))

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

DERIVED = ROOT / "out/derived/drone"
NUMERIC = ("x", "y", "abs_alt", "rel_alt", "yaw", "pitch", "roll", "drone_yaw", "focal_len", "lat", "lon")


def load_telemetry(path):
    rows = []
    with open(path) as fh:
        for r in csv.DictReader(fh):
            rows.append({k: float(v) for k, v in r.items() if v not in ("", None)})
    return rows


def angle_lerp(a, b, f):
    d = (b - a + 180.0) % 360.0 - 180.0
    return a + d * f


def pose_at(rows, times, t):
    i = bisect.bisect_left(times, t)
    if i <= 0:
        return dict(rows[0])
    if i >= len(rows):
        return dict(rows[-1])
    a, b = rows[i - 1], rows[i]
    f = (t - a["t"]) / max(b["t"] - a["t"], 1e-9)
    out = {"t": t}
    for k in NUMERIC:
        if k in a and k in b:
            out[k] = angle_lerp(a[k], b[k], f) if k in ("yaw", "drone_yaw") else a[k] + (b[k] - a[k]) * f
    return out


def frames_by_distance(rows, fps, n_frames, every_m):
    picks, run, last = [0], 0.0, rows[0]
    for r in rows[1:]:
        run += math.hypot(r["x"] - last["x"], r["y"] - last["y"])
        last = r
        if run >= every_m:
            picks.append(min(int(round(r["t"] * fps)), n_frames - 1))
            run = 0.0
    return sorted(set(picks))


def extract(video, frames, dest, quality):
    dest.mkdir(parents=True, exist_ok=True)
    todo = [f for f in frames if not (dest / f"f_{f:05d}.jpg").exists()]
    if todo:
        expr = "+".join(f"eq(n\\,{f})" for f in todo)
        tmp = dest / "_tmp"
        tmp.mkdir(exist_ok=True)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(video), "-vf", f"select='{expr}'",
                        "-fps_mode", "passthrough", "-q:v", str(quality), str(tmp / "o_%05d.jpg")],
                       check=True)
        outs = sorted(tmp.glob("o_*.jpg"))
        if len(outs) != len(todo):
            raise SystemExit(f"FAIL {video.name}: asked for {len(todo)} frames, ffmpeg wrote {len(outs)}")
        for f, o in zip(todo, outs):
            o.rename(dest / f"f_{f:05d}.jpg")
        tmp.rmdir()
    for f in frames:
        arr = np.asarray(Image.open(dest / f"f_{f:05d}.jpg").convert("L").reduce(8), dtype=float)
        if arr.std() <= 4.0:
            raise SystemExit(f"FAIL {video.name} frame {f}: blank (std {arr.std():.1f})")


def sheet(dest, frames, out, cols=6, width=320):
    ims = [Image.open(dest / f"f_{f:05d}.jpg") for f in frames]
    h = int(width * ims[0].height / ims[0].width)
    rows = math.ceil(len(ims) / cols)
    canvas = Image.new("RGB", (cols * width, rows * h), "black")
    for i, im in enumerate(ims):
        canvas.paste(im.resize((width, h)), ((i % cols) * width, (i // cols) * h))
    canvas.save(out, quality=85)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("capture")
    ap.add_argument("--every-m", type=float, default=5.0)
    ap.add_argument("--fps", type=float, default=1.0)
    ap.add_argument("--clip")
    ap.add_argument("--quality", type=int, default=2)
    a = ap.parse_args()
    cap_dir = DERIVED / a.capture
    record = json.loads((cap_dir / "capture.json").read_text())
    for rel, meta in record["videos"].items():
        video = ROOT / rel
        if a.clip and video.stem != a.clip:
            continue
        fps, n = meta["fps"], meta["frames"]
        rows = None
        if meta.get("telemetry"):
            rows = load_telemetry(ROOT / meta["telemetry"]["csv"])
            frames = frames_by_distance(rows, fps, n, a.every_m)
            how = f"every {a.every_m} m"
        else:
            step = max(int(round(fps / a.fps)), 1)
            frames = list(range(0, n, step))
            how = f"{a.fps} fps (no telemetry)"
        dest = cap_dir / "frames" / video.stem
        extract(video, frames, dest, a.quality)
        times = [r["t"] for r in rows] if rows else None
        index = []
        for f in frames:
            entry = {"frame": f, "t": round(f / fps, 4), "file": f"f_{f:05d}.jpg"}
            if rows:
                entry["pose"] = {k: round(v, 4) for k, v in pose_at(rows, times, f / fps).items()}
            index.append(entry)
        (dest / "frames.json").write_text(json.dumps({
            "video": rel, "fps": fps, "size": [meta["width"], meta["height"]],
            "selection": how, "graded": not meta["needs_grade"],
            "pose_source": meta["pose"], "frames": index}, indent=1))
        sheet(dest, frames, cap_dir / "frames" / f"{video.stem}_sheet.jpg")
        print(f"{video.name}: {len(frames)} frames ({how}) -> {dest.relative_to(ROOT)}"
              + ("" if not meta["needs_grade"] else "  [HDR/log, ungraded]"))


if __name__ == "__main__":
    main()
