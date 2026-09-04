# CLAUDE.md — project context for RealityScan_CLI

ROV underwater photogrammetry pipeline driving **RealityScan 2.2** (Epic
Games; the product formerly named RealityCapture) via its CLI. Runs on
Windows with a multi-GPU CUDA setup.

Continuation of `wild-technology/RC_Main` (created from its
`claude/realityscan-repo-cleanup-2gjmu5` branch, July 2026 overhaul, full
history preserved — `git log` reaches all the way back). RC_Main is frozen;
new work happens here.

## Starting a session

The `SessionStart` hook (`.claude/hooks/session_status.py`) prints the current
`HANDOFF.md` section and `git status --short`. Then, in this order — and say in
one line what you are about to do:

1. **`HANDOFF.md`** — current state, what is running, ranked loose ends, exact
   next commands. Read it **before the first mutating action**.
2. **This file** — hard rules, invariants, routing. `docs/ARCHITECTURE.md` is
   the module map (grep it when you touch a subsystem, not to orient);
   `docs/AGENT_OPERATIONS.md` holds the working practices for any session, the
   driving contract and the RealityScan facts to carry in context.
3. **`docs/rs-reference/README.md`** — the manual's routing index: any
   RealityScan question reaches one of 14 documents in one hop. Never answer a
   CLI question from general knowledge; route it. **Do not read `FINDINGS.md`
   cover to cover** (5,300+ lines) — grep it; `docs/` and `testing/` are cited
   sources too.

Baseline before touching anything: `python -m pytest testing -q` with the
interpreter that has every requirement (`CLAUDE.local.md` names it per box) —
737 passed, 1 skipped (offline: geoid grid), ~22 s. An interpreter without
`textual` skips `testing/test_wildscan.py` whole at import (21 tests) and
reports 716 passed, 2 skipped — that is the same green tree, not a broken one
(observed 2026-09-04 with the Microsoft Store `python`). Any other result on a
clean checkout: stop and report — anything built on a broken tree is suspect.

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
- Python is `py -3.13` where the launcher exists; a box without it (the
  NA165/NA168 machine has Microsoft Store 3.13 and no launcher) uses plain
  `python`. The committed `.claude/settings.json` hooks call `python` for
  that reason. `ruff` is **not installed** here — the style check
  in the account-level agreement cannot run; say so rather than claiming it
  passed.
- ASCII-only console output; the cp1252 console crashes on non-ASCII. Set
  `PYTHONIOENCODING=utf-8` when parsing UTF-8 sources.
- Data lives on large local/NAS volumes with user-specific paths. Never
  hardcode them — prompt through `SettingsStore`.

## RealityScan reference

**`docs/rs-reference/`** is the RealityScan documentation of record. Consult it
before writing any new RealityScan workflow; start at its `README.md` — the
"facts that silently destroy a run" table is the highest-value page in the
repo. The `rs-lookup` skill routes any question there in one hop. What the
manual holds, and the few facts worth carrying in context without a lookup,
are in `docs/AGENT_OPERATIONS.md`, "RealityScan facts to carry in context".

## Findings log

`FINDINGS.md` at the repo root is the running log of every discovered fact —
CLI behaviors, merge semantics, rig data, process conventions — each with HOW
it was discovered. Append whenever a fact is established; keep entries short
and dated. It is the raw log; the distilled counterpart is
`docs/rs-reference/`, and deep rationale lives in `docs/`.

## Naming

Everything in this repo says **RealityScan** (`RS`), never RealityCapture.
Exceptions that must NOT be renamed: RealityScan API identifiers that happen to
be current product strings (e.g. `reader="RealityScan.Import.CSVFlightLog"` in
`flightlogs.xml`, feature-detector ids in `Metadata/AlignmentParams.xml`);
legacy file extensions `.rcalign`/`.rcproj`, still accepted when reading old
outputs (new saves use `.rsproj`).

## Architecture

Module-by-module map: **`docs/ARCHITECTURE.md`** — grep it when you touch a
subsystem (`main.py`, the post-align drivers and `modules/` domain logic sit on
`module_base/`: `RSModule`, `Parameter`, `SettingsStore`). Two invariants to
know before the first action: **`modules/realityscan_interface/`** is the ONLY
place RealityScan is executed — `realityscan_cli.py` (`RealityScanCLI`) owns
executable discovery, per-instance locks, marker-file hygiene, progress tailing
and verified shutdown, and every `RS_CLI/Scripts/*.bat` workflow runs through
the shared `:run` subroutine; **`wildscan/session.py`** is a PURE PLANNER
(`build_commands`) whose three consumers are the TUI, `wildscan/runner.py` and
`wildscan/plan.py` — add a fourth consumer rather than a second planner.

### Agent-facing entry points (fixed schemas — prefer them over greps)

- `python -m modules.verify --workspace <ws> --json` — the census/verify
  **oracle** as JSON from disk; exit 0 ok / 1 incomplete / 2 blocked / 3 absent.
- `python -m modules.run_charter --init|--validate <charter>` — the run contract
  as DATA, plus the `--check`/`--path` and `--instance` guards the hooks call.
- `python -m wildscan.plan --charter <charter> --validate` — the run plan,
  headless, proven against `main.py`'s own parser before anyone runs it.
- `.claude/skills/` — `rs-lookup` (routes RealityScan questions into
  `docs/rs-reference/`), `drive-run`, `merge-zones`, `publish-cesium`,
  `finish-model`, `charter` (intake, sign-off), `status`, `handoff`.
- `.claude/agents/` — read-only subagents `run-monitor` (polls a run; reports,
  never acts) and `rs-reference` (`docs/rs-reference/` lookup with provenance).
  `.claude/rules/` — path-scoped rules (`RS_CLI/**`, the interface module and
  post-align drivers, `testing/**`), loaded only when those files are touched.
- `.claude/hooks/` — enforce hard rule 1, the charter's touch rules and CRLF on
  `.bat`/`.vbs`; print status at `SessionStart`. Liveness-tested by
  `testing/test_agent_hooks.py`: a guard nobody tests is a rule nobody enforces.

## When an AI agent is DRIVING (owner said "run this against that dataset")

MANDATORY. `docs/AGENT_OPERATIONS.md` is the contract (every mandate in full,
each traced to an incident) and wins on conflict; this section is one-line
pointers, and the `/drive-run` skill is the executable path.

1. **No writes before the charter** — ask, never infer; charter as DATA (`modules.run_charter`, `RS_RUN_CHARTER`). Mandate 1.
2. **Source data is read-only, forever** — align only from trees the agent created, or with consent. Mandate 2; hard rule 0.
3. **Protected paths are never touched; deliverables never overwritten** — collisions are stop-and-ask. Mandate 3.
4. **Agent working files live in ONE place** (`<results_root>/_agent/`) — enforced by `guard_charter_writes.py`. Mandate 4.
5. **Own instance, own processes** — never kill/quit/delegate-to anything the agent did not start. Mandate 5.
6. **Long runs are scheduler-owned** (schtasks + CRLF launcher), budget declared and monitors live first. Mandate 6.
7. **Frames and fingerprints** — honor FRAME_WARNING and align_inputs.json; never mix frames. Mandate 7.
8. **Every science argument explicit; owner gates are stops** — plan with `wildscan.plan --validate`. Mandate 8.
9. **Destructive ops need per-instance user approval.** Mandate 9.

## Hard rules

0. **NO XMP SIDECARS. The input image tree is READ-ONLY to this
   pipeline.** Owner directive 2026-08-16: "Sidecars are forbidden in the
   workflow — they keep messing things up." The reason is structural, not
   stylistic: an `.xmp` beside an image is READ BY RealityScan on import,
   so anything left there silently becomes a PRIOR for the next run (7,694
   inherited sidecars once confounded a distortion A/B; 6,024 were
   re-created on H2080 in a tree that had just been certified clean).
   Priors travel IN via the flight log — position, orientation, their
   accuracies, and `FocalLength` (a documented CSV flight-log variable,
   along with PrincipalU/V, Skew, AspectRatio and the distortion
   coefficients) — plus `-setPriorCalibrationGroup` / `-setPriorLensGroup`
   in-session. Identity travels OUT via `-exportRegistration` into the
   OUTPUT tree. Anything a stage produces goes to the output tree; if a
   new writer needs to put a file next to an image, the design is wrong.
   NOTE (merge 2026-09-03): main's `AlignZone` identity default still
   harvests `-exportXMP` sidecars in-session (and `realityscan_interface.py`
   repairs calibration XMPs on every exit path); the non-destructive
   `-exportRegistration` CSV path is kept behind `RS_LEGACY_XMP_IDENTITY=0`,
   the VOYIS sidecar writer stays env-gated off (`RS_VOYIS_CALIB_SIDECARS`),
   and `prior_groups.py` groups run on every align — which mechanism
   RealityScan honours is open decision D1, FINDINGS `[RECON] 2026-09-03 -
   prior-groups claim: main and remove-xmp-sidecars disagree`.
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
