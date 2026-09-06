# Archived probe and one-off workflow scripts

Retired from `modules/realityscan_interface/RS_CLI/Scripts/` on 2026-09-05.
Each answered one question; the answer lives in `FINDINGS.md` (dated
entries cited below). All are CRLF and carry their own `::` header. None is
reached by any live driver, and `.claude/hooks/guard_rs_launch.py` refuses
to run them from a shell exactly as it refuses the live workflows.

| Script | What it settled | FINDINGS |
|---|---|---|
| `ProbeCalibGroups.bat` … `ProbeCalibGroups4.bat` | Whether `-selectImage` / `-setPriorCalibrationGroup` / `-addImageWithCalibration` take effect from the delegated CLI (6-image fixture, RSPROBE instance; the census, not exit codes, was the oracle) | `[ON2026] 2026-08-08 calibration-CLI probe results`; open decision D1 |
| `ProbeFlightlog5.bat`, `ProbeFlightlog6.bat` | Flight-log row matching (full path vs basename), params-GUID application (P1/P3/P4) | `[ON2026] 2026-08-08 flight-log probes P1/P3/P4`; `docs/FLIGHTLOG_ARCHITECTURE.md` |
| `ProbeExportSettings.bat` | Dump the live instance's full settings registry (`-exportGlobalSettings`) to learn key names | `docs/rs-reference/03-settings-keys.md` sources |
| `NightGrow.bat` | Attach-only seed-growth primitives against the owner's live GUI instance (never boots, never `-newScene`) - driven by `archive/campaign_drivers/run_workbench_night.py` | `[ON2026] 2026-08-11/12` |
| `CalibCellAlign.bat` | Calibration-ladder variant of `AlignZone.bat` with env-driven calibration hooks (`RS_ALIGN_SCRIPT` override) - driven by `archive/campaign_drivers/run_calib_ladder.py` | `[ON2026] 2026-08-09 calibration ladder VERDICT` |

Production workflow set (13 scripts, all in `RS_CLI/Scripts/`): `startRealityScan`,
`SetVariables`, `AlignZone`, `MergeZoneComponents`, `GrowZone`, `GenerateModel`,
`ComputeModel` (mesh-only front half for thin features), `ModelToFinal`
(attach-only back half), `ExportDeliverables`, `SaveProjectCopy`, `FlushCache`,
`GuiWorkbench` (owner's visible-GUI inspection workbench) and
`AlignImagesFromFolder` (deprecated; kept for `testing/run_zone9_tests.py`).
