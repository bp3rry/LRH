# LRH — Lake Ralph Hall Lakefront Lots

Cinematic marketing renders of ten ~2-acre lakefront lots on the owner's two ~10-acre
tracts at Lake Ralph Hall, Fannin County, Texas. Built in Blender from the terrain,
parcel, shoreline, and lot data established in the sibling projects
[`../property-terrain-modeling-pipeline`](../property-terrain-modeling-pipeline) and
[`../Ladonia`](../Ladonia).

See [PLAN.md](PLAN.md) for scope, phases, and open decisions.

## Layout

| Path | Committed | Contents |
| --- | --- | --- |
| `PLAN.md` | yes | Plan and status |
| `scripts/` | yes | Input import, Blender scene build, and render scripts |
| `shots.yaml` | yes | Camera and render definitions |
| `inputs.lock.json` | yes | Source path and SHA-256 for every input |
| `imagery.lock.json` | yes | NAIP requests, source scenes and SHA-256 |
| `ASSETS.md` | yes | Third-party asset sources and licences |
| `inputs/` | no | Copied source data |
| `assets/` | no | Downloaded trees, textures, HDRIs |
| `out/` | no | `.blend` builds and renders, by date |

## Build

```sh
B=/Applications/Blender.app/Contents/MacOS/Blender
BPY=/Applications/Blender.app/Contents/Resources/5.0/python/bin/python3.11

# once: packages for Blender's Python (kept out of Blender's own site-packages)
$BPY -m pip install --no-deps --target .blender-site -r scripts/blender/requirements.txt

python3 scripts/import_inputs.py              # PTM/Ladonia inputs -> inputs/, inputs.lock.json
python3 scripts/fetch_imagery.py              # NAIP 2022 -> inputs/imagery/, imagery.lock.json
python3 scripts/decode_naip2024.py            # NAIP 2024 from owner download (MrSID SDK)
python3 scripts/classify_ground_cover.py      # cover masks -> out/derived/
$BPY scripts/observed_cover_2026.py           # drone-photo clearing -> out/derived/
$B -b --python scripts/blender/build_baseline.py          # -> out/<date>/lrh_baseline.blend
$B -b --python scripts/blender/render.py -- --shot all --kind check
```

`build_baseline.py` writes `baseline_checks.json` and exits non-zero if any automated
check fails. `render.py` writes a JSON sidecar beside each frame and fails on a blank,
black or clipped frame. `scripts/solve_drone_camera.py` re-solves the drone-match camera
in `shots.yaml` if the inputs change.

All published images are artist's conceptions; see PLAN.md §7.
