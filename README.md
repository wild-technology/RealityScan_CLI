# RealityScan_CLI — ROV photogrammetry pipeline for RealityScan 2.2

Processing pipeline for underwater ROV photogrammetry: extract and
georeference dive imagery, batch it into zones, and drive **RealityScan 2.2**
(Epic Games, formerly RealityCapture) through its CLI to align, merge, model,
export and publish. Designed to be **run by a Claude-guided workflow** with
the owner supervising and deciding at gates; every stage also runs by hand.

## Requirements

- Windows 10/11 (RealityScan is Windows-only; the data-prep scripts are
  Windows-oriented too). RealityScan 2.2 is auto-detected under
  `C:\Program Files\Epic Games\RealityScan_2.2\`; override with `RS_EXECUTABLE`
  or `"realityscan": {"executable": ...}` in `rs_settings.json`.
- Python 3.11+ and `pip install -r requirements.txt`. One or more CUDA GPUs
  (RealityScan uses all of them by default; pin with `RS_INSTANCE` +
  `RS_GPU_DEVICES`).

## Quickstart — the Claude-guided lane

Open Claude Code in this repo. The session hook prints the current state.

```
/charter                          intake: six questions to the owner, then sign-off
python rs.py preflight --charter <C>   what is still MISSING - questions, never guesses
python rs.py plan --charter <C> --validate
python rs.py run --charter <C>         short stages (extract, georeference, preprocess, batch)
python rs.py launch --charter <C>      RealityScan stages: writes a launcher, prints schtasks
python rs.py status --charter <C>      read-only: census verdict, RUN_STATE, markers, logs
python rs.py verify --workspace <ws> --json
```

Skills `/drive-run`, `/merge-zones`, `/finish-model`, `/publish-cesium`,
`/status`, `/handoff` walk each protocol; `rs-lookup` routes any RealityScan
question into `docs/rs-reference/`. Rules: `CLAUDE.md`; contract:
`docs/AGENT_OPERATIONS.md`; open decisions: `docs/DECISIONS.md`; per-box
setup and owner prompt habits: `docs/OPERATOR_SETUP.md`.

Owner habits that keep the lane cheap: start a driving session with
`/charter` and give the six answers in order in the first message; say
"status" for a read-only verdict; after `rs launch`, paste the printed
`/loop 30m ...` line so a small worker polls every 30 minutes.

## Quickstart — by hand

```
python main.py                                  interactive chain: extract -> georeference -> preprocess -> batch -> align
python merge_zones.py --components_root <ws>/aligned_components --images_root <ws>/batched_images_by_zone --output <ws>/merged ...
python run_models.py --workspace <ws>
python modules/export_deliverables.py --project <assembly.rsproj> --exports <ws>/exports --names <ws>/exports/components.names
python publish_batch.py --workspace <ws> --prefix "<wreck>"
python geoall.py --image-base-dir ... --rov-data-dir ... --output-dir ...    standalone georeferencing
```

Prompts remember the previous answer in `rs_settings.json` (repo root,
gitignored; `RS_SETTINGS_PATH` relocates it). Under `RS_NO_INTERACTIVE=1` or a
run charter nothing is prompted: a value is taken and announced, or the run
fails naming the flag. The archived console UI still runs:
`python archive/wildscan_tui/run_wildscan.py <ws>` (see its README).

## Repository layout

| Path | Purpose |
|---|---|
| `rs.py` | The one command surface (above). |
| `main.py` | Chain orchestrator over the `RSModule` framework; `RS_MODULES` / `RS_NO_INTERACTIVE` for headless runs. |
| `merge_zones.py`, `grow_zone.py`, `run_models.py`, `finish_model.py`, `run_decimate.py`, `publish_*.py` | Post-align drivers: cross-zone merge, within-zone growth, scale-gated modelling, attach-only finishing, triangle-budget decimation, Cesium ion / Nira publishing. |
| `modules/run_charter.py`, `preflight.py`, `run_plan.py`, `verify.py` | The agent-facing oracles: contract, missing data, plan, census verdict - all JSON with fixed exit codes. |
| `modules/realityscan_interface/` | The ONLY place RealityScan is executed: `realityscan_cli.py` (`RealityScanCLI`) and the `RS_CLI/Scripts/*.bat` workflows on the shared `:run` pattern; `RS_CLI/Metadata/*.xml` presets. |
| `modules/` (rest) | Domain logic: camera registry, flight logs and formats, prior groups, manifests, scale oracle, workspace census, Cesium placement. |
| `module_base/` | `RSModule`, `Parameter`, `SettingsStore`, scene checkpoint/rollback. |
| `geoall.py`, `poses2flightlog.py`, `decimator.py`, `timestamp_rename.py`, `organize_by_date.py` | Standalone data prep. |
| `flightlogs.xml`, `calibration.xml` | RealityScan import/export FORMATS, merged into the install dir by `modules/flightlog_format.py` (a missing format drops columns silently). |
| `docs/` | `ARCHITECTURE.md` (module map), `AGENT_OPERATIONS.md`, `DECISIONS.md`, `rs-reference/` (the RealityScan manual of record), design records, `history/`. |
| `testing/` | Unit suite (`python -m pytest testing -q`), living test plans, the zone_9 harness. |
| `archive/` | Functional but retired: the WildScan TUI, probes, campaign drivers, COLMAP, reference data. |

## How RealityScan execution works

One persistent headless instance per run, booted by `startRealityScan.bat`
with RealityScan's own monitoring hooks (`-writeProgress`, the ErrorWriter
process trigger, `-silent`); every operation goes through the `:run`
subroutine (`-delegateTo` -> grace -> `-waitCompleted` x2 -> abort on a
non-empty `errors_<instance>.txt`); `RealityScanCLI` adds the per-instance
lock, marker hygiene, progress tailing, resource tracing and verified
shutdown. Completion is never inferred from process names or results-log
growth, and success is never inferred from exit status: `modules.verify`
counts what landed on disk. Full treatment: `docs/ARCHITECTURE.md` and
`docs/rs-reference/11-automation-patterns.md`; every silent-failure mode:
`docs/rs-reference/12-failure-modes-and-race-conditions.md`.

Two facts new users hit first:

- **The align stage writes into the image folder it is given** (the default
  identity harvest moves pose sidecars out and rewrites the rest). Align only
  from trees the pipeline created, or copy your folder first. The charter
  declares source trees read-only and the write guard enforces it.
- **Preprocessing default**: CLAHE (clip 2.0, 8x8 tiles) on copies under
  `preprocessed_images/`; A/B-measured on zone_9 (baseline registered 0%,
  CLAHE 59.8%). Align on the copies, texture from the originals.

## Workspace layout (every run, under the results root)

```
raw_images/  preprocessed_images/  batched_images_by_zone/  aligned_components/
merged/  exports/  logs/  RC_projects/  _agent/{RUN_CHARTER.json, RUN_STATE.json, launch/, logs/}
```

`_agent/` is the only tree an agent may create scratch in or delete from.
