# Drone Capture Plan: Aerial Photos and 3D Scan

**Drafted:** 15 October 2026 · **Status:** draft for owner review
**Scope:** capture the owner's site after mowing and dock-corridor clearing, and bring
the data into LRH. The owner handles pre-flight planning. This plan covers what to
capture, how, and what LRH does with it. It is written to be reused on other
properties, flown either by the owner or by a contracted Part 107 pilot (§8).

## 0. Who flies what (owner, 15 Oct 2026)

- **Existing aerials:** taken by **KwikImage** ([kwikimage.com](https://kwikimage.com/)),
  commissioned by the co-owner (a real estate agent): 42 stills and one video, in
  `inputs/drone/2023-08-11_pilot-existing/` (§6.3).
- **New marketing capture (§4–§6):** a Part 107 pilot, for example the owner's local
  pilot or KwikImage again.
- **Owner, recreational (TRUST):** practice flights for learning only, kept separate
  from marketing capture. Good practice targets for later capture:
  - flying a manual grid at a steady height;
  - holding a camera angle along a line;
  - hovering at a set position and heading.
  
  Don't feed recreational footage into marketing images (§3).

## 1. What the capture is for

The current model is built from data that predates the work now planned on the site:
NAIP July 2024 imagery, the KwikImage drone photo of August 2023 and StratMap lidar from
December 2025. A fresh capture after mowing and clearing would:

1. **Replace the drone-photo clearing map** with a true orthomosaic. The current
   clearing comes from projecting one oblique photo, which is registered only to about
   10 m. An orthomosaic is map-accurate to well under 1 m.
2. **Update trees inside the parcels**: which trees were kept, removed or newly cleared
   along the dock corridors, measured from a fresh surface model.
3. **Give close-range texture** (ground, road edges, shoreline, retained trees) for
   per-lot stills and the low passes of the flyover, where 0.6 m NAIP imagery runs out.
4. **Supply real reference photos** from known positions, so renders can be checked
   side by side as the drone-match view is today.

## 2. Before buying: what the DJI Mini 5 Pro can and cannot do

| Item | Finding | Effect on this plan |
| --- | --- | --- |
| Camera | 1-inch sensor, 50 MP stills, 24 mm-equivalent lens, f/1.8 (DJI specs via retailers) | Good for mapping and stills. About **1.5 cm per pixel at 80 m** in 50 MP mode, calculated from the published sensor size and lens; confirm in your planning app. |
| "LiDAR" | A **forward-facing lidar for obstacle sensing**, alongside the vision sensors | It is not a mapping scanner. I found no way to export a point cloud from it. **The 3D scan in this plan comes from photogrammetry**, which builds a point cloud and surface model from overlapping photos. If true lidar matters, see §8. |
| Weight | 249.9 g with the standard battery | Under 250 g only with that battery; the larger battery takes it over. Remote ID and registration rules depend on weight and on how you fly (§3). |
| Mapping apps | No DJI SDK support reported for third-party mapping apps (DroneDeploy, Dronelink) as of user reports in 2026 | Automated grids are flown by loading a **waypoint KMZ** into DJI Fly. The KMZ is planned in a web tool such as Dronelink's web planner or WaypointMap. Allow time to test this before the real flight. |
| Positioning | GPS only, with no RTK | Photo positions are good to a few metres. LRH fixes this during registration (§6). |
| US availability | Foreign-made drones were added to the FCC Covered List on 22 Dec 2025. Models already FCC-authorized can still be sold, and updates are protected to at least 2029 (DJI's appeal was pending as of mid-2026). | **Before buying, confirm the unit is the US-authorized version, with an FCC ID and Remote ID.** |

## 3. Regulatory note: recreational versus Part 107

The FAA's guidance on the recreational exception (Advisory Circular 91-57, current
version 91-57D, 2025) says recreational flights **may not include flights "related to
or in furtherance of a business"**, and a single flight cannot mix recreational and
commercial purposes. A flight that fails the recreational conditions is treated as a
Part 107 operation.

**Imagery taken to market lots for sale is very likely business use, even on your own
land.** If any of the photos, the orthomosaic or the scan will be used in marketing or
to support lot sales, plan to fly under **Part 107**:
- your own Remote Pilot Certificate (a knowledge test; no flight test), **or**
- a contracted Part 107 pilot.

Recreational flying with your TRUST certificate is fine for personal, non-business
flights. This is guidance, not a legal opinion. If the line matters, confirm with the
FAA or an aviation attorney. Also confirm with UTRWD before flying over its shoreline
land, the lake or the dam: the draft LSMP does not address drones, and the dam is
critical infrastructure.

## 4. Site preparation (after mowing and clearing)

- **Ground control.** 6–8 high-contrast targets (about 60 cm, e.g. painted plywood
  crosses or commercial GCP mats):
  - spread around the parcels and along CR 3635, including one at each end of the site;
  - 2–3 more kept aside as **check points**, which LRH does not use in processing and
    which measure the accuracy;
  - if you can, measure each target with a survey-grade GNSS receiver or have your
    surveyor do it. Phone GPS is not good enough. If they are not measured, still lay
    them: LRH can register them to the lidar (§6).
- **Mark the dock corridors and driveway stakes** with visible flags so they can be
  located in the imagery.
- **Leave brush piles, equipment and vehicles out of the mapped area** if possible.
  They become false "trees" in the surface model.

## 5. What to capture

Fly in this order on one day, with settled light and wind below about 15 mph (trees
moving in the wind ruin 3D reconstruction).

| # | Capture | Settings | Purpose |
| --- | --- | --- | --- |
| A | **Nadir mapping grid** over both parcels plus about 60 m beyond, including the dock corridors and shoreline | 80 m AGL; 75% front / 70% side overlap; camera straight down; 5 m/s or slower (limits rolling-shutter blur); fixed exposure and white balance; JPEG with GPS EXIF (DNG optional) | Orthomosaic and surface model |
| B | **Oblique double grid** over the same area | 70 m AGL; camera 45–60° down; two passes at right angles; 70% overlap | 3D of retained trees, tree lines and the shoreline edge |
| C | **Corridor passes** along each dock path and over each dock site | 30–40 m AGL; camera 60° down; 80% overlap | Detail where the paths and docks will be modelled |
| D | **Reference stills** from the positions in §5.1 | 50 MP; bracket exposure; note time | Side-by-side checks against renders |
| E | **Short video orbits** (optional) of the parcels and creek arm | 4K, slow | Motion reference for the flyover |

Expect roughly 400–800 photos for A–C. That's several batteries, so plan battery swaps
at the edge of the grid rather than mid-line.

**Timing.**
- **Mapping (A–C):** best between 10 am and 2 pm, or under even overcast, for short
  shadows.
- **Reference stills (D):** at the times the hero shots use (late afternoon, golden
  hour).
- **Season:** leaf-on, so canopy reads the way the marketing shows it. A leaf-off repeat
  would add bare-ground detail under the trees.

### 5.1 Reference still positions

All positions stay under 400 ft (122 m) AGL, the legal ceiling. Each of these matches a
view LRH renders:

| Still | From | Looking toward | Height AGL |
| --- | --- | --- | --- |
| Drone match | South-east of the parcels, over CR 3635 near the CR 3640 junction | West-north-west across the parcels | 100–120 m |
| Arrival (H1) | Over CR 3635, south-east of Lot 10 | North-west toward the lake and SH 34 bridge | 120 m |
| From the lake (H3) | Over the open water north-west of the lots (over UTRWD water; see §3) | South-east at the lot frontage and timber | 100–120 m |
| Each dock site | Over the water 60 m out from each dock | Back toward the lot | 30–40 m |

Exact positions are not critical. LRH solves each photo's camera from the imagery
itself.

## 6. Bringing the data into LRH

### 6.1 Handover folder

Copy everything from the SD card unchanged into one folder per capture day:

```
inputs/drone/<YYYY-MM-DD>_<site>/
  raw/A_nadir/  raw/B_oblique/  raw/C_corridors/  raw/D_stills/  raw/E_video/
  flight_logs/                  # DJI flight records (.txt), if available
  gcp.csv                       # target id, easting, northing, elevation (EPSG:6344 / NAVD88) or blank
  capture_manifest.yaml         # date, pilot, certificate type, aircraft, settings, weather, notes
```

`inputs/` is git-ignored, as with all source data. An import step records a SHA-256
of every file in a committed `drone.lock.json`, as `imagery.lock.json` does for NAIP.

### 6.3 Existing pilot photos and video

Copy them unchanged into `inputs/drone/<flight date>_pilot-existing/raw/`, with any
flight logs, and note the date in `capture_manifest.yaml`. LRH can then:
- solve each photo's camera, as was done for the current drone photo, to add more
  side-by-side check views;
- try photogrammetry on overlapping stills and on frames pulled from the video. This
  works if the footage circles or sweeps the site with good overlap; a single pass may
  not;
- use the clearest straight-down or high oblique frames to refine the clearing map.

These predate the planned mowing and clearing, so they describe the site as it was
then, not the final layout.

### 6.2 Processing (LRH tasks, to be built)

1. **`scripts/import_drone_capture.py`**: copies, hashes and checks the folder (photo
   counts, GPS EXIF present, manifest fields).
2. **Photogrammetry with WebODM** (free and open source; runs locally on this Mac). It
   produces an orthomosaic (GeoTIFF), a surface model (DSM), a dense point cloud
   (LAZ) and a textured mesh. The 24 GB machine should handle about 800 photos; larger
   jobs can be split.
3. **Registration to the project frame** (EPSG:6344, NAVD88, `origin.json` local
   metres):
   - with surveyed targets: tie to them directly;
   - without them: align the point cloud to the StratMap 2025 lidar ground on bare,
     unchanged surfaces (roads, the old clearing), then refine with the targets'
     image positions.
4. **Acceptance checks**, recorded in a check report as the baseline checks are:

   | Check | Target |
   | --- | --- |
   | Orthomosaic vs. CR 3635 and CR 3640 centrelines | under 0.5 m horizontal |
   | Surface-model ground vs. lidar ground on bare areas | under 0.15 m RMS (the project's terrain limit) |
   | Check points (if surveyed) | under 0.10 m horizontal, 0.15 m vertical |

   A failed check stops the import, as a blank frame stops a render.
5. **Feed the model:**
   - the orthomosaic replaces the drone-photo clearing map inside the parcels;
   - a fresh canopy-height model (surface model minus lidar ground) updates kept and
     removed trees in and around the parcels, newer than the December 2025 lidar;
   - the orthomosaic and mesh become close-range ground texture for per-lot and
     low-flyover shots;
   - each reference still gets a solved camera and a matching render, as
     `check_drone_match` does today.

## 7. Who does what

| Step | Owner | LRH (Claude) |
| --- | --- | --- |
| Part 107 decision, airspace, UTRWD permission, insurance | ✓ | |
| Buy and test the aircraft; test KMZ waypoint missions in DJI Fly | ✓ | Generate the grid KMZ from the parcel and corridor geometry if useful |
| Mow, clear corridors, lay and (ideally) survey targets | ✓ | Suggest target locations from the model |
| Fly captures A–E | ✓ | |
| Copy the card to the handover folder | ✓ | |
| Import, process, register, check, update the model | | ✓ |

## 8. Reusing this plan on other properties

For land you do not own, hire a Part 107 pilot and hand them §4–§6 as the capture
spec. Ask for:

- a current Remote Pilot Certificate and liability insurance;
- written confirmation of airspace authorization and landowner permission;
- **all raw photos and flight logs**, not only processed products, plus `gcp.csv` with
  the surveyed target coordinates and the method used;
- the folder layout in §6.1, so the same import runs unchanged;
- licence terms allowing you to use the data and derived renders in marketing;
- optionally, a **mapping lidar** flight (for example a lidar payload on an
  enterprise drone) delivering classified LAS/LAZ with a quality report. LRH already
  reads classified lidar (`scripts/lidar_trees.py`), so a contractor's point cloud
  can go through the same tree pipeline used for StratMap.

Sources: DJI Mini 5 Pro specifications as listed by retailers
([D1 Store](https://www.d1store.com.au/mobile/products/dji-mini-5-pro),
[Heliguy](https://www.heliguy.com/blogs/posts/top-10-features-dji-mini-5-pro/));
mapping-app support reports
([Dronelink community](https://support.dronelink.com/hc/en-us/community/posts/48520389244691-Dji-mini-5-pro));
FAA [AC 91-57D](https://www.faa.gov/regulations_policies/advisory_circulars/index.cfm/go/document.information/documentID/1044036)
and [AC 91-57C](https://www.faa.gov/documentLibrary/media/Advisory_Circular/AC_91-57C_FAA_Revised.pdf);
FCC Covered List coverage
([UAV Coach](https://uavcoach.com/fcc-dji-comments/),
[Newsshooter](https://www.newsshooter.com/2026/05/07/dji-drone-users-have-an-opportunity-to-share-concerns-directly-with-fcc-decision-makers/)).
