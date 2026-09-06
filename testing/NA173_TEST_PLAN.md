# NA173 H2014g test plan - the first agent-lane run, and the evidence the open decisions need

Written 2026-09-05, revised 2026-09-06 after the review workflow's test-triage
and integration probe. Nothing below has run against RealityScan yet; the
Status column is updated as results land (research rule: plan, then run).

## 0. What is being tested, why, and to what end

**End goal of the product.** One unattended, agent-driven run from a dataset
(imagery + nav) to census-verified deliverables - per-component textured
meshes exported as OBJ + FBX + dense PLY, then published - with the owner
deciding only at gates (`docs/AGENT_OPERATIONS.md`). The lane is
`python rs.py charter | preflight | plan | launch | status | verify`.

**Why this dataset, now.** Three things have never met RealityScan:

1. The agent lane itself (`rs.py`, `modules/preflight.py`, `modules/run_plan.py`,
   the hooks) - consolidated 2026-09-05 on a macOS box, unit-tested (879
   green on this box after the 2026-09-06 review fixes), never run against a
   live instance or a scheduled task.
2. Two changes made on the owner's word, both un-A/B'd: D3 (Zeuss mount
   25/45, orientation hardness 2.0) and D13 (AdaptiveTexelSize 4096 in every
   texture pass, `:try_unwrap` fallback, JPG exports).
3. The open decisions D1 and D12 are measurement questions, not opinions.

**The dataset.** `test_dataset_NA173_H2014g/` (inside the repo root, untracked):
3,154 JPGs at 3840x2160 with no EXIF, from three cameras with distinct
filename families - `camlower_*` (920, family `legacy_camlower`, cinema body,
mount 10 deg down), `cammid_*` (1,018, `legacy_cammid`, port, 20 deg),
`*_HERC_*` (1,216, `zeuss`, 25/45 after D3) - and `flight_log_57L_UTM.txt`:
RealityScan flight-log format, **13 columns** (no `FocalLength`), one row per
image (0 disk-only, 0 log-only), UTM zone 57L = southern hemisphere =
`EPSG:32757`, a 15 x 9 m footprint at -857..-863 m, 1 Hz capture in 7 bursts
(20:05-22:51 UTC), per-image yaw/pitch/roll with pitch already nadir-referenced
(camlower ~80, cammid ~70, zeuss ~60 deg), accuracies 10/10/1 m and 15 deg
on every row. Three facts that shape the cells:

- The log was generated with the **pre-D3 mount** (Zeuss 30 deg / 15 deg
  accuracy baked into its pitch columns) and there is **no raw ROV nav
  table**, so the georeference stage cannot run and D3's mount half cannot be
  replicated by changing `cameras.json` - only by a derived log (C5).
- Each camera folder holds an `rsmeta.db` written by an earlier GUI session:
  RealityScan has already written into this tree once. The tree is SOURCE
  DATA - read-only forever; fixtures are COPIES (the dataset sits on C:,
  and a copy keeps every RealityScan side-write off the source).
- The folder is named `H2014g` while every zeuss frame is tagged `H2104`.
  The pipeline never reads the label; the owner confirms which dive this is
  before anything is published.

**The logic of the run.** Cheap first, one variable per step, oracle before
iterator:

```
C1 charter/preflight/plan on the mini fixture (no RealityScan)
  -> C2 the mini fixture end to end, owner-run (--foreground): the known-good
  -> C0 the 13-vs-14-column flight-log probe: are priors measured at all?
  -> C3 known-bad rehearsals: every oracle must refuse what it exists for
  -> C10 verify vs texture census (D10 evidence, free)
  -> C12 rs launch + schtasks + /loop 30m on the medium fixture (mandate 6)
  -> C4 hardness 2.0 vs 10.0, two replicates each (the testable half of D3)
  -> C5 mount 25/45 via a derived log (the other half, one variable)
  -> C13 the full 3,154-image run, scheduler-owned: the first deliverable
  -> C7 / C8 D13 bake quality and the fallback, on a real component
  -> C9 D12 numbers, C6 D1 probe, C11 D9 move - when the owner has chosen
```

## 1. Oracles (each proven on a known-good AND a known-bad before it is trusted)

| Oracle | Reads | Known-good | Known-bad | Where |
|---|---|---|---|---|
| O1 plan parses | `rs plan --validate` exit 0; every argv accepted by `main.py`'s own parser | the fixture charter | an answer that reaches no command -> exit 1; a collision with a pinned flag -> refused | `modules/run_plan.py` |
| O2 preflight asks | `missing[]` names every owner answer; READY only when none | complete charter -> READY (probe 2026-09-05) | drop `b_input` -> ASK; frame `local_euclidean` vs the 57L log -> BLOCK; `utm:54N` vs 57L -> BLOCK (since 2026-09-06) | `testing/test_preflight.py`, `test_review_fixes.py` |
| O3 align census | `.rsalign.manifest.json` counts, component count, `align_inputs.json` fingerprint (settings XML sha, flight log sha) | the same zone twice, same settings -> identical census | wrong frame never runs (O2); a variant XML with an unparseable entry trips AlignZone's `:noSettings` | `modules/verify.py`, `workspace_census.py` |
| O4 scale | `testing/scale_oracle.py`: solved spacing vs nav spacing, median in 0.90-1.10 (needs >= 30 solved cameras) | H2060 components 0.937-1.119 | the 2026-07 collapses (0.175, 0.236) | `merge_zones.py --scale_gate` |
| O5 solved-focal equality (D1) | per family: solved `xcr:FocalLength35mm` identical (grouped) vs distinct; `xcr:CalibrationGroup` echo != -1; read from `identity_r0/*.xmp` | an XMP-sidecar-grouped align of the same fixture | an align with no grouping at all (six distinct focals, 2026-08-08) | `modules/prior_groups.py`, `modules/scale_oracle.py` |
| O6 texture census (D13) | offline: every texture file `.jpg`, JPEG SOF width/height <= 4096, `.mtl` carries `map_Kd`, page count; report-based when an instance holds the project: `Unwrapping style`, `Textures' count`, `Texture resolution`, `Textured` (`run_decimate.Rs.info`) | C2's component | an archived 4x8k preset applied by hand -> 8192 flagged (`testing/test_texture_policy.py` pins the static half) | `run_decimate.py`, `testing/test_texture_policy.py` |
| O7 deliverable census | `exports/<comp>/{obj,fbx,ply}` non-empty; count == the merge's `final_components` | H2060 20/20 | empty names file -> refuse (unit-tested); C3(c) shows `rs verify` passes an UNTEXTURED tree - that is D10's gap, not a pass | `modules/export_deliverables.py`, `verify` |

Blindness (no oracle sees these; route to the owner): texture VISUAL quality
(seams, blur) - only page size/count/format are machine-checkable; whether the
adaptive presets' `unwrapMinTexelSize=0` / `MaxTexelSize=4` are the enum ladder
or metres (rs-reference 03 OPEN 17, 10 OPEN 27) - only the report's texel size
tells; Zeuss's true head tilt during the dive (not logged anywhere); the hidden
console of the first `schtasks` launch (`isatty()` lies there); an adaptive
unwrap that neither errors nor mutates the scene is invisible to
`GenerateModel.bat`'s `:try_unwrap` (errors-channel only); GUI state of any
owner instance.

## 2. Fixtures

Under `<results_root>/_agent/fixture/` (mandate 4), COPIES, never hardlinks
into the source tree, each with its own `flight_log_57L_UTM.txt` (same header,
only the matching rows, same filename so the 57L tag resolves EPSG:32757 and
`find_flight_log` matches it), `b_zone_layout copy` (pool layout would harvest
XMPs beside the SOURCE images):

| Fixture | Window | Images | Size | Zones | Purpose |
|---|---|---|---|---|---|
| F1 | 40 s, 20:17:36-20:18:15 (inside the densest 120 s window) | 40 + 40 + 40 = 120 | ~0.8 GB | 1 (b_target 120 / b_min 50 / b_max 200) | the known-good; C0-C3, C6, C8, C10 |
| F2 | the full 120 s window 20:17:36-20:19:36 | 121 x 3 = 363 | ~2.4 GB | 2 overlapping (b_target 180 / b_min 100 / b_max 250) | merge path; C4, C5, C7, C12 |

Target: F1 batch + align under 5 min, model + export under 10 min.

## 3. Cells

Cost is wall-clock on this box (RealityScan 2.2, one instance, one GPU).
`[HELD]` = waits for an owner choice. `[EST]` = estimated, not measured.

| Id | Decision | Question | Hypothesis | Oracle | Inputs | Cost | Decision rule | Status |
|---|---|---|---|---|---|---|---|---|
| C1 | lane | Does `charter -> preflight -> plan` reach READY for F1 without inferring anything, as ONE `main.py` (batch + align) then merge / model / export? | preflight asks the six intake answers plus `b_input`, `b_flight_log_path` (not `r_flight_log` - Batch Directory disables it); all three families recognised (zeuss via `_HERC_`); plan = 1 chain command + 3 | O1, O2 | the F1 charter under `<results>/_agent/` | minutes, no RealityScan | any inferred answer, any camera question for camlower/cammid/HERC, or a split chain = fix the lane before C2 | **DONE for F2 2026-09-06**: charter READY without inference, one chained `main.py` (batch + align) + merge; F1 not needed separately |
| C2 | lane, D13, census | Does the whole chain run headless on F1 and census-verify, and does the first D13 component come out AdaptiveTexelSize <= 4096 with JPG textures? | 1 zone; align registers > 80 % of 120 into a component >= 20 cameras (D7 P0: 78/80 in 94 s on comparable strips); merge takes the single-component path; model textures adaptive; export writes `.jpg` only | O3, O6, O7 (this cell IS their known-good) | F1, the C1 charter; run by the OWNER as `rs run --charter C --foreground` (the agent shell is refused, by design) | batch < 1 min; align [EST] 2-4 min incl. boot; merge < 1 min; model [EST] 5-10 min; export minutes | any stage exiting 0 with an empty or wrong census = STOP and root-cause; any page > 4096, any `.png`, or `Textured` false = D13 not delivered; scale outside 0.90-1.10 = not metric | PARTIAL 2026-09-06: batch + align + merge ran headless on F2 under the CSV lane and census-verified (`rs verify` OK after `591a30f`); model + export (the D13 half) still pending - the F2 assembly `NA173_H2014G_F2_Assembly` (158 cameras) is the input |
| C0 | lane (oracle-first) | Does the 13-column NA173 log import ALL 13 columns under the pinned 14-column format `{D1F2A3B4}`, or do the orientation-accuracy columns drop (as before 2026-08-16)? | rows import (H2060/H2080 13-column logs aligned) and columns 10-12 land because the parser indexes 0-13 and the log simply ends at 12; `FocalLength` is inert either way | (1) import row count in `RealityScan.log` == fixture rows (120); (2) prior landing via `-exportReport` with a COPY of the shipped `SelectedModel.html` carrying `$(inputIsOrientationPrior)`, `$(inputIsPriorAccuracy)`, `$(inputAccuracyYaw)` (rs-reference 06 probe 8) | the C2 scene; a copied template under `<results>/_agent/` | 5-8 min, one boot, GPU idle | columns land -> every later registration number stands; columns drop -> STOP: every align on this dataset would run priors at instance-default accuracies - pick the 13-column format `{B438A617}` via `r_flight_log_params` or regenerate the log with a `FocalLength` column, then re-run C2 | **ANSWERED 2026-09-06**: all 13 columns land under `{D1F2A3B4}` (`absPrior="pose"`, `absu*` = the log's 10/10/1/15/15/15 on 229 + 200 inputs); the probe with `{0E9850E2}` gave `registered` + `-1` orientation accuracies, so `gpsLogFileFormat` is honoured; RealityScan's event-log `file_format` never follows it (FINDINGS `[NA173] 2026-09-06`) |
| C3 | oracle | Do the oracles refuse the failures they exist for? (a) frame mismatch -> preflight BLOCK; (b) an `errors_<inst>.txt` pre-seeded with one line makes `:run` abort the first op; (c) an export tree whose `.mtl` has no `map_Kd` is caught by the texture census and NOT by `rs verify` | (a) and (b) refuse; (c) shows the census is the oracle | preflight JSON; the workflow's exit code + `RealityScan reported a failure during`; verify JSON vs the offline census | C1 charter variants; a copy of C2's export tree; the marker is seeded by the OWNER (hard rule 4) | minutes; (b) needs one boot | an oracle that passes its known-bad is not an oracle: stop, fix, re-run C3 before C4+ | pending |
| C10 | D10 `[HELD]` | Is RUN_STATE's per-stage exit code + the file census enough, or do export (and extract/georeference/preprocess) need `<stage>_report.json`? | C3(c)'s untextured tree is `export: done`, verdict ok - the gap is real | `rs verify --json` on the C3(c) tree | C2/C3 workspaces; no RealityScan | minutes | owner decides whether the texture census (JPG, <= 4096, `map_Kd`, page count) becomes an export report consumed by `verify`; until then it is a manual step after every export | held: owner choice |
| C12 | lane (mandate 6) | Does `rs launch` + the printed `schtasks` lines (one form per shell since 2026-09-06) + the `/loop 30m` monitor drive F2 unattended with RUN_STATE visible? | the CRLF `.cmd`/`.vbs` pair runs hidden; RUN_STATE prepared -> running -> done; `.rc` written; `guard_schtasks` allows the declared launcher and blocks an undeclared one | RUN_STATE transitions, the `.rc` file, `rs status` (now with the budget block and the stale-pid check) | F2 charter, stages batch,align; the owner runs the three printed lines | ~15 min incl. monitoring | a run the monitor cannot see = mandate 6 unmet; no full run until it can | **DONE 2026-09-06**: F2 (batch, align, merge) and the C0 probe ran scheduler-owned and hidden; RUN_STATE prepared -> running -> done, `.rc` written, a 30 s Monitor loop saw every transition; two lane defects found and fixed (`eaa2bb4` stage list, `591a30f` per-zone nav) |
| C4 | D3 (hardness half) | Does `sfmCameraPriorWeightOrientation` 2.0 change registration / fragmentation / scale vs 10.0 on the same zone? | within replicate noise (26 vs 55, 76 vs 61 on marginal geometry, FINDINGS 2026-09-01) - two runs per side minimum | O3 (+ `align_inputs.json` sha proving which XML ran) and O4 | F2 aligned 2x with the live `AlignmentParams.xml` and 2x with a copy under `<results>/_agent/` differing ONLY in the hardness value, delivered through `science.align_settings_xml` -> `RS_ALIGN_PARAMS` (wired 2026-09-06) | 4 aligns x [EST] 4-8 min | 2.0 loses > 10 % registered or doubles the components on BOTH replicates -> owner reverts; otherwise D3-hardness is 'replicated, no measured loss' | pending |
| C5 | D3 (mount half) | Does the Zeuss 25/45 mount prior change the solve vs the 30/15 the supplied log carries? | wider accuracy lets imagery win on the tilting head: registration >= baseline, components <= baseline, scale unchanged | O3 + O4; `align_inputs.json` flight-log sha proves which log ran | F2 with a DERIVED log under `_agent/fixture/`: zeuss rows Pitch + 5.0 (rc_pitch = 90 + vehicle_pitch - mount; 30 -> 25 is +5) and Pitch Accuracy 45; known-bad: zeuss Pitch forced to 0 on every row must degrade | 2 aligns (+2 if inside C4's noise) x [EST] 4-8 min | same threshold as C4; record explicitly that this is a log-edit replicate of D3, not a georeference-stage one | pending |
| C13 | end to end | Full 3,154-image run: batch -> align -> merge -> model -> export -> verify under a charter, scheduler-owned, monitored | batch: **2 zones of ~1,577** (the batcher forces initial_k >= 2; pin b_target/min/max explicitly) so the copy-layout merge path runs; align > 80 %; scale in band; one modelled, exported, census-verified component per final component | O3/O4/O6/O7 via `rs verify --json` + the offline texture census; the run-monitor's RAM / commit / cache readings | the full dataset (copy layout copies ~18 GB); `b_min_zone` is an OWNER answer (2000 would force one zone) | align [EST] 0.5-2 h; merge < 1 h; model [EST] 1-3 h per component (H2060: 40-340 min); export minutes | budget in the charter; abort on cache volume < 50 GB, no progress-file change for 60 min, commit charge > 90 %; verdict `blocked` = stop and quote | pending - after C2's model + export half; F2 measured 10 min for 363 images, so the full 3,154 scale [EST] 1-2 h align + merge |
| C7 | D13 (bake quality) | Is a fresh adaptive-4K bake of a HIGH-POLY comparable to the retired 4 x 8K bake, and what page count / texel does it produce on a never-unwrapped mesh? | more pages at 4096 each; texel close to the old layout's; quality comparable at survey viewing distance | O6 numbers + the owner's glance | one F2 component modelled by the live `GenerateModel.bat` and by an OWNER-RUN copy under `_agent/` pointed at `archive/metadata_retired/` (SetVariables sets `Metadata` unconditionally, so a variant script is the only way) | 2 x model of one component: [EST] 10-40 min each | owner's call on the glance; numbers go to FINDINGS and rs-reference 10 sec.9.2 / sec.22 row 30 either way | pending |
| C8 | D13 (`:try_unwrap`) | When AdaptiveTexelSize rejects a mesh, does `:try_unwrap` fall back to 4 x 4096 and leave the model textured - in `GenerateModel.bat` (errors-file path) and in `ModelToFinal.bat` (rev path, own-marker move since 2026-09-06)? | both fall back; GenerateModel leaves `expected_unwrap_adaptive_<inst>_<tag>.txt`; ModelToFinal's rev moves and the reprojection after it is not blamed; both-failed aborts before any export | evidence file + O6 `Textured` true with >= 1 page; for ModelToFinal, `-getStatus` rev before/after in the log | F1/F2 project; `finish_model.py --instance <inst> --simplify true` for the attach half; no mesh on this box is known to reject adaptive (H2060 c5 is on the NA165 box) - a synthetic trigger (the adaptive preset renamed away in a copy) if none appears | minutes on a loaded scene; one boot | fallback must leave `Textured` true; both-failed must abort with no export; an untextured export with exit 0 = D13 regression | pending |
| C9 | D12 `[HELD]` | (a) Which simplification strategy reaches the owner's target: fixed 4 x 80 % (41 %) + `run_decimate` budget, or iterate-to-target at 75 %/round with clean between? (b) Does the blind `-selectModel` + `-deleteSelectedModel` in `ModelToFinal.bat` delete the working model when an intermediate is missing? | (a) rounds = ceil(log(N/N0)/log(r)); `-cleanModel` removes ~nothing (0.4096 exact on 20 H2060 components) - the round count is arithmetic once N0 is measured; (b) yes, F-102 | `-exportReport` triangle counts per round (`run_decimate.Rs.measure`, 3.87 s); (b) the model list before/after and the export's triangle count vs the pre-sweep count | one F2 component's `_HighPoly_Textured` (N0 measured); N = the owner's target (10 M is the plan's guess); a 75 % preset does NOT exist (25/50/70/80 % and 500k absolute only) - one is written under `_agent/` for the cell | (a) 5 min + [EST] 10-40 min per round on a real component; (b) two ModelToFinal runs | owner picks the strategy from the measured N0, round counts and sizes; the blind-delete pattern is fixed regardless | held: owner choice |
| C6 | D1 `[HELD]` | Do `-setPriorCalibrationGroup` / `-setPriorLensGroup`, delivered through `RS_PRIOR_GROUPS_FILE`, take effect from the delegated CLI on this rig? | two live claims disagree (FINDINGS [RECON] 2026-09-03); if they act: within-family solved focals identical and between-family medians distinct, group echo != -1 | O5 on three FRESH copies of F1 (each verified to hold ZERO `*.xmp` before its align - the exit-path repair writes calibration sidecars AFTER a run): (i) prior groups only, (ii) XMP sidecars = known-good, (iii) neither = known-bad | F1 x3; `RS_LEGACY_XMP_IDENTITY` unset so `identity_r0` exists; the generated command file kept as evidence | 3 aligns x [EST] 2-4 min | verbatim FINDINGS D1: identical + echo -> CSV capture may become default, hard rule 0 without exception; distinct + echo -1 -> `prior_groups.py` is a no-op to retire; if focals equalise but the echo stays -1, decide on focals and note the echo | arm (i) MEASURED 2026-09-06 under the CSV lane: prior groups alone -> every camera its own focal (78 distinct of 78, k2 pinned 0); arms (ii) sidecars = known-good and (iii) neither still to run (FINDINGS `[RECON] 2026-09-06`) |
| C11 | D9 `[HELD]` | Can `stage_features` leave `testing/run_on2026_run2.py` for `modules/feature_merge.py` unchanged? | yes: `test_feature_merge.py` exercises it through tmp fixtures | the suite green with the import retargeted; known-bad: the old import left in place must fail by name | repo only | minutes | green = done; any behavioural diff in the plans the tests build = stop | held: owner choice |

## 4. Budget declaration (full run, to be confirmed in the charter)

Expected: batch minutes; align 0.5-2 h (3,154 x 4K); merge < 1 h (two
zones); model 1-3 h per component (H2060: 40-340 min); export minutes.
Memory peak near total commit during model; disk delta ~72 GB cache per
modelled component (preflight now checks the CACHE volume) plus exports.
Abort: cache volume < 50 GB free, no progress-file change for 60 min,
commit charge past 90 % of RAM + pagefile. `rs status --charter` prints
the declared numbers beside the elapsed hours and free disk.

## 5. Coverage summary (from the review's triage, 2026-09-06)

| Area | Unit-tested | Live-verified | Gap |
|---|---|---|---|
| charter / preflight / plan | 4 files, ~70 tests (+ review fixes) | none - the first live use is C1 | machine checks, zone-vs-frame, the stage-subset gate never met a real Windows charter |
| run / launch / status | `test_rs_cli.py` + review fixes | none on Windows | hidden-console launcher, RUN_STATE transitions under a real task, the `.rc` file, the monitor - C12 |
| batch | 6 files | copy layout H2023/H2024 (2026-07); pool layout H2060 (2026-08/09) | copy layout on the reconciled tree; camera folders holding `rsmeta.db` |
| georeference | 7 files | H2060 29,069/29,069 exact | cannot run on NA173 (no raw nav); D3's mount half - C5 |
| align + identity + prior groups | 5 files | XMP harvest default: H2060 20 components; CSV capture: H2080/H2063 (effect unmeasured) | D1 - C6; hardness 2.0 un-A/B'd - C4; the 13-vs-14-column import - C0 |
| merge | 6 files | NA167 waves, H2060 one evolution | `--resume` reuse, the single-component cluster path - C2 |
| model / texture (D13) | `test_texture_policy.py` (25) + `test_decimate_budget.py` | GenerateModel with the RETIRED 4x8k presets: H2060 20/20; adaptive unwrap on decimated meshes: 20/20 | D13 end to end on a fresh high-poly - C2/C7; both fallback paths - C8 |
| decimate | `test_decimate_budget.py` | H2060 20 components 2026-09-03 | not an `rs.py` stage; the owner's 75 %/10 M recollection has no trace in the tree - C9 |
| export | 3 files + the JPG policy tests | H2060 20/20 with the PNG presets then in force | the JPG presets never run; `rs verify` counts files, not textures - C3(c), C10 |
| publish | 4 files | Cesium NA168 H2080 depth-correct end to end | D11 legacy assets; publish through `rs run` never run; Nira unverified |
| hooks | `test_agent_hooks.py` (34) + review fixes | liveness-tested 2026-08-31; blocked real calls 2026-09-03 and 2026-09-05 | routing phrasing untuned; `guard_schtasks` never met a real `schtasks /Create` |
