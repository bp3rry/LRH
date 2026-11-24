"""Check an encoded flyover against its frames: decode sample frames from the MP4 and
confirm each matches the PNG of the same number (and not a neighbour's), so a scrambled
or truncated encode fails. Owner, 6 Nov 2026: the first full 1080p encode name-sorted its
frames (f_10000 after f_1000) and played out of order from 33 s.

Usage:
  Blender -b --python-exit-code 1 --python scripts/blender/check_video.py -- <video.mp4> <frames dir> [frame ...]
Frames are video frame indices; video frame i is compared with the i-th PNG in numeric order,
so preview and --step renders (f_0000, f_0003, ...) check the same way as full ones.
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
pngs = sorted(frames_dir.glob("f_*.png"), key=lambda p: int(p.stem[2:]))
n = len(pngs)
samples = [int(v) for v in argv[2:]] or sorted({0, 999, 1000, 1001, 1005, 1100, 1321, 1322,
                                                n // 4, n // 2, 3 * n // 4, 9999, 10000, n - 2, n - 1})
samples = [f for f in samples if 0 <= f < n]

scene = bpy.data.scenes.new("LRH_Check")
seq = scene.sequence_editor_create()
strips = seq.strips if hasattr(seq, "strips") else seq.sequences
strip = strips.new_movie("video", str(video), 1, 1)
length = strip.frame_final_duration
if length != n:
    lrh.fail(f"{video.name} has {length} frames, the folder {n}")
src = bpy.data.images.load(str(pngs[0]))
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
    same = float(np.abs(got - pixels(pngs[f])).mean())
    others = [float(np.abs(got - pixels(pngs[g])).mean())
              for g in (f - 30, f + 30) if 0 <= g < n]
    ok = same < 6.0 and all(same < 0.5 * o for o in others)   # H.264 noise is 2-4 levels
    print(f"CHECK frame {f} ({pngs[f].name}): diff {same:.2f} to its own PNG, {['%.2f' % o for o in others]} to +-30", "ok" if ok else "BAD")
    if not ok:
        bad.append(f)
if bad:
    lrh.fail(f"{video.name}: frames {bad} do not match their PNGs")
print(f"VIDEO OK {video.name}: {length} frames, {len(samples)} samples match")
