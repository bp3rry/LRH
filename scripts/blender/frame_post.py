"""Flyover post-processing for one frame, run by flyover.py in a separate process (Blender's
bundled Python) while the next frame renders: the blank-frame check (CLAUDE.md), the
caption (PLAN.md §7), then the raw frame is deleted. Exit 2 if the frame is blank.

Usage: python frame_post.py <raw.png> <f_NNNN.png> <caption text>
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lrh  # noqa: E402


def main():
    raw, dst, text = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
    try:
        lrh.frame_stats_file(raw)
    except lrh.CheckFailed as error:
        print(f"LRH CHECK FAILED: {dst.stem}: {error}", file=sys.stderr)
        sys.exit(2)
    tmp = dst.with_name(dst.stem + ".part.png")                # never a half-written f_NNNN.png
    lrh.caption_image(raw, tmp, text, compress_level=3)
    tmp.replace(dst)
    raw.unlink()


if __name__ == "__main__":
    main()
