# Native calibration + CSV pose delivery, 2026-09-11

## D1 evidence reconciliation

The completed v02 import-only matrix refutes the blanket argument that XMP
calibration sidecars can be retired because CSV focal and in-session groups
replace them. Its four physically distinct image references showed:

- CSV position, YPR and all six accuracies delivered with true availability
  flags, including the second import's +100 position/+1 YPR increments.
- CSV focal remained zero despite nonzero focal columns.
- Legacy Camera-element XMP left groups unassigned and focal readback was
  36 times the supplied value. Native xcr attributes delivered focal/lens/groups.
- Both exact CLI group setters and editInputSelection group setters delivered
  their sentinel IDs. A subsequent ifKGrp=1 import collapsed those groups;
  ifKGrp=0 preserved native XMP groups, even across the second import.
- Native pose XMP returned numeric poses but false absolute-pose/accuracy
  flags. Explicitly re-importing it after CSV reset those flags and accuracies.
- Rotation edit setters did NOT reproduce the requested YPR values, although
  their six accuracy setters did. This does not establish physical axes.

The implementation therefore changes fresh-input calibration delivery, not
`RS_LEGACY_XMP_IDENTITY`. Continuation, saved-scene and merge/export pose XMPs
remain separate. The new validator refuses pose-bearing fresh input without
editing it; georegister-only continuation skips the fresh-input contract and
its sidecar cleanup. Old single-family group evidence remains historically
valid within its scope; it did not test distinct cameras together.

## Production contract

Carver's existing `camera_registry.calibration_xmp(camera)` API now emits native
calibration-only XMP for the Hercules profiles. Existing full-intrinsics branch
values remain unchanged. `validate_calibration_xmp(content, camera)` is read-only
and rejects legacy/stale/pose-bearing fresh-input files. Sidecar writes still
belong to owned staging; these APIs never regenerate the source tree.

`prior_census.build_input_prior_manifest(images, flight_log, params)` checks
the exact selected image set, duplicate paths/content, masks, known cameras,
native sidecars, CSV coverage and finite positive accuracies, and requires
ifKGrp=0. It records image/sidecar/nav/params hashes and the effective project
profile. CSV focal remains compatibility metadata; XMP is focal authority.

`write_input_prior_contract(manifest, new_directory)` creates expected.json and
the actual report template, returning these environment keys:

```
RS_INPUT_PRIOR_MANIFEST  RS_INPUT_PRIOR_SHA256
RS_INPUT_PRIOR_TEMPLATE  RS_INPUT_PRIOR_REPORT  RS_INPUT_PRIOR_RESULT
```

The interface prepares this contract for the exact copied tree or explicit
pool image list. AlignZone imports CSV exactly once, exports the input report,
then invokes the canonical Python census before any alignment command. Missing
or false flags, missing/duplicate/unexpected images, unassigned/wrong groups,
wrong focal/lens, differing XYZ/YPR/six accuracies, changed input bytes, and
unexpected exceptions all block alignment. Failure JSON is durable and output
files are exclusive. The interface also rejects success without the matching
census result. Fingerprints include the camera profile, selected image/prior
content, expected manifest and measured census provenance.

All scientific geometry formulas remain unchanged. VERIFIED_INPUT_PRIORS
means the declared numbers reached the intended inputs; it does not prove the
physical-axis convention or authorize a full scientific run.

## Fresh v03 control (main prepares/launches)

The harness cell `production_calibration_csv` uses the ACTUAL registry serializer,
`build_input_prior_manifest`, production report template, and census CLI. It
imports CSV once with grouping zero and never aligns. It records the production
census result alongside the probe readback. Its dependency hashes include the
registry data/code, census, runtime and canonical batch scripts.
Production controls pin both project and output CRS from the input contract
after adding images. They then apply the canonical AlignmentParams entries,
followed by the recorded sentinel global accuracy overrides, before the single
CSV import. These intentionally different global accuracies are a negative
control, not the project's production accuracy settings. AlignmentParams and
the installed report function-set documentation are hash-pinned dependencies.

After dependencies are stable and runtime release verified:

```powershell
& 'C:/Users/jonat/AppData/Local/Programs/Python/Python313/python.exe' -B 'C:/Users/jonat/Desktop/CoyoteThings/RealityScan_CLI/testing/rs_prior_import_probe.py' prepare --project-root F:/NA171 --source-root E:/NA171/H2101 --install-dir 'C:/Program Files/Epic Games/RealityScan_2.2' --instance ROV_NA171_H2101 --run-name prior_import_probe_03 --reserve-gib 50 --cells report_control production_calibration_csv
```

Main reviews the newly returned hash and channels. Through the approved
scheduler/RealityScanCLI path, run `report_control` first, then
`production_calibration_csv`, each with the new manifest and hash. Never reuse
the immutable v02 directory/hash. This worker has not prepared or launched v03.

The batch-side census entry point is:

```
python -B -m modules.prior_census --input-manifest EXPECTED_JSON --expected-sha256 HASH --input-report REPORT_HTML --output NEW_CENSUS_JSON
```

Run from the repository root (AlignZone pushes that directory explicitly).
The runtime supplies RS_PYTHON; there is no second RealityScan launcher.

## Native mask approval and use

When RS_SELECTION_MANIFEST is present, native zone alignment requires
RS_OCCLUSION_MANIFEST and RS_OCCLUSION_MANIFEST_SHA256. It calls
project_occlusion.validate_external at entry and immediately before CLI dispatch.
The actual zone's resolved parent is passed as the whole batch root; the helper
must match it to the approved workflow root and validate current mask bytes.
RS_PROJECT_FILE is consumed by the helper for unambiguous active Save-As identity.
Legacy/import probes without a selection manifest do not enter this project gate.

Both folder and pool fresh imports converge on selectAllImages followed by
editInputSelection "inpMaskOpts=3", before CSV import and alignment. The setting
means both alignment and meshing per installed Help; saved-scene continuation
retains its input settings. The UI owner should label Apply as "Apply masks for
alignment and meshing". Carrying this setting through component export/import
into a merged scene remains a separate live verification requirement.

For a fresh probe, append production_mask_control to the prepare command's
--cells list, after report_control and production_calibration_csv. This third
cell uses the actual production serializer/census, creates four distinct binary
full-resolution masks beside its OWN image copies, explicitly sets inpMaskOpts=3,
and exports masks for exact filename association and decoded pixel comparison.
No source masks are copied. Mask creation/export space is included in the plan.

The empty export Configuration is an explicit compatibility hypothesis, shared
with the merge probe; export failure blocks this control without a scientific
conclusion. A successful verifier returns VERIFIED_MASK_ATTACHMENT_PIXELS.
No documented mask-option report variable was found in installed image reports:
option_readback remains UNOBSERVABLE_NO_DOCUMENTED_REPORT_VARIABLE. Exported
pixels do not prove feature exclusion, meshing, polarity behavior, or physical
camera axes. The independent comparator repeats actual census and mask checks
instead of trusting a manually written success field.

### v03 result and v04 discriminating import control

v03 report_control and production_calibration_csv passed independent numeric
comparison. The actual production census verified four active pose/accuracy
priors, groups 4/2/3/1, focal 16/16/16/23 mm, division and local Euclidean CRS.
The mask cell failed export with "There is no Mask layer available for export
[err:33640]" (2181038093); canonical runtime cleanup released ownership. Its
post-failure numeric prior analysis also passed, but mask attachment remained
unproven: the export error alone cannot separate attachment and export eligibility.

The v03 mask cell added only geometry paths individually. Installed
Help/en-US/tools/imglayers.htm says to load geometry and layer files together;
that control did not exercise the production folder import. v04 first runs an
explicit-attachment positive control: individual image adds, exact full-path
selection, setImagesLayer mask, inpMaskOpts=3, save and export. It then creates a
fresh scene using appIncSubdirs=true plus addFolder of the owned image-and-mask
directory, followed by the same inpMaskOpts=3 and actual production prior path.
Positive-control output is outside the recursively imported directory. Both
exports must match all four expected masks by identity and decoded pixels.
The same empty Configuration is used for both stages. The installed masklayer.xml
is an exporter descriptor (undistortImages="never"), not a dialog Configuration;
it does not justify inventing parameter keys. If the explicit positive fails,
attachment versus export eligibility remains unresolved. Run only report_control
and production_mask_control in a fresh v04 directory. Never interpret v03 as
evidence that production addFolder failed.

### v04 verified results and native workflow requirements

The authorized v04 scheduler run completed 2026-09-11 17:37:50 EDT. Manifest
SHA-256: 380da555d2ae76674944228c503062da48312a159c56a30f2983792dcbe9cfcc.
The independent comparison is COMPLETE_MATCH with zero violations. Both runtime
terminals are done/return_code=0/ownership_retained=false; the scheduler returned
0, and a subsequent OS check found no RealityScan processes or owner journals.
Every manifest dependency hash still matched at completion. The live dependency
freeze is released; probe manifests, inputs, reports and runtime logs stay immutable.

Measured evidence (reference fixture, not blanket scientific readiness):

- report_control: four inputs, false prior-availability flags, global sentinel
  accuracies and unassigned groups, exactly as required by the negative control.
- Actual native calibration-only XMP plus one ifKGrp=0 CSV import: four active
  pose/accuracy priors; all twelve position/orientation/accuracy numbers within
  1e-5; focal 16/16/16/23 mm; calibration/lens groups 4/2/3/1; division lens model;
  local Euclidean input CRS. Project and output CRS commands were also explicit.
- Explicit full-path selection + setImagesLayer mask: all four exported masks
  matched full resolution and decoded pixels. The empty Configuration exported
  masks successfully BEFORE alignment, so v03's error was not evidence that this
  configuration intrinsically requires aligned cameras.
- Fresh scene + actual production addFolder of geometry and inline masks:
  exactly four geometry inputs, with all four exported masks matching pixels.
  The same cell also passed the actual production input-prior census.
- The mask option was explicitly set to 3 in both stages. There is still no
  documented report-variable readback establishing that per-stage switch.

General deployment requirements supported by this evidence:

1. Owned fresh staging supplies native calibration-only XMP. Retain solved and
   continuation pose sidecars separately; never erase them to make fresh-input
   validation pass. CSV is pose/accuracy authority, native XMP is calibration,
   lens and focal authority. Keep ifKGrp=0 and the positive census before align.
2. For native folder import, stage approved image-and-mask pairs together and
   import the folder, with appIncSubdirs enabled where subfolders are present.
   Masks are layers, never independent geometry images or prior rows.
3. After adding fresh inputs, select all and explicitly set inpMaskOpts=3
   (alignment and meshing). Do not inherit the user's mask-use preferences.
4. With RS_SELECTION_MANIFEST present, require the approved occlusion manifest
   and SHA, validate actual batch mask bytes at entry and immediately before
   dispatch, and let validate_external resolve the active RS_PROJECT_FILE.
5. Individually added orphan images need the independently verified explicit
   mask-attachment lane; merely placing a mask beside an individually added
   geometry image is insufficient evidence of attachment. Carver owns this
   integration. Legacy pool/image-list behavior was not tested by v04 and must
   not be silently described as equivalent to native folder import.

Limits remain explicit: the folder stage ran in a new scene in the same process
after the explicit positive; a cold-process folder test was not performed.
Physical axes, UTM/grid conventions, feature exclusion, meshing, texturing, and
mask-option persistence through component merging were not tested. No alignment,
scientific reconstruction, source-tree write, or source-mask reuse occurred.

Evidence lives in the caller-selected project proc/tmp/prior_import_probe_04:
comparison_complete_01.json, v04_result_01.json, each cell's readback/census,
both mask export directories, and canonical runtime journals. v03 and its initial
comparator mismatch remain preserved. That mismatch was a comparator type bug
(registry string group IDs versus parsed integers); strict numeric normalization
fixed it without changing measured or expected numeric values. Its focused
comparator suite passed 44 tests; the final probe/comparator suite passed 70.

Code scope for this validation round: rs_prior_import_probe.py adds the real
production serializer/census, explicit CRS/settings/mask-use commands, positive
attachment and folder controls, pixel verification and dependency pins;
rs_prior_probe_compare.py compares the production lane and normalizes group ID
types. Associated focused tests cover both. The two rollback/template regression
files were corrected to supply complete native fixtures and require ifKGrp=0;
their adjacent census/guard run passed 122 tests. Production guards were not
weakened. No production runtime code changed during the live v03/v04 sequence.

### v05 cold-process folder-only reproduction

The owner-requested remaining reproduction completed 2026-09-11 17:47:19 EDT.
Manifest SHA-256: 365fe121476439d2d8e3534358c0160314427651236f360eb202a7115b055be8.
Only report_control and production_mask_cold ran. Independent comparison is
COMPLETE_MATCH, zero violations; the cold cell's real input-prior census and
all four exported-mask pixel comparisons passed.

This closes the v04 same-process limitation for native folder import. The cold
cell used new image paths that no previous cell referenced, a single new scene,
and zero setImageLayer/setImagesLayer commands. OS observation recorded the new
dedicated RS process (PID 60612, created 17:44:00 EDT), after report_control had
released its separate runtime. The canonical runtime required a new instance.
The approved persistent cache location was retained; this was a cold-process
test, not an empty-cache or fresh-install test.

Both canonical runtimes finished done/return_code=0/ownership_retained=false;
the scheduler returned 0. Final OS and journal checks found no RS processes or
owner journals. Every pinned dependency matched at completion. No alignment,
source write, feature-exclusion test, meshing test, or physical-axis validation
was performed. Mask option 3 was explicitly commanded, with its undocumented
readback limitation retained. Legacy pool-list import and component-merge
mask-option persistence remain outside this result.

The reusable cold cell is bound in the manifest as
mask_attachment_mode=cold_folder_only. Focused tests require exactly one scene,
folder import, no individual image adds or explicit attachment commands, unique
runtime channels, and no cross-cell reference to its paths. The final focused
probe/comparator run passed 79 tests. Code and tests were then frozen for main's
full-suite snapshot; only result artifacts and this findings document changed
during the live run. No additional runtime-source patch was needed: native fresh
alignment already uses the now-reproduced addFolder path.

Final evidence under project proc/tmp/prior_import_probe_05:
comparison_complete_01.json, v05_result_01.json, cold_process_observation_01.json,
the production_mask_cold input-prior census, all four exported masks, and the
per-cell runtime journals. Earlier v03/v04 evidence stays unchanged. The live
dependency pin period has ended; the full-suite code/test freeze remains active.
# Owned checkpoint restore and reload control (2026-09-11)

`rs_prior_import_probe.py` supports an opt-in `checkpoint_reload` cell, paired
only with `report_control`. This validates a four-image **local Euclidean,
import-only** saved fixture. It does not authorize or validate alignment,
models, UTM/geodetic placement, or physical camera axes.

Preparation takes `--source-root <immutable-prior-probe-root>` and
`--checkpoint-scene <saved-cell/readback.rsproj>`. The general harness verifies
the actual baseline input census, relative scene dependencies and explicit
local project CRS, and pins all files under the immutable baseline root.
It copies the scene bundle, images, masks and calibration/verification inputs
into the new cell's `live` directory. It rebases only its copied verification
CSV; this CSV is never imported in the reload cell.

Before copy, checkpoint, damage and restore, the canonical read-only
`RealityScanCLI._process_inventory()` must establish that no RealityScan
process exists. Unknown process-census status and scene locks refuse the step.
`checkpoint_scene` and `restore_scene` operate on the same newly owned scene
path. Only that copied scene file receives deliberately invalid bytes; those
bytes are retained separately. All scene/companion hashes must return to the
pre-damage values. Timings, quiescence observations, CRS and hashes are saved
in `restore_evidence.json`; failures preserve the fixture and checkpoint.
The checkpoint module and comparator are hash-pinned dependencies.

Prepare (does not launch RealityScan):

```powershell
python -B testing/rs_prior_import_probe.py prepare --project-root <project> --source-root <baseline-probe> --install-dir <RS-install> --instance <dedicated-instance> --run-name <new-name> --reserve-gib 50 --cells report_control checkpoint_reload --checkpoint-scene <baseline-probe/cell/readback.rsproj>
```

The existing scheduler sequence calls `run(manifest, reviewed_sha, cell)` for
`report_control` and then `checkpoint_reload`. The latter starts a fresh native
instance through the same `RealityScanCLI.run_batch_script` and canonical
`:run` wrapper. Its commands are limited to load, report export, image selection
and mask export. It never imports images/CSV/XMP, sets pose/calibration/CRS/mask
options, attaches masks, saves the scene, or aligns. The shipped Overview
report runs before custom reports.

Acceptance requires the actual four copied input paths, unaligned flags,
three active-prior flags, all 12 pose/accuracy values, baseline input CRS,
calibration/lens groups, focal and lens model, and four exact decoded mask
pixel comparisons. Saved project/companion bytes and the complete baseline
tree must remain unchanged. Native cell elapsed time includes loading and
readback exports; it is not an isolated load-time measurement. The saved
project CRS is checked from its pinned scene declaration; input CRS is also
checked through native report readback. Physical axes and mask feature/mesh
semantics remain unproven. A successful byte restore during preparation is
explicitly `NATIVE_RELOAD_PENDING`, never native acceptance.
