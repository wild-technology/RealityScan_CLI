# Optional post-batch temporal occlusion review

`modules/temporal_occlusion.py` proposes camera-fixed fringe exclusions from
unregistered image pixels. It never reads an old mask, inverts a mask, writes
source files, distributes sidecars, deletes data or confirms project settings.
White includes and black excludes, per the official mask semantics recorded in
`rs-reference/04-image-input-and-handling.md`, section 18.

The current algorithm is `temporal-occlusion-2`. Parameters are engineering
proposals, not owner approvals or validated semantic ROV detection. The helper
and controller own optional post-batch enablement, an explicit Skip path,
full-batch validation and distributing approved masks to all zone copies.

## Stable engine contract

```python
TemporalFrame(path, sha256, camera, family, timestamp_utc,
              frame_extent, width, height, registered=False)
TemporalMaskConfig(...)
parameter_schema()  # GUI/validation share key, type, min, max, step, default, units

blocks = plan_temporal_blocks(frames, block_seconds=config.block_seconds)
assessment = assess_temporal_occlusion(
    block_frames, source_root=owned_batch_source_root,
    batch_id=block['block_id'], selection_hash=current_selection_hash,
    config=config, cancelled=cancelled, progress=progress)
preview = write_temporal_preview(assessment, artifact_dir=review_directory)
# Only after explicit user acceptance of the exact preview:
approval = approve_temporal_mask(
    assessment, assessment_hash=assessment['assessment_hash'], confirmed_by=user)
master = publish_temporal_mask(
    assessment, approval, output_dir=owned_artifact_directory,
    selection_hash=current_selection_hash)
```

`frames` are `TemporalFrame` instances. `plan_temporal_blocks` returns dictionaries
with `block_id`, `membership_hash`, `members`, camera/family/extent/dimensions,
UTC `start_unix` and `block_seconds`. A member is a serialized `TemporalFrame`
plus `image_id`; remove `image_id` before reconstructing the dataclass.
Callbacks use `progress(stage, done, total, path)`; stages are `decode`,
`structure`, `complete`. Cancellation raises `InterruptedError` during input
reads between frames, structural analysis and exposure fitting. Existing shared
image helpers read/decode each image; cancellation does not interrupt an active
single-image codec call.

Planning must run once over the complete retained inventory, independent of
zones. Use the same block duration in planning and assessment. Canonical image
identity binds camera, family, verified extent, dimensions and SHA-256, not path
or zone. The helper must reuse the same assignment for every overlap copy.
Identical content with conflicting timestamps fails rather than receiving two
masks. A reviewed membership subset must not silently stand in for a larger
block. The engine can validate only the membership passed to it; the helper
must prove it is the complete current retained membership.

`frame_extent` is a verified sensor/crop/orientation identity. Dimensions alone
do not establish equal fields of view. For byte-identical approved originals,
the helper may record that verified unaltered-original provenance alongside
dimensions and identity EXIF orientation. Cropped/resized/warped/rectified
outputs need an explicit transform identity from their producing manifest.
Unknown transform provenance must be resolved or separated, not assigned a
generic common identity. Nonidentity EXIF rotation, mixed dimensions/dtypes,
alpha inputs and explicitly registered frames fail. A tilting head can move
within an unchanged pixel extent; temporal evidence and manual review remain
necessary. Never reuse a whole-dive mask based only on camera name.

## Evidence and guard behavior

Samples are deterministic time quantiles of distinct hashes. Proposed defaults are 96
samples, at least 24 distinct samples, at least 120 seconds of evidence and fixed
900-second UTC blocks. Configuration is serialized into the assessment hash.
The schema includes the newer integer controls: structure window 5..31, odd;
growth 0..24 analysis pixels; closing window 1..7, odd. GUI code must consume
`parameter_schema()` rather than assign all unfamiliar parameters a 0..1 range.
Cross-field constraints remain in `TemporalMaskConfig.validate()`.

The interior must exhibit changing scene detail after global intensity-offset
removal. Highly correlated central structure, insufficient motion or detail,
too few samples, too short a span, excessive candidate area and no supported
edge occlusion block approval. Fixed UTC boundaries limit time scope; they do
not certify that a Zeuss head remained still throughout a block.

Candidate construction uses locally normalized correlation to the temporal
median. Every sampled frame must support a structural seed; ordinary exposure
changes are tolerated without spatial registration. Seed-supported global
gain/bias fitting admits photometrically stable interiors. Growth stays within
a configured distance of seeds and within the reviewed fringe. Small gaps are
closed only where temporal support also exists. Final components must touch an
image boundary and contain structural seeds. Flat black water alone cannot seed
a candidate. Solid regions without sufficient support remain unmasked; there
is no broad contour fill or semantic inference.

The gain fit has numerical conditioning bounds: gain 0.15..4, absolute bias
at most 0.5 in normalized intensity. An invalid fit contributes no exposure-
corrected interior support; independently stable raw pixels and seeds remain
eligible. These checks do not prove that every candidate pixel is hardware.

Assessment results include sampled hashes/paths, canonical image IDs,
membership hash, configuration, metrics, blockers, status, candidate run-length
encoding and `assessment_hash`. `candidate_mask()` reconstructs a full-resolution
uint8 preview, strictly 0/255. A blocked assessment can be previewed but cannot
be approved or published. Preview files use `.preview.png`, not an importable
mask sidecar name. Preview overlays show red candidate exclusion on the first,
middle and last sampled frame; they are evidence, not proof for unsampled frames.

Approval binds exact assessment, selection and block. Publication rehashes all
sampled originals, creates a new master `.mask.png` and provenance, and returns
`output_path`/`output_sha256`. Provenance records all canonical member IDs, the
membership/selection hashes and sampled evidence. It is not a receipt that all
batch sidecars were installed. The helper must verify current full membership,
actual geometry hashes, each derived sidecar hash, storage and operation ownership
before publishing its own completion receipt. Naming at distribution is exactly
`<original image filename>.mask.png`.

## General acceptance versus reference evidence

The offline tests cover stationary scenery, exposure-only changes, textured
hardware under changing light, evidence-bounded solid interiors, an abrupt
hardware-position change, preserved interior scenery, fringe limits, content/
extent drift, grouping across overlap copies, invalid settings, cancellation,
approval binding and full-resolution binary publication. They do not establish
semantic accuracy on arbitrary dives.

The bounded H2101 reference used 96 distinct available hashes per family in one
15-minute UTC block, comparing N=24/48/96. The old illumination-stability version
under-detected hardware. Version 2 recovers aligned hardware boundaries and some
solid support, while leaving unsupported interiors unmasked. Original legacy
outlines are visibly offset in that block: overlap/outside-outline areas are
provenance diagnostics, **not recall or false-positive rates**. No old outline
was used to construct the new candidate.

N=96 is the proposed engine/GUI default: lower candidate area changes little
versus 48, and weak mid-camera regions contract in the tested block. It requires
more reads and analysis; this single block does not establish a universal
optimum. The default is not a threshold or project approval: Generate/Review
and explicit acceptance remain required, and existing approved project settings
are not changed. Real controls still needed include independently identified
hovering/stationary sequences, known head-tilt transitions, and independent
pixel-level hardware/scene labels. Sampled stability cannot certify unsampled
frames. The controller must expose partial-mask limits and keep user review.
