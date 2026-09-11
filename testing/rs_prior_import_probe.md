# Import-only prior probe (no alignment)

`rs_prior_import_probe.py` is a reusable preparation/readback harness. All
source images and installed files are read-only. `plan` writes nothing.
`prepare` copies four distinct physical-image references into a NEW directory
under the requested project's `proc/tmp`, creates sentinel CSV/XMP, report
templates and CRLF batches, and records hashes. Never stage in the source tree.
The source photographs test import mechanics; their recorded capture times are
not used to claim dive-window eligibility or validate navigation accuracy.

Each cell has its own copies and fresh scene. No `align`, `detectFeatures`,
`update`, component import, or XMP export appears in the generated workflow.
The image copies deliberately do not inherit adjacent source sidecars or masks.
The generated sidecars are experimental metadata, not deployment priors.

## Evidence of record

- Installed `Help/en-US/appbasics/reports_fav_images.htm`: `IterateImages`,
  `ExportImagePriors`, `inputImagePath/Name/Ext`, `inputYaw/Pitch/Roll`, all six
  `inputAccuracy*` values, `calibrationGroup`, `distortionGroup`, `inputF`, OPK.
- Installed `reports_fav_sets.htm`: `IteratorsFunctionSet` and
  `SfmExportFunctionSet` are explicitly enabled in the custom template.
- Installed `tools/xmpalign.htm`: xcr namespace `.../xcr/1.1#`, attribute
  CalibrationPrior=initial, CalibrationGroup, DistortionGroup, Rotation,
  FocalLength35mm, and Position element. XMP pose-accuracy attributes are NOT
  invented; distinct global and CSV accuracies test the actual readback.
- `docs/rs-reference/02-command-reference.md`: full-path selection,
  addImageWithCalibration, editInputSelection, exportReport.
- `docs/rs-reference/05-metadata-xmp-and-sidecars.md` Q9/Q13 and
  `13-camera-rigs-priors-and-orientation.md` Q24 preserve the unresolved claims.

The installed RUMI format GUID and all 14 column indices are checked read-only.
Missing/incompatible format is a stop. The repairing format helper is never
called. Canonical startup/abort scripts and the current AlignZone `:run` body
are reused and hashed; only RealityScanCLI launches the generated batch.

## Cell order

| Cell | Question / comparison |
|---|---|
| report_control | Shipped Overview positive control FIRST, then four imported filenames/priors in the custom macro report. Must pass before any other cell. |
| csv_i0_g0 / csv_i1_g0 | Same CSV, inheritance 0 versus 1; distinguish six CSV accuracy sentinels from explicitly set globals. |
| csv_i1_g1 | Automatic grouping 1 with three equal-focal fixed cameras and one distinct-focal Zeuss. |
| native_xmp_only | Documented xcr attributes: distinct positions, focals, calibration/lens groups and four proper rotation matrices. |
| legacy_xmp_only | Frozen original Camera-element calibration serializer, unaffected by later registry fixes. It never supplied pose/accuracy fields. |
| native_xmp_csv_g0 / native_xmp_csv_g1 | Read after XMP auto-import, first conflicting CSV, then a second CSV whose positions shift +100 and YPR +1. |
| csv_then_explicit_xmp | CSV first, then addImageWithCalibration for each existing path. Readback detects ignored updates or duplicate inputs; do not assume this command re-imports existing images. |
| group_controls | Exact selections plus setPrior*Group; read; editInputSelection group keys; read; CSV with ifKGrp=1; read. |
| rotation_cli_control | CSV import positive control, then distinct inpRx/Ry/Rz and six accuracy setters; read actual values. |

CSV values, XMP values, global accuracy values and setter values are separate
numeric families recorded in `probe.json`. Report output preserves actual raw
values and complete filename identity; missing macros, duplicate/absent rows,
unexpected aligned inputs, and missing numeric readbacks are never success.
Group IDs may renumber: compare physical membership equivalence, not only IDs.
`inputF` units must be interpreted from controls, not assumed equal to 35mm.

Rotation matrices are identity, Rx(30), Ry(20), and Rz(40)Ry(20)Rx(30). They are
proper orthonormal matrices by offline tests, but their axes are NOT declared
to be RS camera/world axes. Compare measured YPR/OPK to candidate transpose,
axis/sign and 180-degree-roll interpretations. No-alignment readback establishes
import representation; physical viewing axes still need an asymmetric target
or a known solved-camera matrix/projection oracle. Existing Euler-formula unit
tests alone do not settle that claim. Do not approve a full scientific run on
the basis of successful import or a nonempty report.

## Owner commands (Windows PowerShell, from repository root)

### 2026-09-11 report-template correction / v02 repeat

The original `prior_import_probe_01` report control failed at custom template
line 7, column 20: `identifier expected but '$' found` and `a numeric expression
expected` (exportReport 20567 / 2147942487). Its empty `added.html` provides no
scientific evidence. Preserve that probe directory and manifest unchanged.
Installed `reports_fav_images.htm` demonstrates
`$ExportImagePriors(inputIndex, ...)`: the numeric argument uses the bare
identifier, while emitted text uses `$(inputIndex)`. The corrected template
follows that example; live acceptance remains to be checked.

After main verifies runtime ownership release, prepare a NEW
`prior_import_probe_02` using the commands below with that run-name/path and
the NEW returned hash. Schedule ONLY `--cell report_control` for the minimal
repeat. It now exports the shipped Overview before attempting the custom
template, so a custom parser failure cannot suppress the positive control.
Do not run the remaining cells until both exports and complete readback pass.
The old manifest hash cannot authorize the corrected harness: dependency
hashes intentionally reject it. This correction does not change sentinels,
rotation formulas, import settings, or runtime ownership handling.

The v01 failure also exposed missing external cancellation channels. New plans
record `runtime_channels[cell]` with a unique UUID hex `RS_RUN_ID`, absolute
`RS_RUNTIME_ROOT=<project>/proc/tmp/<UUID>`, and `RS_CONTROL_FILE` /
`RS_EVENT_FILE` pointing to `control.json` / `runtime.jsonl` directly inside it.
`RS_ERRORS_DIR` points to `<runtime root>/markers`; the canonical runtime/startup
helpers own marker creation there, avoiding repository or install writes.
These are the canonical RealityScanCLI channels, separate from the probe input
directory. Planning/preparation records their paths without creating them.
Each `cell_details[cell].python_log` names the cell's `driver.log`.

Before constructing RealityScanCLI, `run` exclusively records `run_attempt.json`,
opens the new UTF-8 Python log, flushes/fsyncs the run identity and channel paths,
creates the new runtime directory, and applies the reviewed channel environment.
CLI log messages and unhandled constructor/workflow/readback exceptions are
logged; exception tracebacks are flushed/fsynced before exit. Existing attempts,
runtime directories and logs are refused rather than overwritten. Pre-launch
manifest/integrity refusals still go to scheduler stderr without creating a run.
The runtime writes events; no empty or placeholder control request is created.

For an operator cancellation, atomically publish this JSON to the exact planned
`RS_CONTROL_FILE`, using that cell's `RS_RUN_ID` and the actual current timestamp:

```json
{"run_id":"UUID_HEX_FROM_THIS_CELL","mode":"abort_current","requested_at":"CURRENT_ISO_TIMESTAMP_WITH_TIMEZONE"}
```

The existing runtime also accepts `mode: "after_step"`. Use `abort_current`
when requesting cancellation of the current operation/quiescence wait; an
after-step request is not evidence that the current operation stopped. Runtime
ownership checks determine which processes may be controlled. Read the planned
`runtime.jsonl` and `driver.log`, and let the runtime owner verify release before
another launch. This harness does not implement a second cancellation mechanism
or change runtime cleanup behavior. None of these additions retrofit v01.
Final v02 preparation must wait until the runtime owner's marker-directory and
canonical-helper changes are complete. The fresh dependency hashes must include
those changes; later dependency drift remains a launch refusal.

Read-only example validated against the current project and four E: references:

```powershell
& 'C:/Users/jonat/AppData/Local/Programs/Python/Python313/python.exe' -B testing/rs_prior_import_probe.py plan --project-root F:/NA171 --source-root E:/NA171/H2101 --install-dir 'C:/Program Files/Epic Games/RealityScan_2.2' --instance ROV_NA171_H2101 --run-name prior_import_probe_01 --reserve-gib 50
```

Main prepares by replacing `plan` with `prepare`. This is the FIRST command that
writes project data. It returns `manifest` and its `sha256`. Review the generated
commands/metadata and keep that exact hash. Do not edit artifacts after review.
Use a different run-name for a retry; partial evidence is never overwritten.

The approved scheduler action invokes the same Python executable with:

```text
-B C:/Users/jonat/Desktop/CoyoteThings/RealityScan_CLI/testing/rs_prior_import_probe.py run --manifest F:/NA171/proc/tmp/prior_import_probe_01/probe.json --expected-plan-sha256 HASH_RETURNED_BY_PREPARE --cell report_control --execute
```

Run the remaining cells individually and serially by changing `--cell`. Do not
invoke their `.bat` files or RealityScan.exe directly. The dedicated approved
instance must be idle; RealityScanCLI refuses an existing instance. It alone
owns markers and cancellation/ownership handling. Main retains scheduler budget
and live supervision responsibility; this harness adds no overall RS timeout.
The generated probe reuses the approved project cache and 50 GiB reserve.

Inspect a completed cell without launching RS:

```text
python testing/rs_prior_import_probe.py verify --manifest PROJECT/proc/tmp/RUN/probe.json --cell csv_i1_g0
```

`READBACK_ONLY_REQUIRES_SENTINEL_COMPARISON` is evidence availability, not a
scientific PASS. Compare field-by-field with the manifest's sentinels; keep
`INCOMPLETE_READBACK`, command rejection and unexpanded macros as explicit
blockers. Save the observed interpretation and full filenames before advancing.

## Heading correction regression

Both georeferencers now use the same resolved declination once for lever-arm
rotation and yaw. Module resolution uses the accepted sample and preserves raw
heading; standalone calls pass the explicit correction into estimation and
flight-log generation. `POSITION_HEADING_FRAME` records a true-north ENU
approximation. UTM grid convergence is deliberately not applied or inferred;
assessing its relevance requires a declared grid/true-north convention.
