# HANDOFF — state of the July 2026 overhaul

## 2026-07-25 (evening) RESTART POINT — read this first

**PD-6 COMPLETED and answered the metric-scale question: NO, the hull
scale error does not survive a correct configuration.** Nothing is
running; no RealityScan or Python processes are live.

The delivered assembly at `D:\na156_h2023_fresh\merged\assembly\` is
still **METRICALLY INVALID** (hull at 0.175/0.221) and must not be
modelled or shipped. Its replacement inputs now exist.

### The corrected assembly — BUILT, awaiting owner evaluation

`D:\na156_h2023_fresh\merged_pd6\assembly\H2023_PD6_Assembly.rsproj`
— 3 components, **4,496 / 4,600 unique images (97.7%)**, built
2026-07-25 22:00 in ~1.5 min of solve time (zero merge attempts).
Gate: `D:\na156_h2023_fresh\merged_pd6\EVALUATION_READY.txt`.
Daily save copy: `RC_projects\NA156_H2023_PD6_merged_20260725.rsproj`.

**The instance quit at the end of the workflow — the project is saved,
NOT left open on the desktop.** Reopen it to evaluate.

Please glance at, in the GUI: (a) each of the three components is a
coherent feature (hull / bow / west pocket); (b) georeferencing took
(U7 is still GUI-only); (c) the hull, now ONE native 3,738-camera
component, has no seam where the old c0/c1 split used to be.

The single ERROR line in `driver.log` (`result code 2181038335` =
0x820000FF) is the documented benign err:18002 — verified by matching
all 102 "not in scene" images against every manifest: zero overlap,
they are the unregistered remainder. Not a defect.

Superseded by this: `D:\na156_h2023_fresh\merged\assembly\` (the
metrically invalid one). Do not model or ship it.

### Metrically sound inputs (the assembly's sources)

Scale oracle over every fresh-workspace component (all measured
2026-07-25 evening):

| Component | Cameras | Scale | Source |
|---|---|---|---|
| `pd6_zone_1_c0` (hull) | 3,738 | **0.982** | `D:\na156_h2023_fresh\pd_runs\pd6_zone_1_clean\components` |
| `pd6_zone_1_c1` (bow) | 656 | 1.075 | same |
| `zone_3_c0` (west pocket) | 102 | 0.990 | `D:\na156_h2023_fresh\aligned_components\zone_3` |
| *old* `zone_1_c0/c1` | 3,026 / 714 | *0.175 / 0.221* | superseded — do not use |

Total 4,496 cameras (97.8% of 4,598 unique). zone_2's only component
(101 cams, scale 0.998) is a proven subset of `zone_3_c0` and was
twin-dropped in the fresh run — exclude it.

**The merge ladder has nothing to do.** A dry run of
`merge_zones.partition_clusters` over these three puts them in three
disjoint singleton clusters, zero fusable pairs — the hull that the
fresh run spent ~75 min trying to fuse now solves natively. The
remaining work is the ASSEMBLY stage only: import all three, union
flight log + CRS + `-update`, save, census, evaluation gate.

The command that built the assembly, kept for re-runs (`--components_root`
is the workspace root so the complist's three paths all resolve, and
components stay at their original export locations per hard rule 7):

```bash
py -3.13 merge_zones.py --components_root D:/na156_h2023_fresh --complist D:/na156_h2023_fresh/merged_pd6/inputs.complist --images_root D:/na156_h2023_fresh/batched_images_by_zone --output D:/na156_h2023_fresh/merged_pd6 --name H2023_PD6_Assembly --min_size 50 --target 0.95 --project_label NA156_H2023_PD6 --visible true --auto_model false --ladder merge_first
```

### Fixed this session

- `RealityScanAlignment.capture_component_identities` made public and
  called from `testing/relaunch_pd6.py`: AlignZone.bat writes the
  identity harvest but NOT the manifests, so PD-6's exports had none
  and the feature-aware merge would have refused them. Manifests
  rebuilt for the existing exports (3,738 / 656, census matches).
  See FINDINGS 2026-07-25.

### Reading order for a fresh session

1. `FINDINGS.md`, newest entries — the metric-scale crisis (hull at
   0.175/0.220), the sidecar-stripping defect, over-tight priors, and
   the rig-geometry validation.
2. `testing/PRIORS_DISTORTION_TEST_PLAN.md` — PD cell matrix + bow 2×2.
3. `testing/scale_oracle.py` — the quality oracle; run it on any
   component: `py -3.13 testing/scale_oracle.py <components_dir> <log>`.

### Validated config state

- Division canonical in `AlignmentParams.xml`.
- Position accuracies **10/10/1** (tight fragments — bow 2×2).
- Orientation priors at 15° YPR accuracy; the 13-column flight-log
  format is installed in Program Files (re-check after any RS update).
- `camera_registry`: C and P both 16 mm 35-eq, Approximate throughout.

### Open, in priority order

1. **Owner evaluation gate on the new assembly** (built 2026-07-25
   evening, see below), then models per surviving feature component
   (hull / bow / west pocket each get their own).
2. **Close the deliverable-scale blindness**: assemble mode exports no
   XMPs, so `scale_oracle` sees the assembly's INPUTS and not the
   assembled project, while `-update` (a similarity fit) runs after.
   Fix = port the successive-difference harvest to a dated COPY of the
   assembly project — workflow-evaluation item 3, which also yields
   per-component membership. Until then the deliverable's scale is
   inferred from its inputs, not measured.
3. Intermediate accuracy ladder (3/3/0.5, 5/5/1) — loose is proven, not
   proven optimal. Optional now that scale is sound; each cell is a
   ~70 min zone_1 re-align.
4. Optional PD-6 attribution isolation cell (Brown3 + explicit-loose on
   zone_1, ~70 min) — separates Division from the newly-imported
   accuracy columns. Not needed to ship; the corrected config is
   adopted either way.
5. `D:/na156_h2023_v2` is staged through batching; aligns deliberately
   never run.
6. Owner decisions open: whether to supply measured distortion
   coefficients (must be measured under Division). The bounded-loss
   fusion flag is now MOOT for this dive — the hull no longer needs
   fusing — but remains a real design question for future dives.

## 2026-07-25 MORNING STATE — deliverable ready (read this first)

**The fresh end-to-end run COMPLETED overnight.** Full record:
`docs/FRESH_RUN_2026-07-24.md`. Headlines:

- **`D:\na156_h2023_fresh\merged\assembly\H2023_Fresh_Merged.rsproj`
  is OPEN in a RealityScan GUI window on the desktop** (plain app
  session — RS1 stays free). 4 georeferenced components: hull 3,026 +
  hull strip 714 + bow 665 + west pocket 102 = **4,507/4,598 unique
  images (98.0%)** — the best H2023 result to date.
- Evaluation gate: `D:\na156_h2023_fresh\merged\EVALUATION_READY.txt`.
  ONE DECISION WAITING: the hull pair fuses at a reproducible cost of
  2 cameras (3,740 → 3,738 on all three rungs); the never-shrink gate
  auto-rejected it, so hull is currently two overlapping components.
  Options: keep as-is / fuse interactively in the GUI / add a
  bounded-loss acceptance flag to merge_zones.py.
- Please ALSO glance at: georeferencing of the open project (U7 is
  still GUI-only) and the hull seam between c0/c1.
- Optional next automation: cross-zone orphan pickup (91 orphans) on a
  COPY of the merged project; per-component models via
  `--auto_model` / GenerateModel from the gate.
- Everything is committed locally; NOT pushed (say the word).

## 2026-07-24 (evening) FULL FRESH RUN IN FLIGHT — owner deliverable

**Owner directives (2026-07-24 afternoon):** iterate until the workflow
is fully tested/reworked/QA'd AND a full fresh run (raw images + nav →
final project) completes; run the last zone-merge steps GUI-VISIBLE;
deliverable = an OPEN, completely aligned project on the desktop by
morning. Screenshots may verify GUI-only questions.

**State when this section was written:**
- D7 probe DONE → content-fusion rule established (FINDINGS "D7
  RESOLVED"); hook liveness PASSED; merge driver reworked feature-aware
  and unit-tested (44 tests); MergeZoneComponents.bat gained
  assemble mode + count-based peel harvest with tolerant terminal.
- Fresh workspace D:/na156_h2023_fresh: georef 4,598/4,598 → CLAHE →
  3 zones batched (zone_1 4,540 / zone_2 852 / zone_3 124, calibration
  sidecars + filtered logs).
- Production zone aligns RUNNING (sequential, RS1, headless,
  'Batch Directory,RealityScan Alignment' chain, project label
  NA156_H2023_FRESH). Budget declaration: 2.5–5.5 h total for the three
  zones; peak RAM well under the box; abort = stall >45 min / exit
  code 3 / rollback storm.
- NEXT after aligns: (1) re-verify the fixed peel E2E on the smoke pair
  (RS1 free between stages); (2) cross-zone merge via the NEW
  merge_zones.py with --visible true (owner wants to watch); (3) leave
  the assembly .rsproj OPEN in a visible RealityScan instance on the
  desktop; screenshot-verify georeferencing/seams (U7 proxy).
- Growth stage (grow_zone.py) is DELIBERATELY SKIPPED for the fresh
  run deliverable: zone_1/zone_2 production growth showed re-solve
  passes reject or shrink (growth ≈ cheap insurance); the morning
  deliverable is the aligned+merged project. Run growth later if the
  evaluation gate shows recoverable orphans.

## 2026-07-24 (later) ONBOARDING SESSION — recommendations produced

The "onboard, then produce implementation recommendations" task below is
DONE: **`docs/MERGE_REWORK_RECOMMENDATIONS.md`** is the answer to the
workflow-evaluation queue (Q1–Q10), with a recommended order of work.
Read it after this section. What this session settled:

- **The feature geography is in the manifests, and it makes the merge
  target unreachable**: three spatially disjoint clusters — hull 3,720
  images, bow 686, west pocket 102, hull ∩ bow = 0 shared basenames.
  Maximal-component ceiling 80.9% vs `--target` 0.83/0.85. Confirms the
  owner's bow/hull statement from data and quantifies hazard #2.
  Recommended fix is cluster-partitioned merge scenes (one per
  border-connected cluster) — bow and west pocket then get ZERO merge
  attempts instead of ~1.7 h of guaranteed-useless ladder.
- **`D:\na156_h2023\merged` is superseded, not a baseline** (5 ordinal
  exports, empty twin_plan, predates manifests). Stop citing its 83.9%.
- **Zone_1's saved scene escaped the GrowZone disabled-images bug** —
  every component pass was rolled back; `zone_1.rsproj` mtime is the
  `merge` pass's save (all-enabled state). The code bug still stands.
  Confirm in the GUI; the argument is timestamp inference.
- **`-mergeComponents` consolidated zone_1 from 9 components to 4** —
  direct support for queue item 7.
- **MUST-FIX applied**: MergeZoneComponents.bat complist validations now
  route to a top-level `:argfail`. Before/after measured with `cmd //c`:
  a missing complist or missing component returned **0** and would have
  been reported then IGNORED by the driver; now returns 1.
- **Two review items CLOSED as non-issues by measurement**: the shared
  `:run` error-detection channel is LIVE (probe with a non-empty errors
  marker aborts, empty continues), and `startRealityScan.bat`'s nested
  boot-timeout `exit /b 1` propagates correctly through `call`. The
  cmd trap is narrower than recorded — see the refined FINDINGS entry.

Self-tests run: 31 tests pass; all .bat/.vbs confirmed CRLF;
rs_settings.json paths all resolve after the repo move. **Still owed at
the next live run: hook-chain liveness (results_<inst>.log must grow).**

Next concrete step: the smoke-fixture D7 + content-fusion probe (Q1+Q9),
before any production merge_v2.

## NEW-SESSION ONBOARDING (prepared 2026-07-24, session end)

The repo now lives at `C:\Users\jonat\OneDrive\Desktop\CoyoteThings\
RealityScan_CLI` (relocated out of DataProcessing\, owner-approved;
an empty locked leftover folder may linger at the old path — ignore).
Origin is synced through this session's final commit.

Read order: CLAUDE.md -> FINDINGS.md -> this section + the merge
section below -> testing/MERGE_STRATEGY_REPORT.md -> docs/
merge-growth-strategy-2026-07.md -> testing/ALIGN_MERGE_HARDENING_
PLAN.md + testing/MERGE_TEST_PLAN.md. COLMAP material: docs/
COLMAP_CROSSOVER.md only (different workflow — do not mix).

Session-start self-tests (standing): (1) hook-chain liveness —
results_<inst>.log must grow during the first run (CRLF normalization
touched ErrorWriterLaunch.vbs/ErrorWriter.bat on 07-24); (2) confirm
rs_settings.json paths still resolve after the repo move.

**GOVERNING INTENT (owner, 2026-07-24 — reshapes the component
workflow):** H2023 has two discrete physical features (bow + main
hull) surveyed in one dive; zones are density-batched and blind to
feature boundaries. Therefore: a multi-component final state is a
CORRECT outcome; "as big as it can get" is per FEATURE; deletion is
only ever containment-based (no unique images), never size-based; a
maximal-fraction success target misreads disjoint features as merge
failure. End state = ONE project holding every feature component at
its own maximum, georeferenced, owner-evaluated before models (with
an opt-in auto-proceed). The workflow-evaluation queue below is
updated to this intent — the next session should onboard, then
produce implementation recommendations against that queue.

## 2026-07-24 TWO-MACHINE MERGE — read this first in a fresh session

Read order: CLAUDE.md -> FINDINGS.md (consolidated fact base, both
research lines) -> this section -> testing/MERGE_STRATEGY_REPORT.md
(NA167 empirical strategy comparison) -> docs/merge-growth-strategy-
2026-07.md (workflow spec) -> testing/ALIGN_MERGE_HARDENING_PLAN.md +
testing/MERGE_TEST_PLAN.md (open unknowns).

**What happened:** the two parallel research lines — this machine's
NA156/H2023 production + hardening work and the Honeybadger box's
NA167 merge-strategy matrix — were merged (git merge 400e5b1 from the
divergence at 6069d95). Findings logs consolidated into root
FINDINGS.md (testing/FINDINGS.md frozen as NA167 raw provenance).
COLMAP material isolated into docs/COLMAP_CROSSOVER.md. QA: 31 tests
pass, active code compiles, hook-chain scripts re-normalized to CRLF
(*.vbs now pinned in .gitattributes) — **re-verify hook liveness
(results_<inst>.log grows) at the next run on the processing box.**

**CURRENT PROPOSED PRODUCTION WORKFLOW (align → components → merge),
with the data behind each step:**

1. **Per-zone align via AlignZone.bat** — pinned AlignmentParams
   (never instance defaults), appIncSubdirs=true, per-camera XMP
   calibration groups, auto-CRS flight log, exportLatestComponents +
   identity-manifest harvest, no per-zone models. Data: zone regs
   90.1–96.7% across NA167/H2023; settings rationale in
   docs/settings-evaluation-2026-07.md §4; identity capture validated
   end-to-end (FINDINGS, in-session successive-difference).
   Zones run embarrassingly parallel across GPUs (NA167: 21–98
   min/zone, ≤~60 GB each). Joint whole-dive align is OFF the table:
   identical quality to chunked (94.5% vs 94.6%) but ~165 GB at 4k
   images, extrapolating ~700 GB at 19k [NA167 #19].
2. **Within-zone growth via GrowZone.bat under the never-shrink
   invariant** (checkpoint/rollback; accept iff no unique image lost
   and net cameras >= before). Data: align both grows and SHRINKS
   nondeterministically (zone_1: every re-solve pass rejected; zone_2:
   honest zero-gain convergence at 95.1%); rollback validated in anger.
   Expect fast convergence — growth is cheap insurance, not the
   registration engine.
3. **Cross-zone merge via -mergeComponents over SHARED CAMERAS** —
   the only mechanism proven headless [NA167 D6: "Finalizing 1
   component" from halves sharing 390 images; D1–D3: zero-overlap
   never fuses, silently, under any flag]. Budget ~1 h per merge;
   verify EVERY merge by pose-XMP camera census, never exit status.
   PREREQUISITE (batcher change queued): zones must reference a common
   image pool (imagelists/same paths) — per-zone COPIES have no camera
   identity. For existing duplicate-path datasets (H2023), the
   merge_zones.py union-flight-log + -update path apparently fused
   anyway — mechanism UNPROVEN, open cell D7; census + GUI seam
   inspection mandatory until D7 settles.
4. **Rescue failed zones by growing from an aligned neighbor**
   (B-style add→log→align) — the verified workaround for solver-bug
   zones [NA167 #17/#18/#27, MSS_STR001]; verify counts after every
   grow step (a grow can fragment [NA167 #29]).
5. **Georeference the merged scene explicitly** (union flight log +
   CRS + -update — a merged component is NOT georeferenced otherwise
   [H2023]), then models per SURVIVING FEATURE COMPONENT the owner
   approves at the evaluation gate — not "the merged component only";
   discrete features (e.g. H2023 bow vs hull) legitimately end as
   separate components and each gets its own model (owner recipe;
   texture after closeHoles).

**Consolidated priority queue (both machines):**

P0 — production continuity (H2023, processing box):
1. Zone_1 growth is DONE (see previous section) — proceed to cross-zone
   merge_v2 with census + owner GUI seam verification (D7 caveat above).
2. Hook-chain liveness self-test at next session start (CRLF
   normalization touched ErrorWriter.bat/ErrorWriterLaunch.vbs).
3. MUST-FIX review items before the merge/model run (next section):
   MergeZoneComponents.bat exit /b in parens; grow_zone→merge
   .complist handoff; GrowZone component-mode inpEnabled=false
   persistence (CHECK the zone_1 scene for disabled images).

P1 — research follow-ups queued by the reconciliation:
4. **D7** (testing/MERGE_TEST_PLAN.md): does union-flight-log +
   -update in the merge scene enable duplicate-path merging, and is it
   fusion or rigid co-location? Decides merge_zones.py's escalation
   ladder and the H2023 3,860-camera merge's trustworthiness.
5. **Batcher common-image-pool change** (imagelists or hardlinks
   instead of per-zone copies) so future dives merge by identity.
6. Copy the LilyJean/COLMAP fact base off Honeybadger
   (C:\Users\jonat\itsmagicIswear\FINDINGS.md — absent here); then the
   Q-05 CLAHE reconciliation matrix (docs/COLMAP_CROSSOVER.md).
7. Zone_1 +37 census delta attribution (merge effect vs
   census-mapping nuance) — open from the growth run.
8. Report MSS_STR001 to Epic with testing/results/z14_forensic_rslog.txt.
9. Hardening cells still open: U4–U14, U17 (U7 CLI-observable georef
   check matters most); selectImage regexp-vs-Help forum-mine; D6
   export re-run if the fused .rsalign artifact is ever needed.

P2 — hygiene: retire process_h2023.py; simplify presets are
placeholders; SHOULD-FIX/NITS backlog below; Claude Skill +
documentation guide task (FINDINGS.md is the fact base, docs/ the
rationale base).

**Workflow-evaluation queue (owner-requested audit 2026-07-24,
REVISED same day for the feature-aware intent — see GOVERNING INTENT
in the onboarding section; end goal: every FEATURE component at its
own maximum, all in ONE final georeferenced project, owner evaluation
gate before models, optional auto-proceed):**

Size-based hazards the bow/hull case exposes in current code (audit
result; none deletes data on disk, but three misshape the deliverable):
- MergeZoneComponents.bat merge mode exports the MAXIMAL component
  only -> a bow-sized feature component is absent from the output set.
- merge_zones.py judges success as maximal-fraction >= --target -> a
  correct bow+hull outcome (two components, both saturated) reads as
  FAILURE and drives pointless ladder escalation; the "no attempt
  reached target" exit is wrong for disjoint features.
- GenerateModel runs on one selected/maximal component -> the bow
  never gets a model.
Confirmed SAFE (containment-only, feature-preserving): grow_zone
cleanup_stale; component_analysis twin drop (kept-union coverage — a
feature component always has unique images); AlignZone
exportLatestComponents (exports ALL comps >= min_size; keep min_size
well below the smallest plausible feature).

1. D7 on smoke BEFORE production merge_v2 (which merge attempt is
   trustworthy).
2. Merge-driver rework (merge_zones.py + MergeZoneComponents.bat),
   feature-aware: deliverable = saved .rsproj containing ALL surviving
   components, every one exported + censused (not maximal-only);
   success/termination = convergence ("no fusable candidate pairs
   remain" via manifest border-gating from component_analysis, and no
   pass gained), NOT a maximal-fraction target — retire --target as
   the success gate, keep it only as an informational stat; add
   input-union shrink accounting (align-mode attempts can shrink and
   still "pass" today); terminal state "EVALUATION READY" with report
   (per-component members/counts/bboxes/twin decisions/orphans/georef
   check) then owner gate or --auto_model (EOF-safe). Ladder attempts
   that cannot help disjoint features must not run against them
   (border-gate the escalation, don't brute-force it).
3. Port AlignZone's successive-difference identity harvest to a dated
   COPY of the final merge project (merged-stage exports are ordinal =
   count-only today; the evaluation gate and feature accounting need
   per-component membership).
4. Final orphan-pickup growth pass in the merged project (add all
   images + union log + align under checkpoint/invariant) — merge
   never adds images; cross-zone context is what rescued zone_14's;
   for feature components this is exactly per-feature "as big as it
   gets".
5. Fix GrowZone re-enable-all-before-save; CHECK zone_1 scene for
   the disabled-images state (gates "keep final zone projects").
6. Manifest<->scene name correlation by image set (selectComponent
   no-ops on renamed-manifest names — becomes must-fix once
   merge-scene deletion is in the loop).
7. grow_zone: consider accepting zero-gain passes that REDUCE
   component count (consolidation serves merging; invariant otherwise
   unchanged — never-shrink stays the automated default).
8. GenerateModel: per-component model generation driven from the
   evaluation gate (owner selects which surviving components get
   models, or all >= min size on auto-proceed).
9. HYPOTHESIS to verify (then promote to FINDINGS): -align fuses via
   image CONTENT (duplicated overlap frames match visually without
   path identity), unlike -mergeComponents which needs path identity —
   would make attempt-2 align_rematch the mechanistically sound rung
   for duplicate-path zones and argue for inverting the attempt
   ladder. NA167 D3 is not a counterexample (zero content overlap).
10. FUTURE: optional feature tagging at the evaluation gate (owner
   labels components "bow"/"hull"/etc. in the report; manifests carry
   the label forward into model naming) — cheap, makes per-feature
   accounting explicit across sessions.

## 2026-07-24 (earlier) H2023 SESSION END STATE

**Zone_1 growth completed after this was written — final: 4,429/4,540
(97.6%), all re-solve passes rolled back (see FINDINGS). Details below
kept for workspace paths and commands.**

**Where H2023 processing stands (workspace D:\na156_h2023):**
- Zone aligns DONE with manifests + RC_projects daily saves:
  zone_1 = 4,392 registered / 9 components (nondeterministic
  fragmentation - see FINDINGS; first run gave 2 components, same
  registration); zone_2 = 928/976 (95.1%) / 3 components.
- Within-zone growth: zone_2 DONE (clean run, zero real gains - the 48
  orphans are genuinely unregistrable; 3 components remain by design,
  northern strip is visually disjoint). zone_1 growth was IN FLIGHT at
  session end (grow_zone.py, output D:\na156_h2023\growth\zone_1,
  report grow_report.json when done; scene checkpoints under
  growth\zone_1\checkpoints - "initial" restores the pre-growth scene
  if anything went wrong).
- NEXT STEPS in order: (1) check zone_1 grow_report.json; (2) cross-zone
  merge: py -3.13 merge_zones.py --components_root
  D:/na156_h2023/aligned_components --images_root
  D:/na156_h2023/batched_images_by_zone --output D:/na156_h2023/merged_v2
  --name H2023_Merged --min_size 50 --target 0.83 --project_label
  NA156_H2023  (twin resolution via manifests is automatic; union
  flight log + -update georeference the merged component - VERIFY
  georeferencing in the GUI, U7 automation still open); (3) model:
  GenerateModel.bat on the merged .rsproj (owner recipe baked in;
  simplify presets are placeholders - see plan self-audit).
- The old non-georeferenced merge outputs live at D:\na156_h2023\merged
  (reference only). Smoke fixtures at D:\na156_h2023\smoke_test.

**Known open items:**
- GrowZone export mode cannot rebuild identity manifests (in-session
  harvest only exists in AlignZone.bat) - post-growth manifests are
  approximate; rebuild identity by re-running AlignZone.bat OR accept
  approximate until the merge (merge twin-resolution treats
  approximate manifests conservatively).
- grow_zone report's components dict lists stale export paths
  (cosmetic).
- Determinism test queued: third zone_1 align to confirm fragmentation
  nondeterminism (FINDINGS) - run when GPU is free.
- Hardening cells open: U4-U14, U17 (see plan STATUS UPDATE);
  U7 (CLI-observable georeferencing check) matters most for merge
  automation.
- selectImage regexp/glob discrepancy vs Help - forum-mine follow-up.
- Clean-sweep code review findings (three review agents, 2026-07-24):
  triaged into the sections below / applied where safe - check git log.
- Claude Skill + documentation guide (task queued): FINDINGS.md is the
  fact base, docs/ the rationale base.

**Review backlog (2026-07-24 clean-sweep; applied items in FINDINGS):**
MUST-FIX BEFORE NEXT MERGE/MODEL RUN:
- MergeZoneComponents.bat complist-validation `exit /b 1` inside a
  multi-statement block returns 0 (hoist to a subroutine/goto flow).
- grow_zone <-> merge handoff: merge_zones cannot consume
  grow_report.json's scattered final exports - build a .complist from
  the report (or merge the PRE-growth aligned_components when growth
  gained nothing, which is the H2023 zone_2 case).
- GrowZone.bat component-mode saves the scene with most images
  DISABLED (inpEnabled=false persists) - re-enable all before save, and
  CHECK the zone_1 scene after its growth run for this state.
SHOULD-FIX:
- Manifest component names vs in-scene names never match (scene saved
  pre-rename): cleanup_stale selectComponent silently no-ops; key
  correlation by image set instead. AlignImageList/SequentialAlignGrow:
  no AlignmentParams application, no deselect before exports.
  startRealityScan timeout exit-code shape; PowerShell harvest line in
  AlignZone.bat unchecked; :try_delete_model wait shape;
  identity-loop 20-cap absorbs remainder into the last manifest.
NITS: stale AlignImagesFromFolder rationale pointers; pre-B10 comments
in camera_registry/component_manifest; ProbeSubsetAlign headers need a
SUPERSEDED note; MergeZoneComponents delayedexpansion flag; kv colon
replace-all; dead component_manifest helpers (scan_pose_sidecars +
members_from_sidecars now only used by realityscan_interface - verify
before deleting); merge_zones ascii complist crash path.

## 2026-07-23 NA156 H2023 session: settings evaluation + workflow consolidation

Full rationale: `docs/settings-evaluation-2026-07.md`. Summary:

- **Camera registry** (`modules/camera_registry.py`): four physical
  cameras (Zeuss rect 23mm / Port fisheye 14mm / Cinema rect 17mm /
  Starboard fisheye 14mm; owner-confirmed), per-camera calibration/lens
  groups, calibration-only XMP content, pose-sidecar sanitize+census.
  The WCA rendered JPGs are EXIF-identical — XMP groups are the ONLY way
  RealityScan can separate the cameras. Old batcher values (camlower as
  "12mm fisheye") were wrong and plausibly explain the earlier
  "priors hurt" A/B.
- **Workflow consolidation**: `AlignZone.bat` (per-zone canonical:
  always applies AlignmentParams.xml, appIncSubdirs=true, exports ALL
  components >= min size via -exportLatestComponents, XMP census, no
  models) + `merge_zones.py`/`MergeZoneComponents.bat` (iterative merge,
  escalating georef-merge → align+rematch → +High overlap) +
  `GenerateModel.bat` (models once, on the merged component).
  `AlignZonesSequentially.bat` retired to archive/legacy_scripts;
  `AlignImagesFromFolder.bat` deprecated (kept for run_zone9_tests.py).
- **Settings changes**: sfmDistortionModel Division→Brown3 (global
  fallback; real models per-camera via XMP), sfmImagesOverlap
  Low→Medium. sfmEnableCameraPrior=true IS the GUI "use camera priors
  for georeferencing"; sfmMergeGeoreferencedComponents is the
  component-level no-overlap merge flag — they compose.
- **New CLI facts**: B10 (ordinal XMP exports from imported-component
  scenes), B11 (-setFeatureSource/-selectImage regexp ARE CLI;
  -exportLatestComponents; -selectComponentWithLeastReprojectionError).
  This 2.2 build does NOT recurse -addFolder without appIncSubdirs=true
  ("Added 0 layer images" → err:18002 cascade).
- **Smoke-verified end to end** (NA156 H2023 subsets): mini_a 118/120
  registered, mini_b 62/120, georef -mergeComponents fused both into one
  180-camera component in 66 s (supports matrix cell D1). Orchestrator
  now stops on module failure; alignment module aggregates per-zone
  success; overwrite prompts removed from the unattended path.
- **NA156 H2023 state**: 4,598 Port+Cinema images at
  D:\na156_h2023\raw_images (Starboard excluded by owner instruction),
  georeferenced 100%, CLAHE'd, batched into zone_1 (4,540) + zone_2
  (976) — NOTE batched BEFORE the calibration-XMP work: re-run Batch
  Directory with --b_xmp_priors true (or write sidecars into the zone
  folders) before the production zone aligns.

## 2026-07-22 fix pass + NA167 end-to-end verification

A full-code review found and fixed (all verified by a 47-check synthetic
suite plus a live NA167_H2075 run — see `git log` for the commit):

- **Chaining was broken**: alignment read `batched_images` while the
  batcher wrote `batched_images_by_zone`, and every stage expected
  `flight_log.txt` while producers write `flight_log_<zone>_UTM.txt`.
  All discovery now goes through `modules/flight_logs.find_flight_log`.
- **Extractor timestamps were one interval early** (60 s at 1 fpm): the
  frame read and the frame timestamped were different frames. Any
  dataset extracted with the old `__extract_video_cv2` carries that
  offset — re-extract before trusting its georeferencing.
- **`FlightLogParams.xml` is now auto-generated per run** from the zone
  tag in the flight-log filename (`flight_log_53N_UTM.txt` →
  EPSG:32653). Never hand-edit the template's zone again.
- **XMP calibration priors never loaded**: they were written as
  `image.jpg.xmp`; RealityScan only reads `image.xmp`. Naming fixed,
  but generation is now **opt-in** (`batch_xmp_priors`, default off) —
  an NA167 zone_13 A/B measured the current prior content *reducing*
  registration (96.3% → 89.6% on Zeuss). Validate per-rig first.
- **Per-camera zone subfolders were aligned as separate scenes**,
  defeating mixed-camera co-registration. `-addFolder` recurses
  (verified live), so a zone tree is now one alignment scene.
- Plus: georeference image check is header-only (full `.verify()` was
  ~720 GB of reads on NA167), binary-search nav matching, batcher file
  indexing (O(N·M) → one walk), geoall prefers `*final_datatable.csv`,
  PNG support in both georeferencers, warn-once unknown-camera handling,
  PID-exact lock liveness, contiguous match-delta buckets, CRLF-safe
  prompts, tabs→4-space everywhere.

**NA167_H2075 verification** (D:\na167_h2075, WCA U*/C* stills + Zeuss):
29,620 images georeferenced in ~5 min (18,944 matched ≤2 s; the 10.4k
out-of-dive-window WCA files correctly rejected — the legacy
`flight_log.txt` had clamped those to garbage). 18 zones @ target 1000
built in 6.6 min. zone_13 (34 wca + 904 zeuss, one scene) aligned
93.4% registered in 11.5 min on GPU 0, flight log + auto-generated 53N
CRS imported clean, verified shutdown. Basename flight logs match
images in camera subfolders.

This repo was created on 2026-07-21 from `wild-technology/RC_Main`
(branch `claude/realityscan-repo-cleanup-2gjmu5`, full history preserved).
That branch also still exists on RC_Main; no pull request was opened
there. Treat this repo as the single source of truth going forward.

## What the overhaul did

Four commits on top of the old `main_v2`-era code:

1. **Archive COLMAP** — `colmap_processor.py` and the three
   `vocabtrainer_*` variants moved to `archive/colmap/` (see its README).
   No splatting scripts existed.
2. **Unify RealityScan CLI execution + rename** — everything renamed
   RealityCapture → RealityScan (module dir, `RS_CLI`, `RSModule`,
   `RealityScanAlignment`, instance `RS1`, `.rsproj` saves). New unified
   execution layer `modules/realityscan_interface/realityscan_cli.py`;
   batch workflows share one `:run` delegate/wait/error-check subroutine;
   legacy `RealityCapture*` `-set` keys replaced with the `app*` keys
   RealityScan 2.x actually uses. `rs_settings.json` prompt-default
   persistence added to `main.py` and all standalone scripts
   (`module_base/settings_store.py`).
3. **README + CLAUDE.md** for the 2.2 pipeline.
4. **Adversarial-review fixes** — an independent review pass found and
   fixed, among others: component detection that reported every
   successful run as a failure; unquoted `appProcessExecCmd` paths that
   silently disabled all error detection when the checkout path contains
   spaces; markers read before instance shutdown (missed late errors);
   `%ERRORLEVEL%` parse-time expansion breaking every interactive CHOICE
   prompt; per-instance namespacing of marker files for multi-GPU.

Design rules live in `CLAUDE.md` (hard rules) and `README.md`
(architecture + lessons learned). Read both before touching execution
code.

## Verification status

Full write-up of what changed and why:
[`docs/code-review-2026-07.md`](docs/code-review-2026-07.md).

**2026-07-21: first real-machine run completed on the Windows dual-5090
box** via `testing/run_zone9_tests.py` (phases 0–1, from both a normal
checkout path and one containing spaces). Checklist outcomes:

1. **Smoke test small** — DONE. 32-image smoke passes end to end
   (boot → addFolder → importFlightLog → align → select/rename →
   exportXMPForSelectedComponent → exportSelectedComponentDir → save →
   verified shutdown), 17/32 registered on a contiguous subset.
2. **Process trigger fires** — VERIFIED, including from a checkout path
   with spaces. Several real bugs were found and fixed on the way:
   - `RealityScanCLI` now invokes the .bat by absolute path *without*
     `cmd /c` (bare names break under `NoDefaultCurrentDirectoryInExePath`
     environments like Git Bash; a self-built `cmd /c "path with
     spaces.bat"` line gets its quotes stripped by cmd).
   - The `:run` line-count used bare `find`, which resolves to GNU find
     when launched from Git Bash (scans the whole disk); now fully
     qualified as `%SystemRoot%\System32\find.exe`.
   - **The results-log-growth completion check was removed entirely**:
     RealityScan 2.2 emits periodic internal heartbeat processes through
     the same `appProcessExecCmd` trigger, so "the log grew" does not
     mean "our command finished" — it raced ahead of a running `-align`.
     `:run` now does delegate → grace → double `-waitCompleted`.
   - `-mergeComponents` is a no-op with a single component and its async
     re-reconstruction can clear the selection; replaced with
     `-selectMaximalComponent`.
   - `-exportXMP` only covers "the last alignment" and silently skips
     components below `setMinComponentSize` (default 5); replaced with
     `-setMinComponentSize 1` + `-exportXMPForSelectedComponent`.
3. **`-align "%AlignmentParams%"`** — CONFIRMED NOT SUPPORTED. `-align`
   takes no parameters in 2.x (local Help `allcommands.htm` + online
   docs). `AlignZonesSequentially.bat` now parses the sfm*/lis* keys out
   of `AlignmentParams.xml` and applies them via delegated `-set`
   commands before a plain `-align`.
4. **Process result code 1** — benign in practice: routine successful
   operations (e.g. `-addFolder`) report result 1 through the trigger
   while real failures report distinct codes (0x820000FF warning-class,
   0x80070057 E_INVALIDARG). Whitelist of 0/1 kept.
5. **Shutdown timing** — verified on small scenes only; the 15-min bound
   on very large scenes is still untested.
6. **Multi-GPU parallel instances** — still untested. Single-instance GPU
   pinning via `rs_settings.json` `"gpu_devices"` exercised during the
   phase-2 test runs.
7. **Autosave keys** — no stale autosaves observed in any test run.

Other findings from the first runs:

- `FlightLogParams.xml` declared UTM zone 4N (EPSG:32604) from an earlier
  project; the NA173_H2103a flight logs are zone **57S** (EPSG:32757,
  southern hemisphere). Fixed. Check this per-cruise before importing.
- `-importFlightLog` reports a failed process (err:18002, 0x820000FF)
  when the log references images that are not in the scene — even though
  the trajectory itself imports fine. When aligning subsets, filter the
  flight log to the images actually present (the zone_9 runner does).
- `-exportRegistration` without a params XML blocks forever headless —
  avoid it until a params file saved from the GUI dialog exists.

## PENDING RECONCILIATION with LilyJean/COLMAP findings (filed 2026-07-23)

The LilyJean fact base (`C:\Users\jonat\itsmagicIswear\FINDINGS.md`, 34 dated/
sourced entries) reached the OPPOSITE preprocessing verdict from this pipeline:
on 3,607 LilyJean stereo pairs, both adaptive enhancement and fixed backscatter
subtraction reduced COLMAP registration ~30% vs originals (F-20260721-02,
F-20260723-01) — while this repo's CLAHE 2.0/8×8 pre-alignment default is
validated on zone_9 where the baseline aligns to NOTHING (recorded there as
counter-evidence F-20260723-33). Both results are real; scope is unresolved.

When the colmap-studio research completes, run the reconciliation matrix (Q-05):
zone_9 {baseline, CLAHE} × COLMAP, and LilyJean {originals, CLAHE} × this
pipeline's RealityScan alignment, judged on REGISTRATION (not keypoints —
F-20260723-03). Outcome decides whether preprocess_images stays default-on,
becomes per-dataset, or moves to texture-only.

Also relevant from that fact base for this repo:
- RealityScan Image Layers (`.geometry`/`.texture`/`.mask`, F-20260723-23) are
  the official mechanism for "originals align, corrected images texture" — the
  reconciling architecture if CLAHE ends up texture-only.
- Staff caution against over-masking (F-20260723-31) and Ultra detector
  sensitivity manufacturing noise points (F-20260723-26) — relevant to
  `masking.py` and AlignmentParams choices on turbid imagery.
- No stereo-rig support in RealityScan (staff-confirmed through Aug 2025,
  F-20260723-27): Voyis-rig scale must come from GCPs/distance constraints/
  locked XMP — consistent with this repo's per-rig XMP-priors caution (the
  NA167 zone_13 A/B where priors cost 6.7 points of registration is recorded
  as F-20260723-34).

## Known loose ends

- `geoall.py` (canonical) and `modules/georeference/georeference_images.py`
  still duplicate the georeferencing workflow — port improvements into
  the module when it next changes (CLAUDE.md hard rule 6).
- The overwrite prompts in `realityscan_interface.py` use `input()` and
  can stall an unattended pipeline mid-run; consider a `--force`
  parameter if runs go fully unattended.
- `rs_settings.json` is per-machine and gitignored; nothing migrates old
  hardcoded paths — first run on a new machine prompts from the baked-in
  fallbacks.

## Session provenance

Overhaul performed by Claude Code (session linked in the commit
trailers), including web-verified RealityScan 2.2 CLI semantics
(`-delegateTo` queueing, `-waitCompleted` pickup race, `-getStatus`
errorlevel contract, `appProcessAction` triggers, exit codes 0/1/3).
