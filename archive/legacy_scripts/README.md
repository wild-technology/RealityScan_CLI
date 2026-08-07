# Archived RealityScan CLI scripts

`.bat` workflows and probes retired from
`modules/realityscan_interface/RS_CLI/Scripts/`. Each carries a
`::`-comment header at the top of the file stating why it was retired.
All are CRLF (a hard requirement for cmd label search — see the Windows
trap registry); keep them that way if they are ever touched.

## Arrived 2026-08-07 (owner-approved archive quarantine)

| Script | Why archived |
|---|---|
| `ProbeLockAlign.bat` | Hardening probe for cell U18 — RESOLVED as FAIL: `inpPose=3` is an Exact *prior*, not a lock; incremental align rejects it, so rollback stays the primary never-shrink mechanism (testing/ALIGN_MERGE_HARDENING_PLAN.md status update lines 15–21, 2026-07-23 9-boot probe session). |
| `ProbeSubsetAlign.bat` | Hardening probe for cells U1/U19/U2 — RESOLVED: selectImage matches literal paths only (the regexp form this probe relied on does not match), editInputSelection works, align honors enable/disable (same status update). |
| `ProbeSubsetAlign2.bat` | Inverse-ordering variant of the above (disable the complement instead of enabling the subset); same cells U1/U19/U2, same resolution. |
| `AlignImageList.bat` | Retired by owner decision 2026-08-07 with zero callers — superseded by `AlignZone.bat` + `GrowZone.bat`. Carries an unfixed HANDOFF SHOULD-FIX by design (no AlignmentParams application, no deselect before exports; HANDOFF.md 2026-07-24 clean-sweep review backlog). |
| `SequentialAlignGrow.bat` | Retired by owner decision 2026-08-07 with zero callers — superseded by `AlignZone.bat` + `GrowZone.bat`. Same unfixed-by-design HANDOFF SHOULD-FIX as `AlignImageList.bat`. |

## Earlier arrivals

| Script | Why archived |
|---|---|
| `AlignZonesSequentially.bat` | Pre-`AlignZone`/`GrowZone` sequential zone-alignment workflow. |
| `ExportComponentIdentity.bat` | Standalone identity-export primitive; superseded by the in-session identity capture inside the live workflows (ordinal-sidecar rule U20: stems require the live aligning session). |

Do not wire any of these back into `RealityScanCLI` or `main.py` — the
live workflow set is what `modules/realityscan_interface/RS_CLI/Scripts/`
contains.
