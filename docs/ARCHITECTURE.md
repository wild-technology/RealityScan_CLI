# Architecture — RealityScan_CLI

The module-by-module map of the repo. Split out of `CLAUDE.md` (2026-08-31)
because it is REFERENCE material: CLAUDE.md is loaded on every turn of
every session, including every subagent, and this is content you look up
when you touch a subsystem rather than something you must know before the
first action. CLAUDE.md keeps the invariants and routes here.

Grep this file; do not read it through.

---

**Entry points**

- `main.py` — interactive orchestrator over the `RSModule` framework
  (`module_base/rs_module.py`): Extract Images → Georeference → Preprocess
  Images → Batch Directory → RealityScan Alignment. `RS_MODULES` /
  `RS_NO_INTERACTIVE` env vars select modules without a TTY; a module
  reporting Success=False stops the chain (exit 1).
- `wildscan/` — TUI interaction portal (`py -3.13 -m wildscan`): intake,
  runnable model/export/publish stages over the same drivers.
- `merge_zones.py` — iterative component-merge driver (escalating
  mechanism/flags, per-attempt RealityScan.log snapshots + census,
  `merge_report.json`). `--resume` (default true) reuses converged clusters from a prior
  `merge_report.json` whose `run_fingerprint` matches the current inputs and
  settings (sidecars branch 2026-09-03; `testing/test_merge_resume.py`).
- `grow_zone.py` — incremental grow-from-neighbor driver, the workaround
  for zones that fail to align standalone.
- `run_models.py` — per-component model generation, scale-gated.
- `publish_nira.py` / `publish_cesium.py` / `publish_batch.py` —
  deliverable publishers. Nira wants OBJ (not FBX) and refuses PLY point
  clouds. Cesium ion takes raw OBJ as `sourceType=3D_CAPTURE`, placed by
  `options.position` — see `modules/cesium_placement.py` below, and never
  publish without `--verify`.

**RealityScan execution — the ONLY place RealityScan is executed**

`modules/realityscan_interface/`:

- `realityscan_cli.py` — unified execution layer (`RealityScanCLI`). All
  new RealityScan-invoking code goes through it. Owns executable discovery,
  per-instance lock files, marker-file hygiene (60 s retry for the
  getStatus/teardown handle race), progress tailing, stall warnings
  (`#timeout`-aware), and verified instance shutdown.
- `RS_CLI/Scripts/*.bat` — workflow definitions. Every operation runs
  through the shared `:run` subroutine: `-delegateTo %RS_INSTANCE%` →
  double `-waitCompleted` with a grace period → abort if
  `RS_CLI/Errors/errors.txt` is non-empty.
  - Production: `AlignZone` (canonical per-zone align — adds the zone,
    pins both CRS scopes from `RS_PROJECT_CRS`, replays the
    `RS_PRIOR_GROUPS_FILE` command file, applies EVERY
    `AlignmentParams.xml` key (refusing `app*` keys), imports the flight
    log LAST, aligns, saves the scene, then
    by DEFAULT runs the destructive in-session identity loop: per lap
    `-exportXMP` stems are harvested to `identity_r<K>`, the maximal
    component is renamed `<zone>_c<K>`, exported and deleted; membership
    = successive difference, census = manifest sum; quits WITHOUT saving;
    NO model generation. `RS_LEGACY_XMP_IDENTITY=0` selects the
    non-destructive alternative instead — `-exportLatestComponents`, then
    per component `-selectComponent` / `-renameSelectedComponent` /
    `-exportRegistration` into `<output>/identity/<zone>_c<K>.csv` using
    `RegistrationExportParams.xml`, read back by
    `capture_component_identities` (layout-driven). Which one is the
    default is open decision D1 — see hard rule 0),
    `MergeZoneComponents` (`.complist` of in-place `.rsalign` paths;
    merge|align mode; min size; `key:value` settings — driven iteratively
    by `merge_zones.py`), `GenerateModel` (mesh/cull/texture/simplify
    ONCE, on the merged component), `ExportDeliverables` (OBJ-by-parts +
    FBX-by-parts + ultra-dense colored PLY), `SaveProjectCopy`.
  - Boot/env: `startRealityScan`, `SetVariables`. Boot honors
    `RS_HEADLESS=0` for a GUI-visible instance.
  - Supporting/testing: `GrowZone`, `NightGrow` (attach-only seed growth;
    `%1` = target instance), `GuiWorkbench`, `ComputeModel`,
    `CalibCellAlign`, `FlushCache` (sets retention 0 during the clear —
    the 7-day default kept 918 GB), the `ProbeCalibGroups*` /
    `ProbeFlightlog*` / `ProbeExportSettings` probes, and
    `AlignImagesFromFolder` (DEPRECATED; kept for
    `testing/run_zone9_tests.py`). `AlignImageList`, `SequentialAlignGrow`
    and the `ProbeSubsetAlign*` / `ProbeLockAlign` probes now live in
    `archive/legacy_scripts/`.
  - **`ModelToFinal` is the one exception to the `:run` boot pattern.** It
    finishes a mesh that ALREADY exists (texture → simplify → unwrap →
    reproject → export → save) and **attaches** to a running instance
    instead of booting one: it deliberately does NOT call
    `startRealityScan.bat`, because that script issues
    `-newScene -deleteAutosave` when `-getStatus` finds an instance already
    running, which would destroy the very scene it was asked to finish. It
    delegates to `%RS_TARGET%` (not `%RS_INSTANCE%`), accepts `*` as the
    instance, and gates on the `lastError:` + `rev:` fields of `-getStatus`
    rather than `errors_<instance>.txt` — that marker file only exists for
    an instance booted by `startRealityScan.bat`, so a GUI or Epic-Launcher
    instance never writes one. `finish_model.py` is its driver. Use
    `GenerateModel` for the normal path where the pipeline owns the
    instance and computes the mesh itself.
- `RS_CLI/Errors/ErrorWriter.bat` — invoked by RealityScan itself
  (`appProcessAction=ExecuteProgram`); appends every completion to
  `results.log`, failures to `errors.txt`. `ErrorWriterLaunch.vbs` is the
  GUI-subsystem launcher that keeps console windows from popping.
- `RS_CLI/Metadata/*.xml` — parameter presets passed to CLI commands.
  Documented profile by profile in
  `docs/rs-reference/09-xml-parameter-files.md`.
  `RegistrationExportParams.xml` (sidecars branch, 2026-09-03) is the
  `-exportRegistration` preset for the non-destructive identity capture:
  its `calexFileFormatId` resolves against `calibration.xml` in the
  RealityScan INSTALL dir, so `flightlog_format.install_all_managed()` +
  `assert_calibration_format_installed()` run before every AlignZone;
  override the path with `RS_REGISTRATION_PARAMS`.

**Domain modules**

- `modules/camera_registry.py` — single source of truth for the FOUR
  physical rig cameras (Zeuss rect 23mm, Port fisheye 14mm, Cinema rect
  17mm, Starboard fisheye 14mm; legacy cammid/camlower/camupper and WCA
  P/C/S###C filename families). Calibration XMP content and the pose-sidecar
  sanitize/census live here. Mount geometry stays per-cruise in the
  georeference module.
- `modules/flight_logs.py` — flight-log discovery (`find_flight_log`, the
  ONLY way any stage locates a log on disk) and per-cruise CRS generation
  (`write_flight_log_params`: UTM zone parsed from the log's filename tag →
  EPSG → FlightLogParams XML; never hand-edit the template's zone).
  Consumers match by NORMALIZED BASENAME. Architecture and the P1/P3/P4
  probe closures: `docs/FLIGHTLOG_ARCHITECTURE.md`.
- `modules/flightlog_format.py` — guarantees the flight-log FORMAT is
  installed where RealityScan looks. Format GUIDs (`gpsLogFileFormat`)
  resolve against `flightlogs.xml` **in the RealityScan install
  directory**, not this repo, and a missing GUID does NOT error — the
  import falls back and silently DROPS the columns that format defined.
  `assert_format_installed()` runs before every import and SELF-HEALS by
  merging the repo's formats. It also manages `calibration.xml`
  (registration export). Both install files are reverted by RealityScan
  updates, which is why repair is code, not a chore (this bug shipped
  twice — see FINDINGS 2026-08-16).
- `modules/prior_groups.py` — calibration/lens prior GROUPING applied
  in-session instead of via calibration XMPs beside the images.
  `write_command_file(image_root, dest)` turns the `camera_registry`
  filename families present under `image_root` into one
  `-deselectAllImages` / `-selectImage "<regexp>"` /
  `-setPriorCalibrationGroup <n>` / `-setPriorLensGroup <n>` block per
  family, written as a command FILE (hard rule 8) that
  `realityscan_interface.py` hands to `AlignZone.bat` through
  `RS_PRIOR_GROUPS_FILE` (unset when no family is recognised, so a stale
  file is never replayed; generated from the pool root in pool layout).
  Grouping only — numeric intrinsics come from the flight log's
  `FocalLength` column (or, on main's default path, the calibration XMP).
  **OPEN DECISION D1** (FINDINGS `[RECON] 2026-09-03 - prior-groups
  claim: main and remove-xmp-sidecars disagree`): main measured
  `-setPriorCalibrationGroup` as silently non-functional from the
  delegated CLI (2026-08-08, solved-focal-equality oracle); the sidecars
  branch ran NA168 H2080 and NA165 H2063 with this delivery in the
  workflow but never measured the effect. Treat neither claim as settled.
- `modules/calibration_sidecars.py` — per-eye approximate calibration XMPs
  from manufacturer values, plus the sensor registry. The A/B/C ladder
  verdict (prior content collapses registration) is in `FINDINGS.md`.
- `modules/preprocess_images/` — canonical CLAHE / white-balance transforms
  + the pre-alignment preprocessing module (default CLAHE 2.0/8×8,
  validated on zone_9 — baseline aligns to nothing on this imagery).
  `testing/preprocess_variants.py` imports the transforms from here; keep
  it that way (no second implementation).
- `modules/image_batcher/batch_directory.py` — zone batching. Note the
  duplicate-path identity problem: copying overlap images into two zones
  gives one trajectory row two physical files.
- `modules/scale_oracle.py` — metric-scale measurement and the 0.90–1.10
  acceptance band. Fused components need the correspondence-free method
  (`archive/campaign_drivers/run_h2024_fused_models.py`), since merge-scene
  XMP exports are ordinal.
- `modules/component_analysis.py`, `modules/component_manifest.py` —
  component census, membership, and border logic.
- `modules/workspace_census.py` — workspace-level census: what components,
  models and exports exist on disk for a project, and the name mapping
  persisted at capture time.
- `modules/feature_merge.py` — 3D extents, feature-box assignment, and
  merge planning that reports what it can and cannot glue.
- `modules/align_fingerprint.py` — align-input fingerprinting, so retries,
  resumes and merges are nav-aware.
- `modules/export_deliverables.py` — the Python side of the export stage.
- `modules/cesium_placement.py` — where a mesh belongs on the WGS84 globe.
  Reads the export's `.rsInfo` for the CRS and `transformToModel`, DERIVES
  which reading of that matrix is correct (validated against the CRS area of
  use, the dive's nav envelope, and a determinant test that rules out
  mirrored readings), then converts the anchor's SEA-SURFACE depth to an
  ELLIPSOIDAL height through EGM2008 and localises the mesh into East-North-Up
  metres. **The vertical is the whole point:** `geoall.py` writes
  `-abs(kalman_depth)`, i.e. a depth below the sea surface, and Cesium reads
  every height as above the ellipsoid — the gap is the geoid undulation, up to
  +72.7 m on this repo's own data. PROJ silently applies a ZERO correction
  when the geoid grid is missing, so every transformer here passes
  `allow_ballpark=False`.
- `modules/file_metadata_parser.py` — image metadata extraction.
- `module_base/settings_store.py` — persists last-entered prompt answers to
  `rs_settings.json` (repo root, gitignored) and offers them as defaults.
  All user-facing path prompts must go through it.

**Standalone / retired**

- `geoall.py`, `poses2flightlog.py`, `decimator.py`, `timestamp_rename.py`,
  `organize_by_date.py` — data prep; they do not invoke RealityScan.
- `archive/colmap/` — retired COLMAP scripts; do not resurrect into the
  active pipeline.
- `archive/campaign_drivers/`, `archive/legacy_scripts/` — finished
  campaign drivers and superseded workflows, kept as citation targets for
  `FINDINGS.md`. Read for provenance; do not wire back in.
