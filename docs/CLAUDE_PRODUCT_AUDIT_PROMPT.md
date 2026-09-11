# Independent adversarial audit: Hercules deployment product

Audit RealityScan_CLI as a general Windows desktop product, not an H2101 script.
Find reproducible defects, missing workflow capabilities and unsupported claims.
Runtime operation must not require an AI to infer choices or approve settings.
Return evidence and actionable findings; do not silently implement repairs.

## Scope and authority

- Read-only review of code, tests, documentation and existing evidence artifacts.
- No RealityScan launch/attach/control, data processing, source mutation or deletion.
- No settings application, install changes, commits, pushes or project saves.
- Main owns full-suite execution; never start a concurrent suite.
- Run narrow offline checks only with explicit authorization and isolated fixtures.
- Preserve other agents' edits; identify the exact working-tree snapshot reviewed.
- Current owner instructions supersede legacy AI-required workflow assumptions.
- That override does not waive source protection or scientific acceptance gates.
- Prefer raw source formats and primary documentation, then official repositories
  and websites; use forums only as secondary leads. Distinguish policy from evidence.
- Read docs/ARCHITECTURE.md, docs/PROJECT_FORMAT.md and docs/DEPLOYMENT_PLAN.md.
- Route RealityScan questions through docs/rs-reference/README.md and primary Help.
- Use [VERIFICATION_STATUS.md](VERIFICATION_STATUS.md) for current readiness.
- Use [EVIDENCE_LEDGER.json](EVIDENCE_LEDGER.json) for dated counts, hashes,
  contradictions, probe artifacts and exact scope. Do not repeat volatile totals here.
- FINDINGS and frozen history are discovery provenance, not verified authority.

## Reference case and settings authority

Reference source is E:/NA171/H2101, read-only; project/output is F:/NA171.
Cache is F:/NA171/proc/tmp/cache. Runtime must never hardcode these reference paths.
The reference project is F:/NA171/NA171_H2101.rovscan.
Owner-confirmed operating/navigation/camera approvals do not approve later stages.
Read current project-bound values and ownership records without modifying them.
The reference mask-deletion exception is still pending: do not delete anything.
Unknown-camera entries require explicit exclusion or a corrected separate delivery.
The GUI has no arbitrary per-image camera assignment, renaming or time correction.
Known four camera formats are deterministic; unknowns are not auto-approved/excluded.
Original masks are retired from processing, with no inversion or silent substitution.
The owner-selected Hercules camera profile is not empirical frame calibration.
Windows11/Python3.13 is the target; managed-runtime evidence is distinct from tests.
Runtime navigation is integrations/rovdataconcat, upstream baseline93ea56a plus
local fixes. .external/ROVDataConcat is a reference clone, not a runtime dependency.
H2101 evidence must remain separate from general deployment acceptance.

## Review method

Trace each workflow through public UI, controller, persisted state and executor.
Check normal behavior, rejection, cancellation, restart and stale/tampered artifacts.
A unit pass proves its assertions; a process exit or saved file does not prove
RealityScan used a setting, completed a stage or produced scientifically valid output.
Use exact file/line references and hashes for mutable code or external artifacts.
Report inspected evidence separately from owner-reported results and hypotheses.
Never label an unperformed live probe verified or infer approval from cached state.
Keep legacy compatibility checks exact; do not infer missing historical provenance.

## Product test matrix

| Area | Required adversarial checks |
|---|---|
| Project lifecycle | Save/Open/Save As, relocation, backup recovery, malformed schema, lease contention, interrupted attempts; opening never launches work. |
| Source inventory | Cheap shared dive window, resumable hashes/decoding, changed/additional inputs, layouts, unknown formats, duplicate bytes, filename collisions and out-of-window images; every decision attributable. |
| Navigation | SDYN full UTC versus filename date, checksum/quality rejection reasons, manifest-bound inputs, nav type/window coverage, units/CRS/datum/time and angular filtering assumptions. |
| Camera priors | Shared canonical14-column writer; native XMP focal delivery versus compatibility CSV column; profile overrides, pose flags, per-camera accuracies and frame/mount conventions. |
| Import/grouping | Actual production serializer/census, CSV/XMP ordering, repeated imports, physical-camera groups, overlap identity and deterministic block membership; use scoped readbacks. |
| Pre-batch review | Conservative quality screening, useful partial seabed retained, explicit cull choices and retained-density review; source/selection changes invalidate affected approvals. |
| Batching | Only approved retained images and matching priors, deterministic reuse, overlap accounting, source-byte preservation, no retired source masks. |
| Temporal masks | Canonical complete-inventory blocks, explicit accepted subset, no hidden selection, immutable artifacts, exact distribution receipts and honest sampled/blocked/skipped coverage. |
| Alignment | Current approvals and artifacts, native prior census, explicit mask usage, component accounting, no-op/error detection and output-based completion. |
| Merge/orphans | Pair-local geometry/uncertainty bounds, eligible/excluded identities, automatic native import/feature proof, no unrelated whole-pool fallback. |
| Checkpoints | Source exists, validated manifest/hashes, contained paths/no aliases, lock/quiescence refusal, staged restore, retained backup and rollback failure preservation. |
| Execution | One executor/planner, owned process identity, cancellation/recovery, stable-idle evidence, no overall RS timeout, no shared marker interference. |
| Installation/storage | Managed dependency imports, supported application/XML contracts, explicit repair choices, volume-aware reserves and separate project/cache budgets. |
| Results | Scientific coordinates and datum, scene reload, component/model census, save/export correctness; completion is not inferred from logs or process disappearance. |

## Settings dependency contract

Each block approval binds settings_signature([block]) to actual values and identity.
Global settings_hash remains exact whole-project attempt provenance.
Valid legacy approvals migrate in memory only with exact current global proof,
before edits, preserving signer/time and attempts; loading never auto-saves.
Changed or unprovable legacy approval content is revoked.
New geo payloads scope settings to navigation/cameras/georeference and retain
inventory/navigation/flight-log content guards. Legacy geo without scope requires
exact current global equality; a changed global hash requires rerun, not migration.
Shared settings_stage maps operating/budget to no completed-science invalidation,
science to align, cameras to georeference, navigation to navigation, stage-named
blocks to their stage and unknown blocks conservatively to inventory.
Late/resource edits preserve quality/density/mask reviews; batch affects workflow
and masks; early nav/geo changes invalidate dependent reviews. The edited block
still requires approval. Test both over-invalidation and unsafe stale reuse.

## Temporal acceptance and remaining proof

The revised engine, helper repairs and explicit native usage3 are implemented.
Fingerprints exclude mutable XMP/log outputs; canonical artifacts live in proc/masks.
Owned-mask replacement validates every old target before any deletion.
Engineering proposed defaults are96 samples, minimum24, span120s and block900s.
These are not project approval, a universal optimum or unsampled-image certification.
Optional per-block acceptance uses explicit selections: the UI always sends explicit
block IDs with none preselected; the helper maps the definitive actually applied
subset. Focused two-block partial-approval validation exists; see current evidence.
Journaled recovery, scoped ownership and incremental receipt repairs have focused
validation; audit their exact snapshot and integrated coverage before acceptance.
Test empty/partial/all selections, blocked IDs, tampering, stale plans and overlaps;
receipts, preview labels and alignment gates must agree on exactly applied images.
Review/Apply or explicit Skip is the post-batch decision before alignment.
Keep correct layer attachment separate from actual alignment/meshing use;
inpMaskOpts=3 does not establish texturing behavior or live use by itself.
Main visually inspected lower/mid N96 comparison sheets, three frames per family.
Lower red follows the vertical bar/right tool/bottom fringe but leaves significant
flat black hardware unmasked. Mid red follows left protrusions/bottom frame/right
slope, with a small upper-right candidate. This is useful partial visual evidence.
The wider experiment used384 distinct hashes; six displayed frames are not384
independently annotated evaluations. Offset blue historical outlines are not truth.
No quantified semantic accuracy or guaranteed scene preservation is established.
Independent hardware labels, genuine hover and confirmed head-tilt controls remain.
No native H2101 mask is approved or installed. See the ledger for artifact links.

Automatic orphan evidence integration is implemented through the production recorder
and normal executor. Actual component feature readback remains unverified; missing
proof blocks injection. Zero offered orphans permits ordinary merge. No real merge
or manual evidence is assumed. Audit implementation separately from application proof.
Use the latest full-suite snapshot in VERIFICATION_STATUS.md; subsequent changes
require their own checks and cannot inherit an earlier green result.

## Required report

Lead with prioritized reproducible findings and concrete user impact.
For each: claim, evidence kind, file/line or artifact/hash, reproduction, consequence,
minimal proposed correction and the smallest discriminating acceptance check.
Separate confirmed bugs, missing product capabilities and scientific uncertainties.
Provide a compact workflow acceptance matrix: implemented, offline-tested,
application-measured, scientifically accepted and still pending are distinct states.
Keep general product acceptance separate from reference-only H2101 evidence.
Do not turn a proposal, passing fixture or owner policy into a live verified claim.
