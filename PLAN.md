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

### Lot features and lake-view score (15 Oct 2026, owner direction)

- **Clearing.** Brush piles are omitted. Scrub under 4 m is cleared inside the parcels;
  the lidar finds none above its 3 m detection limit, and smaller scrub is not
  modelled. Honey locust cannot be told apart in the imagery or lidar; the owner may mark
  them for removal.
- **Per lot:** a driveway to a 10 m gravel turnaround with a mown island; a conceptual
  house site 35 m inside the lake-side line; and an access path to a cleared, mown circle
  (9 m radius, gravel pad) on a mown shoreline path that follows the 551 ft shoreline 4 m
  landward, in front of all lots. This uses the owner's understanding with UTRWD of a
  one-time riparian clearing of invasives and mowing; written approval is pending.
  Trees under the paths and circles are removed (104). The paired dock layout stays
  optional and clears nothing. Lot numbers are now 45% opaque.
- **Lake-view score** (`scripts/blender/lake_views.py`; `out/2026-10-15/lake_views.md`,
  `lake_views_panoramas.jpg`). It measures the share of the lake-facing 210° in which a
  sight line from the house site reaches open water:

  | Lot | 2nd floor (dying) | 2nd floor (snags) | Ground floor | Blocked by flooded timber | Blocked by shoreline woods |
  | --- | --- | --- | --- | --- | --- |
  | 1 | 5% | 15% | 4% | 16% | 68% |
  | 2 | 10% | 12% | 19% | 10% | 79% |
  | 3 | 10% | 18% | 14% | 29% | 61% |
  | 4 | 7% | 18% | 15% | 25% | 68% |
  | 5 | 12% | 21% | 13% | 23% | 64% |
  | 6 | 10% | 14% | 20% | 23% | 64% |
  | 7 | 12% | 16% | 10% | 18% | 60% |
  | 8 | 6% | 13% | 8% | 22% | 72% |
  | 9 | 4% | 4% | 9% | 8% | 82% |
  | 10 | 2% | 2% | 4% | 4% | 70% |

  Ground-floor values are optimistic: the model has no understory, so low sight lines
  pass under tree crowns.

### Lot 1 secluded build site and new views (15 Oct 2026)

- **Lot 1.** The driveway follows the CR 3635 continuation along the outside of Lot 1's
  road-facing edge, then turns in through the trees. It ends at a turnaround at the
  centre of Lot 1's measured trees, with a 14 m cleared house pad beside it (owner).
  Canopy is opened over every drive, turnaround and shoreline path, so they read from
  the air.
- **Views** (drafts in `out/2026-10-15/`, contact sheet `views_contact_sheet.jpg`):
  - the existing H1, H3 and V_west_to_dam, with driveways and shoreline features;
  - new: `L1_secluded` (low aerial of the Lot 1 build site), `L5_house_view`
    (second-floor eye level, morning) and `S_shore_path` (walking the shoreline path).
  - `S_shore_path` shows the limits of the flat-draped paths and procedural trees at
    walking scale; it is not ready for a cinematic final.

### Lake life and light (16 Oct 2026, owner direction: early fall, a skier)

- **Water:** wind ripples at three scales (swells, chop, fine ripples), so low sun makes a
  glitter path instead of a flat mirror; affects every view.
- **Ski boat and skier** (`scripts/blender/scene_life.py`, procedural): a 6.6 m boat, a 22 m
  rope and a skier, with a Kelvin-wedge wake and skier spray. It is placed per shot
  (`boat:` in `shots.yaml`), always on open main lake more than 100 m from shore: the
  draft LSMP makes water within 200 ft of shore no-wake, and the timbered arm is a no-wake
  habitat zone.
- **Gulls:** 14 ring-billed gulls (common on North Texas lakes October to March), placed
  per shot (`gulls:`). They read as birds within about 60 m of the camera and as specks
  beyond that.
- **Shots:**
  - `G_golden_hour`: from over the lake north-east of the property at 5:40 pm, into the
    sun, with the glitter path, skier and gulls. The lots are hidden behind the peninsula
    from any viewpoint where the glint, open water and boat line up.
  - `V_west_to_dam_life`: the west view, with the skier on the open lake beyond the lots
    and gulls near the camera.
- Haze toward the sun uses the all-around horizon colour (`haze_colour: all_azimuths`),
  so into-the-sun views are not bleached white.
- Ducks, herons and egrets wait for the close-range quality pass: they are sub-pixel at
  aerial distances.

### Phase 2d — Build sites, grading and shared access (in progress; owner direction, 19 Oct 2026)

**Goal.** Identify a raised build site on each lot. The home site goes in the front
(CR 3635) half, where the ground is highest, as is usual for properties in the area. The
lake-side half (about 1 ac per lot) stays open for lake views. A north–south access road
through the lots' midpoint is an option, with shared driveways and two larger shared
dock sites.

**What the terrain shows** (StratMap 2025 lidar, NAVD88, 1 m; per lot):

| Lot | Highest ground | Road-side half, mean | Lake-side half, mean | Road-side relief |
| --- | --- | --- | --- | --- |
| 1 | 574 ft | 568 ft | 564 ft | 12 ft |
| 2 | 578 ft | 574 ft | 565 ft | 9 ft |
| 3 | 583 ft | 578 ft | 568 ft | 10 ft |
| 4 | 584 ft | 580 ft | 569 ft | 10 ft |
| 5 | 587 ft | 580 ft | 568 ft | 25 ft |
| 6 | 593 ft | 585 ft | 569 ft | 17 ft |
| 7 | 599 ft | 587 ft | 568 ft | 22 ft |
| 8 | 603 ft | 590 ft | 569 ft | 25 ft |
| 9 | 604 ft | 591 ft | 570 ft | 26 ft |
| 10 | 605 ft | 584 ft | 566 ft | 44 ft |

The owner's ~600 ft high point near CR 3635 holds for Lots 7–10. The ground falls
northward to about 574 ft at Lot 1. Every lot's road-side half sits 5–21 ft above its
lake-side half, and every build site is more than 20 ft above the 551 ft pool. The 551 ft
label is not yet tied to NAVD88 (see the PTM notes), so treat freeboard as approximate.

**Owner decisions (19 Oct 2026)**
- **Pad:** 60 × 80 ft, leaving room for the house plus a detached garage or outbuilding.
- **House:** two storeys, as a raised "stilt" (beach-house) design. The ground level is
  storage, parking or an apartment, with the full home on the upper floor. A walk-out
  basement was considered but needs about 8–9 ft of fall across the pad. The best 80 ft
  fall on each lot's road-side half is 3–7 ft, and 9.3 ft on Lot 9 only.
- **Septic:** a target area **beside** the house, not lakeward of it, with gravity flow
  from the house to the treatment tank. Include a capped stub-out for future connection to
  a city or regional sewer line.
- **Shared utility corridor:** an informal local "utility easement" along the north–south
  access road, with common paths for water, the future sewer main, electric and internet.
- **Shared docks: tabled.** The owner wants to avoid the cost of a shared sewer facility.

**Wastewater rules found in the draft LSMP (Section 8) and Lake Zoning**
- Septic (OSSF) is allowed by the Lake Ralph Hall Zoning Regulations (7 Feb 2023) for
  single-family detached developments under 20 acres or under 20 lots. This property is
  19.87 ac with 10 lots.
- For an individual OSSF, the draft LSMP requires:
  - subsurface discharge only (spray is prohibited);
  - an annual maintenance contract with a licensed provider;
  - the drain field entirely on the owner's lot and at least 50 ft from UTRWD land;
  - a design for future connection to a centralized system, and connection once one is
    reasonably available.

  The owner's stub-out plan matches this.
- Drip systems are subsurface, so they qualify. TCEQ drip fields normally need pressure
  dosing from a pump tank. "Gravity" applies to the house-to-tank leg, which a raised
  house makes easy. The system type is for a licensed OSSF designer.
- **Key risk, beyond shared docks.** The draft LSMP issues Shoreline Use Permits (docks,
  access paths and, by implication, the shoreline clearing) only to properties that meet
  its Water Quality Protection Criteria. Those criteria prohibit OSSFs and require
  centralized sewer "if located within a subdivision with lots less than 5 acres." Platting
  ten ~2 ac lots on septic could block **individual** shoreline permits, not just
  community docks. The zoning exception and this criterion need reconciling with UTRWD and
  the owner's attorney before platting.

**Tasks**
1. **Build-site analysis.** Per lot, search the road-side half for a 60 × 80 ft pad.
   Rank candidate sites by:
   - elevation and how flat the ground already is;
   - distance from CR 3635 and the lot lines (setbacks to be confirmed with Fannin
     County);
   - trees that would need clearing;
   - the lake-view score from `lake_views.py`, at the stilt house's living-floor eye
     height (about 5.3 m above natural grade: 0.6 m pad, ~3 m ground storey, 1.7 m eye)
     and from an upper deck (about 8.5 m).
   Lot 1 keeps its secluded wooded site as an option.
2. **Grading plan.** Raise each pad about 2 ft, using cut from levelling elsewhere on the
   lot, so cut and fill balance on each lot.
   - Estimated fill: a 60 × 80 ft top raised 2 ft with 4:1 side slopes takes about
     450 cu yd in place, about 510 cu yd before compaction.
   - Outputs: a proposed-grade surface for each lot, with a cut/fill map, volumes and a
     drainage check (pads drain away from the house and toward the lake side, not onto
     CR 3635, the septic area or a neighbouring lot).
   - The grading is modelled in the terrain so renders show the raised pads.
   - Conceptual only; a civil engineer or surveyor designs the real grading.
3. **Septic target areas.** Per lot, a target drain-field area beside the house on the
   pad's side (not lakeward), at least 50 ft from UTRWD land, outside the pad and the
   drives, with a sewer stub-out line toward the access road corridor. Size from the
   house's bedroom count once known; the designer sets the final layout from a soil
   evaluation.
4. **Open lake-side acre.** Keep the lake-side half of each lot clear of structures in the
   model, as mown grass and retained trees, and re-score lake views from the new sites.
5. **Shared access and utility corridor** (a switchable layer):
   - a north–south gravel access road through the lots' east–west midpoints, between the
     build sites and the open lake-side acre, with shared driveways off CR 3635 serving
     pairs of lots;
   - the utility corridor alongside it, carrying water, the future sewer main (stub-outs
     from each septic area), electric and internet;
   - easements shown as conceptual; they need survey and legal drafting.
6. **Shared dock sites: tabled** (owner, 19 Oct 2026). The per-pair dock layer stays
   available but is not developed further.
7. **Renders:**
   - a north-up plan with pads, outbuilding space, septic areas, access road and utility
     corridor;
   - aerials of the raised pads with simple massing for a stilt house and a detached
     garage, clearly labelled as illustrative;
   - all with the §7 caption.

**Owner parameters for initial review (19 Oct 2026, house program revised the same day)**
- Setbacks: 100 ft from CR 3635, 20 ft from side lot lines.
- **House, all lots:** a lake-house / rustic cabin with 2 BR / 1 bath upstairs and an
  optional 1 BR / 1 bath apartment on the ground floor, with boat storage and parking.
  Septic is sized for the full 3 bedrooms: about 240 gal/day under TCEQ Chapter 285. The
  drip area is a 4,000 sq ft placeholder on clay soils (80 × 50 ft; 100 × 40 ft on the
  60 × 40 ft pad) until a soil evaluation is done.
- **Septic in front:** tank and drip area on the road side of the house, on every lot.
- The front drive may reach the front or the side of the house. A second, rear entry from
  the shared access road allows drive-through with a boat or RV.
- **Constrained lots:** the same house program on a 60 × 40 ft pad, wherever the standard
  pad does not fit; today that is Lot 10 only.
- **Style:** massing and any later house models follow the cabin style, for example
  board-and-batten or log-look siding, metal roofs, deep covered porches and timber or
  stone piers under the raised floor.
- **Cabin design reference (owner, 19 Oct 2026):** Satterwhite Log Homes' Hemlock plan
  (`inputs/reference/hemlock-photo-04.jpg`;
  satterwhite-log-homes.com/floor-plans/hemlock). The Hemlock has a 1,260 sq ft main
  floor, 723 sq ft of porches, a 379 sq ft loft and a walk-out terrace level. The model in
  `scripts/blender/cabins.py` follows it:
  - a 30 × 42 ft main floor in honey-tone logs;
  - a steep (10:12) brown-grey shingle roof with its ridge east–west, so the glazed gable
    faces the lake;
  - the roof carried over a 10 ft lake deck on posts with Y-brackets and an exposed truss;
  - an 8 ft front porch along the south side with three gable dormers, and dark green
    window trim;
  - a terrace level with the optional apartment toward the lake and a boat or parking door
    on the road end;
  - stairs from the front porch and from the lake deck down to the patio.

  Test shots: `C5_cabin_sunset` (lake gable, open lot), `C2_cabin_sunset` (wooded
  clearing, lidar trees) and `check_cabin5_back` (road side).

**Hemlock dimensions** (Satterwhite's published floor plans):
- **Main level:** 30 × 42 ft with an 8 × 30 ft gable porch, a 6 × 50 ft porch on one long
  side and a 4 × 50 ft porch on the other. It holds the master bedroom, kitchen, dining
  room, an 18 × 18 ft great room vaulted to the gable, 1½ baths, and a loft bedroom above.
- **Terrace level:** the same 30 × 42 ft footprint. At the lake end: an 11 × 12 ft bedroom,
  a 6 × 10 ft bath and an 18 × 18 ft rec room, opening onto an 8 × 30 ft covered porch.
  At the uphill end: mechanical/storage (16 × 19 ft) and storage (13 × 19 ft).

The terrace level carries the owner's optional 1 BR / 1 BA apartment. Its storage is
tucked into the hill, with a boat / storage door added on the north side.

**Walk-out built into the slope** (owner, 19 Oct 2026; `scripts/blender/grading.py`,
`build_sites.py` `walkout()`):
- **Terrace floor:** 6 in above natural grade along the lake wall, so the lake end walks
  out at grade.
- **Road end:** backfilled 5 ft against a concrete back wall.
- **Side walls:** concrete stepping down toward the lake, faced with stone where they
  show.
- **Yard levels:** the side yards slope from the lake terrace up to the entry yard. The
  entry yard on the road side sits 5.5 ft below the main floor, so the front stair is
  short.
- **Earthwork:** the natural fall across the house is only 1–3½ ft, so most of the
  backfill is imported or borrowed from the lot.

**Septic with the walk-out:**
- **Tank in front:** with 5 ft of earth against the road-side wall, a front tank would need
  its inlet about 6½ ft deep. That means a deep-bury tank, or an ejector pump for the
  downstairs bath.
- **Tank beside the house:** the model puts the tank in the south side yard at the lake end
  instead, where grade is near the floor. The downstairs bath drains to it by gravity
  (inlet 1.9 ft deep, about 28 ft of sewer).
- **Drip field:** stays in front, dosed by the tank's pump chamber. TCEQ drip systems are
  pump-dosed anyway.

| Lot | Natural grade, lake wall | Natural grade, back wall | Terrace floor | Main floor | Back-yard grade | Fill / cut | Side tank inlet depth | Front tank would need |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 565.7 ft | 566.6 ft | 566.2 ft | 576.7 ft | 571.2 ft | 673 / 8 cu yd | 1.9 ft | 6.5 ft |
| 2 | 573.7 ft | 573.4 ft | 574.2 ft | 584.7 ft | 579.2 ft | 632 / 3 cu yd | 1.9 ft | 6.5 ft |
| 3 | 577.7 ft | 579.3 ft | 578.2 ft | 588.7 ft | 583.2 ft | 379 / 99 cu yd | 1.9 ft | 6.5 ft |
| 4 | 578.8 ft | 580.0 ft | 579.3 ft | 589.8 ft | 584.3 ft | 395 / 22 cu yd | 1.9 ft | 6.5 ft |
| 5 | 580.9 ft | 582.6 ft | 581.4 ft | 591.9 ft | 586.4 ft | 371 / 24 cu yd | 1.9 ft | 6.5 ft |
| 6 | 583.0 ft | 585.9 ft | 583.5 ft | 594.0 ft | 588.5 ft | 291 / 58 cu yd | 1.9 ft | 6.5 ft |
| 7 | 587.6 ft | 590.5 ft | 588.1 ft | 598.6 ft | 593.1 ft | 289 / 59 cu yd | 1.9 ft | 6.5 ft |
| 8 | 590.2 ft | 593.7 ft | 590.7 ft | 601.2 ft | 595.7 ft | 225 / 60 cu yd | 1.9 ft | 6.5 ft |
| 9 | 591.6 ft | 592.5 ft | 592.1 ft | 602.6 ft | 597.1 ft | 394 / 8 cu yd | 1.9 ft | 6.5 ft |
| 10 (Hemlock does not fit this pad) | 582.2 ft | 585.4 ft | 582.7 ft | 593.2 ft | 587.7 ft | 133 / 46 cu yd | 1.9 ft | 6.5 ft |

**Structure (conceptual; for the builder and a structural engineer):**
- **Foundation:** Satterwhite builds any plan on a basement, given the required structural
  elements. The walk-out here is that basement, partly above grade: footings, a cast
  concrete back wall and side walls, and log walls above them.
- **Porches:** the porches and the covered terrace stand on concrete piers on footings, with
  round log posts above. This is the "stilt" structure, with log accents.
- **Soils:** on Fannin County's expansive clays, drilled concrete piers with grade beams are
  common. A geotechnical report sets the foundation type.
- **Back wall:** the backfilled wall needs waterproofing, a footing drain and an uphill
  swale.

**Stairs, Hemlock style:**
- **Lake stair:** a switchback tucked alongside the south porch's lake end. A top landing
  leads to a flight running along the porch, a mid landing on posts, and a flight back
  down to the lake terrace.
- **Front stair:** a short run with a top landing at the porch's east end, down to the
  entry yard.

**Septic Option B and private utility easement** (owner, 19 Oct 2026; `build_sites.py`
`lake_option()`, plan `out/2026-10-19/build_sites_plan_option_b.png`; Option A, the field
in front, stays in `build_sites_plan.png`). Showing these in the site plan keeps later
trenches and fields out of random locations.
- **Private utility easement (both options):** 20 ft wide on each lot. It runs from the
  house's treatment tank (south side yard) to the lot's south line, then along it to the
  west edge. It holds two trenches about 10 ft apart, because potable water stays away
  from effluent lines:
  - trench 1: the gravity effluent line to the dose tank, plus the pump's power and alarm
    conduit (Option B);
  - trench 2: PEX water, at least one power circuit and a spare conduit, out to a utility
    pedestal (frost-free hydrant, outlets).
- **Recreation site:** a 40 ft site at the west edge for picnics or rough camping. It is
  kept at least 10 ft from the field.
- **Option B drip field:** 4,000 sq ft on the lowest workable ground of the lake-side acre.
  It sits at least 50 ft from UTRWD land (draft LSMP), 10 ft from lot lines, the easement
  and the rec site, west of the access road, and clear of the house apron and the lot
  label. The field is buried and mown, so the lake-side acre stays open.
- **Dose tank:** sits beside the field. The treatment tank drains to it by gravity. The dose
  tank's pump pressurises the drip field, as TCEQ drip rules require.

| Lot | Easement, house to west edge | Field ground (mean) | Fall, tank outlet to field high side | Effluent line | Field to UTRWD land |
| --- | --- | --- | --- | --- | --- |
| 1 | 238 ft | no field fits (house site lower than the lake-side acre) | | | |
| 2 | 326 ft | 564.7 ft | 6.2 ft | 242 ft | 79 ft |
| 3 | 330 ft | 568.6 ft | 5.8 ft | 271 ft | 107 ft |
| 4 | 372 ft | 568.4 ft | 7.3 ft | 304 ft | 107 ft |
| 5 | 400 ft | 568.0 ft | 9.7 ft | 273 ft | 105 ft |
| 6 | 477 ft | 567.4 ft | 12.8 ft | 334 ft | 121 ft |
| 7 | 507 ft | 565.6 ft | 18.3 ft | 381 ft | 101 ft |
| 8 | 504 ft | 567.2 ft | 19.3 ft | 394 ft | 108 ft |
| 9 | 461 ft | 569.3 ft | 18.2 ft | 405 ft | 66 ft |
| 10 | 611 ft | 564.6 ft | 14.1 ft | 302 ft | 52 ft |

- **Outages:** the fall does not make the drip field itself gravity-fed, because emitters
  need pressure. It keeps the long line by gravity and the pump lift small. The pump tank's
  reserve above the alarm level carries a day or so with careful water use, and a generator
  inlet or small battery backup covers longer outages. With 12–19 ft of fall (Lots 6–10), a
  dosing siphon to a low-pressure field is worth asking the designer about. Gravity
  trenches are unlikely on this clay.
- **To confirm:** TCEQ and County setbacks to the lake and to any UTRWD flood or flowage
  easement (the reservoir's flood-pool elevation is not yet in the project). Also UTRWD's
  view of lake-side fields on a water-supply reservoir, and the open LSMP question on
  septic for lots under 5 ac. The Lot 8 field sits in a tree clump that would need
  clearing.
- **Lot 1:** the secluded house site is lower than its lake-side acre, so Lot 1 keeps the
  field near the house. Its easement still reaches the west edge.
- **Fallback if a lake-side field runs into trouble** (owner, 19 Oct 2026): move the house
  pad farther toward CR 3635. That gains both space and fall for the field. On Lots 2–9
  the pads already sit at the 100 ft initial-review setback (98–107 ft from the road-side
  lot line), so this needs a smaller road setback confirmed with Fannin County. Each 25 ft
  closer adds 25 ft of room on the lake side and, at these lots' slopes, very roughly
  0.5–2 ft of fall. Lot 1 (122 ft) and Lot 10 (222 ft) have room within the current
  setback.

**Lot 10:** the Hemlock footprint (and its porches) does not fit the 60 × 40 ft pad. Lot
10 is left without a cabin in the model until a smaller plan is chosen or the re-survey
enlarges the lot.

**Gravity check for a downstairs bath.** The septic is in front, on the road side, where
the ground is higher. So the check is whether a ground-floor bath on the raised pad can
still drain by gravity to a tank there. Planning assumptions:
- the bath floor is at pad top, and the building drain leaves 1 ft below the floor;
- the tank sits on undisturbed ground just past the fill toe, about 21 ft of sewer from
  the house;
- the sewer falls at least 1/8 in per ft;
- a standard tank's inlet is no more than 3 ft below grade, with at least 1 ft of cover.

Any extra depth would be reported as extra pad height. Upstairs fixtures have ample fall.
A pump tank doses the drip field in any case, so the drip area's own elevation does not
matter.

**Results (`scripts/build_sites.py`, plan drawn by `scripts/plot_build_sites.py`
→ `out/2026-10-19/build_sites_plan.png`)**

| Lot | Site | Natural ground | Pad top | Fill, in place / loose | Trees on pad | Front drive | Rear drive | Floor above ground at tank | Tank inlet depth | Downstairs bath by gravity |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Secluded wooded site (inside the road setback) | 565.9 ft | 567.9 ft | 653 / 751 cu yd | 2 | 264 ft | none | +1.3 ft | 1.0 ft | yes |
| 2 | Road-side half | 573.3 ft | 575.3 ft | 469 / 539 cu yd | 6 | 158 ft | 34 ft | +1.7 ft | 1.0 ft | yes |
| 3 | Road-side half | 578.6 ft | 580.6 ft | 547 / 629 cu yd | 0 | 141 ft | 70 ft | +1.8 ft | 1.0 ft | yes |
| 4 | Road-side half | 579.2 ft | 581.2 ft | 481 / 553 cu yd | 0 | 141 ft | 81 ft | -0.2 ft | 1.4 ft | yes |
| 5 | Road-side half | 581.3 ft | 583.3 ft | 516 / 593 cu yd | 0 | 147 ft | 90 ft | +0.8 ft | 1.0 ft | yes |
| 6 | Road-side half | 583.8 ft | 585.8 ft | 584 / 672 cu yd | 0 | 140 ft | 108 ft | -0.3 ft | 1.5 ft | yes |
| 7 | Road-side half | 588.5 ft | 590.5 ft | 603 / 694 cu yd | 0 | 139 ft | 125 ft | -0.2 ft | 1.4 ft | yes |
| 8 | Road-side half | 591.4 ft | 593.4 ft | 605 / 695 cu yd | 1 | 145 ft | 137 ft | -0.9 ft | 2.1 ft | yes |
| 9 | Road-side half | 591.9 ft | 593.9 ft | 557 / 641 cu yd | 4 | 143 ft | 162 ft | +0.3 ft | 1.0 ft | yes |
| 10 | Road-side half, **60 × 40 ft pad** | 583.6 ft | 585.6 ft | 345 / 397 cu yd | 3 | 266 ft | 85 ft | -1.3 ft | 2.6 ft | yes |

- **No lot needs extra pad height for a downstairs bath.** The 2 ft raise gives enough fall
  everywhere. Lot 10 is tightest: the ground at its tank is 1.3 ft above the pad, so the
  inlet is 2.6 ft deep, with 0.4 ft to spare. Lot 8 has 0.9 ft to spare. Moving a tank
  farther from the house adds about 0.1 ft of depth per 10 ft of sewer. On Lots 8 and 10,
  if the designer needs the tank much farther out, plan on a few more inches of pad, a
  deeper-rated tank, or an ejector pump for the downstairs bath.
- The access road runs about 1,338 ft from Lot 2 south to CR 3640, with the utility
  corridor along it. Owner, 19 Oct 2026: the midpoint rule is relaxed. The road follows a
  gentle curve fitted through the midpoints of Lots 2–9, then runs straight south across
  Lot 10 to CR 3640 instead of angling southwest across it. On Lot 10 it uses 112 ft of
  length (about 0.09 ac of the 35 ft road and corridor). That leaves 0.74 ac east of the
  road for the house and 1.18 ac to the west, open toward the lake. Each septic area has a sewer stub toward the corridor.
- Every lot has its own front drive from CR 3635, with no connector along the road. The
  mapped CR 3635 centreline stops at the bend by Lot 2, so Lot 1's drive leaves its own
  frontage straight out to the road's continuation.
- Siting prefers the road-side half over house size: a small house in the front half
  beats a standard house pushed onto the low lake side.
- **Lot 10:** as a corner lot, 100 ft setbacks from both CR 3635 and CR 3640 leave about
  57 ft of depth, under the standard pad's 60 ft. It takes the small house (owner, 19 Oct
  2026). A smaller CR 3640 setback (Fannin County) or the planned re-survey could restore
  the standard pad.
- **Lot 1:** the road-side half is inside the setback or too low, so the secluded wooded
  site is kept.
- Fill per lot is 345–653 cu yd in place. Cut is assumed to come from levelling elsewhere
  on the same lot; no cut/fill surface has been modelled yet.

**Still open:** whether the access road and utility corridor appear in
marketing images or stay planning-only.

### Phase 2c — Owner drone capture (planned)

After mowing and dock-corridor clearing, the owner flies a mapping grid, oblique and
corridor passes, and reference stills. LRH processes them with photogrammetry,
registers them to the project frame and StratMap lidar, and updates the clearing,
trees and close-range textures. The plan, capture spec and import steps are in
[docs/DRONE-CAPTURE-PLAN.md](docs/DRONE-CAPTURE-PLAN.md). The DJI Mini 5 Pro's lidar
is for obstacle sensing only; the 3D scan comes from photogrammetry.

### Phase 3a — Low-altitude drone flyover, refined toward photoreal (planned; owner direction, 19 Oct 2026)

**Goal.** A drone-style flyover close to the ground, about 50–150 ft up, over the lake,
the flooded timber, the shoreline and the lots, past a cabin at golden hour. It starts
rough and is refined in stages until the frames are photoreal enough for marketing video.

**Method: fixed benchmark frames.** Pick seven frames from the approved flight path. They
are re-rendered at the end of every refinement stage and put side by side with the
previous stage, so progress is visible and regressions are caught. Each stage ends with
an owner review, about 1–2 hours of work and render per checkpoint (owner, 15 Oct 2026).

**Draft flight path** (about 75–90 s; owner to approve in R0):
1. Over the open main lake at about 40 m, low sun behind or to the side, the ski boat
   below. Glide toward the timbered arm.
2. Down to about 20 m over the flooded timber (the Fish and Wildlife Habitat zone stays
   wooded) and along the arm.
3. Across the mown shoreline path at a lot's dock circle, then up the
   open lake-side acre.
4. A slow reveal of the Lot 5 cabin's glazed gable, porch and fire-pit patio, with a
   partial orbit.
5. South along the row of lots at about 30 m. Finish rising over CR 3635, looking back
   west to the lake at sunset.

Path rules:
- The existing `flyover.py` machinery: spline, arc-length pacing, ease in and out, tilt
  cap, per-frame blank-frame checks.
- New clearance checks: at least 15 m above ground and at least 8 m from any lidar tree
  crown, every frame.
- Turn rates no faster than the approved oval (about 4.3°/s); drone speed 8–12 m/s.
- Under 400 ft above ground, so it reads as a real drone.

**Benchmark frames:**

| Frame | What it shows | Height |
| --- | --- | --- |
| B1 | Open lake, boat and glitter path | 40 m |
| B2 | Flooded timber close by, moss, ducks later | 20 m |
| B3 | Shoreline path and dock circle | 15–20 m |
| B4 | Lake-side acre looking east to the cabin | 20 m |
| B5 | Cabin, porch and patio up close | 15 m, about 40 m away |
| B6 | Along the lots | 30 m |
| B7 | Over CR 3635 looking west at sunset | 45 m |

**Refinement stages** (each ends with the benchmark contact sheet and owner review):
- **R0 — Path and animatic.**
  - Work: design the path with the clearance checks. Render a fast, rough animatic of the
    whole path at 960 × 540 and very low samples (about an hour).
  - Accept: the owner approves the route, pacing and height.
- **R1 — Rough baseline.**
  - Work: render B1–B7 at 1080p draft quality with today's assets.
  - Accept: this becomes the reference sheet the later stages are measured against.
- **R2 — Ground near the camera.**
  - Work: grass scattered in clumps along a corridor about 150 m either side of the path,
    thinning with distance. Separate mown lawn, pasture and riparian looks. Fine terrain
    detail to remove the faceting, gravel and soil textures, and a wet edge at the
    shoreline.
  - Accept: at 15–20 m above ground, B3–B5 read as grass, with no tiling or facets.
- **R3 — Trees near the camera.**
  - Work: better post oak, cedar elm, eastern red cedar and bois d'arc models, with bark
    texture and leaf-card crowns. Detailed models within about 120 m of the path, the
    current instanced trees beyond. Gentle wind sway. Sources: free tools only (Blender's
    Sapling tree generator, CC0 textures and models from Poly Haven or ambientCG).
  - Accept: no blob crowns in B2–B5. The lidar tree positions are unchanged.
- **R4 — Sky and light.**
  - Work: clouds, from a CC0 sky photo matched to the sun position or a volumetric cloud
    layer. The physical sun stays as the key light. Golden-hour and sunset variants.
  - Accept: the mood of the owner's sunset reference (`benchmark-cam02-sunset.jpg`).
- **R5 — Water.**
  - Work: near-field ripple detail, reflections of the timber and the shore, a wet line
    and light foam at the edge, a finer boat wake.
- **R6 — Cabin and site detail.**
  - Work: CC0 photo textures for the logs, stone, shingles and flagstone. Warm interior
    glow. Porch props (rockers, hanging ferns), a split-rail fence (Hemlock photos), and
    dusk lighting.
- **R7 — Life and motion.**
  - Work: ducks in the timber, herons and egrets on the edge, gulls and the boat. Tree and
    grass wind, and motion blur.
- **R8 — Production.**
  - Work: a flicker test on a 2-second segment (denoiser fed albedo and normal passes).
    Then a 1080p preview master, then the 4K30 master. Caption, MP4 encode.

**Compute budget** (measured: the 60 s oval flyover at 1080p and 64 samples took 8.5 h,
about 17 s a frame on this M4):
- With grass and detailed near-field trees, expect about 40–90 s a frame.
- A 90 s video at 30 fps is 2,700 frames: roughly 30–70 h at 1080p, and 3–4× that at 4K.
- So iterate on stills and the low-resolution animatic. Render a 1080p preview master
  overnight, resuming across nights (`flyover.py` resumes). Render 4K only for the
  approved cut.
- 24 fps would save 20%.
- A paid cloud render farm is an owner decision if 4K turnaround matters.

**Marketing decisions needed before R8** (§7):
- Whether the video shows one illustrative cabin (Lot 5) or a build-out of all lots.
- Whether the access road and utility easements appear (default: no, planning only).
- The time of day.

The usual rules apply: no overlays, the creek zone stays wooded, and the caption
is shown.

**R0 status (19 Oct 2026):**
- **Path script:** `scripts/flight_path.py` designs the path. It writes
  `out/derived/flight_low.json` and `flight_low_plan.png`.
- **Checks:** the path passes.
  - Height: at least 19 m above the ground or lake, and at least 15 m above the canopy.
  - Turns: pans at most 9.9°/s (a gentle drone pan, allowed up to 10°/s at this height).
  - Tilt and altitude: down-tilt at most 20°; at most 145 ft above the ground; at most
    16 m/s.
- **Length:** about 114 s, longer than the 75–90 s target; pacing is for the owner to judge.
- **Render mode:** `flyover.py --variant low` renders it. `--preview` gives the animatic
  (960 × 540, 8 samples, every third frame at 10 fps, about 2 s a frame).
- **Shown:** the Lot 5 cabin and a simple 5 ft gravel walking path. The path runs from the
  lake stair to the lot's shoreline access path (owner: simple walking paths for now).

**R0 preview and R1 baseline (19 Oct 2026):**
- **Animatic:** `out/2026-10-19/video/low_preview/flyover_low_preview.mp4`, 1,136 frames
  in 35 min.
- **R1 benchmark sheet:** `out/2026-10-19/video/benchmarks_R1.jpg`, frames 45, 545, 1463,
  1699, 2152, 2917 and 3360. At 1080p and 64 samples they take 10–21 s a frame, about
  the same as the oval flyover.
- **Gaps to fix in R2–R4:**
  - the ground is flat and blotchy near the camera (B3, B4, B6, B7);
  - near trees have blob crowns (B2, B3, B6);
  - the sky is a clear gradient with no clouds;
  - views into the sun (B6, B7) are washed out.

**R0 revision (owner, 19 Oct 2026): start at the point of beginning.**
- **Start:** the video starts over the signed survey's point of beginning on the CR 3635
  centreline. As fitted to the TxDOT centreline it is at LRH (114.5, −46.7); the model's
  parcel corner is 10 m west.
- **Route:**
  1. Look west across the lots.
  2. Sweep past the Lot 5 cabin's covered parking and front porch, and along its south
     side to the lake gable and patio.
  3. Follow the walking path down to the shoreline circle.
  4. Run north over the flooded timber.
  5. Finish over the open water, turning back toward the lots.
- **Length and checks:** about 94 s (owner agreed to about 90 s); the path passes its
  checks. Height is at least 19 m above the ground or lake, 14 m above the canopy, and at
  most 144 ft. Pans are at most 9.9°/s, with gimbal smoothing over 2 s.
- **Time of day:** golden hour (agreed).
- **Previous run:** the first route's preview and R1 frames are kept in
  `out/2026-10-19/video/low_preview_r0a/` and `low_r1a/`.
- **New preview and R1 baseline:**
  - `out/2026-10-19/video/low_preview/flyover_low_preview.mp4`: 938 frames in 30 min.
  - `benchmarks_R1.jpg`: frames 45, 511, 687, 1224, 1389, 1916 and 2767, at 11–18 s a
    frame (1080p, 64 samples).
  - Pacing note for review: around frame 750 the view is mostly open lawn, between the
    lake gable and the walking path.

**Covered parking (owner, 19 Oct 2026; until the architectural design is final):**
- **Placement:** a 22 × 24 ft concrete slab at the end of the drive, off the cabin's
  south-east corner, level with the entry yard. The grading includes it.
- **Structure:** log posts on concrete piers with Y-brackets, a pitched (8:12) shingle
  roof with its ridge east–west, board-and-batten gables and an open truss toward the
  drive, matching the house.
- **Walks:** concrete walks from the parking to the front stair (front porch and door),
  and along the south side yard to the lake-side switchback stair.
- **Driveway:** each lot's drive now ends at its parking slab.
- **Septic:** on Lots 3 and 4 the slab leaves too little room for the Option A field in
  front, so Option A goes beside the house there. Option B (lake-side) is unaffected.

**Owner changes, 20 Oct 2026:**
- **Brush piles burned and levelled.** `scripts/brush_piles.py` finds the piles as lidar
  ground mounds, which match the grey-lilac blotches in NAIP 2024. It finds 18 mounds,
  0.7–1.6 m high, inside the parcels. The build flattens the site terrain to each pile's
  surrounding grade (feathered over 3 m) and grasses the footprints in the ground mask
  (`out/derived/ground_mask_leveled.png`). The 11 lidar "brush pile" objects were already
  left out of the trees.
- **Flooded timber after Bois d'Arc Lake.** The reference is NAIP 2024 at 33.6595 N,
  96.0561 W, about two seasons after impoundment, saved in `inputs/reference/`.
  - The dying stage now has a dead interior: a twiggy mauve-grey canopy on grey trunks
    (1,678 trees).
  - A patchy rust-brown fringe of dying trees runs along the waterline (237 trees, in
    water shallower than 1.2 m).
  - Side-by-side: `out/2026-10-20/timber_vs_bois_darc.jpg`; check shot
    `check_timber_aerial`.
  - Renders now allow 32 transparent bounces, because sparse crowns stack many cut-out
    cards.
- **Spanish moss cut by more than half:** from about a third of the dead trees to about
  an eighth (256 trees), because moss takes years to establish.

**R2 — Ground near the camera (20 Oct 2026; comparison `out/2026-10-20/video/benchmarks_R1_vs_R2.jpg`):**
- **Ground material:** lightness variation at about 0.6 m and 10 cm, occasional dry straw
  patches, a fine bump, and a shaded sward base wherever grass tufts stand.
- **Grass tufts** (`scripts/blender/ground_detail.py`, collection `Ground_Detail`):
  - mown-pasture clumps, 26 blades, 4–5 in tall, plus about 5% seed-head clumps;
  - up to 22 per m² within 40 m of the flight path, fading by 200 m; about 2 million
    instances;
  - none below pool, on roads, drives, walks or shoreline paths, or on a shown cabin's
    lawn apron. Each lot's apron grass is its own scatter, so it switches off with that
    lot's cabin;
  - the scatter follows the evaluated, graded terrain, with a fixed seed so nothing
    flickers.
- **Cabin lawn:** mown with 1.5 m stripes, toned to sit in the pasture.
- **Timber after review:** the rust fringe was toned toward brown and thinned to 171 trees,
  because it read too red at golden hour.
- **Render cost:** about 34 s a frame at 1080p and 64 samples (R1: 11–18 s). At that rate
  the 94 s flyover is about 27 h at 1080p.

**Cabin site finishes (owner, 20 Oct 2026):**
- **Driveway and shore walk:** gravel (crushed limestone).
- **Covered parking:** concrete slab.
- **Concrete:** broom-finished with tooled control joints every 10 ft, on the slab, the
  walks, the stair landing pads and the walk-out patio.
- **Walk-out patio:** concrete under the gable porch, 8 ft beyond it, and under the south
  porch's lake end, so the switchback stair lands on it.
- **Fire-pit area:** a decomposed-granite circle about 20 ft across with steel edging,
  joined to the patio. The patio and circle are graded level with the walk-out
  (`grading.layout` "patio", "firepit", "terrace_flat").
- **Landscaping:**
  - mulched foundation beds along the front porch and at the patio's lake corners;
  - dwarf yaupon-style rounded shrubs and pink muhly grass;
  - three pink crape myrtles: two at the patio corners and one in the south yard by the
    front walk;
  - two fruiting pears flanking the drive, with red fall colour.
- **Check shots:** `check_cabin5_walkout` and `check_cabin5_parking`.

**Owner changes, 20 Oct 2026 (afternoon):**
- **Finishes:** the log, timber, board-and-batten and trim stain is darker and redder. The
  driveway gravel is darker, and the decomposed granite is browner.
- **Garden and orchard terraces** below the fire-pit terrace (`build_sites.py`
  `garden_terraces()`, `grading.terrace_boxes()`, `cabins.py` `garden_terraces()`):
  - **Layout:** up to three terraces about 20 ft wide (east–west) across the walk-out
    terrace's north–south extent. They run as far west as 2 m short of the access-road
    corridor, at most 18 m.
  - **Steps:** each drops 1–2 ft toward natural grade, with a dry-stacked stone retaining
    wall, stone steps on the centre line, and a decomposed-granite centre path.
  - **Upper terrace:** a vegetable garden of four cedar raised beds with fall greens and
    peppers, plus pumpkins.
  - **Lower terraces:** a small fruit orchard (peach/apple) in two rows about 11 ft apart,
    with mulch rings.
  - **Shore path:** the gravel walk to the shoreline now starts from the bottom terrace.
  - **Option B:** lake-side drip fields keep 3 m clear of the terraces and still fit on
    Lots 2–10.
  - Check shot: `check_cabin5_terraces`.

| Lot | Terraces | Levels (ft) |
| --- | --- | --- |
| 1 | 3 | 564.6, 563.6, 562.6 |
| 2 | 0 | — |
| 3 | 1 | 576.6 |
| 4 | 2 | 578.0, 577.0 |
| 5 | 2 | 579.5, 578.5 |
| 6 | 3 | 581.4, 580.4, 579.4 |
| 7 | 3 | 586.5, 584.6, 582.6 |
| 8 | 3 | 589.0, 587.5, 585.9 |
| 9 | 3 | 589.9, 588.0, 586.0 |
| 10 | 1 | 580.7 |

  Lot 2 has no room (the access road passes close); Lot 1 (no corridor) has three.

**R3 start, beaches and docks (owner, 20 Oct 2026):**
- **Scanned trees** (CC0 Poly Haven, fetched by `scripts/fetch_assets.py` into `assets/`,
  recorded in `assets.lock.json` and ASSETS.md):
  - `island_tree_01` for post oak, `tree_small_02` for young oaks, `jacaranda_tree` for
    cedar elm and bois d'arc;
  - they replace the procedural crowns for lidar trees within 160 m of the low flight path
    (`trees.load_photoreal`), 719 trees;
  - the planted oak, water oak, pecan and sycamore use them too;
  - bamboo is rebuilt as slender culms with leaf sprays; eastern red cedar and the pine
    stay procedural for now;
  - frames take about 30–90 s at 1080p.
- **Beaches** (`scripts/blender/beach.py`, layer `beach`): each lot's mown shoreline circle
  is replaced by a sand beach running down to the water. Each has an umbrella, a picnic
  table, two Adirondack chairs, a canoe and two kayaks. A beach shifts along the shore to
  stay 17 m clear of a dock.
- **Docks** (`docks`): the four paired docks from Phase 2b, now in muted composite decking.
  - **Riprap:** a band 10 ft past each side of every gangway at the waterline (draft LSMP
    §4.1.3: at least 10 ft of non-vertical protection each side).
  - **Boats:** a ski boat or pontoon moored in each slip, and a kayak on each walkway.
  - **Lake plan rules already met (§6.2–6.3, App. D):**
    - length within 120 ft and 1/3 of the cove width, 300 ft spacing;
    - slips in at least 3 ft of water (1.0–1.9 m);
    - walkway 3–6 ft wide, gangway perpendicular to the shore.
- **Flyover:** the low variant now includes beaches and docks, and `check_beach_dock` is
  the review still. CLAUDE.md now allows docks in marketing frames (owner); `caption_docks`
  is blank.

**Boat channel (owner, 21 Oct 2026: UTRWD will allow a one-time clearing event for the
docks):** `lotplan.boat_channels`.
- **Channel:** one 40 ft channel through the flooded timber linking all four dock heads
  along the arm and running on to the main lake's open water, about 780 m.
- **Basins:** a cleared basin 10 m round each dock and its slips.
- **Clearing:** every tree whose trunk stands in the channel or a basin, or whose crown
  overhangs them, is removed. That is 76 lidar trees, plus the trees already inside the
  dock footprints.
- **Dock paths:** the docks' access paths now clear their corridors too.
- **Shots:** `check_boat_lanes_plan` (north-up), `check_boat_lanes` (oblique),
  `D_dock_channel`.
- The "no docks" rule is removed from CLAUDE.md, PLAN §7, `shots.yaml` and Phase 3a;
  docks are shown (owner).

**Paired-lot concept (owner, 21 Oct 2026):** sell one 2 ac lot for a lakehouse with an
adjacent lot for recreation and privacy; fewer houses means less clutter and fewer people,
which may raise the value of the pair.
- **Layout `pairs`** (`layout: pairs` in a shot, `flyover.py --layout pairs`): houses on
  the lots in `house_lots`, by default Lots 1, 3, 5, 7 and 10, which alternate down the
  shore and keep the Lot 5 cabin and the Lot 10 barndo.
- **Open lots** (2, 4, 6, 8, 9): graded pad (flat at the 2 ft raise) and terraces with
  their stone walls and steps only. The terrain itself is shaped, so the lot keeps its
  pasture and grass. No house, drive, walks, beach, shoreline access path or landscaping.
- **Lot-line screens:** where a lot line touches a house lot, the bamboo is replaced by
  flowering pears (Bradford / Oriental pear stand-ins from the scanned young tree, about
  25 ft) at every other position. Elsewhere the bamboo stays.
- **Open-lot example use (owner, 21 Oct 2026):** each open lot has a 24 × 20 ft covered
  picnic pavilion on a concrete slab at the pad's lake-side end, in the cabins' style (log
  posts with Y-brackets, shingle gable, open trusses). It holds two picnic tables and a
  pedestal grill. Colour trees stand round it: a red maple, a Japanese maple and a peach.
  Shot: `C_pavilion_6`.
- **Cabin variety (owner, 21 Oct 2026):** two house lots get other Satterwhite plans
  (`cabins.CABIN_STYLE`), in the same dark red-brown stain with minimal grading (no garden
  terraces; `build_sites.MINIMAL_LOTS`) and minimal landscaping (front bed and drive pears):
  - **Lot 3, after Bear Creek** (1 storey, 2 BR / 1.5 BA, 1,240 sq ft, 750 sq ft
    porches): a low 6:12 rust standing-seam roof, no dormers, a board-and-batten cross
    gable with a window over the front entry.
  - **Lot 7, after Creekside** (1.5 storey with loft, 2 BR / 2 BA, 1,787 sq ft with a
    walk-out terrace level): a steep 9:12 dark green shingle roof, a long board-and-batten
    shed dormer on the north slope, and a stone chimney up the lake gable.
  - **Footprint:** both are adapted to the common 30 × 42 ft walk-out footprint, so pads,
    grading, septic and drives are unchanged. Bear Creek's 1,240 sq ft matches it closely;
    Creekside's 855 sq ft main floor is stretched.
  - The pond re-balances to the lower fill need (still about 0.34 ac).
  - Shots: `C_bear_creek_3`, `C_creekside_7`.
- The full build-out (`cabins: all`) is unchanged and still available.
- Shots: `B_buildout_pairs`, `C_pair_5_6`; review sheet `out/2026-10-21/pairs_review.jpg`.

**Conifers (21 Oct 2026):** CC0 Poly Haven `fir_sapling_medium` stands in for eastern red
cedar within 160 m of the flight path (146 trees), and `pine_tree_01` for the planted
loblolly pines. All near-field trees are now scanned models.

**R4 sky and channel camera (21 Oct 2026):**
- **Clouds:** `sky.world_clouds`, in the world shader over the physical sky. Noise on the
  view direction projected to a cloud deck makes scattered strato-cumulus that thins to
  the horizon, coloured from the sky's own brightness so they warm at golden hour.
  - Because they have no depth, the compositor haze leaves them alone; they cost nothing
    to render and do not flicker.
  - They are on by default in marketing shots and the low flyover.
- **Channel camera:** the flight rises to 200–206 m and looks further down the channel
  (still passing all checks), so the docks, boats and beaches read past the timber.

**West boat route from the Lot 1–2 dock (owner, 21 Oct 2026):** `scripts/boat_route.py`.
- **Method:** a least-cost path over the flooded arm (2 m lidar grid, water at least 1 m
  deep at 551 ft) with cost rising steeply in shallow water, so it makes for the old creek
  channel. The channel is 10–11 m deep at x ≈ −390.
- **Route:** about 557 m (1,830 ft). Northwest from the dock through the timber for about
  220 m, then north up the deep creek, which is already open water, to the main lake.
- **Clearing:** cleared 40 ft wide like the shore channel (`lotplan.boat_channels` reads
  `out/derived/boat_routes.json`). That removes 56 more lidar trees, 132 for boats in all.
- Check shot: `check_boat_route_west`.

### Phase 3b — Cabins on every lot (planned; owner direction, 19 Oct 2026)

One illustrative cabin (Lot 5) is enough for now. A later phase renders a cabin on every
lot, for build-out stills and a build-out flyover variant:
- `cabins: all`; Lot 10 needs a smaller plan first.
- Each lot's lidar trees on the footprint are removed (already per lot).
- Optional variety, such as mirrored plans and roof or stain colours, so the row does not
  read as cloned.

**Build-out, drainage and planting (owner, 20 Oct 2026; first pass):**
- **Build-out:** a Hemlock-style cabin on every lot that fits one (Lots 1–9). Shot:
  `B_buildout_aerial` (`cabins: all`, `site_works`, `planting`).
- **Drainage analysis** (`scripts/drainage.py`): from the 2 m lidar terrain, with
  depressions filled and steepest-descent flow.
  - **CR 3635:** the roadside ditch carries about 21 ac north past the property; little of
    it enters the lots.
  - **Lots 6–8:** small swales of 3–6 ac drain west across the lake-side halves.
  - **Lot 10 creek:** the largest drain on the property starts at the CR 3640 / CR 3635
    corner, carries about 9 ac including the new road ditch, and runs west through Lot 10's
    low ground (580 → 551 ft) to the lake.
- **Conceptual drainage plan** (`drainage_plan.png`; `site_works.py` in the model):
  - **Creek:** kept as a shallow defined channel with rock check dams.
  - **Pond:** about 0.27 ac on the creek, pool about 561 ft, about 6 ft deep, with a
    downstream berm and a rock spillway back into the creek. Lidar trees on the pond and
    berm are cleared.
  - **Swales:** a diversion swale round the uphill side of each cabin site, splitting east
    of the carport and passing both sides toward the lake.
  - **Culverts:** where the creek crosses the access road and the swales cross the drives.
  - **Drip fields:** Option B fields keep 15 m from the creek and 20 m from the pond. Lot
    10's lake-side field no longer fits, so Lot 10 uses its front field.
- **Planting plan** (`scripts/planting_plan.py`, `planting_plan.png`; `planting3d.py` in
  the model), sized at about 5–7 years. Bamboo does most of the screening, on budget:
  - **Bamboo:** 225 clumps of clumping bamboo along the interior lot lines, from the access
    road to 40 ft short of CR 3635. Clumps step aside where a utility easement runs on the
    line.
  - **Frontage:** a mixed loblolly pine / oak / pecan screen along CR 3635 and CR 3640.
  - **Colour:** crape myrtles flanking each drive entrance.
  - **Low ground:** bald cypress, water oak and sycamore round the pond, along the creek and
    at the lake-side lot corners. The centre of each lake-side acre stays open for views.
  - Everything keeps clear of drives, septic areas, easements, the access road and
    existing trees.
  - Counts: bamboo 225, loblolly pine 13, oak 6, pecan 4, crape myrtle 9, bald cypress 6,
    water oak 4, sycamore 4.
- **Running bamboo:** it spreads aggressively and is hard to remove near a lake, so the
  plan assumes **clumping** bamboo (e.g. Bambusa multiplex varieties hardy to zone 8).
  This is a species choice, not a caution caption.

**Property addresses and Lot 10 barndominium (owner, 20 Oct 2026):**
- **Addresses:**
  - **1021 CR 3635, Ladonia TX** is the parcel's original address. It belongs to the old RV
    site on the high corner of Lot 10, where there were also water and power facilities.
  - **1145 CR 3635, Ladonia TX 75449** is a second address the owners applied for; it is
    currently assigned to a point near Lot 7 or 8.
- **Lot 10 plan:** one of the first structures will be a barndominium on Lot 10's high
  corner, the flat triangle by the CR 3635 / CR 3640 corner ringed by oaks. The ground there
  is about 604 ft, the highest on the property.
  - **Reference plan:** barndominiumplans.com PL-60107 "Iris": 30 × 40 ft, one storey,
    1,200 sq ft heated, 3 BR / 2 BA, 6:12 roof, 240 sq ft front porch.
  - **Owner change:** the covered patio faces the lake.
  - **Use:** this replaces the 60 × 40 ft cabin pad for Lot 10, which has no Hemlock cabin.
    The existing water and power at the old RV site may serve it.
  - **Setbacks (owner exception, 20 Oct 2026):** the 100 ft road setbacks are waived for
    Lot 10. The model uses 15 ft from CR 3635 and CR 3640 and 10 ft from the Lot 9 line,
    because the corner is only about 75 ft deep.
  - **Sited and modelled** (`build_sites.py` `BARNDO_*`, `cabins.py` `barndo()`):
    - **Pad:** a 62 × 36 ft flat pad centred near (100, −186), natural ground about
      596 ft, top about 598 ft. The pad search weights trees heavily, so the corner's oaks
      stay (1 lidar tree on the pad).
    - **Building:** 40 ft east–west by 30 ft. A 6:12 charcoal standing-seam metal gable
      roof, board-and-batten in the cabins' red-brown stain over a stone wainscot.
    - **Porches:** the roof carries 12 ft over a covered concrete patio on the lake (west)
      end, with a table, chairs and rockers. A 6 ft entry porch faces the drive, on posts
      with Y-brackets.
    - **Drive and septic:** a 117 ft gravel drive from CR 3635. The septic drip area sits
      downhill (west) of the house, by gravity from the slab.
    - Shot: `L10_barndo`.
  - **Grading and terraces (owner, 20 Oct 2026):**
    - **Pad:** flat at about 597.8 ft.
    - **Terraces:** two 30 × 36 ft terraces below the lake-side patio, like the cabin lots.
      The upper one at 594.9 ft is open lawn for recreation (a bench); the lower one at
      591.9 ft is a garden of cedar raised beds. Each step is about 3 ft, because the
      corner falls steeply.
    - **Walls and path:** stone retaining walls with centre steps and a decomposed-granite
      path.
    - **Earthwork:** about 659 cu yd of fill and 43 cu yd of cut.
    - **Septic and drainage:** the septic field moves west of the terraces, 4 m clear. The
      drainage plan adds a diversion swale round the barndo site.
    - Check shot: `check_lot10_terraces`.

**Earthwork balance (owner, 20 Oct 2026: no dirt is bought; `scripts/earthwork.py` →
`out/derived/earthwork.json`):**
- **Sources:** every cut on the property counts, as in-place cu yd.
  - Pond excavation: 1,611, less 274 for its own berm.
  - Creek channel: 201.
  - Diversion swales: 820 in all.
  - Dock and shoreline-path work: a placeholder at 0 until the docks are designed.
- **Usable fill:** cut times 0.88 for shrink on compaction, about
  2,075 cu yd.
- **Demand:** each lot's net fill after its own on-lot cut, about
  4,963 cu yd.
- **Shortfall:** about 2,888 cu yd.
- **Allocation:**
  - Each lot's swale dirt stays on that lot.
  - Shared dirt from the pond, creek and later the docks goes to Lot 10 first, because it is
    built first, then nearest first. Haul from the pond is about 490–560 ft.

| Lot | Net fill needed | From own swale | From pond | From creek channel | Still short |
| --- | --- | --- | --- | --- | --- |
| 1 | 746 | 80 | 0 | 0 | 666 |
| 2 | 702 | 55 | 0 | 0 | 647 |
| 3 | 402 | 65 | 0 | 0 | 337 |
| 4 | 420 | 72 | 0 | 0 | 348 |
| 5 | 422 | 72 | 0 | 0 | 350 |
| 6 | 242 | 80 | 0 | 0 | 162 |
| 7 | 407 | 80 | 0 | 0 | 327 |
| 8 | 203 | 80 | 74 | 0 | 50 |
| 9 | 803 | 80 | 723 | 0 | 0 |
| 10 | 616 | 59 | 379 | 177 | 0 |

- **Creek swale (owner, 20 Oct 2026):** the creek is graded into an intentional grassed
  swale from where it enters the property down to the pond.
  - **Size:** 71 m (about 233 ft) long, a trapezoid
    with a 6 ft bottom, 4:1 sides and up to 3 ft deep (about 30 ft across the top).
  - **Grade:** an even invert from 570.2 ft down to the pond's
    561.1 ft pool.
  - **Dirt:** about 252 cu yd
    in place, allocated to Lot 10. Pond dirt that frees up then goes on to Lots 9, 8 and 7.
  - **Off the property:** upstream of that point the creek runs along the CR 3640 side of
    the line, outside the property, so it is not graded.
  - **Below the pond:** it stays a shallow channel.
  - **New totals:** usable supply about 2,243 cu yd against demand of
    4,963; shortfall about 2,720 cu yd.
- **Larger pond and natural swales (owner, 20 Oct 2026; current model):**
  - **Pond:** about 0.87 ac, pool 562.0 ft (`drainage.py`
    `pond_fitted`). It spans the low ground of Lots 9 and 10 on the creek, kept 6 m inside
    the property and clear of pads and septic areas. Lot 9's recreation site moves east to
    clear it. The banks are cut back at 3:1 to grade.
  - **Pond dirt:** about 14,011 cu yd in place (less 414
    for the berm), because the pond cuts into the slope on its north side.
  - **Natural swales:** every natural drainage path draining more than about 0.6 ac,
    inside the property and clear of building sites, drives and septic areas, is graded to
    a 4 ft-bottom, 4:1, 1.5 ft-deep grassed swale. That is 15
    reaches, 319 m and about 743 cu yd.
    Each lot's natural-swale dirt stays on that lot.
  - **Balance:** usable supply about 13,620 cu yd against demand of
    4,963. Every lot is covered, with a surplus of about
    8,657 cu yd.
  - **Balanced size:** a pond of about 0.33 ac would balance exactly. The surplus could
    instead go to berms, a larger walk-out yard, or phase-2 lots.
  - Shots: `check_pond`, `P_pond_golden`.
- **Pond sized to the need (owner, 20 Oct 2026: dig only what is needed):**
  - **Sizing:** `scripts/balance_pond.py` bisects the pond's area until usable supply
    covers demand with no more than 3% spare, then records the size in
    `out/derived/pond_target.json`, which `drainage.py` reads.
  - **Result:** about 0.34 ac, pool 562.6 ft, about
    3,746 cu yd in place (berm 73).
  - **Balance:** supply about 5,042 usable cu yd against
    4,963 needed. Every lot is covered.
  - **When the plan changes:** for example dock cut, or a different backfill depth, re-run
    `balance_pond.py` and the pond resizes.
  - The 0.9 ac case (about 13,600 cu yd usable) stays above for reference.
- **Levers to close the shortfall without buying dirt:**
  - A larger pond on the same site, at the same depth:
  - 0.52 ac pond: about 1,164 cu yd more usable fill (berm 542).
  - 0.87 ac pond: about 2,609 cu yd more usable fill (berm 896).
  - 1.29 ac pond: about 4,031 cu yd more usable fill (berm 1,400).
  - Less backfill against the cabins' back walls. The walk-out's 5 ft of backfill is most of
    each cabin lot's demand.
  - Dock and shoreline-path cut, once designed.
  - Building lots in sequence, so later lots' dirt (their own swales, a phase-2 pond
    enlargement) arrives when needed.

**CR 3640 road fix (owner, 20 Oct 2026):**
- **Grass through the gravel:** the road's grade is smoothed, so the terrain stood above
  it in places and showed through. The build now carves the site and regional terrain to
  6 in under the roadbed, 4.5 m either side of the centreline, then back up at 3:1
  (`build_baseline.carve_roadbed`).
- **Grass tufts:** kept 7 m from all road centrelines.
- **Construction strip:** the bare strip either side of the new road in the 2024 imagery
  (18 m from the centreline) is grassed over in the ground mask.
- **Gravel:** all county roads share a darker, speckled crushed-limestone material.
- Check shot: `check_cr3640`.

**Entries, fence, turnarounds and Lot 10 parking (owner, 20 Oct 2026):**
- **Frontage fence** (`scripts/blender/frontage.py`, in `Roads`): the existing barbed-wire
  fence along the property line beside CR 3635, about 378 m.
  - **Construction:** cedar posts every 12 ft, H-braces at every gate and run end, four
    strands of wire.
  - **Gates:** one per driveway (9), each with a 20 ft clear opening and two 10 ft
    galvanised 5-bar pipe gates, shown swung open inward.
- **Entries** (with each lot's drive):
  - **Apron:** the drive widens to 24 ft at the road, with flared returns, for a truck
    towing an RV or boat.
  - **Culvert:** an 18 in corrugated pipe, 30 ft long, under the apron at the roadside
    ditch, with concrete splash pads at both ends.
- **Turnarounds** (`build_sites.py` `turnaround()`): the largest gravel circle drive that
  fits near the parking, round a mulched island with a crape myrtle or pear and shrubs,
  with a 60, 50 or 42 ft centreline diameter. Where a loop does not fit beside the front
  septic field, a semicircular turning bulb. Results: Lot 1: circle drive 59 ft; Lot 2: circle drive 50 ft; Lot 3: circle drive 59 ft; Lot 4: circle drive 59 ft; Lot 5: semicircular bulb 59 ft; Lot 6: circle drive 59 ft; Lot 7: semicircular bulb 59 ft; Lot 8: semicircular bulb 59 ft; Lot 9: circle drive 42 ft; Lot 10: none.
  - **Lot 10:** the drive is short and the corner tight, so it turns via its carport apron
    or drives through to the access road.
  - **Lots 2–9:** keep their rear drive-through to the access road for long rigs.
- **Lot 10 covered parking:** a 22 × 24 ft carport in the cabins' style, east of the
  barndo's entry porch at pad level, where the drive now ends. It is included in Lot 10's
  flat grading.
- **CR 3635:** shares the speckled crushed-limestone gravel with CR 3640.
- **Follow-up, same day:**
  - Lot 10's drive now runs straight to its carport. It had been pulled south to clear a
    septic field that is actually west of the house.
  - The barbed-wire fence also runs along the CR 3640 side of Lot 10, with a 20 ft gate
    where the shared access road meets CR 3640: 672 m of fence and 10 gates in all.
- Check shots: `check_entry_lot5`, `check_lot10_parking`, `check_cr3640`.

### Phase 3c — Site infrastructure (planned)

Show everything the site plan carries, as switchable layers for stills and video:
- the shared north-south access road and its utility corridor;
- private utility easements to each lot's west edge;
- driveways, rear drive-through drives, entry yards and turnarounds;
- the septic drip areas (as mown lawn, optionally outlined in check views);
- the recreation sites with their utility pedestals;
- shoreline paths and dock circles, mailboxes and gates, and fencing (split rail);
- the docks, beaches and boat channels (shown since 20 Oct 2026).

Marketing frames keep the §7 rules. Infrastructure appears only where the owner approves
it for publication.

### Phase 4 — "Perry Lakeside Resort" concept (end phase; owner direction, 19 Oct 2026)

**Concept.** Improve the property, build a few cabins and start rental operations. Then
market each lot as a working lakehouse rental, which raises the sales-price target
significantly. Renders, stills and video for this phase:
- **Resort vision:** a few rented cabins in use, with lights on, a fire pit, kayaks, golf
  carts on the paths, and guests on the shoreline path and at the dock circles.
- **Entry experience:** a resort sign at CR 3635, the access road and landscaping.
- **Per-lot "working rental" packages:** each lot with its cabin, porch and lake view,
  plus the shared amenities.
- **Seasonal and time-of-day variants:** golden hour, dusk with lights, early fall (owner
  favourite) and spring.

Risk items for this phase are listed under RISK REVIEW below.

### RISK REVIEW (future phase; owner)

The owner has been advised and handles **all** safety, legal, regulatory and other risk
items, and will review them in this phase (owner, 19 Oct 2026). Until then, work does not
add caution statements, disclaimers or extra caution captions to renders, plans or
replies. Items already raised, kept here for that review:
- The LSMP Water Quality Protection Criteria versus the Lake Zoning septic exception for
  lots under 5 ac (§9, before platting).
- Septic options A and B: setbacks to the lake and any flood or flowage easement, and
  UTRWD's view of lake-side fields.
- The "Perry Lakeside Resort" name check, how a concept resort is described, any
  rental-income figures, and short-term-rental rules (County, UTRWD, deed, lender).
- The marketing items in §7 and the KwikImage licence.
- Structural and geotechnical design for the walk-out, piers and backfilled walls.
- Beaches, picnic furniture and moored boats on UTRWD shoreline: the draft LSMP allows
  access paths, docks and riprap by permit, and bars landform change on UTRWD land
  without approval.

### Phase 3+ — Later releases (planned after Phase 2 is accepted)

- **Per-lot stills:** templated cameras for each lot (lot-to-lake, lot-from-water,
  aerial with lot highlight), in clean and outlined variants.
- **Flyover video:** drone-photo-to-lake reveal. Superseded by the low-altitude plan in
  Phase 3a, which includes the compute budget.
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
   north-point dock (Phase 2b), each checked against the LSMP rules.** Docks are shown
   in the model and in marketing frames (owner, 20–21 Oct 2026). Pedestrian shoreline
   paths (5 ft max) are allowed.
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

- **Risk and caution items (owner, 19 Oct 2026):** the owner has been advised and handles
  all safety, legal and other cautions, in the future RISK REVIEW phase. Do not add
  caution statements or extra caution captions now. The existing §7 marketing caption
  stays as it is unless the owner changes it.

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
Revised 20 Oct 2026: the dying stage follows the Bois d'Arc Lake reference (grey dead
interior, rust fringe), and moss is on about an eighth of the dead trees.

## 9. Open Items

| Item | Owner | Needed by |
| --- | --- | --- |
| Section 7 decisions 2–6 | Owner | Before any publication |
| Optional: UTRWD's official georeferenced water-surface classification map, to replace the digitized draft LSMP outline | Owner (request from UTRWD) | Before publication |
| Lots 9–10 dock: **deferred by owner (14 Oct 2026), no action**; options remain share 7–8, fishing dock, or re-pair | Owner | When the owner revisits |
| Lot 1 driveway access (connects at the mapped CR 3635 end) | Owner | Phase 2b finals |
| Phase 2d: whether the access road and utility corridor appear in marketing (Lot 10 takes the small house unless the County allows a smaller CR 3640 setback) | Owner | Before Phase 2d renders |
| Phase 3a flyover: approve the R0 flight path and pacing (preview `out/2026-10-19/video/low_preview/`); time of day. One cabin (Lot 5) and a simple walking path for now (owner, 19 Oct 2026); all cabins in Phase 3b, roads and easements in Phase 3c | Owner | R0 review |
| Lot 10 barndominium: locate the old RV site's water and power (setback exception approved by owner, 20 Oct 2026) | Owner | Before construction planning |
| Phase 4 "Perry Lakeside Resort": name check, caption wording for a concept resort, any rental-income claims, short-term-rental rules (County, UTRWD, deed) | Owner, co-owner/agent, counsel | Before Phase 4 publication |
| **LSMP Water Quality Protection Criteria vs Lake Zoning OSSF exception:** would ten ~2 ac lots on septic still qualify for individual Shoreline Use Permits (docks, paths, shoreline clearing)? | Owner, UTRWD, attorney | **Before platting** |
| Drone capture: Part 107 or a contracted pilot for marketing imagery; UTRWD permission to fly over its land and water (docs/DRONE-CAPTURE-PLAN.md §3) | Owner | Before Phase 2c flights |
| Commit or discard the uncommitted queue/sidecar changes in PTM | Owner | Any time (does not block LRH) |
