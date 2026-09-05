# Archived campaign drivers

One-shot drivers and probes written for specific NA156/H2023, H2024 and
NA167 campaign questions, archived 2026-08-07 (owner-approved
quarantine). Each answered its question; the answers live in
`FINDINGS.md`, `HANDOFF.md` and the `testing/` plans cited below. None
of these are imported by live code (`modules/`, `wildscan/`, root
scripts, or `testing/test_*.py`) — the live importers of
`run_h2024_final.py` were retargeted to the promoted guard before the
move. They are kept for the patterns they encode (phase-skip resume,
census comparison, A/B fixture builds), not for re-running: hardcoded
campaign paths and superseded workflow assumptions mean they will not
run unmodified.

| Script | What it was for | Provenance (sections that cite it) |
|---|---|---|
| `run_h2024_v2.py` | Unattended H2024 v2 driver: fresh per-zone aligns for the five H2024 zones, regression check against the 2026-07-26 baseline, then `merge_zones.py` into one assembly project. | HANDOFF.md "Uncommitted" (2026-07-27 session, `HANDOFF.md:284`) and "Exact next commands" (`HANDOFF.md:321`, the `--skip_merge` invocation). |
| `run_h2024_final.py` | H2024 final chain (owner staging 2026-07-28): non-hull merge under the overlap pair-gate → hull assembly → confirmation → per-component models. | FINDINGS.md "Final review + owner notes applied (2026-07-29)" (`FINDINGS.md:2242`, the PARTIAL `merge_report.json` phase-skip trap). |
| `run_h2024_fused_models.py` | Follow-up to `run_h2024_final.py` phase 4: measure the FUSED components' metric scale (the gate had blocked them as UNMEASURED because ordinal B10 sidecars carry no image identity) and model the ones that pass. | HANDOFF.md "What changed to get here, and why the previous answer was wrong" (`HANDOFF.md:187`). |
| `probe_d7.py` | D7 + Q9 merge-mechanism probe: zero-overlap duplicate-path pair from the smoke minis, four merge cells isolating WHAT fused the NA156 duplicate-path components. Settled D7: fusion is content-driven. | testing/MERGE_TEST_PLAN.md "D7 probe wave (2026-07-24)" (`MERGE_TEST_PLAN.md:152`); FINDINGS.md "Merge & component growth" D7 entry (`FINDINGS.md:421`). |
| `relaunch_pd6.py` | Relaunch PD-6: zone_1 clean re-align with calibration sidecars restored and the Division distortion model — the decisive test of the 0.175 hull scale error. | FINDINGS.md "Merge & component growth" (`FINDINGS.md:701`, `FINDINGS.md:710`); HANDOFF.md "Fixed this session" (`HANDOFF.md:599`, AlignZone.bat manifest handoff). |
| `ab_orientation_priors.py` | Overnight A/B: do orientation priors (ON at 15°) cause the H2024 scale collapse (zone_3 c0 at scale 0.236)? | FINDINGS.md "ON2026 model-to-final + nav prep (2026-08-04/07)" → "Nav / orientation priors" (`FINDINGS.md:2502`, the yaw-convention/UTM conversion at its line 115); HANDOFF.md "LOOSE ENDS, RANKED" (`HANDOFF.md:98`); testing/PRIORS_DISTORTION_TEST_PLAN.md. |

Line references are as of the 2026-08-07 archive commit; section titles
are the stable pointers if lines drift.

## Arrived 2026-09-05 (agent-native consolidation)

| Script | What it was for | Provenance |
|---|---|---|
| `run_on2026_run3.py` | ON2026 run3 campaign driver (pool layout, per-eye COLMAP intrinsics via `-addImageWithCalibration`, M:\ON2026_run3). | FINDINGS `[ON2026]` 2026-08-28 entries; `RUN_CHARTER.md` on the data volume. |
| `run_on2026_union.py` | ON2026 union wave: merge the masts into the hull, one wreck scene, model. | FINDINGS `[ON2026] 2026-08-09`. |
| `run_on2026_wreck.py` | The retired ON2026 monolith driver (PRODUCT_READINESS must-fix 1 names it as the plan to replace). | HANDOFF 2026-08-07. |
| `run_workbench_night.py` | Overnight seed-growth campaign against the owner's live GUI instance via `archive/probes/NightGrow.bat`. | FINDINGS `[ON2026] 2026-08-11/12`. |
| `run_calib_ladder.py` | The A/B/C calibration ladder (control / groups / manufacturer XMP) via `archive/probes/CalibCellAlign.bat`. Verdict: manufacturer prior CONTENT collapses registration. | FINDINGS `[ON2026] 2026-08-09 calibration ladder VERDICT`. |
| `yellow_filter.py` | Yellow-tether contamination scorer (HSV band); calibrated 2026-08-11 on a 600-image sample (`testing/results/yellow_sample600*.csv`). Analysis only. | FINDINGS `[ON2026] 2026-08-11`. |

Not archived (deliberate): `testing/run_on2026_run2.py` - it is imported by
`testing/test_feature_merge.py` (its `stage_features` gate is under test),
so it stays a test dependency until that logic is promoted into
`modules/feature_merge.py`; `testing/run_zone9_tests.py` (live harness);
`testing/probe_cesium_depth.py` (owner: KEPT, re-runnable ion probe);
`testing/preprocess_variants.py` and `testing/scale_oracle.py` (live
tooling); `testing/results/` (cited by path from frozen reports); and all
`testing/test_*.py`.
