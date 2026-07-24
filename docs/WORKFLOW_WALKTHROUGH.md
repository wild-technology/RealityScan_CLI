# Workflow walkthrough — raw images to final project (H2023 example)

Plain-language end-to-end path, written 2026-07-24 for the owner using
H2023 as the worked example: 4,598 usable images (Port P231C* + Cinema
C231C*; Starboard excluded), nav from the ROVDataConcat Kalman table,
wreck in TWO physical pieces (bow + main hull). Zone criteria in the
example: 2,000 images/zone + 20% overlap → ~3 zones of ~2,000 with
~400-image shared bands (the real H2023 run's density batcher gave
4,540 + 976 — uneven zones are normal). Items marked [QUEUED] are in
HANDOFF's workflow-evaluation queue, not yet built; everything else
runs today. Deep rationale: docs/merge-growth-strategy-2026-07.md,
docs/settings-evaluation-2026-07.md; facts cited: FINDINGS.md.

## Stage 0 — Raw images -> georeferenced images

- Start: D:\H2023 raw dumps. Movies (S231C* = Starboard) excluded;
  stills sorted per camera.
- geoall.py matches every image to the nav table by timestamp (stage-2
  Kalman file *final_datatable.csv), applies each camera's mount
  offset (Port: 1 m fwd + 1 m down; Cinema: 45 deg down, 1 m fwd), and
  writes ONE flight log: image basename -> UTM position + orientation
  + accuracies. UTM zone is baked into the filename; the CRS params
  file is auto-generated from it — never hand-edited.
- CLAHE contrast preprocessing runs (current default; contested, Q-05).
- Camera registry writes one calibration sidecar (image.xmp) per image
  — the ONLY thing telling RealityScan Port and Cinema are different
  cameras (their EXIF is identical).
- Identity from here on is the IMAGE BASENAME: flight log, censuses,
  manifests, and orphan math all key on it.

## Stage 1 — Zone batching (2,000 + 20%)

- The batcher walks the georeferenced trajectory and cuts spatial
  zones of ~2,000 images; neighbors share a 20% band (~400 images in
  BOTH zones). The bands are deliberately load-bearing: they are the
  glue the cross-zone merge uses.
- Each zone folder gets its own filtered flight log (only its members).
- Zones are cut on DENSITY, not features — the bow might be all of one
  zone, the hull spread over two. No downstream stage may assume one
  zone or one dive = one object.
- [QUEUED] Zones should REFERENCE a common image pool instead of
  holding copies: RealityScan treats two components' images as "the
  same camera" only at the same on-disk path. Today's copies don't
  share paths, which weakens the merge stage (the D7 uncertainty).

## Stage 2 — Per-zone alignment (AlignZone.bat, parallel across GPUs)

- Boot instance -> add zone folder (subfolder recursion explicitly ON;
  default silently adds nothing) -> sidecars auto-import -> flight log
  + CRS -> push every alignment setting explicitly (never instance
  defaults) -> -align.
- Expect SEVERAL components per zone, with an unstable count across
  identical runs (observed 2 vs 9). WHICH images register is stable;
  how they clump is not — so everything downstream tracks image sets,
  never component names/counts.
- Export every component >= a small noise floor (~50 — the floor must
  stay far below the smallest plausible feature so a bow-sized
  component always survives).
- Census: deselect all (a stray selection silently EMPTIES exports),
  export pose XMPs — each registered image gets a sidecar named after
  itself; count + list = registration ground truth. Sidecars are then
  immediately reverted to calibration-only (exported poses must never
  leak into later runs as fake priors).
- Identity harvest (the CLI cannot enumerate a component's images, so
  we peel): save project FIRST, then destructively loop — select
  maximal component, rename zone_N_cK, export it, delete it, re-export
  the pose census; the basenames that DISAPPEARED were cK's members.
  Repeat until empty; quit WITHOUT saving. Output: one manifest per
  component (member basenames, count, UTM bbox from the flight log).
- Save .rsproj + dated RC_projects copy. H2023 actual: zone_1
  4,391/4,540; zone_2 920/976.

## Stage 3 — Within-zone growth loop (as big as components get IN-zone)

All wrapped in checkpoint/rollback, because re-alignment can silently
SHRINK a component:

- Checkpoint = plain file copy of the project bundle. Take one, export
  components, take the ZONE BASELINE CENSUS (set of registered
  basenames). ORPHANS = zone basenames minus that set (zone_1: 149).
- Pass 1, global re-align: everything enabled, align once, re-census.
  Accept ONLY IF no previously-registered basename lost AND total did
  not drop. Accept -> new baseline + new checkpoint. Reject -> copy
  the checkpoint back (restore path is battle-tested).
- Pass 2, rigid consolidation: -mergeComponents (cannot shrink) fuses
  anything the re-align tied; then delete ONLY components whose entire
  image set is contained in the kept union — NEVER by size. A feature
  component always holds unique images, so it is structurally
  undeletable.
- Pass 3, per-component passes (largest first): disable ALL images
  (per-image literal selectImage — pattern matching is broken in this
  build; ~0.1–0.3 s/image, minutes per 2,000), re-enable one
  component's members PLUS all orphans, align. Purpose: give orphans a
  stable anchor without letting the rest of the zone reshuffle.
  - Accounting trap (hit + fixed): even an "isolated" pass refreshes
    EVERY component — judge gains against the ZONE baseline, never
    per-component before/after (phantom gains otherwise).
  - Re-enable everything after each pass ([QUEUED] fix — the disabled
    state can leak into the save; CHECK zone_1's saved scene).
- Loop passes 2–3 while anything gains. Three exits: converged (no
  gain), budget cap, rollback storm (stop and report — a finding, not
  something to push through).
- Twin scan: an overlap band solved twice (once per zone context)
  yields a weak twin; the copy with ZERO unique images is dropped
  (same containment rule — features safe).
- FINAL ZONE STATE: all images re-enabled -> save project + manifests
  + dated RC_projects copy. THE AUTHORITATIVE ARTIFACT (owner
  convention, FINDINGS 2026-07-24): hand-evaluation fallback, and the
  only scene identity can ever be re-harvested from. H2023 reality:
  zone_2 converged instantly (48 orphans genuinely unregistrable; 3
  components by design — the disjoint northern strip is the
  small-feature pattern in miniature); zone_1 rejected EVERY pass.
  Growth is cheap insurance, not the engine.

## Stage 4 — Between-zone merge (fresh project; the rework target)

- New empty scene. Import every surviving zone component FROM ITS
  ORIGINAL EXPORT PATH via a .complist file (a relocated component
  file hangs the import forever). Import the union flight log (all
  zones, deduped by basename) + CRS. Deselect all.
- The merge loop [partly QUEUED]:
  - Candidate pairs from manifests: bbox border gating — only
    components whose boxes touch/overlap (within margin) are fusable
    candidates. Bow's box never touches hull's -> never a candidate ->
    no wasted attempts, no false "failure". Pairs sharing overlap-band
    images are prime candidates.
  - Escalation ladder per candidate set, one change per attempt:
    (1) -mergeComponents — PROVEN to fuse components sharing cameras
    (NA167 D6); for today's duplicate-path zones this is D7-uncertain;
    (2) re-align + force-rematch — matches image CONTENT, which
    duplicated band frames satisfy even from different paths
    (hypothesis, queue #9); (3) same + widest pair search.
  - After EVERY attempt: census — NEVER exit status (merges fail
    silently). Compare against the union of input manifests: nothing
    lost (shrink accounting [QUEUED]), gains attributed.
  - -update fits everything to the imported constraints -> merged
    scene georeferenced (it is NOT otherwise). Verify (GUI now;
    automated proxy = open cell U7).
  - TERMINATE ON CONVERGENCE: a full ladder cycle with no candidate
    pair fusing and no gain. NOT on "one big component" — bow + hull
    ending as two saturated components is SUCCESS.
- [QUEUED] Cross-zone orphan pickup: add ALL zone images + union log
  to the merged scene, enable orphans + anchors, align under
  checkpoint/invariant. Cross-zone context registers images no single
  zone could (this rescued an entire failing zone on NA167).
- [QUEUED] Identity harvest for final components — on a dated COPY of
  the merged project (merged-scene exports are anonymously numbered;
  membership must be re-derived by the same peel-and-diff).

## Stage 5 — Final saved state + evaluation gate

- Save all_zones_merged.rsproj containing EVERY surviving component —
  hull at its maximum, bow at its maximum, pockets above the floor —
  all georeferenced in one project. Dated RC_projects copy.
- [QUEUED] EVALUATION READY report: per component — members, count,
  bbox, zone provenance, twin/discard log, remaining orphans, georef
  check. Owner opens the project, compares against saved zone projects
  if anything looks off, optionally labels components (bow/hull).
- Per approved component — or all, under --auto_model — the model
  recipe runs: high mesh -> cleanup -> close holes -> texture ->
  simplify -> reproject.
- Recovery chain at every step: merged project <- rebuildable from
  zone projects <- rebuildable from batched images <- rebuildable from
  raw + nav. Nothing downstream is ever the only copy of anything
  upstream.

## Bookkeeping at a glance

| What | Tracked by | Survives |
|---|---|---|
| Who registered | pose-XMP census (basenames) | every mutation — taken after each pass/attempt |
| Component membership | manifests (basename sets + bbox) via peel-and-diff harvest | export/import/delete; scene NAMES do not — always correlate by image set |
| Orphans | zone (or union) basenames − census | re-attempted at every growth context, per-zone then cross-zone |
| Enabled/disabled images | per-image literal selections + inpEnabled | must be reset before every save [fix queued] |
| Undo | project-bundle file copies before every mutating pass | restore = copy back (battle-tested) |
| Did the merge happen | census delta vs input-manifest union — never exit codes | — |
