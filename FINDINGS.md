# FINDINGS — consolidated running log

One entry per established fact, WITH how it was discovered. Refuted
hypotheses stay, marked SUPERSEDED. This is the RAW log: grep it, never read
it through (`grep -n '^## ' FINDINGS.md` lists every entry).

HOW THIS FILE IS ORGANISED (2026-09-05):
- New entries are dated sections appended at the END:
  `## [TAG] YYYY-MM-DD - <claim in one line>`, tags `[NA165]`, `[NA168]`,
  `[ON2026]`, `[CESIUM]`, `[ORIENTATION]`, `[HARNESS]`, `[RECON]`, ...
- The topical sections in the middle ("RealityScan 2.2 CLI behavior",
  "Merge & component growth", ...) are the July 2026 consolidation and are
  frozen; the 2026-08 entries near the top were prepended under the older
  convention. Nothing is reordered - line citations in other documents
  point here.
- RECONCILED WITH `docs/rs-reference/` ON 2026-09-05: every RealityScan
  BEHAVIOUR established here up to 2026-09-03 is distilled into the manual
  (per-file "Addenda" sections, plus in-place corrections of superseded
  claims). Campaign-specific facts (which dive, which clock, which zone)
  and harness-internal findings stay here only. When a new entry states
  RealityScan behaviour, add it to the matching rs-reference file in the
  same session.

CONSOLIDATION NOTE (2026-07-24, extended 2026-08-07): this file merges
THREE research lines:

- **[H2023]** — NA156 H2023 production line (this machine): settings
  evaluation, camera registry, zone aligns, within-zone growth,
  hardening cells U1–U20. Deep docs: `docs/settings-evaluation-2026-07.md`,
  `docs/merge-growth-strategy-2026-07.md`, `testing/ALIGN_MERGE_HARDENING_PLAN.md`.
- **[NA167 #n]** — NA167 H2075 merge-strategy matrix (Honeybadger box):
  strategies A/B/C, D-cell merge-mechanism isolation, findings #1–31.
  Deep docs: `testing/FINDINGS.md` (frozen numbered log, do not append),
  `testing/MERGE_STRATEGY_REPORT.md`, `testing/MERGE_TEST_PLAN.md`,
  `testing/NA167_SESSION_NOTES.md`.
- **[ON2026]** — ON2026 RH0042/RH0043 Voyis stereo line (2026-08-04/07):
  attaching to a GUI-launched instance, the model-to-final half, and the
  nav/orientation groundwork for a re-run. Deep docs:
  `testing/NA167_SESSION_NOTES.md` §3 (operation ids, error codes, exit
  codes). Cross-line: this line's priors are COLMAP-derived and its
  accuracy matrix lives in the external `colmap_studio` fact base
  (cells C-20260730-05/09, C-20260803-01), which upstream code already
  cites — read it before proposing any orientation cell here.

Entries below carry their source tag. Cross-line reconciliations are
tagged **[RECON]** (dated 2026-07-24 for the three-line consolidation,
2026-09-03 for the main / remove-xmp-sidecars merge). `testing/FINDINGS.md` is
frozen as the NA167 raw log; all new findings go HERE.

## [RECON] 2026-09-03 - prior-groups claim: main and remove-xmp-sidecars disagree

Two entries in this section make opposite claims about
`-setPriorCalibrationGroup` / `-setPriorLensGroup` issued from the delegated
CLI. The 2026-09-03 reconciliation of `origin/main` (063add6) with
`origin/remove-xmp-sidecars` (71d6030) keeps BOTH verbatim and settles
nothing:

- **main, [ON2026] 2026-08-08 "calibration-CLI probe results"**: both
  commands are silently NON-FUNCTIONAL from the delegated CLI. Every
  delegated invocation returned success, but after `-align` the exported
  cameras showed `CalibrationGroup="-1"` and six DISTINCT solved focals on
  the 6-image fixture, under both `-selectImage` forms (full-path + union,
  and regex). The solved-focal-equality oracle proved it; exit codes and the
  errors channel said nothing. Restated 2026-08-12 (member of the
  silently-broken delegated-command class) and 2026-08-28 ([MAGIC] run3
  fixture gate: delivered per-eye groups survive on NO channel).
  `docs/PRODUCT_READINESS.md` DONE 2026-08-09 repeats it.
- **remove-xmp-sidecars, [NA168] 2026-08-14 "XMP sidecars are NOT the only
  way to group cameras"**: the same two commands set exactly the groups the
  sidecar carried, against `-selectImage <regexp>`; implemented in
  `modules/prior_groups.py`, delivered to `AlignZone.bat` as a command file
  through `RS_PRIOR_GROUPS_FILE`, recorded as "NOT yet verified against a
  live instance". NA168 H2080 and NA165 H2063 (2026-08-31, bottom of this
  file) were then aligned with that step in the workflow, and no entry on
  that side measures whether the groups took effect (no group echo, no
  solved-focal census). The SUPERSEDED marker on the 2026-07-23 "ONLY way"
  bullet under "Alignment behavior & settings" rests on this claim.

Neither side refutes the other's measurement: main measured the EFFECT on
the fixture; the sidecars side measured only that the commands ran. Merged
state (owner rules 2026-09-03, R1/R3): both mechanisms stay in code.
`AlignZone.bat` runs the XMP identity harvest by DEFAULT (main) and the
non-destructive `-exportLatestComponents` + `-exportRegistration` capture
when `RS_LEGACY_XMP_IDENTITY=0` (`=1`, the sidecars branch's spelling, is
the same as unset); the every-exit-path `ensure_calibration_sidecars`
repair in `realityscan_interface.py` follows the same switch; the
prior-group command file is generated and applied on EVERY align regardless
(additive, and its effect cannot be read from an exit code).

DECISION D1, OPEN (owner): re-run the solved-focal-equality probe on the
smoke fixture with the `RS_PRIOR_GROUPS_FILE` delivery and no sidecars in
the tree. Identical solved focals within each family and a group echo other
than "-1" in the exported cameras settles it for the sidecars side (then the
CSV capture can become the default and hard rule 0 holds without exception);
six distinct focals confirms main (then `prior_groups.py` is a no-op to be
retired and the 2026-08-14 SUPERSEDED marker is itself superseded). Until
then main's align-identity default stands. [RECON] (2026-09-03)

## Frozen entries (2026-07-21 .. 2026-09-03)

Every entry dated before 2026-09-05 lives verbatim in
`docs/history/FINDINGS_2026-07_to_2026-09-03.md` (moved 2026-09-06, D15).
Cite them as `FINDINGS <date>` exactly as before; the rs-reference Addenda
of 2026-09-05 carry their RealityScan facts.

## [HARNESS] 2026-09-05 - agent-native consolidation: what the audit measured

Fresh clone of `main` (`eb3ac8a`) on a macOS box with a Python 3.14 venv
built from `requirements.txt`. Suite there: 713 passed, 22 failed, 4 skipped
in 24 s; every failure is platform-bound (11 alignment tests need the
RealityScan install tree; 11 basename-matching tests push `M:\` paths through
POSIX `os.path`). The Windows expectation is unchanged (fully green).

- **The unit suite wrote `rs_settings.json` into the repo root** (section
  `main`: `b_overlap_percent`, `g_*` accuracies), via `main.parse_arguments`
  under a `SettingsStore()` with the default path. Found by `ls` after one
  run. CLOSED: `testing/conftest.py` points every store at `tmp_path` (module
  attribute + the new `RS_SETTINGS_PATH` env for child processes), scrubs
  `RS_*` from the test environment, and fails the session if the root file
  reappears. ESTABLISHED.
- **Three paths bypassed `RS_NO_SETTINGS_INHERITANCE`**, so a chartered run
  could still inherit another campaign's answers: `main.parse_arguments`
  (`settings.get('main', ...)` then a silent EOF fallback to the stored
  value), `BatchDirectory._stored_default` (`settings.get('batch', ...)`),
  and `geoall.py`'s code defaults, which were one machine's `Z:\` trees and
  count as legitimate fallbacks under refusal. Found by reading every
  `SettingsStore` call site. CLOSED: `default_for()` is the one resolution
  path, `unattended()` (RS_NO_INTERACTIVE or RS_RUN_CHARTER) never calls
  `input()` and announces every value it takes, `geoall` defaults are None
  and the missing flags are named. `testing/test_unattended_prompts.py`.
- **`main.py` did not honour its own epilog** ("RS_NO_INTERACTIVE = never
  prompt; missing required values fail fast"): it still called `input()`
  and took the stored answer on EOF. CLOSED (exit 2 naming the flag).
- **`decimator.py` had no argument parser and an `input()` loop that spins
  forever on an EOF stdin**; `timestamp_rename.py` had no EOF guard. CLOSED
  (`--yes` is the only unattended path that proceeds).
- **`modules.preflight` caught a real gap on its first run**: for the stage
  set georeference+batch+align the batcher's `--b_input` is required (the
  in-process hand-off exists only from Extract or Preprocess) and
  `run_plan --validate` cannot see it (argparse treats every flag as
  optional; the module refuses at run time). Preflight derives required
  answers from the modules' own Parameter declarations, so this class of gap
  is now a question before launch. ESTABLISHED.
- **`test_rig_mounts.py` leaves `logging.disable(CRITICAL)` armed** for the
  rest of the session; any later test relying on `caplog` alone sees
  nothing. Worked around in the new tests (`logging.disable(NOTSET)` in a
  fixture); the leak itself is unchanged. OPEN (trivial fix, not this pass).
- `archive/colmap/vocabtrainer_shipwrecks.py` does not compile (`try` without
  `except`, line ~710) and never did on `main`. Archived code; left as is.
- `wildscan/session.py` still carried its own `IMAGE_EXTS` without `.heif`
  after `modules/image_exts.py` was created to end exactly that duplication.
  CLOSED in `modules/run_plan.py` (ONE inventory).
- The planner moved: `wildscan/session.py` + `wildscan/plan.py` ->
  `modules/run_plan.py`; the TUI is archived FUNCTIONAL under
  `archive/wildscan_tui/` (owner: keep the UI, break it off). New
  `rs.py` (charter | preflight | plan | run | launch | status | verify);
  `rs run` refuses RealityScan stages from a `CLAUDECODE` shell (mandate 6
  made mechanical) and `rs launch` writes the CRLF launcher pair and PRINTS
  the `schtasks` commands rather than running them (the ask-gate must fire).
- Instruction-layer sizes after the pass: `CLAUDE.md` 11.9 KB -> 6.7 KB
  (200 -> 128 lines), `HANDOFF.md` 91.6 KB -> the two current sections
  (older sections verbatim in `docs/history/HANDOFF_2026-07_to_2026-09.md`).

## [HARNESS] 2026-09-05 - first Windows run of the consolidated suite: 810/812, both failures Windows-only test defects

The consolidation branch (`claude/agent-native-consolidation`, macOS box) shipped
with "Windows expectation: fully green (NOT run here)". First run on the
Honeybadger box (`jonat`, Python 3.13.5 at
`C:\Users\jonat\AppData\Local\Programs\Python\Python313`, `py` launcher present,
RealityScan 2.2 installed): **810 passed, 1 failed, 1 skipped in 28 s**, then
a HYGIENE FAILURE at session end. Neither is a pipeline defect:

- `testing/test_rs_cli.py::test_launch_never_calls_schtasks` replaced
  `subprocess.run` with a lambda returning `None`. `modules/preflight.py`'s
  hook-interpreter check (`check_hook_interpreter`) runs `python -c "import
  modules.run_charter"` wherever `python` is on PATH - it is on Windows and
  was not on the macOS box, which is why the test passed there. The fake then
  broke `.returncode`. A second latent defect in the same test: replacing
  `subprocess.Popen` with a lambda makes the first import of
  `asyncio.windows_utils` (which subclasses `subprocess.Popen` at import time)
  fail with `TypeError: function() argument 'code' must be code`. FIX: the
  run fake returns a `CompletedProcess`, the Popen spy is a class that
  raises, and the assertion is what the test means - no argv naming
  `schtasks`/`wscript`, no spawn.
- `testing/conftest.py` failed the session on the mere EXISTENCE of a
  repo-root `rs_settings.json`. The owner's interactive store sits there on
  every box that has run the interactive lane (gitignored). FIX: the check
  records (size, mtime) at session start and fails only when the suite
  created or modified the file.

After both fixes and the D13 change below: **840 passed, 1 skipped in 30 s**.
[VERIFIED: two runs, 2026-09-05] The `M:\` basename and alignment tests the
macOS box could not run pass here.

## [TEXTURE] 2026-09-05 - decision D13 applied: AdaptiveTexelSize 4096 in every workflow, MaxTexturesCount presets retired, JPG exports, preflight-enforced

Owner instruction (chat, 2026-09-05): *"This needs to be changed globally to
'adaptive texture size' never 16 or enforced 4x8k during unwrap. Crucial
textures generates jpgs not pngs."* Applied on branch `agent-native-execution`
(worktree `recon-tmp`); nothing was run against RealityScan - every claim
below is by inspection and unit test, and the first modelled component on the
NA173 test dataset is the live verification.

What changed, and where the old value went:

| Site | Before | After |
|---|---|---|
| `GenerateModel.bat` [6/8] `-calculateTexture` | `Texturing_MaxTextureCount4_8k.xml` (4 x 8192) | `Texturing_AdaptiveTexel_4k.xml` (AdaptiveTexelSize, <= 4096) |
| `GenerateModel.bat` [8/8] `-unwrap` | `Unwrapping_Simplified_4x8k.xml` | `:try_unwrap`: `Unwrapping_AdaptiveTexel_4k.xml`, on a reported error the errors file becomes `expected_unwrap_adaptive_<inst>_<tag>.txt` and `Unwrapping_MaxCount4_4k.xml` runs through `:run` |
| `ModelToFinal.bat` %4 default / table | `4x8k`; `highpoly|8k|4x8k|16k|fixed100|fixed50` | `adaptive`; `adaptive|fixed100|fixed50` |
| `ModelToFinal.bat` final unwrap | `Unwrapping_Simplified.xml` (1 x 16384) for every preset but `4x8k` | always `Unwrapping_AdaptiveTexel_4k.xml`; `:try_unwrap` judges the attach-lane result by `-getStatus` `rev` (moved = took), falls back to 4 x 4096, aborts if both leave `rev` unchanged |
| `AlignImagesFromFolder.bat` (deprecated) | `Texturing_HighPolyTexture.xml` (2 x 16K), `Unwrapping_Simplified.xml` | the adaptive pair |
| `SetVariables.bat` | `Texturing1x8k`, `Texturing4x8k`, `Texturing1x16k` | `TexturingAdaptive4k`, `UnwrappingAdaptive4k`, `UnwrappingMaxCount4x4k` |
| `Texturing_FixedTexelSize{100,50}perQuality.xml` | `unwrapMaxTexResolution=8192` | `4096` |
| 9 `MaxTexturesCount` presets (`Texturing_MaxTextureCount{1,4}_{8k,16k}`, `HighPolyTexture`, `SimplifiedTexture`, `Unwrapping_Simplified{,_4x8k,_4x16k}`) | `RS_CLI/Metadata/` | `archive/metadata_retired/` with a README; nothing live names them |
| `ModelExportParams{OBJ_NiraParts,FBX_Parts,FBX_U1V1,FBX_U1V1_material,FBX_UV,FBX_UDIM,FBX_UDIM_material}.xml` | `MvsMeshExportTexImgFormat_*=png`, FBX pixel format `32bppBGRA` | `jpg`, `24bppBGR` (JPG has no alpha channel; `MvsMeshExportTexAlpha` was already false). `Obj`, `Obj_Metric`, `GLB` were jpg/jpeg already; PLY has no textures |
| `finish_model.py` | `TEXTURE_PRESETS` six names, default `4x8k` | `('adaptive', 'fixed100', 'fixed50')`, default `adaptive` |
| `modules/preflight.py` | model presets = the 4x8k pair | the adaptive pair + fallback; NEW BLOCKS: any live `Texturing_*`/`Unwrapping_*` preset with `unwrapMaxTexResolution` > 4096, any `ModelExportParams*` texture format that is not jpg/jpeg |

Pinned by `testing/test_texture_policy.py` (25 tests: cap, style, retired set,
no live reference, script contents, CRLF, JPG, preflight blocks). Docs of
record updated: rs-reference 02, 03, 09 (registry rows, unwrap example, the
A4 audit box), 10 (sec.9.2 live table, the [8/8] recipe line, export trees,
sec.13.6 table, A4), ARCHITECTURE, DECISIONS D13, archive README.

Two things this does NOT settle, stated so nobody credits them:

1. **Bake quality of the high-poly at adaptive 4K vs the old 4 x 8K is
   unmeasured.** FINDINGS 2026-09-03 noted the 4 x 8K high-poly source was
   "better for bake quality than the 4K it was asked to become". The owner
   chose adaptive globally; the first NA173 component is the A/B against
   H2060's look, and `run_decimate.py`'s texture census (`Textured`, texture
   count, page size) is the oracle.
2. **The `:try_unwrap` fallback in `GenerateModel.bat` sees only the errors
   channel.** An adaptive unwrap that neither errors nor mutates the scene
   (the c5 case DID set `0x83000003`, so the errors file should carry it) is
   invisible to the .bat; the model report (`-exportReport` /
   `run_decimate.info`) is the only proof of "Textured". The export census
   still counts files, not textures - D10 territory.

`unwrapMinTexelSize=0` / `unwrapMaxTexelSize=4` in the adaptive presets remain
the OPEN enum-vs-float question (rs-reference 03 OPEN 17, 10 OPEN 27); the
presets have produced the verified 4096-page H2060 exports as written.

## [HARNESS] 2026-09-06 - review workflow over the reconciled tree: 78 findings, 33 fixed, what stands

A seven-lens review workflow (rs-reference hygiene, in-line docs, agent-lane
correctness, hooks/Windows boundary, adversarial review of the D13 commit,
test triage, an NA173 integration probe) ran over `recon-tmp` at `eca8aba`,
then two adversarial verifiers per must/should finding. The owner's usage
limit cut the verification short: 18 findings confirmed, 4 contested, 31
must/should left unverified, 25 nits. Every unverified must/should was then
verified by hand (reading the code, running the hooks with synthetic stdin,
`rs.py` against scratch charters) before being fixed or dismissed. Suite
after the fixes: 879 passed, 1 skipped.

Defects that would have bitten the first NA173 run (all fixed, each pinned
in `testing/test_review_fixes.py`):

- **`science.align_settings_xml` never reached the run.** Preflight validated
  the file and reported ok; `RunCharter.env()` exported no `RS_ALIGN_PARAMS`,
  so `AlignZone.bat` applied the canonical XML while the signed charter said
  otherwise. Now exported; the D3 hardness A/B (cell C4) depends on it.
- **`rs run/launch --stages` preflighted the charter's FULL stage list**, so
  the READY verdict described a different run than the one executed; the
  drive-run split (`run` batch, `launch` align) could not pass. Preflight now
  judges the subset.
- **A charter answer colliding with a pinned flag was emitted twice**;
  argparse kept the last, so `r_model_generate: true` was silently forced
  false and an `output_dir` answer redirected the run. Now refused by name.
- **`check_frame` compared utm-vs-local only**: `utm:54N` against
  `flight_log_57L_UTM.txt` was READY. Zone and band are compared now.
- **`b_zone_layout=pool` never set `RS_ALIGN_POOL_DIR`** on the charter lane
  (only the archived campaign drivers did), so every pool zone would have been
  skipped as "no images found" - the 2026-08-09 union-wave failure again.
- **`ModelToFinal.bat`'s new `:try_unwrap` (D13) left the adaptive failure's
  own `errors_<inst>.txt` in place** on a pipeline-booted instance, so the
  `-reprojectTexture` after the fallback would have aborted on the stale
  marker. The fallback now moves the marker to
  `expected_unwrap_adaptive_<inst>_<name>.txt` and runs through `:run`.
- **The printed `schtasks` line could not be run from either agent tool**:
  Git Bash turns `/Create` into `C:/Program Files/Git/Create`, PowerShell
  does not honour `\"`. `rs launch` prints one form per shell (cmd.exe,
  PowerShell, Git Bash with doubled slashes).
- **`python rs.py run --foreground` was allow-listed and ungated** from an
  agent shell - RealityScan under the harness job object with no ask. Refused
  while `CLAUDECODE` is set; the owner runs it from their own terminal.
- JSON `null` answers reached `main.py` as the token `None`;
  `science.min_component_size` was decorative (now `--r_min_component_size`
  and merge `--min_size`); a stage that never started left RUN_STATE
  `running` forever (now `failed` with the error); a direct `rs run` reported
  an earlier launch's `.rc`/task beside its own state; the launcher pair was
  written UTF-8 (cmd reads OEM: an accented path silently does not exist -
  non-ASCII is refused) and could record a relative path; the free-disk
  check ignored the CACHE volume (the one that filled the box); the template
  charter did not parse as scaffolded and its placeholder `protected` entry
  counted as an answer; an unknown camera prefix could never be answered
  (charter `cam_<prefix>_*` records now count); `rs status` claimed to
  compare the budget and did not (it prints expected vs elapsed hours and
  free disk on both volumes now, and flags a `running` state whose pid is
  gone).
- Hooks: `guard_rs_launch` refused any heredoc line naming a workflow script
  and missed `&`-chained, `$(...)`, PATHEXT-resolved (`cmd /c AlignZone`) and
  extension-less (`Start-Process '...\RealityScan'`) launches;
  `guard_charter_writes` stopped a quoted target at its first space, so a
  results root with a space was "outside every writable root";
  `guard_schtasks` ignored `/Change ... /TR`. All three fixed with liveness
  tests.

Corrected in the documentation of record (rs-reference 01/02/03/04/05/06/09/
10/11/12/13/README, CLAUDE.md, README, skills, rules, PRODUCT_READINESS):
retired presets still listed as production or as `AlignImagesFromFolder`'s;
`DecimateComponent.bat` (never existed - it is `run_decimate.py`); six
`-importFlightLog` call sites where two are archived; the `:run` "twelve
scripts" inventory; `-getStatus` "never parsed" (ModelToFinal parses `rev` /
`lastError`); the missing `:try_unwrap` row in 11 sec.2.3 and the missing
F-102/F-103 rows in the README's silent-failure table; `Obj_Metric` absent
from 10 sec.13.6 and the 09 registry; the 13 sec.10.3 sentence that still
put 45 deg on Cinema; `sensorsdb.xml` "at the repo root"; hard rule 0 stated
as an absolute the default path breaks; `/charter` and `/drive-run` are
owner-invoked, which the routing hook now says; `WORKFLOW_WALKTHROUGH.md`
moved to `docs/history/` (its D7 collided with DECISIONS D7).

Left standing, on purpose: the routing hook's phrasing (tune on real
prompts); `RS_RUN_CHARTER` set-but-unusable blocking read-only commands
(fail-closed is the safer default; the message names the fix);
`decimator.py`'s EOF-only gates; `testing/test_preprocess_module.py` holds no
tests (a manual staging script under a test name); `test_rig_mounts.py`'s
`logging.disable` leak. Not measured by anything here: every claim about a
live RealityScan run - the cells in `testing/NA173_TEST_PLAN.md`.

## [TEXTURE] 2026-09-06 - correction to 2026-09-05: lastError clears when the next operation starts; the ModelToFinal fallback runs through :run

The 2026-09-05 rationale for `ModelToFinal.bat`'s fallback bypassing `:run`
("lastError is sticky and would misattribute the adaptive failure to the
fallback") is SUPERSEDED. FINDINGS 2026-08-04 and 2026-08-07 (both
ESTABLISHED) already held the measurement: `lastError` is sticky only while
the instance is IDLE and clears the instant the next operation starts; the
C5 sticky code did NOT false-abort the 4b battery. The review's D13 lens
caught the contradiction. Consequence: the fallback is now `call :run
-unwrap "%UnwrapFallback%" || exit /b 1` (all three gates), preceded on the
pipeline's own instance by the errors-marker move, with the `rev` comparison
kept as the "did it take" oracle. [VERIFIED-by-inspection against the two
ESTABLISHED entries; the fallback path itself is still unexercised live -
cell C8]

## [NA173] 2026-09-06 - the H2014g test dataset as the tools see it

Read-only census, 2026-09-05/06, by the integration probe and by hand:

- 3,154 JPGs (camlower 920, cammid 1,018, zeuss 1,216; 3840x2160; no EXIF)
  and 3,154 log rows, 0 disk-only, 0 log-only. Every family recognised
  (`camera_registry.family`, `run_plan.scan_cameras`): the HERC frames
  (`20250709T200515Z_0001_HERC_H.264_H2104_NA173_prob4_frame0.jpg`) match
  the delimiter-bounded `herc` token; preflight asks nothing about cameras.
- `flight_log_57L_UTM.txt` -> zone (57, 'L') -> `EPSG:32757` (southern
  hemisphere, correct); 13 columns, no `FocalLength`; the pinned
  `FlightLogParams.xml` names the 14-column `{D1F2A3B4}`. What the import
  does with a row one column short is UNMEASURED (cell C0); preflight warns.
- The log's pitch columns already carry the PRE-D3 Zeuss mount (30 deg,
  accuracy 15) and there is no raw ROV nav table, so the georeference stage
  cannot run here and D3's mount half cannot be replicated by changing
  `cameras.json` - only by a derived log (cell C5). The hardness half
  (`sfmCameraPriorWeightOrientation` 2.0 vs 10.0) is testable as-is (C4).
- Each camera folder holds an `rsmeta.db` (RealityScan wrote into this tree
  in an earlier GUI session); the batcher's index sees them as its only two
  basename collisions and ignores them.
- The folder says `H2014g`; every zeuss frame says `H2104`. Nothing in the
  pipeline reads the label; the owner confirms the dive before publishing.
- With the batcher defaults the dataset splits into TWO zones of ~1,577
  (initial_k = max(2, ...)), so the copy-layout merge path runs; `b_min_zone`
  is an owner answer.
- A probe charter (batch + align, `b_input` = the dataset root,
  `b_flight_log_path` = the log, frame `utm:57L`, copy layout) was READY with
  no missing line and planned ONE `main.py` command; the full-stage variant
  planned four. [VERIFIED: `scratchpad/agents/na173-probe/` outputs,
  2026-09-05 - a scratch charter signed "probe", never a real sign-off]

## [NA173] 2026-09-06 - D1 end-to-end CSV identity run on fixture F2: zones, merge, zero XMP beside images

Scheduler-owned run (`rs launch` -> Task Scheduler, task RS_NA173_F2_CSV,
instance RSAGENT, cache `_agent/rs_cache`, charter
`NA173_H2014g_RS/_agent/RUN_CHARTER.json` with `science.identity_capture =
csv` -> `RS_LEGACY_XMP_IDENTITY=0`), fixture F2 (363 images = 121 per
camera, 20:17:36-20:19:36, copy layout, b_target 180 / b_min 100 / b_max
250, min component 50, ladder merge_first / neighbour / overlap gate / loss
0.0025). Batch + 2 aligns + merge: 12:55:54 -> 13:05:09, launcher exit 0,
`RUN_STATE` prepared -> running -> done, `.rc` = 0. Evidence under
`NA173_H2014g_RS/` (results) and `_agent/logs/rs_logs/` (RealityScan's own
logs, copied). [VERIFIED: this run]

- **XMP census.** 0 `*.xmp` under the source dataset, 0 under either zone's
  image tree, 0 under `aligned_components/`. 316 under
  `merged/cluster_0/attempt_1_merge_georef/identity_r{0,1,2}/` (158 + 80 + 78,
  ordinal `00000.xmp`...): the merge peel census
  (`-exportXMPForSelectedComponent`, MergeZoneComponents.bat) is the ONE
  remaining XMP writer, and it writes into the merge's own attempt folder,
  never beside an image. The owner's "downstream effects" case (sidecars
  beside images changing the next align) does not arise. [VERIFIED: `find`]
- **Align census.** zone_1: 229 in (camlower 78, cammid 78, zeuss 73) ->
  RealityScan `Count = 1` component, 78 cameras, ALL cammid; 132 s. zone_2:
  200 in (65/64/71) -> `Count = 4`, largest 80 = 64 cammid + 16 camlower;
  70 s. Registration 34 % / 40 %: camlower and zeuss did not join the cammid
  strip (unique orientations; zeuss carries the pre-D3 30/15 mount in the
  log). A science result for the owner, not a lane fault: every component the
  lane promised exists with a manifest and an identity CSV. [VERIFIED:
  manifests, RealityScan `65537` ALIGN records]
- **Identity CSVs** (`aligned_components/<zone>/identity/<zone>_c0.csv`):
  `#cameras N` header, then `name,x,y,z,yaw,pitch,roll,focal,k1,k2` per
  camera - 78 and 80 rows, matching the manifests exactly. x/y/z came out in
  the range -1..8 m on a scene pinned to EPSG:32757 with the trajectory
  imported: the export CRS is the instance's current "Coordinate system"
  choice (rs-reference 13 sec.8 frame #8; only `calexFileFormatId` is pinned,
  the `calexTrans` bundle is not), so the CSV positions are NOT a scale or
  georeference readback yet. [VERIFIED: the CSVs; frame [OPEN]] [SUPERSEDED
  2026-09-06, same day, for the SCALE half: the oracle is rigid-invariant, so
  the model-frame x/y/z ARE a scale readback - `[HARNESS]` scale oracle entry
  below. Not a georeference readback: that half stands]
- **Merge.** `merge_report.json` schema 2: cluster_0 = zone_1_c0 + zone_2_c0
  -> ONE final component, 158 cameras, attribution exact, cameras_lost 0,
  converged, 116 s, `EVALUATION_READY`. 158 = 78 + 80 because the copy
  layout holds the 21 overlap images twice (137 unique registered images;
  `unique_images` 365 counts log rows). **Scale: UNMEASURED for both inputs**
  - the scale oracle reads `identity_r0/*.xmp` poses, which the CSV lane does
  not write; the gate passed vacuously. [VERIFIED: report] [SUPERSEDED
  2026-09-06, same day: the oracle now reads the identity CSVs too; F2 stays
  unmeasured because the ROV moved under 3 m - see the `[HARNESS]` scale
  oracle entry below]
- **`rs verify`** first returned BLOCKED: "navigation flight log DIFFERS
  across aligned zones". False - the batcher cuts every zone its own log.
  Fixed (`591a30f`): the batch fingerprint records each zone log's sha and
  verify collapses vouched-for logs to the source sha; verdict now OK.
- **Flight-log format (cell C0, answered).** The saved `zone_1.rsproj` /
  `zone_2.rsproj` carry `absPrior="pose"` on all 229 / 200 inputs with
  `absuX/Y/Z = 10/10/1` and `absuRX/RY/RZ = 15/15/15` - the log's own
  accuracy columns. The 13-column log imported ALL 13 columns under the
  14-column `{D1F2A3B4}` format; a row one column short of `FocalLength`
  is fine. [VERIFIED: the documented .rsproj oracle, rs-reference 06 sec.2.3]
- **RealityScan's own log is a zip.** `%LOCALAPPDATA%/Temp/CRTemp/{guid}/
  YY_MM_DD[_n].log` is a PK archive of one `log_HH_MM_SS.json` (`Metadata`,
  `Events[]` of `EventId`/`Type`/`Data`). The `65537` ALIGN record carries the
  effective align settings and `align_largest_component_camera_count`; the
  `20598 IMPORT_FLIGHT_LOG` record carries `file_format`, `camera_mount`,
  `euler_angle_order`. In BOTH zone imports `file_format` read
  `B438A61724245A24C1B758920F28345A` = the hand-edited variant
  `{B438A617-2424-5A24-C1B7-58920F28345A}` (rs-reference 06 sec.2.3), which
  is in NO flightlogs.xml on this box, while the params named `{D1F2A3B4}`
  and the .rsproj proves `{D1F2A3B4}` resolved. So the telemetry field is
  NOT the format that parsed - most likely the instance's stored default.
  [VERIFIED: both records; interpretation [INFERRED]]
- **The installed `flightlogs.xml` is not the repo's.** The install's
  `{B438A617}` is a 14-column "Rig local ... FocalLength" block plus three
  sibling rig-local formats (`{6F1B2A84}`, `{A7D4E9C2}`, `{3C92F5B7}`) the
  repo file does not carry; the repo's `{B438A617}` is 13 columns.
  `flightlog_format.install_all_managed` only ADDS missing ids, so the drift
  persists. Harmless today (both 14-column parsers are identical) and a
  portability trap for the NA165 box. [VERIFIED: diff of the two files]
- **Cost.** 363 images, three RealityScan boots: 10 min wall; align peak
  32.7 GB commit / 98 % CPU on 32 threads; cache +0.8 GB. [VERIFIED:
  `resources_AlignZone_*.csv`]

## [RECON] 2026-09-06 - D1 arm (i): prior groups alone leave every camera with its own focal

The F2 run applied `-setPriorCalibrationGroup` / `-setPriorLensGroup` per
family (`logs/prior_groups_zone_*.cmds`, "Applying calibration/lens prior
groups" in the AlignZone output) with NO calibration sidecars beside the
images (`RS_LEGACY_XMP_IDENTITY=0` also skips the sidecar repair). Readback
from the identity CSVs: zone_1 cammid 78 cameras, 78 DISTINCT focals
(2653.3-2665.4 px, spread 12.1); zone_2 cammid 64 distinct (spread 37.9),
camlower 16 distinct (spread 23.1); k1 spreads 0.004-0.03; k2 pinned at 0.
A calibration group shares one focal across its members, so either the
group commands did not take effect from the delegated CLI (main's 2026-08-08
measurement) or each image was solved on its own calibration regardless.
This is C6 arm (i) of `testing/NA173_TEST_PLAN.md`; arm (ii) (the same
fixture with XMP calibration sidecars = known-good) and arm (iii) (neither)
are still to run before the decision rule fires. [MEASURED: the CSVs; the
"did not take effect" reading is [INFERRED] until arm (ii) shows equality]

## [HARNESS] 2026-09-06 - first scheduler-owned run: what the lane got wrong and what it cannot see

- `rs launch --stages batch,align,merge` was refused ("unsafe for cmd") -
  the comma is in the cmd metacharacter set and the stage list went through
  the path check. Fixed `eaa2bb4` (stage grammar check). ESTABLISHED.
- `rs launch` computes the task's start time as launch time + 2 min; the
  printed lines were run two hours later (usage-limit pause) and the
  scheduler warned that the start time was already past - the explicit run
  line is what starts the task, so this is a warning to expect, not a
  failure. ESTABLISHED.
- The scheduler guard hook also fires on the literal create-switch text
  inside a heredoc that only writes a memory or findings file. Keep that
  string out of scripts; append long text through a file.
- `rs verify` blocked a healthy copy-layout run on per-zone flight logs
  (above; fixed `591a30f`). The oracle had never seen a real copy layout.
- [SUPERSEDED same day - ported, see the scale oracle entry below] The scale
  oracle is BLIND under the CSV lane (no `identity_r0` poses);
  `merge_zones --scale_gate true` passes with `unmeasured`. Until the CSV
  positions are exported in the output CRS (pin the `calexTrans` bundle, or
  a GUI-saved Export Registration params - rs-reference 05 Q20) the CSV lane
  has no metric-scale check. OPEN, ranked for the owner.
- preflight's "13 columns vs 14-column format" warning reads the canonical
  `FlightLogParams.xml`, not the charter's `r_flight_log_params` answer.
- RealityScan's logs are ephemeral zips under CRTemp (above); the agent copies
  them into `_agent/logs/rs_logs/` after every run from now on.
- The Monitor loop on `RUN_STATE.json` + the errors marker + the launcher
  `.rc` file saw every transition (prepared -> running -> done, `.rc`
  written 13:05:09); no `/loop` was needed.

## [NA173] 2026-09-06 - C0 probe: `gpsLogFileFormat` IS honoured; RealityScan's event-log `file_format` never changes

Second scheduler-owned run (charter `NA173_C0probe_RS/_agent/RUN_CHARTER.json`,
fixture F0 = 41 cammid frames 20:18:20-20:19:00, copy layout, two zones of 13
and 32, `identity_capture: csv`, min component 10), identical to the F2 run
except that `r_flight_log_params` pointed at a copy of `FlightLogParams.xml`
whose `gpsLogFileFormat` names the STOCK 7-column position + accuracy format
`{0E9850E2-73E1-4538-B2CF-B18BEF6CECEB}` (no orientation columns). 3 min
wall, two boots, exit 0, zero `*.xmp`. Evidence: `NA173_C0probe_RS/`,
RealityScan logs copied to `_agent/logs/rs_logs/`. [VERIFIED: this run]

- **The params GUID is honoured.** Both zone projects carry
  `absPrior="registered"` (position only) on every input, `absuX/Y/Z =
  10/10/1` from the log, `absuRX/RY/RZ = -1` and no `absRX/RY/RZ` at all -
  exactly the 7-column format's footprint - where the F2 run under
  `{D1F2A3B4}` had `absPrior="pose"` with the orientation accuracies. The
  `.rsproj` oracle (rs-reference 06 sec.2.3) now has its known-different
  case: pose + six accuracies vs registered + three. [VERIFIED: 13 + 32 inputs]
- **RealityScan's `20598` `file_format` did not move**: it read
  `B438A61724245A24C1B758920F28345A` again - the same hand-edited
  `{B438A617-2424-...}` variant as under `{D1F2A3B4}`, a GUID in no
  `flightlogs.xml` on this box. The field reports something stored in the
  instance (registry default from an earlier session), never the format
  the params selected. Never use it as a format oracle. ESTABLISHED.
- Registration under position-only priors: 13/13 and 32/32 cammid frames in
  one component each (`Count = 1`), 2.6 s and 9.0 s aligns. [VERIFIED]
- The first launch of this probe died in 30 s AFTER preflight said READY:
  the batcher's own `validate_parameters()` refuses `b_target_images < 100`
  at start-up, which the plan check (argparse only) cannot see. Preflight now
  runs the batcher's validator on the charter's answers when `b_input` and
  `b_flight_log_path` are answered and no zoning exists yet (it would
  otherwise reach the validator's stdin "Overwrite?" prompt);
  `testing/test_preflight.py`. Two `REFUSING stored default` lines
  (`main.b_overlap_percent`, `main.r_project_label`) appear in every
  charter-driven `main.py` log and are NOT failures: the store's own
  refusal of inherited defaults, printed while the declared default is
  installed instead. ESTABLISHED.

## [HARNESS] 2026-09-06 - scale oracle reads the CSV lane; merge attribution counts duplicates correctly (owner-relayed H2063 findings checked against this branch)

The owner relayed three findings from another session (H2063, NA165): (1) the
scale oracle is frame-invariant and only went dark under the CSV lane because
its input (`identity_r0` XMPs) stopped being produced; (2) the batcher copies
overlap images into both zones, RealityScan fuses by content; (3)
`merge_zones.attribute_result` summed input camera counts, so a fusion whose
duplicate copies RealityScan folded into one camera read as a loss of exactly
the duplicate count and was rejected as `ambiguous` (two byte-perfect H2063
cross-zone fusions thrown away). Checked in `agent-native-execution`:

- **`f972b6d` (export CRS set explicitly) IS in this branch.** [VERIFIED: git]
- **The scale oracle CSV port was NOT here** - `scale_for_images` and
  `report` read `identity_r0/*.xmp` only. Ported: `solved_positions()` takes
  the XMP harvest when it holds poses, else `identity/*.csv`;
  `component_members` treats each CSV as one component. The oracle IS
  frame-invariant (`scale_ratio` = median of solved/nav pairwise-distance
  ratios; `solved_position_cloud`'s own docstring: "the frame is the model
  frame, not UTM; irrelevant"), so the identity CSV's model-frame x/y/z is
  exactly the input it wants. **This SUPERSEDES the 2026-09-06 `[NA173]`
  entry's line "the CSV positions are NOT a scale or georeference readback
  yet" and the `[HARNESS]` line "until the CSV positions are exported in the
  output CRS ... the CSV lane has no metric-scale check"** - they are a scale
  readback; they are not a georeference readback. Known-good / known-bad in
  `testing/test_scale_gate.py` (synthetic zone: rotated + shifted model
  frame at 1.0 passes, at 0.236 fails; two CSVs = two components; an XMP
  harvest beside a CSV still wins). [VERIFIED: tests]
- **F2 itself stays UNMEASURED for a geometric reason, not a lane one**: the
  ported oracle matched 78/78 and 80/80 stems, but the ROV moved 0.4 x 0.4 x
  0.6 m (zone_1) and 0.9 x 1.8 x 1.9 m (zone_2) during the 120 s window, so
  NO nav pair exceeds the oracle's 3 m floor (`min_nav_distance`, there to
  keep nav noise out of the ratio) - 0 of 3,003 and 0 of 3,160 pairs. For
  information only, at a 1 m floor zone_2 reads 0.93 (IQR 0.73-1.09, 2,004
  pairs) [EST - below the floor, nav noise dominates]. A fixture that
  translates > 3 m is needed for a real F2 scale number; the full dive does.
- **RealityScan did NOT fold the duplicates on F2**: 78 + 80 with 21 shared
  basenames peeled as 158 (`peel_sizes [158, 80, 78]`, fused manifest
  `camera_count 158`, `images 137`). The H2063 numbers relayed by the owner
  show the opposite (400 + 360 with 4 shared peeled as 756 = the unique
  count). Both are lossless fusions; which condition decides whether
  RealityScan keeps both copies or one camera per unique image is OPEN
  (candidates: merge mode `merge_georef` vs an `align` rung, whether the
  duplicate pair sits in the shared-image graph, RealityScan build). The
  accounting no longer depends on it.
- **`attribute_result` rewritten**: a subset matches a peel count anywhere
  from its UNIQUE basename count up to its camera-count SUM (lossless;
  `collapsed` = copies folded); below the unique count the shortfall is the
  real `loss` and must fit `loss_tolerance`; manifests without an image list
  keep the old sum rule. The attempt record gains `duplicates_collapsed`, and
  `cameras_lost` no longer counts folded copies. Tests carry the owner's
  H2063 numbers (760/756/4 -> lossless; 743/541/202 -> lossless; 1488/1248
  peel 1240 -> loss 8, needs the budget; 1110 -> 1029 same-zone -> loss 81)
  and F2's 158. A lone 100-camera input beside a 100+20 pair sharing 20
  still reads `ambiguous` for a peel of 100 - two lossless readings, never
  silently one. [VERIFIED: `testing/test_merge_zones_rework.py`]
- NOT done here: re-running the H2063 merge (that workspace is on the NA165
  box) - the owner's step 3.

## [NA173] 2026-09-06 - audit of what the code set for the cameras in the F2 and C0 runs, and how they were grouped

Eight read-only agents (four readers, four skeptics re-deriving every claim
from the files; 158 claims, 146 confirmed, 12 corrected on line numbers or
wording, 0 refuted) over the code, the two workspaces and the reference.
The facts that were not already in the entries above:

- **Priors the code set explicitly, both runs.** Position, orientation and
  every accuracy came from the SUPPLIED log rows (X/Y/Alt, 10/10/1 m; yaw,
  pitch pre-composed with the OLD mounts 10/20/30 deg for camlower / cammid
  / zeuss, roll; 15/15/15 deg) - the georeference stage never ran. The code
  chose the params template (`{D1F2A3B4}` for F2, `{0E9850E2}` for C0),
  rewrote its two CRS entries to UTM 57 South, pinned the project and output
  CRS to EPSG:32757 (`absCs="1"` on every input is the on-disk proof),
  asserted the GUID is installed, and applied AlignmentParams.xml's 35 keys
  by `-set` BEFORE the import: `sfmEnableCameraPrior=true`,
  `sfmCameraPriorWeight=10.0`, `sfmCameraPriorWeightOrientation=2.0` (D3),
  `sfmCameraPriorAccuracyYaw/Pitch/Roll=10.0` (globals; the per-row 15 won,
  `ifuuInh=0`), `sfmDistortionModel=Division`,
  `sfmMergeGeoreferencedComponents=false`, `sfmForceComponentRematch=false`,
  position-accuracy globals 5/5/0.5 under the obfuscated keys. The merge set
  `sfmMergeGeoreferencedComponents=true` + `sfmEnableCameraPrior=true` and
  imported the union log with `{D1F2A3B4}` (its `rslog.txt` names the file).
  **No numeric calibration prior** (focal, k1..k4, principal point) reached
  RealityScan in either run: `RS_LEGACY_XMP_IDENTITY=0` skips the sidecar
  repair, `b_xmp_priors` is False, the log has no FocalLength column, and
  `camera_registry.calibration_xmp` never wrote k1..k4 for the rig cameras
  anyway. Each camera self-calibrated. [VERIFIED: AlignZone.bat, the
  interface, AlignmentParams.xml sha in `align_inputs.json`, the .rsproj]
- **Grouping, both runs: NOT grouped.** The group commands ran (cammid 2/2,
  camlower 3/3, zeuss|herc 1/1; C0 cammid 2/2 only; `logs/prior_groups_*.cmds`,
  "Applying calibration/lens prior groups" in every output log), and the
  readback is one focal per CAMERA everywhere: F2 78/78, 64/64, 16/16 distinct;
  C0 13/13, 32/32. New instrument: the merge peel's 316 XMPs carry
  `xcr:CalibrationGroup="-1"` and `xcr:DistortionGroup="-1"` on every file
  (113/70/53 distinct FocalLength35mm) - the group echo of the fused scene
  is "ungrouped". The saved .rsproj records no group; the identity CSV
  format has no group column. The 2026-08-08 fixture measured the same
  under BOTH `-selectImage` forms, so the regexp form is not the cause.
  Candidates left: the commands are inert from the delegated CLI, or the
  import's `ifKGrp=2` re-groups afterwards (rs-reference 13 A3 has the
  discriminating probe: `-exportReport` with the shipped
  ComponentAccuracyReport.html, whose `$(groupCount)` /
  `$(ungroupedInputCount)` echo grouping headless). [MEASURED]
- **C0 zone_2's calibration is degenerate**: 32 cammid cameras solved at
  focal 14,133-28,556 px with k1 -27..-7 on 3840 px images (zone_1's 13
  solved sanely at 2,858-2,884 px), under position-only priors. 32/32
  registered hid it; a focal sanity band per family belongs in the census.
  [MEASURED: `NA173_C0probe_RS/aligned_components/zone_2/identity/zone_2_c0.csv`]
- **The align fingerprint was blind to the prior-group file** - it records
  the log, the params, the settings XML, min component size, repo sha and
  the executable, not the `.cmds` that grouped (or failed to group) the
  cameras. Fixed the same day: `align_inputs.json` gains `prior_groups`
  (path, sha256, bytes; provenance only, not a retry-changing input).
- **Log hygiene**: the D1 merge and assembly RealityScan session logs had
  been copied only into the C0 probe's `rs_logs/`; copied to
  `NA173_H2014g_RS/_agent/logs/rs_logs/26_09_06_{6,7,8}.log` as well. The
  zone-session logs cap at 100 events (the C0 logs, 163-170 events, are the
  only complete align sessions on record).
- **Reference corrections**: 02 row for `-setPriorCalibrationGroup` said
  "never exercised through the CLI here" (it runs on every align); 07's
  table still listed the orientation hardness at 10.0 (2.0 since D3).

## [HARNESS] 2026-09-06 - pipeline variable audit: what is baked, detected, owner-supplied or inherited, and four carry-forward defects fixed

Sixteen read-only agents (eight stage-group readers, eight skeptics re-deriving
every claim from the files; ~620 claims, none refuted) over the code, the two
2026-09-06 runs and the reference. Written up as `docs/PIPELINE_VARIABLES.md`
(routed from CLAUDE.md): the required-owner-input table for any dataset, a
per-stage variable table (kind, value, file:line, whether it reaches the next
stage), the hand-off matrix, the XMP census, and fourteen ranked gaps. Facts
worth having outside that document:

- **The merge stage writes XMP under a `csv` charter, ungated.**
  `merge_zones.py:813-815` sets `RS_MERGE_HARVEST=1` for EVERY ladder attempt and
  `MergeZoneComponents.bat:218/:270/:275` runs `-exportXMPForSelectedComponent`
  plus a PowerShell move; neither file reads `RS_LEGACY_XMP_IDENTITY`, which was
  in the merge environment and ignored. RealityScan writes those sidecars BESIDE
  THE IMAGES first (rs-reference 05:1139-1140), so "zero XMP beside images" is the
  post-move state - a lap dying between export and move leaves them in the zone
  copies. The peel count is the merge's whole camera-accounting instrument and
  `run_models.resolve_scale` reads `identity_r0` for fused components, so a CSV
  port must change both or every fused component reverts to unmeasured.
  [VERIFIED: the workflow, `rslog.txt:214-238`, 316 files on disk]
- **The F2 fused component would be REFUSED by the model stage today.** Replaying
  `run_models.resolve_scale` from disk (158 peel poses, the manifest, the scalegate
  union log) gives median 0.641, IQR 0.607-0.711 - `fail`, not `unmeasured`. So
  `run_models.py:310-316` would skip it and exit with nothing modelled. Whether a
  120 s fixture should be scale-gated at all is an owner question.
  [VERIFIED: `scale_oracle.quantile_ratio_scale` replay, 2026-09-06]
- **Silent defaults that are science, not housekeeping**: zone target/min/max
  (3000/1000/4000 - a small survey collapses to ONE zone), zone overlap 20 %,
  `identity_capture` unset = the destructive harvest, `min_component_size` 50,
  declination 0.0, prior accuracies 10/1/15, assumed mount 10/30, acceptance floor
  80 %, extract 1 fpm / 3 Mpx. Preflight asks for none of them
  (`preflight.py:415-421` asks only required and path/file answers).
- **Detectors that fail open**: an unknown nav datum projects silently; a log that
  loses its zone tag becomes a local-frame campaign; `preprocessed_images` is
  chosen by existence, not by the stage having run; `merge_zones.py:165-166`
  silently drops a manifest whose `.rsalign` is missing.
- **`RS_NO_SETTINGS_INHERITANCE` is only half a refusal**: it blocks prompt
  defaults but not `SettingsStore.get` (`settings_store.py:238-241`), so
  `RS_HEADLESS`, GPU pinning, the shutdown timeout, the executable path and the
  instance-name fallback still come from `rs_settings.json` - both runs booted
  GUI-visible instances under a hidden scheduled task.
- **The lane writes into charter-protected paths**: `rs_settings.json` in the repo
  root (the C0 zone sizes and the F2 merge flags are in it now), marker files under
  `RS_CLI/Errors/`, and the format installs under the RealityScan install
  directory. No driver calls `guard_write` (`run_charter.py:330`, called only from
  tests); the hooks bind the agent's own tool calls, not the pipeline's.

FIXED the same day (carry-forward defects, not design changes):
1. The export command now carries the workspace's zone-tagged flight log, so the
   exported `.rsInfo` states this cruise's CRS instead of whatever the assembly
   project held (H2077 stamped 53N as 57S; H2060 a 2S dive as 55N).
2. `align_inputs.json` records `identity_capture`, and `verify` BLOCKS a csv zone
   merged with an xmp zone.
3. preflight's identity check runs for align OR merge (a merge-only charter used to
   get no line at all, not even on a typo) and its `csv` line no longer claims that
   nothing writes XMP.
4. `publish_nira.py` accepts `.rsInfo`, not only the RealityCapture-era `.rcinfo`,
   so the georeferencing sidecar is in the upload.
Suite: 941 passed, 1 skipped.

## [HARNESS] 2026-09-06 - NA165/H2060 fault set merged; XMP lane covered, pool+xmp refused, export shape recorded

Merged `origin/na165-h2060-directives` (its `BUGS.md` documents twelve faults
from a 19-agent pass). Eleven were live on this branch; B12 (the declared
default recorded as an explicit answer) we had reached independently. Three
conflicts, all resolved by keeping BOTH sides: geoall's required-flag check
plus the typed settings lookup; main.py's unattended branch plus the gated
interactive lookup and the stored-answer distinction; the batcher's gated
lookup plus the shadow warning. Both branches had independently gated the
same two prompt lookups (B8), which is the strongest corroboration in the
set. Suite 941 -> 960. [VERIFIED: merge d955e21]

Two of their guards deserve naming here because they close incidents this
branch had only documented: a missing, header-only or wrong-width flight log
now REFUSES before the module loop instead of aligning for hours to a
component with no georeferencing (B1), and `RS_PROJECT_CRS` is popped per
zone so one zone cannot inherit the previous zone's frame - the defect that
labelled H2060's own deliverables 55N for a 2S dive (B6).

Then, on the three things the XMP-default question left open:

- **The default lane now has on-disk test cover.** The CSV lane had a
  complete set (known-good at 1.0, known-bad at the real 0.236 collapse,
  membership) while the DEFAULT harvest lane had none, so the oracle rule was
  satisfied for the opt-in lane and not the default one, and
  `scale_oracle.component_members`' successive-difference branch had no test
  at all. Added the four twins in `testing/test_scale_gate.py`
  (`_xmp` helper writes the real sidecar shape, not a minimal one), including
  the empty-lap case: an exhausted harvest is UNMEASURED, never a pass.
- **Pool layout + the XMP lane is now refused, in both places.** It was a
  hard-rule-0 violation BY CONSTRUCTION - the pool root is the canonical
  source tree and the harvest writes a sidecar beside every image there
  before moving the pose-bearing ones out - and nothing refused it; the NA173
  charter avoided it by choosing the copy layout by hand. `preflight` BLOCKS
  before any GPU time and `__align_zone` refuses the zone at run time.
  Unset counts as xmp, so the unset case is refused too.
- **The XMP export format cannot be pinned, so the run now records what it
  produced.** `-exportXMP` DOES take an optional params file and this repo
  ships one (`Metadata/XMPExportParams.xml`, Configuration id
  `{EC40D990-B2AF-42A4-9637-1208A0FD1322}`), but nothing passes it, whether
  passing one is honoured is UNMEASURED, and there is no headless read-back
  of the instance's XMP export settings - and a read-back would not prove
  they were honoured, because the config layer stores unrecognised keys
  verbatim (rs-reference 05 sec.9.7, 09 sec.2.3, 03 sec.1.6/1.8). So
  `align_inputs.json` gains `xmp_export` = {files, sample, attributes} read
  off a sidecar the run itself wrote: provenance, never compared. The CSV
  lane records None because it pins its format by GUID instead. The cheap
  probe that would close this properly (export bare vs with the params file,
  diff the attribute set) is rs-reference 05's own Q15 and remains unrun.
  [VERIFIED: rs-reference lookup, 2026-09-06]

Also: the merge's automerge had moved `SCENE_EXTENSIONS` below a function in
`realityscan_interface.py`; restored beside its sibling constant.
Suite: 970 passed, 1 skipped.
