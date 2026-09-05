# CLAUDE.md — RealityScan_CLI

ROV underwater photogrammetry pipeline driving **RealityScan 2.2** (Epic
Games, formerly RealityCapture) through its CLI. Windows, multi-GPU CUDA.
Continuation of `wild-technology/RC_Main` (frozen; history preserved).

## Session start

The `SessionStart` hook prints `HANDOFF.md`'s current section, `git status`
and, when `RS_RUN_CHARTER` is set, the charter verdict and `RUN_STATE.json`.
Do not re-read what it printed. Then, saying in one line what you will do:

1. Act on `HANDOFF.md`'s current section (done / running / ranked loose
   ends / exact next commands) before the first mutating action.
2. Route, never browse: `docs/ARCHITECTURE.md` (module map - grep it),
   `docs/AGENT_OPERATIONS.md` (the driving contract; wins on conflict),
   `docs/DECISIONS.md` (open owner decisions D1..), `docs/rs-reference/README.md`
   (any RealityScan question - never answer one from general knowledge).
3. Baseline: `python -m pytest testing -q`. Windows: fully green expected.
   macOS/Linux: exactly the 22 platform-bound failures named in
   `testing/conftest.py`. Anything else: stop and report.

## Session end

`/handoff`: findings flushed to `FINDINGS.md`, new `HANDOFF.md` top section,
suite count updated here, every changed file committed or named. Never push
without the owner's word in this session.

## Operating model - one command surface

`python rs.py <charter|preflight|plan|run|launch|status|verify>` is the whole
lane; skills call only these.

- `charter` - the run contract as DATA (`modules/run_charter.py`). Six intake
  answers from the OWNER, then sign-off. Arms the write guard via
  `RS_RUN_CHARTER`.
- `preflight` - what is still MISSING (`modules/preflight.py`). Every
  `missing` line is a question to ASK the owner - never answer it from a
  directory listing or a previous campaign. `run`/`launch` refuse until READY.
- `plan` - the exact commands, proven against `main.py`'s own parser
  (`modules/run_plan.py`, the ONLY planner).
- `run` - headless execution with `RUN_STATE.json` under `<results>/_agent/`.
  From an agent shell it refuses RealityScan stages: use `launch`.
- `launch` - CRLF launcher pair + the `schtasks` commands to run (scheduler
  owns long runs; the agent runs the printed command and the ask-gate fires).
- `status` / `verify` - the verdict is a census from disk, never an exit code.

Skills: `/charter`, `/drive-run`, `/status`, `/handoff`, `/merge-zones`,
`/finish-model`, `/publish-cesium`, `rs-lookup`. Read-only agents:
`run-monitor`, `rs-reference`. Hooks enforce hard rule 1, the charter's touch
rules and CRLF; `.claude/rules/` load only when their paths are touched.

## Environment

- Windows 11 native, no WSL: cmd, `.bat`, PowerShell, VBS. `.bat`/`.vbs`/`.cmd`
  are CRLF (`.gitattributes` pins it; `normalize_crlf.py` repairs tool edits).
- Interpreter is `python` (Microsoft Store 3.13 on the NA165 box); `py -3.13`
  where the launcher exists. `CLAUDE.local.md` (gitignored) names this
  machine's interpreter, drives and instance names. `ruff` is not installed.
- ASCII-only console output (cp1252 crashes otherwise); `PYTHONIOENCODING=utf-8`
  when parsing UTF-8.
- Data lives on user-specific volumes: never hardcode a path. The charter
  declares them; `SettingsStore` remembers answers for interactive runs only.

## Hard rules

Each traces to an incident (`docs/AGENT_OPERATIONS.md`, rs-reference 12).

0. **No XMP sidecars written into image trees; input trees are read-only.**
   The `RS_LEGACY_XMP_IDENTITY` switch is open decision D1: flip no default,
   delete no branch, until `FINDINGS.md` `[RECON]` settles it.
1. **One launcher**: `RealityScanCLI` + the `:run` pattern. Never a second
   subprocess path to RealityScan or a `.bat`.
2. Never infer completion from process names or results-log growth.
3. No overall timeouts on RealityScan operations (10+ h is normal); the
   only bounds are the constants in `realityscan_cli.py`.
4. `progress_*`/`errors_*`/`results_*` markers are cleared only by
   `RealityScanCLI`.
5. No hardcoded data paths, anywhere.
6. `geoall.py` is the canonical georeferencing; port into
   `modules/georeference/`, never let the two diverge.
7. `-importComponent` only from the original export location.
8. Lists cross the `.bat` boundary as files, settings as `key:value`;
   arguments carrying cmd metacharacters are refused, never escaped.
9. `docs/rs-reference/` is the RealityScan documentation of record;
   `testing/*.md` matrices hold unsettled assumptions;
   `testing/NA167_SESSION_NOTES.md` is frozen provenance.
10. **The workflows are the product.** The order of operations in
    `RS_CLI/Scripts/*.bat`, the drivers and the modules is hard-earned. Change
    it only for a verified bug or on the owner's explicit instruction - never
    to tidy, simplify or "improve". Report a suspected defect; do not fix it
    silently.

## Driving mandates (one line each; full text `docs/AGENT_OPERATIONS.md`)

1 no writes before a signed charter; 2 source data read-only forever;
3 protected paths untouched, deliverables never overwritten; 4 agent files only
under `<results>/_agent/`; 5 own instance, own processes; 6 long runs
scheduler-owned with a declared budget; 7 frames and fingerprints honoured;
8 every science argument explicit, owner gates (`confirmed: false`) are stops;
9 destructive operations need per-instance approval.

## Invariants

- `modules/realityscan_interface/` is the ONLY place RealityScan is executed.
- `modules/run_plan.py` is the ONLY planner - add a consumer, never a second.
- `modules/preflight.py` decides what is missing; it asks, the code refuses.
- Unit tests never boot RealityScan and never write the repo root
  (`testing/conftest.py` enforces both).
- Everything the run produces lives under the results root; agent working
  files under `<results>/_agent/`; nothing in the repo but code/docs/tests.

## Working discipline (token cost is real)

- Grep, never read whole: `FINDINGS.md` (5,500 lines; `grep -n '^## '` lists
  sections), `docs/rs-reference/*` (28,000 lines; route via its README),
  `docs/history/`.
- Prefer `rs.py` JSON (`--json`) to reading logs; quote its lines verbatim.
- Ask the owner's six intake questions as ONE block, restate any answer
  already given, and stop while `preflight` lists anything.
- Report incompleteness in chat; leave no TODOs, stubs or commented-out code.
- Naming: **RealityScan**/`RS` everywhere; `RealityCapture` only in literal API
  identifiers and the legacy `.rcalign`/`.rcproj` extensions.

## Findings

`FINDINGS.md` is the raw, dated fact log. Append at the moment of discovery
with HOW it was found; mark refuted entries SUPERSEDED, never delete them.
