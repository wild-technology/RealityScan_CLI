# Georeferencing: flight logs, coordinate systems, GCPs, control points, scale

This document covers everything that puts real-world position, orientation, and **metric
scale** into a RealityScan scene from the command line: trajectory (flight-log) import and
its XML parameter file, the shipped coordinate-system databases and the `authority:id`
selection syntax, ground control points, control points and their image measurements,
detected markers, distance constraints, ground-plane and `-update` fitting, and the
measurement of scale as an automated acceptance oracle. It does **not** cover alignment
settings themselves beyond the prior-related keys (see `03-settings-keys.md`), component
and merge semantics (see `08-components-and-merge.md`), model/texture/export (see
`10-reconstruction-texturing-export.md`), the execution layer, delegation, and error markers
(see `01-cli-fundamentals.md` and `02-command-reference.md`), or XMP sidecar calibration
content (see `05-metadata-xmp-and-sidecars.md`).

**Applies to:** RealityScan 2.2 (Epic Games), Windows, headless CLI operation.
**Tags:** [OFFICIAL] shipped Help · [VERIFIED] measured in production here ·
[CONTRADICTED] docs vs observation · [UNDOCUMENTED] · [INFERRED] · [OPEN]

---

## Contents

1. [Command surface](#1-command-surface)
2. [Trajectory / flight-log import](#2-trajectory--flight-log-import)
   - 2.1 [The two command names](#21-the-two-command-names)
   - 2.2 [The log file format](#22-the-log-file-format)
   - 2.3 [`flightlogs.xml` — the shipped reader definitions](#23-flightlogsxml--the-shipped-reader-definitions)
     — including **[CONTRADICTED] Did the pre-2026-07-25 runs import orientation at all?**
   - 2.4 [The full `<Variable>` vocabulary](#24-the-full-variable-vocabulary)
   - 2.5 [Name matching is by BASENAME](#25-name-matching-is-by-basename)
   - 2.6 [err:18002 / 0x820000FF — rows not in the scene](#26-err18002--0x820000ff--rows-not-in-the-scene)
   - 2.7 [The params XML: `FlightLogParams.xml` in full](#27-the-params-xml-flightlogparamsxml-in-full)
   - 2.8 [Inert keys and the real binary key names](#28-inert-keys-and-the-real-binary-key-names)
   - 2.9 [Euler angle order, camera mount, camera axes](#29-euler-angle-order-camera-mount-camera-axes)
   - 2.10 [Accuracies: what the numbers mean and what they do](#210-accuracies-what-the-numbers-mean-and-what-they-do)
   - 2.11 [Per-cruise CRS generation from the log filename](#211-per-cruise-crs-generation-from-the-log-filename)
   - 2.12 [Side effect: import leaves images SELECTED](#212-side-effect-import-leaves-images-selected)
   - 2.13 [Runnable examples](#213-runnable-examples)
3. [Coordinate systems](#3-coordinate-systems)
4. [Ground control points and control points](#4-ground-control-points-and-control-points)
5. [Scale: defining it](#5-scale-defining-it)
6. [Scale: measuring it as an oracle](#6-scale-measuring-it-as-an-oracle)
7. [Verifying georeferencing headless](#7-verifying-georeferencing-headless)
8. [Failure modes and a pre-flight checklist](#8-failure-modes-and-a-pre-flight-checklist)
9. [Open questions](#9-open-questions)

---

## 1. Command surface

Every command below is invoked with a leading `-` on the command line and is delegable
(`-delegateTo <instance> <cmd>`) unless noted. Process IDs are the values that appear in
`-writeProgress` output and in `$(processId)` substitutions.

| Command | Required | Optional | Process ID | Purpose |
|---|---|---|---|---|
| `-importTrajectory` | `flFileName` | `params.xml` | `20598 IMPORT_FLIGHT_LOG` | Import a trajectory (flight log). Documented name. [OFFICIAL: appbasics/allcommands] |
| `-importFlightLog` | `<log>` | `<params.xml>` | `20598 IMPORT_FLIGHT_LOG` | Same operation; **absent from the 2.2 Help** but works. [UNDOCUMENTED / VERIFIED: in production use here since 2026-07-21, `RS_CLI/Scripts/AlignZone.bat` line 77] |
| `-addImageWithCalibration` | `image xmp` | — | — | Import one image plus an XMP whose name/folder need not match the image's. [OFFICIAL: tools/xmpalign] Never used here. |
| `-importGroundControlPoints` | `gcpFileName` | `params.xml` | `20599 IMPORT_GCP` | Import GCP coordinates. [OFFICIAL: appbasics/allcommands] |
| `-exportGroundControlPoints` | `gcpFileName` | `params.xml` | `21814 EXPORT_GCP` | Export GCPs (selected only, or all if none selected). [OFFICIAL: tools/gcpexport] |
| `-importControlPointsMeasurements` | `cpmFileName` | `params.xml` | `20600 IMPORT_CP_MEASUREMENTS` | Import per-image 2D measurements of control points. [OFFICIAL] |
| `-exportControlPointsMeasurements` | `cpmFileName` | `params.xml` | `20569 EXPORT_CP_MEASUREMENTS` | Export per-image measurements. [OFFICIAL] |
| `-listControlPoints` | `fileName` | — | — | Write the control-point list with indices to a file. [OFFICIAL] |
| `-selectControlPoint` | `controlPointName` | — | — | Select one control point by name. [OFFICIAL] |
| `-invertControlPointSelection` | — | — | — | Invert; with none selected, selects all. [OFFICIAL — see the parameter contradiction in `02-command-reference.md`] |
| `-renameControlPoint` | `controlPointName newName` | — | — | Rename by current name. [OFFICIAL] |
| `-renameSelectedControlPoint` | `newName` | — | — | Rename the selection. [OFFICIAL] |
| `-deleteControlPoint` | — | `index` | `22530 REMOVE_CONTROL_POINT` | Delete the selected control point; with `index`, delete that one instead. Indices are 0-based and follow 1Ds-view order. [OFFICIAL] |
| `-editControlPointSelection` | `"key=value"` | — | — | Set type/coords/weight/accuracy on the selection. Keys in §4.4. [OFFICIAL: tutorials/editselectioncommand] |
| `-selectMeasurementByError` | `errorValue` | `controlPointName` | — | Select measurements with position error (px) ≥ value. [OFFICIAL] |
| `-selectMeasurementByIndex` | `controlPointName index` | — | — | Select a measurement by index within a point. [OFFICIAL] |
| `-deleteControlPointMeasurement` | — | — | — | Remove selected measurements. Requires a 1Ds-view selection — **GUI state**. [OFFICIAL] |
| `-defineDistance` | `PointNameA PointNameB distance` | `constraintName` | `21809 DEFINE_DISTANCE` | Create a distance constraint between two control points. Form 1 of 2. [OFFICIAL] |
| `-defineDistance` | `fileName` | `params.xml` | `21809 DEFINE_DISTANCE` | Import distance constraints from a file. Form 2 of 2; formats in `distancedefinitions.xml`. [OFFICIAL] |
| `-editConstraintSelection` | `"key=value"` | — | — | Set A/B/value/accuracy on selected constraints. Keys in §5.1. [OFFICIAL] |
| `-deleteConstraint` | — | `index` | — | Remove the selected distance constraints (they must be selected **in the 1Ds view** — GUI state); with `index`, remove that one. 0-based, 1Ds-view order. [OFFICIAL] |
| `-detectMarkers` | — | `params.xml` | `30 DETECT_MARKERS` | Detect coded targets and create a control point per marker. [OFFICIAL: tools/detectmarkers] |
| `-update` | — | — | `65542 UPDATE_CONSTRAINTS` | Fit components/models to the scene's constraints and control points. [OFFICIAL] |
| `-setProjectCoordinateSystem` | `authority:id` | — | `20640 CHANGE_COORDINATE_SYSTEM` | e.g. `epsg:32653`, `Local:1`. [OFFICIAL] |
| `-setOutputCoordinateSystem` | `authority:id` | — | `20640 CHANGE_COORDINATE_SYSTEM` | e.g. `epsg:4326`. [OFFICIAL] |
| `-setCamerasGravityDirection` | — | `componentID` | — | Rotate the component so `-z` follows `xcr:Gravity` from the images' XMP. Sparse cloud only. [OFFICIAL] |
| `-resetGround` | — | — | `21776 RESET_GROUND_PLANE` | Restore the default ground plane. [OFFICIAL] |
| `-setGroundPlaneFromReconstructionRegion` | — | — | `21778 SET_GROUND_PLANE_BY_RECONSTRUCTION_REGION` | Centre the model on the grid using the reconstruction region, adjusting rotation **and** translation. [OFFICIAL] |
| `-exportRegistration` | `fileName` | `params.xml` | `20576`, `41061`–`41064` | Export camera positions/orientations in one of the `calibration.xml` formats. **Blocks forever headless without a params XML.** [VERIFIED: FINDINGS 2026-07-21] |
| `-exportReport` | `outputFileName templateFileName` | `true`\|`false` | — | Render a report template; **the only headless way to read `isGeoreferenced` / `componentMetric`**. [OFFICIAL: appbasics/allcommands] |

Commands that do **not** exist and will fail: `-setGeoreferencedCoordinateSystem`,
`-setGeoreferenceCRS`, or any similar spelling. The only CRS setters are
`-setProjectCoordinateSystem` and `-setOutputCoordinateSystem`; the flight log's own CRS is
set **inside the params XML**, not by a command. [VERIFIED: exhaustive sweep of
`appbasics/allcommands` + `tutorials/commandline_1..5`; no such identifier occurs]

---

## 2. Trajectory / flight-log import

### 2.1 The two command names

`appbasics/allcommands` documents exactly one name:

```
importTrajectory | flFileName | params.xml
```

[OFFICIAL: appbasics/allcommands, tutorials/commandline_1]

This repository has driven `-importFlightLog <log> <params.xml>` in production since
2026-07-21 across thousands of aligns; it works and is the name baked into every workflow
`.bat` here — **six call sites**: `AlignZone.bat`, `AlignImageList.bat`, `GrowZone.bat`,
`MergeZoneComponents.bat`, `SequentialAlignGrow.bat`, `AlignImagesFromFolder.bat`. The
string `importFlightLog` does not appear anywhere in the 2.2 Help.
[UNDOCUMENTED / VERIFIED: those six scripts; FINDINGS 2026-07-21; SURVEY_commands.md]

Circumstantial support that they are the same implementation: the process ID for the
trajectory import is named `20598 IMPORT_FLIGHT_LOG` even though the documented command is
`importTrajectory` — i.e. `FlightLog` is the internal name and `Trajectory` is the
user-facing rename. [INFERRED: tutorials/processids]

- [OPEN] Are `-importTrajectory` and `-importFlightLog` literally the same handler?
  Cheapest probe: on the 120-image smoke fixture, import the same log with the same params
  XML via each name in two fresh scenes, then `-exportReport` an `$ExportImagePriors`
  template from each and diff the prior tables. ~4 min total.

Both forms take the params XML as an **optional** second argument. Omitting it means "use
the current settings", i.e. whatever the instance's import dialog last held — which for an
unattended instance is unknowable. **Always pass the params XML.**
[OFFICIAL for optionality; VERIFIED-as-policy: CLAUDE.md, every repo workflow]

### 2.2 The log file format

A trajectory file is a plain text / CSV table, one row per image.

| Property | Value | Source |
|---|---|---|
| Separator | one of `,` `;` ` ` (space) `\t` (tab); the set offered is the reader's `allowedSeparators`, and the actual separator is **auto-detected from the file** or chosen in the dialog / by `csvFLSep`. If `allowedSeparators` is absent, the `<parser>`'s `separator` attribute is used instead — no shipped format uses `separator` | [OFFICIAL: tools/defineimportformat] |
| Qualifier | `"` — fields may be wrapped in double quotes so they may contain the separator | [OFFICIAL: tools/flightlogimport] |
| Comment | lines beginning `#` are skipped **automatically**, always | [OFFICIAL: tools/flightlogimport] |
| Header | a single header line may be skipped; controlled by the reader's `showIgnoreFirstline` and the params key `csvFLIgn` | [OFFICIAL + VERIFIED-by-inspection] |
| Column order | fixed by the selected `<format>` in `flightlogs.xml`, referenced from the params XML by GUID | [OFFICIAL + VERIFIED-by-inspection] |
| Encoding | UTF-8 without BOM is safe. A UTF-8 BOM on line 1 is a known hazard for RealityScan list inputs generally (a BOM silently invalidated the first `.complist` entry). Not separately tested on flight logs. | [VERIFIED for `.complist`: FINDINGS 2026-07-27] [INFERRED for logs] |

This repository's canonical log is **13 columns, `;`-separated, one header line**, written by
`geoall.py::generate_flight_log` and `modules/georeference/georeference_images.py::__generate_flight_log`:

```
Name;X (East);Y (North);Alt;X Accuracy;Y Accuracy;Alt Accuracy;Yaw;Pitch;Roll;Yaw Accuracy;Pitch Accuracy;Roll Accuracy
C231C1034_20231104202628_edt.jpg;594701.482174;2345128.905112;-1523.117000;10.000000;10.000000;1.000000;71.418000;135.220000;-1.930000;15.000000;15.000000;15.000000
```

[VERIFIED-by-inspection: `geoall.py::generate_flight_log`, lines 715–770, 2026-08-04]

Two in-repo producers write **different header text** for the identical column layout —
`geoall.py` writes `Name;…`, the georeference module writes `filename;…`. Functionally
irrelevant (the header is skipped via `csvFLIgn=true`), but downstream readers must accept
both: `modules/image_batcher/batch_directory.py` renames `Name` → `filename` on read.
[VERIFIED-by-inspection, 2026-08-04]

`geoall.py` additionally prefixes the image name with its camera subfolder
(`Zeuss/HERC/<file>.jpg`); the module writes the bare basename. Both import correctly —
see §2.5. [VERIFIED-by-inspection]

### 2.3 `flightlogs.xml` — the shipped reader definitions

Path: `C:\Program Files\Epic Games\RealityScan_2.2\flightlogs.xml`. Structure
[OFFICIAL: tools/defineimportformat]:

```xml
<format id="{GUID}" descID="8436" desc="Text shown in the import dialog"
        reader="RealityScan.Import.CSVFlightLog">
    <parser allowedSeparators=",; &tab;" comment="#" showIgnoreFirstline="true"
            qualifiers="&quot;optional">
        <Image index="0" format="name.ext"/>
        <X     index="1" format="value"/>
        ...
    </parser>
</format>
```

| Attribute | Meaning |
|---|---|
| `id` | GUID; this is what `gpsLogFileFormat` in the params XML selects |
| `descID` | internal localisation string id (optional) |
| `desc` | text shown in the GUI import dialog |
| `reader` | **`RealityScan.Import.CSVFlightLog`** — a *current* product identifier; never rename it |
| `allowedSeparators` | separator characters offered; `&tab;` is the tab entity |
| `comment` | comment lead-in character(s) |
| `showIgnoreFirstline` | whether the "ignore first line" option is offered |
| `qualifiers` | quoting characters. Every shipped format uses the literal string `&quot;optional`, i.e. `"optional` — a double quote plus the word `optional`. Reproduce it exactly when authoring a format; the Help's bullet calls this attribute `qualifier` (singular) while every shipped file spells it `qualifiers` |
| `separator` | fallback delimiter set, used only when `allowedSeparators` is absent |
| `<Variable index format>` | column mapping; `index` is 0-based, so unused columns can be skipped |
| `format` | `value` (number), `degrees` (e.g. `N65 23 12.1`), `name` (string), `name.ext` (file name with extension) |

The shipped `desc` strings are terse, space-separated column lists —
`desc="Image X/Lon Y/Lat Z/Alt X/LonAccuracy Y/LatAccuracy Z/AltAccuracy Yaw Pitch Roll"` —
**not** the comma-and-parenthesis prose form the Help's sample shows
(`"Name, X (East), Y (North), Alt, … (character-separated)"`). [CONTRADICTED: the Help
sample for `{97F08A22-…}` in `tools/defineimportformat` prints a `desc` that differs
character-for-character from the same GUID's `desc` in the installed `flightlogs.xml`.
Cosmetic — `desc` is only a dialog label — but do not copy the Help's sample and expect a
byte match.] [VERIFIED-by-inspection: installed `flightlogs.xml`, 2026-08-04]

**All 14 `<format>` entries in the installed file**, verified by direct read
[VERIFIED-by-inspection: `C:\Program Files\Epic Games\RealityScan_2.2\flightlogs.xml`,
2026-08-04]:

| GUID | `descID` | Columns (index order) |
|---|---|---|
| `{45881112-C09A-49FD-92E1-5170016D9AB5}` | 8398 | Image, X, Y, Altitude |
| `{C2B41ED1-9567-43C7-8AE6-1452EBEB9F1F}` | 8399 | Image, Y, X, Altitude |
| `{0E9850E2-73E1-4538-B2CF-B18BEF6CECEB}` | 8433 | Image, X, Y, Altitude, XAccuracy, YAccuracy, AltitudeAccuracy |
| `{EFEB661F-A61E-460E-9499-386ACABBD0F6}` | 8434 | Image, Y, X, Altitude, YAccuracy, XAccuracy, AltitudeAccuracy |
| `{35CD8B84-6573-417D-8FEE-BE8BBEEC00D3}` | 8435 | Image, X, Y, Altitude, Yaw, Pitch, Roll |
| `{80D679DC-DE9C-4866-883D-D2C4EFB24CC6}` | 8438 | Image, Y, X, Altitude, Yaw, Pitch, Roll |
| `{97F08A22-F231-4AB4-A2FD-6FA42BB6D663}` | 8436 | Image, X, Y, Altitude, XAcc, YAcc, AltAcc, Yaw, Pitch, Roll |
| `{11B6FED7-9EAB-4630-BC34-4412249845C1}` | 8439 | Image, Y, X, Altitude, YAcc, XAcc, AltAcc, Yaw, Pitch, Roll |
| `{E2805200-B171-41FE-B6A3-54FA0AC475CA}` | 8440 | Image, X, Y, Altitude, Omega, Phi, Kappa |
| `{2C4786DD-02C6-4C59-810F-AE352B283846}` | 8442 | Image, Y, X, Altitude, Omega, Phi, Kappa |
| `{79B6904A-F60B-4CF0-8711-027CF1B472B6}` | 8441 | Image, X, Y, Altitude, XAcc, YAcc, AltAcc, Omega, Phi, Kappa |
| `{BEE6BAAD-BF18-41D3-8072-45E2228A4925}` | 8443 | Image, Y, X, Altitude, YAcc, XAcc, AltAcc, Omega, Phi, Kappa |
| `{80679981-0DF8-43DE-ABF7-35CCD8563320}` | 8437 | **Custom** — parser body is the placeholder `$(customDef)`, filled from the dialog's *Custom format description* field |
| `{B438A617-2434-5A24-C1B7-58980F28345A}` | 2345 | **NOT SHIPPED BY EPIC** — added by this repo, see below |

#### The 13-column custom format added here

```xml
<format id="{B438A617-2434-5A24-C1B7-58980F28345A}" descID="2345"
        desc="Name,X (East), Y (North), Altitude, XAccuracy, YAccuracy, AltitudeAccuracy, YawAccuracy, PitchAccuracy, RollAccuracy"
        reader="RealityScan.Import.CSVFlightLog">
    <parser allowedSeparators=",; &tab;" comment="#" showIgnoreFirstline="true" qualifiers="&quot;optional">
        <Image           index="0"  format="name.ext"/>
        <X               index="1"  format="value"/>
        <Y               index="2"  format="value"/>
        <Altitude        index="3"  format="value"/>
        <XAccuracy       index="4"  format="value"/>
        <YAccuracy       index="5"  format="value"/>
        <AltitudeAccuracy index="6" format="value"/>
        <Yaw             index="7"  format="value"/>
        <Pitch           index="8"  format="value"/>
        <Roll            index="9"  format="value"/>
        <YawAccuracy     index="10" format="value"/>
        <PitchAccuracy   index="11" format="value"/>
        <RollAccuracy    index="12" format="value"/>
    </parser>
</format>
```

Facts about this block, all load-bearing:

- **It is a hand-edit of an Epic-shipped file.** The installed `flightlogs.xml` has mtime
  `2026-07-25 07:31` while every sibling XML in the install root is `2026-07-21 05:07` — the
  merge is visible in the filesystem. It must be re-applied and re-verified after **any**
  RealityScan update or repair install. [VERIFIED: directory listing + PRIORS_DISTORTION_TEST_PLAN
  audit item 1, 2026-07-25]
- **Before 2026-07-25 the GUID was referenced but not installed.** `FlightLogParams.xml`
  named `{B438A617…}`; stock 2.2 `flightlogs.xml` did not contain it. Consequence:
  **every import before that date silently dropped yaw/pitch/roll and all per-image
  accuracies**. No error was raised. Any registration or scale result measured before
  2026-07-25 that is attributed to orientation priors or to per-image accuracies is
  attributing to something that never arrived. [VERIFIED: PRIORS_DISTORTION_TEST_PLAN audit
  item 1, 2026-07-25]
- **Its `desc` string is wrong** — it lists 10 names while the parser defines 13 columns and
  omits Yaw/Pitch/Roll from the description. The `desc` is only a dialog label, so this is
  cosmetic, but it makes the format hard to recognise in the GUI list.
  [VERIFIED-by-inspection, 2026-08-04]
- The stock 10-column `{97F08A22-…}` is the **no-admin fallback**: it carries position,
  position accuracies and YPR but no orientation accuracies, and it ships with the product,
  so a machine without a merged `flightlogs.xml` can still import a trajectory by pointing
  `gpsLogFileFormat` at it and letting the global `sfmCameraPriorAccuracyYaw/Pitch/Roll`
  supply orientation accuracy. [VERIFIED: PRIORS_DISTORTION_TEST_PLAN, "Standing corrections
  folded in"]
- The 7-column position-only `{0E9850E2-…}` is what cell **PD-6** used (its cell file is
  `FlightLogParams_4Q.xml`) — the only production cell here that was genuinely
  orientation-free. [VERIFIED: FINDINGS 2026-07-26, by reading the two params files rather
  than assuming they matched]

#### [CONTRADICTED] Did the pre-2026-07-25 runs import orientation at all?

Two [VERIFIED] entries in this repo's own record cannot both be true, and the answer decides
what the H2023 scale collapse (§6.1) can be attributed to.

- **Side A — no.** `PRIORS_DISTORTION_TEST_PLAN` audit item 1 (2026-07-25): the custom
  13-column format "was NEVER INSTALLED … orientation (YPR) and per-image accuracies were
  silently dropped on **every import to date**", corroborated by the GUI showing "Global
  camera prior settings". The installed `flightlogs.xml` mtime is `2026-07-25 07:31`.
- **Side B — yes.** FINDINGS 2026-07-26, "CORRECTION to the contamination-flag scope":
  "production `FlightLogParams.xml` → `{B438A617-…}` … with `ifUseOriAcc=true`. So the
  **2026-07-24 fresh-run aligns (zone_1/2/3) DID import orientation, at the then-current
  3/5/3 accuracies**." That correction is what added "(c) orientation priors REMOVED" as the
  third difference between the fresh run (hull scale 0.175) and PD-6 (0.981).
- **The conflict:** the 2026-07-24 fresh run predates the `flightlogs.xml` merge by a day.
  If Side A holds, `gpsLogFileFormat` named a GUID the app could not resolve, so no YPR and
  no per-image accuracy columns reached the solver — and difference (c) evaporates, taking
  "tight, possibly mis-composed orientation priors" off the candidate list for the 0.175
  collapse. Side B reasons from the params file's *contents* and never checks whether the
  named format existed on disk at run time.
- **Cheapest probe** (~4 min, one boot, and it settles §9 items 2, 3 and 11 partially):
  temporarily rename the `{B438A617-…}` block out of `flightlogs.xml`, import the 13-column
  log on the smoke fixture with the production params XML, and `-exportReport` a template
  emitting `$(inputIsOrientationPrior)` / `$(inputIsPriorAccuracy)` / `$(inputAccuracyYaw)`
  (§7). Restore the block afterwards. Whatever RealityScan does with an unresolvable format
  GUID — fall back to a default format, import position only, or fail — is directly readable.
  Until then, **treat every orientation-prior attribution made on data older than
  2026-07-25 as unfounded in both directions.**

### 2.4 The full `<Variable>` vocabulary

Every element name accepted inside `<parser>` for `reader="RealityScan.Import.CSVFlightLog"`
[OFFICIAL: tools/defineimportformat, "Flight Log"]:

| Element | Meaning |
|---|---|
| `Image` | image name **including the whole path and the format extension** (see §2.5 — observation differs) |
| `Longitude` / `LongitudeAccuracy` | geographic longitude and its accuracy |
| `Latitude` / `LatitudeAccuracy` | geographic latitude and its accuracy |
| `X` / `XAccuracy` | projected X of the camera position and its accuracy |
| `Y` / `YAccuracy` | projected Y and its accuracy |
| `Altitude` / `AltitudeAccuracy` | Z / altitude and its accuracy |
| `Yaw` / `YawAccuracy` | prior yaw rotation and accuracy |
| `Pitch` / `PitchAccuracy` | prior pitch rotation and accuracy |
| `Roll` / `RollAccuracy` | prior roll rotation and accuracy |
| `Omega` / `OmegaAccuracy` | prior omega — **only for georeferenced scenes** |
| `Phi` / `PhiAccuracy` | prior phi — only for georeferenced scenes |
| `Kappa` / `KappaAccuracy` | prior kappa — only for georeferenced scenes |
| `FocalLength` | prior calibration focal length |
| `PrincipalU` / `PrincipalV` | prior principal point x / y |
| `Skew` | prior camera skew coefficient |
| `AspectRatio` | prior pixel aspect ratio correction factor |
| `RadialDistortion1` … `RadialDistortion4` | prior radial distortion coefficients |
| `TangentialDistortion1` / `TangentialDistortion2` | prior tangential distortion coefficients |

**A flight log can therefore carry calibration priors as well as pose priors.** None of the
14 shipped formats uses the calibration variables; a custom `<format>` with `FocalLength`,
`PrincipalU/V`, `AspectRatio`, `Skew` and the distortion coefficients would let one text
file deliver per-image intrinsics, which is otherwise only possible through per-image XMP
sidecars. This has never been exercised here. [OFFICIAL for the vocabulary]
[OPEN — §9 item 6.] Note the read-back exists: `$(inputF)`, `$(inputK1..K4)`,
`$(inputT1/T2)`, `$(inputLensModel)` and `$(inputCalibrationPriorType)` report what arrived
(§7), so the probe is self-checking.

Axis convention, **internally contradictory in the Help**:

| Source | Yaw | Pitch | Roll |
|---|---|---|---|
| `tools/flightlogimport` — "Euler angles order (YPR) … around the X (Roll), Y (Pitch), and Z (Yaw) axes in the North-East-Down (NED) coordinate system" | Z | Y | X |
| `tools/defineimportformat` — "Yaw Prior yaw rotation (around Y-axis) … Pitch … (around X-axis) … Roll … (around Z-axis)" | Y | X | Z |
| `appbasics/reports_fav_images` — `inputYaw` "(around y axis)", `inputPitch` "(around x axis)", `inputRoll` "(around z axis)" | Y | X | Z |

[CONTRADICTED: internal to Epic's own Help. Two pages agree on Yaw=Y/Pitch=X/Roll=Z, one on
the standard NED Yaw=Z/Pitch=Y/Roll=X.] The NED reading is the aviation/marine standard and
is the one the flight-log dialog itself states, so it is the safer assumption — but it has
never been settled empirically here. The corroborating datum from the export side: the
shipped registration export format "Comma-separated, Name, X/Lon, Y/Lat, Z/Alt, Yaw, Pitch,
Roll" carries `EulerFormat="zyx"` while the Omega/Phi/Kappa format carries
`EulerFormat="xyz"` — i.e. YPR composes about z, then y, then x, which matches the NED
reading. [VERIFIED-by-inspection: `C:\Program Files\Epic Games\RealityScan_2.2\calibration.xml`,
formats `{121D2018-5016-4A4D-95BB-46382F54CD64}` and `{B3EE1544-1D64-4C22-A47D-FC9F78C107B7}`]

For the OPK family the frame is different: "around the X (Omega), Y (Phi), and Z (Kappa)
axes in the **East-North-Up (ENU)** coordinate system. The rotation order is evaluated from
right to left." [OFFICIAL: tools/flightlogimport]

### 2.5 Name matching is by BASENAME

[CONTRADICTED]

- **Docs say:** `Image` is the "image name including the whole path and the format
  extension". [OFFICIAL: tools/defineimportformat]
- **Observed:** bare basenames match. On NA167 zone_13, a log whose first column held only
  `<file>.jpg` matched images physically living in `wca/` and `zeuss/` subfolders of the
  scene's added folder — 34 + 904 images, 93.4% subsequently registered. Conversely,
  `geoall.py` writes `<CameraType>/<file>.jpg` and those logs import too.
  [VERIFIED: `testing/FINDINGS.md` [NA167 #5], 2026-07-22 — "34 wca + 904 zeuss images in
  subfolders, bare-filename log, 93.4% registered, no err:18002"; and
  `testing/NA167_SESSION_NOTES.md` §`-importFlightLog` — "Name matching is by **basename** and
  finds images in subfolders (verified: bare filenames matched images living in `wca/` and
  `zeuss/`)". Prefixed form: `geoall.py` line 752.]
- **Reading:** matching is on the file **basename**, and RealityScan searches the scene's
  images for a basename match regardless of directory depth. A leading path component is
  tolerated and effectively ignored.
- **Consequence — a real hazard.** If two images in one scene share a basename (the zone
  batcher here **copies** overlap images into two zone folders), one trajectory row cannot
  distinguish them. Measured symptom: `cluster_0`'s merge scene held **4,865 cameras** while
  its union flight log held only **4,227 rows** — a 638-row gap that is exactly the
  duplicated-basename population. [VERIFIED: HANDOFF loose end #6, 2026-07-28] The queued
  fix is a common image pool (imagelists or hardlinks) instead of copies.

### 2.6 err:18002 / 0x820000FF — rows not in the scene

The single most important operational fact about `-importFlightLog`.

- **Behavior:** when the log contains rows naming images that are not in the current scene,
  RealityScan completes the import for every present image, writes
  `Trajectory imported successfully.` into `%LOCALAPPDATA%\Temp\RealityScan.log`, **and
  reports the process as FAILED** with `err:18002` — "The file contains N images which are
  not in the current scene". The process result code delivered to the completion hook is
  decimal `2181038335` = hex `0x820000FF`, a warning class.
  [VERIFIED: FINDINGS 2026-07-21; docs/code-review-2026-07 §"False failure on import"]
- **The errors marker carries only the numeric code**, never the `err:NNNN` text — that
  exists only in `RealityScan.log`, which is truncated on every instance boot. Tolerant
  handlers must match `2181038335`. [VERIFIED: FINDINGS 2026-07-23]
- **It is genuinely benign.** Proven by cross-check rather than assumed: all 102 images that
  a union-log import reported as "not found in the current scene" were matched against every
  component manifest — **zero overlap**; they were exactly the unregistered remainder
  (4,598 log rows − 4,496 cameras = 102). [VERIFIED: FINDINGS 2026-07-25]
- **Therefore: filter logs to the scene**, or tolerate the code deliberately. This repo does
  both — `BatchDirectory` writes a per-zone log filtered to that zone's images, and
  `merge_zones.build_union_flight_log` filters the union to the attributed member basenames.
  Where filtering is impossible the workflow uses a dedicated tolerant runner.

The tolerant runner from `RS_CLI/Scripts/MergeZoneComponents.bat` is the pattern to copy
(executable lines reproduced exactly; `rem`/`echo` commentary elided). Note that it **moves**
the marker rather than deleting it, so the evidence survives:

```bat
:run_geoimport
%RealityScan% -delegateTo %RS_INSTANCE% %*
if errorlevel 1 (
    echo ERROR: Failed to delegate command: %*
    exit /b 1
)
ping -n 3 127.0.0.1 >nul
%RealityScan% -waitCompleted %RS_INSTANCE%
ping -n 2 127.0.0.1 >nul
%RealityScan% -waitCompleted %RS_INSTANCE%
if exist "%ErrorsFile%" (
    for %%A in ("%ErrorsFile%") do if %%~zA GTR 0 (
        %SystemRoot%\System32\findstr.exe /c:"2181038335" "%ErrorsFile%" >nul
        if errorlevel 1 (
            echo ERROR: RealityScan reported a failure during: %*
            exit /b 1
        )
        move /y "%ErrorsFile%" "%ErrorPath%\expected_18002_%RS_INSTANCE%.txt" >nul
    )
)
exit /b 0
```

- [OPEN] **The tolerance is too broad.** It accepts *any* `0x820000FF`, and no other
  warning-class flight-log failure has been enumerated. A wrong-CRS import or a malformed
  row might also report `0x820000FF`, in which case a real defect would be swallowed.
  Hardening cell **U10**; cheapest probe: on the smoke fixture, import (a) a log with a
  deliberately wrong-zone params XML and (b) a corrupt log, and read the resulting codes. If
  either is also `0x820000FF`, add a `RealityScan.log` grep for the literal string `18002`
  as a second factor. Never run.

**Adjacent trap that presents identically.** If `-addFolder` did not recurse — because
`appIncSubdirs` was not set — the scene has zero images, so *every* log row is "not in the
scene" and the same `0x820000FF` fires. A 25-second "successful" zone align with
`Added 0 layer images` in the log is the signature. Always
`-set "appIncSubdirs=true"` before `-addFolder`. [VERIFIED: FINDINGS 2026-07-23]

> **Reading the repo's own notes on this:** `testing/NA167_SESSION_NOTES.md`, under
> `-addFolder`, still says "in our 2.2 build subfolders were included **without** setting the
> key (zone_13: wca/ + zeuss/ both imported)". That line is **SUPERSEDED**. FINDINGS
> 2026-07-23 reconciles it: "that run had `appIncSubdirs` set by the fixed workflow; **the
> flag, not the build, is the variable**." Treat recursion as OFF by default and set the key
> explicitly every time. [CONTRADICTED then RESOLVED: NA167 §`-addFolder` vs
> FINDINGS 2026-07-23 nuance on [NA167 #5]]

### 2.7 The params XML: `FlightLogParams.xml` in full

The second argument of `-importFlightLog` / `-importTrajectory` is a `<Configuration>` file
saved from the GUI's Import Trajectory dialog. This repo's template, verbatim
(`modules/realityscan_interface/RS_CLI/Metadata/FlightLogParams.xml`):

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

`{93DBD041-AE1C-4631-89BC-D9430FCED843}` is the value in the shipped template and survives
every regeneration: `write_flight_log_params` rewrites exactly two `<entry>` values and
copies everything else byte-for-byte, so the id is never touched.
[VERIFIED-by-inspection: `modules/flight_logs.py`, `RS_CLI/Metadata/FlightLogParams.xml`,
2026-08-04] The reading that the id identifies the *dialog* whose settings the file encodes
is [INFERRED] — it matches how `AlignmentParams.xml` carries its own distinct
`{E377B69D-FB4B-4833-9CBE-FF747B7AF6D9}`, but no doc states it and it has not been tested.
What would settle it: save params from two different GUI dialogs and compare the ids.

| Key | Type | Repo value | Meaning | Status |
|---|---|---|---|---|
| `gpsLogFileFormat` | GUID | `{B438A617-…}` | selects a `<format>` from `flightlogs.xml` | **live** — present in the 2.2 binary string table [VERIFIED] |
| `CoordinateSystemFlightLog` | PROJ.4 string | `+proj=utm +zone=57 +south +datum=WGS84 +units=m +no_defs` | the CRS **the log's numbers are in** | **live** [VERIFIED] |
| `CoordinateSystemFlightLogType` | label | `epsg:32757 - WGS 84 / UTM zone 57S` | human-readable CRS label; matches `epsg.xml`'s `desc` | **live** [VERIFIED] |
| `csvFLSep` | int | `1` | separator selection for the flight-log CSV | **live** [VERIFIED] |
| `csvFLIgn` | bool | `true` | ignore first line | **live** [VERIFIED] |
| `ifCSopt` | int | `1` | coordinate-system option | **live**; value semantics [UNDOCUMENTED] |
| `ifKGrp` | int | `2` | "Automatically group camera calibration" — group all / by focal length / do not group | **live**; value→option mapping [UNDOCUMENTED] |
| `ifuuInhEn` | bool | `true` | accuracy inheritance enabled | **live**; [INFERRED] = "Accuracy settings source" |
| `ifuuInh` | int | `0` | accuracy inheritance mode | **live**; [INFERRED] `0` mirrors `inpPriorAccuracyInh=0` "Global camera prior settings" |
| `ifKmode` | hex | `0x0` | believed to carry "Camera mount" | **INERT** — see §2.8 |
| `ifUsePosAcc` | bool | `true` | believed to mean "take position accuracies from the file" | **INERT** — see §2.8 |
| `ifUseOriAcc` | bool | `true` | believed to mean "take orientation accuracies from the file" | **INERT** — see §2.8 |

The dialog options these keys correspond to, per Epic
[OFFICIAL: tools/flightlogimport]: *File name*, *File format*, *Custom format description*,
*Euler angles order (YPR)*, *Euler angles order (OPK)*, *Camera mount* (only when YPR is in
the format), *Camera coordinate system* (only when OPK is in the format), *Values
separator*, *Ignore first line*, *Coordinate system*, *Automatically group camera
calibration*, *Accuracy settings source*.

### 2.8 Inert keys and the real binary key names

Method: the 2.2 `RealityScan.exe` string table was extracted and filtered to settings-key
shape. Presence of a string is weak evidence a key is live; **absence is strong evidence it
is not**, because a key the binary never compares against cannot be honoured.
[VERIFIED-by-inspection: scratchpad `exe_keys_u16.txt` / `exe_keys_u16b.txt`, 2026-08-04]

**Three keys in this repo's `FlightLogParams.xml` do not exist in the 2.2 binary at all:**

| Key in the repo file | Status | Nearest real key |
|---|---|---|
| `ifKmode` | **absent from the binary — inert** | `ifKModel` (capital M) is present |
| `ifUsePosAcc` | **absent from the binary — inert** | `ifuuInhEn` / `ifuuInh` are present |
| `ifUseOriAcc` | **absent from the binary — inert** | as above |

[CONTRADICTED: repo assumption vs binary evidence.] This **supersedes** the long-standing
in-repo reading that `ifKGrp` and `ifKmode` are "the only plausible carriers of the Euler
angles order and Camera mount import settings" (FINDINGS 2026-07-26, HANDOFF loose ends #5
and #7). `ifKGrp` is real; `ifKmode` is not, and Euler order and mount are carried
elsewhere.

**The real flight-log import keys present in the 2.2 binary**, none of which appear in any
installed XML and none of which are documented [UNDOCUMENTED / VERIFIED-by-inspection]:

| Key | [INFERRED] meaning from the dialog vocabulary |
|---|---|
| `gpsLogFileName` | selected trajectory file |
| `gpsLogFolder` | last-used folder |
| `gpsLogFileFormat` | format GUID (this one *is* in the repo file) |
| `gpsLogCustomFormat` | the *Custom format description* string, i.e. `$(customDef)` |
| **`gpsLogEulerAnglesOrderYPR`** | **the "Euler angles order (YPR)" dropdown** |
| **`gpsLogEulerAnglesOrderOPK`** | the "Euler angles order (OPK)" dropdown |
| **`gpsLogMount`** | **the "Camera mount" dropdown** |
| `gpsLogCameraAxes` | the "Camera coordinate system" dropdown (OPK only) |
| `ifKModel` | calibration model on import |
| `ifDistortionmode`, `ifRmode`, `ifTmode` | distortion / rotation / translation prior modes on import |
| `ifOfsX`, `ifOfsY`, `ifOfsZ` | **lever-arm offsets** applied at import |
| `ifOfsRR`, `ifOfsRP`, `ifOfsRY` | **mount roll / pitch / yaw offsets** applied at import |
| `ifOfsifuUseOffset` | master enable for the `ifOfs*` offsets |
| `csvGCSep` / `csvGCIgn` | separator / ignore-first-line for ground control |
| `csvCPMSep` / `csvCPMIgn` | same for control-point measurements |
| `csvDDIgn` | ignore-first-line for distance definitions |

Two consequences worth acting on:

1. **The `ifOfs*` family is RealityScan's own lever-arm / boresight compensation.** This is
   no longer a guess from key names: the report side exposes the same concept explicitly as
   `inputIsInsOffsetValid` — "true if offset between **camera center and position sensor**
   is defined" — with `inputInsOfsX`, `inputInsOfsY`, `inputInsOfsZ`, `inputInsOfsYaw`,
   `inputInsOfsPitch`, `inputInsOfsRoll`. [OFFICIAL: appbasics/reports_fav_images] So
   RealityScan models an INS/camera lever arm and boresight natively, `ifOfsX/Y/Z` +
   `ifOfsRR/RP/RY` are the import-side setters, and `ifOfsifuUseOffset` is the master enable.
   [INFERRED for the key↔variable pairing; the report variables themselves are [OFFICIAL].]

   This pipeline instead bakes the lever arm and mount angles into the flight log upstream
   (`geoall.py::apply_camera_position_offset` and `convert_to_rc_orientation`, driven by the
   `MOUNTS` table in `modules/georeference/georeference_images.py`). Both approaches are
   valid; they must not be applied twice. Since `ifOfsifuUseOffset` is not written by this
   repo's params file, whatever the instance last held governs — another reason to pin every
   key you depend on. **And this is now cheaply checkable:** `-exportReport` a template
   emitting `$(inputIsInsOffsetValid)` and `$(inputInsOfsZ)` after an import. If it comes
   back true with a non-zero offset, the instance is applying an offset on top of the one
   already baked into the log. One boot, ~1 min. Never run.
2. **Orientation-prior attribution before the keys are pinned is unsafe.** Every conclusion
   here about whether orientation priors help or hurt was measured through an import path
   whose Euler order and mount were never set explicitly. Registration counts stand as
   measurements; the *attribution* to "orientation priors" does not. Affected cells: PD-0,
   PD-0b, PD-1b, PD-4, M-DIV-ORI. Not affected: PD-6 (position-only), all scale-oracle
   results, and rig-internal geometry. [VERIFIED-as-flag: FINDINGS 2026-07-26]

### 2.9 Euler angle order, camera mount, camera axes

[OFFICIAL: tools/flightlogimport]

- **Euler angles order (YPR)** — "the rotation order around the X (Roll), Y (Pitch), and Z
  (Yaw) axes in the North-East-Down (NED) coordinate system. **The rotation order is
  evaluated from right to left.**"
- **Euler angles order (OPK)** — same, around X (Omega), Y (Phi), Z (Kappa), in
  **East-North-Up (ENU)**.
- **Camera mount** — "Specifies how the camera is mounted relative to the coordinate system
  of the platform on which it is installed. **This option is available when Yaw-Pitch-Roll
  rotations are included in the file format.**"
- **Camera coordinate system** — "the convention of the coordinate system axes. Available
  when Omega-Phi-Kappa rotations are included."

The **option values** each dropdown offers are not enumerated anywhere in the Help, and the
keys that carry them (`gpsLogEulerAnglesOrderYPR`, `gpsLogMount`, `gpsLogCameraAxes`) are not
written by this repo's params file. **A YPR flight log therefore imports under whatever
order and mount the instance last held.** Three specific consequences, all recorded here:

1. **Composition order.** This repo's angles are written assuming intrinsic
   Roll → Pitch → Yaw. If the instance's default `gpsLogEulerAnglesOrderYPR` composes in a
   different order, the composition is wrong **even though every individual angle is right**
   — and nothing reports it. [VERIFIED-as-risk: FINDINGS 2026-07-26]
2. **Double-applied mount.** The mount is already baked into the exported angles here
   (`camera_offset` added in `convert_to_rc_orientation`). A non-identity default in the
   *Camera mount* dropdown would apply it a **second** time. [VERIFIED-as-risk:
   FINDINGS 2026-07-26]
3. **Near-singular Port geometry.** The Port camera's pitch sits at **~88°**, within 2° of
   the 90° degeneracy where the roll and yaw axes of this parameterisation collapse
   (gimbal lock). Small pitch noise then produces large attitude swings — a plausible
   contributor to the behaviour of any component dominated by Port frames.
   [VERIFIED: FINDINGS 2026-07-26]

For a rig with a 45° down-looking camera and a horizontal camera on one vehicle none of
these is a detail: a wrong mount or order maps attitude error into focal and scale error.
[UNDOCUMENTED for the option values; VERIFIED-as-risk for 1–3]

- [OPEN] What are the allowed values of `gpsLogEulerAnglesOrderYPR` and `gpsLogMount`, and
  which value is the default? **Cheapest probe** (one minute, needs the GUI once): open the
  Import Trajectory dialog on the 13-column format, save params at defaults, change **only**
  *Euler angles order (YPR)*, save again, change **only** *Camera mount*, save again — three
  XMLs; diff them. A pure-CLI alternative: align the smoke fixture with orientation priors
  at several `-set`/params values and read the resulting camera attitudes out of the pose
  XMPs (~2 min per cell). Neither has been run. HANDOFF loose ends #5 / #7.

**Owner decision in force:** orientation priors ON at alignment with a conservative **15°**
YPR accuracy, with the metric-scale oracle (§6) as the named mitigation. The concern above
was raised and overruled, and is recorded. [VERIFIED-as-decision: FINDINGS 2026-07-26]

That decision is empirically supported: **removing orientation priors destroyed two H2024
zones.** A position-only re-alignment of all five zones gave zone_1 0.989 (5 components vs
8), zone_2 1.014, zone_4 0.904 (3 vs 5) — but **zone_3 and zone_5 registered nothing at
all**: zero components, empty harvest, `Identity capture finished after 0 component(s)`
after 12.7 and 32.4 minutes. Orientation priors are load-bearing for registration on this
data, not harmful. [VERIFIED: HANDOFF 2026-07-27; results at
`F:/na156_h2024/ab_position_only/ab_results.json`]

### 2.10 Accuracies: what the numbers mean and what they do

Two independent sources of prior accuracy exist:

1. **Per-image, from the log** — the `*Accuracy` columns of the selected format.
2. **Global, from alignment settings** — `-set` keys, applied to any image without a
   per-image value. [OFFICIAL: appbasics/camerasettings_priors, "Accuracy settings source"]

| Key | Type | App default | Meaning | Source |
|---|---|---|---|---|
| `sfmEnableCameraPrior` | bool | `true` | "Use camera priors for georeferencing" — the master switch that makes priors participate in the bundle adjustment and makes the resulting components georeferenced | [OFFICIAL: tutorials/setkeyvaluetable] [VERIFIED-as-in-use: settings-evaluation §4] |
| `sfmCameraPriorAccuracyX` | float | `10.0` | position X accuracy, project-CRS units | [OFFICIAL] |
| `sfmCameraPriorAccuracyY` | float | `10.0` | position Y accuracy | [OFFICIAL] |
| `sfmCameraPriorAccuracyZ` | float | `20.0` | position Z accuracy | [OFFICIAL] |
| `sfmCameraPriorWeight` | float | `1.0` | "Position prior hardness" | [OFFICIAL] |
| `sfmCameraPriorAccuracyYaw` | float | `10.0` | yaw accuracy, degrees | [OFFICIAL] |
| `sfmCameraPriorAccuracyPitch` | float | `10.0` | pitch accuracy | [OFFICIAL] |
| `sfmCameraPriorAccuracyRoll` | float | `10.0` | roll accuracy | [OFFICIAL] |
| `sfmCameraPriorWeightOrientation` | float | `1.0` | "Orientation prior hardness" | [OFFICIAL] |
| `sfmMergeGeoreferencedComponents` | bool | `false` | allow georeferenced components to merge without visual overlap | [OFFICIAL: appbasics/alignsettings] — **never observed to work headless**, see `08-components-and-merge.md` |

**A trap that has cost real runs here.** The GUI's settings exporter writes the accuracy keys
under generated ids, not their documented names. In this repo's `AlignmentParams.xml` they
appear as:

| Exported id | Value | [INFERRED] documented equivalent |
|---|---|---|
| `s235l` | `5.0` | `sfmCameraPriorAccuracyX` |
| `s236l` | `5.0` | `sfmCameraPriorAccuracyY` |
| `s237l` | `0.5` | `sfmCameraPriorAccuracyZ` |
| `s251l` | `0.05` | `sfmControlPointXAccuracy` |
| `s252l` | `0.05` | `sfmControlPointYAccuracy` |
| `s253l` | `0.1` | `sfmControlPointZAccuracy` |
| `s254l` | `0.001` | `sfmDefinedDistanceAccuracy` |

The identification is [INFERRED] from slot order and from the values matching the documented
defaults (`0.05 / 0.05 / 0.10` for control points). None of the `s###l` strings occurs in the
2.2 binary string table, so they are almost certainly indices generated at export time.

Every repo workflow applies the params file by filtering it to keys beginning `sfm` or `lis`:

```bat
for /f usebackq^ tokens^=2^,4^ delims^=^" %%A in ("%AlignmentParams%") do (
    echo %%A| %SystemRoot%\System32\findstr.exe /b /c:"sfm" /c:"lis" >nul
    if not errorlevel 1 %RealityScan% -delegateTo %RS_INSTANCE% -set "%%A=%%B"
)
```

**Therefore the `s###l` accuracies have never been applied**: the *global* position-accuracy
and defined-distance settings in force were RealityScan's defaults `10.0 / 10.0 / 20.0` and
`0.10`, while the params file claimed `5.0 / 5.0 / 0.5` and `0.001`. This matters because
prior *hardness* (`sfmCameraPriorWeight=10.0`) was tuned on the assumption that the
accuracies bounded the trust envelope. **Fix:** emit the documented `sfm*` names explicitly,
e.g. `-set "sfmCameraPriorAccuracyZ=0.5"`. [VERIFIED: code reading of `AlignZone.bat`
lines 85–88 against `AlignmentParams.xml`, 2026-08-04]

**The asymmetry that makes this easy to misread.** The filter keeps any key starting `sfm`
or `lis`, so `AlignmentParams.xml`'s **orientation** accuracies *are* applied —
`sfmCameraPriorAccuracyYaw`, `…Pitch`, `…Roll` all carry `10.0` under their documented names
and all pass the filter, as do `sfmCameraPriorWeight=10.0`,
`sfmCameraPriorWeightOrientation=10.0`, `sfmEnableCameraPrior=true` and
`sfmControPointImageMeasAccuracy=4.0`. Only the **position** accuracies, the control-point
accuracies and the defined-distance accuracy were exported under `s###l` ids and therefore
silently dropped. [VERIFIED-by-inspection: `AlignmentParams.xml`, 2026-08-04]

**Consequence for every align before 2026-07-25** [INFERRED, from two [VERIFIED] facts —
the format GUID was not installed (§2.3) and `s237l` never reaches the app]: with no
per-image accuracy columns able to arrive, the globals governed, and the global Z accuracy
was the app default **`sfmCameraPriorAccuracyZ = 20.0` m** — not the `0.5` the params file
claimed and not the `1.0` the flight log's Alt-Accuracy column carried. A 20 m vertical
trust envelope on a hull survey whose depth sensor is good to ~0.1 m is a very different
solve from the one the run logs appear to describe. Settling this is the same probe as the
§2.3 contradiction.

**What the per-image accuracy number should be — measured, not guessed.** The decisive
experiment was a 2×2 on a 665-image known-good component (the bow), varying only the
position accuracy triple and the distortion model:

| cell | registered | components | scale (maximal) |
|---|---|---|---|
| `brown3_loose` (10 / 10 / 1) | 665/665 | **1** | 1.049 |
| `brown3_tight` (1 / 1 / 0.1) | 662/665 | 2 | 0.886 |
| `division_loose` (10 / 10 / 1) | 656/665 | **1** | **0.989** |
| `division_tight` (1 / 1 / 0.1) | 659/665 | 3 | 0.826 |

[VERIFIED: PRIORS_DISTORTION_TEST_PLAN "Bow 2×2", 2026-07-25]

Registration barely moved (656–665 in every cell) — which is exactly why a camera-counting
oracle never caught it. **Over-tight position priors fragment the solve and push metric
scale away from truth.** The lesson, now written into the code comments of both flight-log
writers: the accuracy columns want **end-to-end per-image position uncertainty** —
timestamp matching + nav interpolation + lever arm + dive-long drift — **not the
instantaneous sensor spec**. A DVL good to ~1 m and a Paro depth sensor good to ~0.1 m do
not justify writing `1 / 1 / 0.1`.

Values in force in this repo (`geoall.py` lines 723–729,
`georeference_images.py` lines 540–549):

```python
pos_x_acc = 10.0   # metres
pos_y_acc = 10.0   # metres
alt_acc   = 1.0    # metres
yaw_acc   = 15.0   # degrees
roll_acc  = 15.0   # degrees
pitch_acc = MOUNTS[family]['p_acc']   # 30.0 zeuss, 15.0 wca_port/wca_cinema,
                                      # 10.0 legacy_camupper/cammid, 5.0 legacy_camlower,
                                      # 10.0 fallback for an unknown mount
```

- [OPEN] The intermediate accuracy ladder (3 / 3 / 0.5 and 5 / 5 / 1) was queued and never
  run. Loose is **proven**, not proven **optimal**. Each cell is a ~70-minute zone_1
  re-align. HANDOFF 2026-07-25 open item 3.

### 2.11 Per-cruise CRS generation from the log filename

**The declared CRS must match the CRS the log's numbers are actually in. A wrong zone
imports silently and misplaces everything.** The template in this repo once said
`+proj=utm +zone=4` (EPSG:32604) — stale from an earlier project — while the cruise being
processed, NA173_H2103a, is UTM **57S** (EPSG:32757): wrong zone **and** wrong hemisphere,
with no error raised. [VERIFIED: NA167 #6; docs/code-review-2026-07 §"Wrong coordinate
system"; FINDINGS 2026-07-21/22]

The fix is to derive the CRS from the flight log's own filename tag, never to hand-edit the
template. `modules/flight_logs.py` is the single implementation:

```python
_SOUTH_BANDS = set('CDEFGHJKLM')       # MGRS latitude bands south of the equator
_NORTH_BANDS = set('NPQRSTUVWX')       # I and O are never used
_ZONE_IN_NAME = re.compile(r'_(\d{1,2})([C-HJ-NP-X])_UTM\.txt$', re.IGNORECASE)

def epsg_for_utm_zone(zone: int, band: str) -> int:
    """EPSG code for a WGS84 UTM zone: 326xx north, 327xx south."""
    return (32700 if band.upper() in _SOUTH_BANDS else 32600) + zone
```

`write_flight_log_params(template_path, output_path, zone, band)` copies the template and
rewrites exactly two entries:

```python
proj     = f'+proj=utm +zone={zone}{south} +datum=WGS84 +units=m +no_defs'   # south = ' +south' or ''
crs_type = f'epsg:{epsg} - WGS 84 / UTM zone {zone}{hemisphere}'
```

Worked examples, all round-tripped through the generator [VERIFIED: FINDINGS 2026-07-22]:

| Flight-log filename | zone, band | EPSG | `CoordinateSystemFlightLog` | `CoordinateSystemFlightLogType` |
|---|---|---|---|---|
| `flight_log_53N_UTM.txt` | 53, N | 32653 | `+proj=utm +zone=53 +datum=WGS84 +units=m +no_defs` | `epsg:32653 - WGS 84 / UTM zone 53N` |
| `flight_log_NA173_H2103a_57S_UTM.txt` | 57, S | 32757 | `+proj=utm +zone=57 +south +datum=WGS84 +units=m +no_defs` | `epsg:32757 - WGS 84 / UTM zone 57S` |
| `flight_log_4N_UTM.txt` | 4, N | 32604 | `+proj=utm +zone=4 +datum=WGS84 +units=m +no_defs` | `epsg:32604 - WGS 84 / UTM zone 4N` |

The generated PROJ strings are **byte-identical to `epsg.xml`'s own `params` attribute** for
those codes — confirmed by direct read of the shipped database:

```
32653  params="+proj=utm +zone=53 +datum=WGS84 +units=m +no_defs"
32757  params="+proj=utm +zone=57 +south +datum=WGS84 +units=m +no_defs"
32604  params="+proj=utm +zone=4 +datum=WGS84 +units=m +no_defs"
4326   params="+proj=longlat +datum=WGS84 +no_defs"
```

[VERIFIED-by-inspection: `C:\Program Files\Epic Games\RealityScan_2.2\epsg.xml`, 2026-08-04]

`find_flight_log(*directories)` is the **only** sanctioned way for any stage to locate a log
on disk. It searches every candidate directory for `flight_log*_UTM.txt` first, then falls
back to a legacy `flight_log.txt`, and resolves ties lexicographically for determinism. This
exists because the naming conventions diverged: producers wrote
`flight_log_<zone>_UTM.txt` while consumers looked for `flight_log.txt`, and the alignment
stage then **silently aligned without a trajectory at all**. [VERIFIED: NA167 #2; CLAUDE.md]

### 2.12 Side effect: import leaves images SELECTED

Flight-log import leaves every matched image **actively selected**. Exports are
selection-driven, and under `-silent` the "Export Selection" dialog is auto-answered — so a
subsequent XMP or component export silently writes **nothing**. Measured signature: an XMP
export that normally takes 20.5 s completed in **0.057 s** and produced no files.

**`-deselectAllImages` before every export is mandatory.** [VERIFIED: FINDINGS 2026-07-23]
[UNDOCUMENTED: the Help nowhere warns that import leaves a selection.]

### 2.13 Runnable examples

**A. Canonical per-zone align with a trajectory** (the shape of `RS_CLI/Scripts/AlignZone.bat`;
`%RealityScan%` is `C:\Program Files\Epic Games\RealityScan_2.2\RealityScan.exe`, and each
`:run` is delegate → grace → double `-waitCompleted` → errors-marker check — see
`01-cli-fundamentals.md`):

```bat
call :run -newScene
%RealityScan% -delegateTo %RS_INSTANCE% -set "appIncSubdirs=true"
call :run -addFolder "F:\na156_h2024\batched\zone_3"
call :run_geoimport -importFlightLog "F:\na156_h2024\batched\zone_3\flight_log_4N_UTM.txt" ^
                                     "F:\na156_h2024\run\FlightLogParams_4N.xml"
:: apply sfm*/lis* from AlignmentParams.xml as individual -set commands here
call :run -align
call :run -deselectAllImages
call :run -setMinComponentSize 50
call :run -save "F:\na156_h2024\components\zone_3\zone_3.rsproj"
```

Order is load-bearing and matches the shipped script: the `-set "appIncSubdirs=true"` is an
*instant* delegated set that must be queued **before** `-addFolder` (delegated commands run
FIFO, so it needs no completion wait); the settings sweep is queued before `-align` for the
same reason; and `-deselectAllImages` comes **after** `-align`, immediately before anything
selection-driven. [VERIFIED-by-inspection: `AlignZone.bat` lines 72–102, 2026-08-04]

**B. Georeferencing a merged component.** A merged component is a **new** component and is
**not** georeferenced by its parents' georeferencing. The merge scene must hold the
constraints itself, and `-update` is what applies them:

```bat
call :run -newScene
for /f "usebackq delims=" %%F in ("F:\na156_h2024\merged\cluster_0.complist") do call :run -importComponent "%%~F"
call :run_geoimport -importFlightLog "%RS_MERGE_FLIGHT_LOG%" "%RS_MERGE_FLIGHT_LOG_PARAMS%"
call :run -mergeComponents
call :run -update
call :run -deselectAllImages
call :run -save "F:\na156_h2024\merged\cluster_0.rsproj"
```

[VERIFIED: FINDINGS 2026-07-23 — the missing-georeferencing case was caught by owner GUI
inspection and called a showstopper, then confirmed by re-run.]

**C. Building the union log for a merge scene.** `merge_zones.build_union_flight_log`
walks the image root for every `flight_log*_UTM.txt`, dedupes rows by the **lowercased first
column exactly as written** (`line.split(';')[0].strip('"').lower()`), optionally filters to
the attributed member basenames, writes CRLF, and regenerates the CRS params from the first
log's zone tag:

```python
union_path  = os.path.join(output_dir, f'flight_log{suffix}_{zone}{band}_UTM.txt')
with open(union_path, 'w', encoding='utf-8', newline='\r\n') as f:
    f.write(header + '\n' + '\n'.join(rows.values()) + '\n')
params_path = write_flight_log_params(
    os.path.join(METADATA_DIR, 'FlightLogParams.xml'),
    os.path.join(output_dir, f'FlightLogParams_{zone}{band}.xml'), zone, band)
```

**Trap in that key choice.** Because the dedupe key is the whole first field, a log written by
`geoall.py` (`Zeuss/HERC/<file>.jpg`) and one written by the georeference module
(`<file>.jpg`) produce **different keys for the same image**: the union would carry both rows,
and `only_basenames` — which holds bare basenames from the component manifests — would match
**neither** of the prefixed ones, silently emptying the filtered union. In practice the
per-zone logs a merge consumes come from `BatchDirectory`, which writes bare names, so this
has not fired. It is one `os.path.basename()` away from being impossible.
[INFERRED from code reading, 2026-08-04; not observed in a run.]

**D. Setting coordinate systems at startup** [OFFICIAL: tutorials/commandline_4]:

```bat
RealityScan.exe -setProjectCoordinateSystem Local:1 ^
                -setOutputCoordinateSystem epsg:4326
```

---

## 3. Coordinate systems

### 3.1 The shipped databases

| File | Authority | Contents |
|---|---|---|
| `C:\Program Files\Epic Games\RealityScan_2.2\epsg.xml` | `epsg` | **6,756** `<cs>` entries — the EPSG database as shipped. 4.7 MB. [VERIFIED-by-inspection, 2026-08-04] |
| `C:\Program Files\Epic Games\RealityScan_2.2\local.xml` | `Local` | exactly two entries (below) [VERIFIED-by-inspection] |

`local.xml` in full:

```xml
<CoordinateSystems authority="Local">
    <cs id="1" desc="Euclidean"  params="+proj=geocent +ellps=WGS84 +no_defs" />
    <cs id="2" desc="Laboratory" params="+proj=geocent +ellps=WGS84 +units=mm +no_defs" />
</CoordinateSystems>
```

An `epsg.xml` entry carries three attributes that matter:

```xml
<cs id="32653" desc="WGS 84 / UTM zone 53N"
    paramsWKT="PROJCS[&quot;WGS_1984_UTM_Zone_53N&quot;,GEOGCS[…]]"
    params="+proj=utm +zone=53 +datum=WGS84 +units=m +no_defs"/>
```

- `desc` is the label the GUI search box matches and is what
  `CoordinateSystemFlightLogType` reproduces after the `epsg:<id> - ` prefix.
- `params` is the PROJ.4 string and is what `CoordinateSystemFlightLog` reproduces verbatim.
- `paramsWKT` is the ESRI-flavoured WKT.

"RealityScan is shipped with the EPSG database and a local database with Euclidean
coordinate system… You can create your own coordinate systems easily by editing/adding
database files (a properly formatted xml file)." [OFFICIAL: appbasics/coordinatesystem]
Adding a custom `<cs>` to a new file with its own `authority=` and importing it makes
`-setProjectCoordinateSystem <authority>:<id>` work for it. Never exercised here. [INFERRED]

The chosen coordinate system **determines the project's units of measurement**.
[OFFICIAL: appbasics/coordinatesystem] Note that `Local:2` ("Laboratory") is
`+units=mm` — selecting it silently makes every distance, accuracy, and defined-distance
number a millimetre figure.

### 3.2 The three CRS scopes

RealityScan holds more than one coordinate system at a time
[OFFICIAL: appbasics/coordinatesystem, tools/controlpoints]:

| Scope | Set by | Used for |
|---|---|---|
| **Project** coordinate system | `-setProjectCoordinateSystem authority:id`; GUI: WORKFLOW ▸ Settings ▸ Coordinate Systems ▸ Project coordinate system | the global reference for measuring, displaying coordinates, and accuracy reports |
| **Output** coordinate system | `-setOutputCoordinateSystem authority:id`; GUI: same panel ▸ Output coordinate system | model/mesh export; some export dialogs override it locally |
| **Per-object** coordinate system | the import params XML (`CoordinateSystemFlightLog`) for a trajectory; the import dialog for GCPs; `-editControlPointSelection` per control point | the CRS the *imported numbers* are in; RealityScan converts into the project CRS |

"Even every ground control point can be measured with respect to a different coordinate
system." [OFFICIAL] But: "It is advisable for all control points to be in the same
coordinate system as conversions may bring small inaccuracies." [OFFICIAL: appbasics/coordinatesystem]
Conversion errors "are caused by differences in mathematical models of the particular
coordinate systems and, in general, it is not possible to convert points with zero error."
[OFFICIAL: tools/controlpoints]

**Order matters for imports.** Both the trajectory and the GCP Help pages open with the same
instruction: *first* set the project coordinate system to the one the incoming data is in,
*then* import. [OFFICIAL: tools/flightlogimport, tools/gcpimport] This repo never calls
`-setProjectCoordinateSystem` — it relies entirely on `CoordinateSystemFlightLog` in the
params XML, and the resulting components are correctly georeferenced in the GUI. So the
project CRS is evidently not required for a trajectory import to place cameras correctly.
[VERIFIED-as-practice: every production run since 2026-07-21]
[OPEN] whether the unset project CRS degrades reported accuracies or the units of the
`sfmCameraPriorAccuracy*` keys; cheapest probe: `-exportReport` an
`$ExportProjectInfo`/`$(coordSystemName)`/`$(units)` template before and after
`-setProjectCoordinateSystem epsg:32604` on the smoke fixture.

### 3.3 Local frames, the anchor, and why XMP positions are not UTM

For numerical conditioning, "the components are calculated in coordinates that are kept
close to zero. **Anchor** (rotation + translation) transforms such a local scene into a
global Euclidean space":

```
EuclideanX = anchor.Rotation * X + anchor
```

with report variables `anchorX`, `anchorY`, `anchorZ`, `anchorR00` … `anchorR22`,
`anchorYaw`, `anchorPitch`, `anchorRoll`. [OFFICIAL: appbasics/reports_fav_basic, "Component
Anchor Variables"]

This is the documented explanation of the behaviour this repo discovered empirically:

- **`xcr:Position` in an exported XMP sidecar is in a grid-anchored LOCAL frame, not UTM**,
  and the lat/long attributes of those sidecars are garbage.
  [VERIFIED: NA167 §`-exportXMPForSelectedComponent`; confirmed on zone_9 by
  `poses2flightlog.py`, whose module docstring records "xcr:Position is local, the anchor is
  the grid origin, and the lat/long XMP attributes are garbage"]
  [OPEN] Hardening cell **U13** asks whether the same holds for an XMP exported from an
  *original georeferenced zone scene* (as opposed to a merge scene); the evidence above is
  from the merge/NA167 side. Probe: export XMP in zone_2's own scene and compare positions to
  that zone's flight log — one boot.
- `xcr:Position` appears as an **element** (`<xcr:Position>x y z</xcr:Position>`) in current
  exports and in **attribute** form in older ones. Both forms must be parsed. Exactly one
  reader here does — `modules/scale_oracle.py`:
  ```python
  POS_RE = re.compile(r'<xcr:Position>([^<]+)</xcr:Position>|xcr:Position="([^"]+)"')
  ```
  [VERIFIED: FINDINGS 2026-07-28]
  **`poses2flightlog.py` does not.** Its `POSITION_RE` is
  `re.compile(r'<xcr:Position>([^<]+)</xcr:Position>')` — element form only — so pointed at
  an older attribute-form export it reads **zero cameras** and fails the `MIN_CAMERAS = 3`
  check rather than mis-fitting. Loud, but it is a real coverage gap in the tool nominated as
  U7 proxy (b). `grow_zone.py`, `modules/camera_registry.py` and
  `modules/component_manifest.py` test for the substring `xcr:Position` only, which matches
  both forms. [VERIFIED-by-inspection: repo-wide grep, 2026-08-04]
- The XMP sample in Epic's own Help shows the element form together with
  `xcr:Coordinates="absolute"` and `xcr:PosePrior="initial"`.
  [OFFICIAL: tools/xmpalign]

**Converting local → UTM.** `poses2flightlog.py` estimates the rigid local→UTM transform by
least squares (Umeyama) between XMP camera positions and the matching flight-log priors,
then writes a refined 13-column flight log plus a per-image residual CSV. Two design points
are load-bearing:

- **Scale is locked at 1** (`with_scale=False`). The alignment already pins scale via the
  camera priors, and fitting scale against noise-dominated nav collapses it toward zero —
  **observed 0.5 on zone_9**. `--allow-scale` exists for diagnostics only.
- **The residual magnitude is an estimate of the USBL/DVL navigation error**, printed as
  mean / median / p95 / max and written per-image to `<output>_residuals.csv`.
- Orientations are deliberately **not** rewritten: the XMP rotation convention has not been
  validated against the flight-log convention (§2.9), so yaw/pitch/roll and their accuracies
  are carried over unchanged from the original log.

[VERIFIED-by-inspection + VERIFIED-as-behavior: `poses2flightlog.py`, docstring and
`umeyama_rigid`]

A georeferenced component should fit local→UTM at near identity with residuals on the order
of the nav error; a large or structured residual field is evidence the component is **not**
correctly georeferenced. This is one of the three candidate proxies for the still-open
headless georeferencing check (§7).

### 3.4 Export-side coordinate systems and scale

The model/registration export dialogs offer their own coordinate-system choice
[OFFICIAL: tools/export]:

| Option | Meaning |
|---|---|
| **Grid plane** | as seen in the 3Ds view — the local, anchored frame |
| **Project Output** | the output CRS from WORKFLOW ▸ Settings; available only when the model is georeferenced |
| **Shifted project output** | Project Output, translated to the centre of the scene |
| **Same as XMP** | whatever CRS the XMP metadata export used; available for non-georeferenced models too |

The GCP export offers the same three geo options (Grid plane / Project output / Shifted
project output), and "each ground control point has its own coordinate system and the
exporter transforms coordinates from this coordinate system to the one selected".
[OFFICIAL: tools/gcpexport]

Scene transformation on export — `Move X/Y/Z`, `Rotate X/Y/Z` (−180…180°), `Scale X/Y/Z` —
is the "scaling on export" mechanism: "setting the Scale X/Y/Z to 10 will make the model 10
times bigger". [OFFICIAL: tools/export] Do not use it to paper over a metric-scale error in
the solve: an export scale factor fixes the mesh's units and leaves the cameras, the sparse
cloud, and every derived measurement wrong.

`Export an info file` produces a `.rsinfo` XML "which contains important information about
the internal coordinate system and relations to the coordinate system in which the models
coordinates are exported". On re-import, RealityScan looks for `<model>.<ext>.rsInfo` and
uses it to restore placement. "**WARNING:** If you do not use the info file, then your
imported model may be shifted, rotated, and scaled in the scene with respect to the original
model and cameras." [OFFICIAL: tools/export]

`transformdb.xml` in the install root defines the named DCC **Transformation presets** —
`Blender`, `3ds Max`, `Maya`, `Maya + Arnold`, `Unity`, `Unreal` — as 24 `<transform>` rows,
one per (format, name) pair. `format` is one of `obj`, `fbx`, `abc`, or the catch-all
`!obj,!fbx,!abc`. Attributes are `normalFlip`, `rotation`, `scale`; **absent means identity**.
The scale factors are **not uniform across format groups** — this is the trap:

| `format` | which names carry `scale` |
|---|---|
| `!obj,!fbx,!abc` | `3ds Max` = `39.370039 39.370039 39.370039` (m → in); `Maya`, `Maya + Arnold`, **`Unreal`** = `100 100 100` (m → cm) |
| `obj` | `3ds Max` = `39.370039 …`; `Maya`, `Maya + Arnold` = `100 100 100`. `Unreal`, `Unity`, `Blender` carry **no scale** (rotation `-90 -90 0` only) |
| `abc` | same as `obj` |
| `fbx` | **no row carries `scale` at all** — only `normalFlip` |

So "export to Unreal" is a 100× enlargement for a `.ply`/`.xyz`-class output but identity for
`.obj`, `.fbx` and `.abc`. [VERIFIED-by-inspection: `transformdb.xml`, 2026-08-04] A preset
applied unintentionally is an instant 100× (or 39.37×) scale error in the deliverable.

---

## 4. Ground control points and control points

**No GCP or control point has ever been imported through this CLI.** Everything in this
section is [OFFICIAL] or [VERIFIED-by-inspection] of shipped schema files; nothing is
[VERIFIED] empirically here. The only adjacent empirical datum is staff-confirmed **absence
of stereo-rig support** in RealityScan (through Aug 2025), which implies that for a rigid
multi-camera rig, scale must come from GCPs, distance constraints, or locked XMP poses
rather than from a declared baseline. [VERIFIED-second-hand: COLMAP fact base F-20260723-27, quoted in `HANDOFF.md` §"PENDING
RECONCILIATION with LilyJean/COLMAP findings" — "No stereo-rig support in RealityScan
(staff-confirmed through Aug 2025): Voyis-rig scale must come from GCPs/distance
constraints/locked XMP". Second-hand from another project's fact base; not re-verified here.]
[OPEN: no GCP has ever been driven here — §9 item 16]

### 4.1 The three control-point types

[OFFICIAL: tools/controlpoints]

| Type | `gpType` | Purpose |
|---|---|---|
| **Tie Point** | `0` | ties images together — a manual correspondence where automatic matching failed (e.g. a large view-angle change). No real-world coordinate. |
| **Ground Control** | `1` | a tie point *plus* a physical coordinate. Participates in the optimisation. |
| **Ground Test** | `2` | a ground control point **excluded from the optimisation**, used purely to report deviation. |

Ground Test points exist to catch a specific pathology: "especially if a ground control point
is defined only in 2-3 images, it might happen that rather than a scene is corrected, the
system will shift those 2-3 images a little bit to make errors look smaller. However, the
scene will not be corrected and the typical banana effect will remain. Adding test points can
detect this easily, as their error will grow." Distribute test points evenly.
[OFFICIAL: tools/controlpoints]

Guidance on counts [OFFICIAL: tutorials/georeferencing, tools/gcpimport, tools/controlpoints]:

- 1 GCP defines the origin; 2 define origin **and scale**; 3 or more define the full
  coordinate system and orientation.
- Each point should have **at least two** image measurements; **three is recommended**.
- "RealityScan integrates advanced solvers which can solve the scene scale and orientation
  just by creating any 5 independent measurements." [OFFICIAL: tutorials/scaling]
- "Increasing the number of points and images assigned to them will improve the accuracy, but
  too many of them can also have a negative effect on the alignment."
- "Discrepancies of coordinates up to 5 cm are tolerable."
- Add control points **before** alignment where possible.

On weight: "The weight is one way of saying 'use this point and drop all natural points which
do not agree'. On the other hand, increasing the point weight will make the alignment
sensitive to errors in positioning of the point in the image. Even with the best efforts, it
is difficult for a human to place a point with a precision of under 3-4 pixels, while natural
points are placed with sub-pixel accuracy. **However, it is recommended to leave the default
weight value.**" [OFFICIAL: tools/controlpoints]

### 4.2 `-importGroundControlPoints` and `groundcontrol.xml`

`groundcontrol.xml` ships **four** formats, all with
`reader="RealityScan.Import.CSVGroundControl"`, `allowedSeparators=",; &tab;"`,
`comment="#;"` (note: **both** `#` and `;` are comment characters here, unlike the flight-log
reader's `#` alone), `showIgnoreFirstline="true"`, `qualifiers="&quot;optional"`.
[VERIFIED-by-inspection: `C:\Program Files\Epic Games\RealityScan_2.2\groundcontrol.xml`, 2026-08-04]

| GUID | `descID` | Columns |
|---|---|---|
| `{95EB0F80-BF22-4C4E-9DD9-C04C6C95E933}` | 8402 | Name, X, Y, Altitude |
| `{9BAC94F7-24F3-492A-879E-F0991C1FC192}` | 8403 | Name, Y, X, Altitude |
| `{28626CC0-6311-41FD-88EE-988A673A5CB8}` | 8406 | Name, X, Y, Altitude, XAccuracy, YAccuracy, AltitudeAccuracy |
| `{AFCF990C-36F7-4F27-86A4-DC9C1FE9D3A3}` | 8407 | Name, Y, X, Altitude, YAccuracy, XAccuracy, AltitudeAccuracy |

The `Name` element uses `format="name"`; coordinates use `format="value"`. `format="degrees"`
accepts DMS-with-cardinal input such as `N65 23 12.1`.
[OFFICIAL: tools/defineimportformat]

Available `<Variable>` elements for the ground-control reader: `Name`, `Longitude`,
`LongitudeAccuracy`, `X`, `XAccuracy`, `Latitude`, `LatitudeAccuracy`, `Y`, `YAccuracy`,
`Altitude`, `AltitudeAccuracy`. [OFFICIAL: tools/defineimportformat, "Ground Control Points"]

"The system supports inputs in degrees or X, Y and Alt in absolute values, all depending on
the chosen coordinate system." [OFFICIAL: tools/gcpimport]

The GCP import dialog's options are *File name*, *File format*, *Values separator*, *Ignore
first line*, *Coordinate system*, and **Position accuracy** — "the accuracy of the coordinates
of the ground control points. Accuracies can also be loaded from a file by choosing a proper
File format", i.e. the dialog value is the fallback for formats without accuracy columns,
exactly parallel to the flight log's *Accuracy settings source*.
[OFFICIAL: tools/gcpimport]

**Importing a GCP file gives RealityScan the coordinates only — it does not place the points
in images.** After import, each point must be measured in at least two images, either
manually (drag-and-drop from the 1Ds view, or F3), by `-detectMarkers` (§4.5), or by
importing measurements (§4.3). Epic advises checking the imported coordinates of at least two
GCPs against the source file before proceeding. [OFFICIAL: tools/gcpimport]

**A GUI-only fallback when there are no surveyed coordinates at all:** place tie points on
map-identifiable features, then click their location in the map view — the point converts to a
Ground control point and takes its coordinates from the map. All heights default to `1`. "The
accuracy of this method of georeferencing can vary in **meters**, since it is based on the
accuracy of a map." Useful for giving otherwise-ungeoreferenced components enough of a frame
to be combined. No CLI equivalent exists.
[OFFICIAL: tutorials/georeferencing, tools/createcontrolpoints]
[Blindness note: map-view placement is invisible to the CLI.]

A doc inconsistency worth knowing: `appbasics/allcommands` says the params XML for
`-importGroundControlPoints` comes from "the Export Ground Control Points dialog";
`tutorials/commandline_1` says the **Import** dialog. The Import dialog is the correct
source. [CONTRADICTED: internal to the Help]

### 4.3 Control-point image measurements

Measurements are 2D pixel positions, "specified in pixels **in the top-left corner of the
image**" — i.e. the origin is the top-left corner. [OFFICIAL: tools/cpmeasurementsimport]

`measurementsimport.xml` ships two formats, `reader="RealityScan.Import.CSVControlPointsMeasurements"`:

| GUID | `descID` | `desc` | Columns |
|---|---|---|---|
| `{FDB5E38A-823C-446A-B144-6D33B2172D8A}` | 8388 | `Image, Point, X, Y (character-separated)` | Image, PointName, X, Y |
| `{6E9D6C7D-85EC-43E8-98CD-C13804D6C554}` | 8389 | `Image, Point, X, Y, Accuracy (character-separated)` | Image, PointName, X, Y, **one** accuracy |

**`{6E9D6C7D-…}` is a 5-column format, not a 6-column one.** Both accuracy variables point at
the same column — `<XAccuracy index="4" />` **and** `<YAccuracy index="4" />` — and the
`desc` says `Accuracy`, **singular**. Read together these agree: the format deliberately
applies one isotropic accuracy value to both image axes. A file written with distinct values
in columns 4 and 5 will have column 5 silently ignored. If you need anisotropic (or oriented,
via `RotationAccuracy`) measurement uncertainty, define a private `<format>` with
`YAccuracy index="5"`. [VERIFIED-by-inspection: `measurementsimport.xml`, 2026-08-04]

`Image` uses `format="name"` (not `name.ext`) in this reader.
[VERIFIED-by-inspection] The documented variable list adds one element the shipped formats do
not use: `RotationAccuracy` — "rotation of the accuracy region from the X-axis in a
left-handed system", i.e. the measurement uncertainty can be an oriented ellipse.
[OFFICIAL: tools/defineimportformat, "Control Points"]

Global measurement accuracy is `sfmControPointImageMeasAccuracy` (Epic's typo, `Contro` not
`Control` — the corrected spelling **does not exist**), float, "Image measurement accuracy
[px]", app default `2.0`. This repo's `AlignmentParams.xml` carries `4.0`.
[OFFICIAL: tutorials/setkeyvaluetable] [VERIFIED: the typo'd spelling is present in the 2.2
binary and the corrected one is absent]

**Export** side, `measurementsexport.xml`, four formats, all
`writer="RealityScan.Export.ControlPoints"`, `mask="*.csv"`, `supportsGeoref="0"`,
`requires="cpm"`. They differ only in the delimiter inside the `$ExportControlPointsMeasurements(...)`
body:

| GUID | `descID` | Body separator |
|---|---|---|
| `{B1F2CB68-599C-47DF-A4F2-C51FC90FE579}` | 8392 | `, ` (comma) |
| `{4C09EC25-F287-4057-8225-56293E1D2A46}` | 8393 | space, with `"$(pointName)"` quoted |
| `{BD70B5DB-289A-4941-A608-DC17598CC77F}` | 8394 | tab |
| `{BF18FD96-8E12-45EB-960D-2FD3CF082DAA}` | 8395 | space, **every** field quoted |

The comma format's body, exactly:

```
$ExportControlPointsMeasurements($(imagePath)$(imageName)$(imageExt), $(pointName), $(x:.2f), $(y:.2f)
)
```

The trailing newline is *inside* the parentheses — that is what makes it one row per
measurement. [VERIFIED-by-inspection: `measurementsexport.xml`, 2026-08-04]

Export tokens [OFFICIAL: tools/cpmeasurementsexport]: `measurementIndex`, `imageIndex`,
`imagePath`, `imageName` (without extension), `imageExt`, `pointIndex`, `pointName`, `x`, `y`
(pixels from the top-left corner).

Caveats that apply to both GCP and measurement export: **only selected points are
exported; to export everything, leave the control points unselected**, and the export is
available only when the project has at least one control point. The measurement export adds
a second condition — "measurements only from the selected control points (**at least 2
selected**)". The measurement *import* has its own precondition: at least one image must
already be in the project. [OFFICIAL: tools/gcpexport, tools/cpmeasurementsexport,
tools/cpmeasurementsimport]

Because both exports are selection-driven and this build auto-answers the "Export Selection"
dialog under `-silent`, §2.12's rule applies here too: know what is selected before you
export, or you get a 0.05-second success that writes nothing.

### 4.4 `-editControlPointSelection` key table

[OFFICIAL: tutorials/editselectioncommand]

| Panel field | Key | Values |
|---|---|---|
| Name | `gpName` | string |
| Enable | `gpEnabled` | `true` \| `false` |
| Type | `gpType` | `0` Tie point · `1` Ground control · `2` Ground test |
| Weight | `gpWeight` | float |
| x / Longitude | `gpP1` | float; or DMS with a cardinal prefix `N54,49,31.25`; or decimal degrees with a cardinal prefix `N54.825347` |
| y / Latitude | `gpP2` | as above |
| z / Altitude | `gpP3` | float |
| Position X accuracy / Longitude accuracy | `gpuP1` | ≥ 0 |
| Position Y accuracy / Latitude accuracy | `gpuP2` | ≥ 0 |
| Position Z accuracy / Altitude accuracy | `gpuP3` | ≥ 0 |

**The Cartesian and geographic names map onto the same three key slots** — `gpP1` is X *or*
longitude, `gpP2` is Y *or* latitude — so which one you are setting is decided entirely by
the point's coordinate system. Get that wrong and the numbers land transposed with no error.
(Epic's own table prints the **same** `N54,49,31.25` / `N54.825347` examples in both the
Latitude and Longitude rows, i.e. an `N` prefix on a longitude. The corresponding `inpTx`
rows in the same page use `E32,08,25.18` / `E32.140328`, which is the sane form. Use the
cardinal that matches the axis. [CONTRADICTED: internal to `tutorials/editselectioncommand`.])

Note the parallel with the per-image prior keys used by `-editInputSelection`, which are the
XMP-free way to set a camera pose prior from the CLI
[OFFICIAL: tutorials/editselectioncommand]:

| Panel field | Key | Values |
|---|---|---|
| Locked pose group | `inpPosePriorRelativeGroup` | string; positive integer sets a group, blank or negative ungroups |
| Relative pose | `inpPosePriorRelative` | `0` Unknown · `1` Draft ("camera oriented but you wish to change its position") · `2` Exact ("the position is fixed and is not changed") |
| Absolute pose | `inpPose` | `0` Unknown · `1` Position ("known up to some precision; RS searches for the closest position, orientation may differ") · `2` Position and orientation (rough, both) · `3` Locked ("no changes in camera position allowed") |
| x / Longitude | `inpTx` | float; or DMS `E32,08,25.18`; or decimal degrees `E32.140328` |
| y / Latitude | `inpTy` | float; or DMS `N54,49,31.25`; or decimal degrees `N54.825347` |
| z / Altitude | `inpTz` | float |
| Yaw / Heading | `inpRx` | −180 … 180 |
| Pitch / Elevation | `inpRy` | −90 … 90 |
| Roll / Bank | `inpRz` | −180 … 180 |
| Accuracy settings source | `inpPriorAccuracyInh` | `0` Global camera prior settings · `1` Edit custom values |
| Position X / Y / Z accuracy · Longitude / Latitude / Altitude accuracy | `inpuTx` / `inpuTy` / `inpuTz` | ≥ 0 (same three slots serve both naming schemes) |
| Yaw accuracy | `inpuRx` | ≥ 0 |
| Pitch accuracy | `inpuRy` | ≥ 0 |
| Roll accuracy | `inpuRz` | ≥ 0 |

Value definitions for `inpPosePriorRelative` and `inpPose` are quoted from
[OFFICIAL: appbasics/camerasettings_priors]; the key spellings from
[OFFICIAL: tutorials/editselectioncommand]. The prior-calibration and prior-lens-distortion
keys of the same command (`inpCalibrationGroup`, `inpCalibration`, `inpFocal`, `inpPPX`,
`inpPPY`, `inpSkew`, `inpLensGroup`, `inpDistortion`, `inpDistortionModel`,
`inpRadial1..4`, `inpTangential1/2`) belong to calibration — see
`05-metadata-xmp-and-sidecars.md`.

`inpPriorAccuracyInh` is almost certainly the per-image sibling of the flight-log params'
`ifuuInhEn` / `ifuuInh` pair (same "inh" = inheritance stem, same 0 = "use the globals"
semantics). [INFERRED]

Note the axis labels here: `inpRx` = **Yaw**, `inpRy` = **Pitch**, `inpRz` = **Roll** — the
"R*x*" suffix follows the panel row order, not an axis. Do not read `inpRx` as "rotation
about X".

**`-editInputSelection "inpPose=3"` (Locked) is unusable as a growth anchor.** It takes
effect, but `-align` then refuses with *"prior set to 'Exact' mode must be all aligned in a
single run. Incremental adding is not supported."* Checkpoint/rollback remains the primary
never-shrink mechanism here. [VERIFIED: FINDINGS cell U18 FAIL, 2026-07-23]

### 4.5 `-detectMarkers`

Automates control-point placement from printed coded targets. A new control point is created
per detected marker, "provided that there is no control point with the exact same name";
existing points with matching names are **augmented with new measurements but keep all their
other properties**. Newly created points are **tie points** (physical location unknown), but
"ground control points can be located via marker detection by assigning them a suitable name
and running marker detection afterwards" — i.e. import the GCP coordinates first with names
matching the marker ids, then detect. [OFFICIAL: tools/detectmarkers]

| Marker type | Max distinct markers |
|---|---|
| Circular, single ring, 12-bit | 161 |
| Circular, single ring, 16-bit | 2,001 |
| Circular, single ring, 20-bit | 26,013 |
| Circular, dual ring, 12-bit | 512 |
| Square, April Tag, 16h5 | 30 |
| Square, April Tag, 25h7 | 242 |
| Square, April Tag, 25h9 | 35 |
| Square, April Tag, 36h10 | 2,320 |
| Square, April Tag, 36h11 | 587 |

[OFFICIAL: tools/detectmarkers]

Detection guidance: markers should be **at least 100 px wide** in the image; the
camera-to-marker angle should exceed 45° (perpendicular is optimal); markers must not be
covered or edited, including the white background; use one marker type per dataset; large
scenes need large markers. The **Required measurements** setting discards markers found in
fewer than N images — "set Required measurements to a value greater than 1 in order to detect
markers robustly". An **Image layer** selector chooses which layer to detect in.
[OFFICIAL: tools/detectmarkers]

Headless, `-detectMarkers` takes an optional `params.xml` exported from the Detect Markers
tool; without it the instance's current settings apply, including the marker type — so pass
the params file. `-detectMarkers` operates on the **selected images** if a subset is
selected. [OFFICIAL] Note that `-selectImage` matches **literal full paths only** in this
build (see `02-command-reference.md`), which makes composing an image subset for detection a
per-image union loop. [VERIFIED: FINDINGS 2026-07-23, cells U-SEL2…U-SEL8]

### 4.6 GCP export formats

`controlpoints.xml` ships six export formats, all `writer="RealityScan.Export.ControlPoints"`,
`specificCoordSystem="1"`, `requires="GCP"`, `mask="*.csv"`: space-, comma-, and
tab-separated, each in X-then-Y and Y-then-X orderings.
[VERIFIED-by-inspection: `controlpoints.xml`, 2026-08-04]

The body is a template script. Example (`{CE348030-6853-4582-9904-458D3B8C2402}`):

```
$ExportControlPoints($If( isGroundControl,$(name), $(x:f), $(y:f), $(alt:f)
))
```

Supported tokens [OFFICIAL: tools/gcpexport]: `index` (int), `name` (string),
`x`, `y`, `z`, `lat`, `lon`, `alt` (double; `alt` is identical to `z`), `isGroundControl`
(bool — true for **both** 'Ground control' and 'Ground test').

---

## 5. Scale: defining it

"In general, there is a problem to determine the scale of a scene with photogrammetry
methods. Some other prior information must be provided. In fact, just a single number is
needed to scale the scene properly. In RealityScan you have the possibility to scale your 3D
model uniformly in all directions at the same time. **Non-uniform scaling with a separate
factor for each axis direction is not allowed.**" [OFFICIAL: tutorials/scaling]

Four mechanisms, in rough order of directness.

### 5.1 Distance constraints

A distance constraint is a known physical distance between **two control points**, each of
which must be measured in **two or more images**. The constraint "is not used in the
alignment before you define a distance by setting a non-zero value to the Distance property".
A disabled constraint still works as a ruler. [OFFICIAL: tutorials/scaling]

CLI, form 1 — define directly:

```bat
RealityScan.exe -delegateTo RS1 -defineDistance "cp_bow" "cp_stern" 63.400 "hull_length"
```

CLI, form 2 — import from a file:

```bat
RealityScan.exe -delegateTo RS1 -defineDistance "F:\na156\distances.csv" "F:\na156\DistanceParams.xml"
```

`distancedefinitions.xml` ships two formats, `reader="RealityScan.Import.CSVDistanceDefinition"`
(note: `tools/defineimportformat` spells the reader `RealityScan.Import.CsvDistanceDefinition`
with a lowercase `sv` — the shipped file uses `CSV`; **use the shipped file's spelling**)
[VERIFIED-by-inspection vs OFFICIAL — [CONTRADICTED], the file is authoritative]:

| GUID | `descID` | Shipped `desc` | Variables (index order) |
|---|---|---|---|
| `{7A2A52BA-D325-47F8-88A1-C402B4E37EED}` | 8412 | `Image PointA PointB Distance` | `Name`, `PointA`, `PointB`, `Distance` |
| `{08192FC0-A5D9-4E99-B993-F274EFA5745F}` | 8413 | `Image PointA PointB Distance Accuracy` | `Name`, `PointA`, `PointB`, `Distance`, `DistanceAccuracy` |

Two shipped-file quirks worth knowing before you author a format here:

- The `desc` strings say **`Image`** for column 0 while the parser element is **`<Name>`**
  (the constraint's name, not an image). The parser wins; the label is wrong.
  [VERIFIED-by-inspection: `distancedefinitions.xml`, 2026-08-04]
- `<Variable>` elements carry **no `format` attribute** at all — only `index`. Both shipped
  formats omit it, unlike every flight-log and ground-control format.
  [VERIFIED-by-inspection]

Import-dialog options beyond the shared ones: a **Coordinate system** ("the coordinate system
in which the imported distance constraint is placed") and **Imported data accuracy**, which
supplies a *Measurements accuracy* when the file has no accuracy column and lets you declare
the **Units** the distances and accuracies are written in.
[OFFICIAL: tutorials/scaling, "Import Distance Constraints"]

Editing constraints from the CLI, `-editConstraintSelection`
[OFFICIAL: tutorials/editselectioncommand]:

| Panel field | Key | Values |
|---|---|---|
| Name | `cName` | string |
| A | `cA` | name of an existing control point |
| B | `cB` | name of an existing control point |
| Enable | `cEnabled` | `true` \| `false` |
| Defined distance | `cValue1` | positive float |
| Defined distance accuracy | `cValue1Acc` | positive float |

Global default accuracy: `sfmDefinedDistanceAccuracy`, float, app default `0.10`.
[OFFICIAL: tutorials/setkeyvaluetable]

### 5.2 Ground control points

Two GCPs define scale: "place one GCP to the origin and the second one to (distance,0,0)";
three define a complete coordinate system if an orthogonal corner is identifiable.
[OFFICIAL: tutorials/scaling]

Control-point prior accuracies: `sfmControlPointXAccuracy` (`0.05`),
`sfmControlPointYAccuracy` (`0.05`), `sfmControlPointZAccuracy` (`0.10`).
[OFFICIAL: tutorials/setkeyvaluetable]

### 5.3 Camera priors

"If a distance between two or among more cameras is known, then this information can be used
to scale the scene… Alternatively, camera centers can be known from GPS or flight logs and
**then the scene will come properly scaled automatically**." [OFFICIAL: tutorials/scaling]

This is the mechanism this pipeline relies on — and §6 is the record of it failing silently
at a scale of 0.175 on 82% of a delivered assembly's cameras. Prior-driven scale is real but
it is **not** self-verifying.

Camera priors can reach the scene by four routes, of which this repo uses two
[OFFICIAL: tutorials/georeferencing]:

| Route | How | Used here |
|---|---|---|
| Flight log | `-importFlightLog` / `-importTrajectory` + params XML (§2) | **yes**, the primary path |
| XMP sidecars | `<stem>.xmp` beside the images, auto-imported on `-add`/`-addFolder` (§5.4) | **yes**, for calibration; pose sidecars are a contamination hazard (B7) |
| Per-image CLI | `-editInputSelection "inpTx=…"` etc. (§4.4) | no |
| **EXIF** | "Use the coordinates from the embedded image metadata (EXIF). **You need to enable the camera priors for georeferencing in the alignment settings for the EXIF data to be used**" — i.e. `sfmEnableCameraPrior=true` | no — ROV stills carry no GNSS fix |

The EXIF row matters even here as a *negative* check: with `sfmEnableCameraPrior=true` set
globally, any image that happens to carry GPS EXIF becomes a prior without anything in the
flight log saying so. [OFFICIAL for the mechanism; [INFERRED] for the contamination risk.]

### 5.4 XMP-locked poses

"Another option is to fix a camera position and orientation completely. The easiest way to do
this is using XMP files." [OFFICIAL: tutorials/scaling] The XMP export modes are
[OFFICIAL: tools/xmpalign]:

| Mode | Behaviour |
|---|---|
| **draft** | absolute camera positions, subject to adjustment during alignment |
| **exact** | cameras maintain their **relative** positions |
| **locked** | both relative and absolute positions fixed; not adjusted during alignment |

Two operational facts about this route:

- **Any `-add` of images with `<stem>.xmp` sidecars beside them auto-imports those sidecars,
  and pose-bearing sidecars silently become exact-pose priors.** Clean the tree before any
  run that must be independent. [VERIFIED: NA167 B7, 2026-07-22]
- **`_common.xmp`** — "You can add one XMP file named `_common.xmp` to the folder with your
  images to import all of them with the same XMP information." [OFFICIAL: tools/xmpalign]
  A cheap way to apply one calibration group or one prior mode to a whole folder.
- `-addImageWithCalibration` imports an image and its XMP where "the two files don't have to
  have the same name or be placed in the same folder". [OFFICIAL: tools/xmpalign] Never used
  here.

### 5.5 Ground plane and gravity

"RealityScan auto-detects the ground plane. If your component seems skew, then you can
manually adjust the position and orientation of the scene." The tool
(SCENE 3D ▸ TOOLS ▸ Set ground plane) offers *Define Ground Plane*, *Set Ground by
Reconstruction Region*, and *Reset Ground*. [OFFICIAL: tools/alignground]

The interactive widget is **GUI-only**. The CLI exposes only:

- `-resetGround` — restore the original orientation and position.
- `-setGroundPlaneFromReconstructionRegion` — centre the model on the grid using the
  reconstruction region, adjusting both rotation and translation.
- `-setCamerasGravityDirection [componentID]` — if the images' XMP carries `xcr:Gravity`,
  rotate the component so `-z` follows the gravity vector. **Applies to the sparse point
  cloud only, not to the mesh.**

[OFFICIAL: appbasics/allcommands] None has been exercised here.
[Blindness note: ground-plane orientation is a semantic state the CLI cannot read back.]

### 5.6 `-update` — what it actually does

[OFFICIAL] descriptions, which do not agree with each other:

- `appbasics/allcommands`: "Update all components and models by a **rigid transformation** to
  fit the actual constraints and control points."
- `tools/createcontrolpoints`: "the Update function will just use ground control points and
  distance constraints to place and **scale** the scene. However, it does not change relative
  positions of cameras in the scene and thus it can scale and position also all already
  created models."
- `tutorials/scaling`: "The Update changes solely the coordinate system of the **currently
  selected component** and it also updates the scale of all children models, whereas the Align
  Images button creates a new component."

[CONTRADICTED, internal to the Help] — "rigid transformation" excludes scaling; the other two
pages say it scales. Scope also differs (all components vs the selected one).

**Observed here:** `-update` is a **similarity** (rigid + uniform scale) fit to the scene's
imported constraints, applied *after* reconstruction. "It can ROTATE or RESCALE a component
but cannot stiffen or repair its geometry." Established while diagnosing a bow component's
45° tilt. [VERIFIED: FINDINGS 2026-07-26] Its process id is `65542 UPDATE_CONSTRAINTS`.

Two consequences:

1. `-update` is the step that **georeferences a merged component**, and it is the only reason
   the union flight log must be imported into a merge scene at all. Without constraints in the
   scene there is nothing to fit to; the parents' georeferencing does **not** carry into the
   fused child. [VERIFIED: FINDINGS 2026-07-23]
2. `-update` is also the step that can **set scale on the deliverable** — and it runs *after*
   the last point at which this pipeline can measure scale. See §6.5.

---

## 6. Scale: measuring it as an oracle

### 6.1 Why this exists

Every automated check in this pipeline before 2026-07-25 measured **quantity** — cameras
registered, components produced. A component can register 97% of its images, produce one
clean component, look correct in the 3D viewer, and be at **one fifth of true scale**.

The finding that forced the issue: fresh-run zone_1 of H2023 solved

| component | cameras | scale | IQR |
|---|---|---|---|
| c0 (hull main) | 3,026 | **0.175** | 0.168 – 0.186 |
| c1 (hull strip) | 714 | **0.220** | — |
| c2 (bow) | 665 | 1.011 | — |

Two components holding **82% of the delivered assembly's cameras** were 5.7× and 4.5× smaller
than reality. [VERIFIED: FINDINGS 2026-07-25]

Three independent confirmations, deliberately chosen so that no two share an assumption:

1. **Constant across scale bands.** The ratio held at 0.197 / 0.181 / 0.185 / 0.179 / 0.174 /
   0.174 across 1–2, 2–4, 4–8, 8–16, 16–32, 32–64 m nav-distance bins — a pure **similarity**
   error, not drift, fold, or accumulation.
2. **Implied vehicle speed.** The hull solve implies an ROV speed of 0.01 m/s (implausible on
   a 64 m hull); nav says 0.08 m/s. On the bow, solve 0.22 m/s ≈ nav 0.21 m/s.
3. **The rig as an independent ruler.** The fixed Cinema–Port baseline measures 1.11–1.21 m in
   metrically sound components but **0.22 m** in hull c0 — 0.20×, agreeing with the
   nav-derived 0.175× **without using nav at all**.

"A uniform scale error is INVISIBLE in the viewer — 'all components look good' was true and
still is, locally." [VERIFIED: FINDINGS 2026-07-25]

**It is not a chronic property of the pipeline.** The *older* production run's zone_1
components measure **0.77–1.01**. Something about the fresh run's zone_1 solve specifically
lost scale, which is why §6.5 still lists the cause as unestablished rather than "fixed".
[VERIFIED: FINDINGS 2026-07-25]

Three further consequences were mis-attributed before the oracle existed, and each is a
diagnostic signature worth recognising: the owner's "high residuals" (position priors in
metres cannot be satisfied by a 5.7×-shrunken solve); the c0+c1 fusion camera drops of −2/−1
(the merge was asked to rigidly fuse two bodies whose scales differ by 26%, geometrically
impossible without a similarity transform — the never-shrink gate that rejected it was right
for a deeper reason than was known at the time); and the 0.55 m merge deformation.
[VERIFIED: FINDINGS 2026-07-25]

The failure **reproduced on a different dataset**: H2024 `zone_3_c0`, 1,192 cameras at scale
**0.236** (IQR 0.217–0.253), on the first production run with orientation priors enabled, in a
run where registration looked entirely healthy (8,709 cameras, 82–93% per zone, `Success:
True` on every zone). Principal-axes scales 0.229 / 0.248 / 0.238 — cloud shape preserved to a
few percent, i.e. a faithful 1:4.24 model. Intrinsics were exonerated: zone_3 solved cinema
16.408 / port 15.481, within 0.2% of the sound zone_5's 16.448 / 15.506.
[VERIFIED: FINDINGS 2026-07-26; HANDOFF 2026-07-27]

### 6.2 The stem-paired oracle

`modules/scale_oracle.py`. Method: **the median ratio of solved-to-nav pairwise distance over
many random camera pairs.** Pairwise distance is invariant to translation *and* rotation, so
the figure is meaningful even when a component's absolute placement is arbitrary — which it
usually is.

```python
def scale_ratio(members: set, solved: dict, nav: dict,
                samples: int = 4000, min_nav_distance: float = 3.0,
                seed: int = 5) -> dict | None:
    """Median/IQR of solved/nav pairwise-distance ratio for one component."""
```

- **Solved positions** come from the pose XMPs of an `identity_r<K>` harvest directory,
  parsed with the element-or-attribute regex of §3.3. Only components exported by
  `-exportXMP` carry real stems.
- **Nav positions** come from the 13-column flight log, parsed on `;` with the header line
  skipped, keyed by lowercased stem.
- `min_nav_distance = 3.0` m discards pairs too close together to carry signal.
- `seed = 5` makes the sample deterministic and the number reproducible.
- Fewer than 30 shared cameras ⇒ returns `None` = **UNMEASURED**, which callers must treat as
  blocking, never as passing.

Interpretation:

```
ratio ~= 1.0   metrically sound
ratio << 1.0   solve is SMALLER than reality (scale collapse)
wide IQR       not a similarity error - drift, fold, or mixed bodies
```

**The oracle was validated in both directions before use** — against a known-bad case and a
known-good case. Its self-test reproduces the hand-derived fresh-zone_1 figures exactly
(c0 0.175 / c1 0.221 / c2 1.009). [VERIFIED: FINDINGS 2026-07-25]

### 6.3 The gate

```python
DEFAULT_SCALE_MIN = 0.90
DEFAULT_SCALE_MAX = 1.10
```

`verdict(stats, scale_min, scale_max)` returns `('pass' | 'fail' | 'unmeasured', explanation)`:

- outside the band ⇒ `fail`;
- inside the band but with **IQR width > 0.15** ⇒ `pass` **with a call-out**, because by
  construction a wide IQR means something other than a similarity error (drift, a fold, or
  mixed bodies);
- `stats is None` ⇒ `unmeasured`.

`merge_zones.apply_scale_gate` drops model targets whose scale is out of band **or
unmeasurable**: "A result component inherits the verdicts of the inputs attributed to it, and
the WORST one decides: a fused component containing a 0.236 input is not salvaged by a sound
sibling. UNMEASURED blocks too — the whole point is that silence is not evidence, and
modelling is the expensive, deliverable-facing step." `--scale_gate false` overrides for a
deliberate exception.

**A defect worth repeating as a warning:** the operator's `--scale_min` / `--scale_max` were
accepted, persisted, and printed in `EVALUATION_READY` as the authoritative band — and never
passed into `measure_input_scales`. Every verdict was baked at the 0.90–1.10 defaults, so
*tightening* the gate silently did nothing while the report claimed otherwise. Fixed 2026-07-28.
[VERIFIED: FINDINGS audit #5, 2026-07-28] A gate that reports a threshold it does not apply is
a monitor grading its own homework.

### 6.4 The correspondence-free quantile method

The stem oracle **cannot measure a fused component**, by construction: a merge-scene
`-exportXMPForSelectedComponent` writes **ordinal** sidecars (`00000.xmp`, `00001.xmp`, …)
with no image identity, so there is nothing to join on. In the final-assembly run all three
fused components came back UNMEASURED while every unfused original passed — the gate did its
job, and it would have left the hull unmodelled. [VERIFIED: FINDINGS 2026-07-28]

`quantile_ratio_scale(solved, nav)` closes that hole:

> Under a similarity transform, **sorted distances-from-centroid of the same camera multiset
> correspond rank-for-rank**, so ratios of matching quantiles give median + IQR without any
> pairing.

Implementation constants: quantiles `0.05` to `0.95` in steps of `0.01` (91 values, tails
trimmed); requires ≥ 30 points on each side and the two counts to agree within **5%**;
returns the same `{median, iqr_low, iqr_high, cameras}` shape as the stem oracle so callers do
not branch. The frame is the local model frame, not UTM — irrelevant, because distance ratios
are rigid-invariant and the scale factor is exactly the thing being measured.

**Validated in both directions:** known-good `zone_1_c1` measures **1.045** against the stem
oracle's 1.023 — same verdict, 2.2% apart; the hull's 0.236-shrunk cloud measures **0.235**.
[VERIFIED: FINDINGS 2026-07-28]

**Two traps, both hit in practice:**

1. `xcr:Position` is an **element** in current exports and an **attribute** in older ones —
   parse both, or half your corpus silently reads as zero cameras.
2. A fused manifest's `images` list is the **unique-basename union**, but the scene holds one
   camera per input **occurrence** (880 cameras over 537 unique basenames on `cluster_1`,
   because the batcher copies overlap images into two zones). The nav multiset must therefore
   be the **concatenation of the attributed input manifests' members**, not the union —
   `member_multiset()` does exactly this and falls back to the union only when an input
   manifest is unavailable.

**A third trap, about harvest directory semantics:** `identity_r<K>` directories mean
different things in the two scene types.

| Scene type | `identity_r<K>` contains | Component K's own members |
|---|---|---|
| **ALIGN** scene (`AlignZone.bat`) | **cumulative** — the stems of laps K..end | `stems(rK) − stems(rK+1)` (successive difference) |
| **MERGE** scene (`MergeZoneComponents.bat`) | component K **alone** | the directory itself |

[VERIFIED: FINDINGS 2026-07-28] `component_members()` implements the successive difference.

### 6.5 Results of record, and the standing blindness

| dataset / component | cameras | scale | verdict |
|---|---|---|---|
| H2023 fresh zone_1 c0 | 3,026 | 0.175 | FAIL |
| H2023 fresh zone_1 c1 | 714 | 0.220 | FAIL |
| H2023 fresh zone_1 c2 (bow) | 665 | 1.011 | pass |
| H2023 fresh zone_2 | 852 | 0.902 | pass |
| H2023 fresh zone_3 | 124 | 0.965 – 0.991 | pass |
| H2023 PD-6 c0 (corrected config) | 3,738 | **0.981** (IQR 0.949–1.027) | pass |
| H2023 PD-6 c1 | 656 | 1.076 | pass |
| H2024 baseline zone_1 (8 components) | — | 0.937 – 1.119 | mixed |
| H2024 baseline zone_2 | — | 1.086 | pass |
| H2024 baseline **zone_3_c0** | 1,192 | **0.236** (IQR 0.217–0.253) | FAIL |
| H2024 baseline zone_4 (5 components) | — | 0.983 – 1.196 | mixed |
| H2024 baseline zone_5 | — | 1.023 | pass |
| H2024 **v2** zone_3_c0 | — | **0.969** (IQR width 0.147 — inside the band but above the 0.15 call-out threshold's neighbourhood) | pass |
| H2024 v2 zone_1_c2 | — | 1.127 → 1.081 | pass |
| H2024 v2 zone_4_c2 | — | 1.196 → 0.919 | pass |
| H2024 `cluster_0_a2_c0` (hull, fused) | 4,860 | **0.997** (IQR width 0.014) | pass — quantile method |
| H2024 `cluster_1_a1_c0` (fused) | 880 | **1.000** (IQR 0.029) | pass — quantile method |
| H2024 `cluster_4_a1_c0` (fused) | 133 | **0.980** (IQR 0.077) | pass — quantile method |

[VERIFIED: FINDINGS 2026-07-25 … 2026-07-28; HANDOFF]

**The crisis closed, but the cause was never established.** All 14 v2 components pass the
0.90–1.10 band. The v2 re-align changed several things at once (restored calibration sidecars,
fresh solve, code changes) and fragmentation is already nondeterministic, so no controlled cell
explains either the collapse or the repair. Similarly, PD-6's repair of the H2023 hull differs
from its baseline in **three** ways — Brown3→Division, accuracy columns actually being imported
for the first time, and orientation priors removed (PD-6's cell params name the 7-column
position-only `{0E9850E2-…}`; production named the 13-column `{B438A617-…}`) — so the scale
repair must not be attributed to the distortion model alone.
[VERIFIED-as-outcome, ATTRIBUTION OPEN: FINDINGS 2026-07-26/27]
**Caveat on that count:** differences (b) and (c) both presuppose that the baseline run
actually received what `{B438A617-…}` describes, which the §2.3 [CONTRADICTED] entry disputes
— the format was not installed on the baseline's run date. If it was not resolvable, the
baseline was *also* effectively position-only and the real count is **one** (the distortion
model) plus a global-vs-per-image accuracy change. §9 item 14 is the probe.

**Standing blindness: the oracle cannot see the deliverable.** It needs pose XMPs; assemble
mode saves and quits without exporting any. So scale is measured on the assembly's **inputs**
while `-update` — a similarity fit to the nav constraints, i.e. precisely the step that can
*set* scale — runs afterwards unobserved. Closing it means porting the successive-difference
harvest to a dated **copy** of the assembly project, which also yields per-component
membership. [OPEN: FINDINGS 2026-07-25; HANDOFF open item 2]

**Running it:**

```bat
py -3.13 modules\scale_oracle.py F:\na156_h2024\components\zone_3 ^
                                 F:\na156_h2024\batched\zone_3\flight_log_4N_UTM.txt
```

Output, one line per component, maximal first:

```
c0:  1192 cams  scale 0.236  IQR 0.217-0.253
```

---

## 7. Verifying georeferencing headless

**This is the longest-standing open item in the repo** (hardening cell **U7**, open since
2026-07-23). Today the assembly project's georeferencing is verified by an owner opening it in
the GUI and taking a screenshot. [OPEN: FINDINGS/ALIGN_MERGE_HARDENING_PLAN U7]

Three candidate proxies were listed. The survey work for this manual establishes that the
first one is far more tractable than the repo believed, because **`-exportReport` takes a
plain template file, not a GUI-exported params XML**:

```
exportReport | outputFileName templateFileName | true|false
```

"Export a report into a file (`outputFileName` including the path and the `.html` extension)
using a template (`templateFileName` including the path). The default templates are stored in
the installation folder\Reports." [OFFICIAL: appbasics/allcommands]

Shipped templates in `C:\Program Files\Epic Games\RealityScan_2.2\Reports\`:
`Overview.html`, **`ComponentAccuracyReport.html`**, `SelectedComponent.html`,
`SelectedComponentsTiePointsStats.html`, `SelectedModel.html`, `SelectedOrtho.html`,
`MapView.html`, `AlignmentView.html`, `Misalignment.html`, plus per-locale subdirectories,
`images/`, `scripts/`, `styles/`. [VERIFIED-by-inspection, 2026-08-04]

`report.xml` describes `ComponentAccuracyReport.html` as the **"Registration and
Georeferencing Accuracy Report"**, `requires="component,georeferenced"` — the exact question
U7 asks. [VERIFIED-by-inspection: `report.xml`, format `{C86451F2-C5E5-4967-9D5F-AE8959C245EC}`]

The report variables that answer the question directly:

| Variable | Scope | Meaning |
|---|---|---|
| `isGeoreferenced` | global / selected component | `1` if the selected component is georeferenced, `0` if not [OFFICIAL: appbasics/reports_fav_basic] |
| `coordSystemName` | global | the output CRS name if georeferenced, otherwise the literal `"Grid Plane"` [OFFICIAL] |
| `units`, `unitsShort`, `coordSystemUnit2Meter` | global | unit of the selected component and the factor to metres [OFFICIAL] |
| `componentIsGeoreferenced` | `$ComponentStats(...)` | per-component georeferenced flag [OFFICIAL: appbasics/reports_fav_components] |
| **`componentMetric`** | `$ComponentStats(...)` | **"a component is scaled to match real dimensions"** [OFFICIAL] |
| `componentControlPointCountUsed` | `$ComponentStats(...)` | "a number of used control points" [OFFICIAL: appbasics/reports_fav_components] |
| `componentConstraintCountUsed` | `$ComponentStats(...)` | "a number of used distance constraints" [OFFICIAL: appbasics/reports_fav_components] |
| `isCoordSystemLatLon` | global | true if the output CRS is Geographic, false if Cartesian [OFFICIAL: appbasics/reports_fav_basic] |
| `anchorX/Y/Z`, `anchorR00..R22` | global | the local→Euclidean transform (§3.3) [OFFICIAL] |

And, for verifying that a flight-log import actually delivered what the file contained,
`$ExportImagePriors(inputIndex, …)` inside `$IterateImages(…)`
[OFFICIAL: appbasics/reports_fav_images]:

| Variable | Meaning |
|---|---|
| `inputIsGeoreferenced` | this input has a georeferenced prior |
| `inputIsPositionPrior` | **true if a prior position is defined** |
| `inputIsOrientationPrior` | **true if the prior rotation is defined via Yaw, Pitch, Roll** |
| `inputIsOpkRotationPrior` | true if defined via Omega, Phi, Kappa |
| `inputIsPriorAccuracy` | **true if prior position and orientation accuracy is defined** |
| `inputX` / `inputY` / `inputZ` | prior position (Cartesian input CRS) |
| `inputLat` / `inputLon` / `inputAlt` | prior position (geographic input CRS) |
| `inputXOutCS` / `inputYOutCS` / `inputZOutCS`, `inputLatOutCS` / `inputLonOutCS` / `inputAltOutCS` | the prior expressed in the **output** CRS |
| `inputXEuclid` / `inputYEuclid` / `inputZEuclid` | the prior expressed in the **Euclidean** frame |
| **`inputCS`** | **"a coordinate system in which camera took the image"** — reads back the CRS the import actually assigned |
| `inputCSUnit`, `inputCSUnitShort`, `inputCSUnitToMeter` | that CRS's unit and its multiplier to metres |
| `inputIsLatLong` | true if the input CRS is Geographic, false if Cartesian |
| `inputYaw` / `inputPitch` / `inputRoll` | prior rotation angles |
| `inputOmega` / `inputPhi` / `inputKappa` | prior OPK angles |
| `inputAccuracyX/Y/Z` | prior position accuracies |
| `inputAccuracyYaw/Pitch/Roll` | prior orientation accuracies (the Help notes these double as the Omega/Phi/Kappa accuracies) |
| `inputIsInsOffsetValid` | true if an offset between camera centre and position sensor is defined |
| `inputInsOfsX/Y/Z`, `inputInsOfsYaw/Pitch/Roll` | that lever arm and boresight — the read-back for the `ifOfs*` keys of §2.8 |
| `inputIsPointCloud` | true if the input is a LiDAR point cloud |
| `inputCalibrationPriorType` | `Unknown` \| `Approximate` \| `Fixed` |
| `calibrationGroup`, `distortionGroup` | prior grouping ids |
| `inputF`, `inputPX`, `inputPY`, `inputAspect`, `inputSkew`, `inputK1..K4`, `inputT1..T2` | prior calibration |
| `inputLensModel`, `inputLensModelIndex` | prior lens distortion model and its index |

**`inputCS` is the direct answer to the wrong-zone failure mode of §2.11.** A params XML
declaring `+proj=utm +zone=4` against a 57S log misplaces everything silently today; a
one-line report emitting `$(inputCS)` for image 0 shows exactly which CRS the import
attached, before an 80-minute align is spent on it. [OFFICIAL: appbasics/reports_fav_images]
[INFERRED that it distinguishes a wrong zone — untested, but it is the variable's stated
meaning.]

**This is the instrument that settles several standing questions at once**, because it reads
back what RealityScan *received*, not what the file *contained*: whether the 13-column
format's YPR columns landed (`inputIsOrientationPrior`), whether the accuracy columns landed
(`inputIsPriorAccuracy`, `inputAccuracyYaw`), and what accuracies are in force when the log
supplies none. A minimal template is a few lines of text and costs one instance boot.

Companion camera-side variables, post-alignment
[OFFICIAL: appbasics/reports_fav_cameras]: `x`/`y`/`z` (output CRS), `xInpCS`/`yInpCS`/`zInpCS`
(input CRS), `lat`/`lon`/`alt` (always `epsg:4326`), `yaw`/`pitch`/`roll`,
`omega`/`phi`/`kappa`, `euclidX`/`euclidY`/`euclidZ`, and
`$ExportRelativeCameraPositionUncertainty(cameraImageIndex, …)` with covariance terms
(`posUncertCovXX`, …). Camera uncertainty is "a value defining the accuracy of the cameras'
positions… available only for registered images and displayed units are taken from Project
coordinate system." [OFFICIAL: appbasics/uncertainty]

The other two U7 proxies, for completeness:

- **`-exportRegistration` round trip.** `calibration.xml` ships CSV camera-position formats
  including `{121D2018-5016-4A4D-95BB-46382F54CD64}` "Comma-separated, Name, X/Lon, Y/Lat,
  Z/Alt, Yaw, Pitch, Roll" (`requiresGeoref="1"`, `EulerFormat="zyx"`) and
  `{720A2EC9-3EE9-4645-BD4D-36A613EA3F13}` position-only. Exporting one and diffing against
  the input flight log is a direct georeference check. **Blocked**: `-exportRegistration`
  without a params XML blocks forever headless, and no params file has been saved from the
  GUI dialog. [VERIFIED: FINDINGS 2026-07-21]
- **`poses2flightlog.py` local→UTM fit residuals.** A georeferenced component should fit near
  identity with residuals on the order of the nav error (§3.3). Already implemented; not yet
  wired into the acceptance path.

Caution when reading `-printReport`: it "does not work with delegation".
[OFFICIAL: appbasics/allcommands] Use `-exportReport` to a file.

---

## 8. Failure modes and a pre-flight checklist

| Symptom | Cause | Fix |
|---|---|---|
| Zone align "succeeds" in ~25 s; every log row reported not in the scene | `-addFolder` did not recurse; the scene is empty | `-set "appIncSubdirs=true"` before every `-addFolder` [VERIFIED: FINDINGS 2026-07-23] |
| Import reports failure, result `2181038335` / `0x820000FF`, but the log says `Trajectory imported successfully.` | `err:18002` — rows reference images not in the scene | filter the log to the scene, or use the tolerant runner of §2.6 |
| Everything imports cleanly but the scene sits in the wrong place on Earth | `CoordinateSystemFlightLog` zone/hemisphere ≠ the log's actual zone | generate the params XML from the log filename tag (§2.11); never hand-edit |
| Orientation priors and per-image accuracies have no effect | `gpsLogFileFormat` names a GUID absent from `flightlogs.xml`, or the format has no YPR/accuracy columns | verify the GUID exists in the installed `flightlogs.xml`; re-verify after every RealityScan update |
| A subsequent export writes zero files in ~0.05 s | flight-log import left images selected; `-silent` auto-answered "Export Selection" | `-deselectAllImages` before every export [VERIFIED: FINDINGS 2026-07-23] |
| Merged component is not georeferenced | the merge scene held no constraints; parents' georeferencing does not carry | import the union log into the merge scene, then `-update` [VERIFIED: FINDINGS 2026-07-23] |
| Union log has far fewer rows than the scene has cameras | duplicated basenames from copied overlap images | one trajectory row cannot serve two cameras; move to a common image pool [VERIFIED: HANDOFF #6] |
| Component registers 97% and looks perfect but is 1/5 scale | over-tight position priors and/or an unpinned orientation convention | measure with the scale oracle before modelling; loosen accuracies to end-to-end uncertainty (§2.10, §6) |
| Scale gate reports every fused component UNMEASURED | merge-scene XMP exports are ordinal | use `quantile_ratio_scale` (§6.4) |
| Components silently missing from selection and from XMP export | `-setMinComponentSize` default threshold is 5 | `-setMinComponentSize 1` before exports. The command is itself **deprecated in 2.2** ("will be removed in the next release" warning in `RealityScan.log`) but still required. [VERIFIED: FINDINGS [NA167 #22], 2026-07-24] |

**Pre-flight checklist for any georeferenced run:**

1. `flightlogs.xml` in the install root contains the GUID that `gpsLogFileFormat` names —
   and its mtime has not been reset by an app update.
2. The params XML was **generated this run** from the flight log's own zone tag; its
   `CoordinateSystemFlightLog` matches the log's real UTM zone **and hemisphere**.
3. `appIncSubdirs=true` precedes every `-addFolder`.
4. The log is filtered to the scene, or the import runs through a tolerant `0x820000FF` path
   that **moves** rather than deletes the marker.
5. `-deselectAllImages` precedes every export.
6. Position accuracies express end-to-end per-image uncertainty (10 / 10 / 1 m here), not the
   sensor spec; orientation accuracies are conservative (15°).
7. `sfmEnableCameraPrior=true` is applied as an explicit `-set`, and the accuracy keys use
   their documented `sfm*` names rather than the exporter's `s###l` ids.
8. Every component's metric scale is measured **before** any model is generated, and
   UNMEASURED blocks.
9. Merge scenes get the union log **and** `-update`.

---

## 9. Open questions

Each item states the question and the cheapest probe that answers it.

1. **Are `-importTrajectory` and `-importFlightLog` the same handler?**
   Probe: on the 120-image smoke fixture, import the same log with the same params XML via
   each name into two fresh scenes; `-exportReport` an `$ExportImagePriors` template from each
   and diff. ~4 min, two instance boots. (§2.1)

2. **What values do `gpsLogEulerAnglesOrderYPR` and `gpsLogMount` take, and what are the
   defaults?** These are the real carriers of the "Euler angles order (YPR)" and "Camera
   mount" dialog options; `ifKmode` — which this repo has been writing — does not exist in the
   2.2 binary. Probe A (one minute, needs the GUI once): save trajectory-import params at
   defaults, then after changing **only** *Euler angles order (YPR)*, then after changing
   **only** *Camera mount*; diff the three XMLs. Probe B (pure CLI, ~2 min per cell): align
   the smoke fixture with orientation priors under different values and read camera attitudes
   out of the pose XMPs. HANDOFF loose ends #5 / #7. (§2.8, §2.9)

3. **Which flight-log axis convention is correct?** `tools/flightlogimport` says NED with
   Yaw=Z / Pitch=Y / Roll=X; `tools/defineimportformat` and `appbasics/reports_fav_images` say
   Yaw=Y / Pitch=X / Roll=Z. Probe: import a synthetic 6-row log with a single non-zero angle
   per row into the smoke fixture with `inpPose=2`, then read `inputYaw/inputPitch/inputRoll`
   and the solved `yaw/pitch/roll` back out through `-exportReport`. ~5 min. (§2.4)

4. **Is the `0x820000FF` tolerance too broad?** Hardening cell U10. Probe: on smoke, import
   (a) a log with a deliberately wrong-zone params XML and (b) a corrupt log; record the
   result codes. If either is also `0x820000FF`, add a `RealityScan.log` grep for `18002` as a
   second factor in the tolerant path. (§2.6)

5. **Does the hand-merged `{B438A617-…}` format survive a RealityScan update?** Probe:
   after any update or repair install, `findstr /c:"B438A617" "C:\Program Files\Epic Games\RealityScan_2.2\flightlogs.xml"`
   — one command, must be in the post-update checklist. (§2.3)

6. **Can a flight log deliver per-image calibration priors?** The reader's variable vocabulary
   includes `FocalLength`, `PrincipalU/V`, `Skew`, `AspectRatio`, `RadialDistortion1..4`,
   `TangentialDistortion1..2`, but no shipped format uses them. Probe: add a custom `<format>`
   with those columns, import on smoke, and read `inputF` / `inputK1` back through
   `$ExportImagePriors`. Would replace the per-image XMP calibration sidecar route entirely if
   it works. (§2.4)

7. **Does the unset project coordinate system degrade anything?** This repo never calls
   `-setProjectCoordinateSystem`, contrary to Epic's stated import procedure. Probe:
   `-exportReport` a `$(coordSystemName)` / `$(units)` / `$(coordSystemUnit2Meter)` template
   on smoke before and after `-setProjectCoordinateSystem epsg:32604`. (§3.2)

8. **Close U7 — a CLI-observable georeferencing check.** Probe: write a ~10-line report
   template emitting `$(isGeoreferenced)`, `$(coordSystemName)`, and per component
   `$(componentIsGeoreferenced)` / `$(componentMetric)` /
   `$(componentControlPointCountUsed)`; run `-exportReport out.html tpl.html` on a known
   georeferenced zone project and on a merge project. One boot each. This is the item that has
   been open longest and it is now the cheapest to close. (§7)

9. **Confirm the `s###l` ↔ `sfm*Accuracy` identification and ship the accuracies.** That the
   `s###l` ids are inert is settled — none occurs in the 2.2 binary string table
   (§2.8 method). What is *not* settled is which documented key each one stands for. The
   mapping is [INFERRED] from slot order and default magnitudes. Probe: change **one**
   alignment-dialog accuracy field in the GUI, re-export the params XML, and diff — the id
   whose value moved is the answer. Then emit the documented `sfm*` names explicitly from the
   workflow instead of relying on the exporter's ids. (§2.10)

10. **Is the intermediate accuracy ladder better than loose?** 3 / 3 / 0.5 and 5 / 5 / 1 were
    queued and never run; loose (10 / 10 / 1) is proven, not proven optimal. Each cell is a
    ~70-minute zone_1 re-align. HANDOFF 2026-07-25 open item 3. (§2.10)

11. **What caused the H2024 metric-scale collapse and its repair?** Both `zone_3_c0` 0.236 →
    0.969 and the H2023 PD-6 hull repair changed several variables at once. No controlled cell
    exists. Probe: a single-variable cell on `zone_3` — restore the v1 configuration and change
    **only** the calibration-sidecar state — ~30 min. (§6.5)

12. **Measure the DELIVERABLE's scale, not its inputs.** Assemble mode exports no XMPs, so
    `-update` runs unobserved after the last measurement. Probe: port the
    successive-difference harvest to a dated **copy** of the assembly project; also yields
    per-component membership. HANDOFF open item 2. (§6.5)

13. **CLOSED (2026-08-04), kept for the record.** "Is `measurementsimport.xml`'s
    `{6E9D6C7D-…}` accuracy mapping a shipped bug?" — no. Both `XAccuracy` and `YAccuracy`
    carry `index="4"`, and the shipped `desc` reads `Image, Point, X, Y, Accuracy`,
    **singular**: it is a 5-column format applying one isotropic accuracy to both image axes.
    For anisotropic or oriented (`RotationAccuracy`) uncertainty, define a private format with
    `YAccuracy index="5"`. (§4.3)

14. **[CONTRADICTED, unresolved] Did any align before 2026-07-25 receive orientation priors
    or per-image accuracies at all?** The custom 13-column format was not installed until
    `flightlogs.xml` mtime `2026-07-25 07:31`, yet `FlightLogParams.xml` had been naming its
    GUID all along. `PRIORS_DISTORTION_TEST_PLAN` audit item 1 says YPR and accuracies were
    "silently dropped on every import to date"; FINDINGS 2026-07-26 says the 2026-07-24 fresh
    run "DID import orientation, at the then-current 3/5/3 accuracies". Both are tagged
    established. The answer decides whether "orientation priors removed" is a real third
    difference between the 0.175-scale fresh run and the 0.981-scale PD-6 — and therefore
    whether item 11 has three candidate causes or two. **Probe:** rename the
    `{B438A617-…}` block out of `flightlogs.xml`, import the 13-column log on the smoke
    fixture with the production params XML, `-exportReport` `$(inputIsOrientationPrior)` /
    `$(inputIsPriorAccuracy)` / `$(inputAccuracyYaw)` / `$(inputCS)`, restore the block. ~4
    min, one boot. This is the cheapest unrun probe in the document and it also partly settles
    items 2, 3 and 11. (§2.3, §2.10, §6.5)

15. **Does an instance-held lever arm double-apply the one already baked into the log?**
    `ifOfsX/Y/Z` + `ifOfsRR/RP/RY` + `ifOfsifuUseOffset` exist in the binary and are not
    written by this repo's params file, while `geoall.py` bakes the lever arm into the log
    itself. Probe: after an import, `-exportReport` `$(inputIsInsOffsetValid)` and
    `$(inputInsOfsZ)`. Non-zero means it is being applied twice. One boot, ~1 min.
    (§2.8, §7)

16. **Nothing about GCPs, control points, markers, or distance constraints has ever been
    driven through this CLI.** Every claim in §4 and §5.1–§5.2 is documentation or shipped
    schema, not measurement. Probe (half a day, high value): place three control points in the
    smoke fixture, import GCP coordinates and measurements from files, `-defineDistance` a
    known baseline, `-align`, and read `componentControlPointCountUsed`,
    `componentConstraintCountUsed`, `componentMetric` and the control-point residuals back
    through `-exportReport`. This would convert the whole of §4 from [OFFICIAL] to [VERIFIED]
    and give the rig an independent scale source that does not depend on nav. (§4)

17. **Are the ground-plane commands usable headless?** `-resetGround`,
    `-setGroundPlaneFromReconstructionRegion` and `-setCamerasGravityDirection` have never been
    run here, and ground-plane orientation is on the blindness list — the CLI cannot read it
    back. Probe: run each on smoke and check for an error marker; verify the effect via the
    `anchorYaw/anchorPitch/anchorRoll` report variables. (§5.5)
