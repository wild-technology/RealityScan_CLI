# HANDOFF — state of the July 2026 overhaul

## 2026-08-04/05 ON2026 model workflow to final (DONE)

Took the live ON2026 (RH0042/RH0043 Voyis stereo, 38,948 images in
`M:\ON2026 COLMAP processing\rs\rs_images`) GUI session from a finished
Normal Detail mesh through to exported deliverables.

**Deliverables** — `M:\ON2026 COLMAP processing\rs\final\` (96.52 GB):
- `ON2026_final.obj` — 9.37 GB, **30,160,616 verts / 60,322,228 faces**
- 4 × `*_diffuse.jpg` + 4 × `*_normal.jpg`, each **8192 × 8192**
- `ON2026_final.rsproj` (17.24 MB + 48.50 GB data, 670 files)
- `ON2026_premodel_checkpoint.rsproj` (+38.74 GB, 331 files) — the
  rollback point, taken *before* any model step touched the scene.

**Run**: texture (4×8k) → 4× simplify/clean (70% per pass ⇒ ~24% of
original tris) → unwrap → reprojectTexture → export OBJ → save.
23:15 → 03:15 (4 h). Every step clean, `lastError:0`, final `rev:147`.

**Carried by the new `ModelToFinal.bat`** (see CLAUDE.md). It attaches to
a running instance instead of booting one — necessary here because the
session was GUI-launched and because every other workflow would have
called `startRealityScan.bat`, whose `-newScene -deleteAutosave` would
have destroyed 9 h of reconstruction.

### Open items on this dataset

1. **Color correction never succeeded.** Four `Correcting Image Colors
   aborted` entries (2420 s, 214 s), no completion line ever. The
   texture was therefore built on **uncorrected** imagery. For turbid
   ROV imagery this is a visible quality ceiling. To fix: `correctColors`
   from the checkpoint, then re-texture.
2. **The OBJ is exported at 100× scale, Unreal conventions.**
   `ModelExportParamsObj.xml` carries `MvsExportScaleX/Y/Z=100.0`,
   `MvsExportTransformationPreset=Unreal`, `MvsExportNormalFlipY=true`.
   Verified in the artifact: `.rsInfo` says `settingsScale="100 100 100"`
   / `normalFlip="0 1 0"`, and vertices read ≈ ±180/1100 where the local
   flight-log frame is ≈ ±2/18 m. **The model is in centimetres, not
   metres** — wrong for metric/GIS use, right for Unreal.
   **RESOLVED 2026-08-07**: re-exported to `final\metric\` using the new
   `ModelExportParamsObj_Metric.xml` (scale 1.0, `[[Custom]]` preset,
   normal-map conventions deliberately left untouched so scale is the
   only difference). `ON2026_final_metric.obj`, 9.17 GB, same
   30,160,616 verts / 60,322,228 faces, same four 8192×8192 pages;
   `.rsInfo` records `settingsScale="1 1 1"` and vertex 0 reads
   `-1.7990 11.0154 0.4367` against the Unreal build's
   `-179.8996 1101.5427 43.6697` — exactly 100×. Both exports are kept.
3. Scene CRS: the trajectory was imported as **local Euclidean**
   (`+proj=geocent`, `local:1 - Euclidean`), not UTM. The
   `epsg:32757` entry in the .rsproj is the project's default
   coordinate-system slot and is not what the flight log used.

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

## PENDING RECONCILIATION with LilyJean/COLMAP findings (filed 2026-07-23)

The LilyJean fact base (`C:\Users\jonat\Desktop\CoyoteThings\itsmagicIswear\FINDINGS.md`, 34 dated/
sourced entries) reached the OPPOSITE preprocessing verdict from this pipeline:
on 3,607 LilyJean stereo pairs, both adaptive enhancement and fixed backscatter
subtraction reduced COLMAP registration ~30% vs originals (F-20260721-02,
F-20260723-01) — while this repo's CLAHE 2.0/8×8 pre-alignment default is
validated on zone_9 where the baseline aligns to NOTHING (recorded there as
counter-evidence F-20260723-33). Both results are real; scope is unresolved.

When the colmap-studio research completes, run the reconciliation matrix (Q-05):
zone_9 {baseline, CLAHE} × COLMAP, and LilyJean {originals, CLAHE} × this
pipeline's RealityScan alignment, judged on REGISTRATION (not keypoints —
F-20260723-03). Outcome decides whether preprocess_images stays default-on,
becomes per-dataset, or moves to texture-only.

Also relevant from that fact base for this repo:
- RealityScan Image Layers (`.geometry`/`.texture`/`.mask`, F-20260723-23) are
  the official mechanism for "originals align, corrected images texture" — the
  reconciling architecture if CLAHE ends up texture-only.
- Staff caution against over-masking (F-20260723-31) and Ultra detector
  sensitivity manufacturing noise points (F-20260723-26) — relevant to
  `masking.py` and AlignmentParams choices on turbid imagery.
- No stereo-rig support in RealityScan (staff-confirmed through Aug 2025,
  F-20260723-27): Voyis-rig scale must come from GCPs/distance constraints/
  locked XMP — consistent with this repo's per-rig XMP-priors caution (the
  NA167 zone_13 A/B where priors cost 6.7 points of registration is recorded
  as F-20260723-34).

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
