# FINDINGS — consolidated running log

One entry per established fact, WITH how it was discovered. Append new
findings at the bottom of the relevant section with a date. Refuted
hypotheses stay, marked SUPERSEDED.

CONSOLIDATION NOTE (2026-07-24): this file now merges TWO research
lines that ran in parallel from commit 6069d95:

- **[H2023]** — NA156 H2023 production line (this machine): settings
  evaluation, camera registry, zone aligns, within-zone growth,
  hardening cells U1–U20. Deep docs: `docs/settings-evaluation-2026-07.md`,
  `docs/merge-growth-strategy-2026-07.md`, `testing/ALIGN_MERGE_HARDENING_PLAN.md`.
- **[NA167 #n]** — NA167 H2075 merge-strategy matrix (Honeybadger box):
  strategies A/B/C, D-cell merge-mechanism isolation, findings #1–31.
  Deep docs: `testing/FINDINGS.md` (frozen numbered log, do not append),
  `testing/MERGE_STRATEGY_REPORT.md`, `testing/MERGE_TEST_PLAN.md`,
  `testing/NA167_SESSION_NOTES.md`.

Entries below carry their source tag. Cross-line reconciliations are
tagged **[RECON]** and dated 2026-07-24. `testing/FINDINGS.md` is
frozen as the NA167 raw log; all new findings go HERE.

## RealityScan 2.2 CLI behavior

- **addFolder does NOT recurse by default in this build** — zone_1/zone_2
  aligns added "0 layer images" and every flight-log row then failed
  err:18002. Discovered: live H2023 run failed in 25 s; RealityScan.log
  snapshot showed `Added 0 layer images`. Fix: `appIncSubdirs=true`
  before every addFolder. [H2023] (2026-07-23)
  - Nuance: an earlier NA167 zone_13 run DID import camera subfolders
    into one scene via -addFolder [NA167 #5] — that run had
    appIncSubdirs set by the fixed workflow; the flag, not the build,
    is the variable.
- **-align on instance defaults is a real hazard** — AlignImagesFromFolder
  never applied AlignmentParams.xml; only AlignZonesSequentially did.
  Discovered: code reading during settings evaluation. Fix: every
  workflow applies the sfm*/lis* keys; policy "never align on instance
  defaults". [H2023] (2026-07-23)
- **cmd splits unquoted `;` `,` `=` into separate .bat arguments**, and
  Python subprocess only quotes on whitespace — `key=value` settings
  arrived split, RealityScan.log showed `Parsing setting key=value ...
  failed [err:7155]`, meaning **no flag cell had applied its flags** and
  the parse errors aborted workflows via the errors marker. Lists now
  cross as files, settings as `key:value`. [NA167 #15] (2026-07-23)
- **-align takes no parameters in 2.x** — `-align "%AlignmentParams%"`
  is not supported (allcommands.htm + online docs); settings must be
  applied via delegated `-set` commands before a plain `-align`.
  [H2023, first-machine validation] (2026-07-21)
- **-selectAllComponents does not exist in RealityScan 2.2** — fails
  0x82000060; only selectComponent / selectMaximalComponent (+
  selectComponentWithLeastReprojectionError) exist. The dead command
  had lived unnoticed in AlignZonesSequentially.bat. [NA167 #13]
  (2026-07-23)
- **exportLatestComponents exports ALL components of the last alignment**
  (gated by setMinComponentSize) — the old maximal-only export was
  unnecessary loss. Discovered: allcommands.htm sweep. [H2023] (2026-07-23)
- **-setMinComponentSize is deprecated in 2.2** ("will be removed in the
  next release") but still required — without it components under the
  default threshold 5 are silently excluded from selection/export.
  Discovered: warning line in a per-cell RealityScan.log snapshot.
  [NA167 #22] (2026-07-24)
- **-setFeatureSource 0|1|2 and -selectImage ARE CLI** — the
  merge feature-source trio was wrongly believed GUI-only. Discovered:
  allcommands.htm "Commands for Selected Images" section. [H2023]
  (2026-07-23)
- **selectImage matches LITERAL FULL PATHS ONLY in this build** — bare
  regexp, dot-star-wrapped, glob, and regexp with explicit 'set'
  modifier ALL silently select nothing; a literal full path selects
  exactly its image. Selection composition = per-image literal
  selectImage union loop (~0.1–0.3 s per image — budget minutes for
  thousand-image sets). The Help's "imagePath|regexp" wording does not
  match observed 2.2 behavior — forum-mining follow-up open.
  Discovered: bisection probes U-SEL2 through U-SEL8. [H2023, U1/U19/U2]
  (2026-07-23)
- **-editInputSelection is the master per-image CLI control** (local
  Help tutorials/editselectioncommand.htm): on the current image
  selection it sets enable-alignment (inpEnabled), features source
  (aligFeaturesMode 0|1|2), enable meshing/texturing, texture weight,
  masking mode, per-image PRIOR POSE (inpPose 0–3, translation/rotation,
  accuracies, locked-pose groups) AND full calibration/lens priors
  (inpCalibrationGroup, inpCalibration Unknown/Approximate/Fixed,
  inpFocal, principal point, inpDistortionModel 0–5, coefficients).
  `"inpEnabled=false"` works as a single quoted key=value arg, and
  -align honors enable/disable exactly. [H2023] (2026-07-23)
- **XMP export naming: the COMMAND determines it, not the scene** —
  `-exportXMP` writes STEM-named sidecars; `-exportXMPForSelectedComponent`
  writes ORDINAL sidecars (00000.xmp, …) in every observed context.
  Four consistent datapoints; an earlier session-based hypothesis was
  WRONG and is SUPERSEDED. Consequence: per-component membership is
  derived by SUCCESSIVE DIFFERENCE of `-exportXMP` stem harvests as
  components are deleted (AlignZone.bat identity loop). [H2023, B10
  final form] (2026-07-23)
- **Flight-log import leaves the matched images ACTIVELY SELECTED**, and
  selection-driven exports under -silent then export nothing
  ("Export Selection" dialog auto-answered; XMP export completed in
  0.057 s vs 20.5 s). Fix: -deselectAllImages before exports. [H2023]
  (2026-07-23)
- **-importFlightLog reports a failed process (err:18002, 0x820000FF)
  when the log references images not in the scene** — the trajectory
  itself imports fine. Filter the flight log to images present when
  aligning subsets. [H2023, first-machine validation] (2026-07-21)
- **-importComponent of a relocated .rsalign hangs forever** (#timeout
  state, no error; observed 6 h). In-place imports: ~2 s per 0.7 GB.
  Import components from their original export paths — `.complist`
  workflow input exists for exactly this. [NA167 #11] (2026-07-23)
- **The errors marker carries only ErrorWriter's numeric result code**,
  never the err:NNNN text (that is only in %LOCALAPPDATA%\Temp\
  RealityScan.log, truncated each boot). Tolerant handlers must match
  codes (2181038335 = 0x820000FF warning-class; 0x80070057 E_INVALIDARG
  from emptied-scene select paths). [H2023] (2026-07-23)
- **0x8000FFFF is generic ("unexpected program state")** — broken -set
  args and the zone_14 align failure emitted the identical code; and
  RealityScan.log is truncated on every instance boot, so post-failure
  snapshots lose the race to the next boot. Log copies must happen
  inside the driver immediately after the failing call returns.
  [NA167 #16] (2026-07-23)
- **-getStatus says "gone" before the process releases marker-file
  handles** — the next workflow's marker clear raced the teardown;
  60 s per-file retry added. [NA167 #14] (2026-07-23)
- **Process result code 1 is benign in practice** — routine successful
  operations (e.g. -addFolder) report result 1 through the trigger;
  real failures report distinct codes. Whitelist of 0/1 kept. [H2023,
  first-machine validation] (2026-07-21)
- **RealityScan 2.2 emits periodic internal heartbeat processes through
  the same appProcessExecCmd trigger** — "the results log grew" does not
  mean "our command finished"; completion = delegate → grace → double
  -waitCompleted. [H2023, first-machine validation] (2026-07-21)
- **Check Integrity / Check Topology have no CLI commands** — their fix
  action maps to -cleanModel + -closeHoles. [H2023] (2026-07-23)
- **-removeSelectedTriangles removes the SELECTED set** (= Filter
  Selection tool); -selectLargeTrianglesRel threshold is multiples of
  average edge length, not pixels. [H2023] (2026-07-23)
- **-deleteSelectedComponent, -deleteComponent <idx>, and
  -deleteAllComponents all exist** in this build (allcommands.htm sweep).
  [H2023] (2026-07-23)
- **selectMaximalComponent / renameSelectedComponent /
  deleteSelectedComponent silently no-op on an empty scene** (no errors
  marker) — loop terminals must be file-existence checks, not error
  checks. [H2023] (2026-07-23)
- **quit-without-save leaves the .rsproj bundle byte-stable** across
  load/delete/export cycles (hash-verified twice); rename →
  exportSelectedComponentDir writes <newname>.rsalign. [H2023, U15/U16]
  (2026-07-23)
- **-exportRegistration without a params XML blocks forever headless** —
  avoid until a params file saved from the GUI dialog exists. [H2023]
  (2026-07-21)
- **#timeout progress lines defeat line-change stall detection** (every
  tick differs, so a hang counts as activity) — AND #timeout does NOT
  always mean hung: heavy align phases legitimately freeze the progress
  fraction 20+ min (40 #timeout lines in a successful 94.6% run). The
  pathological signature is #timeout from fraction 0.00 with ever-growing
  ETA. Policy: stall-warn on #timeout (2 h), never auto-kill an align on
  it. [NA167 #12, #28] (2026-07-23/24)

## Alignment behavior & settings

- **Settings for the WCA rig class** (full rationale:
  docs/settings-evaluation-2026-07.md §4): sfmEnableCameraPrior=true
  (IS the GUI "use camera priors for georeferencing"), prior weight
  10.0, sfmDistortionModel Brown3 global fallback with REAL models per
  camera via XMP (fisheye=division, rectilinear=brown3, post-merge
  upgrade path Brown4WithTangential2), sfmDetectorSensitivity Ultra,
  sfmImagesOverlap Low→Medium, sfmForceComponentRematch=false and
  sfmMergeGeoreferencedComponents=false for pass-1 zone aligns,
  appIncSubdirs=true always. [H2023] (2026-07-23)
- **XMP calibration sidecars are the ONLY way to separate EXIF-identical
  cameras** — WCA rendered JPGs are EXIF-identical across cameras (Z CAM
  E2-F6, no focal tag). One calibration/lens group per PHYSICAL camera.
  Old batcher values (camlower "12 mm fisheye"; actually rectilinear
  17 mm) were wrong and plausibly explain NA167's "priors hurt" A/B.
  [H2023] (2026-07-23)
- **XMP calibration priors were never loaded in any historical run** —
  written as `image.jpg.xmp`; RealityScan only reads `image.xmp`.
  Discovered by an arithmetic anomaly in sidecar counts after aligning
  zone_13. [NA167 #3] (2026-07-22)
- **The old prior CONTENT itself hurt registration (96.3% → 89.6% on
  Zeuss)** — A/B on zone_13 with priors absent vs promoted. Generation
  is opt-in until corrected per-camera values are re-validated per rig.
  [NA167 #4] (2026-07-22)
- **Extracted frames were timestamped one output interval early** (60 s
  at 1 fpm) — frame seek and timestamp source used different frame
  indices; confirmed with a synthetic per-frame-gray video. Any dataset
  extracted with the old __extract_video_cv2 carries the offset.
  [NA167 #1] (2026-07-22)
- **UTM zone must be derived per cruise, never hand-edited** —
  FlightLogParams.xml is auto-generated from the zone tag in the
  flight-log filename (NA173 was 57S while the template said 4N; NA167
  computed 53N and round-tripped). [NA167 #6 + H2023] (2026-07-22)
- **Alignment fragmentation is strongly nondeterministic; total
  registration is not** — zone_1 (4,540 images, identical settings,
  sidecars, inputs) aligned to 2 components/4,391 cameras in one run and
  9 components/4,392 in another. Component structure cannot be relied on
  across runs — only manifest-tracked image sets can — and within-zone
  growth/merge is MANDATORY machinery. [H2023] (2026-07-24)
- **Alignment runtime varies ~3× with scene character at equal image
  count** (zone_6 61.6/97.8 min vs zone_4 24.3/20.8 min, both ~1.5k
  frames, same GPU, both run twice) — budget by zone, not image count.
  [NA167 #20] (2026-07-23)
- **zone_14 fails standalone alignment deterministically (4/4) with
  fully clean data** — RealityScan internal error MSS_STR001 in the
  reconstruction phase (forensic log: testing/results/z14_forensic_rslog.txt);
  data exonerated by full-pixel decode, MD5, Laplacian, nav checks.
  Its images align FINE inside a larger scene (B grew through it at
  94.6%). Production rule: when a zone fails alignment solo, grow it
  from an aligned neighbor — don't retry solo. Reportable to Epic with
  the captured log. [NA167 #17, #18, #27] (2026-07-23/24)
- **Align output is never pose-stable** — a free re-align moved ALL 118
  cameras of a solved smoke scene and can drop 1–2 marginal ones.
  [H2023, U18 bonus] (2026-07-23)
- **Pose-locking is unusable as a growth anchor** — editInputSelection
  inpPose=3 takes effect but -align then refuses: "prior set to 'Exact'
  mode must be all aligned in a single run. Incremental adding is not
  supported." Checkpoint/rollback stays the primary never-shrink
  mechanism. [H2023, U18 FAIL] (2026-07-23)

## Merge & component growth

### Mechanism (reconciled 2026-07-24)

- **[RECON] Shared cameras are the ONLY merge mechanism verified to work
  headless.** NA167 D-cell isolation: zero-shared-camera pairs NEVER
  fuse — under -mergeComponents or -align-as-merge, georef flag on or
  off, rematch on or off, duplicate-path or shared-path form — and the
  non-merge is always SILENT (workflow exits success; the "merged"
  export is just the biggest input). With shared cameras,
  -mergeComponents FUSES: D6 split-zone fixture (two zone_6 halves
  sharing 390 images, aligned solo to 749 + 342 cams) merged in 56 min
  of real reconstruction ending "Finalizing 1 component". Verify EVERY
  merge by pose-XMP camera census, never exit status. [NA167 #23–26,
  #30, #31] (2026-07-24)
- **[RECON] Camera identity is (at minimum) path identity** — zones
  built as per-zone COPIES of overlap images (different paths) provide
  no shared-camera identity for merging; zones must reference a common
  image pool (imagelists or same on-disk paths). This makes the
  batcher's duplicate-copy output a production defect for the merge
  stage (change queued). [NA167, MERGE_STRATEGY_REPORT] (2026-07-24)
- **[RECON] OPEN CONTRADICTION (test cell D7, testing/MERGE_TEST_PLAN.md):
  the H2023/NA156 line observed apparent fusion WITHOUT path identity,
  twice** — smoke: mini_a (118) + mini_b (62), 40 overlap images
  duplicated at different paths, merge_zones.py produced one 180-camera
  component in 66 s; production H2023: 5 duplicate-path components
  fused to a 3,860-camera maximal in 31 min. NA167 D1/D2 say the georef
  flag never does this. Candidate discriminator: merge_zones.py imports
  the union flight log + CRS into the merge scene and runs `-update` —
  the D-cells never gave the merge scene its own constraints. Suspicion:
  180 = 118 + 62 exactly (no dedup of the 40 duplicated images), which
  is consistent with rigid side-by-side PLACEMENT rather than identity
  fusion — seam quality unverified. Until D7 runs, treat georef-based
  merging as UNPROVEN and duplicate-path "fusions" as suspect placements.
  (2026-07-24)
- **[RECON] "Merge Components is rigid best-fit" needs qualification.**
  The Epic staff claim (2021, pre-rename, outside the 4-year trust
  window) says no re-optimization / no repositioning / no new images.
  Empirically: with shared cameras -mergeComponents runs ~56 min of
  visible "merge reconstruction" and can finalize different component
  counts [NA167 #30–31]; and H2023 zone_1's final census read +37
  cameras vs the manifest baseline after a rigid-merge stage was the
  only accepted mutation (attribution unresolved — merge effect vs
  census-mapping nuance). What stands: merge cannot shrink and cannot
  register orphans. What is UNVERIFIED: "no re-optimization" in the
  current build. (2026-07-24)
- **featureSource is consumed by ALIGN, not Merge Components**: 0 =
  merge using overlaps (images COMMON to components — NOTE per the
  identity finding this means shared-PATH images, not duplicate
  copies), 1 = component features (existing tie points only), 2 = all
  image features (slow, small counts). Discovered: components.htm
  "Features source" prose. [H2023, caveat added at RECON] (2026-07-23)
- **Align is the actual merge/growth engine**: re-runs use "special
  algorithms designed for merging components", are cheap (cached
  features), "try a different strategy" on repetition; after
  georeferencing, align hunts additional cross-component tie points.
  Discovered: mergecomponents*.htm tutorials + staff answer. — BUT
  align-as-merge ALSO requires shared cameras across components
  [NA167 D3]. [H2023 + RECON caveat] (2026-07-23/24)
- **Align can SHRINK components** (re-optimization drops marginal
  cameras) — "grow, never shrink" must be enforced by checkpoint/
  rollback, not assumed. Observed: H2023 3,860 → 3,855; zone_1 c7 pass
  lost 51 previously-registered images. [H2023] (2026-07-23/24)
- **A merged component is NOT georeferenced unless the merge scene holds
  constraints** — imported components' own georeferencing does not carry
  into the new component. Fix: union flight log + CRS params into the
  merge scene, then `-update`. Discovered: owner GUI inspection
  ("showstopper") + allcommands.htm + live re-run. [H2023] (2026-07-23)
- **Component reimport does NOT carry non-member images** — orphans are
  absent from a components-only project and carry no trajectory until
  the flight log is imported. Checkpoint/rollback must use .rsproj file
  copies, not component reimport. [H2023] (2026-07-23)
- **Official fix-and-reimport round trip**: export faulty part →
  fix in spare scene → reimport → align "applies fixes". Components
  tolerate duplicate images by design. [H2023, components.htm] (2026-07-23)

### Strategy results (NA167 zones 6/14/4 matrix + H2023 production)

- **Sequential growth (B) and joint align (C) give identical quality;
  they differ 2.6× in time and 2.7× in memory, opposite winners** —
  B: one component, 3,906/4,131 (94.6%), 444 min, ≤60 GB. C: one
  component, 3,904 (94.5%), 169 min, ~165 GB peak. Joint alignment
  extrapolates to ~700 GB for a 19k-image dive — chunking is mandatory
  at production scale. [NA167 #19] (2026-07-24)
- **Incremental growth is state-sensitive and can DEGRADE existing
  structure** — z6→z14 two-zone grow fragmented to an 870-camera
  maximal (< z6's solo 1,533) while the three-zone B grow through the
  same stages held 3,906. Growth outcomes are not order/subset-
  invariant — verify camera counts after every grow step. [NA167 #29]
  (2026-07-24)
- **Empirical H2023 registration**: zone_1 96.7% (4,391/4,540) first
  run, 4,392 re-run; zone_2 94.3–95.1% (920–928/976); cross-zone merge
  produced a 3,860-camera maximal (83.9% of unique) in 31 min (see
  OPEN CONTRADICTION for mechanism). Registration ceiling is
  unregistrable imagery, not merge mechanics. [H2023] (2026-07-23)
- **Twin components across zones**: the 20% batcher overlap duplicates
  images into both zones; the same strip solved independently can
  fragment into near-identical twins whose residual quality differs
  with solve context. Post--update residuals expose the weak twin. A
  twin with no unique images is discardable by the "never discard
  unique images" rule. Detection/automation: modules/component_analysis.py
  (containment scan, keeper choice, border gating, orphan tracking,
  merge planning; 31-test pytest suite passing). Coverage is checked
  against the UNION of still-kept group members, worst-first. [H2023]
  (2026-07-23)
- **Georef-only rigid fusion** (sfmMergeGeoreferencedComponents +
  merge/-update) was DESIGNED as the last resort placing components
  purely by nav (~1–2 m real accuracy, bakes nav error into seams) —
  but see the OPEN CONTRADICTION: it has never been PROVEN to act
  headless at all. [H2023 design + NA167 negative results] (2026-07-23/24)
- **Growth passes are align-UPDATES that refresh EVERY component** — a
  census after an "isolated" component pass covers the whole zone;
  per-component before/after accounting produced phantom gains. The
  zone-level baseline census drives the invariant, gain, and orphan
  derivation. [H2023] (2026-07-24)
- **Zone_2 growth ground truth**: 928/976 (95.1%), ZERO real gains —
  the 48 orphans are genuinely unregistrable; honest convergence after
  one sweep. Three components remain by design (northern strip has no
  visual ties). [H2023] (2026-07-24)
- **Zone_1 growth ground truth: EVERY re-solve pass shrinks a
  weakly-connected fragment set** — global re-align + all 8 component
  passes rejected and rolled back (c7's pass lost 51 images); final
  4,429/4,540 (97.6%), 148 orphans. The +37 delta vs the 4,392 manifest
  baseline is an OPEN question (rigid merge was the only accepted
  mutation). Implication: for fragmentation like zone_1's, visual
  growth is exhausted immediately; the cross-zone stage is the
  productive path. [H2023] (2026-07-24)
- **Checkpoint/rollback validated in anger** — a growth run killed
  mid-pass was fully recovered by copying the "initial" .rsproj bundle
  checkpoint back over the scene. [H2023] (2026-07-24)
- **In-session successive-difference identity capture VALIDATED end to
  end** (smoke mini_a): align → saves → destructive harvest loop →
  quit-no-save produced .rsalign + manifest (118 members by real
  basename, UTM bbox), census from manifests == original registration,
  zero pose sidecars left beside images. [H2023] (2026-07-23)
- **H2023's feature geography is IN the manifests, and it makes the
  maximal-fraction merge target mathematically unreachable.** Running
  `component_analysis.merge_plan` over the 12 zone manifests
  (`aligned_components`, pure analysis, no RealityScan) resolves three
  spatially disjoint UTM clusters:
  - hull — zone_1 c0/c1/c3/c4/c5/c6/c7/c8 + zone_2 c1, bbox band
    E 594693–594719 / N 2345096–2345160, **3,720 unique images**;
  - bow — zone_2 c0 (686) and its twin zone_1 c2 (672), identical bbox
    E 594653–594668 / N 2345217–2345251, ~60 m NW, **686 images**;
  - west pocket — zone_2 c2, E 594599–594607 / N 2345248–2345256,
    another ~50 m west, **102 images**.
  Hull ∩ bow = **0 shared basenames**, so no merge mechanism (shared
  cameras or content rematch) can ever fuse them. Ceiling on the
  maximal component is therefore 3,720/4,600 = **80.9%**, below both
  `--target` values ever used (0.85 in the `merged` run, 0.83 in
  rs_settings). merge_zones.py must run the full three-attempt ladder
  (~1.7 h) and exit 1 on a CORRECT result. Discovered: manifest
  analysis during 2026-07-24 onboarding; confirms the owner's bow/hull
  statement from the data independently, and quantifies HANDOFF's
  size-based-hazard #2. [H2023] (2026-07-24)
- **The `merged/` run is superseded, not a baseline** — its
  `components_in` are five ordinal `Component N.rsalign` exports with
  an EMPTY twin_plan (it predates manifests). Its three attempts read
  3,860 / 3,855 / 3,855 cameras (83.9%, 83.8%, 83.8%) and it exited
  "no attempt reached the 85% target". Read with the clusters above,
  3,860 is a hull-cluster maximal component, not a shortfall. Do not
  cite it as evidence about merge mechanism. [H2023] (2026-07-24)
- **`-mergeComponents` as a rigid consolidation pass really does
  consolidate: zone_1 went 9 components → 4** (growth pass `merge`,
  38 min, accepted). Discovered: `growth/zone_1/final_components`
  holds four ordinal `Component N (1).rsalign` files against the nine
  manifested pre-growth exports, same 4,392-image union. Supports
  HANDOFF queue item 7 (a zero-camera-gain pass that reduces component
  count still serves the merge stage). [H2023] (2026-07-24)
- **The zone_1 growth +37 census delta most likely = cameras below the
  50-camera export floor, absorbed by the rigid merge** (HYPOTHESIS,
  not yet proven). Both the identity harvest and every census export
  run under `setMinComponentSize 50`, so members of sub-50 components
  are invisible to the census; the only accepted mutation before the
  +37 appeared was the 9→4 consolidation. Cannot be closed from the
  report alone — `try_build_manifests` produced ZERO manifests for the
  post-growth exports (B10 ordinal rule: identity is unharvestable
  outside the original aligning scene), so post-growth membership does
  not exist to diff. Test: re-census the zone_1 scene at
  `setMinComponentSize 1`. [H2023] (2026-07-24)
- **The GrowZone disabled-images bug did NOT reach the zone_1
  authoritative artifact — because every component pass was rolled
  back.** GrowZone.bat component mode disables all images, enables a
  subset, aligns, and falls through to `:save_quit` with no
  re-enable, so each of the eight passes saved a crippled scene; the
  driver then restored the checkpoint each time. Timestamp evidence:
  `zone_1.rsproj` mtime 03:31:57 == the `merge` pass's save; all
  component passes ran 03:31→03:54 and were rolled back; the surviving
  checkpoints are `initial` and `grow_s1_zone_1_c7` (taken before the
  last pass, i.e. the post-merge all-enabled state). The code bug
  stands (HANDOFF queue item 5) — a single ACCEPTED component pass
  would persist it. Confirm in the GUI before trusting the scene.
  [H2023] (2026-07-24)

- **D7 RESOLVED: RealityScan 2.2 fuses components via image CONTENT;
  path identity is NOT required; georef constraints are NOT what
  enabled the NA156 duplicate-path merges.** Probe (testing/probe_d7.py,
  smoke fixture, 2026-07-24): zone_c (78 cams, mini_a-only images) +
  zone_d_c0 (42 cams, mini_b-only images) share ZERO basenames and ZERO
  paths but view the same wreck strip. `-mergeComponents` fused them to
  one 120-camera component (78+42 exact) BOTH without any flight log in
  the merge scene (D7b) AND with union log + -update (D7a) — "Finalizing
  1 component" in both. `-align` + rematch on the 118+62 overlap pair
  fused to 180 without a log (Q9a); the original 66 s merge replicated
  at 180 (D7c). Reconciliation with NA167 D1–D3 (never fused): those
  pairs had zero CONTENT overlap (z6+z4 never see the same seafloor).
  Every fusion observation to date is explained by one rule: **content
  overlap => fusable (either mechanism); no content overlap => no fuse,
  silently, regardless of flags/log**. Consequences: (a) the union-log
  candidate discriminator is refuted — the log is still REQUIRED for
  georeferencing the merged result, but plays no role in fusion;
  (b) queue #9's ladder inversion is unnecessary — merge_first is
  mechanistically sound for duplicate-path zones (and ~25% faster than
  align mode in the probe); (c) bbox border gating is the correct
  candidate filter, since content overlap requires spatial adjacency;
  (d) the H2023 3,860 merge was real content fusion, not co-location —
  seam quality still owner-inspected at the gate. Hook-chain liveness
  self-test PASSED in the same probe (results_RS1.log grew after the
  CRLF normalization). [H2023] (2026-07-24)

- **A merge/align leaves the SOURCE components in the scene alongside
  the fused component.** Smoke E2E of the reworked merge driver
  (2026-07-24): after fusing 78+42, the peel loop read components
  [120, 78, 42] — the fusion PLUS both originals. The legacy
  maximal-only export naturally picked the fused one, which is why
  this went unnoticed. Consequences: (a) any all-components export of
  a merge scene contains residual source copies — consumers must
  attribute, not enumerate (merge_zones.attribute_result: largest-first
  subset matching, residual = count equal to an already-consumed
  input); (b) component COUNT in a merge scene is not "how many
  features" — never use it directly. Discovered: peel harvest counts +
  exact 120=78+42 arithmetic. [H2023] (2026-07-24)
- **Peel-loop terminal state: -selectMaximalComponent on an EMPTY scene
  silently no-ops and the following -renameSelectedComponent fails
  E_INVALIDARG 0x80070057 (2147942487) "in 0 seconds"** — there is no
  CLI query for "how many components remain", so the tolerated rename
  failure IS the loop's exhaustion signal (:run_peelrename, marker
  moved to expected_peelend_<inst>.txt as evidence). Same pattern as
  the tolerated 18002 flight-log import. [H2023] (2026-07-24)

- **Calibration XMP sidecars at align time cut zone_1 fragmentation
  from 9 components to 3** at equal-or-better registration (fresh run
  4,405/4,540 = 97.0% vs production 4,392 = 96.7%; same imagery, same
  box). Discovered: 2026-07-24 fresh end-to-end run — the production
  zones were batched BEFORE the calibration-sidecar work, the fresh
  zones with it. Confirms the camera-registry design decision; details
  docs/FRESH_RUN_2026-07-24.md. [H2023] (2026-07-24)
- **Component fusion can DROP a small number of cameras: hull c0+c1
  (3,026+714=3,740) fused to 3,738 (merge mode) and 3,739 (both
  align-mode rungs)** — a −2/−1/−1 pattern, so the loss is real but
  not a fixed set. Exact-additivity attribution therefore cannot
  assume fusions conserve cameras; the driver's acceptance
  (never-shrink + exact membership) auto-rejected and carried the
  intact inputs forward. Bounded-loss acceptance is an OWNER decision,
  not a driver default. CORRECTED 2026-07-25: an earlier entry said
  "3,738 on all three rungs" — the peel counts are [3738]/[3739]/[3739].
  Follow-up (2026-07-25 ICP over peel poses): merge-mode's confirmed
  drop is C231C1034 (no fused pose within 2 m); the second is masked by
  a ~0.55 m MEDIAN non-rigid deformation of the merged solution vs
  zone_1's own solve — itself a notable fact for seam/residual
  expectations. [H2023] (2026-07-25)
- **Fresh-run end-to-end result (2026-07-24): 4,507/4,598 unique
  images (98.0%) across four feature components** (hull 3,026 + hull
  strip 714 + bow 665 + west pocket 102), assembled georeferenced in
  one project; zone_2 (852 imgs, 11.9% reg) is transit imagery whose
  only aligned part twins the west pocket (twin-dropped, zero loss).
  The feature-aware pipeline (cluster partition → ladder → convergence
  → assembly → evaluation gate) ran end to end unattended. [H2023]
  (2026-07-24)

- **[RECON 2026-07-25] GOVERNING REFRAME (owner-driven): the week's
  pathologies share one upstream cause — the rig's metrology never
  reached the solver.** Until 2026-07-25, every alignment ran with
  position-only priors at 10x-inflated claimed accuracy (10/10/1 m vs
  the rig's real DVL 1 m XY / Paro 0.1 m Z), no orientation priors
  (custom 13-column flight-log format never installed), and the
  fisheye solved through brown3. Re-read under that lens:
  fragmentation (9->3 components from calibration groups alone — a
  partial priors fix — with the residual c0/c1 hull split likely the
  same disease), the merge's 0.55 m median solve-to-solve deformation
  (a DIRECT measurement of under-constraint), the -2/-1 fusion camera
  drops (loose seam cameras), zone_2's 11.9% and the 91 "genuinely
  unregistrable" orphans (concluded under broken priors — transit
  imagery is exactly where nav priors should carry registration), and
  the high residuals the owner observed. Consequence for priorities:
  priors v2 (testing/PRIORS_DISTORTION_TEST_PLAN.md) is the MAIN
  LINE; merge-repair machinery (ladder, attribution, bounded-loss)
  re-evaluates as insurance after re-alignment under real priors.
  Verification-culture lesson recorded: every automated oracle
  measured QUANTITY (census counts, component counts) and none
  measured QUALITY (residuals, prior-vs-solved deviation,
  solve-to-solve deformation) — solve quality was an unnamed
  blindness; the GUI was its only detector. Residual extraction and
  deformation-vs-zone-solve checks are to become standing oracles
  alongside the census. (2026-07-25)
- **[RECON 2026-07-25] SUPERSEDED-RISK flag on NA167 D1/D2** ("georef
  merging never manifested headless"): those cells fed the flag
  components georeferenced from position-only priors with 10 m claimed
  accuracy — the feature's documented premise ("each is georeferenced")
  was arguably never met. Do not treat D1/D2 as final until re-tested
  with priors-v2 components (queued as a PD follow-on cell). The
  content-fusion rule (D7 RESOLVED) stands regardless — it explains
  every observed fusion; what is in doubt is only whether the
  georef-flag path ALSO works when georeferencing is real. (2026-07-25)

- **SUPERSEDED (2026-07-25): "zone_2 is transit imagery whose images
  are genuinely unregistrable."** PD-2b re-aligned the same 852 images
  under Division + orientation priors @15° + real accuracies (1/1/0.1):
  **812/852 registered (95.3%) vs 101/852 (11.9%)** under the old
  config — an 8x improvement from configuration alone, no data change.
  Components [621, 102, 57, 32]; the 621-camera corridor spans the
  hull->bow->pocket connecting extent. Zone_2 is the physical BRIDGE
  between the features, not filler. Every "unregistrable" verdict
  rendered under the pre-2026-07-25 config (including the 91-orphan
  pool and production zone_2's "48 genuinely unregistrable") is
  untrusted until re-tested. Discovered: PD-2b cell, 10.5 min.
  [H2023] (2026-07-25)

- **CRITICAL — THE FRESH-RUN HULL COMPONENTS ARE AT ~1/5 TRUE SCALE;
  THE DELIVERED ASSEMBLY IS METRICALLY INCOHERENT** (2026-07-25).
  Per-component solved-vs-nav pairwise-distance ratio (rotation- and
  translation-invariant), fresh zone_1: **c0 (hull main, 3,026 cams)
  = 0.175** (IQR 0.168–0.186), **c1 (hull strip, 714) = 0.220**,
  c2 (bow, 665) = 1.011. Fresh zone_2 = 0.902, zone_3 = 0.965–0.991.
  So two components holding 82% of the delivered assembly's cameras
  are ~5.7x and ~4.5x SMALLER than reality, while the rest are sound.
  Three independent confirmations:
  1. **Constant across scale bands** — the ratio holds at 0.197 / 0.181
     / 0.185 / 0.179 / 0.174 / 0.174 across 1-2, 2-4, 4-8, 8-16, 16-32,
     32-64 m nav-distance bins. A pure SIMILARITY (uniform scale) error,
     NOT drift, fold, or accumulating error.
  2. **Implied ROV speed** — hull solve says 0.01 m/s (implausible for
     a vehicle surveying a 64 m hull); nav says 0.08 m/s (plausible
     slow inspection). On the bow, solve 0.22 m/s == nav 0.21 m/s.
     Nav is right; the hull solve is wrong.
  3. **The rig as an independent ruler** — the fixed C-P baseline
     measures 1.11-1.21 m in metrically sound components but 0.22 m in
     hull c0, i.e. 0.20x. Agrees with the nav-derived 0.175x without
     using nav at all.
  Consequences, all previously mis-attributed: (a) the owner's "high
  residuals" — position priors in metres cannot be satisfied by a
  5.7x-shrunken solve; (b) the c0+c1 fusion camera drops (-2/-1) — the
  merge was asked to rigidly fuse two bodies whose scales differ by
  26% (0.175 vs 0.220), which is geometrically impossible without a
  similarity transform; the never-shrink gate rejecting it was RIGHT
  for a deeper reason than we knew; (c) the 0.55 m merge deformation.
  A uniform scale error is INVISIBLE in the viewer, which is why
  "all components look good" was true and still is - locally.
  NOT chronic: the older production run's zone_1 components measure
  0.77-1.01. Something about the fresh run's zone_1 solve specifically
  lost scale. Root cause NOT yet established. [H2023] (2026-07-25)
- **RIG GEOMETRY VALIDATED — the georef module's mount angles AND lever
  arms are CORRECT.** Measured on two INDEPENDENT metrically-sound
  solves (bow c2 from the zone_1 align; zone_2 from PD-2b): C-vs-P
  optical-axis angle **47.2°/46.8°** vs the code's 45.0°, and **C above
  P by +1.12 m / +1.03 m** vs the code's implied +1.00 m (P at 1 m
  forward + 1 m down, C at 1 m forward). |P-C| separation 1.21/1.11 m.
  Both mounts at 1 m forward is confirmed (residual relative forward
  offset ~0.15 m, negligible). **RETRACTION:** an earlier entry in this
  session claimed the Port lever arm was wrong by ~1 m. That was
  measured inside hull c0 - the 0.175-scale component - so both its
  separation (0.22 m) and its "vertical" component were meaningless.
  Only the ANGLE from that measurement was valid (angles are invariant
  under scale and rotation). Owner's recollection of "~0.5 m" spacing
  is ~half the measured value; the code's 1.0 m stands, corroborated
  twice. [H2023] (2026-07-25)
- SUPERSEDED (2026-07-25, see the two entries above): **RIG GEOMETRY
  MEASURED FROM THE SOLVE (2,169 near-simultaneous C/P pairs, zone_1
  fresh run). Mount angles CONFIRMED; the PORT LEVER ARM IS WRONG BY
  ~1 m.**
  - C-vs-P optical-axis angle: **47.2°** (IQR 47.0–47.4) vs the code's
    45.0° — owner's "C = 45° down, P = straight-on" CONFIRMED (2.2°
    residual is mount tolerance / solve bias, not a structural error).
  - |P − C| separation: **0.22 m** (IQR 0.21–0.28) vs the 1.00 m the
    code implies. Vertical component: **0.00 m** (IQR −0.09..+0.04) vs
    the code's "P sits 1 m below C". P is ~0.17 m *ahead* of C.
  - Method (immune to the absolute-frame weakness that spoiled the
    earlier mount derivation): both quantities are RIG-INTERNAL —
    relative axis angle and relative position between two cameras on
    one rigid vehicle — so they are observable in any solve regardless
    of how weakly the scene's absolute attitude is constrained. The
    positions used are ECEF (metric) from a georeferenced solve, and
    the 10 m-loose position priors of that run mean the VISUAL solution
    dominated: 0.22 m is what the imagery says, against a 1 m prior.
  - **Why this now matters more than it used to:** with position
    accuracies tightened to 1 m XY / 0.1 m Z (2026-07-25), a 1 m
    lever-arm error in Z is a ~10-sigma conflict on EVERY Port frame,
    where the old 10/10/1 accuracies absorbed it silently. Prime
    suspect for elevated residuals, and a candidate cause of the PD-4
    zone_1 collapse (dense interleaved P/C frames accumulate the
    conflict; sparse zone_2/zone_3 showed no harm from tight positions
    alone — PD-0a neutral). Owner confirmation of true rig offsets
    requested before overwriting `_get_camera_offsets`. [H2023]
    (2026-07-25)
- **`LensDistortionPrior="Approximate"` with NO coefficients supplied
  does NOT pin distortion to zero** — cinema has carried exactly that
  since the camera registry was written and still solved k1 = −0.0524
  over 2,204 cameras. An earlier caution in this session ("Approximate
  would assert approximately-zero distortion, wrong for a fisheye")
  was WRONG; `Unknown` merely withheld a hint. Port/Starboard moved to
  `Approximate` per owner directive. Supplying measured coefficients
  remains a further refinement (must be measured under Division — the
  single-parameter division model is not the brown3 k1). [H2023]
  (2026-07-25)

- **DEFECT (fixed): AlignZone's identity harvest PERMANENTLY STRIPS
  calibration sidecars from the image tree.** The harvest PowerShell
  MOVES every pose-bearing .xmp into identity_r<K>; the last-peeled
  component's sidecars are never re-exported, so those images end up
  with no calibration prior at all. Measured on fresh zone_1: **796 of
  4,540 images (17.5%) had no sidecar** - the ENTIRE bow component
  (665/665), 123 of c0, and 8 unregistered. Consequence: any re-align
  of an already-harvested zone silently runs with a partially
  ungrouped camera set (the WCA JPGs are EXIF-identical, so the XMP
  group is the ONLY thing separating Port from Cinema). **PD-4 and
  PD-4a both re-aligned zone_1 in this state, so their "collapse"
  results (669 and 782 of 4,540) are CONFOUNDED and cannot be read as
  evidence against Division or tight priors.** Fixed:
  `camera_registry.ensure_calibration_sidecars()` regenerates any
  missing sidecar from the registry, and the alignment module now
  calls it after every zone align. Discovered while building the bow
  fixture - 665 images copied, 0 sidecars came with them. [H2023]
  (2026-07-25)
- **A metric-scale oracle now exists** (`testing/scale_oracle.py`):
  median solved-vs-nav pairwise-distance ratio per component,
  invariant to translation and rotation. Self-test reproduces the
  hand-derived figures exactly (fresh zone_1 c0 0.175 / c1 0.221 /
  c2 1.009), i.e. validated against a known-bad AND a known-good case
  before use. This closes the "quantity-only oracle" blindness named
  in the 2026-07-25 reframe: every future align cell reports SCALE,
  not just registration count. [H2023] (2026-07-25)

- **Over-tight position priors FRAGMENT solves and worsen scale** — bow
  2x2 (665-image known-good component, clean sidecars, scale oracle):
  loose 10/10/1 gave ONE component at scale 1.049 (Brown3) / 0.989
  (Division); tight 1/1/0.1 split it into 2 and 3 components and pushed
  the maximal component's scale to 0.886 / 0.826. Registration barely
  moved (656-665 in every cell) - which is precisely why a
  camera-counting oracle never caught it, and why the zone_1 "collapse"
  was misread as a Division or memory problem. LESSON: the flight-log
  accuracy columns want END-TO-END per-image position uncertainty
  (timestamp matching + nav interpolation + lever arm + dive drift),
  NOT the instantaneous sensor spec. The owner's DVL 1 m / Paro 0.1 m
  are sensor figures; using them as prior accuracy over-constrains the
  solve. Reverted to 10/10/1; intermediate ladder queued. [H2023]
  (2026-07-25)

- **RESOLVED: the hull scale error is fixed by the corrected alignment
  configuration.** PD-6 re-aligned fresh zone_1 with Division + explicit
  loose 10/10/1 position priors + calibration sidecars intact:
  **c0 = 3,738 cams at scale 0.981** (IQR 0.949-1.027) and c1 = 656 at
  1.076, total 4,394/4,540 in 67.7 min. Against the baseline's
  4,405/4,540 in THREE components at hull scale 0.175/0.221. So:
  registration unchanged within noise (-11, 0.24%), components 3 -> 2,
  and metric validity restored. Note the hull now solves as ONE
  3,738-camera component natively - exactly the object the merge stage
  was straining to build by fusing c0+c1 (3,026+714=3,740, dropping 2
  cameras in the attempt). The within-zone hull split was itself an
  artifact of the broken configuration, not real geography.
  ATTRIBUTION: two things changed vs baseline - (a) Brown3 -> Division,
  and (b) the accuracy columns are now actually imported (baseline ran
  before the 13-column format was installed, so RS fell back to global
  prior defaults). Division is the physically motivated candidate: the
  Port fisheye forced through a 3-parameter radial model biases the
  focal estimate, and in this geometry focal error maps directly to
  reconstruction scale. A Brown3 + explicit-loose isolation cell on
  zone_1 (~70 min) would settle it; not run, since the corrected config
  is adopted either way. **Owner's instinct that Division was right for
  the fisheye was correct, and its real payoff was metric validity, not
  registration count.** [H2023] (2026-07-25)

- **DEFECT (fixed): AlignZone.bat does not write component manifests —
  only the alignment MODULE does, so any driver invoking the .bat
  directly produces exports the feature-aware merge refuses.** PD-6's
  components carried an identity harvest (identity_r0/r1) and two
  .rsalign exports but ZERO `.rsalign.manifest.json`, because
  `relaunch_pd6.py` calls `RealityScanCLI.run_batch_script` and skips
  the module's post-align manifest step. `merge_zones.load_inputs`
  refuses unmanifested components by design (no membership → no
  border-gating, twin resolution, or attribution), so the corrected
  zone_1 could not have fed the assembly at all. Discovered by
  directory listing while planning the assembly re-run, not by any
  failure — the align reported success. Fixed by making
  `RealityScanAlignment.capture_component_identities` public (ONE
  implementation, per the no-second-way rule) and calling it from
  `relaunch_pd6.py`; manifests rebuilt for the existing PD-6 exports
  from the on-disk harvest (3,738 / 656 cameras, matching the census).
  LESSON: the .bat/module split means "success" from a direct .bat
  driver is a weaker claim than success from the module — research
  cells that must feed production stages have to replay the module's
  post-processing. [H2023] (2026-07-25)

- **The corrected zone_1 leaves NOTHING for the merge ladder to do.**
  Dry-run of `merge_zones.partition_clusters` over the PD-6 exports +
  zone_3: three spatially disjoint singleton clusters — hull 3,738
  (bbox Y 2345096–2345160), bow 656 (Y 2345217–2345251), west pocket
  102 (Y 2345248–2345256) — zero discards, zero fusable pairs. The
  fresh run spent ~75 min on a hull ladder whose entire purpose was to
  fuse c0+c1 into the object the corrected config now solves natively.
  Confirms the GOVERNING INTENT reading from the data: this dive's end
  state is three feature components, and merge work on it is
  self-inflicted. Scale oracle over all fresh zones for the record:
  zone_2 c0 0.998 (101 cams), zone_3 c0 0.990 (102), PD-6 zone_1 c0
  0.982 (3,738) / c1 1.075 (656) — only the old zone_1 hull was ever
  metrically broken. [H2023] (2026-07-25)

- **The corrected assembly is built: 3 components, 4,496/4,600 (97.7%).**
  `merged_pd6` ran in 1.5 min of solve time — three singleton clusters,
  zero merge attempts, straight to assembly; project
  `D:\na156_h2023_fresh\merged_pd6\assembly\H2023_PD6_Assembly.rsproj`
  (sfm0/1/2 = 2,489/295/44 MB, proportional to 3,738/656/102 cameras).
  The run's ONE error line — `result code 2181038335` = **0x820000FF**,
  the documented err:18002 warning class — was verified benign by
  matching all 102 "not found in the current scene" images against every
  component manifest: **zero overlap**, i.e. they are exactly the
  unregistered remainder (4,598 union-log rows − 4,496 cameras = 102).
  `Trajectory imported successfully` and `update` both followed.
  Confirms the standing rule: importing a union log that covers
  unregistered images always raises this warning, and the census, not
  the exit status, is what settles a merge. [H2023] (2026-07-25)

- **DEFECT (fixed): `merge_report.json`'s `census_after_update` was
  structurally incapable of measuring the assembly, and reported 0 for a
  sound 4,496-camera result.** Assemble mode exports no XMPs by design
  (it imports components and georeferences them), so the
  `sanitize_and_census(images_root)` call after it scans pose sidecars
  that assembly never wrote — it reads leftovers from whichever stage
  ran last, and reads zero once a prior stage has sanitized the tree.
  Discovered by disbelieving a 0 next to `workflow_success: true`.
  Replaced with `cameras_from_manifests` (the manifest sum, the same
  number EVALUATION READY reports), tagged as coming from the inputs.
  LESSON per provenance: a number keeps the tag it had when produced, and
  a census that cannot see its subject must not be published under a name
  that claims it did. [H2023] (2026-07-25)

- **BLINDNESS (open): the metric-scale oracle cannot see the
  DELIVERABLE.** `scale_oracle.py` needs pose XMPs, which only an
  identity harvest produces; assemble mode saves and quits without
  exporting any. So scale is measured on the assembly's INPUTS while
  `-update` — a similarity fit to the nav constraints, and therefore
  exactly the step that can set scale — runs afterwards unobserved.
  The 0.982/1.075/0.990 figures for `merged_pd6` are pre-assembly.
  EVALUATION_READY.txt now says so in the report itself rather than
  leaving the reader to assume. Closing it means porting the
  successive-difference harvest to a dated COPY of the assembly project
  (already queued as workflow-evaluation item 3), which yields
  per-component membership and a measurable deliverable in one step.
  [H2023] (2026-07-25)

## Resource envelope & monitoring

- **Near-OOM, RealityScan slows to a crawl WITHOUT crashing and WITHOUT
  spilling to NVMe** — indistinguishable in the progress feed from a
  hang, making memory pressure the THIRD cause of persistent #timeout.
  Mitigation: RealityScanCLI samples available RAM (GlobalMemoryStatusEx),
  warns below 4 GB free, includes the RAM figure in stall warnings.
  MEASUREMENT CAVEAT (owner-caught): workflows run MULTIPLE
  RealityScan.exe processes (persistent instance + transient helpers) —
  identify the instance by largest working set or tracked PID before
  quoting memory numbers (a "2.2 GB during a 4,540-image align" misread
  was a 30 MB transient; the instance was ~11 GB + 4 GB VRAM).
  Processing box: 93.6 GB RAM. [H2023] (2026-07-24)
- **Memory bounds observed**: per-zone aligns ≤ ~60 GB (NA167 ~1.5k
  images/zone); joint 4,131-image align ~165 GB peak on a 192 GB box.
  [NA167 #19] (2026-07-24)

## Rig & data

- **H2023 contains TWO discrete physical features — the bow and the
  main hull of the wreck, surveyed as separate chunks in one dive**
  (owner-stated 2026-07-24). Zones are batched on image DENSITY, not
  features, so zone boundaries are blind to feature boundaries; a
  discrete feature's component may simply be smaller than the main
  hull's and can NEVER fuse with it visually. Consequences (owner
  intent, governs all component handling): a multi-component terminal
  state is a CORRECT outcome; "as big as it can get" is judged
  PER FEATURE, not per scene; no deletion/export/success logic may be
  size-based — only containment-based (no unique images) deletion is
  ever legal; a maximal-fraction success target misreads disjoint
  features as merge failure. Expect this pattern in other dives.
  [H2023, owner] (2026-07-24)
- **Four physical cameras** (owner-confirmed): Zeuss rect 23 mm; Port
  (aka cammid) fisheye 14 mm; Cinema (aka camlower) rect 17 mm;
  Starboard (aka camupper) fisheye 14 mm. NA156 mounts: Port 0 deg,
  1 m fwd + 1 m down; Cinema 45 deg down, 1 m fwd. S231C*.mov videos on
  D:\H2023 ARE Starboard (excluded for photogrammetry). [H2023] (2026-07-23)
- **ROVDataConcat**: georeferencers require stage-2 kalman columns
  (final_datatable.csv); H2023 nav covers 2023-11-03T19:44 to
  2023-11-04T05:48; H2023 has no geotiff (kalman_offset fails, harmless
  for photogrammetry). Multiple nav CSVs per dive collide into one dict
  key — find_rov_datafiles prefers *final_datatable.csv [NA167 #9].
  [H2023 + NA167] (2026-07-23)
- **Full-file image verification is untenable at scale** — PIL
  .verify() ≈ 720 GB of reads over 18k stills; header-probe cut the
  stage to ~5 min. [NA167 #7] (2026-07-22)
- **CLAHE preprocessing: scope is EMPIRICALLY CONTESTED** — zone_9
  (NA173): baseline aligns to NOTHING, CLAHE 2.0/8×8 rescues it
  (validated default-on here). LilyJean stereo pairs (COLMAP pipeline,
  3,607 pairs): both adaptive enhancement and fixed backscatter
  subtraction REDUCED registration ~30% vs originals. Both results are
  real; scope unresolved; reconciliation matrix Q-05 queued (zone_9 ×
  COLMAP, LilyJean × RealityScan, judged on REGISTRATION). If CLAHE
  ends up texture-only, RealityScan Image Layers
  (.geometry/.texture/.mask) are the official reconciling mechanism.
  See docs/COLMAP_CROSSOVER.md. [H2023 + LilyJean fact base via
  HANDOFF] (2026-07-23)
  - UPDATE 2026-07-24: full COLMAP fact base received from owner
    (frozen copy docs/COLMAP_FINDINGS_UNIFIED.md). Its candidate
    explanations for the conflict (F-20260723-33): ENGINE (RealityScan
    applies internal tone mapping pre-detection), DETECTOR, or IMAGERY
    REGIME (zone_9 baseline catastrophically flat vs LilyJean baseline
    that aligns well). Also externally corroborated on the COLMAP side
    (Summers & Jones, arXiv:2507.21715: enhancement generally degrades
    feature matching; raw preferred). Their standing policy — geometry
    on originals, color-correct only at texturing — is the opposite of
    this pipeline's default; Q-05's four cells decide the
    documentation-guide policy for both.
- **Cross-engine Zeuss-camera anomaly** — COLMAP zone_9: 710 zeuss
  frames REGISTERED but with ZERO triangulated points (contribute
  nothing downstream; C-20260721-15/Q-07 in the COLMAP fact base) —
  independently echoing this line's NA167 zone_13 A/B where XMP priors
  cost 6.7 points of registration specifically on Zeuss [NA167 #4].
  Two engines, two failure shapes, one physical camera family: treat
  Zeuss calibration/imagery as suspect and prioritize per-camera
  validation when Zeuss zones underperform. [RECON, via COLMAP fact
  base] (2026-07-24)

## Windows & automation traps

- **cmd: exit /b N inside a MULTI-STATEMENT parenthesized block returns
  0 to the caller**; the single-line `( echo msg & exit /b 1 )` form
  propagates correctly. Never put exit /b inside multi-line parens; use
  single-line chains or goto. [H2023] (2026-07-23)
  - **REFINED 2026-07-24 by direct measurement** (four probe .bats,
    `cmd //c`, before/after on MergeZoneComponents.bat). The code is
    lost in exactly ONE configuration: `exit /b` sitting inside an
    outer multi-line parenthesized block (an `if (...)` body or a
    `for ... do (...)` body) in the body of the script that IS the
    process entry point. Measured:
    - top-level `( echo … & exit /b 1 )` → **1** (correct);
    - top-level multi-line `if … (` … `exit /b 1` `)` → **1** (correct
      — the original review finding over-reached here);
    - `exit /b 1` in an `if`-block nested inside `if defined … (` → **0**;
    - `exit /b 1` in an `if`-block nested inside a `for /f … do (` → **0**;
    - the same nested shapes inside a `call :label` SUBROUTINE → **1**;
    - the same nested shape in a `call`ed CHILD .bat → **1**.
    Consequences, both verified rather than assumed: (a) the shared
    `:run` abort contract is **LIVE** — a probe replicating `:run` with
    a non-empty errors marker aborts (exit 1) and with an empty one
    continues, so `call :run … || goto :fail` does detect RealityScan
    errors in every workflow; (b) `startRealityScan.bat`'s nested
    boot-timeout `exit /b 1` propagates correctly through `call`, so
    the "timeout exit-code shape" review item is a NON-ISSUE; (c) the
    only genuinely broken sites were MergeZoneComponents.bat's
    top-level complist validations (missing complist, missing
    component) — both returned 0, i.e. an unreadable component list
    would have been reported and then IGNORED by the driver. Fixed by
    routing every validation to a top-level `:argfail` label.
    [H2023] (2026-07-24)
- **cmd label-search fails on LF-only line endings** — "cannot find the
  batch label" strikes intermittently at LF-only byte offsets, even
  after earlier `call :label` calls in the same file succeeded. All
  .bat/.vbs must be CRLF; .gitattributes pins *.bat and *.vbs eol=crlf;
  normalize after any scripted edit. [H2023 + NA167 #21, independently
  hit on BOTH machines] (2026-07-23)
- **Git Bash mangles cmd switches** — `cmd /c foo.bat` under MSYS
  converts /c to C:\ and launches an interactive cmd that exits 0
  silently. Use `cmd //c` or PowerShell for .bat invocation tests.
  [H2023] (2026-07-23)
- **VBS quote-escaping in string literals is a trap — compose with
  Chr(34)** — CRITICAL SELF-INFLICTED: malformed ErrorWriterLaunch.vbs
  quoting meant ErrorWriter.bat NEVER RAN and the errors-marker system
  was inert for ~a day of runs (caught by review; completed results
  remained trustworthy because they were validated by census/manifest
  data). Diagnostic: the hook fires for every completed process incl.
  heartbeats, so an active progress file WITHOUT a results log is proof
  the hook is dead. After ANY hook-chain change, verify
  results_<inst>.log grows during the next run. [H2023] (2026-07-24)
- **Unattended prompts must catch EOFError, not trust isatty()** —
  hidden consoles report isatty()=True with an EOF stdin. [H2023]
  (2026-07-24)
- **cmd/stdin encoding breaks scripted prompts** — PowerShell native
  piping prepends a BOM and delivers CRLF (`input()` returned "a\r").
  .strip() everywhere; scripted input() in drivers. [NA167 #10]
  (2026-07-22)
- **ASCII-only console output everywhere** (cp1252 crashes; hit twice).
  PYTHONIOENCODING=utf-8 when parsing UTF-8 sources. [both lines]
- **One-off cmd anomaly, unexplained**: after D6's 56-min merge block,
  `%RealityScan%` expanded empty ("'-delegateTo' is not recognized") —
  single occurrence across ~10 identical workflows; the export step
  died. Watch for recurrence. [NA167 #31 note] (2026-07-24)

## Process conventions

- RC_projects daily save schema: {expedition_dive}_{zone|merged}_YYYYMMDD
  .rsproj in RC_projects one level up from the zone image directory;
  saves after components / merge / texture / final model. (owner
  requirement 2026-07-23)
- **Final per-zone alignment projects are the AUTHORITATIVE artifacts;
  the cross-zone merged project is derived and never trusted over
  them** (owner rationale 2026-07-24). The saved zone project = the
  post-growth accepted state ("as big as the components got
  within-zone"), all images re-enabled, paired with its identity
  manifests as one recovery unit. Three reasons: (a) hand-evaluation
  fallback when the merged result looks wrong — it shows exactly what
  the merge stage was handed, per feature; (b) per-component identity
  is only harvestable from the original aligning scene (B10 ordinal
  rule) and re-alignment is nondeterministic, so a lost zone project
  means unrebuildable identity; (c) the merge stage is the
  least-proven link (D7 open, silent non-merge modes on record) —
  recovery from a bad merge must never require re-running the stage
  upstream of these saves. (2026-07-24)
- Model recipe (owner 2026-07-23): high → remove marginal → remove
  large(30) → largest component → closeHoles+clean → simplify(noise)
  → texture → 4× simplify(smooth 80%)+clean → unwrap → reproject.
  Keep: raw high, textured pre-simplify, textured post-simplify.
  Texture AFTER closeHoles so fill areas get blended image color;
  reprojection then maps manifold→manifold (no nodata).
- Never run RealityScan headless for owner-attended runs: RS_HEADLESS=0.
- Verify merges/grows by camera census, never exit status (multiple
  silent-failure modes are on record: silent non-merge, silent no-op
  selects, inert error hook).
- Forum-mining rules (owner directive 2026-07-23): staff replies
  outrank user lore; only posts ≤4 years old trusted; pre-rename
  (RealityCapture-era) posts get most suspicion; every adopted gem goes
  here with URL, author status, date, verification status.

## H2024 run + ROVDataConcat (2026-07-25 evening)

- **Hook-chain liveness PASSED — the standing self-test owed since the
  2026-07-24 CRLF normalization is now CLOSED.** `results_RS1.log` grew
  with fresh entries (22:17:02 → 22:17:12, six completions) during the
  H2023 model run, so `appProcessAction=ExecuteProgram` →
  `ErrorWriterLaunch.vbs` → `ErrorWriter.bat` still fires end to end
  after the .vbs/.bat line-ending changes. Discovered by reading the
  marker directory during a live run. [H2023] (2026-07-25)

- **ROVDataConcat: `main_kalman.py` exits 0 even when a module FAILS.**
  The H2024 stage-2 run printed `ERROR in kalman_offset: No GeoTIFF
  matching 'H2024_k2mapping_geotiff*.tif'`, then `Aborting:
  kalman_offset failed; downstream modules depend on its output`, and
  the run summary listed `kalman_offset FAILED` — yet the process
  returned exit code 0. Any caller gating on exit status treats a
  failed pipeline as success. Discovered by reading the log of a run
  whose exit code said success. Harmless for photogrammetry (the
  needed `*_final_datatable.csv` comes from `kalman_filter`, which
  succeeded; `kalman_offset` only produces the Unreal upload file),
  but it is a silent-failure channel in a tool this pipeline depends
  on. [H2024] (2026-07-25)

- **ROVDataConcat stage-1 resume detection is EXPEDITION-WIDE, not
  per-dive** — `STEP_OUTPUT_GLOBS` matches `*/[!.]*_<output>.csv` under
  `RUMI_processed`, so a step counts as done if ANY dive has its
  output. Consequence: a single new dive cannot be extracted by simply
  running the orchestrator (every step is skipped because older dives
  satisfy the glob), and `--force` is all-or-nothing across the whole
  expedition. This is why the first H2024 attempt "finished way too
  fast": stage 1 was skipped entirely and stage 2 consumed pre-existing
  2026-07-23 extracts. Discovered by reading `step_outputs_exist` after
  the owner flagged the runtime as implausible. Mitigation used:
  backed up `RUMI_processed` and ran `main.py --force` for the whole
  expedition. [H2024] (2026-07-25)

- **H2024 imagery is clean and rig-identical to H2023.** All 8,197 JPGs
  under `F:\H2024\Images\edited` fully DECODE (not merely verify) with
  zero corruption, and `camera_registry.identify` classifies every one:
  cinema 4,100 + port 4,097, zero unknown — confirming the owner's
  "camera locations are the same as H2023". ANOMALY: exactly one image,
  `C231C2370_20231104202628_edt.jpg`, is 3846x2163 while the other
  8,196 are 4244x2827. A different sensor footprint means different
  intrinsics, so RealityScan will group it separately from the rest of
  the cinema set regardless of its XMP calibration group. Discovered by
  a full-decode validation pass with a dimension census. [H2024]
  (2026-07-25)

- **The hull model CRASHED RealityScan at `closeHoles`/`cleanModel`** —
  minidump `RealityScanCrash-20260726-054742.dmp` written at 01:47:42
  local, and the workflow's next command could not be delegated at all
  (`ERROR: Failed to delegate command: -renameSelectedModel
  "pd6_zone_1_c0_Manifold"`), which is the signature of a dead instance
  rather than a rejected operation. Step [5/8] on the 3,738-camera hull
  is the largest mesh in the deliverable. `merge_zones` recorded
  `success: false` for `pd6_zone_1_c0` and correctly carried on to the
  next component, so bow and torpedo were unaffected. The crash itself
  is ESTABLISHED; its attribution is not - see the SUPERSEDED clause
  next. [H2023] (2026-07-26)
  - **SUPERSEDED (same night, by timeline evidence): "the crash was
    caused by contention from the H2024 CLAHE + zone copy."** The claim
    was that CLAHE at 12 workers and a 9,835-file copy ran concurrently
    with the hull "for the whole window". File mtimes refute it: CLAHE
    output spans 22:30:42-22:33:51 (THREE minutes) and the zone copy
    02:43:57-02:45:15 (78 seconds), while the crash was at 01:47:43 -
    neither was running. The only concurrent load was the batcher's
    zone-computation phase, a single Python process. Lesson: "was
    something else running?" is answerable from mtimes and should be
    checked before it is asserted as a prime suspect; the near-OOM
    precedent made a memory story feel plausible without evidence.
    Corrected reading at the time: the crash is most likely INTRINSIC to
    `closeHoles`/`cleanModel` at this mesh size, so a clean-box retry is
    a cheap discriminator rather than an expected fix. (2026-07-26)
  - **SUPERSEDED IN TURN (2026-07-26, by the retry's exit code): the cause
    was neither contention NOR intrinsic memory - it was the DISK.** The
    clean-box retry reached step [6/8] and failed with
    `0x80070070 ERROR_DISK_FULL` on a `D:` drive at 0 bytes free. See the
    ROOT CAUSE entry below. Both memory stories are retired as causes; the
    memory readings were real but incidental.

- **H2024 prep completed clean end to end.** Georeference 8,197/8,197
  (100% acceptance, all exact matches, zone 4Q), CLAHE 2.0/8x8 on
  8,197 with 0 failures, density batch into 5 zones (2,983 / 1,537 /
  1,279 / 1,413 / 2,623 = 9,835 with overlap bands, 8,197 unique).
  Every zone carries per-camera subfolders, a per-zone flight log, and
  a 1:1 calibration sidecar for every image (`b_xmp_priors true`
  verified by count). Reaching this took four attempts, each blocked by
  a separate real defect - see the four fixes committed 2026-07-25
  evening. [H2024] (2026-07-26)

- **The image batcher spends HOURS in zone computation and seconds
  copying.** On 8,197 H2024 images the run georeferenced in ~1 min and
  CLAHE'd in 3 min, then sat in the batcher's zone-analysis phase from
  ~22:34 to 02:43 - roughly **4 h 10 min** - before writing all five
  zones in **78 seconds** (02:43:57-02:45:15). So >99% of the batch
  stage's wall clock is analysis, not I/O, on a dataset of only 8k
  points. Discovered while reconstructing the hull-crash timeline from
  file mtimes. [H2024] (2026-07-26)
  - **SUPERSEDED (same session): the 4 h 10 min was NOT analysis - it was
    `plt.show()` waiting for someone to close a window.** The batcher
    called `plt.show()` unconditionally after saving each figure; on an
    interactive backend that BLOCKS until the window is dismissed, and the
    second figure cannot even appear until the first is closed
    (owner-observed independently). An identical re-run with the call gated
    on `stdin.isatty()` completed the whole stage in **28.9 min**. So the
    "> 99% of wall clock is analysis" claim is withdrawn, and there is no
    evidence of an O(N^2) path to hunt. LESSON: I inferred an algorithmic
    cost from one wall-clock measurement without asking what the process
    was actually doing - the same error as attributing the hull crash to
    contention. A blocking UI call is indistinguishable from slow compute
    if you only look at elapsed time. The real defect was worse than the
    imagined one: an unattended pipeline stage that stalls forever on a
    window nobody is there to close. Fixed, and the plots are still written
    as PNGs. (2026-07-26)
  - **RE-OPENED (2026-07-26, later): the retraction above was itself WRONG.
    The zone computation really is slow.** A third run, with `plt.show()`
    gated off and NO window in existence, wrote `kernel_density.png` at
    12:38:31 and `batch_zones.png` at **15:31:17** - **2 h 53 min** of
    genuine compute between the two saves, since everything between them is
    KMeans + zone split/merge + overlap scoring. So the ORIGINAL finding
    stands: the batch stage is dominated by analysis, not I/O, and an
    O(N^2)-ish path is worth hunting after all. What does NOT stand is my
    explanation for it. The 28.9 min run I retracted on is now the
    UNEXPLAINED outlier - it processed the same 8,197 images with the same
    parameters and cannot have done this work in that time; whatever it
    skipped is unidentified. LESSON: I used a single faster run as a control
    without establishing that it did equivalent work, which is the same
    error as reading elapsed time as compute in the first place. The
    `plt.show()` gate remains correct on its own merits - a blocking window
    in an unattended stage is a real hazard, owner-observed - it just was
    not the cause of the 4 h. (2026-07-26)

- **Zone copies happen only AFTER the accept gate, as designed** - the
  batcher prints its per-zone table, asks `Accept these batches?
  (a)ccept, (r)eject and set new params:`, and copies only once
  accepted. Under `RS_NO_INTERACTIVE` it logs `Non-interactive run:
  batches auto-accepted` and proceeds. Confirmed in the H2024 log plus
  mtimes showing every zone file written after that line. Worth keeping
  in mind: unattended runs therefore accept whatever zoning the KDE
  produced, with no human look at the table. [H2024] (2026-07-26)

- **CLAHE 2.0/8x8 visually verified on H2024 output, with its cost
  visible too.** Eight random frames compared against the pipeline's
  actual `preprocessed_images` artifacts (read from disk, not
  re-applied): hull plating goes from flat grey to legible painted
  characters and rivet lines (`C231C4652`), and encrustation texture
  emerges from near-uniform murk (`C231C5220`, `C231C2970`) - i.e. real
  local structure for feature detection. Cost: particulate is amplified
  with the signal, invisible marine snow becomes distinct speckle, and
  water-column haze lifts with it; `C231C3153` is a near-featureless
  frame that ends up merely brighter and noisier. Consistent with the
  staff caution about detectors manufacturing noise points on turbid
  imagery, and it sharpens Q-05 rather than settling it. NOTE the
  current pipeline order (Georeference -> Preprocess -> Batch -> Align)
  means CLAHE'd imagery is what gets BOTH aligned and textured;
  RealityScan Image Layers (`.geometry`/`.texture`) is the mechanism if
  geometry should come from originals and appearance from enhanced
  images. [H2024] (2026-07-26)

- **H2024 imagery spans 2023-11-04 ~20:26 to 2023-11-05 ~01:28**, not
  the 20:26-22:24 first stated - that figure came from sorting
  filenames rather than timestamps, and the two camera prefixes
  interleave in time. Well inside the nav window (17:27 11-04 to
  02:03 11-05), which the 100%-exact georeference match confirms
  independently. Lesson: for two-camera filename families, name order
  is not time order. [H2024] (2026-07-26)

- **DEFECT (fixed): `GenerateModel.bat` used FIXED model names while
  being run once per component against ONE shared project.** Every
  `-renameSelectedModel` wrote a constant name, so from the second
  component onward the scene held duplicates - and step [8/8] resolves
  its operands by name (`-reprojectTexture "HighPoly_Textured"
  "Simplified"`), so the bow's reprojection could map the HULL's texture
  onto the bow's mesh with a clean exit status. The intermediate-cleanup
  loop also deletes by name and could remove another component's models.
  All 19 references now carry a `%model_tag%` prefix taken from the
  component. Discovered by reading the workflow before the second
  component started, not by a failure; the run was stopped mid-hull and
  restarted rather than risk a silently wrong deliverable. [H2023]
  (2026-07-25)

- **`-selectComponent` DOES resolve manifest component names in an
  assembled project.** The standing worry (manifest names vs in-scene
  names never matching, because zone scenes were saved pre-rename) does
  NOT apply to the assembly: components are imported from `.rsalign`
  files that were renamed BEFORE export, so `-selectComponent
  "pd6_zone_1_c0"` and `"pd6_zone_1_c1"` both selected and modelled
  correctly. Discovered by running the real `--auto_model` path and
  reading the per-component workflow logs. Scope note: this says nothing
  about zone scenes, where the pre-rename save still applies. [H2023]
  (2026-07-26)

- **Three unattended-run defects in the orchestrator, all fixed.**
  Found by driving the documented `RS_MODULES` / `RS_NO_INTERACTIVE`
  entry point on a new dataset; each cost one failed attempt:
  - `main.py --help` crashed with `ValueError: unsupported format
    character '>'`. argparse %-expands help text at `print_help()` time
    and `batch_xmp_priors`' description contains `96.3% -> 89.6%`. This
    killed `--help` AND every argparse error path. Escaped at the
    argparse layer, so descriptions stay readable for prompts and no
    future percent can reintroduce it.
  - The inter-module `input("Press enter to continue...")` was
    unguarded, so an unattended chain died with `EOFError` BETWEEN two
    successful modules - georeference finished 8,197/8,197 and the
    pipeline stopped there. EOF now means continue. The codebase already
    guarded its other `input()` sites; this one was missed.
  - `preprocess_images.validate_parameters` raised `TypeError:
    _path_isdir: path should be string... not NoneType` when `-p_i` was
    absent, instead of naming the missing flag. Now reports which flag
    to pass.
  LESSON: the non-TTY path had not been exercised end to end on a fresh
  dataset since the overhaul, and all three failures were in the
  scaffolding around working modules, not the modules themselves.
  [H2024] (2026-07-25)

- **`sfmDistortionModel` is GLOBAL and all-or-nothing; the per-camera XMP
  `Camera:DistortionModel` hint does NOT switch models per camera.** The
  cinema sidecars declare `brown3`, yet every one of 2,558 cinema pose
  XMPs from PD-6 came back `xcr:DistortionModel="division"` - the same
  model as the 2,492 port records. Discovered by aggregating solved
  intrinsics out of the PD-6 identity harvest. This SETTLES the open
  decision rule in `testing/PRIORS_DISTORTION_TEST_PLAN.md` ("adopt
  division-for-P only if ... if the global key is all-or-nothing"): it
  is all-or-nothing, so a mixed-optics rig gets ONE distortion model and
  only the coefficients differ per calibration group. Consequence for
  PD-6's attribution: Division was not applied to the fisheye
  selectively - it was applied to everything, and the rectilinear camera
  tolerated it (k1 -0.038, tight IQR, hull scale 0.982). Supplying
  measured coefficients remains per-group and therefore still useful.
  [H2023] (2026-07-26)

- **Solved intrinsics under the corrected (PD-6) config, and the
  calibration groups are demonstrably working.** Over 5,050 harvest
  records (4,394 unique cameras; bow members appear in two laps by the
  successive-difference design):
  - cinema, 2,558 records: focal 35mm-eq **16.374** (IQR 16.302-16.476),
    division k1 **-0.0378** (IQR -0.0415..-0.0336), principal point
    (-0.0071, -0.0031), skew 0, aspect 1.
  - port, 2,492 records: focal 35mm-eq **15.499** (IQR 15.435-15.574),
    division k1 **-0.3875** (IQR -0.3933..-0.3832), principal point
    (+0.0027, +0.0056), skew 0, aspect 1.
  Both cameras were given the SAME 16.0 mm prior, and the solve
  separated them by 5.6% with IQRs of only about +/-0.5%. Because the
  WCA JPGs are EXIF-identical, the XMP calibration groups (3 cinema /
  2 port) are the only mechanism that could have separated them - so
  this is independent confirmation that the sidecar grouping works, not
  just that it is written. The order-of-magnitude k1 gap is the fisheye
  declaring itself. Discovered by parsing `xcr:` attributes from the
  PD-6 harvest XMPs. NOTE the exports also carry
  `xcr:CalibrationGroup="-1"`/`DistortionGroup="-1"` alongside
  `Camera:CalibrationGroup="3"`; the -1 is an export artifact, not a
  lost grouping. [H2023] (2026-07-26)

- **OWNER REPORT + DIAGNOSIS: the bow model sits ~45 deg off the true
  ground plane (site is a flat mud floor). The ALIGN is not the culprit;
  orientation priors are absent where they would constrain geometry and
  present only where they can merely rotate a finished component.**
  Measured from the PD-6 harvest: the bow's solved camera cloud matches
  nav to **0.8 deg** in best-fit-plane attitude (solved 8.1 deg off
  vertical vs nav 7.3 deg), with shape ratios agreeing to three decimals
  (mid/max 0.371 vs 0.370), and its optical axes are statistically
  identical to the hull's (median 148.1 vs 147.7 deg from local up, same
  ~50 deg spread). So there is no 45 deg rotation in the zone solve.
  WHERE YPR ACTUALLY ENTERS: the PD-6 align log is 7-column
  position-only, while the assembly's union log is 13-column carrying
  Yaw/Pitch/Roll at 3/5/3 accuracies - so the ONLY consumer of
  orientation was `-update` in the assembly, a rigid/similarity fit
  applied AFTER reconstruction, which can rotate a component but cannot
  stiffen or repair its geometry.
  RANKED CANDIDATES:
  1. `-update` rotated the bow to satisfy MIS-CONVERTED orientation
     priors. The Euler order / camera-mount convention for imported YPR
     is explicitly UNVERIFIED (the planned one-minute GUI check was
     never done). NOTE: an earlier version of this candidate also cited
     "Port lever arm off by ~1 m" as independent support - that claim was
     RETRACTED on 2026-07-25 (measured inside the 0.175-scale hull) and
     must not be used as evidence here; the validated lever arms are the
     code's originals. A 656-camera component spanning 9.3 m on a
     near-1D track is cheap to rotate about that track - the fit trades
     a small position penalty for the orientation term - whereas the
     hull (3,738 cams over 17.9 m) is far stiffer. Predicts a clean
     near-rigid tilt, which matches a crisp "45 degrees".
  2. Internal deformation of the bow: scale IQR width **0.444** vs the
     hull's 0.081 (5.5x wider), which by the oracle's own semantics means
     drift/fold, not a similarity error. Explains floor NON-FLATNESS but
     not a clean 45 deg plane.
  BLINDNESS NOW LOAD-BEARING (escalation condition): assemble mode
  exports no poses, so the assembled project - the artifact the owner
  actually looked at - cannot be measured. Hypotheses can only be ranked
  until poses are harvested from a copy of the assembly.
  CHEAP DECISIVE TEST: re-run the assembly `-update` with a
  POSITION-ONLY union log and re-measure the bow's attitude; the
  assembly stage costs ~2 min. If the tilt disappears, candidate 1 is
  confirmed and the remedy is to verify the YPR convention before
  importing orientation anywhere.
  OWNER POSITION (agreed, with a caveat): pitch/roll/yaw belong in the
  ALIGNMENT priors, not merely in the post-hoc georeferencing fit - that
  is where they would anchor absolute attitude AND stiffen a solve
  against exactly the drift measured in candidate 2. Caveat: they must be
  imported at 15 deg accuracy - PROVISIONAL, not validated, see the
  contamination flag - rather than the 3/5/3 in the zone logs (tight orientation at dense scale is already suspect
  from PD-4), and the convention must be verified first - importing
  wrong-convention YPR is itself a mechanism for this defect. [H2023]
  (2026-07-26)

- **RESOLVED BY FORUM MINING: the RealityScan YPR convention, and our
  flight log is 90 deg wrong for the Port camera.** Epic staff
  **OndrejTrhan** (2023-10-23, Epic Developer Community knowledge base
  "Registration export and camera orientations"): *"Yaw = 0, image is
  oriented to Y (upper side of image is oriented that way), Pitch = 0,
  image is looking down, Roll = 0, image is parallel with X axis."*
  Composition is intrinsic Roll -> Pitch -> Yaw; Yaw about Z, Pitch about
  Y, Roll about X. The Help's Trajectory Import page adds that imported
  **YPR is interpreted in NED** (OPK is the ENU variant), that "Euler
  angles order (YPR)" is a SETTING evaluated right-to-left, and that a
  **"Camera mount"** option exists whenever YPR is included.
  OUR PITCH CONVERSION IS CORRECT - verified against the written logs.
  `_convert_to_rc_orientation` already computes
  `rc_pitch = 90 + (pitch_vehicle - camera_offset)`, i.e. it already
  references pitch to nadir. Measured in `zone_1`'s flight log: **Port
  median 88.11 deg** (n=2,267; range 86.6-89.4) = essentially horizontal
  on a 90-deg-is-horizontal scale, and **Cinema median 43.11 deg**
  (n=2,273; range 41.5-44.3) = ~45 deg down from horizontal. Both match
  the rig as the owner describes it. Discovered by forum mining at owner
  instruction (owner recalled a staff post confirming the convention -
  correct, and it is OndrejTrhan's above). [H2023] (2026-07-26)
  - **SUPERSEDED (same session, within minutes, by reading the written
    logs): "we write pitch from horizontal, so Port is 90 deg wrong and
    Cinema is coincidentally right."** FALSE. I read
    `_get_camera_pitch_offset`'s "degrees down from vehicle forward axis"
    docstring and the flight-log writer, and asserted the defect WITHOUT
    checking the function between them or the actual column values. The
    +90 conversion was already there, and one `grep` of P231C rows
    (88.1 deg, not ~0 deg) refutes the claim outright. Lesson, and it is
    the same one as the earlier contention hypothesis this session: an
    output claim must be checked against the OUTPUT, not inferred from
    two ends of a call chain. Cost: a wrong diagnosis reported to the
    owner and committed. (2026-07-26)
  STILL OPEN after the correction - the import-side settings, which our
  `FlightLogParams.xml` does NOT pin, so both fall to defaults:
  1. **Euler angles order (YPR)** - a documented import setting evaluated
     right-to-left. Our angles assume intrinsic Roll -> Pitch -> Yaw per
     OndrejTrhan; if the default order differs, the composition is wrong
     even though each individual angle is right.
  2. **Camera mount** - offered whenever YPR is included. We already bake
     the camera mount into the angles (adding `camera_offset`), so a
     non-identity default here would DOUBLE-APPLY the mount.
  3. **Near-singular Port geometry**: Port's pitch sits at ~88 deg, within
     2 deg of the 90 deg degeneracy where roll and yaw axes collapse in
     this parameterisation. Small pitch noise then produces large
     attitude swings - a plausible contributor to a component that holds
     mostly Port frames.
  SCOPE — **CORRECTED, see the scope-correction entry below.** I first
  wrote "harmless to every align so far (production aligns ran
  POSITION-ONLY)". That is FALSE: the production params point at the
  13-column format with `ifUseOriAcc=true`, so the 2026-07-24 fresh-run
  aligns DID import orientation at 3/5/3. Only PD-6's cell was
  position-only. Orientation is consumed by BOTH the fresh-run aligns and
  the assembly's `-update`.

- **REVERTED 2026-07-26 (owner: "change lever"). The entry below is
  SUPERSEDED; the code is back to Port (1.0 fwd, 0.0 lat, 1.0 down) and
  Cinema (1.0, 0.0, 0.0), the values two metrically-sound solves validated.
  H2024's nav, flight log and zones are being regenerated from raw under
  the restored geometry.** Original flag follows:
  **DISPUTED — THIS CHANGE RESTS ON RETRACTED EVIDENCE AND SHOULD PROBABLY
  BE REVERTED (flagged 2026-07-26 by a contradiction audit).** The entry
  below cites "|P-C| separation 0.22 m, vertical component 0.00 m, P ~0.17 m
  ahead" as corroboration. Those figures were **already retracted on
  2026-07-25**: they were measured inside hull c0, the **0.175-scale**
  component, so both the separation and its vertical part are meaningless
  (0.22 x 5.7 ~= 1.25 m, which is what the sound solves actually report).
  The RETRACTION entry above validated the ORIGINAL code on two
  INDEPENDENT metrically-sound solves - bow c2 and zone_2 from PD-2b -
  finding **C above P by +1.12 m and +1.03 m** against the code's implied
  +1.00 m, separation 1.21/1.11 m, and concluded "the code's 1.0 m stands,
  corroborated twice".
  So the owner's 2026-07-26 instruction ("roughly the same distance
  forward, the Z in my notes may be wrong") conflicts with the measured
  evidence, and I implemented it while quoting numbers the log had already
  thrown out. CONSEQUENCE: H2024's flight log and its re-batched zones are
  currently built with Port 1 m too HIGH and 0.17 m too far forward. H2023
  is unaffected (it was not re-georeferenced). AWAITING OWNER DECISION;
  if reverted, H2024 needs its flight log and zones regenerated again.
  [H2023] (2026-07-26)

- **Rig lever arms corrected: Port and Cinema are level, not 1 m apart in
  Z.** Owner (2026-07-26): both cameras are roughly the same distance
  forward of the USBL, and the Z figure in the notes was the doubtful
  one. This matches the solve-derived rig-internal geometry already
  recorded - |P-C| separation 0.22 m (IQR 0.21-0.28), vertical component
  **0.00 m** (IQR -0.09..+0.04), P about 0.17 m ahead of C. Applied in
  `_get_camera_offsets`: Port 1.0 m forward / 1.0 m DOWN -> **1.17 m
  forward / 0.0 m down**, Cinema unchanged at 1.0 / 0.0. Removes a
  ~10-sigma-per-Port-frame conflict at the 0.1 m Z accuracy that was in
  force when the error was found. Rig-internal quantities are observable
  regardless of how weakly absolute attitude is constrained, which is why
  this derivation is trusted where the mount-ANGLE derivation was not.
  [H2023] (2026-07-26)

- **CONTAMINATION FLAG: every prior conclusion about whether ORIENTATION
  PRIORS help or hurt was measured through an unverified import path, and
  none of them isolates what was actually being tested.** The orientation
  work above establishes that (a) imported YPR is read in NED with a
  CONFIGURABLE Euler order evaluated right-to-left, (b) a **Camera mount**
  option applies whenever YPR is included, and (c) our
  `FlightLogParams.xml` pins NEITHER - so every orientation cell ran on
  whatever the import defaults are, composing angles in a possibly
  different order than the intrinsic Roll -> Pitch -> Yaw our numbers
  assume, and possibly double-applying a camera mount we already baked in.
  Additionally Port's pitch sits at ~88 deg, within 2 deg of the
  parameterisation's 90 deg degeneracy.
  CELLS AFFECTED (registration counts stand as measurements; the
  ATTRIBUTION to "orientation priors" does not):
  - **PD-0** (13-col + tight YPR 3-5 deg) - already a bad cell for
    changing two variables; now doubly so.
  - **PD-0b** ("orientation at HONEST 15 deg", 109/124, +7 vs baseline,
    "dose-response proven: 5 deg fragments, 15 deg gains"). The ACCURACY
    dose-response may well survive, since weighting is independent of
    composition order, but "orientation helps" really means "these
    particular numbers, composed by an unknown default order, helped".
  - **PD-1b** (Division + orientation@15, 112/124, "gains not additive").
  - **PD-4** (Division + orientation@15 + 1/1/0.1, COLLAPSED to
    669/4540) - already confounded by the sidecar-stripping defect AND by
    memory contention; the unpinned import is a third confound. Its
    reading that "orientation-at-scale is the poison" is not supported.
  - **M-DIV-ORI** (smoke + orientation@15, 118/120).
  - **Interim v2-config policy** "orientation@15 deg is validated on
    SPARSE zones (zone_2 8x, zone_3 +7)" - downgrade from validated to
    PROVISIONAL.
  - **Mount-angle derivation from solved scenes** (zone_3 C~58 deg down vs
    a zone_1 strip C~-42 deg, both with tight IQRs) - already recorded as
    unreliable because position-only georeferencing leaves absolute
    attitude weakly constrained; any re-derivation must pin the import
    settings FIRST or it will inherit the same ambiguity.
  NOT affected: **PD-6 only** among the production aligns (its cell params
  point at a 7-column position-only format), plus all scale-oracle results
  and the rig-INTERNAL geometry (relative axis angle, relative camera
  separation) that the lever-arm correction rests on - those are observable
  regardless of absolute attitude.
  **AFFECTED, corrected 2026-07-26: the 2026-07-24 FRESH RUN.** An earlier
  version of this line claimed the fresh run was position-only. It was not -
  production `FlightLogParams.xml` selects the 13-column YPR format with
  `ifUseOriAcc=true`, so zone_1/2/3 imported orientation at 3/5/3 under the
  same unpinned Euler order. See the scope-correction entry below.
  REQUIRED BEFORE ANY FURTHER ORIENTATION CELL: pin Euler order and camera
  mount explicitly in `FlightLogParams.xml`, then re-run one cheap sparse
  cell (Z3) to see whether the PD-0b gain survives a pinned import.
  [H2023] (2026-07-26)

- **CORRECTION to the contamination-flag scope, and a THIRD candidate for
  the PD-6 scale fix.** I wrote that "production aligns ran POSITION-ONLY,
  so the unpinned orientation import was harmless". That is FALSE for the
  fresh run. The params files differ by format GUID:
  - production `FlightLogParams.xml` -> `{B438A617-...}` = the 13-column
    format whose parser maps **Yaw/Pitch/Roll at indices 7/8/9**, with
    `ifUseOriAcc=true`. So the 2026-07-24 fresh-run aligns (zone_1/2/3)
    DID import orientation, at the then-current **3/5/3** accuracies.
  - PD-6's cell `FlightLogParams_4Q.xml` -> `{0E9850E2-...}`, a 7-column
    position-only format. PD-6 genuinely had no orientation.
  CONSEQUENCE: PD-6 vs the fresh run differs in THREE ways, not two -
  (a) Brown3 -> Division, (b) accuracy columns actually imported, and
  (c) **orientation priors REMOVED**. Since the fresh run is exactly the
  run whose hull solved at scale **0.175** and PD-6 the one that solved at
  **0.982**, "removing tight, possibly mis-composed orientation priors" is
  a live candidate for the scale repair and was never listed. It is also
  mechanically plausible: orientation priors composed under the wrong
  Euler order fight the visual solution on every frame, and this geometry
  maps attitude error into focal/scale error.
  DOES NOT change the bow diagnosis: the bow the owner inspected comes
  from PD-6 (position-only), so its tilt cannot have been caused by
  align-time orientation priors - the assembly's `-update` remains the
  leading suspect. Discovered while pinning the import settings, by
  reading the two params files instead of assuming they matched. [H2023]
  (2026-07-26)

- **OWNER DECISION (2026-07-26): apply orientation priors at alignment
  regardless of the outstanding discriminator test, staying conservative
  on the claimed accuracy.** Rationale given: validated data should not be
  thrown away. Concern raised and overruled, recorded per the working
  agreement: the Euler order and Camera-mount import settings are still
  unpinned, and the correction above makes "tight orientation priors" a
  live candidate for the fresh run's scale collapse - so orientation ON
  with an unverified composition carries a real scale risk. MITIGATIONS in
  force: accuracies are already the conservative **15 deg** for yaw, pitch
  and roll (`_get_camera_pitch_accuracy` returns 15 for P/C, `yaw_acc` and
  `roll_acc` are 15) rather than the fresh run's 3/5/3, and every H2024
  component will be measured with `testing/scale_oracle.py` before it is
  used, so a repeat of the 0.175 failure is caught by evidence rather than
  by eye. [H2024] (2026-07-26)

- **Import settings `ifKGrp` and `ifKmode` cannot be pinned by
  inspection - they are the only plausible carriers of Euler order and
  Camera mount, and their value mapping is undocumented.** The Help
  documents the SETTINGS ("Euler angles order (YPR)", "Camera mount",
  both present whenever YPR is imported) but not their config keys;
  `flightlogs.xml` defines only column mapping; and neither key string
  appears in any file under the RealityScan install, so both are compiled
  into the binary. Current values, unchanged since the template was
  written: `ifKGrp=2`, `ifKmode=0x0`. Guessing a value here would silently
  change orientation handling - the exact failure class under
  investigation - so nothing was changed. TWO WAYS TO SETTLE IT: (1) set
  the two dropdowns in the GUI import dialog, save the params, and diff
  against this template (one minute, needs the GUI); (2) a CLI probe -
  align the smoke fixture with orientation at several `ifKmode` values and
  read the resulting camera attitudes out of the pose XMPs, which is
  fully headless and about 2 min per cell. [H2023] (2026-07-26)

- **NEAR MISS (fixed): five H2024 zones were silently a BLEND of two
  zonings, and were about to be aligned.** After the lever-arm correction
  changed every Port position, a re-batch reused the existing
  `batched_images_by_zone` folder: the batcher's unattended overwrite path
  reuses on the stated premise that "zone recomputation is deterministic
  for the same log+parameters", which was true and never verified. The
  flight log HAD changed, so zone membership changed, and `__copy_files`
  skips files already present but has no way to remove a member the new
  zoning dropped. Result: **12,679 jpgs on disk against 9,834 reported**
  (zone_2 1,537 -> 3,497, zone_5 2,623 -> 3,497), i.e. ~2,845 stale
  images, with the module reporting `Success: True`. Discovered by
  counting files per zone instead of trusting the summary. Fixed by
  making the premise mechanical: `batch_inputs.json` records the flight
  log's sha256 plus the six zoning parameters, and reuse is REFUSED with
  the remedy named when they differ. Contaminated folder removed and
  rebuilt clean - 9,834 jpgs, 1:1 sidecars, totals matching the report.
  LESSON: a reuse/resume path needs an input fingerprint, not a comment
  asserting the inputs are unchanged; and "Success: True" from a stage
  whose output is a directory means nothing without counting the
  directory. [H2024] (2026-07-26)

- **Hull model memory profile, now measurable.** The retry's resource
  trace (`logs/resources_GenerateModel_*.csv`) shows `-calculateHighModel`
  on 3,738 cameras driving the box to its limit: available RAM fell from
  79.4 GB to **3.1 GB within 3 minutes**, commit charge went 19.6 -> 105 GB
  and Windows grew the commit limit from 99.5 GB to ~120 GB to absorb it,
  after which the run oscillated at 87-105 GB committed with 7-32 GB free
  for the next half hour. RealityScan's working set peaked at 62.5 GB.
  Confirmed still doing real work rather than hanging: 9.1 cores busy and
  33% GPU measured over a 20 s window. The bow (656 cams) and torpedo (102)
  completed comfortably; the hull is 5.7x the bow.
  **These figures stand as a MEMORY PROFILE and NOT as the cause of any
  failure.** An earlier version of this entry read them as "memory
  exhaustion INTRINSIC to this component's mesh" and inferred that High
  detail plus `closeHoles` "does not fit in 93.6 GB without paging". The
  retry then failed on `ERROR_DISK_FULL`, not memory, so that inference is
  withdrawn - see the ROOT CAUSE entry below. What survives: the hull does
  page heavily at High detail, which makes it SLOW (step [1/8] alone ran
  far longer than the bow's entire recipe), and the pagefile is only
  6.9 GB. Whether the recipe needs a lever for the hull is therefore still
  open, but it is a THROUGHPUT question, not the explanation for the two
  crashes. [H2023] (2026-07-26)

- **ROOT CAUSE of the hull model failures: the DISK, not memory.** The
  retry ran 143.5 min, got past `closeHoles` (step [5/8], which the first
  attempt died at) and failed at **[6/8] texture generation** with
  `result code 2147942512` = **0x80070070 = ERROR_DISK_FULL**. `D:` had
  reached **0 bytes free**; the driver's own log-snapshot then failed with
  `[Errno 28] No space left on device`, which is what made it unmissable.
  The memory readings were real but incidental: RAM did fall to 3.1 GB, the
  pagefile is only 6.9 GB, and the process was verified doing genuine work
  (9.1 cores, 33% GPU) throughout. Both earlier explanations - concurrent
  load, then intrinsic memory exhaustion - are therefore SUPERSEDED as
  causes of these failures. `:fail` quits WITHOUT saving, so the assembly
  survived intact (parses, no zero-byte files, bow + torpedo models
  present).
  METHOD LESSON, and the sharpest one of the session: I built a resource
  trace hours earlier and instrumented CPU and memory *because memory was
  my hypothesis*. It faithfully recorded RAM falling to 3.1 GB and was
  silent about the disk that actually killed the run. A monitor built
  around one hypothesis will confirm or refute that hypothesis and tell you
  nothing else. Free disk on the project drive is now a trace column with a
  peak-minimum in the summary line. [H2023] (2026-07-26)

- **H2023 workspace physically relocated to `F:` behind a directory
  junction at the old `D:` path.** Owner-approved cleanup deleted
  `RC_projects` (57.1 GB), the superseded `merged` assembly (31.9 GB) and
  `orphan_pickup`/`orphan_pickup2` (17.6 GB), then the remaining 90.6 GB /
  39,235 files moved to `F:\na156_h2023_fresh` in 3.2 min, with
  `D:\na156_h2023_fresh` recreated as a JUNCTION to it. WHY the junction
  rather than a plain move: the saved `.rsproj` stores ABSOLUTE image paths
  that texturing needs, and hard rule 7 says a relocated `.rsalign` hangs
  the instance forever on import - a bare move would have broken both. With
  the junction every historical absolute path still resolves (verified for
  the .rsproj, a component .rsalign, a zone flight log and a real image)
  while the bytes live on F:. Result: **D: 0 -> 197.3 GB free, F: 773.9 GB
  free**. FOR FUTURE SESSIONS: `D:\na156_h2023_fresh` is NOT a real
  directory - if it is ever deleted or recreated, the junction must be
  restored (`New-Item -ItemType Junction -Path D:\na156_h2023_fresh -Target
  F:\na156_h2023_fresh`) or every recorded path in this log breaks.
  [H2023] (2026-07-26)

- **TRUE ROOT CAUSE of all three hull-model failures: RealityScan's CACHE
  DISK, not the project disk.** The instance log - snapshotted for the
  first time thanks to the per-model snapshot added earlier - says it
  outright: `Processing failed: Out of disk space..` during
  `simplify` (step [6/8], after `closeHoles` 125 s and `cleanModel` 230 s
  had both SUCCEEDED). The cache lives at **`D:\rccache`, 1,089 GB**, and
  it refilled the 197 GB freed by the owner-approved cleanup within one
  run. Moving the PROJECT to F: did nothing, because the cache does not
  move with it. Epic's own "Out of Disk Space" page confirms the
  mechanism - "processing cannot continue without freeing up some space on
  it", the process is aborted and "the progress will be lost" - and warns
  **"don't delete the files from your cache folder since this may lead to
  some failures in the project"**, so hand-clearing `rccache` is NOT a
  legitimate remedy. Their sanctioned levers are freeing space on the cache
  disk or changing the cache disk.
  SETTINGS (from `tutorials/setkeyvaluetable.htm`): `appCacheLocation` =
  `SystemTemp` | `Custom`; `appCacheCustomLocation` = path (used when
  Custom); `appAutoClearCache` = retention in days, where 999999 = never
  clear, 0 = clear all, and 3/7/14/30/90 select an age cutoff. `-clearCache`
  is also a CLI command, and requires the project be saved first.
  APPLIED: `startRealityScan.bat` now honours an opt-in `RS_CACHE_DIR` -
  when set it boots with `appCacheLocation=Custom` +
  `appCacheCustomLocation`, and unset keeps RealityScan's default, so
  nothing changes silently. `appAutoClearCache` deliberately untouched:
  retention is owner policy.
  INSTRUMENTATION LESSON, the third variation of the same mistake: after
  the disk-full diagnosis I added a `disk_free_gb` column - and pointed it
  at the drive holding the trace, i.e. the PROJECT drive. It faithfully
  reported 773.9 GB free for the whole run while the CACHE drive went to
  zero. Watching the right RESOURCE is not enough; it has to be the right
  INSTANCE of that resource. [H2023] (2026-07-26)

- **ROVDataConcat is DETERMINISTIC end to end — verified, not assumed.** A
  full forced re-run for H2024 (stage 1 raw extraction over the whole
  expedition, then stage 2 kalman) reproduced **all nine output CSVs
  byte-identically** (sha256 over USBL Atalanta/Hercules, dvl_lat_long,
  octans, sealog_sensors_merged, filtered_datatable, kalman_filtered_data,
  final_datatable, kalman_assessment). Confirmed the work actually re-ran:
  every stage-1 step reported `done` rather than `skipped (resume)`. Worth
  having as a fact rather than a belief, because several "deterministic for
  the same inputs" assumptions failed elsewhere this session (the batcher's
  zone-reuse premise most notably). Also re-confirms that the camera lever
  arm lives entirely in THIS repo's georeference module - it has no effect
  on nav, so a lever-arm change never requires re-running ROVDataConcat.
  [H2024] (2026-07-26)

- **DEFECT (fixed): `main.py` exited 0 when a module REFUSED to run.** On
  `validate_parameters()` returning False the orchestrator logged the error
  and did a bare `return`, which exits 0 - while the module-FAILURE branch a
  few lines below has always used `sys.exit(1)`. So a refused run was
  indistinguishable from a successful one to any caller gating on exit
  status. Discovered because the batcher's new fingerprint guard correctly
  refused to reuse zones built from a different flight log, and the process
  still reported success. Fixed to `sys.exit(1)` and verified by re-running
  the same refusal: now exit 1. NOTE this is the second silent-failure exit
  code found this session, after ROVDataConcat's `main_kalman.py` returning
  0 with a FAILED module - worth checking any other orchestrator here for
  the same shape. [H2024] (2026-07-26)

- **The batcher's input fingerprint WORKS IN ANGER.** After the lever-arm
  revert changed every Port position, the re-batch was refused with
  `Existing batched zones were built from DIFFERENT inputs (changed:
  flight_log_sha256). Reusing them would mix two zonings...`. This is the
  exact near-miss it was written for hours earlier (12,679 images on disk
  against 9,834 reported), now caught mechanically instead of by manually
  counting files. [H2024] (2026-07-26)

- **H2023 HULL MODEL COMPLETE.** Attempt 4 succeeded: `success=True` in
  384.1 min, all eight recipe steps, no errors, project saved plus dated
  copy. The only variable changed from the three failures was the cache
  drive (`RS_CACHE_DIR=E:\rscache`), which closes the loop on the
  disk-not-memory diagnosis. Resource peaks are worth recording because
  they are extreme: **CPU 100%, commit used 142.3 GB, minimum available
  RAM 0.3 GB**, minimum free project disk 672.6 GB, minimum free CACHE
  disk 6,900.5 GB. So the hull DOES run the box to the edge of memory - it
  simply never failed there. All three H2023 components (hull 3,738 / bow
  656 / torpedo 102) now carry models. [H2023] (2026-07-26)

- **CRITICAL: the metric-scale failure REPRODUCED on H2024 zone_3 - 1,192
  cameras at scale 0.236 - on the first production run with ORIENTATION
  PRIORS ENABLED.** Full sweep (`testing/scale_oracle.py`, all 16
  components): zone_1 eight components 0.937-1.119; zone_2 1.086;
  **zone_3 c0 = 0.236 (IQR 0.217-0.253)**; zone_4 five components
  0.983-1.196; zone_5 1.023. Registration looked entirely healthy
  throughout - 8,709 cameras, 82-93% per zone, `Success: True` on every
  zone - which is exactly the blindness the oracle was built for: a
  camera-counting gate passes this dataset.
  This is the SAME failure mode as the fresh-run H2023 hull (0.175) and it
  is the risk that was explicitly raised and overruled when orientation
  priors were switched on ("apply the orientations regardless of test...
  we should not throw away validated data"), with the scale oracle named
  as the mitigation. The mitigation worked on its first outing.
  ATTRIBUTION NOT YET ESTABLISHED - and must not be assumed. This run
  differs from the sound PD-6 run in more than one way: different dataset,
  orientation priors ON at 15 deg, and the unpinned Euler order / camera
  mount. The narrow IQR (0.217-0.253) says it is a clean SIMILARITY error,
  i.e. a whole-component scale collapse rather than drift or a fold -
  consistent with a focal/attitude conflict rather than a bad solve.
  DISCRIMINATOR (cheap, decisive, ~20 min for 1,279 images): re-align
  zone_3 alone with a POSITION-ONLY flight log and the 7-column format
  GUID, exactly as PD-6 was configured, and re-measure. If scale returns to
  ~1.0 then orientation priors under an unpinned Euler order are the cause
  and the priors must come back out until the convention is verified.
  NOTE zone_4 c2 (1.196) and c4 (1.100) also sit outside a +/-10% band, so
  zone_3 may be the extreme of a spectrum rather than an isolated fault.
  [H2024] (2026-07-26)
