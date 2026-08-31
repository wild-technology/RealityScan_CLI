# CLAUDE.md — project context for RealityScan_CLI

ROV underwater photogrammetry pipeline driving **RealityScan 2.2** (Epic
Games; the product formerly named RealityCapture) via its CLI. Runs on
Windows with a multi-GPU CUDA setup.

Continuation of `wild-technology/RC_Main` (created from its
`claude/realityscan-repo-cleanup-2gjmu5` branch, July 2026 overhaul, full
history preserved — `git log` reaches all the way back). RC_Main is frozen;
new work happens here.

---

## Starting a session

Read in this order, then say in one line what you are about to do:

1. **`HANDOFF.md`** — current state, what is running, ranked loose ends,
   exact next commands. Read this **before the first mutating action**.
2. **This file** — architecture, hard rules, working practices.
3. **`docs/rs-reference/README.md`** — the RealityScan manual's routing
   index. It sends any RealityScan question to one of 14 documents in one
   hop. Do not answer a CLI question from general knowledge; route it.

**Do not read `FINDINGS.md` cover to cover** (2,400+ lines). It is a
grep target: search it for the command, key, or symptom you care about.
Same for `docs/` and `testing/` — they are cited sources, not orientation
reading.

Baseline before touching anything:

```bash
py -3.13 -m pytest testing -q
```

498 tests, ~30 s. If they do not pass on a clean checkout, stop and report
— you have inherited a broken tree and anything you build on it is suspect.

## Working practices for any session

These apply regardless of task. They exist because each was learned the
expensive way.

- **Verify by census, never by exit status.** RealityScan exits SUCCESS
  while doing nothing — merges that do not fuse, settings that never
  applied, exports that wrote zero files. Count cameras, count sidecars,
  diff manifests. `docs/rs-reference/12-failure-modes-and-race-conditions.md`
  is the catalogue of every silent-success mode found so far.
- **Own your instance before you run anything.** A cross-session incident
  (2026-07-28) had one session running on `RS1` while believing it was
  isolated on `RS2`, and it overwrote another session's `rs_settings.json`.
  Resolve `RS_INSTANCE` and `RS_GPU_DEVICES` explicitly, check no other
  instance holds that name, and never write another session's settings.
- **Write findings at the moment of discovery**, in the same turn, to
  `FINDINGS.md`. Deferred logging is lost logging. Refuted hypotheses stay,
  marked SUPERSEDED — deleting one guarantees rediscovering it.
- **Declare a budget before any long run**: expected duration, expected
  resource peak, abort criterion. Then "is it stuck?" is a lookup, not a
  judgment call. Model generation has been measured to run 40–340 min per
  component and to peak near total system commit; watch RAM unasked.
- **Snapshot evidence immediately.** `RealityScan.log` is global and
  truncated on every instance boot — the reason line behind a generic
  failure exists only until the next boot. Copy it inside the driver, right
  after the failing call returns.
- **One variable per iteration.** Escalation ladders change exactly one
  thing per attempt with per-attempt evidence. A re-align that changed
  several things at once cannot attribute its result to any of them.
- **Checkpoint before mutating, and rehearse the restore.** A loop without
  a tested rollback is a ratchet toward corruption.
- **Prefer the mini fixture.** No workflow change touches production data
  until it passes a <5 min smoke fixture. Smoke fixtures have caught the
  large majority of workflow bugs at a fraction of the cost.
- **Report incompleteness in chat, not in the file.** No TODOs, stubs, or
  commented-out code left behind.

Escalate rather than work around: invariant violations, two monitors
disagreeing about one run, a resource trend projecting past capacity, a
result that would revise an ESTABLISHED finding, or anything on the
blindness list (GUI state, georeferencing correctness, seam quality)
becoming load-bearing for a conclusion.

## Ending a session

`HANDOFF.md` outlives the session and is what the next one reads first.
Before you stop: findings flushed to `FINDINGS.md`; running processes
documented with resume commands; work committed or explicitly stashed with
reasons; `HANDOFF.md` refreshed with done / running / ranked loose ends /
artifact locations / exact next commands.

## Environment

- Windows 11, native. **No WSL** — cmd, `.bat`, PowerShell, VBS are the
  substrate. `.bat` and `.vbs` must be CRLF (`.gitattributes` pins it);
  LF breaks cmd's byte-offset label search nondeterministically.
- Python is `py -3.13`. `ruff` is **not installed** here — the style check
  in the account-level agreement cannot run; say so rather than claiming it
  passed.
- ASCII-only console output; the cp1252 console crashes on non-ASCII. Set
  `PYTHONIOENCODING=utf-8` when parsing UTF-8 sources.
- Data lives on large local/NAS volumes with user-specific paths. Never
  hardcode them — prompt through `SettingsStore`.

---

## RealityScan reference

**`docs/rs-reference/`** is the consolidated manual: the shipped offline
Help (`C:\Program Files\Epic Games\RealityScan_2.2\Help\en-US\`, which is
the only reliably readable form of the official docs — the public site is
JS-rendered), the install-tree XML format dictionaries, and this repo's
empirical record. 218 command names, 740 settings keys, 84 numbered failure
modes. Every claim carries a provenance tag; `[CONTRADICTED]` entries state
both what the docs claim and what was observed.

Consult it before writing any new RealityScan workflow. Start at its
`README.md`; the "facts that silently destroy a run" table is the highest
-value page in the repo.

The few facts worth carrying in context without a lookup:

- Delegated commands (`-delegateTo <instance> <cmd>`) are QUEUED; the
  delegating process returns at hand-over, not completion.
- `-waitCompleted <instance>` returns prematurely if issued before the
  instance picks up the queued command — hence the double-wait in `:run`.
- `-getStatus <instance>` → errorlevel 0 iff the instance exists, but
  "gone" precedes process teardown by seconds (file handles outlive it).
  It also prints a live progress line on stdout (capture by redirecting;
  RealityScan is a GUI-subsystem binary): `id:<op> progress:<pct>
  runtime:<s> endEstimation:<s> rev:<n> lastError:<code>`. `rev:` tracks
  scene MUTATIONS, not operations.
- **`*` is a valid instance argument** meaning "first available instance",
  accepted by `-delegateTo`, `-waitCompleted`, `-getStatus`,
  `-pauseInstance`, `-unpauseInstance` and `-abortInstance`. A GUI or
  Epic-Launcher RealityScan has no `-setInstanceName` and answers no named
  lookup, but IS reachable via `*`. Ambiguous once two instances run — use
  explicit names for multi-GPU, `*` only to attach to a single interactive
  session.
- App settings use `app*` key names. The legacy `RealityCapture*` names are
  dead.
- Exit codes: 0 = success; with `appQuitOnError=true` the error's decimal
  code; 3 = crash (minidump at the `-silent` path).
- Multi-GPU: RealityScan uses all CUDA GPUs by default. Pin via
  `RS_INSTANCE` + `RS_GPU_DEVICES` (exported as `CUDA_VISIBLE_DEVICES`),
  one instance name per GPU set.

## Findings log

`FINDINGS.md` at the repo root is the running log of every discovered fact
— CLI behaviors, merge semantics, rig data, process conventions — each with
HOW it was discovered. Append whenever a fact is established; keep entries
short and dated. It is the raw log; the distilled counterpart is
`docs/rs-reference/`, and deep rationale lives in `docs/`.

## Naming

Everything in this repo says **RealityScan** (`RS`), never RealityCapture.
Exceptions that must NOT be renamed:

- RealityScan API identifiers that happen to be current product strings
  (e.g. `reader="RealityScan.Import.CSVFlightLog"` in `flightlogs.xml`,
  feature-detector ids in `Metadata/AlignmentParams.xml`);
- legacy file extensions `.rcalign`/`.rcproj`, still accepted when reading
  old outputs (new saves use `.rsproj`).

---

## Architecture

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
  `merge_report.json`).
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
  - Production: `AlignZone` (canonical per-zone align — applies
    `AlignmentParams.xml`, saves the scene, then runs the destructive
    in-session identity loop: per lap `-exportXMP` stems are harvested to
    `identity_r<K>`, the maximal component is renamed `<zone>_c<K>`,
    exported and deleted; membership = successive difference, census =
    manifest sum; quits WITHOUT saving; NO model generation),
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

---

## When an AI agent is DRIVING (owner said "run this against that dataset")

MANDATORY — full contract in `docs/AGENT_OPERATIONS.md`; on conflict this
section wins. Every rule traces to a recorded incident.

1. **No writes before the charter.** Run the intake (docs/
   RUN_CHARTER.template.md): ask the user — never infer — where the
   ORIGINALS are, where the NAV is, where OUTPUTS go, and what is
   PROTECTED. Owner signs off; then work.
2. **Source data is read-only, forever.** This pipeline writes sidecars
   into input folders — an agent aligns only from trees it created
   (hardlinks/copies) or with explicit consent.
3. **Protected paths** (charter list) are never touched, cleaned, or
   reorganized. Deliverables are never overwritten — collisions are
   stop-and-ask.
4. **Agent working files live in ONE place**: `<results_root>/_agent/`.
   Never in the repo, never beside source data. It is the only tree the
   agent may delete freely.
5. **Own instance, own processes.** Charter-named RS instance (never the
   user's), own cache. Never kill/quit/delegate-to anything the agent
   did not start; identify by PID+cmdline first.
6. **Long runs are scheduler-owned** (schtasks + CRLF launcher, never a
   harness shell — job objects killed 14.4 h once), with a written
   budget declaration and liveness-tested monitors BEFORE launch.
7. **Frames and fingerprints**: honor FRAME_WARNING markers and
   align_inputs.json; never mix coordinate frames; components without a
   current-nav fingerprint are not "done".
8. **Every science argument explicit** — no rs_settings inheritance
   unattended. **Owner gates (`confirmed: false`) are stops, never flags
   to flip.**
9. **Destructive ops need per-instance user approval**: anything outside
   the agent workspace, force-pushes, killing user processes, app-global
   RealityScan settings (they leak into the user's GUI), raising safety
   ceilings.

## Hard rules

1. Never add a second way to launch/monitor RealityScan — extend
   `RealityScanCLI` and the `:run` pattern instead.
2. Never infer completion from process names (`tasklist`); the pre-2.x code
   did that with `RealityCapture.exe` and silently broke at the rename.
3. No overall timeouts on RealityScan operations — 10+ hour runs are
   normal. Startup and shutdown are the only bounds; the authoritative
   values are the constants in `realityscan_cli.py`
   (`SHUTDOWN_VERIFY_TIMEOUT_SECONDS`, `STATUS_CALL_TIMEOUT_SECONDS`),
   not a number quoted in prose.
4. Clear `progress.txt` / `errors.txt` / `results.log` only through
   `RealityScanCLI` (it does this pre-run); they are the source of truth
   while a run is live.
5. Data lives on large local/NAS volumes with user-specific paths — never
   hardcode them. Use `SettingsStore` prompts with the previous value as
   default.
6. `geoall.py` is the canonical georeferencing implementation; port
   improvements from it into `modules/georeference/` rather than letting
   the two diverge further.
7. Import components (`-importComponent`) ONLY from their original export
   location — a relocated `.rsalign` hangs the instance forever in a
   `#timeout` state.
8. Never pass delimited data as `.bat` arguments: cmd splits unquoted
   `;` `,` `=` and Python's subprocess only quotes on whitespace. Lists
   cross the boundary as files (`.complist`/`.imagelist`); settings as
   `key:value` (converted inside the workflow).
9. `docs/rs-reference/` is the RealityScan documentation of record —
   consult it before writing any new workflow. The historical test matrices
   (`testing/MERGE_TEST_PLAN.md`,
   `testing/ALIGN_MERGE_HARDENING_PLAN.md`,
   `testing/PRIORS_DISTORTION_TEST_PLAN.md`) track design assumptions not
   settled by documentation; cells graduate into `FINDINGS.md` with
   results. `testing/NA167_SESSION_NOTES.md` is a **frozen** raw log kept
   as the citation target for `NA167 B*`/`#*` references — read it for
   provenance, not for current behavior.

## History notes

An earlier, richer iteration (delegation client, GUI, tests, docs) was
reverted by the `main_v2` merge — it survives only in git history around
commit `4bc8549`. Its race-condition lessons are baked into the current
execution layer; consult it before re-deriving old solutions.
