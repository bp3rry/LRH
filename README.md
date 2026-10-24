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
| `docs/` | yes | Supporting plans (drone capture) |
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
$BPY scripts/observed_cover_drone.py           # drone-photo clearing -> out/derived/
# lidar: owner-downloaded LAZ tiles unzipped into inputs/lidar/; LASzip 3.5 (brew install laszip)
clang -O2 -I/opt/homebrew/include/laszip -L/opt/homebrew/lib -llaszip_api \
      scripts/native/laz_dump.c -o .build/laz_dump
$BPY scripts/lidar_trees.py                   # measured trees -> out/derived/lidar_trees.npz
$BPY scripts/digitize_fwh_zone.py             # LSMP habitat zone -> out/derived/fwh_zone_lsmp.geojson
$BPY scripts/lidar_surfaces.py                # 1 m lidar DSM/DTM -> out/derived/
$BPY scripts/calibrate_crowns.py              # crown radii calibrated to lidar canopy cover
$BPY scripts/kwik_ortho.py 24 18 14 15 17 28  # KwikImage cameras, ortho, canopy checks
$B -b --command extension install -e sapling_tree_gen      # once (free, GPL)
python3 scripts/fetch_assets.py island_tree_01 jacaranda_tree tree_small_02 shrub_04 pine_tree_01 fir_sapling_medium
$B -b --python-exit-code 1 --python scripts/blender/gen_trees.py           # -> assets/generated/sapling_trees.blend
$B -b --python-exit-code 1 --python scripts/blender/build_baseline.py          # -> out/<date>/lrh_baseline.blend
$B -b --python-exit-code 1 --python scripts/blender/render.py -- --shot all --kind check
```

`build_baseline.py` writes `baseline_checks.json` and exits non-zero if any automated
check fails. `render.py` writes a JSON sidecar beside each frame and fails on a blank,
black or clipped frame. `scripts/solve_drone_camera.py` re-solves the drone-match camera
in `shots.yaml` if the inputs change.

## Cloud render (RunPod)

Long flyovers (4K) can run on a rented RunPod GPU pod with the same scripts. Pod: an
NVIDIA GPU template (Ubuntu) with SSH over exposed TCP, a network volume on
`/workspace`, and the public key `~/.ssh/runpod_ed25519.pub` in RunPod settings. On
Linux the scripts render with OptiX (`LRH_GPU` overrides) and caption in Liberation Sans.

```sh
scripts/cloud/push.sh <ip> <port>             # repo, derived data, newest .blend, assets; pod_setup.sh
ssh -i ~/.ssh/runpod_ed25519 -p <port> root@<ip> \
    'cd /workspace/LRH && bash scripts/cloud/render.sh <date> --variant low --layout pairs --4k'
scripts/cloud/pull.sh <ip> <port> <date>      # frames back to out/<date>/video/ (repeatable)
$B -b out/<date>/lrh_baseline.blend --python-exit-code 1 --python scripts/blender/flyover.py \
    -- --variant low --layout pairs --4k --encode-only
```

`render.sh` runs one Blender per GPU (`--shard i/n`), each resuming after a stop.

All published images are artist's conceptions; see PLAN.md §7.
