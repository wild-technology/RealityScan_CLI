# Priors v2 + distortion-model test plan — H2023 fresh data

Owner-requested 2026-07-25 ("have you tried running everything with
Division? make a test plan with this data to test exactly that"),
motivated by high residuals in the fresh-run assembly. Written after
the morning audit established five concrete defects/factors — this
matrix isolates them. Update cell statuses in place; graduate results
to FINDINGS.md.

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
| PD-0 | Z3 | re-run baseline post-format-install (13-col import now live, 1/1/0.1 acc) | orientation+accuracy priors alone change registration/residuals measurably | PLANNED |
| PD-1 | Z3 | global sfmDistortionModel=Division (sidecar models unchanged) | if P solves as division now, the global key IS the override; C may degrade (division too weak for rect?) | PLANNED |
| PD-2 | Z3 | per-image models honored check: global Brown3 + P sidecar division — inspect exported model per camera | decides whether per-camera models are POSSIBLE via XMP or the global key always wins (Q: does xcr:DistortionModel attribute-form work better than Camera: element?) | PLANNED |
| PD-3 | Z3 | priors v2 focals (C 16.4 / P 15.4 35-eq, Approximate) | tighter starting point → faster convergence, marginally better registration | PLANNED |
| PD-4 | Z1 | winner of PD-1/2/3 combined | ≥97.0% registration, residuals materially lower than baseline, ≤3 components | PLANNED |
| PD-5 | Z1 | full priors v2: 13-col import + 1/1/0.1 + division-for-P + empirical focals | the production configuration for the next dive | PLANNED |

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
