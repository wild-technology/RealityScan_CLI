# Owner decisions - the open and settled record

One row per decision the code cannot make. An OPEN row is a stop: no agent
flips it. Numbering continues from `docs/history/AGENT_NATIVE_ROADMAP.md`.

| # | Decision | Status | Where it bites |
|---|---|---|---|
| D1 | Do CLI prior groups (`-setPriorCalibrationGroup`/`-setPriorLensGroup`) take effect from the delegated CLI? main measured them silently non-functional (FINDINGS 2026-08-08); the sidecars line ran H2080/H2063 with them and never measured. | **OPEN** - settle with the solved-focal-equality oracle on the smoke fixture, record as `[RECON]` in FINDINGS | `RS_LEGACY_XMP_IDENTITY` default in `AlignZone.bat` and `realityscan_interface.py`; hard rule 0 |
| D2 | Base branch for the 2026-09 reconciliation | SETTLED 2026-09-03: `main` | - |
| D3 | Adopt `85c556a` (Zeuss 25/45, orientation hardness 2.0)? | **OPEN** - un-A/B'd science; preserved as tag `agent-native-execution-final` | `modules/cameras.json`, `georeference_images.MOUNTS` |
| D4 | Delete or archive the manual UI and campaign drivers? | SETTLED 2026-09-05 (owner): **archive, keep functional** - `archive/wildscan_tui/` runs; drivers and probes archived as citation targets | `archive/` |
| D5 | `rs_settings.json` remembered answers | SETTLED: machine constants only (`realityscan.*`); science and paths come from the charter; `RS_NO_SETTINGS_INHERITANCE` is on for every chartered child | `module_base/settings_store.py` |
| D6 | Retire the old checkout under `coyotethings\tools` and bring its five staging scripts (`stage_wca_stills.py`, `convert_dng.py`, `crop_upper_1to1.py`, ...) into `modules/staging/` | **OPEN** - not done; the scripts are not in this repo | roadmap sec.1.6 |
| D7 | Chain stages run as ONE `main.py` invocation (in-process hand-off between Batch Directory and Alignment) - `rs run`/`launch` preserve this; per-stage launching would change data handling | SETTLED 2026-09-05: preserved | `modules/run_plan.build_commands` |
| D8 | From an agent harness (`CLAUDECODE` set) RealityScan stages may not run in the foreground; `rs launch` + `schtasks` is the path, `--foreground` is the owner's override | SETTLED 2026-09-05 (mandate 6 made mechanical) | `rs.py` |
| D9 | Promote `stage_features` out of `testing/run_on2026_run2.py` into `modules/feature_merge.py` (the driver stays in `testing/` only because `test_feature_merge.py` imports it) | **OPEN** - low risk, not science | `testing/run_on2026_run2.py` |
| D10 | Per-stage `<stage>_report.json` for extract/georeference/preprocess/export (roadmap Phase 2 step 3) | **OPEN** - `RUN_STATE.json` records exit codes per stage meanwhile | `modules/verify.py` |
| D11 | The three legacy Cesium assets still sit at the sea surface (`2017323`, `2335997`, `2336618`); ion cannot reposition after tiling | **OPEN** - owner decision to re-publish from source | `publish_cesium.py` |
| D12 | `ModelToFinal.bat` drops simplify intermediates with `-selectModel <name>` + `-deleteSelectedModel`; a missing name is a silent no-op, so the delete lands on the working model (FINDINGS 2026-09-03, rs-reference 12 F-102) | **OPEN** - a production-script change; verify each select via `-exportReport` first, as `run_decimate.py` does | `ModelToFinal.bat` |
| D13 | `ModelToFinal.bat` pairs an unwrap with the texture preset only for `4x8k`; every other preset falls through to `Unwrapping_Simplified.xml` (1 × 16K), breaching the 4096 export cap (FINDINGS 2026-09-03, rs-reference 10 A4) | **OPEN** - default path is safe; fix the fallthrough or retire the other presets | `ModelToFinal.bat` |
| D14 | Reconciliation cadence: a FINDINGS entry stating RealityScan behaviour is added to the matching `docs/rs-reference/` file in the same session (Addenda section) | SETTLED 2026-09-05 (this pass reconciled everything through 2026-09-03) | `.claude/skills/handoff` |

## Recording a decision

Add a row here the moment the owner decides; cite the FINDINGS entry or the
chat quote in HANDOFF. An agent never fills the Status column of an OPEN row.
