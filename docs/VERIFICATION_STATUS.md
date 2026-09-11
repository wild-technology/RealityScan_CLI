# Deployment verification status

Updated 2026-09-11. **The general Hercules deployment is implemented and undergoing
live validation; the full audit and product acceptance remain open.** H2101 is the
reference dataset, not a dive-specific runtime solution. Detailed claim scope,
hashes, contradictions and probes live in [EVIDENCE_LEDGER.json](EVIDENCE_LEDGER.json).

## Current evidence

| Area | Evidence available | Limit / next acceptance check |
|---|---|---|
| Navigation | Complete vendored suite: **147 passed in 9.34 s** (reported). H2101 candidate has 54,344 finite pose rows, UTM 55N and no reported gaps greater than 1 s. | Absolute accuracy, clock/frame/datum and filter assumptions remain under audit. |
| Navigation integrity fixes | SDYN full-UTC/checksum/quality checks and exact manifest inputs implemented. Comparison of 41 DAT and 46 SDYN copies reproduced all 17,570 saved USBL rows with **zero changed filter inputs**. | No rerun indicated by those checked defects. Previously unselected originals and scientific validity are outside that comparison. |
| Report positive control | `prior_import_probe_02/report_control` contains populated custom and built-in reports, empty error files and `readback.json`; report execution succeeded. | Report transport success does not establish sentinel correctness or scientific validity. |
| v02 sentinel comparison | Sequence completed; `comparison_complete_01.json` has complete evidence for all 11 cells. `native_xmp_csv_g0` matches encoded delivery requirements. CSV-only focal is 0; grouping/reimport limitations remain. | Overall comparator is **BLOCKED**, tolerance `1e-5`; group and rotation control contracts are mismatches. Physical axes/grid heading and scientific acceptance remain open. |
| Owned recovery | Hashed `recovery_result_03.json` and journal record diagnostic wait exit 1, two stable-idle observations at revision 4, then exact owned-process and instance absence. | Recovery of that attempt only; no proof of prior correctness, restored-scene validity or universal safety of exit 1. |
| Reference inventory | Complete: **175,761 files**, worker `review_ready`, ended and released its OS lease. Main stored `ignore_existing`: all **47,394** original masks excluded from processing, **0 deleted**. | Inventory approval remains absent. Upper/starboard variant choice and 61 unknown-camera occurrences are unresolved; general detection and processing-set acceptance are not established. |
| Source mismatch investigation | Read-only audit matched all **175,761** known paths, with zero changed/missing known files, zero newer metadata and equal saved/current fingerprints. | No persistent mismatch found at audit time. The earlier failure's cause is **unknown**; transient changes are not excluded. |
| Managed installation | Runtime installation passed: 59 packages (56 runtime, 3 build); machine/project setup smoke reported ready. | 1 GiB project + 1 GiB cache smoke budgets are not full-processing estimates. |

Current artifact links:

- [v02 report-control readback](F:/NA171/proc/tmp/prior_import_probe_02/report_control/readback.json) and [sequence events](F:/NA171/proc/tmp/prior_import_probe_02/sequence_events.jsonl).
- [Detailed partial sentinel comparison](F:/NA171/proc/tmp/prior_import_probe_02/comparison_partial_01.json): exact cell/stage values, requirements, violations and evidence hashes.
- [Complete sentinel comparison](F:/NA171/proc/tmp/prior_import_probe_02/comparison_complete_01.json): all 11 cells recorded; overall acceptance remains blocked.
- [Inventory checkpoint progress](F:/NA171/metadata/reference_inventory/checkpoint_progress.json) and [source-mismatch audit](F:/NA171/metadata/reference_inventory/source_mismatch_audit_20260911T194650Z.json).
- [Owned recovery result](F:/NA171/proc/tmp/prior_import_probe_01/recovery_result_03.json).
- [H2101 navigation comparison](F:/NA171/metadata/nav_validation/20260911T193028Z_728772e2/final_code_comparison.json).

Process IDs and running states describe this update only. Artifact contents are
inspected where stated; reported test results and ownership details retain that
attribution. Neither running processes nor saved readbacks imply acceptance.

The metadata census counts **128,366 image occurrences / 118,101,633,652 bytes
(109.99 GiB)** within 175,761 files. These are summed occurrence bytes, not unique
images or unique-content storage. Completed reference verification places all
128,366 image occurrences in the dive window, zero outside, plus one map.

| Mount-family alias / optical camera | Composite unique count | Additional census facts |
|---|---:|---|
| `legacy_camlower` / cinema | 21,604 | Distinct lower mount retained |
| `legacy_cammid` / port | 21,467 | Distinct mid mount retained |
| `legacy_camupper` / starboard | 55,698 | 55,780 occurrences; 82 identical duplicates; 21,980 conflicting names reported |
| Zeuss | 26,990 | 29,454 occurrences; 2,464 identical duplicates |
| Unknown camera | 61 | Unresolved, not automatically excluded or approved |

Total **125,820** is unique by camera + basename + content, including unknowns;
it is not an approved processing set or a pure global content-hash count. Three
checked upper/starboard conflict pairs have 1975-square batched versions versus
3840x2160 `timer_still/upper` versions: distinct variants, not identical duplicates.
Owner choice of source version is pending; processing all variants is not approved.
Different-content flags affect **44,042 image occurrences across21,980 names**.
There are **4,323 unmatched retired masks, zero included masks**, and no other
reported image decode exceptions. Historical log wording suggesting camera
assignment is corrected by the UI formatter; no arbitrary assignment exists.
The [retired-mask census](F:/NA171/metadata/reference_inventory/mask_retired_census.json)
records the stored exclusion policy; physical deletion remains a separate pending
question. Worker completion lifts the inventory/checkpoint code freeze.

## Tests and current validation

Actual reference UI read-only smoke loaded **175,761 rows / 48,426 flagged rows**:
read6.662 s, hydration9.189 s, with **one2.335 s heartbeat gap** under concurrent
suite load, so this is not a freeze-free claim. All-files/flags filters took
0.136/0.142 s; scrolling5.2/2.7 ms. All five camera rows loaded; Zeuss requires
scrolling at the180-pixel table cap, a layout limit rather than missing data.
The [inspected provenance](F:/NA171/proc/tmp/screenshots/ui-review-20260911/REFERENCE-readonly-sources-20260911-175409-e703a3.json)
records unchanged SHA/mtime for the5681-byte project and162,482,968-byte inventory,
no submitted work, lease, source-byte scan or approvals, and zero denied Python
write attempts. This global-Python UI smoke is not managed-runtime/scientific acceptance.

Final full Windows suite: **2854 passed, 1 skipped, 0 failed in 364.10 s**
(main-reported, session 89101). The prior obsolete mock was corrected without
production changes; the clean-baseline rerun passed. Code and documentation are
frozen for main's commit/push. V05 is independently COMPLETE_MATCH; neither result
settles the owner decisions or scientific acceptance below. Historical test counts
remain in [EVIDENCE_LEDGER.json](EVIDENCE_LEDGER.json), not as current totals.
Scoped settings dependencies are implemented and included in the final offline validation.
Block approvals bind their own values; global hashes retain attempt provenance.
Exact-current-global legacy approval migration preserves signer/time and does
not save automatically. Legacy geo artifacts still require exact global equality
or a rerun. The reported read-only reference-project check preserved approvals,
signer/time, attempts and file bytes. Completed suites cover their own snapshots;
subsequent changes are explicitly excluded.

Both flight-log entry points share the canonical 14-column writer. Its focal
column is compatibility output; native XMP supplies focal in the measured lane.
V02 and the attach guard repair are complete, with scientific limits unchanged.
Runtime fixture locks are isolated; main coordinates full-suite execution.

## General product acceptance still required

- Complete the adversarial audit and close regressions with attributable tests.
- Resolve the complete v02 comparator's mismatches; retain cell/stage-specific
  transport, import precedence, grouping and rotation/unit conclusions. No alignment
  or physical calibration conclusion follows from import-only readbacks.
- Complete and resume the generic inventory, resolve exceptions and the earlier
  source-mismatch cause, and prove source-addition/layout/mask/duplicate/window
  handling through reusable checks. Checkpoint hits never restore user approval.
- Optional temporal masks are post-batch, white-includes/black-excludes, never
  inverted. Original masks are retired from processing. Generate/review/Apply or
  explicitly Skip is a required post-batch decision before alignment. Canonical
  grouping runs once over retained content across zones, by
  camera/family/verified extent and fixed UTC blocks (default 900 s, validated
  60-3600 s). The engineering PROPOSED default is now 96 sampled distinct frames,
  minimum 24 across 120 s; this is not project approval. A tilting head can move
  within a block, and samples do not prove unsampled stationarity. Peirce
  owns the engine/tests; main routes the helper to the runtime owner ending 64c5
  and owns controller/UI. Real-camera overlays,
  tilt-transition/stationary/no-occlusion controls, explicit review and accurate
  sampled/skipped/blocked/applied coverage are required before acceptance.
- Obtain explicit inventory/culling and retained-density review before batching;
  validate mask handoff and spatially bounded pair-orphan behavior end to end.
- Automatic orphan evidence integration is implemented: **184 focused passes in
  72.92 s**, no scoped failures. The controller uses the normal recorded executor
  after initial preflight, preserves ownership exceptions, passes explicit environment
  and re-preflights final policy. Production recorder is `modules/orphan_import_probe`;
  the testing entrypoint is only a wrapper. Zero offered orphans returns `None` and
  permits ordinary merge. Mapped masks attach explicitly; export runs only for a
  nonempty expected mask set. **Actual component feature readback remains unverified
  and blocks injection when missing.** No real merge was run; code completion is
  separate from application proof.
- Source GUI supports the four known camera formats deterministically, but has no
  arbitrary per-image camera assignment, renaming or timestamp correction. Unknown
  files require explicit exclusion or a corrected separate delivery. The 61
  reference unknown-camera occurrences are neither auto-excluded nor approved.
  This is an acceptance limit, not blanket source readiness.
- Validate navigation clock, frame, vertical datum and uncertainty independently.
  Finite output and a 6.8e-9 m inverse-projection discrepancy do not establish
  absolute accuracy. Kalman/angular-history, 3-sigma and depth-only bottom-lock
  questions remain open; those policies were not tuned by the integrity fixes.
- Prove actual scene reload after checkpoint restore and interrupted-transaction
  recovery. Hash/staging/rollback tests alone do not establish application reload
  or quiescence. `.lock` absence alone is insufficient; multi-file commit is not
  power-loss atomic. Selection/no-op, stage-completion and `-update` claims retain
  their separate ledger probes.

The temporal engine, Generate/Review/Apply/Skip integration, and helper repairs
are implemented. Fingerprints exclude mutable AlignZone XMP/log outputs;
canonical masks and receipts live under proc/masks; new Apply replaces only
owned masks after validating every old target before deletion. Explicit native
inpMaskOpts=3 is implemented for alignment and meshing. Application attachment
and actual stage use still require separate live evidence.

Per-block acceptance now has reported focused evidence: **15 controller lifecycle
tests passed in 49.15 s**, including the actual engine with two time blocks and
explicit partial approval. Only selected copies were masked, including overlaps.
The UI sends explicit IDs with none preselected; receipts identify the applied
subset. This is offline integration evidence, not final mask-product acceptance.

Helper repairs are complete and frozen: **69 scoped passes in165.35 s**, including
crash/foreign/history/cancel and100k-budget cases. Incremental journaling, exclusive
promotion by stable ID/hash, current-batch ownership, final compact receipts,
encoded-copy budgeting and UTC group fields address the identified defects.
Viewer implementation is complete and frozen: **146 desktop passes in22.29 s**, plus
**two checks after the last assertion in2.72 s**. It provides asynchronous full-res
viewing with containment/allocation guards, zoom clipping10-400% and a real-engine
three-row contact sheet without false approval. Separate scopes are not additive
or scientific acceptance. The final integrated offline suite is green as recorded above.

Native v03 used the actual managed runtime. Main inspected production readback
`VERIFIED_PRODUCTION_IMPORT`, saved at **21:21:31Z**, using the actual native
calibration serializer and census. Independent comparison is pending Ampere;
the result covers import-sentinel delivery, not physical axes. Manifest SHA256 is
`6e22823ba19bebd138f986bf0a9644f8d5d732d3611a544d4a27152138ea670c`.
The separate mask control failed during actual RS export at **21:25:23Z**, code
**2181038093**, with `ownership_retained=false`. That attempt did not prove attachment.
After `exportMasks`, the application reported **"There is no Mask layer available
for export [err:33640]"** (process `0x3f`). The probe imported geometry using
individual-add; auto-discovery versus explicit layer attachment and empty export
parameters are being tested. Cause is not established: neither a configuration
bug nor ignored sidecars is proved.
This failure does not invalidate the measured production calibration import.
V04 completed at **21:37:50Z** in actual RealityScan2.2/managed runtime. Main inspected
`VERIFIED_MASK_ATTACHMENT_PIXELS`: four distinct images match expected exports;
explicit `setImagesLayer` and folder discovery each have four matching exports.
Overall production verdict is `VERIFIED_PRODUCTION_IMPORT`. Manifest SHA256:
`380da555d2ae76674944228c503062da48312a159c56a30f2983792dcbe9cfcc`.
Ampere's independent comparison remains pending. This contrasts with v03's failed
individual-add control, without proving a universal individual-add failure or its cause.
**Feature exclusion and meshing remain unverified**; option readback is
`UNOBSERVABLE_NO_DOCUMENTED_REPORT_VARIABLE`. These are proof limits, not measured
stage failures. Attachment/export-pixel success does not approve real temporal
candidates, establish physical axes or complete scientific acceptance.

V05 completed at **21:47:19Z**: main inspected `VERIFIED_PRODUCTION_IMPORT` and
`VERIFIED_MASK_ATTACHMENT_PIXELS` for four real-image controls in a **fresh process,
folder-only import, no explicit attachment**. Runtime final success was true,
ownership was released and errors were empty. Manifest SHA256:
`365fe121476439d2d8e3534358c0160314427651236f360eb202a7115b055be8`.
This closes cold-folder attachment/export-pixel delivery for that fixture.
Ampere's independent `v05_result_01.json` is **COMPLETE_MATCH, zero violations**,
with **79 focused passes** reported. Four cold masks, absence of explicit attach
commands and actual calibration/census pass were confirmed; both runtime ownerships
released, scheduler exit0, no RS process/owner journals at final observation and
dependency hashes unchanged. Main inspected `cold_process_observation`, confirming
actual new PID creation under the per-run root. Feature exclusion and meshing
were not measured; real temporal candidates remain unapproved.

The [bounded real-image report](F:/NA171/metadata/quality_validation/temporal_20260911T202315Z/REPORT.md)
covers 384 distinct hashes/four families/one 15-minute block, with 12 N24/48/96
cases in 56.09 s including previews. N48 to N96 contracts mid candidate area
12.27% to 10.28%; lower changes 5.76% to 5.54%; upper/Zeuss remain blocked.
The proposed96 engine default is implemented, with minimum24/span120s/block900s
unchanged. Useful hardware edges remain partial. Offset historic outlines are
not ground truth: overlap is not recall and outside area is not false-positive
rate. Genuine hover, confirmed head-tilt transitions and independent hardware
labels remain acceptance requirements.

Main inspected three displayed frames each in the lower/mid N96 comparison sheets.
Lower red follows the vertical bar/right tool/bottom fringe, leaving substantial
flat black hardware unmasked. Mid red follows left protrusions/bottom frame/right
slope with a small upper-right candidate. These six displayed frames do not provide
quantified semantic accuracy or guaranteed scene preservation across the experiment.

Offline public-controller Generate/Apply/Skip validation used the actual engine,
receipts and ReviewStore on 24 synthetic images/36 zone copies: all12 shared
overlaps matched, original bytes stayed unchanged and Skip cleaned owned masks.
That establishes synthetic integration, not a real H2101 Apply. No real candidate
has been accepted or installed.

Physical source deletion still needs an explicit read-only exception. The proposed
manifest contains47,394 files/1,429,816,122 bytes in the E: source tree; no source
files have been modified. Source retirement from processing is already policy.

Official documentation rechecked2026-09-11 defines
[inpMaskOpts=3](https://rshelp.capturingreality.com/en-US/tutorials/editselectioncommand.htm)
as alignment plus meshing; this is not texturing proof.
[Polarity](https://rshelp.capturingreality.com/en-US/tools/mask.htm) is white include,
black exclude, with [layer naming](https://rshelp.capturingreality.com/en-US/tools/imglayers.htm)
using the original filename including extension followed by .mask.png.

## Reference configuration and owner policy

Source **E:/NA171/H2101** remains read-only. Project/output is **F:/NA171**, cache
**F:/NA171/proc/tmp/cache**, instance `ROV_NA171_H2101`, reserve 50 GiB.
Runtime navigation is vendored at `integrations/rovdataconcat` (upstream `93ea56a`
plus local changes); `.external/ROVDataConcat` is reference-only. These paths are
reference-case inputs, never hardcoded product defaults.

| Hercules family | Mount pitch down | Pitch accuracy | Yaw / roll accuracy |
|---|---:|---:|---:|
| Upper | 70 degrees | 10 degrees | 10 / 10 degrees |
| Mid | 20 degrees | 10 degrees | 10 / 10 degrees |
| Lower | 10 degrees | 10 degrees | 10 / 10 degrees |
| Zeuss | 40 degrees | 40 degrees | 10 / 10 degrees |

Position accuracy is 5/5/1 m, position weight 10, orientation weight locked at 2.
These are owner-selected profile defaults, **not empirical calibration**. Effective
values and overrides must be recorded per project. Saved reference project
`F:/NA171/NA171_H2101.rovscan` has operating/navigation/camera approvals; source-count,
alignment and other processing approvals are not inferred from those blocks.

## Evidence and history

Official contracts, code inspection, offline tests, inspected live artifacts and
owner policy remain distinct. Each conclusion applies to its named revision,
fixture and oracle. Historical navigation comparison hashes describe that earlier
code snapshot, not every subsequent planner revision. The original H2101 candidate
remains preserved; no fresh candidate was generated for the integrity comparison.

FINDINGS history is preserved verbatim in linked archives, with dated current
entries and a live-log cap of 900 lines. Neither the documentation nor the product
is blanket verified. See [DEPLOYMENT_PLAN.md](DEPLOYMENT_PLAN.md) for scope and
[CLAUDE_PRODUCT_AUDIT_PROMPT.md](CLAUDE_PRODUCT_AUDIT_PROMPT.md) for the full audit.
