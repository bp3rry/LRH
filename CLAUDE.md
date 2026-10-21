# LRH agent notes

- Read `PLAN.md` first. The goal is settled; do not re-debate it.
- Inputs come read-only from `../property-terrain-modeling-pipeline` (PTM) and
  `../Ladonia`. Never write to either project.
- Blender: `/Applications/Blender.app/Contents/MacOS/Blender -b --python <script>`.
  Set camera `clip_end` explicitly (default 1000 m clips the scene); never call
  `read_factory_settings()` (it unloads importers). Verify renders numerically: a
  blank frame must fail.
- Coordinates: PTM `origin.json` local metres, EPSG:6344, NAVD88. The PTM OBJ files are Y-up.
- Marketing frames: no overlays, creek preservation zone stays wooded except the dock
  clearing, and the artist's-conception caption is required (PLAN.md §7). Docks are
  placed to the draft LSMP rules with riprap each side.
- No binaries in git.
