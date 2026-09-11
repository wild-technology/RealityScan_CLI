# Hercules desktop deployment work

Owner request: 2026-09-11. Baseline commit: `0c9224e`; full suite before
implementation: 1065 passed, one optional-data skip. Scope: RealityScan 2.2,
Hercules with three WCA cameras and Zeuss, expedition/dive projects, deterministic
processing without an AI operator. Navigation source: ROVDataConcat at
`93ea56a`, fetched from `wild-technology/ROVDataConcat`; its 83 tests pass.

Owner corrected the project root to `F:\NA171` during implementation; source
remains `E:\NA171\H2101`. Instance `ROV_NA171_H2101`, cache under
`F:\NA171\proc\tmp\cache`, 50 GiB reserve, and full processing after settings
approval are authorized. Duplicate content, filename conflicts, and images
outside the recorded dive window must be explicit inventory checks.

## Generalization contract

H2101 is a reference fixture, not a special runtime branch. No expedition,
dive, drive letter, fixture count, or observed UTM zone may be hardcoded into
processing logic. User steering is converted into reusable rules and regression
tests. Fixture evidence is recorded separately from product acceptance.

| Discovery | Required general behavior | Verification |
|---|---|---|
| Data spread across original and old zone folders | Inventory all eligible imagery, regardless of prior folder organization | Inventory fixtures and reference census |
| Identical copies and filename collisions | Hash before deduplication; block differing bytes under the same identity | `test_source_inventory.py` |
| Images outside a dive or without nav | Derive dive bounds from metadata; report every inclusion/exclusion decision | Inventory and navigation boundary tests |
| Dataset changes while work proceeds | Invalidate inventory approval and affected results on source change | Source fingerprint regression tests |
| Original mask sidecars mixed with imagery | Inventory for provenance but retire original masks from processing; never invert or automatically copy them into new batches | Retirement/inventory fixtures; exact source-deletion authorization remains separate |
| Optional new ROV masks | After batching, generate bounded temporal candidates, review and Apply or explicitly Skip before alignment; distribute only approved masks by canonical image identity | Real sampled coverage, no-occlusion/tilting-head controls, approval and distribution tests |
| Project moved to another volume | User-selected root, volume-aware reserve, relocation provenance, no fixed drives | Storage and project lifecycle tests |
| Per-camera prior corrections | Versioned Hercules defaults, applied by detected camera family, visibly recorded per step | Registry parity and settings approval tests |
| Nautilus TSV data named `.csv` | Content-validated import supporting known delivery suffixes; conflicting reports fail | Navigation deployment tests |
| One dataset passes | Report only the properties actually measured; retain outstanding deployment requirements | Evidence ledger and acceptance matrix |
| Unknown camera identity or incorrect names/times | Known four camera formats are deterministic; GUI has no arbitrary per-image assignment, renaming or time correction. Require explicit exclusion or a corrected separate delivery | Source acceptance remains blocked for unresolved entries; 61 reference unknown occurrences are not auto-excluded or approved |
| Almost entirely water frames harm batching | Automatically screen local reconstruction evidence before batching; review candidates, adjust tolerances, rerun, and explicitly confirm exclusions | Partial-seafloor, low-contrast, masks, noise and reference-image tests |

Image quality screening is conservative and nondestructive. Colour percentage
alone cannot identify an unusable frame: 80% water with 20% useful seafloor must
remain eligible. The confirmed selection, not the original unscreened tree,
feeds every subsequent batch/align/merge stage. Altering thresholds or selections
invalidates downstream fingerprints. Originals and review evidence remain saved.

Before batching, the user must confirm a spatial review of retained and culled
image density over the dive track. Layers can be toggled independently. Isolated
short bursts are culling candidates with camera/time/distance evidence, never
automatic deletions: separate sites and connecting imagery can be valuable.
Changing the selection or source inventory invalidates this review approval.

## Delivery order and acceptance

1. Audit raw navigation parsers, UTC alignment, projection and Kalman output;
   add explicit source/output/expedition/dive handling; run H2101 navigation
   without modifying its originals. Compare output to independent raw samples.
2. Inventory H2101 imagery, masks, existing sidecars and floating-point map.
   Stage verified imagery into `raw/`; retired original masks do not accompany it.
   Generated data belongs in `proc/` and
   temporary files in `proc/tmp/`. Refuse mismatched or ambiguous identities.
3. Present camera, navigation, grouping, alignment/merge and output settings
   as approval blocks. Record approval against the exact settings content.
   Changed values revoke that block's approval and only the dependent stage chain;
   global settings hashes remain exact attempt provenance.
4. Verify the installed 2.2 application and managed XML/import definitions.
   Review before repair; back up vendor files and preserve unrelated formats.
5. Resolve identity/pose precedence and grouping with documented evidence and
   discriminating live probes. Check overlap/orphan/camera accounting at each
   alignment/merge boundary; never accept a process exit as a result census.
6. Implement the versioned `.rovscan` project document, native desktop UI,
   deterministic controller, stage progress/logging, owned cancellation and
   restart from validated artifacts. Reuse the single science planner and
   RealityScan execution layer.
7. Validate corruption, missing inputs, time gaps, masks, coordinates, disk
   pressure, abort/restart, crash recovery and old project schema handling.
   Run complete suites serially under coordinated ownership. Runtime test locks
   are now isolated; earlier shared-lock contention is historical.
8. Reconcile evidence into maintained reference documentation, freeze the raw
   findings log, and produce the independent Claude product-audit prompt.

## Project design

Settings approvals are independent per block. `settings_signature(blocks)` binds
actual scoped values plus project/path identity; the shared `settings_stage` map
preserves completed science for operating/budget edits, starts science changes at
align, cameras at georeference, navigation at navigation and stage-named blocks at
their stage. Unknown blocks conservatively start at inventory. Late/resource edits
retain quality/density/mask reviews; batch changes invalidate workflow/masks; early
nav/geo edits invalidate affected downstream reviews. The edited block still needs
approval and execution still checks resources. New georeference provenance uses
navigation/cameras/georeference settings plus navigation/image content hashes.
Legacy geo records keep the exact global guard and require rerun if it changes.
Only exact-current-global legacy settings approvals migrate in memory, retaining
signer/time and attempts, without automatic file writes.

Focused evidence: 100 workspace tests passed in 3.46 s and four graph regressions
passed. A read-only check of the reference project preserved camera/nav/operating
approvals, signer/time, attempts and file bytes. The scope fix is reported complete:
152 UI/store passes in 19.37 s and 11 controller dependency/legacy passes in 8.79 s,
separate scopes. The final clean-baseline Windows suite passed 2854 tests with one
skip in 364.10 s after a fixture-only correction. See VERIFICATION_STATUS.md for
current acceptance limits; code is frozen for main's commit/push.
Automatic orphan evidence integration is implemented with 184 focused passes in
72.92 s; production recorder is modules/orphan_import_probe, with a testing wrapper.
The normal recorded executor runs after initial preflight, with explicit environment,
ownership exception preservation and final policy re-preflight. Zero offered orphans
allows ordinary merge. Actual component feature readback is still unverified and
blocks injection if missing; no real merge or manual evidence is assumed.

Mandatory pre-batch gate: source/camera census approval, conservative image-detail
screening with explicit cull/keep decisions, and final retained/culled density
review against the dive track. The backend checks content-bound approvals even
if a caller skips a GUI step. A changed inventory, tolerance, cull decision or
navigation artifact invalidates affected reviews and derived batches. Each
selection gets a distinct image tree and a flight log containing exactly its
retained exposures. Original masks are retired as processing inputs, not inverted.

Mandatory post-batch decision before alignment: optionally generate new temporal
ROV-mask candidates, review them and Apply, or explicitly Skip. Generation is not
application. Applied masks are white-includes/black-excludes, bound to the current
batch/selection and canonical image identities, and distributed consistently to
overlapping-zone copies. Source masks are never silently substituted. Report
sampled, unsampled, blocked, skipped and applied coverage; real tilting-head and
stationary/no-occlusion controls remain necessary. The revised temporal engine is
implemented; its strict predecessor is historical. Semantic acceptance remains open.

The current engineering PROPOSED temporal sample default is 96; minimum 24 distinct
samples, 120-second evidence span and 900-second blocks are unchanged. The bounded
reference report compares N24/48/96 on 384 distinct hashes/four families/one block:
N96 reduces questionable mid-camera regions and retains useful partial hardware
edges. This is not a universal optimum, project approval or native mask installation.
Independent hardware ground truth, genuine hover and confirmed head-tilt controls
remain acceptance requirements; retain historical N48 results as measured.

Physical source deletion is separate and still requires an explicit read-only
exception. The reference manifest contains **47,394 files / 1,429,816,122 bytes**,
all under E:/NA171/H2101. No source files have been modified or deleted.

The engine and Generate/Review/Apply/Skip integration are implemented, including
helper repairs: fingerprints exclude mutable AlignZone XMP/log outputs;
canonical masks/receipts live under proc/masks; new Apply replaces previously
owned masks only after all old targets pass validation. Explicit native
[inpMaskOpts=3](https://rshelp.capturingreality.com/en-US/tutorials/editselectioncommand.htm)
is implemented for alignment and meshing. Attachment and actual stage use
remain separate claims. V04 supplies actual application attachment/export-pixel
evidence for four sentinel images using explicit attachment and folder discovery;
independent comparison is pending. Actual feature exclusion and meshing use remain
unproved, with no documented option-report variable. No texturing claim follows.

The per-block acceptance extension has focused validation: 15 controller lifecycle
tests passed in 49.15 s, including actual-engine two-block partial approval with
only selected copies masked, including overlaps. The UI passes explicit IDs with
none preselected; the helper records the applied subset. Journaled recovery,
current-batch ownership and incremental receipt updates are now implemented with
69 scoped passes; the full-resolution guarded viewer is implemented with separate
desktop checks. The final full suite is green and code is frozen. V05 provides
four-image cold-folder attachment/pixel evidence
in a fresh process without explicit attachment; its independent comparison is
COMPLETE_MATCH with zero violations. Actual feature-exclusion/meshing evidence
remains pending. Mask-product acceptance is not final.

Synthetic public-controller validation used the actual engine, receipts and
ReviewStore across24 images/36 zone copies;12 shared overlaps matched, source
fixture bytes stayed unchanged and Skip cleanup passed. The revised real-image
detector demonstrates partial useful hardware edges, not semantic acceptance.
Historic outlines are offset: overlap is not recall and outside area is not a
false-positive rate. No real H2101 candidate is approved or installed. Current
test status is in VERIFICATION_STATUS.md; dated historical counts remain in the
evidence ledger. Subsequent changes do not inherit the earlier green full-suite result.

Orphan injection into a pairwise merge is spatially bounded: only images inside
either component footprint or between the two components may be offered, with
an explicit uncertainty margin. Unrelated orphan images remain available for
other attempts. Membership, positions, offered/excluded identifiers and reasons
must be attributable to the specific attempted pair. Runtime acceptance remains
pending controlled RealityScan probes; offline geometry tests alone are not a
claim that RealityScan consumed the offered images.

New-machine deployment has a dedicated implementation/audit scope covering
isolated dependencies, binary imports, strict RealityScan 2.2/version/XML checks,
storage and writable directories, and explicit installation/repair choices.

`.rovscan` is a versioned JSON document associated with the installed desktop
application, not an executable script. It records identity, paths, settings,
approvals, stage attempts, fingerprints and outputs. Save uses atomic replacement
and a previous-valid backup. Open never runs a stage. Restart creates a new
attempt and invalidates dependent results; it never silently overwrites a
deliverable. Source inventory and per-file identity live alongside the project
so resume decisions remain reproducible across application sessions.

The UI uses PySide6 and a controller interface. Qt handles presentation and
user choices; Python modules validate data and decide the allowed next actions.
The controller adapts approved project data into the existing planner rather
than constructing another alignment/merge algorithm.

## Evidence rules

The historical findings are leads, not an authority above raw inputs, shipped
Help or repeatable tests. Each material claim needs its scope, source, date and
verification method. Offline fixtures prove code behavior; they do not prove
RealityScan honored a command. Unsupported or contradictory application behavior
remains an explicit open item until a discriminating live observation exists.

## Parallel ownership

Navigation/integration: main. Project document and lifecycle: project worker.
Install/XML contract: installation worker. Independent adversaries cover camera
poses, merge/identity accounting, execution/storage, and evidence reconciliation.
Implementation workers own disjoint files; full-suite execution belongs to main.
