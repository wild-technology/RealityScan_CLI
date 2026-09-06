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
