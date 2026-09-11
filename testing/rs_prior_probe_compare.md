# Deterministic import-probe comparison

`rs_prior_probe_compare.py` is separate from the pinned probe harness. It reads
the reviewed manifest, verifies its SHA256, checks relevant pinned input hashes,
and compares each finished JSON readback with its raw HTML report. It prints JSON
to stdout and never launches RealityScan or writes project/source files.

```powershell
& 'C:/Users/jonat/AppData/Local/Programs/Python/Python313/python.exe' -B 'C:/Users/jonat/Desktop/CoyoteThings/RealityScan_CLI/testing/rs_prior_probe_compare.py' --manifest F:/NA171/proc/tmp/prior_import_probe_02/probe.json --expected-plan-sha256 b5ac5a535ad3b3f9c3c5f8ecb6eb2ee52e8deae6c455cfed6bfa107f6437611f --cell report_control
```

Repeat `--cell` to compare selected finished cells, or omit it for the entire
manifest. Missing readbacks are `PENDING`, not successful evidence. Exit 0 means
all requested control contracts match; exit 2 means missing/invalid evidence or
a control mismatch. This is an evidence-analysis exit code, not permission to
run the deployment or an instruction to stop independent experiment cells.

Each cell reports:

- `evidence_status`: COMPLETE, INVALID, or PENDING; hashes bind the inspected
  raw outputs and readback JSON. Filenames and stage coverage must match exactly.
- `control_contract`: MATCH/MISMATCH for explicit negative controls, CSV pose
  delivery, known focal inputs, native XMP metadata and exact group/setter controls.
  Unknown import-option semantics are not filled in from an enum guess.
- `stages.*.rows`: flags, measured values, matching sentinel sources, focal
  ratios, raw and normalized groups, calibration enum provenance, and raw OPK.
- `stages.*.production_requirements`: booleans for delivered position, YPR,
  per-camera accuracy, focal, and separate calibration/lens groups after CSV.
  In native-XMP/CSV cells, calibration focal authority is explicitly XMP while
  pose and accuracy authority is CSV. Pure CSV cells require their CSV focal.
- `production_delivery`: MATCH/MISMATCH/NOT_TESTED for the final stage's
  requirements. A successful negative control is NOT_TESTED, not deployment-ready.

`reported_pose_flags_active` is independent of numeric-field matches. Native
initial-XMP metadata may match its import contract while this remains false;
the result then carries an explicit unresolved absolute-prior-activity claim.

No field requires AI interpretation to calculate those results. A control match
does not necessarily satisfy deployment requirements: global accuracy inheritance
can be a measured experiment outcome while failing per-camera accuracy delivery.
The top-level `scientific_run_authorized` remains false. Physical camera/world
axes and grid/true-heading interpretation are separate explicit open claims.

## Comparison rules

All six accuracy fields are compared as a vector; mixed global/CSV values cannot
masquerade as a known source. Second-CSV position is first+100, YPR is first+1,
and accuracies/focal remain unchanged. Absolute tolerance is 1e-5 in reported
units, accounting for report rounding, with modulo-360 comparison for YPR.
Angles are not transformed between physical frames.

Both `-1` and observed uint32 `4294967295` mean unassigned groups. Four distinct
physical camera references require four assigned groups in each partition;
renumbered XMP groups retain membership validity, while explicit CLI/edit group
setter controls require their exact sentinel IDs. `ifKGrp` values are not given
unproven labels such as "group by focal". The returned partitions expose behavior.

Known text calibration enums are preserved. Other values, including live
`20640`, are recorded as `UNDOCUMENTED_ENUM`, not mapped to guessed labels.
The native/legacy XMP focal comparisons expose rescaling using an explicit
`focal_to_xmp_sentinel_ratio`; they do not guess physical focal units.

Negative controls require false position/orientation/accuracy/OPK flags and
the six global accuracy sentinels. Numeric defaults such as YPR 180/0/180 do not
become active priors. CSV delivery requires true pose flags and Cartesian CS;
per-camera accuracy delivery also requires `inputIsPriorAccuracy=true`.

## XMP pose activity limitation (2026-09-11)

Installed Help `appbasics/reports_fav_images.htm` lines 96, 116, 120, 124 defines
position, YPR, OPK and accuracy availability flags. Its selected-component note
at lines 78-79 applies to `inputIsAligned`/`inputCameraIndex`.
Shipped `Reports/ComponentAccuracyReport.html` lines 509-512 counts unaligned
georeferenced inputs via `inputIsPositionPrior`, and lines 675-678 gates their
display on it. This is evidence against dismissing false flags merely because
the probe has not aligned or selected a component; CSV controls return true.

The native-XMP-only control returns its numeric position, focal, group and
rotation-derived values but false position/orientation/accuracy flags. Therefore
the comparator does not certify active absolute pose/accuracy delivery from
those values. It also does not assert that XMP `PosePrior="initial"` is ignored
by alignment: installed `tools/xmpalign.htm` describes draft starting positions
that can adjust, without defining their relation to these report booleans.
An initial-pose optimization effect is distinct from reported absolute prior
activity and needs its own discriminating evidence.
