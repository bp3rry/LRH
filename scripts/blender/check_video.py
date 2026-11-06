"""Check an encoded flyover against its frames: decode sample frames from the MP4 and
confirm each matches the PNG of the same number (and not a neighbour's), so a scrambled
or truncated encode fails. Owner, 6 Nov 2026: the first full 1080p encode name-sorted its
frames (f_10000 after f_1000) and played out of order from 33 s.

Usage:
  Blender -b --python-exit-code 1 --python scripts/blender/check_video.py -- <video.mp4> <frames dir> [frame ...]
Default frames: the start, the ends of each 4/5-digit boundary, a spread through the
flight and the last frame.
"""

import sys
import tempfile
from pathlib import Path

import bpy
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lrh  # noqa: E402

argv = sys.argv[sys.argv.index("--") + 1:]
video, frames_dir = Path(argv[0]), Path(argv[1])
n = sum(1 for _ in frames_dir.glob("f_*.png"))
samples = [int(v) for v in argv[2:]] or sorted({0, 999, 1000, 1001, 1005, 1100, 1321, 1322,
                                                n // 4, n // 2, 3 * n // 4, 9999, 10000, n - 2, n - 1} - {f for f in [9999, 10000] if f >= n})

scene = bpy.data.scenes.new("LRH_Check")
seq = scene.sequence_editor_create()
strips = seq.strips if hasattr(seq, "strips") else seq.sequences
strip = strips.new_movie("video", str(video), 1, 1)
length = strip.frame_final_duration
if length != n:
    lrh.fail(f"{video.name} has {length} frames, the folder {n}")
src = bpy.data.images.load(str(frames_dir / "f_0000.png"))
w, h = src.size
scene.render.resolution_x, scene.render.resolution_y = w, h
scene.render.resolution_percentage = 100
scene.view_settings.view_transform = "Standard"
scene.render.image_settings.file_format = "PNG"
if hasattr(scene.render.image_settings, "media_type"):
    scene.render.image_settings.media_type = "IMAGE"


def pixels(path):
    img = bpy.data.images.load(str(path), check_existing=False)
    iw, ih = img.size
    a = np.empty(iw * ih * 4, np.float32)
    img.pixels.foreach_get(a)
    bpy.data.images.remove(img)
    return a.reshape(ih, iw, 4)[::8, ::8, :3] * 255


tmp = Path(tempfile.mkdtemp(prefix="lrh_check_"))
bad = []
for f in samples:
    # A one-frame animation render: write_still after frame_set decodes the strip's first frame.
    scene.frame_start = scene.frame_end = f + 1
    scene.render.filepath = str(tmp / f"v_{f}_")
    bpy.ops.render.render(animation=True, scene=scene.name)
    (tmp / f"v_{f}_{f + 1:04d}.png").rename(tmp / f"v_{f}.png")
    got = pixels(tmp / f"v_{f}.png")
    same = float(np.abs(got - pixels(frames_dir / f"f_{f:04d}.png")).mean())
    others = [float(np.abs(got - pixels(frames_dir / f"f_{g:04d}.png")).mean())
              for g in (f - 30, f + 30) if 0 <= g < n]
    ok = same < 6.0 and all(same < 0.5 * o for o in others)   # H.264 noise is 2-4 levels
    print(f"CHECK frame {f}: diff {same:.2f} to its own PNG, {['%.2f' % o for o in others]} to +-30", "ok" if ok else "BAD")
    if not ok:
        bad.append(f)
if bad:
    lrh.fail(f"{video.name}: frames {bad} do not match their PNGs")
print(f"VIDEO OK {video.name}: {length} frames, {len(samples)} samples match")
