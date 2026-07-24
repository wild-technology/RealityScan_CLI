# HANDOFF — state of the July 2026 overhaul

## 2026-07-24 SESSION END STATE — read this first in a fresh session

Read order for a new session: CLAUDE.md -> FINDINGS.md (every verified
fact + how discovered) -> this section -> docs/merge-growth-strategy-
2026-07.md (the workflow spec) -> testing/ALIGN_MERGE_HARDENING_PLAN.md
(open unknowns).

**Where H2023 processing stands (workspace D:\na156_h2023):**
- Zone aligns DONE with manifests + RC_projects daily saves:
  zone_1 = 4,392 registered / 9 components (nondeterministic
  fragmentation - see FINDINGS; first run gave 2 components, same
  registration); zone_2 = 928/976 (95.1%) / 3 components.
- Within-zone growth: zone_2 DONE (clean run, zero real gains - the 48
  orphans are genuinely unregistrable; 3 components remain by design,
  northern strip is visually disjoint). zone_1 growth was IN FLIGHT at
  session end (grow_zone.py, output D:\na156_h2023\growth\zone_1,
  report grow_report.json when done; scene checkpoints under
  growth\zone_1\checkpoints - "initial" restores the pre-growth scene
  if anything went wrong).
- NEXT STEPS in order: (1) check zone_1 grow_report.json; (2) cross-zone
  merge: py -3.13 merge_zones.py --components_root
  D:/na156_h2023/aligned_components --images_root
  D:/na156_h2023/batched_images_by_zone --output D:/na156_h2023/merged_v2
  --name H2023_Merged --min_size 50 --target 0.83 --project_label
  NA156_H2023  (twin resolution via manifests is automatic; union
  flight log + -update georeference the merged component - VERIFY
  georeferencing in the GUI, U7 automation still open); (3) model:
  GenerateModel.bat on the merged .rsproj (owner recipe baked in;
  simplify presets are placeholders - see plan self-audit).
- The old non-georeferenced merge outputs live at D:\na156_h2023\merged
  (reference only). Smoke fixtures at D:\na156_h2023\smoke_test.

**Known open items:**
- GrowZone export mode cannot rebuild identity manifests (in-session
  harvest only exists in AlignZone.bat) - post-growth manifests are
  approximate; rebuild identity by re-running AlignZone.bat OR accept
  approximate until the merge (merge twin-resolution treats
  approximate manifests conservatively).
- grow_zone report's components dict lists stale export paths
  (cosmetic).
- Determinism test queued: third zone_1 align to confirm fragmentation
  nondeterminism (FINDINGS) - run when GPU is free.
- Hardening cells open: U4-U14, U17 (see plan STATUS UPDATE);
  U7 (CLI-observable georeferencing check) matters most for merge
  automation.
- selectImage regexp/glob discrepancy vs Help - forum-mine follow-up.
- Clean-sweep code review findings (three review agents, 2026-07-24):
  triaged into the sections below / applied where safe - check git log.
- Claude Skill + documentation guide (task queued): FINDINGS.md is the
  fact base, docs/ the rationale base.

**Review backlog (2026-07-24 clean-sweep; applied items in FINDINGS):**
MUST-FIX BEFORE NEXT MERGE/MODEL RUN:
- MergeZoneComponents.bat complist-validation `exit /b 1` inside a
  multi-statement block returns 0 (hoist to a subroutine/goto flow).
- grow_zone <-> merge handoff: merge_zones cannot consume
  grow_report.json's scattered final exports - build a .complist from
  the report (or merge the PRE-growth aligned_components when growth
  gained nothing, which is the H2023 zone_2 case).
- GrowZone.bat component-mode saves the scene with most images
  DISABLED (inpEnabled=false persists) - re-enable all before save, and
  CHECK the zone_1 scene after its growth run for this state.
SHOULD-FIX:
- Manifest component names vs in-scene names never match (scene saved
  pre-rename): cleanup_stale selectComponent silently no-ops; key
  correlation by image set instead. AlignImageList/SequentialAlignGrow:
  no AlignmentParams application, no deselect before exports.
  startRealityScan timeout exit-code shape; PowerShell harvest line in
  AlignZone.bat unchecked; :try_delete_model wait shape;
  identity-loop 20-cap absorbs remainder into the last manifest.
NITS: stale AlignImagesFromFolder rationale pointers; pre-B10 comments
in camera_registry/component_manifest; ProbeSubsetAlign headers need a
SUPERSEDED note; MergeZoneComponents delayedexpansion flag; kv colon
replace-all; dead component_manifest helpers (scan_pose_sidecars +
members_from_sidecars now only used by realityscan_interface - verify
before deleting); merge_zones ascii complist crash path.

## 2026-07-23 NA156 H2023 session: settings evaluation + workflow consolidation

Full rationale: `docs/settings-evaluation-2026-07.md`. Summary:

- **Camera registry** (`modules/camera_registry.py`): four physical
  cameras (Zeuss rect 23mm / Port fisheye 14mm / Cinema rect 17mm /
  Starboard fisheye 14mm; owner-confirmed), per-camera calibration/lens
  groups, calibration-only XMP content, pose-sidecar sanitize+census.
  The WCA rendered JPGs are EXIF-identical — XMP groups are the ONLY way
  RealityScan can separate the cameras. Old batcher values (camlower as
  "12mm fisheye") were wrong and plausibly explain the earlier
  "priors hurt" A/B.
- **Workflow consolidation**: `AlignZone.bat` (per-zone canonical:
  always applies AlignmentParams.xml, appIncSubdirs=true, exports ALL
  components >= min size via -exportLatestComponents, XMP census, no
  models) + `merge_zones.py`/`MergeZoneComponents.bat` (iterative merge,
  escalating georef-merge → align+rematch → +High overlap) +
  `GenerateModel.bat` (models once, on the merged component).
  `AlignZonesSequentially.bat` retired to archive/legacy_scripts;
  `AlignImagesFromFolder.bat` deprecated (kept for run_zone9_tests.py).
- **Settings changes**: sfmDistortionModel Division→Brown3 (global
  fallback; real models per-camera via XMP), sfmImagesOverlap
  Low→Medium. sfmEnableCameraPrior=true IS the GUI "use camera priors
  for georeferencing"; sfmMergeGeoreferencedComponents is the
  component-level no-overlap merge flag — they compose.
- **New CLI facts**: B10 (ordinal XMP exports from imported-component
  scenes), B11 (-setFeatureSource/-selectImage regexp ARE CLI;
  -exportLatestComponents; -selectComponentWithLeastReprojectionError).
  This 2.2 build does NOT recurse -addFolder without appIncSubdirs=true
  ("Added 0 layer images" → err:18002 cascade).
- **Smoke-verified end to end** (NA156 H2023 subsets): mini_a 118/120
  registered, mini_b 62/120, georef -mergeComponents fused both into one
  180-camera component in 66 s (supports matrix cell D1). Orchestrator
  now stops on module failure; alignment module aggregates per-zone
  success; overwrite prompts removed from the unattended path.
- **NA156 H2023 state**: 4,598 Port+Cinema images at
  D:\na156_h2023\raw_images (Starboard excluded by owner instruction),
  georeferenced 100%, CLAHE'd, batched into zone_1 (4,540) + zone_2
  (976) — NOTE batched BEFORE the calibration-XMP work: re-run Batch
  Directory with --b_xmp_priors true (or write sidecars into the zone
  folders) before the production zone aligns.

## 2026-07-22 fix pass + NA167 end-to-end verification

A full-code review found and fixed (all verified by a 47-check synthetic
suite plus a live NA167_H2075 run — see `git log` for the commit):

- **Chaining was broken**: alignment read `batched_images` while the
  batcher wrote `batched_images_by_zone`, and every stage expected
  `flight_log.txt` while producers write `flight_log_<zone>_UTM.txt`.
  All discovery now goes through `modules/flight_logs.find_flight_log`.
- **Extractor timestamps were one interval early** (60 s at 1 fpm): the
  frame read and the frame timestamped were different frames. Any
  dataset extracted with the old `__extract_video_cv2` carries that
  offset — re-extract before trusting its georeferencing.
- **`FlightLogParams.xml` is now auto-generated per run** from the zone
  tag in the flight-log filename (`flight_log_53N_UTM.txt` →
  EPSG:32653). Never hand-edit the template's zone again.
- **XMP calibration priors never loaded**: they were written as
  `image.jpg.xmp`; RealityScan only reads `image.xmp`. Naming fixed,
  but generation is now **opt-in** (`batch_xmp_priors`, default off) —
  an NA167 zone_13 A/B measured the current prior content *reducing*
  registration (96.3% → 89.6% on Zeuss). Validate per-rig first.
- **Per-camera zone subfolders were aligned as separate scenes**,
  defeating mixed-camera co-registration. `-addFolder` recurses
  (verified live), so a zone tree is now one alignment scene.
- Plus: georeference image check is header-only (full `.verify()` was
  ~720 GB of reads on NA167), binary-search nav matching, batcher file
  indexing (O(N·M) → one walk), geoall prefers `*final_datatable.csv`,
  PNG support in both georeferencers, warn-once unknown-camera handling,
  PID-exact lock liveness, contiguous match-delta buckets, CRLF-safe
  prompts, tabs→4-space everywhere.

**NA167_H2075 verification** (D:\na167_h2075, WCA U*/C* stills + Zeuss):
29,620 images georeferenced in ~5 min (18,944 matched ≤2 s; the 10.4k
out-of-dive-window WCA files correctly rejected — the legacy
`flight_log.txt` had clamped those to garbage). 18 zones @ target 1000
built in 6.6 min. zone_13 (34 wca + 904 zeuss, one scene) aligned
93.4% registered in 11.5 min on GPU 0, flight log + auto-generated 53N
CRS imported clean, verified shutdown. Basename flight logs match
images in camera subfolders.

This repo was created on 2026-07-21 from `wild-technology/RC_Main`
(branch `claude/realityscan-repo-cleanup-2gjmu5`, full history preserved).
That branch also still exists on RC_Main; no pull request was opened
there. Treat this repo as the single source of truth going forward.

## What the overhaul did

Four commits on top of the old `main_v2`-era code:

1. **Archive COLMAP** — `colmap_processor.py` and the three
   `vocabtrainer_*` variants moved to `archive/colmap/` (see its README).
   No splatting scripts existed.
2. **Unify RealityScan CLI execution + rename** — everything renamed
   RealityCapture → RealityScan (module dir, `RS_CLI`, `RSModule`,
   `RealityScanAlignment`, instance `RS1`, `.rsproj` saves). New unified
   execution layer `modules/realityscan_interface/realityscan_cli.py`;
   batch workflows share one `:run` delegate/wait/error-check subroutine;
   legacy `RealityCapture*` `-set` keys replaced with the `app*` keys
   RealityScan 2.x actually uses. `rs_settings.json` prompt-default
   persistence added to `main.py` and all standalone scripts
   (`module_base/settings_store.py`).
3. **README + CLAUDE.md** for the 2.2 pipeline.
4. **Adversarial-review fixes** — an independent review pass found and
   fixed, among others: component detection that reported every
   successful run as a failure; unquoted `appProcessExecCmd` paths that
   silently disabled all error detection when the checkout path contains
   spaces; markers read before instance shutdown (missed late errors);
   `%ERRORLEVEL%` parse-time expansion breaking every interactive CHOICE
   prompt; per-instance namespacing of marker files for multi-GPU.

Design rules live in `CLAUDE.md` (hard rules) and `README.md`
(architecture + lessons learned). Read both before touching execution
code.

## Verification status

Full write-up of what changed and why:
[`docs/code-review-2026-07.md`](docs/code-review-2026-07.md).

**2026-07-21: first real-machine run completed on the Windows dual-5090
box** via `testing/run_zone9_tests.py` (phases 0–1, from both a normal
checkout path and one containing spaces). Checklist outcomes:

1. **Smoke test small** — DONE. 32-image smoke passes end to end
   (boot → addFolder → importFlightLog → align → select/rename →
   exportXMPForSelectedComponent → exportSelectedComponentDir → save →
   verified shutdown), 17/32 registered on a contiguous subset.
2. **Process trigger fires** — VERIFIED, including from a checkout path
   with spaces. Several real bugs were found and fixed on the way:
   - `RealityScanCLI` now invokes the .bat by absolute path *without*
     `cmd /c` (bare names break under `NoDefaultCurrentDirectoryInExePath`
     environments like Git Bash; a self-built `cmd /c "path with
     spaces.bat"` line gets its quotes stripped by cmd).
   - The `:run` line-count used bare `find`, which resolves to GNU find
     when launched from Git Bash (scans the whole disk); now fully
     qualified as `%SystemRoot%\System32\find.exe`.
   - **The results-log-growth completion check was removed entirely**:
     RealityScan 2.2 emits periodic internal heartbeat processes through
     the same `appProcessExecCmd` trigger, so "the log grew" does not
     mean "our command finished" — it raced ahead of a running `-align`.
     `:run` now does delegate → grace → double `-waitCompleted`.
   - `-mergeComponents` is a no-op with a single component and its async
     re-reconstruction can clear the selection; replaced with
     `-selectMaximalComponent`.
   - `-exportXMP` only covers "the last alignment" and silently skips
     components below `setMinComponentSize` (default 5); replaced with
     `-setMinComponentSize 1` + `-exportXMPForSelectedComponent`.
3. **`-align "%AlignmentParams%"`** — CONFIRMED NOT SUPPORTED. `-align`
   takes no parameters in 2.x (local Help `allcommands.htm` + online
   docs). `AlignZonesSequentially.bat` now parses the sfm*/lis* keys out
   of `AlignmentParams.xml` and applies them via delegated `-set`
   commands before a plain `-align`.
4. **Process result code 1** — benign in practice: routine successful
   operations (e.g. `-addFolder`) report result 1 through the trigger
   while real failures report distinct codes (0x820000FF warning-class,
   0x80070057 E_INVALIDARG). Whitelist of 0/1 kept.
5. **Shutdown timing** — verified on small scenes only; the 15-min bound
   on very large scenes is still untested.
6. **Multi-GPU parallel instances** — still untested. Single-instance GPU
   pinning via `rs_settings.json` `"gpu_devices"` exercised during the
   phase-2 test runs.
7. **Autosave keys** — no stale autosaves observed in any test run.

Other findings from the first runs:

- `FlightLogParams.xml` declared UTM zone 4N (EPSG:32604) from an earlier
  project; the NA173_H2103a flight logs are zone **57S** (EPSG:32757,
  southern hemisphere). Fixed. Check this per-cruise before importing.
- `-importFlightLog` reports a failed process (err:18002, 0x820000FF)
  when the log references images that are not in the scene — even though
  the trajectory itself imports fine. When aligning subsets, filter the
  flight log to the images actually present (the zone_9 runner does).
- `-exportRegistration` without a params XML blocks forever headless —
  avoid it until a params file saved from the GUI dialog exists.

## Known loose ends

- `geoall.py` (canonical) and `modules/georeference/georeference_images.py`
  still duplicate the georeferencing workflow — port improvements into
  the module when it next changes (CLAUDE.md hard rule 6).
- The overwrite prompts in `realityscan_interface.py` use `input()` and
  can stall an unattended pipeline mid-run; consider a `--force`
  parameter if runs go fully unattended.
- `rs_settings.json` is per-machine and gitignored; nothing migrates old
  hardcoded paths — first run on a new machine prompts from the baked-in
  fallbacks.

## Session provenance

Overhaul performed by Claude Code (session linked in the commit
trailers), including web-verified RealityScan 2.2 CLI semantics
(`-delegateTo` queueing, `-waitCompleted` pickup race, `-getStatus`
errorlevel contract, `appProcessAction` triggers, exit codes 0/1/3).
