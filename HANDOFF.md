# HANDOFF — generalized Hercules deployment

## 2026-09-11 — selection-resolution follow-up

The deployment implementation was committed and pushed as `69297cf` to
`origin/agent-native-execution`; the precommit section below is historical.
This continuation found a concrete backend defect: excluding a different-content
variant left the kept image's conflict flag, and removing an identical canonical
copy left retained copies pointing at it. The shared identity classifier now runs
after selection edits as well as hashing, preserving unrelated findings and
invalidating approval. GUI filtering/visible-row bulk selection is explained.

Targeted source/controller suite: **184 passed in 19.10 s**. Read-only hypothetical
selection checks against the saved H2101 census left zero selected name conflicts
and zero excluded duplicate targets for either upper-camera variant choice.
Both retained 103,840 unique image identities, including the 61 unresolved unknowns;
neither scenario was saved or approved. Source bytes were not read or modified;
the saved inventory bytes were confirmed unchanged. Full follow-up suite:
**2857 passed, 1 skipped in 371.35 s** (session79800).

A packaging audit also reproduced the documented relative project argument
failing the absolute-only loader. `app.py` now makes it absolute at the boundary,
retaining strict validation. Five entrypoint tests were added after full-suite
session79800 started; the subsequent entrypoint/desktop run passed **151 tests
in 25.90 s** (session23407), including all five new cases. These scopes are not
additive. No new-machine GUI or RealityScan startup claim follows from mocked tests.

Owner source choices, remaining review/settings gates and scientific validation
still block full processing. The approved project root remains F:/NA171.

## 2026-09-11 — current state; goal INCOMPLETE

Build the general native Windows 11/Python 3.13 deployment product; H2101 is reference
validation, never a hardcoded runtime branch. The workflows must work without an
AI operator. Production code and documentation are frozen for main's imminent
commit/push on agent-native-execution. The final Windows suite is green; owner
decisions and scientific acceptance below remain open. Owner-authorized commit/push
is the final integration step; the earlier "Push these changes..." remains continuing authority.

Source E:/NA171/H2101 remains physically read-only. Project/output F:/NA171;
cache F:/NA171/proc/tmp/cache; owned instance ROV_NA171_H2101; reserve 50 GiB.
The saved NA171_H2101.rovscan has operating/navigation/camera approvals only.
Effective profile: legacy lower/cinema 10°, mid/port 20°, upper/starboard 70° down,
each pitch accuracy 10°; Zeuss 40° down with pitch accuracy 40°. All yaw/roll accuracy
10°, orientation weight 2, position accuracy 5/5/1m and weight 10. Mount-family and
optical-camera identities remain distinct. These are owner policy, not calibration.

### Completed implementation and evidence limits

Native project lifecycle, scoped block approvals, deterministic inventory/staging,
navigation adapter, pre-batch quality/density gates, priors, owned execution,
checkpoint safety, temporal review/distribution and automatic orphan integration
are implemented. Read VERIFICATION_STATUS.md for current evidence; the ledger
holds dated test scopes, hashes, contradictions and remaining probes.

Final full Windows suite: **2854 passed, 1 skipped, 0 failed in 364.10 s**
(main session 89101). This includes the corrected adversarial fixture; the
correction changed no production code. Earlier results and scoped checks remain
in EVIDENCE_LEDGER.json. Green offline validation and v05's independently matched
sentinel proof do not constitute scientific or full processing acceptance.

The helper is frozen with incremental journaling, exclusive stable-ID/hash promotion,
current-batch ownership, final compact receipts and realistic encoded-copy budgets.
The frozen UI starts groups unchecked, passes exact IDs, labels actual applied
subsets, provides guarded async full-resolution viewing and persistent log-failure
banners. No real temporal candidate is approved or installed.

Automatic orphan integration uses production modules/orphan_import_probe (testing
entrypoint only wraps it), normal recorded executor after initial preflight,
explicit environment, preserved ownership exceptions and final policy re-preflight.
Zero offered orphans returns None and allows ordinary merge. Mapped masks attach
explicitly; exportMasks runs only for nonempty expected sets. Actual component
feature readback remains unverified and blocks injection when missing. No real
merge was run. Offline integration does not establish native feature behavior.

### Completed reference census; owner decisions still block processing

The worker ended at review_ready and released its OS lease; inventory/checkpoint
code freeze is lifted. Final census: 175,761 files, 128,366 image occurrences, all
in-window and zero outside, one map; no other image decode exceptions reported.
There are 125,820 unique camera+basename+content identities, including 61 unknowns.
This is neither a global unique-content count nor an approved processing set.

| Mount alias / optical camera | Composite unique | Other reported counts |
|---|---:|---|
| legacy_camlower / cinema |21,604|Distinct lower mount|
| legacy_cammid / port |21,467|Distinct mid mount|
| legacy_camupper / starboard |55,698|55,780 occurrences;82 identical duplicates|
| Zeuss |26,990|29,454 occurrences;2,464 identical duplicates|
| Unknown |61|Unresolved|

Same-camera/name different-content flags affect 44,042 occurrences across 21,980
names. Three checked upper/starboard pairs compare 1975-square batched variants
with 3840x2160 timer_still/upper variants. These are not identical duplicates;
owner choice of retained source version is pending. Unknowns need explicit
exclusion or corrected separate delivery; GUI has no arbitrary camera assignment,
renaming or timestamp correction. General camera/count acceptance is not complete.

Main acquired the lease and stored source_mask_policy=ignore_existing: all 47,394
original masks excluded from processing, zero included/deleted; 4,323 unmatched
retired masks. Inventory approval remains None. Artifact:
F:/NA171/metadata/reference_inventory/mask_retired_census.json, assessment hash
7a66db1ab8423c1d866971d8d9f84ae72f100e082c171684bf31e40bcbf9ebb4.
Physical deletion of 47,394 files/1,429,816,122 bytes still awaits explicit owner
answer. Stored processing exclusion does not authorize deletion.

### Native probes and remaining scientific uncertainty

V03 production serializer/census readback reports VERIFIED_PRODUCTION_IMPORT.
Its individual-add mask export failed with no Mask layer, err33640, process0x3f,
top code2181038093. Cause is not proved; do not label ignored sidecars/configuration
bugs as established. V04 explicit attachment and folder discovery each produced
four matching mask exports and VERIFIED_MASK_ATTACHMENT_PIXELS.

V05 completed 21:47:19Z: fresh process, folder-only import, no explicit attachment;
four real-image controls passed VERIFIED_PRODUCTION_IMPORT and
VERIFIED_MASK_ATTACHMENT_PIXELS. Final success true, ownership_retained false,
errors empty. Manifest 365fe121476439d2d8e3534358c0160314427651236f360eb202a7115b055be8.
This establishes cold-folder attachment/export pixels in that fixture. Ampere's
independent v05_result_01.json is COMPLETE_MATCH with zero violations and79 focused
passes. Both runtime ownerships released, scheduler0, no RS process/owner journals,
dependency hashes unchanged at final observation. Main inspected fresh PID creation
under the per-run root in cold_process_observation. Feature exclusion/meshing were not measured;
option readback is UNOBSERVABLE_NO_DOCUMENTED_REPORT_VARIABLE.

Temporal default 96 / min 24 / span 120 s / block 900 s is an engineering proposal. The bounded
384-hash/four-family experiment shows useful partial edges; three displayed frames
per lower/mid sheet are not semantic ground truth. Significant hardware remains
unmasked; offset historical outlines do not measure recall/false positives.
Independent labels, genuine hover and confirmed head-tilt controls remain open.

Navigation integrity repairs leave the checked H2101 filter input unchanged;
54,344 finite UTM55N rows and inverse-projection consistency do not prove absolute
accuracy, frame/datum, timing or filtering validity. Actual checkpoint scene reload,
alignment/merge science and downstream output acceptance are still open.

### Ranked loose ends

1. Owner: choose upper/starboard source variant; resolve 61 unknowns; decide physical
   mask deletion exception. Then review the resulting retained inventory explicitly.
2. Owner: complete remaining stage/settings, quality/culling and density approvals;
   optional post-batch masks require explicit accepted blocks or Skip before align.
3. Validate actual orphan component-feature readback; missing proof must continue
   blocking injection. Separately prove feature exclusion/meshing as required.
4. Complete independent nav/frame/datum/mount/hover/tilt validation and controlled
   processing/reload/output acceptance. No blanket scientific readiness claim.
5. Finish adversarial product audit using docs/CLAUDE_PRODUCT_AUDIT_PROMPT.md and
   evidence-led FINDINGS retirement under D15; preserve provenance and open D1's
   legacy identity decision. New native calibration lane does not resolve legacy D1.

### Uncommitted work and ownership

At this precommit snapshot on agent-native-execution, **201 deployment files are
staged**, with final documentation updates requiring restaging by main. Main reports
the fetched origin/main is already included in HEAD; this local branch has no
remote/upstream yet. Exact
per-file statuses and the local exclusions are in
[docs/UNCOMMITTED_FILES.json](docs/UNCOMMITTED_FILES.json). The inventory records
observation time and intended inclusion, not a perpetual uncommitted-state claim;
it becomes historical after commit.
Leave pre-existing .agents/, .codex/, .claude/settings.local.json and AGENTS.md
excluded and untouched. Main owns integration/tests and commit/push; Wegener's
documentation is frozen. Historical sections below retain
their original context and must not override this current section.

## 2026-09-11 - latest GitHub development merged locally

Fetched origin. `main` has no new commits for this checkout, and the old
`origin/agent-native-execution` tracking branch is gone. Merged the newest
development line, `origin/na165-h2060-directives` at `2bbd307` (18 new commits),
into `agent-native-execution`. The export work below was first preserved in
`330a15a`; its five fixes and all 15 regression cases remain intact.

Resolved four conflicts: retained the strict settings-inheritance guard in
`main.py`, kept both CSV/XMP and hash-seed scale tests, and combined the new
findings/handoff entries with the local history. Older findings were moved
verbatim into `docs/history/FINDINGS_2026-09-05_to_2026-09-06.md` to respect the
existing 900-line live-log limit. No historical entries were discarded.

**Compatibility limit found during merge review:** the incoming prior census
reads `identity_r0/*.xmp` only. A CSV-only align supplies no such harvest and
is refused as unmeasured. The prior check has not been weakened or bypassed;
group-aware CSV/report support remains required before that lane can pass it.
The new grouping mode's multi-camera behavior also remains unverified upstream.

Baseline: 985 passed, 1 skipped. Final: **1065 passed, 1 skipped** (44.99 s).
No live pipeline was run. No push was requested or performed. Pre-existing
untracked `.agents/`, `.codex/`, `.claude/settings.local.json` and `AGENTS.md`
remain untouched. The older working-tree statement below describes September 9;
those changes are now committed. Other remote branches were fetched, not merged.

## 2026-09-09 - H2060 export walkthrough and regression fixes

**Done:** reviewed the current export chain against the recorded completed
NA165/H2060 run (20/20 components, OBJ + FBX + dense PLY, 91 GB). The current
walkthrough is rs-reference 10 section 13.7. Corrected the stale missing-raw-model
diagnosis and distinguished the later c5 unwrap failure from the initial export.
No new NAS census, live RealityScan operation or Cesium upload was performed.

Fixed five reproduced defects: direct-script census import failure; stale
component names after an empty/missing/malformed merge report; unverified
raw-model selection before PLY coloring; ignored cleanup failures before save;
and OBJ texture false positives from missing MTLs or broken map_Kd references.
Reused the existing selection guard, preserved the workflow order and CRLF.
Expected optional-select refusals still skip; actual report/delete failures stop.

**Validation:** baseline 970 passed, 1 skipped; final **985 passed, 1 skipped**
(`python -m pytest testing -q`, Windows, 38.88 s). New tests exercise the actual
script entry point and batch control flow with RS I/O stubbed. Diff check clean.

**Working tree:** changes remain local, uncommitted and unpushed. Changed files:
`CLAUDE.md`, `FINDINGS.md`, `HANDOFF.md`, `docs/ARCHITECTURE.md`,
`docs/PIPELINE_VARIABLES.md`, `docs/rs-reference/10-reconstruction-texturing-export.md`,
`modules/export_deliverables.py`, `modules/run_plan.py`, `modules/texture_census.py`,
`modules/realityscan_interface/RS_CLI/Scripts/ExportDeliverables.bat`,
`testing/test_export_kinds.py`, plus new `testing/test_export_workflow.py`.
Pre-existing untracked `.agents/`, `.codex/`, `.claude/settings.local.json` and
`AGENTS.md` were left untouched.

**Carry forward:** the previous section's campaign state and D1 decisions.
For a future authorized export, use a fresh destination; the census checks
present files, not freshness or complete FBX/OBJ material bindings. These fixes
have offline regression coverage; their next live confirmation is an export
through the signed run lane, not a rerun against the completed master here.

## 2026-09-08 (06:15) — ASSEMBLY READY FOR REVIEW. Three decisions waiting.

**Open this:**
`D:\CoyoteThings\NA165_H2060\proc\merged\assembly\NA165_H2060_Assembly.rsproj`
5.52 GB, **43 components, 11,587 cameras**, exit 0. Gate file:
`proc\merged\EVALUATION_READY.txt`.

**CRS is correct** — the project records exactly one coordinate system,
`epsg:32702` / WGS 84 UTM zone 2S. That closes the 2026-09-02 loose end #2:
the previous delivery labelled its exports 55N on a 2S dive. The align-time pin
(project + output CRS from the flight log's zone tag, before import) held
through to the assembly.

**Against the previous delivery: 11,587 cameras vs 2,813, 43 components vs 20 —
4.1× more registered imagery**, at 60.2 % of unique images.

| zone | images | registered | % | components |
|---|---:|---:|---:|---:|
| zone_1 | 8,757 | 7,655 | 87.4 % | 33 |
| zone_3 | 3,366 | 3,279 | **97.4 %** | 6 |
| zone_4 | 1,826 | 653 | 35.8 % | 4 |
| zone_2 | 9,136 | — | killed | — |

### DECISION 1 — the scale gate blocks modelling of 38 of 43

Only 5 components fall inside 0.90–1.10. The failures are two distinct
populations and should not be treated alike:

* **Near-miss, tight IQR** — zone_3's six are 0.70–1.26, clustered near 1.19,
  IQR spreads ~0.1. Coherent geometry with what looks like a *systematic* ~20 %
  bias. This includes the 2,128-camera block, the best thing on the dive.
* **Degenerate** — zone_1's small fragments at 0.000–0.008. Collapsed solves,
  the residue of the 33-way matching fragmentation.

Only 4 of 43 were flagged "drift or a fold", so the wide-IQR pathology is rare.
FINDINGS [NA165] 2026-08-31 already attributes this dive's scale failures to its
**3.8 cm baseline geometry** (median 1 s step 0.069 m against a 9.85 m standoff
— a baseline/depth ratio of 0.007), having tested and rejected the zoom
hypothesis. The previous delivery shipped 20/20 models by **disabling the
gate**. The systematic ~20 % offset in zone_3 is a separate, possibly
correctable question and is worth its own look.

### DECISION 2 — no cross-zone fusion, because the measurement channel is broken

The merge ladder ran, produced real components (`cluster_0_a1_c0.rsalign`,
982 MB) and then **correctly refused to score them**: the peel harvest returned
empty while the .rsalign existed. `merge_zones` aborts rather than mis-assign
cameras — the invariant working as designed.

Diagnosis so far:
* **Ruled out:** calibration sidecars blocking the export. zone_1's align
  harvested 7,655 pose sidecars from the same tree with the same sidecars
  present.
* **Prime suspect:** `-exportXMPForSelectedComponent` runs with **no params
  file**. `Metadata/XMPExportParams.xml` exists (`xmpMerge`, `xmpExGps`,
  `xmpCamera=3`) and **nothing in the repo references it**, so the export
  inherits the instance's current settings. Identical failure class to the one
  already documented for `-exportRegistration`: an absent params reference does
  not error, it falls back and produces the wrong thing with exit 0.

The delivered assembly was produced with `--assemble_only`, which carries each
component as-is and never touches that channel. Components sit side by side;
they are not fused.

**SUPERSEDED 2026-09-08 — B17 is real but it was not the blocker.** The root
cause is B18: the calibration priors never reached any solve. Measured on 3,000
harvested cameras from zone_1, `xcr:CalibrationGroup="-1"` on every one and
1,700 distinct solved focals spanning 8.9–4,640 mm against a 23 mm prior — free
per-image self-calibration, therefore free scale (35 of 43 components outside
0.90–1.10, two at exactly 2.00). With scales that inconsistent `--pair_gate
overlap` found no overlaps, so the ladder attempted **no** fusions at all:
`merge_report.json` shows all 43 clusters with `"attempts": []`. The peel B17
describes was never reached in the final run.

Cause: `ifKGrp` in the flight-log import params, shipped at `2`, mapping
undocumented and never probed. Measured on 120 contiguous zone_2 frames —
`ifKGrp=0` 91/91 ungrouped, **`ifKGrp=1` 0 ungrouped and ONE focal**,
`ifKGrp=2` 93/93 ungrouped. A fourth cell with no flight log at all still came
back 16/16 ungrouped, which proves `-setPriorCalibrationGroup` was never
working either (FINDINGS 2026-08-08) and corrects the 2026-08-28 note that the
import "stomps" prior groups — nothing was stomped; the import's auto-grouping
is simply the only grouping channel that works here.

Fixed: `ifKGrp` → 1 in both templates with the cell table recorded inline and
pinned by test; `modules/prior_census.py` refuses any zone whose priors
provably did not land, treating an empty harvest as a failure rather than a
pass. **Order of work from here: B18 is fixed, so re-test B17** — with a shared
scale the ladder will actually attempt fusions and the peel gets exercised
again.

### DECISION 3 — zone_2 still has no remedy

All four interventions measured and rejected (see the section below).

### Not run

Modelling. `--auto_model false` by directive: the goal was a project to review
before modelling.

### Housekeeping

* 7 commits on `na165-h2060-directives`, pushed, tree clean. **778 tests pass**;
  the 11 failures are the no-console-stdin subprocess artifact.
* `BUGS.md` holds 16 faults with reasoning. B14 (frozen-progress detection) was
  live during zone_3 and correctly did **not** fire on a healthy-but-slow run —
  `p` moved 1.32e-2 over the window against a 1e-4 threshold.
* `_agent\logs\merge.log` was overwritten by the assemble run (a bad `sed` in my
  launcher); its diagnostic content survives in BUGS.md.
* `proc\batched_images_by_zone\zone_3d` is a decimated copy that must NOT be
  used. `proc\superseded\` holds the pre-fix truncated zone_1.

---

## 2026-09-08 — NA165/H2060 reprocess: zone_2 is intractable, 14 faults fixed

Branch `na165-h2060-directives` (4 commits, pushed, tree clean). Faults and
reasoning in **`BUGS.md`**. Suite **773 passed / 1 skipped**; the 6 failures are
a harness artifact — no console stdin, so `subprocess` handle duplication raises
`WinError 6` in `test_attach_mode.py`. They fail identically on a clean checkout
and pass in a real terminal.

### The dive

`D:\CoyoteThings\NA165_H2060` — raw frames in `raw\` (21,023, READ-ONLY),
results in `proc\`, RealityScan cache in `rs_cache\`. Nothing on C: but the
RealityScan install. Nav copied to `_agent\NA165_H2060_final_datatable.csv`.

Georeference matched **19,239 / 21,023 (91.5 %)**; the 1,784 rejects are all
"nearest nav row > 2 s" (nav gaps), zero parse failures. Flight log is 14-column
with `FocalLength`, zone-tagged `2L` → **EPSG:32702**.

### Zone status

| zone | images | bandwidth | cost vs zone_1 | state |
|---|---:|---:|---:|---|
| zone_1 | 8,757 | 75 | 1.0× | **DONE** — 33 components, 7,655 cameras (87 %) |
| zone_2 | 9,136 | 3,955 | 53–2,900× | **KILLED after 14.2 h.** See below |
| zone_3 | 3,366 | 1,538 | 162× (or 7×) | not run — expected expensive |
| zone_4 | 1,826 | 202 | 1.5× | running, healthy |

### zone_2: what is actually wrong

It is a **44.7 × 41.8 m hover patch holding 9,136 images** (4.89 img/m² against
zone_1's 0.08). The camera footprint is 15–18 m, so every frame sees a third of
the zone and the proximity graph is near-complete. It was attempting a single
connected solve **15× larger than the largest block RealityScan ever solved
here** — zone_1's 33 components have a largest of 604 cameras.

**zone_1 is therefore a compromised reference.** Its r=3 m graph is a single
connected component, yet it produced 33 blocks. Its 4 h runtime is not evidence
that a 9,000-camera solve is tractable; it is evidence RealityScan declined to
attempt one.

**Would zone_2 have finished? Unknowable from outside.** `p` is self-reported
with an undisclosed denominator, nothing emits a residual, and it saved no
project. Against: the progress rate decayed monotonically and the terminal
freeze was 6.5× the longest it had recovered from. For: three earlier freezes
of that class did resolve. Killing it was right on cost; it was not provably
dead.

**Four interventions were modelled and three were rejected on measurement:**

* **Decimation — REJECTED by the owner, and they are right.** The 0.09 m figure
  is a *relative* residual against an 11 s rolling median, a smoothness
  statistic, not absolute accuracy. Nothing in the repo establishes the absolute
  nav precision a spacing rule would need, and median 1 s displacement (0.069 m)
  is *below* that noise floor. Do not discard real frames on an unestablished
  threshold.
* **Splitting — 15×, not the k² predicted.** 9-way leaves zone_2 at 188×
  zone_1. Sub-zones of a 45 m box are still smaller than the camera footprint,
  so bandwidth stays high. It also makes zone_4 *worse* (1.51 → 1.57).
  Note the batcher's k-means XY splitter is the ineffective direction.
* **Content cull — 1.7× at safe thresholds.** zone_2 genuinely is full of blue
  water (33.7 % of frames >50 % featureless vs 8.6 % in zone_1; 4.2× the median
  water fraction; half the detail). Full-res SIFT on those frames yields
  **191–1,690 keypoints against a 25,000 cap** — they cannot register, yet
  geometric pre-selection still pairs them with every neighbour. But culling
  them leaves the dense core untouched: even discarding **half the zone** by
  water content leaves it 72× zone_1.
* **Tightening the position prior — helps ~10× on candidate pairs, cannot save
  the zone.** The r=3 m graph is the floor no prior can prune, and zone_2 is
  already far over at that floor. `testing/PRIORS_DISTORTION_TEST_PLAN.md`
  records 1/1/0.1 fragmenting a known-good component and moving hull scale from
  1.049/0.989 to 0.886/0.826.

**No corruption anywhere.** Full census of 17,893 frames: zero undecodable,
zero truncated, zero duplicates, uniform 3840×2160, all sidecars byte-identical.

### Running

`zone_4` align, launcher `_agent\align_zone4.bat`, log `_agent\logs\zone4.log`.
zone_1 output preserved; the pre-fix truncated zone_1 is in
`proc\superseded\aligned_components_zone_1_20260907-045436`.
`proc\batched_images_by_zone\zone_3d` is a decimated copy that must NOT be used.

### Ranked loose ends

Read-only reference UI smoke loaded175,761 rows/48,426 flags with unchanged project
and inventory SHA/mtime, no submitted work/lease/scan/approval. Read6.662s and
hydration9.189s included one2.335s heartbeat gap: not freeze-free. All five camera
rows loaded; Zeuss needs scrolling at table height180. Provenance/screenshot:
F:/NA171/proc/tmp/screenshots/ui-review-20260911/REFERENCE-readonly-sources-20260911-175409-e703a3.json
and matching.png. No production changes; detailed scope is in the evidence ledger.

1. **zone_2 has no accepted remedy.** All four levers measured above. The
   honest options are: accept it will not align as one zone; re-batch that
   region with a density-aware rule; or treat a dense inspection patch as a
   different workflow from a survey transit.
2. **The batcher caps by image COUNT only** — no notion of area, density or
   graph structure. That is why a 45 m box with 9,136 images shipped as one
   zone. A pre-flight cost guard from the flight log alone runs in ~13 s.
3. **Merge peel cap 40** (`MergeZoneComponents.bat`) and **NightGrow census cap
   24** have the same shape as the identity ceiling fixed in B13 — a cap
   indistinguishable from exhaustion. zone_1 alone has 33 components, so the
   NightGrow cap is already below the real count.
4. **`RealityScan.log` is session-scoped and has been overwritten three times.**
   Copy it per zone on every exit path; it is the one artifact that could settle
   "would it have finished".
5. **Decision D1 (prior groups) still open**, and the XMP harvest rewrote
   exactly zone_1's 7,655 registered sidecars. COPY layout saved zone_2; a
   symlink/hardlink layout would corrupt shared priors.

### Exact next commands

```bash
python -m pytest testing -q
python -m modules.verify --workspace D:/CoyoteThings/NA165_H2060/proc --json
```

---

## 2026-09-06 (afternoon) — D1 CSV LANE RAN END TO END, scheduler-owned, read this first

Two RealityScan runs happened this afternoon, both through the lane
(`rs charter` -> `preflight` -> `plan --validate` -> `launch` -> Task
Scheduler -> `RUN_STATE.json` -> `rs verify`), both on instance RSAGENT with
their own cache, both with the source dataset read-only and zero `*.xmp`
beside any image. The owner's instruction ("D1: design and execute an end to
end comprehensive test of the CSV workflow. End to end means zones too and
merging. Ideally no xmp are written") is the sign-off quote in both charters;
every charter answer was DERIVED by the agent and is listed below for veto.
Suite: **970 passed, 1 skipped** (`python -m pytest testing -q`, this box). Nothing pushed.

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
- **Priors and grouping audit** (8 read-only agents, 158 claims, 0 refuted;
  FINDINGS `[NA173] 2026-09-06` audit entry): both runs set only CRS, the
  params template, AlignmentParams.xml's 35 keys and the group commands;
  every pose prior came from the supplied log; no numeric calibration prior
  reached RealityScan; NOT grouped (one focal per camera everywhere, the
  merge peel's 316 XMPs all `CalibrationGroup="-1"`). Discriminating probe
  written up in rs-reference 13 A3 (`-exportReport` with the shipped
  ComponentAccuracyReport.html echoes `$(groupCount)`). C0 zone_2's
  calibration is degenerate (focal 14-29k px) - a focal sanity band per
  family is a census gap. `align_inputs.json` now records the
  prior-group command file.
- **NA165/H2060 fault set merged** (`d955e21`, their `BUGS.md` is now in the
  tree): eleven of twelve faults were live here. Headlines: a missing,
  header-only or wrong-width flight log refuses BEFORE the module loop instead
  of aligning for hours to an ungeoreferenced component; the coordinate system
  is popped per zone (the defect that labelled H2060's exports 55N for a 2S
  dive); one zone-sizing resolver with the invariants and a dead-band check;
  a zero-registered-camera guard; the gated settings lookup in the two prompt
  paths that still bypassed it; declination estimated always but applied only
  when the heading source is magnetic.
- **The XMP-default questions answered and closed** (FINDINGS `[HARNESS]`
  2026-09-06, NA165 entry): the default lane now has its own on-disk
  known-good, known-bad, membership and empty-lap tests; pool layout with the
  XMP lane is REFUSED by preflight and again at run time as a hard-rule-0
  violation by construction; and because `-exportXMP`'s format cannot be
  pinned or read back headless, `align_inputs.json` records the attribute set
  the harvest actually produced.
- **Pipeline variable audit** -> `docs/PIPELINE_VARIABLES.md` (routed from
  CLAUDE.md): every variable classified baked / detected / owner / inherited
  with its file:line and whether it crosses the stage boundary, the
  required-owner-input table, the hand-off matrix, the XMP census and 14
  ranked gaps. Headlines: the MERGE stage writes XMP under a csv charter
  (ungated, `RS_MERGE_HARVEST=1` always); the F2 fused component would be
  REFUSED by the model stage (scale replays as 0.641, a fail, not
  unmeasured); zone sizes, overlap, identity capture, min component size,
  export CRS, publish credentials and the georeference science values are
  silent defaults the lane never asks for. Four carry-forward defects fixed
  the same day (export CRS carried, identity capture fingerprinted and
  cross-checked by verify, preflight's identity check widened, Nira sidecar).
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

1. **Owner decisions the audit surfaced** (`docs/PIPELINE_VARIABLES.md` section 6):
   should the zone sizes, overlap, `identity_capture`, `min_component_size` and the
   georeference science values become required intake questions? Should the merge
   peel be ported from XMP to `-exportRegistration` (it is the last XMP writer, and
   `run_models` must change with it)? Should a 120-second fixture be scale-gated at
   all, given F2's fused component reads 0.641?
2. **When does RealityScan fold duplicate copies?** F2 kept both copies of
   the 21 shared images (158 = 78 + 80); the owner's H2063 numbers show
   fused components peeling at the unique count. The accounting now accepts
   both (`attribute_result`, `duplicates_collapsed` in the report), but the
   condition (merge mode? shared-image graph? build?) is unmeasured. The
   H2063 re-merge the owner's other session proposed (`--resume`,
   `--loss_tolerance 0.0025`) is the live test; it runs on the NA165 box.
3. **C6 arms (ii) and (iii)** on F0/F2 (XMP sidecars = known-good; neither
   = known-bad) to finish D1's prior-group question; arm (i) is measured.
4. **C2's model + export half** on the F2 assembly (158 cameras) - D12/D13
   live proof; then C13 at full scale (F2 measured 10 min for 363 images).
5. **Registration on this rig**: camlower and zeuss barely join the cammid
   strip (34-40 % per zone). Science, not lane; the owner may want C4/C5
   (hardness, Zeuss mount) before C13.
6. The installed `flightlogs.xml` has drifted from the repo copy (06 A8);
   `install_all_managed` never corrects an existing id.
7. The merge peel census still writes ordinal XMPs (inside its attempt
   folder); porting it to `-exportRegistration` is optional hygiene.
8. `stash@{0}` (the 90 on-disk deletions from 2026-09-05 22:25) is still
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
