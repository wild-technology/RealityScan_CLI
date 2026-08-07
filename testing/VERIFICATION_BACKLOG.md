# VERIFICATION BACKLOG — living list of claims requiring proof

Started 2026-08-07 (owner instruction, during the consolidation review).
One row per claim or job; update STATUS in place, never delete rows —
resolved rows get their resolution and date. Companion to the root
`FINDINGS.md` (established facts) — this file holds what is NOT yet
established. When an item resolves, its fact goes to `FINDINGS.md` and
the row here points at it.

STATUS vocabulary: `OPEN` (needs work) · `BLOCKED(<on what>)` ·
`VERIFIED(date)` · `REFUTED(date)` · `PENDING-INTEGRATION` (evidence
exists on another machine / unpushed commit).

---

## A. Claims from the stranded Honeybadger session (correspondence, never completed)

That session committed `085b89c` (docs/rs-reference/ manual, 14 files,
27,703 lines, +5 FINDINGS entries) and `e4a4d10` (CLAUDE.md rewrite +
FROZEN header on NA167_SESSION_NOTES.md) — **neither commit is on
origin nor on this machine** (verified 2026-08-07: `git cat-file -e`
fails for both; sibling checkout `../RealityScan_CLI` is at `902fcf7`
clean; this box has no `py` launcher the session used). Until pushed,
every claim below about the manual's content is unverifiable here.

| # | Claim | Status |
|---|---|---|
| A1 | CLAUDE.md hard rule 3 quotes a 300 s shutdown bound while code sets 900 s | **VERIFIED(2026-08-07)** — CLAUDE.md:150 "shutdown (300 s)"; `realityscan_cli.py:190` `SHUTDOWN_VERIFY_TIMEOUT_SECONDS = 900`, settings-overridable at :296. Fix arrives with their CLAUDE.md rewrite — do NOT also fix locally (conflict). |
| A2 | NA167 notes number B10 and B11 twice each | **VERIFIED(2026-08-07)** — B10(INT):261 / B10(RS):274, B11(RS):267 / B11(RS):283. Renumber is DEFERRED: their manual cites "B10"/"B11" 35 times and their citation-rewrite plan handles the disambiguation — renumbering here first would remap their citations wrongly. |
| A3 | B1–B9 are near-1:1 restatements of frozen NA167 #-findings (B1→#11, B2→#13, B3→#14, B4→#12, B5→#15, B6→#16, B7→#3+#4, B8→#17+#18, B9→#10) | **PARTIALLY VERIFIED(2026-08-07)** — spot-checked B1→#11, B3→#14, B9→#10: all correct. Remaining six mappings unchecked. |
| A4 | 167 tests pass on their tree | **DISCREPANCY** — this tree collects **148**. 19-test gap unexplained: their machine may carry unpushed test files, or the number is stale. Resolve on push. |
| A5 | Manual carries ~355 NA167 mentions: 147→frozen #1–31 (safe), 136→notes B*/filenames (the real job), ~72 prose | BLOCKED(push) — manual not present here. |
| A6 | A **D7 cell refuted** part of the merge-mechanism claim: `-mergeComponents` "fuses ONLY through cameras shared by identity" is superseded; the surviving half is "no content overlap → nothing fuses, silently" | **PENDING-INTEGRATION** — this tree's docs (root FINDINGS.md D6 entries, MERGE_STRATEGY_REPORT, MERGE_REWORK_RECOMMENDATIONS) still carry the pre-D7 reading. Per the docs-are-fact rule, LOCAL docs stay unchanged until the D7 evidence arrives. Any merge-logic work between now and then must treat the identity-fusing claim as CONTESTED. |
| A7 | Their CLAUDE.md rewrite: read-order, pytest baseline, nine working practices, session-end checklist, architecture brought current | BLOCKED(push) — integrate by rebase when it lands; local `main` (7 commits) edits CLAUDE.md and WILL conflict with a full rewrite. |

**Standing constraint until their push lands:** no further local edits
to `CLAUDE.md` or the NA167 notes header region; no doc restructuring
that assumes the manual's absence. The consolidation review's doc
dispositions must route "canonical CLI reference" content toward
`docs/rs-reference/` (incoming), not toward new local homes.

## B. Pending verification jobs (defined, not yet run)

| # | Job | Status |
|---|---|---|
| B1 | The 136-site citation verification + remap (B*→#n / self-contained form) in the manual, then retirement of the notes as a citation target. Their session estimated ~30–45 min, ~12 agents, preservation-audit-first. | BLOCKED(push) — owner already directed this ("evaluate LOE… then delete that reference citation"); execute here once the manual exists in this tree. |
| B2 | Preservation audit of NA167 notes **Section 1** (revised command docs): is any content sole-source (in neither frozen #1–31, root FINDINGS, nor the manual)? Must complete BEFORE any deletion/freeze deepens. | BLOCKED(push) |
| B3 | Relocate NA167 notes **Section 3** (operation ids, error codes, exit codes — added 2026-08-04, i.e. AFTER their freeze decision) into the manual, repoint the root-FINDINGS [ON2026] citations. | BLOCKED(push) |
| B4 | `ModelToFinal.bat` live attach-mode verification. | **VERIFIED(2026-08-07)** — battery on the zone_9 smoke scene: marker gate fires for own-instance (4a exit 1) and skips for `*`-attach (4b exit 0, 143 s full chain: 4x8k default, 80% simplify, `objmetric` scale 1 1 1 in the artifact, RS_SAVE_PATH save, verified shutdown). The C5 probe additionally REFUTED the gate's rev assumption (rev tracks mutations, not ops) — gate rebuilt with lastError baselining the same day; see the [ON2026] battery entries in root FINDINGS.md. |
| B5 | The 4×8k texture-page count against a scene whose unwrap NEEDS >4 pages (does RealityScan clamp, error, or spill?) — nothing in the fact base covers the over-budget case. | OPEN |
| B6 | 19-test collection gap (A4). | BLOCKED(push) |
| B7 | **Smoke-fixture registration ladder converged at a null (2026-08-07).** Five cells on the 32-image zone_9 fixture: A raw-template/no-sidecars 3–5/32; B +correct 57L UTM params 3/32 (frame-poisoning hypothesis REFUTED); C +registry calibration sidecars 8/32 (partial); D +CLAHE 2.0/8×8 8/32 (REFUTED as recovering variable); E +ori accuracies 3/30/3→90 8/32 (REFUTED). The 17/32 precedent (2026-07-21) is not reproduced. Remaining hypotheses: (i) the v2 AlignmentParams config — the precedent predates the settings-application step entirely; (ii) **persisted per-user app settings**: `-set` commands accumulate in RealityScan's stored settings across sessions, so "defaults" today ≠ "defaults" on 7/21 — if (ii) holds, NO historical registration comparison across sessions is trustworthy without a settings-reset protocol, and it interacts with the recorded "whatever the import defaults are" contamination flag. Evidence: `M:\NA173_H2103a\rs_cli_tests\mtf_battery\out{,_b,_c,_d,_e}`. | OPEN |
| B8 | Merge-policy provenance — RESOLVED(2026-08-07) by owner-directed analysis: the library 0.0 default and the drivers' explicit 0.0025 are two halves of ONE owner decision (2026-07-28 bounded loss, hull incident); loss is evidence FOR a real joint solve; wildscan's hardcode is deliberate pinning against rs_settings inheritance; scale band 0.90–1.10 predates and could not have caught the rigid glue. Enshrined as comments at `merge_zones.py` (`loss_tolerance_frac`) and `wildscan/session.py` (merge argv). Owner's recollection recorded as directionally right with causality inverted: better solves shed cameras, not dropping-cameras→better solves. | VERIFIED(2026-08-07) |

## C. Standing technical unknowns (carried from FINDINGS, gating future runs)

| # | Item | Status |
|---|---|---|
| C1 | **Euler-order / camera-mount pin** (`ifKGrp`/`ifKmode` value mapping undocumented). Live progress 2026-08-07 (`testing/EULER_PIN_TEST_PLAN.md`, evidence `M:\...\mtf_battery\euler\`): **P0 REFUTED oracle O1** — no XMP export of imported prior poses without alignment (`-exportXMP` is a silent no-op success; `-exportXMPForSelectedComponent` errors 0x80004005 with no component). **O2 calibration pair FAILED sensitivity** (K0t 6/32 vs KBt-scrambled 8/32, stop rule fired) — but diagnostically: the cells delegated a plain `-align` without applying AlignmentParams, so `sfmEnableCameraPrior` etc. were never set; under fresh-boot defaults, orientation priors demonstrably do not influence this fixture's alignment. REFINED DESIGN: the sweep harness must delegate the `-set` block (mirroring AlignImagesFromFolder's settings application) before `-align`, and the **persisted-settings audit (B7 hypothesis ii) is now a hard prerequisite** — without knowing what settings survive a boot, no cell's in-force config is provable. GUI-dropdown diff (1 min of owner time) remains the cheapest decisive path. | OPEN — blocked on B7(ii) or the GUI diff |
| C2 | Import-side pitch-90 (horizontal-view) YPR singularity — contingent on C1. Decides whether the 24.9% of ON2026 frames near pitch 90 need import-side accuracy widening. | BLOCKED(C1) |
| C3 | Orientation A/B **with true roll** (exporter note: priors now honest at ~1°, `--ori-acc` may be tightened — "A/B it"). Distinct from the already-run-and-lost 90-vs-10 matrix (C-20260730-09), which used fabricated roll. | BLOCKED(C1) |
| C4 | Operation id `0x5034` — observed once adjacent to a save, never isolated. Marked UNCONFIRMED in notes §3; needs one deliberate reproduction. | OPEN |
| C5 | `lastError` stickiness / `rev` semantics. | **VERIFIED(2026-08-07)** — rev does NOT advance on a failed non-mutating op (11→11 on select-miss, lastError 0x80070057 set, trigger fired); stickiness + clear-on-next-op re-confirmed for a second code live (the sticky C5 code did not false-abort the following run). Gate redesigned accordingly. |
| C6 | `modules/flight_logs.py` local-Euclidean support + accuracy-key pinning (`ifUsePosAcc`/`ifUseOriAcc`/`ifCSopt`) — design owned by the consolidation review; verification = round-trip a generated params XML through an import on the smoke fixture. | OPEN — consolidation deliverable |
| C7 | Voyis rig entry in the camera registry (patterns `L_*`/`R_*`, per-eye geometry, stereo-rig scale caveat: RealityScan has no stereo support, staff-confirmed) — design owned by the consolidation review. | OPEN — consolidation deliverable |

## D. Rules for maintaining this file

1. New claims discovered during ANY review land here first with OPEN,
   not in FINDINGS.md — FINDINGS is for established facts only.
2. A row resolves only with evidence attached (command, output, date).
3. Refuted claims stay, marked REFUTED, per the findings-log rule.
4. Session-end: sweep this file; anything resolved-but-unrecorded is a
   session-hygiene failure.
