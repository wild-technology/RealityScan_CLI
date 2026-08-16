# Product readiness backlog — RealityScan_CLI as a shipping analysis product

Working queue distilled from three evidence streams (2026-08-05 review,
2026-08-08 re-audit — 17 agents, every must-fix adversarially verified at
HEAD — and 2026-08-08 persona role-play: four "knows the data, not the
tool" users driving the real tool on fixture data). Owner bar: software
quality + user-delivery/expectations/experience + scientific rigor as an
ANALYSIS PRODUCT. END GOAL: a single unified component per major surveyed
feature (ON2026: hull, two masts, stern flag-pole), delivered with
provenance.

Update discipline: when an item lands, move it to DONE with the commit
hash. Every fix ships with a test or an empirical verification transcript.

## DONE

- 2026-08-08 `8e38316` batch 1: local-frame align unblocked
  (frame-derived FlightLogParams selection + `--r_flight_log_params`,
  unit-tested); merge-scene camera ceiling enforced pre-launch
  (`scene_ceiling_verdict`, default 34,000, C-20260802-01, tested incl.
  the recorded OOM scene); `--help` exits 0 with the full parser;
  `--r_min_component_size` exposed (field-validated same day: fixture
  align exported a 20-camera component at threshold 10); root
  requirements.txt (discovery: textual/rich absent on HONEYBADGER — the
  WildScan portal could not import and 26 of its tests were dormant; 461
  tests now pass, zero skips).

## MUST-FIX

### Blocks run2 (ON2026 per-feature delivery)
1. **run_on2026_wreck.py is the retired plan** — monolith terminal stage,
   old campaign paths, nav-blind `zone_done()` (any .rsalign+.json =
   skip). Replace per the run2 architecture spec (re-audit `run2-arch`):
   folder-copy Z-aware zones from `M:\ON2026_run2\nav\flight_log_run2.txt`
   → per-zone aligns → per-feature merge complists under the ceiling →
   ModelToFinal per feature → deliverable manifest. Every merge arg
   explicit (rs_settings inheritance is a recorded incident).
2. **Align-stage fingerprint missing** (persona: settings-change retry is
   messaged identically to a same-settings retry; nothing records which
   settings/nav built a component). Write `align_inputs.json` next to each
   zone's exports: sha256 of flight log + params XML + template + repo
   SHA + RS build. This is also what a nav-aware `zone_done()` needs, and
   what the merge stage should verify for frame/settings unanimity.

### Scientific rigor (analysis-product claims)
3. **"Metric" is asserted, not measured** — ON2026_final_metric.obj's
   scale claim rests on the export preset + a vertex ratio (convention,
   not measurement); the scale oracle never ran on exported geometry.
   Add a post-export measured-scale verification + record the result.
4. **No provenance travels with deliverables** — `final\` holds geometry
   only. Emit DELIVERABLE_MANIFEST.json + rendered README per export
   (persona draft schema in the role-play report: role/feature/path/
   format/scale/units/coordinate_frame/nav_version/mesh stats/sha256,
   plus variant and checkpoint roles); point the workspace census at it.
5. **No customer-visible accuracy statement** — the analysis-product
   question "what positional accuracy is this mesh?" is unanswerable from
   the deliverable. Derive from nav priors + solve residuals + scale-gate
   result; state it in the manifest/README.
6. **Settings persistence has zero provenance** (persona-verified: a
   REFUSED run's bogus path resurfaces as the next default identically to
   a good run's). rs_settings entries need {value, saved-when, campaign,
   last-run-outcome}; surface that provenance in the prompt default.
7. **AlignmentParams changes between zone runs are invisible** — zones
   aligned under different settings merge into one deliverable with no
   record and no refusal (fix rides on item 2's fingerprint).

### User experience (persona-verified)
8. **Killed driver ≠ cancelled run** — the .bat/cmd child keeps driving
   RealityScan headless to completion; no interruption record exists;
   outputs look normal. Process-group termination or an interruption
   marker + startup detection.
9. **Deliverable directory answers nothing** — no manifest/README (item
   4); `final\` absent from WildScan's results taxonomy (session.py); the
   scale-100 Unreal build carries the plain "final" name while the metric
   analysis product carries a suffix. Fix naming + taxonomy + manifest
   together.
10. **ModelToFinal silently overwrites a prior deliverable** on same-name
    re-export (no existence check/versioning) — and fixed internal model
    names collide on re-run in a persistent scene (new-chain audit).
11. **Non-tty prompts silently self-answer** with stored/fallback
    defaults (persona: 21 prompts auto-answered; piped answers never
    read). Non-tty + missing required value must fail fast naming the
    flag (partially true today only for output_dir); a `--yes` flag
    should be the only auto-accept path.
12. **No pre-run confirmation gate** — the "Parameters:" echo prints
    after prompts and execution starts immediately. Implement the
    persona-drafted PRE-FLIGHT CHECKLIST (data locations w/ provenance,
    write-into-originals consent, resolved coordinate frame, priors
    accuracies vs campaign, detector/texture budgets, instance+cache,
    disk headroom vs stage estimate, resume state) with explicit
    confirm; `--yes` for unattended.
13. **StatusScreen unreachable without launching a run** (wildscan) and
    failure UX offers only skip-forward — no retry-current-stage.
14. **Wizard prefill precedence inverted** — previous survey's persisted
    answers override fresh auto-detection for a NEW dive
    (wrong-provenance risk, verified app.py:275).

## MUST-FIX — added from the goal-verification decisions (2026-08-08)

15. **Stop the staging rename** (owner directive, N2): RhodyProc
    stereo_rename.py strips the left/right eye token from VOYIS original
    filenames, manufacturing the basename collision the L_/R_ views then
    solve. Original filenames are preserved end-to-end; pairing keys on
    the eye token in the ORIGINAL name; disambiguation only on true
    collision. (Cross-repo: RhodyProc + the colmap_studio bridge.)
16. **Calibration registry update** (owner-directed): Zeuss 25 mm
    rectilinear, Port/Starboard/Upper/Mid 15 mm fisheye, Cinema 17 mm
    rectilinear — replaces the 2026-07-23 values (23/14 mm) in
    cameras.json, camera_registry XMP content, CLAUDE.md, geoall
    constants, wildscan OFFICIAL_CAMERAS, and the rig-mount tests, in
    ONE change set.
17. **Unknown-camera intake flow**: ask the user for what is known
    (never require invented numbers — supersedes the wizard
    invented-lever-arm finding); DIVISION is the default distortion
    model across all camera types.
18. **Video robustness**: h.264 AND h.265 across varied container
    extensions; HEIC reader (pillow-heif) across all six extension
    filters — all four data families are v1 scope.
19. **Naming scheme implementation**: `{expedition}_{dive}_{product}`
    with explicit `LOCAL`/zone tags in flight-log names (parser learns
    the LOCAL tag); Expedition/Dive/[data] deliverable trees; ON2026
    merged code `ON2026_RH0041_RH2042` (verify RH2042 vs RH0042 before
    first use).

## SHOULD-FIX
- Resolved-settings provenance banner at merge startup (CLI vs stored vs
  fallback per arg).
- batch_use_z silent 2D degeneration when the alt column is missing
  (still logs "Z-aware batching").
- pair_gate 2D bboxes chain vertically-separated zones (extend manifests
  with Z range; 3D overlap when present).
- GenerateModel: keep-largest-component unconditional + large-triangle
  cull — thin-feature hostile on the run_models/driver path (ModelToFinal
  avoids it); parameterize; delete the dead `_HighPoly` cleanup entry.
- shared_graph_spans admits merge rungs on basenames without path
  identity (rigid-glue scored by additive counts) — acknowledged hazard,
  ungated.
- build_union_flight_log sources per-zone logs (stale-frame risk);
  local-frame decision reads first-in-walk-order log; add unanimity check
  (partially fixed 7a22b51 — verify remaining gap).
- Wildcard attach bypasses the per-instance lock contract.
- ~~AlignZone applier silently drops the 7 GUI-obfuscated keys
  (s235l/s236l/s237l/s251l–s254l) from AlignmentParams.xml.~~ **CLOSED
  2026-08-15.** Settings contract restated: the params XML is
  authoritative for every key it names (all 35 now applied, verified by
  parse); keys it does not name are explicitly UNDEFINED and inherit the
  instance. `app*` keys fail closed rather than being dropped.
- Direct .bat invocation path: instance-name collision at boot yields a
  raw HRESULT; frame guard not applied.
- Silent 900 s shutdown-verify wait on cancel/failure; orphaned instance
  left with no PID named and no recovery instruction.
- "Re-run resumes from successful zones" failure message is untrue —
  every re-run supersedes and redoes the zone; align either resumes or
  the message changes.
- Progress UX during multi-hour ops: unlabeled raw tuples; zone-count
  granularity bar.
- README: no quickstart; leads with the developer orchestrator while
  WildScan is the de-facto product entry; RS_ALIGN_PARAMS/RS_CACHE_DIR
  (science- and survival-critical) documented only in source comments;
  raw-.bat workflows taught where hardened drivers exist; branding
  three-way incoherent (RealityScan_CLI / WildScan / drivers).
- Campaign-level retry organization: sibling roots hand-minted per merge
  retry (merged, merged_lt005, ...) with no product support or record.
- Model names don't identify surveyed features ("maximal_HighPoly_
  Textured") — conflicts with one-component-per-feature delivery.
- run_models.py workspace mode reaches only latest_merge() and cannot
  pass the triangle threshold.
- Camera wizard requires invented lever-arm/tilt numbers for unknown
  prefixes (fabricated-provenance risk).
- SessionScreen re-scans the filesystem on every keystroke in path
  fields.
- RealityScan build/version never recorded per run (2.0/2.1/2.2 accepted
  interchangeably).
- Batcher writes flight-log rows for images it never copied (strict gate
  risk downstream); folder-copy zoning copies ~130 GB where os.link
  would do.
- Per-zone flight logs inherit the master's row for EVERY member incl.
  overlap donations — fine — but zone logs and components carry no frame
  tag (FRAME_WARNING markers are manual); fold frame identity into item
  2's fingerprint.

## NITS
- Logging-formatted prompts + Matplotlib/Seaborn version banner as the
  first user-visible line of every invocation.
- Attempt ordinals carry no "accepted" marker in merged trees.
- `main.py --help` epilog should name RS_MODULES / RS_NO_INTERACTIVE /
  RS_ALIGN_PARAMS / RS_CACHE_DIR / RS_INSTANCE (fixed alongside batch 2).

## Design anchors (persona-drafted, adopt when implementing items 4/12)
- PRE-FLIGHT CHECKLIST: see role-play report `config-confidence`
  transcript (8 confirmations, each mapped to today's mechanism).
- DELIVERABLE_MANIFEST.json: see role-play report `downstream-products`
  transcript (schema v1 with PRIMARY/variant/project/checkpoint roles,
  feature labels bound to user vocabulary, nav_version, sha256).
