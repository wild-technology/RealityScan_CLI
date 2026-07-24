# FINDINGS — running log

One entry per finding: what we know, and how it was discovered. Append
new findings at the bottom of the relevant section with a date. This is
the quick-reference companion to the deep docs
(docs/settings-evaluation-2026-07.md, docs/merge-growth-strategy-2026-07.md,
testing/NA167_SESSION_NOTES.md B1-B11).

## RealityScan 2.2 CLI behavior

- **addFolder does NOT recurse by default in this build** — zone_1/zone_2
  aligns added "0 layer images" and every flight-log row then failed
  err:18002. Discovered: live H2023 run failed in 25 s; RealityScan.log
  snapshot showed `Added 0 layer images`. Fix: `appIncSubdirs=true`
  before every addFolder. (2026-07-23)
- **-align on instance defaults is a real hazard** — AlignImagesFromFolder
  never applied AlignmentParams.xml; only AlignZonesSequentially did.
  Discovered: code reading during settings evaluation. Fix: every
  workflow applies the sfm*/lis* keys; policy "never align on instance
  defaults". (2026-07-23)
- **exportLatestComponents exports ALL components of the last alignment**
  (gated by setMinComponentSize) — the old maximal-only export was
  unnecessary loss. Discovered: allcommands.htm sweep. (2026-07-23)
- **-setFeatureSource 0|1|2 and -selectImage <regexp> ARE CLI** — the
  merge feature-source trio was wrongly believed GUI-only. Discovered:
  allcommands.htm "Commands for Selected Images" section. (2026-07-23)
- **XMP export from an imported-component scene writes ORDINAL sidecars**
  (00000.xmp...) instead of <stem>.xmp — census by count only; identity
  needs the original aligned scene. Discovered: smoke merge census
  classified all 180 sidecars "unknown camera"; instrumented sanitize
  printed the filenames. (B10, 2026-07-23)
- **Flight-log import leaves the matched images ACTIVELY SELECTED**, and
  selection-driven exports under -silent then export nothing
  ("Export Selection" dialog auto-answered; XMP export completed in
  0.057 s vs 20.5 s). Discovered: merged census dropped to 0 after
  adding the union-log import; RealityScan.log snapshot showed the
  dialog; components.htm documents exports as selection-driven. Fix:
  -deselectAllImages before exports. (2026-07-23)
- **A merged component is NOT georeferenced unless the merge scene holds
  constraints** — imported components' own georeferencing does not carry
  into the new component. Fix: union flight log + CRS params into the
  merge scene, then `-update` ("rigid transformation to fit the actual
  constraints"). Discovered: owner GUI inspection ("showstopper");
  mechanism from allcommands.htm -update + live re-run. (2026-07-23)
- **The errors marker carries only ErrorWriter's numeric result code**,
  never the err:NNNN text (that is only in %LOCALAPPDATA%\Temp\
  RealityScan.log, truncated each boot). Tolerant handlers must match
  codes (2181038335 = 0x820000FF warning-class). Discovered: first
  tolerant-import attempt matched "18002" and failed. (2026-07-23)
- **Check Integrity / Check Topology have no CLI commands** — their fix
  action maps to -cleanModel + -closeHoles. Discovered: zero hits in
  allcommands.htm. (2026-07-23)
- **-removeSelectedTriangles removes the SELECTED set** (= Filter
  Selection tool); -selectLargeTrianglesRel threshold is multiples of
  average edge length, not pixels. Discovered: allcommands.htm.
  (2026-07-23)

- **-editInputSelection is the master per-image CLI control** (local
  Help tutorials/editselectioncommand.htm): on the current image
  selection it sets enable-alignment (inpEnabled), features source
  (aligFeaturesMode 0|1|2), enable meshing/texturing, texture weight,
  masking mode, AND per-image PRIOR POSE (inpPose: 0 Unknown, 1
  Position, 2 Position+orientation, 3 **Locked**; inpTx/Ty/Tz,
  inpRx/Ry/Rz, per-image accuracies, locked-pose groups) AND full
  calibration/lens priors (inpCalibrationGroup, inpCalibration
  Unknown/Approximate/**Fixed**, inpFocal, principal point,
  inpDistortionModel 0-5, radial/tangential coefficients).
  Consequences: (a) pose-LOCKING well-solved components before growth
  aligns is a solver-level never-shrink anchor (test cell U18);
  (b) calibration/distortion priors can be set or FIXED per camera
  without XMP sidecars, including post-solve refinement model switches;
  (c) two command paths exist for enable/featureSource (dedicated
  enableAlignment/setFeatureSource vs editInputSelection key=value) -
  equivalence untested (cell U19). Discovered: forum-mining track led
  to "CLI Settings for Selections" help page, read from local 2.2 Help.
  (2026-07-23)

## Merge & component growth (research + empirical)

- **Merge Components is rigid best-fit**: no re-optimization, no camera
  repositioning, no new images; cannot shrink, cannot fix distortion,
  cannot register orphans. Discovered: Epic staff answer
  (forums.unrealengine.com/t/712116, OndrejTrhan, 2021-09 - NOTE:
  outside the 4-year trust window and pre-rename; "no new images"
  corroborated by current 2.2 Help, performance/recommendation nuances
  status UNVERIFIED-dated, covered by hardening cells U8/U11).
  (2026-07-23)
- **Align is the actual merge/growth engine**: re-runs use "special
  algorithms designed for merging components", are cheap (cached
  features), and "try a different strategy" on repetition; after
  georeferencing, align hunts additional cross-component tie points.
  Discovered: mergecomponents*.htm tutorials + staff answer. (2026-07-23)
- **Align can SHRINK components** (re-optimization drops marginal
  cameras) — "grow, never shrink" must be enforced by checkpoint/
  rollback, not assumed. Discovered: H2023 align_rematch attempt
  registered 3,855 vs merge's 3,860. (2026-07-23)
- **featureSource is consumed by ALIGN, not Merge Components**: 0 =
  merge using overlaps (only images COMMON to components — the
  duplicated zone-overlap bands), 1 = component features (existing tie
  points only), 2 = all image features (slow, small counts).
  Discovered: components.htm "Features source" prose ties it to "a new
  alignment of components". (2026-07-23)
- **Twin components across zones**: the 20% batcher overlap duplicates
  images into both zones; the same strip solved independently in each
  zone can fragment into near-identical twin components whose residual
  quality differs with solve context (big-network twin stiff, small-
  network twin distorted). Post--update residuals expose the weak twin
  (rigid fit cannot absorb internal warp). A twin with no unique images
  is discardable by the "never discard unique images" rule. Discovered:
  owner GUI inspection of H2023 components 3/5 + network reasoning;
  detection automation in progress. (2026-07-23)
- **Georef-only rigid fusion** (sfmMergeGeoreferencedComponents +
  merge/-update) places components purely by nav (~1-2 m real accuracy)
  — bakes nav error into seams, can double surfaces; last resort after
  visual merging is exhausted. Discovered: Help + kalman accuracy
  analysis. (2026-07-23)
- **Official fix-and-reimport round trip**: export faulty part as
  component -> fix in spare scene -> reimport -> align "applies fixes".
  Components tolerate duplicate images by design. Discovered:
  components.htm. (2026-07-23)
- **Component reimport does NOT carry non-member images**: a fresh
  project built from imported components contains ONLY the components'
  registered cameras - orphan images are absent, and if added manually
  they carry no trajectory data until the flight log is imported (or
  XMP priors are present). Consequences: (a) cross-scene orphan-pickup
  passes must explicitly -add the orphan images AND import the union
  flight log; (b) checkpoint/rollback must use .rsproj file copies, not
  component reimport, or orphans are silently lost. Discovered: owner
  experience (2026-07-23). (2026-07-23)
- **Empirical H2023 numbers**: zone_1 96.7% (4,391/4,540, 2 comps),
  zone_2 94.3% (920/976, 3 comps); georef -mergeComponents fused 5
  components to a 3,860-camera maximal (83.9% of unique) in 31 min;
  align+rematch and +High overlap did not beat it (3,855). Registration
  ceiling is unregistrable imagery, not merge mechanics. (2026-07-23)

- **Twin/discard automation exists**: modules/component_analysis.py
  implements the containment scan (find_twins), keeper choice, border
  gating, orphan tracking, and merge planning. The discard invariant is
  stronger than pairwise containment: coverage is checked against the
  UNION of still-kept group members, worst-first, so no image basename
  can ever leave the kept set even in mutual/triplet twin cases.
  Discovered: built + 31-test pytest suite (verified passing by main
  session). (2026-07-23)

- **B10 FINAL FORM - the XMP export COMMAND determines sidecar naming,
  not the session or scene origin**: `-exportXMP` (all components of
  the last alignment) writes STEM-named sidecars; 
  `-exportXMPForSelectedComponent` writes ORDINAL sidecars (00000.xmp,
  ...) in every observed context (live align session, loaded scene,
  merge scene). Four consistent datapoints: zone censuses (exportXMP,
  stems), U-SEL5 (exportXMP after in-session align, stems), smoke-merge
  + U20 + in-session identity first attempt
  (exportXMPForSelectedComponent, ordinal each time). An earlier
  session-based hypothesis was WRONG and is superseded by this entry.
  Consequence: per-component membership cannot come from the selected-
  component export at all - AlignZone.bat's identity loop instead
  harvests `-exportXMP` stems each lap and derives membership by
  SUCCESSIVE DIFFERENCE as components are deleted (members(cK) =
  stems(rK) - stems(rK+1)). Also observed: selectMaximalComponent /
  renameSelectedComponent / deleteSelectedComponent all silently no-op
  on an empty scene (no errors marker) - loop terminals must be
  file-existence checks, not error checks. Discovered: hardening cells
  + in-session loop first run, 2026-07-23.
- **U15/U16 PASS**: quit-without-save leaves the .rsproj bundle
  byte-stable across load/delete/export cycles (hash-verified twice);
  rename -> exportSelectedComponentDir writes <newname>.rsalign.
  Exhaustion terminal works functionally but the tolerant wrap must
  also accept 0x80070057 E_INVALIDARG (observed from the emptied-scene
  select path). (2026-07-23)
- **U18 FAIL - pose-locking is unusable as a growth anchor**:
  editInputSelection inpPose=3 executes and takes effect, but -align
  then refuses: "Image rigs and laser scans with the prior set to
  'Exact' mode must be all aligned in a single run. Incremental adding
  is not supported." Locked = Exact-mode prior; incremental aligns
  reject them. Checkpoint/rollback stays the primary never-shrink
  mechanism. Bonus contrast: a free re-align moved ALL 118 cameras and
  can drop 1-2 marginal ones - align output is never pose-stable.
  Discovered: U18 probes + RealityScan.log snapshot. (2026-07-23)
- **U1/U19/U2 RESOLVED - selectImage matches LITERAL FULL PATHS ONLY**
  in this build: bare regexp (C231C05.*), dot-star-wrapped
  (.*P231C.*), glob (P231C*), and regexp with explicit 'set' modifier
  ALL silently select nothing (no error, empty selection); a literal
  full path selects exactly its image. editInputSelection
  "inpEnabled=false/true" works (key=value single quoted arg), and
  -align honors enable/disable exactly (single disabled image absent
  from an otherwise full registration). Selection composition for image
  sets = per-image literal selectImage union loop (the growth driver's
  implemented approach; ~0.1-0.3 s per image - budget minutes for
  thousand-image sets). The Help's "imagePath|regexp" wording does not
  match observed 2.2 behavior - candidate for a forum-mining follow-up.
  Discovered: bisection probes U-SEL2 through U-SEL8. (2026-07-23)

- **In-session successive-difference identity capture VALIDATED end to
  end** (smoke mini_a): AlignZone.bat align -> saves -> destructive
  harvest loop -> quit-no-save produced mini_a_c0.rsalign + manifest
  (118 members by real basename, UTM bbox from flight log), census
  from manifests == original registration, calibration sidecars
  restored, zero pose sidecars left beside images. The hardened
  zone-align + manifest pipeline is production-ready. (2026-07-23)

- **Near-OOM, RealityScan slows to a crawl WITHOUT crashing and WITHOUT
  spilling to the NVMe** (no ram-disk/pagefile overflow observed) - in
  the progress feed this is indistinguishable from a hung operation or
  a quiet compute phase, making memory pressure the THIRD cause of a
  persistent #timeout. Mitigation: RealityScanCLI now samples available
  RAM (GlobalMemoryStatusEx, no subprocess), warns once per workflow
  below 4 GB free, and includes the RAM figure in every stall warning
  so stalls can be attributed. Processing box: 93.6 GB RAM. Discovered:
  owner operational experience (2026-07-24). MEASUREMENT CAVEAT (owner
  caught this): workflows run MULTIPLE RealityScan.exe processes - the
  persistent instance plus transient delegator/wait calls - and a naive
  single-process memory read can catch a 30 MB transient instead of the
  instance (a "2.2 GB during a 4,540-image align" misread happened
  exactly this way; the instance was actually ~11 GB with 4 GB VRAM in
  use). Rule: identify the instance as the RealityScan.exe with the
  largest working set (or track its PID from boot) before quoting
  memory numbers. System-available-RAM telemetry (what the crawl
  warning uses) is unaffected. (2026-07-24)

- **Alignment fragmentation is strongly nondeterministic; total
  registration is not**: zone_1 (4,540 images, identical settings,
  sidecars, and inputs) aligned to 2 components/4,391 cameras in one
  run and 9 components/4,392 cameras in another. Component structure
  cannot be relied upon across runs - only the manifest-tracked image
  sets can - and within-zone growth/merge is MANDATORY machinery, not
  an edge case. Manifests show several fragments spatially nested
  inside the maximal component's bbox (within-zone twin/fragment
  candidates). Discovered: H2023 production re-align vs first run
  comparison, 2026-07-24. (2026-07-24)

- **Growth passes are align-UPDATES that refresh EVERY component** - the
  census after an "isolated" component pass covers the whole zone, so
  per-component before/after accounting produced phantom gains ("sweep
  gain 1856" on a 976-image zone) and an inflating manifest fallback.
  Fixed: zone-level baseline census drives the invariant, the gain, and
  orphan derivation; the fallback keeps pre-pass membership (untrusted-
  flagged) instead of assigning the union. Discovered: first live
  grow_zone runs on zone_2, 2026-07-24. (2026-07-24)
- **Checkpoint/rollback validated in anger**: a growth run killed
  mid-pass was fully recovered by copying the "initial" .rsproj bundle
  checkpoint back over the scene - the owner-mandated file-copy design
  did exactly what it exists for. (2026-07-24)
- **Unattended prompts must catch EOFError, not trust isatty()**: hidden
  consoles report isatty()=True with an EOF stdin, so input() crashes
  backgrounded runs; both drivers now fall back to stored defaults on
  EOF. (2026-07-24)
- **Zone_2 growth ground truth**: 928/976 (95.1%) with ZERO real gains -
  the 48 orphans are genuinely unregistrable; honest convergence after
  one sweep. Three components remain by design (northern strip has no
  visual ties; georef-fusion is reserved for the cross-zone stage).
  (2026-07-24)

## Rig & data

- **Four physical cameras** (owner-confirmed): Zeuss rect 23 mm; Port
  (aka cammid) fisheye 14 mm; Cinema (aka camlower) rect 17 mm;
  Starboard (aka camupper) fisheye 14 mm. NA156 mounts: Port 0 deg,
  1 m fwd + 1 m down; Cinema 45 deg down, 1 m fwd. S231C*.mov videos on
  D:\H2023 ARE Starboard (excluded for photogrammetry). (2026-07-23)
- **WCA rendered JPGs are EXIF-identical across cameras** (Z CAM E2-F6,
  no focal tag) — only per-image XMP CalibrationGroup separates them.
  Old batcher values (camlower "12 mm fisheye") were wrong and may
  explain NA167's "priors hurt" A/B. Discovered: PIL EXIF dump +
  owner camera table. (2026-07-23)
- **ROVDataConcat**: georeferencers require stage-2 kalman columns
  (final_datatable.csv); H2023 nav covers 2023-11-03T19:44 to
  2023-11-04T05:48; H2023 has no geotiff (kalman_offset fails,
  harmless for photogrammetry). (2026-07-23)

- **Component manifest system exists** (modules/component_manifest.py +
  ExportComponentIdentity.bat + realityscan_interface hooks): identity
  captured per component from the ORIGINAL zone scene, one boot per
  component, skip-k-largest + rename + export + quit-WITHOUT-save;
  membership = pose-sidecar delta between invocations; bbox from zone
  flight log. Live validation pending (hardening cell U20). Built by
  team agent; compile + arg-validation verified by main session.
  (2026-07-23)
- **-deleteSelectedComponent, -deleteComponent <idx>, and
  -deleteAllComponents all exist** in this build. Discovered:
  allcommands.htm sweep during model-recipe research; resolves the
  manifest agent's top open risk. (2026-07-23)
- **Git Bash mangles cmd switches**: `cmd /c foo.bat` under MSYS
  converts /c to C:\ and launches an INTERACTIVE cmd that exits 0
  silently - .bat invocations from Bash need `cmd //c` or PowerShell.
  Discovered: ExportComponentIdentity arg-validation test "passed" with
  a bare banner; PowerShell rerun showed the real error path.
  (2026-07-23)

- **cmd: exit /b N inside a MULTI-STATEMENT parenthesized block returns
  0 to the caller** - error paths written that way silently disarm the
  orchestrator's failure handling. The single-line
  `( echo msg & exit /b 1 )` form DOES propagate correctly (verified:
  all five workflow bats return exit 1 on arg errors via PowerShell
  $LASTEXITCODE). Rule: never put exit /b inside multi-line parens; use
  single-line chains or goto. Discovered: growth-driver agent reproduced
  the quirk during GrowZone.bat testing; single-line form verified by
  main session. (2026-07-23)
- **Within-zone growth driver exists** (grow_zone.py + GrowZone.bat,
  five modes: global/component/merge/export/cleanup): .rsproj-bundle
  checkpoints (project stem folder holds sfm*.dat blobs - zone_1's
  sfm9.dat is 322 MB), -editInputSelection default with legacy
  fallback, lock-anchor behind a flag pending U18, stale cleanup by
  strict containment with untrusted-manifest exclusion. Open risks
  filed as hardening cells: selectImage per-image spawn cost at
  thousands-scale, exportLatestComponents coverage after isolated
  passes, editInputSelection value forms, -load on a delegated
  instance. Built by team agent; compile + arg-validation verified by
  main session. (2026-07-23)

- **cmd label-search fails on LF-only line endings**: "The system
  cannot find the batch label specified - run" struck mid-loop in
  AlignZone.bat after earlier `call :run` calls in the SAME file
  succeeded - cmd re-scans the file for the label at each call and the
  scan breaks intermittently at LF-only byte offsets. All .bat/.vbs
  written by tooling must be CRLF; seven scripts were silently LF and
  are now normalized. Rule: normalize line endings after any scripted
  .bat edit. Discovered: in-session identity loop smoke run failing at
  a label lookup, 2026-07-23. (2026-07-23)

- **CRITICAL SELF-INFLICTED (caught by review, fixed + verified
  2026-07-24): the ErrorWriterLaunch.vbs quoting was malformed and
  ErrorWriter.bat NEVER RAN** - the errors-marker system was inert for
  every run between the shim's introduction (07-23 ~19:54) and the fix,
  meaning workflow success was judged by exit codes only. Completed
  results remain trustworthy because they were validated by
  census/manifest data, not markers. Diagnostic that proved it: the
  hook fires for every completed process incl. heartbeats, so an
  active progress file WITHOUT a results log is proof the hook is
  dead. Fix: Chr(34)-composed `cmd /c ""<bat>" args"` + unquoted
  numeric args + %~N in ErrorWriter.bat; verified live on both the
  success and error paths. Lessons: (a) VBS quote-escaping in string
  literals is a trap - compose with Chr(34); (b) after ANY change to
  the hook chain, verify results_<inst>.log grows during the next run.
  (2026-07-24)
- **Clean-sweep review (3 agents, 2026-07-24)**: 40+ findings triaged.
  Applied same-day: the VBS blocker above; growth-manifest naming to
  contract (<rsalign>.manifest.json) so merge twin-resolution can see
  them; honest no-op for the impossible growth manifest refresh;
  RC_projects location unified (growth saves had landed one level too
  deep); merge_plan crash guards; GenerateModel tolerant handlers now
  WHITELIST empty-selection codes (2147942487/2181038335) and set a
  skip flag so a skipped filter can no longer rename+delete
  HighPoly_Raw; deselectAllImages before align-mode exportLatest in
  the merge workflow; README/CLAUDE doc corrections. Remaining
  findings queued in HANDOFF review backlog. (2026-07-24)

## Process conventions

- RC_projects daily save schema: {expedition_dive}_{zone|merged}_YYYYMMDD
  .rsproj in RC_projects one level up from the zone image directory;
  saves after components / merge / texture / final model. (owner
  requirement 2026-07-23)
- Model recipe (owner 2026-07-23): high -> remove marginal -> remove
  large(30) -> largest component -> closeHoles+clean -> simplify(noise)
  -> texture -> 4x simplify(smooth 80%)+clean -> unwrap -> reproject.
  Keep: raw high, textured pre-simplify, textured post-simplify.
  Texture AFTER closeHoles so fill areas get blended image color;
  reprojection then maps manifold->manifold (no nodata).
- Never run RealityScan headless for owner-attended runs: RS_HEADLESS=0.
- ASCII-only console output everywhere (cp1252 crashes; hit twice:
  ROVDataConcat convention, georeference module U+2264). Python stdout
  under redirection needs PYTHONIOENCODING=utf-8 or ASCII text.
