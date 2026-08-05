# Reconstruction, texturing, and export

Everything downstream of a solved alignment: the reconstruction region, mesh
computation and its quality tiers, depth-map controls, model selection and
naming, mesh cleaning/filtering/classification, colorization versus texturing,
unwrapping, texture reprojection, every export command and the parameter-XML
profile each one consumes, parts-based export, the measured resource envelope
at production scale, the third-party publishing targets (Nira, Cesium ion,
Sketchfab), and the report/inspection outputs a headless pipeline needs in
order to have a machine-readable record of what it built. It does **not**
cover: image input, calibration or XMP sidecars; alignment settings and the
`sfm*` key space; components, `-mergeComponents` and component export
(`.rsalign`); georeferencing, flight logs, CRS and the metric-scale oracle;
the CLI execution model (delegation, `-waitCompleted`, progress files, error
markers, result codes). Those live in `01-cli-fundamentals.md` and
`11-automation-patterns.md` (execution layer), `04-image-input-and-handling.md`
and `05-metadata-xmp-and-sidecars.md` (images/metadata), `07-alignment.md`,
`06-georeferencing-flightlogs-and-scale.md` and `08-components-and-merge.md`.
The `-set` key inventory referenced throughout is `03-settings-keys.md`; the XML
profile schemas are `09-xml-parameter-files.md`.

**Applies to:** RealityScan 2.2 (Epic Games), Windows, headless CLI operation.
**Tags:** [OFFICIAL] shipped Help · [VERIFIED] measured in production here ·
[CONTRADICTED] docs vs observation · [UNDOCUMENTED] · [INFERRED] · [OPEN]

---

## Contents

1. [Preconditions and the shape of the stage](#1-preconditions-and-the-shape-of-the-stage)
2. [Reconstruction region (`.rsbox`)](#2-reconstruction-region-rsbox)
3. [Model computation and the quality tiers](#3-model-computation-and-the-quality-tiers)
4. [Depth maps and mesh-calculation settings](#4-depth-maps-and-mesh-calculation-settings)
5. [Model selection, naming and lifecycle](#5-model-selection-naming-and-lifecycle)
6. [Cleaning: triangle selection, filtering, holes, simplify, smooth](#6-cleaning-triangle-selection-filtering-holes-simplify-smooth)
7. [Classification and DTM](#7-classification-and-dtm)
8. [Colorization versus texturing](#8-colorization-versus-texturing)
9. [Unwrapping and the texture budget](#9-unwrapping-and-the-texture-budget)
10. [Texture reprojection](#10-texture-reprojection)
11. [The production model recipe (`GenerateModel.bat`)](#11-the-production-model-recipe-generatemodelbat)
12. [Measured resource envelope](#12-measured-resource-envelope)
13. [Model export](#13-model-export)
14. [Level of detail and 3D Tiles](#14-level-of-detail-and-3d-tiles)
15. [Orthographic projections, DSM/DTM, contours, cross sections](#15-orthographic-projections-dsmdtm-contours-cross-sections)
16. [Other exports from a modelled scene](#16-other-exports-from-a-modelled-scene)
17. [Publishing targets: Nira, Cesium ion, Sketchfab](#17-publishing-targets-nira-cesium-ion-sketchfab)
18. [Reports, quality analysis and inspection](#18-reports-quality-analysis-and-inspection)
19. [Progress IDs for this stage](#19-progress-ids-for-this-stage)
20. [Result codes seen in this stage](#20-result-codes-seen-in-this-stage)
21. [End-to-end runnable examples](#21-end-to-end-runnable-examples)
22. [Open questions](#22-open-questions)

---

## 1. Preconditions and the shape of the stage

A model is always computed **for one component**. Nothing in this document
works until a component is selected. The selection primitives are
`-selectMaximalComponent`, `-selectComponent <name>` and
`-selectComponentWithLeastReprojectionError` (`-selectAllComponents` does not
exist in 2.2 and fails `0x82000060`) [VERIFIED: NA167 B2 / FINDINGS
2026-07-23]. Component selection semantics are in the components sibling
document.

Ordering constraints that are real:

| Step | Requires | Source |
|---|---|---|
| `-calculateHighModel` / `Normal` / `Preview` | a selected component | [OFFICIAL: tutorials/commandline_2 — every reconstruction example runs `-selectMaximalComponent` first; quickstart_6 refuses with "Your project doesn't have any components"] |
| any Model Tool (`-simplify`, `-closeHoles`, …) | a selected **model** | [OFFICIAL: tools/simplify — "becomes active just after you reconstruct and select a model"] |
| `-calculateTexture` | a model; unwrap is computed automatically if absent | [OFFICIAL: tools/texturing] |
| `-reprojectTexture <src> <dst>` | `dst` must already be unwrapped; both models in the **same component** | [OFFICIAL: tools/reprojection] |
| `-exportModel` / `-exportSelectedModel` | at least one model created and selected | [OFFICIAL: tools/export] |
| `-calculateOrthoProjection` | a reconstruction region **and** at least one model | [OFFICIAL: tutorials/orthophoto] |
| `-exportOrthoProjection` | an ortho projection | [OFFICIAL: tutorials/orthophoto_export] |
| `-dtmClassify` | a model | [OFFICIAL: tools/classification] |

Two global cautions that bite hardest in this stage:

- **Verify by artifact, never by exit status.** The repository's single most
  repeated operational rule. A command can complete "successfully" and write
  nothing — the canonical case is a selection-driven export under `-silent`,
  where the auto-answered "Export Selection" dialog turned a 20.5 s XMP export
  into a 0.057 s no-op [VERIFIED: FINDINGS 2026-07-23].
- **The cache disk, not the project disk, is what fills.** Three consecutive
  hull-model failures were all `ERROR_DISK_FULL` on RealityScan's cache volume
  while the project volume showed 773.9 GB free [VERIFIED: FINDINGS
  2026-07-26]. See §12.

---

## 2. Reconstruction region (`.rsbox`)

The reconstruction region bounds where a mesh is computed. It is set
automatically after alignment, sized from the sparse point cloud
[OFFICIAL: tutorials/quickstart_5_reconstructionRegion]. Restricting it speeds
up model computation because excluded parts of the scene are never considered
[OFFICIAL: tools/reconbox].

### 2.1 Commands

[OFFICIAL: appbasics/allcommands "Reconstruction"; tutorials/commandline_2]

| Command | Required | Optional | Behaviour |
|---|---|---|---|
| `-setReconstructionRegionAuto` | — | — | Region from the size of the sparse point cloud. |
| `-setReconstructionRegion` | `box.rsbox` | — | Import a region from a file. |
| `-setReconstructionRegionOnCPs` | `CP1 CP2 CP3 CP4`\|`heightValue` (all four in the Help's *required* column) | — | Base plane from three control points — **CP1+CP2 define the width, CP3 the length**; height from a fourth CP or a numeric value in coordinate-system units (**may be negative**). At least three CPs must exist. Right-handed axes, origin at CP1, X from the origin through CP2. |
| `-setReconstructionRegionByDensity` | — | — | Region on the densest part of the sparse cloud. Best on turntable / low-background datasets. |
| `-scaleReconstructionRegion` | `scaleX scaleY scaleZ` | `origin`\|`center` `absolute`\|`factor` | Defaults `absolute` and `center`. `origin` = the first control point when the region was set on CPs. |
| `-moveReconstructionRegion` | `moveX moveY moveZ` | — | Along the region's own axes, in coordinate-system units. |
| `-rotateReconstructionRegion` | `rotateX rotateY rotateZ` | — | Degrees; the axes rotate with the box. |
| `-offsetReconstructionRegion` | `offsetX offsetY offsetZ` | — | Multiples of the region's own side lengths (`1 2 0.5` = one depth, two widths, half a height). |
| `-exportReconstructionRegion` | `box.rsbox` | — | Write the region to a file. |
| `-setGroundPlaneFromReconstructionRegion` | — | — | Center the model on the grid using the region (rotation + translation). |
| `-resetGround` | — | — | Restore the ground plane's original orientation/position. |
| `-cutByBox` | `inner`\|`outer` | `fillHoles` `true`\|`false` (default `true`) | Filter out triangles inside/outside the region. **Creates a new model.** |
| `-selectTrianglesInsideReconReg` | — | — | Note the abbreviated `ReconReg` spelling. |
| `-selectTrianglesOutsideReconReg` | — | — | Same. |

`-setReconRegionOnCPs` appears as a short alias in one Help example
(`tutorials/commandline_2`) immediately after the long name is documented.
[INFERRED] it is a genuine alias — the Help would not print a broken example —
but it is unverified. Cheapest probe: type it in the GUI console view and see
whether it resolves.

**Units warning** [OFFICIAL: tutorials/commandline_2]: every command that
alters a side length works in coordinate-system units, and behaviour is
**undefined for non-georeferenced projects** (scale-factor scaling is the
exception). Scale the scene with distance constraints first if it is not
georeferenced.

### 2.2 The `.rsbox` file

- Extensions: **`.rsbox`** current, **`.rcbox`** legacy — both are accepted by
  the export/import filter (`mask="*.rsbox;*.rcbox"`)
  [OFFICIAL: `C:\Program Files\Epic Games\RealityScan_2.2\sceneobjects.xml`,
  format id `{669B2D61-1359-4FF3-9C61-06A10A70B073}`,
  `writer="RealityScan.Export.ReconstructionRegion"`,
  `requires="component,reconstruction region"`].
- It is a small XML and is **hand-editable**: "you can first export it from the
  application by clicking on MESH & COLOR / Export / Reconstruction Region and
  then alter the values and parameters inside the `.rsbox` file"
  [OFFICIAL: tutorials/commandline_2]. Its element structure is visible inside a
  `.rsortho` file, which embeds a `<ReconstructionRegion>` block verbatim
  [OFFICIAL: tools/xmlparamsfiles]:

```xml
<ReconstructionRegion globalCoordinateSystem="NONE" globalCoordinateSystemName="NONE"
                      isGeoreferenced="0" isLatLon="0" yawPitchRoll="0 -0 -0">
  <widthHeightDepth>29.8926887512207 29.9313926696777 24.1154346466064</widthHeightDepth>
  <Header magic="5395016" version="2"/>
  <CentreEuclid><centre>-0.098011314868927 0.0846212208271027 12.4095182418823</centre></CentreEuclid>
  <Residual R="1 0 0 0 1 0 0 0 1" t="0 0 0" s="1"/>
</ReconstructionRegion>
```

- [INFERRED] a standalone `.rsbox` written by `-exportReconstructionRegion`
  **is** this element: `tools/xmlparamsfiles` says of the `<ReconstructionRegion>`
  block inside a `.rsortho` that "this part can be obtained by setting the
  reconstruction region manually and then exporting it", and
  `tutorials/commandline_2` says the exported `.rsbox` can have "the values and
  parameters inside" altered by hand. Whether the standalone file is
  byte-for-byte the same (root element, XML declaration) is untested. Cheapest
  probe: `-setReconstructionRegionAuto -exportReconstructionRegion
  D:\probe\box.rsbox` on the smoke fixture and read the file (seconds).

### 2.3 What has no CLI

The **clipping box** (a display-only crop that never loses geometry, used when
RAM/GPU cannot render the whole model) is GUI-only: there is no clipping-box
command in `appbasics/allcommands`. In headless operation use `-cutByBox` or the
`selectTrianglesInside/OutsideReconReg` + `-removeSelectedTriangles` pair
instead [OFFICIAL: tools/clipbox; appbasics/allcommands].

Several other region actions exist as GUI buttons with their own process ids
but have **no command** in the master table [OFFICIAL: tools/reconbox;
tutorials/processids]:

| Process id | GUI action | CLI equivalent |
|---|---|---|
| `21784 SET_RECONSTRUCTION_REGION_CLIPPING_BOX` | Set Region from Clip Box (does not clear the clip box) | none |
| `21781 SET_RECONSTRUCTION_REGION_GRID` | Set Region on Grid (three clicks) | none |
| `21780 SET_RECONSTRUCTION_REGION_ON_RECONSTRUCTION` | Set Region on Reconstruction (four clicks on the model) | none |
| `21782 SET_RECONSTRUCTION_REGION_BEST_NORTH_SOUTH` | *(no Help coverage)* | none [UNDOCUMENTED — id only] |
| `21783 SET_RECONSTRUCTION_REGION_BEST_FIT` | *(no Help coverage)* | none [UNDOCUMENTED — id only] |
| `21815 CLEAR_RECONSTRUCTION_REGION` | Clear Region | none — there is no `-clearReconstructionRegion` |
| `21779 IMPORT_RECONSTRUCTION_REGION` / `21800 EXPORT_RECONSTRUCTION_REGION` | Import / Export Reconstruction Region | `-setReconstructionRegion` / `-exportReconstructionRegion` |

### 2.4 Production practice here

This repository **never sets a reconstruction region**. `GenerateModel.bat`
loads the scene, selects a component and calls `-calculateHighModel` on
whatever region the alignment left behind, then removes unwanted geometry
*post hoc* with the triangle filters of §6 [VERIFIED-by-inspection:
`RS_CLI/Scripts/GenerateModel.bat` — no `-set*ReconstructionRegion*` command
appears anywhere in `RS_CLI/Scripts/*.bat`].
`<entry key="sfmAutoReconRegionAfterAlignment" value="false"/>` is pinned in
`AlignmentParams.xml` line 40 [VERIFIED-by-inspection:
`RS_CLI/Metadata/AlignmentParams.xml`]; [INFERRED from the key name] that also
suppresses the automatic post-alignment region, so whatever region the project
carries at load time is what bounds the mesh. See `07-alignment.md` for the
`sfm*` key space.

[OPEN] whether bounding each component's model with an explicit `.rsbox`
derived from its manifest bbox would cut the runtimes in §12 materially —
`tools/reconbox` says restricting the region speeds up model computation, and
these components are long thin hull sections inside a much larger aligned scene.
Per-component bboxes already exist (`bbox_utm` in the component manifest,
`modules/component_manifest.py`), so the probe is one `-setReconstructionRegion`
+ one `-calculateHighModel` on the 133-camera component (~40 min baseline). Note
the units warning above: this scene **is** georeferenced, so the region commands
are well-defined on it.

---

## 3. Model computation and the quality tiers

[OFFICIAL: appbasics/allcommands "Reconstruction"; tutorials/commandline_2;
tutorials/quickstart_6_computeModel]

| Command | Tier | Process id | Notes |
|---|---|---|---|
| `-calculatePreviewModel` | preview | `20560 CALCULATE_MODEL_PREVIEW` | Always a **singleton** model (single part) [OFFICIAL: appbasics/modelsettings]. Uses the `mvsPreview*` key family. |
| `-calculateNormalModel` | normal | `20561 CALCULATE_MODEL_NORMAL` | "The most commonly used reconstruction" per the quick start. Uses `mvsNormalDownscaleFactor`. |
| `-calculateHighModel` | high | `20562 CALCULATE_MODEL_HIGH` | **REPO** — the only tier this pipeline runs. High Detail always uses full-resolution depth maps (downscale 1) and therefore exposes no image-downscale option [OFFICIAL: appbasics/modelsettings]. |
| `-continueModelCalculation` | — | `20601 CONTINUE_MODEL_CALCULATION` | Continue an unfinished model after a pause or crash. Scans from the last component backwards, and within a component from the last model backwards. **After a crash this only works if autosave was on and the project is loaded with `-load project.rsproj recoverAutosave`** [OFFICIAL: tutorials/commandline_2]. |

Sub-phases surface in the progress feed with their own ids —
`8208 DEPTH_MAPS`, `8240 MESHING`, `8242 CLUSTERING`,
`20736 COMPUTING_MODEL_PARAMS` — so a tail of `progress.txt` can tell depth-map
time from meshing time without a report [OFFICIAL: tutorials/processids].

**`-continueModelCalculation` cannot recover a crash in this pipeline as
configured.** `startRealityScan.bat` boots with `-set "appAutoSaveMode=false"`,
and autosave is the exact precondition the Help names for the post-crash form
[VERIFIED-by-inspection: `RS_CLI/Scripts/startRealityScan.bat` line 61;
OFFICIAL: tutorials/commandline_2]. The *paused* form
(`-load project.rsproj -continueModelCalculation`) needs no autosave, only that
the project was saved before closing — but this pipeline never pauses. The
existing recovery mechanism is instead `:fail` → quit **without saving**, which
was verified to leave the assembly intact (project parses, no zero-byte files,
previously-built models present) after the hull crash [VERIFIED: FINDINGS
2026-07-26].

### 3.1 Splitting depth maps from meshing across machines

`PrecomputeDepthmaps` is a real setting that is **absent from the Help's key
table** and documented only in prose [OFFICIAL: tutorials/commandline_2;
[UNDOCUMENTED] in `setkeyvaluetable`]. Its two states:

| Value | `-calculatePreviewModel` / `-calculateNormalModel` / `-calculateHighModel` behaviour |
|---|---|
| `true` | Depth maps only. They are stored in the **application cache**; **no model is created**. |
| `false` (default) | Depth maps *and* a model. **If depth maps are already in the cache the depth-map phase is skipped** and only meshing runs. |

Epic warns explicitly that the value must be set back to `false` afterwards.
Their worked two-machine split, reproduced with their own commands
[OFFICIAL: tutorials/commandline_2]:

```bat
REM GPU machine: align, depth maps only, save, then move project + cache
RealityScan.exe -addFolder "C:\MyFolder_on_GPU-PC\Images\" ^
  -align ^
  -set "PrecomputeDepthmaps=true" ^
  -calculateNormalModel ^
  -save "C:\MyFolder_on_GPU-PC\Project.rsproj" -quit

REM CPU machine: import the cache, mesh, export, save
RealityScan.exe -load "C:\MyFolder_on_CPU-PC\Project.rsproj" ^
  -importCache "C:\MyFolder_on_CPU-PC\Cache\" ^
  -set "PrecomputeDepthmaps=false" ^
  -calculateNormalModel ^
  -exportModel "Model 1" "C:\MyFolder_on_CPU-PC\Model.obj" "C:\MyFolder_on_CPU-PC\params.xml" ^
  -save "C:\MyFolder_on_CPU-PC\Project_Model.rsproj" -quit
```

Epic's own caveat: **do not put the cache on a network drive**; keep it on a
local SSD on both machines and copy the contents between them
[OFFICIAL: tutorials/commandline_2]. That interacts directly with §12.4 — the
cache disk is the one that fills.

Never exercised here [OPEN: whether `-importCache` also carries the multi-GPU
pinning implications of `RS_GPU_DEVICES`; cheapest probe is the smoke fixture
across two instances].

---

## 4. Depth maps and mesh-calculation settings

GUI home: **MESH & COLOR ▸ Create Mesh ▸ Settings**
[OFFICIAL: appbasics/modelsettings]. **None of these keys is set by this
repository** — `GenerateModel.bat` runs the model tools on instance defaults.
That is a standing gap, not a decision [VERIFIED-by-inspection:
`GenerateModel.bat`; see also `03-settings-keys.md` §6].

### 4.1 Depth-map keys

| Key | Type | Default | Values | Controls |
|---|---|---|---|---|
| `mvsPreviewDownscaleFactor` | int | `4` | `1`,`2`,`4`,… | Image downscale for **preview** depth maps. 1 = 100 % resolution, 2 = each side halved (25 % of pixels). |
| `mvsNormalDownscaleFactor` | int | `2` | `1`,`2`,`4`,… | Same, for **normal**. High Detail has no such option (always 1). |
| `MvsDepthMapsLibVersion` | enum | `1` | `0` = Version 1 (legacy), `1` = Version 2 | Depth-map algorithm version. |
| `mvsFilteringRadius` | float | `3.0` | > 0 | Mesh filtration filter radius, applied in the depth-map stage. Epic: **should not be modified**. |
| `mvsFilteringStrength` | int | `2` | int | Same caution. |

All [OFFICIAL: appbasics/modelsettings + tutorials/setkeyvaluetable].

LiDAR-scan inputs have their own block in the same dialog. Irrelevant to this
pipeline (no LiDAR), listed so an agent does not hunt for them
[OFFICIAL: appbasics/modelsettings + tutorials/setkeyvaluetable]:

| Key | Type | Default | Controls |
|---|---|---|---|
| `mvsMinSampleDistanceLaserScan` | float | `0.002` | Minimal distance between two scan points; density of scan-derived mesh parts. |
| `mvsMaxSampleDistanceLaserScan` | float | `150.0` | Point-cloud cropping radius — points further from the scanner than this are dropped. |
| `mvsMinIntensityLaserScan` | float | `0.03` | Points below this intensity are not used. |

"Filtering based on classification" (which LiDAR classes take part in meshing)
is a GUI control with no key in the Help's table [OFFICIAL: appbasics/modelsettings;
key [OPEN]].

**Per-image depth-map downscale** is a *selection* command, not a `-set` key:
`-setDownscaleForDepthMaps <integer>` on the current image selection
(`-editInputSelection` key `inpImageDepthMapDownscale`). The two multiply:
*per-image downscale × Reconstruction-settings image downscale = the effective
downscale for that image* [OFFICIAL: appbasics/modelsettings, allcommands].

**Maximal depth-map pixel count** (preview and normal; default `0` = ignored)
is described in `appbasics/modelsettings` but **has no key in the Help's key
table**. Epic is explicit that it does **not** override Image downscale —
"both will be applied and may affect resolution" — so the effective depth-map
resolution is `original ÷ (per-image downscale × tier downscale)`, then clamped
to this pixel budget. Binary candidates: `MvsPreviewUndistMaxPixels`,
`MvsNormalUndistMaxPixels` [INFERRED; see `03-settings-keys.md` §6.2].
[OPEN] — settled by changing the GUI field and diffing an exported
`-exportGlobalSettings` config.

### 4.2 Mesh-calculation keys

| Key | Type | Default | Values | Controls |
|---|---|---|---|---|
| `MvsGeometryGpuAccel` | bool | `true` | `true` `false` | GPU acceleration for meshing. |
| `MvsGeometryMarginStyle` | bool | `false` | `true` `false` | Remove marginal triangles at mesh time → non-watertight mesh. **This repo leaves it at the default and removes marginal triangles post hoc instead**, with `-selectMarginalTriangles` + `-removeSelectedTriangles` in `GenerateModel.bat` `[2/8]` [VERIFIED-by-inspection: the key appears in no repo file; the post-hoc filter is the owner-specified recipe, docs/settings-evaluation-2026-07 §7]. The two routes were never compared — **the key is not mentioned anywhere in the repo's settings evaluation** [OPEN]. |
| `mvsMinSampleDistance` | float | `0.0` | ≥ 0, in project CRS units | Minimal distance between two vertices = final model density. **Only meaningful on a scaled/georeferenced scene**; Epic warns to reset it per project. |
| `mvsPreviewMeshStrategy` | enum | `sfm` | `sfm`, `vertexCount` | Preview strategy: use the sparse cloud, or target a vertex count. |
| `mvsPreviewMaxVetrexCountInModel` *(sic)* | int | `10000000` | int > 0 | Preview max vertex count; only with `vertexCount`. |
| `mvsMaxVertexCountInPart` | int | `5000000` | int > 0 | Max vertices per **part**. Epic: do not change. This is what decides how many parts a by-parts export produces (§13.4). |
| `mvsDecimationFactor` | float | `1.0` | > 0 | Detail decimation: larger = fewer triangles. |
| `mvsAdaptiveBlendingStart` | float | `0.45` | 0..1 | Level of detail created; Epic: do not deviate from 0.45. |
| `mvsSmoothingWeight` | float | `1.5` | ≥ 0 | Mesh-time smoothing; behaves like the Smooth tool. |
| `mvsDefaultGroupingFactor` | float | `1.0` | > 0 | Vertex density (2 ⇒ ~4× fewer vertices). Raising it also **prioritises LiDAR over images** in mixed meshing. |
| `mvsLowTextureGroupingFactor` | float | `0.25` | > 0 | Density in low-texture areas. |
| `mvsDefaultNoiseFactor` | float | `1.0` | > 0 | Mesh smoothness; larger = smoother, less detail. |
| `mvsLowTextureNoiseFactor` | float | `2.0` | > 0 | Smoothness in low-texture areas. |
| `mvsImportMaxTrianglesPerPart` | int | `100000000` | int > 0 | Max vertices per part for **imported** models. |

All [OFFICIAL: appbasics/modelsettings + tutorials/setkeyvaluetable].

**Relevance to underwater imagery, untested:** `mvsLowTextureGroupingFactor`
and `mvsLowTextureNoiseFactor` govern exactly the regime this pipeline lives
in (weak texture, turbid water) and have never been varied here.
[OPEN] — one cheap A/B on the 133-camera component (baseline 40.1 min) would
say whether the low-texture defaults are helping or over-smoothing.

Per-image participation in meshing is controlled by `-enableMeshing true|false`
on the current image selection (`inpMeshing`), and `-enableInComponent` for
already-registered images [OFFICIAL: appbasics/allcommands].

---

## 5. Model selection, naming and lifecycle

### 5.1 Commands

| Command | Params | Notes |
|---|---|---|
| `-selectModel` | `modelName` | **REPO**. Exact-name match. |
| `-renameSelectedModel` | `newModelName` | **REPO**, 26 call sites. |
| `-duplicateSelectedModel` | — | Duplicates the model **including textures**. Process id `29 DUPLICATE_MODEL`. |
| `-deleteSelectedModel` | — | **REPO** (intermediate cleanup). |

[OFFICIAL: appbasics/allcommands "Model Tools"; tutorials/commandline_3]

### 5.2 Default names, and implicit selection

New models are named **`Model N`**, N assigned by the application in creation
order. Every model-creating operation increments it, and this is documented by
worked example: `-calculateNormalModel -simplify 100000 -smooth
-calculateTexture` leaves **three** models — "the first one is a normal model,
the second one is simplified, and the third one is simplified, smoothed and
textured at the same time" — and Epic's example then exports `"Model 3"`
[OFFICIAL: tutorials/commandline_3]. (Texturing does *not* create a model; the
third one is the smooth output, textured in place.)

**"By default, the last created model is selected for the next processing"**
[OFFICIAL: tutorials/commandline_3]. This is the rule that makes
`GenerateModel.bat` work at all: the recipe chains `-simplify` →
`-renameSelectedModel` → `-cleanModel` → `-renameSelectedModel` with **no
`-selectModel` between steps**, because each new model is already selected.
`-selectModel` appears only where the chain must jump backwards (the `[8/8]`
re-select of `<tag>_Simplified`) or where an arbitrary name is targeted (the
cleanup loop, the export workflow).

In this pipeline a filter or simplify step leaves a **default-named residual**
behind: the six-component H2024 assembly ended up with exactly **one**
`Model 1` in the whole project, not one per component as had been hypothesised
[VERIFIED: FINDINGS 2026-07-29 export probe]. Both `GenerateModel.bat` and
`ExportDeliverables.bat` therefore sweep `"Model 1"`…`"Model 9"` tolerantly
before saving — the sweep range is headroom, not an observed count.

### 5.3 `-selectModel` matches exactly — the prefix hazard is not real

`<tag>_HighPoly` does **not** match `<tag>_HighPoly_Textured`. The Help says
only "Select a model with the specified name"; empirically, on the H2023 PD6
deliverable the cleanup loop deleted `<tag>_HighPoly` and all three kept models
survived [OFFICIAL: appbasics/allcommands "selectModel modelName"; VERIFIED:
FINDINGS 2026-07-28]. (That same H2023 observation is one side of the
`_HighPoly_Raw` conflict in §5.4 — it is good evidence for exact matching and
inconclusive about raw-model survival.)

Selecting a name that does not exist produces **`err:5601` "model name not
found"**, surfaced through the process trigger as **`2147942487`
(`0x80070057`, `E_INVALIDARG`)** — the generic empty/no-op-selection code
[VERIFIED: FINDINGS 2026-07-29; SURVEY_empirical §1 result-code table].

### 5.4 Renaming rewrites identity — the defect class

`-renameSelectedModel` **removes the old name from the project**. Two
production consequences, both paid for:

1. **`<comp>_HighPoly_Raw` does not survive the production recipe when the
   filter steps fire.** Mechanism: step `[2/8]` renames the selected model to
   `_Cleanup1` as soon as the marginal-triangle filter produces a model, so the
   raw name leaves the project, and `_Cleanup1` is then deleted by the cleanup
   loop. Probed directly on the H2024 assembly:
   `-selectModel cluster_4_a1_c0_HighPoly_Raw` → `err:5601` 'not found'. **The
   models that actually persist per component there are `_HighPoly_Textured`,
   `_Simplified_Textured`, plus one default-named residual**
   [VERIFIED: FINDINGS 2026-07-29].
   *Queued fix if raw retention is wanted:* `-duplicateSelectedModel`
   immediately after `[1/8]`, before the filter chain touches it.

   **The survival is conditional, and the repo record still disagrees with
   itself** [CONTRADICTED, internal]: `:try_filter` skips its rename when the
   selection is empty (§11), so on a mesh with no marginal triangles the raw
   name is never consumed. The H2023 PD6 deliverable is recorded as keeping all
   three models including `_HighPoly_Raw` [FINDINGS 2026-07-28, HANDOFF
   2026-07-29 §"THE DELIVERABLE"], while the H2024 probe found it absent
   [FINDINGS 2026-07-29]. **Do not assume either outcome — check by
   `-selectModel` before depending on the name.** Both `HANDOFF.md` ("Three
   kept models each: `_HighPoly_Raw`, …") and the `GenerateModel.bat` docstring
   ("Models kept … `<comp>_HighPoly_Raw`") **still state the unconditional
   version and are still wrong as shipped** [VERIFIED-by-inspection:
   `GenerateModel.bat` lines 26–30, `HANDOFF.md` line 38, 2026-08-04].
2. **Fixed model names across a per-component loop against one shared project
   created duplicate names**, and name-resolved steps (`-reprojectTexture`,
   delete-by-name) then crossed components with a clean exit status — one
   component's texture could be reprojected onto another's mesh. Every model
   name now carries a per-component `%model_tag%` [VERIFIED: FINDINGS
   2026-07-25].

### 5.5 The benign empty-selection code

**`-selectModel <tag>_HighPoly` reports result code `2147942487` in every
component's cleanup loop** — six for six on H2024. It is whitelisted, the
delete is skipped, evidence is filed as
`expected_select_RS1_<component>_HighPoly.txt`, and the recipe continues,
leaving one cosmetic `_HighPoly` intermediate [VERIFIED-as-observation: FINDINGS
2026-07-29].

The repo's own log carries **two readings of the cause**, in two entries of the
same day: the "Benign, recurring" entry marks it `OPEN` ("cause not
investigated … the name may be consumed by the texture step"), while the "Export
probe facts" entry states the mechanism outright — "the same rename chain is why
`-selectModel <tag>_HighPoly` missed in every component's cleanup loop (it had
become `_HighPoly_Textured` at `[6/8]`)". The second reading is consistent with
the recipe as written: `[6/8]` renames to `_HighPoly`, textures, then renames
again to `_HighPoly_Textured`, so by cleanup time `_HighPoly` genuinely does not
exist and the whitelist is doing exactly the right thing. **Treat the mechanism
as [INFERRED-but-well-supported], not established** — nobody has probed it
(§22 #3).

The tolerant pattern that makes this safe, and the trap it closes:

```bat
:try_delete_model
%RealityScan% -delegateTo %RS_INSTANCE% -selectModel "%~1"
if errorlevel 1 ( echo NOTE: could not delegate & exit /b 0 )
ping -n 3 127.0.0.1 >nul
%RealityScan% -waitCompleted %RS_INSTANCE%
ping -n 2 127.0.0.1 >nul
%RealityScan% -waitCompleted %RS_INSTANCE%
if exist "%ErrorsFile%" (
    for %%A in ("%ErrorsFile%") do if %%~zA GTR 0 (
        move /y "%ErrorsFile%" "%ErrorPath%\expected_select_%RS_INSTANCE%_%~1.txt" >nul
        exit /b 0
    )
)
%RealityScan% -delegateTo %RS_INSTANCE% -deleteSelectedModel
ping -n 3 127.0.0.1 >nul
%RealityScan% -waitCompleted %RS_INSTANCE%
ping -n 2 127.0.0.1 >nul
%RealityScan% -waitCompleted %RS_INSTANCE%
if exist "%ErrorsFile%" (
    for %%A in ("%ErrorsFile%") do if %%~zA GTR 0 (
        move /y "%ErrorsFile%" "%ErrorPath%\expected_delete_%RS_INSTANCE%_%~1.txt" >nul
    )
)
exit /b 0
```

`ExportDeliverables.bat` carries the same subroutine with one addition: it
flattens spaces in the evidence file name (`set "evname=%evname: =_%"`) because
its sweep targets `"Model 1"`…`"Model 9"`.

**The double `-waitCompleted` is load-bearing, not decoration.** An earlier
single short wait could return before the instance picked the select up, so a
no-op `-selectModel` on a missing intermediate left the **previous** selection
live — which at loop entry is the final textured model — and the following
`-deleteSelectedModel` targeted the deliverable [VERIFIED: FINDINGS 2026-07-29,
audit #4].

---

## 6. Cleaning: triangle selection, filtering, holes, simplify, smooth

### 6.1 Triangle selection and filtering

| Command | Params | Behaviour | Process id |
|---|---|---|---|
| `-selectMarginalTriangles` | — | Triangles that enclose the volume but are not part of the reconstruction (watertightness filler). | `21028` |
| `-selectLargeTrianglesAbs` | `edgeSizeThreshold` | Edge length above an **absolute** threshold. | `21029` |
| `-selectLargeTrianglesRel` | `edgeSizeThreshold` | Edge length above `threshold × average edge length`. | `21029` |
| `-selectLargestModelComponent` | — | Triangles of the model's largest connected component. | `21030` |
| `-selectTrianglesInsideReconReg` / `-selectTrianglesOutsideReconReg` | — | Region-based selection. | — |
| `-invertTrianglesSelection` | — | Invert. | — |
| `-deselectModelTriangles` | — | Clear. | — |
| `-removeSelectedTriangles` | — | **Creates a new model with the selected triangles left out** = the Filter Selection tool. | `10 FILTER_SELECTED_TRIANGLES` |
| `-cutByBox` | `inner`\|`outer` `[fillHoles]` | Filter by the reconstruction region; creates a new model. | — |

[OFFICIAL: appbasics/allcommands; tutorials/commandline_3; tools/filter;
appbasics/reconselection]

**`-removeSelectedTriangles` removes the SELECTED set.** This is the fact that
determines the shape of the recipe: the marginal and large-triangle steps
select what should go and filter directly, and **only** the
keep-largest-component step needs `-invertTrianglesSelection` first
[VERIFIED: FINDINGS 2026-07-23].

**`-selectLargeTrianglesRel <t>` is in multiples of average edge length, not
pixels.** The GUI's "30 px" intuition does not transfer. The production value
of `30` (the third argument of `GenerateModel.bat`) **has never been visually
validated on a real model** [VERIFIED: FINDINGS 2026-07-23; [OPEN]].

Filtering "does not modify the reference model" — the original stays in the
project [OFFICIAL: tools/filter]. In this recipe that would mean ~15 live
models per component, which is why the cleanup loop of §5.5 exists.

### 6.2 Holes and manifoldness

| Command | Params | Behaviour |
|---|---|---|
| `-closeHoles` | `maxEdgesCount` (optional) | Removes **surface-bound** holes — those completely enclosed by mesh geometry. A hole with more edges than the parameter is **not** closed. If only part of a model is selected, only holes in the selection are affected. |
| `-cleanModel` | — | Remove non-manifold edges and vertices, close small holes, remove isolated vertices. |

[OFFICIAL: appbasics/allcommands; tools/closeholes; tools/clean_model_check_topo]

**Check Integrity and Check Topology have no CLI commands.** They are GUI-only
*checks* in MESH & COLOR ▸ Analyze, each run on the currently selected model.
The Help's split [OFFICIAL: tools/clean_model_check_topo]: **Check Integrity**
scans for corrupted files (no repair action of its own); **Check Topology**
reports non-manifold edges, non-manifold vertices and hole counts; **Clean
Model** "fix[es] issues with non-manifold vertices/edges, holes, and isolated
vertices identified by the Check Topology tool". So the CLI substitute for the
*repair* half is `-cleanModel` (+ `-closeHoles` for holes above Clean Model's
small-hole limit) — the mapping this repository adopted
[VERIFIED: mapping exercise against the GUI tool docs, FINDINGS 2026-07-23] —
and there is **no CLI substitute for the reporting half**, which is why hole
and non-manifold counts never enter the build record (§18.6). `closeholes`
adds: use Check Topology to find out how many holes a model has.

Their process ids nevertheless exist (`23 CHECK_MODEL_INTEGRITY`,
`28 CHECK_MODEL_TOPOLOGY`) and `mvsPptInspectTopology` exists as a binary
setting string, so a settings-level hook may exist even though no command does
[OFFICIAL: tutorials/processids; [OPEN], see `03-settings-keys.md` §6.2].

### 6.3 `-simplify`

`-simplify` with **no parameter** uses current settings; with a bare integer it
targets that triangle count; with a `params.xml` it uses the exported preset
[OFFICIAL: appbasics/allcommands]. It **creates a new model that loses its
texture and keeps only the coloring** — the reason the production recipe
textures the high-poly model first and then reprojects onto the simplified one
[OFFICIAL: tools/simplify, tools/texturing WARNING].

Params key space (`mvsFlt*` / `simpl*`), Configuration id
`{033AEF62-8421-47A4-81CB-203741113577}`:

| Key | Type | Epic shipped `Settings\SimplifiedExport\simplify.xml` | Repo values | Meaning |
|---|---|---|---|---|
| `mvsFltSimplificationType` | enum int | `3` | `0`, `1` | Which target the simplifier honours. The GUI offers **four** types in this order: `Absolute` (target triangle count — Epic's recommended way), `Relative` (target percentage), `Maximum of absolute and relative`, `Minimum of absolute and relative` [OFFICIAL: tools/simplify]. Repo files pair `0` with `…Abs` only and `1` with `…Rel` only, so `0` = Absolute, `1` = Relative [VERIFIED-by-inspection]. Epic's shipped `3` with **both** Abs and Rel set is consistent with 0-based ordinals over that list, i.e. `3` = "Minimum of absolute and relative" (and `2` = "Maximum") [INFERRED — settled by exporting each of the four from the GUI and diffing]. |
| `mvsFltTargetTrisCountAbs` | int | `1000000` | `500000` | Absolute triangle target. |
| `mvsFltTargetTrisCountRel` | int (%) | `10` | `50`, `70`, `80` | Relative target as a percentage of the source. |
| `mvsFltMinEdgeLength` | float | `0.0` | `0.0` | Affected edges will not be shortened below this; simplification stops at it. |
| `mvsFltBorderDecimationStyle` | enum int | `1` | `1` | GUI: "Simplify the border" vs "Keep border intact". Ordinal mapping [OPEN]. |
| `mvsFltReprojectColor` | bool | `false` | `false` | Reproject the color layer onto the simplified mesh. |
| `mvsFltReprojectNormal` | int | `0` | `0` | Reproject the normal layer. GUI offers a third "Automatic" option. |
| `mvsFltUnwrapTexCount` | int | `0` | `0` | GUI "Maximal texture count" for the simplified model: same as source, or a custom value (`0` = same as source) [OFFICIAL: tools/simplify]. |
| `mvsFltUnwrapTexSide` | int | `0` | `0` | GUI "Texture resolution" for the simplified model (`0` = same as source). The GUI exposes a **custom minimal *and* maximal** resolution when not "same as source"; only one key is present in any repo or Epic file, so the second is [OPEN] — `mvsFltUnwrapMinTexSideCustom` / `mvsFltUnwrapMaxTexSideCustom` exist as binary strings [INFERRED; see `03-settings-keys.md` §8.1]. |
| `simplPreserveParts` | enum int | `0` | `2` | GUI "Part merging": Disable / Enable / Create a singleton. Ordinal mapping [OPEN] — but value `2` is **not** "Create a singleton", because a `_Simplified_Textured` model produced under it exported as **4 parts** [VERIFIED: FINDINGS 2026-07-29]. |
| `simplEqualizeDensity` | bool | *absent* | `true` | Density equalization across parts (prevents visible seams; costs time). Present only in the repo files. [UNDOCUMENTED as a key; the GUI control is [OFFICIAL: tools/simplify]] |

Repo presets, all derived from a single 50 % GUI export:

| File | Type | Target | Used by |
|---|---|---|---|
| `SimplifyNoise_Params.xml` | relative | `70` % | `GenerateModel.bat` step `[6/8]` |
| `SimplifySmooth_80per_Params.xml` | relative | `80` % | `GenerateModel.bat` step `[7/8]`, four times |
| `Simplify50Per_Params.xml` | relative | `50` % | template |
| `SimplifyAutomationParams.xml` | relative | `70` % | unused |
| `Simplify500k_Params.xml` | absolute | `500000` | unused |
| `Simplify25per_Params.xml` | **absolute `500000`** (filename says 25 %) | — | unused; **the filename lies about the content** [VERIFIED-by-inspection, 2026-08-04] |

`SimplifyNoise_Params.xml` (70 % rel) and `SimplifySmooth_80per_Params.xml`
(80 % rel) are **placeholders derived from the 50 % template**; if owner GUI
presets for "noise" and "smooth" simplification exist they should be exported
over these files [VERIFIED-as-caveat: docs/settings-evaluation-2026-07 §7;
[OPEN] standing self-audit item].

Four 80 % passes compound to `0.8⁴ ≈ 40.96 %` of the post-`SimplifyNoise`
count, i.e. ≈ `0.70 × 0.4096 ≈ 28.7 %` of the raw high-poly triangle count
[INFERRED arithmetic from the pinned presets; the absolute triangle counts of
delivered models were never recorded — a `Selected Model Report` (§18) would
capture them].

### 6.4 `-smooth`

`-smooth [params.xml]`. Smoothing **creates a new model; the original is
preserved** [OFFICIAL: tools/smoothing]. Epic's tip: smaller weight + more
iterations to remove noise; higher weight + fewer iterations for mesh
smoothing; "we recommend you use the default values".

Params key space, Configuration id `{585E749B-DC69-4D8C-9114-FA8CBB6F88F3}`:

| Key | Epic shipped `smooth.xml` | Repo | Meaning |
|---|---|---|---|
| `smoothIterations` | `5` | `2` (surface), `5` (peaks) | Number of iterations. |
| `smoothWeight` | `0.5` | `0.2` (surface), `0.5` (peaks) | Weight per iteration; higher = smoother, less detail. |
| `mvsFltSmoothingType` | `1` | `0` | GUI "Smoothing type" = overall strength of the tool. Ordinal mapping [OPEN]. |
| `mvsFltSmoothingStyle` | `3` | `1` (surface), `3` (peaks) | GUI "Smoothing style" = which vertices are smoothed. The Help lists them in this order: **surface / borders / peaks / all (surface and borders)** [OFFICIAL: tools/smoothing]. The repo filenames label `1` = surface and `3` = peaks, which fits **1-based** ordinals over that list (1 surface, 2 borders, 3 peaks, 4 all) [VERIFIED-by-inspection of filenames vs values; the 1-based reading is [INFERRED] and the filename is the only label]. |
| `mvsSmoothing_useIntelligentSmoothing` | `0` | *absent* | **In Epic's own shipped preset but absent from the 2.2 binary — inert** [CONTRADICTED: `03-settings-keys.md` §8.2/§12]. |

**`-smooth` is not used by the production recipe at all.** The three smoothing
presets (`Smoothing_02_2_Params.xml`, `SmoothingSurface_02_2_Params.xml`,
`SmoothingPeaks_05_5_Params.xml`) exist and are unreferenced by any workflow
[VERIFIED-by-inspection: `RS_CLI/Scripts/*.bat`, 2026-08-04]. Two of them are
also **content-identical** — `Smoothing_02_2_Params.xml` and
`SmoothingSurface_02_2_Params.xml` carry exactly the same four entries
(iterations `2`, weight `0.2`, style `1`, type `0`), so the unqualified name is
a duplicate of the surface preset, not a third variant
[VERIFIED-by-inspection, 2026-08-04]. Smoothing in this pipeline happens
implicitly through the four 80 % simplify passes.

---

## 7. Classification and DTM

Classification divides model **vertices** into classes; it is the prerequisite
for a Digital Terrain Model, which is generated during ortho-projection
creation [OFFICIAL: tools/classification].

| Command | Params | Notes |
|---|---|---|
| `-dtmClassify` | `[params.xml]` | Classify the selected model. Process id `42 AI_CLASSIFY`. |
| `-transferClassification` | `[params.xml]` | Transfer classification from label-layer images or LiDAR classes. `47 TRANSFER_IMAGE_LABELS`. |
| `-selectClassification` / `-renameSelectedClassification` / `-deleteSelectedClassification` | name / newName / — | Classification object management. |
| `-selectClass` / `-deselectClass` / `-renameSelectedClass` | className / — / newName | Class management. |
| `-selectVerticesOfSelectedClass` | — | Select the model vertices of the selected class. |
| `-overrideSelectedVertices` | `[className]` | Reassign selected vertices to a class. `48`, `51`. |
| `-setSelectedClassAsGroundForDTM` | `true`\|`false` | "Use as ground for DTM". |
| `-setSelectedClassAsGroundForExport` | — | Set the class's LAS code to Ground (2). |
| `-setSelectedClassLasFormat` | `0`–`12` | ASPRS LAS 1.3 classification code. |
| `-colorModelBySelectedClassification` | — | Colorize the model by class. |
| `-exportClassificationSettings` / `-importClassificationSettings` | `XMLfilePath` | AI Classify panel settings. |
| `-selectClassificationFormat` / `-renameSelectedClassificationFormat` | name | Format management. |
| `-exportClassificationFormat` / `-exportSelectedClassificationFormat` / `-importClassificationFormat` | `.cfd` path | Class-format definitions. |

[OFFICIAL: appbasics/allcommands "Classification Commands"; tutorials/commandline_3]

The DTM classifier enums are documented only inside the `.rsortho` schema
[OFFICIAL: tools/xmlparamsfiles]:

| Field | Allowed values |
|---|---|
| `modelType` | `industrial_complex`, `mixed`, `city`, `nature`, `meadows`, `countryside`, `mountains` |
| `postprocessType` | `none`, `soft_edges`, `hard_edges` |
| `sensitivity` | 0..1 — `0` classifies everything "Artificial object", `1` everything "Ground" |
| `classificationLayerId` | `-1` = compute a new classification during rendering (then `ClassificationParams` is required) |

Class inventory and formats [OFFICIAL: tools/classification]:

- The **AI classifier** (`-dtmClassify`) produces a classification whose format
  is named **`DTM`**, with the predefined classes **`Ground`**,
  **`Artificial Object`**, **`None`** and **`Ignored`**.
- **Transferring labels** (`-transferClassification`) can create custom formats
  with arbitrary colour-named classes. To pull ASPRS classes off imported LiDAR
  instead, set the classification format to **`LAS ASPRS Classification`**.
- Up to **250 classes** per dataset when transferring labels; not every image
  needs a label layer, only enough to cover the areas being separated.
- Reclassifying only part of a model ("Classify selection according to
  settings") is **GUI-only** — no command selects a vertex subset for
  re-classification, only `-selectVerticesOfSelectedClass` (which selects *by*
  class) and `-overrideSelectedVertices`.

`-overrideSelectedVertices`: the Help's table places `className` in the
**required** column while its own prose calls it optional
[CONTRADICTED, minor: appbasics/allcommands table vs its description]. Treat it
as optional (omitting it assigns to the currently selected class) and verify on
first use.

**Nothing about classification has ever been exercised through this CLI.** No
`-dtmClassify` run, no LAS export, no classification format. There is also no
`modelType` in the list that plainly describes a shipwreck on a seabed
[OPEN: whether `nature` or `mixed` produces a usable ground/artificial split on
ROV bathymetry — cheapest probe is `-dtmClassify` on the 133-camera component,
minutes, non-destructive since it creates a new classification object].

---

## 8. Colorization versus texturing

**The distinction** [OFFICIAL: tools/texturing]: coloring creates colors for
model **vertices** only — smaller files, adequate for very dense meshes, and
color is interpolated across polygons. Texturing computes one or more texture
**images** plus a UV mapping (the unwrap), which is more realistic. Coloring
does not create a new model; it colorizes the existing one.

| Command | Params | Notes | Process id |
|---|---|---|---|
| `-calculateVertexColors` | — | Full-quality vertex coloring. **REPO** (`ExportDeliverables.bat`). | `8 MODEL_COLORIZE` |
| `-calculatePreviewVertexColors` | — | Draft coloring. | — |
| `-calculateQualityColors` | — | Vertex colors from **mesh quality values**; the values need not exist beforehand. | — |
| `-calculateTexture` | `[params.xml]` | **REPO**. Unwrap is computed automatically if the model has none; if the model is already textured, only the texture images are recomputed and the existing unwrap is reused. | `7 MODEL_TEXTURE` |
| `-calculateQualityTexture` | — | Texture baked from mesh quality values. | — |
| `-correctColors` | `layerName` | Color correction for all layers or one named layer of the selected component. | `20563 CORRECT_COLORS` (`50 MODEL_BASED_COLORNORMALIZATION` and `20590 COLOR_NORMALIZATION_AUTOMATIC` also exist; which of the three this command emits is [INFERRED] from the names) |

[OFFICIAL: appbasics/allcommands; tutorials/commandline_3; tools/texturing]

[CONTRADICTED, minor] `appbasics/allcommands` lists an optional `params.xml`
for `-calculateTexture`; `tutorials/commandline_3` lists no parameter at all.
The master table is correct — this repository passes a params XML to
`-calculateTexture` in production and it takes effect [VERIFIED: GenerateModel
step `[6/8]`].

### 8.1 Which images are used

Texturing/coloring participation is per image, via the current image selection:

| Command | `-editInputSelection` key | Effect |
|---|---|---|
| `-enableTexturingAndColoring true\|false` | `inpTexturing` | The GUI's `Tx` flag. |
| `-setWeightInTexturing <0,1>` | `inpImageColorsWeight` | Weight of the image in coloring/texturing. |
| `-enableColorNormalizationReference true\|false` | `inpColorRef` | Mark as a color reference (its colors are not changed). |
| `-enableColorNormalization true\|false` | `inpColorNorm` | Participate in color normalization. |

[OFFICIAL: appbasics/allcommands "Commands for Selected Images";
tutorials/editselectioncommand]

Establishing the selection is the hard part headless: **`-selectImage` matches
literal full paths only in this build** — bare regexp, `.*`-wrapped regexp,
glob and regexp with an explicit `set` modifier all silently select nothing, so
composition is a per-image union loop at ~0.1–0.3 s/image
[CONTRADICTED: Help documents `selectImage <imagePath|regexp> [set|union|sub|intersect|toggle]`;
observed by bisection probes U-SEL2…U-SEL8, FINDINGS 2026-07-23]. For a
thousand-image texturing subset that is minutes of pure selection.

### 8.2 Texturing and coloring algorithm keys

GUI home: **MESH & COLOR ▸ Color & Texture ▸ Settings**. Key names and defaults
from `tutorials/setkeyvaluetable` ("Color and Texture Settings" table);
behaviour from `tools/texturing_part2` ("Texturing Algorithm"). Note that
`appbasics/modelsettings` covers only *reconstruction* settings and merely links
onward — do not look for these keys there. **None of these is pinned by this
repository** — see the gap note in §9.3.

| Key | Type | Default | Values | Controls |
|---|---|---|---|---|
| `txtMethod` | enum | `MultiBand` | `Linear`, `MultiBand` | Coloring method. Multi-band splits images into frequency bands: low frequencies carry color/brightness and blend linearly over wide areas, high frequencies carry detail and are joined by an optimized rule. |
| `colStyle` | enum | `VisibilityBased` | `PhotoConsistencyBased`, `VisibilityBased` | Coloring style. Visibility-based = fast and sharp; photo-consistency = slower, more complex. |
| `txtStyle` | enum | `VisibilityBased` | `PhotoConsistencyBased`, `VisibilityBased`, `MosaicingBased`, `MaximalIntensity`, `MinimalIntensity`, `AverageIntensity` | Texturing style. `MosaicingBased` (experimental) textures each surface area from a **single** image and blends at seams — sharper than visibility-based, slower, **not recommended with larger datasets**. The three `*Intensity` styles produce monochrome. |
| `ImageLayerForColoring` | string | `geometry` (or `texture01` if a texturing layer exists) | `geometry/<layer>`, `texture01/<layer>`, `texture2/<layer2>` | Which image layer feeds coloring. |
| `ImageLayerForTexturing` | string | `all` | `geometry/<layer>`, `texture01/<layer>`, `texture2/<layer2>`, `all` | Which image layer feeds texturing. |
| `txtImageDownscaleTexture` | int | `1` | `1`,`2`,`4`,… | Downscale images before texturing. |
| `txtImageDownscaleColor` | int | `2` | `1`,`2`,`4`,… | Downscale images before coloring; `2` is the recommended default. |
| `txtFillInUncoloredParts` | bool | `true` | `true` `false` | Fill uncolored areas. |
| `txtFillInUntextoredParts` *(Epic's typo)* | bool | `true` | `true` `false` | Fill untextured areas. Both the typo'd key and a correctly-spelled `txtFillInUntexturedParts` exist in the 2.2 binary; which is live is [OPEN]. |
| `txtRecolorAfterTexturing` | bool | `true` | `true` `false` | Compute vertex colors from textures after texturing. |
| `MvsDoCorrectColors` | bool | `false` | `true` `false` | Correct colors across the component's images. |
| `MvsIgnoreCorrectColors` | bool | `false` | `true` `false` | Ignore image color correction during coloring/texturing. |
| `MvsGeometryTexturingDoHdr` | bool | `true` | `true` `false` | Prefer 16-bit/HDR texture generation. |
| `txtImportDefaultTexResolution` | enum | `8192` | `512`…`16384` | Default texture resolution for **imported** models with unknown resolution. Ignored for FBX imports. |

All [OFFICIAL: tutorials/setkeyvaluetable + tools/texturing_part2]. See
`03-settings-keys.md` §7 for the binary-only siblings.

**`ImageLayerForTexturing` is the documented mechanism for "align on
originals, texture from enhanced images".** This pipeline currently applies
CLAHE **upstream** of batching, so the imagery that is aligned is also the
imagery that is textured — including its amplified marine snow and lifted
water-column haze. RealityScan **Image Layers**
(`.geometry` / `.texture` / `.mask`) is agreed as the eventual mechanism but is
**not adopted** and **has never been exercised through this CLI**
[VERIFIED-as-decision: HANDOFF 2026-07-26; [OPEN]].

### 8.3 Texture after hole-closing — the decision and its mechanism

The production recipe textures **after** `-closeHoles` + `-cleanModel`, not
before. The reasoning was tested against the alternatives
[VERIFIED-as-design-decision with mechanism: docs/settings-evaluation-2026-07 §7]:

| Strategy | Result |
|---|---|
| Texture the holey model → close holes → reproject | **Wrong.** Reprojection samples the source **surface**; hole-fill triangles have no source → nodata patches, no blending. |
| Close holes + clean → texture → simplify → reproject (**chosen**) | `-calculateTexture` projects from the source **images** with multi-band blending, so hole-fill triangles that any camera saw receive real blended color. The final `-reprojectTexture` then maps manifold → manifold, introducing no nodata. |
| Residual limitation | Fill areas **no camera ever saw** come out untextured under any strategy. `reprojectionTool_colorSampling` / `_supersampling` affect sampling quality, not unseen-area synthesis. External inpainting is the only remedy. |

---

## 9. Unwrapping and the texture budget

`-unwrap [params.xml]` computes the UV map [OFFICIAL: appbasics/allcommands;
tools/unwrap]. Process ids `20737`–`20741 UNWRAP_MODEL`, plus
`20742 FILL_TEXTURES`.

The default unwrap parameters are used **only** when a model has no UV map and
texturing is invoked; to recompute an unwrap on an already-textured model you
must call the Unwrap tool explicitly [OFFICIAL: tools/texturing_part2 WARNING].

### 9.1 Unwrap key space

Configuration id `{54A4029C-DE57-43F6-8F81-75C62E159021}` — the same id is used
by the repo's `Texturing_*.xml` and `Unwrapping_*.xml` files, because they are
the same dialog's settings.

| Key | Type | Default | Values | Controls |
|---|---|---|---|---|
| `unwrapStyle` | enum | `MaxTexturesCount` | `MaxTexturesCount`, `FixedTexelSize`, `AdaptiveTexelSize` (ordinals accepted — Epic's own example uses `unwrapStyle=1`) | Strategy for building the UV map. |
| `unwrapMaximalTexCount` | int | `1` | int > 0 | Max texture count; relevant when `unwrapStyle=MaxTexturesCount`. Texel detail is adjusted automatically to fit this count within the max resolution. |
| `unwrapMinTexResolution` | enum | `512` | `512` `1024` `2048` `4096` `8192` `16384` | Minimal texture resolution. Cannot exceed the maximum. |
| `unwrapMaxTexResolution` | enum | `8192` | `512` … `16384` | Maximal texture resolution. Cannot be below the minimum. |
| `unwrapGutter` | int | `2` | int > 0 | Chart-border padding in texels. `2` avoids mip-map bleeding in most renderers. |
| `unwrapLargeTriangleRemovalThr` | int | `10` | int > 0 | If a triangle's edge length × this value exceeds the model's average edge length, the triangle is mapped to a **single texel**. `400` ⇒ triangles with edges 400× the average collapse to one texel. |
| `unwrapFixedTexelSizeType` | enum | `0` | `0` Optimal, `1` 2× optimal (50 % quality), `2` 4× (25 %), `3` 10× (10 %), `4` 100× (1 %), `5` Custom | Texel size preset; relevant when `unwrapStyle=FixedTexelSize`. |
| `unwrapFixedTexelSize` | float | `0.01` | > 0 | Custom texel size in CRS units; relevant when `unwrapStyle=FixedTexelSize` **and** `unwrapFixedTexelSizeType=5`. `0.01` = 1 cm when the unit is the metre. |
| `unwrapMinTexelSizeType` *(Help prints `unwrapMinTexelSize`)* | enum | `0` | `0`–`5`, same ladder as `unwrapFixedTexelSizeType` | Minimal **required** texel size for `AdaptiveTexelSize` — the *smallest* texel allowed, useful to stop a high-resolution camera close to an object from burning texture pixels. |
| `unwrapMinTexelSize` | float | `0.01` | > 0 | The custom value, when the type above is `5`. |
| `unwrapMaxTexelSizeType` *(Help prints `unwrapMaxTexelSize`)* | enum | `4` (`100×` optimal) | `0`–`5` | Maximal **required** texel size for `AdaptiveTexelSize` — no texel bigger than this; practical when the texture will be painted into later. |
| `unwrapMaxTexelSize` | float | `10` | > 0 | The custom value, when the type above is `5`. |
| `unwrapMethod` | string | — | `Geometric`, mosaicing-based | `Geometric` is the legacy fast method; mosaicing-based (experimental) produces fewer UV islands but is slower. [UNDOCUMENTED as a key — read from the repo XMLs and the binary; the GUI control is [OFFICIAL: tools/unwrap]] |
| `unwrapFillTextures` | flag | — | `0x0`, `0x1` | Fill textures / "Fill with charts". [UNDOCUMENTED] |
| `unwrapCheckerBoardCellSize` | int | — | `64` in repo presets | GUI "Grid size" (checkerboard preview cell size). **Inert in 2.2** — the string in the binary is `unwrapCheckerBoardCellCount`, not `…CellSize` [CONTRADICTED: repo presets vs binary; see `03-settings-keys.md` §12]. |
| `unwrapButtonDisabled` | int | — | `0` | UI state carried in the exported preset; inert. [UNDOCUMENTED] |

[OFFICIAL: tools/unwrap, tools/texturing_part2, tutorials/setkeyvaluetable]
unless marked otherwise.

[CONTRADICTED] **Epic's key table prints `unwrapMinTexelSize` and
`unwrapMaxTexelSize` twice each, with incompatible types** — once as an
`AdaptiveTexelSize` enum `0`–`5` (defaults `0` and `4`) and once as a float
(defaults `0.01` and `10`) [OFFICIAL: tutorials/setkeyvaluetable]. One key
cannot be both. The 2.2 binary contains **`unwrapMinTexelSizeType` and
`unwrapMaxTexelSizeType`**, exactly mirroring the
`unwrapFixedTexelSize` / `unwrapFixedTexelSizeType` pair, so the enum rows are
almost certainly mis-printed and should carry the `…Type` suffix
[INFERRED from the binary string table; see `03-settings-keys.md` §13.6 for the
full write-up, including a second copy-paste error in the same rows' "relevant
for" notes]. **Practical consequence:** writing a metre value into
`unwrapMinTexelSize` while `unwrapStyle=AdaptiveTexelSize` will not do what an
agent expects. Confirm by exporting an adaptive preset from the GUI Unwrap tool
before relying on either name.

Also GUI-documented with no confirmed key: **Defragment charts** (larger UV
islands, Maggiordomo/Cignoni/Tarini approach) and **Style** options under the
mosaicing method (`Maximal texture count` or `Quality`)
[OFFICIAL: tools/unwrap; key names [OPEN]].

Read-back properties of an already-unwrapped/textured model (visible in the
GUI's Selected Model panel and in report variables, §18): coloring style,
unwrapping style, unwrap method, count of textures, texture resolution (all
textures must share one resolution), chart gutter size, texture utilization
with gutter, optimal texel size, **texture quality = texel size as a percentage
of the optimal texel size**, texel size [OFFICIAL: tools/texturing_part2].

### 9.2 Production presets and the texture budget

**Texture budget in force: max 4 textures at 16384×16384 in BOTH texture
passes** [VERIFIED-as-config: HANDOFF 2026-07-29; `GenerateModel.bat`].

| File | Style | Count | Max res | Gutter | LargeTriRemovalThr | Extra | Used by |
|---|---|---|---|---|---|---|---|
| `Texturing_MaxTextureCount4_16k.xml` | `MaxTexturesCount` | 4 | 16384 | 2 | 1000 | `unwrapFillTextures=0x1` | **`-calculateTexture` in `GenerateModel.bat` `[6/8]`** |
| `Unwrapping_Simplified_4x16k.xml` | `MaxTexturesCount` | 4 | 16384 | 2 | 10 | `unwrapMinTexResolution=512`, `unwrapMethod=Geometric`, `unwrapFillTextures=0x0` | **`-unwrap` in `GenerateModel.bat` `[8/8]`** |
| `Texturing_HighPolyTexture.xml` | `MaxTexturesCount` | 2 | 16384 | 2 | 1000 | — | superseded (was `[6/8]`) |
| `Texturing_SimplifiedTexture.xml` | `MaxTexturesCount` | 2 | 16384 | 2 | 1000 | — | unused |
| `Unwrapping_Simplified.xml` | `MaxTexturesCount` | 1 | 16384 | 2 | 10 | `Geometric`, min 512 | superseded (was `[8/8]`) |
| `Texturing_MaxTextureCount1_8k.xml` / `1_16k` / `4_8k` | `MaxTexturesCount` | 1 / 1 / 4 | 8192 / 16384 / 8192 | 2 | 1000 | — | alternatives |
| `Texturing_FixedTexelSize100perQuality.xml` | `FixedTexelSize` | — | 8192 | 10 | 400 | `unwrapFixedTexelSizeType=0` (optimal) | alternatives |
| `Texturing_FixedTexelSize50perQuality.xml` | `FixedTexelSize` | — | 8192 | 10 | 400 | `unwrapFixedTexelSizeType=1` (2× optimal) | alternatives |

[VERIFIED-by-inspection: `RS_CLI/Metadata/*.xml`, 2026-08-04]

**Terminology trap.** `GenerateModel.bat`'s comment calls
`unwrapStyle=MaxTexturesCount` "the adaptive mode". Epic's `AdaptiveTexelSize`
is a **different style** with its own min/max texel-size clamps. What the
comment means — "texel size adapts to fit the count" — is true of
`MaxTexturesCount` per the Help, but an agent that sets
`unwrapStyle=AdaptiveTexelSize` expecting to reproduce the production budget
will get something else entirely
[CONTRADICTED-in-terminology: repo comment vs OFFICIAL tools/texturing_part2].

**Choosing between the styles** [OFFICIAL: tools/texturing_part2]: use
`MaxTexturesCount` when the delivery target caps texture count (web viewers,
game engines); use `FixedTexelSize` / `AdaptiveTexelSize` when the delivery
target specifies a **ground resolution** (e.g. 1 cm for a true orthophoto) —
those styles produce as many textures as the texel size requires.

### 9.3 The gap: no `txt*` key is ever pinned

Every "texturing" params file in this repo contains **only `unwrap*` keys**.
The production texture step therefore controls texture *count and resolution*
and nothing else: `txtStyle`, `txtMethod`, `colStyle`,
`txtImageDownscaleTexture`, `txtFillInUntextoredParts`,
`txtRecolorAfterTexturing`, `MvsDoCorrectColors` and the image-layer selectors
all run at **instance defaults** and were never recorded per run
[VERIFIED-by-inspection, 2026-08-04]. That is a provenance hole in every
delivered texture: the settings are knowable (they are the app defaults listed
in §8.2) but were not pinned, so a future build changing a default would change
the deliverable silently. [OPEN] — the cheap fix is to `-set` the ten keys
before `-calculateTexture` and record them in the environment snapshot; no
extra runtime.

---

## 10. Texture reprojection

`-reprojectTexture <sourceModel> <resultModel> [params.xml]` projects the
texture of an already-textured model onto another model **within the same
component**. The result model **must already be unwrapped**
[OFFICIAL: appbasics/allcommands; tools/reprojection]. Process id
`21040 REPROJECT_TEXTURE`.

Its purpose: a strongly simplified or re-topologized model loses roughness and
textures blurrily from the original images, because the surfaces differ.
Reprojecting the high-detail model's texture gives the sharpest possible result
in a fraction of the time of a fresh `-calculateTexture`
[OFFICIAL: tools/reprojection].

**It resolves both operands by NAME.** With duplicate model names in a shared
project it will silently map the wrong component's texture onto this
component's mesh — a real defect that shipped and was fixed by namespacing
every model name with the component tag [VERIFIED: FINDINGS 2026-07-25].

Params key space, Configuration id `{8F3517E3-5632-40FE-BD10-9967EA8F299F}`:

| Key | Epic shipped `reprojectTexture.xml` | Repo `ReprojectionParams.xml` | Meaning |
|---|---|---|---|
| `reprojectionTool_supersampling` | `-1` | `-1` | Sample each quantity multiple times to reduce aliasing; `Off` samples once and is faster. `-1` = inherit/default. |
| `reprojectionTool_enableColor` | *absent* | `-1` | Reproject the color layer. |
| `reprojectionTool_allowColor` | `false` | `true` | Color reprojection permitted (the section only appears when the source has a color texture). |
| `reprojectionTool_sourceColorLayer` | *absent* | `Color8_0` | Which source color layer to sample. [UNDOCUMENTED] |
| `reprojectionTool_colorSampling` | *absent* | `0` | Texture sampling method. GUI offers "Nearest sampling" (fast, aliases) and "Trilinear sampling" (**recommended**). Ordinal mapping [OPEN] — if `0` is Nearest, the production preset is on the non-recommended setting with supersampling left at default. |
| `reprojectionTool_normal` | `1` | `2` | Normal-map reprojection mode (creates a texture layer storing the source model's surface direction). |
| `reprojectionTool_enableDisplacement` | `false` | `false` | Displacement reprojection (stores the distance between the two models, for tessellation in external renderers). |
| `reprojectionTool_useCustomDistance` | `0` | `0` | Use a custom search distance. |
| `reprojectionTool_customDistance` | — | — | The distance value. [UNDOCUMENTED, binary only] |

[OFFICIAL: tools/reprojection for the controls; VERIFIED-by-inspection for the
values; see `03-settings-keys.md` §8.3]

---

## 11. The production model recipe (`GenerateModel.bat`)

Owner-specified, 2026-07-23; the literal step order and model names as shipped
[VERIFIED-by-inspection:
`modules/realityscan_interface/RS_CLI/Scripts/GenerateModel.bat`]:

```
-load <scene.rsproj>
-selectComponent <name>              (or -selectMaximalComponent when name is "")
[1/8] -calculateHighModel            -> rename <tag>_HighPoly_Raw
[2/8] -selectMarginalTriangles + -removeSelectedTriangles   -> rename <tag>_Cleanup1
[3/8] -selectLargeTrianglesRel 30 + -removeSelectedTriangles -> rename <tag>_Cleanup2
[4/8] -selectLargestModelComponent + -invertTrianglesSelection
      + -removeSelectedTriangles                             -> rename <tag>_Cleanup3
[5/8] -closeHoles ; -cleanModel                              -> rename <tag>_Manifold
[6/8] -simplify SimplifyNoise_Params.xml                     -> rename <tag>_HighPoly
      -calculateTexture Texturing_MaxTextureCount4_16k.xml   -> rename <tag>_HighPoly_Textured
      (if RS_PROJECTS_DIR+RS_PROJECT_LABEL: -save <dated copy>  <-- all intermediates live)
[7/8] 4 x ( -simplify SimplifySmooth_80per_Params.xml -> <tag>_SimplifyPassNRaw
            -cleanModel                                -> <tag>_SimplifyPassN )
      last pass renames to <tag>_Simplified
[8/8] -unwrap Unwrapping_Simplified_4x16k.xml
      -reprojectTexture <tag>_HighPoly_Textured <tag>_Simplified ReprojectionParams.xml
      -selectModel <tag>_Simplified -> rename <tag>_Simplified_Textured
delete intermediates: Cleanup1, Cleanup2, Cleanup3, Manifold, HighPoly,
                      SimplifyPass1Raw, SimplifyPass1, SimplifyPass2Raw,
                      SimplifyPass2, SimplifyPass3Raw, SimplifyPass3,
                      SimplifyPass4Raw          (SimplifyPass4 never exists -
                                                 that pass renamed to _Simplified)
delete residuals: "Model 1".."Model 9"
-save <scene.rsproj>
      (if RS_PROJECTS_DIR+RS_PROJECT_LABEL: -save <dated copy> again)
-quit
```

Facts an agent must carry:

- **`%model_tag%` = the component name** (or `maximal`). Every model name is
  namespaced by it. This is what makes running the recipe once per component
  against **one shared project** safe [VERIFIED: FINDINGS 2026-07-25].
- **Three models were intended to persist; only two do.**
  `_HighPoly_Textured` and `_Simplified_Textured` survive; `_HighPoly_Raw` does
  not (§5.4), plus one default-named residual [VERIFIED: FINDINGS 2026-07-29].
- **Steps `[2/8]` and `[3/8]` are tolerant.** `:try_filter` whitelists result
  codes `2147942487` and `2181038335`, files the evidence as
  `expected_select_<instance>.txt`, sets `step_skipped` and continues — a clean
  mesh with no marginal or oversized triangles must not abort the recipe. A
  skipped step also skips its rename, so the model name chain shortens
  [VERIFIED-by-inspection].
- **`:fail` quits WITHOUT saving**, so a failed model run leaves the assembly
  intact [VERIFIED: FINDINGS 2026-07-26].
- **The scene itself (`-save "%scene_path%"`) is saved only after the cleanup
  loop**, deliberately: saving with ~15 live models is inordinately slow and
  large (§12.5). The deliverable is protected across the loop by the double
  `-waitCompleted` in `:try_delete_model`, not by an early save.
- **But a dated project *copy* IS written before the cleanup loop** when
  `RS_PROJECTS_DIR` **and** `RS_PROJECT_LABEL` are both set: one at the `[6/8]`
  texture milestone — **with every intermediate model live** — and a second
  after the final scene save, both to
  `%RS_PROJECTS_DIR%\%RS_PROJECT_LABEL%_merged_%RS_PROJECT_DATE%.rsproj`
  [VERIFIED-by-inspection: `GenerateModel.bat` lines 127–131 and 184–187]. The
  mid-recipe one is what makes the copies expensive.
- **Leaving `RS_PROJECTS_DIR` / `RS_PROJECT_LABEL` unset skips both dated
  copies** — worth ~10× on save cost (§12.5). `run_models.py` does exactly
  that, then takes **one** copy of the finished project at the end.

Driver: `run_models.py --workspace <ws> [--force]`. It reads the latest
`merge_report.json`, resolves each final component's **metric scale**, and runs
`GenerateModel.bat` per **passing** component **smallest-first** (cost ladder:
the recipe proves itself on a cheap component before the big one spends hours),
aborting below a 50 GB free-disk floor, resumable via `models_report.json`, and
ending with **one** dated project copy through `SaveProjectCopy.bat`
[VERIFIED-by-inspection: `run_models.py`].

**The scale gate is upstream of modelling and it is not optional.** Two
components holding 82 % of a delivered assembly's cameras were once at ~1/5
true scale, and a uniform scale error is **invisible in the viewer** — "all
components look good" was true and still is, locally [VERIFIED: FINDINGS
2026-07-25]. Modelling a metrically invalid component wastes hours and produces
an unusable deliverable. The oracle lives in the georeferencing sibling
document.

---

## 12. Measured resource envelope

All figures on the production box: **93.6 GB physical RAM**, dual RTX 5090,
Windows commit limit grown dynamically. Traces are written by
`RealityScanCLI` to `logs/resources_GenerateModel_<stamp>.csv` with columns
including `ram_avail_gb`, `commit_used_gb`, `commit_total_gb`, `disk_free_gb`,
`cache_free_gb` [VERIFIED-by-inspection: `realityscan_cli.py`].

### 12.1 Per-component model cost

| Component | Cameras | Scale | Model wall clock | Peak commit | Min available RAM |
|---|---:|---:|---:|---:|---:|
| `cluster_0_a2_c0` (H2024 HULL) | 4,860 | 0.997 | 338.3 min | **148.7 GB** | **0.9 GB** |
| `zone_1_c0` | 1,634 | 1.084 | 249.3 min | 139.9 GB | 2.0 GB |
| `cluster_1_a1_c0` | 880 | 1.000 | 122.8 min | 138.6 GB | 2.8 GB |
| `zone_4_c0` | 576 | 0.947 | 106.1 min | 116.8 GB | 3.0 GB |
| `zone_1_c1` | 392 | 1.023 | 97.4 min | 107.1 GB | 3.5 GB |
| `cluster_4_a1_c0` | 133 | 0.980 | 40.1 min | 96.2 GB | 25.9 GB |
| `pd6_zone_1_c0` (H2023 hull, attempt 4) | 3,738 | 0.982 | 384.1 min | 142.3 GB | 0.3 GB |

[VERIFIED: FINDINGS 2026-07-26 and 2026-07-29]

The H2023 hull run also recorded CPU 100 %, minimum free **project** disk
672.6 GB and minimum free **cache** disk 6,900.5 GB — the cache headroom being
the only variable that changed from three failures to success
[VERIFIED: FINDINGS 2026-07-26].

### 12.2 The envelope does not plateau

The apparent plateau at ~140 GB across 392–1,634 cameras **was an artifact of
that range**. The 4,860-camera hull pushed ~9 GB past it and completed with
**under a gigabyte of headroom** on a 93.6 GB box. **Treat anything materially
larger than ~5,000 cameras as at risk, not as covered by precedent**
[VERIFIED: FINDINGS 2026-07-29].

Planning consequences:

| Question | Answer from the record |
|---|---|
| Can I model a 10,000-camera component here? | Unknown and unsupported. Nothing above 4,860 has been run; the trend is still rising at that point. Split the component or get more RAM/commit. |
| How long will it take? | Not linear in camera count and not predictable from it. 133 → 4,860 cameras is 36× the cameras and 8.4× the time; 576 → 880 is 1.5× the cameras and 1.2× the time. Budget per component from a neighbour of similar size, not from a formula. |
| What will it peak at? | Commit, not working set, is the binding resource. RealityScan's own working set peaked at **62.5 GB** while commit charge was 105 GB — the rest is Windows growing the commit limit (99.5 → ~120 GB observed) to absorb it [VERIFIED: FINDINGS 2026-07-26]. |
| What is the abort criterion? | `run_models.py` uses a **50 GB free-disk floor** on the workspace drive (`MIN_FREE_GB = 50.0`) checked before each component. `RealityScanCLI` warns below **4 GB available RAM** (`LOW_MEMORY_WARN_GB = 4.0`). There is deliberately **no overall timeout**. |

### 12.3 The memory profile of `-calculateHighModel`

On 3,738 cameras: available RAM fell from 79.4 GB to **3.1 GB within 3
minutes**; commit charge went 19.6 → 105 GB; Windows grew the commit limit from
99.5 GB to ~120 GB; the run then oscillated at 87–105 GB committed with 7–32 GB
free for the next half hour. Verified doing real work rather than hanging: 9.1
cores busy and 33 % GPU over a 20 s window
[VERIFIED: FINDINGS 2026-07-26].

**These figures are a memory profile, not the cause of any failure.**
[SUPERSEDED] the earlier reading "memory exhaustion intrinsic to this mesh" —
refuted by the retry's `ERROR_DISK_FULL` exit code. What survives: the hull
pages heavily at High detail, which makes it slow (step `[1/8]` alone ran
longer than the bow's entire recipe), and the pagefile is only 6.9 GB.

There is a **third cause of persistent `#timeout`** in the progress feed that
matters here: near-OOM. RealityScan slows to a crawl without crashing and
without spilling to NVMe — indistinguishable in the progress feed from a hang
[VERIFIED: FINDINGS 2026-07-24].

### 12.4 The failure that actually happens: the cache disk

All three H2023 hull-model failures were the **cache disk**, not memory and not
the project disk [VERIFIED: FINDINGS 2026-07-26]:

| Attempt | Symptom | Reading at the time |
|---|---|---|
| 1 | Crash at `closeHoles`/`cleanModel`; minidump `RealityScanCrash-20260726-054742.dmp` | blamed on concurrent CLAHE + copy — **refuted** by file mtimes |
| 2 | 143.5 min, failed at `[6/8]` texture generation with result `2147942512` = `0x80070070 ERROR_DISK_FULL`; `D:` at 0 bytes free; the driver's own log snapshot failed with `[Errno 28] No space left on device` | blamed on intrinsic memory exhaustion — **refuted** by the exit code |
| 3 | Same class; instance log said it outright: `Processing failed: Out of disk space..` during `simplify` (`[6/8]`), **after** `closeHoles` (125 s) and `cleanModel` (230 s) had both succeeded. Cache at `D:\rccache`, **1,089 GB**, refilled 197 GB of freshly-cleaned space within one run | blamed on the project disk — **refuted** by the instance log naming the cache |
| 4 | Succeeded, 384.1 min. **Only variable changed: `RS_CACHE_DIR=E:\rscache`** | — |

Epic's own guidance confirms the mechanism and forbids the obvious workaround:
processing cannot continue without freeing space, the process is aborted and
the progress is lost, and **"don't delete the files from your cache folder"**
[OFFICIAL: Epic "Out of Disk Space" page, quoted in FINDINGS 2026-07-26]. The
sanctioned levers are freeing space on the cache disk or changing the cache
disk:

| Key | Values | Notes |
|---|---|---|
| `appCacheLocation` | `SystemTemp`, `Custom` | Pinned to `Custom` when `RS_CACHE_DIR` is set. |
| `appCacheCustomLocation` | path | The cache is placed by the **drive of the path given** and does **not** move when the project moves. |
| `appAutoClearCache` | retention in days: `999999` = never, `0` = clear all, `3`/`7`/`14`/`30`/`90` = age cutoff | **Deliberately untouched here** — retention is owner policy. |
| `-clearCache` | command | Requires the project be **saved first**. |

[OFFICIAL for the enum values: tutorials/setkeyvaluetable;
VERIFIED-as-applied: FINDINGS 2026-07-26]

**Instrumentation lesson, recorded three times in one session:** a resource
trace built around one hypothesis will confirm or refute *that hypothesis* and
tell you nothing else. The trace faithfully recorded RAM falling to 3.1 GB and
was silent about the disk that killed the run; the disk column added afterwards
pointed at the **project** drive, not the cache. `cache_free_gb` is now its own
column [VERIFIED: FINDINGS 2026-07-26].

### 12.5 Save cost

| What | Cost |
|---|---|
| `GenerateModel.bat` with `RS_PROJECTS_DIR` set: two `RC_projects` copies per component, one **mid-recipe with every intermediate model live** | `zone_1_c0`'s saves consumed **~81 GB** |
| Same component class with `RS_PROJECTS_DIR` unset (skips both copies) | `cluster_4_a1_c0` cost **6.8 GB** end to end |
| **One** dated copy of the finished six-component project via `SaveProjectCopy.bat` | **13.1 min / 95.2 GB** |

[VERIFIED: FINDINGS 2026-07-29]

**The per-component scene save must stay** — the workflow loads/models/quits
per component, so the models would be lost otherwise
[VERIFIED-as-constraint: FINDINGS 2026-07-29].

Related load hazard: **a stale `<name>.rsproj.new` beside the project makes the
next headless `-load` emit warning-class `0x82000017` while still completing** —
enough to abort an errors-marker-gated workflow. An interrupted GUI save is the
source; renaming the temp aside cleans the load [VERIFIED: FINDINGS 2026-07-29].

---

## 13. Model export

### 13.1 Commands

| Command | Required | Optional | Notes |
|---|---|---|---|
| `-exportModel` | `modelName` `fileName` | `params.xml` | **REPO**. `fileName` includes path **and format extension**. Process ids `6 EXPORT_MODEL`, `21876 CLI_EXPORT_MODEL`. |
| `-exportSelectedModel` | `fileName` | `params.xml` | Same, for whatever is selected. |
| `-exportModelToZip` | `filePath` | `modelFormat` | Compressed archive; archive extension optional, model format (e.g. `.obj`, `.fbx`) optional. |
| `-importModel` | `fileName` | `params.xml` | [CONTRADICTED, minor] `tutorials/commandline_3` shows no optional `params.xml`; `appbasics/allcommands` does. Prefer the master table. Process id `17 IMPORT_MODEL`. |

[OFFICIAL: appbasics/allcommands; tutorials/commandline_3]

File names **cannot contain Unicode characters or spaces** — the app raises a
message if they are used [OFFICIAL: tools/export].

**A simplified model must be re-textured before its textures can be exported**
[OFFICIAL: tools/export]. This is the export-side statement of the same fact
`tools/simplify` makes about losing the texture, and it is precisely why the
production recipe ends with `-unwrap` + `-reprojectTexture` on
`<tag>_Simplified` rather than exporting the simplify output directly (§11).

### 13.2 Formats

Selectable in the export dialog, therefore selectable by extension on
`-exportModel` [OFFICIAL: tools/export]:

`.obj` (Wavefront) · `.ply` (Polygon File Format) · `.xyz` (XYZ point cloud) ·
`.abc` (Alembic) · `.glb` (binary glTF) · `.stl` · `.3mf` · `.usd` · `.usdz` ·
`.ptx` (laser point cloud) · `.las` (LAS point cloud) · `.partList` (list of
visible parts — needs no export settings) · `.fbx` · `.dxf` (AutoCAD) ·
`.dae` (Collada). Plus "just textures".

Format-conditional options:

| Option | Only for |
|---|---|
| Format version (`FBX201100`, `FBX201200`, `FBX201300`, `FBX201400`, `FBX201800`, `FBX201900`, `FBX202000`) | `.fbx` — the control is **enabled for various formats but "relevant only when exporting a model as .fbx"** [OFFICIAL: tools/export], which is why `ModelExportFormatVersion` shows up in OBJ/GLB/PLY presets too |
| File type Binary / ASCII (binary is smaller) | `.ply` |
| Export materials | `.fbx` |
| Classification export | `.ply`, `.xyz`, `.las` |
| Generate multi-scan PTX, Output Decimal Precision | `.ptx` |
| Embedded textures | formats that support embedding (e.g. `.glb`) |
| Export cameras / undistort / export images settings | mostly `.fbx` and `.abc` |

### 13.3 Where a params XML comes from

**The only way to obtain a valid params XML for a tool is to export it from
that tool's GUI dialog once** [VERIFIED-as-practice: FINDINGS 2026-07-21]. For
model export there is a second, documented route
[OFFICIAL: tools/export]:

> Set **Export an info file** to Yes. RealityScan writes an XML sidecar
> (`.rsInfo`). Copy the text inside its `ModelExport` tag into an empty `.xml`
> and use that file with `-exportModel`.

The `.rsInfo` file is also the round-trip mechanism: it records the internal
coordinate system and its relation to the export coordinate system, so an
exported → post-processed → re-imported model lands back in the right place.
**The application searches for it automatically and it must be named
`<modelfile>.rsInfo`** (e.g. `myObject.obj.rsInfo`). Without it, a re-imported
model may be shifted, rotated and scaled relative to the original
[OFFICIAL: tools/export].

### 13.4 Parts

**Save mesh by parts** exports the model in the parts it was created in rather
than as a singleton [OFFICIAL: tools/export]. Part granularity is set at mesh
time by `mvsMaxVertexCountInPart` (default 5,000,000) [OFFICIAL:
appbasics/modelsettings], and part behaviour through simplification is governed
by `simplPreserveParts` (§6.3).

A related model-tools command exists but is **hidden**: `-undercut` (no parameters,
process ID `27 UNDERCUT_MODEL_PARTS`) — "undercut the selected model so that each part
contains geometry just in its cluster box". Its row is present in the shipped Help
**source** but commented out of the rendered page, so it is neither properly documented nor
proven to still parse in 2.2. Do not put it in a workflow until probed; full entry and the
probe in `02-command-reference.md` §12.2. [UNDOCUMENTED / OPEN]

**When parts are required:**

| Target | Requirement | Source |
|---|---|---|
| Nira | "Save mesh by parts: **Yes**" is Nira's documented recommendation for RealityScan photogrammetry exports | [VERIFIED-as-guidance: help.nira.app article 5591333681307, recorded in `publish_nira.py` and HANDOFF 2026-07-29] |
| Very large models generally | A singleton mesh must fit one contiguous structure in the consumer; parts also let a viewer stream. Epic recommends "Create a singleton" in Simplify **only for models smaller than a few million triangles** | [OFFICIAL: tools/simplify] |

**Verified output layout of the production by-parts exports** (133-camera
component, ~35–38 s each) [VERIFIED: FINDINGS 2026-07-29]:

```
exports\<component>\obj\
    <component>.obj              4 parts
    <component>.mtl              per-part MTL
    <component>_u1_v1_*.png      textures, u1_v1 tiling
    <component>.obj.rsInfo
exports\<component>\fbx\
    <component>.fbx              4 parts
    <component>_*.png            textures
```

### 13.5 Params key families (`Mvs*`)

Structural rules observed across all **eleven** repo export presets
[VERIFIED-by-inspection: `RS_CLI/Metadata/ModelExportParams*.xml`, 2026-08-04]:

- Per-texture-layer keys carry a **layer suffix**:
  `MvsMeshExportTexturing_Color8_0`, `MvsMeshExportTexImgFormat_Color8_0`,
  `MvsMeshExportTexPixFormat_Color8_0`, plus `_Normal_0` and `_no_alpha`
  variants. Unsuffixed base keys also exist.
- `…Allowed` keys (`MvsMeshExportTexturingAllowed`, `…NormalsAllowed`,
  `…CamerasAllowed`, `…MaterialsAllowed`, `…ClassificationAllowed`,
  `…NumberFormatAllowed`, `…EmbeddTxrsAllowed`, `…ByPartsAllowed`,
  `…ColorsAllowed`, `…ColorInByteAllowed`) use `-1` = allowed/inherit,
  `0` = not allowed. They gate what the target format supports, and they gate
  **presence**: `MvsMeshExportNumberFormat` appears only in the two presets
  whose `MvsMeshExportNumberFormatAllowed` is `-1` (both OBJ), and is absent
  from every preset where it is `0` [VERIFIED-by-inspection, 2026-08-04].
- Booleans appear as `true`/`false`, `0`/`1` and `0x1` **interchangeably in the
  same key across files** (e.g. `MvsExportIsGeoreferenced` = `1.0` in one file,
  `0x1` in another). Do not write a strict parser.

| Key | Values seen | Meaning |
|---|---|---|
| `ModelExportFormatVersion` | `0` (`…OBJ_NiraParts`, `…Obj`, `…GLB`), `13` (all FBX presets, `…PLY_DensePoints`, `ModelExportParams.xml`) | [OPEN] two readings: the "Format version" selector — which the Help says is *enabled for various formats but relevant only for `.fbx`*, and whose FBX values are the seven `FBX2011xx`…`FBX202000` labels — or the schema version of the params file. `13` on a PLY preset is consistent with either (an irrelevant-but-serialized control); `0` on two OBJ presets and `13` on a third generic one argues against a pure schema version. Cheapest probe: export an FBX from the GUI at `FBX201100` and again at `FBX202000` and diff the two params files. |
| `MvsExportcoordinatesystemtype` | `0`, `3` | Export CRS mode. The dialog offers **Grid plane / Project Output / Shifted project output / Same as XMP**, so [INFERRED] `0` = Grid plane and `3` = Same as XMP. Cheapest probe: set each of the four in the GUI, export params, read the value. |
| `MvsExportIsGeoreferenced` | `0x1`, `1.0` | Export in world coordinates. |
| `MvsExportIsModelCoordinates` | `0` | Export in model-local coordinates. |
| `MvsExportScaleX/Y/Z` | `1.0`, `10.0`, `100.0` | Export scale. `100` = metres → centimetres (the "Maya + Arnold, Unreal" preset); GLB preset uses `10`. |
| `MvsExportMoveX/Y/Z` | `0.0` | Export translation, in coordinate-system units (metres by default). |
| `MvsExportRotationX/Y/Z` | `0.0` in every repo preset **except `ModelExportParamsGLB.xml`, which sets `MvsExportRotationX` = `-90.0`** (Z-up → Y-up for glTF) | Euclidean rotation per axis, −180..180°. |
| `MvsExportTransformationPreset` | `Maya + Arnold, Unreal`, `Unreal`, `Custom`, **`[[Custom]]`** (the GLB preset — double square brackets, presumably an unresolved localisation token) | Named transform preset; sets the scene- and normal-transformation blocks. |
| `MvsExportNormalSpace` | `Mikktspace` | Normal space. Options are World / Object / Tangent (Mikktspace); Mikktspace is compatible with several third-party renderers and **requires `MvsMeshExportNormals=true` for best results** [OFFICIAL: tools/export]. |
| `MvsExportNormalRange` | `ZeroToOne` | Float range used to encode normals; no effect for non-float texture pixel formats. |
| `MvsExportNormalFlipX/Y/Z` | X `false`, **Y `true` in every repo preset**, Z `false` | Mirror normal directions. Flipping Y is needed for correct normal maps in several third-party renderers [OFFICIAL: tools/export]. |
| `MvsMeshExportNormals` | `true` | Write vertex normals. |
| `MvsMeshExportColors` | `false`, `true` | Write vertex colors. **`true` only in `ModelExportParamsPLY_DensePoints.xml`.** |
| `MvsMeshExportTexturing` | `-1`, `0`, `true` | Write textures (`0` in the PLY preset). |
| `MvsMeshExportTexOneFile` | `0` | "Export to a single texture file". `0` = No, which is what makes the Tile type options apply. |
| `MvsMeshExportTileType` | `0`, `1`, `2` | Tile type when `TexOneFile=0`. Repo filenames + the verified `u1_v1` output make the mapping **`0` = `_u1_v1`, `1` = `(u,v)`, `2` = `UDIM`** [VERIFIED-by-inspection + FINDINGS 2026-07-29 file naming]. Note this **corrects** a reading of `0` as "single texture" — the single-file switch is `MvsMeshExportTexOneFile`, a different key. |
| `MvsMeshExportTexImgFormat[_<layer>]` | `jpg`, `png`, `jpeg` | Texture image format. |
| `MvsMeshExportTexPixFormat[_<layer>]` | `24bppBGR`, `32bppBGRA` | Texture pixel format (the dialog also offers 64-bit RGBA). |
| `MvsMeshExportTexAlpha` | `false`, `0` | Export texture alpha mask. |
| `MvsMeshExportByParts` | `0`, `1` | **`1` = save mesh by parts.** |
| `MvsMeshExportMaterials` | `true`, `false` | Write materials (usable only for FBX per the Help). |
| `MvsMeshExportEmbeddTxrs` *(sic)* | `true` (GLB), `false` | Embed textures into the model file. |
| `MvsMeshExportCameras` / `MvsMeshExportCamerasAsModelPart` | `0` / `false` | Export camera positions/orientations/focals; or convert cameras to mesh. |
| `MvsMeshExportInfoFile` | `true` | Write the `.rsInfo` sidecar (§13.3). **`true` in every repo preset.** |
| `MvsMeshExportNumberFormat` | `5` (`ModelExportParamsObj.xml`), `6` (Nira OBJ) | [CONTRADICTED] The Help describes the control as a **three-option enum**: "Number format … The options are: Decimal, Scientific, and General. Decimal and Scientific both contain maximum 17 digits and trim zeros … General uses Decimal or Scientific depending on which is shorter" [OFFICIAL: tools/export]. The only values ever observed in an exported preset are `5` and `6`, which cannot be ordinals over a three-item list [VERIFIED-by-inspection of the two OBJ presets, 2026-08-04]. Nira's stated requirement is "decimal-6", so [INFERRED] the serialized value is a decimal-precision count and the dialog exposes precision separately from the three-way style. [OPEN] — settled by toggling the GUI control and diffing. |
| `MvsMeshExportFileTypeSelectionDisplay` | `0` | Dialog state; inert. |

Additional GUI-documented controls absent from every repo preset
[OFFICIAL: tools/export]. Binary key candidates from the 2.2 executable's string
table [INFERRED, see `03-settings-keys.md` §8.6 — none verified as live]:

| GUI control | Meaning | Binary key candidate |
|---|---|---|
| Texture maximal side | 512 … 65536; **only when "Export to a single texture file" = Yes** | `MvsMeshExportTexOneFileMaxResolution` |
| Use pow2 texture size | only for single-texture export; assembles the atlas at the nearest power-of-two multiple, square, smallest area | `MvsMeshExportOneFileUsePow2TexSize` |
| Grayscale quality values | for quality-colorized / quality-textured models — "preserve the full range and precision of the quality information" | `MvsMeshExportColorsHaveQuality`, `MvsMeshExportColorsMapQuality` |
| Classification export | `.ply` / `.xyz` / `.las` only | `MvsMeshExportClassificationLayer` |
| Texture pixel format 64-bit RGBA | third option beside `24bppBGR` / `32bppBGRA` | `MvsMeshExportTexPixFormat` value, name unknown |
| Output Decimal Precision | `.ptx` only | unknown |
| Undistortion / Export image blocks | §16 lists the undistortion order | `MvsExport*` / `MvsSnapshot*` families |

**Warning that matters at 4×16K:** "If the textures do not fit into the
maximal resolution, they will be resized to fit in, which results in lowering
of the detail quality" — i.e. exporting a 4×16384 model to a *single* texture
file with `Texture maximal side` below 32768 silently downsamples
[OFFICIAL: tools/export].

### 13.6 The repo's export presets

| File | FormatVersion | ByParts | TileType | Tex format / pix | Colors | Scale | CRS type | Preset & notes |
|---|---|---|---|---|---|---|---|---|
| `ModelExportParamsOBJ_NiraParts.xml` | 0 | **1** | 0 (`u1_v1`) | `png` / `24bppBGR` | false | 1.0 | 3 | `Custom`, `NumberFormat=6`, `Texturing=true` |
| `ModelExportParamsFBX_Parts.xml` | 13 | **1** | 0 | `png` / `24bppBGR` | false | 1.0 | 3 | `Custom`, `Materials=true`, `Texturing=-1` |
| `ModelExportParamsPLY_DensePoints.xml` | 13 | 0 | 0 | — | **true** | 1.0 | 0 | `Custom`, `Texturing=0`, `Materials=false` |
| `ModelExportParamsObj.xml` | 0 | 0 | 0 | `jpg` / `24bppBGR` (+ `_Normal_0` layer) | false | 100.0 | 0 | `Unreal`, `NumberFormat=5` |
| `ModelExportParams.xml` | 13 | 0 | 0 | `jpg` / `24bppBGR` | false | 100.0 | 3 | `Maya + Arnold, Unreal` |
| `ModelExportParamsFBX_U1V1.xml` | 13 | 0 | **0** | `png` / `32bppBGRA` | false | 100.0 | 0 | `Maya + Arnold, Unreal`, `Materials=false` |
| `ModelExportParamsFBX_UV.xml` | 13 | 0 | **1** | `png` / `32bppBGRA` | false | 100.0 | 0 | same |
| `ModelExportParamsFBX_UDIM.xml` | 13 | 0 | **2** | `png` / `32bppBGRA` | false | 100.0 | 0 | same |
| `ModelExportParamsFBX_U1V1_material.xml` / `…UDIM_material.xml` | 13 | 0 | 0 / **2** | `png` / `32bppBGRA` + `_Normal_0` layer | false | 100.0 | 0 | same, `Materials=true` |
| `ModelExportParamsGLB.xml` | 0 | 0 | *(absent)* | `jpeg` / `24bppBGR`, keys suffixed **`_no_alpha`** | `0` | 10.0 | 0 | **`[[Custom]]`**, `EmbeddTxrs=true`, **`MvsExportRotationX=-90.0`**, `IsGeoreferenced=1.0` |

[VERIFIED-by-inspection: `RS_CLI/Metadata/ModelExportParams*.xml`, 2026-08-04]

Eleven files; only three have a production call site — `…OBJ_NiraParts.xml`,
`…FBX_Parts.xml`, and `…PLY_DensePoints.xml` (whose call site is defective,
§13.7). The other eight are unreferenced by any `.bat`
[VERIFIED-by-inspection: `RS_CLI/Scripts/*.bat`, 2026-08-04], though
`SetVariables.bat` defines convenience variables for several of them.
`MvsMeshExportInfoFile=true` in **all eleven**.

### 13.7 The deliverable export workflow (`ExportDeliverables.bat`)

One RealityScan session for everything — the project load is the expensive
part. Per component, names read one-per-line from a list file:

```bat
cmd /c modules\realityscan_interface\RS_CLI\Scripts\ExportDeliverables.bat ^
    "F:\na156_h2024_v2\final_assembly\assembly\H2024_Final_Assembly.rsproj" ^
    "F:\na156_h2024_v2\exports" ^
    "F:\na156_h2024_v2\exports\components.names"
```

1. `-load`, sweep `"Model 1"`…`"Model 9"` residuals, `-save` **once**.
2. `-exportModel <name>_Simplified_Textured … \obj\<name>.obj ModelExportParamsOBJ_NiraParts.xml`
3. `-exportModel <name>_Simplified_Textured … \fbx\<name>.fbx ModelExportParamsFBX_Parts.xml`
4. `-selectModel <name>_HighPoly_Raw` → `-calculateVertexColors` →
   `-exportModel <name>_HighPoly_Raw … \ply\<name>_dense.ply ModelExportParamsPLY_DensePoints.xml`
5. `-quit` **without saving** — the vertex colors are computed in memory only,
   deliberately, so the project stays lean.

[VERIFIED-by-inspection: `RS_CLI/Scripts/ExportDeliverables.bat`]

**KNOWN DEFECT, unfixed as shipped:** step 4 selects
`<name>_HighPoly_Raw`, which **the model recipe does not reliably leave in the
project** (§5.4) — on the H2024 assembly it was probed absent. When it is
absent, `-selectModel` reports `err:5601` / `2147942487`, and unlike the
tolerant `:try_delete_model`, `:export_component` calls the strict `:run`
subroutine three times with `|| exit /b 1` — so the PLY step **aborts the whole
export**, taking the remaining components with it (the caller's
`call :export_component "%%N" || goto :fail` unwinds to `:fail` and quits). The
finding records the intended fallback: **use `_HighPoly_Textured`, the densest
model guaranteed to exist**, or `-duplicateSelectedModel` right after `[1/8]`
[VERIFIED: FINDINGS 2026-07-29; the OBJ and FBX steps were verified end to end
on the 133-camera component, the PLY step was not]. Because the OBJ and FBX
exports for a component run *before* its PLY step, an abort mid-list leaves a
partially-populated `exports\` tree — check for `ply\<name>_dense.ply` per
component before assuming the set is complete.

The names file must be **BOM-free**: `Set-Content -Encoding utf8` in Windows
PowerShell 5.1 writes a BOM, and a BOM on line 1 of a list file silently
invalidates the first entry (the same class of bug that invalidated a
`.complist`) [VERIFIED: FINDINGS 2026-07-27]. `wildscan.session.export_names_file`
writes it with Python and CRLF line endings.

---

## 14. Level of detail and 3D Tiles

| Command | Required | Optional | Produces |
|---|---|---|---|
| `-exportLod` | `fileName` | `params.xml` | **Linear** LoD set — several simplified versions of the model as separate files. Process id `28672 EXPORT_LOD`. |
| `-export3dTiles` | `fileName` (`.json`) | `params.xml` | **Hierarchical** LoD — Cesium 3D Tiles. Process id `21813 EXPORT_CESIUM`. |

[OFFICIAL: appbasics/allcommands; tools/lodexport]

**Linear LoD dialog** (shown for `obj`, `ply`, `xyz`, `abc`, `glb`, `fbx`,
`dxf`, `dae`) [OFFICIAL: tools/lodexport]:

| Control | Values / meaning |
|---|---|
| Stopping criterion | `Model Count` (exact number of levels) or `Triangle Count` (keep going while the simplified triangle count exceeds a value) |
| Model count | Number of levels, when the criterion is Model Count |
| Simplification type | `Relative` (reduce by a percentage per level) or `Absolute` (distribute triangle counts evenly across a range; **only available with Model count**) |
| Relative simplification factor | Triangle count of a level relative to the next higher-quality one |
| Maximal triangles | Triangle count of the highest-quality exported level |
| Minimal triangles | Triangle count of the lowest-quality level; unavailable with Model Count + Relative |
| File suffix | Default `_LODn`; `Custom` enables a custom suffix |
| Numbering start | Default: the first, highest-quality model is `0` |
| Mesh settings | Identical to the Export Model dialog (§13.5) |

**Hierarchical LoD dialog** (Cesium 3D Tiles). Splits the model into a
hierarchy of nodes; a compatible viewer displays only some of them. If the
model is georeferenced the geospatial location is preserved
[OFFICIAL: tools/lodexport]:

| Control | Meaning |
|---|---|
| Initial simplification `Type` | `None`, `Relative`, `Absolute` — caps the maximum detail present in the export |
| Iterative simplification `Type` | Currently only `Relative` is allowed |
| Export textures | The model **must** have a texture to export it textured |
| Source Layer | Which texture layer to use |
| Texel size | Best texture quality present in the export; lower = higher quality |
| Texture Format | `.webp`, `.jpg` or `.png` |
| Maximum node triangle count | Granularity of the node decomposition; lower = finer hierarchy |
| Bandwidth Scale | < 1 = faster streaming/lower quality; > 1 = slower/higher quality |
| Altitude | Tweaks the model's height above terrain |

Binary key family for both (all [UNDOCUMENTED], none confirmed as `-set` keys,
none used here): `LodType`, `lodPath`, `lodFilename`, `lodPrimitive`,
`lodCriterion`, `lodAltitude`, `lodBandwidthScale`, `lodModelCount`,
`lodMinTriangles`, `lodMinTrianglesEnabled`, `lodMaxTriangles`,
`lodMaxNodeTriangleCount`, `lodSimplificationType`,
`lodSimplificationPercentage`, `lodInitialSimplType`,
`lodInitialSimplTargetPercentage`, `lodIterativeSimplType`,
`lodIterativeSimplTargetPercentage`, `lodLargeTriangleRemovalThresh`,
`lodTexelSize`, `lodTexelSizeCustom`, `lodTexelSizeOptimal`,
`lodTextureFormat`, `lodColorInputTextureLayer`, `lodIsModelTextured`,
`lodExportTexturingFalse`, `lodGzip`, `LodSuffix`, `LodSuffixNumbering`,
`lodSuffixType` [see `03-settings-keys.md` §8.7].

**Neither LoD command has ever been run here.** The Cesium path this pipeline
uses uploads a **raw OBJ** and lets ion tile it (§17.2), on explicit Cesium
staff guidance — ion hosts a pre-tiled 3D Tiles export as-is, **without**
reprocessing [VERIFIED-as-guidance: `publish_cesium.py` docstring, 2026-07-29].
[OPEN] whether `-export3dTiles` + manual ion upload gives a better or worse
result than ion's Reality Tiler on this imagery; the probe is one 133-camera
component through both paths.

---

## 15. Orthographic projections, DSM/DTM, contours, cross sections

Each ortho projection is stored in the project with **color, depth and altitude
layers**; a DTM layer can be added. Georeferenced orthophoto maps, image
mosaics, DSMs, DTMs and side projections all come from the same object
[OFFICIAL: tutorials/orthophoto].

### 15.1 Commands

| Command | Params | Notes |
|---|---|---|
| `-calculateOrthoProjection` | — / `rsorthoFile` / `rsorthoFile rsboxFile` | Optional `.rsortho` parameter file, optional `.rsbox` to bound the area. Process id `20564 CREATE_ORTHO_PROJECTION`; batch rendering is `20565 RENDER_ORTHOS_IN_BATCH`. |
| `-selectOrthoProjection` | `orthoName` | — |
| `-editOrthoProjectionSelection` | `"key=value"` | Only documented key: `orthoProjectionName`. |
| `-exportOrthoProjection` | form 1: `orthoName fullPath params.xml`<br>form 2: `orthoName folderPath exportName params.xml`<br>form 3: `fullPath params.xml` (selected projection) | Omitting the extension on `fullPath`/`exportName` yields **TIFF**. Process ids `20578`, `20579`, `20583`. |
| `-computeContours` | `[params.xml]` | Contours for the selected ortho. |
| `-exportContours` / `-renameContours` / `-selectContours` | `fileName [params.xml]` / name / name | Contour objects. Formats: `.dxf`, `.shp` [OFFICIAL: install `isolines.xml`]. |
| `-calculateCrossSections` | `[step] [axis]` | Axis is a **local axis of the reconstruction region**. |
| `-exportCrossSections` / `-renameCrossSections` / `-selectCrossSections` | `fileName [params.xml]` / name / name | Formats `.dxf`, `.shp` [OFFICIAL: install `modelcrosssections.xml`]. Process id `20744 EXPORT_MODEL_CUTS`. |
| `-exportShapes` | `fileName` `[params.xml]` | Selected shapes → `.json`. |
| `-importShapesToSelectedOrtho` / `-importShapesToOrtho` | `fileName [orthoName] mosaicing`\|`measurements` | Shape type follows the active shape-creating tool. |
| `-selectShape` / `-addShapeToSelection` | `shapeName` | — |

[OFFICIAL: appbasics/allcommands; tutorials/commandline_3]

**There is no `-exportOrtho` command.** The name is `-exportOrthoProjection`.

Epic's own end-to-end example — note that **both** files are required and both
come from the GUI [OFFICIAL: tutorials/commandline_3]:

```bat
RealityScan.exe -load "F:\na156_h2024_v2\aligned\zone_1.rsproj" ^
  -selectMaximalComponent ^
  -calculateNormalModel ^
  -calculateOrthoProjection "F:\rs_params\params.rsortho" ^
  -exportOrthoProjection "F:\out\ortho.tiff" "F:\rs_params\exportOrthoParams.xml" ^
  -save "F:\na156_h2024_v2\aligned\zone_1.rsproj" -quit
```

(That last `-exportOrthoProjection` is **form 3** — `fullPath params.xml`,
acting on the currently selected projection, which the freshly-computed one is.)

**Export formats** [OFFICIAL: install `ortho.xml`], all `writer="RealityScan.Export.OrthoExport"`:

| Format id | Mask | `desc` (exactly as shipped) | Requires |
|---|---|---|---|
| `{97A2849B-5E03-4F4A-9694-8FD29DA987D6}` | `*.tiff` | `Color Orthographics Projection` *(sic — "Orthographics")* | `projection` |
| `{73F14019-F106-4663-97D3-06E2F5E7705D}` | `*.tiff` | `Digital Surface Model` | `projection` |
| `{28F39DAB-2F88-4C1A-8024-9498E6A281BC}` | `*.tiff` | `Digital Terrain Model` | `projection,dtm` |

The DTM entry's `requires="projection,dtm"` is the machine-readable statement of
§7: a DTM export is impossible unless the ortho was rendered with **Generate
DTM** on.

Export-dialog options common to all three [OFFICIAL: tutorials/orthophoto_export]:

| Control | Values / meaning |
|---|---|
| Export world file | Yes/No — the plain-text sidecar GIS software uses to georeference a raster. |
| World file coordinate system | `Projected` (model projected on the plane defined by the reconstruction box — for turned elevations) · `Global` (maps, top views) · `Image` (elevations, sections). |
| Export projection parameters file | Writes the `.rsortho` (§15.2). **This is the only way to obtain one.** |
| Compression | Compression algorithm for the raster. |
| Export as BigTIFF | For outputs above 4 GB; offered when `.tif`/`.tiff` is chosen. |
| Tile image format / Tile image resolution (pixel) | Pyramid tiling; offered only for `.KML` / `.KMZ`. Epic recommends the `Map` projection type for these. |

### 15.2 The `.rsortho` parameter file

Generated by creating an ortho manually, exporting it in any format with
**`exportProjectionParametersFile` = True**
[OFFICIAL: tools/xmlparamsfiles]. Structure — three blocks in one file:

| Attribute | Meaning |
|---|---|
| `width` / `height` | Projection resolution in pixels |
| `name` | Projection name |
| `modelName` | **Which model the projection is computed for** |
| `boxSideConerIndex` *(sic)* | `0`–`23`; which side of the reconstruction region is the projection plane and which corner is the image top-left. Not derivable analytically — create one ortho manually, export the params, reuse the number |
| `colorType` | `texturing` or `coloring` |
| `bEmpty` | `0` = render now (the Render button); `1` = create unprocessed, batch later (Add to batch). Epic recommends leaving it `0` |
| `backFaceColorType` | `0` = None, `1` = FixedColor |
| `backFaceColor` | Packed color for back faces (e.g. `2130706687`) |

Then a `<ReconstructionRegion>` block (§2.2) and a `<DTMParams>` block (§7).

### 15.3 Ortho projection controls

[OFFICIAL: tutorials/orthophoto]

| Control | Values |
|---|---|
| Type | `Arbitrary` (no restrictions) · `Top` (georeferenced orthophoto/DSM for GIS; always aligned to the chosen CRS) · `Side` (plane orthogonal to the ground plane; for CAD documentation) · `Map` (CRS forced to WGS84, rotations locked to 0; use for KML/KMZ). Type is only available for georeferenced scenes; otherwise `Arbitrary` is forced |
| Rendering method | Image mosaicing (general or aerial); true ortho from a textured or a colored model |
| Width / Height / Ortho pixel size | Mutually dependent; changing one recomputes the others. "Estimate optimal resolution" derives them from the selected model |
| Color type | From coloring or from texturing |
| Backface color / transparency | Applies when a back face projects into the rectangle (model sections) |
| Generate DTM / DTM from classification | ON/OFF; pick an existing classification or create a new one (then §7's `ClassificationParams` apply) |

DSM/DTM export adds: Color palette, Color depth (8-bit/16-bit), **Pixel type**
(`Altitude` in the project CRS · `Depth (local)` from the top of the
reconstruction region · `Depth (global)` from the plane through the CRS zero
point parallel to the projection plane), Normalize image (heights to <0,1> —
never with Depth (global)), and Alpha channel (RGBA with transparent
background; ~4× file size). **Depths export in a JET color scale for RGB
formats; choose `.tiff` to get float depths**
[OFFICIAL: tutorials/orthophoto_export].

### 15.4 Volumes and areas

There are **two different sets** of volume/area numbers and they are not
computed the same way. Conflating them is easy and wrong.

**Whole-ortho values**, shown in the Selected ortho photo(s) panel, referenced
to the **reconstruction region** [OFFICIAL: tutorials/orthophoto_export]:

| Value | Definition |
|---|---|
| `Cut volume` | Volume between the **bottom** side of the reconstruction region and the visible surface of the rendered model. |
| `Fill volume` | Volume between the **top** side of the reconstruction region and the visible surface. |
| `Area 2D` | Area of the rendered projection = area of the top/bottom side of the region. |
| `Area 3D` | Area of the visible surface of the rendered model. |

**Per-shape values**, computed from shapes drawn on the ortho, referenced to a
chosen **base plane** [OFFICIAL: tools/volumeandsurface]:

| Value | Definition |
|---|---|
| `Cut volume` | Volume **above** the base plane, from the plane to the model surface. |
| `Fill volume` | Volume **below** the base plane. |
| `Area 2D` | Area of the shape's surface parallel to the region's upper side. |
| `Area 3D` | The same shape translated onto the model. |
| Base plane type | `None` (values are not updated; the last computed ones stay) · `Interpolated` (interpolates the terrain inside the shape; need not be flat) · `Flat at min. and max. height` (two planes — cut measured from the bottom, fill from the top) · `Flat at user-defined height` (set `Base plane at height`) · `Best-fit plane` (linear regression over the terrain heights). |

**No CLI command returns any of these numbers, and shapes cannot be created
headless.** Shape creation is mouse-driven (`Measure` / `Enhance Mosaic`;
line, circle, rectangle, polygon, freeform, brush); shapes can only be
*imported* (`-importShapesToOrtho` / `-importShapesToSelectedOrtho`) or
*exported* (`-exportShapes` → `.json`).

The values are reachable headless **only through report functions** (§18.4)
[OFFICIAL: appbasics/reports_fav_ortho]:

| Function | Variables | Scope |
|---|---|---|
| `$OrthoProjectionVolume( orthoGuid, … )` | `orthoCutVolume`, `orthoFillVolume`, `orthoArea2d`, `orthoArea3d` | whole ortho, region-referenced |
| `$IterateOrthoMeasurements( orthoGuid, … )` | `cutVolume`, `fillVolume`, `area2d`, `area3d`, `orthoPerimeter`, `gpsPerimeter`, `hasOrthoVolume`, `hasOrthoArea`, `isClosed`, `boundaryMin/MaxBoxHeight`, `boundaryMin/MaxAltitude`, `regionName`, `regionGuid` | per shape/region |

Note the exact spellings: **`orthoArea2d`/`orthoArea3d` are lower-case `d`**,
and the whole-ortho names have no `Projection` in them. The similar-looking
`orthoProjectionCutVolume` / `orthoProjectionFillVolume` /
`orthoProjectionArea2D` / `orthoProjectionArea3D` are strings in the
**`-editOrthoProjectionSelection` panel-key space**, not report variables
[[UNDOCUMENTED]; see `03-settings-keys.md` §8.7]. Using one where the other
belongs yields an empty substitution, silently.

### 15.5 Status here

**Nothing in the ortho/DTM/contour/cross-section family has ever been run
through this CLI.** No `.rsortho` exists in the repo. For a wreck survey the
plausible first deliverable is a `Side`-type true ortho of the hull from the
textured model plus a DSM. [OPEN] — the blocking prerequisite is one manual GUI
ortho to obtain a `boxSideConerIndex` and a params file; after that it is fully
scriptable.

---

## 16. Other exports from a modelled scene

| Command | Params | Output | Notes |
|---|---|---|---|
| `-exportSparsePointCloud` | `fileName` `[params.xml]` | 3D **tie points** (sparse cloud) | Formats defined in install `structure.xml`, all `writer="cvs"` with template bodies you can read: `XYZ File Format` (`*.xyz`), `XYZRGB File Format` (`*.xyzrgb`), `Sparse point cloud as XYZ Point Cloud (*.xyz)`, `… as Wavefront obj (*.obj)`, `… as Polygon File Format (*.ply)`. The last three take boolean parameters `Export vertex colors` (default `true`) and, for PLY, `Export ascii` (default `true`). Process id `20585 EXPORT_POINT_CLOUD`. **There is no `-exportPointCloud` command.** |
| *(dense point cloud)* | — | — | There is **no dense-cloud command either**. The dense cloud *is* the model's vertices — "this point cloud is not the same as the sparse point cloud created after the alignment, but it is made out of the mesh vertices" [OFFICIAL: tutorials/quickstart_6_computeModel] — so it is exported with `-exportModel` to `.ply` / `.xyz` / `.las` / `.ptx`, which is exactly what `ExportDeliverables.bat` does with `ModelExportParamsPLY_DensePoints.xml` (`MvsMeshExportColors=true`, `MvsMeshExportTexturing=0`). |
| `-exportMapsAndMask` | `folderName params.xml` (both effectively required) | Model-derived masks + **depth** and **normal** maps for the selected images | **Depth maps are EXR; normal maps and mask images are PNG** — the format is fixed, not chosen. Dialog controls: Export masks / Export camera depths / Export camera normals toggles, `Distance scale`, `Near Plane Distance` and `Far Plance Distance` *(sic)* which clip the depth range, camera-space vs world-space `Normals format`, `Export Image List` + `Export Image List File Name` (writes a text file pairing each input's full path with its map filenames), `Export File Naming`, and the full undistortion block. With neither parameter results land beside the originals. Named `-exportDepthAndMask` in `tutorials/commandline_3` — [INFERRED] a stale pre-rename page; both process ids exist (`36 EXPORT_DEPTH_AND_MASK_IMAGES`, `20586 EXPORT_DEPTH_AND_MASK`). |
| `-generateMaskFromMesh` | — | Mask images from existing camera views + the selected model | Everything around the model is masked out. |
| `-exportMasks` | `folderPath params.xml` **or** `params.xml` | Current mask images | Two forms; the one-argument form writes beside the originals. Process id `14 EXPORT_MASK`. |
| `-exportSTMap` | `folderName params.xml` | `.exr` ST maps (distorted↔undistorted mapping) | Prerequisite: aligned model. Params from the Export Registration dialog. Process id `43 EXPORT_ST_MAPS`. |
| `-exportUndistortedImages` | `folderName` `[params.xml]` | Undistorted images | Spelled `exportUndistoredImages` (missing `t`) in `tutorials/commandline_1` — **do not use that spelling**. Process id `21812`. |
| `-exportCameraSnapshots` | `folderName` `[params.xml]` | Rendered views of the model from camera positions | All cameras when none or one is selected, otherwise only the selected. Process id `15 EXPORT_RENDER`. |
| `-exportSelectedCamerasSnapshots` | `folderName fileFormat` `[params.xml]` | Same, selected cameras only, `fileFormat` e.g. `jpg`, `png` | Master table only. |
| `-renderMeshFromCustomPositionYPR` / `…LookAt` / `…GridPositionYPR` / `…GridPositionLookAt` | `fileName params.xml` **or** fully inline | Rendered image from an arbitrary camera pose | Inline form: `fileName width height focalLength x y z yaw pitch roll` (or `atX atY atZ [upX upY upZ]`). Doc example: `RealityScan.exe -renderMeshFromCustomPositionYPR "D:/Project/render.png" 1280 720 100 0 0 150 0 0 0`. |
| `-exportControlPointsMeasurements` | `cpmFileName` `[params.xml]` | Control-point image measurements | Four CSV variants in install `measurementsexport.xml`: comma / space / tab separated, and space-with-quotes, each `Image, Point, X, Y` at 2 decimals. **The params file requires Shift + the Control Points button in ALIGNMENT ▸ Export** — a GUI-only prerequisite. Process id `20569`. |
| `-exportGroundControlPoints` | `gcpFileName` `[params.xml]` | GCPs | Process id `21814`. |
| `-listControlPoints` | `fileName` | Control-point list with indices | The one control-point readout that needs no params file. |

[OFFICIAL: appbasics/allcommands; tools/depthandmask; tools/st_maps;
tools/undistort; install `structure.xml`, `measurementsexport.xml`,
`depthnormalmaskimage.xml`, `masklayer.xml`, `camerassnapshots.xml`]

**There is no `-exportMeasurements` command.** Measurement exports are split
across `-exportControlPointsMeasurements` (image measurements),
`-exportShapes` (ortho measurement shapes → `.json`), `-exportCrossSections`
and `-exportContours`.

Undistortion parameters, in the order the application applies them, since they
appear in three different dialogs (model export, maps-and-masks, undistorted
images) [OFFICIAL: tools/undistort]:

1. **Image cut-out** — fraction of the image considered (`1.0` = full;
   **`0.8` recommended for fish-eye lenses**).
2. **Fit** — `Outer boundary` / `Inner region` / `In between` / `Keep
   intrinsics` (the last preserves the calibration parameters).
3. **Resolution** — `Fit` (keep step-2 resolution) / `Preserve` (original
   resolution) / `Custom`.
4. **Downscale** — integer divisor of each side.
5. **Max count of pixels** — `0` = no limit; otherwise the aspect ratio is kept
   and the image is resampled to fit.
6. **Undistort principal point** — `1` shifts the optical center to the actual
   image center, `0` leaves it.

**XMP and registration exports** (`-exportXMP`, `-exportXMPForSelectedComponent`,
`-exportRegistration`) belong to the alignment/metadata sibling document. Two
facts must be repeated here because they bite during export sessions:
`-exportRegistration` **without a params XML blocks forever headless**
[VERIFIED: FINDINGS 2026-07-21], and **flight-log import leaves the matched
images actively selected**, after which selection-driven exports under
`-silent` export nothing — always `-deselectAllImages` before exporting
[VERIFIED: FINDINGS 2026-07-23].

---

## 17. Publishing targets: Nira, Cesium ion, Sketchfab

The in-app Share menu is defined in install `share.xml`, three formats, all
`mask="*.zip"` and all `requires="model"`
[OFFICIAL: install `share.xml`; tools/share]:

| `desc` (exactly as shipped) | `writer` |
|---|---|
| `Upload To SketchFab` | `RealityScan.Export.SketchFabUploader` |
| `Upload To Cesium ion` | `RealityScan.Export.CesiumIonUploader` |
| `Upload to Nira` | `RealityScan.Export.NiraUploader` |

The SketchFab entry's own `<hint>` carries a behaviour the Sketchfab Help page
does not: **"The model triangle count and texture will be automatically adjusted
to your account limits if necessary"** [OFFICIAL: install `share.xml`] — i.e. a
Sketchfab upload can silently decimate the deliverable to fit a plan quota.

**Only Sketchfab has a CLI command.** `-uploadToSketchfab <APIToken>`
(process ids `21802 EXPORT_SKETCHFAB`, `24576 UPLOAD_TO_SKETCHFAB`). Cesium ion
and Nira uploads are **GUI-only** — verified against the official command list
[VERIFIED: `publish_cesium.py` docstring 2026-07-29; HANDOFF 2026-07-29:
"neither platform's in-app share is scriptable"]. Both therefore go through
each platform's own API from outside RealityScan.

### 17.1 Nira

| Fact | Detail | Source |
|---|---|---|
| Preferred format | **OBJ, not FBX** | [VERIFIED-as-guidance: help.nira.app article 5591333681307, recorded in `publish_nira.py` + HANDOFF 2026-07-29] |
| Mesh by parts | **Yes** | same |
| Vertex colors | **No** | same |
| Number precision | **decimal-6** (`MvsMeshExportNumberFormat=6`) | same |
| CRS | matched **cartesian** project/output CRS; if the preferred CRS is not cartesian, use the UTM zone matching the model's location | [OFFICIAL: tools/niraexport] + same |
| Point clouds | **PLY is REFUSED.** Only LAS / LAZ / E57, and a point cloud must be part of the **initial** upload — it cannot be appended later | [VERIFIED-as-guidance: `publish_nira.py`] |
| Include | the `.mtl`, the textures, and the `.rcInfo`/`.rsInfo` sidecar (it carries georeferencing) | same |
| Scripted upload | Nira's official client `github.com/NiraOfficial/niraclient`. **Requires a Nira ENTERPRISE plan**; Individual/Professional accounts are browser-upload only | same |

The in-app path, for contrast [OFFICIAL: tools/niraexport]: WORKFLOW ▸ Output ▸
Share ▸ Upload to Nira, authenticating with the Nira **Organization** name,
**Key ID** and **Key secret** from the Nira admin page; options are *Upload
Camera parameters and images* (exports the camera positions and the images
alongside the model) and *Open in the default web browser after upload*.
**RealityScan stages the prepared files in its own cache before uploading** —
so a Nira upload of a large asset is another consumer of the cache disk that
§12.4 is about.

`ModelExportParamsOBJ_NiraParts.xml` is exactly this specification
(`ByParts=1`, `Colors=false`, `NumberFormat=6`, `TexImgFormat=png`,
`InfoFile=true`, scale 1.0). `publish_nira.py` builds an explicit typed JSON
file list rather than relying on Nira's auto-detection (its docstring records
that image auto-detection is unreliable) and pipes it to
`nira.py asset create <name> photogrammetry`.

**KNOWN DEFECT, unfixed as shipped:** `publish_nira.py`'s sidecar filter is
`SIDECAR = {'.rcinfo'}` — the **legacy** extension. RealityScan 2.2 writes
`<model>.<ext>.rsInfo`, whose lower-cased suffix is `.rsinfo`, so the info file
is **silently excluded from the Nira file list** even though the script's own
docstring says to include it because it carries georeferencing. Fix: accept
both `.rsinfo` and `.rcinfo` [VERIFIED-by-inspection: `publish_nira.py`
vs the verified export layout in §13.4, 2026-08-04].

**The dense PLY deliverable is for local use only** and is explicitly not a
Nira artifact [VERIFIED-by-inspection: `ExportDeliverables.bat` header].

### 17.2 Cesium ion

A model **does not have to be georeferenced** to be uploaded; its approximate
position can be defined later [OFFICIAL: tools/cesiumion]. Two documented
routes: the GUI Share button, or exporting Cesium 3D Tiles (`.json`) via the
Level of Detail button and uploading through ion's "Add data".

**Cesium staff guidance recorded here: upload the RAW mesh (OBJ recommended) so
ion's Reality Tiler processes it — ion hosts a pre-tiled 3D Tiles export as-is
without reprocessing. Multi-texture meshes (e.g. 4×16K) are supported by the
current tiler** [VERIFIED-as-guidance: `publish_cesium.py` docstring,
2026-07-29].

`publish_cesium.py` implements ion's documented REST flow:

```
1. POST /v1/assets           type=3DTILES, options.sourceType=3D_CAPTURE,
                             options.targetVersion=1.1, options.textureFormat=KTX2,
                             options.inputCrs=<EPSG:xxxxx>   (omit for local coords)
2. upload the files to the returned S3 location (12 h credentials)
3. POST the onComplete notification
4. poll GET /v1/assets/<id> until COMPLETE / ERROR / DATA_ERROR
```

Uploaded extensions: `.obj .mtl .fbx .dae .gltf .glb .jpg .jpeg .png .bmp .tga
.dds .bin`. Auth: an ion access token with `assets:write` + `assets:read`, via
`--token` or `CESIUM_ION_TOKEN`. Dependencies `requests`, `boto3`.

```bat
py -3.13 publish_cesium.py --name "IN-401 hull" ^
    --dir F:/na156_h2024_v2/exports/cluster_0_a2_c0/obj ^
    --input-crs EPSG:32604 --description "NA156 H2024 hull" --poll
```

### 17.3 Sketchfab

`-uploadToSketchfab <APIToken>` is the only scriptable publish command. The GUI
dialog offers Mesh and Texture quality presets `Original`, `High`, `Medium`,
`Low`, and a "Publish the model after upload" toggle; diffuse and normal
textures upload automatically; the uploaded model is saved back into the
project as a new object in the 1Ds view; the model is **unlit (shadeless) by
default** [OFFICIAL: tools/sketchfabexport].

[INFERRED] it requires online communication and is therefore incompatible with
`-disableOnlineCommunication` — not stated in the Help; would be settled by
running both in one command sequence. Never exercised here.

### 17.4 Batch driver

`publish_batch.py --workspace <ws> --prefix "<name>" [--input-crs EPSG:…]
[--components …] [--dry-run]` loops `exports/<component>/obj` — the format
**both** platforms recommend for photogrammetry — and drives
`publish_cesium.py` / `publish_nira.py` per component. Each destination
activates only when its credential env var is present (`CESIUM_ION_TOKEN`,
`NIRACLIENT_DIR`); `--dry-run` previews every command without uploading.
Results land in `<workspace>/publish_report.json`
[VERIFIED-by-inspection: `publish_batch.py`].

---

## 18. Reports, quality analysis and inspection

This is the answer to "a headless pipeline needs a machine-readable record of
what it built". RealityScan's report system is a **generic text-substitution
templating engine**, and Epic states plainly that **you can create any type of
file, not just HTML** [OFFICIAL: appbasics/reports_functions_and_variables]. A
CSV or JSON report template is therefore the sanctioned way to get structured
build metadata out of a headless session.

### 18.1 Commands

| Command | Required | Optional | Notes |
|---|---|---|---|
| `-exportReport` | `outputFileName` `templateFileName` | `true`\|`false` | Render a template to a file (`outputFileName` includes the path and the `.html` extension in Epic's wording). Default templates live in `<install>\Reports`. The boolean "exports a file with the reports found in the specified template". Process id `20567 EXPORT_REPORT`. |
| `-printReport` | `reportString` | — | **Does not work with delegation** [OFFICIAL] — therefore unusable in this repository's `-delegateTo` architecture. |

[OFFICIAL: appbasics/allcommands]

### 18.2 Shipped templates

Registered in `C:\Program Files\Epic Games\RealityScan_2.2\report.xml`, bodies
`$Include("Reports\<file>.html")` [OFFICIAL: install `report.xml`;
appbasics/reports]:

| `desc` | Template file | `requires` |
|---|---|---|
| Overview Report | `Reports\Overview.html` | — |
| Registration and Georeferencing Accuracy Report | `Reports\ComponentAccuracyReport.html` | `component,georeferenced` |
| Selected Component Report | `Reports\SelectedComponent.html` | `component` |
| Selected Ortho Projection Report | `Reports\SelectedOrtho.html` | `projection` |
| Selected Model Report | `Reports\SelectedModel.html` | `model` |
| Tie Points of Selected Component | `Reports\SelectedComponentsTiePointsStats.html` | `component` |
| Map View Report | `Reports\MapView.html` | `component,projection,geospatial` |
| RealityScan sparse reconstruction in web-browser | `Reports\AlignmentView.html` | `component` |

Also present in the folder but not registered as separate formats:
`Misalignment.html`, plus `images\`, `scripts\`, `styles\` and per-language
subfolders. **Epic warns these are replaced by any software update or
reinstall — back up edited templates and keep custom ones on a local drive**
[OFFICIAL: appbasics/reports].

Registering a custom template — add between the `<Report>` tags of
`report.xml` [OFFICIAL: appbasics/reports_functions_and_variables]:

```xml
<format id="{00000000-0000-0000-0000-000000000001}" mask="*.htm"
        desc="Your Custom Report Name" writer="RealityScan.Export.ReportWriter">
  <hint>Describe what the report is intended for</hint>
  <body>$Include("D:\rs_templates\myReport.csv")</body>
</format>
```

**This is a modification of an Epic-shipped file in Program Files.** The same
class of edit was already made here once — `flightlogs.xml` was hand-edited to
add a 13-column flight-log format — and it must be re-checked after any app
update [VERIFIED: PRIORS_DISTORTION_TEST_PLAN, 2026-07-25]. `-exportReport`
takes the template **path** directly, so a custom template does **not** have to
be registered in `report.xml` to be used from the CLI; registration is only
needed for the GUI dialog [INFERRED from the command signature — the parameter
is `templateFileName including the path`; untested].

### 18.3 Template syntax

[OFFICIAL: appbasics/reports_functions_and_variables]

- `$(variable_name)` substitutes a variable; the contents may be an
  **expression** with formatting: `$(focalLength*36:.2)`,
  `$(modelTextureUtilization * 100 :.0f)`, `$(x:.8)`.
- `$FunctionName( args )` calls a function. Iterator functions define a scope
  and expand their body once per item:
  `$ExportCameras(Camera $(index), image="$(imageName).$(imageExt)\n")`.
- Two output locations: the main file (chosen by the caller) and an
  **attachments folder** created automatically. All relative paths resolve
  against the attachments folder; prefix `global://` for absolute paths, e.g.
  `"global://d:/exports/image.jpg"`.
- `$Include("path")` inlines a file; `$ImportFile(src, dst)` copies one into
  the attachments folder, e.g.
  `$ImportFile("Reports\\images\\camera.png", "camera.png")` — note the doubled
  backslashes in Epic's own example.
- Control-flow / arithmetic functions usable in any scope
  [OFFICIAL: appbasics/reports_fav_basic]: `$If( condition, text )`,
  `$Ifdef( var, text )`, `$Ifndef( var, text )`, `$Declare( var, value )`,
  `$Set( var, value )`, `$Sum( outputVar, … )`, `$Prod( outputVar, … )`,
  `$Append( var, … )`. Constants `true` and `false` exist as variables. These
  are what make a machine-readable (CSV/JSON) template practical: emit a header
  once, guard optional fields with `$Ifdef`, accumulate totals with `$Sum`.

### 18.4 The variables a build record needs

**Model scope** [OFFICIAL: appbasics/reports_fav_models]:

| Function | Variables |
|---|---|
| `$IterateModels( componentGUID, … )` | `modelGUID`, `modelName`, `modelTrianglesCount`, `modelVerticesCount` |
| `$ExportModels( … )` | `modelName`, `modelGuid`, `modelTriangleCount`, `modelVertexCount`, **`modelPartCount`**, `modelUnitSize`, `modelUnits`, `modelIsColored`, `modelIsTextured` |
| `$ExportTextureInfo( … )` | `modelTextureLayerCount`, `modelUnwrapStyle`, **`modelTextureCount`**, `modelTextureResolutionX/Y`, `modelGutterSize`, `modelTextureUtilization`, `modelOptimalTexelSize`, **`modelTextureQuality`**, `modelTexelSize`, `selectedTextureLayerGuid` |
| `$IterateTextureLayers` / `$ExportTextureLayerInfo( textureLayerGuid, … )` | `textureLayerGuid`, `textureLayerStyle`, `textureLayerType`, `textureLayerName`, `textureLayerPixelFormat`, `textureLayerHasInputLayer`, `textureLayerInputLayer`, **`textureLayerHasSourceModel`**, `textureLayerSourceModelGuid`, `textureLayerHasSourceLayer`, `textureLayerSourceLayerGuid`, `textureLayerTime` |
| `$ModelStats( modelGuid, … )` | `modelDepthMapsTime`, `modelMeshingTime`, `modelPostprocessTime`, `modelColoringTime`, `modelUnwrapTime`, plus `modelTexturingTime` and `modelTotalTime` used in Epic's own example (and `…Str` string forms of each) |
| `$ModelSettings( modelGuid, … )` | **`modelQuality`** (the quality level actually used), **`modelImageDownscaleFactor`** (the depth-map image downscale) |
| `GetNumberOfModels( componentGuid )` | expression function (not `$`-prefixed — usable inside `$(…)`) |

`$ExportTextureInfo`'s documented variable list omits `modelTextureStyle`, which
Epic's own worked example nevertheless uses ("Texturing style:
`$(modelTextureStyle)`") [OFFICIAL-in-example: appbasics/reports_fav_models;
[INFERRED] it is live]. `$ModelStats`'s list likewise omits `modelTexturingTime`
and `modelTotalTime`, both used in the same example.

`textureLayerHasSourceModel` / `textureLayerSourceModelGuid` are set when a
texture layer was created by the **Texture Reprojection** tool — i.e. a report
can prove that `_Simplified_Textured` really carries the reprojected
`_HighPoly_Textured` texture rather than a fresh one [OFFICIAL:
appbasics/reports_fav_models].

**Component scope** [OFFICIAL: appbasics/reports_fav_components] — this is what
would close two long-standing open cells:

| Function | Variables |
|---|---|
| `$IterateComponents( … )` | `componentGUID`, `componentName`, `componentCamerasCount` |
| `$ComponentInfo( componentGUID, … )` | `componentName`, `componentId`, `componentReconstructionId`, `componentCameraCount`, `componentPointCount`, `componentControlPointCountUsed`, `componentConstraintCountUsed` |
| `$ComponentStats( componentGUID, … )` | `componentTotalProjection`, `componentAverageTrackLength`, **`componentMaximalError`**, **`componentMedianError`**, **`componentMeanError`** (reprojection error in pixels), **`componentIsGeoreferenced`**, **`componentMetric`** (component is scaled to real dimensions), `componentAlignmentTime` |
| `$ComponentSettings( componentGUID, … )` | `componentAlignmentEngine`, `componentAlignmentMode`, `componentMaxFeaturesPerMpx`, `componentMaxFeaturesPerImage`, `componentDetectorSensitivity`, `componentPreselectorFeatures`, `componentImageDownscaleFactor`, `componentMaxFeatureReprojectionError`, `componentUseCameraPositions`, `componentLensDistortionModel`, `componentFinalOptimization` — i.e. **the alignment settings actually used, read back out of the project**, which is the only route to a provenance record of a component whose `AlignmentParams.xml` was not archived |
| `$SelectComponent( componentGUID )` | sets the component for `$IterateImages` / `$IterateCameras`; affects nothing else |

**`componentIsGeoreferenced` and `componentMetric` are candidate answers to
hardening cell U7** (a CLI-observable georeferencing check for a merged
assembly — the longest-standing open item, open since 2026-07-23, with owner
GUI screenshots as the interim proxy), and **`componentMedianError` /
`componentMeanError` are the candidate answer to U14** (per-component
reprojection error headless, needed for twin-keeper choice)
[VERIFIED-as-candidate: `testing/ALIGN_MERGE_HARDENING_PLAN.md` U7/U14].
[OPEN] — the blocker is that `-exportReport` has **never been run here**, and
the sibling `-exportRegistration` is known to block forever headless without a
params file, so the cell explicitly flags a blocking risk. Note that both cells
describe the probe as "`-exportReport` with a components **params file**
exported once from the GUI" — that phrasing is wrong: `-exportReport` takes
`outputFileName templateFileName`, a **template**, and there is no GUI export
that produces one. Write the template by hand. **Cheapest probe:
delegate `-exportReport` with a watchdog on the smoke fixture using a
one-line custom template containing only `$IterateComponents($ComponentStats(…))`;
if it returns, U7 and U14 both close.**

**Global/project scope** [OFFICIAL: appbasics/reports_fav_basic]: `dateTime`,
`appVersion` (the environment-snapshot value a run record needs),
`appLanguage`, `fileName`, `attachmentPath`, `cameraCount`, `pointCount`,
`measurementCount`, `commonWidth`, `commonHeight`, `isGeoreferenced`, `units`,
`unitsShort`, `coordSystemName`, `isCoordSystemLatLon`, `coordSystemUnit2Meter`,
`displayScale`, plus the **component anchor** block (`anchorX/Y/Z`,
`anchorR00`…`anchorR22`, `anchorYaw/Pitch/Roll`) that maps a component's
near-zero local coordinates into global Euclidean space:
`EuclideanX = anchor.Rotation * X + anchor` (and the Y/Z forms).

`$ExportProjectInfo( … )` adds the project-identity block a build record needs:
`projectName`, `projectPath`, `changeCount` (number of actions performed in the
project), `imageCount`, `componentCount`, `actualComponentGUID`,
`actualModelGUID` [OFFICIAL: appbasics/reports_fav_basic].

**Ortho scope** [OFFICIAL: appbasics/reports_fav_ortho]:

| Function | What it yields |
|---|---|
| `$IterateOrthoProjections( … )` | `orthoIndex`, `orthoGuid`, `orthoName`. Iterates the **selected** orthos, or all of them if none is selected. |
| `$ExportOrthoProjection( orthoGuid, … )` | `orthoGUID`, `componentGUID`, `orthoName`, `orthoWidth`, `orthoHeight`, `orthoUppx`/`orthoUppy` (units per column/row pixel), `orthoDepth/Width/HeightInOrthoCoordUnits`, `orthoType`, `orthoCoordSystem`, `orthoCoordProjection`, `orthoCoordPrimeMeridian`, `orthoCoordUnits`, `orthoCoordUnitsShort`, and — **only when `orthoType` is `Map (GPS)`**, in `epsg:4326` — `orthoCentreLat/Lon/Alt` and `orthoCornerNW/NE/SE/SWLat/Lon`. |
| `$OrthoProjectionVolume( orthoGuid, … )` | `orthoCutVolume`, `orthoFillVolume`, `orthoArea2d`, `orthoArea3d` (§15.4). |
| `$OrthoProjectionTiming( orthoGuid, … )` | `orthoRasterizeTime`, `orthoDtmTime`, `orthoMosaicTime`, `orthoTotalTime`, all in seconds. |
| `$IterateOrthoMeasurements( orthoGuid, … )` | per-shape geometry and volumes (§15.4). |
| `$SaveOrtho( orthoGuid, inputLayer, filePath, width, height )` / `$SaveOrthoWithRegions( … )` | Writes a raster. `inputLayer` ∈ `"color"`, `"altitude"`, `"depth"` for the DSM layer and `"color@1"`, `"altitude@1"`, `"depth@1"` for the DTM layer. |
| `$IterateOrthoMapTiles( orthoGuid, inputLayer, … )` + `$SaveOrthoMapTile( "path" )` / `$SaveOrthoMapTileMask( "path" )` | 256×256 slippy tiles with `tileX`/`tileY`/`tileZ`; georeferenced components only; `png`, `bmp`, `dib`, `tiff`. |
| `$IterateContourSets` / `$ExportContourSet` / `$IterateContours` / `$IteratePolylines` / `$IteratePoints` | The full contour geometry, headless — the only route to contour *values* without `-exportContours`. |

**Render functions usable from a template**: `$RenderMesh( modelGuid,
"filepath", width, height, cameraIndex[, textureLayerGuid] )` — **camera index
`-1` renders automatically from a camera with a good overview of the model** —
plus `$RenderMeshFromCustomPositionYPR` and `$RenderMeshFromCustomPositionLookAt`
with the same signatures as their CLI twins. That makes a per-component contact
sheet a report-only operation [OFFICIAL: appbasics/reports_fav_models].

### 18.5 Quality analysis and inspection

[OFFICIAL: tools/qualityanalysis; tools/inspection]

Three analysis types, reached from ALIGNMENT ▸ Analyze or MESH & COLOR ▸
Analyze:

| Type | What it computes | CLI reachability |
|---|---|---|
| **Tie point quality** | Quality of sparse tie points, primarily camera coverage per point; green→red scale in the 3Ds view | **No command.** GUI-only |
| **Mesh quality** | Quality per triangle, primarily camera coverage. Can be **baked into a texture** or used to **colorize vertices**; the values need not be computed beforehand | **`-calculateQualityTexture`** and **`-calculateQualityColors`** are the CLI equivalents of the Bake and Colorize buttons |
| **Advanced** | Camera relations, point-cloud uncertainty, misalignment detection | **No commands.** GUI-only — the tool runs as process `21807 INSPECT`, so it is a real background operation with no CLI entry point [OFFICIAL: tutorials/processids] |

Advanced parameters, for completeness (all GUI-only): *Camera relations* —
Component connectivity, Apical angle (smaller is better), Feature consistency,
Match count, Minimal/Maximal matches, Show edges (internal/external/both),
Analyze selection. *Point cloud uncertainty* — Relative method (Reference
uncertainty region percentile, default **70**; Color palette radius; Estimated
reference uncertainty (blue) and Low-quality points' threshold (red)) or
Absolute method (Minimal/Maximal uncertainty size in scene units, e.g. `0.01`
= 1 cm), plus Uncertainty line multiplier. *Misalignment detection* —
Misaligned points threshold, Misaligned camera pairs threshold, detector
sensitivity (higher = slower, more data, more false positives), Point size
multiplier, Display-only toggles, Misaligned components count.

**Exporting mesh quality is a real machine-readable option.** A quality
texture or quality vertex colors can be exported with the model — the export
dialog exposes **Grayscale quality values** precisely "to preserve the full
range and precision of the quality information"
[OFFICIAL: tools/export]. That is the one route by which per-triangle camera
coverage leaves a headless session as data rather than as a screenshot.
[OPEN] — never attempted here; the probe is
`-calculateQualityColors` + `-exportModel … .ply` with
`MvsMeshExportColors=true` on the 133-camera component.

### 18.6 What this repository actually records instead

No RealityScan report has ever been generated here. The machine-readable record
is entirely repo-side [VERIFIED-by-inspection]:

| Artifact | Contents |
|---|---|
| `models_report.json` | per component: `component`, `cameras`, `scale`, `status`, `why` (the scale-gate verdict and its explanation), `success`, `errors`, `duration_min`; plus a top-level `dated_copy` `{path, success}` [VERIFIED-by-inspection: `run_models.py`] |
| `merge_report.json` | per cluster: final components, camera counts, attribution, per-attempt evidence |
| `publish_report.json` | per component: asset name, per-destination command and return code |
| `logs/resources_GenerateModel_<stamp>.csv` | CPU, RAM, commit, project-disk and cache-disk free, sampled through the run |
| `<ErrorPath>\progress_<instance>.txt` | `algId frac elapsed remaining #tag` lines from `-writeProgress` |
| `expected_select_*.txt` / `expected_delete_*.txt` | filed evidence for every tolerated whitelisted failure |

The gap a report would close: **triangle counts, part counts, texture counts,
texture resolution, texture utilization, texel size and per-phase timings of
the delivered models are nowhere in this record.** They exist only inside the
`.rsproj`. A single `Selected Model Report` per component, or one custom CSV
template iterating models, would capture all of them in seconds.

---

## 19. Progress IDs for this stage

`-writeProgress` lines have the shape `algId progress duration estimation
eventType`, with `eventType` ∈ `#started`, `#progress`, `#timeout`,
`#completed` [OFFICIAL: tutorials/commandline_5]. These are the ids a tail
will see downstream of alignment [OFFICIAL: tutorials/processids]:

| id | Name | id | Name |
|---:|---|---:|---|
| `6` | `EXPORT_MODEL` | `20560` | `CALCULATE_MODEL_PREVIEW` |
| `7` | `MODEL_TEXTURE` | `20561` | `CALCULATE_MODEL_NORMAL` |
| `8` | `MODEL_COLORIZE` | `20562` | `CALCULATE_MODEL_HIGH` |
| `9` | `MARK_TRIANGLES` | `20564` | `CREATE_ORTHO_PROJECTION` |
| `10` | `FILTER_SELECTED_TRIANGLES` | `20565` | `RENDER_ORTHOS_IN_BATCH` |
| `11` | `SIMPLIFY` | `20567` | `EXPORT_REPORT` |
| `12` | `SMOOTH` | `20578` / `20583` / `20579` | `EXPORT_ORTHO_PHOTO` (×2) / `EXPORT_ORTHO_PHOTO_SINGLE_SELECTION` |
| `13` | `EXPORT_DEPTH_MAPS` | `20585` | `EXPORT_POINT_CLOUD` |
| `14` | `EXPORT_MASK` | `20586` | `EXPORT_DEPTH_AND_MASK` |
| `15` | `EXPORT_RENDER` | `20601` | `CONTINUE_MODEL_CALCULATION` |
| `17` | `IMPORT_MODEL` | `20736` | `COMPUTING_MODEL_PARAMS` |
| `23` | `CHECK_MODEL_INTEGRITY` | `20737`–`20741` | `UNWRAP_MODEL` |
| `25` | `CLEAN_MODEL` | `20742` | `FILL_TEXTURES` |
| `26` | `CLOSE_HOLES` | `20744` | `EXPORT_MODEL_CUTS` |
| `27` | `UNDERCUT_MODEL_PARTS` | `21024` | `EXPAND_SELECTION` |
| `28` | `CHECK_MODEL_TOPOLOGY` | `21025` | `EXPAND_CONNECTED_COMPONENTS_SELECTION` |
| `29` | `DUPLICATE_MODEL` | `21028` | `SELECT_MARGINAL_TRIANGLES` |
| `32` | `MERGING_PART_PAIRS` | `21029` | `SELECT_TRIANGLES_BY_EDGE_SIZE` |
| `33` | `MERGING_SIBLING_PARTS_IN_DECOMPOSITION` | `21030` | `SELECT_MAX_CONNECTED_COMPONENTS` |
| `34` | `CREATING_EXTERNAL_TRIANGLES_FOR_MODEL_PARTS` | `21040` | `REPROJECT_TEXTURE` |
| `35` | `EXPORTING_TO_PTX` | `21776`–`21786`, `21800`, `21815` | ground plane / reconstruction region ops (§2.3) |
| `36` | `EXPORT_DEPTH_AND_MASK_IMAGES` | `21802`, `24576` | Sketchfab export / upload |
| `42` | `AI_CLASSIFY` | `21811` | `ATOMIC_TRIANGLE_SELECTION` |
| `43` | `EXPORT_ST_MAPS` | `21812` | `EXPORT_UNDISTORTED_IMAGES` |
| `44` | `SIMPLIFY_GROUP` | `21813` | `EXPORT_CESIUM` |
| `45` | `REMOVE_TEXTURES` | `21876` | `CLI_EXPORT_MODEL` |
| `47` | `TRANSFER_IMAGE_LABELS` | `28672` | `EXPORT_LOD` |
| `48` / `51` | `OVERRIDE_CLASSIFICATION` / `AI_OVERRIDE_CLASSIFICATION` | `8208` / `8240` / `8242` | `DEPTH_MAPS` / `MESHING` / `CLUSTERING` |
| `50` | `MODEL_BASED_COLORNORMALIZATION` | `20532` / `20533` | `PROJECT_LOAD` / `PROJECT_SAVE` |

`#timeout` does **not** always mean hung: a successful 94.6 % align emitted 40
`#timeout` lines; the pathological signature is `#timeout` from fraction 0.00
with an ever-growing ETA. Adopted policy: warn at 2 h, never auto-kill
[VERIFIED: NA167 B4/#28]. In this stage the near-OOM case of §12.3 is a third
generator of the same signature.

---

## 20. Result codes seen in this stage

| Decimal | Hex | Meaning established here | Where it appears downstream of alignment |
|---|---|---|---|
| `0`, `1` | — | Routine success (both) | Every completed operation |
| `2147942487` | `0x80070057` `E_INVALIDARG` | Empty / no-op selection | `-selectModel <missing name>` (`err:5601`), empty triangle selections in `[2/8]`/`[3/8]`. **Whitelisted** by `:try_filter`, `:try_remove`, `:try_delete_model` |
| `2181038335` | `0x820000FF` | Warning class | Whitelisted alongside the above in the filter steps |
| `2147942512` | `0x80070070` `ERROR_DISK_FULL` | **RealityScan's CACHE disk full**, not necessarily the project disk | `-calculateTexture` / `-simplify` on a large component (§12.4) |
| `2147549183` | `0x8000FFFF` | Generic "unexpected program state" | Broken `-set` arguments; also a real reconstruction failure |
| `3` | — | Process exit code for a crash [OFFICIAL: see `01-cli-fundamentals.md`]. What was actually *observed* here is the aftermath: a minidump `RealityScanCrash-20260726-054742.dmp` in the `-silent` directory, and **the NEXT delegated command failing with `ERROR: Failed to delegate command: -renameSelectedModel "pd6_zone_1_c0_Manifold"`** — the signature of a dead instance, not a rejected operation. Under delegation the crashing instance's exit code is never seen by the driver at all | `closeHoles`/`cleanModel` (`[5/8]`) on the 3,738-camera hull [VERIFIED: FINDINGS 2026-07-26] |
| — | `0x82000017` | Warning-class load complaint from a stale `<name>.rsproj.new` beside the project — the load **still completes**, but an errors-marker-gated workflow aborts on it. Fix: rename the temp aside (reversible) | `-load` at the start of a model or export run [VERIFIED: FINDINGS 2026-07-29] |
| — | `0x82000060` | Unknown / invalid command | `-selectAllComponents`, which does not exist in 2.2 [VERIFIED: NA167 B2] |
| — | `err:5601` | "model name not found" — visible only in `RealityScan.log`, never in the errors marker | `-selectModel` |
| — | `err:7155` | "Parsing setting … failed" — an unquoted `key=value` split into two `.bat` arguments; the setting is **silently not applied** | any `-set` on this stage's keys [VERIFIED: NA167 B5] |

[VERIFIED: FINDINGS 2026-07-23 … 2026-07-29; SURVEY_empirical §1]

**The errors marker carries only the numeric result code, never the `err:NNNN`
text** — that exists only in `RealityScan.log`, which is **truncated on every
instance boot**. Copy the log inside the driver immediately after the failing
call returns, and validate any saved snapshot against a run-unique token before
reading numbers out of it: two overlapping drivers once produced a snapshot
whose head and tail belonged to different runs
[VERIFIED: FINDINGS 2026-07-23, 2026-07-27].

---

## 21. End-to-end runnable examples

### 21.1 Minimal: aligned project → high model → textured OBJ

```bat
set "MD=C:\Users\jonat\Desktop\CoyoteThings\RealityScan_CLI\modules\realityscan_interface\RS_CLI\Metadata"

RealityScan.exe -load "F:\na156_h2024_v2\aligned\zone_1.rsproj" ^
  -selectMaximalComponent ^
  -setReconstructionRegionAuto ^
  -calculateHighModel ^
  -closeHoles ^
  -cleanModel ^
  -calculateTexture "%MD%\Texturing_MaxTextureCount4_16k.xml" ^
  -renameSelectedModel "zone_1_High" ^
  -exportModel "zone_1_High" "F:\out\zone_1.obj" "%MD%\ModelExportParamsOBJ_NiraParts.xml" ^
  -save "F:\na156_h2024_v2\aligned\zone_1.rsproj" ^
  -quit
```

**The rename is deliberately last.** Naming the model right after
`-calculateHighModel` and exporting that name at the end is the obvious ordering
and it is wrong: any intervening step that creates a new model (Filter, Simplify,
Smooth, Cut by Box — and possibly Close Holes / Clean Model, which the Help does
not settle either way) leaves the *old* geometry under the old name, and
`-exportModel` matches exactly (§5.3), so the export would silently ship the
pre-cleaning mesh. Renaming the currently-selected model immediately before
exporting it relies only on the documented "last created model is selected"
rule (§5.2). `-exportSelectedModel "F:\out\zone_1.obj" "%MD%\…xml"` avoids the
name entirely and is safer still.

Non-delegated form, suitable for a one-shot `.bat`. In this repository every
operation instead goes through the `:run` subroutine
(`-delegateTo %RS_INSTANCE%` → grace → `-waitCompleted` → grace →
`-waitCompleted` → abort if `errors_<instance>.txt` is non-empty); never add a
second way to launch or monitor RealityScan.

### 21.2 Production: model every scale-passing component of an assembly

```bat
set RS_INSTANCE=RS1
set RS_CACHE_DIR=E:\rscache
REM RS_PROJECTS_DIR / RS_PROJECT_LABEL deliberately NOT set - see §11, §12.5
py -3.13 run_models.py --workspace F:\na156_h2024_v2
```

Smallest component first, scale-gated, resumable, one dated project copy at the
end. Expect the table in §12.1 for timings.

`RS_CACHE_DIR` is the one variable that turned three H2023 hull failures into a
success (§12.4) — set it to a volume with room for hundreds of GB and keep it
off the project drive. Add `set RS_HEADLESS=0` **only** when you want the
instance's GUI visible for a live look at the mesh; delegation and monitoring
behave identically either way, and any other value (or unset) keeps the default
`-headless` boot [VERIFIED-by-inspection: `SetVariables.bat` lines 34–38].

### 21.3 Production: export deliverables and publish

`exports\components.names` is authored from `merge_report.json` by
`wildscan.session.export_names_file` (Python, UTF-8 without BOM, CRLF). Hand
authoring it in PowerShell 5.1 with `Set-Content -Encoding utf8` writes a BOM
and silently invalidates the first component.

```bat
cmd /c modules\realityscan_interface\RS_CLI\Scripts\ExportDeliverables.bat ^
    "F:\na156_h2024_v2\final_assembly\assembly\H2024_Final_Assembly.rsproj" ^
    "F:\na156_h2024_v2\exports" ^
    "F:\na156_h2024_v2\exports\components.names"

set CESIUM_ION_TOKEN=<token with assets:write,assets:read>
set NIRACLIENT_DIR=C:\tools\niraclient
py -3.13 publish_batch.py --workspace F:\na156_h2024_v2 ^
    --prefix "IN-401" --input-crs EPSG:32604
```

Note the known defect in the PLY step (§13.7) before running the export
unattended.

### 21.4 Probe: does `-exportReport` work headless?

Not yet run. Template (`D:\rs_templates\components.csv`, any extension):

```
component,cameras,projections,mean_px,median_px,max_px,georeferenced,metric
$IterateComponents($ComponentStats("$(componentGUID)",$(componentName),$(componentCamerasCount),$(componentTotalProjection),$(componentMeanError:.3f),$(componentMedianError:.3f),$(componentMaximalError:.3f),$(componentIsGeoreferenced),$(componentMetric)
))
```

The nesting is the documented idiom: `$ComponentStats`'s own variable list does
not include `componentName` or `componentCamerasCount`, but the enclosing
`$IterateComponents` scope supplies them — Epic's `$ComponentInfo` example does
exactly this [OFFICIAL: appbasics/reports_fav_components]. The newline before
`))` is inside the body, so each component emits one CSV row. `:.3f` is the
documented rounding form.

```bat
RealityScan.exe -delegateTo RS1 -exportReport ^
    "F:\probe\components.csv" "D:\rs_templates\components.csv"
```

Run it under the standard watchdog. If it returns, hardening cells **U7** and
**U14** both close and the per-component quality record becomes automatic. If
it blocks, mark it GUI-only alongside `-exportRegistration` and record the
result.

---

## 22. Open questions

Each with the cheapest probe that answers it.

| # | Question | Cheapest probe |
|---|---|---|
| 1 | Does `-exportReport` complete headless under delegation, and does it emit georeferencing status and reprojection residuals? (hardening cells **U7**, **U14** — U7 open since 2026-07-23) | The custom one-line CSV template in §21.4, delegated with a watchdog on the smoke fixture. Minutes. |
| 2 | Is the `-selectLargeTrianglesRel 30` threshold right for this imagery? Never visually validated. | Run `[3/8]` at 15 / 30 / 60 on the 133-camera component and inspect the three results in the GUI. ~2 h total. |
| 3 | Why does `-selectModel <tag>_HighPoly` return `2147942487` in every cleanup loop? The FINDINGS 2026-07-29 reading is that `[6/8]`'s second `-renameSelectedModel` consumed the name into `_HighPoly_Textured`, i.e. the loop is looking for a name that by then does not exist — which would make the code correct behaviour, not a defect. | Delegate `-selectModel <tag>_HighPoly` twice inside `[6/8]`: once immediately after the first rename, once after `-calculateTexture` + the second rename, comparing the errors marker each time. Seconds; also the input to the queued error-whitelist redesign. |
| 4 | Does the shipped `ExportDeliverables.bat` PLY step abort, as §13.7 predicts? | Run it on the 133-camera component. ~2 min to the failure point. Fix by switching to `_HighPoly_Textured` or duplicating after `[1/8]`. |
| 5 | `ModelExportFormatVersion` — FBX format-version selector or params-file schema version? | Export an FBX from the GUI at `FBX201100` and again at `FBX202000`; diff the two params files. |
| 6 | `MvsExportcoordinatesystemtype` ordinal → label mapping (`0`, `3` observed against four documented options). | Set each of Grid plane / Project Output / Shifted project output / Same as XMP in the GUI export dialog, export params, read the value. |
| 7 | `MvsMeshExportNumberFormat` — decimal-precision count or the Decimal/Scientific/General enum? | Toggle the GUI Number format control and the `.ptx` Output Decimal Precision separately; diff. |
| 8 | `simplPreserveParts` ordinal → label mapping. Known: `2` is **not** "Create a singleton" (a model simplified under it exported as 4 parts). | Set the three Part merging options in the GUI Simplify tool, export params each time, diff. |
| 9 | `mvsFltBorderDecimationStyle` and `mvsFltSmoothingType` ordinal mappings. | Same method as #8, in the Simplify and Smooth tools. |
| 10 | `reprojectionTool_colorSampling=0` — is that "Nearest sampling"? If so the production preset uses the non-recommended sampler with supersampling at default. | Open the Reproject Texture tool, set Trilinear, export params, diff against `ReprojectionParams.xml`. Minutes; a quality issue on every delivered simplified texture if confirmed. |
| 11 | Would bounding each component's model with an explicit `.rsbox` from its manifest bbox materially cut the runtimes in §12.1? | One `-setReconstructionRegion` + `-calculateHighModel` on the 133-camera component against its 40.1 min baseline. |
| 12 | Do the low-texture meshing keys (`mvsLowTextureGroupingFactor`, `mvsLowTextureNoiseFactor`) help or over-smooth turbid underwater geometry? | One A/B at default vs halved noise factor on the 133-camera component. ~80 min. |
| 13 | What are the delivered models' triangle counts, part counts, texture counts and per-phase timings? Nowhere in the current record. | Falls out of #1; otherwise one `Selected Model Report` per component from the GUI. |
| 14 | Can mesh-quality values be exported as data (grayscale quality in a PLY or a baked quality texture)? | `-calculateQualityColors` then `-exportModel … .ply` with `MvsMeshExportColors=true` on the 133-camera component. Minutes. |
| 15 | Is `-export3dTiles` better or worse than letting Cesium ion's Reality Tiler process a raw OBJ? | Push the 133-camera component through both paths and compare in the ion viewer. |
| 16 | Does a standalone `.rsbox` from `-exportReconstructionRegion` match the `<ReconstructionRegion>` element embedded in a `.rsortho`? | `-setReconstructionRegionAuto -exportReconstructionRegion` on the smoke fixture; read the file. Seconds. |
| 17 | Is `-setReconRegionOnCPs` a genuine alias of `-setReconstructionRegionOnCPs`? | Type it in the GUI console view; TAB completion or the error answers it. |
| 18 | Can a model be built at materially more than ~5,000 cameras on this hardware? The envelope has not plateaued. | No cheap probe. Either split the component or add RAM/commit before trying. Treat as unsupported until measured. |
| 19 | Does the model-tool stack behave differently on `-calculateNormalModel`? Only High has ever been run here. | One `-calculateNormalModel` on the 133-camera component; compare time, triangle count and the filter-step outcomes. |
| 20 | Which of `txtFillInUntextoredParts` (Epic's typo) and `txtFillInUntexturedParts` is live in 2.2? Both strings are in the binary. | `-set` each and check for `err:7155` in `RealityScan.log`. Seconds. |
| 21 | Does `-exportReport` accept an unregistered template path directly, or must the template be registered in `report.xml` first? | Falls out of #1 — §21.4 passes an unregistered path deliberately. |
| 22 | Would pinning the ten `txt*`/`col*` texturing keys (§9.3) change the delivered textures, and what were the instance defaults during the H2023/H2024 deliveries? | `-set` them explicitly before `-calculateTexture` on the 133-camera component and compare against its existing texture. Also removes a provenance hole at zero runtime cost. |
| 23 | Does classification (`-dtmClassify`) produce a usable ground/artificial split on ROV bathymetry, and which `modelType` fits a wreck on a seabed? | `-dtmClassify` on the 133-camera component; non-destructive (creates a new classification object). |
| 24 | Is `-uploadToSketchfab` incompatible with `-disableOnlineCommunication`? | Run both in one command sequence and read the result code. |
| 25 | Does `-importCache` (split GPU/CPU depth-map workflow) interact correctly with `RS_GPU_DEVICES` instance pinning? | Smoke fixture across two instances; ~10 min. |
| 26 | **Does `<tag>_HighPoly_Raw` survive when step `[2/8]` is skipped?** The 2026-07-29 mechanism says the rename is what consumes the name, and `:try_filter` skips the rename on an empty selection — which would explain why H2023 PD6 kept the model and H2024's `cluster_4_a1_c0` did not (§5.4). Until settled, `HANDOFF.md` and the `GenerateModel.bat` docstring are both stating an unconditional claim that is at best conditional. | On any modelled component, read the `expected_select_*.txt` evidence files to see whether `[2/8]` fired, then `-selectModel <tag>_HighPoly_Raw` and compare. Seconds, no recomputation. |
| 27 | `unwrapMinTexelSize` / `unwrapMaxTexelSize` are each documented **twice** with different types (0–5 enum for `AdaptiveTexelSize`, float for custom `FixedTexelSize`) — are they one setting whose parse depends on `unwrapStyle`, or two binary settings the Help's table merged? Writing metres where ordinals are expected would silently produce a wrong texel budget. | Set `unwrapStyle=AdaptiveTexelSize` in the GUI Unwrap tool, export the params, read what is written for both keys; repeat with `FixedTexelSize` + type `5`. Minutes. |
| 28 | `mvsFltUnwrapTexSide` is one key, but the GUI Simplify tool exposes **custom minimal *and* maximal** texture resolution. Which key carries the second? (`mvsFltUnwrapMinTexSideCustom` / `mvsFltUnwrapMaxTexSideCustom` are binary strings.) | Set a custom resolution range in the Simplify tool, export params, diff against `Simplify50Per_Params.xml`. Minutes. |
| 29 | Would `MvsGeometryMarginStyle=true` (drop marginal triangles at mesh time) beat the post-hoc `[2/8]` filter on runtime or quality? Never compared; the key appears in no repo file and in no settings evaluation. | One `-set "MvsGeometryMarginStyle=true"` + `-calculateHighModel` on the 133-camera component against its 40.1 min baseline, then compare against a `[2/8]`-filtered run. ~80 min. |
