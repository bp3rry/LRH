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

**Status (14 Oct 2026): accepted.** Automated checks pass. The owner reviewed the
drone-match side-by-side and accepted it. Build products are in `out/2026-10-14/` (`lrh_baseline.blend`,
`baseline_checks.json`, three check views with sidecars, and
`check_drone_match_side_by_side.jpg`).

- [x] Terrain. The site mesh is unaltered: its 3×3 block means reproduce `terrain_site.tif`
      to 7×10⁻⁵ m (the tif is exactly that aggregate). Regional faces within 120 m are
      replaced by a constrained-Delaunay ring that shares every 1 m site edge vertex.
- [x] Water, with two deviations for the owner to note. (a) The published polygon is
      generalised: 40% of its edge lies over ground below pool. So the water mask is the
      official polygon plus PTM's terrain-connected pool, buffered 60 m, and the visible
      shoreline is the 551 ft terrain contour. Edge exposure: 17 of 12,824 samples, 3 near
      the site. (b) The 2025 regional terrain has no dam embankment, so a schematic
      embankment sits on PTM's dam marker. Without it the lake ends in a water wall.
- [x] Ground cover from imagery. Uses NAIP 2024 (0.6 m, flown 3 Jul 2024), decoded from
      the TxGIO county MrSID mosaic with LizardTech's SDK; it aligns with NAIP 2022 to
      within a pixel. NAIP 2022 is kept as a fallback. Classes: water, bare, pasture,
      woods, with per-year thresholds.
      Inside the parcels, the clearing comes from the KwikImage drone photo of 11 Aug 2023
      (EXIF; confirmed by the owner), projected through the solved camera: 69% cleared, 22%
      woods, 9% pasture. NAIP July 2024 is newer, but at 0.6 m it reads the scraped ground as
      pasture, so the photo still defines the clearing.
- [x] Trees: 90,838 instances. 30,152 are measured StratMap 2025 lidar trees (source (a);
      position, height, crown radius; red cedar where the leaf-off evergreen score is
      ≥ 0.8) over the six near tiles. The rest are mask-scattered outside lidar coverage
      (source (c)). 19,374 lidar trees in the creek bottom are below pool and omitted. The
      creek preservation zone has no cleared cells and 555 measured trees.
- [x] Roads: CR 3635 (1.46 km of TxDOT centreline on terrain) and relocated CR 3640.
      SH 34 bridge marker.
- [x] Overlays: parcel and lot lines and labels in `Overlays_Review`. Scene lot areas
      match PTM within 0.0009 ac.
- [x] Check views: north-up lot plan, drone match, lake oblique. The drone camera was
      solved against PTM's survey-registered outline (29 px RMS at 2048 px); the roads
      line up with the photo.
- [x] Photo vs lidar inside the parcels. The drone photo (11 Aug 2023; first recorded
      here as "late 2024") predates the lidar (9 Dec 2025). A lidar object on ground the photo already shows
      cleared, with no woods within 15 m, cannot be a standing tree. These 51 objects sit
      on the photo's brush piles and are omitted. Lidar trees within 15 m of the photo's
      retained clumps are kept (the photo projection is registered to ~10 m; the camera
      is confirmed by `scripts/refine_drone_camera.py`).
- [ ] Known visual gaps for owner review: tree crowns are rounder and more uniform than
      real oaks; there are fewer small pasture cedars than the photo shows; pastures read
      beige rather than the photo's yellow-green.

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

**Status (14 Oct 2026):** H1 and H3 first drafts rendered
(`out/2026-10-14/H1_arrival_draft.png`, `H3_from_lake_draft.png`, captioned, with
sidecars). Look development so far:
- pasture grade toward the drone photo;
- a far-ground disc beyond the regional terrain;
- compositor aerial perspective (25 km visibility, fading toward the measured horizon
  sky colour).

Owner direction (14 Oct 2026):
- Cleared lots show as green grass in marketing shots (`cleared_ground: grassed`); check
  views keep the soil as photographed.
- Accurate flooded timber in the Fish and Wildlife zone matters more than tree realism.
  The zone is UTRWD's mapped "Fish and Wildlife Habitat" water-surface classification
  from the draft LSMP (16 Oct 2025, Appendix A). The plan states that timber in it "was
  left in place as fish and wildlife habitat". It covers the creek arm from CR 3640 to
  the main lake, plus a western side arm, about 51 ac. It was digitized by
  `scripts/digitize_fwh_zone.py`, registered to UTRWD's CR 3640 and TxDOT's CR 3635
  with about 8 m residuals. It is approximate: the map is a planning graphic, and UTRWD
  holds the official georeferenced version.
- 1,935 StratMap lidar trees below pool inside the zone (median water depth 2.7 m,
  maximum 11.4 m in the old channel) stand in the water. They are built as two
  switchable layers: `snags`, the default and the long-term look (permanently flooded
  oaks and elms die within a few seasons), and `leafy`, the first season after
  flooding.

Draft timing on the M4: H1 1920 × 1080, 96 samples, 15 s; H3 19 s. A first estimate for an
8K final (16× the pixels, 1024 samples) is about 40 min per frame, to be confirmed with a
tiled test render. H2 waits on foreground trees (free assets only, decided 14 Oct).

### Phase 2a — Baseline extensions (owner direction, 14 Oct 2026)

These go into the baseline so later stills, per-lot views and the flyover can all use them.

- [x] **Flooded timber after a season or two.** A `dying` layer (the marketing default)
      sits between `leafy` and `snags`: 974 of the 1,935 trees are dead snags and the rest
      have thin, browning crowns. See `out/2026-10-14/flooded_timber_stages.jpg`.
- [x] **Spanish moss** on 633 dead flooded trees, as a switchable layer
      (`spanish_moss`, render `--spanish-moss on`). Its
      native range in Fannin County is unconfirmed: Spanish moss is typical of East and
      Southeast Texas lakes such as Caddo Lake. It stays **off in published frames** until
      the owner confirms it occurs at Lake Ralph Hall. (Sphagnum is a ground and bog moss,
      not a tree moss.)
- [x] **SH 34 bridges.** Twin 13 m decks with parapets on the TxDOT SH 34 centreline,
      2.23 km over the lake, on 110 bents, with the deck at 178.9 m for about 30 ft of
      clearance. Approaches on grade. Schematic structure.
- [x] **Leon Hurse Dam surface.** Grey rock riprap on the lake face, gravel crest,
      grassed downstream face. The geometry stays schematic.
- [x] **Relocated CR 3640 west to SH 34.** 2.44 km: the TxDOT western approach plus
      UTRWD's Road Plan New Alignment, on grade with 2:1 fill slopes and a causeway over
      the creek arm (never below 169.3 m). It replaces the owner-directed line, which
      clipped 7.8 m into the parcels; UTRWD's line stays 6 m outside them.

### Phase 2b — Lot plan features (after Phase 2a)

Built 14 Oct 2026 as switchable layers (`redline`, `driveways`, `docks` in `shots.yaml`).
Review renders: `out/2026-10-14/check_lotplan_features_draft.png` (north-up) and
`H1_arrival_lotplan_draft.png`.

- [x] **Redline overlays.** Each CAD parcel outline in red, so the shared line between
      Lots 5 and 6 shows. A dashed red line marks the **proposed east–west parcel
      boundary** (owner is considering a re-survey with more regular lot shapes). It sits
      at y = −9.6 m, where each parcel keeps its CAD acreage (9.831 / 10.034 ac) and
      Lots 5 and 6 keep their areas (1.966 / 2.007 ac). Lot lines in white. Lot numbers sit on each lot's most open
      ground and turn to read upright from each shot's camera.
- [x] **Driveways.** One 4 m gravel driveway per lot, square to CR 3635, with trees cleared
      only on the driveway. Lot 2's frontage runs past the mapped road end, so its
      driveway leaves the road end and enters at the middle of the east frontage, then
      heads for the lot centre (owner). Lot 1 has no frontage on the mapped CR 3635: the TxDOT
      centreline stops at the bend south of it, though UTRWD maps show the road continuing
      north-west. Its driveway therefore runs from the mapped road end. **Owner to
      confirm Lot 1 access.**
- [x] **Docks, one per lot pair.** Revised per owner direction (14 Oct 2026):
      - The Lots 1–2 path (second revision) may start anywhere on Lot 1's north-facing
        boundary east of the middle of its north-west edge. It leaves square to the
        boundary and curves (quadratic Bézier) to the shore, and the dock aims at the
        deepest water within 150 m. The search keeps 300 ft from the Lots 3–4 site. The
        result starts near the top of Lot 1's north-west edge: an 86 m path to a 120 ft
        dock in 1.9 m of water.
      - Each access path is a 4 m mown-grass corridor with a 5 ft grey gravel trail. No
        tree stands in the corridor and no measured crown overhangs it (32 lidar trees
        removed), including through the creek preservation woods (owner-approved).

      Result: four docks, all passing the draft LSMP spacing and length rules
      (`docks_lsmp` in `baseline_checks.json`).

      | Pair | Length | Cove width | Depth at end (full pool) | Nearest dock | Path |
      | --- | --- | --- | --- | --- | --- |
      | 1–2 (curved path from Lot 1's north edge) | 120 ft | 182 m | 1.9 m | 355 ft | 86 m |
      | 3–4 | 120 ft | 192 m | 1.7 m | 314 ft | 70 m |
      | 5–6 | 120 ft | 206 m | 1.2 m | 314 ft | 64 m |
      | 7–8 | 103 ft | 94 m | 1.0 m | 411 ft | 99 m |
      | 9–10 | — | — | — | — | — |

      **Lots 9–10:** the arm in front of them is too narrow and shallow for a boat dock.
      Options: share the Lots 7–8 dock, a fishing/patio dock (33 ft maximum), or
      re-pair the lots. The docks stand in the no-wake, timbered habitat zone at
      1.0–1.7 m depth at full pool. Not checked: the Shoreline Management Zone
      classification at each site, the occupied-residence rule, and the UTRWD permit
      itself.

### Accuracy pass with the KwikImage aerials (15 Oct 2026)

Priority: flooded-timber and creek tree positions, which decide open versus obstructed
lake views from each lot.

- **Cameras.** Six KwikImage photos (11 Aug 2023) were solved from their GPS, altitude
  and gimbal data, refined by correlating the photo canopy with the lidar canopy
  (`scripts/kwik_ortho.py`). Each camera lands 1.4–3.6 m from its GPS fix and within
  6 m of its recorded altitude, with the lens at 25.1–25.4 mm (spec 25.0).
- **Timber positions confirmed.** 86–99% of the habitat-zone lidar crowns land on photo
  tree canopy in every view (about 48% by chance). The straight-down shot 24 shows no
  canopy offset between photo and lidar at 1 m resolution.
- **Crown sizes corrected.** In closed woods the lidar crown measure ran far wider than
  tree spacing (median radius 7.9 m at 5.8 m spacing), over-closing the stand. Radii
  are now capped at 1.13 × the nearest-neighbour distance, calibrated so crowns cover
  exactly the lidar canopy area (`scripts/calibrate_crowns.py`). The habitat-zone median
  is now 5.8 m.
- **Drone-match camera corrected.** The earlier outline-only solve sat about 140 m too far
  south-east and about 50 m too high, with a longer lens hiding the error. The GPS-anchored
  camera replaces it, and the clearing map was re-projected through it. The brush-pile
  tolerance dropped from 15 m to 4 m to match the better registration.
- Result: 1,912 flooded-timber trees; all baseline checks pass.

### Phase 2c — Owner drone capture (planned)

After mowing and dock-corridor clearing, the owner flies a mapping grid, oblique and
corridor passes, and reference stills. LRH processes them with photogrammetry,
registers them to the project frame and StratMap lidar, and updates the clearing,
trees and close-range textures. The plan, capture spec and import steps are in
[docs/DRONE-CAPTURE-PLAN.md](docs/DRONE-CAPTURE-PLAN.md). The DJI Mini 5 Pro's lidar
is for obstacle sensing only; the 3D scan comes from photogrammetry.

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
   spacing). **Owner decision, 14 Oct 2026: show one dock per pair of lots, plus the
   north-point dock (Phase 2b), each checked against the LSMP rules.** Dock images need
   a caption line such as "Docks subject to UTRWD Shoreline Use Permit". Pedestrian
   shoreline paths (5 ft max) are allowed.
4. **Homes.** **Empty, wooded, buildable lots.** Optional variant: the prior Perry
   lakehouse as one clearly labelled example home on one lot.
5. **Acreage figures.** The CAD polygon for 116505 is 0.39 ac smaller than the
   10.221 ac in the survey. **Quote acreage from the survey or plat, not from
   CAD-derived lot areas.**
6. **Pre-plat marketing.** The lots are not yet platted. **Before publishing
   lot-specific marketing, confirm with a Texas real-estate attorney or broker what
   Fannin County and Texas law allow** for advertising lots ahead of plat approval.
7. **Creek preservation zone.** **Always depicted wooded and uncleared**, except the dock
   access trails: 4 m mown corridors with 5 ft gravel paths (owner, 14 Oct 2026).

## 8. Working Rules

- **End-of-day delivery (carried from PTM BR-1):** each workday ends with a saved
  `out/YYYY-MM-DD/lrh_baseline.blend` and preview renders, ready for owner review.
- One commit per meaningful step. No binaries in git (`.blend`, renders, inputs, and
  assets are all ignored); scripts, configs, `inputs.lock.json`, `ASSETS.md`, and docs
  are committed.
- Never modify files in `../property-terrain-modeling-pipeline` or `../Ladonia` from
  this project.

Decided 14 Oct 2026: assets stay free/CC0 for now (no paid tree packs); revisit if H2
foreground trees fall short of `cam_02`.

Decided 14 Oct 2026: marketing timber is `dying` with Spanish moss (owner choice; the
owner was told its natural range at Lake Ralph Hall is unconfirmed).

## 9. Open Items

| Item | Owner | Needed by |
| --- | --- | --- |
| Section 7 decisions 2–6 | Owner | Before any publication |
| Optional: UTRWD's official georeferenced water-surface classification map, to replace the digitized draft LSMP outline | Owner (request from UTRWD) | Before publication |
| Lots 9–10 dock: **deferred by owner (14 Oct 2026), no action**; options remain share 7–8, fishing dock, or re-pair | Owner | When the owner revisits |
| Lot 1 driveway access (connects at the mapped CR 3635 end) | Owner | Phase 2b finals |
| Drone capture: Part 107 or a contracted pilot for marketing imagery; UTRWD permission to fly over its land and water (docs/DRONE-CAPTURE-PLAN.md §3) | Owner | Before Phase 2c flights |
| Commit or discard the uncommitted queue/sidecar changes in PTM | Owner | Any time (does not block LRH) |
