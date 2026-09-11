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

## [HARNESS] 2026-09-05 - agent-native consolidation: archived

The consolidation audit, first Windows validation, D13 texture policy and
2026-09-06 review findings are preserved verbatim in
[the next frozen log](docs/history/FINDINGS_2026-09-05_to_2026-09-06.md).
Moved 2026-09-11 to keep the live log below its existing 900-line limit.
The later runtime corrections and current findings remain below.

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

## [EXPORT] 2026-09-09 - completed H2060 walkthrough and export regressions

**Evidence:** inspected the current planner, Python export driver, batch
workflow and texture census at `f3ab62e`; compared the H2060 completion record
in HANDOFF (2026-09-02/03) and rs-reference 10 A1/A2/A5. Baseline: 970 passed,
1 skipped. New offline regressions initially reproduced 11 failing cases
across five defects. Tests use fixture files, `runpy` for the actual script
entry point and real Windows batch subroutines with RealityScan I/O stubbed.
No project was opened, changed, exported or uploaded in this review.

- **Direct-script export crashed after successful work.** The planner runs
  `python modules/export_deliverables.py`; `missing_exports` used a relative
  import that only worked when imported as a package. `runpy(..., __main__)`
  reproduced `ImportError: attempted relative import with no known parent
  package`. Use the same absolute-import pattern as the rest of the driver.
- **Stale component names survived an empty/missing/malformed merge report.**
  `refresh_export_command` called `export_names_file`, but that writer did
  nothing when no current names were found. It now writes an empty list;
  the existing driver gate refuses before boot. A valid report still writes
  BOM-free CRLF names. The old comment claiming refresh covered this case
  was false.
- **PLY coloring bypassed the selection guard.** Component selection was
  already fixed, but the subsequent raw-model select could silently leave
  another model selected (F-102). It now calls the existing
  `:select_verified` before coloring. Stub execution proved the old path
  colored a previous model and the new path stops before that mutation.
  Removed unreachable `_HighPoly_Textured` fallback text and its stray `)`.
- **The residual cleanup loop ignored failures.** A failed report/delete
  still reached `-save`. The loop now propagates failure. An explicitly
  refused optional select archives its error and skips without trying to
  measure an empty selection; a failure to archive or measure still aborts.
  This verifies the target before deletion, not a post-delete inventory.
- **The texture census accepted broken OBJ companions.** An OBJ plus an
  unrelated JPEG passed with no MTL, a commented `# map_Kd`, a bare directive,
  or `map_Kd missing.jpg`. The census now requires an MTL for OBJ and checks
  each actual map_Kd target exists among the folder's supported image files.
  Quoted filenames with spaces pass; unsupported map options/external paths
  are reported. JPEG/header/4096 checks remain. This is companion validation,
  not a full OBJ material-binding or FBX parser. Driver errors now say
  "census problems", not that every texture problem is a missing folder.

**Corrections to the earlier conversational walkthrough (SUPERSEDED):**
H2060's recorded completion was 20/20 components with OBJ, FBX and dense PLY
(91 GB), not a predicted mass export failure. Its initial PLY failure was
missing `-selectComponent`, not absent raw models. `Model 1` through `Model 9`
is a residual cleanup range, never an export component limit. A non-empty
error marker is fatal in the export `:run`, not a general success whitelist.
`setMinComponentSize` controls alignment-component/XMP exports, not named
`exportModel` calls (official Help: tutorials/commandline_1 and _3, checked
2026-09-09). Counts alone do not support a duration estimate. The cleanup
sweep does not enumerate every component's residuals.

**Scope of the example:** H2060 figures are the recorded completed run, not
a fresh NAS census. Its later c5 decimation/unwrap failure is separate from
that original file census (rs-reference 10 A5); "20/20 exported" did not prove
all later derivatives textured. Current policy uses JPG pages at <=4096,
and the stronger current census must not be projected backward onto the old
run. H2060 type-3 geometry was verified ECEF despite the stale 55N metadata
label; neither file existence nor CRS pinning alone proves depth placement.

Validation after fixes: **985 passed, 1 skipped** (38.88 s, full Windows
`python -m pytest testing -q`); 15 new regression cases. Batch file CRLF
preserved; `git diff --check` clean. Updated the master manual's model
selection/cleanup discussion and section 13.7, architecture routing,
pipeline handoff notes, CLAUDE and HANDOFF. No live RS or Cesium validation
was performed for these changes.

## [NA165] 2026-09-08 - alignment cost is set by camera-graph BANDWIDTH, not image count

Two zones of the same dive, 4% apart in image count, differed by orders of
magnitude in cost. zone_1 (8,757 images, 217 x 496 m corridor) aligned in ~4 h.
zone_2 (9,136 images, 44.7 x 41.8 m hover patch) ran 14.2 h without finishing.

HOW DISCOVERED: built the r=3 m proximity graph from each zone flight log -
positions only, no image decoding, ~13 s for all four zones - and measured
edge count and median bandwidth (max |i-j| over spatial neighbours in
acquisition order).

    zone      images   area m2   density   edges@3m   med bw   n*bw^2 vs z1
    zone_1     8,757   107,849      0.08    808,441       75          1.0x
    zone_2     9,136     1,870      4.89  3,915,034    3,955      2,900x
    zone_3     3,366       384      8.76    748,856    1,537        162x
    zone_4     1,826     1,111      1.64    192,225      202          1.5x

Cholesky on the bundle-adjustment normal equations goes as n * bandwidth^2, so
a corridor (banded, bw 75) is near-O(N) while an isotropic blob is not.
CAVEAT, stated because it matters: the proxy ORDERS the zones correctly but is
NOT calibrated to wall clock - n*bw^2 gives 2,900x while n*median_degree^2
gives 53x on the same data, a 55x disagreement, and only one zone has ever
completed. Use it to rank, never to predict hours.

Pairs-within-3m alone is NOT sufficient: zone_3 has FEWER pairs than zone_1
(749k vs 808k) yet is far more expensive, because its bandwidth is 20x higher.

## [NA165] 2026-09-08 - zone_1's 33 components are a MATCHING failure, not geometry, so it is a compromised reference

zone_1's r=3 m proximity graph is a SINGLE connected component (8,757/8,757,
zero singletons) yet RealityScan produced 33 separate components with a largest
of 604 cameras and 1,102 images (12.6%) unregistered.

Consequence, and it reframes the whole zone_2 question: zone_1's 4 h runtime is
not evidence that a ~9,000-camera connected solve is tractable on this box. It
is evidence RealityScan DECLINED to attempt one and solved 33 small blocks
instead. zone_2 was attempting a single block 15x larger than anything zone_1
ever solved.

## [NA165] 2026-09-08 - blue-water frames yield almost NO features, not noise features

The standing theory was that low-texture underwater frames get forced to the
sfmMaxFeaturesPerImage cap (25,000) and fill the descriptor budget with noise.
MEASURED, and it is the opposite.

HOW DISCOVERED: full-resolution SIFT (nfeatures=25000) on frames selected by
measured flatness, with keypoints localised against a tile-flatness mask.

    frame                       full-res SIFT kp    water area
    zone_2 flattest                        1,690        90.8%
    zone_2 next flattest                     191        88.8%
    zone_2 rich (carbonate structure)     25,000 (cap)   0.0%
    zone_1 typical                        25,001 (cap)   0.0%

A frame with 191 keypoints cannot register against anything. It is not a source
of false matches; it is dead weight that geometric pre-selection still pairs
with every spatial neighbour, paying full matching cost per pair before failing.

NOTE the earlier sampled analysis reached the opposite conclusion ("essentially
zero features land in flat water") because it measured at 1/8 scale, where
water looks smooth. Scale matters for this question.

Full census of both zones (17,893 frames, every frame, no sampling): ZERO
undecodable, zero truncated, zero within-zone duplicates, uniform 3840x2160,
all 17,893 XMP sidecars byte-identical. Content differs sharply though -
median water fraction 0.075 (zone_1) vs 0.317 (zone_2); frames >50% water
8.6% vs 33.7%; median Laplacian 1,330 vs 640.

Culling the dead frames does NOT rescue such a zone: removing 12% at safe
thresholds gives 1.7x, and removing HALF the zone by water content still leaves
it 72x zone_1. The cost is the dense core, not the empty frames.

## [NA165] 2026-09-08 - relative nav precision is ~0.09 m, but that figure cannot underwrite a spacing rule

MEASURED from NA165_H2060_final_datatable.csv (33,881 rows): residual against
an 11 s rolling median has p95 = 0.09 m; median 1 s step = 0.069 m; USBL-vs-
Kalman offset median 0.35 m, p95 1.35 m. The flight log declares 10 m.

Two consequences pull in opposite directions and BOTH matter:

1. The declared 10 m prior is 10-30x looser than achieved relative precision,
   and a 10 m prior at 3 sigma spans 30 m against a 44.7 m zone - so
   pre-selection admits ~96% of all possible pairs instead of pruning to ~12%.
2. That 0.09 m is a SMOOTHNESS statistic (residual against a rolling median),
   not an absolute accuracy, and the median 1 s displacement (0.069 m) is BELOW
   it. So frame-to-frame motion at typical speed is not reliably resolvable,
   and a displacement-threshold decimation is partly sampling jitter. A greedy
   accumulator additionally random-walks during station-keeping and spuriously
   keeps frames in exactly the dense regions that matter.

Owner directive 2026-09-08: do not decimate. Nothing in the repo establishes
the absolute nav precision such a rule would need.

## [NA165] 2026-09-08 - ifKGrp=1 is the ONLY working calibration-grouping
## channel; -setPriorCalibrationGroup has never worked and the prior groups
## were never applied on any zone of this dive

- **MEASURED, the failure: every camera on NA165/H2060 self-calibrated.** 3,000
  pose XMPs sampled from `proc/aligned_components/zone_1/identity_r0`:
  `xcr:CalibrationGroup="-1"` on 3000/3000, `xcr:DistortionGroup="-1"` on
  3000/3000, and **1,700 distinct `FocalLength35mm` values** spanning
  **8.947 - 4,640.580 mm** against a 23.0 mm prior. Focal length and scale are
  the same degree of freedom in a monocular solve, so this is a free scale:
  the gate returned 35 FAIL / 5 PASS / 3 UNMEASURED, with `zone_1_c0` at
  6.05e-07, `zone_4_c1` at 5.61, and `zone_1_c30`/`c32` at **2.00757 / 2.00030**
  - exactly 2x, the focal doubling surfacing as a scale doubling. The scale
  gate was never broken; it was reporting this correctly all along.
  [NA165] (2026-09-08) ESTABLISHED

- **CONSEQUENCE, previously unnoticed: the delivered "merge" merged nothing.**
  `proc/merged/merge_report.json` carries 43 clusters, every one with
  `"attempts": []` and `"origin": "assemble_only - carried as-is"`. With
  components at mutually inconsistent scale, `--pair_gate overlap` compares
  bounding boxes that share no metric, so nothing overlapped and every cluster
  came out a singleton. The assembly is 43 unmerged zone components in one
  project. This also DEMOTES B17: the peel harvest it describes was never
  reached in the final run, so `XMPExportParams.xml` was never the thing to
  chase first. [NA165] (2026-09-08) ESTABLISHED

- **CAUSE: `ifKGrp`, undocumented, shipped at the value that does not group.**
  120 contiguous zone_2 frames, one variable per cell, calibration sidecars
  deliberately absent so the only prior channel under test is the import
  (`_agent/probe_ifkgrp`):

      cell        cameras  ungrouped  distinct focals  focal range
      ifKGrp=0         91         91               58  23.12 - 24.14 mm
      ifKGrp=1         95          0                1  25.09 mm flat
      ifKGrp=2         93         93               55  29.50 - 30.42 mm

  Only 1 groups; 0 and 2 both leave every camera at -1. `ifKGrp=2` was the
  shipped template value for the life of this repo. Note the grouped solve
  landed at 25.09 mm, NOT the 23.0 prior - consistent with the ladder finding
  that RealityScan steers away from a claimed value; what matters for scale is
  that it is ONE value. [NA165] (2026-09-08) ESTABLISHED

- **CORRECTION to the 2026-08-28 reading that the import "appears to stomp
  prior groups". It does not.** A fourth cell ran with NO flight log at all, so
  the import could not touch anything: the prior groups still did not take -
  16 cameras, 16 ungrouped, 12 distinct focals. `-setPriorCalibrationGroup` /
  `-setPriorLensGroup` were never working, exactly as the 2026-08-08
  calibration-CLI probe established and as `CalibCellAlign.bat:93` states in an
  error message. The main align path called them anyway for every dive since.
  The [RECON] 2026-09-03 entry that kept both sides of this disagreement and
  "settled nothing" is now SETTLED in favour of `main`'s 2026-08-08 finding.
  [NA165] (2026-09-08) ESTABLISHED

- **Why it was invisible for so long, which is the transferable part.** Every
  channel reported success: the delegated command returned 0,
  `prior_groups.write_command_file` logged "1 camera family", `AlignZone.bat`'s
  `:run` saw no error, the run exited clean and produced components. The
  failure was observable in exactly ONE artefact - the exported pose - and
  nothing read it. A prior that cannot be observed in the output is not a
  prior. `modules/prior_census.py` now reads the solve after every zone align
  and refuses a run whose priors did not land, treating an EMPTY harvest as a
  failure rather than a pass. [NA165] (2026-09-08) ESTABLISHED

- **OPEN: what `ifKGrp=1` actually means.** "Group all" and "group by focal
  length" are indistinguishable on this dive - one camera family, one focal
  column. On a multi-camera rig they are not: "group all" would calibrate the
  four EXIF-identical WCA cameras as one, the exact fault prior groups were
  introduced to prevent. Probe with a two-camera fixture before the next
  multi-camera dive. This also reopens, in a useful direction, doc Q19 (the
  `ifKGrp`/`ifKmode` value mappings): `ifKGrp`'s effect is now partially
  mapped by measurement rather than by the GUI diff the question proposed.
  [NA165] (2026-09-08) OPEN

## [NA165] 2026-09-08 - the B18 fix CONFIRMED on zone_2: the freeze was the
## free focal, not the density; scale in-band goes 10.6% -> 57.8% camera-weighted

- **zone_2 completed where it previously could not.** Run 1 (ifKGrp=2, 10 m
  priors) froze at recovered p=0.615012 after 11.07 h and was killed at 14.37 h
  having delivered NOTHING. Run 2 (ifKGrp=1, 5 m priors) finished in 13.29 h,
  exit 0: 20 components, 5,649 of 9,136 cameras registered (61.8%), and the
  prior census PASSED - `groups {0: 5649}`, 9 distinct focal lengths across
  20 components, against run 1's `-1` on every camera and 1,700 distinct
  focals. [NA165] (2026-09-08) ESTABLISHED

- **THE DIAGNOSTIC POINT, and it reframes the whole run-1 investigation: the
  stall was UNDER-DETERMINATION, not size.** The two runs track each other
  closely to p=0.60 (run 2 is 1.1-1.4x ahead, and at p=0.55 it was actually
  0.90x SLOWER), so the tighter position prior is not what changed the
  outcome. What changed is that run 2 walked through the barrier run 1 died
  on - past p=0.615 at 8.79 h - and then converged explosively:

      p=0.650 at 46,515 s      p=0.800 at 46,699 s
      p=0.700 at 46,591 s      p=0.860 at 46,930 s

  i.e. 0.65 -> 0.86 in 415 SECONDS after hours of crawling. A bundle with
  9,136 free focal parameters could not close; grouped, it closed in minutes.
  This SUPERSEDES the run-1 conclusion that zone_2 was intractable at 4.89
  img/m^2. The density/bandwidth/edge-count cost model built during run 1
  correlates with real work but was describing the SYMPTOM: all four
  interventions weighed then (decimation, further splitting, content culling,
  prior tightening) were attacking the wrong variable, and the owner's two
  vetoes - "no decimation, dangerous" and "splitting is not the answer" -
  were right for better reasons than were available at the time.
  [NA165] (2026-09-08) ESTABLISHED

- **MEASURED scale after the fix, and it is a large but PARTIAL win.** Median
  solved/nav pairwise-distance ratio per component, zone_2 run 2:

      c0  1831 cams  0.9973 PASS     c1   568  1.1550 fail
      c3   415 cams  1.0257 PASS     c2   432  0.8118 fail
      c5   329 cams  1.0059 PASS     c6   294  1.3163 fail
      c4   333 cams  1.0968 PASS     c8   170  1.4387 fail
      ...                            c17   85  1.8391 fail

  8 of 20 components and 3,265 of 5,649 cameras (57.8%) inside 0.90-1.10.
  Camera-weighted against the first pass across all zones - 5 of 43
  components, 1,231 of 11,587 cameras - that is **10.6% -> 57.8%**, and the
  largest single component (1,831 cameras, a third of the zone) came in at
  0.9973. But 42% of registered cameras remain out of band and the failures
  concentrate in the SMALL components (85-570 cameras), where there is least
  geometry to pin scale. Grouping removed the systematic free-focal error; it
  did not make every fragment metric. Do not report this as "scale fixed".
  [NA165] (2026-09-08) ESTABLISHED

- **Registration 61.8% is the honest weak spot.** zone_1's first pass managed
  87.4% and zone_3 97.4%, both on far easier terrain, and both with the
  broken priors - so those numbers are not a clean baseline either. Whether
  61.8% reflects the terrain, the 5 m / 5 deg tightening (which runs against
  PD-0), or a genuine ceiling for a 44.7 x 41.8 m hover patch is NOT
  determined by this run. The zone_1/3/4 re-aligns now running use identical
  settings on zones with known first-pass rates, which is the comparison that
  will separate them. [NA165] (2026-09-08) OPEN

## [HARNESS] 2026-09-11 - merge latest NA165 development without losing local fixes

Fetched `origin`; newest development head `na165-h2060-directives` = `2bbd307`,
18 commits beyond this checkout. `main` was already contained and the old
tracking branch was deleted remotely. Saved export fixes in `330a15a`, then
merged the development head. Resolved four conflicts by retaining the strict
inheritance guard, both scale-test families, and both documentation histories.
Only the upstream documentation additions were imported; previously archived
July/August material was not duplicated back into the live log. The merged
suite first returned 1064 passed, 1 failed, 1 skipped: the sole failure was the
900-line live-findings limit. Froze the oldest live block verbatim in
`docs/history/FINDINGS_2026-09-05_to_2026-09-06.md`, preserving its lookup pointer.

Compatibility finding by code inspection: the incoming `prior_census` reads
only pose XMPs, and alignment always calls it on `identity_r0`. CSV-only
identity capture therefore fails that gate as unmeasured, even with valid CSV
poses. No bypass was introduced; adding verified group evidence for the CSV
lane is outstanding. No live RealityScan operation or GitHub push occurred.

Final validation: **1065 passed, 1 skipped** in 44.99 s on Windows; full
`python -m pytest testing -q`. Export fixes unchanged from `330a15a`, archived
findings compared verbatim with their originals, and `git diff --check` clean.
