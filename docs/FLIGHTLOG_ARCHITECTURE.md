# Flight-log-first architecture (owner directive 2026-08-08)

Directive: purge XMP sidecar use; deliver everything through RealityScan
flight logs + settings-XML modification; bake master/zone flight-log
generation into zoning for BOTH nav sources (COLMAP bridge and
ROVDataConcat); image locations hardcoded as complete paths; flight log
loaded at every alignment step. This document records the
investigation (4-agent sweep, 2026-08-08, evidence in FINDINGS.md), the
assumption checks the owner asked for, and the implementation plan.

## 1. Assumption checks (owner: "check my assumptions")

### 1a. "Complete image paths, or RS cannot detect images across zone
### folders in overlapping-zone merges" — CONFIRMED, root cause deeper

RealityScan performs NO image-path matching across folders, ever. The
real mechanism: merge fusion requires SHARED cameras = the SAME image
path in both components. Batch Directory today materializes zone
overlap as per-zone physical COPIES (batch_directory.py:958-959), so
`zone_1\...\img.jpg` and `zone_2\...\img.jpg` are DISTINCT cameras;
overlapping components share nothing, and `-mergeComponents` exits
SUCCESS while silently leaving them separate (FINDINGS.md:326-342 —
already queued as a production defect).

Full-path flight-log rows are documented-legal (`Image — Image name
including the whole path and the format extension`,
defineimportformat.htm) and REQUIRED — but not sufficient. The fix is
both halves:
  1. ONE canonical image pool; zones reference the SAME on-disk paths
     (image lists / hardlinks — junction points silently break XMP
     export, FINDINGS.md:1987-2002, hardlinks validated).
  2. Flight-log rows carry the canonical FULL path per image.
Then overlap images are genuinely shared cameras and merges can fuse.
Basename-vs-path matching semantics when rows carry bare names are
undocumented → probe P3 before relying on mixed forms.

### 1b. "Load the flight log at each alignment step; this purges
### ambiguity/stale-cache issues" — PARTIALLY CONFIRMED, one gap

Current per-step reality (evidence: usage map, FINDINGS refs):
  - Zone align (AlignZone.bat:75-78): flight log imported — YES.
  - Grow (GrowZone.bat): NO mode the driver uses re-imports a flight
    log; the scene's align-time constraints are the only georef. (The
    one import branch, addgrow, is dormant.) → gains an import step.
  - Merge (MergeZoneComponents.bat:164-167): YES — a per-cluster UNION
    flight log is built and imported, followed by `-update` (the step
    that actually georeferences the merged component).
  - Model/export steps: no alignment happens; nothing to import.

Stale-cache: no stale-cache CORRECTNESS hazard is on record; the two
real cache incidents were disk-exhaustion (0x80070070, three hull
models) and cross-instance cache CONCURRENCY (2026-08-08 calib cell,
fixed by per-instance caches: RS1=M:\rs_cache, RS2=M:\rs_cache_rs2).
Re-importing a trajectory into an ALREADY-ALIGNED scene is completely
undocumented (update-vs-replace semantics unknown) → probe P4 before
claiming the per-step import refreshes priors on registered images.
Until P4 lands, per-step loading is correct hygiene for NEW aligns and
merge `-update` placement, but its effect on existing components is an
open question, not a fact.

## 2. What XMP is used for today (inventory verdict)

Three load-bearing roles (full inventory with file:line refs in the
2026-08-08 workflow output; summary here):

  (a) Calibration-prior INPUT — same-name sidecars (WCA/H2023
      production) or explicit `-addImageWithCalibration` (VOYIS test
      path). PURGEABLE for ON2026 — production run2 already runs
      sidecar-free — with TWO capability losses to manage:
      per-physical-camera calibration GROUPS (the only separator for
      EXIF-identical WCA cameras) and per-camera approximate
      intrinsics. Mitigation: flight-log calibration columns (§3) +
      import-time auto-grouping (§3), pending probes.
  (b) Identity-harvest CENSUS — a MEASUREMENT channel, not an input:
      `-exportXMP` successive-difference is the ONLY way the CLI
      reveals registration counts and component membership. Manifests,
      merge attribution, never-shrink invariants, the scale oracle,
      and poses2flightlog (refined flight logs are DERIVED from these
      reads) all sit on it. NOT purgeable without losing the
      measurement system; flight logs and settings are inputs and
      cannot replace an output oracle. Candidate future replacement:
      `-loadColmap` bridge + a validated non-XMP membership oracle —
      needs its own test plan.
  (c) Pose-sidecar hygiene — exists only because (b) drops pose XMPs
      beside images and RS auto-imports same-name sidecars as exact
      priors (B7). Stands or falls with (b).

Decision: purge XMP as an INPUT channel (a); keep (b)+(c) as the
internal measurement machinery until a replacement oracle is validated.
Trivially deletable now: RS_CLI/Metadata/XMPExportParams.xml and
SetVariables.bat's dead XMPMetadata var.

## 3. Flight-log capabilities (RS 2.2, doc-mined + binary-verified)

  - Documented per-row variables (defineimportformat.htm): Image;
    Long/Lat/X/Y/Altitude (+Accuracy each); Yaw/Pitch/Roll and
    Omega/Phi/Kappa (+Accuracy each); AND full prior calibration:
    FocalLength, PrincipalU/V, Skew, AspectRatio, RadialDistortion1-4,
    TangentialDistortion1-2. The exe additionally understands
    FocalLengthNorm/35mm/Pix unit variants (F35MM, FPIX, FNORM),
    principal-point variants, offset columns, and header aliases
    (IMG/NAME/IMAGE, K1-K4, T1/T2).
  - NO per-row calibration-GROUP column. Import-dialog option
    "Automatically group camera calibration": none / one group / by
    focal length (ifKGrp in the params; our template value 2). Per-eye
    groups via flight log would require the by-focal-length mode with
    minutely distinct per-eye focal priors — probe P5, only if the
    calibration ladder says calibration priors matter.
  - production cell A census showed ALL 3,528 cameras in ONE
    calibration group (group 0) — consistent with import-time
    auto-grouping already being active in production. The calibration
    ladder (cells A/B/C) quantifies what per-eye grouping and
    manufacturer priors change.
  - Euler conventions: YPR = ZYX in NED, right-to-left
    (flightlogimport.htm); defineimportformat.htm CONTRADICTS it on
    axes — never trust these pages over the empirical roll validation
    (C-20260803-01).

## 4. Format-ID portability (SHIPPING landmine)

{B438A617-2434-5A24-C1B7-58980F28345A} (our 13-column format) is NOT a
factory format: it exists only in the hand-patched RS 2.0
flightlogs.xml and the repo copy. Stock 2.2 ships 12 fixed formats
(none with orientation ACCURACY or calibration columns) + Custom
{80679981-...}. Production 2.2 on HONEYBADGER imports our logs
correctly ANYWAY — with the ID absent from 2.2's flightlogs.xml, the
user registry, ProgramData, and AppData — so 2.2 is resolving the file
some other way (most plausibly header-alias parsing; our logs carry a
`filename;x;y;alt;...` header). Probes P1/P2 pin this down. Until
then: any deployment recipe must either ship a patched flightlogs.xml
(documented-editable, install dir) or prove header-driven parsing on a
clean install. ifUsePosAcc/ifUseOriAcc (in our params template) exist
in NO 2.x binary — likely dead keys; per-row accuracies demonstrably
DO take effect (ori-accuracy A/B changed solves), so consumption is
row-driven, not key-driven.

## 5. Implementation plan (task #7)

  1. Canonical pool + full-path rows:
     - export_rs_flightlog.py (colmap_studio): emit rows whose Image
       column is the COMPLETE canonical path (new --path-root /
       --path-mode=absolute), CRLF, header aliases RS recognizes.
     - Batch Directory: zone flight logs inherit full paths; stop
       materializing overlap COPIES — zones become image LISTS over
       the canonical pool (hardlinks where a physical tree is needed).
       This is the queued merge-stage defect fix.
     - merge_zones.build_union_flight_log: dedupe by FULL PATH (today
       by basename), rows carry full paths.
  2. Always-generate: master + zone logs generated for BOTH nav
     sources (COLMAP bridge; ROVDataConcat/geoall) through ONE writer
     so header/columns/CRLF/paths cannot diverge (today three writers
     disagree on header case and newlines).
  3. Per-step loading: add flight-log import to the grow workflow;
     keep align + merge imports; document P4's answer once probed.
  4. Calibration via flight log (CONDITIONAL on ladder verdict):
     add F35MM/PrincipalXNorm columns + ifKGrp mode to the generated
     logs; per-eye groups via by-focal-length trick if P5 validates.
  5. Purge XMP INPUT channel: retire sidecar generation calls from
     the batcher path (keep camera_registry content generation for
     the census/hygiene machinery), delete dead Metadata files.
  6. Probes (RSPROBE, cheap, ordered): P1 unknown-GUID/header parse →
     P3 full-path + duplicate-basename matching → P4 re-import onto
     aligned scene → P5 calibration columns + grouping modes.

## 6. Honest boundaries

  - The identity census stays XMP-based for now (measurement channel,
    §2b). "Purge all XMP" is implemented as "no XMP as INPUT";
    replacing the oracle is a separate validated project.
  - WCA (H2023) re-runs still need per-camera XMP groups until P5 (or
    loadColmap) provides an alternative separator for EXIF-identical
    cameras. The WCA sidecar path is therefore mothballed, not
    deleted.
  - Re-import-refreshes-priors is UNVERIFIED (P4) — the per-step-load
    rationale is hygiene + new-align correctness, not yet a proven
    stale-state purge.
