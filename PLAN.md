# LRH — Lake Ralph Hall Lakefront Lots: Plan

**Drafted:** 14 October 2026
**Status:** Owner-approved 14 October 2026

## 1. Goal

Produce cinematic, photoreal marketing renders of ten approximately two-acre lakefront
lots on the owner's two ~10-acre tracts at Lake Ralph Hall, Fannin County, TX.

1. **Baseline model:** a Blender scene of the two tracts, their terrain, the lake at
   conservation pool, roads, and existing vegetation. It must be accurate enough that
   the drone photo and the render read as the same place.
2. **Hero stills (first release):** three 8K (7680 × 4320) cinematic stills of the whole
   development, meeting the benchmark set in
   `../property-terrain-modeling-pipeline/properties/ladonia/Sketchup/`
   (`444-perry_lakehouse_exterior_cam_02.jpg` sunset and `cam_03` high oblique).
3. **Later releases:** per-lot stills, flyover video, and a lot-plan graphic.

The goal is settled. Do not re-explain or re-debate it in later documents or sessions.

## 2. Decisions Already Made (14 Oct 2026)

| Decision | Choice |
| --- | --- |
| Property | Same Ladonia tracts: CAD 116505 (North) + 135089 (South), 19.87 ac, between CR 3635 (east) and relocated CR 3640 (south) |
| Lot layout | The pipeline's ten equal-area lake-to-road lots: Lots 1–5 at 1.966 ac (North), Lots 6–10 at 2.007 ac (South) |
| Renderer | Blender 5.0.1 (installed), Python-driven headless, Cycles on Metal |
| First deliverable | Hero stills |

## 3. What Carries Over, and What Does Not

### Reused as read-only inputs

These come from `../property-terrain-modeling-pipeline` (abbreviated `PTM`) and
`../Ladonia`. They are copied into `inputs/` (git-ignored) by an import script that
writes `inputs.lock.json` (committed) with each file's source path and SHA-256.

| Input | Source | Use |
| --- | --- | --- |
| 1 m site terrain mesh (400k tris, parcel + 200 m buffer) | `PTM/out/terrain_design.obj`, `PTM/out/terrain_site.tif` | Foreground ground surface |
| Local origin and axis convention | `PTM/out/origin.json` (EPSG:6344, origin E 228812.806 / N 3704358.802; OBJ is Y-up) | One coordinate frame for every input |
| Regional 50 m terrain + official 551 ft lake | `PTM/properties/ladonia/geometry/lake-ralph-hall-50m-terrain-551ft-reference.dae` | Mid/background terrain and shoreline |
| Parcel boundaries | `PTM/properties/ladonia/geometry/parcel.geojson` (cemetery 85553 excluded) | Overlay and lot clipping |
| Ten lots, roads, connected water | `PTM/out/site-review-context*.json` (from `tools/export_site_review_context.py`) | Lot overlays and road placement |
| CR 3635 / SH 34 centerlines | `PTM/properties/ladonia/geometry/txdot-*.geojson` | Road surfaces and the bridge landmark |
| Drone photo | `Ladonia Arial 1.jpeg` | Match-camera check, vegetation and clearing reference |
| Visual benchmarks | `PTM/properties/ladonia/Sketchup/` | Acceptance comparison |
| Prior lakehouse model | `12NOV23-perry_lakehouse_exterior.skp` | Optional "example home" (Section 7) |
| LSMP draft, UTRWD maps | `../Ladonia/Reference/Lake-Ralph-Hall/` | Shoreline and dock rules |

The `PTM` Python code stays where it is. If new terrain products are needed, run the
pipeline there and re-import; do not fork its code into LRH.

### Deliberately left behind

- **The SketchUp command queue, runtime, and extension.** Blender is scripted directly,
  so there is no queue, no active-model guessing, and no `Model#close` crashes.
- **Hash-chained decision records, addenda, and per-step review gates.** These were
  right for a model that supports surveyor discussions. Here, provenance is one
  inputs manifest plus a small JSON sidecar per render recording the git commit,
  `inputs.lock.json` hash, camera, and render settings.
- **Diagram-style presentation.** Red outlines and lollipop trees are review aids
  only, in a toggleable overlay collection; they never appear in marketing frames.

Still applicable from `PTM/docs/LESSONS-LEARNED.md`: verify content, not just file
existence; never invent terrain in a void; assert non-zero counts. Also from
`PTM/memory/3d-review-toolchain.md`: set the Blender camera `clip_end` explicitly and
do not call `read_factory_settings()`.

## 4. Pipeline

```
inputs/ (copied + hashed)
   │  scripts/import_inputs.py  ->  inputs.lock.json
   ▼
scripts/build_baseline.py   (Blender headless)  ->  out/<date>/lrh_baseline.blend
   │  terrain, water, roads, vegetation, overlays, cameras
   ▼
scripts/render.py --shot <name> --res draft|final  ->  out/<date>/<shot>.png + .json
```

- The `.blend` is a build product and can always be regenerated from scripts and inputs.
  Hand edits made in the Blender GUI must be reflected back into the scripts or a
  committed config, or they are lost on the next build.
- Shots are defined in a committed `shots.yaml`: camera position, target, lens, time of
  day, visible collections, and resolution.
- Assets (trees, grass, HDRIs, textures) go in `assets/` (git-ignored). Each asset's
  name, source URL, and licence is listed in the committed `ASSETS.md`. CC0 sources
  (Poly Haven, ambientCG) come first.

## 5. Phases

### Phase 0 — Scaffold (today)

- [x] Repo, README, this plan.
- [x] `scripts/import_inputs.py` and the first `inputs.lock.json` (11 files; PTM
      sibling-hash consistency checks pass).
- [x] Blender smoke test (`scripts/blender/smoke_test.py`): 1 m site terrain
      (630,360 vertices, matching `origin.json`), 50 m regional terrain, and the UTRWD lake
      render in one frame. Blank, clipped, or black frames fail the check. A 960 × 540
      frame at 32 samples takes about 1 minute end to end on Metal.

### Phase 1 — Baseline model

1. **Terrain:** 1 m site mesh, blended into 50 m regional terrain beyond the buffer, in
   `origin.json` local metres (Blender Z-up).
2. **Water:** lake surface at 551 ft (167.9448 m) clipped to the UTRWD shoreline
   polygon, with a physically based water shader. Shoreline XY stays as published.
3. **Ground cover from imagery.** Acquire recent orthoimagery (TxGIO StratMap or NAIP,
   0.3–0.6 m) and classify it into woods, clearing/pasture, and bare/road masks. This
   replaces invented placements with the real clearing pattern shown in the drone photo.
4. **Trees.** Use a canopy-height source in this order:
   (a) classified StratMap 2025 LAZ point cloud, if TxGIO serves it for this area
   (previously unavailable, so retry);
   (b) Meta/WRI 1 m global canopy-height map (AWS Open Data);
   (c) imagery masks only, with species-appropriate random heights.
   Species palette from the drone photo: post oak, cedar elm, eastern red cedar
   (scattered cedars in the pasture), and bois d'arc along fence lines.
   The western creek preservation zone stays fully wooded: no clearing in any render.
5. **Roads:** CR 3635 (gravel/chip seal per the drone photo) and relocated CR 3640 as
   conceptual surfaces. SH 34 bridge as a distant schematic silhouette for orientation.
6. **Overlays (review only):** parcel lines, lot lines and numbers, in their own
   collection, hidden in marketing shots.
7. **Check views:** north-up ortho matching the PTM lot plan; a camera matched to
   `Ladonia Arial 1.jpeg`; and a lake-facing oblique.

**Acceptance:**
- Automated: lot areas computed from scene geometry match the PTM values to 0.01 ac;
  terrain vertex error against `terrain_site.tif` is within the PTM 0.15 m limit;
  every check view renders non-blank.
- Owner: the drone-match view, seen side by side with the drone photo, reads as the
  same place (tree masses, clearings, roads).

### Phase 2 — Hero stills (first release)

Three compositions; the owner may swap any of them:

| Shot | Composition | Benchmark |
| --- | --- | --- |
| H1 "Arrival" | High oblique from the southeast over CR 3635, looking west and northwest across the lots to the lake and SH 34 bridge | `cam_03`, drone photo |
| H2 "Sunset shore" | Low, near-shore view across the water toward the wooded lots at golden hour, with sun reflection | `cam_02` |
| H3 "From the lake" | Elevated view from over the water looking back east at the lot frontage, mid-afternoon | — |

Process: 1920 × 1080 drafts → the owner picks and directs → 7680 × 4320 Cycles finals,
denoised, with a light colour grade. Each final ships with its JSON sidecar.

**Acceptance:** owner side-by-side review against `cam_02` and `cam_03` for realism,
lighting, materials, vegetation, and composition.

### Phase 3+ — Later releases (planned after Phase 2 is accepted)

- **Per-lot stills:** templated cameras for each lot (lot-to-lake, lot-from-water,
  aerial with lot highlight), in clean and outlined variants.
- **Flyover video:** drone-photo-to-lake reveal. Use EEVEE or a render farm, because
  local Cycles at 4K for about 1,800 frames is a multi-day render on this machine.
- **Lot-plan graphic:** north-up plan over orthoimagery with lot numbers and acreage.

## 6. Compute Notes

The machine is an Apple M4 with 10 GPU cores and 24 GB unified memory, using Cycles on
Metal. 8K frames with dense vegetation scatter are limited by memory, not time. To
stay within it, use instanced trees (never realised geometry), lower-detail meshes past
about 300 m, and render in tiles. Measure the time per frame on the first H1 draft and
record it here before promising final turnaround.

## 7. Marketing Representation: Owner Decisions Before Publishing

These renders will be used to sell lots, so what they depict carries obligations the
surveyor model did not have. Default behaviour is shown in **bold**; the owner decides.

1. **Caption.** **Every published image carries "Artist's conception. Lake shown at
   conservation pool. Lot lines approximate, subject to survey and plat."**
2. **Lake level.** **Full pool, 551 ft.** Before publishing, confirm the current fill
   status and decide whether the caption needs to say the lake is still filling.
3. **Docks.** The draft LSMP requires 300 ft between docks and allows one per owner
   with an occupied residence. The PTM study found ten docks infeasible (126 ft minimum
   spacing). **No docks in marketing frames.** Pedestrian shoreline paths (5 ft max)
   are allowed.
4. **Homes.** **Empty, wooded, buildable lots.** Optional variant: the prior Perry
   lakehouse as one clearly labelled example home on one lot.
5. **Acreage figures.** The CAD polygon for 116505 is 0.39 ac smaller than the
   10.221 ac in the survey. **Quote acreage from the survey or plat, not from
   CAD-derived lot areas.**
6. **Pre-plat marketing.** The lots are not yet platted. **Before publishing
   lot-specific marketing, confirm with a Texas real-estate attorney or broker what
   Fannin County and Texas law allow** for advertising lots ahead of plat approval.
7. **Creek preservation zone.** **Always depicted wooded and uncleared.**

## 8. Working Rules

- **End-of-day delivery (carried from PTM BR-1):** each workday ends with a saved
  `out/YYYY-MM-DD/lrh_baseline.blend` and preview renders, ready for owner review.
- One commit per meaningful step. No binaries in git (`.blend`, renders, inputs, and
  assets are all ignored); scripts, configs, `inputs.lock.json`, `ASSETS.md`, and docs
  are committed.
- Never modify files in `../property-terrain-modeling-pipeline` or `../Ladonia` from
  this project.

## 9. Open Items

| Item | Owner | Needed by |
| --- | --- | --- |
| Asset budget: CC0-only (current default), or allow paid tree packs (e.g. Botaniq) | Owner | Phase 1 step 4 |
| Section 7 decisions 2–6 | Owner | Before any publication |
| Retry for StratMap 2025 classified LAZ | Claude | Phase 1 step 4 |
| Commit or discard the uncommitted queue/sidecar changes in PTM | Owner | Any time (does not block LRH) |
