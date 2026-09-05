# COLMAP crossover — inventory & open reconciliation (2026-07-24)

COLMAP and RealityScan are COMPLETELY DIFFERENT workflows. This doc
exists to keep COLMAP material out of the RealityScan fact base while
tracking the one place the two lines genuinely interact (preprocessing
scope). Nothing here feeds the active pipeline; CLAUDE.md hard rule:
do not resurrect `archive/colmap/` into it.

## 1. COLMAP material in this repo (all archived, reference-only)

`archive/colmap/` (see `archive/README.md`):

| File | Purpose |
|---|---|
| `colmap_processor.py` | Hierarchical COLMAP reconstruction driver (per-zone SfM → align → merge → global bundle adjust), hardcoded to NA173_H2102 on E:, camera model by filename prefix. |
| `vocabtrainer_shipwrecks.py` | Most complete vocab-tree trainer (NA173 + Zeuss, 256k words). **Broken: pre-existing SyntaxError at line 710 (unterminated `try` in `main()`) — left as-is, archived.** |
| `vocabtrainer_shipwrecks2.py` | Near-duplicate with per-camera decimation enabled, 175k words. Parses clean. |
| `vocabtrainer_shallow.py` | Resumable variant for "NA173 Shallow", 50k words. Parses clean. |

The three trainers are near-duplicates of one script; consolidate if
ever revived. No Gaussian-splatting scripts existed at archive time.

Elsewhere in DataProcessing: **zero COLMAP content** (ROVDataConcat,
H2023 nav, and `NA156_old_vs_new_comparison.md` are all ROV-nav
material feeding both pipelines equally; the comparison doc validates
ROVDataConcat old-vs-new, not photogrammetry).

## 2. The COLMAP unified fact base (RECEIVED 2026-07-24)

The owner delivered the merged COLMAP fact base (colmap_studio ⊕
itsmagicIswear, C-*/F-* IDs) in-session on 2026-07-24; frozen copy:
`docs/COLMAP_FINDINGS_UNIFIED.md`. Canonical home is the colmap_studio
repo on the HONEYBADGER machine; the itsmagicIswear parent
(`C:\Users\jonat\Desktop\CoyoteThings\itsmagicIswear\FINDINGS.md`) is
frozen there. The RealityScan repo on that machine is checked out as
`Desktop\CoyoteThings\RS_main` (the fact base's F-20260723-33/34 cite
it by that name).

## 3. The one real crossover: preprocessing scope conflict

- LilyJean (COLMAP, 3,607 stereo pairs): adaptive enhancement AND fixed
  backscatter subtraction each reduced registration ~30% vs originals
  (F-20260721-02, F-20260723-01).
- This repo (RealityScan, NA173 zone_9): baseline aligns to NOTHING;
  CLAHE 2.0/8×8 rescues alignment — the basis for CLAHE default-on
  (recorded there as counter-evidence F-20260723-33).

Both results are real; scope unresolved. Confounds not yet separated:
different tool (COLMAP vs RealityScan feature detectors), different
data (stereo pairs vs ROV video frames), different water/turbidity.

**Reconciliation matrix Q-05 (queued, gated on colmap-studio research
completing):** zone_9 {baseline, CLAHE} × COLMAP, and LilyJean
{originals, CLAHE} × RealityScan alignment — judged on REGISTRATION,
not keypoint counts (F-20260723-03). Outcome decides whether
`preprocess_images` stays default-on, becomes per-dataset, or moves to
texture-only. If texture-only: RealityScan Image Layers
(`.geometry`/`.texture`/`.mask`, F-20260723-23) are the official
"originals align, corrected images texture" mechanism.

## 4. Other RealityScan-relevant claims carried via the COLMAP line

Second-hand (from the missing fact base, quoted in HANDOFF):

- Staff caution against over-masking (F-20260723-31) and Ultra detector
  sensitivity manufacturing noise points (F-20260723-26) — relevant to
  AlignmentParams choices and any future masking step on turbid imagery
  (the repo has no masking step: `masking.py` was a misnamed timestamp
  renamer, since renamed `timestamp_rename.py` 2026-08-07).
- No stereo-rig support in RealityScan (staff-confirmed through
  Aug 2025, F-20260723-27): Voyis-rig scale must come from GCPs /
  distance constraints / locked XMP — consistent with this repo's
  per-rig XMP-priors caution.

## 5. Operational note

`testing/NA167_SESSION_NOTES.md` records that an unrelated user COLMAP
python job may be running on the Honeybadger box — leave it alone.
