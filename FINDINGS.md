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

## Archived runtime/navigation findings (2026-09-06)

The TEXTURE correction through the NA165/H2060 fault-set section are preserved
verbatim in [the runtime/navigation archive](docs/history/FINDINGS_2026-09-06_runtime_and_navigation.md).
Moved 2026-09-11 under owner authorization to meet the 900-line live-log cap.
Later entries retain their original order and text. Cite archived entries by date/tag.

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

## [DEPLOYMENT] 2026-09-11 - pre-batch review and mask handoff regression evidence

Owner decisions: culling and retained/culled density review against the dive
track are mandatory BEFORE batching. Candidate detection never deletes raw
imagery. Changed selections retire downstream approvals. Pairwise merge orphan
injection must be limited to images within or between the attempted components,
not the global orphan pool; live acceptance remains outstanding.

Reproduced with `testing/test_project_selection_handoff.py`: a Windows folder
mtime cache missed a mask added after its first lookup. Replaced it with bounded
exact-filename probes. The geometry-image predicate now excludes mask layers;
batch and enhancement copies carry matching masks unchanged. Source originals
are not rewritten. Unsupported image formats remain visible in batch diagnostics.

Evidence: 179 focused source/navigation/quality/spatial/review tests passed;
45 focused batch/review/mask/flight-log handoff tests passed. These are offline
code tests, not evidence of application import, alignment or cull quality on
field imagery. General deployment integration and controlled RS probes continue.

## [DEPLOYMENT] 2026-09-11 - first integrated suite and import probe

The integrated Windows suite produced 2034 passed, 1 skipped, 8 failed (249 s).
Three failures exposed `organize_by_date` still treating epoch as the missing
timestamp sentinel after the shared parser changed to None. Fixed that consumer
and the same obsolete checks in video extraction. Other failures were test
fixture drift or a wildcard test contending with the live application's OS
lease. Test locks now use an isolated temporary namespace; production ownership
checks remain intact. The five affected test files pass 122 tests after fixes.
This is not yet a fresh full-suite pass. Vendored navigation passes 92 tests
from its documented working directory; repository-root invocation still collides
with the legacy navigation tests' top-level imports.

Actual import-only probe `prior_import_probe_01` failed before prior readback:
process 20567 / 2147942487, `added_err.txt` reports "identifier expected but '$'
found" at line 7, column 20 in the generated template. Its nested
`ExportImagePriors($(inputIndex),...)` argument must be corrected and the shipped
report positive control run first. Empty output is a failed probe, not evidence
for CSV/XMP precedence. Preserve the F:/NA171 probe artifacts and verify owned
shutdown before retrying. No alignment or scientific accuracy claim follows.

## [NAVIGATION] 2026-09-11 - bounded integrity fixes preserve checked H2101 filter inputs

Implemented full-UTC SDYN acquisition-date resolution, checksum/quality rejection
accounting, and manifest-bound DAT/SDYN parsing in the vendored integration.
Valid bare legacy GGA retains its counted filename fallback. No 3-sigma, Kalman,
DVL bottom-lock or physical uncertainty tuning was performed.

Evidence: the bounded repair's 62 focused offline tests passed. Existing copied
H2101 inputs were compared in memory: the original parser reproduced all 17,570
saved USBL rows; corrected extraction added/removed/changed zero seconds and
changed zero filter inputs. Final recheck verified 41 DAT and 46 SDYN manifest
inputs. No fresh navigation candidate was generated; the existing final candidate
hash stayed unchanged. Reports, code hashes and scope are in
`docs/EVIDENCE_LEDGER.json:navigation_fix_validation` and
`F:/NA171/metadata/nav_validation/20260911T193028Z_728772e2/final_code_comparison.json`.
Previously unselected originals and absolute navigation/frame accuracy were not
proved. No H2101 rerun is indicated by these checked extraction/manifest defects.

## [INVENTORY] 2026-09-11 - cheap dive window and reusable checkpoint wired

Owner reported minutes spent scanning cruise logs solely to discover the image
inventory window. Added `navigation.source_window`, reusing delivery/report
validation without enumerating or reading sensor logs. Full `source_plan` retains
record coverage with optional metadata-identity cache, progress and cancellation.
The subsequent focused window/cache/SDYN run passed 64 tests in 1.90 s; fixtures
forbid sensor reads/enumeration in window-only lookup and check cache boundaries.

Code inspected: `modules/project_controller.py:473` now calls `source_window`, then
`modules.inventory_checkpoint.scan_inventory` at `<project>/proc/tmp/inventory_checkpoint`.
It saves `metadata/navigation_window.json`. The checkpoint reuses the existing
scanner, hashes and pixel verification; cached results never restore approval.
The controller resume fixture explicitly forbids full `source_plan`; it was read,
not executed in this documentation update. The earlier source-change failure is
still under investigation. No completed live resumed census or speedup is claimed.

## [RECOVERY] 2026-09-11 - owned import-probe shutdown proved; readback remains open

Read and hashed `F:/NA171/proc/tmp/prior_import_probe_01/recovery_result_03.json`
and its linked recovery journal. For the named approved recovery, waitCompleted
returned 1 with empty output (diagnostic only), followed by two idle-sentinel
observations at stable revision 4, with lastError -2147467259 retained. The journal
then records quit requested and reconciled instance/exact-owned-process absence;
the process evidence is a complete Windows process-ID snapshot. Original-owner
release responsibility is recorded, not independently proven cleanup of every
ownership record. Ledger `owned_recovery_artifact_review` preserves both hashes.

This is recovery evidence for that attempt, not successful report execution,
checkpoint restore or scientific acceptance. Main reports the v02 report control
running; its completion/prior readback has not been inspected here. No CSV/XMP
precedence, grouping, frame/datum, alignment or absolute-accuracy claim is blessed.
No RealityScan command or tests were run by this documentation update.

## [TESTING] 2026-09-11 - fresh integrated result and order-dependent corrections pending

Main reports the whole suite at 2268 passed, 1 skipped, 8 failed. One failure was
the FINDINGS 919-line cap; 451 older lines have now been archived verbatim with a
lookup pointer, preserving the previous newest entries. One stale attach fixture
(`loaded=1`) is reported corrected by Peirce. Main traces five probe-log assertions
and one orphan-log assertion to `logging.disable(CRITICAL)` leaking from the
rig-mount geo fixture, and reports removal of it and the stale unattended re-enable
workaround. The targeted order-dependent check is next; no post-fix full-suite
pass is claimed. Main reports the complete vendored suite at 147 passed in 9.34 s.
These are main-reported results, not new tests run by this documentation worker.
