# Goal verification session — tests + owner Q&A for the FINAL goal

Written 2026-08-08 on owner directive: separate what is crucial to the
FINAL GOAL from what merely finishes ON2026, re-assess the goal, decide
whether another audit is required, and design the verification session
for the crucial set.

## 1. The final goal, re-assessed

Three goal layers have accumulated; the FINAL goal is the third:

- **Dataset goal (ON2026)**: one unified, textured, metric component per
  major feature (hull, two masts, stern flag-pole) from the COLMAP
  master nav.
- **Product goal**: RealityScan_CLI as a shipping product - software
  quality + user delivery/expectations/experience + scientific rigor as
  an ANALYSIS product.
- **FINAL GOAL (synthesis)**: a repeatable pipeline product that a
  data-literate operator - human or AI agent under the driving contract
  - can point at ANY expedition dataset ("pull this CLI and run it
  against this dataset") and obtain feature-labeled, metrically
  VERIFIED, provenance-carrying textured models, through an intake ->
  pre-flight -> hardened-run -> manifested-deliverable flow. ON2026 is
  the current instance and proving ground, not the goal.

## 2. Classification of the 14 must-fixes

CRUCIAL TO THE FINAL GOAL (the product does not exist without them):
  #3 measured metric verification, #4 deliverable manifest/provenance,
  #5 accuracy statement, #6 settings provenance, #7-remnant merge
  unanimity, #8 cancel semantics, #10 overwrite/versioning safety,
  #11 non-tty fail-fast, #12 pre-flight gate.
PRODUCT-IMPORTANT, SECOND TIER (portal UX; CLI path can ship first):
  #13 StatusScreen/retry-current, #14 wizard prefill.
ON2026-SCOPED: #1 run2 driver instance, features.json confirmation,
  ori-accuracy A/B gate. (#2 fingerprint served both; done.)

GAPS THE 14 DO NOT COVER (surfaced by this re-assessment - the
generalization axis the final goal adds):
  G1. No end-to-end test exists (fixture -> zones -> align -> merge ->
      model -> manifest); every stage is tested, the SPINE is not.
  G2. The nav bridge (COLMAP -> flight log) lives OUTSIDE the product
      (colmap_studio/pipeline/export_rs_flightlog.py) - the master-nav
      concept is product-core but is campaign glue today.
  G3. Rig extensibility is unproven: modules/cameras.json on2026_voyis
      carries axes:null (open ENU/NED question), eye patterns that do
      not match the staged L_/R_ names, stereo_baseline_m:null (since
      measured: 0.16970 m exactly); unknown-rig intake requires
      operators to invent lever-arm numbers (fabricated provenance).
  G4. The driving contract (AGENT_OPERATIONS) is documentation only -
      no code performs intake/charter; each campaign hand-rolls a
      testing/run_<campaign>.py driver instead of a config-driven
      generic one.

## 3. Is another audit required?

- Another BROAD audit: **NO.** Two full audits + an empirical persona
  campaign in four days have converged (the re-audit mostly confirmed
  and statused the first); a third sweep re-finds the queue.
- A TARGETED goal-alignment audit: **YES**, folded into this session as
  its first block (Block A) - scope strictly G1-G4 + registry/format
  generalization, judged against the final-goal statement above, not
  against code quality (already covered).

## 4. The session

Two interleaved tracks: TESTS (empirical, each with pass criteria and a
known-bad case where the oracle discipline demands one) and OWNER Q&A
(each question with context and a proposed default, so answering is
minutes, not design work). Order matters: questions whose answers shape
implementations come before their tests.

### Block A - targeted goal-alignment audit (agent work, ~half day)
Charter: verify and size G1-G4 at current HEAD; deliver findings +
implementation order. Includes: does any single command take the fixture
to a manifested deliverable; what would moving the nav bridge in-repo
take; enumerate every rig/format assumption that breaks on a novel dive
(patterns, extensions, mounts, frame conventions).

### Block B - owner Q&A (the decision session)

ALL ANSWERED 2026-08-08 (owner session):
- **Q1 RATIFIED** - the final-goal statement in section 1 is correct.
- **Q2** - TWO first-class nav sources: the COLMAP bridge OR the existing
  Expedition Data structure (ROVDataConcat-derived products via the
  georeference path). The bridge becomes a product module (G2).
- **Q3** - three-part accuracy claim ADOPTED (internal consistency p95 +
  absolute-position basis + measured scale). Local-frame deliverables
  ACCEPTABLE for ON2026, stated plainly; UTM georeferencing later via
  the USBL fit.
- **Q4** - Expedition/Dive/[data] organization; products named
  `{expedition}_{dive}_{product}`; IMAGE FILENAMES NEVER OVERWRITTEN
  (see N2). ON2026 merged code: `ON2026_RH0041_RH2042_...` (as typed;
  flag: verify RH2042 vs RH0042 against dive logs before first use).
- **Q5** - CANCEL CANCELS: kill tears down the process tree, interruption
  recorded; `--detach` opts into finish-then-stop.
- **Q6** - pre-flight checklist RATIFIED: the drafted 8 PLUS an
  expected-duration/stage-cost line.
- **Q7** - v1 scope: ALL FOUR families (ROV 4-camera, VOYIS stereo via
  bridge, video-only, HEIC). Video must handle h.264 AND h.265 across
  varied container extensions, robustly. Known-camera priors are
  HARDCODED per owner: Zeuss = 25 mm rectilinear; Port/Starboard/Upper/
  Mid = 15 mm fisheye; Cinema = 17 mm rectilinear (owner UPDATED the
  2026-07-23 registry values of 23/14 mm - registry, CLAUDE.md, XMP
  content, and dependent constants must be updated together). Unknown
  camera: ASK the user for what is known; DIVISION is the default
  distortion model across all camera types.
- **Q8** - generic config-driven campaign driver IS v1 (charter intake in
  code; per-campaign scripts retire).
- **Q9** - metric shipping band ±1% (0.99-1.01) on exported geometry.
- **N1** - explicit `LOCAL` tag in local-frame log names
  (`{exp}_{dive}_LOCAL_flight_log.txt`); parser learns the tag; UTM logs
  keep zone tags.
- **N2** - VOYIS originals DO carry left/right in their filenames
  (verified: `...image_left_processed_D....jpg`); the basename collision
  was CREATED by our own staging (RhodyProc stereo_rename.py strips the
  eye token). Owner directive: STOP the renaming - preserve original
  filenames end-to-end; disambiguate only on TRUE collision, smartly;
  derived views only where genuinely needed, mapping recorded in the
  manifest. (ON2026-as-staged keeps its L_/R_ bridge views - originals
  untouched - since its names were already stripped upstream.)
- **Q10** - agent verifies ENU/NED from bundle-adjusted poses and fills
  the registry (in progress; local frame = axis convention only).
- **Q1 Goal ratification.** Is section 1's FINAL GOAL statement right?
  Anything missing (delivery targets like Nira/Cesium? multi-user?).
- **Q2 Nav-source policy.** Is COLMAP the standing master-nav source for
  stereo-rig campaigns (bridge becomes a product module, G2), with
  USBL/DVL georeference as the alternative path - or is COLMAP
  per-campaign glue? Default: product module.
- **Q3 Accuracy claim (#5).** Proposed statement per deliverable:
  "positions accurate to X m (p95) relative to the navigation solution;
  navigation solution accurate to Y (source-dependent); scale verified
  Z% of reference". I draft numbers per campaign; you approve the FORM.
- **Q4 Deliverable naming (#9).** Default: metric analysis product owns
  the plain name `<campaign>_<feature>.obj`; game-engine builds get
  explicit suffixes (`_unreal100`); feature labels come from
  features.json vocabulary.
- **Q5 Cancel semantics (#8).** Default: cancel CANCELS (kill tree +
  interruption record); `--detach` opts into finish-headless.
- **Q6 Pre-flight checklist (#12).** Ratify/edit the 8 persona-drafted
  confirmations (locations+provenance, write-consent, frame, priors,
  budgets, instance/cache, disk, resume state).
- **Q7 Generalization scope for v1.** Which rigs/formats must v1 intake
  cleanly: NA156 4-camera family + VOYIS stereo? HEIC stills? Video-only
  dives? Sets Block D's matrix.
- **Q8 Driving depth for v1.** Should charter intake exist as CODE (a
  config-driven generic driver replacing per-campaign scripts, G4), or
  stay contract-docs + hand-written drivers for now? Default: code.
- **Q9 Metric acceptance band (#3).** Default: exported-geometry scale
  within 0.99-1.01 of the nav reference (tighter than the 0.9-1.1
  component gate; it is the SHIPPING claim).
- **Q10 ENU/NED for on2026_voyis axes** - I supply the evidence from the
  bundle-adjusted poses; you confirm the convention entry.

### Block C - crucial-item tests (each lands with its fix, in order)
- **T1 End-to-end spine (G1)**: one command, fixture -> zoned -> aligned
  -> merged -> ModelToFinal -> DELIVERABLE_MANIFEST. Pass: deliverable +
  manifest exist; manifest hashes verify; measured scale in band.
- **T2 Metric measurement (#3)**: scale oracle runs on the EXPORTED OBJ
  vs nav. Known-good passes; a deliberately scale-100 export MUST FAIL
  the gate (known-bad case).
- **T3 Provenance round-trip (#4)**: a fresh session, given only the
  manifest, locates and hash-verifies every input (nav, settings XML,
  repo SHA, RS build) or reports precisely what is missing.
- **T4 Interruption matrix (#8)**: kill driver mid-align and mid-model;
  per Q5 the work stops; an interruption record exists; the next run
  says "previous run was interrupted at <stage>".
- **T5 Overwrite safety (#10)**: same-name re-export versions instead of
  clobbering; ModelToFinal re-run on the same scene does not collide.
- **T6 Agent-driving fail-fast (#11)**: non-tty + missing required value
  exits nonzero naming the flag; `--yes` is the only auto-accept.
- **T7 Settings provenance (#6)**: a REFUSED run's value does not
  resurface as a bare default; prompts show value + age + outcome.
- **T8 Alien-rig intake (G3, scope per Q7)**: synthetic dive with
  unknown camera prefixes and (per Q7) HEIC names - intake surfaces the
  unknowns loudly, refuses to fabricate mounts, nothing silently drops.
- **T9 Driving rehearsal (G4)**: full charter session against the
  fixture as if the owner said "pull this CLI and run it against this
  dataset" - intake Q&A performed for real, charter written, signed,
  run executed, manifest delivered. The rehearsal grades the CONTRACT,
  not just the code.

### Dataset gates (ON2026, outside this session's scope)
features.json confirmation; ori-accuracy A/B; run2 execution. These
resume independently whenever the owner flips the gates.

## 5. Exit criterion

The final goal is MET for v1 when T1-T9 pass on the fixture plus one
full-scale campaign (ON2026) end-to-end, with Q1-Q10 answered and
recorded here with dates.
