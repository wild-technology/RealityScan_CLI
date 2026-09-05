# Agent-native roadmap — RealityScan_CLI run by a Claude-guided workflow

Written 2026-09-03 against a fresh clone of `origin/main` (`c6123b4`).
Baseline on that tree: `597 passed, 1 skipped` in 37 s (CLAUDE.md still says
498 — stale). Nothing in the repo was changed to produce this document except
adding it.

The goal, in the owner's words: stop running the product by hand; have it
always executed by a Claude-guided workflow, with the owner supervising and
deciding at gates. The manual UI can go now and come back later.

## Status

- **2026-09-03 — Phase 0 done** (owner: main is the base; reconcile, examine
  agent-native against the findings, execute, delete stale branches).
  Merge `b640c81` (remove-xmp-sidecars into main, both identity mechanisms
  kept, main's default), adoption `d38d5f3` (agent-native lane, hooks
  rewired to `python`, launch guard widened), tag `manual-era-final` =
  `b640c81`. Suite 725 passed, 1 skipped. D2 decided (main). D1 still open
  (probe pending). D3: `85c556a` not adopted, tagged
  `agent-native-execution-final`. D6 pending. Branches
  `remove-xmp-sidecars` and `agent-native-execution` deleted on origin.
  The §1 facts below describe the tree as it was BEFORE Phase 0.
- Next: Phase 1.

---

## 0. The answer in one screen

**It is not "a skill OR code OR CLAUDE.md". It is all of them, layered, with
each rule pushed to the cheapest layer that can enforce it.** That principle
is already stated in this repo — commit `37d6d41` on the
`agent-native-execution` branch: *"every rule that lived only in prose is a
rule that could be forgotten, so each was pushed down to the cheapest layer
that can enforce it."* The branch built the first draft; this roadmap
finishes the job.

| Layer | Put here | Why it is the cheapest place |
|---|---|---|
| **Code** — Python modules with a `--json` CLI | Anything that must be *true*: the run charter as data, the plan, the census/verify oracle, run state, stage reports. | Deterministic, unit-tested, costs zero context tokens, works whether a human or Claude is driving. |
| **Hooks + permissions** — `.claude/settings.json` | Rules Claude could break by accident: no direct RealityScan launch, no writes outside the charter, CRLF on `.bat`, allow-list for routine commands, ask before `schtasks`/`taskkill`/`git push`. | Mechanical. A hook fires whether or not the agent remembered the rule. |
| **Skills** — `.claude/skills/*/SKILL.md` | Procedures: how to charter a run, drive it, merge, model, publish, hand off. The operator runbook. This is what replaces the TUI wizard. | Loaded only when invoked, so long procedures cost nothing on ordinary turns. |
| **Subagents** — `.claude/agents/*.md` | Bounded, tool-restricted workers: a read-only run monitor; a lookup agent over the 28,000-line RealityScan reference. | Keeps bulk out of the main context and removes write authority from tasks that never need it. |
| **CLAUDE.md** (≤ 150 lines) | Identity, session start/end protocol, the hard invariants, and *routing* to everything else. | Paid on every turn of every session and every subagent. Today's 392 lines are the single largest recurring cost. |
| **`.claude/rules/*.md`** (path-scoped) | Rules about one tree only: `RS_CLI/Scripts/**` (CRLF, `:run`, one command per delegation), `realityscan_interface/*.py`, `testing/**`. | Loaded only when Claude touches a matching file. |
| **HANDOFF.md / FINDINGS.md** | Project memory — current state, established facts. Already exists and works. | Keep. Make HANDOFF cheap to read (current section only); FINDINGS stays a grep target. |

**Long runs** (1–14 h) stay **scheduler-owned**: `schtasks` + a CRLF launcher,
never a harness shell. That is already mandate 6 in `docs/AGENT_OPERATIONS.md`
(a job object killed a 14.4 h run once), and Claude Code confirms it — Bash
children die with the session. Claude *launches* through code, then *polls*
through the oracle (`/loop`, or the run-monitor agent), and the next session
picks up from `HANDOFF.md` + a `RUN_STATE.json`.

**The biggest efficiency win is to stop paying for prose.** Three changes do
most of it: CLAUDE.md to ≤ 150 lines with the architecture map and driving
protocol moved out; "did the stage actually work" answered by
`py -3.13 -m modules.verify --workspace <ws> --json` instead of reading logs;
procedures loaded on demand as skills instead of living in the always-loaded
file.

**Before any of that: the repo has three unmerged lines and one scientific
contradiction between two of them.** Reconciling them is Phase 0. Moving
files first would turn every later merge into a fight.

---

## 1. What the repo looks like today

### 1.1 Three unmerged lines on GitHub

| Branch | Head | Since fork | What it carries |
|---|---|---|---|
| `main` | `c6123b4` 2026-09-03 | 57 commits since `c9eb222` (08-13) | NA165/H2060 delivered end to end (20/20 models, 91 GB exports); `docs/rs-reference/` manual (14 files); Cesium depth solved (`modules/cesium_placement.py`); 597 tests. |
| `remove-xmp-sidecars` | `71d6030` 2026-09-03 13:05 | 16 commits since `c9eb222` | The line the old checkout under `tools\` is on. NO-XMP-SIDECARS hard rule (owner directive 2026-08-16); `modules/prior_groups.py`; non-destructive identity CSV; merge resume; NA168 H2080 + NA165 H2063 campaigns. 483 tests. |
| `agent-native-execution` | `85c556a` 2026-09-01 | 2 commits since `2900c1f` (08-31); **19 behind main** | `.claude/` hooks, settings, 5 skills; `modules/run_charter.py`; `modules/verify.py`; `wildscan/plan.py`; `RS_NO_SETTINGS_INHERITANCE`; `docs/ARCHITECTURE.md`; CLAUDE.md 21.0 → 15.9 KB. 641 tests. |
| `claude/cesium-ion-georeferenced-ue5-vvpoau` | 2026-08-31 | 4 commits | `cesium2unreal` — separate feature, leave alone. |

`main` and `remove-xmp-sidecars` both touched `realityscan_interface.py`
(323 lines each side), `AlignZone.bat`, `run_models.py`, `scale_oracle.py`,
`MergeZoneComponents.bat`, `batch_directory.py`, `ExportDeliverables.bat`,
`publish_cesium.py`, `requirements.txt`, `wildscan/session.py`, and all
three narrative files. Expect real conflicts.

### 1.2 The contradiction that makes the merge an owner decision

- `main` — `FINDINGS.md` `[ON2026] 2026-08-08`: **`-setPriorCalibrationGroup`
  / `-setPriorLensGroup` are silently NON-FUNCTIONAL from the delegated CLI**
  (6-image fixture; after `-align` every camera shows `CalibrationGroup="-1"`
  and six distinct solved focals). `docs/PRODUCT_READINESS.md` repeats it as
  "proven silently non-functional".
- `remove-xmp-sidecars` — `FINDINGS.md` `[NA168] 2026-08-14` "XMP sidecars
  are NOT the only way to group cameras"; `modules/prior_groups.py` is built
  on exactly those two commands, and the H2080 and H2063 campaigns were
  aligned that way.

Both cannot stand as written. Decision **D1** below.

### 1.3 The agent-native branch already has the right shape

It is the correct design and should be adopted, but as *code cherry-picks*,
not a branch merge: its `FINDINGS.md`, `HANDOFF.md` and `CLAUDE.md` edits
were made against a tree that has since moved (main's FINDINGS gained ~230
lines, HANDOFF ~220). Take the modules, hooks, skills and tests; re-derive
the three narrative files on current main.

Its second commit (`85c556a`, Zeuss mount 25/45 and orientation hardness
2.0, `cameras.json` updated) is a **science change**, not tooling. It rides
along only if the owner wants it — decision **D3**.

### 1.4 Every human touchpoint in a manual run today

Blocking prompts (stop a run dead without a TTY):

| Site | Prompt |
|---|---|
| `main.py:57-70` | `inquirer` module-selection checkbox; `sys.exit(1)` with no TTY |
| `main.py:196` | one `input()` per unset parameter |
| `main.py:300` | "Press enter to continue..." between every stage |
| `modules/image_batcher/batch_directory.py:1158` | "Accept these batches? (a)ccept, (r)eject" |
| `batch_directory.py:1044`, `:1064` | `_prompt_int` / `_prompt_float` after a reject |
| `batch_directory.py:1283` | "Batched images folder already exists… Overwrite?" |
| `modules/extract_images/extract_images.py:355` | "Extracted images folder already exists. Overwrite?" |
| `geoall.py:719` | "Delete all corrupt images? (yes/no)" — destructive |
| `timestamp_rename.py:105` | "Proceed with renaming?" — **no EOF guard** |
| `decimator.py:178`, `:91` | "Proceed with copy?" in `while True` — **no EOF guard, no argparse at all** |

TTY-gated prompts that silently take the stored answer when unattended
(`SettingsStore.ask`, `module_base/settings_store.py:241`): `geoall.py`
(7), `grow_zone.py` (7), `merge_zones.py` (19 flags), `run_models.py` (2),
`modules/export_deliverables.py` (2), `organize_by_date.py` (1). This is the
mechanism behind two recorded incidents (stored merge options 2026-07-29;
wizard prefill crossing campaigns 2026-08-08) and PRODUCT_READINESS must-fix
items 6, 11 and 12.

Judgement gates that are already *data*, not prompts — keep and extend:
`EVALUATION_READY.txt` (`merge_zones.py:1609`), `features.json`
`"confirmed": true` (`modules/feature_merge.py:99`, enforced only in
`testing/run_on2026_run2.py:342`), `align_inputs.json` fingerprints
(`modules/align_fingerprint.py`).

### 1.5 The manual UI: `wildscan/`

A Textual TUI, 1,664 lines, `py -3.13 -m wildscan`. Zero production
importers; only `testing/test_wildscan.py` (21 tests) and
`testing/test_wildscan_commands_runnable.py` (14) import it. `textual` and
`rich` exist in `requirements.txt` only for it; `inquirer` only for
`main.py:8`.

Three things live **only** in wildscan and must be extracted before deletion:

1. `wildscan/session.py:589-727` `build_commands()` — the run plan, including
   the **pinned merge policy** `--loss_tolerance 0.0025 --scale_gate true
   --scale_min 0.9 --scale_max 1.1 --ladder merge_first --merge_scope
   neighbour --pair_gate overlap`. These are owner decisions
   (`testing/VERIFICATION_BACKLOG.md` B8) recorded nowhere else;
   `rs_settings.json` on the old checkout held `loss_tolerance: 0.0`.
2. `wildscan/app.py:398-418` `_refresh_export_command()` — re-resolves the
   export's `--project`/`--names` from a fresh census right before launch;
   fixes a real bug where a merge+export run exported the *previous*
   assembly.
3. `wildscan/session.py:749` `workspace_input_crs()` — EPSG from the
   workspace's own flight log for `publish_batch.py --input-crs`.

Also worth keeping from `session.py`: `scan_raw_data` / `scan_cameras` /
`scan_processed_data` (raw-data detection), `write_camera_records()`,
`export_names_file()`, `RESULTS_LAYOUT`, `CHAIN_STAGES`/`POST_STAGES`.
`wildscan/workspace.py` is a shim over `modules/workspace_census.py` —
delete freely.

### 1.6 Pipeline knowledge living outside the repo

`C:\Users\produ\coyotethings\tools\` holds five scripts that are correct only
because of repo invariants (filename timestamp grammar, `camera_registry`
tokens, `image_exts` inventory, `raw_images` layout, prior-group delivery)
and that encode hard-won dataset facts (Sony clock on UTC+9, DNG
`white_level=255` over 12-bit data, fixed WB triple, cinemacam forward
mount):

| Script | Depends on | Move in as |
|---|---|---|
| `extract_pipeline.py` | shells `main.py` with `RS_MODULES='Extract Images'`; hardcodes `RS_CLI = …\tools\RealityScan_CLI` (**now the wrong path**) | the extract-stage driver |
| `stage_wca_stills.py` | `<UTC14>_<token>.jpg` contract; fully argparse'd | `modules/staging/` |
| `stage_h2082.py` | same contract; one-dive constants | rules → `modules/staging/`; constants → the dive's charter |
| `convert_dng.py` | `image_exts` lacks DNG; OpenCV cannot decode Bayer | `modules/staging/`; add `rawpy` to requirements |
| `crop_upper_1to1.py` | `cameras.json` focal for `starboard_1to1` | `modules/staging/` next to the value it derives from |

### 1.7 Conventions already in place to build on

Per-stage JSON reports (`batch_inputs.json`, `align_inputs.json` +
`*.rsalign.manifest.json`, `merge_report.json`, `grow_report.json`,
`models_report.json`, `publish_report.json`, `DELIVERABLE_MANIFEST.json` v0);
the `<results_root>/_agent/` workspace (real instance:
`NA165\H2063\proc\_agent\{RUN_CHARTER.md, RUN_LOG.md, run_*.cmd,
run_*.py}`); the hand-rolled scheduler launchers
(`launch_merge_resume.vbs`, `run_merge_resume.cmd`); the owner-facing
`RUN_REPORT_<date>.md` format (`NA168\RUN_REPORT_2026-08-14.md`); 40 `RS_*`
environment variables as the Python→cmd channel; `docs/rs-reference/` with
provenance tags; `STAGE_ORDER` in `modules/workspace_census.py:41`.

### 1.8 Dead weight (fresh `main`, verified)

| Item | Size | Verdict | Reason |
|---|---|---|---|
| `wildscan/` + its 2 test files | 224 KB | **delete** (after §1.5 extraction) | the manual UI |
| `testing/run_on2026_{run2,run3,union,wreck}.py`, `run_workbench_night.py`, `run_calib_ladder.py`, `yellow_filter.py`, `probe_cesium_depth.py` | ~3,400 lines | **archive** → `archive/campaign_drivers/` | finished campaign drivers with hardcoded `M:\` paths; `run_on2026_wreck.py` is declared retired |
| `testing/results/` (4 files) | 240 KB | **archive** | raw campaign data cited by frozen reports |
| `RS_CLI/Scripts/Probe*.bat` (7), `GuiWorkbench.bat`, `NightGrow.bat`, `CalibCellAlign.bat`, `ComputeModel.bat` | 11 scripts | **archive** → `archive/probes/` | probes and one-offs; production is 10 scripts (below) |
| `AlignImagesFromFolder.bat` | | keep while `run_zone9_tests.py` lives | its only caller |
| `sensorsdb.xml` | 48 KB | **archive** | no code on main reads it |
| `docs/FRESH_RUN_2026-07-24.md`, `GOAL_VERIFICATION_SESSION.md`, `code-review-2026-07.md`, `MERGE_REWORK_RECOMMENDATIONS.md` | 865 lines | **move** → `docs/history/` | session logs; update `README.md:46` |
| `docs/COLMAP_CROSSOVER.md`, `COLMAP_FINDINGS_UNIFIED.md` | 588 lines | **move** → `archive/colmap/docs/` | frozen; canonical home is another repo |
| `HANDOFF.md` | 1,474 lines | **split**: current section stays; dated sections → `docs/handoff/` | CLAUDE.md says read it first — make that cheap |
| `testing/*.md`, `archive/`, `RS_CLI/Metadata/*.xml`, `flightlogs.xml`, `calibration.xml`, `FINDINGS.md` | | **keep in place** | cited by path from FINDINGS and rs-reference; Metadata and the two format XMLs are live |

Production workflow scripts after slimming: `startRealityScan`,
`SetVariables`, `AlignZone`, `MergeZoneComponents`, `GrowZone`,
`GenerateModel`, `ModelToFinal`, `ExportDeliverables`, `SaveProjectCopy`,
`FlushCache`.

One test-hygiene defect found while baselining: `testing/test_preprocess_module.py`
constructs `SettingsStore()` with the default path, so **the unit suite
writes `rs_settings.json` into the repo root** (created here at 13:19,
removed). Tests must use a `tmp_path` store.

---

## 2. Target layout

```
RealityScan_CLI/
├── CLAUDE.md                     ≤150 lines: identity · session protocol · invariants · routing
├── CLAUDE.local.md               gitignored: this machine's venv, drives, instance names
├── HANDOFF.md                    current campaign only; older sections → docs/handoff/
├── FINDINGS.md                   raw fact log (unchanged role; add a heading index)
├── README.md                     "this pipeline is driven by Claude Code" quickstart
├── .claude/
│   ├── settings.json             hooks + permissions (allow / deny / ask)
│   ├── hooks/                    guard_rs_launch · guard_charter_writes · normalize_crlf · session_status
│   ├── skills/                   rs-lookup · charter · drive-run · status · merge-zones · model · publish · handoff
│   ├── agents/                   run-monitor (read-only) · rs-reference (read-only)
│   └── rules/                    rs-scripts.md · realityscan-interface.md · testing.md
├── rs.py                         Phase 3: ONE entry — charter | plan | run | launch | status | verify | handoff
├── main.py  merge_zones.py  grow_zone.py  run_models.py  finish_model.py  publish_*.py  geoall.py …
├── module_base/                  RSModule · Parameter · SettingsStore (+ NO_INHERIT) · scene_checkpoint
├── modules/
│   ├── run_charter.py  verify.py  run_plan.py  launch.py     ← the agent-facing oracles
│   ├── staging/                                              ← ex tools/*.py
│   └── … (domain modules unchanged)
├── modules/realityscan_interface/RS_CLI/{Scripts,Metadata,Errors}   Scripts = 10 production workflows
├── docs/  ARCHITECTURE.md · AGENT_OPERATIONS.md · RUN_CHARTER.template.md · rs-reference/ · history/ · handoff/
├── testing/                      tests + run_zone9 harness + the living *.md plans
└── archive/  colmap/ · campaign_drivers/ · legacy_scripts/ · probes/
```

---

## 3. Phases

Order matters: reconcile → guardrails → headless code → one entry point →
slim. Each phase ends green (`py -3.13 -m pytest testing -q`) and with
`HANDOFF.md` refreshed.

### Phase 0 — Reconcile and freeze (1 session + one RealityScan probe)

1. **D1 probe.** On the smoke fixture, run the sidecars-branch `AlignZone`
   with `prior_groups` and export registration; apply the solved-focal-
   equality oracle from the 2026-08-08 cell (do groups stick? are focals
   equal within a group?). Record the result in `FINDINGS.md` as `[RECON]`.
2. **Merge `remove-xmp-sidecars` into `main`** (main is the base: it has the
   delivered H2060 run, the reference manual, Cesium placement and the
   larger suite). Resolve the conflict set in §1.1 with D1's answer in hand.
   Full suite green.
3. **Cherry-pick the agent-native code** onto the merged main:
   `modules/run_charter.py`, `modules/verify.py`, `wildscan/plan.py` (lands
   as `modules/run_plan.py` in Phase 2 — for now keep the path),
   `module_base/settings_store.py` `RS_NO_SETTINGS_INHERITANCE`, all of
   `.claude/`, `docs/ARCHITECTURE.md`, and `testing/test_agent_hooks.py`,
   `test_run_charter.py`, `test_verify_oracle.py`, `test_wildscan_plan.py`.
   Skip its CLAUDE.md/FINDINGS/HANDOFF edits; skip `85c556a` unless D3 says
   yes.
4. **Tag** `manual-era-final` on the merged tree before anything is deleted.
   Git is the archive for the TUI; no in-tree copy.
5. Fix the stale numbers in CLAUDE.md (test count; the 300 s shutdown figure
   `VERIFICATION_BACKLOG` A1 already flags).
6. **Retire the old checkout** at `coyotethings\tools\RealityScan_CLI` once
   its branch is merged (D6). This clone at `coyotethings\RealityScan_CLI`
   is the working copy. Note the untracked runtime bloat there
   (`RS_CLI/Errors/*.dmp`, `.lock`, `expected_*.txt`, ~1.5 MB) simply goes
   with it — check no instance is live first.

Verify: `git log --graph --oneline -20` shows one line; suite green; the D1
`[RECON]` entry exists; `git tag` lists `manual-era-final`.

### Phase 1 — Agent substrate: `.claude/` (1 session)

1. **`settings.json`** — keep the three hooks from the branch; add:
   - `permissions.allow`: `Bash(py -3.13 -m pytest *)`, `Bash(py -3.13 -m
     modules.verify *)`, `Bash(py -3.13 -m modules.run_charter *)`,
     `Bash(py -3.13 -m modules.run_plan *)`, `Bash(git status*)`,
     `Bash(git log*)`, `Bash(git diff*)`, and the PowerShell read-only
     equivalents. The routine loop stops prompting.
   - `permissions.ask`: `Bash(schtasks *)`, `Bash(taskkill *)`,
     `Bash(git push*)`, `PowerShell(Stop-Process *)`.
   - Protected *data* paths are per-machine; they stay in the charter (the
     hook enforces them) and in `CLAUDE.local.md`, not in the committed
     settings — exactly what `AGENT_OPERATIONS.md` §7 recommends.
2. **`hooks/session_status.py`** (new, `SessionStart`): prints the current
   `HANDOFF.md` section, `git status --short`, and — if `RS_RUN_CHARTER` or
   a `RUN_STATE.json` is present — the verify oracle's one-line verdict.
   Orientation becomes one hook instead of three file reads.
3. **CLAUDE.md diet** to ≤ 150 lines. Keep: identity, "Starting a session"
   (now three lines because the hook does the reading), "Ending a session",
   Environment, the 9 hard rules, the 9 driving mandates *as one-liners*
   pointing at `/drive-run`. Move: Architecture → `docs/ARCHITECTURE.md`
   (branch already did it); RealityScan facts → `/rs-lookup`; working
   practices → `docs/AGENT_OPERATIONS.md` §"practices".
4. **Skills** (8). From the branch: `rs-lookup`, `drive-run`,
   `merge-zones`, `finish-model` → rename `model`, `publish-cesium` →
   `publish`. New: `charter` (the intake Q&A that writes and validates
   `RUN_CHARTER.json` and gets sign-off — the one skill that talks to the
   owner), `status` (runs verify + reads `RUN_STATE.json`; read-only;
   auto-invocable), `handoff` (session end: FINDINGS flush, HANDOFF current
   section, commit). Skills that launch work carry
   `disable-model-invocation: true` so they run only when the owner says so.
5. **Agents** (2). `run-monitor`: `tools: Read, Glob, Grep, Bash` with
   `permissionMode: plan`; polls progress files, `RUN_STATE.json`,
   RAM/disk; reports, never acts. `rs-reference`: read-only over
   `docs/rs-reference/`; returns the answer with its provenance tag.
6. **Rules** (3): `rs-scripts.md` (`paths: modules/realityscan_interface/RS_CLI/**`),
   `realityscan-interface.md` (`paths: modules/realityscan_interface/*.py`),
   `testing.md` (`paths: testing/**` — no RealityScan boot in unit tests,
   `tmp_path` SettingsStore).
7. `CLAUDE.local.md` (gitignored): this machine's interpreter
   (`C:\Users\produ\coyotethings\tools\.venv\Scripts\python.exe`, 3.13.14 —
   `py -3.13` is not on PATH in Git Bash here), drives, instance names.

Verify: `testing/test_agent_hooks.py` green (liveness); a new session shows
the status hook output; `wc -l CLAUDE.md` ≤ 150; `/status` works on the
NA165/H2063 workspace.

### Phase 2 — Headless-first pipeline and TUI removal (2–3 sessions)

1. **Prompts fail fast.** Under `RS_RUN_CHARTER` or `RS_NO_INTERACTIVE`,
   every site in §1.4 raises a named error instead of prompting or silently
   defaulting; `--yes` is the only auto-accept (PRODUCT_READINESS 11/12).
   Batch accept/reject → `--b_accept`; overwrite prompts → `--overwrite
   {refuse,replace}`; `decimator.py` gains argparse; `timestamp_rename.py`
   gains `--yes`; `main.py` drops `inquirer` (`RS_MODULES`/`--modules` is
   the picker).
2. **Extract, then delete the TUI.** `wildscan/session.py` planner + branch
   `plan.py` → `modules/run_plan.py` (keep §1.5 items 1 and 3; port
   `_refresh_export_command` so export project/names resolve at *launch*
   time). Delete `app.py`, `branding.py`, `runner.py`, `__main__.py`,
   `__init__.py`, `workspace.py`, `wildscan/requirements.txt`. Retarget
   `test_wildscan_commands_runnable.py` and `test_wildscan_plan.py` to
   `modules.run_plan`; keep the session-model tests from `test_wildscan.py`,
   drop the Textual screens. Remove `textual`, `rich`, `inquirer` from
   `requirements.txt`. Fix the 13 prose mentions (`README.md`,
   `PRODUCT_READINESS.md`, comments).
3. **Stage reports everywhere.** Extract, georeference, preprocess and
   export write `<stage>_report.json` (schema, inputs by sha256, outputs by
   count, verdict) alongside the existing five; `DELIVERABLE_MANIFEST.json`
   goes to v1 (PRODUCT_READINESS 4). `modules.verify` reads all nine.
4. **`modules/launch.py`** — scheduler-owned launch as code: writes
   `<results>/_agent/launch/<stage>.cmd` (CRLF) + `.vbs`, registers
   `schtasks /Create /SC ONCE`, writes `RUN_STATE.json` (task name, pid
   file, log, budget, abort criteria, resume command). Codifies the
   `NA165\H2063\proc\_agent\run_*.cmd` pattern. `status` reads it. Add the
   interruption marker (PRODUCT_READINESS 8: a killed driver is not a
   cancelled run).
5. **Bring the staging scripts in** as `modules/staging/` (§1.6) with one
   `stage` CLI; add `rawpy`.
6. Tests use `SettingsStore(path=tmp_path/...)`; the suite never writes
   the repo root.

Verify: a charter-driven smoke run on the fixture end to end with no TTY
(`RS_RUN_CHARTER` set, `stdin=DEVNULL`) exits 0 and `modules.verify`
returns 0; `grep -rn "import inquirer\|from textual" .` returns nothing
outside `archive/`; suite green.

### Phase 3 — One command surface (1 session)

`rs.py` — a thin façade, no logic moved:

```
rs charter init|validate <path>      → modules.run_charter
rs plan --charter <c> [--validate]   → modules.run_plan
rs run <stage> --charter <c>         → the existing driver, headless
rs launch <stage> --charter <c>      → modules.launch (scheduler-owned)
rs status [--workspace <ws>]         → RUN_STATE + modules.verify
rs verify --workspace <ws> --json    → modules.verify
rs handoff                           → HANDOFF/FINDINGS checklist
```

Skills call only `rs …`; the allow-list shrinks to `Bash(py -3.13 rs.py *)`;
a future UI consumes the same JSON. This is where the branch's "agent-facing
entry points" list in CLAUDE.md collapses to one line.

Verify: every SKILL.md command is an `rs` command; `rs --help` lists seven
subcommands; suite green.

### Phase 4 — Slim the repo and docs (1 session)

Execute §1.8: archive campaign drivers, probes, results, `sensorsdb.xml`;
move session-log docs to `docs/history/`; split HANDOFF; add a heading index
to FINDINGS; rewrite README around the operating model ("open Claude Code
here; `/charter` a run; `/drive-run`; `/status`"); retire
`guard_rs_launch.py`'s regex to the 10 production scripts.

Verify: suite green; `grep -rn` for each moved path in CLAUDE.md, README,
skills and rs-reference finds only intentional history references.

### Phase 5 — UI, later (out of scope now)

Any future UI reads `rs status --json` and `RUN_STATE.json` — the same
oracle the agent reads — and writes a charter. Nothing from the deleted TUI
is needed for that beyond what Phase 2 preserved in `modules/run_plan.py`.

---

## 4. Owner decisions

| # | Decision | Recommendation |
|---|---|---|
| **D1** | Do CLI prior groups work, or not? (`main` 2026-08-08 vs `remove-xmp-sidecars` 2026-08-14) | Run the probe in Phase 0 step 1 before merging. If groups stick, the sidecar-free line is canonical and hard rule 0 stands. If not, hard rule 0 needs a different delivery path (`-addImageWithCalibration`, which main records as validated) and the H2080/H2063 components were aligned with per-image self-calibration. |
| **D2** | Base branch for the merge | `main`. Merge `remove-xmp-sidecars` into it. |
| **D3** | Adopt `85c556a` (Zeuss 25/45, orientation hardness 2.0) with the tooling? | Separate it. It is un-A/B'd science by its own commit message; review it on its own. |
| **D4** | Delete scope | Delete the TUI entirely (git tag is the archive). *Archive*, don't delete, campaign drivers and probes — they are `FINDINGS.md` citation targets. |
| **D5** | `rs_settings.json` remembered answers | Keep for machine constants (`realityscan.executable`, `instance_name`, `cache_dir`). Science and path answers come from the charter; `RS_NO_SETTINGS_INHERITANCE` is on whenever a charter is. |
| **D6** | Retire `coyotethings\tools\RealityScan_CLI` and move the five `tools\*.py` scripts into the repo | Yes, after Phase 0 step 2. `extract_pipeline.py` already points at the wrong path. |

---

## 5. What was and was not done in this session

- Cloned `origin/main` fresh into `C:\Users\produ\coyotethings\RealityScan_CLI`
  (the previously empty working directory) and ran the suite: 597 passed,
  1 skipped. Removed the `rs_settings.json` the suite wrote.
- Read the three branches, the `.claude/` draft on `agent-native-execution`,
  the agent-operations contract, the charter template, the readiness
  backlog, and the on-disk NA165/NA168 workspaces.
- Added this document. No other file changed; nothing committed; the old
  checkout under `tools\` is untouched (clean, on `remove-xmp-sidecars`,
  fully pushed).
- Not done, by design: no merge, no deletion, no `.claude/` scaffolding —
  Phase 0 needs D1 and D2 first.
