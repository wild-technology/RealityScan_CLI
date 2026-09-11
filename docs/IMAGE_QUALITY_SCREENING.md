# Conservative local-detail screening

`modules/image_quality.py` assesses original image pixels and reports local
detail for review. It never deletes, moves, transforms, excludes, or rewrites an
input. It does not identify water or seafloor semantically and cannot predict
whether an image will reconstruct. No camera or campaign paths are embedded.

The controller must call this assessor during preprocessing, before optional
image enhancement, and present its results for user confirmation. Controller
integration and GUI controls are separate work; this module supplies the
assessment API and optional review artifacts only.

The current product flow screens initial imagery without source masks
(`mask_path=None`). Optional temporal ROV masks are generated and approved
after batching; retired source masks are not required delivery inputs. The
mask-aware assessor remains available for explicitly reviewed assessments,
including its insufficient-support refusal. This does not authorize source
mask deletion, automatic inversion, or automatic culling.

## Decisions and confirmation

| `decision` | `reason` | Controller treatment |
|---|---|---|
| `keep` | `meaningful_textured_patch` | Keep the whole image. One coherent patch is enough. |
| `candidate` | `low_texture_candidate` | Flag for review; retain unless the user explicitly confirms exclusion. |
| `review_required` | `sparse_or_weak_detail_uncertain` | Retain; weak or isolated detail conflicts with a low-texture assessment. |
| `review_required` | `insufficient_unmasked_support` | Retain; too little trustworthy area was assessed. |
| `review_required` | `edge_only_detail_uncertain` | Retain; detail is confined to the image border and may be equipment or useful scene. |
| `review_required` | `input_unassessed` | Retain; inspect `errors` for unreadable, corrupt, unsupported inputs or masks. |

Every result has `exclusion_requires_confirmation: true`. There is deliberately
no exclusion operation. A candidate is an assessment, never an instruction to
remove a frame. In particular, 80% uniform water with 20% useful texture must
remain included. Sparse backscatter can cause a conservative keep or uncertain
result; false keeps are preferable to losing a useful frame.

Since `local-detail-2`, insufficient valid-mask area or analysis coverage takes
precedence over a textured tile. A small hardware-shaped valid region cannot
certify that the scene was assessed. This produces `review_required`, never a
cull. Water is still valid image area: an unmasked image containing 80% smooth
water and 20% textured seafloor remains `keep`.

`local-detail-3` also distinguishes detail confined to a thin image border from
detail extending into the interior. The default border is 10% of each image
dimension (`edge_band_fraction`, configurable from 0 to 0.25; zero disables the
border distinction). The existing local detector is rerun on clipped interior
support with a blur halo, so a textured border tile cannot falsely claim interior
detail. Edge-only evidence returns `review_required / edge_only_detail_uncertain`,
never a cull candidate. Pixels are not cropped or removed. This is not a hardware
classifier: a thin sliver of real seafloor also stays included for review. Synthetic
20%-area scene patches at all four edges and corners still produce `keep`.

The main controller owns exact inclusion overrides and persistence. Bind an
override to the image identity, assessment fingerprint, explicit chosen action,
threshold values, and the inventory revision. On changed content, masks,
algorithm, engine version, or thresholds, recompute and show the changed
assessment before applying a previous exclusion. Preserve the recorded user
choice as history; do not silently reinterpret it. Threshold adjustment and
rerun must be available before applying confirmed exclusions to derived input
lists. Never modify the source tree to apply a choice.

Approval reuse must compare the recorded algorithm version with the CURRENT
`image_quality.ALGORITHM_VERSION`, not merely recompute a hash of the old payload.
Older versions require a fresh screen and review. A normalized mask's byte hash
and the explicitly approved polarity/normalization choice must both be bound
by the controller's review and selection provenance; changes invalidate quality,
density and staging approvals. This assessor treats nonzero as valid and never
infers or inverts polarity. Mask-review/controller APIs are owned separately.

## API

```python
from modules.image_quality import ScreeningThresholds, assess_image

assessment = assess_image(
    image_path,
    mask_path=mask_path,  # optional; None means no external mask
    thresholds=ScreeningThresholds(),
    artifact_dir=project_root / 'proc' / 'tmp' / 'image_quality',  # optional
)
```

Inputs are decoded read-only from their bytes, with size/mtime stability checks
across each read. PNG/JPEG and other formats are subject to the installed OpenCV
decoder. The assessor accepts unsigned 8-bit and 16-bit grayscale, BGR, and BGRA
images. Intensities are divided by the dtype maximum, without per-image range
stretching. A 12-bit signal stored in a 16-bit container therefore needs reviewed
project thresholds; it is not silently stretched. Images smaller than 32 pixels
on either axis or with aspect ratio above 8 require review. EXIF camera geometry
and orientation are not interpreted; masks must match decoded raster coordinates.

Masks must be single-channel, exactly match decoded image dimensions, and be
binary `{0, 1}` or `{0, dtype_max}`. Zero excludes and nonzero includes. Color,
soft, mismatched, missing, or corrupt masks produce `review_required`, never a
candidate. Zero-alpha image pixels are also excluded. The controller resolves
mask association and ambiguous mask formats before calling the assessor.

Invalid threshold configuration raises `ValueError` before reading the input.
Unreadable or unsupported images/masks return an incomplete review result.
Artifact errors are recorded separately in `errors`; they do not erase a valid
pixel assessment. An assessment result is JSON serializable without NaN values.

## Method and metrics

Analysis resizes the long edge to a common resolution and examines a primary
square tile grid plus half-tile shifted windows. The default is 64 primary and
49 shifted windows. Offsets protect small patches crossing grid boundaries.
Resampling can still lose subpixel detail; the scale tests below demonstrate
only the supplied fixtures, not general mathematical scale invariance.

Absolute contrast, gradient magnitude, and spatial support accompany corner
counts. OpenCV's GFTT `qualityLevel` is relative to the strongest corner, so
corner counts alone cannot distinguish noise from useful texture.
[OpenCV feature detection reference](https://docs.opencv.org/4.x/dd/d1a/group__imgproc__feature.html)

The decision uses original normalized grayscale, a 3-pixel median filter, a
13-pixel Gaussian filter with sigma 2, and Sobel gradients scaled by 1/8. Mask
support is eroded by 8 analysis pixels on each side to avoid artificial
mask-boundary evidence. Coverage includes support lost to erosion; fragmented
masks cannot certify coverage by shrinking its denominator.

For each window, `contrast` is the coarse intensity 99th minus 1st percentile.
`structure_fraction` is the fraction exceeding the absolute gradient floor.
`structure_span` is the maximum connected gradient region bounding-box diagonal
relative to the tile diagonal (regions need at least 8 pixels). GFTT operates
on coarse and raw intensities with at most 128 corners, minimum distance 4,
block size 3, and Shi-Tomasi response. A patch passes when coarse contrast and
gradient support pass their floors, and either connected span or coarse corner
count passes. One passing window keeps the entire image.

If no patch passes, raw intensity range above the contrast floor, or sufficient
raw corners with half-floor percentile contrast, vetoes a candidate and requests
review. This deliberately catches isolated bright pixels and may retain noisy
frames. No global blue fraction enters any decision; uniform low-detail frames
can be flagged regardless of hue.

Optional CLAHE supplies only `diagnostic_clahe_corners` (clip limit 2, grid 8).
It never enters the decision or replaces the source. CLAHE can enhance local
contrast and amplify noise; its contrast limit mitigates that amplification.
[OpenCV histogram equalization tutorial](https://docs.opencv.org/4.x/d5/daf/tutorial_py_histogram_equalization.html)

## Defaults

These are engineering starting values, **not field-calibrated thresholds**.
Overrides are explicit `ScreeningThresholds` values, recorded in every result.

| Field | Default | Meaning |
|---|---:|---|
| `analysis_long_edge` | 768 | Common analysis resolution; integer 256–1536 |
| `grid_size` | 8 | Windows per primary axis; integer 4–16 |
| `contrast_floor` | 0.006 | Absolute normalized coarse contrast floor |
| `gradient_floor` | 0.001 | Absolute normalized gradient floor |
| `structure_fraction` | 0.015 | Minimum fraction of gradient support |
| `structure_span` | 0.18 | Minimum connected span, alternative to corner count |
| `min_corners` | 3 | Minimum coarse corners; integer 1–64 |
| `corner_quality` | 0.02 | Relative GFTT quality level |
| `min_valid_fraction` | 0.25 | Minimum unmasked frame fraction for a candidate |
| `min_tile_valid_fraction` | 0.20 | Minimum usable tile fraction; also needs 64 pixels |
| `min_analysis_coverage` | 0.90 | Minimum assessed support / unmasked pixels |
| `diagnostic_clahe` | false | Add a diagnostic corner count only |

All fractional thresholds must be finite and in `(0, 1]`. Keep takes precedence
over insufficient total mask support when there is a positive coherent patch.

## Results, fingerprints and artifacts

Results include image/mask paths and SHA-256 hashes, algorithm version, every
threshold, OpenCV/NumPy versions, decision, reason, errors, limitations, frame
metrics, per-window metrics, and `tile_grid` indexing the primary windows.
Window bounds use analysis-pixel coordinates, not source coordinates; original
dimensions and analysis dimensions are supplied. `offset` identifies shifted
windows. Unassessed tiles omit texture metrics instead of inventing zero evidence.

`assessment_fingerprint` hashes canonical JSON containing image bytes' hash,
mask bytes' hash, whether a mask was requested, algorithm version, thresholds,
and engine versions. Renames with identical bytes preserve it. Any algorithm
change must bump `ALGORITHM_VERSION`. Cache only complete assessments and
validate current content and configuration first. A failed read with a missing
hash does not prove identity and must never authorize reuse or an exclusion.
The fingerprint describes the bytes actually read; the controller must detect
later input changes before applying a reviewed result.

Without `artifact_dir`, no files are written. With it, each call writes a fresh
unique subdirectory containing `assessment.json`, `thumbnail.jpg` (long edge at
most 384), and `heatmap.jpg` (analysis resolution). Returned absolute paths are
optional. Heatmap colors: green means coherent texture, yellow uncertain detail,
red low texture, gray unassessed. Green outlines include passing offset windows.
Colors represent measured detail states, not semantic classes.
For edge-only uncertainty, an orange rectangle marks the tested interior;
green border texture remains visible evidence rather than being erased.

The caller must validate the destination as owned project `proc/tmp` before
calling. The module additionally refuses destinations inside the image or mask
parent directory before creating anything. That local safeguard is not a
substitute for the controller's complete source-root ownership check. No source
or previous artifact is overwritten.

## Acceptance and limits

`testing/test_image_quality.py` uses deterministic synthetic fixtures for uniform
blue and non-blue images; 80% uniform/20% textured images; a weak 1.7% textured
patch; relative corners in uniform noise; sparse scatter and isolated pixels;
masked texture and fragmented/insufficient masks; corrupt inputs and invalid
masks; 8/16-bit signals; 0.5x/1x/2x scale comparisons; fingerprints; optional
CLAHE; and fresh artifacts without input changes.

The `local-detail-3` regressions add thin edge-only texture at four rotations
and 20%-area scene patches at every edge and corner. In a separate read-only
reference check, sample IDs `1-04`, `2-03`, `3-06`, and `4-07` from the existing
2026-09-11 bounded 40-image review all remained `keep` without external masks.
Their image hashes matched that review's pins; they had respectively 97, 97,
63, and 65 textured interior tiles. These are retention checks only. That
reference set has no independently established all-water negative, so it
cannot validate hardware-only detection or a water-only false-cull rate.

These tests are **not field validation**. No real imagery was culled or used to
estimate sensitivity, specificity, reconstruction value, or threshold accuracy.
Haze, smooth surfaces, tiny distant structures, compression artifacts, camera
noise, lighting, masks, and resampling can confound this proxy. Real acceptance
requires owner review of representative retained and candidate frames and
measurement of reconstruction outcomes. A keep decision does not establish
overlap, identity uniqueness, dive-window eligibility, or camera retention.

The general deployment controller must independently enforce deterministic
duplicate-content/identity checks, capture-window eligibility, mask association,
source inventory changes, storage ownership, and exact user overrides. Screening
does not replace these checks and does not hardcode an example dive's values.
