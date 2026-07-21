# HANDOFF — state of the July 2026 overhaul

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
