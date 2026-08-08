# CLAUDE.md — project context for RealityScan_CLI

ROV underwater photogrammetry pipeline driving **RealityScan 2.2** (Epic
Games; the product formerly named RealityCapture) via its CLI. Runs on
Windows with a multi-GPU CUDA setup.

This repo is the continuation of `wild-technology/RC_Main` — it was
created from RC_Main's `claude/realityscan-repo-cleanup-2gjmu5` branch
(July 2026 overhaul) with full history preserved, so `git log` reaches all
the way back. RC_Main is frozen; new work happens here. See `HANDOFF.md`
for the state of the overhaul and what still needs on-machine
verification.

## Findings log

`FINDINGS.md` at the repo root is the running log of every discovered
fact — CLI behaviors, merge semantics, rig data, process conventions —
each with HOW it was discovered. Append to it whenever a new fact is
established (a failed run diagnosed, a Help/forum fact verified, an
owner-confirmed rig detail); keep entries short and dated. It is the
quick reference; deep rationale lives in docs/.

## Naming

Everything in this repo says **RealityScan** (`RS`), never RealityCapture.
Exceptions that must NOT be renamed:
- RealityScan API identifiers that happen to be current product strings
  (e.g. `reader="RealityScan.Import.CSVFlightLog"` in `flightlogs.xml`,
  feature-detector ids in `Metadata/AlignmentParams.xml`);
- legacy file extensions `.rcalign`/`.rcproj`, still accepted when reading
  old outputs (new saves use `.rsproj`).

## Architecture

- `main.py` — interactive orchestrator over the `RSModule` framework
  (`module_base/rs_module.py`): Extract Images → Georeference → Preprocess
  Images → Batch Directory → RealityScan Alignment. `RS_MODULES` /
  `RS_NO_INTERACTIVE` env vars select modules without a TTY; a module
  reporting Success=False stops the chain (exit 1).
- `modules/camera_registry.py` — single source of truth for the FOUR
  physical rig cameras (Zeuss rect 23mm, Port fisheye 14mm, Cinema rect
  17mm, Starboard fisheye 14mm; legacy cammid/camlower/camupper and WCA
  P/C/S###C filename families). Calibration XMP content and the
  pose-sidecar sanitize/census live here. Mount geometry stays per-cruise
  in the georeference module.
- `merge_zones.py` — iterative component-merge driver (escalating
  mechanism/flags, per-attempt RealityScan.log snapshots + census,
  merge_report.json).
- `modules/preprocess_images/` — canonical CLAHE / white-balance
  transforms + the pre-alignment preprocessing module (default CLAHE
  2.0/8×8, validated on zone_9 — baseline aligns to nothing on this
  imagery). `testing/preprocess_variants.py` imports the transforms from
  here; keep it that way (no second implementation).
- `modules/flight_logs.py` — flight-log discovery (`find_flight_log`,
  the ONLY way any stage locates a log on disk) and per-cruise CRS
  generation (`write_flight_log_params`: UTM zone parsed from the log's
  filename tag → EPSG → FlightLogParams XML; never hand-edit the
  template's zone).
- `modules/realityscan_interface/` — the ONLY place RealityScan is
  executed:
  - `realityscan_cli.py` — unified execution layer (`RealityScanCLI`).
    All new RealityScan-invoking code must go through it. It owns
    executable discovery, per-instance lock files, marker-file hygiene
    (with a 60 s retry for the getStatus/teardown handle race),
    progress tailing, stall warnings (`#timeout`-aware), and verified
    instance shutdown.
  - `RS_CLI/Scripts/*.bat` — workflow definitions. Every operation runs
    through the shared `:run` subroutine: `-delegateTo %RS_INSTANCE%` →
    double `-waitCompleted` with a grace period → abort if
    `RS_CLI/Errors/errors.txt` is non-empty. Production workflows
    (2026-07-23 consolidation, see docs/settings-evaluation-2026-07.md):
    `AlignZone` (canonical per-zone align: applies AlignmentParams.xml,
    then saves the scene and runs the destructive in-session identity
    loop - per lap -exportXMP stems are harvested to identity_r<K> and
    the maximal component is renamed <zone>_c<K>, exported, and deleted;
    membership = successive difference, census = manifest sum; quits
    WITHOUT saving. NO model generation),
    `MergeZoneComponents` (.complist of in-place .rsalign paths;
    merge|align mode; min size; `key:value` settings — driven iteratively
    by `merge_zones.py`),
    `GenerateModel` (mesh/cull/texture/simplify ONCE, on the merged
    component). Supporting/testing: `AlignImageList` (.imagelist input),
    `SequentialAlignGrow` (incremental add→log→align),
    `AlignImagesFromFolder` (DEPRECATED; kept for run_zone9_tests.py).
    Boot honors `RS_HEADLESS=0` for a GUI-visible instance.

    **`ModelToFinal` is the one exception to the paragraph above.** It
    finishes a mesh that ALREADY exists (texture → simplify → unwrap →
    reproject → export → save) and **attaches** to a running instance
    rather than booting one: it deliberately does NOT call
    `startRealityScan.bat`, because that script issues
    `-newScene -deleteAutosave` when `-getStatus` finds an instance
    already running, which would destroy the very scene it was asked to
    finish. It therefore delegates to `%RS_TARGET%` (not `%RS_INSTANCE%`),
    accepts `*` as the instance (see below), and gates on the
    `lastError:` + `rev:` fields of `-getStatus` rather than
    `errors_<instance>.txt` — that marker file only exists for an
    instance booted by `startRealityScan.bat`, so an instance from the
    Epic Launcher or any foreign GUI session never writes one. Use
    `GenerateModel` for the normal path where the pipeline owns the
    instance and computes the mesh itself.
  - `RS_CLI/Errors/ErrorWriter.bat` — invoked by RealityScan itself
    (`appProcessAction=ExecuteProgram`); appends every completion to
    `results.log`, failures to `errors.txt`.
  - `RS_CLI/Metadata/*.xml` — parameter presets passed to CLI commands.
- Standalone scripts at repo root (`geoall.py`, `decimator.py`,
  `masking.py`, `organize_by_date.py`) — data prep; they do not invoke
  RealityScan.
- `module_base/settings_store.py` — persists last-entered prompt answers
  to `rs_settings.json` (repo root, gitignored) and offers them as
  defaults. All user-facing path prompts must go through it.
- `archive/colmap/` — retired COLMAP scripts; do not resurrect into the
  active pipeline.

## RealityScan 2.2 CLI facts (verified against Epic docs)

- Delegated commands (`-delegateTo <instance> <cmd>`) are QUEUED; the
  delegating process can return before the operation finishes.
- `-waitCompleted <instance>` blocks until the current process finishes
  but can return prematurely if issued before the instance picks up the
  queued command — hence the double-wait in `:run`.
- `-getStatus <instance>` → errorlevel 0 iff the instance exists (used
  for readiness and shutdown verification). It ALSO prints a live
  progress line on stdout (capture by redirecting; RealityScan is a
  GUI-subsystem binary): `id:<op> progress:<pct> runtime:<s>
  endEstimation:<s> rev:<n> lastError:<code>`.
- **`*` is a valid instance argument** meaning "first available
  instance", accepted by `-delegateTo`, `-waitCompleted`, `-getStatus`,
  `-pauseInstance`, `-unpauseInstance` and `-abortInstance`. A
  GUI/Epic-Launcher RealityScan has no `-setInstanceName` and so answers
  no named lookup, but IS reachable via `*`. Ambiguous once two
  instances run — use explicit names for multi-GPU, `*` only to attach
  to a single interactive session.
- App settings use `app*` key names (`appQuitOnError`, `appAutoSaveMode`,
  `appProcessAction`, `appProcessActionTime`, `appProcessExecCmd`). The
  legacy `RealityCapture*` key names are dead.
- Exit codes: 0 = success; with `appQuitOnError=true` the error's decimal
  code; 3 = crash (minidump written to the `-silent` path).
- Multi-GPU: RealityScan uses all CUDA GPUs by default. Pin instances via
  `RS_INSTANCE` + `RS_GPU_DEVICES` (exported as `CUDA_VISIBLE_DEVICES`),
  one instance name per GPU set.

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
2. Never infer completion from process names (`tasklist`); the pre-2.x
   code did that with `RealityCapture.exe` and silently broke.
3. No overall timeouts on RealityScan operations — 10+ hour runs are
   normal. Startup (120 s) and shutdown (300 s) are the only bounds.
4. Clear `progress.txt` / `errors.txt` / `results.log` only through
   `RealityScanCLI` (it does this pre-run); they are the source of truth
   while a run is live.
5. Data lives on large local/NAS volumes with user-specific paths — never
   hardcode them. Use `SettingsStore` prompts with the previous value as
   default.
6. `geoall.py` is the canonical georeferencing implementation; port
   improvements from it into `modules/georeference/` rather than letting
   the two diverge further.
7. Import components (`-importComponent`) ONLY from their original
   export location — a relocated `.rsalign` hangs the instance forever
   in a `#timeout` state.
8. Never pass delimited data as .bat arguments: cmd splits unquoted
   `;` `,` `=` and Python's subprocess only quotes on whitespace. Lists
   cross the boundary as files (`.complist`/`.imagelist`); settings as
   `key:value` (converted inside the workflow).
9. `testing/NA167_SESSION_NOTES.md` is the revised CLI documentation +
   bug-findings reference (B1–B11); consult it before writing any new
   RealityScan workflow. `testing/MERGE_TEST_PLAN.md` tracks the
   component-merge test matrix;
   `testing/ALIGN_MERGE_HARDENING_PLAN.md` tracks every
   design assumption not settled by documentation (cells graduate into
   FINDINGS.md with results).

## History notes

An earlier, richer iteration (delegation client, GUI, tests, docs) was
reverted by the `main_v2` merge — it survives only in git history around
commit `4bc8549`. Its race-condition lessons are baked into the current
execution layer; consult it before re-deriving old solutions.
