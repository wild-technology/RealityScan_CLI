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

## Verification status — read before the first real run

Verified so far: `py_compile` on all Python, an adversarial code review
(findings fixed), and functional smoke tests of the settings store. The
batch scripts have **never executed on a real Windows machine with
RealityScan installed** — this environment is Linux and cannot run them.

First-run checklist on the Windows multi-GPU box:

1. **Smoke test small**: run `python main.py` on a tiny image set before
   any 10-hour dataset.
2. **Confirm the process trigger fires**: during the run,
   `RS_CLI/Errors/results_RS1.log` must grow by one line per completed
   operation. If it stays empty, error detection is dead — most likely
   the `appProcessExecCmd` quoting (see `startRealityScan.bat`) or
   RealityScan refusing `cmd /c` — fix before trusting any run. Test
   from a checkout path containing spaces specifically.
3. **`-align "%AlignmentParams%"`** (`AlignZonesSequentially.bat`):
   pre-existing usage that was kept; confirm RealityScan 2.2 actually
   accepts a params XML on `-align`, otherwise the custom alignment
   settings are silently ignored.
4. **Process result code 1**: `ErrorWriter.bat` whitelists it as benign
   (inherited from the Epic sample). Verify what 1 means in 2.2 — if it
   can mean user-abort/failure, remove it from the whitelist.
5. **Shutdown timing**: closing very large scenes after `-quit` must
   finish inside 15 min or the run is flagged failed; raise
   `"realityscan": {"shutdown_timeout": ...}` in `rs_settings.json` if
   needed.
6. **Multi-GPU parallel instances**: when trying one-instance-per-GPU,
   set unique `RS_INSTANCE` + `RS_GPU_DEVICES` per orchestrator (see
   README "Multi-GPU"). Marker files and locks are per-instance; the
   `Models/` folder and Metadata XMLs are shared.
7. **`sfmMaxFailedTasks` / autosave keys**: the old
   `RealityCaptureAutoSaveCliHandling=delete` setting was dropped because
   its 2.x replacement key could not be verified from public docs;
   autosave is disabled via `appAutoSaveMode=false` + `-deleteAutosave`
   on attach. If stale autosaves ever resurface, research the current
   key name.

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
