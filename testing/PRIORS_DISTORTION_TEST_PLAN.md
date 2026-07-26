# Priors v2 + distortion-model test plan — H2023 fresh data

Owner-requested 2026-07-25 ("have you tried running everything with
Division? make a test plan with this data to test exactly that"),
motivated by high residuals in the fresh-run assembly. Written after
the morning audit established five concrete defects/factors — this
matrix isolates them. Update cell statuses in place; graduate results
to FINDINGS.md.

**STATUS ELEVATION (owner + reframe, 2026-07-25): this plan is the
MAIN LINE, not a side branch** — the week's downstream pathologies
(fragmentation, fusion camera drops, 0.55 m merge deformation, zone_2
/ orphan "unregistrable" verdicts, high residuals) plausibly share the
missing-priors cause (FINDINGS "GOVERNING REFRAME"). PD-4/PD-5 are the
gate for ALL further merge-machinery investment; re-run the
orphan/zone_2 verdicts and the D1/D2 georef-merge cells (see
SUPERSEDED-RISK flag in FINDINGS) after priors v2 lands. Every cell
reports QUALITY metrics first (residuals, prior-vs-solved deviation),
counts second.

## What the audit established (2026-07-25, all verified)

1. **The custom 13-column flight-log format was NEVER INSTALLED** —
   `FlightLogParams.xml` references GUID `{B438A617…}`, but the app's
   `flightlogs.xml` (stock 2.2) did not contain it: orientation (YPR)
   and per-image accuracies were silently dropped on every import to
   date ("Global camera prior settings" in the GUI — owner
   observation confirmed). FIXED: format merged into
   `C:\Program Files\Epic Games\RealityScan_2.2\flightlogs.xml`;
   verify it survives app updates.
2. **XY/Z accuracies were placeholder-loose** (10/10/1 m) vs the rig's
   real DVL/Paro figures (1/1/0.1 m). FIXED in the georef module
   (regenerate flight logs to take effect).
3. **The fisheye Port camera is being SOLVED AS BROWN3** despite its
   `division` sidecar prior — every exported P XMP reads
   `xcr:DistortionModel="brown3"`. Hypothesis: the global
   `sfmDistortionModel=Brown3` (AlignmentParams) overrides the
   per-image Camera:DistortionModel element. Help explicitly
   recommends Division for fisheye. This is the PRIME residuals
   suspect.
4. **Empirical calibrations from the fresh run's 4,405 solved
   cameras** (medians, tight spreads):
   - Cinema: 16.37 mm 35-eq (p10–p90: 16.24–16.53), k1 −0.053
     (prior said 17.0 — close; owner's "23 mm" is the physical lens)
   - Port: 15.37 mm 35-eq (15.23–15.52), k1 −0.324 (strong barrel —
     fisheye through a brown3 model; prior said 14.0, owner's 16 mm
     physical ≈ right)
   Calibration groups ARE honored (Camera:* tags echoed back in
   exports); grouping C vs P is already per-camera.
5. **Merged-scene solutions deform non-rigidly ~0.55 m median vs the
   zone's own solve** (ICP, fused hull vs zone_1) — merge-stage
   refits are not cosmetic; residual expectations must account for it.

## Fixture ladder (cost order)

- S: smoke minis (240 imgs, ~2 min/align) — mechanics only.
- Z3: fresh zone_3 (124 imgs, ~4 min) — cheap real-data cell.
- Z1: fresh zone_1 (4,540 imgs, ~90 min) — the decision cell.
Baseline for every comparison: the 2026-07-24 fresh run (Brown3-solved,
position-only priors, 10/10/1 accuracies): zone_1 4,405/4,540 (97.0%),
3 comps; zone_3 102/124.

## Metrics (oracle first)

Per cell: registered count + component count (manifest census);
**mean reprojection error** — extract per-camera from exported XMP
(`xcr:DistortionCoeficients` neighbors carry no residual: mine
RealityScan.log's per-align RMS lines; if absent, owner reads the GUI
alignment report — record source per cell); solved focal/k1 medians
per camera (xcr:FocalLength35mm); wall clock. Verify the residual
metric on a known-good/known-bad pair (S cells) BEFORE trusting it on
Z1 (oracle-before-iterator).

## Cells

Change ONE variable per cell; all others pinned at fresh-run values.

| Cell | Fixture | Variable under test | Hypothesis | Status |
|---|---|---|---|---|
| PD-0 | Z3 | 13-col import live + 1/1/0.1 acc + tight YPR acc (3-5°) | orientation+accuracy priors change the solve | DONE — **BAD CELL (two variables at once)**: 101/124 in FOUR comps [62,18,11,10] vs baseline 102/1. Superseded by the a/b split **[CONTAMINATED 2026-07-26: ran with Euler order and Camera mount UNPINNED - see FINDINGS contamination flag. Count stands; attribution to orientation priors does not.]** |
| PD-0a | Z3 | position-only, 1/1/0.1 (stock 7-col format) | tight position accuracies alone are safe | DONE: 101/124, ONE comp — safe, neutral |
| PD-0b | Z3 | + orientation at HONEST 15° YPR accuracy | orientation helps when honestly weighted | DONE: **109/124 (+7 vs baseline)**, comps [99,10]. Dose-response proven: 5°→fragments, 15°→gains **[CONTAMINATED 2026-07-26: ran with Euler order and Camera mount UNPINNED - see FINDINGS contamination flag. Count stands; attribution to orientation priors does not.]** |
| PD-1 | Z3 | global sfmDistortionModel=Division (on PD-0a config) | Division fits the fisheye; C may degrade | DONE: **112/124, best result**, comps [102,10]; BOTH cameras solved division — C did not degrade |
| PD-2 | Z3 | are per-image XMP models honored vs global key | — | DONE (from fresh-run data + PD-1): the GLOBAL key owns the model; Camera:DistortionModel element does NOT override. Mixed-optics rigs need a global choice (or an Epic feature request) |
| PD-1b | Z3 | Division + orientation@15° combined | additive gains | DONE: 112/124 [102,10] — same as PD-1; orientation gains not additive on Z3 (its weak frames rescued by either lever) **[CONTAMINATED 2026-07-26: ran with Euler order and Camera mount UNPINNED - see FINDINGS contamination flag. Count stands; attribution to orientation priors does not.]** |
| PD-3 | Z3 | priors v2 focals (C 16.4 / P 15.4 35-eq, Approximate) | faster convergence, marginal gains | PLANNED |
| PD-4 | Z1 | Division + orientation@15° + 1/1/0.1 | ≥97.0%, fewer comps | DONE — **COLLAPSED: 669/4540 (14.7%), ONE comp = the BOW box.** The hull band did not solve at all. Ran under heavy contention (owner tests, ~4 GB free) — partially confounded **[CONTAMINATED 2026-07-26: ran with Euler order and Camera mount UNPINNED - see FINDINGS contamination flag. Count stands; attribution to orientation priors does not.]** |
| M-DIV / M-DIV-ORI | smoke mini_a (hull-band strip) | Division alone / + orientation@15 | is hull IMAGERY incompatible with v2? | DONE — both PERFECT: 118/120, 1 comp each. Hull imagery is fine at single-pass scale; PD-4's collapse is SCALE- or ENVIRONMENT-dependent (orientation priors tearing across maneuvering passes, or memory pressure) **[CONTAMINATED 2026-07-26: ran with Euler order and Camera mount UNPINNED - see FINDINGS contamination flag. Count stands; attribution to orientation priors does not.]** |
| PD-4a | Z1 | Division + POSITION-ONLY (orientation off) | if ≥97% → orientation-at-scale is the poison; dense zones ship position-only | RUNNING |
| PD-5 | Z1 | full priors v2 production config | next-dive configuration | SUPERSEDED by PD-6 |
| **PD-6** | Z1 | Division + LOOSE 10/10/1 + sidecars intact | does the hull scale error survive a correct config? | DONE — **NO: hull scale 0.175 -> 0.981.** 4,394/4,540 in TWO components (hull 3,738 @ 0.981, bow 656 @ 1.076), 67.7 min. Registration unchanged vs baseline (-0.24%); metric validity restored; the hull's within-zone split was a configuration artifact |

### Bow 2x2 (2026-07-25) — the decisive isolation

Fixture: the 665-image bow component (known-good, scale 1.009), clean
calibration sidecars regenerated before every cell, position-only logs,
scale measured by `testing/scale_oracle.py`.

| Cell | Registered | Comps | Scale (maximal) |
|---|---|---|---|
| brown3_loose (10/10/1) | 665/665 | **1** | 1.049 |
| brown3_tight (1/1/0.1) | 662/665 | 2 | 0.886 |
| division_loose | 656/665 | **1** | **0.989** |
| division_tight | 659/665 | 3 | 0.826 |

**VERDICT: tight position priors FRAGMENT components and move scale
AWAY from truth** — reproducible on a healthy component under both
distortion models. Registration count barely moves (656-665), which is
exactly why counting cameras never caught this. The zone_1 "collapse"
is the same effect at scale, not a Division problem.

Root cause: the flight log's accuracy columns want END-TO-END per-image
position uncertainty, not the sensor spec. DVL 1 m XY / Paro 0.1 m Z are
instantaneous sensor figures; per-image error also carries timestamp
matching, nav interpolation, lever arm, and dive-long drift. Claiming
the sensor figure over-constrains the solve.

Applied: georef position accuracies reverted to 10/10/1 with rationale.
QUEUED: an intermediate ladder (3/3/0.5, 5/5/1) to find the real
sweet spot - loose is proven, not necessarily optimal.

**Interim v2-config policy (until PD-4a lands):** Division is validated
everywhere; orientation@15° is **PROVISIONAL, NOT validated** (downgraded
2026-07-26: every orientation cell ran with the import's Euler order and
Camera mount unpinned) on SPARSE zones (zone_2 8x,
zone_3 +7) and suspect at dense-maneuvering scale. The clean-slate v2
align stage is HELD for zone_1's config decision.

**Orientation-frame caveat (2026-07-25, open):** empirical mount
derivation from solved scenes is UNRELIABLE — zone_3-derived offsets
(C≈58° down, P≈11° down, tight IQR) conflict with a steady zone_1
strip (C≈−42°?!, also tight IQR): per-zone absolute orientation is
itself weakly constrained by position-only georeferencing (a
trajectory is near-1D; scene rotation about it is cheap), so
solved-scene "truth" is per-scene, not rig truth. Mount offsets need
rig ground truth from the owner (or a solve WITH orientation priors
at honest accuracy to anchor the frame first). Until then: import
orientation at 15° accuracy (proven helpful), do NOT tighten.

Decision rules: adopt division-for-P only if PD-1/PD-2 show P solved
as division WITHOUT degrading C (if the global key is all-or-nothing
and C suffers under Division, keep Brown3 global and pursue the
per-image mechanism; if per-image is impossible, escalate to Epic —
mixed-optics rigs need it). Adopt priors v2 focals if PD-3 is neutral
or better. PD-5 gates the next production alignment; the CURRENT
delivered assembly stays as-is (owner evaluation gate).

Non-goals: re-litigating CLAHE (Q-05 owns that); joint-align memory
(settled); merge mechanism (D7 settled).

## Standing corrections folded in

- FlightLogParams template still references `{B438A617…}` — correct
  now that the format is installed. If Program Files is ever wiped by
  an update, the stock 10-column `{97F08A22…}` (X,Y,Alt,3×acc,YPR) is
  the no-admin fallback: full position accuracies + orientation, only
  YPR-accuracy columns lost.
- Euler order / camera-mount convention for the imported YPR is
  UNVERIFIED (import dialog options exist; our params XML carries no
  explicit keys for them). PD-0 must include a GUI glance at one
  image's orientation prior vs its flight-log row (owner, 1 minute)
  before any Z1 spend.
