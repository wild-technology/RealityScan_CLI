# COLMAP unified fact base — FROZEN COPY (received from owner 2026-07-24)

PROVENANCE: pasted by the owner into the RealityScan_CLI merge session on
2026-07-24. Canonical home is the colmap_studio repo on the BIMBOX machine
(2× RTX 5090 box); the itsmagicIswear parent log lives at
`C:\Users\jonat\Desktop\CoyoteThings\itsmagicIswear\FINDINGS.md` (frozen)
on that machine. **Do not append here** — this copy exists so the
RealityScan documentation effort can cite the COLMAP side of the Q-05
preprocessing reconciliation and the cross-engine Zeuss anomaly (Q-07)
without cross-machine file access. COLMAP and RealityScan remain
completely separate workflows (see COLMAP_CROSSOVER.md).

---

# FINDINGS.md — unified COLMAP fact base (colmap_studio ⊕ itsmagicIswear)

Merged 2026-07-24 from two parallel research projects:
- **colmap_studio** (this repo): NA173/H2103a zone work, RH0041/42 Lake Ontario
  monolith, camera-model forensics, coordinate-system bugs, app tooling.
- **itsmagicIswear** (`C:\Users\jonat\Desktop\CoyoteThings\itsmagicIswear\FINDINGS.md`, now frozen):
  Sea-thru / underwater preprocessing, stereo-rig handling, mapper & solver
  selection on the LilyJean wreck. Its `F-*` IDs are preserved verbatim here.

**Discipline (unchanged from both parents):** one atomic entry per established
fact, dated, WITH how it was discovered and a source. Refuted hypotheses stay,
marked SUPERSEDED. New entries in this file use `C-YYYYMMDD-NN`; inherited
LilyJean entries keep `F-YYYYMMDD-NN`. Append at the moment of discovery.
This file is the raw fact base feeding the eventual documentation guide;
RealityScan material lives in `docs/REALITYSCAN_NOTES.md` (different engine,
different workflow — kept separate by design).

**Machine context (all entries):** BIMBOX — 2× RTX 5090 (sm_120), Threadripper
7980X (64c/128t), Windows 11, no admin. COLMAP 4.1.1 official CUDA
(`C:\Users\jonat\colmap\bin\colmap.exe`) + self-built CASPAR_ENABLED
(`C:\Users\jonat\colmap-caspar\colmap.exe`), both commit a0d785f (2026-07-17).

**Dataset shorthand:**
- **zone_9** — NA173/H2103a deep-sea wreck zone, 2,656 images, 4 physical
  cameras, UTM priors, `C:\Users\jonat\colmap_work\zone_9`.
- **LilyJean** — wreck, 3,607 rectified Voyis stereo pairs @1 fps, 2816×2816,
  turbid green water, artificial light. Rig baseline 0.16969684810099406 m,
  fx=fy=1895.6747569500258, cx=1444.9779663085938, cy=1386.6773681640625
  (shared PINHOLE). `M:\LilyJean\decimated_1s`.
- **RH0041/42 monolith** — Lake Ontario Voyis surveys, same camera serial
  180114031 and 169.7 mm baseline as LilyJean; 33,217 pairs / 66,434 images
  @2 fps, workspace `E:\colmap_work\monolith` (E: failing — see C-20260724-03).

---

## 1. Coordinates & georeferencing (the founding bugs)

- **C-20260721-01** — Dense reconstruction MUST run in LOCAL coordinates.
  Float32 at UTM northing ≈9e6 quantises to ~1 m inside the CUDA kernels →
  geometric depth maps empty, fusion returns 0 points. Georeference the FINAL
  cloud only. Discovered via zone_9 fusion returning 0 points; root-caused by
  magnitude analysis. Source: HANDOFF §1 bug 1.
- **C-20260721-02** — COLMAP 4.x keeps AUTHORITATIVE poses in `frames.txt`
  (rig format); `model_converter` DISCARDS `images.txt` pose columns on
  TXT→BIN. Any external model transform must transform points3D, images AND
  frames (`t' = t − R·T` on RIG_FROM_WORLD). Discovered when a
  points+images-only translation left local points with UTM cameras
  (PatchMatch: "no source images", "Configuration has 0 problems" — `__auto__`
  source selection filters on triangulation angles from the inconsistent
  geometry). Detection artifact: images.bin/frames.bin byte-identical to the
  UTM originals. Fixed in `pipeline/translate_model.py`; verified by direct
  reprojection (median 0.497 px over 31k observations, 0 points behind
  cameras). Source: HANDOFF §1 bug 2.
- **C-20260721-03** — Depth/normal maps computed on a UTM workspace are
  IRRECOVERABLY poisoned even though storage is camera-relative: they were
  computed with float32-degraded relative geometry. Verified: photometric
  depths vs sparse triangulated depths at same pixels → median 50% relative
  error, 2% within 5%. SUPERSEDES the earlier claim "camera-relative depth
  maps remain valid". After fixing coordinates, re-run PatchMatch from
  scratch — NOTHING computed on a UTM workspace is reusable. Source:
  HANDOFF §1 bug 3.
- **C-20260721-04** — `colmap model_transformer --transform_path` mangled the
  translation when tested; use `pipeline/translate_model.py` instead.
  Source: CLAUDE.md rule 1 (session 2026-07-21).

## 2. Underwater preprocessing vs SfM

**Policy as of 2026-07-24: geometry on ORIGINAL imagery; color-correct only at
texturing time. Exception: if the raw baseline fails to align, A/B with
REGISTRATION as the metric.** (Two LilyJean experiments + one external paper
vs one RealityScan counter-case; reconciliation experiment Q-05 pending.)

- **F-20260721-01** — Sea-thru (Akkaynak & Treibitz, CVPR 2019) is
  physics-based inversion of a revised image-formation model; NO training
  step; requires a per-pixel metric range map (authors used SfM ranges).
  Community implementations: hainh/sea-thru (MIT), Teragion/Sea-Thru-Impl.
  Source: paper + repo review, 2026-07-21.
- **F-20260721-02** — Adaptive enhancement (per-frame percentile
  normalization, gray-world, CLAHE, Sea-thru) on all 3,607 LilyJean left
  frames: +53% SIFT keypoints but −32% raw matches, −9% verified pairs,
  largest model 1,078 vs 1,353 registered, 22 vs 17 fragments. Identical
  COLMAP settings (pycolmap CPU, sequential overlap 10, PINHOLE fixed).
  Source: `seathru_test/colmap_test/sfm_original/stats.json` vs
  `sfm_seathru/stats.json`.
- **F-20260721-03** — Consecutive-pair SIFT tests (6 pairs, 1 s apart) showed
  the OPPOSITE sign (3.8× RANSAC inliers after enhancement). Pairwise tests
  do NOT predict full-SfM outcomes; descriptor repeatability across hundreds
  of frame combinations is the binding constraint. Source:
  `seathru_test/eval_results.json` vs F-20260721-02.
- **F-20260723-01** — Even NON-adaptive preprocessing hurts geometry: fixed
  backscatter subtraction J = I − B(z) (site-calibrated, metric stereo depth,
  zero per-frame statistics) collapsed registration 1,978 → 1,388 stereo
  frames (55% → 38%), reproj 0.549 → 0.751 px, identical global_mapper
  settings. Source: `seathru_test/rig_comparison.json` (A vs B).
  *QA note 2026-07-24: counting/arithmetic verified correct against
  rig_comparison.json; caveat — the global_mapper commands were hand-typed
  and not persisted, so "identical settings" rests on log-consistency checks
  (loaded-pair counts match per variant), not a pinned script.*
- **F-20260723-02** — Adding despeckle + stereo-derived open-water feature
  masks (variant C) changed nothing vs subtraction alone (1,388 frames,
  0.770 px): the harm is subtraction destroying low-intensity far-field
  texture, not residual marine snow. Ratio test + RANSAC + rig constraint
  already cope with suspended particles. Source: `rig_comparison.json` (B vs C).
  *QA note 2026-07-24: mechanism attribution has a confound —
  `stereo_depth.py` fills invalid/open-water pixels with a p95 far-field
  depth before B(z) subtraction, so some harm may be depth-artifact-induced
  rather than pure texture destruction. The B≈C equivalence itself stands.*
- **F-20260723-03** — Matcher-level stats understate mapper impact: −4%/−7%
  verified pairs became −30% registration. Judge preprocessing by
  REGISTRATION in a full reconstruction, never keypoint or pair counts.
  Source: `rig_comparison.json` db_stats vs largest_model.
- **F-20260723-04** — Workflow conclusion (2 independent experiments,
  mono + rig): SfM/geometry on ORIGINAL imagery; apply color correction
  (site-calibrated Sea-thru) only for texturing/orthomosaicking. Source:
  F-20260721-02 + F-20260723-01. *QA note 2026-07-24: the original
  "0.2 s/frame @2048 px" figure has no surviving measurement artifact;
  process_all.log implies ~0.12 s/frame amortized over 24 workers (~2.8
  s/frame serial incl. SGBM + JPEG I/O). Directionally unchanged (cheap
  enough for texturing-time correction); re-measure before publishing.*
- **F-20260721-04** — Site-calibrated water model: median Sea-thru
  backscatter/attenuation coefficients over 16 frames are stable and
  physically sensible (red veiling ≈ 0; red attenuates ~3× blue in green
  water); 55× faster than per-frame fitting and radiometrically consistent
  across a survey. Params: `seathru_test/site_params_stereo.json`.
  *QA note 2026-07-24: "radiometrically consistent" holds only for the
  water-model step — the shipped application code (`process_all.recover`)
  ALSO applies per-frame percentile stretch, gray-world WB, and CLAHE. For a
  truly site-consistent texture pass, apply the water model without the
  per-frame adaptive tail.*
- **F-20260723-13** — External corroboration: Summers & Jones
  (arXiv:2507.21715, July 2025) tested color-correction and deep-learning
  enhancement vs raw across SIFT/SURF/ORB/KAZE/FAST + SLAM: enhancement
  generally DEGRADES feature matching; raw preferable for feature-based
  SLAM/SfM. Independent method+data, same conclusion.
- **C-20260721-09** — colmap_studio's own recipe
  (`pipeline/preprocess_underwater.py`: LAB → CLAHE(L) → Otsu mask → masked
  gray-world, JPEG q95, CPU multiprocess, 30k imgs ≈ 10–15 min on ~55
  workers) smoke-tested on zone_9 camlower: wreck contrast clearly better,
  marine snow amplified. Judge any A/B on verified CROSS-PASS matches, never
  keypoint counts. Motivating literature: Adams et al. ISPRS X-4-2024 (3–26×
  keypoints on wrecks). STATUS: adoption gated on the Q-05 reconciliation;
  burden of proof has flipped against preprocessing. Source: HANDOFF §4,
  RESEARCH_30K §2 + REVISIONS #1.
- **F-20260723-33** — CONFLICTING RESULT, different engine+imagery: RS_main
  (RealityScan 2.2 CLI, `Desktop\CoyoteThings\RS_main`) validated CLAHE
  2.0/8×8 pre-alignment on zone_9 imagery where the UNPROCESSED baseline
  "aligns to nothing"; preprocessing is that pipeline's default. The
  "enhancement hurts" verdict is COLMAP-SIFT-on-LilyJean evidence and does
  NOT automatically generalize: candidate explanations are engine (RealityScan
  applies internal tone mapping pre-detection), detector, and imagery regime
  (zone_9 baseline catastrophically flat vs LilyJean baseline that aligns
  well). Reconciliation defined in Q-05. Source: `RS_main/CLAUDE.md`.
- **F-20260723-34** — Priors can hurt: RS_main's NA167 zone_13 A/B measured
  XMP calibration priors REDUCING registration (96.3% → 89.6%, Zeuss camera);
  generation now opt-in. Lesson class: constraints/priors must be validated
  per dataset, never assumed beneficial. Source: `RS_main/HANDOFF.md`.

## 3. Stereo-rig handling

- **F-20260722-01** — Voyis rectified pairs (image_left_/image_right_, same
  timestamp) verified rectified: median |Δy| ≈ 2 px at 2816 px. OpenCV SGBM
  (3-way, 1024 px work res) yields metric depth 1.3–3.5 m standoff at
  ~0.1 s/pair CPU; right-camera depth via horizontal-flip trick. Source:
  `seathru_test/stereo_depth.py`, 2026-07-22.
- **F-20260722-02** — SILENT FAILURE: multi-GPU `feature_extractor`
  (`gpu_index 0,1`) + `--ImageReader.single_camera_per_folder 1` races across
  GPU worker threads and can mint extra camera rows (3 cameras from 2
  folders). Fix: normalize the DB between extraction and rig_configurator
  (`seathru_test/run_colmap_rig.py::normalize_cameras`), or pre-build the DB
  with explicit camera_ids (immune — `pipeline/build_monolith_db.py`).
  Source: variant_a DB forensics; also HANDOFF §8.
- **F-20260722-03** — SILENT FAILURE: `rig_config.json` `camera_params` MUST
  be a JSON numeric array. A comma string parses empty and `rig_configurator`
  WIPES camera intrinsics with exit 0; surfaces two stages later as a matcher
  CHECK failure (0 vs 4 params). Hit independently in BOTH projects
  (RH0041 pilot + LilyJean variant_a). Source: HANDOFF §6; variant_a
  forensics 2026-07-22.
- **F-20260722-04** — DATA-DEPENDENT CRASH:
  `mapper --Mapper.ba_refine_sensor_from_rig 0` (frozen rig) died silently
  (exit −1, no log/dump) at ~215 registered frames on LilyJean; control
  without the flag passed the same point. CONTRAST: RH0041 pilot ran
  rig-locked to 96% of 485 frames. Scale- or data-dependent; treat
  rig-locking the incremental mapper as suspect until isolated. Source:
  `rig_test/variant_a/sfm/colmap_stages.log` + `mapper_test.err` A/B.
- **F-20260723-05** — Letting BA refine rig extrinsics costs nothing on
  LilyJean: recovered left↔right separation = 0.16970 m = calibration to 5
  decimals, every variant, both mappers. Calibrated rig initialization
  anchors metric scale; models come out in true meters. Measure baseline
  empirically (median distance between per-frame left/right projection
  centers), not via stored rig data. Source:
  `seathru_test/compare_rig.py::recovered_baseline`.
- **F-20260723-06** — `pycolmap.compute_mean_reprojection_error()` reads
  STORED per-point error fields; they go stale after external
  optimization/perturbation (stored 0.537 px on a model whose true error was
  11.77 px). Validate solver results by MANUAL reprojection. Source:
  `seathru_test/true_reproj.py`.
- **F-20260723-19** — The frozen-rig mapper crash (F-20260722-04) is
  UNREPORTED upstream as of 2026-07-23. Closest precedent: silent crash on
  missing sensor_from_rig poses (issue #3588) → proper error in PR #3988
  (4.0.0). A fresh 4.1.1 report with our flag-correlation + size dependence
  would likely be actionable.
- **F-20260723-20** — Plausible mechanism (source inspection):
  `ba_refine_sensor_from_rig 0` marks sensor_from_rig blocks constant →
  changes gauge-fixing path (`FixGaugeWithTwoCamsFromWorld` keys off
  IsParameterBlockConstant) and exposes a
  `THROW_CHECK(sensor_from_rig.has_value())` path — both only exercised
  under the flag; gauge fixing has a regression history (3.12.4/3.12.6/3.13.0).
  Source: `estimators/bundle_adjustment_ceres.cc`, main branch.
- **F-20260723-21** — Version-dependent flag semantics: in 3.12.4,
  `ba_refine_sensor_from_rig 0` locked only ROTATION (issue #3569). Older
  guidance about this flag predates its current meaning — verify per version.

## 4. Mapper & solver selection

**Policy: on stereo-rig / high-overlap surveys, `global_mapper` first, then a
rig-locked CASPAR BA polish. Incremental `mapper` is the fallback for
sparse-overlap non-rig data.**

- **F-20260723-07** — `global_mapper` beat incremental `mapper` on the
  IDENTICAL LilyJean database: 1,978 vs 1,381 registered stereo frames
  (+43%), 1 model each, same quality (0.549 px, track 7.6), 106 min vs
  >24 h. Incremental's cost driver is global BA (1–2+ h single BAs at ~1.4k
  frames). Source: `rig_test/variant_a/sfm/global/0` vs `sparse_test/0`.
- **C-20260723-01** — Second head-to-head, monolith validation subset
  (250 pairs, identical DB): global_mapper 11.7 min, 250/250 frames, 1
  model, 0.742 px, track 16.3 — incremental killed unfinished at >50 min.
  Incremental drowns at high frame rates (each image sees ~10k existing
  points). REVERSES RESEARCH_30K §4's "incremental backbone" advice for
  rig/high-overlap data. Source: HANDOFF §7.
- **F-20260723-22** — global_mapper caveats: (a) OPEN issue #4376 — on an
  ETH3D 4-camera rig, ~4× worse median rotation error than incremental with
  fixed rig (1.73° vs 0.44°); rig-constraint exploitation is a known
  weakness → follow with rig-locked BA polish; (b) refine_sensor_from_rig
  honored in ALL global stages only from 4.1.0 (PR #4377); (c) official
  Windows CUDA builds silently fall back to CPU for global-positioning/BA
  GPU options (#4328, #4306); (d) FULL_OPENCV/EUCM can produce degenerate
  global_mapper output (#4557, open). LilyJean rotation accuracy vs
  incremental NOT compared (Q-04).
- **F-20260723-10** — Incremental mapper writes models to disk only at
  completion (per model). Killing a long mapper loses the in-progress model;
  OS-level suspend (NtSuspendProcess) preserves and resumes exactly — used
  to serialize three contending mappers (three concurrent BAs cost ~40% each
  on shared memory bandwidth despite 128 cores). Source:
  `seathru_test/suspend_proc.ps1`.
- **C-20260723-02** — `global_mapper`'s "Decomposing relative poses" is a
  SERIAL single-core loop (verified in 4.1.1 and main source,
  `MaybeDecomposeRelativePoses`) ≈ 13 ms/pair ≈ 6 h at 1.7M pairs. FIX for
  all future runs: pass `--TwoViewGeometry.compute_relative_pose 1` to the
  MATCHERS (or a `geometric_verifier` re-pass) — verification then stores
  each pair's relative pose and the loop skips them; cost moves into the
  parallel stage. Upstream filing candidate. Source: HANDOFF §7 run notes.
- **C-20260724-01** — Ceres 32-bit nnz overflow: monolith global positioning
  crashed (`triplet_sparse_matrix.cc` CHECK, nnz −318,813,896) at 31.2M
  tracks / 508M observations; process commit hit 252 GB (system 334.6/335.4).
  Fix on rerun: `--GlobalMapper.keep_max_num_tracks 4000000` (31M is ~10×
  typical). Recovery tooling validated: `geometric_verifier
  --TwoViewGeometry.compute_relative_pose 1 --num_threads 48` re-verifies in
  parallel (~26 min) so a rerun skips the 6 h serial decomposition; expected
  rerun ≈ 3–5 h. Source: HANDOFF §7, global.log 2026-07-24 04:26.

## 5. GPU bundle adjustment (CASPAR)

- **F-20260723-08** — Official COLMAP 4.1.1 CUDA binary:
  `--Mapper.ba_use_gpu` / `--BundleAdjustmentCeres.use_gpu` are STUBS —
  Ceres compiled without CUDA/cuDSS, warns and falls back to CPU.
- **F-20260723-18** — Root cause: maintainer-documented — official CUDA
  binaries won't ship ceres[cuda] "until Ceres 2.3 is officially released";
  Ceres latest tag is 2.2.0 (2023). Not licensing. Simpler path is CASPAR.
- **F-20260723-14** — CASPAR identified: ICRA 2026 (arXiv:2605.30583), built
  on Skydio SymForce; damped LM with PCG + block-Jacobi on full normal
  equations (no Schur), fused CUDA kernels. Merged via PR #4018, shipped
  4.1.0, opt-in build flag `-DCASPAR_ENABLED=ON`.
- **F-20260723-09** — CASPAR VALIDATED on LilyJean (2,762 imgs, PINHOLE rig,
  local coords): 1 cm-perturbed 1.15M-point model recovered to the EXACT
  Ceres optimum (true reproj 11.77 → 0.6304 px, 4-decimal match) in ~20 s vs
  6.6 min for 5 CPU-Ceres iterations. Constraints: PINHOLE/SIMPLE_RADIAL
  only; errors loudly (exit 9) unless `refine_sensor_from_rig 0`.
  **SUPERSEDES the earlier "Caspar diverges" verdict — that was the UTM
  float32 artifact.** Timing caveat: not iteration-matched; CASPAR ran under
  partial GPU load (conservative). Source: `ba_caspar_test2/` +
  `true_reproj.py`; HANDOFF §5.
- **F-20260723-15** — Documented limitations (COLMAP FAQ) match observations:
  experimental; SIMPLE_RADIAL/PINHOLE only (other-model observations
  skipped); no pose priors; cannot refine sensor_from_rig (rigs as constant
  extrinsics since PR #4385/4.1.0); refine_focal_length must equal
  refine_extra_params; GPU-only, no CPU fallback.
- **F-20260723-16** — Pipelines: incremental `mapper` supports CASPAR in
  released 4.1.x (`--Mapper.ba_local_backend/ba_global_backend CASPAR`);
  `global_mapper` does NOT expose a backend selector in any release ≤4.1.1 —
  `GlobalMapper.ba_backend` merged to main 2026-06-28 (PR #4484), requires
  building from main.
- **F-20260723-17** — Caveat ≤4.1.1: `Mapper.ba_*` option values (e.g.
  max_num_iterations) NOT propagated to the Caspar backend (issue #4382);
  tune `BundleAdjustmentCaspar.solver_iter_max` directly. Fix merged
  2026-07-18 (PR #4527), unreleased.
- **C-20260724-02** — Local binary verification (this session): colmap-caspar
  `mapper --help` exposes `ba_local_backend/ba_global_backend` (default
  CERES); `global_mapper --help` has NO backend flag in EITHER binary;
  official binary exposes `--BundleAdjustment.backend` but CASPAR is not
  compiled in. Confirms F-20260723-16 on our exact builds (both a0d785f).
  Consequence: to GPU-accelerate the monolith global_mapper BA, rebuild
  colmap-caspar from main ≥2026-06-28; until then the CASPAR polish is a
  separate `bundle_adjuster` step after global_mapper. Source: `--help`
  inspection 2026-07-24.

## 6. Matching, vocab tree & the OpenBLAS defect

- **C-20260721-10** — Matching plan for large surveys: sequential → spatial →
  vocab-tree against ONE database; matchers skip already-matched pairs so
  passes compose; order cheapest-first. Sequential sorts lexicographically →
  per-folder streams come out as independent sequences. Spatial reads ONLY
  `pose_priors` (no EXIF fallback, silent skip); mean-centering built in, so
  UTM magnitudes are safe THERE (unlike dense). Do NOT use LightGlue on
  4.1.1 (SIFT integration flagged broken at 4.1.0). Source: RESEARCH_30K §1
  (web-grounded pass, 2026-07-21).
- **C-20260721-11** — `vocab_tree_matcher` dies silently on the 128-thread
  Threadripper (exit 0 or 127, zero new pairs, "BLAS : Bad memory
  unallocation!"). ROOT CAUSE (confirmed 2026-07-22): bundled
  `colmap\bin\openblas.dll` is a crippled vcpkg build — OpenBLAS 0.3.33
  SINGLE_THREADED, `generic` scalar core (no AVX2/512), NO_LAPACK — and
  COLMAP calls it from up to 128 worker threads. `OPENBLAS_NUM_THREADS` is
  the WRONG knob (caps threads inside a BLAS call, not callers). FIX: cap
  COLMAP's own threads — `--VocabTreeMatching.num_threads 4
  --FeatureMatching.num_threads 4` (verified clean on 970 images). Source:
  HANDOFF §6.
- **C-20260721-12** — `--VocabTreeMatching.max_num_features 2000` cuts
  retrieval indexing 7.8× (600 s → 77 s per 970 images); retrieval only
  needs to recognize the place — full features still used for actual
  matching. Projects ~1.6 h indexing for a 74.6k-image monolith vs >12 h.
  Source: HANDOFF §6.
- **C-20260723-03** — OpenBLAS ROOT-CAUSE FIX STAGED, NOT APPLIED (verified
  in place 2026-07-24: `colmap\bin\openblas.dll` still the 1.78 MB vcpkg
  original). Staged in `colmap_work\openblas_staging\`: official prebuilt
  0.3.33 (DYNAMIC_ARCH, AVX-512 Cooperlake path on Zen 4, threaded,
  MAX_THREADS=64) + 6.6 KB forwarder shim (136 pragma-forwarded exports;
  .def forward syntax misparsed by MSVC link, `#pragma
  comment(linker,"/export:...")` works). sgemm_/dgemm_ through the shim
  match numpy exactly. Swap procedure + rollback in HANDOFF §6. Caveat:
  complex-dot routines may have f2c/flang ABI mismatch — COLMAP/faiss/Ceres
  use only real-valued BLAS. AWAITING GO-AHEAD.
- **F-20260721-05** — pycolmap PyPI wheels on Windows are CPU-only: 3,607
  imgs @2048 px ≈ 2.9–3.7 h matching CPU vs 18 min GPU (official binary,
  `gpu_index 0,1`), ~19×; extraction ~3× GPU advantage. Use the official
  binary for extraction/matching; pycolmap for DB/model manipulation only.
- **C-20260721-13** — Vocab-tree recall experiment (RESEARCH_30K §1) still
  OPEN: pretrained 256K/1M faiss trees vs zone_9's 705k exhaustive-verified
  pairs; adopt pretrained if ≥~85–90% recall, else `vocab_tree_builder` on
  ~4k survey images. Underwater literature says domain-trained wins, but bad
  retrieval costs recall, not precision.

## 7. Camera model (dome port)

- **C-20260721-05** — zone_9 residual forensics
  (`pipeline/residual_forensics.py`, Menna-2020-style): all three live
  cameras show a clear radial harmonic (cam2 ±1.1 px) → under-parameterized
  radial distortion (missing k3), the dome axial-decentering signature.
  Depth trends ±0.1 px and non-monotonic → refraction adequately absorbed;
  the GEOMAR refractive fork is NOT needed for this imagery. Principal
  points were never refined. Source: HANDOFF §3,
  `zone_9\logs\residual_forensics*\`.
- **C-20260721-06** — FULL_OPENCV upgrade (k3–k6 seeded 0) + global BA with
  `refine_principal_point 1`: 173 iterations to convergence (~42 min CPU;
  the iteration flag is `--BundleAdjustmentCeres.max_num_iterations`, NOT
  `BundleAdjustment.`). Cost 0.747 → 0.683 px; cam2 median 1.156 → 0.878 px;
  radial harmonics ELIMINATED (±1.1 → ±0.06 px); PPs settled 4–8 px off
  center (real dome decentering). **`zone_9\sparse_fullopencv_ba2\cameras`
  is the calibration to LOCK for production** (calibrate-then-lock:
  `--ImageReader.camera_params` + `--Mapper.ba_refine_focal_length 0
  --ba_refine_principal_point 0 --ba_refine_extra_params 0`). Source:
  HANDOFF §3.
- **C-20260721-07** — Model-selection verdicts (web-grounded, RESEARCH_30K
  §3): OPENCV per physical camera for production; fisheye models wrong tool
  for rectilinear lenses; per-pass intrinsics NO (stability is mechanical,
  not water-property-driven — Shortis 2015; split only across physical
  interventions); SIMPLE_RADIAL insufficient (k1-only leaves ~0.37 px
  systematic + 25× object-space error in weak networks); CASPAR hybrid done
  right = lock OPENCV → undistort → exactly PINHOLE → CASPAR with zero model
  loss. GEOMAR refractive fork: COLMAP 3.10-dev base, incompatible DB,
  SfM-only, frozen ~2024 — validation instrument only.

## 8. Dense reconstruction

- **C-20260721-08** — zone_9 dense DONE on the fixed local model: PatchMatch
  full re-run 244 min both GPUs, depth quality verified vs sparse
  (photometric 0.5% median rel. error / 89% within 5%; geometric 0.7% / 98%
  within 5%, fill 4–40%); stereo fusion 9,301,888 points in 18 min →
  `zone_9\dense\fused.ply` (251 MB, local). Georeference at delivery by
  adding back (+596082.7, +8993484.4, −854.6). UTM-era poisoned outputs
  quarantined under `dense\stereo\_*_utm_broken\` (~120 GB, safe to delete).
  Source: HANDOFF §2.
- **C-20260721-14** — Dense pitfalls automated in `server.py` build_stages
  (keep them there): `StereoFusion.max_image_size` MUST equal
  `PatchMatchStereo.max_image_size`; fusion `--input_type` must match
  whether geometric consistency ran; PatchMatch silently discards output if
  per-camera subdirs under `dense/stereo/{depth_maps,normal_maps,
  consistency_graphs}` are missing. Source: CLAUDE.md rules 2–4, learned
  zone_9 sessions.
- **C-20260721-15** — zone_9 sparse oddity: 710 `zeuss` (camera 3) frames
  are registered but have ZERO triangulated points — contribute nothing
  downstream (dense sees 1,886 of 2,596 registered). Unexplained; echoes
  RS_main's independent zeuss-camera trouble (F-20260723-34). Source:
  HANDOFF §2.

## 9. Survey design & scale

- **C-20260723-04** — Sampling-rate analysis (measured on the monolith
  reconstruction): ROV moves 0.079 m between frames at 3 fps; footprint
  4.9 m at 3.3 m altitude (73° HFOV) → 98.4% forward overlap, heavily
  oversampled. 0.5 m spacing = 90% overlap = 0.47 fps; 1.0 m = 80% =
  0.24 fps. Measured on one 83 s segment; speeds vary per run. 2 fps chosen
  as margin-safe. Extraction is route-independent — more frames can be
  added later. Source: HANDOFF §7.
- **C-20260723-05** — RH0041 dataset facts: 58 runs, 54,734 rectified pairs
  (109k images 2816×2816, Voyis-processed); geo CSVs EMPTY (header only);
  IMU CSVs 1980-epoch (unsynced) → no usable priors; scale from rig baseline
  only, cross-run linking from vocab tree only. RH0042 shares the identical
  camera (serial 180114031, same intrinsics/baseline) → legitimately one
  monolith. Metric scale independently verified on the 250-pair global
  model: left↔right spacing exactly 0.170 m, altitude 3.3 m. Source:
  HANDOFF §6–7.
- **C-20260723-06** — `pipeline/build_monolith_db.py` writes the DB directly
  (cameras, images, rigs, frames) instead of feature_extractor +
  rig_configurator, because those group by FOLDER layout: on the in-place
  nested tree, `single_camera_per_folder` would mint ~94 cameras and
  `rig_configurator --image_prefix` can't isolate eyes from nested paths.
  Also dedupes Run_* dirs present in both caches. Validated on the 250-pair
  subset: extraction in place preserved all hand-built rows (500 images, 2
  cameras 250/250, params intact, 1 rig / 250 frames / 500 frame_data).
  Source: HANDOFF §7.

## 10. Tooling / app

- **F-20260723-11** — COLMAP Studio viewer first-load hang root cause:
  synchronous `model_converter` TXT conversion (minutes for ~0.9 GB models)
  inside the request; frontend timed out and "reload" re-hit the same lock.
  Patched: background conversion thread + `202 {"status":"converting"}` +
  2 s frontend poll with token guard. Verified live (warm 200 instant / cold
  202 → 200 in 45 s). Source: `server.py` + `static/index.html`, 2026-07-23.
- **F-20260723-12** — Workspaces outside `colmap_work` can be exposed to the
  Studio via file HARDLINKS (no admin, zero extra disk, same volume) shaped
  as `<ws>/database.db` + `<ws>/sparse/0/*.bin`. Writes through links mutate
  the originals — safe for viewing/dense, not re-matching. Source:
  `colmap_work/lilyjean_*`.

## 11. Infrastructure events

- **C-20260724-03** — E: NVMe ("4TB-RUMI-F") FAILING: stornvme controller
  error (Event ID 11) at 06:35 destroyed the un-checkpointed 82 GB WAL
  holding the monolith verifier's writes (raw-level unreadable; quarantined
  as `database.db-wal.corrupt`). Main DB `quick_check: ok` — 1,704,507
  verified pairs intact; only the 26-min verifier output lost. SECOND
  stornvme error 12:20 same day; volume HealthStatus=Warning,
  OperationalStatus="Full Repair Needed" (checked this session).
  MITIGATION (this session): rescue copy of database.db +
  database_backup_precrash.db + logs to `M:\colmap_work\monolith_rescue\`
  (M: healthy, 2.5 TB free; robocopy 292.9 GB, 0 failed, ~1.08 GB/s).
  Rescued database.db VERIFIED on M:: `PRAGMA quick_check` = ok, 66,434
  image rows (exact expected count), 3,236,987 two_view_geometries rows
  (raw row count; HANDOFF's "1,704,507 verified pairs" is the
  inlier-filtered figure — different metric, not a discrepancy). Treat E:
  as untrusted for compute until Jonathan decides (repair/replace/relocate).
  Source: HANDOFF §7; Get-Volume + Get-WinEvent + robocopy log + sqlite
  quick_check 2026-07-24.

## Open questions / queued experiments

- **Q-01** (PARTIALLY RESOLVED) — frozen-rig incremental-mapper crash:
  unreported upstream; likely gauge-fixing/THROW_CHECK path
  (F-20260723-19/20). ACTION: file COLMAP issue with LilyJean repro.
- **Q-02** — 45% of LilyJean frames register in NO model (all variants):
  acquisition connectivity limit. Next lever: vocab-tree loop closure on
  originals (with C-20260721-11 thread caps), then dense on variant A.
- **Q-03** — RESOLVED (F-20260723-16 + C-20260724-02): mapper has CASPAR
  backends in 4.1.x; global_mapper needs a build from main. Untested
  locally; next practical step is a mapper re-run with CASPAR backends.
- **Q-04** — Does global_mapper's weaker rig-constraint exploitation
  (issue #4376) measurably degrade pose accuracy vs incremental on our
  data? Baseline check passed; rotation accuracy never compared.
- **Q-05** — Preprocessing reconciliation (2×2): (a) zone_9 baseline-vs-CLAHE
  through COLMAP (does the conflict track ENGINE or IMAGERY?); (b) LilyJean
  originals-vs-CLAHE through RealityScan alignment, registration as metric.
  Four cells decide the documentation-guide policy.
- **Q-06** — Vocab-tree recall experiment (C-20260721-13): pretrained vs
  custom tree against zone_9's exhaustive ground truth.
- **Q-07** — zone_9 zeuss camera: why do 710 registered frames carry zero
  triangulated points (C-20260721-15)? Same physical camera family also
  underperformed in RS_main (F-20260723-34).
- **Q-08** — Monolith resume (BLOCKED on drive decision, C-20260724-03):
  geometric_verifier w/ compute_relative_pose (~26 min, 48 threads) →
  global_mapper with `keep_max_num_tracks 4000000` + calibrate-then-lock
  flags (~4–5 h) → model_analyzer → 0.170 m baseline check → rig-locked
  CASPAR polish → OpenBLAS swap test (C-20260723-03) on go-ahead.
- **Q-09** — Upstream filing candidates: serial relative-pose decomposition
  loop (C-20260723-02); single-threaded-OpenBLAS vocab crash
  (C-20260721-11); frozen-rig mapper crash (Q-01); Ceres 32-bit nnz
  overflow ergonomics at 500M observations (C-20260724-01).
