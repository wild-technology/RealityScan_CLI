# Merge-stage rework — implementation recommendations

Written 2026-07-24 in response to the HANDOFF task "onboard, then produce
implementation recommendations against the revised [feature-aware]
workflow-evaluation queue". Numbering below tracks that queue (Q1–Q10).
Facts cited are in FINDINGS.md; nothing here has been implemented except
where marked DONE.

## What onboarding established (new, and it changes the plan)

Running `component_analysis.merge_plan` over the twelve H2023 zone
manifests — pure analysis, no RealityScan — resolves the owner's
bow/hull statement straight out of the data:

| cluster | components | images | UTM extent |
|---|---|---|---|
| hull | zone_1 c0/c1/c3/c4/c5/c6/c7/c8 + zone_2 c1 | 3,720 | E 594693–594719 / N 2345096–2345160 |
| bow | zone_2 c0 (keeper) + zone_1 c2 (twin, discarded) | 686 | E 594653–594668 / N 2345217–2345251 |
| west pocket | zone_2 c2 | 102 | E 594599–594607 / N 2345248–2345256 |

Hull ∩ bow = **zero shared basenames**. Three consequences drive
everything below:

1. **The maximal-fraction gate is unreachable by construction.** Ceiling
   is 3,720/4,600 = 80.9%, under both `--target` values ever used (0.85,
   0.83). merge_zones.py would burn the full three-attempt ladder (~1.7 h
   measured) and exit 1 on a *correct* result. Q2 is not a refinement —
   it is a correctness fix.
2. **Two of the three clusters need no merge at all.** Bow is a single
   surviving component; west pocket likewise. Every attempt run against
   them is guaranteed-wasted wall clock, and their presence is what drags
   the scene-wide fraction below target.
3. **Border gating already exists and is already computed and thrown
   away.** `merge_zones.resolve_twins_and_plan` calls `merge_plan` and
   uses only `twin_resolutions`; `merge_candidates` /
   `within_zone_border_pairs` are discarded. The expensive analysis is
   built — only the driver's consumption of it is missing.

Also established: the `D:\na156_h2023\merged` run is **superseded, not a
baseline** (five ordinal exports, empty twin_plan, predates manifests) —
do not cite its 83.9% as evidence about merge mechanism.

## Recommended order of work

| # | Work | Gates | Cost |
|---|---|---|---|
| 0 | MergeZoneComponents complist exit codes | — | **DONE** |
| 1 | D7 + content-fusion probe on the smoke fixture (Q1, Q9) | everything downstream | ~1–2 h |
| 2 | Shared scene-checkpoint module + peel-harvest primitive (Q3, Q6) | Q2, Q4 | ~half day |
| 3 | Cluster-partitioned, convergence-terminated merge driver (Q2) | production merge_v2 | ~1 day |
| 4 | GrowZone re-enable-before-save (Q5) | any accepted component pass | ~1 h |
| 5 | Cross-zone orphan pickup (Q4) | — | ~half day + run |
| 6 | Evaluation-gate report + per-component GenerateModel (Q8) | delivery | ~half day |

Q7 and Q10 are cheap add-ons; take them opportunistically.

## Q1 + Q9 — settle the mechanism on the smoke fixture first

Do not start production merge_v2 until this returns. The two open
questions are one experiment:

- **D7**: does union-flight-log + `-update` let duplicate-path zones
  merge, and is the result fusion or rigid co-location?
- **Q9 hypothesis**: does `-align` + `sfmForceComponentRematch` fuse by
  image *content*, where `-mergeComponents` needs path identity?

Fixture: two smoke zones whose overlap band is **copied** (no shared
paths) plus a control pair sharing paths, at `D:\na156_h2023\smoke_test`.
Judge by manifest membership, never exit status.

**Evidence to weigh going in, and why it is weak:** in the superseded
`merged` run, `align_rematch` scored 3,855 against `merge_georef`'s
3,860 — align did not beat merge, it lost slightly. That is mild
evidence *against* Q9, but it is confounded (no manifests, stale ordinal
exports, no per-component accounting), so it should not pre-empt the
probe. If Q9 confirms, invert the ladder for duplicate-path datasets; if
it refutes, the Q5-batcher common-image-pool change (HANDOFF P1 #5)
becomes the only route and should be promoted.

## Q3 + Q6 — the enabling primitive (do before Q2)

Q2's convergence test cannot be written before per-component membership
exists in the merge scene: today the merge census counts pose sidecars
from `-exportXMPForSelectedComponent`, i.e. **the maximal component
only**, and merged-scene exports are ordinal (B10).

Recommendations:

- **Reuse AlignZone.bat's identity loop; do not write a second one.**
  Hard rule 1 in spirit: the successive-difference harvest (save → select
  maximal → rename → export → delete → re-census → repeat → quit WITHOUT
  saving) is validated end to end. Lift it into a callable subroutine
  shared by AlignZone.bat and the merge workflow rather than duplicating
  it.
- **Run it on a dated COPY of the merge project**, as the queue says —
  the loop is destructive and the "quit without saving" guard is the only
  thing protecting the original.
- **Q6 becomes MUST-FIX here, not SHOULD-FIX.** The harvest deletes
  components in the merge scene, and `-selectComponent` silently no-ops
  on names that do not match the scene's. Correlate manifest ↔ scene by
  **image set**, never by name, before any deletion enters the loop.
- Lift `checkpoint_scene` / `restore_scene` / `prune_checkpoints` out of
  `grow_zone.py` into a shared module (e.g. `module_base/scene_checkpoint.py`)
  and have the merge driver use them. The restore path is battle-tested;
  copy-pasting it would fork a proven component.

## Q2 — merge-driver rework (merge_zones.py + MergeZoneComponents.bat)

Four changes, in dependency order:

**(a) Partition the merge into one scene per border-connected cluster.**
`-mergeComponents` and `-align` act on every component in the scene, so
border gating cannot select pairs *within* a scene — but it can decide
what goes *into* one. Take the connected components of the border graph
(`find_borders` over the twin-survivors) and run one merge scene per
cluster. For H2023 that means: hull cluster gets the ladder; bow and west
pocket are single-component clusters and get **zero attempts**. This is
what makes "attempts that cannot help disjoint features must not run
against them" mechanical rather than aspirational, and it removes the
~1.7 h of guaranteed-useless work measured above.

**(b) Terminate on convergence, not on a fraction.** Replace
`if result.success and fraction >= target: break` with: stop when a full
ladder cycle fuses no candidate pair and gains no cameras. `--target`
survives only as an informational stat in the report. Delete the "no
attempt reached the target" error exit — with (a) in place the correct
H2023 outcome is three clusters, and that must be exit 0.

**(c) Export every surviving component, not the maximal one.** The
current export block (`-selectMaximalComponent` → rename →
`exportSelectedComponentDir`) is the hazard that would leave the bow out
of the deliverable entirely. The peel loop from Q3 replaces it and
serves both purposes — each peel iteration exports one component. Keep
`min_size` well below the smallest plausible feature (50 is fine; bow is
686, west pocket 102).

**(d) Input-union shrink accounting.** After every attempt, diff the
harvested membership union against the union of the input manifests. Any
input basename absent afterwards is a shrink: reject the attempt and
restore the checkpoint. Today an align-mode attempt can shrink and still
report success — this is the same never-shrink invariant grow_zone
already enforces, and it should be the same code.

**Deliverable of the reworked driver:** one saved `.rsproj` holding every
surviving component across all clusters, georeferenced (union flight log
+ CRS + `-update`), each component exported and censused, plus an
`EVALUATION READY` report (Q8).

## Q5 — GrowZone re-enable before save (real bug, currently dormant)

`GrowZone.bat` component mode disables all images, enables a subset,
aligns, and falls straight through to `:save_quit` with no re-enable, so
every component pass saves a crippled scene.

**Checked, per the queue's "CHECK the zone_1 scene" instruction: zone_1
escaped it — every component pass was rolled back**, and `zone_1.rsproj`'s
mtime (03:31:57) is the `merge` pass's save, i.e. the post-merge
all-enabled state. Confirm in the GUI before trusting the scene; the
timestamp argument is inference, not observation.

Fix is small: `-selectAllImages` + `:selEnable` immediately before
`:save_quit` on the align/component path. Do it before any run that
could *accept* a component pass — the bug is one accepted pass away from
corrupting an artifact FINDINGS now calls authoritative.

## grow → merge handoff (MUST-FIX, and easier than it looks for H2023)

`grow_zone.py` reports `final_components` pointing at
`growth/zone_1/final_components`, which holds **four ordinal
`Component N (1).rsalign` files with no manifests** —
`try_build_manifests` produced zero (B10: identity is unharvestable
outside the original aligning scene).

- **For H2023 specifically: merge the nine PRE-growth manifested exports
  in `aligned_components/zone_1`.** Every growth pass was rejected, so the
  image union is identical (4,392); the only thing the post-growth
  exports add is the 9→4 rigid consolidation, which the cross-zone ladder
  will redo anyway. This trades nothing and keeps full identity.
- **Generally:** have `grow_zone.py` write a `final.complist` next to
  `grow_report.json` naming the authoritative export paths, and give
  `merge_zones.py` a `--complist` input. That closes the handoff without
  the driver having to interpret the report's component dict (whose paths
  are also stale — the known cosmetic bug).

## Q4, Q7, Q8, Q10 — after the driver lands

- **Q4 (cross-zone orphan pickup)** is the only stage that can *add*
  images; merge never does, and cross-zone context is what rescued
  zone_14 on NA167. Run it under checkpoint + the never-shrink invariant,
  after the ladder converges. Per-feature this is exactly "as big as it
  gets".
- **Q7 (accept zero-gain passes that reduce component count)** now has
  direct support: zone_1's rigid `merge` pass gained no cameras and took
  9 components → 4. Recommend accepting on `component_count` decrease
  with `camera_count` unchanged; never-shrink stays the default.
- **Q8 (per-component models)** — drive `GenerateModel` from the
  evaluation gate: owner selects surviving components, or all above a
  size floor under `--auto_model`. Must be EOF-safe (hidden consoles
  report `isatty()` true with EOF stdin).
- **Q10 (feature labels at the gate)** — cheap; carry the label through
  the manifests into model naming. Worth doing at the same time as Q8,
  since the report is being written anyway.

## Open, unchanged by this pass

- **U7** (CLI-observable georeferencing check) still matters most —
  merge-scene georeferencing is verified only in the GUI today.
- The zone_1 **+37 census delta** now has a hypothesis (sub-50-camera
  components absorbed by the rigid merge, invisible under
  `setMinComponentSize 50`) but cannot be closed without post-growth
  membership. Test: re-census the zone_1 scene at `setMinComponentSize 1`.
- Whether the **west pocket (102 images)** is a third real feature, ROV
  transit imagery, or a mis-solve is unknown — flag it at the evaluation
  gate rather than deciding it in code.
