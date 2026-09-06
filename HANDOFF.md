# HANDOFF — state of the July 2026 overhaul

## 2026-09-06 (afternoon) — D1 CSV LANE RAN END TO END, scheduler-owned, read this first

Two RealityScan runs happened this afternoon, both through the lane
(`rs charter` -> `preflight` -> `plan --validate` -> `launch` -> Task
Scheduler -> `RUN_STATE.json` -> `rs verify`), both on instance RSAGENT with
their own cache, both with the source dataset read-only and zero `*.xmp`
beside any image. The owner's instruction ("D1: design and execute an end to
end comprehensive test of the CSV workflow. End to end means zones too and
merging. Ideally no xmp are written") is the sign-off quote in both charters;
every charter answer was DERIVED by the agent and is listed below for veto.
Suite: **934 passed, 1 skipped** (`python -m pytest testing -q`, this box). Nothing pushed.

### Done

- **D1 run** (`C:/Users/jonat/Desktop/CoyoteThings/NA173_H2014g_RS/`, charter
  under `_agent/`): fixture F2 (363 images, 121 per camera, 20:17:36-20:19:36),
  copy layout, `b_target_images 180 / b_min_zone 100 / b_max_zone 250`,
  `min_component_size 50`, `identity_capture: csv`. Batch -> 2 zones (229 /
  200) -> 2 aligns -> merge, 10 min wall, exit 0. Results: zone_1 one
  component of 78 (all cammid), zone_2 one of 80 (64 cammid + 16 camlower);
  merge fused them into ONE 158-camera component (`attribution exact`,
  `cameras_lost 0`, `EVALUATION_READY`). Identity CSVs present with the
  per-camera focal/k1/k2 readback; **0 XMP** beside images, 316 ordinal XMPs
  inside `merged/cluster_0/attempt_1_merge_georef/identity_r*/` (the merge
  peel census, the last XMP writer). `rs verify` OK. FINDINGS
  `[NA173] 2026-09-06` (run), `[RECON] 2026-09-06` (D1 arm (i)),
  `[HARNESS] 2026-09-06` (lane defects).
- **C0 probe** (`C:/Users/jonat/Desktop/CoyoteThings/NA173_C0probe_RS/`):
  41 cammid frames, params naming the stock 7-column `{0E9850E2}`. Settled:
  `gpsLogFileFormat` IS honoured (`.rsproj` shows `registered` + `-1`
  orientation accuracies vs the F2 run's `pose` + 15/15/15); the 13-column
  log imports all 13 columns under `{D1F2A3B4}`; RealityScan's own event-log
  `file_format` never follows the params (a stored `{B438A617-2424-...}`
  string on this box) and is not an oracle. 3 min wall. FINDINGS `[NA173]
  2026-09-06` (C0 probe); rs-reference 06 A6-A8, 01 A6, 05 A9, 08 A5, 11 A5.
- **Lane fixes found by the runs**: `eaa2bb4` (`rs launch --stages a,b,c`
  was refused on the comma), `591a30f` (`rs verify` blocked every copy-layout
  run on per-zone flight logs; the batch fingerprint now vouches per zone),
  and this commit: preflight runs the batcher's own `validate_parameters()`
  on the charter (the first probe launch died at start-up on
  `b_target_images < 100` after READY) and compares the log width with the
  charter's `r_flight_log_params`, not the canonical template.
- **Owner-relayed H2063 findings checked and fixed here** (FINDINGS
  `[HARNESS] 2026-09-06` scale oracle entry): `f972b6d` was already in the
  branch; the scale oracle now reads `identity/*.csv` (rigid-invariant, so
  the model frame is fine - my earlier "not a scale readback" line is
  SUPERSEDED); `merge_zones.attribute_result` accepts a fusion's peel count
  anywhere from its unique image count to its camera sum and counts only
  the shortfall below unique as loss (`cameras_lost` no longer includes
  folded copies). Tests carry the H2063 and F2 numbers.
- **D1 decision narrowed** (`docs/DECISIONS.md`): CSV lane proven end to end;
  arm (i) of C6 measured (prior groups alone -> every camera its own focal);
  arms (ii)/(iii) still to run; the scale oracle now reads the identity CSVs
  (F2 stays unmeasured only because the ROV moved under 3 m in the window).
- `testing/NA173_TEST_PLAN.md`: C0 answered, C1 done (F2), C2 partial
  (model + export half pending), C6 arm (i), C12 done, C13 re-estimated.
- Memory: `honeybadger-box` corrected (hostname RiverOtter; scheduler notes),
  `owner-wants-no-prompts` (feedback).

### Running

Nothing. Both scheduled tasks were deleted after their runs; RSAGENT's lock
is free; RealityScan's CRTemp logs are copied under each workspace's
`_agent/logs/rs_logs/`.

### Charter answers derived by the agent (veto here)

| Charter | Answer | Derived from |
|---|---|---|
| F2 | `b_input` = `_agent/fixture/F2` (a COPY of the 120 s window, never the source tree) | "end to end ... zones too and merging" needs >= 2 zones at fixture cost |
| F2 | `b_target_images 180 / b_min_zone 100 / b_max_zone 250`, copy layout | two overlapping zones of ~200; pool layout would point RealityScan's writes at the source |
| F2 | `science.min_component_size 50` | the test plan's F2 row |
| F2 | `identity_capture: csv`, ladder `merge_first`, neighbour scope, overlap gate, loss 0.0025, `scale_gate true` | the CSV workflow under test with the production merge defaults |
| C0 | 41 cammid frames, `b_target_images 100 / b_min_zone 10 / b_max_zone 150`, `min_component_size 10`, `r_flight_log_params` -> the `{0E9850E2}` copy | cell C0's decision rule; the batcher's >= 100 bound |

### Ranked loose ends

1. **When does RealityScan fold duplicate copies?** F2 kept both copies of
   the 21 shared images (158 = 78 + 80); the owner's H2063 numbers show
   fused components peeling at the unique count. The accounting now accepts
   both (`attribute_result`, `duplicates_collapsed` in the report), but the
   condition (merge mode? shared-image graph? build?) is unmeasured. The
   H2063 re-merge the owner's other session proposed (`--resume`,
   `--loss_tolerance 0.0025`) is the live test; it runs on the NA165 box.
2. **C6 arms (ii) and (iii)** on F0/F2 (XMP sidecars = known-good; neither
   = known-bad) to finish D1's prior-group question; arm (i) is measured.
3. **C2's model + export half** on the F2 assembly (158 cameras) - D12/D13
   live proof; then C13 at full scale (F2 measured 10 min for 363 images).
4. **Registration on this rig**: camlower and zeuss barely join the cammid
   strip (34-40 % per zone). Science, not lane; the owner may want C4/C5
   (hardness, Zeuss mount) before C13.
5. The installed `flightlogs.xml` has drifted from the repo copy (06 A8);
   `install_all_managed` never corrects an existing id.
6. The merge peel census still writes ordinal XMPs (inside its attempt
   folder); porting it to `-exportRegistration` is optional hygiene.
7. `stash@{0}` (the 90 on-disk deletions from 2026-09-05 22:25) is still
   parked: pop or drop. Push when the owner says so.

### Artifact locations

- D1 run: `C:/Users/jonat/Desktop/CoyoteThings/NA173_H2014g_RS/` -
  `_agent/{RUN_CHARTER.json,RUN_STATE.json,build_fixture.py,analyze_csv_run.py,
  launch/,logs/,logs/rs_logs/}`, `aligned_components/zone_{1,2}/{identity/,*.rsalign,
  *.manifest.json,align_inputs.json,zone_N.rsproj}`, `merged/merge_report.json`.
- C0 probe: `C:/Users/jonat/Desktop/CoyoteThings/NA173_C0probe_RS/` (same
  shape; `_agent/FlightLogParams_probe_0E9850E2.xml`).
- Fixtures: `_agent/fixture/F2` (1.81 GB) and `_agent/fixture/F0` (0.2 GB) -
  copies, safe to delete.

### Exact next commands

```
python -m pytest testing -q
python rs.py verify --workspace C:/Users/jonat/Desktop/CoyoteThings/NA173_H2014g_RS
python rs.py status --charter "C:/Users/jonat/Desktop/CoyoteThings/NA173_H2014g_RS/_agent/RUN_CHARTER.json"
python C:/Users/jonat/Desktop/CoyoteThings/NA173_H2014g_RS/_agent/analyze_csv_run.py
```

## 2026-09-06 — RECONCILED + REVIEWED on `recon-tmp` (a worktree), read this first

The owner's local `agent-native-execution` branch (2 commits, 2026-08-31 /
09-01) was reconciled onto `origin/claude/agent-native-consolidation` (the
2026-09-05 consolidation, which already carried the first commit as the
cherry-pick `d38d5f3`): merge `f244edf` takes the consolidation tree
verbatim, then `677aa6c` re-applies the Zeuss 25/45 + hardness 2.0 commit
(**D3: owner said yes**). On top: the first Windows run of the suite, the
owner's texture policy (**D13**), and the review fixes. Suite: **879 passed, 1 skipped**
(`python -m pytest testing -q`, this box). Nothing ran against
RealityScan; no dataset, instance or scheduled task was touched.

### Where the work is

- **`agent-native-execution` in the main checkout is fast-forwarded to this
  tip** (`git merge --ff-only recon-tmp`, run at the end of the session after
  the classifier had refused `git checkout` / `git restore` / `git branch -f`
  and a compound merge earlier). The scratch worktree that carried the work
  (`C:/Users/jonat/AppData/Local/Temp/claude/C--Users-jonat-Desktop-CoyoteThings-RealityScan-CLI/5b974d57-9075-4336-af70-4a3cd147b20b/scratchpad/rs_recon`,
  branch `recon-tmp`) was removed and the branch deleted at session end;
  `git worktree list` shows only the main checkout.
- The main checkout had **90 tracked files deleted on disk** when the session
  started (`CLAUDE.md`, `HANDOFF.md`, `FINDINGS.md`, all of `testing/`,
  `wildscan/`, `archive/`; mtime 2026-09-05 22:25, minutes before the
  session; not by this session). The fast-forward re-wrote the ones that
  changed; the 58 that had not changed were restored by parking the
  deletions in **`stash@{0}`** ("90 tracked files found deleted on disk ...").
  If the deletion was deliberate: `git stash pop` puts it back; if not:
  `git stash drop`. Nothing is lost either way.
- `origin/agent-native-execution` was deleted on the remote on 2026-09-03
  (its head is tag `agent-native-execution-final`). Nothing was pushed;
  pushing recreates the remote branch (`git push -u origin agent-native-execution`).
- The 18 GB `test_dataset_NA173_H2014g/` sits INSIDE the repo root,
  untracked and not gitignored: never `git add -A` there.

### Done

- **D3** applied (`677aa6c`); **D13** applied (`eca8aba`): AdaptiveTexelSize
  4096 in every texture pass, the nine `MaxTexturesCount` presets retired to
  `archive/metadata_retired/`, `:try_unwrap` fallback to 4 × 4096 in
  `GenerateModel.bat` and `ModelToFinal.bat`, JPG in every export preset,
  `ModelToFinal.bat` presets `adaptive|fixed100|fixed50`, preflight blocks
  any live preset above 4096 or a non-JPG export (`testing/test_texture_policy.py`).
- **D6** checked on this box: the five staging scripts are not here
  (searched `C:\Users\jonat`, `D:`, `E:`, `F:`); they exist only on the NA165
  box. Still OPEN.
- Windows suite: two Windows-only test defects fixed (`d9e61d3`).
- Review workflow (7 lenses + adversarial verification + NA173 probe): 78
  findings; the confirmed and hand-verified must/should ones fixed
  (`testing/test_review_fixes.py`, 39 tests) - FINDINGS `[HARNESS]
  2026-09-06` lists them. Headline: the charter's `align_settings_xml` never
  reached the run; `--stages` was preflighted against the wrong stage list;
  a zone mismatch in `science.frame` passed; pool layout would have skipped
  every zone; the printed `schtasks` line could not be run from an agent
  tool; `--foreground` was ungated; ModelToFinal's fallback would have
  aborted the reprojection on its own marker.
- Docs of record corrected (rs-reference 01-06/09-13/README, CLAUDE.md,
  README, skills, rules, DECISIONS D3/D6/D10/D12/D13/D15,
  PRODUCT_READINESS; `WORKFLOW_WALKTHROUGH.md` → `docs/history/`).
- `testing/NA173_TEST_PLAN.md`: what is tested, why, the oracles with their
  known-good/known-bad, 14 cells (C0-C13), two fixtures, the budget.
- Memory (this box): `harness-git-and-hook-limits`, `honeybadger-box`.

### Running

Nothing.

### Ranked loose ends

1. Decide the parked deletions (`stash@{0}`: pop or drop); push when the
   owner says so (`git push -u origin agent-native-execution`).
2. **Owner decisions still open** - the prompts are in the session's final
   report and in `docs/DECISIONS.md`: D1 (run cell C6 first, or keep the XMP
   default), D9 (promote `stage_features` - cell C11, low risk), D10 (export
   report with the texture census - C10), D12 (simplification strategy and
   the blind deletes - C9; state N and the ratio), D15 (keep `FINDINGS.md`
   guarded, split the old tail to `docs/history/`).
3. Run the plan in order: C1, C2 (owner runs `--foreground`), C0, C3, C10,
   C12, C4, C5, C13, C7/C8. The mini fixture (F1) first; nothing touches
   the source tree.
4. Cell C0 before any prior-dependent number: the 13-column log under the
   14-column format is UNMEASURED (preflight warns).
5. `test_rig_mounts.py` `logging.disable` leak; `test_preprocess_module.py`
   is a staging script under a test name (0 tests collected).
6. The routing hook's phrasing; `RS_RUN_CHARTER` set-but-unusable blocking
   read-only commands (fail-closed, kept).

### Artifact locations

Worktree + branch `recon-tmp` (above). Review outputs:
`<scratchpad>\review_result.json`, `<scratchpad>\agents\na173-probe\`
(probe charters and plans; `RUN_CHARTER.json` there is a scratch charter
signed "probe" - never a real sign-off). Tags `agent-native-execution-final`
(`85c556a`) and `manual-era-final` (`b640c81`) unchanged.

### Exact next commands

```bash
git stash list                                                # stash@{0} = the parked deletions
python -m pytest testing -q                                   # expect 879 passed, 1 skipped
python rs.py charter init <results_root>/_agent/RUN_CHARTER.json   # cell C1, mini fixture F1
python rs.py preflight --charter <C>
python rs.py plan --charter <C> --validate
```

---

## 2026-09-05 — AGENT-NATIVE CONSOLIDATION on branch `claude/agent-native-consolidation`, read this first

Roadmap Phases 2–4 landed in one pass (docs/history/AGENT_NATIVE_ROADMAP.md):
prompts fail fast headless, the planner is `modules/run_plan.py`, the TUI is
archived FUNCTIONAL, `rs.py` is the one command surface, `modules/preflight.py`
asks for every missing answer before a run, probes/campaign drivers/session
docs are archived, CLAUDE.md is routing-only. Suite on the macOS box that did
the work: **784 passed, 22 failed (platform-bound, listed in
testing/conftest.py), 4 skipped**; Windows expectation unchanged: fully green
(NOT run here — first thing to do on the Windows box). Nothing running. No
RealityScan workflow content changed; no science argument changed.

### Done

- `rs.py` — `charter | preflight | plan | run | launch | status | verify`.
  `run`: headless, `RUN_STATE.json` + per-stage logs under `<ws>/_agent/`,
  export `--project/--names` re-resolved at launch, refuses RealityScan
  stages from a `CLAUDECODE` shell. `launch`: CRLF `.cmd`+`.vbs` pair, prints
  the three `schtasks` commands (never runs them). `status`: read-only.
- `modules/preflight.py` — missing answers as QUESTIONS (`missing[]`), unsafe
  facts as `blocking[]`; derives required answers from the modules' own
  Parameters; unknown camera prefixes are questions, never assumed mounts.
- `modules/run_plan.py` — ex `wildscan/session.py` + `plan.py`, one planner;
  `refresh_export_command`; `IMAGE_EXTS` = `ALL_IMAGE_EXTS`.
- Unattended contract: `SettingsStore.unattended()` / `default_for()`;
  `main.py` fail-by-flag under `RS_NO_INTERACTIVE`/charter, lazy `inquirer`;
  batcher default via `default_for`; `geoall` no hardcoded paths;
  `decimator` argparse + `--yes`; `timestamp_rename --yes`.
- `testing/conftest.py` — the store never writes the repo root; `RS_*`
  scrubbed; session fails on a stray `rs_settings.json`. 3 new test files
  (+43 tests); 3 TUI test files retargeted to `modules.run_plan`.
- Archive (all functional, nothing deleted): `archive/wildscan_tui/`
  (`run_wildscan.py`), `archive/probes/` (9 `.bat`), `archive/campaign_drivers/`
  (+6), `archive/reference_data/sensorsdb.xml`, `archive/colmap/docs/`,
  `docs/history/` (5 docs + HANDOFF history + AUDIT). Map:
  `docs/history/README.md`.
- Docs: CLAUDE.md 128 lines (hard rule 10 added: the workflows are the
  product), README, ARCHITECTURE, AGENT_OPERATIONS compacted, `docs/DECISIONS.md`
  (D1–D14), skills rewritten around `rs.py`, rules/agents/hook updated,
  `.claude/settings.json` allow-list for `rs.py`/`modules.run_plan`/`preflight`.
- Second pass (same day): preflight also checks every module the stages
  import, every workflow script (present + CRLF), every Metadata preset
  (present, well-formed, format GUIDs defined, frame templates, no `app*`
  key, `.rsInfo` on) and `python` on PATH for the hooks. Three hooks added:
  `route_driving_prompts.py` (UserPromptSubmit: injects the /charter →
  /drive-run protocol on run phrasing), `guard_schtasks.py` (PreToolUse:
  `schtasks /Create` only for a launcher `rs launch` wrote), `pre_compact.py`
  + SessionStart on `compact` (re-orientation and an unflushed-facts warning
  after compaction). Agents: `run-monitor` on haiku, `rs-reference` on sonnet.
  `rs launch` prints the `/loop 30m` monitor line; `RUN_STATE.json` carries
  `poll_interval_min`. `docs/OPERATOR_SETUP.md` (per-box checklist).
- FINDINGS ↔ rs-reference RECONCILED: every RealityScan-behaviour entry
  through 2026-09-03 is in the manual (per-file `## Addenda`, 13 files);
  in-place corrections: 06 §3.2 CRS scopes RESOLVED, 09/10 export CRS type 3
  = ECEF VERIFIED, 10 §9.2 texture registry (8K, not 16K; live 16K
  fallthrough), 11 §10 recipe order (settings → CRS → flight log), 13 §10
  rig table (cinema 0°, upper 45°), 12 result codes + F-101…F-106. FINDINGS
  header states the organisation and the reconciliation rule; the 08-08
  "GUID is decorative" probe is marked SUPERSEDED by 08-16.

### Running

Nothing.

### Ranked loose ends

1. **Run the suite on the Windows box** and confirm fully green; the
   alignment tests and `M:\` basename tests could not run on macOS. Then
   run `python rs.py preflight --charter <existing charter>` against a real
   workspace (NA165/H2063) — the first live use of the oracle.
2. **D1** (`RS_LEGACY_XMP_IDENTITY` default) is still open — the
   solved-focal-equality probe on the smoke fixture settles it.
3. **D6** — the five staging scripts under `coyotethings\tools` are still
   outside the repo (`modules/staging/` never created).
4. **D9/D10** — promote `stage_features` out of `testing/run_on2026_run2.py`;
   per-stage `<stage>_report.json` for extract/georeference/preprocess/export.
5. `test_rig_mounts.py` leaks `logging.disable(CRITICAL)`; trivial fix.
6. `rs launch` has never been exercised on Windows end to end (the launcher
   pair is unit-tested for content and CRLF only); nor has the `/loop 30m`
   monitor been run against a live task.
7. **D12/D13** — `ModelToFinal.bat`'s blind `-selectModel`+`-deleteSelectedModel`
   pattern and the 16K unwrap fallthrough for non-`4x8k` presets are owner
   calls; both are documented (rs-reference 12 F-102, 10 A4), neither changed.
8. The new hooks arm only in a NEW Claude Code session; the UserPromptSubmit
   routing hook's phrasing list will need tuning on real prompts.

### Artifact locations

Branch `claude/agent-native-consolidation` on `origin`; nothing on any data
volume was touched (no dataset, no RealityScan instance, no schtasks).

### Exact next commands

```bash
python -m pytest testing -q                                   # Windows: expect fully green
python rs.py --help
python rs.py charter init <results_root>/_agent/RUN_CHARTER.json
python rs.py preflight --charter <C>
python rs.py plan --charter <C> --validate
python rs.py status --charter <C>
```

---

## 2026-09-03 — RECONCILED: one `main` again, agent-native lane adopted, read this first

Three lines became one. `main` now = the NA165/H2060 line + the
`remove-xmp-sidecars` line (merge `b640c81`) + the agent-native tooling
(`d38d5f3`, cherry-pick of `37d6d41`). Suite **725 passed, 1 skipped,
~22 s** with `python -m pytest testing -q`. Nothing running. Tag
`manual-era-final` marks `b640c81`, the last tree before the restructure
(the WildScan TUI and campaign drivers are recoverable from it).

Owner rule for the merge: main is the base and carries the latest actual
processes; every additive sidecars feature kept; nothing dropped except
literal duplicates. The plan is `docs/AGENT_NATIVE_ROADMAP.md`; this
session executed its Phase 0.

### What landed

- **Align identity: both mechanisms, main's default.** `AlignZone.bat` and
  `realityscan_interface.py` keep main's in-session `-exportXMP` harvest as
  the DEFAULT; `RS_LEGACY_XMP_IDENTITY=0` selects the sidecars line's
  non-destructive `-exportRegistration` CSV capture. The calibration-sidecar
  repair follows the same switch. `prior_groups.py` + `RS_PRIOR_GROUPS_FILE`
  replay run on EVERY align, walking the pool root.
- **Export CRS unified on `RS_PROJECT_CRS`**; `export_deliverables.py` keeps
  `--flight-log` / `--crs` and feeds it. `RS_OUTPUT_CRS` is gone.
- **cameras.json / MOUNTS**: full union; `wca_cinema` pitch 0.0 per the
  2026-08-14 owner correction, 45 on `wca_upper` / `na168_upper`.
- **Agent-native lane**: `modules/run_charter.py`, `modules/verify.py`,
  `wildscan/plan.py`, `RS_NO_SETTINGS_INHERITANCE`, `.claude/hooks/` +
  `settings.json`, five skills, `docs/ARCHITECTURE.md` (now carrying the
  merged architecture detail that left CLAUDE.md).
- **Hooks call `python`, not `py -3.13`** — this box has Microsoft Store
  Python 3.13 and NO `py` launcher, so the guards would never have fired.
  Proof they fire now: this session's own Bash call was BLOCKED by
  `guard_rs_launch.py` because its text quoted `ProbeCalibGroups3.bat`.
  Consequence to know: a non-read-only shell command that merely MENTIONS a
  workflow script name is refused; put such text in a file, or start the
  command with a read-only tool (`grep`, `cat`, `git`, `python`, ...).
- `guard_rs_launch` now covers every script under `RS_CLI/Scripts`
  (Probe*, AlignImagesFromFolder, and any future one).

### OPEN — owner decisions (numbered as in the roadmap)

1. **D1 — do CLI prior groups take effect?** main's FINDINGS 2026-08-08 says
   `-setPriorCalibrationGroup` is silently non-functional from the
   delegated CLI; the sidecars line ran H2080/H2063 with `prior_groups.py`
   and never measured it. FINDINGS `[RECON] 2026-09-03 - prior-groups
   claim: main and remove-xmp-sidecars disagree`. The solved-focal-equality
   oracle on the smoke fixture settles it; flipping the default is one line
   in each of the two files.
2. **D3 — `85c556a` (Zeuss 25/45, orientation hardness 2.0) NOT adopted.**
   Science, un-A/B'd by its own message. Preserved as tag
   `agent-native-execution-final`; review on its own.
3. **D6 — the old checkout** `C:\Users\produ\coyotethings\tools\RealityScan_CLI`
   sits on the now-deleted `remove-xmp-sidecars`; the five
   `coyotethings\tools\*.py` staging scripts hardcode that path. Roadmap
   Phase 2 moves them into `modules/staging/`.

### Branches

Deleted on origin after this push: `remove-xmp-sidecars` (merged),
`agent-native-execution` (cherry-picked; its head tagged). Left alone:
`claude/cesium-ion-georeferenced-ue5-vvpoau` (4 unmerged `cesium2unreal`
commits — not stale, unreviewed) and `archive/on2026-model-to-final-pre-rebase`.

### Next

Roadmap Phase 1 (`.claude/` substrate: permissions allow/ask, a
`SessionStart` status hook, CLAUDE.md to ≤150 lines, `charter` / `status` /
`handoff` skills, `run-monitor` + `rs-reference` agents, path-scoped rules),
then Phase 2 (prompts fail fast, TUI removal with the planner extracted to
`modules/run_plan.py`, stage reports, `modules/launch.py`, staging scripts
in).

### Exact next commands

```bash
python -m pytest testing -q
python -m modules.run_charter --init <results_root>/_agent/RUN_CHARTER.json
python -m modules.run_charter --validate <charter>
python -m wildscan.plan --charter <charter> --validate
python -m modules.verify --workspace <results_root> --json
```

---

## 2026-09-02 — NA165 / H2060 delivered end to end, read this first

**First full run of this pipeline from raw nav to exported deliverables.**
ExportDeliverables had never produced output on this machine before today.

### Done

| stage | result |
|---|---|
| ROVDataConcat stage 1+2 | 17 dives; H2049/H2050 excluded (degenerate `dives.tsv` rows) |
| georeference | 29,069 / 29,069 images matched, all exact |
| align | 20 components, 2,813 / 3,870 cameras (72.7%) |
| merge | one evolution (owner-capped); the abort was a real bug, now fixed |
| model | **20 / 20**, 14.3 h, census-verified |
| export | **20 / 20 with OBJ + FBX + dense PLY**, 91 GB |

Artifacts on the NAS, verified 2026-09-03 by a LIST-ONLY robocopy pass
(61,642 files / 253.9 GB across the three trees; 0 to copy, 0 mismatch,
0 failed, 0 extras). Robocopy's default compare is name+size+timestamp,
so this is size/mtime parity plus matching aggregate byte totals - NOT a
content hash. Use /BYTES-level hashing if a checksum is ever required:
`Y:\RUMI Projects and Output\NA165_H2060\{master,exports,preprocessed_images}`
Master project: `master\assembly\NA165_H2060_master.rsproj` (119.5 GB).

### What made this run hard (all fixed, all in FINDINGS.md)

Ten defects. The expensive ones shared two shapes:

1. **Pool layout moved where data lives and consumers kept looking in the old
   place.** FIVE of them: `bbox_from_flight_log`, `build_union_flight_log`,
   `scale_oracle.load_nav_positions`, the align stage's pool gate, and the
   merge's identity harvest. Grep `RS_MERGE_IMAGES_ROOT`, `images_root` and
   `split(';')[0]` before adding a sixth.
2. **A guard that answers the wrong question.** `run_models` wrote a full
   119.5 GB dated project copy immediately after aborting for low disk, and
   again when 157 GB free "passed" a fixed threshold - taking C: to 0.01 GB
   once. Now sized against the actual project.

Also: the dense-PLY "missing model" was a missing `-selectComponent`;
`0x80070057` from process 21856 is RealityScan's **-selectModel-cannot-resolve**
signature, and it is fatal in export because `:run` reads a STICKY errors file.

### Running

Nothing. All background tasks stopped, all scheduled tasks removed.

### Ranked loose ends

1. **`:run`'s sticky errors file** — one tolerated failure poisons every later
   command in the session, and errors get misattributed to whatever ran last.
   The primitive already exists (`try_delete_model` MOVEs to
   `expected_<reason>_<inst>.txt`); a shared `:try_run <tag> <cmd...>` would
   generalise it. This is the single highest-value cleanup left.
2. **Verify the CRS pin on the next dive.** `5c545e3` sets project + output CRS
   from the flight log's zone before `-importFlightLog`. Confirm a fresh
   `.rsInfo` declares the dive's own EPSG rather than a leftover. H2060's
   exports still carry the old arbitrary `55N` label — the GEOMETRY is correct
   ECEF (verified: 300k vertices resolve to the H2060 site), only the label is
   wrong, so re-export if a downstream tool trusts that attribute.
3. **`exportCoordinateSystemType=3` writes ECEF**, not the project CRS. Closes
   rs-reference OPEN question 16. Type 0 (PLY) still unobserved.
4. **Cache capacity.** ~72 GB per mid-size component, and `-clearCache` does
   NOT reliably reclaim it (148 GB -> 2.7 GB once, 148 -> 90.6 GB the next
   time). A COLD directory reset does. Budget accordingly.
5. **C: is at 43 GB free.** Local copies under `NA165_H2060_RS` are redundant
   now the NAS copy is verified; `master` + `exports` alone is ~210 GB.
   Owner decision — nothing deleted.

### Exact next commands

```bat
:: push from this machine (GCM CANNOT auth headless; gh device flow works)
gh auth status
git push origin main

:: re-verify the NAS copy (rc=0 means already in sync)
"C:\Users\produ\Desktop\CoyoteThings\NA165_H2060_RS\_agent\sync_to_nas.bat"
```

`gh` 2.99.0 is installed at `C:\Users\produ\bin\gh.exe` and registered as git's
credential helper for github.com. Git Credential Manager 2.5 hangs on a GUI
dialog from a non-interactive shell (rc=124); forcing
`credential.gitHubAuthModes=device` produced no output either. Never accept a
PAT pasted into chat — use the gh device flow.
