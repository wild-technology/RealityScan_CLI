# Alignment: settings, parameters, behavior, tuning

This document covers the RealityScan 2.2 alignment (structure-from-motion) stage driven
from the command line: the `-align` / `-draft` / `-detectFeatures` / `-update` commands and
the rest of the master table's Alignment section, every
alignment-relevant `-set` key (`sfm*`, `lis*`) and its measured effect, the
`AlignmentParams.xml` profile this repository ships field by field, the per-image
alignment controls (`-editInputSelection` / `inp*`), how camera priors change the solve,
component control during alignment, and how to judge whether a solve is good. It does
**not** cover: the general `-set` mechanism and the full application-wide key inventory
(see `03-settings-keys.md`); the general params-XML mechanism, GUIDs, and how to author
one from a GUI dialog (see `09-xml-parameter-files.md`); flight-log formats, CRS/EPSG
selection and georeferencing arithmetic (see `06-georeferencing-flightlogs-and-scale.md`);
component merging, `-mergeComponents`, `.complist` handling, cluster gating and fusion
arithmetic (see `08-components-and-merge.md`); meshing, texturing and export (see
`10-reconstruction-texturing-export.md`); camera rigs, distortion models and rotation
conventions (see `13-camera-rigs-priors-and-orientation.md`); the execution layer and
error markers (see `01-cli-fundamentals.md`, `11-automation-patterns.md`,
`12-failure-modes-and-race-conditions.md`). Alignment settings that only matter to merging
are named here and cross-referenced there.

**Applies to:** RealityScan 2.2 (Epic Games), Windows, headless CLI operation.
**Tags:** [OFFICIAL] shipped Help · [VERIFIED] measured in production here ·
[CONTRADICTED] docs vs observation · [UNDOCUMENTED] · [INFERRED] · [OPEN]

Build under discussion: `RealityScan.exe` FileVersion `2.2.0.119430.RS`, installed at
`C:\Program Files\Epic Games\RealityScan_2.2\`.

**Citation note.** `testing/NA167_SESSION_NOTES.md` numbers its bug findings twice over:
there are two entries labelled **B10** (one INT — LF-only `.bat` files break `call :label`;
one RS — ordinal XMP sidecars from an imported-component scene) and two labelled **B11**
(one INT — `-setMinComponentSize` deprecation warning + in-place import timing; one RS —
the feature-source trio is CLI-accessible). Citations below say which one is meant when it
is not obvious from context. [VERIFIED-by-inspection: `testing/NA167_SESSION_NOTES.md`
§2, read 2026-08-04]

---

## Contents

1. [The alignment commands](#1-the-alignment-commands)
2. [Applying alignment settings: `-align` takes no parameter file](#2-applying-alignment-settings--align-takes-no-parameter-file)
3. [The `sfm*` / `lis*` settings reference](#3-the-sfm--lis-settings-reference)
4. [`AlignmentParams.xml` field by field](#4-alignmentparamsxml-field-by-field)
5. [Per-image alignment controls (`-editInputSelection`, `inp*`)](#5-per-image-alignment-controls--editinputselection-inp)
6. [Priors and alignment: measured effects](#6-priors-and-alignment-measured-effects)
7. [Behavior: what alignment actually does at production scale](#7-behavior-what-alignment-actually-does-at-production-scale)
8. [Failure modes and workarounds](#8-failure-modes-and-workarounds)
9. [Component control during alignment](#9-component-control-during-alignment)
10. [Quality assessment: what numbers mean a bad solve](#10-quality-assessment-what-numbers-mean-a-bad-solve)
11. [Tuning playbook](#11-tuning-playbook)
12. [Complete runnable examples](#12-complete-runnable-examples)
13. [Open questions](#13-open-questions)

---

## 1. The alignment commands

### 1.1 Inventory

Every command in this table is from the Alignment section of the master command table
[OFFICIAL: appbasics/allcommands]. The `algId` values are the process ids that appear in
`-writeProgress` output [OFFICIAL: tutorials/processids].

| Command | Params | Official description (compressed) | `algId` |
|---|---|---|---|
| `-align` | none | "Align images using the current settings." | `65537 ALIGN_NORMAL`; sub-phases `65539 SFM_FEATURES_DETECTION`, `77824 SFM_MATCHING`, `77840 SFM_ALIGNMENT_MAIN` |
| `-draft` | none | "Align images in the draft mode using the current settings." | `65538 ALIGN_DRAFT` |
| `-detectFeatures` | none | "Run feature detection according to the alignment settings. Detected features will be saved in the application cache." | `65539 SFM_FEATURES_DETECTION` |
| `-update` | none | "Update all components and models by a rigid transformation to fit the actual constraints and control points." | `65542 UPDATE_CONSTRAINTS` |
| `-mergeComponents` | none | "Merge already created components. When using this command, no new images are added to the existing components." | — |
| `-setMinComponentSize` | `size` | Minimum component size for `-exportLatestComponents` and `-exportXMP`. Default `5`. | — |
| `-setCamerasGravityDirection` | `[componentID]` | If images' XMP carries `xcr:Gravity`, rotate the component so `-z` follows gravity. Sparse cloud only. | — |

**There is no `-alignImages` command in 2.2.** The GUI button is labelled "Align Images
(F6)" but the CLI verb is `-align`. A full sweep of the master command table plus every
Help page that mentions a command found no `alignImages`, `alignAll`, or
`alignSelected` spelling [VERIFIED: exhaustive command inventory, SURVEY_commands.md;
cross-checked against appbasics/allcommands].

**Legacy command names appear in Epic's own alignment examples and do not exist in the
2.2 master table**: `tutorials/commandline_1` uses `-exportComponent %MyPath%\max` and
`-minComponentSize 5`. The live 2.2 names are `-exportSelectedComponentDir` /
`-exportSelectedComponentFile` / `-exportLatestComponents` and `-setMinComponentSize`.
[CONTRADICTED: tutorials/commandline_1 examples (lines confirmed verbatim: `RealityScan.exe
-load %MyPath%\AlignedProject.rsproj -selectMaximalComponent -exportComponent %MyPath%\max
-quit` and `… -minComponentSize 5 -exportComponent %MyPath%\ …`) vs appbasics/allcommands
master table in the same Help build] [INFERRED: the example pages are stale; the master
table is authoritative — untested because the repo never invoked the legacy spellings.]

### 1.1b Alignment-section commands not otherwise covered here

These are in the same **Alignment** table of the master command list and are alignment-stage
commands, but this repository has never invoked any of them. Listed so the inventory is
complete; none is [VERIFIED]. [OFFICIAL: appbasics/allcommands]

| Command | Params | Official description (compressed) | Note |
|---|---|---|---|
| `-loadBundler` | `filePath` `[params.xml]` | Import a Bundler project; optional config file defines scene transformation / coordinate system on import. | An **alternative to running `-align`**: an externally-solved SfM result can be brought in instead of solving here. [OPEN: never tried.] |
| `-loadColmap` | `filePath` `[params.xml]` | Import a COLMAP project (path to any of the three text files); same optional transform config. | Same. Note `archive/colmap/` in this repo is retired and must not be resurrected (CLAUDE.md). |
| `-exportSparsePointCloud` | `fileName` `[params.xml]` | Export the 3D tie points (sparse cloud) to a file; settings exportable from the Export Point Cloud dialog. | The only CLI route to the alignment's own point cloud; relevant to §10. |
| `-exportRegistration` | `fileName` `[params.xml]` | Export registration using current settings or a params XML. | [VERIFIED: **blocks forever headless when the params XML is omitted** — FINDINGS 2026-07-21.] |
| `-exportUndistortedImages` | `folderName` `[params.xml]` | Export undistorted images. | Consumes the solved distortion model (§3.9). |
| `-exportSTMap` | `folderName params.xml` | Export ST maps for the selected images; without arguments results land beside the originals. | — |
| `-detectMarkers` | `[params.xml]` | Detect markers in images using current settings or a params XML from the Detect Markers tool. | The coded-target route into control points; unused here (no targets underwater). |
| `-importGroundControlPoints` | `gcpFileName` `[params.xml]` | Import GCPs. | Consumer of `sfmControlPoint*Accuracy` (§3.3). |
| `-importControlPointsMeasurements` | `cpmFileName` `[params.xml]` | Import CP image measurements. | Consumer of `sfmControPointImageMeasAccuracy` (§3.3). |
| `-editControlPointSelection` | `"key=value"` | Edit Selected-control-point(s) settings by key (`gp*` keys). | Same `key=value` quoting hazard as §2.3. |
| `-editConstraintSelection` | `"key=value"` | Edit Selected-constraint(s) settings by key (`c*` keys, incl. `cValue1Acc`). | Consumer of `sfmDefinedDistanceAccuracy` (§3.3). |
| `-defineDistance` | `PointNameA PointNameB distance` `[constraintName]`, **or** `fileName` `[params.xml]` | Define a distance constraint between two control points, or import definitions from a file (supported formats: `distancedefinitions.xml` in the install folder). | The scale-constraint route; the alternative to trusting nav for metric scale (§10.5). |
| `-selectMeasurementByError` | `errorValue` `[controlPointName]` | Select any CP measurement with position error ≥ `errorValue` px. | The one built-in error-thresholded selector in the alignment section. |
| `-listControlPoints` | `fileName` | Write the control-point list (each with its index) to a file. | One of very few CLI commands that emit *readable* scene state. |

### 1.2 `-align` — the complete behavioral contract

- **It takes no arguments.** See §2.
- **It runs feature detection itself** when features are not already cached. The
  RealityScan log of a bare `-align` shows `Detected N features in image '<file>'` lines
  for every input, then a matching phase, then reconstruction
  [VERIFIED-by-inspection: `testing/results/z14_forensic_rslog.txt`, a 1,476-image align
  captured end to end]. `-detectFeatures` exists to do only that step and cache the
  result [OFFICIAL: appbasics/allcommands]; the repo has never used it
  [VERIFIED-by-inspection: no `-detectFeatures` in `RS_CLI/Scripts/*.bat`].
- **It honours per-image enable/disable exactly.** With `inpEnabled=false` on a
  selection, those images do not participate [VERIFIED: FINDINGS 2026-07-23, cell U2].
- **It consumes XMP sidecars that were auto-imported when the images were added** —
  including pose sidecars left behind by a previous `-exportXMP`, which silently become
  exact-pose priors. See §6.5.
- **It is the only operation that can register new images.** `-mergeComponents`
  explicitly adds none [OFFICIAL: appbasics/allcommands, tutorials/mergecomponents], so a
  scene containing unregistered orphans can only pick them up through `-align`
  [VERIFIED-as-consequence: FINDINGS 2026-07-27].
- **It is not bounded by any timeout in this pipeline.** 10+ hour aligns are normal. The
  only bounded waits are instance **startup** — `startRealityScan.bat` polls `-getStatus`
  and gives up after 120 tries at ~1 s (`did not become ready within 120 seconds`) — and
  **shutdown verification**, `SHUTDOWN_VERIFY_TIMEOUT_SECONDS = 900` in
  `realityscan_cli.py`, overridable through `rs_settings.json`
  `realityscan` / `shutdown_timeout`.
  [VERIFIED-by-inspection: `RS_CLI/Scripts/startRealityScan.bat`,
  `modules/realityscan_interface/realityscan_cli.py` lines 189–297, read 2026-08-04]
  [CONTRADICTED-internally: CLAUDE.md hard rule 3 still says the shutdown bound is 300 s;
  the code says 900 s. The code is the artifact that runs.]

### 1.3 align vs align/update semantics when components already exist

With one or more components already in the scene, `-align` behaves as **align/update**:

- it adds newly-added images to existing components;
- it can **fuse** existing components when it finds cross-component ties;
- it **re-optimizes** everything, which means it can also **shrink** components.

[VERIFIED: NA167_SESSION_NOTES §`-align`; corroborated by the D7 probe wave and by every
growth pass in `grow_zone.py`]

Consequences that bite in automation:

| Consequence | Evidence |
|---|---|
| A "free" re-align is never pose-stable: it moved **all 118** cameras of an already-solved 120-image smoke scene. | [VERIFIED: FINDINGS 2026-07-23, cell U18 bonus] |
| A re-align routinely drops **1–2 marginal cameras**. Larger losses happen: H2023 hull 3,860 → 3,855; zone_1 component c7's growth pass lost **51** previously-registered images. | [VERIFIED: FINDINGS 2026-07-23/24] |
| A growth pass is an align/update that refreshes **every** component, not just the one you targeted — so a per-component before/after census produces phantom gains. Judge gains against the **zone-level** census. | [VERIFIED: FINDINGS 2026-07-24] |
| Growth outcomes are **not order- or subset-invariant**: a z6→z14 two-zone grow fragmented to an 870-camera maximal (worse than z6's 1,533 solo), while a three-zone grow through the same stages held 3,906. | [VERIFIED: NA167 #29, 2026-07-24] |
| Therefore any driver that re-aligns must checkpoint the `.rsproj` bundle first and be able to roll back. Component re-import is **not** a valid rollback: importing components into a fresh scene does not bring the images that are in no component. | [VERIFIED: FINDINGS 2026-07-23/24; `grow_zone.py` docstring] |

Epic's own sanctioned repair round trip depends on this update semantics: export the
faulty component → import it into a spare scene → fix it (control points, more images,
constraints) → import it back → "press the Align Images button again. RealityScan engine
will apply fixes from the corrected component" [OFFICIAL: appbasics/components].

### 1.4 `-draft`

Draft alignment estimates poses of all inputs quickly, trading quality for speed
[OFFICIAL: tutorials/draftalign]. It is driven by its own three settings, which are
separate keys from the normal-mode ones:

| Key | Default | Repo value |
|---|---|---|
| `sfmImagesOverlapDraftMode` | `Medium` | `Medium` |
| `sfmImageDownscaleFactorDraftMode` | `2` | `2` |
| `sfmFinalModelOptimizationDraftMode` | `false` | `false` |

[OFFICIAL: tutorials/setkeyvaluetable] + [VERIFIED-by-inspection: `AlignmentParams.xml`]

"Final model optimization Enable/disable a global scene optimization. It is not
necessary for model previews, but it is strongly recommended for high-precision models."
[OFFICIAL: tutorials/draftalign] — `appbasics/alignsettings` states the same key
differently: "When set to Yes, a final bundle adjustment is performed to optimize camera
registration." Both descriptions are of `sfmFinalModelOptimizationDraftMode`; nothing in
the Help says what the **non-draft** counterpart `sfmFinalModelOptimization` does or what
its default is (§4.4).

The two Help pages also describe `sfmImagesOverlapDraftMode` in opposite directions —
`tutorials/draftalign`: "A bigger overlap setting improves speed but may cause disconnected
components if there are no enough images"; `appbasics/alignsettings` (Draft block):
"Defines how many common features are expected between images … Low indicates minimal
overlap and High indicates the greatest overlap." This is the same unresolved question as
§3.6, restated for the draft key.

Epic's own CLI example of a draft-then-normal chain [OFFICIAL: tutorials/commandline_1]:

```bat
RealityScan.exe -addFolder %MyPath%\Images\ -save %MyPath%\MyProject.rsproj -draft
RealityScan.exe -load %MyPath%\MyProject.rsproj -align .... -quit
```

(The literal `....` is Epic's own placeholder for further commands. Note the first line has
no `-quit`, so that process blocks until the application is closed — the pattern this
pipeline replaces with `-delegateTo` + double `-waitCompleted`.)

**`-draft` has never been run in this repository.** No workflow script invokes it and no
findings entry records a draft result. The three draft keys are pinned in
`AlignmentParams.xml` only so that the instance is never left in an unknown state.
[VERIFIED-by-inspection: `RS_CLI/Scripts/*.bat`] [OPEN: whether `-draft` is a useful
cheap oracle for "will this zone align at all" — see §13.]

### 1.5 `-update` is not alignment

`-update` fits **existing** components to the scene's constraints. Empirically it is a
similarity fit: it can rotate or rescale a component but cannot stiffen or repair its
geometry, and it does not register anything [VERIFIED: FINDINGS 2026-07-26, established
while diagnosing a 45° component tilt]. It is the step that **sets scale** on an
assembled scene, and therefore the step that will happily rotate geometry to satisfy
mis-composed orientation priors [VERIFIED: FINDINGS 2026-07-25 / 2026-07-27].

### 1.6 What `-align` reads at the moment it runs — preflight checklist

Everything below is scene or instance state, not an argument. Get any of it wrong and the
align "succeeds" with the wrong inputs.

```
1. appIncSubdirs=true        set BEFORE -addFolder, or subfolders are silently skipped
2. images present            -addFolder <dir> | -add <list.imagelist>
3. XMP sidecars beside them  auto-imported: calibration groups, focal, distortion, POSE
4. flight log imported       -importFlightLog <log> <FlightLogParams.xml>
5. every sfm*/lis* key       applied by -set (see §2); anything not set keeps the
                             instance's last value, which PERSISTS ACROSS RESTARTS
6. per-image state           inpEnabled / aligFeaturesMode / inpPose from earlier passes
                             persist in a loaded scene and into a save
7. selection                 flight-log import leaves images SELECTED; selection-driven
                             operations afterwards misfire (see §8.6)
```

[VERIFIED: assembled from `AlignZone.bat`, `GrowZone.bat`, and the findings cited in the
relevant sections below]

### 1.7 Progress and monitoring during an align

`-writeProgress <fileName> [<timeout>]` — **the optional second parameter is a period in
SECONDS, not milliseconds** ("during a defined period of time (timeout in seconds)")
[OFFICIAL: appbasics/allcommands, tutorials/commandline_5]. `startRealityScan.bat` passes
`600` [VERIFIED-by-inspection], and the value `600` is echoed back in the app log line
`Executing command 'writeProgress' with parameters '…\progress_RS1.txt 600'`
[VERIFIED-by-inspection: `testing/results/z14_forensic_rslog.txt` line 8].

The file has **five** whitespace-separated columns [OFFICIAL: tutorials/commandline_5]:

| # | Official name | Meaning |
|---|---|---|
| 1 | `algId` | process ID (the table in §1.1; full list in tutorials/processids) |
| 2 | `progress` | number in ⟨0,1⟩ indicating the stage of the process |
| 3 | `duration` | elapsed time in **seconds** |
| 4 | `estimation` | estimated remaining time in **seconds** |
| 5 | `eventType` | one of `#started` `#progress` `#timeout` `#completed` |

Epic's own sample rows: `20561 0.00 0.04 404.08 #started` … `20561 1.00 17.13 0.00
#completed` [OFFICIAL: tutorials/commandline_5].

So `#timeout` is a **documented event type**, not an undocumented anomaly. What is
empirical here is its *interpretation*. During a long align:

- `#timeout` in a progress line means the operation is internally stalled: column 3
  (`duration`) keeps ticking and column 4 (`estimation`) becomes garbage. Because every
  line then differs, naive line-change stall detection counts a 6-hour hang as activity
  [VERIFIED: NA167 #12 / B4].
- `#timeout` does **not** always mean hung. Heavy align phases legitimately freeze the
  fraction for 20+ minutes: a **successful** 94.6 % align emitted **40** `#timeout` lines.
  The pathological signature is `#timeout` from fraction `0.00` with an ever-growing ETA
  [VERIFIED: NA167 #28, 2026-07-24].
- A third cause is near-OOM: RealityScan slows to a crawl without crashing and without
  spilling to disk, and the progress feed cannot distinguish it. The repo's monitor
  samples available RAM and warns below `LOW_MEMORY_WARN_GB = 4.0`
  [VERIFIED: FINDINGS 2026-07-24; `realityscan_cli.py`].
- Adopted policy: **warn** on `#timeout` after `STALL_WARNING_SECONDS = 2*60*60`, never
  auto-kill an align [VERIFIED: `realityscan_cli.py`; NA167 #28].

---

## 2. Applying alignment settings: `-align` takes no parameter file

### 2.1 The rule

**`-align` accepts no `params.xml`. An XML path passed to it is silently ignored.** All
alignment configuration must be pushed as `-set "key=value"` **before** the align.

[CONTRADICTED: pre-2.x lore and this repo's own older scripts passed
`-align "%AlignmentParams%"` / observed: the argument has no effect; confirmed against
`appbasics/allcommands` (the align row has no parameter column entry) and against online
2.2 docs, 2026-07-21] [VERIFIED: FINDINGS 2026-07-21]

This is why `AlignmentParams.xml` exists as a *source of `-set` calls* rather than as a
command argument — see §4.

### 2.2 Ordering under delegation

Delegated commands queue FIFO and `-set` is instant, so a `-set` issued before a queued
`-align` is guaranteed to execute first. No `-waitCompleted` is needed between them
[VERIFIED: `AlignZone.bat` lines 71–88 + production runs].

```bat
%RealityScan% -delegateTo %RS_INSTANCE% -set "appIncSubdirs=true"
call :run -addFolder "%input_dir%"
```

### 2.3 The quoting hazard that silently disarmed every early experiment

`=` is a cmd token delimiter. An unquoted `key=value` reaching a `.bat` **as an argument**
is split into two arguments; RealityScan then logs
`Parsing setting key=value 'sfmMergeGeoreferencedComponents' failed [err:7155]` and
`'false' failed`, the setting is **never applied**, and — because the parse failure lands
in `errors.txt` — the workflow aborts on the next `:run` check.

Consequence recorded at the time: **no flag cell before NA167 wave 1f had ever applied its
flags.** [VERIFIED: NA167 #15 / B5, 2026-07-23]

Two mandatory mitigations:

1. Write `-set "key=value"` with the quotes inside the RealityScan invocation. Never pass
   the pair as a `.bat` argument.
2. When a pair must cross a `.bat` boundary, encode it `key:value` and convert inside the
   script:

```bat
:applySet
set "kv=%~1"
set "kv=%kv::==%"
%RealityScan% -delegateTo %RS_INSTANCE% -set "%kv%"
exit /b 0
```

[VERIFIED: `RS_CLI/Scripts/MergeZoneComponents.bat`]

### 2.4 Value encodings accepted by alignment keys

| Form | Example | Status |
|---|---|---|
| bool | `-set "sfmEnableCameraPrior=true"` | [OFFICIAL: tutorials/commandline_5] |
| decimal int | `-set "sfmPreselectorFeatures=20000"` | [OFFICIAL] |
| **hex int `0x…`** | `-set "sfmMaxFeaturesPerImage=0xc350"` (= 50000) | [UNDOCUMENTED] the GUI settings exporter writes ints in hex and `AlignZone.bat` replays them verbatim; production zone aligns completed with no `err:7155` |
| float | `-set "sfmMaxFeatureReprojectionError=1.29999995"` | [UNDOCUMENTED: same route] |
| enum by name | `-set "sfmDistortionModel=Brown3"` — Epic's own literal example line | [OFFICIAL: tutorials/commandline_4, "Examples of the Settings"] |
| enum by ordinal | Epic's own examples use ordinals for keys documented only by name (`unwrapStyle=1`, `appProcessAction=2`) | [OFFICIAL] for those two keys; [INFERRED] that `sfmImagesOverlap=1` ≡ `Medium` and `sfmDetectorSensitivity=3` ≡ `Ultra` — never tested. Settle by setting the ordinal and re-exporting the Alignment Settings panel. |

### 2.5 Silence is not success

Nothing in the CLI confirms that a key name was recognised. An unknown-but-parseable key
produces no error and no effect. The only observed failure signature is `err:7155`
(pair split by cmd), and `0x8000FFFF` is generic — a broken `-set` and a genuine align
failure emit the identical code, and the real reason line exists only in
`%LOCALAPPDATA%\Temp\RealityScan.log`, which is **truncated on every instance boot**.
Snapshot the log inside the driver immediately after the failing call returns.
[VERIFIED: NA167 B5, B6; FINDINGS 2026-07-23]

[OPEN: a positive read-back oracle for `-set`. Two candidate probes, both cheap:
(a) `-set "<key>=<value>"` then `-exportGlobalSettings "F:\tmp\after.rsconfig"` and diff
against a baseline export — note the extension is **`.rsconfig`**, and the paired importer
is `-importGlobalSettings settings.rsconfig` [OFFICIAL: tutorials/commandline_4];
(b) after an align, read `$ComponentSettings` out of a report (§10.3), which reports the
settings that were actually **in force for that component** rather than what the instance
currently holds — strictly the better oracle of the two, if `-exportReport` works headless.]

**`-preset "key=value"` is a different command from `-set`**: "Change an application
setting during the setup phase. Ideal for changes that require a reset of the application"
[OFFICIAL: tutorials/commandline_5]. No `sfm*` key is known to need it, and this repo has
never used it. [OPEN: whether any alignment key is `-preset`-only. General `-set`/`-preset`
mechanics live in `03-settings-keys.md`.]

### 2.6 The repo's replay loop, and the bug in it

`AlignZone.bat` and `GrowZone.bat` parse `AlignmentParams.xml` and replay each row:

```bat
for /f usebackq^ tokens^=2^,4^ delims^=^" %%A in ("%AlignmentParams%") do (
    echo %%A| %SystemRoot%\System32\findstr.exe /b /c:"sfm" /c:"lis" >nul
    if not errorlevel 1 %RealityScan% -delegateTo %RS_INSTANCE% -set "%%A=%%B"
)
```

[VERIFIED-by-inspection: `RS_CLI/Scripts/AlignZone.bat` lines 85–88, identical block in
`GrowZone.bat` lines 232–235]

Two properties of this loop that matter:

1. **The `sfm`/`lis` prefix filter drops the accuracy keys.** The GUI settings exporter
   writes `sfmCameraPriorAccuracyX/Y/Z` as `s235l`/`s236l`/`s237l` and
   `sfmControlPointXAccuracy/Y/Z` + `sfmDefinedDistanceAccuracy` as
   `s251l`/`s252l`/`s253l`/`s254l`. Those rows never match the filter, so **the intended
   non-default accuracies (5.0 / 5.0 / 0.5 m camera-prior, 0.001 defined-distance) have
   never been applied in production.** Every run used RealityScan's defaults
   `10.0 / 10.0 / 20.0` and `0.10`. This matters because prior *hardness*
   (`sfmCameraPriorWeight=10.0`) was chosen on the assumption that those accuracies
   bounded the trust envelope. [VERIFIED: code reading of `AlignZone.bat` +
   `AlignmentParams.xml`] Fix: emit the documented names explicitly, e.g.
   `-set "sfmCameraPriorAccuracyZ=0.5"`.
   *Caveat:* per-image accuracies imported from the flight log (`ifUsePosAcc=true`,
   `ifUseOriAcc=true`) set `inpPriorAccuracyInh=1` ("Edit custom values") per image, which
   overrides the global keys for those images. So the miss is scoped to images with no
   per-image accuracy. [INFERRED from `appbasics/camerasettings_priors` +
   `tutorials/editselectioncommand`; not isolated by a cell.]
2. **Keys absent from the file keep whatever the instance last had**, and swept `-set`
   values persist across instance restarts [VERIFIED: MERGE_TEST_PLAN §3 contamination
   controls]. Pin every key you depend on; do not rely on documented defaults.

---

## 3. The `sfm*` / `lis*` settings reference

GUI home: **ALIGNMENT tab → Registration → Settings** [OFFICIAL: appbasics/alignsettings].
Types, allowed values and defaults are [OFFICIAL: tutorials/setkeyvaluetable] unless the
row says otherwise. "Repo" = the value in `RS_CLI/Metadata/AlignmentParams.xml`, which is
what every production align has run with since 2026-07-25.

### 3.1 Feature detection and matching

| Key | Type | Default | Allowed | Repo | Meaning / measured effect |
|---|---|---|---|---|---|
| `sfmFeatureDetectionQuality` | enum | `High` | `High` `Normal` | `RealityScan.FeatureDetector.RSa1` | "Choose the quality level for detecting features in images. Setting it to High improves feature detection, resulting in a more precise alignment process, but increases processing time and RAM usage." [OFFICIAL: appbasics/alignsettings]. See the contradiction in §3.7. |
| `sfmMaxFeaturesPerMpx` | int | `10000` | any positive int | `0x36b0` (14000) | "Set the maximum number of features per megapixel … Using more features may slow processing but can result in less components." [OFFICIAL] Raised for low-texture seabed [VERIFIED-as-decision: docs/settings-evaluation-2026-07 §4]. |
| `sfmMaxFeaturesPerImage` | int | `40000` | any positive int | `0xc350` (50000) | Same idea, per image. The default is directly observable: an align run **without** the settings replay logged `Detected 40000 features in image '…'` for every one of 1,476 inputs [VERIFIED-by-inspection: `testing/results/z14_forensic_rslog.txt`]. |
| `sfmImagesOverlap` | enum | `Medium` | `Low` `Medium` `High` | `Medium` | See §3.6 — the direction of this control is genuinely unsettled. |
| `sfmImageDownscaleFactor` | int | `1` | `1`,`2`,`4`,… | `1` | "A multiplier by which the size of an image is reduced before feature detection. In order to get the best precision, use full image resolution (downscale factor 1)." [OFFICIAL] Never varied here [OPEN]. |
| `sfmMaxFeatureReprojectionError` | float | `2.0` | Epic: ≤ `3` px | `1.29999995` | "Internal precision level used during alignment. We recommend you to set it maximum to 3px." [OFFICIAL] Never A/B'd here. |
| `sfmPreselectorFeatures` | int | `10000` | any positive int | `0x4e20` (20000) | "This is the number of features that will be used in alignment from the detected ones. Optimally, set it to 1/4-1/2 of the detected features." [OFFICIAL] 20000 is 40 % of 50000 — above Epic's band. |
| `sfmDetectorSensitivity` | enum | `Medium` | `Low` `Medium` `High` `Ultra` | `Ultra` | "Higher sensitivity, like Ultra, allows detection of more features, even in areas with weak texture, but may also include less reliable points caused by image noise." [OFFICIAL] In force for all production aligns (weak underwater texture); the CLAHE A/B was validated at this setting [VERIFIED-as-in-use: docs/settings-evaluation-2026-07 §4]. A staff caution exists that Ultra manufactures noise points on turbid imagery [OFFICIAL-adjacent, second-hand, unverified here]. **No Ultra-vs-High A/B has ever been run on this rig** [OPEN]. |
| `sfmBackgroundDetectFeatures` | bool | — | `true` `false` | `false` | "Choose whether you want the system to automatically detect feature points in the background with a low priority of the processor." [OFFICIAL: appbasics/alignsettings prose] — the key name itself is [UNDOCUMENTED: present in `AlignmentParams.xml` and in the 2.2 binary; absent from the Help key table]. Pinned `false`: background detection competes with the foreground align for CPU and there is no interactive session to benefit. |
| `sfmBackgroundDetectThreadPriority` | enum | — | `Low` `Normal` | `Low` | "Priority of the background detection. You have the possibility to choose from low and normal." [OFFICIAL: prose] Key name [UNDOCUMENTED]. Inert while `sfmBackgroundDetectFeatures=false` [INFERRED]. |
| `sfmGPUAcceleration` | bool | — | `true` `false` | `true` | "Enable GPU usage to speed up the alignment process." [OFFICIAL: appbasics/alignsettings prose, "GPU acceleration" under Advanced] Key name [UNDOCUMENTED: `AlignmentParams.xml` + binary string sweep]. It is a **single on/off switch, not a device selector** [INFERRED from the bool type and the absence of any device-list key in the binary]; per-instance GPU selection is done by exporting `CUDA_VISIBLE_DEVICES` before boot, never by this key [VERIFIED-by-inspection: `startRealityScan.bat`, `RS_GPU_DEVICES` branch]. |

### 3.2 Camera priors

"Define the accuracy of initial camera positions and rotations, and their hardness — how
strongly they influence the alignment." [OFFICIAL: appbasics/alignsettings]

| Key | Type | Default | Repo | Applied in production? | Meaning |
|---|---|---|---|---|---|
| `sfmEnableCameraPrior` | bool | `true` | `true` | **yes** | GUI "Use camera priors for georeferencing". "When set to Yes, prior positions for the images are used in the alignment process **and** for georeferencing the scene." [OFFICIAL] Pose priors participate inside the bundle adjustment and make the resulting components georeferenced [VERIFIED: docs/settings-evaluation-2026-07 §4–§5]. Kept ON always. |
| `sfmCameraPriorAccuracyX` | float | `10.0` | `s235l=5.0` | **no** — filtered out, see §2.6 | "Specify the accuracy of the cameras' prior positions. It defines the range, in which the calculated positions are going to be considered as equal to the prior values." [OFFICIAL] |
| `sfmCameraPriorAccuracyY` | float | `10.0` | `s236l=5.0` | **no** | as above |
| `sfmCameraPriorAccuracyZ` | float | `20.0` | `s237l=0.5` | **no** | as above |
| `sfmCameraPriorWeight` | float | `1.0` | `10.0` | yes | "Position prior hardness … The greater the value, the closer the calculated positions are going to be to the prior positions. This may change the visual connections between cameras." [OFFICIAL] Kept at 10.0 as proven on this data class (NA167 zone_13, 93.4 %); documented fallback 1.0 if a zone under-registers, **never exercised** [VERIFIED-as-in-use: settings-evaluation §4] [OPEN: the weight has never been A/B'd]. |
| `sfmCameraPriorAccuracyYaw` | float | `10.0` | `10.0` | yes | "Yaw/Pitch/Roll accuracy … defines the range, in which the calculated orientations are going to be considered as equal to the prior values." [OFFICIAL] |
| `sfmCameraPriorAccuracyPitch` | float | `10.0` | `10.0` | yes | as above |
| `sfmCameraPriorAccuracyRoll` | float | `10.0` | `10.0` | yes | as above |
| `sfmCameraPriorWeightOrientation` | float | `1.0` | `10.0` | yes | "Orientation prior hardness …" [OFFICIAL] |
| `sfmCameraDepthmapWeight` | float | — | `0.05` | yes | [UNDOCUMENTED: present in `AlignmentParams.xml` and the 2.2 binary; no Help coverage and no identified GUI control]. What it weights is unknown. [OPEN] |

Note the units asymmetry: position accuracies are in **project CRS units** (metres here);
YPR accuracies are in **degrees** [OFFICIAL: appbasics/alignsettings "Units — The units of
the coordinate system in which the cameras' priors and their accuracies are displayed"].

### 3.3 Control-point priors

None of these has ever been exercised — **no GCP or control point has ever been imported
through this CLI** [OPEN: FINDINGS 2026-07-25 gap statement]. The commands that would
consume them (`-importGroundControlPoints`, `-importControlPointsMeasurements`,
`-editControlPointSelection`, `-defineDistance`, `-editConstraintSelection`) are listed in
§1.1b. `-defineDistance` matters beyond control points: it is the CLI's only route to an
explicit **scale constraint**, i.e. the one mechanism that would make the metric-scale
failure of §10.5 impossible rather than merely detectable.

| Key | Type | Default | Repo | Applied? | Meaning |
|---|---|---|---|---|---|
| `sfmControPointImageMeasAccuracy` *(Epic's spelling: no `l` in "Control")* | float | `2.0` | `4.0` | **yes** | "Image measurements accuracy [px] — A value that defines the deviations' range of the manually placed control points in the images." [OFFICIAL] The corrected spelling `sfmControlPointImageMeasAccuracy` does **not** exist in the 2.2 binary — the typo is load-bearing [VERIFIED: binary string sweep]. |
| `sfmControlPointXAccuracy` | float | `0.05` | `s251l=0.05` | no | GCP position accuracy per coordinate [OFFICIAL] |
| `sfmControlPointYAccuracy` | float | `0.05` | `s252l=0.05` | no | as above |
| `sfmControlPointZAccuracy` | float | `0.10` | `s253l=0.1` | no | as above |
| `sfmDefinedDistanceAccuracy` | float | `0.10` | `s254l=0.001` | no | "Set the value of the usual accuracy of distance constraint." [OFFICIAL] |

### 3.4 Draft mode

Covered in §1.4.

### 3.5 Advanced

"Advanced settings are intended for users familiar with structure-from-motion processing.
Do not change these settings unless you understand their impact." [OFFICIAL:
appbasics/alignsettings]

| Key | Type | Default | Repo | Meaning / measured |
|---|---|---|---|---|
| `sfmAutoReconRegionAfterAlignment` | bool | `true` | `false` | "Setting this to Yes will secure an automatic creation of the reconstruction region once the alignment has been finished." [OFFICIAL] Off here: the merge and model stages set the region explicitly. |
| `sfmEnableAutoSuggestions` | bool | — | `true` | "Here you can enable suggestions of image measurement in the 3Ds view when placing control points." [OFFICIAL: prose] Key name [UNDOCUMENTED]. Irrelevant headless; left at the exporter's value. |
| `sfmForceComponentRematch` | bool | `false` | `false` in pass-1 zone aligns; `true` on merge-ladder align rungs | "When set to Yes, the application realigns images and cameras to find better connections. It uses existing camera poses to search for new matches, potentially improving the quality of the final alignment." [OFFICIAL] A merge-stage tool — wasted per zone [VERIFIED-as-decision: settings-evaluation §4; `merge_zones.py` LADDERS]. |
| `sfmMergeGeoreferencedComponents` | bool | `false` | `false` in pass-1 zone aligns; `true` on every merge-ladder rung | "When multiple components are created and each is georeferenced, enabling this setting allows them to be merged even without visual overlap." [OFFICIAL] See §3.8 — the documented capability was never observed headless. Deliberately `false` per zone so that per-zone components stay honest: auto-fusing disjoint pockets by georeference during a zone align would freeze bad geometry invisibly [VERIFIED-as-decision: settings-evaluation §4]. |
| `sfmDistortionModel` | enum | `Brown3` | `Division` | See §3.9. **Global and all-or-nothing.** |
| `lisPreferImagesAsFeatureSource` | bool | `true` | `false` | "Set to Yes to import .zfprj mosaic images and use them as feature source during the alignment process… Applies only for the Z+F scans." [OFFICIAL] The only `lis*` key in the Help and the only one in the binary. No LiDAR in this pipeline; pinned `false` rather than left to the default. Its low-priority probe cell (E3) was never run [OPEN]. |

### 3.6 `sfmImagesOverlap` — a control whose direction is not settled

**Doc prose** [OFFICIAL: appbasics/alignsettings]: "Image overlap — Defines how much of the
image space is covered with the same part of the object, when talking about neighboring
images… Set Low when image overlap is below 20 %. For the best quality, the neighboring
images should have overlap greater than 60 %. Bigger overlap improves speed while a smaller
overlap may cause disconnected components if there are not enough photographs."

Read literally, the setting **declares** the physical overlap of the imagery, and declaring
a bigger overlap makes RealityScan faster (fewer candidate pairs need checking).

**This repo's operative reading** is the opposite direction: the setting controls "breadth
of the candidate-pair search", and `Low` → `Medium` was adopted precisely to *widen* the
search for loop closures on 2–3 s frame spacing with interleaved cameras and track revisits
[VERIFIED-as-decision: docs/settings-evaluation-2026-07 §4, 2026-07-23; comment preserved
verbatim in `AlignmentParams.xml`]. The same reading is used to reject `High` as a merge
ladder rung: "it only widens candidate-pair search, so it can help only where components
share content the matcher skipped" [VERIFIED-as-reasoning: FINDINGS 2026-07-27].

These two readings cannot both be right about which direction widens the search.
**[CONTRADICTED: appbasics/alignsettings prose ("bigger overlap improves speed") vs this
repo's adopted reading ("Medium widens the pair search vs Low"). No A/B has ever been run;
the change was adopted on reasoning, not measurement.]** The registration numbers in §7.1
were all produced at `Medium`, so nothing in the empirical record separates the two.

[OPEN — cheap: align the 124-image `zone_3` fixture three times at `Low` / `Medium` /
`High`, everything else pinned, and record wall clock, registered count and component
count. ~12 minutes total on the production box. Wall clock alone settles the direction.]

### 3.7 `sfmFeatureDetectionQuality` — the documented values are not the values the app writes

- **Docs**: `High` | `Normal`, default `High` [OFFICIAL: tutorials/setkeyvaluetable].
- **Observed**: the Alignment Settings panel exported from the 2.2 GUI writes
  `<entry key="sfmFeatureDetectionQuality" value="RealityScan.FeatureDetector.RSa1"/>`.
  The binary contains exactly two such identifiers: `RealityScan.FeatureDetector.RSa1`
  and `RealityScan.FeatureDetector.TB` [UNDOCUMENTED: `AlignmentParams.xml` + binary
  string sweep].
- **Status**: the repo pushes the detector-id form through `-set` in every zone align and
  those aligns completed with no `err:7155`, which is evidence the form **parses** — not
  evidence the key was **honoured**. An unknown value may be accepted and ignored
  ([INFERRED], and see §2.5: silence is not success).
- These identifiers are current product strings and must not be renamed away from
  `RealityScan.*` (CLAUDE.md naming rule).

[OPEN: which detector id corresponds to `High` and which to `Normal`. Cheapest probe:
toggle the GUI dropdown, re-export the Alignment Settings panel, read the value.]

### 3.8 `sfmMergeGeoreferencedComponents` — documented capability never observed headless

- **Docs**: "…enabling this setting allows them to be merged even without visual overlap."
  [OFFICIAL: appbasics/alignsettings]
- **Observed**: with the flag `true`, neither `-mergeComponents` (cell D1) nor `-align`
  with `sfmForceComponentRematch=true` (cell D2) produced an overlap-free merge. Every
  zero-shared-content pairing exited SUCCESS with the maximal component unchanged, under
  every mechanism × flag × path-form combination tested.
  [CONTRADICTED: NA167 wave-1f / D1 / D2, 2026-07-24]
- **Do not treat D1/D2 as final.** Those cells fed the flag components that were
  georeferenced from **position-only priors at 10 m claimed accuracy**; the feature's
  documented premise ("each is georeferenced") was arguably never met, and RealityScan may
  distinguish prior-weighted georeferencing from ground-control-locked georeferencing.
  [SUPERSEDED-RISK: FINDINGS 2026-07-25 RECON] [OPEN: re-test with priors-v2 components.]
- Governing rule established later and independently: **fusion is content-driven.**
  Content overlap ⇒ fusable by either mechanism, with or without scene georeferencing
  constraints; zero content overlap ⇒ silent no-fuse regardless of flags
  [VERIFIED: probe D7, `testing/probe_d7.py`, 2026-07-24]. D1–D3 are consistent with that
  rule rather than contradictory — those pairs never saw the same seafloor.
- `sfmEnableCameraPrior` and `sfmMergeGeoreferencedComponents` are different scopes and
  compose: (a) is per-camera during alignment and makes components georeferenced; (b) is
  per-component and post-solve. (b) without (a) is inert.
  [INFERRED from Help prose + design reasoning, settings-evaluation §5; not isolated by a
  cell.]

Full merge semantics live in the sibling components-and-merge document.

### 3.9 Distortion models

| `sfmDistortionModel` value | Model | When to use [OFFICIAL: appbasics/settings_distortion_models] |
|---|---|---|
| `Division` | single-parameter division model | "reliably covers simple distortions but works very well also for fish-eyes optics (for example GoPro)". [INFERRED: it is the only model whose description is not bounded below 180°, so it is the one to reach for on ≥ 180° optics — Epic never says that literally.] |
| `Brown3` | polynomial radial, 3 coefficients | default; "works for optics with less than 180°" |
| `Brown4` | polynomial radial, 4 coefficients | "able to cover different distortion in the middle and borders of an image" |
| `Brown3WithTangential2` | + 2 tangential | compensates lens offset; "Majority of current optics has negligibly small tangential distortion" |
| `Brown4WithTangential2` | + 2 tangential | as above |
| `KplusBrown3WithTangential2` | + skew & aspect optimisation | "If K + … is not used, RealityScan by default assumes a zero skew and aspect ratio as 1" |
| `KplusBrown4WithTangential2` | + skew & aspect optimisation | as above |

Epic's own tuning tip: "You can switch between models, e.g., starting with a simpler
Division model first, and later change it to Brown and click Align Images (F6) to optimize
data." [OFFICIAL: appbasics/settings_distortion_models]

**The key is global and all-or-nothing.**
[CONTRADICTED: `docs/settings-evaluation-2026-07 §3` asserted that a per-image XMP
`Camera:DistortionModel` overrides the global key, and Epic documents per-image lens
priors including a per-image Model (`inpDistortionModel`, appbasics/camerasettings_priors)
/ observed: the Cinema sidecars declared `brown3`, yet **all 2,558** Cinema pose XMPs came
back `xcr:DistortionModel="division"` — the same model as the 2,492 Port records.
Aggregated from 5,050 PD-6 harvest records, 2026-07-26.] [VERIFIED: FINDINGS 2026-07-26;
cell PD-2]

Consequence for mixed-optics rigs: pick **one** global model and supply measured
coefficients per calibration group; the per-camera-model plan is not achievable in 2.2.

**Measured Division vs Brown3:**

| Fixture | Cell | Result |
|---|---|---|
| Z3, 124 images | PD-1: `Division` on the PD-0a config | **112/124 registered, best of the series** (baseline Brown3: 102), components `[102, 10]`, and **both** cameras solved division — the rectilinear camera did not degrade |
| Z1, 4,540 images | PD-6: `Division` + loose 10/10/1 + intact calibration sidecars | 4,394/4,540 in **two** components, hull scale **0.981**; the Brown3 baseline gave 4,405 in **three** components at hull scale **0.175** |

[VERIFIED: PRIORS_DISTORTION_TEST_PLAN cells PD-1 / PD-6, 2026-07-25]

**PD-6's attribution is not clean.** It differs from the fresh-run baseline in three ways:
(a) Brown3→Division, (b) the flight-log accuracy columns actually being imported for the
first time, (c) orientation priors removed (its cell used a 7-column position-only format).
Do not attribute the scale repair to Division alone. [VERIFIED-as-caveat: FINDINGS
2026-07-26] [OPEN: a Brown3 + explicit-loose isolation cell on zone_1 (~70 min) separates
them; never run, and the corrected config was adopted regardless.]

---

## 4. `AlignmentParams.xml` field by field

### 4.1 What it is

`modules/realityscan_interface/RS_CLI/Metadata/AlignmentParams.xml` is a settings-panel
export produced once from the GUI's Alignment Settings dialog. Its root is:

```xml
<Configuration id="{E377B69D-FB4B-4833-9CBE-FF747B7AF6D9}">
```

The GUID identifies the owning settings panel and matches a
`HKCU\Software\EpicGames.RealityScan\RealityScan\Workspace\SP-{GUID}` registry subkey
[UNDOCUMENTED: read-only registry enumeration]. The general mechanism — how params XML
files are structured, which commands consume them as arguments, and how to obtain one —
is in `09-xml-parameter-files.md`.

**This file is never passed to a command.** `-align` takes no parameter file (§2.1), so
the workflow parses it and replays the `sfm*`/`lis*` rows as `-set` calls (§2.6). The
repo's policy statement is "never align on instance defaults": an instance carries
whatever the last GUI or CLI session set, so aligning on unknown settings is not
reproducible [VERIFIED-as-policy: `AlignZone.bat` header comment; FINDINGS 2026-07-21/23].

**The policy is not uniformly enforced — two shipped align workflows still run on instance
defaults.** Exactly these `.bat` files reference `AlignmentParams.xml`: `AlignZone.bat`,
`GrowZone.bat`, `AlignImagesFromFolder.bat` (deprecated), `ProbeLockAlign.bat`,
`ProbeSubsetAlign.bat`, `ProbeSubsetAlign2.bat`. **`AlignImageList.bat` and
`SequentialAlignGrow.bat` contain no settings replay at all**: they go
`-newScene` → `-add`/`:grow` → `-importFlightLog` → `-align` with whatever the instance
happens to hold.
[VERIFIED-by-inspection: `grep -l AlignmentParams RS_CLI/Scripts/*.bat`, 2026-08-04]

Consequences, both load-bearing for reading §7.1:

- Every NA167 result produced through `AlignImageList.bat` or `SequentialAlignGrow.bat`
  (the A2 imagelist cells, the B sequential-grow runs) carries an unrecorded settings
  state. The instance in those runs was typically *not* fresh — it may have been left
  configured by a preceding `AlignZone` run in the same session, because swept `-set`
  values persist across restarts (§2.6 point 2). Their registration numbers stand as
  measurements of *those runs*; they are not attributable to `AlignmentParams.xml`.
- The zone_14 forensic log is the proof case: its only `set` commands are the five
  `app*` ones from `startRealityScan.bat`, and it detected exactly `40000` features per
  image — RealityScan's documented `sfmMaxFeaturesPerImage` default, not the profile's
  `0xc350` (§8.1).

Fix if you need those two workflows to be reproducible: copy the eight-line replay block
from `AlignZone.bat` (lines 80–88) into them verbatim.

### 4.2 Every entry, verbatim

35 entries: 27 `sfm*`, 1 `lis*`, 7 opaque `s<NNN>l`. Values as of 2026-07-25 onward.

| # | `key` | `value` | Applied by the replay loop? | Notes |
|---:|---|---|---|---|
| 1 | `s237l` | `0.5` | no | occupies the `sfmCameraPriorAccuracyZ` slot [INFERRED] |
| 2 | `sfmFeatureDetectionQuality` | `RealityScan.FeatureDetector.RSa1` | yes | §3.7 |
| 3 | `s251l` | `0.05` | no | `sfmControlPointXAccuracy` slot [INFERRED] |
| 4 | `sfmMaxFeaturesPerImage` | `0xc350` | yes | = 50000 |
| 5 | `sfmForceComponentRematch` | `false` | yes | merge-stage tool |
| 6 | `sfmDistortionModel` | `Division` | yes | preceded in the file by a 4-line XML comment recording that this is a global fallback for a mixed rig |
| 7 | `sfmCameraPriorAccuracyRoll` | `10.0` | yes | degrees |
| 8 | `sfmMaxFeatureReprojectionError` | `1.29999995` | yes | px |
| 9 | `sfmMaxFeaturesPerMpx` | `0x36b0` | yes | = 14000 |
| 10 | `sfmGPUAcceleration` | `true` | yes | [UNDOCUMENTED key] |
| 11 | `sfmBackgroundDetectThreadPriority` | `Low` | yes | [UNDOCUMENTED key] |
| 12 | `sfmCameraPriorWeightOrientation` | `10.0` | yes | |
| 13 | `s236l` | `5.0` | no | `sfmCameraPriorAccuracyY` slot [INFERRED] |
| 14 | `sfmEnableCameraPrior` | `true` | yes | |
| 15 | `lisPreferImagesAsFeatureSource` | `false` | yes | the only `lis*` row |
| 16 | `sfmCameraPriorWeight` | `10.0` | yes | |
| 17 | `sfmImagesOverlap` | `Medium` | yes | preceded by a 2-line XML comment recording the Low→Medium rationale |
| 18 | `sfmCameraDepthmapWeight` | `0.05` | yes | [UNDOCUMENTED key, unknown meaning] |
| 19 | `sfmControPointImageMeasAccuracy` | `4.0` | yes | Epic's typo, load-bearing |
| 20 | `sfmPreselectorFeatures` | `0x4e20` | yes | = 20000 |
| 21 | `sfmDetectorSensitivity` | `Ultra` | yes | |
| 22 | `sfmImageDownscaleFactorDraftMode` | `2` | yes | draft only |
| 23 | `sfmMergeGeoreferencedComponents` | `false` | yes | pass-1 policy |
| 24 | `s252l` | `0.05` | no | `sfmControlPointYAccuracy` slot [INFERRED] |
| 25 | `sfmCameraPriorAccuracyPitch` | `10.0` | yes | degrees |
| 26 | `sfmFinalModelOptimizationDraftMode` | `false` | yes | draft only |
| 27 | `sfmCameraPriorAccuracyYaw` | `10.0` | yes | degrees |
| 28 | `sfmImagesOverlapDraftMode` | `Medium` | yes | draft only |
| 29 | `sfmBackgroundDetectFeatures` | `false` | yes | [UNDOCUMENTED key] |
| 30 | `sfmImageDownscaleFactor` | `1` | yes | full resolution |
| 31 | `s235l` | `5.0` | no | `sfmCameraPriorAccuracyX` slot [INFERRED] |
| 32 | `s253l` | `0.1` | no | `sfmControlPointZAccuracy` slot [INFERRED] |
| 33 | `sfmAutoReconRegionAfterAlignment` | `false` | yes | |
| 34 | `sfmEnableAutoSuggestions` | `true` | yes | [UNDOCUMENTED key] |
| 35 | `s254l` | `0.001` | no | `sfmDefinedDistanceAccuracy` slot [INFERRED] |

[VERIFIED-by-inspection: `RS_CLI/Metadata/AlignmentParams.xml`, read 2026-08-04]

Entry order in the file is arbitrary (the exporter does not sort), and the replay loop is
order-insensitive because each row is an independent `-set`.

### 4.3 The `s<NNN>l` ids

`s235l`, `s236l`, `s237l`, `s251l`, `s252l`, `s253l`, `s254l` are auto-generated internal
setting ids emitted by the settings-panel XML exporter for keys with no exported friendly
name. They have **no Help coverage anywhere** and are known only from this exported XML
plus matching strings in the binary. [UNDOCUMENTED]

The slot mapping in the table above is [INFERRED] from two things: the exporter's slot
order and the magnitude match to the documented defaults (camera prior 10/10/20 ↔
`5.0/5.0/0.5`; control point 0.05/0.05/0.10 and defined distance 0.10 ↔
`0.05/0.05/0.1/0.001`).

[OPEN — one minute with the GUI: `-set "sfmCameraPriorAccuracyZ=99"`, re-export the
Alignment Settings panel, and see which `s<NNN>l` entry became `99`. Alternative with no
GUI: change one alignment dialog control at a time and diff successive exports.]

### 4.4 Keys the profile does **not** carry

These alignment-relevant keys are absent from the file, so they keep whatever the instance
last had (which persists across restarts):

- `sfmCameraPriorAccuracyX/Y/Z`, `sfmControlPointXAccuracy/Y/Z`,
  `sfmDefinedDistanceAccuracy` — present only under their `s<NNN>l` aliases, which the
  replay filter drops (§2.6).
- `sfmFinalModelOptimization` — the **non-draft** counterpart of
  `sfmFinalModelOptimizationDraftMode`. The Help documents only the draft variant; the
  string exists in the 2.2 binary [UNDOCUMENTED]. Given the draft doc's "strongly
  recommended for high-precision models", leaving this unpinned is a real gap
  [OPEN: pin it explicitly and confirm it parses; if a report's `componentFinalOptimization`
  variable (§10.3) reads back, that closes it in one align].
- `sfmAlgorithm`, `sfmMergeComponenetsOnly` *(sic)*, `sfmSBPTRemoveCameras` — strings
  present in the 2.2 binary with no documentation and no known semantics [UNDOCUMENTED].

### 4.5 Authoring or modifying a profile

1. **Obtain a baseline.** The only reliable way to get a valid settings export is to open
   the corresponding GUI dialog once and export it. That is how this file was produced
   [VERIFIED-as-practice: FINDINGS 2026-07-21].
2. **Edit by hand for known keys.** Because the file is consumed by a `-set` replay, not
   handed to a command, adding a row with the *documented* key name works and is the
   recommended fix for the accuracy keys — e.g. add
   `<entry key="sfmCameraPriorAccuracyZ" value="0.5"/>` next to `s237l`.
3. **Keep the `sfm`/`lis` prefix**, or extend the filter. Any key not starting `sfm` or
   `lis` is silently dropped by the current loop.
4. **Do not rename `RealityScan.FeatureDetector.RSa1`** — it is a current product string,
   not a legacy RealityCapture name (CLAUDE.md naming rule).
5. **Test-cell overrides**: `AlignZone.bat` honours `RS_ALIGN_PARAMS` so a variant profile
   can be pointed at without touching the canonical file:

```bat
set "RS_ALIGN_PARAMS=F:\na156_h2024\cells\AlignmentParams_brown3_loose.xml"
```

[VERIFIED-by-inspection: `AlignZone.bat` lines 30–32]

6. **One variable per cell.** The plan's own worked example of violating this is cell
   PD-0, marked "BAD CELL (two variables at once)" [VERIFIED: PRIORS_DISTORTION_TEST_PLAN].

---

## 5. Per-image alignment controls (`-editInputSelection`, `inp*`)

`-editInputSelection "key=value"` applies a setting to the **current image selection**.
It is the master per-image control and the one the growth workflows use.
[OFFICIAL: appbasics/allcommands + tutorials/editselectioncommand] [VERIFIED: FINDINGS
2026-07-23, cells U1/U19/U2]

`inp*` is **not** a `-set` key space; these keys only reach the app through
`-editInputSelection`.

**Every setting has two accepted key spellings.** "Almost every setting has two possible
keys… The upper key (blue) is usually an abbreviation of the setting, and the lower key
(gray) is the whole path to the setting based on the panel in which it can be found"
[OFFICIAL: tutorials/editselectioncommand]. So `inpPose` and `Prior pose/Absolute pose`
name the same setting, as do `inpuTz` and `Prior pose/Pose accuracy/Position Z accuracy`.
The path form contains spaces and `/`, so it must be a single quoted argument
(`-editInputSelection "Prior pose/Absolute pose=1"`) and is strictly worse for automation.
**Use the abbreviated form.** [INFERRED that the path form works over the CLI at all —
the Help presents both as "keys" for the command, but only the abbreviated form has ever
been executed here.]

Process id for the command: `21877 CLI_SET_SELECTED_INPUTS_PROPERTY`
[OFFICIAL: tutorials/processids].

### 5.1 Alignment-relevant keys

| Key | Values | Meaning [OFFICIAL: tutorials/editselectioncommand] |
|---|---|---|
| `inpEnabled` | `true` `false` | Enable/disable in the alignment process |
| `aligFeaturesMode` | `0` `1` `2` | Features source: 0 merge using overlaps, 1 use component features, 2 use all image features |
| `inpMaskOpts` | `0` `1` `2` `3` | Masking layer use: 0 do not use, 1 only in alignment, 2 only in meshing, 3 both |
| `inpPose` | `0` `1` `2` `3` | Absolute pose prior: 0 Unknown, 1 Position, 2 Position and orientation, 3 Locked |
| `inpPosePriorRelative` | `0` `1` `2` | Relative pose: 0 Unknown, 1 Draft, 2 Exact |
| `inpPosePriorRelativeGroup` | string | Locked pose group (any alphanumeric value) |
| `inpTx` `inpTy` `inpTz` | float | Prior pose x/y/z (also longitude/latitude/altitude, DMS or decimal-degree with a cardinal prefix, e.g. `N54.825347`) |
| `inpRx` `inpRy` `inpRz` | float | Yaw/Heading (−180…180), Pitch/Elevation (−90…90), Roll/Bank (−180…180) |
| `inpPriorAccuracyInh` | `0` `1` | Accuracy settings source: 0 Global camera prior settings, 1 Edit custom values |
| `inpuTx` `inpuTy` `inpuTz` | float ≥ 0 | Per-image position X/Y/Z accuracy |
| `inpuRx` `inpuRy` `inpuRz` | float ≥ 0 | Per-image yaw/pitch/roll accuracy |
| `inpCalibrationGroup` | int, or `-1` | Calibration group; `-1` = groupless. "All images with the same number (other than −1) will share the same calibration parameters after images are aligned." [OFFICIAL: appbasics/camerasettings_priors] |
| `inpCalibration` | `0` `1` `2` | Calibration prior: 0 Unknown, 1 Approximate, 2 Fixed |
| `inpFocal` | float | Focal length (35 mm) in millimetres |
| `inpPPX` `inpPPY` | float | Principal point x/y [mm] |
| `inpSkew` | float | Skew. **The Help lists `inpSkew` a second time as the key for "Aspect ratio"** — two different settings, one key. The 2.2 binary contains a distinct string `inpAspect`, so aspect ratio is almost certainly `inpAspect` and the Help table has a copy-paste error. [CONTRADICTED: tutorials/editselectioncommand (`Aspect ratio` → `inpSkew`, path form `Prior calibration/Aspect ratio`) vs binary string sweep (`inpAspect` present); never executed either way.] [INFERRED] |
| `inpLensGroup` | int, or `-1` | Lens/distortion group |
| `inpDistortion` | `0` `1` `2` | Lens prior: 0 Unknown, 1 Approximate, 2 Fixed |
| `inpDistortionModel` | `0`…`5` | 0 No lens distortion, 1 Division, 2 Brown3, 3 Brown4, 4 Brown3 with tangential, 5 Brown4 with tangential |
| `inpRadial1`…`inpRadial4`, `inpTangential1`, `inpTangential2` | float | Distortion coefficients |

Dedicated single-purpose commands exist for a few of these and are equivalent
[OFFICIAL: appbasics/allcommands "Commands for Selected Images"]:

| Command | `-editInputSelection` equivalent |
|---|---|
| `-enableAlignment true\|false` | `inpEnabled` |
| `-setFeatureSource 0\|1\|2` | `aligFeaturesMode` |
| `-lockPoseForContinue true\|false` | `inpPosePriorRelative` / `inpPosePriorRelativeGroup` |
| `-setPriorCalibrationGroup <n>` (`-1` = do not group) | `inpCalibrationGroup` |
| `-setPriorLensGroup <n>` (`-1` = do not group) | `inpLensGroup` |
| `-setConstantCalibrationGroups` | groups all selected inputs into one calibration group |
| `-setCalibrationGroupByExif` | sets the calibration group of **all** inputs from EXIF |

The repo prefers `-editInputSelection` (one command family, more capabilities) and keeps
the dedicated commands as a verified fallback behind `RS_GROW_SELECT_CMDS=legacy`
[VERIFIED-by-inspection: `GrowZone.bat` `:selEnable` / `:selDisable` / `:selFeature`].

The pair must be composed **inside** the script as one quoted argument so cmd never splits
the `=` (§2.3):

```bat
call :run -editInputSelection "inpEnabled=false"
```

### 5.1b Per-image key strings present in the 2.2 binary but absent from the Help

A string sweep of `RealityScan.exe` returns `inp*` and `alig*` identifiers that the
`-editInputSelection` table does not list. They are grouped below by what their names
imply. **Nothing here has been executed**; the only established facts are that the strings
exist in the 2.2 binary and that the Help does not mention them.
[UNDOCUMENTED: binary string sweep, `scratchpad/exe_keys_u16*.txt`, 2026-08-04]
[INFERRED: the reading of each name.]

| Family | Strings | Why it matters for alignment |
|---|---|---|
| **Camera rig** | `inpRig`, `inpRigId`, `inpRigIndex`, `inpRigInstance`, `inpRigValid` | A rigid multi-camera rig is exactly this pipeline's situation (four cameras bolted to one ROV, fixed baselines measured at 1.11–1.21 m, §6.5). If RealityScan 2.2 can be told "these four images are one rig instance", it constrains the solve far harder than per-camera priors do. **No CLI or GUI route to these is documented anywhere.** [OPEN — highest-value unknown in this section. Cheapest probe: `-editInputSelection "inpRigId=1"` on the smoke fixture; if it does not throw and the Selected-inputs panel changes, the feature is reachable.] |
| **INS / lever-arm offsets** | `inpEnableInsOffset`, `inpInsOfsX`, `inpInsOfsY`, `inpInsOfsZ`, `inpInsOfsRY`, `inpInsOfsRP`, `inpInsOfsRR` | Per-image navigation-sensor offset: three translations plus yaw/pitch/roll. This is the *application-side* form of the lever arm that `modules/georeference/` currently bakes into the flight log by hand (Port 1.17 m forward / 0.0 m down, Cinema 1.0 / 0.0 — FINDINGS 2026-07-26). If these keys work, the mount could be declared once instead of pre-applied per row, which would also remove the double-application risk flagged in §6.1. [OPEN] |
| **Per-image prior CRS** | `inpPosePriorAbsoluteCs`, `inpPosePriorAbsoluteCsInput`, `inpPosePriorAbsoluteCsType`, `inpPosePriorAbsoluteCsWkt`, `inpPosePriorAbsoluteCsWktCheckProj`, `inpPosePriorAccuracyMode`, `inpPosePriorRelativeValid` | The "Absolute coordinates — Defines the coordinate system in which the camera is located" control [OFFICIAL: appbasics/camerasettings_priors] has no key in the Help table; these are its likely carriers, including a raw-WKT form. |
| **Solved (read-back) per-image values** | `aligIsReg`, `aligIsAnyReg`, `aligTx/aligTy/aligTz`, `aligRx/aligRy/aligRz`, `aligFocal`, `aligPPX/aligPPY`, `aligSkew`, `aligAspect`, `aligRadial1..4`, `aligTangential1..2`, `aligLensModel`, `aligLensModelId`, `aligCalibrationGroup`, `aligPoints`, `aligTCS`, `aligFixedSfm`, `aligConvCam2Im`, `aligConvIm2Cam` | The `alig*` family is the **solved** counterpart of the `inp*` priors — the right-hand column of the Selected-inputs panel. `aligFeaturesMode` is the one member the Help documents, and it is the one member that is genuinely a *setting*; the rest read like outputs. [INFERRED: they are read-only display values, not `-editInputSelection` targets.] |
| **Per-image residuals** | `inpMaxErr`, `inpMeanErr`, `inpMedErr`, `inpMeasCnt`, `aligMaxErr`, `aligMeanErr`, `aligMedErr` | Per-image maximal/mean/median reprojection error and measurement count. If these are reachable as report variables they would close the per-camera half of the quality gap in §10 — `$ExportCameras` does **not** expose any error variable [VERIFIED-by-inspection: appbasics/reports_fav_cameras]. [OPEN] |
| **Other** | `inpAspect`, `inpCamModel`, `inpLensModel`, `inpFeatures`, `inpPtsOverlap`, `inpAlignDepth`, `inpAlignMask`, `inpMeshingDepth`, `inpMeshingMask`, `inpTexturingMask`, `inpPointCouldFeatureDetectionQuality` *(sic — "Could" for "Cloud")*, `inpuUn` | `inpAspect` resolves the Help's `inpSkew` collision (§5.1). `inpPointCouldFeatureDetectionQuality` is a per-input feature-detection-quality override for point clouds and carries a product typo, like `sfmControPointImageMeasAccuracy` — reproduce it exactly if you ever use it. |

Also present, and worth knowing because their names are misleading: `alignMinComponents`,
`alignGcTotal`, `alignGcUnit`, `alignGcValid`, `alignGcX/Y/Z`, and a `align_*` snake_case
family (`align_max_features_per_image`, `align_detector_sensitivity`,
`align_final_model_otpimization` *(sic)*, `align_merge_georef_comps`,
`align_largest_component_camera_count`, …). These mirror the alignment settings one-for-one
but are **report/telemetry field names, not `-set` keys** [VERIFIED-as-classification:
`SURVEY_settings.md` §2; corroborated by `appbasics/reports_functions_and_variables`].
Their existence is independent confirmation that `sfmFinalModelOptimization` (non-draft) is
a real setting the app tracks (§4.4) and that the four undocumented Advanced keys in §3.1
are genuine settings rather than exporter artifacts.

### 5.2 Feature source semantics

[OFFICIAL: appbasics/components "Useful Component-related Settings"]

| Value | GUI name | What it does |
|---|---|---|
| `0` | Merge using overlaps | "use solely the components' images/points which are in common (the same in all components)… extremely speeds up the reconstruction process, as well as reduces computer memory consumption" |
| `1` | Use component features | "the most common and fastest type… especially beneficial with RAM shortage… the application will use only the points used in the alignment of the imported component" |
| `2` | Use all image features | "The slowest process of all these, recommended for a small number of camera poses. The program will use all images/points." |

The repo's per-component growth mode sets `1` on the component being grown and leaves the
orphan images at their per-image defaults [VERIFIED-by-inspection: `GrowZone.bat`
`:mode_component`]. `-setFeatureSource` and `-selectImage` were both wrongly believed
GUI-only until the 2026-07-23 allcommands sweep [SUPERSEDED: MERGE_TEST_PLAN §1]
[VERIFIED: NA167 B11].

[OPEN: cell U3 — does `aligFeaturesMode` persist across save/reload, and does it apply
strictly per image? Never run. Cheapest probe: set it on a selection in the smoke fixture,
save, reload, export the settings-bearing report, compare.]

### 5.3 Composing the selection: `-selectImage` matches literal full paths only

`-selectImage` is documented as
`selectImage <imagePath|regexp> [set|union|sub|intersect|toggle]`.

[CONTRADICTED: Help documents a regexp form / observed: **only literal full paths select
anything**. Bare regexp, dot-star-wrapped regexp, glob, and regexp with an explicit `set`
modifier all silently select nothing; a literal full path selects exactly its image.
Bisected across probes U-SEL2…U-SEL8, 2026-07-23.] [VERIFIED: FINDINGS 2026-07-23]

Cost: ~0.1–0.3 s per image, so a selection is a per-image union loop and takes minutes for
thousand-image sets. The repo fires the union calls without per-command waits (they are
instant and FIFO-ordered) and lets the next `:run` flush the queue and check the error
marker:

```bat
:selectFromList
for /f "usebackq delims=" %%L in ("%~1") do (
    %RealityScan% -delegateTo %RS_INSTANCE% -selectImage "%%~L" union
)
exit /b 0
```

[VERIFIED-by-inspection: `GrowZone.bat` `:selectFromList`]

[OPEN: forum-mine the regexp dialect — a staff reply may explain the discrepancy. Standing
follow-up since 2026-07-23.]

### 5.4 Pose locking is unusable as a growth anchor

`-editInputSelection "inpPose=3"` (Locked) **takes effect**, but `-align` then refuses:

> "prior set to 'Exact' mode must be all aligned in a single run. Incremental adding is
> not supported."

[VERIFIED: FINDINGS 2026-07-23, cell U18 FAIL]

Consequence: checkpoint/rollback of the `.rsproj` bundle remains the primary never-shrink
mechanism. `GrowZone.bat` keeps the lock path behind `RS_GROW_LOCK_ANCHOR=1`, **off by
default**; its header gives the reason as "until hardening cell U18 verifies that locked
cameras are guaranteed retained and that new images still register onto them", and U18 is
the cell that FAILED above. Lock/unlock always goes through `-editInputSelection`
(`inpPose=3` before the align, `inpPose=0` after) regardless of
`RS_GROW_SELECT_CMDS`. [VERIFIED-by-inspection: `GrowZone.bat` header + `:mode_component`
and `:align_and_export`] [VERIFIED: FINDINGS 2026-07-23, U18 FAIL]

### 5.5 Per-image state persists into the save

Component-mode growth passes disable most of the scene (`inpEnabled=false`) and that state
**persists into a save**. A saved zone project must always be the all-enabled state,
because it is the authoritative artifact. `GrowZone.bat` re-enables everything before every
save [VERIFIED: FINDINGS 2026-07-24; `GrowZone.bat` `:save_quit`].

---

## 6. Priors and alignment: measured effects

### 6.1 Two distinct prior families

| Family | Carrier | Key that consumes it | Scope |
|---|---|---|---|
| **Pose priors** — per-image position, optionally orientation, with accuracies | flight log imported by `-importFlightLog <log> <FlightLogParams.xml>` | `sfmEnableCameraPrior=true` | per camera, inside the bundle adjustment; also georeferences the result |
| **Calibration priors** — calibration/lens group, focal, distortion model hint, coefficients | `<stem>.xmp` sidecars beside the images, auto-imported on add | none — read directly | per image |

[VERIFIED: docs/settings-evaluation-2026-07 §2 and §5]

Flight-log formats, CRS derivation and the `ifKGrp` / `ifKmode` unknowns are the
georeferencing document's subject. Two facts from there are load-bearing here:

- The custom 13-column format (`{B438A617-2434-5A24-C1B7-58980F28345A}`) was **never
  installed** in the app's `flightlogs.xml` until 2026-07-25, so **orientation (YPR) and
  per-image accuracies were silently dropped on every import before that date**
  [VERIFIED: PRIORS_DISTORTION_TEST_PLAN audit item 1].
- **The import's Euler-angle order and "Camera mount" settings are unpinned.** Both
  *settings* are documented — the Help's Trajectory Import page states that imported YPR is
  interpreted in **NED** (OPK being the ENU variant), that "Euler angles order (YPR)" is a
  setting **evaluated right-to-left**, and that a **"Camera mount"** option is offered
  whenever YPR is included [OFFICIAL]. What is missing is their *config keys*: no key
  string for either appears in any file under the RealityScan install, so both are compiled
  into the binary, and `flightlogs.xml` defines column mapping only. The only plausible
  carriers in `FlightLogParams.xml` are `ifKGrp` and `ifKmode`, whose value mapping is
  undocumented; this repo has left them at the template's `ifKGrp=2`, `ifKmode=0x0` rather
  than guess. [UNDOCUMENTED + VERIFIED-as-flag: FINDINGS 2026-07-26]
  Consequence: every conclusion about whether orientation priors help or hurt was measured
  through an **unpinned import path**, composing angles in a possibly different order than
  the intrinsic Roll → Pitch → Yaw the flight-log writer assumes, and possibly
  double-applying a camera mount already baked into the angles. Registration counts stand
  as measurements; the attribution to "orientation priors" does not. Cells carrying the
  flag: PD-0, PD-0b, PD-1b, PD-4, M-DIV-ORI, the whole 2026-07-24 fresh run, and the
  mount-angle derivations. **Not** affected: PD-6 (its cell used a 7-column position-only
  format), every scale-oracle result, and rig-*internal* geometry.
  [VERIFIED: FINDINGS 2026-07-26 contamination flag + its scope correction]
  Two ways to settle it, both cheap: (1) set the two dropdowns in the GUI import dialog,
  save the params, diff against the template — one minute, needs the GUI; (2) headless,
  align the smoke fixture with orientation at several `ifKmode` values and read the
  resulting camera attitudes out of the pose XMPs — ~2 min per cell.
- The YPR convention itself **is** settled: Epic staff (OndrejTrhan, 2023-10-23, Epic
  Developer Community, "Registration export and camera orientations") — "Yaw = 0, image is
  oriented to Y…, Pitch = 0, image is looking down, Roll = 0, image is parallel with X
  axis", composed intrinsic Roll → Pitch → Yaw. This repo's `_convert_to_rc_orientation`
  already references pitch to nadir (`rc_pitch = 90 + (pitch_vehicle - camera_offset)`),
  confirmed against the written logs: zone_1 Port median **88.11°** (n=2,267), Cinema
  median **43.11°** (n=2,273). [VERIFIED: FINDINGS 2026-07-26, by forum mining + reading
  the written logs] [SUPERSEDED, same session: a claim that "Port is 90° wrong" — refuted
  by one grep of the actual column values.]

### 6.2 Where accuracies actually come from

With `ifUsePosAcc=true` / `ifUseOriAcc=true` in `FlightLogParams.xml`, the log's accuracy
columns become per-image values. The global `sfmCameraPriorAccuracy*` keys are the
fallback for images that have none — and in this pipeline they were never applied anyway
(§2.6). So **when the PD cells say "1/1/0.1" or "10/10/1", those are flight-log column
values, not `-set` values.** [VERIFIED-by-inspection: `FlightLogParams.xml` +
`ab_orientation_priors.py`; the accuracy-source semantics are OFFICIAL:
appbasics/camerasettings_priors "If the Accuracy settings source is set to 'Global camera
prior settings', the values set in the Alignment settings will be used."]

### 6.3 The decisive isolation: tight position priors fragment and mis-scale

665-image bow component, known-good (scale 1.009), calibration sidecars regenerated before
every cell, position-only logs, scale measured by `testing/scale_oracle.py`:

| Cell | Registered | Components | Scale (maximal) |
|---|---:|---:|---:|
| `brown3_loose` (10/10/1) | 665/665 | **1** | 1.049 |
| `brown3_tight` (1/1/0.1) | 662/665 | 2 | 0.886 |
| `division_loose` | 656/665 | **1** | **0.989** |
| `division_tight` | 659/665 | 3 | 0.826 |

**Verdict: tight position priors fragment components and move scale away from truth**,
reproducibly, under both distortion models. Registration barely moved (656–665 in every
cell) — which is exactly why a camera-counting oracle never caught it.

Root cause: the flight log's accuracy columns want **end-to-end per-image position
uncertainty** (timestamp matching + nav interpolation + lever arm + dive-long drift), not
the instantaneous sensor spec. DVL 1 m XY / Paro 0.1 m Z are sensor figures; claiming them
over-constrains the solve. Reverted to 10/10/1.

[VERIFIED: PRIORS_DISTORTION_TEST_PLAN "Bow 2×2", 2026-07-25]

[OPEN: an intermediate ladder (3/3/0.5, 5/5/1) is queued and never run — loose is proven,
not proven optimal. Each cell is a ~70 min zone_1 re-align.]

### 6.4 Orientation priors: load-bearing here, not harmful

| Evidence | Result |
|---|---|
| Z3 (124 imgs), PD-0b: orientation at **honest 15°** accuracy | **109/124, +7 vs baseline**, components `[99, 10]` |
| Z3, PD-0: orientation at **tight 3–5°** accuracy (two variables — bad cell) | 101/124 in **four** components `[62, 18, 11, 10]` |
| Z3, PD-1b: Division + orientation@15° | 112/124 `[102, 10]` — same as Division alone; gains **not additive** |
| H2023 zone_2 (852 imgs), PD-2b: Division + orientation@15° + real accuracies | **101/852 (11.9 %) → 812/852 (95.3 %)**, an 8× improvement from configuration alone, no data change; components `[621, 102, 57, 32]` |
| H2024, all five zones re-aligned **position-only** (single variable: 7-column log instead of 13-column) | zone_1 scale 0.989 (5 comps vs 8), zone_2 1.014, zone_4 0.904 (3 vs 5) — but **zone_3 and zone_5 registered nothing at all**: zero components, empty harvest, "Identity capture finished after 0 component(s)" after 12.7 and 32.4 minutes |

[VERIFIED: PRIORS_DISTORTION_TEST_PLAN cells; HANDOFF 2026-07-27; raw results at
`F:/na156_h2024/ab_position_only/ab_results.json`; driver
`testing/ab_orientation_priors.py`]

**Dose-response is the pattern: 5° fragments, 15° gains, absent can be catastrophic.**

Every Z3 orientation cell (PD-0, PD-0b, PD-1b, PD-4, M-DIV-ORI) carries the contamination
flag of §6.1 — counts stand, attribution does not.

**Owner decision in force: orientation priors ON at alignment, conservative 15° YPR
accuracy**, with the scale oracle as the named mitigation. The concern (unpinned Euler
order + camera mount makes tight orientation a live scale risk) was raised and overruled,
and is recorded. [VERIFIED-as-decision: FINDINGS 2026-07-26]

### 6.5 Calibration priors: sidecar grouping demonstrably works

- **RealityScan reads and writes `<stem>.xmp` only.** `image.jpg.xmp` files are ignored
  **silently**. A batcher bug wrote priors that way, so no historical run before
  2026-07-22 ever loaded its calibration priors [VERIFIED: NA167 #3 / B7].
- Per-image `Camera:CalibrationGroup` / `Camera:LensDistortionGroup` sidecars are the only
  way to separate EXIF-identical cameras. One group per **physical camera**, never per lens
  type [VERIFIED: settings-evaluation §1–§2].
- **It works.** Both cameras were given the same 16.0 mm prior and the solve separated them
  by 5.6 % with IQRs of ±0.5 %: Cinema (2,558 records) focal 35 mm-eq **16.374**
  (IQR 16.302–16.476), division k1 **−0.0378**; Port (2,492 records) focal **15.499**
  (IQR 15.435–15.574), division k1 **−0.3875**. The order-of-magnitude k1 gap is the
  fisheye declaring itself. [VERIFIED: FINDINGS 2026-07-26, parsed from 5,050 PD-6 harvest
  records]
- **Fragmentation improves with them**: calibration sidecars at align time cut zone_1 from
  9 components to 3 at equal-or-better registration (4,405/4,540 = 97.0 % vs the
  pre-sidecar production run's 4,392 = 96.7 %, same imagery, same box)
  [VERIFIED: FINDINGS 2026-07-24].
- **Prior *content* can hurt**: with the *old* wrong values (three physical cameras grouped
  together at "12 mm fisheye" when one is rectilinear 17 mm), registration fell 96.3 % →
  89.6 % on Zeuss. Generation became opt-in. Corrected per-camera values reverse the
  calculus — validate per rig before trusting either direction. [VERIFIED: NA167 #4 / B7]
  [SUPERSEDED-in-scope by the corrected registry]
- **`LensDistortionPrior="Approximate"` with no coefficients supplied does not pin
  distortion to zero.** [CONTRADICTED: appbasics/camerasettings_priors states "By default,
  the lens distortion model is set to 'No lens distortion' with prior set to 'Approximate'.
  This means that RealityScan tries to find a solution where lens distortion is as close to
  zero as possible" / observed: Cinema carried exactly `Approximate` with no coefficients
  and still solved k1 = −0.0524 over 2,204 cameras. Note the doc's claim is scoped to the
  *default model* "No lens distortion"; the observation was under a real model.]
  [VERIFIED: FINDINGS 2026-07-25] [SUPERSEDED: an earlier same-session caution that
  "Approximate would assert approximately-zero distortion" was wrong.]
- **`appGroupCalibrationByExif` (bool, default `false`) is unusable for an EXIF-identical
  rig in either position**: enabled it would collapse two different lenses into one
  calibration group; left false, images calibrate without EXIF grouping at all. Sidecars
  are the answer. [VERIFIED-by-inspection: settings-evaluation §1]

### 6.6 The contamination trap: exported pose sidecars become exact-pose priors

Adding images auto-imports `<stem>.xmp` sidecars found next to them, and **pose-bearing
sidecars silently become exact-pose priors on any later `-add` of the same images**. Epic
documents this as a feature — "The align command will now use the camera positions and
calibration according to the setting stored in these .xmp files and application settings"
[OFFICIAL: tutorials/commandline_1 "Export XMP to reuse alignment", whose worked example is
`-exportXMP` from project 1 → `copy Images1/*.xmp Images2/` → `-addFolder Images2 -align`]
— but for a pipeline that re-aligns the same tree repeatedly it is cross-run contamination.

[VERIFIED: NA167 B7, 2026-07-22] The pipeline sanitizes the image tree back to
calibration-only content after every census (`camera_registry.sanitize_and_census`).

**A related defect, now fixed, invalidated two cells:** the identity harvest *moves* every
pose-bearing `.xmp` out of the image tree, and the last-peeled component's sidecars are
never re-exported. Measured on fresh zone_1: **796 of 4,540 images (17.5 %) had no
sidecar** — the entire bow component (665/665), 123 of c0, 8 unregistered. Any re-align of
an already-harvested zone then silently ran with a partially ungrouped camera set. **PD-4
and PD-4a both re-aligned zone_1 in that state, so their "collapse" results (669 and 782 of
4,540) are confounded.** Fixed by `camera_registry.ensure_calibration_sidecars()`, which
every A/B driver now calls before each align. [VERIFIED: FINDINGS 2026-07-25]

---

## 7. Behavior: what alignment actually does at production scale

### 7.1 Registration rates actually measured

| Dataset / zone | Images | Registered | % | Components | Wall clock |
|---|---:|---:|---:|---:|---|
| NA167 zone_13 (34 wca + 904 zeuss) | 938 | — | 93.4 % | — | 11.5 min |
| NA167 zone_6 (A1, `-addFolder`) | 1,610 | 1,533 | 95.2 % | 1 | 61.6 min |
| NA167 zone_6 (A2, `.imagelist`) | 1,610 | 1,534 | 95.3 % | 1 | 97.8 min |
| NA167 zone_4 (A1, folder) | 1,596 | 1,438 | 90.1 % | 1 | 24.3 min |
| NA167 zone_4 (A2, imagelist) | 1,596 | 1,453 | 91.0 % | 1 | 20.8 min |
| NA167 zone_14 solo | 1,476 | — | **FAILED 4/4** | — | 30.8–54.6 min to failure |
| NA167 sequential grow 6→14→4 | 4,131 | 3,906 | 94.6 % | 1 | 444 min |
| NA167 joint align | 4,131 | 3,904 | 94.5 % | 1 | 168.8 min |
| H2023 production zone_1 | 4,540 | 4,391 / 4,392 | 96.7 % | 2, then 9 | — |
| H2023 production zone_2 | 976 | 920–928 | 94.3–95.1 % | 3 | — |
| H2023 fresh zone_1 | 4,540 | 4,405 | 97.0 % | 3 | 87 min |
| H2023 fresh zone_2 | 852 | 101 | 11.9 % | 1 | ~8 min |
| H2023 fresh zone_3 | 124 | 102 | 82.3 % | 1 | ~4 min |
| H2023 PD-6 zone_1 (Division + loose + sidecars) | 4,540 | 4,394 | 96.8 % | 2 | 67.7 min |
| H2023 zone_2 re-aligned (PD-2b config) | 852 | 812 | 95.3 % | 4 | 10.5 min |
| H2024 baseline (5 zones) | 9,835 | 8,709 | 82–93 % / zone | 16 | — |
| H2024 v2 (5 zones) | 9,835 | 8,781 | — | 14 | — |
| smoke `mini_a` / `mini_b` | 120 / 120 | 118 / 62 | 98 % / 52 % | 1 / 2 | ~2 min each |

[VERIFIED: FINDINGS, MERGE_TEST_PLAN, docs/history/FRESH_RUN_2026-07-24.md, HANDOFF, 2026-07-21 …
2026-07-28]

### 7.2 Registration is independent of how images were added

Folder vs imagelist on identical zones: **95.2 % vs 95.3 %** (zone_6) and **90.1 % vs
91.0 %** (zone_4). The difference is inside run-to-run noise. Choose the input mechanism
for path-identity reasons (an imagelist references images at their original paths, which is
what makes shared-camera merging possible), not for registration.
[VERIFIED: NA167 wave-1 cells A1 vs A2, 2026-07-23]

Note the **runtime** did differ substantially between the same pairs (61.6 vs 97.8 min;
24.3 vs 20.8 min) in both directions — that is §7.3's variance, not an input-mode effect.

### 7.3 Runtime varies ~3× with scene character at equal image count

zone_6 (61.6 / 97.8 min) vs zone_4 (24.3 / 20.8 min) — both ~1.5 k frames, same GPU, each
run twice. **Budget by zone, not by image count.**
[VERIFIED: NA167 #20, 2026-07-23]

### 7.4 Memory

| Scenario | Peak |
|---|---|
| per-zone align, ~1.5 k images | ≤ ~60 GB |
| joint align, 4,131 images, 192 GB box | ~165 GB (27 GB commit headroom left) |
| 4,540-image align, production box | ~11 GB RAM + 4 GB VRAM in the instance |
| extrapolated joint align of a 19 k-image dive | **~700 GB — chunking is mandatory** |

[VERIFIED: NA167 #19, 2026-07-24]

Measurement caveat (owner-caught): workflows run **multiple** `RealityScan.exe` processes
(the persistent instance plus transient helpers). A "2.2 GB during a 4,540-image align"
reading was a 30 MB transient. Identify the instance by largest working set or tracked PID
before quoting a memory number. [VERIFIED: FINDINGS 2026-07-24]

Sequential growth vs joint align give **identical quality and opposite resource winners**:
B (grow) 94.6 %, 444 min, ≤60 GB; C (joint) 94.5 %, 169 min, ~165 GB — 2.6× time vs 2.7×
memory. [VERIFIED: NA167 #19]

### 7.5 Determinism

**Fragmentation is strongly nondeterministic; total registration is not.** zone_1
(4,540 images, identical settings, sidecars, inputs) aligned to **2 components / 4,391
cameras** in one run and **9 components / 4,392** in another.

**Component structure cannot be relied on across runs — only manifest-tracked image sets
can.** [VERIFIED: FINDINGS 2026-07-24]

Corollaries already stated: a free re-align moves every camera and drops 1–2 marginal ones
(§1.3); new components are named `Component N` with **unstable N** (observed 5, 9, 0, 3, 4
across two zones) [VERIFIED-as-observation] — so rename immediately after selecting, and
never key anything on a default component name. Whether `-align` updates an existing
component *in place*, keeping its name, when it only grows is not established
[OPEN: cell U6, never run].

### 7.6 Multi-component terminal states are correct outcomes

Governing owner intent: a zone containing two discrete physical features surveyed in one
dive **should** end as more than one component. Zones are batched on image density and are
blind to feature boundaries. "As big as it can get" is judged **per feature**; no
deletion/export/success logic may be size-based — only containment-based (no unique images)
deletion is ever legal. A maximal-fraction success target misreads disjoint features as
merge failure. [VERIFIED-as-owner-intent: FINDINGS 2026-07-24]

The arithmetic instance of this: H2023's hull ∩ bow = **zero shared basenames**, so no
mechanism can ever fuse them, and the ceiling on the maximal component is 3,720/4,600 =
**80.9 %** — below both `--target` values ever used (0.85, 0.83)
[VERIFIED: `component_analysis.merge_plan` over 12 zone manifests, pure analysis].

### 7.7 Growth: what a second pass actually buys

| Zone | Ground truth |
|---|---|
| zone_1 | **Every re-solve pass shrinks a weakly-connected fragment set.** Global re-align and all 8 component passes were rejected and rolled back (c7's pass lost 51 images); final 4,429/4,540 (97.6 %), 148 orphans. For fragmentation like zone_1's, visual growth is exhausted immediately. *(The source's own two numbers do not reconcile — 4,540 − 4,429 = 111, not 148 — so at least one of them is scoped differently, most likely unique-image vs total-file counting across the 20 % batcher overlap. Quote the ratio, not the orphan count.)* |
| zone_2 | 928/976 (95.1 %), **zero real gains** — honest convergence after one sweep. Three components remain **by design**: the northern strip has no visual ties. |

[VERIFIED: FINDINGS 2026-07-24]

Checkpoint/rollback was validated in anger: a growth run killed mid-pass was fully recovered
by copying the "initial" `.rsproj` bundle checkpoint back over the scene
[VERIFIED: FINDINGS 2026-07-24]. `-quit` without saving leaves the `.rsproj` bundle
**byte-stable** across load/delete/export cycles (hash-verified twice), which is what makes
the destructive identity harvest safe [VERIFIED: cells U15/U16, 2026-07-23].

---

## 8. Failure modes and workarounds

### 8.1 A standalone zone that fails 0x8000FFFF while the same images align fine inside a growing scene

**Observation.** NA167 `zone_14` (1,476 images) failed standalone alignment
**deterministically, 4/4**, at 30.8–54.6 minutes, always with process result
`2147549183` = `0x8000FFFF` ("unexpected program state"). The same 1,476 images aligned
**fine** inside a growing three-zone scene (94.6 % overall, single component).

**The real reason line, captured only because the driver snapshotted the app log
immediately:**

```
Detected 40000 features in image '…_frame0.jpg'.
Feature detection completed in 9 seconds.
Reconstruction failed after 1449.365 seconds.
Processing failed: Unexpected program state.
  [Internal error MSS_STR001]
  [\0x13011\0x13010\0x10001\0x4999\0x10001]
```

[VERIFIED: `testing/results/z14_forensic_rslog.txt`; NA167 #17/#18/#27 / B8, 2026-07-23/24]

**Data exonerated**: full-pixel decode of all 1,476 frames, zero MD5 duplicates, zero
near-black or featureless frames (Laplacian), clean nav, normal motion profile, bracketed
by healthy neighbours. Feature detection itself completed in 9 s. The failure is in the
**reconstruction** phase and is specific to solving this image set as a *standalone scene*.

**Cause: not established.** It is a solver bug triggered by this scene's structure.
[OPEN: never reported to Epic — HANDOFF P1 item 8. The forensic log is the report artifact.]

**Production rule: when a zone fails alignment solo, GROW IT FROM AN ALIGNED NEIGHBOR — do
not retry solo.** [VERIFIED-as-workaround: NA167, 2026-07-24]

The grow shape is `-add <list> → -importFlightLog → -align`, repeated per zone in one
scene:

```bat
:grow
call :run -add "%~1"
if not "%~2" == "" call :run -importFlightLog "%~2" "%flight_log_params%"
call :run -align
exit /b 0
```

[VERIFIED-by-inspection: `RS_CLI/Scripts/SequentialAlignGrow.bat`]

**But verify camera counts after every grow step** — growth is state-sensitive and can
degrade existing structure (§1.3). [VERIFIED: NA167 #29]

Note also what the forensic log proves incidentally: the failing run applied **no `sfm*`
settings at all** (the log's only `set` commands are `app*`), and detected exactly
**40000** features per image — the documented `sfmMaxFeaturesPerImage` default. That run
was on instance defaults, which is why "never align on instance defaults" became policy.
[VERIFIED-by-inspection: same log]

### 8.2 `-addFolder` silently adds nothing

Without `appIncSubdirs=true`, `-addFolder` over a zone tree whose images live in per-camera
or `preprocessed_images` subfolders added **0 layer images**; every flight-log row then
failed `err:18002`, and the whole thing was a 25-second "successful" run. The cause was
visible only in the app log (`Added 0 layer images`).

`-set "appIncSubdirs=true"` before **every** `-addFolder`, no exceptions.
[VERIFIED: FINDINGS 2026-07-23] [CONTRADICTED-adjacent: an earlier NA167 run appeared to
recurse without the key; reconciled as flag-dependent, not build-dependent — the NA167 run
had it set by the fixed workflow.]

### 8.3 Flight-log import raises a warning-class failure that is benign

`-importFlightLog` reports `err:18002` / `0x820000FF` when the log references images not in
the scene. The trajectory itself imports fine. Verified by matching all 102 "not found in
the current scene" images against every component manifest: **zero overlap** — they are
exactly the unregistered remainder. Filter logs to the scene's images when aligning
subsets, or tolerate the code. [VERIFIED: FINDINGS 2026-07-21 and 2026-07-25]

### 8.4 The scene resolves through a directory junction and no XMP is written

**RealityScan writes no XMP sidecars when a scene's images resolve through a reparse point
(directory junction), and reports success.** Four baseline components on real paths
harvested exactly 267 files (= 116+94+57); the same workflow on junction-rooted components
harvested **zero**, silently, across 18 attempts and 5 h 12 m of correct GPU work.

[VERIFIED: FINDINGS 2026-07-27] [UNDOCUMENTED: no Epic coverage of reparse-point behavior]

Because the registration census *is* the pose-sidecar count, this failure mode reads as
"nothing aligned". Fix verified: replace per-zone junctions with real directories of
hardlinked `.jpg` plus **copied** `.xmp` (deliberately not hardlinked, so a v2 write cannot
corrupt the baseline's). No re-align was needed [VERIFIED: FINDINGS 2026-07-28].

A related enumeration trap: PowerShell 5.1 `Get-ChildItem -Recurse` does **not** descend
into junction *children* (0 vs 9,835 `.xmp` on the same tree via its real path), while
Python's `os.walk` crosses junctions in both directions.

### 8.5 An empty harvest beside a non-empty export is an instrument failure

Adopted rule: abort the run rather than score it as "nothing fused"/"nothing aligned" —
that shape silently discarded 5 h 12 m across two junction-blinded runs.
[VERIFIED-as-fix: FINDINGS 2026-07-28]

### 8.6 A leftover selection empties selection-driven exports

Flight-log import leaves its matched images **actively selected**, and selection-driven
exports under `-silent` then export **nothing** — the "Export Selection" dialog is
auto-answered. An XMP export completed in 0.057 s instead of 20.5 s.
`-deselectAllImages` before every export is mandatory.
[VERIFIED: FINDINGS 2026-07-23] [UNDOCUMENTED: the Help does not warn that import leaves a
selection]

### 8.7 Result codes an align can produce

| decimal | hex | meaning established here |
|---|---|---|
| 0, 1 | — | routine success (result code 1 is benign and common) |
| 2181038335 | `0x820000FF` | warning class; e.g. `-importFlightLog` err:18002 |
| 2147942487 | `0x80070057` | `E_INVALIDARG` — empty/no-op selection paths |
| 2147549183 | `0x8000FFFF` | generic "unexpected program state" — a broken `-set` **and** a genuine align failure emit the identical code |
| 2147942512 | `0x80070070` | `ERROR_DISK_FULL` — RealityScan's **cache** disk, not necessarily the project disk |
| 3 | — | crash; minidump `RealityScanCrash-YYYYMMDD-HHMMSS.dmp` in the `-silent` directory |

[VERIFIED: FINDINGS 2026-07-23 … 2026-07-29]

The errors marker carries **only the numeric code**, never the `err:NNNN` text — that
exists only in `RealityScan.log`. Tolerant handlers must match codes.
[VERIFIED: FINDINGS 2026-07-23]

### 8.8 Cache disk, not project disk

The RealityScan cache is placed by the **drive of the path given** and does not move when
the project moves. `D:\rccache` reached 1,089 GB and refilled 197 GB of freshly-cleaned
space within one run while the **project** drive showed 773.9 GB free.
[VERIFIED: FINDINGS 2026-07-26] Epic's guidance: do not hand-delete cache files; free
space on the cache disk or change the cache disk [OFFICIAL: Epic "Out of Disk Space"].
Pin it explicitly for long aligns:

```bat
-set "appCacheLocation=Custom" -set "appCacheCustomLocation=E:\rscache"
```

---

## 9. Component control during alignment

Component *merging* is the sibling document's subject. What follows is only what governs
components **as an output of `-align`**.

### 9.1 `-setMinComponentSize <n>` — deprecated, still mandatory

[OFFICIAL: appbasics/allcommands] "Specify the minimal component size for export when
using the `exportLatestComponents` and `exportXMP` commands. The default value is 5."

[VERIFIED: NA167 #22 / B11, 2026-07-24] The app logs that the command **"will be removed in
the next release"** (read out of a per-cell `RealityScan.log` snapshot) — and it is still
required, because **without it, components under the default threshold 5 are silently
excluded from selection AND from XMP export.**

Its reach is therefore wider than the doc sentence: it gates
- `-exportLatestComponents` [OFFICIAL],
- `-exportXMP` [OFFICIAL],
- component **selection** [VERIFIED],
- and hence the registration census, because the census *is* the pose-sidecar count.

Production values: `50` for per-zone aligns (keeps every meaningful pocket, drops noise);
`1` immediately before an export that must not lose anything
[VERIFIED-by-inspection: `AlignZone.bat` arg 6 default 50; `AlignImageList.bat` and
`SequentialAlignGrow.bat` use `-setMinComponentSize 1`].

### 9.2 "Small components" is a GUI concept with no CLI equivalent

[OFFICIAL: appbasics/smallcomponents] Components below a threshold are grouped into one
expandable entity in the 1Ds view, with three controls: **Include smaller than** (default
**3**), **Exclude bigger than**, **As small as a percentage of inputs**. A
"Delete all small components" button exists, and the action is undoable.

No command in the 2.2 master table exposes these thresholds or that bulk delete
[INFERRED from a full sweep of appbasics/allcommands — no probe run]. The CLI route to the
same outcome is `-setMinComponentSize` for export gating plus
`-selectComponent <name>` / `-deleteSelectedComponent`, or `-deleteComponent <index>`
(0-based).

### 9.3 Component selection and surgery commands

| Command | Behavior |
|---|---|
| `-selectMaximalComponent` | Select the largest component. [VERIFIED] **silently no-ops on an empty scene** — loop terminals must be file-existence checks, not error checks. |
| `-selectComponentWithLeastReprojectionError` | Select the component with the smallest Mean error [pixels] [OFFICIAL]. Exists in this build [VERIFIED: NA167 B11]. **Never used here** — component choice is by camera count. This is the only CLI primitive that ranks components by quality. |
| `-selectComponent <name>` | [VERIFIED] resolves manifest component names in an **assembled** project (components imported from `.rsalign` and renamed before export); silently no-ops in zone scenes, which were saved pre-rename. |
| `-renameSelectedComponent <name>` | [VERIFIED] silently no-ops on an empty scene; the **following** operation is what fails. |
| `-deleteSelectedComponent` / `-deleteComponent <idx>` / `-deleteAllComponents` | all exist in this build [VERIFIED: allcommands sweep 2026-07-23]. |
| `-selectAllComponents` | **DOES NOT EXIST** in 2.2 — fails `0x82000060`. It had lived unnoticed in a legacy script. [VERIFIED: NA167 #13 / B2] |

**There is no CLI query for "how many components are in the scene."** The peel-loop
exhaustion signal is a *tolerated* failure: `-selectMaximalComponent` on an empty scene
silently no-ops and the following `-renameSelectedComponent` fails `E_INVALIDARG`
(`0x80070057`) "in 0 seconds". [VERIFIED: FINDINGS 2026-07-24] [UNDOCUMENTED]

### 9.4 Getting per-component membership out of an align

`-exportLatestComponents <dir>` exports **all** components of the last alignment (gated by
`-setMinComponentSize`) [OFFICIAL + VERIFIED]. Component `.rsalign` files are ~0.7 GB per
~1.5 k cameras and are opaque `TBSM` binary — **there is no readable camera list**
[VERIFIED: NA167_SESSION_NOTES §1]. Membership must come from the XMP census.

The naming rule that makes membership recoverable:

- `-exportXMP` writes **stem-named** sidecars `<stem>.xmp`;
- `-exportXMPForSelectedComponent` writes **ordinal** sidecars `00000.xmp`, `00001.xmp`, …
  in every observed context.

[VERIFIED: FINDINGS 2026-07-23, B10 final form — four consistent datapoints]
[SUPERSEDED: an earlier session-based hypothesis that stems require the live aligning
session]

Hence `AlignZone.bat`'s **successive-difference identity loop**: each lap exports the stems
of *all* remaining components, harvests them into `identity_r<K>`, then exports + deletes
the maximal component. `members(c<K>) = stems(r<K>) − stems(r<K+1>)`. The scene is saved
*before* the loop and the instance quits **without saving**, so the loop is destructive in
memory only.

```bat
:identityLoop
if %comp_index% GEQ 20 goto :identityDone
call :run -deselectAllImages
call :run -exportXMP
powershell -NoProfile -Command "Get-ChildItem -LiteralPath '%input_dir%' -Recurse -Filter *.xmp | Where-Object { Select-String -LiteralPath $_.FullName -Pattern 'xcr:Position' -Quiet } | Move-Item -Destination '%output_dir%\identity_r%comp_index%' -Force"
set "have_poses="
for %%F in ("%output_dir%\identity_r%comp_index%\*.xmp") do set have_poses=1
if not defined have_poses goto :identityDone
call :run -selectMaximalComponent
call :run -renameSelectedComponent "%scene_name%_c%comp_index%"
call :run -exportSelectedComponentDir "%output_dir%"
if not exist "%output_dir%\%scene_name%_c%comp_index%.rsalign" goto :identityDone
call :run -deleteSelectedComponent
set /a comp_index+=1
goto :identityLoop
```

[VERIFIED-by-inspection: `RS_CLI/Scripts/AlignZone.bat` lines 129–148. **Abridged**: every
`call :run` in the real file is suffixed `|| goto :fail`, and the loop `mkdir`s
`identity_r<K>` before the harvest. Reproduce those if you lift this block.]

Two properties: `identity_r<K>` in an **align** scene is cumulative (rK = laps K..end), so
component K's own sidecars are the difference rK − rK+1; in a **merge** scene rK is
component K alone [VERIFIED: FINDINGS 2026-07-28]. And `-exportSelectedComponentDir` names
the file after the **component**, not the scene — hence the rename first
[VERIFIED: NA167_SESSION_NOTES §1; cell U16 PASS].

---

## 10. Quality assessment: what numbers mean a bad solve

### 10.1 Epic's own quality ladder

[OFFICIAL: tools/alignquality] "One basic and very rough way to assess the alignment
quality … is to look at the generated cameras' and points' count, and at values in the
Alignment report … Further, you have the possibility to display matches among your images,
which is more accurate … Another, even more apparent and thorough, (and probably the best)
way to check the alignment quality is to use the Quality Analysis tool."

| Metric [OFFICIAL: tools/alignquality] | Meaning | Epic's stated target |
|---|---|---|
| cameras aligned per component | "The ideal situation is when all of them are aligned in one model." | all in one |
| points count | "The higher the number of generated points of a model, the better." | higher |
| **Total projections** | how many times 3D points are seen in images = average track length × points count | higher |
| **Average track length** | "in how many images, on average, a point appears. The higher the number, the better interconnected a scene is." | higher |
| **Maximal error (pixels)** | greatest error of a point projection | — |
| **Median error (pixels)** | "The smaller, the better. **Ideally under 0.5 px.**" | < 0.5 px |
| **Mean error (pixels)** | "The smaller, the better. **Ideally under 0.5 px.**" | < 0.5 px |
| **Geo-referenced** | whether the scene is georeferenced, and by which process (alignment or update) | — |
| **Metric** | whether the scene uses correct measurement units, and when it was set | — |
| **Alignment time** | elapsed to completion | — |

Epic names four checks on that page, in increasing thoroughness: camera/point counts and
the Alignment report → **Show Matched Points** (CTRL+M; "the greater the number of
(correct) matches among images, the better quality of their alignment")
[OFFICIAL: tools/showmatches] → the **Lens Distortion** overlay in the 2D image-view
ribbon ("verify if the distortion grid is realistically bent") → **Quality Analysis**, "and
probably the best", with Tie point quality / Mesh quality / Advanced
[OFFICIAL: tools/qualityanalysis]. **Advanced Quality Analysis** adds Camera relations,
Point cloud uncertainty and Misalignment detection, parameterised by Component
connectivity, Apical angle, Feature consistency, Match count, Minimal matches and Maximal
matches [OFFICIAL: tools/inspection].

**No command in the master table invokes any of these tools** [INFERRED from a full sweep
of appbasics/allcommands; not probed]. That is *not* the same as "their numbers are
unreachable headless" — an earlier version of this document said so and it was wrong.
Three of the shipped report templates call exactly the underlying function sets, and
`-exportReport` is a delegable CLI command (§10.3):

| Interactive tool | Report function set that carries its data | Shipped template that calls it |
|---|---|---|
| Advanced QA → **Misalignment detection** | `$ExportMisalignmentPoints` (`index`, `misalignment`), `$ExportMisalignmentCameras` (`cameraSfmImage`, `connectionCount`), `$ExportMisalignmentCameraConnections` (`neighborSfmImage`, `connectionStrength`) | `Misalignment.html` |
| Advanced QA → **Camera relations** | the same camera/connection functions above — `connectionStrength` is the per-edge match count the Camera-relations view colours by | `Misalignment.html` |
| QA → **Tie point quality** | `$TiePointsHistogram( componentGUID, stepSize, stepCount, … )` (histogram of *maximal* per-tie-point projection error, px) and `$TracksStats( componentGUID, stepSize, stepCount, … )` (track-length histogram); both yield `histIndex` `histCount` `histValue` `histCumsum` `histTotalSum` `histMaxCount` | `SelectedComponentsTiePointsStats.html` |
| Advanced QA → **Point cloud uncertainty** / camera uncertainty (§10.2) | `$ExportRelativeCameraPositionUncertainty` + `$CovToEllipse2D` | `ComponentAccuracyReport.html` |

[OFFICIAL for the function/variable names: appbasics/reports_fav_points,
reports_fav_cameras] [VERIFIED-by-inspection of the shipped templates in
`C:\Program Files\Epic Games\RealityScan_2.2\Reports\`, 2026-08-04]
[OPEN: none of this has ever been executed here — it all rides on `-exportReport` working
headless, which is question 1 of §13.]

Corrected blindness statement: **the interactive tools and their 3D visualisations are on
the headless blindness list; the numbers behind them are not — they are one unproven
`-exportReport` call away.**

### 10.2 Camera uncertainty

[OFFICIAL: appbasics/uncertainty] "The camera uncertainty is a value defining the accuracy
of the cameras' positions … the camera should be in the error ellipsoid during the image
capturing." Relative position uncertainty is X/Y/Z in **project coordinate system units**,
available only for **registered** images, shown in the Selected inputs panel and (for
georeferenced images) as ellipses in map view.

### 10.3 The headless route: `-exportReport`

```
-exportReport <outputFileName.html> <templateFileName> [true|false]
```

"Export a report into a file … using a template … The default templates are stored in the
installation folder\Reports. Use the optional boolean parameter … to export a file with
reports found in the specified template." [OFFICIAL: appbasics/allcommands]

Shipped templates and what each actually calls — **this matters, because picking the wrong
template silently yields a report without the numbers you wanted**
[VERIFIED-by-inspection of `C:\Program Files\Epic Games\RealityScan_2.2\Reports\*.html`,
2026-08-04; counts are `$Function(` occurrences]:

| Template | Alignment-quality functions it calls | Use it for |
|---|---|---|
| `SelectedComponent.html` | `$ComponentStats` **and** `$ComponentSettings` | **The one template that gives mean/median/maximal reprojection error *and* the settings in force.** Requires a selected component (`-selectMaximalComponent` first). |
| `Overview.html` | `$IterateComponents`, `$ComponentStats`, `$ExportProjectInfo` | Whole-project sweep: per-component errors and georeferenced/metric flags without selecting anything. |
| `ComponentAccuracyReport.html` | `$ExportCameras` ×31, `$ExportImagePriors` ×16, `$ExportRelativeCameraPositionUncertainty` ×14, `$ExportControlPoints` ×13, `$IterateImages` ×11, `$ComponentInfo` ×3, `$ComponentSettings` | Per-**camera** work: solved pose vs **prior** pose (the prior-vs-solved deviation oracle §10.5 wants), solved focal/k1..k4/t1/t2, position-uncertainty covariances. **It does NOT call `$ComponentStats`, so it yields no component reprojection error.** The Help calls it "the Registration and Camera Accuracy Report" [OFFICIAL: appbasics/uncertainty]. |
| `SelectedComponentsTiePointsStats.html` | `$TracksStats` ×4, `$TiePointsHistogram` ×4 | Tie-point error and track-length histograms — the Quality Analysis "Tie point quality" numbers. |
| `Misalignment.html` | `$ExportMisalignmentPoints`, `$ExportMisalignmentCameras`, `$ExportMisalignmentCameraConnections` | Misalignment detection and camera-connection strength. Smallest template in the set. |
| `AlignmentView.html`, `MapView.html` | `$IterateComponents` + `$ImportFile` / `$WriteFile` render plumbing | Visual views; not a data source. |
| `SelectedModel.html`, `SelectedOrtho.html` | model / ortho scope | Not alignment. |

Plus per-language subfolders (`en-US`, `de-DE`, …), `images/`, `scripts/`, `styles/`.

**Do not confuse `ReprojectionParams.xml` with anything on this page.** That file in
`RS_CLI/Metadata/` is the **Texture Reprojection** tool's profile (`reprojectionTool_*`
keys, root GUID `{8F3517E3-5632-40FE-BD10-9967EA8F299F}`, consumed by `-reprojectTexture`)
and has nothing to do with alignment reprojection error
[VERIFIED-by-inspection: `RS_CLI/Metadata/ReprojectionParams.xml`; OFFICIAL:
tools/reprojection]. It belongs to the reconstruction/texturing document.

The report variables that expose alignment quality
[OFFICIAL: appbasics/reports_fav_components]:

```
$IterateComponents( componentGUID, componentName, componentCamerasCount )

$ComponentStats( componentGUID, … )
    componentTotalProjection      total image projections
    componentAverageTrackLength   average images per observed 3D point
    componentMaximalError         maximal reprojection error [px]
    componentMedianError          median reprojection error [px]
    componentMeanError            mean reprojection error [px]
    componentIsGeoreferenced      component is geo-referenced
    componentMetric               component is scaled to real dimensions
    componentAlignmentTime        total alignment time

$ComponentSettings( componentGUID, … )
    componentAlignmentEngine, componentAlignmentMode,
    componentMaxFeaturesPerMpx, componentMaxFeaturesPerImage,
    componentDetectorSensitivity, componentPreselectorFeatures,
    componentImageDownscaleFactor, componentMaxFeatureReprojectionError,
    componentUseCameraPositions, componentLensDistortionModel,
    componentFinalOptimization

$ComponentInfo( componentGUID, … )
    componentName, componentId, componentReconstructionId,
    componentCameraCount, componentPointCount,
    componentControlPointCountUsed, componentConstraintCountUsed
```

**Naming trap in Epic's own page.** `$ComponentInfo` *declares* the singular forms
`componentCameraCount`, `componentPointCount`, `componentControlPointCountUsed`,
`componentConstraintCountUsed`, but the worked example immediately below on the same page
uses the **plural** forms `$(componentCamerasCount)`, `$(componentPointsCount)`,
`$(componentControlPointsCountUsed)`, `$(componentConstraintsCountUsed)`. `$IterateComponents`
independently declares `componentCamerasCount` (plural). One of the two `$ComponentInfo`
spellings is wrong and the page does not say which.
[CONTRADICTED: appbasics/reports_fav_components declaration list vs its own example, same
page, same build] [OPEN: write a template that emits both spellings for the same component;
whichever renders empty is the dead one. Free once question 1 lands.]

`$ComponentSettings` is doubly valuable: it is a **read-back oracle for the settings that
were actually in force**, which is the missing half of §2.5. Its variables map onto the
`sfm*` keys as `componentMaxFeaturesPerMpx`↔`sfmMaxFeaturesPerMpx`,
`componentMaxFeaturesPerImage`↔`sfmMaxFeaturesPerImage`,
`componentDetectorSensitivity`↔`sfmDetectorSensitivity`,
`componentPreselectorFeatures`↔`sfmPreselectorFeatures`,
`componentImageDownscaleFactor`↔`sfmImageDownscaleFactor`,
`componentMaxFeatureReprojectionError`↔`sfmMaxFeatureReprojectionError`,
`componentUseCameraPositions`↔`sfmEnableCameraPrior`,
`componentLensDistortionModel`↔`sfmDistortionModel`,
`componentFinalOptimization`↔`sfmFinalModelOptimization` [INFERRED from the names; the
Help defines `componentUseCameraPositions` as "indicates whether GPS positions for camera
centers have been used" and `componentFinalOptimization` as "indicates whether the final
optimization has been used"]. `componentAlignmentEngine` and `componentAlignmentMode` have
no documented mapping and are the likely read-back for the `sfmFeatureDetectionQuality`
detector-id question (§3.7).

Note there is **no** `$ComponentSettings` variable for `sfmImagesOverlap`,
`sfmForceComponentRematch`, `sfmMergeGeoreferencedComponents`, or any camera-prior
accuracy/weight — so the report closes the read-back gap for nine keys, not all of them.
[VERIFIED-by-inspection: the full variable list of appbasics/reports_fav_components]

Per-camera uncertainty is available too
[OFFICIAL: appbasics/reports_fav_cameras]:
`$ExportRelativeCameraPositionUncertainty( cameraImageIndex, … )` yielding
`posUncertCovXX`, `posUncertCovXY`, `posUncertCovXZ`, `posUncertCovYY`, `posUncertCovYZ`,
`posUncertCovZZ`, with `$CovToEllipse2D( Qxx, Qxy, Qyy, … )` to turn them into ellipses.
`ComponentAccuracyReport.html` already calls `$ExportRelativeCameraPositionUncertainty`
(14 sites) and `$ComponentInfo` [VERIFIED-by-inspection of the shipped template].

**Status of this route in this repository: never run.** It is hardening cell **U14**
("per-component reprojection error, headless"), still open, with a stated blocking risk —
`-exportRegistration` **without** a params XML blocks forever headless
[VERIFIED: FINDINGS 2026-07-21], and `-printReport` "does not work with delegation"
[OFFICIAL: appbasics/allcommands], which rules it out under this architecture.
[OPEN — the single highest-value cheap probe in this document. Use **`Overview.html`**,
not `ComponentAccuracyReport.html`: only the former emits `$ComponentStats`, and it needs
no component selected. On the 120-image smoke fixture, with a watchdog:

```bat
set "RS=C:\Program Files\Epic Games\RealityScan_2.2\RealityScan.exe"
set "TPL=C:\Program Files\Epic Games\RealityScan_2.2\Reports"
"%RS%" -delegateTo RS1 -load "F:\smoke\mini_a\mini_a.rsproj"
"%RS%" -delegateTo RS1 -deselectAllImages
"%RS%" -delegateTo RS1 -exportReport "F:\tmp\overview.html" "%TPL%\Overview.html"
"%RS%" -waitCompleted RS1
"%RS%" -waitCompleted RS1
rem  then, for the per-camera prior-vs-solved half:
"%RS%" -delegateTo RS1 -selectMaximalComponent
"%RS%" -delegateTo RS1 -exportReport "F:\tmp\accuracy.html" "%TPL%\ComponentAccuracyReport.html"
"%RS%" -waitCompleted RS1
"%RS%" -waitCompleted RS1
```

If it returns, per-component mean/median/maximal reprojection error, the georeferenced and
metric flags, and nine of the in-force `sfm*` settings become machine-readable — closing
U14 and giving `-selectComponentWithLeastReprojectionError` a measurable basis. Watch for
the `-exportRegistration` failure mode (blocks forever headless without a params XML), and
note `-exportReport`'s own process id is `20567 EXPORT_REPORT`, so a `#timeout` line
carrying `20567` in a progress file is the signal that it hung
[OFFICIAL: tutorials/processids].]

### 10.4 The oracle this pipeline actually uses: pose-sidecar census

**Counting pose-bearing sidecars is a reliable registration census — only registered
cameras get pose entries.** [VERIFIED: NA167_SESSION_NOTES §1; the pipeline's primary
oracle]

Implementation: walk the image tree for `*.xmp`, keep files containing `xcr:Position`,
map stem → image basename. Parse both forms of the position — `xcr:Position` appears as an
**element** (`<xcr:Position>x y z</xcr:Position>`) in current exports and in **attribute**
form in older ones [VERIFIED: FINDINGS 2026-07-28].

Ordinal sidecars (`00000.xmp`) are inert as priors (no image has an ordinal stem) and are
deleted quietly by `camera_registry.sanitize_and_census` [VERIFIED: B10].

### 10.5 Camera counts do not detect a broken solve

This is the most important quality lesson in the repository.

- **Two components holding 82 % of a delivered assembly's cameras were at ~1/5 true
  scale.** Fresh zone_1: c0 (hull main, 3,026 cams) = **0.175** (IQR 0.168–0.186), c1
  (714) = 0.220, c2 (bow, 665) = 1.011. A uniform scale error is **invisible in the
  viewer** — "all components look good" was true, and still is, locally.
- Three independent confirmations that it was a pure **similarity** error, not drift:
  (1) the ratio is constant across scale bands (0.197/0.181/0.185/0.179/0.174/0.174 over
  1–2, 2–4, 4–8, 8–16, 16–32, 32–64 m nav bins); (2) implied ROV speed 0.01 m/s vs nav
  0.08 m/s, while a sound component gave 0.22 m/s ≈ nav 0.21 m/s; (3) the rig as an
  independent ruler — the fixed Cinema–Port baseline measures 1.11–1.21 m in sound
  components but 0.22 m in hull c0 (0.20×), agreeing with the nav-derived 0.175× **without
  using nav**.
- **Reproduced on a different dataset**: H2024 `zone_3_c0`, 1,192 cameras at scale 0.236
  (IQR 0.217–0.253), on a run whose registration looked entirely healthy (8,709 cameras,
  82–93 % per zone, `Success: True` on every zone).
- Intrinsics were **not** the cause: zone_3 solved Cinema 16.408 / Port 15.481, within
  0.2 % of the sound zone_5's 16.448 / 15.506.

[VERIFIED: FINDINGS 2026-07-25, 2026-07-26; HANDOFF 2026-07-27]

The mitigation is `testing/scale_oracle.py` — median solved-vs-nav pairwise-distance ratio
per component, invariant to translation and rotation, validated against a known-good **and**
a known-bad case before use [VERIFIED: FINDINGS 2026-07-25]. Acceptance band in force:
**0.90–1.10**.

Fused components cannot be measured by the stem oracle (merge-scene XMP exports are
ordinal); the correspondence-free variant compares matching quantiles of
distance-from-centroid, validated both directions (known-good 1.045 vs stem 1.023;
0.236-shrunk hull → 0.235) [VERIFIED: FINDINGS 2026-07-28].

### 10.6 Practical bad-solve indicators

| Signal | Reading |
|---|---|
| Mean or median reprojection error ≫ 0.5 px | poor solve [OFFICIAL: tools/alignquality] |
| Low average track length | weakly interconnected scene [OFFICIAL] |
| Registration high **and** component count jumped (e.g. 3 → 8) with identical inputs | fragmentation is nondeterministic; not by itself a defect, but it correlates with the tight-prior failure mode (§6.3) [VERIFIED] |
| Registration ~unchanged, scale ratio outside 0.90–1.10 | the failure counts cannot see (§10.5) [VERIFIED] |
| One camera group's solved focal/k1 far off its siblings — e.g. Port at 11.929 mm with k1 +0.0055 versus 15.48–15.52 and k1 ≈ −0.385 everywhere else | classic focal-vs-radial degeneracy on a long straight run [VERIFIED-as-observation: HANDOFF 2026-07-27] [OPEN: testable by pinning that camera's focal or supplying measured coefficients under Division on that one zone and seeing whether the 8-way fragmentation collapses] |
| Align "completed" in seconds on a large input | almost certainly added nothing — check `Added N images` in the app log (§8.2) |
| A merge "completed" in seconds | no-op; a real fusion of 1–4 k-camera pairs takes ~1 h [VERIFIED] |

---

## 11. Tuning playbook

### 11.1 The production configuration, and why each choice was made

| Setting | Value | Basis |
|---|---|---|
| `sfmEnableCameraPrior` | `true` | required for georeferenced components [VERIFIED-as-decision] |
| `sfmCameraPriorWeight` / `…WeightOrientation` | `10.0` / `10.0` | proven on this data class (NA167 zone_13 93.4 %); fallback 1.0 never exercised [VERIFIED-as-in-use; OPEN: never A/B'd] |
| flight-log position accuracies | **10 / 10 / 1 m** | Bow 2×2: tight (1/1/0.1) fragments and mis-scales [VERIFIED] |
| flight-log orientation | **ON at 15° YPR** | dose-response (5° fragments, 15° gains); removing it destroyed two H2024 zones [VERIFIED-as-decision, attribution flagged] |
| `sfmDistortionModel` | `Division` | best Z3 registration; both optics solved division; global and all-or-nothing [VERIFIED, with the PD-6 attribution caveat] |
| `sfmDetectorSensitivity` | `Ultra` | weak underwater texture [VERIFIED-as-in-use; OPEN: no A/B] |
| `sfmMaxFeaturesPerImage` / `PerMpx` / `sfmPreselectorFeatures` | 50000 / 14000 / 20000 | "more features ⇒ fewer components on low-texture seabed" [VERIFIED-as-decision] |
| `sfmImagesOverlap` | `Medium` | adopted on reasoning, not measurement — see the §3.6 contradiction |
| `sfmForceComponentRematch` | `false` per zone, `true` on merge rungs | merge-stage tool [VERIFIED-as-decision] |
| `sfmMergeGeoreferencedComponents` | `false` per zone, `true` on merge rungs | per-zone components must stay honest [VERIFIED-as-decision] |
| `appIncSubdirs` | `true` before every `-addFolder` | §8.2 [VERIFIED] |
| calibration sidecars | one group per **physical** camera, regenerated before every align | §6.5 [VERIFIED] |
| `-setMinComponentSize` | `50` per zone, `1` before a lossless export | §9.1 |

### 11.2 Escalation ladders that exist in code

`merge_zones.py` `LADDERS` — one variable per rung, and an accepted rung short-circuits the
rest (worth roughly half the wall clock: 68 min vs 122 min on comparable runs)
[VERIFIED-by-inspection + FINDINGS 2026-07-28]:

Two ladders exist over the **same three rungs**, differing only in order.
`merge_first` is the default (`--ladder`); `content_first` runs the two align rungs before
the rigid merge. Verbatim, `merge_zones.py` lines 81–110:

```python
LADDERS = {
    'merge_first': [
        {'label': 'merge_georef', 'mode': 'merge',
         'settings': ['sfmMergeGeoreferencedComponents:true',
                      'sfmEnableCameraPrior:true']},
        {'label': 'align_rematch', 'mode': 'align',
         'settings': ['sfmMergeGeoreferencedComponents:true',
                      'sfmEnableCameraPrior:true',
                      'sfmForceComponentRematch:true']},
        {'label': 'align_rematch_high_overlap', 'mode': 'align',
         'settings': ['sfmMergeGeoreferencedComponents:true',
                      'sfmEnableCameraPrior:true',
                      'sfmForceComponentRematch:true',
                      'sfmImagesOverlap:High']},
    ],
    'content_first': [ ... same three, order 2, 3, 1 ... ],
}
```

Note the `key:value` (colon) encoding: these strings cross a `.bat` argument boundary, so
the `=` would be split by cmd (§2.3). `MergeZoneComponents.bat` converts the colon back
inside the script.

Note the recorded judgment that the `sfmImagesOverlap:High` rung is **not defensible**: it
only widens candidate-pair search, so it can help only where components share content the
matcher skipped, and both observed cases fall outside that [VERIFIED: FINDINGS 2026-07-27].
That judgment rests on the §3.6 reading of the key, which is itself unmeasured.

### 11.3 A tuning order that matches the evidence

1. **Fix the inputs first.** `appIncSubdirs`, calibration sidecars present and correct,
   pose sidecars cleaned, flight log filtered and CRS derived per cruise. Most "alignment
   problems" in this record were input problems.
2. **Loosen priors before touching the solver.** Tight position priors were the single
   largest measured harm (fragmentation + scale, invisible to camera counts).
3. **Distortion model.** Try `Division` on a cheap fixture; Epic's own tip is Division
   first, then Brown, then re-align to optimize.
4. **Detector budget.** Raise `sfmMaxFeaturesPerImage` / `PerMpx` on low-texture scenes
   before raising sensitivity; both cost RAM and time.
5. **Do not re-align a healthy scene for a marginal gain.** Every free re-align moves all
   cameras and can lose a few; zone_1's growth exhausted itself immediately and every pass
   had to be rolled back.
6. **Grow, don't retry.** A zone that fails solo is a solver-state problem, not a data
   problem — grow it from an aligned neighbour and verify counts after each step.
7. **Measure scale, not just cameras**, on every accepted result.

---

## 12. Complete runnable examples

Paths below use the production shape: images at
`F:\na156_h2024\batched_images_by_zone\<zone>`, components out to
`F:\na156_h2024\aligned_components\<zone>`, flight log
`flight_log_<UTMzone>_UTM.txt` beside the images, generated params
`FlightLogParams_<UTMzone>.xml`.

### 12.1 Minimal correct headless align of one zone

```bat
@echo off
setlocal
set "RS=C:\Program Files\Epic Games\RealityScan_2.2\RealityScan.exe"
set "INST=RS1"
set "ZONE=F:\na156_h2024\batched_images_by_zone\zone_3"
set "OUT=F:\na156_h2024\aligned_components\zone_3"
set "LOG=%ZONE%\flight_log_4Q_UTM.txt"
set "LOGPARAMS=F:\na156_h2024\params\FlightLogParams_4Q.xml"

"%RS%" -delegateTo %INST% -newScene

rem  MUST precede -addFolder, or subfolders are silently skipped
"%RS%" -delegateTo %INST% -set "appIncSubdirs=true"
"%RS%" -delegateTo %INST% -addFolder "%ZONE%"
"%RS%" -waitCompleted %INST%

"%RS%" -delegateTo %INST% -importFlightLog "%LOG%" "%LOGPARAMS%"
"%RS%" -waitCompleted %INST%

rem  -align takes NO params.xml: push every alignment key first
"%RS%" -delegateTo %INST% -set "sfmEnableCameraPrior=true"
"%RS%" -delegateTo %INST% -set "sfmCameraPriorWeight=10.0"
"%RS%" -delegateTo %INST% -set "sfmCameraPriorWeightOrientation=10.0"
"%RS%" -delegateTo %INST% -set "sfmCameraPriorAccuracyYaw=10.0"
"%RS%" -delegateTo %INST% -set "sfmCameraPriorAccuracyPitch=10.0"
"%RS%" -delegateTo %INST% -set "sfmCameraPriorAccuracyRoll=10.0"
"%RS%" -delegateTo %INST% -set "sfmDistortionModel=Division"
"%RS%" -delegateTo %INST% -set "sfmDetectorSensitivity=Ultra"
"%RS%" -delegateTo %INST% -set "sfmImagesOverlap=Medium"
"%RS%" -delegateTo %INST% -set "sfmMaxFeaturesPerImage=0xc350"
"%RS%" -delegateTo %INST% -set "sfmMaxFeaturesPerMpx=0x36b0"
"%RS%" -delegateTo %INST% -set "sfmPreselectorFeatures=0x4e20"
"%RS%" -delegateTo %INST% -set "sfmMaxFeatureReprojectionError=1.29999995"
"%RS%" -delegateTo %INST% -set "sfmForceComponentRematch=false"
"%RS%" -delegateTo %INST% -set "sfmMergeGeoreferencedComponents=false"
"%RS%" -delegateTo %INST% -set "sfmAutoReconRegionAfterAlignment=false"
"%RS%" -delegateTo %INST% -set "sfmImageDownscaleFactor=1"

"%RS%" -delegateTo %INST% -align
"%RS%" -waitCompleted %INST%
"%RS%" -waitCompleted %INST%

rem  flight-log import left a selection; clear it or exports come out empty
"%RS%" -delegateTo %INST% -deselectAllImages
"%RS%" -delegateTo %INST% -setMinComponentSize 50
"%RS%" -delegateTo %INST% -exportLatestComponents "%OUT%"
"%RS%" -delegateTo %INST% -exportXMP
"%RS%" -waitCompleted %INST%

"%RS%" -delegateTo %INST% -save "%OUT%\zone_3.rsproj"
rem  wait the save out before quitting: a 4,500-camera scene takes minutes to write
"%RS%" -waitCompleted %INST%
"%RS%" -waitCompleted %INST%
"%RS%" -delegateTo %INST% -quit
```

The double `-waitCompleted` after every long operation is not decoration: `-waitCompleted`
returns **prematurely** when it runs before the instance has picked up the queued command
[VERIFIED: FINDINGS 2026-07-21; OFFICIAL: appbasics/allcommands defines it as "Pause
execution of other commands until the **current** process is finished"]. Production code
adds a grace delay before each wait and a second between them, and then checks
`RS_CLI/Errors/errors_<instance>.txt` for non-zero size — that whole pattern is the `:run`
subroutine reproduced in every workflow `.bat`. This example inlines only the waits; it has
no error check, so a failed `-align` here would fall through to the exports silently.

### 12.2 Align from an imagelist (shared-path components, mergeable by identity)

```bat
"%RS%" -delegateTo %INST% -newScene
"%RS%" -delegateTo %INST% -add "F:\na156_h2024\lists\zone_3.imagelist"
"%RS%" -waitCompleted %INST%
"%RS%" -delegateTo %INST% -importFlightLog "%LOG%" "%LOGPARAMS%"
"%RS%" -waitCompleted %INST%
rem  ... settings as above ...
"%RS%" -delegateTo %INST% -align
```

`.imagelist` is full paths, one per line; CRLF is fine
[VERIFIED: NA167 wave-1 cell A2]. Write it from Python (`encoding='utf-8'`, no BOM) — a BOM
on line 1 of a list file silently invalidates the first entry, and Windows PowerShell 5.1
`Set-Content -Encoding utf8` writes one [VERIFIED: FINDINGS 2026-07-27].

### 12.3 Grow a failed zone from an aligned neighbour

Complete and self-contained (`:grow` is a subroutine, so the script must `goto :quit`
before falling into it):

```bat
@echo off
setlocal
set "RS=C:\Program Files\Epic Games\RealityScan_2.2\RealityScan.exe"
set "INST=RS1"
set "LISTS=D:\na167_h2075\rs_test\lists"
set "ZONES=D:\na167_h2075\rs_test\batched_images_by_zone"
set "LOGPARAMS=D:\na167_h2075\rs_test\merge_test\FlightLogParams_53N.xml"
set "OUT=D:\na167_h2075\rs_test\grown"

"%RS%" -delegateTo %INST% -newScene
rem  ... apply the sfm settings here: SequentialAlignGrow.bat does NOT (see 4.1) ...
call :grow "%LISTS%\zone_6.imagelist"  "%ZONES%\zone_6\flight_log_53N_UTM.txt"  || goto :fail
call :grow "%LISTS%\zone_14.imagelist" "%ZONES%\zone_14\flight_log_53N_UTM.txt" || goto :fail
call :grow "%LISTS%\zone_4.imagelist"  "%ZONES%\zone_4\flight_log_53N_UTM.txt"  || goto :fail

"%RS%" -delegateTo %INST% -setMinComponentSize 1
"%RS%" -delegateTo %INST% -deselectAllImages
"%RS%" -delegateTo %INST% -selectMaximalComponent
"%RS%" -delegateTo %INST% -renameSelectedComponent "grown_6_14_4"
"%RS%" -delegateTo %INST% -exportSelectedComponentDir "%OUT%"
"%RS%" -delegateTo %INST% -exportXMPForSelectedComponent
"%RS%" -waitCompleted %INST%
"%RS%" -waitCompleted %INST%
goto :quit

:grow
"%RS%" -delegateTo %INST% -add "%~1"                        || exit /b 1
"%RS%" -waitCompleted %INST%
"%RS%" -waitCompleted %INST%
if not "%~2" == "" (
    "%RS%" -delegateTo %INST% -importFlightLog "%~2" "%LOGPARAMS%" || exit /b 1
    "%RS%" -waitCompleted %INST%
    "%RS%" -waitCompleted %INST%
)
"%RS%" -delegateTo %INST% -align                            || exit /b 1
"%RS%" -waitCompleted %INST%
"%RS%" -waitCompleted %INST%
exit /b 0

:fail
echo ERROR: grow failed
:quit
"%RS%" -delegateTo %INST% -quit
```

[VERIFIED-by-inspection: `RS_CLI/Scripts/SequentialAlignGrow.bat`; the 6→14→4 grow is the
run that reached 94.6 % including all of solver-bug zone_14. The real script routes every
operation through its `:run` subroutine — the double `-waitCompleted` plus an
`errors_<instance>.txt` size check — instead of inlining the waits as above.]

Note the export uses `-exportXMPForSelectedComponent`, which writes **ordinal** sidecars
(`00000.xmp`, …), so this shape gives a camera *count* but no per-camera identity (§9.4).
The `.bat` file itself must be CRLF: cmd's `call :label` search is byte-offset sensitive
and LF-only files fail intermittently [VERIFIED: NA167 B10 (INT)].

### 12.4 Re-align a subset of a loaded scene

```bat
"%RS%" -delegateTo %INST% -load "%OUT%\zone_3.rsproj"
"%RS%" -delegateTo %INST% -deselectAllImages
"%RS%" -delegateTo %INST% -selectAllImages
"%RS%" -delegateTo %INST% -editInputSelection "inpEnabled=false"
"%RS%" -delegateTo %INST% -deselectAllImages
rem  select the target set: literal full paths only, one call each
for /f "usebackq delims=" %%L in ("F:\...\lists\zone_3_c0.imagelist") do (
    "%RS%" -delegateTo %INST% -selectImage "%%~L" union
)
"%RS%" -delegateTo %INST% -editInputSelection "inpEnabled=true"
"%RS%" -delegateTo %INST% -editInputSelection "aligFeaturesMode=1"
rem  ... apply sfm settings, then align ...
"%RS%" -delegateTo %INST% -align
"%RS%" -waitCompleted %INST%
"%RS%" -waitCompleted %INST%
rem  MANDATORY before any save: a disabled state persists into the file
"%RS%" -delegateTo %INST% -selectAllImages
"%RS%" -delegateTo %INST% -editInputSelection "inpEnabled=true"
"%RS%" -delegateTo %INST% -deselectAllImages
"%RS%" -delegateTo %INST% -save "%OUT%\zone_3.rsproj"
```

Checkpoint the `.rsproj` **and its companion data folder** (the sibling directory named
after the project stem) before this runs; that copy is the only rehearsed rollback
[VERIFIED: `grow_zone.py`; FINDINGS 2026-07-24].

---

## 13. Open questions

Ordered by value per minute of RealityScan time. In-text citations of the form `§13`
point here.

1. **Is `-exportReport` usable headless?** (§10.3, hardening cell U14.) It would make
   per-component mean/median/maximal reprojection error, georeferenced/metric flags, nine
   of the in-force `sfm*` settings, per-camera prior-vs-solved deviation, tie-point error
   histograms and misalignment data machine-readable — closing the quality-oracle gap, most
   of the "silence is not success" gap for `-set` (§2.5), and most of the headless
   blindness list (§10.1) in one call.
   *Probe:* the block in §10.3 — `Overview.html` first (needs no selection, carries
   `$ComponentStats`), then `ComponentAccuracyReport.html` with the maximal component
   selected. Watchdog it: `-exportRegistration` without params blocks forever, so assume
   the risk is real. ~3 min if it returns.
2. **Which direction does `sfmImagesOverlap` move the pair search?** (§3.6 — a live
   contradiction between Epic's prose and this repo's adopted reading, and the basis for
   both the Low→Medium production change and the rejection of the `High` merge rung.)
   *Probe:* align the 124-image zone_3 fixture at `Low` / `Medium` / `High`, everything
   else pinned; record wall clock, registered count, component count. ~12 min total. Wall
   clock alone settles the direction.
3. **Which `s<NNN>l` id is which `sfm*` accuracy key?** (§4.3.)
   *Probe:* `-set "sfmCameraPriorAccuracyZ=99"`, re-export the Alignment Settings panel
   from the GUI, see which entry became `99`. One minute, needs the GUI. Then fix the
   replay filter so the intended accuracies actually ship (§2.6).
4. **Does `sfmFeatureDetectionQuality=RealityScan.FeatureDetector.RSa1` do anything?**
   (§3.7 — the value the GUI writes is not one of the documented values, and parsing is not
   honouring.) *Probe:* toggle the GUI dropdown between High and Normal, re-export the
   panel each time, read the values; then confirm with `$ComponentSettings`'
   `componentAlignmentEngine` / `componentAlignmentMode` read-back once (1) lands.
5. **`sfmDetectorSensitivity` Ultra vs High on this rig.** (§3.1 — Ultra is in force for
   every production align on the strength of reasoning plus a staff caution that it
   manufactures noise points on turbid imagery; no A/B has ever been run.)
   *Probe:* two zone_3 aligns (~8 min total), judged on registered count, component count
   **and** scale ratio.
6. **The intermediate prior-accuracy ladder (3/3/0.5, 5/5/1).** (§6.3 — loose 10/10/1 is
   proven better than tight 1/1/0.1, but is not proven optimal.) *Probe:* two zone_1
   re-aligns at ~70 min each, or run it first on the 665-image bow fixture at a few minutes
   per cell.
7. **Isolate PD-6: Brown3 + explicit-loose accuracies on zone_1.** (§3.9 — PD-6 changed
   three things at once, so the hull scale repair 0.175 → 0.981 is not attributable.)
   *Probe:* one ~70 min zone_1 align.
8. **Re-test `sfmMergeGeoreferencedComponents` with priors-v2 components.** (§3.8 — D1/D2
   fed the flag components georeferenced from position-only priors at 10 m claimed
   accuracy, so the feature's documented premise may never have been met.)
9. **Is `-draft` a useful cheap gate?** (§1.4 — never run here.) *Probe:* `-draft` on the
   1,476-image zone_14 fixture that fails `-align` deterministically. If draft succeeds
   where align fails, draft becomes a cheap pre-flight for solver-bug zones; if it fails
   the same way, that is a sharper bug report for Epic.
10. **`sfmFinalModelOptimization` (non-draft).** (§4.4 — not in the profile, not in the
    Help key table, string present in the binary; the draft doc calls the global
    optimization "strongly recommended for high-precision models".) *Probe:* set it
    explicitly and confirm no `err:7155`; read back via `$ComponentSettings`'
    `componentFinalOptimization`.
11. **`sfmCameraDepthmapWeight`** (§3.2) — undocumented, pinned at `0.05`, meaning unknown.
    *Probe:* A/B on the smoke fixture at 0.0 / 0.05 / 0.5.
12. **`sfmImageDownscaleFactor` on 12 MP underwater stills** (§3.1) — pinned at 1 and never
    varied. *Probe:* one zone_3 align at 2.
13. **Does `aligFeaturesMode` persist across save/reload, and is it strictly per image?**
    (§5.2, cell U3, never run.)
14. **Does `-align` update an existing component in place, keeping its name, when it only
    grows?** (§7.5, cell U6, never run.) It determines how much renaming discipline the
    manifests need.
15. **The Port focal-vs-radial degeneracy** (§10.6) — one H2024 zone solved Port at
    11.929 mm with k1 +0.0055 against 15.48–15.52 / k1 ≈ −0.385 everywhere else, alongside
    8-way fragmentation. *Probe:* pin Port's focal (`inpFocal` + `inpCalibration=2` Fixed)
    or supply measured coefficients under Division on that one zone, and see whether the
    fragmentation collapses.
16. **`-selectImage` regexp dialect** (§5.3) — the Help documents a regexp form; only
    literal full paths select anything. Standing forum-mine item since 2026-07-23; a staff
    reply may explain the discrepancy without any RealityScan time.
17. **Report `MSS_STR001` to Epic** (§8.1) — never done; `testing/results/z14_forensic_rslog.txt`
    is the artifact. No probe needed, only a submission.
18. **Multi-GPU parallel aligns** — single-instance GPU pinning is exercised; two concurrent
    instances on different GPUs is untested. *Probe:* boot RS1 on GPU 0 and RS2 on GPU 1,
    align two small zones simultaneously, confirm marker-file isolation and no cache
    contention.
19. **Is there any CLI access to Quality Analysis / Inspection / Show Matches?** (§10.1.)
    No *command* invokes the tools — that much is settled from the master-table sweep. But
    `Misalignment.html` and `SelectedComponentsTiePointsStats.html` call exactly their
    function sets, so the question reduces to question 1. Rides on the same probe.
20. **Can a camera rig be declared to RealityScan 2.2?** (§5.1b — `inpRig`, `inpRigId`,
    `inpRigIndex`, `inpRigInstance`, `inpRigValid` exist in the binary with no Help
    coverage and no known GUI control.) This is the largest untested lever available to a
    four-camera fixed-baseline rig: a rig constraint would attack fragmentation, scale and
    focal-vs-radial degeneracy (§10.6) at once. *Probe:* `-editInputSelection "inpRigId=1"`
    on the 120-image smoke fixture; if it does not error, escalate to a real cell.
21. **Do `inpInsOfs*` per-image lever-arm keys work?** (§5.1b.) If they do, the rig mount
    could be declared to the application instead of pre-applied into every flight-log row,
    which removes the double-application risk that the unpinned "Camera mount" import
    setting creates (§6.1). *Probe:* same shape as 20, then compare solved poses.
22. **Which `$ComponentInfo` spelling is live — singular or plural?** (§10.3 — Epic's page
    declares `componentCameraCount` and then uses `$(componentCamerasCount)` in its own
    example.) *Probe:* a two-line custom template emitting both; free once question 1
    lands.
