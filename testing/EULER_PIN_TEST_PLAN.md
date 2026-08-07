# Euler-order / camera-mount pin — test plan (C1)

Filed 2026-08-07. Cells P0/K0/KB runnable on the mtf_battery smoke scene.

## Question

`FlightLogParams.xml` carries `ifKGrp=2` and `ifKmode=0x0`. The Help
documents two import settings ("Euler angles order (YPR)", evaluated
right-to-left; "Camera mount", present whenever YPR is imported) but not
their config keys; neither key string exists in any file under the
RealityScan install, so the value mapping is compiled in ([H2023]
2026-07-26). Every 13-column import to date ran on whatever these
defaults mean. Root FINDINGS standing gate: no further orientation cell
until pinned.

## Prior knowledge (treat as fact)

- Staff composition (OndrejTrhan via 2026-07-26 forum mining): intrinsic
  Roll → Pitch → Yaw; Yaw about Z, Pitch about Y, Roll about X; pitch
  0 = looking down; YPR interpreted in NED.
- Our writers (georeference module + colmap_studio exporter) emit pitch
  0 = nadir / 90 = horizontal, yaw CW from +Y, roll about view axis —
  validated 0.4°/1.1° median against RS solved rotations (C-20260803-01).
- Candidate degeneracy at pitch 90 (horizontal) if the staff composition
  is in force — 24.9 % of ON2026 sits there ([ON2026] OPEN entry).

## Oracle design

Preferred oracle O1 (no alignment, ~2 min/cell): import the flight log
over the 32-image smoke fixture, then export XMP sidecars WITHOUT
aligning. IF RealityScan writes prior-pose XMPs, the exported rotation
matrices are a direct read of how the import composed our angles.
**O1 viability is itself cell P0 — probe before the sweep.** If P0
fails (no XMP without alignment), fall back to O2.

Fallback oracle O2 (~6 min/cell): align the smoke fixture with
orientation accuracies pinned tight (0.5°) so the solve is
prior-dominated; export component XMPs; compare solved attitudes to the
log's angles under each candidate composition. Weaker (vision still
pulls), so decision rule uses rotation-cluster separation, not absolute
agreement.

Known-good / known-bad calibration of the oracle: cell K0 (current
defaults) must reproduce the C-20260803-01 agreement (≤ ~2° median vs
our convention) if the staff composition is the default; a deliberately
scrambled log (yaw↔roll columns swapped, cell KB) must produce ~90°+
disagreement. If K0 and KB are not separable, STOP — the oracle is
broken, do not interpret the sweep.

## Cells

| Cell | Change (one variable) | Hypothesis |
|---|---|---|
| P0 | no-align XMP export probe | RS may export prior poses without alignment |
| K0 | baseline `ifKmode=0x0`, `ifKGrp=2` | matches staff composition |
| KB | scrambled log, baseline keys | oracle known-bad; large disagreement |
| K1–K5 | `ifKmode=0x1 … 0x5` | one of six YPR axis orders each; import may also ERROR on invalid values (that is a finding too) |
| G1, G3 | `ifKGrp=1`, `3` | grouping vs mount carrier — if rotations move, ifKGrp carries mount |
| G-GUI | owner sets the two GUI dropdowns, saves params, we diff | definitive key↔dropdown mapping; 1 minute of owner time, next time the GUI is open |

Decision rules: rotations identical across K1–K5 → ifKmode does not
carry Euler order (revisit ifKGrp / other keys). Rotations cluster into
distinct compositions → map each value, record in FINDINGS, pin the
production template explicitly. Any import error code → record in the
notes §3 table.

## Budget & exits

O1 path: ~20 min total for all cells. O2 path: ~60 min. Abort criterion:
any cell hangs the instance (`#timeout` state) — kill via
`-abortInstance`, record, continue with next cell; two consecutive
hangs → stop the sweep, report. All cells run on the throwaway smoke
scene; nothing touches production data.

## Outputs

- FINDINGS entries (established or refuted per cell) + backlog C1/C2
  updates; if the staff composition is confirmed in force, C2's 24.9 %
  import-side concern gets its own follow-up cell design.
- `FlightLogParams` templates gain explicitly pinned values + comment.
