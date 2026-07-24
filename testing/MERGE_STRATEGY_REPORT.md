# Component-merge strategy report — NA167 zones 6/14/4

Empirical comparison of every way RealityScan 2.2 can turn overlapping
zone chunks into one complete georeferenced component, run 2026-07-22→24
on the dual-5090/192 GB box, GPU 0, instance RS1. Raw numbers:
`strategy_results.json`; provenance for every claim: `FINDINGS.md`;
cell-by-cell status: `MERGE_TEST_PLAN.md`.

Fixture: `zone_6 ←312 shared→ zone_14 ←239 shared→ zone_4`
(4,131 unique images, zero direct 6↔4 overlap — a single final
component requires transitive stitching).

## Headline results

| Strategy | Single component? | Registered | Wall time | Peak RAM |
|---|---|---|---|---|
| **B — sequential growth** (`add→log→align` per zone, one scene) | **YES** | 3,906/4,131 (94.6%) | 444 min | ≤ ~60 GB |
| **C — joint align** (all images, one scene) | **YES** | 3,904/4,131 (94.5%) | 169 min | ~165 GB |
| **A — separate aligns → `-mergeComponents`** | see merge mechanics below | per-zone 90–95% | 21–98 min/zone, parallelizable | ≤ ~60 GB/zone |

Quality is strategy-independent (94.5% vs 94.6% is noise). The choice is
resource-shaped: C is 2.6× faster than B but 2.7× hungrier, and joint
alignment extrapolates to ~700 GB for a full 19k-image dive — **chunking
is mandatory at production scale**.

## Merge mechanics (what actually fuses)

- **Zero shared cameras ⇒ no fusion, ever, silently.** All mechanism ×
  flag × path-form combinations (`-mergeComponents`, `-align`-as-merge;
  `sfmMergeGeoreferencedComponents` on/off; `sfmForceComponentRematch`
  on/off; duplicate-path and shared-path components) exit SUCCESS and
  leave components separate. Verify merges by camera count (pose-bearing
  XMP census), never exit status.
- **Georeference-based merging never manifested headless.** The
  documented "merge even without visual overlap" behavior did not occur
  for flight-log-prior components in any CLI-drivable form (caveat:
  prior-weighted vs ground-control-locked georeferencing may gate it).
  Consequence: **inter-zone image overlap is the only merge glue** —
  the batcher's overlap percentage is load-bearing, not insurance.
- **With shared cameras, `-mergeComponents` FUSES — confirmed.** The D6
  split-zone fixture (two zone_6 halves, 390 shared images, aligned
  solo to 749 and 342 cameras) merged in 56 min of real reconstruction
  ending in "Finalizing 1 component" (RealityScan app log; two
  components in, one out). D5-alt corroborates (11-fragment finalize,
  full 3,906 retained). Merge time is NOT instant when it works — budget
  ~1 h per merge of ~1–4k-camera pairs.
- **Components must be imported from their original export paths**
  (relocated `.rsalign` ⇒ permanent hang) — `.complist` workflow input.

## Operational discoveries that shape production

1. **zone_14**: deterministic solver bug (`MSS_STR001`, 4/4, data fully
   exonerated) in standalone alignment — but its images register fine
   inside larger scenes (B: 94.6% including all of zone_14).
   → Production rule: when a zone fails alignment, don't retry solo —
   grow it from an aligned neighbor.
2. **Incremental growth is state-sensitive**: z6+z14 (two-zone grow)
   fragmented to an 870-camera maximal, while z6+z14+z4 (B) held 3,906.
   → Verify camera counts after every grow step; a bad step is
   recoverable by re-growing with more context.
3. Alignment runtime varies ~3× with scene character at equal size —
   budget by zone, not by image count.
4. `#timeout` progress freezes up to 20+ min are normal in heavy solves;
   the pathological signature is `#timeout` from 0% with growing ETA.

## Production recommendation (D6-confirmed)

For a full dive (18+ zones, ~19k images):

1. **Align zones independently** — embarrassingly parallel across GPUs
   (multi-instance via `RS_INSTANCE`/`RS_GPU_DEVICES`; per-zone RAM fits
   many-per-box), 21–98 min per zone.
2. **Merge chains of components** via `-mergeComponents` over shared
   cameras, pairwise/progressively (~1 h per merge) — CONFIRMED working
   (D6). Requires zones built from a common image pool (imagelists or
   the same on-disk paths) so overlap images share identity; verify
   every merge by camera count (silent non-merge otherwise).
3. **Rescue failed zones by growing** from an aligned neighbor
   (B-style `add→log→align`), the verified workaround for solver-bug
   zones (`MSS_STR001`); verify counts after every grow step (a grow can
   fragment — finding 29).
4. **Batcher change this implies**: zones should reference a canonical
   image pool (hardlinks or imagelists) rather than per-zone copies —
   duplicate-path copies can never merge (no camera identity).

Trajectory quality levers stay as recommended in the fix-pass
evaluation: per-cruise camera map (orientation priors for unknown rigs),
per-cruise magnetic declination, poses2flightlog refinement loop between
alignment passes, and CLAHE preprocessing for still-camera zones.
