# HANDOFF — state of the July 2026 overhaul

## 2026-08-07 — ON2026 MODEL DELIVERED + NAV PREP BLOCKED, read this first

Different dataset and different lineage from the H2024 line below: ON2026
RH0042/RH0043 Voyis stereo, 38,948 images, `M:\ON2026 COLMAP processing\rs\`.
Nothing running. Rebased onto `902fcf7`; **not pushed**.

### THE DELIVERABLE

`M:\ON2026 COLMAP processing\rs\final\` — 96.5 GB, two exports of one model:

| artifact | detail |
|---|---|
| `ON2026_final.obj` | 9.37 GB, **30,160,616 verts / 60,322,228 faces**, scale 100 (Unreal preset) |
| `metric\ON2026_final_metric.obj` | same mesh at **true scale** — `.rsInfo` `settingsScale="1 1 1"`, vertex 0 `-1.7990 11.0154 0.4367` vs the Unreal build's `-179.8996 1101.5427 43.6697` |
| textures | 4 × diffuse + 4 × normal, each **8192 × 8192** (per set) |
| `ON2026_final.rsproj` | 17.2 MB + 48.5 GB data |
| `ON2026_premodel_checkpoint.rsproj` | +38.7 GB — rollback point taken **before** any model step |

Recipe: texture 4×8k → 4× simplify/clean → unwrap → reproject → export →
save, 4 h, `lastError:0` throughout, final `rev:147`. Driven by
`ModelToFinal.bat`, which **attaches** to a running instance — necessary
because the scene was reconstructed interactively in a GUI session and
every other workflow opens by calling `startRealityScan.bat`, whose
`-newScene -deleteAutosave` would have destroyed 9 h of reconstruction.

**The texture was built on UNCORRECTED imagery** — colour correction
aborted all four attempts and never completed (no completion line in the
app log). That is a quality ceiling, not a defect in the run. Re-texturing
from the checkpoint is the fix if it matters.

### DECISION IN FORCE (owner, pending)

Three questions block the nav re-run; nothing on that track can start
until they are answered:

1. **Where does the updated nav come from?** Nothing newer than the 08-04
   logs exists on `M:`. Candidates: generate from raw Subsonus/DVL/INS
   under `M:\ON2026\RH00xx`; an existing file elsewhere; or Voyis vSLAM.
2. **Is the ON2026 local Euclidean frame ENU or NED?** Decides whether YPR
   needs converting. Settle it against the bundle-adjusted poses already
   in `ON2026_final.rsproj`.
3. **Validation scope** — smoke fixture A/B, full-zone A/B, or straight to
   the full 38,948 run.

**DECIDED (owner, 2026-08-07):** `ModelToFinal.bat` now matches
`GenerateModel.bat` on both formerly-open recipe calls — default texture
preset is `4x8k` (the 2026-07-31 8K cap; `highpoly` = 2×16K remains
available explicitly) and simplify is `SimplifySmooth_80per_Params.xml`
(80%/pass, 0.80⁴ ≈ 41% of input triangles). Note the 2026-08-04 ON2026
deliverable predates this and was simplified at 70%/pass (≈ 24%).

### READ BEFORE PROPOSING ANY ORIENTATION CELL

The `[ON2026]` entries in the repo-root `FINDINGS.md` supersede an earlier,
wrong analysis produced in this session. Specifically:

- ON2026's orientation accuracies are 90° on all 38,948 rows because
  `--ori-acc` defaults to 90 in `colmap_studio/pipeline/export_rs_flightlog.py`
  — **not** because anything is broken.
- The accuracy A/B has **already been run and lost**: colmap_studio
  C-20260730-09 (2,262 images) makes 0.02 m / 90° the production winner;
  tight 10° orientation priors were actively worse. Do not propose it
  fresh — the open question is whether TRUE roll changes that.
- The pitch-convention "conflict" is now RECONCILED as two DIFFERENT
  degeneracies (see the updated `[ON2026]` entry): 1.3% = exporter-side,
  near-vertical views, already mitigated in the exporter; 24.9% = frames
  near pitch 90 (horizontal), which is RealityScan's own candidate YPR
  singularity (middle rotation of intrinsic Roll→Pitch→Yaw), the same
  degeneracy the H2023 line flags for Port at ~88°. The 24.9% reading is
  contingent on the unpinned Euler-order import settings — still OPEN, not
  established.
- The standing gate elsewhere in this log still applies: pin Euler order
  and camera mount in `FlightLogParams.xml` before any further cell.

### LOOSE ENDS, RANKED

1. Answer the three questions above.
2. `modules/flight_logs.py` still emits UTM only, while the shared
   `FlightLogParams.xml` now carries a local-Euclidean value and
   `testing/ab_orientation_priors.py:115` converts it back to UTM — one
   template, two mutually exclusive campaign frames, no guard.
3. Re-texture ON2026 from the checkpoint if colour correction matters.
4. Two ON2026 model paths now coexist: `ModelToFinal.bat` (attach to a live
   scene) and `testing/run_on2026_wreck.py:172` → `GenerateModel.bat`
   (headless from an on-disk scene, no `RS_HEADLESS` in its ENV block).
   Different lineages; keep them labelled.
5. `testing/NA167_SESSION_NOTES.md` has duplicate B10/B11 entries
   (pre-existing upstream, left alone) while `CLAUDE.md` says "B1–B11".

### Exact next commands

Re-inspect the flight-log variants behind the `[ON2026]` nav entries:

```
cd "M:\ON2026 COLMAP processing"
py -3 -c "import csv,statistics as st; rows=[r for r in csv.reader(open('rs/flight_log_zones.txt',newline=''),delimiter=';') if len(r)>=13][1:]; print('n',len(rows)); [print(n, st.median(float(x[i]) for x in rows)) for n,i in [('pitch',8),('roll',9),('yaw_acc',10)]]"
```

Finish a model on an instance you did NOT boot (attaches; never resets a
scene; `*` = first available instance):

```
set "RS_SAVE_PATH=<out>\<name>.rsproj"
modules\realityscan_interface\RS_CLI\Scripts\ModelToFinal.bat "*" "<outdir>" <name> 4x8k true objmetric false false
```

## 2026-07-29 — H2024 COMPLETE + DELIVERABLE TOOLING, read this first

**Committed and pushed**: `656915b` (pipeline fixes, tests 115→143) and the
follow-up commit carrying WildScan, the export/publish tooling and the final
adversarial review's 20 applied findings (tests →157). Pull `origin/main` to
test in another instance.

**New since the models finished**: WildScan TUI (`py -3.13 -m wildscan`),
`ExportDeliverables.bat` (OBJ-by-parts per Nira guidance + FBX-by-parts +
ultra-dense colored PLY; sweeps the "Model N" residuals), `publish_cesium.py`
(ion REST, raw-OBJ + 3D_CAPTURE per Cesium staff guidance) and
`publish_nira.py` (official niraclient wrapper; Enterprise-gated). Texture
budget is now max 4 adaptive 16K textures in both texture passes. Facts:
Nira recommends OBJ not FBX and REFUSES PLY point clouds (LAS/LAZ/E57);
neither platform's in-app share is scriptable.

**Export state**: blocked mid-probe by an owner GUI session holding
H2024_Final_Assembly open (title carries an unsaved `*`); a watcher re-runs
the probe (smallest component first) when it closes, then the full set.

### THE DELIVERABLE

`F:/na156_h2024_v2/final_assembly/assembly/H2024_Final_Assembly.rsproj`
Dated copy: `F:/na156_h2024_v2/RC_projects/NA156_H2024_V2_merged_20260729`
(95.2 GB). **Six components, all modelled, all metrically measured:**

| component | cams | scale | model |
|---|---:|---:|---:|
| `cluster_0_a2_c0` — the HULL | 4,860 | 0.997 | 338.3 min |
| `zone_1_c0` | 1,634 | 1.084 | 249.3 min |
| `cluster_1_a1_c0` | 880 | 1.000 | 122.8 min |
| `zone_4_c0` | 576 | 0.947 | 106.1 min |
| `zone_1_c1` | 392 | 1.023 | 97.4 min |
| `cluster_4_a1_c0` | 133 | 0.980 | 40.1 min |

Three kept models each: `_HighPoly_Raw`, `_HighPoly_Textured`,
`_Simplified_Textured`.

**SIX, not the nominal seven** — align content-fused `zone_4_c2` into the
`zone_1_c2 + zone_4_c1` object (they share 343 images). If your eye says
otherwise, inspect `cluster_1_a1_c0` (880 cams); its pre-fusion inputs are
untouched under `aligned_components/` to rebuild from.

### What changed to get here, and why the previous answer was wrong

merged5's `cluster_1_a3_c0` (3,615 cams) was challenged by the owner and is
CONFIRMED WRONG: a rigid glue of eight disjoint objects. One of its 28 pairs
shared imagery; all three accepted attempts were `merge_georef`; RealityScan
logged "Finalizing 3/7/8" while the arithmetic scored exact fusions with zero
loss. Zero loss on a zero-shared-imagery "fusion" is the co-location
signature. The hull, by contrast, was an ALIGN fusion that lost 5 cameras —
real joint solving.

The rework, now default: `pair_gate=overlap` (components relate only when
they share imagery OR their bboxes truly overlap — transitive 20 m adjacency
is gone), merge rungs admitted only when the shared-image graph SPANS the
subset, and an empty-peel invariant that ABORTS rather than scoring a broken
instrument. Under it the 8 non-hull components partition into 5 clusters and
both fusions were align-driven and exact.

**Fused components cannot be scale-measured by the stem oracle** (merge-scene
XMP exports are ordinal, B10) — it correctly returned UNMEASURED and blocked
all three, including the hull. `testing/run_h2024_fused_models.py` measures
them correspondence-free by quantile ratio, validated against known-good
(1.045 vs stem 1.023) and known-bad (0.236-shrunk hull → FAIL). That is where
0.997 / 1.000 / 0.980 come from — the first time delivered geometry's scale
has been measured rather than inherited.

### LOOSE ENDS, RANKED

1. **Your GUI evaluation of the six modelled components.** Everything else is
   done; this is the only gate left.
2. **The ~5,000-camera model envelope does not plateau.** Peaks: 880 cams ->
   commit 138.6 GB / min RAM 2.8; 1,634 -> 139.9 / 2.0; **hull 4,860 -> 148.7 /
   0.9**. It completed with under a gigabyte of headroom on a 93.6 GB box.
   Treat anything materially larger as at risk, not covered by precedent.
3. **Benign but unexplained**: `-selectModel <tag>_HighPoly` returns the
   whitelisted empty-selection code in EVERY component's cleanup loop, leaving
   one cosmetic intermediate behind. Six for six.
4. **Five RealityScan probes queued, none run** (owner instruction: none until
   modelling completed — that condition is now MET). See FINDINGS "Queued
   RealityScan probes": Finalizing-N semantics, census of merged5's glued
   component, rigid-glue reproduction, the overlap probe's unfinished
   `arm_r2/arm_r6`, and the GenerateModel error-whitelist redesign.
5. **~285 GB reclaimed** from `merged`/`merged2`/`merged3`/`merged4` (bulk
   deleted, 290 record files kept for the FINDINGS evidence trail). `merged5`
   and `nonhull` are KEPT — they hold the original export locations of the
   hull and the two fused components (hard rule 7). F: at 123 GB.
6. **The 6 m overlap band is NOT settled** — only the probe's control arm ran.
   The donor-pool cap is applied and tested; the distance ceiling
   (`batch_overlap_max_distance_m`) defaults to 0 = off pending that answer.
7. **~80 lines of verified-dead code** in `modules/component_manifest.py`
   (`scan_pose_sidecars`, `members_from_sidecars`, `_resolve_image_basename`,
   `_POSE_TAG`) — zero callers, left for your call.
8. **`ruff` is not installed here**, so the Python style check never ran.

### Cross-session incident (2026-07-28)

An exploration session ran its overlap probe FROM this checkout on RS1 while
believing it was isolated on RS2: `RS_INSTANCE` was never read as an input
(fixed — env var now resolves after constructor arg, before settings), and it
overwrote rs_settings.json's `merge` section (restored). Its handoff, findings
and 27-finding audit live at `F:/_copylogs/*2026-07-28*` — reviewed; the
verified items are integrated (see FINDINGS 2026-07-28), the unsettled ones
(6 m overlap band, block-invariant calibration) are explicitly NOT adopted.

### THE H2024 DELIVERABLE (superseded merged5 form)

8,475 cameras total, georeferenced, component names UNIQUE so per-component
model generation can target them. **No models generated** — that gate is still
yours. Every input component passes the 0.90–1.10 metric-scale band.

**The metric-scale crisis is closed.** `zone_3_c0` went 0.236 → 0.965 on the
fresh re-align; the other two baseline failures cleared too. Cause NOT
established — the re-align changed several things at once, so do not attribute
it to any single change without a controlled cell.

**Regression vs the 2026-07-26 baseline** (this was the owner's check): total
8,709 → 8,781 cameras, zone_1 8→6 components, zone_4 5→4, zone_3 +25. Two
small losses, zone_2 −8 (0.57%) and zone_5 −3 (0.13%), both inside the ±1–2
marginal-camera variation a free re-align is already recorded as producing.
The one structural change worth a look: **zone_5 split 1 → 2 components.**

### DECISION IN FORCE (owner, 2026-07-28)

**Bounded loss at 0.25% of input cameras.** A fusion may drop up to that many
cameras and still be accepted. Default remains 0 (exact only) — the 0.25% is
passed explicitly by the driver, warned at startup, and recorded per attempt
plus in EVALUATION_READY. Without it the hull was invisible: it fused 4,860 of
4,865 cameras on every rung and was rejected three times because 4,860 is not
an exact subset sum.

### What was broken, and what fixed it

1. **The peel harvest was blind** — I laid the v2 workspace out with per-zone
   junctions. RealityScan writes no XMP sidecars when a scene's images resolve
   through a reparse point, AND `Get-ChildItem -Recurse` skips reparse-point
   children. Two full merge runs (5h12m) measured nothing. Fixed by replacing
   the junctions with real directories of HARDLINKS (sidecars/flight logs are
   COPIES so a v2 write cannot corrupt the baseline's). `assert_harvestable()`
   now refuses to start if anyone re-junctions that tree — 4 tests, real
   junctions.
2. **Bounded loss** — see above. 5 tests, including the real hull numbers as a
   known-bad/known-good pair.
3. **Duplicate component identity** — `peel_index` restarts each attempt, so two
   accepted fusions in one cluster both claimed `<tag>_m_c0`; `find_borders`
   raised and killed a run after two good fusions. Exports are now
   `<tag>_a<attempt>_c<K>`. 2 tests.
4. **Model targeting** — same collision one layer down: two attempt directories
   exporting the same stem put two identically-named components in the
   assembly, and `GenerateModel.bat` selects by name, so a model would build on
   the wrong component silently. Same fix; verified in merged5.
5. **`MergeZoneComponents.bat` refused to assemble a single component** — the
   `LSS 2` guard applied to every mode. Assemble now needs ≥1, everything else
   ≥2. Verified three ways via `cmd /c`; file re-checked pure CRLF.

### Uncommitted

`FINDINGS.md`, `merge_zones.py`, `MergeZoneComponents.bat`,
`testing/test_merge_scope.py`, plus new `testing/run_h2024_v2.py` and
`testing/test_harvest_guard.py`. 131 tests pass. Nothing committed or pushed.

### LOOSE ENDS, RANKED

1. **Your GUI evaluation of the two components**, then models per component if
   they look right. `--auto_model true` is wired and scale-gated.
2. **~300 GB of superseded merge trees** (`merged/`, `merged2/`, `merged3/`,
   `merged4/`) on F:, which is down to 162 GB. Bulk deletes need your
   approval, so they are untouched. merged5 is the only one to keep.
3. **Dead code, verified zero callers**: `scan_pose_sidecars`,
   `members_from_sidecars`, `_resolve_image_basename`, `_POSE_TAG` in
   `modules/component_manifest.py` (~80 lines). Left in place for your call.
4. **`ruff` is not installed here** — the Python style check in CLAUDE.md could
   not be run this session.
5. **OPEN, not explained**: attempts that re-import a previously fused
   component sometimes harvest nothing (merged3 cluster_1 attempts 2–4). Did
   not recur in merged5. Do not build on it without a probe.
6. **The 638-row flight-log gap**: cluster_0's scene had 4,865 cameras but its
   union flight log only 4,227 rows, because the batcher COPIES overlap images
   into two zones — same basename, two physical files, one trajectory row.
   This is the duplicate-path identity problem already on record; the queued
   batcher change (common image pool via imagelists or hardlinks) is the fix
   and was never applied to H2024.
7. **`ifKGrp=2` / `ifKmode=0x0` still unpinned** — see the 2026-07-27 section.
   Constant across baseline and v2, so it cannot have confounded the
   comparison, but nobody knows what those values select. The GUI
   save-and-diff is still the only way to settle it.
8. **M7 (DVL fused as an absolute fix)** — owner decision, unchanged.

### Exact next commands

```bash
py -3.13 -m pytest testing -q
```

```bash
py -3.13 testing/run_h2024_v2.py --skip_merge
```

To re-run the merge only (aligns are skipped when components exist), edit the
`merged5` output name in `run_merge` first so nothing is overwritten.

## 2026-07-27 SESSION END — nothing running, read this first

**Nothing is running.** No RealityScan, no Python drivers, no workflows. All
RealityScan instances stopped, stale lock files cleared, `rs_settings.json`
restored to `instance_name: RS1`. Repo clean, 115 tests pass, pushed to origin.

### Deliverables as they stand

| Dataset | State |
|---|---|
| **H2023** | **COMPLETE.** 3 components, all modelled and saved |
| **H2024** | Aligned, held at your inspection gate. Merge attempted and killed |

**H2023 project:** `F:/na156_h2023_fresh/merged_pd6/assembly/H2023_PD6_Assembly.rsproj`
(62.6 GB of project data; also reachable at the `D:` path through the junction).
Dated copy: `F:/na156_h2023_fresh/RC_projects/NA156_H2023_PD6_merged_20260726.rsproj`.

| Component | Cameras | Input scale | Models |
|---|---|---|---|
| hull `pd6_zone_1_c0` | 3,738 | 0.982 | `<comp>_HighPoly_Raw`, `_HighPoly_Textured`, `_Simplified_Textured` |
| bow `pd6_zone_1_c1` | 656 | 1.075 (wide IQR) | same three |
| torpedo `zone_3_c0` | 102 | 0.990 | same three |

**H2024:** `F:/na156_h2024/aligned_components/<zone>/` — 16 components from 5
zones (zone_1 **8**, zone_2 1, zone_3 1, zone_4 **5**, zone_5 1), 8,709 cameras.
Per-zone projects openable individually. No models, per instruction.

### CRITICAL PATH NOTE — `D:/na156_h2023_fresh` IS A JUNCTION

The workspace physically lives at `F:/na156_h2023_fresh`. The junction exists
because the saved `.rsproj` stores ABSOLUTE image paths and hard rule 7 says a
relocated `.rsalign` hangs the instance forever. If it is ever deleted, restore
it or every path in this repo breaks:

```bash
powershell -NoProfile -Command "New-Item -ItemType Junction -Path 'D:\na156_h2023_fresh' -Target 'F:\na156_h2023_fresh'"
```

Free space: D: ~197 GB, E: ~6.9 TB (RealityScan cache), F: ~774 GB.

### THE ONE UNRESOLVED DELIVERABLE PROBLEM

**H2024 `zone_3_c0`: 1,192 cameras at metric scale 0.236** — a quarter of true
size, same failure mode as the old H2023 hull (0.175). Measured facts:

- It is a PURE similarity error. Principal axes scale by 0.229 / 0.248 / 0.238
  and the cloud shape is preserved to a few percent — a faithful 1:4.24 model.
- Intrinsics are NOT the cause. zone_3 solved cinema 16.408 / port 15.481, within
  0.2% of the sound zone_5 (16.448 / 15.506).
- Registration looked healthy (93%), `Success: True`. Only the oracle caught it.

**The orientation-prior A/B did NOT explain it.** Position-only re-alignment of
all five zones: zone_1 0.989 (5 comps vs 8), zone_2 1.014, zone_4 0.904 (3 vs 5),
but **zone_3 and zone_5 registered NOTHING AT ALL** — zero components, empty
harvest, "Identity capture finished after 0 component(s)" after 12.7 and 32.4
minutes. So orientation priors are LOAD-BEARING for registration here, not
harmful; removing them destroyed two zones including a perfectly sound one. That
vindicates the owner's "don't throw away validated data" call and leaves zone_3
unexplained. Results: `F:/na156_h2024/ab_position_only/ab_results.json`.

**Next suspect by elimination: the nav.** Review finding M7 — DVL dead-reckoning
is fused as an ABSOLUTE fix at sigma=3 m, 23x tighter than USBL, giving it 96%
posterior weight, in a regime never validated because the depth gate previously
admitted zero DVL fixes. Those positions become the camera priors. **This needs
an owner decision before anything is changed: fixing it alters filter output, so
every existing datatable becomes a different regime.**

### THREE CODE REVIEWS LANDED — reports saved outside the repo

- `F:/_copylogs/review_synthesis.md` — 58 confirmed findings across bugs, QA,
  security and ergonomics, plus a **9-mechanism configuration inventory** (31 CLI
  flags, 15 env vars, 3 key conventions in rs_settings.json) and a concrete
  consolidation design.
- `F:/_copylogs/review_critique.md` — completeness critique of the above.
- `F:/_copylogs/defensive_design.md` — 23 defensive-coding defects ranked by how
  SILENTLY they corrupt a result, plus a validation-layer design.
- `F:/_copylogs/merge_logic_review.md` — 35 confirmed findings on the merge
  acceptance path (see FINDINGS 2026-07-27).

### APPLIED AND COMMITTED THIS SESSION

Tests went 44 -> 115. In dependency order:

1. **`main.py --help` crashed** on a literal `%` in a parameter description
   (argparse %-expansion). Escaped at the argparse layer.
2. **Unattended runs died between modules** on `input("Press enter...")`.
   EOF now means continue.
3. **`main.py` exited 0 when a module REFUSED to run** — bare `return` where the
   module-failure branch used `sys.exit(1)`. Verified exit 1 on the real case.
4. **Unset required params raised `TypeError` from `os.path.isdir`** — guarded
   once in `RSModule.validate_parameters`, covering all six gated params.
5. **`GenerateModel.bat` used FIXED model names** across per-component runs, so
   step [8/8] could reproject one component's texture onto another's mesh
   silently. All 19 references namespaced by component.
6. **Batcher reused zone folders built from different inputs** — 12,679 images on
   disk against 9,834 reported, a blend of two zonings, about to be aligned. Now
   fingerprinted (`batch_inputs.json`) including the IMAGE SOURCE, and failing
   closed on a missing/corrupt/in-progress marker.
7. **`plt.show()` blocked unattended runs** — gated on `stdin.isatty()`.
8. **Resource trace added** to every RealityScan workflow: CPU, RAM, commit
   charge, project disk AND cache disk, every 30 s, flushed per sample.
9. **Scale oracle promoted to a real gate** — moved to `modules/scale_oracle.py`
   (shim left at the old path), measured per component BEFORE any GPU work,
   recorded in the report and EVALUATION_READY, and blocking `--auto_model` for
   anything failing or unmeasurable.
10. **Rig geometry unified** — one `MOUNTS` table keyed by FILENAME FAMILY via
    `camera_registry.family()`, imported by both the module and `geoall.py`.
    Fixed: cruise-digit hardcoding (next cruise got a zero lever arm at 10 deg
    claimed confidence), `geoall` having no WCA table at all while docs call it
    canonical, and its 3 deg orientation accuracy vs the module's 15.
11. **ROVDataConcat failure propagation** — a FAILED module can no longer exit 0.
    Verified against the real `kalman_offset` failure.
12. **Neighbour-scoped merge attempts** — `--merge_scope neighbour` (default),
    with `cluster` retained for comparison.

### LOOSE ENDS, RANKED

1. ~~Two defects in this session's own work~~ **FIXED before session end**
   (commit below). The neighbour-scoping now memoises attempted subsets, so a
   symmetric pair costs three attempts rather than six, and a fusion reopens only
   the targets that border the NEW component instead of clearing everything. The
   scale gate now receives transitive `inputs` on `final_components` - transitive
   because a second-round fusion's attribution names first-round SYNTHETIC keys,
   and the gate is keyed by original inputs. 5 regression tests; 120 total.
2. **The staged `.bat` work** — could not be applied while a merge was executing
   (cmd reads batch files by byte offset). Two changes, one edit:
   - **orphan rung**: replace `sfmImagesOverlap:High` with orphan inclusion.
     `MergeZoneComponents.bat` has NO `-addFolder`, so the merge scene
     structurally cannot contain an orphan today. Orphans need FULL image
     features and an `-align` rung (`-mergeComponents` never adds images).
   - **pin the feature-source mode** (`setFeatureSource 0|1|2`) for components —
     currently never set, so it inherits an unknown default.
   Re-verify CRLF and re-run the marker-hygiene check after any `.bat` edit.
3. **Never-shrink is dead code** — delete it, or move a signed tolerance into
   `attribute_result`. Note a bounded-loss flag is INERT without that, because a
   lossy fusion cannot be attributed at all.
4. **Settle the 2 missing cameras from artifacts already on disk** — read
   RealityScan's own count from the attempt's `rslog.txt`, or re-import
   `cluster_*_m_c0.rsalign` from its ORIGINAL location and census it. 3,740 means
   accounting artifact, 3,738 means real loss.
5. **Pin the flight-log Euler order and Camera mount.** `ifKGrp=2` and
   `ifKmode=0x0` are the only plausible carriers and neither string exists in any
   installed file. **Needs the owner's GUI save-and-diff**: open the
   trajectory-import dialog on the 13-column format, save params at defaults, then
   once more after changing ONLY *Euler angles order (YPR)*, then once more after
   changing ONLY *Camera mount*. Three XMLs plus the chosen option names.
6. **Orphans are never captured in the merge path.** `orphan_images()` exists and
   only `grow_zone.py` calls it. For H2023, 104 images are unaccounted and
   unnamed. Cheap first step: report them in EVALUATION_READY.
7. **M7 (DVL as absolute fix)** — owner decision, see above.
8. **Configuration consolidation** — the largest remaining piece and the one the
   "keep variables in one spot" ask actually points at. Design is in
   `review_synthesis.md` section 2.
9. **Finish the Kalman heading review.** Established: no declination is applied
   anywhere, `kalman_yaw_deg` comes from an Octans gyrocompass, so it is TRUE
   north and `decl = 0` is correct — the repo's `HEADING_MAG` name is a misnomer.
   Still to do: confirm the Octans true-vs-magnetic claim from a primary source,
   and review `filter_heading`'s circular wrap handling.
10. **The batcher's ~3 h zone computation is real.** I wrongly retracted this
    mid-session; a third run with plots gated off still spent 2 h 53 min between
    the two figure saves. The 28.9 min run is an unexplained outlier. Worth
    hunting before the 19k-image datasets.
11. **zone_1's Port intrinsics solved wrong** — 11.929 mm with k1 +0.0055,
    versus 15.48-15.52 and k1 ~ -0.385 everywhere else. Classic focal-vs-radial
    degeneracy on a long straight run (owner's own observation). Testable: pin
    Port's focal or supply measured coefficients under Division on that one zone
    and see whether the 8-way fragmentation collapses.

### DECISIONS IN FORCE

- **CLAHE stays upstream** of batch/align until Q-05 settles. Consequence:
  imagery is both aligned AND textured from CLAHE'd files. Image Layers
  (`.geometry`/`.texture`) agreed as the eventual mechanism, not adopted.
- **Orientation priors ON at alignment**, conservative 15 deg accuracy. The A/B
  now supports this decision on registration grounds.
- **Lever arms**: Port 1.0 m forward / 1.0 m DOWN, Cinema 1.0 / 0.0. Validated on
  two metrically-sound solves (C above P by +1.12 and +1.03 m). **Do not flatten
  them** on the strength of the 0.22 m / 0.00 m figures in FINDINGS — those came
  from the 0.175-scale hull and are scale-corrupted; they were retracted once and
  re-applied by mistake before an audit caught it.
- **No models for H2024** pending visual inspection.

### METHOD NOTES WORTH CARRYING FORWARD

Several of this session's wrong turns share one shape, and the log records each
with what refuted it:

- The hull model failed three times. I blamed concurrent load, then intrinsic
  memory exhaustion. It was **ERROR_DISK_FULL** — and specifically RealityScan's
  CACHE disk, which is placed by drive of the path given and which my own
  junction kept on D: after the project moved to F:. Fixed by `RS_CACHE_DIR`.
- I built the resource trace around the memory hypothesis, so it faithfully
  recorded RAM falling to 3.1 GB and stayed silent about the disk that killed the
  run. Then I added a disk column pointed at the PROJECT drive, which read
  773.9 GB free while the CACHE drive hit zero. **Instrument the resource you
  suspect AND the ones you do not — and the right instance of it.**
- Three rounds of escape corruption in HANDOFF.md, from writing Windows paths
  through Python string literals in shell heredocs (`E:\rscache` -> CR,
  `F:\na156...` -> a real newline). Use forward slashes in docs; never author
  Windows paths inside a heredoc string literal.
- Claims must be checked against the artifact, not inferred from two ends of a
  call chain (the 90-deg Port pitch claim), and a faster run is not a control
  unless it did equivalent work (the batcher retraction).

## 2026-07-25 (evening) RESTART POINT — read this first

**PD-6 COMPLETED and answered the metric-scale question: NO, the hull
scale error does not survive a correct configuration.** Nothing is
running; no RealityScan or Python processes are live.

The delivered assembly at `D:\na156_h2023_fresh\merged\assembly\` is
still **METRICALLY INVALID** (hull at 0.175/0.221) and must not be
modelled or shipped. Its replacement inputs now exist.

### The corrected assembly — BUILT, awaiting owner evaluation

`D:\na156_h2023_fresh\merged_pd6\assembly\H2023_PD6_Assembly.rsproj`
— 3 components, **4,496 / 4,600 unique images (97.7%)**, built
2026-07-25 22:00 in ~1.5 min of solve time (zero merge attempts).
Gate: `D:\na156_h2023_fresh\merged_pd6\EVALUATION_READY.txt`.
Daily save copy: `RC_projects\NA156_H2023_PD6_merged_20260725.rsproj`.

**The instance quit at the end of the workflow — the project is saved,
NOT left open on the desktop.** Reopen it to evaluate.

Please glance at, in the GUI: (a) each of the three components is a
coherent feature (hull / bow / west pocket); (b) georeferencing took
(U7 is still GUI-only); (c) the hull, now ONE native 3,738-camera
component, has no seam where the old c0/c1 split used to be.

The single ERROR line in `driver.log` (`result code 2181038335` =
0x820000FF) is the documented benign err:18002 — verified by matching
all 102 "not in scene" images against every manifest: zero overlap,
they are the unregistered remainder. Not a defect.

Superseded by this: `D:\na156_h2023_fresh\merged\assembly\` (the
metrically invalid one). Do not model or ship it.

### Metrically sound inputs (the assembly's sources)

Scale oracle over every fresh-workspace component (all measured
2026-07-25 evening):

| Component | Cameras | Scale | Source |
|---|---|---|---|
| `pd6_zone_1_c0` (hull) | 3,738 | **0.982** | `D:\na156_h2023_fresh\pd_runs\pd6_zone_1_clean\components` |
| `pd6_zone_1_c1` (bow) | 656 | 1.075 | same |
| `zone_3_c0` (west pocket) | 102 | 0.990 | `D:\na156_h2023_fresh\aligned_components\zone_3` |
| *old* `zone_1_c0/c1` | 3,026 / 714 | *0.175 / 0.221* | superseded — do not use |

Total 4,496 cameras (97.8% of 4,598 unique). zone_2's only component
(101 cams, scale 0.998) is a proven subset of `zone_3_c0` and was
twin-dropped in the fresh run — exclude it.

**The merge ladder has nothing to do.** A dry run of
`merge_zones.partition_clusters` over these three puts them in three
disjoint singleton clusters, zero fusable pairs — the hull that the
fresh run spent ~75 min trying to fuse now solves natively. The
remaining work is the ASSEMBLY stage only: import all three, union
flight log + CRS + `-update`, save, census, evaluation gate.

The command that built the assembly, kept for re-runs (`--components_root`
is the workspace root so the complist's three paths all resolve, and
components stay at their original export locations per hard rule 7):

```bash
py -3.13 merge_zones.py --components_root D:/na156_h2023_fresh --complist D:/na156_h2023_fresh/merged_pd6/inputs.complist --images_root D:/na156_h2023_fresh/batched_images_by_zone --output D:/na156_h2023_fresh/merged_pd6 --name H2023_PD6_Assembly --min_size 50 --target 0.95 --project_label NA156_H2023_PD6 --visible true --auto_model false --ladder merge_first
```

### Fixed this session

- `RealityScanAlignment.capture_component_identities` made public and
  called from `testing/relaunch_pd6.py`: AlignZone.bat writes the
  identity harvest but NOT the manifests, so PD-6's exports had none
  and the feature-aware merge would have refused them. Manifests
  rebuilt for the existing exports (3,738 / 656, census matches).
  See FINDINGS 2026-07-25.

### Reading order for a fresh session

1. `FINDINGS.md`, newest entries — the metric-scale crisis (hull at
   0.175/0.220), the sidecar-stripping defect, over-tight priors, and
   the rig-geometry validation.
2. `testing/PRIORS_DISTORTION_TEST_PLAN.md` — PD cell matrix + bow 2×2.
3. `testing/scale_oracle.py` — the quality oracle; run it on any
   component: `py -3.13 testing/scale_oracle.py <components_dir> <log>`.

### Validated config state

- Division canonical in `AlignmentParams.xml`.
- Position accuracies **10/10/1** (tight fragments — bow 2×2).
- Orientation priors at 15° YPR accuracy; the 13-column flight-log
  format is installed in Program Files (re-check after any RS update).
- `camera_registry`: C and P both 16 mm 35-eq, Approximate throughout.

### Decision in force (owner, 2026-07-26)

**CLAHE stays where it is — upstream of batch/align — until Q-05 is
settled.** No preprocessing changes land while the evidence is split
(LilyJean/COLMAP: CLAHE cut registration ~30%; H2023 zone_9: baseline
aligned to nothing). Consequence to keep in mind: aligned AND textured
imagery is currently the CLAHE'd imagery. Owner agrees RealityScan
**Image Layers** (`.geometry`/`.texture`) is the right eventual
mechanism — align on originals, texture from enhanced. REVISIT TRIGGER:
Q-05 resolves, or an H2024 align shows CLAHE hurting registration on
this rig.

### Open, in priority order

1. **Owner evaluation gate on the new assembly** (built 2026-07-25
   evening, see below), then models per surviving feature component
   (hull / bow / west pocket each get their own).
2. **Close the deliverable-scale blindness**: assemble mode exports no
   XMPs, so `scale_oracle` sees the assembly's INPUTS and not the
   assembled project, while `-update` (a similarity fit) runs after.
   Fix = port the successive-difference harvest to a dated COPY of the
   assembly project — workflow-evaluation item 3, which also yields
   per-component membership. Until then the deliverable's scale is
   inferred from its inputs, not measured.
3. Intermediate accuracy ladder (3/3/0.5, 5/5/1) — loose is proven, not
   proven optimal. Optional now that scale is sound; each cell is a
   ~70 min zone_1 re-align.
4. Optional PD-6 attribution isolation cell (Brown3 + explicit-loose on
   zone_1, ~70 min) — separates Division from the newly-imported
   accuracy columns. Not needed to ship; the corrected config is
   adopted either way.
5. `D:/na156_h2023_v2` is staged through batching; aligns deliberately
   never run.
6. Owner decisions open: whether to supply measured distortion
   coefficients (must be measured under Division). The bounded-loss
   fusion flag is now MOOT for this dive — the hull no longer needs
   fusing — but remains a real design question for future dives.

## 2026-07-25 MORNING STATE — deliverable ready (read this first)

**The fresh end-to-end run COMPLETED overnight.** Full record:
`docs/FRESH_RUN_2026-07-24.md`. Headlines:

- **`D:\na156_h2023_fresh\merged\assembly\H2023_Fresh_Merged.rsproj`
  is OPEN in a RealityScan GUI window on the desktop** (plain app
  session — RS1 stays free). 4 georeferenced components: hull 3,026 +
  hull strip 714 + bow 665 + west pocket 102 = **4,507/4,598 unique
  images (98.0%)** — the best H2023 result to date.
- Evaluation gate: `D:\na156_h2023_fresh\merged\EVALUATION_READY.txt`.
  ONE DECISION WAITING: the hull pair fuses at a reproducible cost of
  2 cameras (3,740 → 3,738 on all three rungs); the never-shrink gate
  auto-rejected it, so hull is currently two overlapping components.
  Options: keep as-is / fuse interactively in the GUI / add a
  bounded-loss acceptance flag to merge_zones.py.
- Please ALSO glance at: georeferencing of the open project (U7 is
  still GUI-only) and the hull seam between c0/c1.
- Optional next automation: cross-zone orphan pickup (91 orphans) on a
  COPY of the merged project; per-component models via
  `--auto_model` / GenerateModel from the gate.
- Everything is committed locally; NOT pushed (say the word).

## 2026-07-24 (evening) FULL FRESH RUN IN FLIGHT — owner deliverable

**Owner directives (2026-07-24 afternoon):** iterate until the workflow
is fully tested/reworked/QA'd AND a full fresh run (raw images + nav →
final project) completes; run the last zone-merge steps GUI-VISIBLE;
deliverable = an OPEN, completely aligned project on the desktop by
morning. Screenshots may verify GUI-only questions.

**State when this section was written:**
- D7 probe DONE → content-fusion rule established (FINDINGS "D7
  RESOLVED"); hook liveness PASSED; merge driver reworked feature-aware
  and unit-tested (44 tests); MergeZoneComponents.bat gained
  assemble mode + count-based peel harvest with tolerant terminal.
- Fresh workspace D:/na156_h2023_fresh: georef 4,598/4,598 → CLAHE →
  3 zones batched (zone_1 4,540 / zone_2 852 / zone_3 124, calibration
  sidecars + filtered logs).
- Production zone aligns RUNNING (sequential, RS1, headless,
  'Batch Directory,RealityScan Alignment' chain, project label
  NA156_H2023_FRESH). Budget declaration: 2.5–5.5 h total for the three
  zones; peak RAM well under the box; abort = stall >45 min / exit
  code 3 / rollback storm.
- NEXT after aligns: (1) re-verify the fixed peel E2E on the smoke pair
  (RS1 free between stages); (2) cross-zone merge via the NEW
  merge_zones.py with --visible true (owner wants to watch); (3) leave
  the assembly .rsproj OPEN in a visible RealityScan instance on the
  desktop; screenshot-verify georeferencing/seams (U7 proxy).
- Growth stage (grow_zone.py) is DELIBERATELY SKIPPED for the fresh
  run deliverable: zone_1/zone_2 production growth showed re-solve
  passes reject or shrink (growth ≈ cheap insurance); the morning
  deliverable is the aligned+merged project. Run growth later if the
  evaluation gate shows recoverable orphans.

## 2026-07-24 (later) ONBOARDING SESSION — recommendations produced

The "onboard, then produce implementation recommendations" task below is
DONE: **`docs/MERGE_REWORK_RECOMMENDATIONS.md`** is the answer to the
workflow-evaluation queue (Q1–Q10), with a recommended order of work.
Read it after this section. What this session settled:

- **The feature geography is in the manifests, and it makes the merge
  target unreachable**: three spatially disjoint clusters — hull 3,720
  images, bow 686, west pocket 102, hull ∩ bow = 0 shared basenames.
  Maximal-component ceiling 80.9% vs `--target` 0.83/0.85. Confirms the
  owner's bow/hull statement from data and quantifies hazard #2.
  Recommended fix is cluster-partitioned merge scenes (one per
  border-connected cluster) — bow and west pocket then get ZERO merge
  attempts instead of ~1.7 h of guaranteed-useless ladder.
- **`D:\na156_h2023\merged` is superseded, not a baseline** (5 ordinal
  exports, empty twin_plan, predates manifests). Stop citing its 83.9%.
- **Zone_1's saved scene escaped the GrowZone disabled-images bug** —
  every component pass was rolled back; `zone_1.rsproj` mtime is the
  `merge` pass's save (all-enabled state). The code bug still stands.
  Confirm in the GUI; the argument is timestamp inference.
- **`-mergeComponents` consolidated zone_1 from 9 components to 4** —
  direct support for queue item 7.
- **MUST-FIX applied**: MergeZoneComponents.bat complist validations now
  route to a top-level `:argfail`. Before/after measured with `cmd //c`:
  a missing complist or missing component returned **0** and would have
  been reported then IGNORED by the driver; now returns 1.
- **Two review items CLOSED as non-issues by measurement**: the shared
  `:run` error-detection channel is LIVE (probe with a non-empty errors
  marker aborts, empty continues), and `startRealityScan.bat`'s nested
  boot-timeout `exit /b 1` propagates correctly through `call`. The
  cmd trap is narrower than recorded — see the refined FINDINGS entry.

Self-tests run: 31 tests pass; all .bat/.vbs confirmed CRLF;
rs_settings.json paths all resolve after the repo move. **Still owed at
the next live run: hook-chain liveness (results_<inst>.log must grow).**

Next concrete step: the smoke-fixture D7 + content-fusion probe (Q1+Q9),
before any production merge_v2.

## NEW-SESSION ONBOARDING (prepared 2026-07-24, session end)

The repo now lives at `C:\Users\jonat\OneDrive\Desktop\CoyoteThings\
RealityScan_CLI` (relocated out of DataProcessing\, owner-approved;
an empty locked leftover folder may linger at the old path — ignore).
Origin is synced through this session's final commit.

Read order: CLAUDE.md -> FINDINGS.md -> this section + the merge
section below -> testing/MERGE_STRATEGY_REPORT.md -> docs/
merge-growth-strategy-2026-07.md -> testing/ALIGN_MERGE_HARDENING_
PLAN.md + testing/MERGE_TEST_PLAN.md. COLMAP material: docs/
COLMAP_CROSSOVER.md only (different workflow — do not mix).

Session-start self-tests (standing): (1) hook-chain liveness —
results_<inst>.log must grow during the first run (CRLF normalization
touched ErrorWriterLaunch.vbs/ErrorWriter.bat on 07-24); (2) confirm
rs_settings.json paths still resolve after the repo move.

**GOVERNING INTENT (owner, 2026-07-24 — reshapes the component
workflow):** H2023 has two discrete physical features (bow + main
hull) surveyed in one dive; zones are density-batched and blind to
feature boundaries. Therefore: a multi-component final state is a
CORRECT outcome; "as big as it can get" is per FEATURE; deletion is
only ever containment-based (no unique images), never size-based; a
maximal-fraction success target misreads disjoint features as merge
failure. End state = ONE project holding every feature component at
its own maximum, georeferenced, owner-evaluated before models (with
an opt-in auto-proceed). The workflow-evaluation queue below is
updated to this intent — the next session should onboard, then
produce implementation recommendations against that queue.

## 2026-07-24 TWO-MACHINE MERGE — read this first in a fresh session

Read order: CLAUDE.md -> FINDINGS.md (consolidated fact base, both
research lines) -> this section -> testing/MERGE_STRATEGY_REPORT.md
(NA167 empirical strategy comparison) -> docs/merge-growth-strategy-
2026-07.md (workflow spec) -> testing/ALIGN_MERGE_HARDENING_PLAN.md +
testing/MERGE_TEST_PLAN.md (open unknowns).

**What happened:** the two parallel research lines — this machine's
NA156/H2023 production + hardening work and the Honeybadger box's
NA167 merge-strategy matrix — were merged (git merge 400e5b1 from the
divergence at 6069d95). Findings logs consolidated into root
FINDINGS.md (testing/FINDINGS.md frozen as NA167 raw provenance).
COLMAP material isolated into docs/COLMAP_CROSSOVER.md. QA: 31 tests
pass, active code compiles, hook-chain scripts re-normalized to CRLF
(*.vbs now pinned in .gitattributes) — **re-verify hook liveness
(results_<inst>.log grows) at the next run on the processing box.**

**CURRENT PROPOSED PRODUCTION WORKFLOW (align → components → merge),
with the data behind each step:**

1. **Per-zone align via AlignZone.bat** — pinned AlignmentParams
   (never instance defaults), appIncSubdirs=true, per-camera XMP
   calibration groups, auto-CRS flight log, exportLatestComponents +
   identity-manifest harvest, no per-zone models. Data: zone regs
   90.1–96.7% across NA167/H2023; settings rationale in
   docs/settings-evaluation-2026-07.md §4; identity capture validated
   end-to-end (FINDINGS, in-session successive-difference).
   Zones run embarrassingly parallel across GPUs (NA167: 21–98
   min/zone, ≤~60 GB each). Joint whole-dive align is OFF the table:
   identical quality to chunked (94.5% vs 94.6%) but ~165 GB at 4k
   images, extrapolating ~700 GB at 19k [NA167 #19].
2. **Within-zone growth via GrowZone.bat under the never-shrink
   invariant** (checkpoint/rollback; accept iff no unique image lost
   and net cameras >= before). Data: align both grows and SHRINKS
   nondeterministically (zone_1: every re-solve pass rejected; zone_2:
   honest zero-gain convergence at 95.1%); rollback validated in anger.
   Expect fast convergence — growth is cheap insurance, not the
   registration engine.
3. **Cross-zone merge via -mergeComponents over SHARED CAMERAS** —
   the only mechanism proven headless [NA167 D6: "Finalizing 1
   component" from halves sharing 390 images; D1–D3: zero-overlap
   never fuses, silently, under any flag]. Budget ~1 h per merge;
   verify EVERY merge by pose-XMP camera census, never exit status.
   PREREQUISITE (batcher change queued): zones must reference a common
   image pool (imagelists/same paths) — per-zone COPIES have no camera
   identity. For existing duplicate-path datasets (H2023), the
   merge_zones.py union-flight-log + -update path apparently fused
   anyway — mechanism UNPROVEN, open cell D7; census + GUI seam
   inspection mandatory until D7 settles.
4. **Rescue failed zones by growing from an aligned neighbor**
   (B-style add→log→align) — the verified workaround for solver-bug
   zones [NA167 #17/#18/#27, MSS_STR001]; verify counts after every
   grow step (a grow can fragment [NA167 #29]).
5. **Georeference the merged scene explicitly** (union flight log +
   CRS + -update — a merged component is NOT georeferenced otherwise
   [H2023]), then models per SURVIVING FEATURE COMPONENT the owner
   approves at the evaluation gate — not "the merged component only";
   discrete features (e.g. H2023 bow vs hull) legitimately end as
   separate components and each gets its own model (owner recipe;
   texture after closeHoles).

**Consolidated priority queue (both machines):**

P0 — production continuity (H2023, processing box):
1. Zone_1 growth is DONE (see previous section) — proceed to cross-zone
   merge_v2 with census + owner GUI seam verification (D7 caveat above).
2. Hook-chain liveness self-test at next session start (CRLF
   normalization touched ErrorWriter.bat/ErrorWriterLaunch.vbs).
3. MUST-FIX review items before the merge/model run (next section):
   MergeZoneComponents.bat exit /b in parens; grow_zone→merge
   .complist handoff; GrowZone component-mode inpEnabled=false
   persistence (CHECK the zone_1 scene for disabled images).

P1 — research follow-ups queued by the reconciliation:
4. **D7** (testing/MERGE_TEST_PLAN.md): does union-flight-log +
   -update in the merge scene enable duplicate-path merging, and is it
   fusion or rigid co-location? Decides merge_zones.py's escalation
   ladder and the H2023 3,860-camera merge's trustworthiness.
5. **Batcher common-image-pool change** (imagelists or hardlinks
   instead of per-zone copies) so future dives merge by identity.
6. Copy the LilyJean/COLMAP fact base off Honeybadger
   (C:\Users\jonat\Desktop\CoyoteThings\itsmagicIswear\FINDINGS.md — PRESENT on this machine as of 2026-08-07); then the
   Q-05 CLAHE reconciliation matrix (docs/COLMAP_CROSSOVER.md).
7. Zone_1 +37 census delta attribution (merge effect vs
   census-mapping nuance) — open from the growth run.
8. Report MSS_STR001 to Epic with testing/results/z14_forensic_rslog.txt.
9. Hardening cells still open: U4–U14, U17 (U7 CLI-observable georef
   check matters most); selectImage regexp-vs-Help forum-mine; D6
   export re-run if the fused .rsalign artifact is ever needed.

P2 — hygiene: retire process_h2023.py; simplify presets are
placeholders; SHOULD-FIX/NITS backlog below; Claude Skill +
documentation guide task (FINDINGS.md is the fact base, docs/ the
rationale base).

**Workflow-evaluation queue (owner-requested audit 2026-07-24,
REVISED same day for the feature-aware intent — see GOVERNING INTENT
in the onboarding section; end goal: every FEATURE component at its
own maximum, all in ONE final georeferenced project, owner evaluation
gate before models, optional auto-proceed):**

Size-based hazards the bow/hull case exposes in current code (audit
result; none deletes data on disk, but three misshape the deliverable):
- MergeZoneComponents.bat merge mode exports the MAXIMAL component
  only -> a bow-sized feature component is absent from the output set.
- merge_zones.py judges success as maximal-fraction >= --target -> a
  correct bow+hull outcome (two components, both saturated) reads as
  FAILURE and drives pointless ladder escalation; the "no attempt
  reached target" exit is wrong for disjoint features.
- GenerateModel runs on one selected/maximal component -> the bow
  never gets a model.
Confirmed SAFE (containment-only, feature-preserving): grow_zone
cleanup_stale; component_analysis twin drop (kept-union coverage — a
feature component always has unique images); AlignZone
exportLatestComponents (exports ALL comps >= min_size; keep min_size
well below the smallest plausible feature).

1. D7 on smoke BEFORE production merge_v2 (which merge attempt is
   trustworthy).
2. Merge-driver rework (merge_zones.py + MergeZoneComponents.bat),
   feature-aware: deliverable = saved .rsproj containing ALL surviving
   components, every one exported + censused (not maximal-only);
   success/termination = convergence ("no fusable candidate pairs
   remain" via manifest border-gating from component_analysis, and no
   pass gained), NOT a maximal-fraction target — retire --target as
   the success gate, keep it only as an informational stat; add
   input-union shrink accounting (align-mode attempts can shrink and
   still "pass" today); terminal state "EVALUATION READY" with report
   (per-component members/counts/bboxes/twin decisions/orphans/georef
   check) then owner gate or --auto_model (EOF-safe). Ladder attempts
   that cannot help disjoint features must not run against them
   (border-gate the escalation, don't brute-force it).
3. Port AlignZone's successive-difference identity harvest to a dated
   COPY of the final merge project (merged-stage exports are ordinal =
   count-only today; the evaluation gate and feature accounting need
   per-component membership).
4. Final orphan-pickup growth pass in the merged project (add all
   images + union log + align under checkpoint/invariant) — merge
   never adds images; cross-zone context is what rescued zone_14's;
   for feature components this is exactly per-feature "as big as it
   gets".
5. Fix GrowZone re-enable-all-before-save; CHECK zone_1 scene for
   the disabled-images state (gates "keep final zone projects").
6. Manifest<->scene name correlation by image set (selectComponent
   no-ops on renamed-manifest names — becomes must-fix once
   merge-scene deletion is in the loop).
7. grow_zone: consider accepting zero-gain passes that REDUCE
   component count (consolidation serves merging; invariant otherwise
   unchanged — never-shrink stays the automated default).
8. GenerateModel: per-component model generation driven from the
   evaluation gate (owner selects which surviving components get
   models, or all >= min size on auto-proceed).
9. HYPOTHESIS to verify (then promote to FINDINGS): -align fuses via
   image CONTENT (duplicated overlap frames match visually without
   path identity), unlike -mergeComponents which needs path identity —
   would make attempt-2 align_rematch the mechanistically sound rung
   for duplicate-path zones and argue for inverting the attempt
   ladder. NA167 D3 is not a counterexample (zero content overlap).
10. FUTURE: optional feature tagging at the evaluation gate (owner
   labels components "bow"/"hull"/etc. in the report; manifests carry
   the label forward into model naming) — cheap, makes per-feature
   accounting explicit across sessions.

## 2026-07-24 (earlier) H2023 SESSION END STATE

**Zone_1 growth completed after this was written — final: 4,429/4,540
(97.6%), all re-solve passes rolled back (see FINDINGS). Details below
kept for workspace paths and commands.**

**Where H2023 processing stands (workspace D:\na156_h2023):**
- Zone aligns DONE with manifests + RC_projects daily saves:
  zone_1 = 4,392 registered / 9 components (nondeterministic
  fragmentation - see FINDINGS; first run gave 2 components, same
  registration); zone_2 = 928/976 (95.1%) / 3 components.
- Within-zone growth: zone_2 DONE (clean run, zero real gains - the 48
  orphans are genuinely unregistrable; 3 components remain by design,
  northern strip is visually disjoint). zone_1 growth was IN FLIGHT at
  session end (grow_zone.py, output D:\na156_h2023\growth\zone_1,
  report grow_report.json when done; scene checkpoints under
  growth\zone_1\checkpoints - "initial" restores the pre-growth scene
  if anything went wrong).
- NEXT STEPS in order: (1) check zone_1 grow_report.json; (2) cross-zone
  merge: py -3.13 merge_zones.py --components_root
  D:/na156_h2023/aligned_components --images_root
  D:/na156_h2023/batched_images_by_zone --output D:/na156_h2023/merged_v2
  --name H2023_Merged --min_size 50 --target 0.83 --project_label
  NA156_H2023  (twin resolution via manifests is automatic; union
  flight log + -update georeference the merged component - VERIFY
  georeferencing in the GUI, U7 automation still open); (3) model:
  GenerateModel.bat on the merged .rsproj (owner recipe baked in;
  simplify presets are placeholders - see plan self-audit).
- The old non-georeferenced merge outputs live at D:\na156_h2023\merged
  (reference only). Smoke fixtures at D:\na156_h2023\smoke_test.

**Known open items:**
- GrowZone export mode cannot rebuild identity manifests (in-session
  harvest only exists in AlignZone.bat) - post-growth manifests are
  approximate; rebuild identity by re-running AlignZone.bat OR accept
  approximate until the merge (merge twin-resolution treats
  approximate manifests conservatively).
- grow_zone report's components dict lists stale export paths
  (cosmetic).
- Determinism test queued: third zone_1 align to confirm fragmentation
  nondeterminism (FINDINGS) - run when GPU is free.
- Hardening cells open: U4-U14, U17 (see plan STATUS UPDATE);
  U7 (CLI-observable georeferencing check) matters most for merge
  automation.
- selectImage regexp/glob discrepancy vs Help - forum-mine follow-up.
- Clean-sweep code review findings (three review agents, 2026-07-24):
  triaged into the sections below / applied where safe - check git log.
- Claude Skill + documentation guide (task queued): FINDINGS.md is the
  fact base, docs/ the rationale base.

**Review backlog (2026-07-24 clean-sweep; applied items in FINDINGS):**
MUST-FIX BEFORE NEXT MERGE/MODEL RUN:
- MergeZoneComponents.bat complist-validation `exit /b 1` inside a
  multi-statement block returns 0 (hoist to a subroutine/goto flow).
- grow_zone <-> merge handoff: merge_zones cannot consume
  grow_report.json's scattered final exports - build a .complist from
  the report (or merge the PRE-growth aligned_components when growth
  gained nothing, which is the H2023 zone_2 case).
- GrowZone.bat component-mode saves the scene with most images
  DISABLED (inpEnabled=false persists) - re-enable all before save, and
  CHECK the zone_1 scene after its growth run for this state.
SHOULD-FIX:
- Manifest component names vs in-scene names never match (scene saved
  pre-rename): cleanup_stale selectComponent silently no-ops; key
  correlation by image set instead. AlignImageList/SequentialAlignGrow:
  no AlignmentParams application, no deselect before exports.
  startRealityScan timeout exit-code shape; PowerShell harvest line in
  AlignZone.bat unchecked; :try_delete_model wait shape;
  identity-loop 20-cap absorbs remainder into the last manifest.
NITS: stale AlignImagesFromFolder rationale pointers; pre-B10 comments
in camera_registry/component_manifest; ProbeSubsetAlign headers need a
SUPERSEDED note; MergeZoneComponents delayedexpansion flag; kv colon
replace-all; dead component_manifest helpers (scan_pose_sidecars +
members_from_sidecars now only used by realityscan_interface - verify
before deleting); merge_zones ascii complist crash path.

## 2026-07-23 NA156 H2023 session: settings evaluation + workflow consolidation

Full rationale: `docs/settings-evaluation-2026-07.md`. Summary:

- **Camera registry** (`modules/camera_registry.py`): four physical
  cameras (Zeuss rect 23mm / Port fisheye 14mm / Cinema rect 17mm /
  Starboard fisheye 14mm; owner-confirmed), per-camera calibration/lens
  groups, calibration-only XMP content, pose-sidecar sanitize+census.
  The WCA rendered JPGs are EXIF-identical — XMP groups are the ONLY way
  RealityScan can separate the cameras. Old batcher values (camlower as
  "12mm fisheye") were wrong and plausibly explain the earlier
  "priors hurt" A/B.
- **Workflow consolidation**: `AlignZone.bat` (per-zone canonical:
  always applies AlignmentParams.xml, appIncSubdirs=true, exports ALL
  components >= min size via -exportLatestComponents, XMP census, no
  models) + `merge_zones.py`/`MergeZoneComponents.bat` (iterative merge,
  escalating georef-merge → align+rematch → +High overlap) +
  `GenerateModel.bat` (models once, on the merged component).
  `AlignZonesSequentially.bat` retired to archive/legacy_scripts;
  `AlignImagesFromFolder.bat` deprecated (kept for run_zone9_tests.py).
- **Settings changes**: sfmDistortionModel Division→Brown3 (global
  fallback; real models per-camera via XMP), sfmImagesOverlap
  Low→Medium. sfmEnableCameraPrior=true IS the GUI "use camera priors
  for georeferencing"; sfmMergeGeoreferencedComponents is the
  component-level no-overlap merge flag — they compose.
- **New CLI facts**: B10 (ordinal XMP exports from imported-component
  scenes), B11 (-setFeatureSource/-selectImage regexp ARE CLI;
  -exportLatestComponents; -selectComponentWithLeastReprojectionError).
  This 2.2 build does NOT recurse -addFolder without appIncSubdirs=true
  ("Added 0 layer images" → err:18002 cascade).
- **Smoke-verified end to end** (NA156 H2023 subsets): mini_a 118/120
  registered, mini_b 62/120, georef -mergeComponents fused both into one
  180-camera component in 66 s (supports matrix cell D1). Orchestrator
  now stops on module failure; alignment module aggregates per-zone
  success; overwrite prompts removed from the unattended path.
- **NA156 H2023 state**: 4,598 Port+Cinema images at
  D:\na156_h2023\raw_images (Starboard excluded by owner instruction),
  georeferenced 100%, CLAHE'd, batched into zone_1 (4,540) + zone_2
  (976) — NOTE batched BEFORE the calibration-XMP work: re-run Batch
  Directory with --b_xmp_priors true (or write sidecars into the zone
  folders) before the production zone aligns.

## 2026-07-22 fix pass + NA167 end-to-end verification

A full-code review found and fixed (all verified by a 47-check synthetic
suite plus a live NA167_H2075 run — see `git log` for the commit):

- **Chaining was broken**: alignment read `batched_images` while the
  batcher wrote `batched_images_by_zone`, and every stage expected
  `flight_log.txt` while producers write `flight_log_<zone>_UTM.txt`.
  All discovery now goes through `modules/flight_logs.find_flight_log`.
- **Extractor timestamps were one interval early** (60 s at 1 fpm): the
  frame read and the frame timestamped were different frames. Any
  dataset extracted with the old `__extract_video_cv2` carries that
  offset — re-extract before trusting its georeferencing.
- **`FlightLogParams.xml` is now auto-generated per run** from the zone
  tag in the flight-log filename (`flight_log_53N_UTM.txt` →
  EPSG:32653). Never hand-edit the template's zone again.
- **XMP calibration priors never loaded**: they were written as
  `image.jpg.xmp`; RealityScan only reads `image.xmp`. Naming fixed,
  but generation is now **opt-in** (`batch_xmp_priors`, default off) —
  an NA167 zone_13 A/B measured the current prior content *reducing*
  registration (96.3% → 89.6% on Zeuss). Validate per-rig first.
- **Per-camera zone subfolders were aligned as separate scenes**,
  defeating mixed-camera co-registration. `-addFolder` recurses
  (verified live), so a zone tree is now one alignment scene.
- Plus: georeference image check is header-only (full `.verify()` was
  ~720 GB of reads on NA167), binary-search nav matching, batcher file
  indexing (O(N·M) → one walk), geoall prefers `*final_datatable.csv`,
  PNG support in both georeferencers, warn-once unknown-camera handling,
  PID-exact lock liveness, contiguous match-delta buckets, CRLF-safe
  prompts, tabs→4-space everywhere.

**NA167_H2075 verification** (D:\na167_h2075, WCA U*/C* stills + Zeuss):
29,620 images georeferenced in ~5 min (18,944 matched ≤2 s; the 10.4k
out-of-dive-window WCA files correctly rejected — the legacy
`flight_log.txt` had clamped those to garbage). 18 zones @ target 1000
built in 6.6 min. zone_13 (34 wca + 904 zeuss, one scene) aligned
93.4% registered in 11.5 min on GPU 0, flight log + auto-generated 53N
CRS imported clean, verified shutdown. Basename flight logs match
images in camera subfolders.

This repo was created on 2026-07-21 from `wild-technology/RC_Main`
(branch `claude/realityscan-repo-cleanup-2gjmu5`, full history preserved).
That branch also still exists on RC_Main; no pull request was opened
there. Treat this repo as the single source of truth going forward.

## What the overhaul did

Four commits on top of the old `main_v2`-era code:

1. **Archive COLMAP** — `colmap_processor.py` and the three
   `vocabtrainer_*` variants moved to `archive/colmap/` (see its README).
   No splatting scripts existed.
2. **Unify RealityScan CLI execution + rename** — everything renamed
   RealityCapture → RealityScan (module dir, `RS_CLI`, `RSModule`,
   `RealityScanAlignment`, instance `RS1`, `.rsproj` saves). New unified
   execution layer `modules/realityscan_interface/realityscan_cli.py`;
   batch workflows share one `:run` delegate/wait/error-check subroutine;
   legacy `RealityCapture*` `-set` keys replaced with the `app*` keys
   RealityScan 2.x actually uses. `rs_settings.json` prompt-default
   persistence added to `main.py` and all standalone scripts
   (`module_base/settings_store.py`).
3. **README + CLAUDE.md** for the 2.2 pipeline.
4. **Adversarial-review fixes** — an independent review pass found and
   fixed, among others: component detection that reported every
   successful run as a failure; unquoted `appProcessExecCmd` paths that
   silently disabled all error detection when the checkout path contains
   spaces; markers read before instance shutdown (missed late errors);
   `%ERRORLEVEL%` parse-time expansion breaking every interactive CHOICE
   prompt; per-instance namespacing of marker files for multi-GPU.

Design rules live in `CLAUDE.md` (hard rules) and `README.md`
(architecture + lessons learned). Read both before touching execution
code.

## Verification status

Full write-up of what changed and why:
[`docs/code-review-2026-07.md`](docs/code-review-2026-07.md).

**2026-07-21: first real-machine run completed on the Windows dual-5090
box** via `testing/run_zone9_tests.py` (phases 0–1, from both a normal
checkout path and one containing spaces). Checklist outcomes:

1. **Smoke test small** — DONE. 32-image smoke passes end to end
   (boot → addFolder → importFlightLog → align → select/rename →
   exportXMPForSelectedComponent → exportSelectedComponentDir → save →
   verified shutdown), 17/32 registered on a contiguous subset.
2. **Process trigger fires** — VERIFIED, including from a checkout path
   with spaces. Several real bugs were found and fixed on the way:
   - `RealityScanCLI` now invokes the .bat by absolute path *without*
     `cmd /c` (bare names break under `NoDefaultCurrentDirectoryInExePath`
     environments like Git Bash; a self-built `cmd /c "path with
     spaces.bat"` line gets its quotes stripped by cmd).
   - The `:run` line-count used bare `find`, which resolves to GNU find
     when launched from Git Bash (scans the whole disk); now fully
     qualified as `%SystemRoot%\System32\find.exe`.
   - **The results-log-growth completion check was removed entirely**:
     RealityScan 2.2 emits periodic internal heartbeat processes through
     the same `appProcessExecCmd` trigger, so "the log grew" does not
     mean "our command finished" — it raced ahead of a running `-align`.
     `:run` now does delegate → grace → double `-waitCompleted`.
   - `-mergeComponents` is a no-op with a single component and its async
     re-reconstruction can clear the selection; replaced with
     `-selectMaximalComponent`.
   - `-exportXMP` only covers "the last alignment" and silently skips
     components below `setMinComponentSize` (default 5); replaced with
     `-setMinComponentSize 1` + `-exportXMPForSelectedComponent`.
3. **`-align "%AlignmentParams%"`** — CONFIRMED NOT SUPPORTED. `-align`
   takes no parameters in 2.x (local Help `allcommands.htm` + online
   docs). `AlignZonesSequentially.bat` now parses the sfm*/lis* keys out
   of `AlignmentParams.xml` and applies them via delegated `-set`
   commands before a plain `-align`.
4. **Process result code 1** — benign in practice: routine successful
   operations (e.g. `-addFolder`) report result 1 through the trigger
   while real failures report distinct codes (0x820000FF warning-class,
   0x80070057 E_INVALIDARG). Whitelist of 0/1 kept.
5. **Shutdown timing** — verified on small scenes only; the 15-min bound
   on very large scenes is still untested.
6. **Multi-GPU parallel instances** — still untested. Single-instance GPU
   pinning via `rs_settings.json` `"gpu_devices"` exercised during the
   phase-2 test runs.
7. **Autosave keys** — no stale autosaves observed in any test run.

Other findings from the first runs:

- `FlightLogParams.xml` declared UTM zone 4N (EPSG:32604) from an earlier
  project; the NA173_H2103a flight logs are zone **57S** (EPSG:32757,
  southern hemisphere). Fixed. Check this per-cruise before importing.
- `-importFlightLog` reports a failed process (err:18002, 0x820000FF)
  when the log references images that are not in the scene — even though
  the trajectory itself imports fine. When aligning subsets, filter the
  flight log to the images actually present (the zone_9 runner does).
- `-exportRegistration` without a params XML blocks forever headless —
  avoid it until a params file saved from the GUI dialog exists.

## PENDING RECONCILIATION with LilyJean/COLMAP findings (filed 2026-07-23)

The LilyJean fact base (`C:\Users\jonat\Desktop\CoyoteThings\itsmagicIswear\FINDINGS.md`, 34 dated/
sourced entries) reached the OPPOSITE preprocessing verdict from this pipeline:
on 3,607 LilyJean stereo pairs, both adaptive enhancement and fixed backscatter
subtraction reduced COLMAP registration ~30% vs originals (F-20260721-02,
F-20260723-01) — while this repo's CLAHE 2.0/8×8 pre-alignment default is
validated on zone_9 where the baseline aligns to NOTHING (recorded there as
counter-evidence F-20260723-33). Both results are real; scope is unresolved.

When the colmap-studio research completes, run the reconciliation matrix (Q-05):
zone_9 {baseline, CLAHE} × COLMAP, and LilyJean {originals, CLAHE} × this
pipeline's RealityScan alignment, judged on REGISTRATION (not keypoints —
F-20260723-03). Outcome decides whether preprocess_images stays default-on,
becomes per-dataset, or moves to texture-only.

Also relevant from that fact base for this repo:
- RealityScan Image Layers (`.geometry`/`.texture`/`.mask`, F-20260723-23) are
  the official mechanism for "originals align, corrected images texture" — the
  reconciling architecture if CLAHE ends up texture-only.
- Staff caution against over-masking (F-20260723-31) and Ultra detector
  sensitivity manufacturing noise points (F-20260723-26) — relevant to
  `masking.py` and AlignmentParams choices on turbid imagery.
- No stereo-rig support in RealityScan (staff-confirmed through Aug 2025,
  F-20260723-27): Voyis-rig scale must come from GCPs/distance constraints/
  locked XMP — consistent with this repo's per-rig XMP-priors caution (the
  NA167 zone_13 A/B where priors cost 6.7 points of registration is recorded
  as F-20260723-34).

## Known loose ends

- `geoall.py` (canonical) and `modules/georeference/georeference_images.py`
  still duplicate the georeferencing workflow — port improvements into
  the module when it next changes (CLAUDE.md hard rule 6).
- The overwrite prompts in `realityscan_interface.py` use `input()` and
  can stall an unattended pipeline mid-run; consider a `--force`
  parameter if runs go fully unattended.
- `rs_settings.json` is per-machine and gitignored; nothing migrates old
  hardcoded paths — first run on a new machine prompts from the baked-in
  fallbacks.

## Session provenance

Overhaul performed by Claude Code (session linked in the commit
trailers), including web-verified RealityScan 2.2 CLI semantics
(`-delegateTo` queueing, `-waitCompleted` pickup race, `-getStatus`
errorlevel contract, `appProcessAction` triggers, exit codes 0/1/3).
