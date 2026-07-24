# Alignment & merge hardening test plan — 2026-07-23

STATUS UPDATE (2026-07-23, 9-boot probe session; details in FINDINGS.md):
U1/U19/U2 RESOLVED (selectImage = literal paths only; editInputSelection
works; align honors enable/disable). U15/U16 PASS (scene byte-stable;
rename->export naming). U18 FAIL (inpPose=3 = Exact prior; incremental
align rejects - rollback stays primary). U20 PARTIAL (ordinal-export rule
confirmed and REFINED: stems require the live aligning session; identity
capture must move in-session; exhaustion wrap must accept 0x80070057).
Open: U4-U14, U17, plus new follow-ups: selectImage regexp discrepancy
vs Help (forum-mine), in-session identity loop rebuild.

Purpose: every assumption in the automated align/merge/growth design
that is NOT settled by documentation gets a test cell here. A cell
graduates into FINDINGS.md (with its result) once run. Cells are
prioritized by what they gate: P0 gates the growth driver working at
all; P1 gates quality/robustness; P2 is optimization.

Fixtures: `smoke` = the two 120-image mini-zones + saved scenes under
D:\na156_h2023\smoke_test (cheap, minutes); `z2` = zone_2 (976 images,
3 components, realistic); `z1` = zone_1 (4,540 images, expensive - only
for final validation). All cells snapshot %LOCALAPPDATA%\Temp\
RealityScan.log per RealityScan boot (it truncates per boot).

## P0 — selection & enable mechanics (gate the growth loop)

- **U1 selectImage forms & scale.** Docs give `selectImage
  imagePath|regexp` with set/union/sub/intersect/toggle but not: full
  path vs basename matching, regexp dialect, or cost of composing
  thousands of unions. TEST (smoke scene): select by (a) full path,
  (b) basename, (c) regexp `P231C.*`, each verified by -enableAlignment
  false + a probe export or GUI count; then time a 1,000-term union
  composition vs one regexp alternation. GATES: GrowZone.bat selection
  composition strategy.
- **U2 enable/disable actually constrains align.** Assumption: with all
  images disabled except a target set, -align touches only the enabled
  set and does NOT disturb components containing disabled images. TEST
  (z2 scene copy): disable all, enable one component + 20 orphans,
  align; manifest-diff all components before/after - only the target
  may change. GATES: the entire per-component growth loop; if false,
  isolation must come from export/reimport into scratch scenes instead.
- **U3 featureSource persistence & scope.** Set featureSource 1 on a
  selection, save, reload: does it persist? Does it apply per-image (as
  the Selected input(s) panel implies)? TEST: set, save, reload, align,
  compare runtime/behavior vs default. GATES: whether featureSource
  must be re-set every pass.
- **U4 component deletion frees images.** Assumption: deleting a stale
  component returns its images to "not in any component" and a later
  align may re-register them. TEST (smoke): delete the smaller
  component, align, check whether its images reappear in a component.
  GATES: stale-cleanup ordering.
- **U5 selectMaximalComponent ignores names.** Assumption: it picks by
  size regardless of prior renames (identity loop relies on
  rename+delete to iterate). TEST (z2 scene copy): rename largest, call
  selectMaximalComponent, verify it reselects the renamed one.
  GATES: ExportComponentIdentity loop.
- **U15 quit-without-save preserves on-disk scene.** The identity loop
  deletes components in a loaded scene and quits WITHOUT saving;
  assumption: the .rsproj on disk is untouched. TEST (smoke): checksum
  rsproj + companion folder before/after a load-delete-quit cycle.
  GATES: identity capture safety. NOTE: autosave must be off
  (appAutoSaveMode=false is already set at boot - verify no autosave
  files appear).
- **U16 export takes the renamed component name.** Assumption:
  rename then exportSelectedComponentDir writes <newname>.rsalign.
  Observed once (Merged.rsalign) but verify with a fresh rename in the
  same session. GATES: manifest <-> rsalign pairing.

- **U18 pose-locking as the never-shrink anchor.** -editInputSelection
  inpPose=3 (Locked) on a component's cameras before a growth align:
  does align (a) preserve every locked camera in the component,
  (b) refuse to move them, (c) still register new images onto the
  locked skeleton? If yes, this REPLACES rollback as the primary
  never-shrink mechanism (rollback stays as belt-and-braces). TEST
  (smoke): lock mini_a's component, enable orphans, align; verify
  locked poses unchanged (XMP export before/after) and no camera loss.
  GATES: growth-loop core design - run EARLY.
- **U19 editInputSelection vs dedicated commands.** enableAlignment /
  setFeatureSource exist as dedicated commands AND as editInputSelection
  keys (inpEnabled / aligFeaturesMode). Same effect? Selection scope
  identical? TEST alongside U1. GATES: which API the workflows use
  (prefer editInputSelection - one command family, more capabilities).

- **U20 identity-capture loop, live end-to-end.** Covers the manifest
  agent's open risks on smoke: (a) stem-named (non-ordinal) sidecars
  when exporting from a LOADED original scene (B10 refinement);
  (b) rename->exportSelectedComponentDir produces <name>.rsalign;
  (c) selectMaximalComponent on an emptied scene reports through the
  errors marker (exhaustion terminal); (d) quit-without-save leaves the
  .rsproj byte-identical (overlaps U15). Run BEFORE the first
  production manifest capture.

## P1 — merge & georeferencing (gate quality)

- **U7 georeferenced-merged verification, CLI-observable.** Owner's GUI
  check is ground truth but automation needs a proxy. CANDIDATES:
  (a) -exportReport with a components params xml (does it emit georef
  status/residuals headless? HANDOFF warns exportRegistration without
  params blocks forever - test with GUI-exported params only);
  (b) poses2flightlog.py fit residuals local-vs-UTM (a georeferenced
  component should fit with near-identity transform);
  (c) exported flight log round-trip. TEST on the merged_georef2
  partial outputs + a fresh small merge. GATES: automated
  merge-acceptance check.
- **U8 flag interaction with shared cameras.** With duplicated overlap
  images present AND sfmMergeGeoreferencedComponents=true, which
  mechanism does -mergeComponents use (identity? georef? both), and
  does the placement differ from flag-off? TEST (smoke twins):
  merge with flag off vs on; compare merged camera positions vs nav.
  GATES: whether cross-zone rigid merge needs the flag when overlap
  bands exist.
- **U9 exportLatestComponents after -mergeComponents.** Assumed to
  fail/export nothing ("last alignment" wording). TEST (smoke): run
  merge mode then exportLatestComponents; observe. GATES: whether
  merge-mode outputs can include leftovers without an align pass.
- **U11 does a merge-scene align re-detect features for imported
  components?** Staff say features are cached for re-align in the
  ORIGINAL scene; imported components carry "component features" - but
  does -align in the merge scene re-detect from image files (slow, and
  requires image paths valid) or reuse? TEST: time align in merge scene
  with featureSource 1 vs 2 on smoke twins; watch RealityScan.log for
  feature-detection lines. GATES: cross-zone align cost model, and
  whether image files must be accessible from the merge scene.
- **U12 twin removal improves the merge.** A/B on H2023: merge all 5
  components vs merge with the weak twin dropped; compare max/mean
  residuals (via U7's proxy) and mesh artifacts in the overlap strip.
  GATES: automatic twin-drop policy (currently justified by reasoning,
  not measurement).
- **U13 xcr:Position frame in an original georeferenced zone scene.**
  B10 says grid-anchored local frame (NA167 evidence). Re-verify on
  zone_2: export XMP in the original scene, compare positions to the
  flight log UTM. If they ARE UTM here, manifests can carry true
  per-camera positions (better bboxes than flight-log lookup).
  GATES: manifest bbox source; possible B10 refinement.
- **U14 per-component reprojection error, headless.** Needed for twin
  keeper choice. CANDIDATE: -exportReport with a components report
  params file exported once from the GUI. TEST carefully (blocking
  risk): delegate with a watchdog; if it blocks, mark GUI-only and use
  camera_count-only keeper choice. GATES: quality field in manifests.

## P2 — robustness & cost

- **U6 component naming/creation after align.** Are new components
  always named "Component N" with unstable N (observed: Component 5, 9,
  0, 3, 4 across two zones)? Does align UPDATE an existing component in
  place (keeping its name) when it only grows? TEST: observe names
  across grow passes on smoke. INFORMS: how much renaming discipline
  the manifests need.
- **U10 tolerance breadth of 0x820000FF.** Our importFlightLog
  tolerance accepts ANY warning-class result. Enumerate other
  warning-class importFlightLog failures (wrong CRS? malformed rows?) by
  deliberately feeding a wrong-zone params file and a corrupt log on
  smoke; check they also report 0x820000FF (if so, add RealityScan.log
  text verification to the tolerant path, not just the numeric code).
  GATES: false-tolerance risk.
- **U17 rollback fidelity via rsproj file copy.** Checkpoint = copying
  .rsproj + companion folder; restore = copy back. TEST: checkpoint,
  run a destructive pass, restore, verify scene equivalence (component
  census + align behavior). Also verify what the companion folder is
  named and whether absolute paths inside break on copy-back to the
  SAME location (should be fine; relocation is NOT supported - B1).
  GATES: the never-shrink invariant's enforcement mechanism.

## Forum mining track (standing, owner directive 2026-07-23)

The official Epic forums (forums.unrealengine.com, Photogrammetry /
Asset Creation categories; legacy support.capturingreality.com threads
redirect there) hold undocumented behavior in EPIC STAFF replies. Rules:

- For every open U-cell, run a targeted forum search BEFORE burning
  RealityScan hours on it - a staff reply may settle it outright.
- **Only posts from the last 4 years (2022-07 or newer).** The older the
  post, the more suspicion: verify anything pre-dating the current
  major version against the local 2.2 Help and, where cheap, a live
  probe. Pre-rename posts (RealityCapture era; the RealityScan rename
  shipped with the 2.x line) get the MOST suspicion - commands, key
  names (RealityCapture* -> app*), defaults, and even tool behavior
  changed across the rename.
- Staff replies outrank user lore; user consensus with reproduction
  steps outranks single anecdotes.
- Every adopted gem goes to FINDINGS.md with URL, author + staff/user
  status, post date, and verification status
  (verified-live | corroborated-by-help | UNVERIFIED-dated).
- Search patterns that worked: site:forums.unrealengine.com + exact
  command/setting name in quotes; staff usernames seen so far:
  OndrejTrhan.

AUDIT FLAG on existing citation: the merge-vs-align staff answer
(t/712116) is from 2021-09 - OUTSIDE the 4-year window and pre-rename.
Its "no new images added" claim is corroborated by current 2.2 Help
wording (mergecomponents.htm), so the rigid-merge fact stands at
corroborated-by-help; the recommendation nuances (align-over-merge
performance claims) need a fresher source or live measurement (U-cells
U8/U11 cover this).

## Self-audit (challenges to our own recent work - standing items)

1. The 2181038335 tolerance currently trusts a numeric code alone
   (U10). The RealityScan.log snapshot at failure time should be
   grepped for "18002" as a second factor before continuing.
2. expected_18002_*.txt / expected_select_*.txt marker archives
   accumulate in RS_CLI/Errors and are never cleaned - add rotation or
   per-run relocation into the run's log dir.
3. merged_georef2 on disk is a partial run (attempt 2 killed mid-flight)
   - clean before any fresh merge, and never point a census at it.
4. GenerateModel.bat's large-triangle threshold (Rel 30 = 30x average
   edge length) is NOT the GUI's pixel-based intuition - visual check
   required on first real model (flagged in evaluation doc).
5. The simplify "noise"/"smooth" params are placeholder percentages
   (70/80 rel) pending owner GUI presets.
6. process_h2023.py chain script predates project_label and the new
   merge/growth pipeline - retire it; drive future runs through the new
   drivers.
7. (Checked and CLEARED 2026-07-23: the processing chain wrote all
   5,516 calibration sidecars BEFORE the zone aligns, and addFolder
   auto-imports sidecars - the 96.7%/94.3% registrations did benefit
   from calibration groups. Kept here as an example of the audit
   catching its own false alarm.)
