# PIPELINE_VARIABLES - what is baked, what is detected, what the owner must supply

Audited read-only on 2026-09-06 by eight readers and eight adversarial verifiers over
the code, the two finished runs (`NA173_H2014g_RS` = fixture F2, `NA173_C0probe_RS` =
the C0 probe) and `docs/rs-reference/`. 158 + 460 claims, none refuted; corrections
folded in. Every line cites `file:line`. This document is the answer to "what runs as
code, what does the AI decide, and what must a human answer for a new dataset". Four
carry-forward defects found by the audit were fixed the same day and are marked in
section 6; suite 941 passed, 1 skipped.

## 1. The model

**The science is code.** Every alignment setting, every mount angle, every texture and
simplification preset, the zoning algorithm, the merge ladder and the acceptance
arithmetic are constants in the repo (`RS_CLI/Metadata/*.xml`, `modules/cameras.json`,
`modules/image_batcher/batch_directory.py`, `merge_zones.py`). They are versioned,
diffed by the fingerprints and enforced by `modules/preflight.py`. Nothing in a run
invents them and the AI must not: hard rule 10 says the order of operations is the
product.

**The dataset facts are detected.** Camera family from the filename
(`modules/camera_registry.py:234-253`), UTM zone and band from the nav table then
carried in the flight-log FILENAME (`modules/georeference/georeference_images.py:608-642`,
`modules/flight_logs.py:88-99`), zone membership from the geometry, component
membership from RealityScan's own exports, triangle counts and texture pages from
`-exportReport` and the export tree. A detector that cannot decide either asks
(unknown camera prefix) or fails loudly - with the exceptions listed in section 6.

**The owner supplies the frame, the scope and the ownership.** Section 2 is the whole
list. The AI's job is to run `charter -> preflight -> plan -> launch`, to ask every
line preflight reports as missing, to watch the run, and to flag what section 6 calls
a silent default. On 2026-09-06 the AI went further than that: it derived every
charter answer from one chat sentence, built the fixtures by hand and wrote its own
post-run census. That is recorded in section 6 as the top gap, not as the model.

## 2. Required owner inputs (any dataset)

| # | Input | Stage | Does the lane ask? | If absent |
|---|---|---|---|---|
| 1 | `locations.originals[]` | guard only | ASKS `preflight.py:237-257` | blocks | 
| 2 | `locations.nav[]` | guard only | ASKS `preflight.py:237-257` | blocks |
| 3 | `locations.results_root` (absolute) | all | ASKS `preflight.py:258-269` | blocks; also blocks under `disk_delta_gb + 50 GB` free `preflight.py:611-624` |
| 4 | `locations.protected[]` + why | guard only | ASKS only for the placeholder `preflight.py:286-292`; an EMPTY list only warns `:281-285` | run proceeds unguarded |
| 5 | `budget` hours / RAM / disk / abort criteria | any RealityScan stage | ASKS `preflight.py:320-340` | blocks |
| 6 | `ownership.rs_instance`, `rs_cache_dir` | any RealityScan stage | ASKS `preflight.py:299-316`; BLOCKS if the instance is an owner instance `:304-307` | blocks |
| 7 | `campaign` / `dive` | merge naming | ASKS `preflight.py:232-236` | blocks |
| 8 | `science.frame` (`utm:<zone><band>`) | align | ASKS `preflight.py:344-352`; BLOCKS on disagreement with the log's zone tag `:494-538` | blocks |
| 9 | `signed_off.by` / `.date` | all | ASKS `preflight.py:225-231`; `rs run`/`launch` refuse unsigned `rs.py:134-137` | blocks |
| 10 | `pipeline.stages[]` | all | ASKS when empty/unknown `preflight.py:380-393` | blocks |
| 11 | `b_input`, `b_flight_log_path` (batch without georeference) | batch | ASKS `run_plan.py:422-423`, `preflight.py:415-421` | blocks |
| 12 | `g_input`, `g_flight_log`, `g_type` (georeference) | georeference | ASKS `run_plan.py:419-437` | blocks |
| 13 | `i_input` (extract) | extract | ASKS `run_plan.py:418,431` | `main.py:222-226` exit 2 |
| 14 | camera identity for an unknown filename prefix | georeference, align | ASKS once per prefix `preflight.py:464-473` | **the answer changes nothing** - see gap G7 |
| 15 | **zone sizes** `b_target_images` / `b_min_zone` / `b_max_zone` | batch | **NEVER ASKED** | 3000 / 1000 / 4000 - collapses a small survey to one zone; the batcher refuses a target under 100 at start-up `batch_directory.py:1418-1419` |
| 16 | **zone overlap** `b_overlap_percent` | batch | **NEVER ASKED** | 20.0 silently `main.py:217-220` |
| 17 | **`science.identity_capture`** (`csv`/`xmp`) | align | **NEVER ASKED**; unset only WARNS `preflight.py:373-376` | the DESTRUCTIVE XMP harvest runs |
| 18 | `science.min_component_size` | align + merge | **NEVER ASKED** | 50 for both `run_plan.py:718,983-987` |
| 19 | **export CRS** | export | **NEVER ASKED, NEVER DERIVED** | the `.rsInfo` carries whatever CRS the assembly project holds - gap G3 |
| 20 | publish credentials `CESIUM_ION_TOKEN` / `NIRACLIENT_DIR` | publish | **NEVER ASKED** | the planner appends `--dry-run` silently `run_plan.py:788-790` |
| 21 | georeference science: declination, position/altitude/orientation accuracy, assumed mount | georeference | **NEVER ASKED** | 0.0 deg, 10/1/15, 10 deg at 30 deg accuracy `georeference_images.py:128-160,262-338` |

Rows 15 to 21 are the answer to "what must a human answer that the lane does not ask
for today". Section 6 ranks them.

## 3. Stage by stage

### 3.1 Extract images

| Variable | Kind | Value or source | Where | To next stage |
|---|---|---|---|---|
| video extensions | baked | `.mp4`, `.mov` | `extract_images.py:19` | n/a |
| JPEG quality | baked | 80 | `extract_images.py:179` | n/a |
| output folder | baked | `<results>/raw_images` | `extract_images.py:254` | wired (by name) |
| video timestamp, fps, frame count | detected | filename regex + `cv2` | `file_metadata_parser.py:15`, `extract_images.py:120-129` | wired into the frame filename |
| split-part offset | detected | `_PART_REGEX`, summed durations of earlier parts | `extract_images.py:25-26,209-249` | n/a |
| `i_output_fpm` | owner | **1.0 silently** | `extract_images.py:46-54` | n/a |
| `i_mpx` | owner | **3 silently** - this is the resolution RealityScan sees | `extract_images.py:56-64` | n/a |

### 3.2 Georeference

| Variable | Kind | Value or source | Where | To next stage |
|---|---|---|---|---|
| mounts per family (lever arm, pitch, pitch accuracy) | baked | zeuss 0.5/0/0.5 m, 25 deg, 45; cammid 1/0/1, 20, 10; camlower 1/0/1, 10, 5; upper 45, 15 | `georeference_images.py:36-101` (runtime), `cameras.json` families (declared copy) | wired into the log's Pitch columns, unrecoverable afterwards |
| prior accuracies | baked | position 10 m, altitude 1 m, yaw/roll 15 deg | `georeference_images.py:128-133` | wired as log columns 4-6, 10, 12 |
| assumed mount for an unmeasured camera | baked | 10 deg down, 30 deg accuracy | `georeference_images.py:157-160` | wired |
| orientation convention | baked | `rc_pitch = 90 + vehicle_pitch - mount_pitch`; yaw + declination; roll passthrough | `georeference_images.py:540-581` | wired |
| nav match window | baked | 2.0 s; unmatched images are dropped from the log | `georeference_images.py:748-764,916` | n/a |
| nav CSV schema | baked | `Timestamp`, `kalman_lat/long/depth/yaw_deg/pitch_deg/roll_deg`, `%Y-%m-%dT%H:%M:%SZ` | `georeference_images.py:192,583-606` | n/a |
| flight-log layout | baked | 14 columns, `;`-separated, `filename;X (East);...;FocalLength` | `georeference_images.py:931-973` | wired (the batcher preserves the source column order) |
| camera family | detected | first matching pattern in `cameras.json`, case-insensitive | `camera_registry.py:234-253` | re-detected by every later stage from the same filename |
| **UTM zone + band (the CRS)** | detected | `utm.from_latlon` on the first successfully converted row, then forced for the run | `georeference_images.py:608-642` | wired ONLY through the log FILENAME |
| EPSG | derived | `(32700 if band in C..M else 32600) + zone` | `flight_logs.py:88-146` | wired |
| `FocalLength` column | derived | `camera_registry.identify().focal_length_35mm`, empty when unknown | `georeference_images.py:412-440` | wired - the only sidecar-free focal prior |
| declination | owner | **0.0 silently** | `georeference_images.py:262-271` | not passed (the log records no declination) |
| accuracies, acceptance floor, assumed pitch | owner | **10/1/15, 80 %, 10/30 silently** | `georeference_images.py:277-351` | wired as columns |

`geoall.py` is the canonical implementation and has diverged from the module: 13
columns and no `FocalLength`, a `Name` header, path-prefixed rows, no acceptance gate,
no unknown-camera warning, malformed nav rows skipped silently (`geoall.py:825-867,355-356`).
Hard rule 6 says these must not diverge.

### 3.3 Preprocess (CLAHE)

Everything is a silent default: clip 2.0, tile 8, white balance off, workers = CPU
count (`preprocess_images.py:115-153`), and `prompt_user=False` means preflight never
asks (`run_plan.py:581-582`). The stage has NO fingerprint and skips by filename
existence (`preprocess_images.py:179-181`), so a re-run with a different clip keeps the
old pixels. The hand-off to batch is the folder NAME: the batcher switches to
`<results>/preprocessed_images` whenever that folder exists (`batch_directory.py:412-414`),
so a stale CLAHE tree from an earlier run is used silently.

### 3.4 Batch into zones

| Variable | Kind | Value or source | Where | To next stage |
|---|---|---|---|---|
| `initial_k` | derived | `max(2, ceil(n / target))` - **always at least two zones** | `batch_directory.py:575` | n/a |
| split / merge rules | baked | split above `max`, merge nearest below `min`, 10 iterations | `batch_directory.py:588-652` | n/a |
| clustering | baked | `StandardScaler` on [x, y(, z), log density], `KMeans(random_state=42, n_init=10)` | `batch_directory.py:513-525` | n/a |
| overlap sizing | derived | `20 %` of the receiver capped at `20 %` of the donor pool | `batch_directory.py:711-718` | n/a |
| overlap score | baked | 0.7 distance + 0.3 inverse density | `batch_directory.py:752-754` | n/a |
| `utm_zone_suffix` | detected | string surgery on the log filename | `batch_directory.py:443-448` | wired (names the per-zone logs) |
| file index, basename collisions | detected | one walk; duplicate LOG ROWS refused, duplicate FILES first-wins | `batch_directory.py:860-931` | n/a |
| reuse guard | detected | `batch_inputs.json`: log sha, input dir, count/bytes/mtime, 9 zoning params, status, per-zone log shas | `batch_directory.py:202-245,267-325` | read by the batcher itself and by `verify.py:93-131` |
| `b_target_images` / `b_min_zone` / `b_max_zone` | owner | **3000 / 1000 / 4000 silently**; refused below 100 at start-up | `batch_directory.py:49-77,1418-1419` | not passed - align never reads the zoning params |
| `b_overlap_percent` | owner | **20.0 silently** | `batch_directory.py:79-87` | not passed |
| `b_zone_layout` | owner | `copy` silently; `pool` needs `RS_ALIGN_POOL_DIR`, which only the planner sets | `batch_directory.py:178-198`, `run_plan.py:689-706` | re-entered |
| `b_xmp_priors` | owner | False silently; **not in the reuse fingerprint** | `batch_directory.py:164-176,232-236` | wired when on |
| zone acceptance | owner gate | interactive `input()`; **auto-accepted on the lane** | `batch_directory.py:1317-1324` | n/a |

### 3.5 Align zones

Thirty-five settings are applied by `-set` before the flight-log import
(`AlignZone.bat:199-214`). The science half:

| Key | Value | Where |
|---|---|---|
| `sfmEnableCameraPrior` | true | `AlignmentParams.xml:24` |
| `sfmCameraPriorWeight` | 10.0 | `:26` |
| `sfmCameraPriorWeightOrientation` | **2.0** (D3) | `:22` |
| `sfmCameraPriorAccuracyYaw/Pitch/Roll` | 10.0 - **overridden by the log's per-row values** because `ifuuInh=0` | `:39,:37,:17`; `FlightLogParams.xml:24` |
| `sfmDistortionModel` | Division (global) | `:16` |
| `sfmMergeGeoreferencedComponents` | false (the merge flips it) | `:35` |
| `sfmMaxFeaturesPerImage` / `PerMpx` / `PreselectorFeatures` | 25000 / 14000 / 20000 | `:5,:19,:32` |
| `sfmDetectorSensitivity` / `sfmImagesOverlap` | Ultra / Medium | `:33,:29` |
| `s235l` / `s236l` / `s237l` | 5.0 / 5.0 / 0.5 - obfuscated ids, read as position accuracies | `:43,:23,:2` |

Flight-log import: `gpsLogFileFormat {D1F2A3B4}` (14 columns), `ifUsePosAcc` and
`ifUseOriAcc` true, `ifKGrp=2` ("automatically group camera calibration", mapping
undocumented), `csvFLSep=1` (`FlightLogParams.xml:11,22,26-28`). The CRS pair is
rewritten per zone from the log's filename tag into `<results>/logs/FlightLogParams_<zone>.xml`
(`flight_logs.py:227-295`) and the project plus output CRS are pinned to it
(`AlignZone.bat:135-140`).

Identity capture, `RS_LEGACY_XMP_IDENTITY=0` (charter `identity_capture: csv`):
`-exportLatestComponents`, then per component `-selectComponent`,
`-renameSelectedComponent <zone>_c<K>`, `-exportRegistration identity/<zone>_c<K>.csv`
with a `#cameras N` content gate, `-exportSelectedComponentDir`
(`AlignZone.bat:290-333`). Unset or `1` selects the destructive XMP harvest
(`:356-392`). Calibration/lens groups are replayed from
`<results>/logs/prior_groups_<zone>.cmds` BEFORE the settings and the import
(`AlignZone.bat:151-161`, `prior_groups.py:100-165`); groups come from
`cameras.json` (zeuss 1, port 2, cinema 3, starboard 4, voyis 5/6, sony 7,
starboard_1to1 8).

Detected: the zone list (every subdirectory of `batched_images_by_zone`), the per-zone
log by glob, the frame from that filename, the camera families present, whether the
format GUIDs are installed in the RealityScan install directory, and retry-versus-rerun
from `align_inputs.json`.

Owner: instance, cache, `identity_capture`, optional `align_settings_xml`,
`min_component_size` (silently 50), `r_flight_log_params` (never asked),
`r_project_label` (never asked, defaults to empty so no dated project copy is written).

### 3.6 Merge components

| Variable | Kind | Value | Where |
|---|---|---|---|
| ladder `merge_first` | baked | `merge_georef` {merge georeferenced components, camera prior}, then `align_rematch`, then the same at High overlap | `merge_zones.py:88-117` |
| border margin | baked | 10 m each box (20 m effective) | `component_analysis.py` |
| scene cap | baked | 34,000 cameras | `merge_zones.py:298-306` |
| loss tolerance | baked on the lane | 0.0025 fraction | `run_plan.py:735` |
| scale band, nav floor, minimum cameras | baked | 0.90-1.10, 3 m, 30 | `scale_oracle.py:226-227,279-298` |
| peel loop cap, peel min component size | baked | 40 laps, `-setMinComponentSize 1` | `MergeZoneComponents.bat:260,263` |
| union flight log | detected | every `flight_log*_UTM.txt` under `--images_root`, deduped by basename, one zone asserted | `merge_zones.py:646-757` |
| clusters, borders, twins, shared-image graph | detected | from `bbox_utm` and the manifests | `merge_zones.py:369-457` |
| peel sizes | detected | count of `identity_r<K>/*.xmp` per lap | `merge_zones.py:823-842` |
| attribution | derived | subset sums from the UNIQUE image count to the camera SUM (2026-09-06) | `merge_zones.py:459-630` |
| `--min_size` | owner | re-entered from `science.min_component_size`, silently 50 | `run_plan.py:718` |
| ladder / scope / pair gate / loss tolerance / band / auto-model | **baked on the lane** | the charter CANNOT change them | `run_plan.py:719-736` |
| `RS_PROJECT_CRS` | **not set** | the merge scene inherits the instance's CRS list | grep clean in `merge_zones.py` and `MergeZoneComponents.bat` |

### 3.7 Generate models, export, publish

None of these ran on 2026-09-06. Baked: `RS_TARGET_TRIS` 10,000,000
(`GenerateModel.bat:71`), 75 % kept per pass (`Simplify75per_Params.xml:4-11`), a noise
pass at 70 % (`SimplifyNoise_Params.xml:4`), `AdaptiveTexelSize` capped at 4096 with a
4 x 4096 fallback (`Texturing_AdaptiveTexel_4k.xml`, `Unwrapping_MaxCount4_4k.xml`),
JPG textures, the recipe order itself (`GenerateModel.bat:118-231`), export kinds
`obj`/`fbx`/`ply` with their presets, the 500k web tier in `run_decimate.py`, the
Cesium request shape (3D_CAPTURE, KTX2, DRACO) and the EGM2008 vertical datum
(`cesium_placement.py:60-61,414-471`).

Detected: the model report from `-exportReport` proves every `-selectModel` and every
delete, and carries the triangle count that drives the simplify loop
(`GenerateModel.bat:324-378`, `model_report.py`); the export census reads the tree
(pages, JPEG, 4096 cap, `map_Kd`) rather than a report file (`texture_census.py`).

Inherited: which components to model, from `merge_report.json` final components; the
scale gate and its verdicts; the assembly project. **The export CRS is inherited from
whatever the assembly project holds** - see gap G3.

## 4. Hand-off matrix

| From | To | Artifact | Written by | Read by | NOT carried |
|---|---|---|---|---|---|
| extract | georeference | `raw_images/` | `extract_images.py:254` | in-process when chained | fpm, megapixels |
| georeference | batch | `flight_log_<zone>_UTM.txt` written INTO the image folder | `georeference_images.py:899-901` | `find_flight_log` `batch_directory.py:417-437` | declination, accuracies, assumed mounts, acceptance rate - no stage report exists |
| preprocess | batch | `preprocessed_images/` (folder name is the contract) | `preprocess_images.py:162-183` | `batch_directory.py:412-414` | CLAHE parameters (no fingerprint) |
| batch | align | `zone_N/` trees, per-zone logs, `batch_inputs.json` | `batch_directory.py:1055-1126,366-383` | zone list and log by glob; `batch_inputs.json` is **not read by align** | zoning parameters, layout (re-derived by the planner) |
| align | merge | `<zone>_c<K>.rsalign` + `.manifest.json` | `AlignZone.bat:331`, `component_manifest.py:62-99` | `merge_zones.py:134-170` | frame, min size, settings, instance - all re-entered |
| align | scale oracle | `identity/<zone>_c<K>.csv` | `AlignZone.bat:313-314` | `scale_oracle.py:66-109` (since 2026-09-06) | nothing else reads the focal/k1/k2 columns |
| align | verify | `align_inputs.json` | `align_fingerprint.py:151-157` | `verify.py:76-204` | not read by merge |
| merge | model/export | `merge_report.json`, `assembly/*.rsproj`, `EVALUATION_READY.txt` | `merge_zones.py:1506-1509,1576-1588` | `run_models.py:241-247`, `run_plan.py:879-900` | the charter label (models re-derive it from the folder name); `EVALUATION_READY` is not checked by `run_models` |
| model | export | model NAMES inside the shared project (`<comp>_Simplified_Textured`, `<comp>_HighPoly_Raw`) | `GenerateModel.bat:231` | `ExportDeliverables.bat:166-182` | triangle counts and texture pages (measured, never persisted) |
| export | publish | `exports/<comp>/obj/` + `.rsInfo` | `ExportDeliverables.bat:166` | `publish_cesium.py`, `cesium_placement.py:125-187` | the CRS, unless the owner passed one |

## 5. XMP: what still writes and reads sidecars

The owner's belief that XMP sidecars are retired is correct for the ALIGN stage and
wrong for the MERGE stage.

**Dead under `identity_capture: csv`.** The align stage's destructive harvest
(`AlignZone.bat:356-392`, gated at `:274`), the calibration-sidecar repair
(`realityscan_interface.py:536-548`, "Calibration-sidecar repair skipped" in both run
logs), the XMP manifest reader (`realityscan_interface.py:755-846`), and the batcher's
sidecar writer (`batch_directory.py:945-989`, off by the `b_xmp_priors` default).

**LIVE under `csv`.**

1. **The merge peel census.** `merge_zones.py:813-815` sets `RS_MERGE_HARVEST=1` for
   EVERY ladder attempt, `MergeZoneComponents.bat:218` jumps to the harvest, and each
   lap runs `-exportXMPForSelectedComponent` (`:270`) followed by a PowerShell sweep
   that MOVES every pose-bearing sidecar into `identity_r<K>` (`:275`). Neither
   `merge_zones.py` nor the workflow reads `RS_LEGACY_XMP_IDENTITY`; the variable was
   in the merge environment and ignored. F2 produced 316 files (158 + 80 + 78).
   RealityScan writes them BESIDE THE IMAGES first (rs-reference 05:1139-1140), so the
   "zero XMP beside images" census is the post-move state; a lap that dies between the
   export and the move leaves them in the zone copies.
2. **`peel_counts_from`** (`merge_zones.py:823-842`) counts those files. That count is
   the merge's whole camera-accounting instrument.
3. **The fused-component scale** (`run_models.py:118-129` via
   `scale_oracle.solved_position_cloud:177-186`) reads `identity_r0` and has no CSV
   twin, so the model stage's gate depends on the peel's XMPs.
4. **`sanitize_and_census`** walks the zone tree after every attempt
   (`merge_zones.py:1034,1594`) and is a latent WRITER: a pose sidecar of a known
   camera is rewritten to calibration-only content (`camera_registry.py:522-526`).
5. Out of lane and ungated: `GrowZone.bat:275,290`, the plain (non-harvest) merge path
   `MergeZoneComponents.bat:220-234`, the deprecated `AlignImagesFromFolder.bat:163`.

**What a CSV port of the peel needs.** Replace `:270` and `:275` with
`-exportRegistration "<attempt>/identity/<name>_c<K>.csv" "%RegistrationParams%"`
exactly as `AlignZone.bat:313-314`, keep the `#cameras N` line-1 gate, and add the
format install and assert the merge stage does not run today
(`flightlog_format.install_all_managed` + `assert_calibration_format_installed`,
`realityscan_interface.py:473-477`). Readers to change: `peel_counts_from`, the
empty-peel invariant (`merge_zones.py:1041-1047`), `assert_harvestable` (`:1448`)
becomes unnecessary, and **`run_models.resolve_scale` must look for `identity/` beside
the fused `.rsalign`** or every fused component silently reverts to unmeasured. Tests
that pin the XMP shape: `test_merge_zones_rework.py:215-228`,
`test_cmd_boundary_guards.py:236-244` (asserts the PowerShell text in BOTH workflows),
`test_scale_gate.py:197-210`, `test_harvest_guard.py`. A bonus: the CSV's `#cameras`
header answers directly whether RealityScan folded the duplicate copies.

Also note `preflight.py:368` prints "identity capture: csv (-exportRegistration, no XMP
written)", which overclaims, and the whole `identity_capture` check sits inside
`if "align" in self.stages` (`preflight.py:366`), so a merge-only charter is never
even warned.

## 6. Gaps and flags, ranked

**G1 - The charter was authored by the AI, not answered by the owner.** Both
`signed_off.by` fields say so verbatim; the C0 charter copied F2's locations,
protected list, ownership and frame wholesale. `is_signed` only checks non-emptiness
(`run_charter.py:119-121`). Fix: make `rs charter` refuse a sign-off that names the
agent, and keep the six questions as a literal owner transcript.

**G2 - The merge stage writes XMP sidecars under a `csv` charter** (section 5). Fix:
port the peel to `-exportRegistration`, or gate the harvest on the same variable the
align stage reads.

**G3 - The export CRS was never declared. FIXED 2026-09-06.** The planner passed
neither `--crs` nor `--flight-log`, no stage environment carried `RS_PROJECT_CRS`
(`realityscan_interface.py:391` sets it only inside the align process), and
`export_deliverables.py:217-222` merely warned; H2077 stamped a 53N cruise as 57S and
H2060 a 2S dive as 55N. The export command now carries the same zone-tagged log the
publish command already got (`run_plan.py` export builder, `workspace_flight_log`),
from which `export_deliverables` derives the CRS. A local-frame campaign has no tagged
log and correctly gets nothing (`testing/test_run_plan_session.py`).

**G4 - The model stage would refuse the F2 component today.** `scale_gate.enabled` is
true, `input_scales` holds only the two zone inputs (both unmeasured), so
`run_models.resolve_scale` falls back to the quantile oracle over the peel's 158
sidecars. Replayed from disk during this audit it returns **fail at 0.641**, so
`run_models.py:310-316` would skip the component and exit with nothing modelled. Fix:
decide whether a 120-second fixture should be scale-gated at all, and give the gate a
bypass that is a charter answer rather than a re-merge.

**G5 - Zone science is a silent default.** Target, minimum, maximum, overlap, density
weight, KDE bandwidth, overlap distance cap and `use_z` are never asked
(`preflight.py:415-421` asks only required and path/file answers). With the declared
defaults a 363-image survey collapses to one zone and the merge path is never
exercised. The batcher then refuses a target below 100 at start-up - which killed the
first C0 launch after preflight said READY. Fix: make the zoning answers required
intake questions, and keep the module-bounds check that now runs
(`preflight.py:895-955`).

**G6 - `identity_capture` unset selects the destructive path.** Warning only
(`preflight.py:373-376`). The check used to run only when align was planned, so a
merge-only charter was never even warned; since 2026-09-06 it runs for align OR merge,
and the `csv` line no longer claims that nothing writes XMP. Still a warning: making it
required, or flipping the default, waits on decision D1.

**G7 - An unknown camera answers nothing.** Preflight asks per prefix
(`preflight.py:464-473`) but `cam_*` answers are dropped from the command line and
`write_camera_records` is never called by `rs.py` (`run_plan.py:828-869`). The
georeference module then proceeds with zero lever arm, an assumed 10 degree pitch at
30 degree accuracy and no focal, with one warning whose text is stale. Fix: wire the
answer into `cameras.json` or refuse the run.

**G8 - The lane writes into paths the charter declares protected.** Both runs wrote
`rs_settings.json` in the repo root (`settings_store.py:251-255` via the batcher's
prompts and the merge's `ask`), leaving C0's zone sizes and F2's merge flags as the
next interactive run's defaults; every align also installs format ids into
`C:\Program Files\...\RealityScan_2.2\` and writes marker files inside the checkout. No
driver calls `guard_write` (defined at `run_charter.py:330`, called only from tests).
Fix: set `RS_SETTINGS_PATH` to the agent workspace in the launcher, and have the
drivers consult the charter.

**G9 - Values re-entered rather than carried.** `science.min_component_size` fans out
to two flags; the frame is re-derived from the filename at every stage; the merge
regenerates its own flight-log parameters and never reads `align_inputs.json`; the
charter label reaches merge but not align (`r_project_label` empty, so zones get no
dated copy) and not `run_models` (which re-derives it from the folder name, producing
two differently named copies). Partly fixed 2026-09-06: `align_inputs.json` now records
`identity_capture` and `verify` BLOCKS a csv zone merged with an xmp zone
(`align_fingerprint.py`, `verify.py`, `testing/test_verify_oracle.py`). The label and
min-size fan-out remain owner decisions.

**G10 - Detectors that fail open.** A nav table in an unknown datum projects silently;
out-of-range rows become empty coordinates and are dropped by the batcher; a log that
loses its zone tag is treated as a local-frame campaign; `preprocessed_images` is
chosen by existence; `load_inputs` silently drops a manifest whose `.rsalign` is
missing (`merge_zones.py:165-166`).

**G11 - Settings inheritance is only half refused.** `RS_NO_SETTINGS_INHERITANCE`
blocks prompt defaults but not `SettingsStore.get` (`settings_store.py:238-241`), so
`RS_HEADLESS`, GPU pinning, the shutdown timeout, the executable path and the
instance-name fallback still come from `rs_settings.json`. Both 2026-09-06 runs booted
GUI-visible instances under a hidden scheduled task because of it.

**G12 - No per-stage report.** Extract and georeference statistics (acceptance rate,
unknown cameras, the accuracies actually used, the declination) exist only in console
logs; model reports prove triangles and textures at run time but `models_report.json`
records none of them. `rs verify` cannot see any of it.

**G13 - Assembled by hand on 2026-09-06, with no code path:** the fixtures, the
scheduled-task lines and their deletion, the copies of RealityScan's own event logs,
the post-run XMP and focal census (`analyze_csv_run.py`), and the probe's edited
flight-log parameters file. Each is a candidate for an `rs` subcommand.

**G14 - Small things worth fixing in passing:** `publish_nira.py` looked for
`.rcinfo` only while RealityScan 2.2 writes `.rsInfo`, so the georeferencing sidecar
was never uploaded (fixed 2026-09-06); `GenerateModel.bat:242-252` defines
one label twice; `ExportDeliverables.bat:184-189` is unreachable after `exit /b 0`;
`model_report_*.html` is written into the checkout and is not gitignored;
`preflight.py:119` validates `AlignmentParams.xml` for the merge stage, which never
applies it.

## 7. What the AI decides, what it must ask

**The AI may decide alone:** which stage to run next from the charter's stage list;
whether preflight is READY; how to phrase what preflight reports missing; when to stop
a run against the declared abort criteria; how to census the result and what to record
in `FINDINGS.md`; whether an observed number contradicts a recorded finding.

**The AI must ask, and must not fill in:** every line preflight lists as `missing`;
every row of section 2, including the ones the lane does not ask for yet (zone sizes,
overlap, identity capture, minimum component size, export CRS, the georeference science
values, publish credentials); the identity and mounting of an unrecognised camera; any
change to a baked constant; the sign-off. The rule the 2026-09-06 runs broke is the
one that matters most: an answer derived from a directory listing, from a previous
campaign, or from the AI's own reasoning is not an owner answer, and the lane cannot
currently tell the difference.
