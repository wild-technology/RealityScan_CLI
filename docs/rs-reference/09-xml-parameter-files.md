# XML parameter files: the settings-profile system

This document covers every XML file RealityScan 2.2 reads or writes as *configuration*: the
`<Configuration>` settings profiles that CLI commands accept as a `params.xml` argument, the
structured `.rsortho` / `.rsbox` / `.rsinfo` / `.rcconfig` files that are configuration by another
name, and the `<format>` dictionaries in the install tree that define which import readers and
export writers exist at all. It covers the general mechanism (who produces a profile, who consumes
it, what happens when one is wrong, and which commands silently ignore one), a schema section per
profile type, the 34 shipped profiles in this repository as worked examples, and an authoring
guide. It does **not** re-enumerate the settings-key namespace itself — every `-set` key, its type,
allowed values and default live in `03-settings-keys.md`, which is the authority for key semantics;
this document is the authority for the *file* that carries them. Command syntax and per-command
behavior live in `02-command-reference.md`; alignment in `07-alignment.md`, merge in
`08-components-and-merge.md`, georeferencing in `06-georeferencing-flightlogs-and-scale.md`,
modeling and export in `10-reconstruction-texturing-export.md`.

**Applies to:** RealityScan 2.2 (Epic Games), Windows, headless CLI operation.
**Tags:** [OFFICIAL] shipped Help · [VERIFIED] measured in production here ·
[CONTRADICTED] docs vs observation · [UNDOCUMENTED] · [INFERRED] · [OPEN]

---

## Contents

1. [The mechanism](#1-the-mechanism)
   - [1.1 What a profile is](#11-what-a-profile-is)
   - [1.2 Two unrelated XML families — do not confuse them](#12-two-unrelated-xml-families--do-not-confuse-them)
   - [1.3 Every command that accepts a profile](#13-every-command-that-accepts-a-profile)
   - [1.4 Commands that SILENTLY IGNORE a profile](#14-commands-that-silently-ignore-a-profile)
   - [1.5 Optional in the docs, mandatory in practice](#15-optional-in-the-docs-mandatory-in-practice)
   - [1.6 How to obtain a valid profile](#16-how-to-obtain-a-valid-profile)
   - [1.7 The `Configuration id` GUID and what it binds to](#17-the-configuration-id-guid-and-what-it-binds-to)
   - [1.8 Value encodings inside a profile](#18-value-encodings-inside-a-profile)
   - [1.9 Relationship to `-set`](#19-relationship-to--set)
   - [1.10 Failure modes: malformed, wrong-type, missing, unknown-key](#110-failure-modes-malformed-wrong-type-missing-unknown-key)
   - [1.11 Passing a profile path across cmd and subprocess boundaries](#111-passing-a-profile-path-across-cmd-and-subprocess-boundaries)
2. [Profile schemas by type](#2-profile-schemas-by-type)
   - [2.1 Alignment params](#21-alignment-params)
   - [2.2 Flight-log / trajectory import params](#22-flight-log--trajectory-import-params)
   - [2.3 XMP export params](#23-xmp-export-params)
   - [2.4 Simplify params](#24-simplify-params)
   - [2.5 Smoothing params](#25-smoothing-params)
   - [2.6 Unwrap params](#26-unwrap-params)
   - [2.7 Texturing params](#27-texturing-params)
   - [2.8 Texture-reprojection params](#28-texture-reprojection-params)
   - [2.9 Model export params](#29-model-export-params)
   - [2.10 Ortho projection: `.rsortho`](#210-ortho-projection-rsortho)
   - [2.11 Reconstruction region: `.rsbox` / `.rcbox`](#211-reconstruction-region-rsbox--rcbox)
   - [2.12 Mask export params](#212-mask-export-params)
   - [2.13 Depth / normal / mask maps export params](#213-depth--normal--mask-maps-export-params)
   - [2.14 LoD and Cesium 3D Tiles export params](#214-lod-and-cesium-3d-tiles-export-params)
   - [2.15 Registration export params](#215-registration-export-params)
   - [2.16 Control-point measurement import/export params](#216-control-point-measurement-importexport-params)
   - [2.17 Ground-control-point import/export params](#217-ground-control-point-importexport-params)
   - [2.18 Distance-definition import params](#218-distance-definition-import-params)
   - [2.19 LiDAR scan import params](#219-lidar-scan-import-params)
   - [2.20 16-bit / HDR image import params](#220-16-bit--hdr-image-import-params)
   - [2.21 Model import params and `.rsinfo`](#221-model-import-params-and-rsinfo)
     — including **the `<Model>` tag and how to decode `transformToModel`**
   - [2.22 Bundler and COLMAP import params](#222-bundler-and-colmap-import-params)
   - [2.23 Classification params and the `.cfd` format file](#223-classification-params-and-the-cfd-format-file)
   - [2.24 Sparse point cloud, cross-sections, contours, shapes](#224-sparse-point-cloud-cross-sections-contours-shapes)
   - [2.25 Snapshot and custom-render params](#225-snapshot-and-custom-render-params)
   - [2.26 Whole-application settings: `.rcconfig`](#226-whole-application-settings-rcconfig)
3. [The install-tree format dictionaries](#3-the-install-tree-format-dictionaries)
   - [3.1 Complete inventory](#31-complete-inventory)
   - [3.2 Import dictionary schema](#32-import-dictionary-schema)
   - [3.3 Export dictionary schema](#33-export-dictionary-schema)
   - [3.4 The writer attribute — which formats are customizable](#34-the-writer-attribute--which-formats-are-customizable)
   - [3.5 How to read a dictionary to discover legal values](#35-how-to-read-a-dictionary-to-discover-legal-values)
   - [3.6 The dictionaries are not well-formed XML](#36-the-dictionaries-are-not-well-formed-xml)
   - [3.7 Editing an install-tree dictionary](#37-editing-an-install-tree-dictionary)
4. [This repository's 34 profiles](#4-this-repositorys-34-profiles)
   - [4.1 Inventory with purpose and delta-from-default](#41-inventory-with-purpose-and-delta-from-default)
   - [4.2 Which profile to pick when](#42-which-profile-to-pick-when)
   - [4.3 Known defects in the profile set](#43-known-defects-in-the-profile-set)
5. [Authoring guide](#5-authoring-guide)
   - [5.1 Safe hand-edit procedure](#51-safe-hand-edit-procedure)
   - [5.2 Fields that must never be hand-edited](#52-fields-that-must-never-be-hand-edited)
   - [5.3 Verifying a profile took effect](#53-verifying-a-profile-took-effect)
   - [5.4 Encoding, BOM, line endings](#54-encoding-bom-line-endings)
   - [5.5 Pre-flight checklist](#55-pre-flight-checklist)
6. [Open questions](#6-open-questions)

---

## 1. The mechanism

### 1.1 What a profile is

A settings profile is a flat XML file: one root `<Configuration>` element carrying an optional
`id` GUID, and one `<entry key="…" value="…"/>` child per setting. There is no nesting, no ordering
requirement, no schema declaration, no XML prolog in any observed file.

```xml
<Configuration id="{54A4029C-DE57-43F6-8F81-75C62E159021}">
  <entry key="unwrapStyle" value="MaxTexturesCount"/>
  <entry key="unwrapMaximalTexCount" value="4"/>
  <entry key="unwrapMaxTexResolution" value="16384"/>
</Configuration>
```

[VERIFIED-by-inspection: all 34 profiles in `RS_CLI/Metadata/` plus the three Epic-authored
profiles in `C:\Program Files\Epic Games\RealityScan_2.2\Settings\SimplifiedExport\`, 2026-08-04]

Facts about the shape:

| Property | Fact | Tag |
|---|---|---|
| Root element | `<Configuration>` always | [VERIFIED: 37 files] |
| `id` attribute | present on tool/panel profiles; **absent** on every `ModelExportParams*.xml` | [VERIFIED: 34 repo files] |
| Attribute order | `key` then `value`, always | [VERIFIED: 34 repo files] |
| Entry order | arbitrary; GUI exports are unordered (not alphabetical, not GUI order) | [VERIFIED: e.g. `AlignmentParams.xml` interleaves `s237l`, `sfmFeatureDetectionQuality`, `s251l`) |
| Partial files | legal — a profile need not contain every key of its panel; `Texturing_FixedTexelSize*.xml` carries 7 entries, `Texturing_MaxTextureCount*.xml` carries 8 | [VERIFIED: repo files] |
| XML prolog | never present | [VERIFIED: 37 files] |
| Comments | not produced by the GUI, but tolerated — `AlignmentParams.xml` carries three hand-added `<!-- … -->` blocks and has driven every production align since 2026-07-23 | [VERIFIED: repo file + production use] |
| Well-formedness | all 34 repo profiles and all 3 Epic profiles parse cleanly with `System.Xml.XmlDocument` | [VERIFIED-by-probe: 2026-08-04] |

Profiles are **not** the same thing as a project (`.rsproj`), a component (`.rsalign`), or the
install-tree format dictionaries (§3). A profile carries the state of one GUI settings panel or one
tool dialog, frozen at the moment of export.

### 1.2 Two unrelated XML families — do not confuse them

RealityScan uses XML for two entirely different jobs, and mixing them up is the single most common
way to waste an hour.

| Family | Root | Lives in | Governs | Passed to a command? |
|---|---|---|---|---|
| **Settings profile** | `<Configuration>` | anywhere you like (this repo: `RS_CLI/Metadata/`) | the values a single operation runs with | **Yes** — as the `params.xml` argument |
| **Format dictionary** | `<FlightLogs>`, `<Calibration>`, `<GroundControl>`, `<Structure>`, `<Ortho>`, … | `C:\Program Files\Epic Games\RealityScan_2.2\*.xml` only | *which* import readers and export writers exist, their column mapping, their output templates | **No** — read at application start, never named on a command line |

A third group is structured, non-`<Configuration>` configuration:

| File | Root | Produced by | Consumed by |
|---|---|---|---|
| `.rsortho` | `<OrthoProjection>` + `<ReconstructionRegion>` + `<DTMParams>` | ortho export with `exportProjectionParametersFile=True` | `-calculateOrthoProjection` |
| `.rsbox` / `.rcbox` | `<ReconstructionRegion>` | `-exportReconstructionRegion` | `-setReconstructionRegion`, `-calculateOrthoProjection` |
| `.rsinfo` | contains a `<ModelExport>` tag | any `-exportModel` with `MvsMeshExportInfoFile=true` | model *import* (auto-discovered by name); its `<ModelExport>` tag is copy-pasteable into a model-export profile |
| `.rcconfig` | whole-app settings dump | `-exportGlobalSettings` | `-importGlobalSettings` |
| `.cfd` | classification format | `-exportClassificationFormat` | `-importClassificationFormat` |

[OFFICIAL: tools/xmlparamsfiles, tools/export, appbasics/allcommands]

### 1.3 Every command that accepts a profile

Complete list for 2.2. "Req" = the Help lists `params.xml` as a required parameter; "Opt" = listed
as optional. Producing dialog is the GUI dialog whose *export settings* button writes a usable file.

| Command | Profile arg | Position | Producing dialog | Tag |
|---|---|---|---|---|
| `-importLaserScan <name> <params.xml>` | Opt | 2nd | LiDAR Scan Import | [OFFICIAL: appbasics/allcommands] |
| `-importLaserScanFolder <folder> <params.xml>` | Opt | 2nd | LiDAR Scan Import | [OFFICIAL] |
| `-importHDRimages <file\|folder\|imagelist> <params.xml>` | Opt | 2nd | 16-bit/HDR Images Import | [OFFICIAL] |
| `-exportMasks <folderPath> <params.xml>` | **Req** | 2nd | Export Mask Images | [OFFICIAL] |
| `-exportMasks <params.xml>` | **Req** | 1st | Export Mask Images | [OFFICIAL] — 2nd form, writes beside the originals |
| `-exportXMP <params.xml>` | Opt | 1st | XMP metadata export | [OFFICIAL] |
| `-loadBundler <filePath> <params.xml>` | Opt | 2nd | Bundler import | [OFFICIAL] |
| `-loadColmap <filePath> <params.xml>` | Opt | 2nd | COLMAP import | [OFFICIAL] |
| `-exportRegistration <fileName> <params.xml>` | Opt | 2nd | Export Registration | [OFFICIAL] — but see §1.5 |
| `-exportUndistortedImages <folder> <params.xml>` | Opt | 2nd | Export Registration | [OFFICIAL] |
| `-exportSTMap <folder> <params.xml>` | Opt (both or neither) | 2nd | Export Registration | [OFFICIAL] |
| `-exportSparsePointCloud <fileName> <params.xml>` | Opt | 2nd | Export Point Cloud | [OFFICIAL] |
| `-importTrajectory <log> <params.xml>` | Opt | 2nd | Import Trajectory | [OFFICIAL] |
| `-importFlightLog <log> <params.xml>` | Opt | 2nd | Import Trajectory | [UNDOCUMENTED] — the string does not appear anywhere in the 2.2 Help; it is this repo's only georeferencing import path and works [VERIFIED: 6 call sites, production since 2026-07-21] |
| `-importGroundControlPoints <gcpFile> <params.xml>` | Opt | 2nd | **Import** Ground Control Points | [CONTRADICTED: `appbasics/allcommands` says "Export Ground Control Points dialog" / `tutorials/commandline_1` says "Import Ground Control Points dialog". Prefer Import — `tools/gcpimport` documents an Import dialog with exactly these controls and no settings-export from the GCP *export* path.] |
| `-importControlPointsMeasurements <cpmFile> <params.xml>` | Opt | 2nd | **Import** Control Points Measurements | [CONTRADICTED: `appbasics/allcommands` says "Export Control Points Measurements dialog" / `tutorials/commandline_1` says "Import Control Points Measurements dialog". Same copy-paste class of error as the GCP row; prefer Import.] |
| `-exportGroundControlPoints <gcpFile> <params.xml>` | Opt | 2nd | Export Ground Control | [OFFICIAL] |
| `-exportControlPointsMeasurements <cpmFile> <params.xml>` | Opt | 2nd | Shift + **Control Points** in ALIGNMENT ▸ Export | [OFFICIAL] |
| `-defineDistance <fileName> <params.xml>` | Opt | 2nd | Import Distance Definitions | [OFFICIAL] |
| `-detectMarkers <params.xml>` | Opt | 1st | Detect Markers tool | [OFFICIAL] |
| `-unwrap <params.xml>` | Opt | 1st | Unwrap tool | [OFFICIAL] — **REPO** |
| `-calculateTexture <params.xml>` | Opt | 1st | Color and Texture Settings panel | [OFFICIAL] — **REPO** |
| `-reprojectTexture <src> <dst> <params.xml>` | Opt | 3rd | Texture Reprojection tool | [OFFICIAL] — **REPO** |
| `-simplify <targetTriangleCount \| params.xml>` | Opt, polymorphic | 1st | Simplify tool | [OFFICIAL] — **REPO** |
| `-smooth <params.xml>` | Opt | 1st | Smooth tool | [OFFICIAL] |
| `-exportModel <modelName> <fileName> <params.xml>` | Opt | 3rd | Export model | [OFFICIAL] — **REPO** |
| `-exportSelectedModel <fileName> <params.xml>` | Opt | 2nd | Export model | [OFFICIAL] |
| `-importModel <fileName> <params.xml>` | Opt | 2nd | Import model | [OFFICIAL] — `tutorials/commandline_3` shows no optional arg; the master table does [CONTRADICTED-internal, prefer the master table] |
| `-calculateOrthoProjection <rsorthoFile> <rsboxFile>` | Opt ×2 | 1st, 2nd | ortho export with `exportProjectionParametersFile=True` | [OFFICIAL: tools/xmlparamsfiles] — **not** a `<Configuration>` file |
| `-exportOrthoProjection <orthoName> <fullPath> <params.xml>` | **Req** | 3rd | ortho export dialog | [OFFICIAL] — form 1 of 3 |
| `-exportOrthoProjection <orthoName> <folderPath> <exportName> <params.xml>` | **Req** | 4th | same | [OFFICIAL] — form 2 of 3 |
| `-exportOrthoProjection <fullPath> <params.xml>` | **Req** | 2nd | same | [OFFICIAL] — form 3 of 3, selected projection |
| `-exportCrossSections <fileName> <params.xml>` | Opt | 2nd | Export Cross Sections | [OFFICIAL] |
| `-computeContours <params.xml>` | Opt | 1st | Contours tool | [OFFICIAL] |
| `-exportContours <fileName> <params.xml>` | Opt | 2nd | Export Contours | [OFFICIAL] |
| `-exportShapes <fileName> <params.xml>` | Opt | 2nd | Export Shapes | [OFFICIAL] |
| `-exportMapsAndMask <folderName> <params.xml>` | Opt (both or neither) | 2nd | maps-and-masks export dialog | [OFFICIAL] |
| `-exportLod <fileName> <params.xml>` | Opt | 2nd | Export LoD (linear dialog) | [OFFICIAL] |
| `-export3dTiles <fileName> <params.xml>` | Opt | 2nd | Export LoD, Cesium 3D Tiles selected | [OFFICIAL] |
| `-exportCameraSnapshots <folderName> <params.xml>` | Opt | 2nd | camera snapshots export dialog | [OFFICIAL] |
| `-exportSelectedCamerasSnapshots <folder> <fileFormat> <params.xml>` | Opt | 3rd | same | [OFFICIAL] |
| `-renderMeshFromCustomPositionYPR <fileName> <params.xml>` | Alternative form | 2nd | — | [OFFICIAL] — the profile *replaces* nine positional arguments |
| `-renderMeshFromCustomPositionLookAt <fileName> <params.xml>` | Alternative form | 2nd | — | [OFFICIAL] |
| `-renderMeshFromCustomGridPositionYPR <fileName> <params.xml>` | Alternative form | 2nd | — | [OFFICIAL] |
| `-renderMeshFromCustomGridPositionLookAt <fileName> <params.xml>` | Alternative form | 2nd | — | [OFFICIAL] |
| `-dtmClassify <params.xml>` | Opt | 1st | Classify tool | [OFFICIAL] — `appbasics/allcommands` calls it the "Classify tool" here and the "AI Classify tool panel" three rows later for `-transferClassification` / `-exportClassificationSettings`; one page, two names for one panel [CONTRADICTED-internal] |
| `-transferClassification <params.xml>` | Opt | 1st | AI Classify panel | [OFFICIAL] |
| `-importClassificationSettings <XMLfilePath>` | **Req** | 1st | — produced by `-exportClassificationSettings` | [OFFICIAL] |

Count: **48 command forms** across **45 distinct commands** take an XML file argument (`-exportMasks`
contributes 2 forms, `-exportOrthoProjection` 3). [VERIFIED-by-inspection: row count of the table
above against `appbasics/allcommands`, 2026-08-04]

Three of those 48 take an XML file that is *not* a `<Configuration>` settings profile and must not
be confused with one: `-calculateOrthoProjection <rsorthoFile> <rsboxFile>` (§2.10), plus the two
region commands that are not in the table at all because they carry no settings —
`-setReconstructionRegion <box.rsbox>` and `-exportReconstructionRegion <box.rsbox>` (§2.11).

### 1.4 Commands that SILENTLY IGNORE a profile

This is the distinction that is nowhere in Epic's documentation and that costs the most time.

**`-align` takes no parameters in 2.x. A params XML passed to it is accepted on the command line
and silently ignored — no error, no warning, no log line, and the alignment runs on whatever
settings the instance happens to be carrying.**
[CONTRADICTED: pre-2.x lore and this repo's own earlier scripts passed `-align "%AlignmentParams%"`
/ observed: the argument has no effect; confirmed against `appbasics/allcommands`, whose row reads
`align | | Align images using the current settings.` with both parameter columns empty, and against
Epic's online docs, 2026-07-21] [VERIFIED: FINDINGS 2026-07-21]

The consequences are severe and were all hit here:

- An instance carries whatever the last GUI or CLI session set, and swept `-set` values **persist
  across instance restarts**, so "aligning on instance defaults" is not even reproducible run to
  run. [VERIFIED: MERGE_TEST_PLAN §3 contamination controls, 2026-07-23]
- `AlignImagesFromFolder.bat` never applied `AlignmentParams.xml` at all while
  `AlignZonesSequentially.bat` did — two workflows in one repo silently running different
  alignment settings. Discovered by code reading, not by any error.
  [VERIFIED: FINDINGS 2026-07-23]
- The adopted policy is **"never align on instance defaults"**: every alignment workflow parses
  the `sfm*` / `lis*` entries out of `AlignmentParams.xml` and replays each one as a delegated
  `-set` before a plain `-align`. See §2.1 for the exact loop.

The general rule to apply when a command is not in the §1.3 table:

> If `appbasics/allcommands` shows both parameter columns empty for a command, an XML argument is
> ignored, not rejected. Nothing in the CLI will tell you. Verify by the operation's *output*, never
> by its exit code. [INFERRED from the `-align` case; the only command confirmed to behave this way
> is `-align`.] [OPEN: whether any other zero-parameter command — `-mergeComponents`,
> `-calculateHighModel`, `-colorize`, `-update`, `-cleanModel` — also swallows a stray XML argument
> silently, or errors. Cheapest probe: `-delegateTo RS1 -cleanModel "C:\nonexistent.xml"` on a
> loaded smoke scene and read the errors marker; costs seconds.]

### 1.5 Optional in the docs, mandatory in practice

| Command | Doc status | Reality | Tag |
|---|---|---|---|
| `-exportRegistration <file> [params.xml]` | optional | **without a params XML it blocks forever headless.** The command never returns; the workflow hangs with no error and no dump. Avoid entirely until a GUI-saved Export Registration profile exists. | [CONTRADICTED: Help lists `params.xml` optional / observed: indefinite headless block, 2026-07-21] [VERIFIED: FINDINGS 2026-07-21] |
| `-exportMasks` | required in both forms | required — consistent | [OFFICIAL] |
| `-exportOrthoProjection` | required in all three forms | required — consistent | [OFFICIAL] |
| `-exportXMP [params.xml]` | optional | genuinely optional. This repo has **never** passed one: `XMPExportParams.xml` is shipped in `RS_CLI/Metadata/` but is referenced by zero scripts and zero Python modules, so every production `-exportXMP` and `-exportXMPForSelectedComponent` ran on instance defaults. | [VERIFIED-by-probe: repo-wide grep for `XMPExportParams`, 2026-08-04] |

The general shape of the hazard: a dialog that would prompt for interaction under a GUI becomes a
silent block or a silent auto-answer under `-headless` + `-silent`. Two recorded instances:
`-exportRegistration` blocks; a selection-driven export auto-answers its "Export Selection" dialog
and exports **nothing** in 0.057 s instead of 20.5 s.
[VERIFIED: FINDINGS 2026-07-21 and 2026-07-23]

### 1.6 How to obtain a valid profile

**The canonical way is to configure the operation once in the GUI and export the settings from that
dialog.** There is no CLI command that emits a `<Configuration>` profile for a tool, no documented
schema to author one from scratch, and no validator. This repo obtained every simplify, smoothing,
texturing, unwrap, reprojection and model-export profile that way, and `-exportRegistration`
remains unusable here precisely because nobody has yet sat at the GUI and saved its dialog.
[VERIFIED-as-practice: FINDINGS 2026-07-21; hardening cells U7 / U14]

There are, however, **four CLI-reachable producers** — worth knowing because they break the
GUI dependency for specific families:

| Producer | Emits | Consumed by | Tag |
|---|---|---|---|
| `-exportClassificationSettings <path.xml>` | the AI Classify panel's profile | `-importClassificationSettings`, `-dtmClassify`, `-transferClassification` | [OFFICIAL: appbasics/allcommands] — the only command that writes a tool profile |
| `-exportModel …` with `MvsMeshExportInfoFile=true` | `<model>.rsInfo` beside the model; its `<ModelExport>` tag pasted into an empty `.xml` **is** a model-export profile | `-exportModel`, `-exportSelectedModel` | [OFFICIAL: tools/export] for the mechanism; [VERIFIED: `.rsInfo` files are produced headless — FINDINGS 2026-07-29 by-parts export probe] |
| `-exportGlobalSettings <settings.rcconfig>` | every application-global setting | `-importGlobalSettings` | [OFFICIAL] — whole-app, not per-tool |
| ortho export with `exportProjectionParametersFile=True` | `.rsortho` | `-calculateOrthoProjection` | [OFFICIAL: tools/xmlparamsfiles] — chicken-and-egg: setting that flag headless needs an ortho-export profile you do not have yet |

The `.rsInfo` route is the practical bootstrap for model export and deserves to be spelled out,
because it needs no GUI at all:

```bat
:: 1. Export once with NO params file. Info-file writing is on by default.
RealityScan.exe -delegateTo RS1 -selectModel "cluster_0_a2_c0_Simplified_Textured" ^
                -exportSelectedModel "F:\na156_h2024\probe\seed.obj"
:: 2. Read F:\na156_h2024\probe\seed.obj.rsInfo, copy the <ModelExport> element
::    into an empty file, save as ModelExportParams_seed.xml.
:: 3. Hand-tune that file and pass it from then on.
set "MD=C:\Users\jonat\Desktop\CoyoteThings\RealityScan_CLI\modules\realityscan_interface\RS_CLI\Metadata"
RealityScan.exe -delegateTo RS1 -exportModel "cluster_0_a2_c0_Simplified_Textured" ^
                "F:\na156_h2024\deliverables\cluster_0\obj\cluster_0.obj" ^
                "%MD%\ModelExportParams_seed.xml"
```

Step 1's model name must exist in the scene — `-selectModel <modelName>` selects by name and
`-exportSelectedModel` writes whatever is selected. [OFFICIAL: appbasics/allcommands]

[OFFICIAL: tools/export "copy the text in the ModelExport tag from the created .rsinfo file and
paste it into an empty .xml file"] [INFERRED: that the extracted tag works unchanged as a profile
— never round-tripped here. The correlating evidence is structural: every `ModelExportParams*.xml`
in this repo has a bare `<Configuration>` root with **no `id` GUID**, unlike every tool profile,
which is exactly what an extracted-and-renamed `<ModelExport>` tag would look like.]

Two further routes exist and are worth knowing:

- **Copy a sibling and change one value.** `SimplifyNoise_Params.xml` and
  `SimplifySmooth_80per_Params.xml` differ in exactly one line
  (`mvsFltTargetTrisCountRel` `70` → `80`); `Texturing_MaxTextureCount1_16k.xml` and
  `Texturing_MaxTextureCount4_16k.xml` differ in exactly one value
  (`unwrapMaximalTexCount` `1` → `4`) — their whole-file diff is noise from CRLF vs LF, not content.
  [VERIFIED-by-probe: `diff` over both pairs, 2026-08-04]
- **Start from Epic's own shipped profiles.** `C:\Program Files\Epic Games\RealityScan_2.2\
  Settings\SimplifiedExport\` contains three Epic-authored `<Configuration>` files —
  `simplify.xml`, `smooth.xml`, `reprojectTexture.xml` — which are the app's default states for
  those three tools and therefore the closest thing that exists to an official template.
  [VERIFIED-by-inspection, 2026-08-04]

### 1.7 The `Configuration id` GUID and what it binds to

The `id` identifies the owning settings panel. Two profiles with the same GUID are
interchangeable in shape; two with different GUIDs are not.

| GUID | Panel / tool | Commands | Repo files |
|---|---|---|---|
| `{E377B69D-FB4B-4833-9CBE-FF747B7AF6D9}` | Alignment settings | *(none — see §2.1)* | `AlignmentParams.xml` |
| `{93DBD041-AE1C-4631-89BC-D9430FCED843}` | Trajectory import | `-importFlightLog`, `-importTrajectory` | `FlightLogParams.xml` |
| `{EC40D990-B2AF-42A4-9637-1208A0FD1322}` | XMP metadata export | `-exportXMP` | `XMPExportParams.xml` |
| `{033AEF62-8421-47A4-81CB-203741113577}` | Simplify tool | `-simplify` | 6 files + Epic's `SimplifiedExport\simplify.xml` |
| `{585E749B-DC69-4D8C-9114-FA8CBB6F88F3}` | Smoothing tool | `-smooth` | 3 files + Epic's `SimplifiedExport\smooth.xml` |
| `{54A4029C-DE57-43F6-8F81-75C62E159021}` | Unwrap / Color & Texture settings | `-unwrap` **and** `-calculateTexture` | 10 files |
| `{8F3517E3-5632-40FE-BD10-9967EA8F299F}` | Texture Reprojection tool | `-reprojectTexture` | `ReprojectionParams.xml` + Epic's `SimplifiedExport\reprojectTexture.xml` |
| *(none)* | Model export dialog | `-exportModel`, `-exportSelectedModel` | 11 `ModelExportParams*.xml` |

[VERIFIED-by-inspection: 37 files, 2026-08-04]

**`-unwrap` and `-calculateTexture` share one profile type.** The texturing and unwrap dialogs are
one settings panel, so a single `Texturing_*.xml` can be passed to either command, and this repo
does exactly that: `GenerateModel.bat` passes `Texturing_MaxTextureCount4_16k.xml` to
`-calculateTexture` and `Unwrapping_Simplified_4x16k.xml` — same GUID, same key family — to
`-unwrap`. The only structural difference between the two file groups is that the unwrap files add
`unwrapMinTexResolution` and `unwrapMethod` and the texturing files add
`unwrapCheckerBoardCellSize`. [VERIFIED-by-inspection + production use, 2026-07-29]

Each GUID also names a registry subkey,
`HKCU\Software\EpicGames.RealityScan\RealityScan\Workspace\SP-{GUID}`, which is where the
GUI persists the same panel state between sessions.
[UNDOCUMENTED: registry enumeration, read-only — see `03-settings-keys.md` §1.9]

### 1.8 Value encodings inside a profile

The GUI writes several encodings for what is nominally one type, and all of them are accepted.
Do not normalize when hand-editing.

| Encoding | Example, verbatim from a shipped profile | Notes |
|---|---|---|
| bool as word | `<entry key="sfmEnableCameraPrior" value="true"/>` | most common |
| bool as digit | `<entry key="MvsMeshExportCameras" value="0"/>` | same key is `false` in a sibling file |
| bool as hex | `<entry key="MvsExportIsGeoreferenced" value="0x1"/>` | same key is `1.0` in `ModelExportParams.xml` |
| bool as float | `<entry key="MvsExportIsGeoreferenced" value="1.0"/>` | — |
| int decimal | `<entry key="unwrapMaxTexResolution" value="16384"/>` | — |
| **int hex** | `<entry key="sfmMaxFeaturesPerImage" value="0xc350"/>` | = 50000. Also `0x36b0` = 14000, `0x4e20` = 20000, `0x1` , `0x0`. [VERIFIED: `AlignmentParams.xml`; the same hex strings are pushed verbatim through `-set` by `AlignZone.bat` and every production zone align completed without `err:7155`] |
| float | `<entry key="sfmMaxFeatureReprojectionError" value="1.29999995"/>` | single-precision round-trip artifact, harmless |
| enum by name | `<entry key="unwrapStyle" value="MaxTexturesCount"/>` | — |
| enum by ordinal | `-set "unwrapStyle=1"` in Epic's own tutorial | ordinals are the 0-based order of the value list; [OFFICIAL for `unwrapStyle` and `appProcessAction`, INFERRED for the rest — see `03-settings-keys.md` §1.4] |
| tri-state int | `<entry key="MvsMeshExportTexturing" value="-1"/>` | `-1` = allowed/inherit, `0` = off, `true` = on |
| GUID string | `<entry key="gpsLogFileFormat" value="{B438A617-2434-5A24-C1B7-58980F28345A}"/>` | must match a `<format id>` in `flightlogs.xml` |
| PROJ string | `<entry key="CoordinateSystemFlightLog" value="+proj=utm +zone=57 +south +datum=WGS84 +units=m +no_defs"/>` | spaces inside the value are fine — it is an XML attribute, not a command-line argument |
| layer-suffixed key | `<entry key="MvsMeshExportTexImgFormat_Color8_0" value="jpg"/>` | suffix names a texture layer; `_Normal_0`, `_no_alpha` also observed |
| bracketed literal | `<entry key="MvsExportTransformationPreset" value="[[Custom]]"/>` | GLB only; every other file writes bare `Custom`. Cause unknown. [UNDOCUMENTED] |

### 1.9 Relationship to `-set`

Profile keys are drawn from the same global settings namespace as `-set "key=value"`. The
alignment family is *proven* interchangeable: `AlignZone.bat` reads the `sfm*` / `lis*` rows out of
`AlignmentParams.xml` and replays each one through `-set`, and production aligns behave as
configured. [VERIFIED: production since 2026-07-23]

Whether *every* profile key is also a working `-set` key is **[OPEN]** for the export and tool
families (`Mvs*`, `mvsFlt*`, `unwrap*`, `reprojectionTool_*`, `xmp*`, `if*`). Nothing in this repo
has ever pushed one of those through `-set`. [OPEN: cheapest probe — `-set
"unwrapMaximalTexCount=4"`, then `-exportGlobalSettings out.rcconfig`, and grep the dump for the
key; costs seconds and needs no scene.]

The choice between the two mechanisms in practice:

| Use a profile when | Use `-set` when |
|---|---|
| The command accepts one and you want the whole panel pinned atomically | The command accepts no profile (`-align`) |
| You want the settings under version control as one reviewable artifact | You are overriding one value for one attempt (the merge ladder does this: `merge_zones.py` passes `key:value` pairs down to `MergeZoneComponents.bat`) |
| The keys are export/tool keys whose `-set` support is unproven | The key is `app*` and must be in force at instance boot |

### 1.10 Failure modes: malformed, wrong-type, missing, unknown-key

| Situation | Observed behavior | Tag |
|---|---|---|
| **Unknown key inside a profile** | **Silently ignored.** Five keys whose exact spelling is absent from the 2.2 binary's string pool sit in profiles that have driven hundreds of production operations with no error ever recorded: `ifKmode`, `ifUsePosAcc`, `ifUseOriAcc` (all in `FlightLogParams.xml`), `unwrapCheckerBoardCellSize` (in five `Texturing_*.xml`), and `mvsSmoothing_useIntelligentSmoothing` — which is in **Epic's own** `SimplifiedExport\smooth.xml`. | [VERIFIED-by-consequence: UTF-16LE string sweep of `RealityScan.exe` (2.2, 45,211,352 bytes) for each exact key spelling — none present; recorded in `06-georeferencing-flightlogs-and-scale.md` §2 (the `if*` keys) and `10-reconstruction-texturing-export.md` §6/§9 (the other two) — combined with this repo's zero-error production record] [UNDOCUMENTED: no Help coverage of unknown-key handling] [INFERRED: absence of the literal string implies the key is unreachable; a settings key could in principle be assembled at runtime, so this is strong evidence, not proof] |
| **Missing file** | Not characterised — every repo workflow pre-checks with `if not exist "%AlignmentParams%" ( echo ERROR … & exit /b 1 )` before delegating. | [OPEN: pass a nonexistent path to `-simplify` on a loaded smoke scene and read the errors marker; costs seconds] |
| **Wrong-type profile** (e.g. a simplify profile handed to `-calculateTexture`) | Not characterised. Both are `<Configuration>` files; the GUIDs differ but nothing is known about whether the GUID is checked. | [OPEN: pass `SimplifyNoise_Params.xml` to `-unwrap` on the smoke fixture and compare the resulting texture count against a default unwrap; ~2 min] |
| **Malformed XML** | Not characterised. | [OPEN: truncate a copy of `SimplifyNoise_Params.xml` mid-element and pass it; costs seconds] |
| **Broken `key=value` reaching `-set`** (the adjacent failure, and the one that actually bit) | `Parsing setting key=value 'sfmMergeGeoreferencedComponents' failed [err:7155]` and `'false' failed` — cmd had split the pair on the unquoted `=`. Worse, **the parse errors landed in the errors marker and spuriously aborted the carrying workflow**, and no flag cell before wave 1f had ever applied its flags. | [VERIFIED: NA167 #15 / B5, 2026-07-23] |
| **Wrong *value* in a right key** | The dangerous case, because it succeeds. A wrong UTM zone in `FlightLogParams.xml` imports **silently** and misplaces the entire scene. | [VERIFIED: NA167 #6, 2026-07-22] |

**The operational rule that follows: a profile's effect must be verified from the operation's
output, never from its exit code.** Silence is not success — the CLI has no mechanism that reports
"this key was not recognised".

### 1.11 Passing a profile path across cmd and subprocess boundaries

A profile path is a plain path and crosses cleanly if quoted. The rules that matter here are the
general ones, restated because half of this repo's early failures were boundary failures:

- **Always quote the path.** Checkout paths containing spaces silently disabled *all* error
  detection once, when `appProcessExecCmd` went unquoted. [VERIFIED: HANDOFF overhaul item 4, 2026-07-21]
- **Never pass delimited data as a .bat argument.** cmd splits unquoted `;` `,` `=` into separate
  arguments and Python's `subprocess` quotes only on whitespace. Lists cross as files
  (`.complist` / `.imagelist`); settings cross as `key:value` and the `.bat` converts the colon.
  [VERIFIED: NA167 B5; CLAUDE.md hard rule 8]
- A profile file *is* the sanctioned way to move many `key=value` pairs across the boundary
  intact — that is the mechanism's main practical virtue in an automated pipeline.

Argument-position shapes from production. These are the real call sites with the profile-path
variables expanded inline for legibility — the scripts set `%SimplifyNoise%` etc. near the top and
pass the variable:

```bat
:: Model tools - profile is the SOLE argument
call :run -simplify         "%MetadataDir%\SimplifyNoise_Params.xml"
call :run -calculateTexture "%MetadataDir%\Texturing_MaxTextureCount4_16k.xml"
call :run -unwrap           "%MetadataDir%\Unwrapping_Simplified_4x16k.xml"

:: Reprojection - profile is the THIRD argument, after two model names
call :run -reprojectTexture "%model_tag%_HighPoly_Textured" "%model_tag%_Simplified" ^
                            "%MetadataDir%\ReprojectionParams.xml"

:: Model export - profile is the THIRD argument, after model name and output path
call :run -exportModel "%comp%_Simplified_Textured" ^
                       "%out_dir%\%comp%\obj\%comp%.obj" ^
                       "%MetadataDir%\ModelExportParamsOBJ_NiraParts.xml"

:: Flight log - profile is the SECOND argument
call :run -importFlightLog "%flight_log_dir%" "%flight_log_params_dir%"
```

Source lines: `GenerateModel.bat` 122 / 124 / 155 / 156, `ExportDeliverables.bat` 93,
`AlignZone.bat` 77. [VERIFIED-by-inspection, 2026-08-04]

---

## 2. Profile schemas by type

Each section gives: purpose, producing dialog, root/GUID, the keys observed in a real file with
type and meaning, a minimal working example, and the repo files of that type. Key-level semantics
(defaults, full allowed-value lists, binary-only siblings) are in `03-settings-keys.md`; this
section documents the *file*.

### 2.1 Alignment params

| | |
|---|---|
| **Purpose** | Pin every structure-from-motion setting for a reproducible alignment |
| **Producing dialog** | ALIGNMENT ▸ Registration ▸ Settings |
| **Root** | `<Configuration id="{E377B69D-FB4B-4833-9CBE-FF747B7AF6D9}">` |
| **Consumed by** | **Nothing.** `-align` takes no parameter file (§1.4) |
| **Repo file** | `RS_CLI/Metadata/AlignmentParams.xml` (39 entries) |

**This is the profile type that is not a profile argument.** `AlignmentParams.xml` is read by the
*workflow*, not by RealityScan: `AlignZone.bat` parses it and replays each `sfm*` / `lis*` row as a
delegated `-set` before a plain `-align`. The exact loop, verbatim, because its quoting is
load-bearing:

```bat
for /f usebackq^ tokens^=2^,4^ delims^=^" %%A in ("%AlignmentParams%") do (
    echo %%A| %SystemRoot%\System32\findstr.exe /b /c:"sfm" /c:"lis" >nul
    if not errorlevel 1 %RealityScan% -delegateTo %RS_INSTANCE% -set "%%A=%%B"
)
```

Splitting on `"` yields token 2 = the key and token 4 = the value from
`<entry key="K" value="V"/>`. This depends on **key preceding value in every entry** — true in all
34 repo profiles — and it silently skips any line without at least four quote-delimited tokens,
which is why hand-added XML comments survive it. **A double quote inside a comment would inject
garbage into a `-set`.** [VERIFIED-by-inspection: `AlignZone.bat` lines 85–88; repo attribute-order
audit 2026-08-04]

Production values in force since 2026-07-25, all 39 entries:

| Key | Value | Note |
|---|---|---|
| `sfmDistortionModel` | `Division` | **global and all-or-nothing** — the per-camera XMP `Camera:DistortionModel` hint written by `modules/camera_registry.py` does **not** switch models per camera; every solved camera came back `xcr:DistortionModel="division"` [VERIFIED: FINDINGS 2026-07-26]. The file's own comment records the intent (fisheye Port/Starboard division, rectilinear Cinema/Zeuss brown3) that the setting cannot express. Note `docs/settings-evaluation-2026-07` §4 and FINDINGS 2026-07-23 recommend `Brown3` as the global fallback for this rig class while the shipped file still says `Division` [CONTRADICTED-internal: repo recommendation vs shipped profile; the profile is what runs] |
| `sfmEnableCameraPrior` | `true` | the GUI's "use camera priors for georeferencing" |
| `sfmCameraPriorWeight` | `10.0` | never A/B'd |
| `sfmCameraPriorWeightOrientation` | `2.0` | lowered from `10.0` 2026-09-01; still never A/B'd |
| `sfmCameraPriorAccuracyYaw` / `Pitch` / `Roll` | `10.0` each | |
| `sfmDetectorSensitivity` | `Ultra` | weak underwater texture |
| `sfmImagesOverlap` | `Medium` | Low was legacy |
| `sfmImagesOverlapDraftMode` | `Medium` | |
| `sfmForceComponentRematch` | `false` | merge-stage tool; wasted per zone |
| `sfmMergeGeoreferencedComponents` | `false` | never manifested headless in any form [CONTRADICTED: NA167 D1/D2, 2026-07-24] |
| `sfmMaxFeaturesPerImage` | `0xc350` | = 50000 |
| `sfmMaxFeaturesPerMpx` | `0x36b0` | = 14000 |
| `sfmPreselectorFeatures` | `0x4e20` | = 20000 |
| `sfmMaxFeatureReprojectionError` | `1.29999995` | |
| `sfmGPUAcceleration` | `true` | |
| `sfmFeatureDetectionQuality` | `RealityScan.FeatureDetector.RSa1` | a current product string — never rename |
| `sfmImageDownscaleFactor` | `1` | never varied |
| `sfmImageDownscaleFactorDraftMode` | `2` | |
| `sfmCameraDepthmapWeight` | `0.05` | |
| `sfmControPointImageMeasAccuracy` | `4.0` | **Epic's typo, sic** — the corrected spelling does not exist. Help default `2.0` [OFFICIAL: tutorials/setkeyvaluetable] |
| `sfmBackgroundDetectFeatures` | `false` | |
| `sfmBackgroundDetectThreadPriority` | `Low` | |
| `sfmAutoReconRegionAfterAlignment` | `false` | Help default is **`true`** [OFFICIAL: tutorials/setkeyvaluetable] — this profile disables it |
| `sfmEnableAutoSuggestions` | `true` | |
| `sfmFinalModelOptimizationDraftMode` | `false` | |
| `lisPreferImagesAsFeatureSource` | `false` | LiDAR-oriented; never probed |
| `s235l` `s236l` | `5.0`, `5.0` | **meaning unknown** |
| `s237l` | `0.5` | **meaning unknown** |
| `s251l` `s252l` | `0.05`, `0.05` | **meaning unknown** |
| `s253l` | `0.1` | **meaning unknown** |
| `s254l` | `0.001` | **meaning unknown** |

[VERIFIED-by-inspection: `RS_CLI/Metadata/AlignmentParams.xml`, 2026-08-04]

The `s2NNl` keys came from a GUI-exported params file and are passed through untouched. They have
no Help coverage of any kind. Because the `.bat` loop only replays `sfm*` and `lis*` rows,
**they are not applied to anything today** — they are inert cargo.
[UNDOCUMENTED] [OPEN: export the alignment panel from the GUI, change exactly one control, export
again, diff — one minute at the GUI identifies each `s2NNl`.]

Minimal working example (this is a complete, valid file):

```xml
<Configuration id="{E377B69D-FB4B-4833-9CBE-FF747B7AF6D9}">
  <entry key="sfmDistortionModel" value="Division"/>
  <entry key="sfmEnableCameraPrior" value="true"/>
  <entry key="sfmDetectorSensitivity" value="Ultra"/>
  <entry key="sfmImagesOverlap" value="Medium"/>
</Configuration>
```

Test-cell override: `AlignZone.bat` honours `RS_ALIGN_PARAMS` to point at a variant file without
touching the canonical copy — the pattern to copy for any experiment.
[VERIFIED-by-inspection: `AlignZone.bat`]

### 2.2 Flight-log / trajectory import params

| | |
|---|---|
| **Purpose** | Select the log's column format and declare the CRS its coordinates are in |
| **Producing dialog** | WORKFLOW ▸ Import Metadata ▸ Trajectory |
| **Root** | `<Configuration id="{93DBD041-AE1C-4631-89BC-D9430FCED843}">` |
| **Consumed by** | `-importFlightLog <log> <params.xml>`, `-importTrajectory <log> <params.xml>` |
| **Repo file** | `RS_CLI/Metadata/FlightLogParams.xml` — **regenerated per run**, never used as-is |

Complete file, as generated for NA173_H2103a (UTM 57S):

```xml
<Configuration id="{93DBD041-AE1C-4631-89BC-D9430FCED843}">
  <entry key="ifuuInhEn" value="true"/>
  <entry key="ifCSopt" value="1"/>
  <entry key="gpsLogFileFormat" value="{B438A617-2434-5A24-C1B7-58980F28345A}"/>
  <entry key="CoordinateSystemFlightLog" value="+proj=utm +zone=57 +south +datum=WGS84 +units=m +no_defs"/>
  <entry key="CoordinateSystemFlightLogType" value="epsg:32757 - WGS 84 / UTM zone 57S"/>
  <entry key="ifKGrp" value="2"/>
  <entry key="csvFLIgn" value="true"/>
  <entry key="ifuuInh" value="0"/>
  <entry key="ifKmode" value="0x0"/>
  <entry key="csvFLSep" value="1"/>
  <entry key="ifUsePosAcc" value="true"/>
  <entry key="ifUseOriAcc" value="true"/>
</Configuration>
```

| Key | Type | Meaning | Tag |
|---|---|---|---|
| `gpsLogFileFormat` | GUID | selects a `<format id>` from `flightlogs.xml` — this is the join between the profile and the install-tree dictionary | [VERIFIED-by-inspection] |
| `CoordinateSystemFlightLog` | PROJ string | the CRS the log's X/Y/Z are in | [VERIFIED] |
| `CoordinateSystemFlightLogType` | display string, shape `epsg:<code> - <name>` | the same CRS, human-readable | [VERIFIED] |
| `ifCSopt` | int `1` | coordinate-system option | [UNDOCUMENTED] |
| `ifKGrp` | int `2` | **two competing readings, neither tested.** (a) calibration-group mode on import ("Automatically group camera calibration") — name-based; (b) one of the two carriers of *Euler angles order (YPR)* / *Camera mount*, the pair FINDINGS 2026-07-26 names as the only plausible carriers | [UNDOCUMENTED] [OPEN: question 9] |
| `ifuuInhEn` / `ifuuInh` | bool / int | accuracy inheritance enabled / value. Both strings **are** present in the 2.2 binary | [UNDOCUMENTED] |
| `csvFLSep` | int `1` | value separator | [UNDOCUMENTED] |
| `csvFLIgn` | bool | ignore first line | [UNDOCUMENTED] |
| `ifKmode` | `0x0` | **the exact spelling is absent from the 2.2 binary string pool — almost certainly inert.** The binary has `ifKModel` (capital M) | [CONTRADICTED: repo profile carries `ifKmode` / UTF-16LE string sweep of `RealityScan.exe` finds only `ifKModel`; recorded in `06-georeferencing-flightlogs-and-scale.md` §2] |
| `ifUsePosAcc` / `ifUseOriAcc` | `true` | **exact spellings absent from the 2.2 binary string pool — almost certainly inert.** The live accuracy-inheritance strings are `ifuuInhEn` / `ifuuInh` | [CONTRADICTED: same sweep, same section] |

**This contradiction is load-bearing and unresolved.** The repo's own findings log repeatedly
attributes behaviour to `ifUseOriAcc=true` ("production `FlightLogParams.xml` selects the 13-column
YPR format with `ifUseOriAcc=true`, so zone_1/2/3 imported orientation"), while the binary-string
scan says the key does not exist in 2.2. Both can be true simultaneously — orientation may be
imported because the *selected format* (`{B438A617…}`) maps `Yaw`/`Pitch`/`Roll` at indices 7/8/9,
with the `ifUse*Acc` keys contributing nothing. That reading reconciles the two, but it has not
been tested. [CONTRADICTED: FINDINGS 2026-07-26 attributes orientation import to `ifUseOriAcc=true`
/ the binary string sweep finds no such key] [OPEN: import the same log twice with `ifUseOriAcc`
`true` and `false` under the same 13-column format and diff the resulting camera attitudes out of
the pose XMPs; ~2 min on the smoke fixture.]

**Two settings the import dialog exposes are not pinned by this file at all** — *Euler angles order
(YPR)* and *Camera mount*, both documented in `tools/flightlogimport` and both present whenever YPR
is included. Neither `ifKGrp` nor `ifKmode` is a confirmed carrier, and **neither key string appears
in any file under the RealityScan install**, so both settings are compiled into the binary. Every
orientation-prior result in this repo was therefore measured through an unverified import path: the
registration counts stand as measurements, the attribution to "orientation priors" does not.
[UNDOCUMENTED / VERIFIED-as-flag: FINDINGS 2026-07-26]

**The zone must never be hand-edited.** `modules/flight_logs.write_flight_log_params` rewrites
`CoordinateSystemFlightLog` and `CoordinateSystemFlightLogType` from the UTM zone parsed out of the
flight log's own filename (`flight_log_53N_UTM.txt` → EPSG:32653), regenerating the file per run:

```python
proj     = f'+proj=utm +zone={zone}{south} +datum=WGS84 +units=m +no_defs'
crs_type = f'epsg:{epsg} - WGS 84 / UTM zone {zone}{hemisphere}'
```

The template once said 4N from an earlier project while the cruise was 57S. **A wrong zone imports
silently and misplaces everything.** [VERIFIED: NA167 #6 + FINDINGS 2026-07-21/22]

The `{B438A617-2434-5A24-C1B7-58980F28345A}` format referenced above **did not exist in the stock
2.2 `flightlogs.xml`** until it was hand-merged into `C:\Program Files\Epic Games\
RealityScan_2.2\flightlogs.xml` on 2026-07-25. Until that date the profile named a format the app
did not have, and **orientation and per-image accuracies were silently dropped on every import**.
This is a modification of an Epic-shipped file and must be re-verified after any application
update. [VERIFIED: PRIORS_DISTORTION_TEST_PLAN audit item 1, 2026-07-25] [OPEN: whether the merge
survives an app update — re-check after any RealityScan update.]

**Why a custom format was needed at all.** The 14 formats now in `flightlogs.xml` are the 13 stock
ones plus this one. The stock set tops out at **10 columns** — `{97F08A22-F231-4AB4-A2FD-6FA42BB6D663}`
= `Image X/Lon Y/Lat Z/Alt X/LonAccuracy Y/LatAccuracy Z/AltAccuracy Yaw Pitch Roll` — and offers no
`YawAccuracy` / `PitchAccuracy` / `RollAccuracy` columns anywhere. Per-image orientation *accuracies*
are therefore unreachable through stock RealityScan; the 13-column format exists solely to carry
them at indices 10/11/12. A `Custom` entry `{80679981-0DF8-43DE-ABF7-35CCD8563320}` also ships, but
its parser maps nothing.
[VERIFIED-by-inspection: installed `flightlogs.xml`, 2026-08-04]

### 2.3 XMP export params

| | |
|---|---|
| **Purpose** | Control what goes into exported `<stem>.xmp` sidecars |
| **Producing dialog** | ALIGNMENT ▸ Export ▸ **XMP Files** |
| **Root** | `<Configuration id="{EC40D990-B2AF-42A4-9637-1208A0FD1322}">` |
| **Consumed by** | `-exportXMP <params.xml>` |
| **Repo file** | `RS_CLI/Metadata/XMPExportParams.xml` — **shipped but never used** |

```xml
<Configuration id="{EC40D990-B2AF-42A4-9637-1208A0FD1322}">
  <entry key="xmpMerge" value="true"/>
  <entry key="xmpExGps" value="true"/>
  <entry key="xmpFlags" value="true"/>
  <entry key="xmpCalibGroups" value="true"/>
  <entry key="xmpCamera" value="3"/>
  <entry key="xmpRig" value="true"/>
</Configuration>
```

| Key | Maps to the dialog control | Tag |
|---|---|---|
| `xmpCamera` = `3` | *Camera export mode* — **Export as draft** (absolute positions, adjusted during alignment) / **Export as exact** (relative positions preserved) / **Export as locked** (relative **and** absolute preserved, never adjusted) | Control semantics [OFFICIAL: tools/xmpalign]. That `3` selects one of them, and which, is [INFERRED] — three modes plus a "none" would give a 0..3 range. **Not confirmed.** |
| `xmpMerge` | *Merge with existing XMP files* — "creating new XMP files for the same images will result in the replacement of existing ones" | Control [OFFICIAL: tools/xmpalign]; key mapping [INFERRED: name ↔ control] |
| `xmpRig` | *Export rigging setup* — rig info for laser scans; if disabled only position and orientation are exported | [OFFICIAL] / [INFERRED] |
| `xmpCalibGroups` | *Export camera calibration groups* | [OFFICIAL] / [INFERRED] |
| `xmpFlags` | *Include editor options* — marks images enabled for texturing and meshing (`xcr:InTexturing` / `xcr:InMeshing`) | [OFFICIAL] / [INFERRED] |
| `xmpExGps` | *Replace GPS Exif with optimized values* — use alignment-solved coordinates instead of EXIF | [OFFICIAL] / [INFERRED] |

[UNDOCUMENTED: none of these six key **names** appears in the Help. The controls are all documented
in `tools/xmpalign`; the key→control mapping is name-to-control inference over that page's six
options, which match one-to-one and in the same order.]

**The same six controls are also reachable from the registration export.** `calibration.xml` ships
`{B95BEEA0-5E3C-49FC-9823-97AAD709D1BF}` — `desc="RealityScan XMPs with Image List"`,
`writer="RealityScan.Export.XMP"`, `mask="*.imagelist"` — and its dialog is the Export Registration
dialog carrying the same Camera export mode / Merge / Rigging / Calibration groups / Editor options
/ GPS controls **plus** undistortion, image-export and transformation settings. So a registration
profile is a superset of an XMP profile.
[OFFICIAL: tools/xmpalign; VERIFIED-by-inspection: installed `calibration.xml`, 2026-08-04]

**Every production XMP export in this repo ran without this file**, so all of it used instance
defaults. [VERIFIED-by-probe: repo-wide grep, 2026-08-04] The `xmpCamera` mode matters more than it
looks: exporting as *exact* or *locked* changes how the sidecars behave on any later `-add` of the
same images, and pose-bearing sidecars are auto-imported as priors, silently.
[VERIFIED: NA167 B7]

Hard constraints that no key in this profile can change:

- RealityScan reads and writes `<stem>.xmp` **only** — "an image and an XMP file with the same name
  will act as one". `image.jpg.xmp` is ignored **silently** — a batcher bug wrote priors that way
  and **no run before 2026-07-22 ever loaded its calibration priors**.
  [OFFICIAL: tools/xmpalign] [VERIFIED: NA167 #3 / B7]
- One `_common.xmp` placed in the image folder applies its content to **every** image in that
  folder — the cheapest way to push a shared prior without writing per-image sidecars, and never
  used here. `-addImageWithCalibration` is the other exception: it takes image and XMP paths
  explicitly, so the two files need not share a name or a folder.
  [OFFICIAL: tools/xmpalign] [OPEN: neither has been exercised through this CLI]
- Naming is decided by the **command**, not by this profile and not by the scene: `-exportXMP`
  writes stem-named sidecars, `-exportXMPForSelectedComponent` writes ordinal sidecars
  (`00000.xmp`, `00001.xmp`, …) in every observed context. Ordinal sidecars are inert as priors,
  since no image has an ordinal stem. [VERIFIED: FINDINGS 2026-07-23, B10 final form]
- `-exportXMP` covers only "the last alignment" and silently skips components below
  `-setMinComponentSize` (default 5). [OFFICIAL + VERIFIED: HANDOFF 2026-07-21]
- Scenes whose images resolve through a **directory junction** (any NTFS reparse point) get no
  sidecars written at all, and the export **reports success** — `exportXMPForSelectedComponent`
  logged "Exporting Registration completed in 8.758 seconds" while a sweep of the whole volume
  found zero new `.xmp`. Isolated by probe: four components whose `.rsalign` files carried real
  (non-junction) image paths ran the identical workflow and produced 267 pose-bearing sidecars.
  Fix verified 2026-07-28 — replacing five per-zone junctions with real directories (JPGs
  hardlinked, XMPs copied) took recursive enumeration through the path from **0 to 9,835**
  sidecars, with no re-align needed.
  [VERIFIED: FINDINGS 2026-07-27 ESTABLISHED + 2026-07-28 ESTABLISHED] [UNDOCUMENTED]

### 2.4 Simplify params

| | |
|---|---|
| **Purpose** | Target triangle count and decimation behavior for `-simplify` |
| **Producing dialog** | SCENE 3D ▸ TOOLS ▸ Simplify |
| **Root** | `<Configuration id="{033AEF62-8421-47A4-81CB-203741113577}">` |
| **Consumed by** | `-simplify <params.xml>` |
| **Epic default** | `C:\Program Files\Epic Games\RealityScan_2.2\Settings\SimplifiedExport\simplify.xml` |

Epic's shipped default, complete:

```xml
<Configuration id="{033AEF62-8421-47A4-81CB-203741113577}">
    <entry key="mvsFltUnwrapTexSide" value="0"/>
    <entry key="mvsFltReprojectColor" value="false"/>
    <entry key="mvsFltTargetTrisCountAbs" value="1000000"/>
    <entry key="mvsFltTargetTrisCountRel" value="10"/>
    <entry key="mvsFltSimplificationType" value="3"/>
    <entry key="mvsFltUnwrapTexCount" value="0"/>
    <entry key="mvsFltReprojectNormal" value="0"/>
    <entry key="mvsFltMinEdgeLength" value="0.0"/>
    <entry key="mvsFltBorderDecimationStyle" value="1"/>
    <entry key="simplPreserveParts" value="0"/>
</Configuration>
```

| Key | Type | Values seen | GUI control | Tag |
|---|---|---|---|---|
| `mvsFltSimplificationType` | enum int | `0`, `1`, `3` | *Type* — **Absolute** (to `…Abs`; Epic's "recommended way") / **Relative** (to `…Rel` %) / **Maximum of absolute and relative** (picks the higher count) / **Minimum of absolute and relative** (picks the lower) | Option list and semantics [OFFICIAL: tools/simplify]. `0`=Absolute and `1`=Relative [VERIFIED-by-correspondence: repo files pair `0` with `…Abs` and `1` with `…Rel`, and the filenames say which]; `2`/`3` are [OPEN]. Epic's own `simplify.xml` ships type `3` with **both** targets set (1,000,000 abs and 10 %), which is the only configuration where 2/3 mean anything |
| `mvsFltTargetTrisCountAbs` | int | `500000`, `1000000` | *Target triangle count* | [OFFICIAL + VERIFIED] |
| `mvsFltTargetTrisCountRel` | int percent | `10`, `50`, `70`, `80` | *Target triangles percentage* | [OFFICIAL + VERIFIED] |
| `mvsFltMinEdgeLength` | float | `0.0` | *Minimal edge length* — "the affected edges will not be shorter than this threshold" | [OFFICIAL] |
| `mvsFltBorderDecimationStyle` | enum int | `1` | *Border Decimation* — Simplify the border / Keep border intact ("not recommended for very extreme decimation") | [OFFICIAL] for the options, [OPEN] for which is `1` |
| `simplPreserveParts` | enum int | `0` (Epic), `2` (repo) | *Part merging* — **Disable** (original parts preserved) / **Enable** (parts merged into the largest processable parts) / **Create a singleton** (forces one part; Epic recommends it only under a few million triangles) | Options [OFFICIAL: tools/simplify]. [CONTRADICTED: a 0-based reading of that option order makes `2` = "Create a singleton", yet the H2024 deliverable models — four consecutive `simplPreserveParts=2` passes — exported as **4 parts**, not one [VERIFIED: FINDINGS 2026-07-29]. Either the enum is not 0-based in this order, or `2` means something else. Unresolved; see question 13] |
| `simplEqualizeDensity` | bool | `true` | *Density Equalization* — "ensures consistent vertex density throughout all simplified model parts in multi-part models"; when off, density varies per part and causes visible seams; when on, computation takes longer | Control [OFFICIAL: tools/simplify]; key name [UNDOCUMENTED] — present in every repo file, **absent from Epic's shipped `simplify.xml`** |
| `mvsFltReprojectColor` | bool | `false` | *Color reprojection* — reproject the colour layer from the source model onto the simplified one | [OFFICIAL] |
| `mvsFltReprojectNormal` | int | `0` | *Normal reprojection* — Enable / Disable / **Automatic** ("the normal layer is reprojected only when it is reasonable to create it") | Options [OFFICIAL: tools/simplify]; [OPEN: which is `0`] |
| `mvsFltUnwrapTexCount` / `mvsFltUnwrapTexSide` | int | `0`, `0` | *Unwrap parameters* — *Maximal texture count* / *Texture resolution*, each "same as source or custom value"; `0` = same as source | [INFERRED from the Help's same-as-source/custom pairing] |

Two behavioural facts that no key here changes and that decide *when* you simplify:

- **Simplify does not modify the existing model — it creates a new one**, and that new model
  **loses its texture and keeps only the coloring**. This is why the production recipe textures the
  high-poly model, simplifies, unwraps, and then *reprojects* rather than re-texturing.
  [OFFICIAL: tools/simplify]
- The tool is only active once a model exists **and is selected**. [OFFICIAL: tools/simplify]

`-simplify` is the one polymorphic case: `-simplify 1000000` (bare integer) and
`-simplify params.xml` are both legal, and `-simplify` with no argument uses current settings.
[OFFICIAL: appbasics/allcommands]

### 2.5 Smoothing params

| | |
|---|---|
| **Purpose** | Smoothing strength, target vertices, weight and iteration count |
| **Producing dialog** | SCENE 3D ▸ TOOLS ▸ Model & Texture ▸ Smoothing |
| **Root** | `<Configuration id="{585E749B-DC69-4D8C-9114-FA8CBB6F88F3}">` |
| **Consumed by** | `-smooth <params.xml>` |
| **Epic default** | `Settings\SimplifiedExport\smooth.xml` |

Epic's shipped default, complete — note the fifth key, which the binary does not contain:

```xml
<Configuration id="{585E749B-DC69-4D8C-9114-FA8CBB6F88F3}">
  <entry key="mvsSmoothing_useIntelligentSmoothing" value="0"/>
  <entry key="smoothIterations" value="5"/>
  <entry key="mvsFltSmoothingType" value="1"/>
  <entry key="mvsFltSmoothingStyle" value="3"/>
  <entry key="smoothWeight" value="0.5"/>
</Configuration>
```

| Key | Type | Values seen | GUI control | Tag |
|---|---|---|---|---|
| `smoothIterations` | int | `2` (repo), `5` (Epic) | *Smoothing iterations* | [OFFICIAL + VERIFIED] |
| `smoothWeight` | float | `0.2` (repo), `0.5` (Epic) | *Smoothing weight* | [OFFICIAL + VERIFIED] |
| `mvsFltSmoothingType` | enum int | `0` (repo), `1` (Epic) | *Smoothing type* — "defines the overall strength of the tool" | Control [OFFICIAL: tools/smoothing]; [OPEN: value↔name mapping, and the Help does not print the option list] |
| `mvsFltSmoothingStyle` | enum int | `1`, `3` | *Smoothing style* — "only vertices on the surface" / "only vertices that create the borders" / "only vertices that create peaks" / "all vertices (surface and borders)" | Option order [OFFICIAL: tools/smoothing]. [CONTRADICTED: repo filenames assert `1`=surface (`SmoothingSurface_02_2`) and `3`=peaks (`SmoothingPeaks_05_5`), which contradicts a 0-based reading of that order (0=surface, 1=borders, 2=peaks, 3=all). A **1-based** enum reconciles them exactly — 1=surface, 2=borders, 3=peaks, 4=all — but nothing tests it, and the repo names were themselves guesses. See question 12] |
| `mvsSmoothing_useIntelligentSmoothing` | bool | `0` | — | **Exact spelling absent from the 2.2 binary string pool — almost certainly inert, and it is Epic's own shipped file.** [CONTRADICTED: Epic's `SimplifiedExport\smooth.xml` carries it / UTF-16LE sweep of `RealityScan.exe` does not contain it; recorded in `10-reconstruction-texturing-export.md` §6] |

Epic's own tip: smaller weight + more iterations to remove noise; higher weight + fewer iterations
to smooth mesh; "we recommend you use the default values". Smoothing **creates a new model** and
preserves the original. [OFFICIAL: tools/smoothing]

`-smooth` has never been run in this repo. All three smoothing profiles are unused, and two of them
are byte-identical (§4.3).

### 2.6 Unwrap params

| | |
|---|---|
| **Purpose** | UV layout strategy, texture count and resolution bounds |
| **Producing dialog** | MESH & COLOR ▸ Color & Texture ▸ Unwrap tool |
| **Root** | `<Configuration id="{54A4029C-DE57-43F6-8F81-75C62E159021}">` — **shared with texturing** |
| **Consumed by** | `-unwrap <params.xml>` |
| **Repo files** | `Unwrapping_Simplified.xml`, `Unwrapping_Simplified_4x16k.xml` |

```xml
<Configuration id="{54A4029C-DE57-43F6-8F81-75C62E159021}">
  <entry key="unwrapButtonDisabled" value="0"/>
  <entry key="unwrapGutter" value="2"/>
  <entry key="unwrapMinTexResolution" value="512"/>
  <entry key="unwrapStyle" value="MaxTexturesCount"/>
  <entry key="unwrapMaximalTexCount" value="4"/>
  <entry key="unwrapFillTextures" value="0x0"/>
  <entry key="unwrapMaxTexResolution" value="16384"/>
  <entry key="unwrapLargeTriangleRemovalThr" value="10"/>
  <entry key="unwrapMethod" value="Geometric"/>
</Configuration>
```

| Key | Type | Values seen | GUI control | Tag |
|---|---|---|---|---|
| `unwrapStyle` | enum name | `MaxTexturesCount`, `FixedTexelSize` | *Style*. Under the **Geometric** method the values are `MaxTexturesCount` (default), `FixedTexelSize`, `AdaptiveTexelSize`; under **Mosaicing based** the Style options become *Maximal texture count* and *Quality* | Value list and default [OFFICIAL: tutorials/setkeyvaluetable, row `Style | unwrapStyle`]. The mosaicing-only *Quality* option is prose in `tools/texturing_part2`; **its value string is not printed anywhere** [OPEN] |
| `unwrapMaximalTexCount` | int | `1`, `2`, `4` | *Maximal texture count*; relevant only when `unwrapStyle=MaxTexturesCount`. Help default `1` | [OFFICIAL: tutorials/setkeyvaluetable] |
| `unwrapMinTexResolution` | enum int | `512` | *Minimal texture resolution*: 512 / 1024 / 2048 / 4096 / 8192 / 16384. Help default `512`. Cannot exceed `unwrapMaxTexResolution` | [OFFICIAL] |
| `unwrapMaxTexResolution` | enum int | `8192`, `16384` | *Maximal texture resolution*, same list. Help default `8192` | [OFFICIAL] |
| `unwrapGutter` | int | `2`, `10` | *Gutter* in texels; Help default `2`, "enough to avoid this type of artefact in most rendering engines" (mip-map chart bleed) | [OFFICIAL] |
| `unwrapLargeTriangleRemovalThr` | int | `10`, `400`, `1000` | *Large triangle removal threshold*: a triangle whose edge length × threshold exceeds the model's average edge length is mapped to a single texel. Help default `10` | [OFFICIAL] |
| `unwrapMethod` | enum name | `Geometric` | *Unwrap method*: **Geometric** (legacy, fast) or **Mosaicing based** (experimental, fewer UV islands, slower) | Control [OFFICIAL: tools/unwrap]; key name [UNDOCUMENTED] and the mosaicing value string is unknown [OPEN: question 19] |
| `unwrapFixedTexelSizeType` | enum int | `0`, `1` | *Texel size*, relevant when `unwrapStyle=FixedTexelSize`: `0` Optimal (default), `1` 2× optimal (50 % texture quality), `2` 4× optimal (25 %), `3` 10× optimal (10 %), `4` 100× optimal (1 %), `5` Custom | [OFFICIAL: tutorials/setkeyvaluetable, row `Texel size | unwrapFixedTexelSizeType`] |
| `unwrapFixedTexelSize` | float | *(not in any repo file)* | *Custom texel size*, active only when `unwrapStyle=FixedTexelSize` **and** `unwrapFixedTexelSizeType=5`. Help default `0.01` — i.e. a 1 cm texel when the project unit is the metre | [OFFICIAL: tutorials/setkeyvaluetable] |
| `unwrapMinTexelSize` / `unwrapMaxTexelSize` | enum int, or float when type = 5 | *(not in any repo file)* | *Minimal / Maximal required texel size*, active when `unwrapStyle=AdaptiveTexelSize`. Same 0–5 ladder as `unwrapFixedTexelSizeType`; Help defaults `0` and `4`. As custom floats the defaults are `0.01` and `10` | [OFFICIAL: tutorials/setkeyvaluetable] |
| `unwrapFillTextures` | hex bool | `0x0` (unwrap files), `0x1` (texturing files) | *Fill with charts* — "display the UV charts over the UV checker in the 2D view". A **preview-only** control | [INFERRED: name ↔ the only fill-related control on the panel; `tools/unwrap` documents the control, nothing documents the key] [OPEN: question 18] |
| `unwrapCheckerBoardCellSize` | int | `64` | *Grid size* — "sets the size of the checkerboard grid pattern" for previewing seams in the 3D view. Preview-only | **Exact spelling absent from the 2.2 binary string pool — almost certainly inert.** The binary has `unwrapCheckerBoardCellCount`. [CONTRADICTED: repo profiles carry `…CellSize` / UTF-16LE sweep finds only `…CellCount`; recorded in `10-reconstruction-texturing-export.md` §9] |
| `unwrapButtonDisabled` | int | `0` | — | Not a setting: **exported UI state**, carried into the file by the GUI export and inert. [INFERRED] |

**One documented control has no observed key**: *Defragment charts* ("create larger UV islands
during the unwrapping process using the approach of Maggiordomo, Cignoni, and Tarini"). It appears
in both `tools/unwrap` and `tools/texturing_part2` but in no repo profile, no Epic profile, and no
`setkeyvaluetable` row. [OFFICIAL: the control] [OPEN: the key name — export the Unwrap panel from
the GUI once and diff]

The `unwrapFillTextures`, `unwrapCheckerBoardCellSize` and `unwrapButtonDisabled` entries are worth
internalising as a general property: **a GUI-exported profile captures dialog state, not only
algorithm parameters.** Preview-only controls and button-enabled flags ride along.

### 2.7 Texturing params

Same GUID, same key family, same commands' worth of keys as §2.6 — the difference is which command
you hand the file to. `-calculateTexture <params.xml>` reads the same panel.

Two shapes are in production use here:

**Texture-count budget** (`Texturing_MaxTextureCount<N>_<res>.xml`, four variants):

```xml
<Configuration id="{54A4029C-DE57-43F6-8F81-75C62E159021}">
  <entry key="unwrapCheckerBoardCellSize" value="64"/>
  <entry key="unwrapButtonDisabled" value="0"/>
  <entry key="unwrapGutter" value="2"/>
  <entry key="unwrapStyle" value="MaxTexturesCount"/>
  <entry key="unwrapMaximalTexCount" value="4"/>
  <entry key="unwrapFillTextures" value="0x1"/>
  <entry key="unwrapMaxTexResolution" value="16384"/>
  <entry key="unwrapLargeTriangleRemovalThr" value="1000"/>
</Configuration>
```

**Fixed texel size** (`Texturing_FixedTexelSize<N>perQuality.xml`, two variants) — swaps
`unwrapStyle` to `FixedTexelSize`, adds `unwrapFixedTexelSizeType`, drops the texture-count key,
raises `unwrapGutter` to `10`, and lowers `unwrapLargeTriangleRemovalThr` to `400`:

```xml
<Configuration id="{54A4029C-DE57-43F6-8F81-75C62E159021}">
  <entry key="unwrapButtonDisabled" value="0"/>
  <entry key="unwrapGutter" value="10"/>
  <entry key="unwrapFixedTexelSizeType" value="1"/>
  <entry key="unwrapStyle" value="FixedTexelSize"/>
  <entry key="unwrapFillTextures" value="0x0"/>
  <entry key="unwrapMaxTexResolution" value="8192"/>
  <entry key="unwrapLargeTriangleRemovalThr" value="400"/>
</Configuration>
```

Which to use — and a naming trap:

- **`MaxTexturesCount` auto-adapts the texel size to fit the budget.** "The texel detail is
  adjusted automatically so that the texturing fits into the selected maximal number of textures
  within the selected maximal resolution." So a 4 × 16K budget caps cost while small components
  naturally use fewer and smaller textures. [OFFICIAL: tools/texturing_part2]
  **This is not the `AdaptiveTexelSize` style.** `AdaptiveTexelSize` is a *different* value of the
  same key: it clamps an algorithm-estimated texel into a `unwrapMinTexelSize`…`unwrapMaxTexelSize`
  range (finer near the subject, coarser elsewhere), and it produces however many textures that
  requires. The repo's shorthand "MaxTexturesCount IS the adaptive mode" (in the
  `GenerateModel.bat` comment) means *auto texel*, not `AdaptiveTexelSize`.
- **`FixedTexelSize` delivers a pre-declared visual precision** (e.g. 1 cm texels for a true
  ortho-photo map) and "there will be so many textures how many are needed".
  [OFFICIAL: tools/texturing_part2] [VERIFIED-as-decision: HANDOFF 2026-07-29 texture budget]

A hazard specific to `-calculateTexture`: the *default* unwrap parameters in this panel are applied
**only** when the model has no UV map and you texture directly. If the model is already unwrapped,
changing `unwrap*` values here does nothing to it — you must re-run `-unwrap` with a profile.
[OFFICIAL: tools/texturing_part2 — "WARNING: The default unwrap parameters are used only when an
object does not contain UV maps…"]

Behaviour that no key in this profile changes, and that dictates *when* you texture:
`-calculateTexture` projects from the **source images** with multi-band blending, so hole-fill
triangles that any camera saw receive real blended colour. Texture *after* `-closeHoles` +
`-cleanModel`; texturing a holey model and then reprojecting onto the closed one produces nodata
patches, because reprojection samples the source **surface**.
[VERIFIED-as-design-decision with mechanism: docs/settings-evaluation-2026-07 §7, 2026-07-23]

### 2.8 Texture-reprojection params

| | |
|---|---|
| **Purpose** | Which channels to carry from a textured source model onto an unwrapped target |
| **Producing dialog** | SCENE 3D ▸ TOOLS ▸ Model & Texture ▸ Reproject Texture |
| **Root** | `<Configuration id="{8F3517E3-5632-40FE-BD10-9967EA8F299F}">` |
| **Consumed by** | `-reprojectTexture <sourceModel> <resultModel> <params.xml>` |
| **Epic default** | `Settings\SimplifiedExport\reprojectTexture.xml` |

Epic's default (left) vs this repo's `ReprojectionParams.xml` (right) — the delta is the whole
point of the file:

| Key | Epic | Repo | Effect |
|---|---|---|---|
| `reprojectionTool_allowColor` | `false` | **`true`** | enables colour reprojection at all |
| `reprojectionTool_enableColor` | *(absent)* | `-1` | tri-state: reproject the colour layer |
| `reprojectionTool_sourceColorLayer` | *(absent)* | `Color8_0` | which source layer to sample |
| `reprojectionTool_colorSampling` | *(absent)* | `0` | *Texture sampling method* — "Nearest sampling" (fast, aliasing unless supersampled) vs "Trilinear sampling" (**recommended**, eliminates aliasing) |
| `reprojectionTool_normal` | `1` | `2` | *Normal reprojection* — writes a layer storing the source model's surface direction |
| `reprojectionTool_supersampling` | `-1` | `-1` | *Supersampling* — sample each quantity multiple times to reduce aliasing; "Off" samples once and is faster |
| `reprojectionTool_enableDisplacement` | `false` | `false` | *Displacement reprojection* — writes a layer storing the distance between the two models (for tessellation in external renderers) |
| `reprojectionTool_useCustomDistance` | `0` | `0` | custom search distance off |

Control semantics [OFFICIAL: tools/reprojection]; values [VERIFIED-by-inspection: both files,
2026-08-04].

[OPEN: whether `reprojectionTool_colorSampling=0` is "Nearest" or "Trilinear". The Help lists
Nearest first and recommends Trilinear, so a 0-based enum makes `0` = Nearest [INFERRED] — in which
case **every reprojected deliverable here carries avoidable aliasing**, since `supersampling` is
also `-1`. Cheapest probe: flip to `1`, reproject an existing high/simplified pair, compare the
texture visually.]

Three preconditions the profile cannot supply:

- **Both models must be in the same component.** The tool "project[s] a texture from an already
  textured model onto another model within the same component". [OFFICIAL: tools/reprojection]
- **The result model must already be unwrapped.** [OFFICIAL: tools/reprojection] — which is why
  `GenerateModel.bat` runs `-unwrap` immediately before `-reprojectTexture`.
- `-reprojectTexture` resolves both model operands **by name**. In a shared project holding several
  components' models, an unqualified name can map one component's texture onto another's mesh,
  silently — which is why `GenerateModel.bat` prefixes every model name with the component tag.
  [VERIFIED: FINDINGS 2026-07-25]

### 2.9 Model export params

| | |
|---|---|
| **Purpose** | Format, geometry attributes, textures, tiling, units and axis convention for `-exportModel` |
| **Producing dialog** | Export model — *or* extracted from a `.rsInfo` (§1.6) |
| **Root** | `<Configuration>` — **no `id` attribute on any of the 11 repo files** |
| **Consumed by** | `-exportModel <modelName> <fileName> <params.xml>`, `-exportSelectedModel <fileName> <params.xml>` |

**The target format is chosen by the output file's extension, not by the profile.** In the GUI the
format is the Save-As type; on the CLI the `fileName` argument carries "path and file extension".
A profile tuned for FBX passed with an `.obj` output path is an untested combination.
[INFERRED from `tools/export` + `appbasics/allcommands`] [OPEN: question 21]

Available save-as types, verbatim: Wavefront `.obj`, Polygon File Format `.ply`, XYZ Point Cloud
`.xyz`, Alembic `.abc`, Binary GL Transmission Format `.glb`, Stereo-litography `.stl`, 3D
Manufacturing `.3mf`, Universal Scene Descriptor `.usd`, Universal Scene Descriptor Zipped `.usdz`,
Laser Point Cloud `.ptx`, LAS Point Cloud `.las`, List of visible parts `.partList`, just textures,
Autodesk `.fbx`, AutoCAD DXF `.dxf`, Collada `.dae`. `.partList` needs no export settings at all.
[OFFICIAL: tools/export]

**Hard naming constraint:** "the file name cannot contain Unicode characters and/or spaces."
This is an export-dialog rule, not a cmd-quoting rule — quoting the path does not save you.
[OFFICIAL: tools/export]

Structural rules that hold across all 11 files [VERIFIED-by-inspection, 2026-08-04]:

- `ModelExportFormatVersion` is `0` or `13`. It is **not** the FBX version — that is the separate
  *Format version* control, whose options are FBX201100, FBX201200, FBX201300, FBX201400,
  FBX201800, FBX201900, FBX202000 (binary and ASCII), and which is "relevant only when exporting a
  model as .fbx" [OFFICIAL: tools/export]. What `ModelExportFormatVersion` *is* — most plausibly the
  schema version of the profile itself — is [INFERRED]: `0` appears on the OBJ and GLB profiles and
  `13` on the FBX/PLY/generic ones, which does not fit a per-format version either. [OPEN]
- Per-texture-layer keys carry a **layer suffix**: `MvsMeshExportTexturing_Color8_0`,
  `MvsMeshExportTexImgFormat_Color8_0`, `MvsMeshExportTexPixFormat_Color8_0`, and the `_Normal_0`
  and `_no_alpha` variants. Unsuffixed base keys also exist.
- `…Allowed` keys (`MvsMeshExportTexturingAllowed`, `…NormalsAllowed`, `…CamerasAllowed`,
  `…MaterialsAllowed`, `…ClassificationAllowed`, `…NumberFormatAllowed`, `…EmbeddTxrsAllowed`)
  use `-1` = allowed/inherit and `0` = not allowed. **They gate what the target format supports** —
  they are capability flags captured from the dialog, not user choices.
- Booleans appear as `true`/`false`, `0`/`1`, `0x1` and `1.0` interchangeably, sometimes for the
  same key across sibling files.

Core key reference:

| Key | Type | Observed | Meaning |
|---|---|---|---|
| `MvsExportcoordinatesystemtype` *(sic — lowercase `c`)* | int | `0`, `3` | export CRS mode. The dialog's *Coordinate system* options, in Help order: **Grid plane** (as seen in the 3D view) / **Project Output** (georeferenced models only; set in WORKFLOW ▸ Settings ▸ Coordinate systems) / **Shifted project output** (Project Output moved to the scene centre) / **Same as XMP** (also available for non-georeferenced models) [OFFICIAL: tools/export]. [INFERRED: `0`..`3` index that list in order; not confirmed — question 16] |
| `MvsExportIsGeoreferenced` | bool | `0x1`, `1.0` | export in world coordinates |
| `MvsExportIsModelCoordinates` | bool | `0` | export in model-local coordinates |
| `MvsExportScaleX/Y/Z` | float | `1.0`, `10.0`, `100.0` | `100` = metres → centimetres (Unreal/Maya) |
| `MvsExportMoveX/Y/Z` | float | `0.0` | translation |
| `MvsExportRotationX/Y/Z` | float | `0.0`, `-90.0` | GLB uses X = `-90.0` (Y-up) |
| `MvsExportTransformationPreset` | string | `Unreal`, `Maya + Arnold, Unreal`, `Custom`, `[[Custom]]` | *Transformation preset* — "applies a predefined Scene transformation and Normal transformation settings" [OFFICIAL: tools/export]. Must name a `<transform name>` from `transformdb.xml`. The comma-joined label appears when two presets are byte-identical for the applicable format group: in the generic group (`format="!obj,!fbx,!abc"`) `Maya + Arnold` and `Unreal` are exactly `normalFlip="0 1 0" scale="100 100 100"`, and no other pair matches [VERIFIED-by-inspection: `transformdb.xml`]. Because the preset only *seeds* the explicit `MvsExportScale*` / `Rotation*` / `NormalFlip*` entries, the label is descriptive of how the file was produced, not an instruction the exporter re-applies [INFERRED] |
| `MvsExportNormalSpace` | string | `Mikktspace` | *Normal transformation ▸ Space*: **World** (normals in the model's coordinate system) / **Object** (as World but Scene-transformation rotation is not applied to normals) / **Tangent (Mikktspace)** (compatible with several third-party renderers; "always enable Export vertex normals" with it) [OFFICIAL: tools/export] |
| `MvsExportNormalRange` | string | `ZeroToOne` | *Normal transformation ▸ Range* — float encoding range; "has no effect when a non-floating point Texture pixel format is selected" [OFFICIAL: tools/export] |
| `MvsExportNormalFlipX/Y/Z` | bool | Y = `true` everywhere here | channel mirroring |
| `MvsMeshExportNormals` | bool | `true` | write vertex normals |
| `MvsMeshExportColors` | bool | `false`, `true`, `0` | write vertex colours — `true` only in the dense-PLY profile |
| `MvsMeshExportTexturing` | tri-state | `-1`, `0`, `true` | write textures |
| `MvsMeshExportTexOneFile` | int | `0` | *Export to a single texture file*. `0` = No, which is what makes `MvsMeshExportTileType` appear at all: "If set to No, three Tile type options show up" [OFFICIAL: tools/export]. Setting it to Yes stitches all square textures into one image and instead exposes *Texture maximal side* (512 … 65536) and *Use pow2 texture size* — **whose key names are unknown**, since no repo profile has ever set it [OPEN] |
| `MvsMeshExportTileType` | int | `0`, `1`, `2` | *Tile type*: `_u1_v1`, `(u,v)`, UDIM — in that Help order. `0` = `_u1_v1`, `1` = `(u,v)`, `2` = UDIM [VERIFIED-by-correspondence: the three FBX profiles named `_U1V1` / `_UV` / `_UDIM` carry exactly `0` / `1` / `2`, and the Nira-parts OBJ profile (`0`) produced `u1_v1` textures on disk — FINDINGS 2026-07-29] |
| `MvsMeshExportByParts` | int | `0`, `1` | *Save mesh by parts* |
| `MvsMeshExportMaterials` | bool | `true`, `false` | *Export materials*; FBX only per the Help |
| `MvsMeshExportEmbeddTxrs` *(sic)* | bool | `true` (GLB), `false` | *Embedded textures* — single-file delivery |
| `MvsMeshExportTexImgFormat[_layer]` | string | `jpg`, `png`, `jpeg` | texture image format |
| `MvsMeshExportTexPixFormat[_layer]` | string | `24bppBGR`, `32bppBGRA` | 24-bit BGR / 32-bit BGRA / 64-bit RGBA |
| `MvsMeshExportTexAlpha` | bool | `false`, `0` | *Export texture alpha* |
| `MvsMeshExportCameras` | bool/int | `false`, `0` | export camera objects (FBX/ABC) |
| `MvsMeshExportCamerasAsModelPart` | bool | `false` | cameras as mesh |
| `MvsMeshExportInfoFile` | bool | `true` everywhere | write `<model>.rsInfo` — **leave this on**, §1.6 and §2.21 both depend on it |
| `MvsMeshExportNumberFormat` | int | `5` (`ModelExportParamsObj`), `6` (`ModelExportParamsOBJ_NiraParts`) | *Number format*. **[CONTRADICTED]**: the Help documents this control as a **three-option enum** — "Decimal, Scientific, and General. Decimal and Scientific both contain maximum 17 digits and trim zeros… General uses Decimal or Scientific depending on which is shorter" [OFFICIAL: tools/export] — which cannot be indexed by `5` or `6` under any 0- or 1-based reading. Observed: only the two OBJ profiles carry the key, and both are the only profiles with `MvsMeshExportNumberFormatAllowed="-1"` (all others `0`), so OBJ is the format that enables it. The repo's `6` was chosen believing it meant six decimal places, to satisfy Nira's decimal-6 guidance — **that belief is unverified and contradicted by the Help's enum**. [OPEN: question 17] |
| `MvsMeshExportFileTypeSelectionDisplay` | int | `0` | dialog state, inert [INFERRED] |

Dialog controls with **no observed key** because no repo profile ever set them: *Grayscale quality
values*, *Classification export* (`.ply` / `.xyz` / `.las` only), *Generate multi-scan PTX*, *Output
Decimal Precision* (`.ptx`), *Texture maximal side*, *Use pow2 texture size*, *Undistort images* +
the whole Undistortion group, *Export images* + the whole Export Image Settings group, and
*File type* (Binary vs ASCII, `.ply` only). All are documented controls; none of their key names is
printed anywhere. [OFFICIAL: tools/export for the controls] [OPEN: key names — export the dialog
from the GUI with each toggled and diff]

**Per-format profiles in this repo, and exactly what each one asserts:**

| File | Format | Scale | CRS type | Tile | Parts | Materials | Textures | Preset |
|---|---|---|---|---|---|---|---|---|
| `ModelExportParams.xml` | generic (v13) | 100 | 3 | 0 | 0 | — | jpg / 24bppBGR | `Maya + Arnold, Unreal` |
| `ModelExportParamsObj.xml` | OBJ (v0) | 100 | 0 | 0 | 0 | — | jpg / 24bppBGR + a `_Normal_0` layer | `Unreal` |
| `ModelExportParamsOBJ_NiraParts.xml` | OBJ (v0) | **1.0** | 3 | 0 | **1** | — | **png** / 24bppBGR | `Custom` |
| `ModelExportParamsFBX_Parts.xml` | FBX (v13) | **1.0** | 3 | 0 | **1** | **true** | png / 24bppBGR | `Custom` |
| `ModelExportParamsFBX_U1V1.xml` | FBX (v13) | 100 | 0 | **0** | 0 | false | png / **32bppBGRA** | `Maya + Arnold, Unreal` |
| `ModelExportParamsFBX_U1V1_material.xml` | FBX (v13) | 100 | 0 | 0 | 0 | **true** | png / 32bppBGRA + `_Normal_0` | `Maya + Arnold, Unreal` |
| `ModelExportParamsFBX_UV.xml` | FBX (v13) | 100 | 0 | **1** | 0 | false | png / 32bppBGRA | `Maya + Arnold, Unreal` |
| `ModelExportParamsFBX_UDIM.xml` | FBX (v13) | 100 | 0 | **2** | 0 | false | png / 32bppBGRA | `Maya + Arnold, Unreal` |
| `ModelExportParamsFBX_UDIM_material.xml` | FBX (v13) | 100 | 0 | **2** | 0 | **true** | png / 32bppBGRA + `_Normal_0` | `Maya + Arnold, Unreal` |
| `ModelExportParamsGLB.xml` | GLB (v0) | **10** | 0 | — | 0 | — | **jpeg embedded** | `[[Custom]]`, rotation X = `-90.0` |
| `ModelExportParamsPLY_DensePoints.xml` | PLY (v13) | **1.0** | 0 | 0 | 0 | false | **none** (`MvsMeshExportTexturing=0`), **vertex colours on** | `Custom` |

[VERIFIED-by-inspection: 11 files, 2026-08-04]

Complete minimal example — a by-parts OBJ, the shape Nira expects:

```xml
<Configuration>
  <entry key="ModelExportFormatVersion" value="0"/>
  <entry key="MvsMeshExportByParts" value="1"/>
  <entry key="MvsMeshExportTexturing" value="true"/>
  <entry key="MvsMeshExportTexturing_Color8_0" value="true"/>
  <entry key="MvsMeshExportTexImgFormat_Color8_0" value="png"/>
  <entry key="MvsMeshExportTexPixFormat_Color8_0" value="24bppBGR"/>
  <entry key="MvsMeshExportColors" value="false"/>
  <entry key="MvsMeshExportNormals" value="true"/>
  <entry key="MvsMeshExportNumberFormat" value="6"/>
  <entry key="MvsMeshExportInfoFile" value="true"/>
  <entry key="MvsExportScaleX" value="1.0"/>
  <entry key="MvsExportScaleY" value="1.0"/>
  <entry key="MvsExportScaleZ" value="1.0"/>
  <entry key="MvsExportIsGeoreferenced" value="0x1"/>
  <entry key="MvsExportcoordinatesystemtype" value="3"/>
</Configuration>
```

Verified output shape for that profile: **OBJ 4 parts + per-part MTL + `u1_v1` textures +
`.rsInfo`**, and the FBX-parts profile gave 4 parts + textures; ~35–38 s each on a 133-camera
component. [VERIFIED: FINDINGS 2026-07-29 export probe]

**Do not disable the info file.** Without a `.rsInfo`, a re-imported model may be shifted, rotated
and scaled relative to the original model and cameras, and cannot be textured against the same
component. [OFFICIAL: tools/export — "WARNING: If you do not use the info file…"]

### 2.10 Ortho projection: `.rsortho`

| | |
|---|---|
| **Purpose** | Define a rendered orthographic projection: extent, plane, colour source, DTM classification |
| **Producing** | create an ortho projection manually, export it in any format with `exportProjectionParametersFile` = True |
| **Root** | **not** `<Configuration>` — three sibling elements: `<OrthoProjection>`, `<ReconstructionRegion>`, `<DTMParams>` |
| **Consumed by** | `-calculateOrthoProjection <rsorthoFile> [rsboxFile]` |
| **Repo files** | none — no ortho has ever been driven through this CLI |

Structure, reformatted from Epic's single-line example for legibility (element and attribute names
verbatim):

```xml
<OrthoProjection width="10011" height="8076" name="Ortho projection 1"
                 modelName="Model 1" colorType="texturing" boxSideConerIndex="13"
                 bEmpty="0" backFaceColorType="1" backFaceColor="2130706687">
  <Header magic="5787472" version="1"/>
</OrthoProjection>
<ReconstructionRegion globalCoordinateSystem="NONE" globalCoordinateSystemName="NONE"
                      isGeoreferenced="0" isLatLon="0" yawPitchRoll="0 -0 -0">
  <widthHeightDepth>29.8926887512207 29.9313926696777 24.1154346466064</widthHeightDepth>
  <Header magic="5395016" version="2"/>
  <CentreEuclid>
    <centre>-0.098011314868927 0.0846212208271027 12.4095182418823</centre>
  </CentreEuclid>
  <Residual R="1 0 0 0 1 0 0 0 1" t="0 0 0" s="1"/>
</ReconstructionRegion>
<DTMParams classificationLayerId="-1">
  <ClassificationParams modelType="nature" postprocessType="soft_edges" sensitivity="0.5"/>
  <Header magic="1480868688" version="1"/>
</DTMParams>
```

| Attribute | Type / allowed values | Meaning | Tag |
|---|---|---|---|
| `width` / `height` | int | projection raster size in pixels | [OFFICIAL] |
| `name` | string | projection name | [OFFICIAL] |
| `modelName` | string | which model to project | [OFFICIAL] |
| `boxSideConerIndex` *(sic — Epic's typo)* | int 0–23 | which reconstruction-region side is the projected plane and which corner is upper-left. **Not derivable analytically** — it depends on the region's rotation. Obtain it by making one projection manually and exporting its parameters; reuse the number thereafter. | [OFFICIAL] |
| `colorType` | `texturing` \| `coloring` | colour source | [OFFICIAL] |
| `bEmpty` | `0` \| `1` | `0` = render now (the Render button); `1` = add to batch only. **Epic recommends leaving it 0** — for CLI use, `1` means nothing is produced. | [OFFICIAL] |
| `backFaceColorType` | `0` None \| `1` FixedColor | colour inner surfaces differently | [OFFICIAL] |
| `backFaceColor` | packed int | the colour used when type = 1 | [OFFICIAL] |
| `classificationLayerId` | int, `-1` = compute a new classification during rendering | DTM source layer; `-1` **requires** `ClassificationParams` | [OFFICIAL] |
| `modelType` | `industrial_complex` \| `mixed` \| `city` \| `nature` \| `meadows` \| `countryside` \| `mountains` | classification scene type | [OFFICIAL] |
| `postprocessType` | `none` \| `soft_edges` \| `hard_edges` | post-classification cleanup | [OFFICIAL] |
| `sensitivity` | float 0–1 | `0` = everything is "Artificial object"; `1` = everything is "Ground" | [OFFICIAL] |

[OFFICIAL: tools/xmlparamsfiles — the only Help page dedicated to a parameter-file schema]

Note the bootstrap trap: `exportProjectionParametersFile` is an *ortho export dialog* parameter, so
producing a `.rsortho` headless would require an ortho-export `params.xml` you do not have. The
GUI is the practical entry point. [INFERRED]

### 2.11 Reconstruction region: `.rsbox` / `.rcbox`

| | |
|---|---|
| **Purpose** | A reusable, transportable reconstruction region |
| **Producing** | `-exportReconstructionRegion box.rsbox`, or SCENE 3D ▸ TOOLS ▸ Export ▸ Reconstruction Region |
| **Consumed by** | `-setReconstructionRegion box.rsbox`; second argument of `-calculateOrthoProjection` |
| **Format entry** | `sceneobjects.xml`: `mask="*.rsbox;*.rcbox"`, `writer="RealityScan.Export.ReconstructionRegion"`, `requires="component,reconstruction region"` |

The `.rcbox` extension is the legacy name and is still accepted for reading.
[OFFICIAL: install `sceneobjects.xml`; CLAUDE.md naming exception]

The file's content is the `<ReconstructionRegion>` element shown in §2.10 — same attributes,
same `<widthHeightDepth>` / `<CentreEuclid><centre>` / `<Residual R t s>` children, same
`<Header magic="5395016" version="2"/>`. [INFERRED: the `.rsortho` embeds a region produced by
"setting the reconstruction region manually and then exporting it" [OFFICIAL: tools/xmlparamsfiles],
so the standalone export is that element as root. Never round-tripped here.]
[OPEN: `-exportReconstructionRegion` has never been run in this repo; one call on the smoke fixture
settles the root element and whether the `<Header>` is required.]

The writer has **no `<body>` element**, so its content is an integrated format and cannot be
customized through `sceneobjects.xml`. [OFFICIAL: tools/defineexportformat]

### 2.12 Mask export params

| | |
|---|---|
| **Purpose** | Export the project's current mask images |
| **Producing dialog** | Export Mask Images (ALIGNMENT ▸ Process ▸ Mask Images dropdown) |
| **Consumed by** | `-exportMasks <folderPath> <params.xml>` **or** `-exportMasks <params.xml>` |
| **Format entry** | `masklayer.xml`: one format, `id="{83470127-6B66-4D31-B1D3-6B60A97C5705}"`, `mask="*.*"`, `desc="Export Mask Images"`, `writer="RealityScan.Export.MaskLayer"`, `supportsGeoref="0"`, `undistortImages="never"`, `exportImages="never"` |

**The params file is required in both command forms** — this is one of only two families (with
`-exportOrthoProjection`) where the Help words it as required rather than optional:
"Specify the output folder and the full path to the XML file with export parameters."
[OFFICIAL: appbasics/allcommands]

Masks are grayscale: white areas are used in processing, black are excluded. Grayscale values up to
256 shades, or partial transparency, "may interfere with processing and produce inconsistent
results". Masks can be separate grayscale images (e.g. PNG) or ride in the alpha channel of the
originals (e.g. TIFF); they come from the AI Masking tool, the Masking from Mesh tool, or an import
following the image-layer naming convention. Per-image, the mask layer's availability during
alignment, meshing and texturing is set independently in the Selected input panel.
[OFFICIAL: tools/mask]

**No mask has ever been driven through this CLI.** `masking.py` exists at the repo root as a
standalone data-prep script and does not invoke RealityScan; there is no empirical masking result
of any kind here, and a staff caution against over-masking is recorded only second-hand.
[OPEN: nothing in `FINDINGS.md` records a masked run]

### 2.13 Depth / normal / mask maps export params

| | |
|---|---|
| **Purpose** | Export mesh-derived masks (PNG) plus depth and normal maps (EXR) for the selected images |
| **Producing dialog** | button **Maps and Masks** in MESH & COLOR ▸ Export (or SCENE 3D/TOOLS); the dialog itself is titled *Export Depth Maps and Masks* and lets you pick masks-from-mesh, depth maps, or both |
| **Consumed by** | `-exportMapsAndMask <folderName> <params.xml>`; with neither argument, results land beside the originals |
| **Format entry** | `depthnormalmaskimage.xml`: one format, `id="{0ABB46B2-4FAA-4CE1-AA39-D96128D39BD9}"`, `mask="*.*"`, `desc="PNG and EXR"`, `writer="RealityScan.Export.DepthNormalAndMaskImages"`, `supportsGeoref="0"`, `undistortImages="no"`, `exportImages="never"`, `requires="model"` |

The writer has no `<body>` element — content is integrated and not customizable.
[OFFICIAL: tools/defineexportformat, tools/mask] [VERIFIED-by-inspection: installed
`depthnormalmaskimage.xml`, 2026-08-04]

**Writer-name discrepancy.** `tools/defineexportformat` lists the no-`<body>` writer as
`RealityScan.Export.DepthAndMaskImages`; the shipped `depthnormalmaskimage.xml` uses
`RealityScan.Export.DepthNormalAndMaskImages`. The installed spelling is what the application
loads. [CONTRADICTED: Help vs installed file, read 2026-08-04]

The masks produced this way are generated from the mesh exactly as *Masking from Mesh* would, but
are **not added to the project** — they are written straight out alongside the depth maps.
[OFFICIAL: tools/mask]

A stale alias `-exportDepthAndMask` appears only in `tutorials/commandline_3`.
[INFERRED: pre-rename name in a stale tutorial page; prefer `-exportMapsAndMask`.]

### 2.14 LoD and Cesium 3D Tiles export params

| | |
|---|---|
| **Purpose** | Generate and export multiple simplified levels of a model |
| **Producing dialog** | MESH & COLOR ▸ Export ▸ **Level of Detail** — two different dialogs |
| **Consumed by** | `-exportLod <fileName> <params.xml>` (linear), `-export3dTiles <fileName> <params.xml>` (hierarchical) |
| **Format entry** | `lodmesh.xml`: `<LodMesh name="Dense Mesh As a Level-of-Detail Set"><importFormats class="RealityScan.Export.LodMeshProviders"/></LodMesh>` |

Which dialog you get — and therefore which key set the profile carries — depends on the chosen
output format:

| Dialog | Triggered by | Controls (each a profile key) |
|---|---|---|
| **Linear LoD** | obj, ply, xyz, abc, glb, fbx, dxf, dae | *Stopping criterion* (Model Count \| Triangle Count), *Model count*, *Simplification type* (Relative \| Absolute; Absolute only when the criterion is Model Count), *Relative simplification factor*, *Maximal triangles*, *Minimal triangles*, *File suffix* (default `_LODn`) + custom *Suffix*, *Numbering start* (default 0), plus the full *Mesh settings* group identical to the Export Model dialog |
| **Hierarchical LoD** | Cesium 3D Tiles (`.json`) | *Initial simplification* Type (None \| Relative \| Absolute), *Iterative simplification* Type (Relative only), *Export textures* + *Source Layer* + *Texel size* + *Texture Format* (`.webp` \| `.jpg` \| `.png`), *Maximum node triangle count*, *Bandwidth Scale* (<1 faster/lower quality, >1 slower/higher), *Altitude* |

[OFFICIAL: tools/lodexport]

Because the linear dialog embeds the whole model-export settings group, an `-exportLod` profile is
a superset of a `-exportModel` profile. [INFERRED from the Help's "options are identical to those
in the Export Model dialog".] Never exercised here. [OPEN: the actual key names for the LoD-specific
controls are unknown — none appears in the Help; the binary-only `lod*` family is catalogued in
`10-reconstruction-texturing-export.md` §14. Cheapest probe: save the Export LoD dialog from the GUI
once, in each of its two variants, and read the files.]

### 2.15 Registration export params

| | |
|---|---|
| **Purpose** | Export camera registration in one of 18 formats |
| **Producing dialog** | ALIGNMENT ▸ Export ▸ **Registration** — the dialog appears *after* the Save-As |
| **Consumed by** | `-exportRegistration <fileName> <params.xml>`, and shares its dialog with `-exportUndistortedImages` and `-exportSTMap` |
| **Format entry** | `calibration.xml` — **18** `<format>` entries [VERIFIED-by-inspection: element count, 2026-08-04] |

**`-exportRegistration` without a params XML blocks forever headless.** Do not call it until a
GUI-saved profile exists. [VERIFIED: FINDINGS 2026-07-21] This is the single largest gap in this
repo's CLI coverage: the georeferencing-verification hardening cell (U7) has been open since
2026-07-23 partly because its most promising oracle is behind this dialog.

The available target formats, read out of the shipped `calibration.xml` (these are what the
`params.xml`'s format selection can name):

| desc | mask | writer |
|---|---|---|
| Image List | `*.imagelist` | `cvs` |
| Original Images with Image List | `*.imagelist` | `cvs` |
| Undistorted Images with Image List | `*.imagelist` | `cvs` |
| RealityScan Alignment Component | `*.rsalign;*.rcalign` | `rca` |
| RealityScan XMPs with Image List | `*.imagelist` | `RealityScan.Export.XMP` |
| Comma-separated, Name, X/Lon, Y/Lat, Z/Alt | `*.csv` | `cvs`, `requiresGeoref="1"` |
| …+ Omega, Phi, Kappa | `*.csv` | `cvs`, `<body EulerFormat="xyz">` |
| …+ Yaw, Pitch, Roll | `*.csv` | `cvs`, `<body EulerFormat="zyx">` |
| Boujou | `*.txt` | `cvs` |
| Bundler v0.3 | `*.out` | `cvs` |
| Bundler v0.3 (negative Z) | `*.out` | `cvs` |
| CmpMvs _P Matrices | `*.imagelist` | `cvs` |
| COLMAP | `*.txt` | `RealityScan.Export.COLMAP` |
| Internal/External Camera Parameters | `*.csv` | `cvs`, `<body EulerFormat="zyx">` |
| Maya 2013 ASCII Scene | `*.ma` | `cvs`, `<body EulerFormat="zxy">` |
| OpenCV-compliant Internal/External Camera Parameters | `*.csv` | `cvs` |
| Radiance Fields Transformation File | `*.json` | `cvs` |
| ST Maps | `*.*` | `RealityScan.Export.STMaps` |

[VERIFIED-by-inspection: `C:\Program Files\Epic Games\RealityScan_2.2\calibration.xml`, 2026-08-04]

Note the mask on the alignment-component writer: `*.rsalign;*.rcalign` — the legacy extension is
still a first-class accepted mask in 2.2. And note that **four of the eighteen have no `<body>` and
therefore cannot have their content customized**: `rca`, `RealityScan.Export.STMaps`,
`RealityScan.Export.COLMAP` and `RealityScan.Export.XMP`. The other fourteen carry a `<body>`, of
which four declare a rotation convention (`EulerFormat` = `xyz` ×1, `zyx` ×2, `zxy` ×1).
[VERIFIED-by-inspection: `<body>` census over `calibration.xml`, 2026-08-04]

Two attributes appear here that `tools/defineexportformat` does not document:
`undistortPrincipal="1"` (on Boujou and both Bundler formats — presumably the *Undistort principal
point* control) and the `always`/`never`/`yes`/`no`/`0`/`1` value spread on `undistortImages` and
`exportImages` (§3.3). [UNDOCUMENTED: read directly out of the shipped file, 2026-08-04]

Dialog controls that a registration profile carries: File format, File name, Export location,
Export transformation settings, Undistort images + Undistortion settings (Fit, Custom width/height,
Downscale, Image cut-out, Max count of pixels), Export images + Export image settings (Image
format, Pixel format, Naming convention, Customize image path, Image path, Background colour),
plus format-specific extras — *Export image planes* (Maya), *Bounding box scale* (Radiance Fields),
*Exported ST Map Image format* / *Export Image List* / *Export Image List File Name* /
*Export File Naming* (ST Maps). Three formats have **no** settings at all and export straight from
the Save-As: RealityScan Alignment Component, Image list, CmpMvs _P matrices.
[OFFICIAL: tools/exportregistration]

### 2.16 Control-point measurement import/export params

| | |
|---|---|
| **Import command** | `-importControlPointsMeasurements <cpmFile> <params.xml>` |
| **Export command** | `-exportControlPointsMeasurements <cpmFile> <params.xml>` |
| **Import dictionary** | `measurementsimport.xml`, reader `RealityScan.Import.CSVControlPointsMeasurements` |
| **Export dictionary** | `measurementsexport.xml`, writer `RealityScan.Export.ControlPoints`, `requires="cpm"` |
| **Export profile source** | Shift + **Control Points** in ALIGNMENT ▸ Export |

Importable variables: `Image` (name incl. path and extension), `PointName`, `X`, `Y` (pixels from
the image's upper-left corner), `XAccuracy`, `YAccuracy`, `RotationAccuracy` (rotation of the
accuracy region from the X axis, left-handed).
[OFFICIAL: tools/defineimportformat]

Shipped export formats: comma-, space-, tab-separated and space-with-quotes, all
`Image, Point, X, Y` with `$(x:.2f)` precision.
[VERIFIED-by-inspection: `measurementsexport.xml`]

**Looks like a defect, probably is not:** the 5-column import format
`{6E9D6C7D-85EC-43E8-98CD-C13804D6C554}` maps **both** `<XAccuracy index="4"/>` and
`<YAccuracy index="4"/>` to column 4. Its own `desc` is `Image, Point, X, Y, Accuracy
(character-separated)` — **"Accuracy", singular, five columns** — so one value feeding both axes is
consistent with the declared layout rather than a typo for index 5.
[UNDOCUMENTED: read directly out of the shipped `measurementsimport.xml`, 2026-08-04]
[INFERRED from the `desc`; settled by importing a 5-column file and reading both accuracies back —
question 27]

Nothing in this family has ever been driven here. [OPEN: no control point has ever been imported
through this CLI.]

### 2.17 Ground-control-point import/export params

| | |
|---|---|
| **Import command** | `-importGroundControlPoints <gcpFile> <params.xml>` |
| **Export command** | `-exportGroundControlPoints <gcpFile> <params.xml>` |
| **Import dictionary** | `groundcontrol.xml`, reader `RealityScan.Import.CSVGroundControl` — 4 shipped formats |
| **Export dictionary** | `controlpoints.xml`, writer `RealityScan.Export.ControlPoints`, `specificCoordSystem="1"`, `requires="GCP"` — 6 shipped formats |

Importable variables: `Name`, `X`, `Y`, `Longitude`, `Latitude`, `Altitude`, and an accuracy
sibling for each (`XAccuracy`, `YAccuracy`, `LongitudeAccuracy`, `LatitudeAccuracy`,
`AltitudeAccuracy`). [OFFICIAL: tools/defineimportformat]

The four shipped import formats are the X/Y and Y/X orderings, with and without the three accuracy
columns. The six shipped export formats are space/comma/tab × X-first/Y-first.
[VERIFIED-by-inspection]

**Nothing empirical exists here.** `controlpoints.xml` and `groundcontrol.xml` have never been
driven from this pipeline. The one adjacent fact of record is staff-confirmed **absence of
stereo-rig support** in RealityScan through Aug 2025, which implies that rig-derived scale must
come from GCPs, distance constraints, or locked XMP — none of which is exercised here.
[OPEN: no GCP has ever been imported through this CLI] [VERIFIED-second-hand: COLMAP fact base
F-20260723-27]

### 2.18 Distance-definition import params

| | |
|---|---|
| **Command** | `-defineDistance <fileName> <params.xml>` |
| **Dictionary** | `distancedefinitions.xml`, reader `RealityScan.Import.CSVDistanceDefinition` |
| **Producing dialog** | Import Distance Definitions |

Importable variables: `Name`, `PointA`, `PointB`, `Distance`, `DistanceAccuracy`.
[OFFICIAL: tools/defineimportformat]

Note a **spelling discrepancy between the Help and the shipped file**: the Help's sample writes
`reader="RealityScan.Import.CsvDistanceDefinition"` (lowercase `sv`) and instructs "as a reader use
`RealityScan.Import.CsvDistanceDefinition`"; both formats in the installed
`distancedefinitions.xml` write `reader="RealityScan.Import.CSVDistanceDefinition"` (uppercase).
The installed file is what the application actually loads.
[CONTRADICTED: tools/defineimportformat vs the shipped `distancedefinitions.xml`, read 2026-08-04.
Use the installed spelling.]

A second, cosmetic mismatch in the same file: both shipped `desc` strings start with `Image`
(`"Image PointA PointB Distance"`, `"Image PointA PointB Distance Accuracy"`) while the parser's
first variable is `<Name index="0"/>`, and the Help's sample `desc` is the more accurate
`"Name, Point A, Point B, Distance, Accuracy (character-separated)"`. `desc` is display text only,
so this misleads the dialog reader and nothing else — the same class of bug as the hand-added
flight-log format's `desc` (§3.2). [VERIFIED-by-inspection, 2026-08-04]

Two formats ship, `{7A2A52BA-D325-47F8-88A1-C402B4E37EED}` (4 columns) and
`{08192FC0-A5D9-4E99-B993-F274EFA5745F}` (5, with `DistanceAccuracy`). This is the mechanism a
known-length reference bar would use to impose metric scale — directly relevant to this repo's
scale work, and never used. [OPEN]

### 2.19 LiDAR scan import params

| | |
|---|---|
| **Commands** | `-importLaserScan <name> <params.xml>`, `-importLaserScanFolder <folder> <params.xml>` |
| **Producing dialog** | LiDAR Scan Import |
| **Related dictionary** | `noiseprofiles.xml` — per-scanner noise/quality models |

Never used here. The one adjacent key this repo does pin is `lisPreferImagesAsFeatureSource=false`
in `AlignmentParams.xml`, declared a low-priority probe and never run.
[OPEN: wave-3 cell E3, never executed]

`noiseprofiles.xml` is the field dictionary for scanner noise: each `<profile desc=… width=…
height=… quality=…>` carries `<distances>`, `<intensities>`, and a `width×height` grid of
`<noiseFactors>` and `<qualityFactors>`. Two ship: `Noise free` (1×1, all zeros) and
`ScanStationP20` (8×8). To add a scanner, copy the P20 block and replace the two grids.
[VERIFIED-by-inspection: shipped `noiseprofiles.xml`, 2026-08-04]

### 2.20 16-bit / HDR image import params

| | |
|---|---|
| **Command** | `-importHDRimages <file\|folder\|imagelist> <params.xml>` — note the lowercase `i` in `images` |
| **Producing dialog** | 16-bit/HDR Images Import |

Dialog controls the profile carries: *Tone-mapping method* (No tone mapping = a local Windows codec,
straight 16-bit→8-bit with no colour/contrast/gamma adjustment; or **RS tone mapping**, recommended)
and *Output path* for the converted `.geometry.jpg` files (With original files \| Custom).
[OFFICIAL: tools/importhdr]

Two facts worth carrying: the import **automatically adds** the tone-mapped `.geometry.jpg` files
to the open project — do not add them again; and the exported output retains the full 16-bit/HDR
information from the source images despite processing running on the 8-bit conversions.
[OFFICIAL: tools/importhdr]

Never used here. The `.geometry` / `.texture` / `.mask` **Image Layers** mechanism this touches is
the agreed eventual answer to the repo's CLAHE dilemma (align on originals, texture from enhanced)
but has never been exercised through the CLI.
[OPEN: HANDOFF 2026-07-26]

### 2.21 Model import params and `.rsinfo`

| | |
|---|---|
| **Command** | `-importModel <fileName> <params.xml>` |
| **Producing dialog** | Import Model |
| **Related** | `mesh.xml` (`<importFormats class="RealityScan.Export.MeshProviders"/>`) |

The profile carries the import transformation: coordinate system, move/rotate/scale, normal space
and range, normal flips — the `MvsImport*` twins of the export keys.
[UNDOCUMENTED: key names known only from binary strings; see `03-settings-keys.md` §8.6]

**The `.rsinfo` mechanism supersedes the profile for the common case.** If the model was exported
from RealityScan with `MvsMeshExportInfoFile=true`, an info file named `<model>.<ext>.rsInfo`
(e.g. `myObject.obj.rsInfo`) sits beside it; the application searches for it automatically and uses
it to place the model correctly in the internal coordinate system, prefilling every import setting.
Without it, a reimported model may be shifted, rotated and scaled relative to the original.
[OFFICIAL: tools/export, tools/import]

The naming is exact and load-bearing: the info file must be the **model name plus** an additional
`.rsInfo` extension. `myObject.rsInfo` will not be found for `myObject.obj`; `myObject.obj.rsInfo`
will. [OFFICIAL: tools/export]

#### 2.21.1 The `<Model>` tag — the export's placement record

The Help documents the `.rsInfo` only as a re-import convenience. It is more
than that: **it is the sole on-disk record of what coordinate system an export
landed in, and of the transform back to it.** Any consumer outside RealityScan
— a globe renderer, a GIS, a publish script — has nothing else to go on.

A sidecar holds several sibling top-level tags and **no single root element**,
so it is *not* well-formed XML on its own; wrap it before parsing.
`<ModelExport>` (§1.6) is the profile bootstrap. `<Model>` is the placement
record:

```xml
<Model globalCoordinateSystem="+proj=utm +zone=53 +datum=WGS84 +units=m +no_defs"
   globalCoordinateSystemName="epsg:32653 - WGS 84 / UTM zone 53N"
   exportCoordinateSystemType="2">
  <globalCoordinateSystemWkt>PROJCS["WGS_1984_UTM_Zone_53N", …]</globalCoordinateSystemWkt>
  <transformToModel>0 0 1 348355.8364815 1 0 0 396321.994618801 0 1 0 -587.41083970014 0 0 0 1</transformToModel>
  <Header magic="5786959" version="1"/>
</Model>
```

| item | notes |
|---|---|
| `globalCoordinateSystem` | PROJ string. **2D** — says nothing about the vertical (`06-…` §3.5) |
| `globalCoordinateSystemName` | `epsg:NNNNN - <label>`; the practical source of an EPSG code |
| `globalCoordinateSystemWkt` | child **element**, not an attribute |
| `exportCoordinateSystemType` | observed `1` (LAS, identity transform) and `2` (OBJ, local frame). The repo's own presets set `3` (OBJ/FBX) and `0` (PLY) — **neither has ever been seen in a written sidecar** |
| `transformToModel` | 16 numbers. Written as a child **element** on the OBJ sidecar and as an **attribute** on the LAS one — match both forms or read nothing |

**Decoding `transformToModel`.** The 16 values have **no single obvious
reading**, and guessing wrong relocates a mesh by hundreds of kilometres
silently. For `NA168_H2080_20Jan.obj` the correct reading is row-major, applied
as `M @ v`, with the output components then permuted `(1,2,0)` to give
`(E, N, Z)` — which for that file reduces to a pure per-axis translation:

```
E = x + 396321.994618801
N = y - 587.41083970014
Z = z + 348355.8364815
```

Note that the constant added to the *easting* is a northing-magnitude number:
the model frame is genuinely scrambled, so the operands do not "look right"
even when they are. **This is why the reading must be derived and validated,
not assumed.**

How it was settled: all 178,269 vertices were transformed under every
combination of {row-major, column-major} × {`M @ v`, `v @ M`} × all six output
permutations, and scored by the fraction landing inside the envelope of the
dive's own flight log. **Exactly one reading scored 1.0000; every rival scored
0.3333.** [VERIFIED: FINDINGS 2026-08-31]

Two rules for any code that consumes this:

1. **Validate, do not assume.** Score candidate readings against the declared
   CRS's area of use (and a nav envelope when one exists), and fail when zero
   *or more than one* survives.
2. **Reject reflections.** A reading whose composed 3×3 has a negative
   determinant mirrors the geometry. It matters because an East/North swap is
   invisible to a bounds check when easting and northing are of similar
   magnitude — ~348 355 against ~396 318 on this site — but is a reflection,
   and no rigid transform between right-handed frames can produce one.

Reference implementation: `modules/cesium_placement.py::resolve_to_global`.
Consumers: `10-…` §17.2.1, `12-…` `F-88`.

### 2.22 Bundler and COLMAP import params

`-loadBundler <filePath> <params.xml>` and `-loadColmap <filePath> <params.xml>`. The optional
config "defines the scene transformation settings saved from the import dialog" and "can be used to
adjust the coordinate system or apply custom transformations during import". COLMAP takes the path
to any of the three text files. [OFFICIAL: appbasics/allcommands]

Not used here, and `archive/colmap/` is retired — do not resurrect it into the active pipeline.
[CLAUDE.md]

### 2.23 Classification params and the `.cfd` format file

Three distinct XML/binary artifacts, easily confused:

| Artifact | Command | What it is |
|---|---|---|
| Classification **params** | `-dtmClassify <params.xml>`, `-transferClassification <params.xml>` | a run-time profile from the AI Classify tool panel |
| Classification **settings** | `-exportClassificationSettings <XMLfilePath>` / `-importClassificationSettings <XMLfilePath>` | the panel's state, **exportable from the CLI** — the only tool profile with a CLI producer |
| Classification **format** (`.cfd`) | `-exportClassificationFormat <name> <filePath>`, `-exportSelectedClassificationFormat <filePath>`, `-importClassificationFormat <filePath>` | the class-list definition, not a settings profile |

[OFFICIAL: appbasics/allcommands]

The same classification parameters appear inline in a `.rsortho`'s `<DTMParams>` block (§2.10) —
`classificationLayerId`, `modelType`, `postprocessType`, `sensitivity` — which is the only place
Epic documents their allowed values.

### 2.24 Sparse point cloud, cross-sections, contours, shapes

| Command | Profile from | Dictionary | Notes |
|---|---|---|---|
| `-exportSparsePointCloud <file> <params.xml>` | Export Point Cloud dialog | `structure.xml` | 5 shipped formats: `.xyz`, `.xyzrgb`, XYZ with a *Export vertex colors* parameter, Wavefront `.obj`, and `.ply` with *Export vertex colors* + *Export ascii* parameters. All `writer="cvs"` with a `<body>` — **fully customizable**. |
| `-exportCrossSections <file> <params.xml>` | Export Cross Sections | `modelcrosssections.xml` | `.dxf` and `.shp`, writer `RealityScan.Export.ModelCrossSections`, `requires="model,crosssections"` — `<body>` present but empty, so content is integrated |
| `-computeContours <params.xml>` | Contours tool | — | computes on the selected ortho |
| `-exportContours <file> <params.xml>` | Export Contours | `isolines.xml` (root `<OrthoIsolines>`) | `.dxf` and `.shp`, writer `RealityScan.Export.Isolines`, `requires="projection,isolines"` — `<body>` present but empty, same as cross sections |
| `-exportShapes <file> <params.xml>` | Export Shapes | **none in the install tree** | `.json` only, per the Help's parameter text |

[VERIFIED-by-inspection: shipped `structure.xml`, `modelcrosssections.xml`, `isolines.xml`,
2026-08-04] [OFFICIAL: appbasics/allcommands]

`structure.xml` is the best worked example of a customizable export in the whole install tree and
is the file to read first when learning the templating system — see §3.3.

### 2.25 Snapshot and custom-render params

| Command | Profile role |
|---|---|
| `-exportCameraSnapshots <folder> <params.xml>` | render the model from every (or the selected) camera position |
| `-exportSelectedCamerasSnapshots <folder> <fileFormat> <params.xml>` | same, selected cameras only, explicit image format |
| `-renderMeshFromCustomPositionYPR <file> <params.xml>` | **the profile replaces nine positional arguments**: `width height focalLength x y z yaw pitch roll` |
| `-renderMeshFromCustomPositionLookAt <file> <params.xml>` | replaces `width height focalLength x y z atX atY atZ [upX upY upZ]` |
| `-renderMeshFromCustomGridPositionYPR <file> <params.xml>` | grid-space variant |
| `-renderMeshFromCustomGridPositionLookAt <file> <params.xml>` | grid-space variant |

[OFFICIAL: appbasics/allcommands]

The render commands are the only family where a profile is an *alternative syntax* rather than a
settings supplement. The positional form is documented with a working example and needs no XML:

```bat
:: Epic's own example, verbatim, incl. its forward slashes (cmd accepts them here)
RealityScan.exe -renderMeshFromCustomPositionYPR "D:/Project/render.png" 1280 720 100 0 0 150 0 0 0

:: LookAt form: the last three values (up vector) are optional
RealityScan.exe -renderMeshFromCustomPositionLookAt "D:/Project/render.png" 1280 720 50 0 -100 0 0 0 10 0 0 1
```

Both examples are [OFFICIAL: appbasics/allcommands] — the first renders a 1280×720 view from above
a model at the origin in local Euclidean space, the second a side view with the vertical axis
pinned to +Z.

`camerassnapshots.xml` is the dictionary: one format, `writer="RealityScan.Export.CamerasSnapshots"`,
`requires="model"`, hint "Render an image of the selected model for each of the selected cameras.
(If no cameras are selected, then all cameras in that component are used.)"
[VERIFIED-by-inspection]

### 2.26 Whole-application settings: `.rcconfig`

`-exportGlobalSettings <settings.rcconfig>` and `-importGlobalSettings <settings.rcconfig>` move
the entire application-global settings state as one file. This is not a per-operation profile and
is not passed to any other command.

**The Help contradicts itself on the extension**: `.rcconfig` in `appbasics/allcommands` and
`appbasics/appsettings`, `.rsconfig` in `tutorials/commandline_4`. The GUI's Global Settings panel
says `.rcconfig`. [CONTRADICTED-internal; trust `.rcconfig`, and settle it by running the export
and reading the produced name.]

`-exportGlobalSettings` is the **cheapest known oracle for "did my setting actually take"**: export,
apply, export again, diff. Never exercised in this repo. [OPEN]

Related: `-reset ui|cfg|cfgui|all` resets the interface, the settings, both, or restores a
clean-install state — but **only from a batch file, never through delegation**.
[OFFICIAL: appbasics/allcommands]

---

## 3. The install-tree format dictionaries

### 3.1 Complete inventory

Everything at `C:\Program Files\Epic Games\RealityScan_2.2\*.xml`. These are the authoritative
field dictionaries: they define which readers and writers exist, what columns each import format
maps, and what text each customizable export emits. Editing one changes what appears in the
application's dialogs and what a `params.xml` can name.

| File | Bytes | Root | Governs | Customizable? |
|---|---|---|---|---|
| `flightlogs.xml` | 9,413 | `<FlightLogs>` | trajectory/flight-log import column mapping — **14 formats** incl. one hand-added here | Yes (reader `RealityScan.Import.CSVFlightLog`) |
| `groundcontrol.xml` | 2,366 | `<GroundControl>` | GCP import column mapping — 4 formats | Yes (`RealityScan.Import.CSVGroundControl`) |
| `measurementsimport.xml` | 1,087 | `<ControlPointsMeasurements>` | control-point measurement import — 2 formats | Yes (`RealityScan.Import.CSVControlPointsMeasurements`) |
| `distancedefinitions.xml` | 981 | `<DistanceDefinitions>` | distance-constraint import — 2 formats | Yes (`RealityScan.Import.CSVDistanceDefinition`) |
| `calibration.xml` | 12,274 | `<Calibration>` | **registration export** — **18** formats, incl. `.rsalign`, XMP, COLMAP, Bundler, Boujou, Maya, OpenCV, Radiance Fields, ST Maps | Partly — 14 of 18 carry a `<body>` |
| `controlpoints.xml` | 1,980 | `<ControlPoints>` | GCP **export** — 6 formats | Yes (`RealityScan.Export.ControlPoints`) |
| `measurementsexport.xml` | 1,448 | `<ControlPointsMeasurements>` | control-point measurement **export** — 4 formats | Yes |
| `structure.xml` | 2,933 | `<Structure>` | sparse point cloud export — 5 formats incl. binary PLY | Yes — the best `<body>` example in the tree |
| `mesh.xml` | 117 | `<Mesh>` | dense mesh + texture export; delegates to `RealityScan.Export.MeshProviders` | No |
| `lodmesh.xml` | 132 | `<LodMesh>` | LoD set export; delegates to `RealityScan.Export.LodMeshProviders` | No |
| `sceneobjects.xml` | 415 | `<SceneObjects>` | reconstruction region `*.rsbox;*.rcbox` | No (integrated writer) |
| `depthnormalmaskimage.xml` | 355 | `<DepthNormalMask>` | depth/normal/mask images (PNG + EXR) | No |
| `masklayer.xml` | 289 | `<MaskLayer>` | mask image export | No |
| `camerassnapshots.xml` | 464 | `<CamerasSnapshots>` | per-camera model renders | No |
| `ortho.xml` | 913 | `<Ortho>` | ortho projection / DSM / DTM export, all `*.tiff` | No |
| `isolines.xml` | 665 | `<OrthoIsolines>` | contours `.dxf` / `.shp` | No |
| `modelcrosssections.xml` | 721 | `<ModelCrossSections>` | cross sections `.dxf` / `.shp` | No |
| `oneexport.xml` | 437 | *(multiple roots)* | the export dialog's aggregate: a `<Recent>` element plus `<include file="…"/>` of 11 other dictionaries | — |
| `report.xml` | 2,951 | `<Report>` | 8 HTML report templates via `RealityScan.Export.ReportWriter` | Yes (all function sets) |
| `reportmapwizardmodel.xml` | 1,687 | `<Report>` | Map Wizard report templates | Yes |
| `share.xml` | 965 | `<Share>` | upload targets: SketchFab, Cesium ion, Nira | No |
| `epsg.xml` | 4,720,220 | `<CoordinateSystems authority="epsg">` | **6,756** coordinate systems, each with `paramsWKT` and PROJ `params` | — reference data |
| `local.xml` | 234 | `<CoordinateSystems authority="Local">` | 2 local systems: `id="1"` Euclidean, `id="2"` Laboratory (mm) | — reference data |
| `transformdb.xml` | 1,960 | `<transforms>` | 24 export transform presets: {Blender, 3ds Max, Maya, Maya + Arnold, Unity, Unreal} × {generic, obj, fbx, abc} | — reference data |
| `sensorsdb.xml` | 47,925 | `<cameras>` | **785** camera models with `ccdWidth` and optional `GPSMode` | — reference data |
| `noiseprofiles.xml` | 1,533 | `<NoiseProfiles>` | LiDAR noise/quality models | Yes, by copying a profile block |
| `mapproviders.xml` | 2,290 | `<MapProviders>` | tile-server URLs for the map view | — |
| `languages.xml` / `languagesMY.xml` | 1,639 / 7,731 | — | localization | — |

[VERIFIED-by-inspection: directory listing + reads, 2026-08-04]

Two of these have direct, recorded relevance here:

- **`epsg.xml` and `local.xml` are the databases `-setProjectCoordinateSystem authority:id` and
  `-setOutputCoordinateSystem authority:id` resolve against.** `epsg:32653` is a row in
  `epsg.xml`; `Local:1` is a row in `local.xml`. [OFFICIAL: appbasics/allcommands]
- **`sensorsdb.xml` is unusable for this rig.** Its entries are keyed to model strings that cannot
  match the WCA cameras' EXIF, and it cannot distinguish two cameras with identical EXIF anyway —
  which is exactly this rig's situation (both cameras report Make `Z CAM`, Model `E2-F6`, with no
  focal length and no lens tag). Per-image XMP `Camera:CalibrationGroup` sidecars are the only
  mechanism that separates them. [VERIFIED-by-inspection: docs/settings-evaluation-2026-07 §1,
  2026-07-23]
- **`transformdb.xml` is what `MvsExportTransformationPreset` names must match.** It holds 24
  `<transform>` rows — {Blender, 3ds Max, Maya, Maya + Arnold, Unity, Unreal} × four format groups
  (`!obj,!fbx,!abc` = generic, then `obj`, `fbx`, `abc`) — each optionally carrying `normalFlip`,
  `rotation` and `scale`. In the **generic** group `Maya + Arnold` and `Unreal` are byte-identical
  (`normalFlip="0 1 0" scale="100 100 100"`) and are the only such pair, which is exactly the
  comma-joined label the GUI wrote into every scale-100 profile here. (In the `fbx` group four rows
  collapse to `normalFlip="0 1 0"` with no scale, so the label did **not** come from that group.)
  [VERIFIED-by-inspection: `transformdb.xml`, 2026-08-04] [INFERRED: the preset merely *applies*
  Scene/Normal transformation values, so the explicit `MvsExportScale*` / `Rotation*` /
  `NormalFlip*` entries in a profile are what the exporter uses and the label is descriptive]

### 3.2 Import dictionary schema

Epic's skeleton, verbatim in structure (`separator` is documented as an attribute but is absent
from the skeleton and from every shipped format, which all rely on `allowedSeparators`):

```xml
<format id="{GUID}" descID="" desc="Text Displayed in the Import Dialog" reader="">
  <parser allowedSeparators="" comment="" showIgnoreFirstline="" qualifiers="">
    <Variable index="" format=""/>
  </parser>
</format>
```

| Attribute | Meaning |
|---|---|
| `id` (optional) | unique GUID — **this is what `gpsLogFileFormat` in a params profile names** |
| `descID` (optional) | internal id for localization |
| `desc` | the name shown in the import dialog |
| `reader` | the file reader; Epic's advice is to reuse the reader of an existing format |
| `separator` | the delimiters actually used |
| `allowedSeparators` | delimiters offered in the dialog; auto-detected from the file or chosen manually. If unset, `separator` is used |
| `comment` | comment-introducing symbols; text after one is ignored |
| `showIgnoreFirstline` | `true`/`false` — show the "ignore first line" option |
| `qualifiers` | symbols that may wrap values, e.g. double quotes; useful when values contain the separator. **The Help's bullet spells this `qualifier` (singular)** while the Help's own samples and every shipped file write `qualifiers`. Use `qualifiers`. [CONTRADICTED: tools/defineimportformat prose vs its own samples and the installed dictionaries, 2026-08-04] |
| `<Variable index format>` | one element per column. `index` is 0-based and may skip columns. `format` is `value` (exact number), `degrees` (e.g. `N65 23 12.1`), `name` (string), or `name.ext` (file path incl. extension) |

[OFFICIAL: tools/defineimportformat]

The Help gives the install path as `C:\Program Files\Epic Games\RealityScan`; the 2.2 installer
actually writes `C:\Program Files\Epic Games\RealityScan_2.2`. [CONTRADICTED: Help vs disk]

The element **name** is the variable; the available names depend on the reader. Flight-log readers
accept the widest set: `Image`, `X`/`Y`/`Longitude`/`Latitude`/`Altitude` and an `*Accuracy` for
each, `Yaw`/`Pitch`/`Roll` + accuracies, `Omega`/`Phi`/`Kappa` + accuracies (georeferenced scenes
only), and full prior calibration — `FocalLength`, `PrincipalU`, `PrincipalV`, `Skew`,
`AspectRatio`, `RadialDistortion1`–`4`, `TangentialDistortion1`–`2`.
[OFFICIAL: tools/defineimportformat]

**The Help states the rotation axes explicitly, and they are not the intuitive ones:** "Yaw — prior
yaw rotation (**around Y-axis**)", "Pitch — … (**around X-axis**)", "Roll — … (**around Z-axis**)".
Anything composing YPR for a flight log must match that, and the *order* in which the three are
applied is a separate, unpinned import setting (§2.2).
[OFFICIAL: tools/defineimportformat]

That last group is significant and unexploited here: **a flight log can carry per-image intrinsics
and distortion coefficients**, which is a second route to the per-camera calibration priors this
repo currently delivers only through XMP sidecars. [OPEN: never tried.]

The hand-added 13-column format in this installation, verbatim, as a worked authoring example:

```xml
<format id="{B438A617-2434-5A24-C1B7-58980F28345A}" descID="2345"
        desc="Name,X (East), Y (North), Altitude, XAccuracy, YAccuracy, AltitudeAccuracy, YawAccuracy, PitchAccuracy, RollAccuracy"
        reader="RealityScan.Import.CSVFlightLog">
    <parser allowedSeparators=",; &tab;" comment="#" showIgnoreFirstline="true" qualifiers="&quot;optional">
        <Image index="0" format="name.ext"/>
        <X index="1" format="value"/>
        <Y index="2" format="value"/>
        <Altitude index="3" format="value"/>
        <XAccuracy index="4" format="value"/>
        <YAccuracy index="5" format="value"/>
        <AltitudeAccuracy index="6" format="value"/>
        <Yaw index="7" format="value"/>
        <Pitch index="8" format="value"/>
        <Roll index="9" format="value"/>
        <YawAccuracy index="10" format="value"/>
        <PitchAccuracy index="11" format="value"/>
        <RollAccuracy index="12" format="value"/>
    </parser>
</format>
```

[VERIFIED-by-inspection: installed `flightlogs.xml`, hand-merged 2026-07-25]

Note that its `desc` is **wrong** — it omits Yaw, Pitch and Roll from the human-readable column
list even though the parser maps them at 7/8/9. `desc` is display text only, so this is cosmetic, but it
would mislead anyone reading the dialog. [VERIFIED-by-inspection, 2026-08-04]

Two attribute-value gotchas that look like errors and are not:

- `allowedSeparators=",; &tab;"` — comma, semicolon, **space**, tab. `&tab;` is a RealityScan
  extension, not a standard XML entity (§3.6).
- `qualifiers="&quot;optional"` — a double quote followed by the literal word `optional`, i.e.
  "the `"` qualifier is optional". It is not a malformed attribute.

### 3.3 Export dictionary schema

```xml
<format id="" mask="" descID="" desc="" writer=""
        requiresGeoref="" requiresEqualResolution="" undistortImages=""
        exportImages="" supportsGeoref="" specificCoordSystem="" requires="">
  <parameter name="" type="" default="" variable="" hint=""/>
  <body> … </body>
</format>
```

| Attribute | Meaning |
|---|---|
| `mask` | file extension filter, e.g. `*.xyz`; multiple allowed, `;`-separated (`*.rsbox;*.rcbox`) |
| `desc` / `descID` | dialog label / localization id |
| `writer` | determines the usable parameters and whether `<body>` is honoured (§3.4) |
| `requiresGeoref` | `1` = only offered for georeferenced components |
| `requiresEqualResolution` | `1` = enable custom image width/height in Undistortion settings |
| `undistortImages` | documented as `always` / `never` — show Undistortion settings. **Shipped values across the tree: `always` ×6, `never` ×7, `no` ×2, `0` ×2, `1` ×1, `yes` ×1** [VERIFIED-by-inspection, 2026-08-04] |
| `exportImages` | documented as "set it to `1` to enable". **Shipped values: `never` ×8, `1` ×5, `always` ×2, `0` ×2, `yes` ×1** [VERIFIED-by-inspection, 2026-08-04] |
| `undistortPrincipal` | **not documented.** `="1"` on Boujou and both Bundler formats in `calibration.xml`; presumably the *Undistort principal point* control [UNDOCUMENTED] |
| `supportsGeoref` | `1` = show transformation settings |
| `specificCoordSystem` | `1` = allow setting the coordinate system to project output |
| `requires` | what must exist and be selected: `component`, `model`, `GCP`, `cpm`, `projection`, `dtm`, `crosssections`, `isolines`, `georeferenced` — comma-separated |
| `<parameter>` | a user-editable field in the export dialog: `name` (label), `type` (`bool`, `integer`, `float`, `value`), `default`, `variable` (**the name it gets in the params.xml and inside `<body>`**), `hint` (tooltip) |
| `<body>` | the emitted file content, via the templating system |

[OFFICIAL: tools/defineexportformat — note that page's own skeleton is malformed, closing
`<parameter …/>` a second time with a stray `</parameter>`; the shipped files use the self-closing
form only.]

**The Help contradicts itself about what "customizable" means.** Its opening sentence lists the
customizable exports as "registration, ground control points, control points, point cloud, ortho
photo, cross sections, contours, depth and mask images, reconstruction region, reports, and Map
Wizard reports" — but four of those (ortho photo, cross sections, contours, depth and mask images,
reconstruction region) use writers the same page lists as having **no `<body>`**. Resolution:
the `<format>` *entry* is always editable (its `desc`, `mask`, `requires`, `<parameter>` set), so
you can add or relabel an entry; the file *content* those writers emit is integrated and cannot be
changed. [CONTRADICTED-internal: tools/defineexportformat intro vs its own writer list]
[INFERRED: the reconciliation]

**`<parameter variable="…">` is the bridge between a dictionary and a profile**: the variable name
declared here is the key that appears in the exported `params.xml`. That is how a custom export
format gets custom settings that survive into CLI use. [OFFICIAL: tools/defineexportformat —
"the name of the parameter that can be used as a variable in the body element will be shown in the
parameters file (params.xml)"]

Worked example from the shipped `structure.xml`, showing parameter → body wiring:

```xml
<format id="{43C3A779-C8F1-4B68-95B8-4492DD736796}" mask="*.xyz"
        desc="Sparse point cloud as XYZ Point Cloud (*.xyz)" writer="cvs"
        undistortImages="never" exportImages="never" requires="component">
  <parameter name="Export vertex colors" type="bool" default="true" variable="bVertexColor" />
  <body>$If( bVertexColor, $ExportPoints($(x:f) $(y:f) $(z:f) $(r) $(g) $(b)
))$If( !bVertexColor, $ExportPoints($(x:f) $(y:f) $(z:f)
))</body>
</format>
```

Templating primitives visible across the shipped dictionaries:
`$ExportPoints(…)`, `$ExportPointsEx(…)`, `$ExportCameras(…)`, `$ExportTrack(…)`,
`$ExportControlPoints(…)`, `$ExportControlPointsMeasurements(…)`, `$If(cond, …)`, `$Ifdef(…)`,
`$Include("Reports\Overview.html")`, `$WriteFile("global://…", …)`, `$EscapeBackslashes(…)`,
`$Mat44Inv(…)`, `$Strip(1)`, `$[a]` / `$[b]` (ASCII / binary mode switches), and `$(expr:fmt)`
substitution with format suffixes `:f`, `:g`, `:.8`, `:.2f`, `:d`, `:bf` (binary float),
`:bc` (binary char). Arithmetic inside `$( )` is real: `$(f*scale)`, `$(px*scale+width*0.5)`,
`$(r/255)`, `$(ATan(width /(f*scale*2))*2)`.
[VERIFIED-by-inspection: `structure.xml`, `calibration.xml`, `controlpoints.xml`, `report.xml`,
2026-08-04]

A `<body EulerFormat="…">` attribute selects the rotation convention for the angle variables inside
that body: `xyz` for omega/phi/kappa, `zyx` for yaw/pitch/roll, `zxy` for the Maya export.
[VERIFIED-by-inspection: `calibration.xml`]

### 3.4 The writer attribute — which formats are customizable

Only formats with a `<body>` can have their content customized, and not every writer supports one.

**Writers without `<body>` — integrated formats, content not changeable:**
`rca` (RealityScan Alignment Component `.rsalign`), `RealityScan.Export.STMaps`,
`RealityScan.Export.OrthoExport` (ortho, DSM, DTM), `RealityScan.Export.ModelCrossSections`,
`RealityScan.Export.DepthAndMaskImages`, `RealityScan.Export.Isolines`,
`RealityScan.Export.ReconstructionRegion`.
[OFFICIAL: tools/defineexportformat] — but see the two spelling notes below: the fifth of those
does not exist under that name on disk.

**Writers with `<body>` and their available function sets:**

| Writer, as the Help spells it | Writer, as the shipped files spell it | Function sets |
|---|---|---|
| `csv` | **`cvs`** — 19 occurrences, no `csv` anywhere | `BasicExportFunctionSet`, `ConfigExportFunctionSet`, `SfmExportFunctionSet` |
| `RealityScan.Export.ControlPoints` | same — 10 occurrences | the above plus `ControlPointsExportFunctionSet` |
| `RealityScan.Export.ReportWriter` | same — 13 occurrences | all function sets |

Function-set assignment [OFFICIAL: tools/defineexportformat].

**Two writer-name contradictions, both resolved in favour of the installed file:**

| Help spells it | Shipped files spell it | Where |
|---|---|---|
| `csv` | **`cvs`** | `structure.xml`, `calibration.xml`, `controlpoints.xml`, `measurementsexport.xml` |
| `RealityScan.Export.DepthAndMaskImages` | **`RealityScan.Export.DepthNormalAndMaskImages`** | `depthnormalmaskimage.xml` |

[CONTRADICTED: tools/defineexportformat vs a `writer="…"` census over every `*.xml` in the install
root, 2026-08-04.] Writing `writer="csv"` into a dictionary would not match any writer the
application knows. The transposition is Epic's, not this document's.

Additional writers present in the shipped tree but not listed on the Help page (occurrence counts
from the same census): `RealityScan.Export.XMP` ×1, `RealityScan.Export.COLMAP` ×1,
`RealityScan.Export.MaskLayer` ×1, `RealityScan.Export.DepthNormalAndMaskImages` ×1,
`RealityScan.Export.CamerasSnapshots` ×1, `RealityScan.Export.SketchFabUploader` ×1,
`RealityScan.Export.CesiumIonUploader` ×1, `RealityScan.Export.NiraUploader` ×1, plus the two
provider classes `RealityScan.Export.MeshProviders` / `RealityScan.Export.LodMeshProviders` (which
appear as `<importFormats class="…"/>`, not as `writer` values).
[VERIFIED-by-inspection, 2026-08-04] — none of the eight carries a `<body>`, so all are integrated.
[VERIFIED-by-inspection for the absence of `<body>`; [INFERRED] that absence means the same thing
here as for the Help's listed writers]

### 3.5 How to read a dictionary to discover legal values

The procedure, in order, when you need to know what a field will accept:

1. **Find the dictionary by what the operation imports or exports.** Import → the file named after
   the data (`flightlogs.xml`, `groundcontrol.xml`, `measurementsimport.xml`,
   `distancedefinitions.xml`); these four are *not* aggregated anywhere. Export →
   **`oneexport.xml` is the index**: it `<include>`s exactly eleven dictionaries, in this order —
   `calibration.xml`, `controlpoints.xml`, `measurementsexport.xml`, `structure.xml`, `mesh.xml`,
   `lodmesh.xml`, `sceneobjects.xml`, `depthnormalmaskimage.xml`, `ortho.xml`, `isolines.xml`,
   `modelcrosssections.xml`. Not included, and therefore not part of the unified export dialog:
   `masklayer.xml`, `camerassnapshots.xml`, `share.xml`, `report.xml`, `reportmapwizardmodel.xml`.
   [VERIFIED-by-inspection: `oneexport.xml`, 2026-08-04]
2. **Enumerate `<format id>` entries.** Each is one dialog entry. The `id` GUID is what a profile
   references — e.g. `FlightLogParams.xml`'s `gpsLogFileFormat` value must be one of the fourteen
   `<format id>` GUIDs in `flightlogs.xml`, or the format silently does not exist and columns are
   dropped without complaint (this happened here for four months, §2.2).
3. **For an import, read the `<parser>` children.** The element names are the legal variables, the
   `index` values are the column mapping, and `format` is the type. The Help's per-reader variable
   lists (tools/defineimportformat) are the superset you may add from.
4. **For an export, read `<parameter variable="…">`.** Those variable names are the profile keys the
   export dialog will write; anything else in a params file for that format came from the shared
   settings namespace.
5. **For enum-valued settings, the dictionary does not help** — enums live in the Help's
   `tutorials/setkeyvaluetable` table and in `03-settings-keys.md`. Read those, not the dictionary.
6. **For coordinate systems, grep `epsg.xml`.** `<cs id="32757" desc="WGS 84 / UTM zone 57S" …
   params="+proj=utm +zone=57 +south …"/>` gives both the `authority:id` for
   `-setProjectCoordinateSystem` and the exact PROJ string a flight-log profile needs. This is how
   `write_flight_log_params` composes its two CRS entries.

### 3.6 The dictionaries are not well-formed XML

Do not open one with a conformant XML parser expecting success. Probe result, `System.Xml.XmlDocument`
`.Load()` on 2026-08-04:

| File | Result |
|---|---|
| `flightlogs.xml` | **FAIL** — `Reference to undeclared entity 'tab'. Line 4, position 40.` |
| `groundcontrol.xml` | **FAIL** — same |
| `measurementsimport.xml` | **FAIL** — same |
| `distancedefinitions.xml` | **FAIL** — same |
| `oneexport.xml` | **FAIL** — `There are multiple root elements. Line 3, position 2.` |
| `structure.xml`, `calibration.xml`, `report.xml`, `local.xml`, `transformdb.xml`, `sceneobjects.xml`, `masklayer.xml`, `ortho.xml`, `noiseprofiles.xml` | OK |

[VERIFIED-by-probe, 2026-08-04]

Two independent causes:

- **`&tab;` is a RealityScan-specific entity** with no DTD declaring it. Every dictionary whose
  `allowedSeparators` includes a tab is unparseable by a standard parser.
- **`oneexport.xml` has multiple root elements** — a `<Recent>` element followed by eleven sibling
  `<include file="…"/>` elements. It is an include manifest, not a document.

Consequences for automation: **use text/regex editing on install-tree dictionaries, not a
DOM round-trip.** A conformant parser will either refuse the file or, if you strip `&tab;` to make
it load, silently rewrite it on save and change what the application sees. The repository's own
2026-07-25 merge of the 13-column format into `flightlogs.xml` was a text insertion for this reason.

By contrast, **all 34 `<Configuration>` profiles in `RS_CLI/Metadata/` and all three Epic-authored
profiles parse cleanly** — DOM editing of a profile is safe. [VERIFIED-by-probe, 2026-08-04]

### 3.7 Editing an install-tree dictionary

Editing one of these files is editing an Epic-shipped file inside `C:\Program Files`. It requires
administrator rights, it is invisible to version control, and **it is lost or reverted by an
application update**. This repository has done it exactly once — adding the 13-column flight-log
format on 2026-07-25 — and that change is a standing re-verification item after any RealityScan
update. [VERIFIED: PRIORS_DISTORTION_TEST_PLAN, 2026-07-25] [OPEN: whether the hand-merged format
survives an app update.]

Rules:

1. **Back up the original file first**, outside `Program Files`, and record its byte size and hash
   in the run's environment snapshot.
2. **Keep a copy in the repository.** This repo keeps `flightlogs.xml` and `sensorsdb.xml` at its
   root for exactly this reason. Diff repo copy vs installed copy at session start.
3. **Never renumber or reuse an existing `id` GUID.** A profile that names it will bind to the
   wrong parser. Generate a fresh GUID for a new format.
4. **Copy an adjacent `<format>` block wholesale and edit it.** Reusing an existing `reader` is
   Epic's own advice, and it guarantees the parser exists.
5. **Preserve `&tab;` and `&quot;optional`** verbatim; do not "fix" them.
6. **Verify by round-trip, not by inspection**: after the edit, import a small file that exercises
   the new columns and read the imported values back out of the pose XMPs. A format the app does
   not have is not an error — it is silently dropped columns.

---

## 4. This repository's 34 profiles

All at `C:\Users\jonat\Desktop\CoyoteThings\RealityScan_CLI\modules\realityscan_interface\RS_CLI\Metadata\`.
`SetVariables.bat` declares path variables for many of them; the *consuming* script is what matters
and is listed below.

### 4.1 Inventory with purpose and delta-from-default

| File | Type | Consumed by | What it sets / changes | Status |
|---|---|---|---|---|
| `AlignmentParams.xml` | alignment | `AlignZone.bat`, `GrowZone.bat`, `AlignImagesFromFolder.bat`, 3 probe scripts (parsed → `-set`, never passed as an argument) | the full 39-entry production alignment config, §2.1 | **Production** |
| `FlightLogParams.xml` | trajectory import | `-importFlightLog` at 6 `.bat` call sites — `AlignZone.bat`:77, `GrowZone.bat`:182, `AlignImagesFromFolder.bat`:137, `AlignImageList.bat`:47, `SequentialAlignGrow.bat`:64, `MergeZoneComponents.bat`:154; path supplied by `modules/flight_logs.py`, `merge_zones.py`, `realityscan_interface.py` | 13-column format GUID + per-cruise UTM CRS | **Production, generated** |
| `XMPExportParams.xml` | XMP export | **nothing** | would enable merge / GPS / flags / calib-groups / rig, `xmpCamera=3` | **Unreferenced** |
| `SimplifyNoise_Params.xml` | simplify | `GenerateModel.bat` step [6/8] | relative 70 %, `simplPreserveParts=2`, `simplEqualizeDensity=true` | **Production** — but a documented placeholder derived from the 50 % template |
| `SimplifySmooth_80per_Params.xml` | simplify | `GenerateModel.bat` step [7/8], run 4× | relative 80 %, otherwise identical | **Production** — same placeholder caveat |
| `Simplify50Per_Params.xml` | simplify | declared in `SetVariables.bat` only | relative 50 % | Unused |
| `SimplifyAutomationParams.xml` | simplify | `AlignImagesFromFolder.bat` (**deprecated** workflow) | relative 70 % — same values as `SimplifyNoise`, different entry order | Legacy |
| `Simplify500k_Params.xml` | simplify | declared in `SetVariables.bat` only | **absolute** 500,000 triangles (`mvsFltSimplificationType=0`) | Unused |
| `Simplify25per_Params.xml` | simplify | **nothing** | **byte-identical to `Simplify500k_Params.xml`** — absolute 500 k, not 25 % | **Misnamed, unreferenced** |
| `Smoothing_02_2_Params.xml` | smoothing | declared in `SetVariables.bat` only | weight 0.2, 2 iterations, style 1, type 0 | Unused |
| `SmoothingSurface_02_2_Params.xml` | smoothing | **nothing** | **byte-identical to `Smoothing_02_2_Params.xml`** | Unused duplicate |
| `SmoothingPeaks_05_5_Params.xml` | smoothing | **nothing** | weight 0.5, 5 iterations, style 3 — i.e. Epic's shipped default minus `mvsSmoothing_useIntelligentSmoothing`, with `mvsFltSmoothingType` 1→0 | Unused |
| `Texturing_MaxTextureCount4_16k.xml` | texturing | `GenerateModel.bat` step [6/8] | **4 × 16K adaptive** — the production texture budget | **Production** |
| `Texturing_MaxTextureCount1_16k.xml` | texturing | `SetVariables.bat` only | 1 × 16K | Unused |
| `Texturing_MaxTextureCount1_8k.xml` | texturing | `SetVariables.bat` only | 1 × 8K | Unused |
| `Texturing_MaxTextureCount4_8k.xml` | texturing | `SetVariables.bat` only | 4 × 8K | Unused |
| `Texturing_HighPolyTexture.xml` | texturing | `AlignImagesFromFolder.bat` (deprecated) | 2 × 16K | Legacy |
| `Texturing_SimplifiedTexture.xml` | texturing | `AlignImagesFromFolder.bat` (deprecated) | **byte-identical to `Texturing_HighPolyTexture.xml`** | Legacy duplicate |
| `Texturing_FixedTexelSize100perQuality.xml` | texturing | `SetVariables.bat` only | `FixedTexelSize`, type 0 (optimal texel), gutter 10, max 8K, large-tri thr 400 | Unused |
| `Texturing_FixedTexelSize50perQuality.xml` | texturing | `SetVariables.bat` only | same but type 1 (2× optimal = 50 % quality) | Unused |
| `Unwrapping_Simplified_4x16k.xml` | unwrap | `GenerateModel.bat` step [8/8] | 4 × 16K, min 512, `Geometric`, gutter 2, large-tri thr 10 | **Production** |
| `Unwrapping_Simplified.xml` | unwrap | `AlignImagesFromFolder.bat` (**deprecated** workflow) only — `GenerateModel.bat` references the 4×16k file exclusively | same but 1 × 16K | Legacy; superseded by the 4× variant |
| `ReprojectionParams.xml` | reprojection | `GenerateModel.bat` step [8/8] | **enables colour reprojection** (`allowColor=true`, `enableColor=-1`, `sourceColorLayer=Color8_0`), `normal=2` | **Production** |
| `ModelExportParamsOBJ_NiraParts.xml` | model export | `ExportDeliverables.bat` | OBJ, **by parts**, png, scale 1.0, number format 6, CRS type 3 — Nira's documented layout | **Production** |
| `ModelExportParamsFBX_Parts.xml` | model export | `ExportDeliverables.bat` | FBX, **by parts**, materials on, png, scale 1.0 | **Production** |
| `ModelExportParamsPLY_DensePoints.xml` | model export | `ExportDeliverables.bat` | PLY, **vertex colours on, textures off**, scale 1.0 | **Production** |
| `ModelExportParams.xml` | model export | `SetVariables.bat` + declared in `ExportDeliverables.bat` | generic v13, scale 100, jpg | Unused as an argument |
| `ModelExportParamsObj.xml` | model export | **nothing** (`SetVariables.bat` refers to `ModelExportParamsOBJ.xml`, which resolves only because NTFS is case-insensitive — and the variable is never consumed) | OBJ, scale 100, `Unreal` preset, jpg, a `_Normal_0` layer | Unreferenced |
| `ModelExportParamsGLB.xml` | model export | `SetVariables.bat` only | GLB, scale 10, rotation X `-90.0`, **embedded jpeg** | Unused |
| `ModelExportParamsFBX_U1V1.xml` | model export | `SetVariables.bat` only | FBX, tile `_u1_v1`, no materials, 32bppBGRA | Unused |
| `ModelExportParamsFBX_U1V1_material.xml` | model export | `SetVariables.bat` only | same + materials + normal layer | Unused |
| `ModelExportParamsFBX_UV.xml` | model export | `SetVariables.bat` only | FBX, tile `(u,v)` | Unused |
| `ModelExportParamsFBX_UDIM.xml` | model export | `SetVariables.bat` only | FBX, UDIM tiles, no materials | Unused |
| `ModelExportParamsFBX_UDIM_material.xml` | model export | `SetVariables.bat` only | FBX, UDIM tiles + materials + normal layer | Unused |

[VERIFIED-by-probe: repo-wide reference scan excluding `Metadata/` itself, plus per-file reads and
MD5 comparison, 2026-08-04]

Summary: of 34 profiles, **10 are in the production path** (`AlignmentParams`, `FlightLogParams`,
`SimplifyNoise`, `SimplifySmooth_80per`, `Texturing_MaxTextureCount4_16k`,
`Unwrapping_Simplified_4x16k`, `ReprojectionParams`, and the three `ExportDeliverables` model-export
profiles), **4 belong to the deprecated `AlignImagesFromFolder.bat`** (`SimplifyAutomationParams`,
`Texturing_HighPolyTexture`, `Texturing_SimplifiedTexture`, `Unwrapping_Simplified`), and the
remaining **20 are declared-but-unconsumed or entirely unreferenced**.

### 4.2 Which profile to pick when

| Goal | Profile | Why |
|---|---|---|
| Align a zone reproducibly | `AlignmentParams.xml` — replayed as `-set` | never align on instance defaults; settings persist across restarts |
| Georeference a scene | `FlightLogParams.xml` **regenerated for this cruise** | a hand-carried zone from another project imports silently and misplaces everything |
| Knock noise off a high model before texturing | `SimplifyNoise_Params.xml` (70 % rel) | the recipe's step [6/8]; keeps enough density for texture projection |
| Reduce to a deliverable-sized mesh | `SimplifySmooth_80per_Params.xml` ×4 with `-cleanModel` between | four gentle passes beat one aggressive one; each pass is followed by a clean because simplification can reintroduce non-manifold edges |
| Hit an exact triangle budget | `Simplify500k_Params.xml` (absolute 500 k) | absolute is Epic's recommended type |
| Texture a high-poly model | `Texturing_MaxTextureCount4_16k.xml` | `MaxTexturesCount` **is** the adaptive mode: 4 × 16K caps cost, small components use less |
| Deliver a declared texel precision (e.g. 1 cm for an ortho) | `Texturing_FixedTexelSize*.xml` | count follows from the precision, not the other way round |
| Unwrap a simplified model before reprojection | `Unwrapping_Simplified_4x16k.xml` | must match the texture budget of the source, or reprojection quality is wasted; `-reprojectTexture` **requires** the result model to be unwrapped |
| Carry a high-poly texture onto a simplified mesh | `ReprojectionParams.xml` | Epic's default has `allowColor=false` and would silently reproject **no colour** |
| Deliver to Nira | `ModelExportParamsOBJ_NiraParts.xml` | by parts + png + no vertex colours + decimal-6 is Nira's documented expectation; **Nira does not accept PLY point clouds** |
| Deliver an editable FBX | `ModelExportParamsFBX_Parts.xml` | parts preserved, materials written |
| Deliver dense coloured geometry for local use | `ModelExportParamsPLY_DensePoints.xml` | run `-calculateVertexColors` first — it colours in memory only, and the workflow deliberately quits without saving |
| Deliver a single self-contained web asset | `ModelExportParamsGLB.xml` | embedded jpeg textures, Y-up rotation |
| Deliver UDIM tiles for a DCC pipeline | `ModelExportParamsFBX_UDIM_material.xml` | `MvsMeshExportTileType=2` + materials |

### 4.3 Known defects in the profile set

Each of these is real, each was found by reading the files, and each is worth knowing before
trusting a filename.

1. **`Simplify25per_Params.xml` is byte-identical to `Simplify500k_Params.xml`** (MD5
   `12cfffa2b86bfe6c2ffa0f9e2096dff0`) — it contains `mvsFltSimplificationType=0` with
   `mvsFltTargetTrisCountAbs=500000` and **no relative target at all**. Using it expecting a 25 %
   reduction gives an absolute 500,000-triangle result. It is unreferenced, so nothing has been
   damaged. [VERIFIED-by-probe: MD5, 2026-08-04]
2. **`SmoothingSurface_02_2_Params.xml` is byte-identical to `Smoothing_02_2_Params.xml`**
   (MD5 `ba7b5ba9b6e9d7f9c7b4b0e3ca0eb0d9`). The "Surface" name asserts a `mvsFltSmoothingStyle`
   semantic that has never been verified. [VERIFIED-by-probe]
3. **`Texturing_SimplifiedTexture.xml` is byte-identical to `Texturing_HighPolyTexture.xml`**
   (MD5 `d97f57c353d62570a3fe6ba51c834112`) — both 2 × 16K. The deprecated workflow that uses them
   therefore textures the simplified model at high-poly settings. [VERIFIED-by-probe]
4. **`SimplifyNoise_Params.xml` (70 % rel) and `SimplifySmooth_80per_Params.xml` (80 % rel) are
   placeholders** derived from the 50 % template, not GUI exports of owner-chosen presets. They are
   nonetheless in the production model recipe. If owner presets exist they should be exported over
   these files. [OPEN: standing self-audit item 5, unresolved]
5. **`XMPExportParams.xml` is referenced by nothing** — zero `.bat`, zero `.py`, zero test scripts —
   so every `-exportXMP` and `-exportXMPForSelectedComponent` in this repo's history ran on instance
   defaults. [VERIFIED-by-probe: repo-wide reference scan excluding `Metadata/` itself, 2026-08-04]
   This corrects the survey layer, which pairs the file with `-exportXMP` as though it were wired up.
6. **`SetVariables.bat` sets `ModelExportParamsOBJ=%Metadata%\ModelExportParamsOBJ.xml`** while the
   file on disk is `ModelExportParamsObj.xml`. It resolves only because NTFS is case-insensitive,
   and the variable is never consumed anyway. On a case-sensitive volume this would break.
   [VERIFIED-by-inspection]
7. **The `s2NNl` keys in `AlignmentParams.xml` are never applied** — the replay loop filters to
   `sfm*` and `lis*` prefixes. Whatever they control is running at instance default.
   [VERIFIED-by-inspection]
8. **Line endings split the set cleanly into GUI-exported (CRLF) and hand-authored (LF).** LF files:
   `AlignmentParams.xml`, `ModelExportParamsFBX_Parts.xml`, `ModelExportParamsOBJ_NiraParts.xml`,
   `ModelExportParamsPLY_DensePoints.xml`, `SimplifyNoise_Params.xml`,
   `SimplifySmooth_80per_Params.xml`, `Texturing_MaxTextureCount4_16k.xml`,
   `Unwrapping_Simplified_4x16k.xml` — exactly the eight files whose provenance is documented as
   hand-derived. **All eight are in the production path and all work**, so LF is harmless in a
   profile (unlike in a `.bat`, where LF intermittently breaks cmd's label search).
   [VERIFIED-by-probe: line-ending census + production use, 2026-08-04]

---

## 5. Authoring guide

### 5.1 Safe hand-edit procedure

Hand-editing a profile is legitimate and this repository does it. The procedure that keeps it safe:

1. **Start from a GUI export or an Epic-shipped file**, never from a blank document. You cannot
   know which keys a panel requires; a partial file inherits the rest from instance state, and
   instance state persists across restarts.
2. **Copy the nearest sibling and rename it**, then change the fewest possible entries. Each
   Texturing variant here differs from its neighbour in exactly one value, and the two production
   Simplify profiles differ in exactly one line (§1.6).
3. **Change one variable per edit**, and record which. An escalation ladder that changes two things
   at once produces an uninterpretable result — this repo has a documented case (cell PD-0) whose
   registration numbers are permanently unattributable because two variables moved together.
4. **Do not reformat.** Do not alphabetise entries, do not normalise `0x1` to `true`, do not add an
   XML prolog, do not change attribute order (`key` must precede `value` for `AlignZone.bat`'s
   parser).
5. **Comments are tolerated but must never contain a double quote.** `AlignmentParams.xml` carries
   three comment blocks safely; a `"` inside one would inject garbage into a `-set` through the
   `delims="` token split.
6. **Keep the `Configuration id` GUID from the source file.** A profile for the wrong panel has
   uncharacterised behaviour (§1.10).
7. **Commit it.** A profile is the reproducibility artifact for an operation; a run whose settings
   are not in version control is not reproducible. Attach the profile hash to the run's environment
   snapshot alongside tool version and git SHA.
8. **Verify before trusting** (§5.3). No error means nothing.

### 5.2 Fields that must never be hand-edited

| Field | File | Why | Correct procedure |
|---|---|---|---|
| `CoordinateSystemFlightLog`, `CoordinateSystemFlightLogType` | `FlightLogParams.xml` | **The UTM zone must be derived per cruise.** The template once said 4N while the cruise was 57S. A wrong zone imports silently and misplaces the entire scene — no error, no warning, plausible-looking output. | Generate with `modules.flight_logs.write_flight_log_params(template, out, zone, band)`, which parses the zone from the flight log's own filename tag |
| `gpsLogFileFormat` | `FlightLogParams.xml` | Must name a `<format id>` that **exists in the installed `flightlogs.xml`**. For four months it named one that did not, and orientation plus per-image accuracies were silently dropped on every import. | Grep the installed `flightlogs.xml` for the GUID before changing it; re-verify after every app update |
| `MvsMeshExportInfoFile` | any `ModelExportParams*.xml` | Turning it off loses the `.rsInfo`, which is both the re-import placement record and the bootstrap route for new export profiles | leave `true` |
| `sfmFeatureDetectionQuality` value string | `AlignmentParams.xml` | `RealityScan.FeatureDetector.RSa1` is a live API identifier that happens to contain the product name; renaming it to match repo naming conventions breaks the setting | never rename; same rule as `reader="RealityScan.Import.CSVFlightLog"` |
| `sfmControPointImageMeasAccuracy` | `AlignmentParams.xml` | Epic's typo is the real key; the corrected spelling does not exist | never "fix" it |
| `MvsMeshExportEmbeddTxrs` | model export profiles | same — the doubled `d` is the real key | never "fix" it |
| `MvsExportcoordinatesystemtype` | model export profiles | same — the all-lowercase tail is the real key, unlike every sibling `Mvs*` key | never camel-case it |
| `writer="cvs"`, `reader="RealityScan.Import.CSVDistanceDefinition"` | install-tree dictionaries | Epic's Help prints `csv` and `…CsvDistanceDefinition`; the installed files use the other spelling and the installed files are what loads | copy the spelling out of the file you are editing, never out of the Help |
| `boxSideConerIndex` | `.rsortho` | Epic's typo, and the value itself is not analytically derivable — it depends on the region's rotation | obtain by exporting one manually-made projection; reuse the number |
| `&tab;`, `&quot;optional` | install-tree dictionaries | RealityScan-specific tokens; "fixing" them to standard XML changes the parser's behaviour | leave verbatim |
| The `id` GUID | any profile | binds the file to a settings panel | keep the source file's GUID |

### 5.3 Verifying a profile took effect

**Exit code 0 proves nothing.** Neither does an empty errors marker. Unknown keys are silently
ignored, wrong values succeed, and a profile handed to `-align` is discarded without a trace. Every
verification below is an *independent* observation of the operation's output.

| Profile type | Independent check | Cost |
|---|---|---|
| Alignment | Count pose-bearing `.xmp` sidecars — only registered cameras get pose entries, so the count is a registration census. Then run the metric-scale oracle (`testing/scale_oracle.py`) on the poses: a component at 0.236 registers perfectly and is 1:4.24 scale, invisible in any viewer. | minutes, on artifacts you already produce |
| Alignment settings replay | `RealityScan.log` shows `Parsing setting key=value '<key>' failed [err:7155]` when a `-set` was split by cmd. Snapshot the log **immediately** — it is truncated on the next instance boot. | free, but the window is short |
| Flight-log import | Read `xcr:Position` back out of the exported pose XMPs and fit local→UTM (`poses2flightlog.py`); a correctly georeferenced component fits near-identity. Cross-check the row count: `4,598 log rows − 4,496 cameras = 102` unregistered is benign; a wrong zone shows up as absurd residuals. | minutes |
| Simplify | Triangle count of the resulting model, and its part count. A profile that forced a singleton would show 1 part on export — the production profile (`simplPreserveParts=2`) shows 4, which is how the §2.4 contradiction was found. Also confirm a **new** model appeared: simplify never edits in place. | seconds, from the export |
| Texturing / unwrap | Count and resolution of the emitted texture files. A 4 × 16K budget produces at most four 16384² images. | seconds, `dir` on the export folder |
| Reprojection | Open one exported texture. `allowColor=false` produces a geometrically valid model with no reprojected colour — and no error. | seconds |
| Model export | File count and layout: the Nira OBJ profile produces **4 parts + per-part MTL + `u1_v1` textures + `.rsInfo`**. Read the `.rsInfo`'s `<ModelExport>` tag — it echoes the parameters actually used. | seconds |
| Any `-set` key | `-exportGlobalSettings before.rcconfig`, apply, `-exportGlobalSettings after.rcconfig`, diff. Never exercised here, but it is the cheapest general oracle available. | seconds [OPEN] |

The `.rsInfo` echo deserves emphasis: it is the **only** self-describing output in the whole
system — an artifact that reports back the parameters it was made with. For model export it closes
the verification loop without any external oracle.
[OFFICIAL: tools/export "It also contains export parameters"]

### 5.4 Encoding, BOM, line endings

| Property | Requirement | Evidence |
|---|---|---|
| Encoding | ASCII / UTF-8 without BOM. All 34 repo profiles are BOM-free. | [VERIFIED-by-probe, 2026-08-04] |
| BOM | **Avoid.** No profile has one, and the adjacent lesson is severe: PowerShell 5.1's `Set-Content -Encoding utf8` writes a BOM, and a BOM on line 1 of a `.complist` silently invalidated the first entry (`\ufeffF:\...\zone_1_c6.rsalign` matched no manifest and aborted the driver). Whether a profile tolerates one is untested. | [VERIFIED: FINDINGS 2026-07-27] [OPEN for profiles] |
| Writing from PowerShell | `[System.IO.File]::WriteAllLines($p, $lines, (New-Object System.Text.UTF8Encoding($false)))` | [VERIFIED: FINDINGS 2026-07-27] |
| Writing from Python | `open(path, 'w', encoding='utf-8', newline='')` — no BOM, and `newline=''` preserves whatever the template had. This is what `write_flight_log_params` does. | [VERIFIED-by-inspection: `modules/flight_logs.py`] |
| Line endings | **Either works.** Eight production profiles are LF and have driven every H2024 model. Do not confuse this with `.bat` files, which **must** be CRLF — LF intermittently breaks cmd's batch-label search. | [VERIFIED-by-probe + production use, 2026-08-04] |
| Non-ASCII | Avoid entirely. The cp1252 console crashes on non-ASCII output, and `PYTHONIOENCODING=utf-8` is required when parsing UTF-8 sources. No profile here contains a non-ASCII byte. | [VERIFIED: standing Windows-automation constraint] |
| Console output while parsing | Set `PYTHONIOENCODING=utf-8` in any tool that reads these files and prints from them | same |

### 5.5 Pre-flight checklist

Before a long run that depends on a profile:

- [ ] The file exists at the path the workflow will use, and the workflow **checks existence
      before delegating**. Note the `exit /b` trap: inside a parenthesised block `exit /b 1` returns
      0 to the process caller, so the check must be a single-line chain or a `goto`, exactly as
      `AlignZone.bat` writes it:
      `if not exist "%AlignmentParams%" ( echo ERROR: AlignmentParams.xml not found: %AlignmentParams% & exit /b 1 )`
- [ ] The `Configuration id` matches the consuming command's panel (§1.7), or the file is a
      `ModelExportParams*` with no id.
- [ ] The command actually accepts a profile (§1.3) — and is not `-align` (§1.4).
- [ ] For a flight-log profile: the CRS was **generated for this cruise**, and the
      `gpsLogFileFormat` GUID exists in the **installed** `flightlogs.xml`.
- [ ] For a model-export profile: `MvsMeshExportInfoFile=true`, and the output extension matches
      the format the profile was exported for.
- [ ] For a texture/unwrap pair: the unwrap budget matches the texture budget.
- [ ] No double quote inside any XML comment.
- [ ] The file parses (`System.Xml.XmlDocument.Load` or `xml.etree.ElementTree.parse`), has no BOM,
      and contains no non-ASCII byte.
- [ ] The file is committed, and its hash is in the run's environment snapshot alongside the tool
      version and git SHA.
- [ ] An **independent** verification for its effect is chosen in advance (§5.3) — not the exit code.

---

## 6. Open questions

Ordered by cost of the probe that settles them. Every one is genuinely unknown here; none is a
placeholder.

| # | Question | Cheapest probe | Cost |
|---|---|---|---|
| 1 | Do other zero-parameter commands also swallow a stray XML argument silently, as `-align` does? | `-delegateTo RS1 -cleanModel "C:\nonexistent.xml"` on a loaded smoke scene; read the errors marker | seconds |
| 2 | What does a **missing** profile path do? | pass a nonexistent path to `-simplify` on a loaded smoke scene | seconds |
| 3 | What does a **malformed** profile do? | truncate a copy of `SimplifyNoise_Params.xml` mid-element and pass it | seconds |
| 4 | Is the `Configuration id` GUID checked — does a **wrong-type** profile error or get ignored? | pass `SimplifyNoise_Params.xml` to `-unwrap` on the smoke fixture; compare texture count vs a default unwrap | ~2 min |
| 5 | Are export/tool profile keys (`Mvs*`, `unwrap*`, `mvsFlt*`, `reprojectionTool_*`, `xmp*`, `if*`) also valid `-set` keys? | `-set "unwrapMaximalTexCount=4"`, then `-exportGlobalSettings out.rcconfig` and grep for the key | seconds |
| 6 | Is `.rcconfig` or `.rsconfig` the real global-settings extension? | run `-exportGlobalSettings settings` and read the produced filename | seconds |
| 7 | Does `-exportGlobalSettings` diffing actually work as a "did my setting take" oracle? | export, `-set` one known key, export again, diff | seconds |
| 8 | What are the `s235l` `s236l` `s237l` `s251l` `s252l` `s253l` `s254l` keys in `AlignmentParams.xml`? | GUI: export the alignment panel, change one control, export again, diff — repeat per control | ~1 min each, needs the GUI |
| 9 | What are the config keys for *Euler angles order (YPR)* and *Camera mount*, and what are their values? | GUI: save trajectory-import params at defaults, then after changing only *Euler angles order*, then only *Camera mount*; three-way diff | ~5 min, needs the GUI |
| 10 | Are `ifUsePosAcc` / `ifUseOriAcc` / `ifKmode` genuinely inert, given the findings log attributes orientation import to them? | import the same 13-column log twice with `ifUseOriAcc` `true` vs `false`; diff camera attitudes from the pose XMPs | ~2 min on the smoke fixture |
| 11 | Is `reprojectionTool_colorSampling=0` "Nearest" or "Trilinear"? If nearest, every reprojected deliverable carries avoidable aliasing. | flip to `1`, reproject an existing high/simplified pair, compare visually | minutes |
| 12 | `mvsFltSmoothingStyle`: repo filenames say `1`=surface, `3`=peaks; a 0-based reading of the Help's option order (surface, borders, peaks, all) says `0`=surface, `2`=peaks. A **1-based** enum reconciles both. Which? | smooth a fixture at each of 0–4 and inspect which vertices moved | minutes each, needs a viewer |
| 13 | `simplPreserveParts`: `0` (Epic) vs `2` (repo) — which value is Disable / Enable / Create a singleton? A 0-based reading makes `2`=singleton, but four `2` passes produced a **4-part** export, so the mapping is wrong somewhere. | simplify a multi-part fixture at 0, 1, 2 (and 3) and count parts on export | minutes each |
| 14 | `mvsFltSimplificationType` `2` and `3` — which is "Maximum of absolute and relative" and which "Minimum"? | simplify with both Abs and Rel set to values that differ by 10× at type 2 then 3; read the resulting triangle counts | minutes |
| 15 | `mvsFltBorderDecimationStyle` and `mvsFltReprojectNormal` value↔name mappings | GUI export at each setting, diff | ~1 min each, needs the GUI |
| 16 | `MvsExportcoordinatesystemtype`: does `0..3` index Grid plane / Project Output / Shifted project output / Same as XMP? | export the same model at each of the four dialog choices and diff the four profiles | minutes, needs the GUI |
| 17 | `MvsMeshExportNumberFormat` `5` vs `6`. The Help documents *Number format* as a **three-option enum** (Decimal / Scientific / General), which `5` and `6` cannot index — so either the key is not that control, or the enum has hidden members. The repo's `6` was chosen believing it meant six decimals. | export the same model at each of the three dialog choices, diff the three profiles, then compare vertex-coordinate decimal places in the OBJ | minutes, needs the GUI for the diff |
| 17b | *(new)* What are the keys for the Export-Model controls no repo profile ever set — *Texture maximal side*, *Use pow2 texture size*, *Grayscale quality values*, *Classification export*, *File type* (PLY binary/ASCII), *Output Decimal Precision* (PTX), and the Undistortion / Export-Image groups? | export the dialog from the GUI once with each group enabled and diff | ~5 min, needs the GUI |
| 17c | *(new)* What is the key for the Unwrap panel's *Defragment charts* control? It is documented in two Help topics and appears in no profile, Epic's or ours. | export the Unwrap panel with it on and off, diff | ~1 min, needs the GUI |
| 18 | `unwrapFillTextures` (`0x0`/`0x1`) — which dialog control? | GUI export with the control toggled | ~1 min, needs the GUI |
| 19 | `unwrapMethod` — the value string for "Mosaicing based" | GUI export with the mosaicing method selected | ~1 min, needs the GUI |
| 20 | `xmpCamera=3` — is 0..3 the draft/exact/locked ladder, and which is 3? | export XMPs at each of the three modes and diff the sidecars' `xcr:PosePrior` | minutes |
| 21 | Is the target format for `-exportModel` chosen by extension only, or does the profile constrain it? | pass `ModelExportParamsGLB.xml` with an `.obj` output path and inspect the result | seconds |
| 22 | Does the `<ModelExport>` tag extracted from a `.rsInfo` work unchanged as an `-exportModel` profile? | run the §1.6 bootstrap end to end on the 133-camera component | ~1 min |
| 23 | What is the root element of a standalone `.rsbox`, and is its `<Header>` required? | `-exportReconstructionRegion` on the smoke fixture, then read the file | seconds |
| 24 | What are the key names in a `-exportLod` / `-export3dTiles` profile? | GUI: save the Export LoD dialog once, both variants | ~2 min, needs the GUI |
| 25 | Does `-exportRegistration` still block forever when given a valid params XML? (The blocking is only established for the no-params case, and it gates hardening cell U7.) | GUI-save an Export Registration profile once, then delegate with a watchdog on the smoke fixture | ~5 min, needs the GUI once |
| 26 | Does the hand-merged `{B438A617…}` flight-log format survive a RealityScan update? | after any update, diff the installed `flightlogs.xml` against the repo copy | seconds, but must be remembered |
| 27 | Is `<XAccuracy index="4"/>` + `<YAccuracy index="4"/>` in shipped `measurementsimport.xml` intentional or a typo for index 5? The format's own `desc` says "…, X, Y, **Accuracy**" (singular, five columns), which argues intentional. | import a 5-column CPM file with a distinctive accuracy value and read both accuracies back | minutes |
| 28 | Can a flight log carry per-image `FocalLength` / `PrincipalU/V` / `RadialDistortion1-4` priors as an alternative to XMP sidecars? | add those `<Variable>` elements to a custom format, import, and read the solved intrinsics out of the pose XMPs | ~10 min incl. the format edit |
| 29 | Are all `.rcconfig`-transportable settings also profile keys, i.e. can a global-settings dump seed a per-tool profile? | export globals, grep for `unwrap*` / `mvsFlt*` keys | seconds |
| 30 | Does a profile tolerate a UTF-8 BOM? (Known to break `.complist`.) | prepend a BOM to a copy of `SimplifyNoise_Params.xml` and pass it | seconds |
| 31 | Is `-importFlightLog` an alias of the documented `-importTrajectory`, or a separate implementation? Six production call sites use the **undocumented** name and nothing has ever used the documented one. | run both on the smoke fixture with the same params XML and diff the resulting prior poses | ~2 min |
| 32 | Does the whole `-exportRegistration` family (`-exportUndistortedImages`, `-exportSTMap`) share the block-without-params behaviour, or is `-exportRegistration` alone? | delegate `-exportSTMap` with no arguments on the smoke fixture under a watchdog | ~2 min |
