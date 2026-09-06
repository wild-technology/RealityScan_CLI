# Camera rigs, orientation conventions, priors, and coordinate frames

This document covers the *geometry layer* of RealityScan 2.2 driven from the CLI: how the
application is told where a camera is and which way it points, what a "rig" is, how
calibration and lens-distortion groups partition the intrinsics solve, what each prior
strength actually does, which distortion models exist and what their coefficient vectors
mean, and the full set of coordinate frames a camera can be expressed in — plus the exact
transformations between them. It does **not** cover general command syntax and delegation
(see `02-command-reference.md`, `01-cli-fundamentals.md`), the `-set` key inventory (see
`03-settings-keys.md`), merge/component semantics (see `08-components-and-merge.md`),
reconstruction/texturing (see `10-reconstruction-texturing-export.md`), or export-format
catalogues except where a format's shipped template is itself the evidence for a rotation
convention. The XMP sidecar file format itself is `05-metadata-xmp-and-sidecars.md`; the
flight-log import path is `06-georeferencing-flightlogs-and-scale.md`. Everything about
*aligning* is here only insofar as priors and frames drive it.

**Applies to:** RealityScan 2.2 (Epic Games), build 2.2.0.119430, Windows, headless CLI
operation.
**Tags:** [OFFICIAL] shipped Help · [VERIFIED] measured in production here ·
[CONTRADICTED] docs vs observation · [UNDOCUMENTED] · [INFERRED] · [OPEN]

**A note on one source class.** Several facts below carry
"[UNDOCUMENTED: binary string extraction]". Those come from reading UTF-16 and ASCII string
tables out of `C:\Program Files\Epic Games\RealityScan_2.2\RealityScan.exe`
(2.2.0.119430) — key names, combo-box option lists and tooltips that the shipped Help
omits entirely. A string's *existence* in the binary is a fact; the *pairing* of a key to a
field, and any "default value", is read from adjacency in the string table and is therefore
[INFERRED] unless separately confirmed. Where that distinction matters it is stated
inline. Nothing in this class has been confirmed by running the application.

---

## Contents

1. [The prior model in one table](#1-the-prior-model-in-one-table)
2. [XMP sidecars: the per-image metadata channel](#2-xmp-sidecars-the-per-image-metadata-channel)
3. [Rigs: `xcr:Rig` / `RigInstance` / `RigPoseIndex`](#3-rigs-xcrrig--riginstance--rigposeindex) — incl. §3.5, the `.rcrx` requirement and importing an external solve as locked poses
4. [Calibration groups vs distortion (lens) groups](#4-calibration-groups-vs-distortion-lens-groups)
5. [Distortion models and the coefficient vector](#5-distortion-models-and-the-coefficient-vector)
6. [Rotation conventions](#6-rotation-conventions)
7. [Prior strength, accuracy, hardness, and composition](#7-prior-strength-accuracy-hardness-and-composition)
8. [Coordinate frames in play](#8-coordinate-frames-in-play)
9. [Flight-log (trajectory) priors](#9-flight-log-trajectory-priors)
10. [Applied: the four-camera underwater ROV rig](#10-applied-the-four-camera-underwater-rov-rig)
11. [Undistortion and registration export](#11-undistortion-and-registration-export)
12. [Recipes and checklists](#12-recipes-and-checklists)
13. [Open questions](#open-questions)

### The [CONTRADICTED] entries, in one place

Read these first; they are the facts most likely to be wrong in your head.

| § | Docs say | Observed |
|---|---|---|
| 1 | "prior set to Approximate … lens distortion as close to zero as possible" | that describes the *"No lens distortion" model*, not the `Approximate` **strength**; `Approximate` with no coefficients still solved k1 = −0.0524 over 2,204 cameras |
| 2.4 | no naming rule given for `-exportXMPForSelectedComponent` | it writes **ordinal** `00000.xmp`, not `<stem>.xmp`; the command, not the scene, decides |
| 3.1 | rigging is "only for inputs connected in a rig (e.g. individual `.lsp` files)" and "when using the laser scans" | the binary ships an image-based **Rig Creation Wizard**: "a set of cameras mounted together which are synchronously taking pictures" |
| 3.2 | route 1 says XMP `xcr:Rig`/`RigInstance`/`RigPoseIndex` is a documented way to declare a rig | declaring `xcr:Rig` makes `-add` demand `rig<GUID>.rcrx` beside the images and the run dies without it; no `.rcrx` ships and the extension is in no Help topic (§3.5) |
| 5.4 | a per-image lens **Model** field and `xcr:DistortionModel` imply per-camera models | `sfmDistortionModel` is **global and all-or-nothing**; 2,558 `brown3` sidecars came back `division` |
| 6.3 | `appbasics/selectedinputs` + `tools/defineimportformat`: Yaw→Y, Pitch→X, Roll→Z | `tools/flightlogimport`, the shipped `EulerFormat="zyx"` templates, the staff post and the binary tooltip all say Yaw→**Z**, Pitch→**Y**, Roll→**X** in NED |
| 9.3 | (repo record) `ifKGrp`/`ifKmode` are the Euler-order and Camera-mount carriers, and neither string is in any installed file | `ifKmode` does not exist in the binary at all (the real key is `ifKModel`); `ifKGrp` does; the rotation settings are `gpsLogEulerAnglesOrderYPR` / `gpsLogMount` |
| 9.3 | (repo record) "the production params … with `ifUseOriAcc=true`, so the fresh-run aligns DID import orientation [accuracies]" | **`ifUsePosAcc` and `ifUseOriAcc` do not exist in the binary either.** Three of the twelve entries in `FlightLogParams.xml` name nothing. What the accuracies actually were is now [OPEN] — Q24 |
| 11.1 | `tutorials/commandline_1` spells the command `exportUndistoredImages` | the master table and process id `21812 EXPORT_UNDISTORTED_IMAGES` spell it `exportUndistortedImages`; the short form is a doc typo |

---

## 1. The prior model in one table

RealityScan carries **three prior families** per input — "Pose, calibration and lens
distortion priors" [OFFICIAL: appbasics/camerasettings_priors] — but Pose splits into a
*relative* and an *absolute* half with separate strength enums, so four rows. Each row has
its own strength enum, its own group id, and its own set of CLI entry points. They are set
independently and can disagree.
[OFFICIAL: appbasics/camerasettings_priors, appbasics/selectedinputs]

| Family | What it constrains | Strength enum | Group id | Set via |
|---|---|---|---|---|
| **Prior pose — relative** | camera-to-camera geometry inside a rig | `0` Unknown · `1` Draft · `2` Exact | `inpPosePriorRelativeGroup` ("Locked pose group", any alphanumeric; negative/blank = ungroup) | `-editInputSelection "inpPosePriorRelative=2"`, `-lockPoseForContinue true`, XMP `xcr:Rig`/`RigInstance`/`RigPoseIndex` |
| **Prior pose — absolute** | camera position/orientation in a world CRS | `0` Unknown · `1` Position · `2` Position and orientation · `3` Locked | — | `-editInputSelection "inpPose=2"`, `-importFlightLog`, EXIF GPS, XMP `xcr:Position` + `xcr:Rotation` |
| **Prior calibration** | focal, principal point, skew, aspect | `0` Unknown · `1` Approximate · `2` Fixed | `inpCalibrationGroup` (int ≥ 0, `-1` = groupless) | `-editInputSelection "inpCalibration=1"`, `-setPriorCalibrationGroup`, XMP `Camera:CalibrationGroup`, `sensorsdb.xml` |
| **Prior lens distortion** | model + radial/tangential coefficients | `0` Unknown · `1` Approximate · `2` Fixed | `inpLensGroup` (int ≥ 0, `-1` = groupless) | `-editInputSelection "inpDistortion=1"`, `-setPriorLensGroup`, XMP `Camera:LensDistortionGroup`, `sensorsdb.xml` `<lens>` |

[OFFICIAL: tutorials/editselectioncommand for every key and value; appbasics/allcommands for
the commands]

One type discrepancy inside the Help: the **Locked pose group** field is documented as
"type in a **positive integer** … blank or a negative integer to ungroup"
[OFFICIAL: appbasics/camerasettings_priors, appbasics/selectedinputs] but its CLI key
`inpPosePriorRelativeGroup` is typed `string | Any alphanumeric value`
[OFFICIAL: tutorials/editselectioncommand]. Untested which the parser enforces; use an
integer and nothing breaks either way. [OPEN.] Note the *calibration* and *lens* group keys
are unambiguously `int | Any positive whole number, zero or −1 (groupless)` — `0` is a
legal group, `-1` is the only ungrouped value.

Semantics of the strength enums, verbatim in compressed form
[OFFICIAL: appbasics/camerasettings_priors, appbasics/selectedinputs]:

- **Unknown** — value missing or deliberately not applied; RealityScan computes it freely.
- **Approximate** — starting values known; the solver *will adjust them* but should not
  deviate far.
- **Fixed** — user-defined values are used and *not changed*.
- **Relative pose Draft** — inter-camera geometry known to some precision, optimised
  during alignment.
- **Relative pose Exact** — inter-camera geometry known and **not altered**.
- **Absolute pose Position** — position known to some precision, orientation free.
- **Absolute pose Position and orientation** — both known approximately, both optimised.
- **Absolute pose Locked** — no change in camera position *or orientation* allowed.

**The default lens prior is a trap.** [OFFICIAL: appbasics/camerasettings_priors] "By
default, the lens distortion model is set to 'No lens distortion' with prior set to
'Approximate'. This means that RealityScan tries to find a solution where lens distortion
is as close to zero as possible." For any visibly distorted optic that is actively wrong —
supply coefficients or set the prior to `Unknown`.

**But `Approximate` with *no* coefficients supplied does NOT pin distortion to zero.**
The rig's Cinema camera carried `LensDistortionPrior=Approximate` with no coefficients
from the day the registry was written and still solved k1 = −0.0524 over 2,204 cameras.
`Unknown` merely withholds a hint. An earlier caution in this repo ("Approximate would
assert approximately-zero distortion, wrong for a fisheye") was **wrong** and is retained
as superseded. [VERIFIED: FINDINGS 2026-07-25] [CONTRADICTED-in-part: the Help's
"as close to zero as possible" wording describes the *"No lens distortion" model*, not the
`Approximate` strength on a real model — the two are separate fields and the Help sentence
conflates them]

---

## 2. XMP sidecars: the per-image metadata channel

Full treatment of the sidecar format lives in `05-metadata-xmp-and-sidecars.md`; this
section covers only what the geometry layer needs — the rig attributes, the export options
that decide whether rigging and pose are written at all, and the traps that silently void
a prior. Epic's own framing is worth noting: the georeferencing and scaling tutorials both
link "Export and import **camera pose templates**" directly at `tools/xmpalign`, i.e. the
XMP sidecar *is* the product's camera-pose template mechanism.
[OFFICIAL: tutorials/georeferencing, tutorials/scaling — link targets read from the
shipped HTML]

### 2.1 Discovery and naming rules

- An image and an XMP file **with the same stem, in the same folder, act as one** on
  import; everything in the XMP is assigned to the image.
  [OFFICIAL: tools/xmpalign]
- `Image01.jpg` ⇄ `Image01.xmp`. **`image.jpg.xmp` is IGNORED — silently.** A batcher bug
  wrote priors that way, so **no run in this repo before 2026-07-22 ever loaded its
  calibration priors**; it surfaced only as an arithmetic anomaly in sidecar counts (871
  "new" `.xmp` appearing in a folder that already had 904).
  [VERIFIED: NA167 B7, 2026-07-22] [UNDOCUMENTED: the Help states the same-name rule but
  never warns that a near-miss is silent]
- `_common.xmp` in an image folder applies its content to **every** image in that folder.
  [OFFICIAL: tools/xmpalign] — never exercised in this repo. [OPEN]
- `-addImageWithCalibration <fileName> <xmpFileName>` imports an image and an XMP whose
  name and location need **not** match. [OFFICIAL: appbasics/allcommands, tools/xmpalign]
- Adding images **auto-imports** any `<stem>.xmp` found beside them, and a pose-bearing
  sidecar silently becomes an exact-pose prior. Any pipeline that must be independent of a
  previous run has to sanitise the tree first.
  [VERIFIED: NA167 B7, 2026-07-22]

### 2.2 Full attribute reference

The shipped sample [OFFICIAL: tools/xmpalign]:

```xml
<x:xmpmeta xmlns:x="adobe:ns:meta/">
    <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
        <rdf:Description xmlns:xcr="http://www.capturingreality.com/ns/xcr/1.1#" xcr:Version="3"
            xcr:PosePrior="initial" xcr:Rotation="-1 0 0 0 0 -1 0 -1 0" xcr:Coordinates="absolute"
            xcr:DistortionModel="division" xcr:DistortionCoeficients="0 0 0 0 0 0"
            xcr:FocalLength35mm="18" xcr:Skew="0" xcr:AspectRatio="1" xcr:PrincipalPointU="0"
            xcr:PrincipalPointV="0" xcr:CalibrationPrior="initial" xcr:CalibrationGroup="-1"
            xcr:DistortionGroup="-1" xcr:Rig="{1E204070-A17D-444E-9455-493C15B37B93}"
            xcr:RigInstance="{2DC9F356-432F-4234-9148-DC2655788342}" xcr:RigPoseIndex="3"
            xcr:InTexturing="1" xcr:InMeshing="1">
            <xcr:Position>0.262424475861358 -2.26397531586648 7.03879070281982</xcr:Position>
        </rdf:Description>
    </rdf:RDF>
</x:xmpmeta>
```

| Attribute (exact spelling) | Type | Meaning | Tag |
|---|---|---|---|
| `xcr:Version` | int (`"3"`) | XMP schema version written by 2.2 | [OFFICIAL: tools/xmpalign] |
| `xcr:PosePrior` | string (`"initial"` observed) | pose prior strength; corresponds to the export mode of §2.5 (`1` draft → `initial`, `2` exact, `3` locked) | [OFFICIAL] for the sample value; [INFERRED] for the rest — the export-mode enum is now known but the token it writes is not. See Q16 |
| `xcr:Rotation` | 9 floats, row-major 3×3 | camera rotation — see §6 | [OFFICIAL] that it exists; frame [INFERRED] |
| `xcr:Position` | **element**, 3 floats | camera centre. Appears as an **element** in current exports and as an **attribute** in older ones — parse both | [VERIFIED: FINDINGS 2026-07-28] |
| `xcr:Coordinates` | string (`"absolute"` observed) | frame of `Position`/`Rotation` | [OFFICIAL] for the sample; `"relative"` counterpart [INFERRED] from the Relative/Absolute pose split |
| `xcr:DistortionModel` | string (`"division"` observed) | per-image distortion model **hint** | [OFFICIAL] that it exists; [CONTRADICTED] that it selects the model — §5.4 |
| `xcr:DistortionCoeficients` | **6 floats** (Epic's spelling, one `f`) | distortion coefficient vector, fixed width 6 | [OFFICIAL] for the spelling and width; slot order [INFERRED] — §5.3 |
| `xcr:FocalLength35mm` | float, mm | 35 mm-equivalent focal length | [OFFICIAL] |
| `xcr:Skew` | float | image-plane skew | [OFFICIAL] |
| `xcr:AspectRatio` | float | pixel aspect ratio | [OFFICIAL] |
| `xcr:PrincipalPointU` / `xcr:PrincipalPointV` | float | principal-point offset from image centre. Panel units are **mm w.r.t. 35 mm film format**; harvested values are small relatives (e.g. `−0.0071`) | [OFFICIAL] for the panel units (appbasics/selectedinputs, appbasics/reports_fav_cameras `px`); [INFERRED] that the XMP attribute uses the same normalisation |
| `xcr:CalibrationPrior` | string (`"initial"` observed; `Approximate` also accepted) | calibration prior strength | [OFFICIAL] for the sample; [VERIFIED] that `Approximate` is accepted from the `Camera:` namespace form |
| `xcr:CalibrationGroup` | int, `-1` = groupless | calibration group | [OFFICIAL] |
| `xcr:DistortionGroup` | int, `-1` = groupless | lens/distortion group | [OFFICIAL] |
| `xcr:Rig` | GUID | rig **type** id | [OFFICIAL] |
| `xcr:RigInstance` | GUID | rig **instance** id (one physical station/exposure) | [OFFICIAL] |
| `xcr:RigPoseIndex` | int | camera index within the rig | [OFFICIAL] |
| `xcr:InTexturing` / `xcr:InMeshing` | `0`/`1` | "Include editor options" flags | [OFFICIAL] |
| `xcr:Gravity` | vector | gravity direction; consumed by `-setCamerasGravityDirection` | [OFFICIAL: appbasics/allcommands] — never exercised here [OPEN] |

**Export artifact worth knowing:** exported pose sidecars from this repo's runs carry
`xcr:CalibrationGroup="-1"` / `xcr:DistortionGroup="-1"` *alongside* a correct
`Camera:CalibrationGroup="3"`. The `-1` is an export artifact, **not** a lost grouping —
the solve demonstrably honoured the `Camera:` groups (§4.4).
[VERIFIED: FINDINGS 2026-07-26] [UNDOCUMENTED]

### 2.3 The `Camera:` namespace (what this repo actually writes)

The Help's sample uses only `xcr:` attributes in the `.../xcr/1.1#` namespace. This repo
writes a **different, element-based form** in the `.../xcr/1.0/` and
`.../camera/1.0/` namespaces, and RealityScan accepts it — proven by the intrinsics
separation in §4.4. Literal content of `camera_registry.calibration_xmp()`
(`modules/camera_registry.py`):

```xml
<?xml version="1.0" encoding="UTF-8"?>
<x:xmpmeta xmlns:x="adobe:ns:meta/" xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
  <rdf:RDF>
    <rdf:Description xmlns:Camera="http://www.capturingreality.com/ns/camera/1.0/" xmlns:xcr="http://www.capturingreality.com/ns/xcr/1.0/">
      <Camera:CalibrationGroup>2</Camera:CalibrationGroup>
      <Camera:CalibrationPrior>Approximate</Camera:CalibrationPrior>
      <xcr:FocalLength35mm>16.0</xcr:FocalLength35mm>
      <Camera:LensDistortionGroup>2</Camera:LensDistortionGroup>
      <Camera:LensDistortionPrior>Approximate</Camera:LensDistortionPrior>
      <Camera:DistortionModel>division</Camera:DistortionModel>
    </rdf:Description>
  </rdf:RDF>
</x:xmpmeta>
```

Facts about this form:

- It contains **no pose entries by design** — pose sidecars auto-import as exact-pose
  priors on any later `-add`, and the original prior content measurably reduced
  registration (§7.5). [VERIFIED: NA167 B7]
- `Camera:CalibrationGroup` and `Camera:LensDistortionGroup` are the **only** mechanism
  that can separate EXIF-identical cameras. [VERIFIED: docs/settings-evaluation-2026-07 §1–2]
- The element-vs-attribute form and the 1.0-vs-1.1 namespace are both accepted.
  [VERIFIED-by-consequence: the calibration groups demonstrably took effect, FINDINGS
  2026-07-26] [UNDOCUMENTED: no Help coverage of the `Camera:` namespace at all]

### 2.4 Export: `-exportXMP` vs `-exportXMPForSelectedComponent`

| Command | Params XML | Naming of written sidecars | Scope |
|---|---|---|---|
| `-exportXMP [params.xml]` | optional; from the XMP metadata export dialog | **stem-named** `<stem>.xmp` | components from the *last alignment*, gated by `-setMinComponentSize` |
| `-exportXMPForSelectedComponent` | none | **ordinal** `00000.xmp`, `00001.xmp`, … | the selected component |

[OFFICIAL: appbasics/allcommands] for the commands and the min-size gate;
[VERIFIED: FINDINGS 2026-07-23, B10 final form] that **the command determines the naming,
not the scene** — four consistent datapoints; an earlier session-based hypothesis is
SUPERSEDED. [CONTRADICTED: the Help gives no naming rule for
`-exportXMPForSelectedComponent`; ordinal naming is undocumented.]

Both commands carry the same note: **"XMP files are stored in the same folder as the
respective images."** There is no output-path parameter. [OFFICIAL: appbasics/allcommands]
The gate is `-setMinComponentSize <size>`, **default 5**, shared with
`-exportLatestComponents` [OFFICIAL: appbasics/allcommands]; the app also logs that it
"will be removed in the next release", yet it is still required, because components below
the threshold are silently excluded from selection and export
[VERIFIED: NA167 B11, FINDINGS 2026-07-24].

Consequences that bite:

- Ordinal sidecars are **inert as priors** (no image has an ordinal stem) but are still a
  valid registration *count*. `camera_registry.sanitize_and_census` deletes them quietly.
  [VERIFIED: B10, 2026-07-23]
- Per-camera identity is only available from `-exportXMP` in the original aligned scene.
  This is why membership is derived by **successive difference** of stem harvests in the
  `AlignZone.bat` identity loop. [VERIFIED: FINDINGS 2026-07-23]
- Only **registered** cameras get pose entries, so counting pose-bearing sidecars is the
  pipeline's primary registration oracle. [VERIFIED: NA167_SESSION_NOTES §1]
- **Flight-log import leaves its matched images actively selected**, and selection-driven
  exports under `-silent` then export **nothing** (an XMP export completed in 0.057 s
  instead of 20.5 s). `-deselectAllImages` before every export is mandatory.
  [VERIFIED: FINDINGS 2026-07-23] [UNDOCUMENTED]
- **RealityScan writes no XMP sidecars at all when the scene's images resolve through a
  reparse point (directory junction), and reports success.** Four baseline components on
  real paths harvested 267 files; the same workflow on junction-rooted components
  harvested zero, silently, across 18 attempts and 5 h 12 m of correct GPU work. Fix:
  real directories of hardlinked images. [VERIFIED: FINDINGS 2026-07-27/28] [UNDOCUMENTED]
- **The identity harvest permanently strips calibration sidecars** unless restored: the
  harvest *moves* pose-bearing `.xmp` into `identity_r<K>` and the last-peeled component's
  sidecars are never re-exported. Measured on fresh zone_1: 796 of 4,540 images (17.5%)
  left with no sidecar, including an entire 665-camera component. Two later test cells
  re-aligned in that state and their results are confounded. Fixed by
  `camera_registry.ensure_calibration_sidecars()`. [VERIFIED: FINDINGS 2026-07-25]

### 2.5 XMP export options and the `xmp*` params keys

Export dialog fields [OFFICIAL: tools/xmpalign]:

| Field | Effect |
|---|---|
| **Camera export mode** — *draft* | absolute positions exported, **adjustable** during later alignment |
| **Camera export mode** — *exact* | cameras keep their **relative** positions |
| **Camera export mode** — *locked* | **both** relative and absolute positions preserved and not adjusted |
| **Merge with existing XMP files** | new XMPs replace existing ones for the same images |
| **Export rigging setup** | writes the rig setup (`xcr:Rig*`); "when using the laser scans". Disabled ⇒ position and orientation only |
| **Export camera calibration groups** | writes the calibration/lens group ids |
| **Include editor options** | writes `xcr:InTexturing` / `xcr:InMeshing` |
| **Replace GPS Exif with optimized values** | writes solved coordinates instead of EXIF |

The repo's `RS_CLI/Metadata/XMPExportParams.xml`
(`<Configuration id="{EC40D990-B2AF-42A4-9637-1208A0FD1322}">`):

```xml
<entry key="xmpMerge" value="true"/>
<entry key="xmpExGps" value="true"/>
<entry key="xmpFlags" value="true"/>
<entry key="xmpCalibGroups" value="true"/>
<entry key="xmpCamera" value="3"/>
<entry key="xmpRig" value="true"/>
```

Process id `20568 EXPORTING_RIGGING_XMP_FILES` exists, confirming rigging export is a
distinct internal stage. [OFFICIAL: tutorials/processids]

#### The full `xmp*` key family — [UNDOCUMENTED], recovered from the binary

Thirteen `xmp*` keys exist in `RealityScan.exe` 2.2.0.119430; the repo uses six. In the
same string block each key sits beside the params-XML attribute name it serialises to,
which gives the mapping the Help never states.
[UNDOCUMENTED: UTF-16 string extraction from
`C:\Program Files\Epic Games\RealityScan_2.2\RealityScan.exe`, this session]

| Key | Adjacent attribute name | Dialog field it corresponds to |
|---|---|---|
| `xmpCamera` | `CameraExportMode` | **Camera export mode** |
| `xmpPose` | `Pose` (`pose_int`) | **Poses export mode** — "Export just positions" / "Export positions and orientations" |
| `xmpPrecision` | `Precision` (`precision_int`) | **Registration precision** — "Should cameras be optimized in the future?" |
| `xmpComponentMode` | `ComponentMode` (`component_mode_int`) | **Component relations** — "Define inter-camera relations" |
| `xmpCalib` | `Calibration` | "Check to export internal camera calibration parameters like focal length or lens distortion" |
| `xmpCalibGroups` | `CalibrationGroups` | **Export camera calibration groups** |
| `xmpRig` | `Rig` | **Export rigging setup** |
| `xmpMerge` | `MergeWithExistingFiles` | **Merge with existing XMP files** |
| `xmpExGps` | `ReplaceGPSExif` | **Replace GPS Exif with optimized values** |
| `xmpFlags` | `UseConfigFlags` | **Include editor options** (`xcr:InTexturing`/`xcr:InMeshing`) |
| `xmpEnabledOnly` | `EnabledCamerasOnly` | "Export enabled images only" |
| `xmpImageList` | — | "Export an image list … can be used later to import exported images" |
| `xmpPath` | — | export location (a second string, `xmp file path`, sits in the same block) |

**`xmpComponentMode` is the rig-relevant one and is not in the Help at all.** Its three
options, verbatim from the binary's combo tooltips:

| Option | Tooltip |
|---|---|
| **Absolute** | "Every camera is treated independently, i.e. like if they were globally registered" |
| **Relative** | "Cameras form a group whose common global position, orientation and scale are not known" |
| **Rigid** | "Scale of the camera group is fully determined, but the global position and orientation is not known" |

That is precisely the rig-export vocabulary: *Rigid* exports a camera group whose internal
scale is fixed — the thing a multi-camera rig wants — and it has **never been exercised
here**. [UNDOCUMENTED] [OPEN — see Q6.]

#### [LARGELY RESOLVED] `xmpCamera=3` is *Export as locked*

The camera-export-mode combo is a **four**-entry list, recovered verbatim as one
comma-separated resource string. The raw bytes read
`…relative poses are precise0Export as locked…`; the `0` is [INFERRED] to be a
resource-table length prefix rather than part of the text, on the grounds that the other
three separators are commas and `0` is not a plausible sentence ending:

```
Do not export,Export as draft - initial starting positions,Export as exact - relative poses are precise,Export as locked - fixed in further calculations
```

| Index | Option |
|---:|---|
| `0` | Do not export |
| `1` | Export as draft — initial starting positions |
| `2` | Export as exact — relative poses are precise |
| `3` | **Export as locked — fixed in further calculations** |

So `xmpCamera=3` selects **locked**. **This repo's `-exportXMP` therefore writes pose
sidecars carrying LOCKED priors**, which is the worst case for the B7 auto-import
contamination in §2.1: any later `-add` of the same folder imports cameras that
RealityScan is forbidden to move, *and* §3.3's "Exact/Locked cannot be grown
incrementally" then applies. `camera_registry.sanitize_and_census` /
`ensure_calibration_sidecars` are what stand between that and a corrupted re-align — they
are not optional hygiene.
[UNDOCUMENTED: binary UI resource strings, this session] [INFERRED that the same enum
backs `xmpCamera` rather than the adjacent `xmpPrecision`: `CameraExportMode` is the
attribute name paired with `xmpCamera`, and the Help's own XMP dialog names this field
"Camera export mode" with exactly the draft/exact/locked options. **Confirm in one
second** by `findstr xcr:PosePrior` on any sidecar `-exportXMP` produced — a value of
`locked` settles it. See Q1.]

---

## 3. Rigs: `xcr:Rig` / `RigInstance` / `RigPoseIndex`

### 3.1 What a rig is in RealityScan's model

A rig is a set of inputs whose **relative** pose is shared and reused across exposures.
The Selected-Input panel exposes exactly three rigging fields
[OFFICIAL: appbasics/selectedinputs, "Rigging"]:

| Panel label | Meaning | XMP attribute | `-editInputSelection` key |
|---|---|---|---|
| **Rig ID** | *type* of rig, e.g. LiDAR scan point clouds | `xcr:Rig` (GUID) | `inpRigId` / `inpRig` |
| **Prior** | identifier of a rig **instance** at a certain position — all 6 `.lsp` files for one scanner position share this number | `xcr:RigInstance` (GUID) | `inpRigInstance` |
| **Model** | camera **index within** the rig (e.g. 0–5 for an `.lsp` set) | `xcr:RigPoseIndex` (int) | `inpRigIndex` |

Panel→XMP mapping is [OFFICIAL] by name correspondence. The `inpRig*` keys are
**[UNDOCUMENTED]** — they do not appear in `tutorials/editselectioncommand`; they were
recovered as key-shaped strings from `RealityScan.exe` 2.2.0.119430 and appear in the
selection-edit key space alongside the documented `inp*` keys
(`SURVEY_settings.md` Tier 4). The full set in the binary is `inpRig`, `inpRigId`,
`inpRigIndex`, `inpRigInstance` and **`inpRigValid`** (a fifth the survey omits), beside
`inCreateRig` and the internal command names `EditSfmRigCommand` /
`EditSfmRigInstanceCommand`. Their value grammar is unverified. [INFERRED] that
`inpRigId`/`inpRigInstance` take GUID strings and `inpRigIndex` an int, by analogy with the
XMP attributes. The XMP parse path strings `/xcr:Rig`, `/xcr:RigInstance` and
`/xcr:RigPoseIndex` are also present, confirming the sidecar attributes are read.
[UNDOCUMENTED: binary string extraction, this session]

#### [CONTRADICTED] The Help says rigging is for laser scans; the product ships an image-rig wizard

- **Docs say**: "Rigging parameters are applicable only for inputs connected in a rig
  (e.g. individual `.lsp` files in one LiDAR scanner position)" and, for **Export rigging
  setup**, "Enable to export the rig setup information **when using the laser scans**."
  [OFFICIAL: appbasics/selectedinputs, tools/xmpalign] The string `rig` appears in exactly
  **two** topics of the entire shipped Help — those two.
- **Observed**: `RealityScan.exe` 2.2.0.119430 contains a **Rig Creation Wizard** whose own
  first sentence is image-based: *"A rig represents a set of cameras mounted together which
  are synchronously taking pictures. This wizard will help you map these images to rigs."*
  It is reached from an Inputs-panel button **"Create a rig" / "Open the Rig Creation
  Wizard — Create a camera rig from the selected input images"**, sitting beside the three
  buttons that *do* have CLI equivalents (Group → `-setCalibrationGroupByExif`,
  Constant → `-setConstantCalibrationGroups`, Ungroup → `-removeCalibrationGroups`).
  Related strings: `Create Rig from Images in the Folder`, `Rigging Panel`, `Rigging View`,
  `Rig Report`, `Rig mapping options`.
- **How observed**: UTF-16 string extraction from the shipped executable, cross-checked
  against a full-text search of the offline Help for "rig creation"/"create a rig"
  (zero hits). [UNDOCUMENTED: this session]
- **Consequence**: image rigs are a first-class product feature that the 2.2 Help does not
  document at all, and the "LiDAR only" reading should not be used to conclude that a
  camera rig is unsupported.

The same Help also says a rig arises from **images with exact or locked XMP files**:
"Relative coordinates … This option is visible only for the inputs that are connected in a
rig (e.g. individual `.lsp` files in one LiDAR scanner position, **or images with exact or
locked XMP files**)." [OFFICIAL: appbasics/selectedinputs] So an image rig can be declared
by *pose-prior strength* as well as by `xcr:Rig*` ids and by the wizard. The three
mechanisms are not reconciled by any Help page.
[UNDOCUMENTED: their interaction.]

#### How the wizard maps images to rigs — `#rig` / `#pose` / `#camera`

The wizard's mapping is **path-pattern based**, and the pattern vocabulary is exactly what
a filename-encoded rig like §10.2's needs:

> "The keywords `#rig`, `#pose`, `#camera` represent rig name, rig pose name, and camera
> name in the file path string."

Four patterns ship as `RigGroupingFormatOptions` (backslash = a directory level,
underscore = a filename separator):

| Pattern | Layout it expects |
|---|---|
| `#rig\#pose\#camera.*` | rig folder / pose folder / camera-named file |
| `#rig\#pose_#camera.*` | rig folder / `<pose>_<camera>.ext` |
| `#rig\#camera_#pose.*` | rig folder / `<camera>_<pose>.ext` |
| `#rig_#pose_#camera.*` | all three in one flat filename |

There is also a **"File name"** grouping option — "Cameras will be grouped by the file
name" — and a rig **can be imported from XML**: the strings `Rig Setup Import`,
`Import Rig Definition` and the file-dialog filter `Rig Definition XML Files` all exist.
**No rig schema ships in the install root** (`C:\Program Files\Epic Games\RealityScan_2.2`
contains `calibration.xml`, `flightlogs.xml`, `sensorsdb.xml`, … but nothing rig-named), so
the definition file's grammar is unknown and would have to be obtained by exporting one
from the wizard. The wizard's per-rig fields are `Rig ID` ("A unique identifier of a rig"),
`Name` ("Rig-friendly name"), and `Rig pose ID` ("Unique rig pose identifier") — the same
three concepts as `xcr:Rig` / `xcr:RigInstance`.
[UNDOCUMENTED: binary UI strings, this session] [OPEN — see Q6.]

**None of this is reachable from the CLI.** `appbasics/allcommands` contains no rig command
of any kind, and neither does the recovered command table in `SURVEY_commands.md`. Headless
rig declaration therefore has to go through XMP sidecars or `-editInputSelection` with the
undocumented `inpRig*` keys. [VERIFIED-by-absence: full-text search of
`appbasics/allcommands` and `SURVEY_commands.md`.]

### 3.2 How to declare a multi-camera rig (documented paths)

1. **XMP, per exposure.** Give every image from one simultaneous exposure the same
   `xcr:RigInstance` GUID, a stable `xcr:RigPoseIndex` per physical camera (0..N−1), the
   same `xcr:Rig` type GUID for the whole rig, and pose data with the export mode set to
   *exact* (relative positions preserved) or *locked* (relative **and** absolute).
   [OFFICIAL: tools/xmpalign — the sample XMP is exactly this shape]

   > **[CONTRADICTED 2026-08-23] Route 1 is NOT sufficient on its own.** Declaring
   > `xcr:Rig` makes RealityScan demand a companion **rig file** beside the images and
   > abort the run when it is absent — see §3.5. The sample XMP's shape is necessary but
   > not sufficient.
2. **CLI, per selection.** Select the images of one physical camera, then
   `-editInputSelection "inpPosePriorRelative=2"` (Exact) and a shared
   `-editInputSelection "inpPosePriorRelativeGroup=<name>"`. [OFFICIAL:
   tutorials/editselectioncommand] The locked-pose *group* is the documented
   "these cameras move together" handle.
3. **After a solve.** `-lockPoseForContinue true` on a selection freezes the relative pose
   of already-registered cameras for the next registration — the documented batch-growth
   pattern ("Align the first set, fine-tune, lock positions, add another set, align
   again… camera positions cannot be changed (e.g. the component cannot be split)").
   [OFFICIAL: appbasics/allcommands, appbasics/selectedinputs]

Two further routes exist but are **not documented**: the GUI **Rig Creation Wizard** with a
`#rig`/`#pose`/`#camera` path pattern, and the `inpRig*` selection keys (§3.1). Only routes
1–3 are headless *and* documented.

The full-body-scan tutorial is the canonical use case and states the CLI branch outright:
a *fixed-camera setup* with a *fixed coordinate system* processed automatically uses "the
RealityScan workflow with **XMP metadata**", while a *bending-camera* setup uses "the
RealityScan workflow with **flight-log data**". Scans with an arbitrary coordinate system
cannot be automated at all "because none of the available data and metadata can be reused
suitably". [OFFICIAL: videotutorials/fullbodyscans/fullbodyscanstutorials]

### 3.3 How a fixed rig constrains alignment — and the one hard limit measured here

- A fixed rig removes 6 DoF per exposure beyond the first camera and lets the solver pool
  matches across the rig. [INFERRED from the prior semantics; not isolated by any cell here.]
- **Exact-mode priors cannot be grown incrementally.** `-editInputSelection "inpPose=3"`
  (Locked) takes effect, but `-align` then refuses with: *"prior set to 'Exact' mode must
  be all aligned in a single run. Incremental adding is not supported."* Pose-locking is
  therefore **unusable as a growth anchor**; checkpoint/rollback (a plain `.rsproj` file
  copy) stays the never-shrink mechanism.
  [VERIFIED: FINDINGS cell U18 FAIL, 2026-07-23] [UNDOCUMENTED: the Help advertises
  lock-and-continue as *the* batch pattern and never mentions this restriction]
- **RealityScan has no stereo-rig support** (staff-confirmed through Aug 2025), which
  implies rig scale must come from GCPs, distance constraints, or locked XMP rather than a
  declared baseline. [VERIFIED-second-hand: COLMAP fact base F-20260723-27, recorded here
  2026-07-24] — treat as the weakest link in any scale plan.

### 3.4 What this repo does *not* do

**No rig has ever been declared through this CLI.** The four-camera ROV rig is handled
purely as four *calibration groups* plus per-image pose priors from the trajectory; no
`xcr:Rig`, `xcr:RigInstance` or `xcr:RigPoseIndex` is written, and `inpRig*` has never been
sent. `xmpRig=true` is set in `XMPExportParams.xml`, so *exports* would carry rigging if
RealityScan had any to write. [VERIFIED-by-inspection: `modules/camera_registry.py`,
`RS_CLI/Metadata/XMPExportParams.xml`, and the absence of any rig identifier in the repo]

This is a deliberate consequence of the rig being **non-rigid in practice**: the cameras
are on an ROV frame whose mount angles differ *per cruise* for the same physical unit
(§10.3). A declared Exact rig would also forbid incremental growth (§3.3), which is the
pipeline's primary recovery mechanism for zones that fail solo.
[INFERRED — the reasoning is sound but no cell tested a declared rig on this data.] The
untested opportunity is real, and larger than the repo's own notes suggest:

- the rig-internal C–P geometry has been measured twice on metrically sound solves and is
  stable to ~0.1 m (§10.4) — exactly the input a **Draft**-strength relative-pose rig wants;
- the WCA filenames already encode camera identity and exposure time
  (`P231C0003_20231104202628_edt.jpg`), which is the shape the Rig Creation Wizard's
  `#rig_#pose_#camera` mapping consumes (§3.1);
- `xmpComponentMode=Rigid` (§2.5) exports "a camera group whose scale is fully determined"
  — the closest thing the product has to declaring a metric rig baseline, and the natural
  companion to the missing stereo-rig support in §3.3.

[OPEN — see Q6.]

---

### 3.5 [VERIFIED 2026-08-23] `xcr:Rig` requires a `.rcrx` rig file — and what to do instead

Measured on a two-camera stereo survey (Sony ILX-LR1 pair, 483 images), RealityScan
2.2.0.119430.

**The blocker.** Sidecars carrying `xcr:Rig` / `xcr:RigInstance` / `xcr:RigPoseIndex` in
the documented attribute form, with 201 rig instances over 402 images, produced this on
`-add`:

```
Missing rig file: '<image dir>\rig7F3A1C58-2E64-4B90-A1D7-6C50B93E28AA.rcrx'
```

i.e. `rig<GUID-without-braces>.rcrx` next to the imagery. The workflow then died at the
next command (`-deselectAllImages`, rc=1, **0 images registered**). Reproduced on two
arms, raw and preprocessed. No `.rcrx` file ships anywhere under the install tree and the
extension appears in **no** Help topic, so its format is unknown and the image-rig route is
effectively closed from the CLI until someone reverse-engineers it.
**Do not declare `xcr:Rig` unless you can also supply the `.rcrx`.**

**What works instead — hand RealityScan an external solve as locked poses.** Dropping the
three rig attributes and writing pose sidecars only:

| | best RealityScan self-alignment | COLMAP poses supplied via XMP |
|---|---:|---:|
| registered | 87 / 483 | **392 / 483** |
| components | fragmented | **1** |
| rig baseline (measured 225.425 mm) | 224.71 mm | **225.42 mm** |
| pairs within 5 % of baseline | 53.8 % | **100 %** |

The relative geometry the rig declaration would have imposed is already implied by the
absolute poses, so nothing was lost by dropping it.

**Token behaviour.** `xcr:PosePrior="locked"` and `xcr:PosePrior="exact"` gave *identical*
results (392 registered, scale ratio 1.0000, zero residual against the supplied values),
and **both are echoed back as `"initial"`** on re-export. The echo therefore cannot be used
to confirm which strength was applied, and the mode-2/mode-3 token question stays open.

**What survives the round-trip.** `Position`, `Rotation` and `FocalLength35mm` came back
bit-for-bit. `CalibrationGroup` and `DistortionGroup` were reset to `-1`, and
`DistortionModel` to `perspective` — the latter despite a global
`sfmDistortionModel=Brown3`, which is consistent with §5.4.

**What it does not prove.** RealityScan *adopted* the supplied poses rather than re-solving
them, so none of this is independent corroboration of the external solve. It is a transport
mechanism, not a validation.

## 4. Calibration groups vs distortion (lens) groups

### 4.1 Semantics

"By defining a calibration group we state that all images in this group have the same
properties, e.g. the same focal length, the same principal point or the same lens
distortion coefficients." [OFFICIAL: appbasics/camerasettings]

- **Calibration group** — shared focal / principal point / skew / aspect.
- **Lens (distortion) group** — shared distortion coefficients.
- `-1` in either field means *do not group*; any other integer groups.
  [OFFICIAL: appbasics/camerasettings, appbasics/selectedinputs]

Documented benefits: fixed-optics cameras (GoPro-class) where the same focal and distortion
are expected; **weak-texture or low-feature-count scenes, because grouping means fewer
parameters to estimate and therefore fewer feature points needed**; and forcing a set of
cameras to share a focal length. Documented cost: high-resolution bodies (60 Mpx+) show
real per-exposure variation from focus/mechanical/thermal drift that grouping suppresses.
[OFFICIAL: appbasics/camerasettings]

Documented refinement pattern: **group → align → ungroup → align again.** "After
calculating a scene with grouped camera parameters, ungroup camera parameters and align the
scene again. It will fine-tune the camera parameters and the scene also stays
well-conditioned. This is recommended for scenes with weak texture or small image count.
Alignment in such case will take just a few seconds." [OFFICIAL: appbasics/camerasettings]
— **never exercised in this repo.** [OPEN — see Q5.]

### 4.2 CLI entry points

| Command | Effect | Notes |
|---|---|---|
| `-setPriorCalibrationGroup <number>` | set prior calibration group on the **selected** images; `-1` = ungroup | key equivalent `inpCalibrationGroup` |
| `-setPriorLensGroup <number>` | set prior lens group on the selection; `-1` = ungroup | key equivalent `inpLensGroup` |
| `-setConstantCalibrationGroups` | group **all selected** inputs into a single calibration group | |
| `-setCalibrationGroupByExif` | set the calibration group of **all inputs** from their EXIF | Help wording says all inputs, not just the selection |
| `-removeCalibrationGroups` | clear **all** inputs from their calibration groups | project-scope, not selection-scope |
| `-set "appGroupCalibrationByExif=<bool>"` | group calibration by EXIF *at import*; default `false` | [OFFICIAL: tutorials/setkeyvaluetable] |

[OFFICIAL: appbasics/allcommands for all five commands]

### 4.3 When to share and when to separate

| Situation | Group? | Why |
|---|---|---|
| One body, fixed prime, one physical unit | **share** one calibration + one lens group | fewer parameters, better conditioning [OFFICIAL] |
| Two physical units with the *same lens model* | **separate** | different units have different real intrinsics — sharing forces a compromise that is wrong for both [VERIFIED: settings-evaluation §2 + §4.4 below] |
| Zoom lens, focal changed mid-shoot | **separate per focal** | grouping asserts a constant focal that is false [INFERRED from the group definition] |
| Weak texture / few images | **share aggressively**, then ungroup and re-align | explicit Epic guidance [OFFICIAL: appbasics/camerasettings] |
| ≥ 60 Mpx body, high-precision target | **do not group**, or group then ungroup | per-exposure optics drift is visible at that resolution [OFFICIAL] |
| One image with a **different pixel footprint** | it separates itself | a different sensor footprint means different intrinsics regardless of the declared group [VERIFIED: FINDINGS 2026-07-25 — exactly one of 8,197 rig JPGs is 3846×2163 while the other 8,196 are 4244×2827] |

**One group per PHYSICAL camera, never per lens type.** This is the governing rule for
multi-camera rigs. Port and Starboard on the ROV rig share a lens *spec* but are different
units. The pre-2026-07 writer grouped three cameras together as "12 mm fisheye" when one of
them was a rectilinear 17 mm — plausibly the whole explanation for the priors A/B that cost
6.7 points of registration (§7.5). [VERIFIED: docs/settings-evaluation-2026-07 §2]

### 4.4 Proof that XMP grouping works (and how it was measured)

The rig's two WCA cameras are **EXIF-identical**: `Make="Z CAM"`, `Model="E2-F6"`, exposure
data, **no focal length and no lens tag**, 4244×2827, Lightroom-rendered from a full-frame
sensor. RealityScan cannot tell them apart from EXIF, so `appGroupCalibrationByExif` is
unusable in *either* position — enabled it collapses two different lenses into one group;
left `false` the images calibrate without grouping at all, which is weak.
[VERIFIED-by-inspection: settings-evaluation §1, 2026-07-23]

Both cameras were given the **same 16.0 mm prior** and separated only by their XMP groups.
Over 5,050 harvest records from the PD-6 run:

| Camera | Group | Records | Focal 35 mm-eq (median, IQR) | division k1 (median, IQR) | Principal point | Skew | Aspect |
|---|---|---:|---|---|---|---|---|
| cinema | 3 | 2,558 | **16.374** (16.302–16.476) | **−0.0378** (−0.0415…−0.0336) | (−0.0071, −0.0031) | 0 | 1 |
| port | 2 | 2,492 | **15.499** (15.435–15.574) | **−0.3875** (−0.3933…−0.3832) | (+0.0027, +0.0056) | 0 | 1 |

The solve separated the two by **5.6 %** with IQRs of ±0.5 %, and the order-of-magnitude
k1 gap is the fisheye declaring itself. Because the JPGs are EXIF-identical, the XMP groups
are the *only* mechanism that could have produced the separation — this is independent
confirmation that the sidecar grouping is honoured, not merely written.
[VERIFIED: FINDINGS 2026-07-26, parsed from the PD-6 identity harvest]

#### [VERIFIED 2026-08-23] Independent confirmation, using the DOCUMENTED `xcr:` form

§4.4's proof used the `Camera:`-namespaced sidecars this repo writes (§2.3). The same
conclusion now holds for the **documented `xcr:` attribute form**, measured on a different
rig and by a different statistic — the within-eye *spread* of solved focal, which a real
group must collapse:

| Arm | Sidecars | Eye | Focal IQR | Focal p10–p90 | `CalibrationGroup` echoed back |
|---|---|---|---:|---:|---|
| `L_all_levers` | none | left | 1.175 | **10.432** | `-1` |
| `L_all_levers` | none | right | 9.569 | **22.995** | `-1` |
| `M_rig_all` | `xcr:CalibrationGroup` + `xcr:FocalLength35mm` | left | 0.173 | **0.228** | `2` |
| `M_rig_all` | same | right | 0.105 | **0.182** | `3` |

Supplying the group collapses the spread by 50–100× and RealityScan echoes a real group id
instead of `-1`. **RealityScan RENUMBERS supplied groups** — 1 and 2 came back as 2 and 3 —
so the grouping *structure* is preserved but the identifiers are not; never key anything off
the id you wrote.

A caution on method: an earlier reading of this same pair of arms attributed a
registration-count difference (87 → 66) to the calibration priors. That difference is
**inside the run-to-run noise** of this dataset (§ below) and proved nothing. The focal-spread
statistic above is deterministic and is what the claim rests on.
[VERIFIED: onr2 arms L_all_levers vs M_rig_all, 2026-08-23]

#### [VERIFIED 2026-08-23] RealityScan alignment is not necessarily repeatable — check before attributing

On this dataset, bit-identical reruns of the same configuration gave **26 vs 55** and
**76 vs 61** registered images. Within-configuration spread (15–29) covered a third to a
half of the entire range seen *across* thirteen different configurations (26–87). Any
attribution of an effect smaller than that spread is unfounded.

`-align` exposes no seed key in `AlignmentParams.xml`. **Run one replicate before ranking
settings**, particularly on marginal, low-texture or near-degenerate geometry.
[VERIFIED: onr2 arms A/A2 and E/E2, 2026-08-23]

### 4.4a Reading grouping back out — the direct check nobody used

§4.4 proved grouping statistically, from 5,050 harvested sidecars. There is a direct route:
`-exportReport <out.html> <template>` with a template using the report function
**`$ExportInputsGrouping`**, which exposes `groupCount`, `groupedInputCount`,
`ungroupedInputCount` and, per group via `$IterateGroups`, the variables
`groupIndex`, **`calibrationGroup`**, **`distortionGroup`**, `refWidth`, `refHeight`,
`refImageIndex`, `count`, `cameraModel`, `lensModel`.
[OFFICIAL: appbasics/reports_fav_cameras] Minimal template body:

```
$ExportInputsGrouping(groups=$(groupCount) grouped=$(groupedInputCount) ungrouped=$(ungroupedInputCount)
$IterateGroups(g$(groupIndex) calib=$(calibrationGroup) lens=$(distortionGroup) n=$(count) $(refWidth)x$(refHeight) $(cameraModel) $(lensModel)
))
```

This answers "did my `Camera:CalibrationGroup` sidecars actually take?" in one command
instead of a 5,000-record harvest, and it also surfaces the pixel-footprint outlier of
§10.8 (`refWidth`/`refHeight` differ for a group of one).
**Never exercised in this repo.** [OPEN — the function is documented; only its behaviour
on this rig is untested.] See `10-reconstruction-texturing-export.md` for report mechanics.

### 4.5 `sensorsdb.xml` — the camera database

`C:\Program Files\Epic Games\RealityScan_2.2\sensorsdb.xml` (the Help says the *user* copy
lives at `C:\ProgramData\Epic\RealityScan\sensorsdb.xml`). Structure
[OFFICIAL: appbasics/cameradb, corroborated by direct read of the shipped file]:

```xml
<cameras>
  <camera model="Apple iPhone 4" ccdWidth="4.5400" GPSMode="ignore"/>
  <camera model="Canon Canon EOS 5D Mark II" ccdWidth="35.9500"/>
  <camera model="Gopro HD3"><lens type="division" focal="15" c1="-0.3143"/></camera>
</cameras>
```

| Attribute | Meaning |
|---|---|
| `model` | matched against the EXIF camera model string (and, where present, the lens model) |
| `ccdWidth` | sensor width in mm; lets RS compute a 35 mm equivalent when EXIF has only a native focal. Defining it also clears the yellow "incomplete camera information" mark |
| `GPSMode="ignore"` | ignore this camera's EXIF GPS |
| `<lens type=… focal=… c1=…>` | distortion prior for a given focal; interpolated for other focals of the same camera+lens model |
| `quality="exact"` on `<lens>` | make it a **hard** prior the solver will not change (default is a soft prior) |

Matching uses **camera model + lens model + focal length** together, and for a
camera+lens pair present at other focals RealityScan interpolates the distortion for an
unseen focal. [OFFICIAL: appbasics/cameradb] The shipped file is almost entirely
`ccdWidth` entries: a direct read finds exactly **two** `<lens>` elements
(`Gopro HD3` and `GoPro Hero3-Black Edition`, both
`<lens type="division" focal="15" c1="-0.3143"/>`) and **zero** occurrences of
`quality="exact"` — the hard-prior form is documented but not exemplified anywhere in the
shipped data. [VERIFIED-by-direct-read of the shipped `sensorsdb.xml`, this session]

**Unusable for the ROV rig**: its entries are keyed to NA167-era model strings ("ZCAM F6
8-15mm Fisheye Upper") that cannot match the current EXIF, and the database is keyed on
model strings, so it cannot distinguish two cameras with identical EXIF anyway.
[VERIFIED-by-inspection: settings-evaluation §1]

---

## 5. Distortion models and the coefficient vector

### 5.1 The global setting

```bat
RealityScan.exe -delegateTo RS1 -set "sfmDistortionModel=Division"
```

| Value (exact spelling) | Coefficients | Epic's description |
|---|---|---|
| `Division` | 1 | "reliably covers simple distortions but works very well also for fish-eyes optics (for example GoPro). The distortion is modelled by means of a single-parameter division model." |
| `Brown3` | 3 radial | "the most popular distortion model worldwide. It works for optics with less than 180°… polynomial model of radial distortion with 3 modelling parameters. **Used as default.**" |
| `Brown4` | 4 radial | "able to cover different distortion in the middle and borders of an image" |
| `Brown3WithTangential2` | 3 radial + 2 tangential | adds tangential distortion, "can compensate offset of lenses" |
| `Brown4WithTangential2` | 4 radial + 2 tangential | same, on Brown4 |
| `KplusBrown3WithTangential2` | + skew + aspect | "add to the Brown model a possibility to optimize the whole camera calibration, including Skew and Aspect ratio" |
| `KplusBrown4WithTangential2` | + skew + aspect | same, on Brown4 |

[OFFICIAL: appbasics/settings_distortion_models for the descriptions;
tutorials/setkeyvaluetable for the key, type and `Brown3` default]

"If K + … is not used, RealityScan by default assumes a zero skew and aspect ratio as 1."
[OFFICIAL] — consistent with the harvest above reporting skew 0 and aspect 1 for every
camera under `Division`.

Epic's own recommended workflow: "starting with a simpler Division model first, and later
change it to Brown and click Align Images (F6) to optimize data."
[OFFICIAL: appbasics/settings_distortion_models]

### 5.2 The per-image enum is a *different* enum

`-editInputSelection "inpDistortionModel=<n>"`. Note the key table labels this field
**"Camera model"** while the Selected-Input page labels the same field **"Model"**
[OFFICIAL: tutorials/editselectioncommand vs appbasics/selectedinputs] — the same string
"Camera model" also labels the trajectory-import distortion setting `ifDistortionmode`
(§9.3), so do not use the label to identify the setting; use the key.

| `inpDistortionModel` | Model |
|---|---|
| `0` | No lens distortion |
| `1` | Division |
| `2` | Brown3 |
| `3` | Brown4 |
| `4` | Brown3 with tangential distortion |
| `5` | Brown4 with tangential distortion |

[OFFICIAL: tutorials/editselectioncommand]

Two mismatches with the global key, both real and both undocumented as such:

- The per-image enum has **`0` = No lens distortion**, which the global `sfmDistortionModel`
  enum does not offer. [OFFICIAL, by comparing the two tables]
- The per-image enum has **no K+ variants**. So skew/aspect optimisation is a *global-only*
  choice. [OFFICIAL, same comparison] [UNDOCUMENTED: neither page mentions the other.]

### 5.3 What `xcr:DistortionCoeficients` means

The vector is **fixed width 6** regardless of model — the shipped sample carries
`"0 0 0 0 0 0"` while declaring `division`, a one-parameter model.
[OFFICIAL: tools/xmpalign]

Slot order is **[k1, k2, k3, k4, t1, t2]**. Evidence
[INFERRED — as strongly evidenced as an untested inference gets]:

- `appbasics/reports_fav_cameras` defines exactly six camera-distortion variables in that
  order: `k1 k2 k3 k4 t1 t2` (plus the distorted-calibration twins `k1d…t2d`).
  [OFFICIAL]
- The shipped Maya export body writes them as one array in that order:
  `setAttr -k on ".lensDistortion" -type doubleArray 6 $(k1) $(k2) $(k3) $(k4) $(t1) $(t2);`
  [shipped schema: `calibration.xml`, format `{93B7C9C6-…}`]
- The shipped OpenCV export **explicitly reorders** them and says so — header
  `…k1,k2,t2,t1,k3,k4 (… Brown lens distortion model coefficients provided in **OpenCV
  ordering**)`, body `$(k1),$(k2),$(t2),$(t1),$(k3),$(k4)`. Since OpenCV's order is
  (k1, k2, p1, p2, k3, k4), the mapping is **RS `t2` ⇄ OpenCV `p1`** and
  **RS `t1` ⇄ OpenCV `p2`** — RealityScan's tangential indices are *swapped* relative to
  OpenCV's. [shipped schema: `calibration.xml`, format `{B5331837-…}`]

Per model, the slots that carry meaning:

| Model | k1 | k2 | k3 | k4 | t1 | t2 |
|---|---|---|---|---|---|---|
| No lens distortion | — | — | — | — | — | — |
| `Division` | ✔ (the single parameter) | — | — | — | — | — |
| `Brown3` | ✔ | ✔ | ✔ | — | — | — |
| `Brown4` | ✔ | ✔ | ✔ | ✔ | — | — |
| `Brown3WithTangential2` | ✔ | ✔ | ✔ | — | ✔ | ✔ |
| `Brown4WithTangential2` | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ |
| `Kplus…` | as above, **plus** skew and aspect become free parameters | | | | | |

[INFERRED] from the coefficient counts stated in `appbasics/settings_distortion_models`
plus the panel fields `Radial 1/2/3/4` and `Tangential 1/2`
[OFFICIAL: appbasics/camerasettings_priors]. That `Division`'s single parameter lands in
the **k1** slot is corroborated twice: `sensorsdb.xml` names the single division
coefficient `c1` on a one-coefficient `<lens type="division" focal="15" c1="-0.3143"/>`,
and this repo's harvest reads "division k1" straight out of exported records
[VERIFIED: FINDINGS 2026-07-26]. **The mathematical form of the division model is not
stated anywhere in the shipped Help** — do not assume a particular normalisation of r when
converting to or from another engine. [OPEN — see Q3.]

`inpRadial1`…`inpRadial4`, `inpTangential1`, `inpTangential2` are the per-image setters for
the same six slots. [OFFICIAL: tutorials/editselectioncommand]

### 5.4 [CONTRADICTED] The per-image model does not override the global key

- **Docs say**: `appbasics/camerasettings_priors` and `appbasics/selectedinputs` both
  document a per-image lens-distortion **Model** field, and `tools/xmpalign` shows
  `xcr:DistortionModel` in the sample sidecar — the natural reading is that a mixed-optics
  rig can run one model per camera.
- **Observed**: with `sfmDistortionModel=Division` set globally, **all 2,558 cinema pose
  XMPs came back `xcr:DistortionModel="division"`** despite their sidecars declaring
  `brown3` — identical to the 2,492 port records. Aggregated from 5,050 harvest records.
  `sfmDistortionModel` is **global and all-or-nothing**; only the *coefficients* differ per
  calibration group.
- **How observed**: parsing `xcr:` attributes out of every sidecar produced by the PD-6
  identity harvest, then grouping by camera. [VERIFIED: FINDINGS 2026-07-26; PD-2]
- **Consequence**: a mixed fisheye/rectilinear rig gets **one** model. This retires the
  "per-camera model via XMP" design in `docs/settings-evaluation-2026-07 §3`. Supplying
  measured coefficients per group remains useful and per-group.
- An earlier repo statement — "per-image XMP overrides the global key"
  (settings-evaluation §3) — is **SUPERSEDED**.

### 5.5 Choosing a model — measured, not theoretical

| Evidence | Result |
|---|---|
| Z3 (124 images), Division vs the Brown3 baseline | **112/124 vs 102/124** — Division best of the whole cell series; **both** cameras solved division and the rectilinear camera did **not** degrade [VERIFIED: PD-1, 2026-07-25] |
| Z1 (4,540 images), Division + loose priors + intact sidecars (PD-6) vs Brown3 baseline | 4,394/4,540 in **2** components at hull scale **0.981**, vs 4,405 in **3** components at hull scale **0.175** [VERIFIED: PD-6, 2026-07-25] |
| Attribution caveat on PD-6 | it differs from the baseline in **three** ways — Brown3→Division, accuracy columns actually importing for the first time, and orientation priors removed. **Do not attribute the scale repair to Division alone.** The isolating cell (Brown3 + explicit-loose on zone_1, ~70 min) was never run [VERIFIED-as-caveat: FINDINGS 2026-07-26] [OPEN] |

Practical decision rules:

- **Any fisheye in the scene ⇒ `Division`.** It is Epic's stated fisheye model, and on this
  rig it did not cost the rectilinear camera anything measurable.
- **Rectilinear-only, well-textured ⇒ `Brown3`** (the app default).
- **Housing ports / dome ports on rectilinear glass**: `Brown4WithTangential2` was the
  planned post-merge refinement (mid-vs-edge distortion plus lens/port axis offset), but
  §5.4 makes it a *global* choice that would then also apply to the fisheye. Never run here.
  [OPEN]
- **K+ variants only if residuals stay high after a Brown refinement** — freeing skew and
  aspect on weak-texture underwater data risks overfitting.
  [VERIFIED-as-decision: settings-evaluation §3]
- **Fisheye undistortion export**: Epic recommends **Image cut-out = 0.8** for fish-eye
  lenses. [OFFICIAL: tools/undistort]

---

## 6. Rotation conventions

> This is the section most likely to silently flip a whole survey. Read the confidence tags.

### 6.1 What is certain

- `xcr:Rotation` is **nine whitespace-separated floats**, and the Help presents it as a
  3×3 in row order. [OFFICIAL: tools/xmpalign — the attribute and its width]
- The report/template variables expose the same 3×3 as `R00 R01 R02 R10 R11 R12 R20 R21
  R22`, and the shipped OpenCV export header states outright that "R = [Rij] provided in
  **row major** ordering". [OFFICIAL: appbasics/reports_fav_cameras; shipped schema
  `calibration.xml`, format `{B5331837-…}`]
- The Help's sample value `"-1 0 0 0 0 -1 0 -1 0"` read row-major is
  `[[-1,0,0],[0,0,-1],[0,-1,0]]`, which has **det = +1** and **trace = −1** — a proper
  rotation of 180° about the axis `(0, 1, −1)/√2`. It is not a reflection, and it is not
  the identity, so the sample is genuinely a rotation matrix in the row-major reading.
  [VERIFIED-by-arithmetic on the OFFICIAL sample]

### 6.2 Which frames `R` maps between — [INFERRED], strongly evidenced

> **[2026-08-23] Do not try to settle this on nadir imagery.** An attempt to confirm the
> world→camera reading empirically — comparing RealityScan's own solved rotations against an
> external solve carried through a similarity fitted on camera centres — was **inconclusive
> on three separate arms** (world→camera median 10.0° / 22.8° / 28.7°; camera→world 10.4° /
> 22.4° / 39.6°; never cleanly separated). The reason is structural: a downward-looking
> camera has a rotation matrix close to a 180° rotation, and a 180° rotation **is its own
> inverse** (R = Rᵀ), so the two hypotheses are near-indistinguishable by construction.
> Settling §6.2 empirically needs a dataset with substantial off-nadir variety.
>
> Note also that supplying poses and checking a rig baseline does **not** test this: the
> baseline depends only on camera positions, so a transposed convention passes unnoticed.
> [VERIFIED-as-inconclusive: onr2 arms L / E / C, 2026-08-23]

**Claim: `R00..R22` (and `tX,tY,tZ`) form the world→camera pose, i.e. `X_cam = R·X_world +
t`, with the camera frame x-right / y-down / z-forward (OpenCV-style) and the world frame
Z-up right-handed.** Nothing in the Help states this. Three independent shipped export
templates in `C:\Program Files\Epic Games\RealityScan_2.2\calibration.xml` imply it:

1. **OpenCV export `{B5331837-609D-4B12-A931-2863653d19F7}`** emits `$(R00)…$(R22)` and
   `$(tX),$(tY),$(tZ)` **unmodified** under the header "…are the rotation matrix R and the
   translation vector t of the pose (R,t) of the camera". OpenCV's `(R,t)` pose is
   world→camera by definition, and no sign or transpose is applied.
2. **Radiance Fields export `{314B5F22-…}`** builds a 4×4 from
   `R00,-R02,R01,tx / R10,-R12,R11,ty / R20,-R22,R21,tz / 0,0,0,1` and then writes
   **`$Mat44Inv(...)`** into the JSON field `"transform_matrix"`. In the instant-NGP/NeRF
   convention `transform_matrix` is **camera-to-world**; taking the *inverse* of the RS
   matrix to obtain camera-to-world means the RS matrix is **world-to-camera**.
3. **Bundler v0.3 export `{ECC4131A-…}`** writes
   `R00,-R02,R01 / -R10,R12,-R11 / -R20,R22,-R21` and `tx,-ty,-tz`, and its point block
   writes `$(x), $(-z), $(y)`. Decomposed, that is `R' = diag(1,−1,−1) · R · M` with
   `M = [[1,0,0],[0,0,1],[0,−1,0]]`. `diag(1,−1,−1)` is the standard OpenCV↔OpenGL camera
   flip (y-down/z-forward → y-up/z-back). `M` is exactly `Qᵀ = Q⁻¹` for the point
   permutation `Q: (x,y,z) → (x,−z,y)` written in the same file — and `R' = R·Q⁻¹` is
   precisely the consistency relation a world-axis change `X' = Q·X` forces on a
   world→camera rotation. `Q` is the standard **Z-up world → Y-up world** change. Both
   flips are exactly what is needed *if* RS is Z-up world with an OpenCV camera frame; if
   RS's `R` were camera→world the same file would need `Q` on the *left*, not `Q⁻¹` on the
   right.

Corroborating facts:

- `transformdb.xml` gives OBJ and Alembic exports `rotation="-90 -90 0"` while FBX gets
  none — i.e. RS's native up-axis needs rotating to reach OBJ's Y-up convention.
  [shipped schema: `transformdb.xml`]
- `transformdb.xml` scales are `100` for Maya/Unreal (m→cm) and `39.370039` for 3ds Max
  (m→inch), so **RealityScan's native linear unit is the metre**.
  [shipped schema: `transformdb.xml`] [VERIFIED-by-schema]
- The Help's own render example places a camera at `0 0 150` to get "a render **from
  above** of a model at 0,0,0 in local Euclidean space", and the LookAt example passes
  `upX upY upZ = 0 0 1` "defining the vertical axis going up the Z axis" — **+Z is up**.
  [OFFICIAL: appbasics/allcommands, `renderMeshFromCustomPositionYPR` /
  `renderMeshFromCustomPositionLookAt` examples]

**What would settle it (cheap, headless, needs one aligned component and nothing else):**
export the *same* component twice.

- `-exportXMP` gives `xcr:Rotation` and `<xcr:Position>`. `<xcr:Position>` is the camera
  **centre** `C` (§6.5).
- `-exportRegistration <file>.csv <params>.xml` in the **OpenCV-compliant
  Internal/External Camera Parameters** format `{B5331837-…}` gives `R00..R22` and
  `tX,tY,tZ` — the pose `(R,t)`, **not** a camera centre. Its header line names its own
  columns: `#name,tx,ty,tz,R00,…,R22,f_pix,px_pix,py_pix,k1,k2,t2,t1,k3,k4`.
  [shipped schema: `calibration.xml`]

Both are in the same frame — the OpenCV format carries `supportsGeoref="0"`, so it exports
in the component/local frame, which is where `xcr:Position` already lives (§8.1 #6). Then
for one camera check numerically whether `t == −R·C` (world→camera) or `t == C`
(camera→world), and whether `xcr:Rotation` equals `R` or `Rᵀ`. Two exports and nine
multiplications. Do **not** pair the OpenCV export with the `{720A2EC9-…}` "Name, X/Lon,
Y/Lat, Z/Alt" CSV for `C`: that one is `requiresGeoref="1"` and would put the two sides in
different frames. [OPEN — see Q2.]

### 6.3 Yaw / pitch / roll — the Help contradicts itself

Seven sources, three answers:

| Source | Yaw axis | Pitch axis | Roll axis | Tag |
|---|---|---|---|---|
| `tools/flightlogimport` — "rotation order around the X (**Roll**), Y (**Pitch**), and Z (**Yaw**) axes in the North-East-Down (NED) coordinate system" | **Z** | **Y** | **X** | [OFFICIAL] |
| `tools/defineimportformat` — "Yaw Prior yaw rotation (around **Y**-axis)… Pitch … (around **X**-axis)… Roll … (around **Z**-axis)" | **Y** | **X** | **Z** | [OFFICIAL] |
| `appbasics/selectedinputs` — "Yaw/Heading, Pitch/Elevation, Roll/Bank Rotation angles of a camera around **Y, X, Z** axis, respectively" | **Y** | **X** | **Z** | [OFFICIAL] |
| `appbasics/reports_fav_cameras` — yaw = "the vertical axis", pitch = "the lateral axis", roll = "the longitudinal axis" | axis-agnostic aircraft wording | | | [OFFICIAL] |
| shipped `calibration.xml`, YPR CSV export `{121D2018-…}` carries `EulerFormat="zyx"`; the OPK export `{B3EE1544-…}` carries `EulerFormat="xyz"`; the Maya export carries `EulerFormat="zxy"` | **Z** | **Y** | **X** | [shipped schema] |
| Epic staff **OndrejTrhan**, 2023-10-23, Epic Developer Community KB "Registration export and camera orientations": intrinsic **Roll → Pitch → Yaw**; Yaw about Z, Pitch about Y, Roll about X | **Z** | **Y** | **X** | [staff, inside the 4-year trust window; quoted in FINDINGS 2026-07-26] |
| `RealityScan.exe` 2.2.0.119430 UI resource, tooltip on **Euler angles order (YPR)**: "Define the order (applied right to left) of rotations about the X (**roll**), Y (**pitch**), and Z (**yaw**) in the NED coordinate system" — and the combo's own label for the default is `ZYX (photogrammetric YPR convention)` | **Z** | **Y** | **X** | [UNDOCUMENTED: binary string extraction, this session] |

**[CONTRADICTED] — the offline Help states both mappings on different pages.** Weight of
evidence favours **Yaw→Z, Pitch→Y, Roll→X in the world (NED) frame**: it is the aviation/NED
standard; it matches the shipped `EulerFormat="zyx"` on the YPR export template; the
companion OPK export carries `EulerFormat="xyz"` and omega/phi/kappa are documented as
x/y/z respectively [OFFICIAL: appbasics/reports_fav_cameras], so `zyx` for yaw/pitch/roll
is the consistent reading of the same attribute; it matches the staff post; and the
binary's tooltip states it in the same words as `tools/flightlogimport`. **Four independent
sources agree** (Help import page, shipped export templates, staff, binary); one is
axis-agnostic; the two that disagree are single sentences in field-reference lists with no
worked example. Treat `appbasics/selectedinputs` and `tools/defineimportformat` as
documentation defects.

**The `x/y/z` in `inpRx/inpRy/inpRz` are IMAGE axes, not world axes.** `-editInputSelection`
uses:

| Key | Field | Range |
|---|---|---|
| `inpRx` | **Yaw / Heading** | −180 … 180 |
| `inpRy` | **Pitch / Elevation** | −90 … 90 |
| `inpRz` | **Roll / Bank** | −180 … 180 |

[OFFICIAL: tutorials/editselectioncommand]

This looks arbitrary until you read the parallel naming in the trajectory-import dialog,
where the same Yaw/Pitch/Roll↔x/y/z pairing carries an explicit frame:
**"Yaw angle offset — Relative rotation round image X axis"**, **"Pitch angle offset —
… image Y axis"**, **"Roll angle offset — … image Z axis"** (keys `ifOfsRY`/`ifOfsRP`/
`ifOfsRR`, §9.3). [UNDOCUMENTED: binary UI strings, this session]

So the product uses **two frames for the same three angle names**: world/NED
(yaw→Z, pitch→Y, roll→X) for imported trajectory angles and the export templates, and
image/camera (yaw→x, pitch→y, roll→z) for the per-input and per-camera *offset* fields.
They are not contradictory once the frame is attached — but a prior generator that reads
`inpRx` as "rotation about world X" gets roll where it wanted yaw.
[INFERRED that `inpRx/Ry/Rz` inherit the image-frame naming from the same internal
convention as `ifOfsR*`; the Help never says so. Settled by `-editInputSelection
"inpRx=90"` on one image followed by `-exportXMP` and reading `xcr:Rotation`.]
Note also that `appbasics/selectedinputs`'s "around Y, X, Z respectively" matches
**neither** frame, which is why it is treated as a defect above.

### 6.4 The zero pose — [OFFICIAL] and now corroborated

Staff statement: *"Yaw = 0, image is oriented to Y (upper side of image is oriented that
way), Pitch = 0, image is looking down, Roll = 0, image is parallel with X axis."*
[staff: OndrejTrhan, 2023-10-23]

**Independently corroborated by the shipped Help**: the documented example
`-renderMeshFromCustomPositionYPR "D:/Project/render.png" 1280 720 100 0 0 150 0 0 0`
is described as "a render **from above** of a model at 0,0,0 in local Euclidean space" —
camera at `(0,0,150)` with `yaw=pitch=roll=0`, looking **down**.
[OFFICIAL: appbasics/allcommands] So **pitch 0 = nadir** on a scale where 90 = horizontal.

This is exactly what this repo's converter assumes:

```python
# modules/georeference/georeference_images.py
camera_pitch_from_horiz = pitch_vehicle - camera_offset
rc_pitch = 90.0 + camera_pitch_from_horiz      # 0 = nadir, 90 = horizontal
```

and the written logs confirm it: **Port median 88.11°** (n = 2,267, range 86.6–89.4 —
essentially horizontal) and **Cinema median 43.11°** (n = 2,273, range 41.5–44.3 — ~45°
down), both matching the physical rig. [VERIFIED: FINDINGS 2026-07-26]

A same-session claim that "we write pitch from horizontal, so Port is 90° wrong" was
**SUPERSEDED within minutes** — it was asserted from a docstring and the writer without
reading the function between them, and one grep of the actual rows refuted it. Retained
because deleting refuted findings guarantees rediscovering them.
[SUPERSEDED: FINDINGS 2026-07-26]

**Degeneracy warning:** Port's pitch sits at ~88°, within 2° of the 90° singularity where
roll and yaw collapse in this parameterisation. Small pitch noise then produces large
attitude swings — a plausible contributor to a component holding mostly Port frames.
[INFERRED: FINDINGS 2026-07-26; not isolated by a cell]

### 6.5 Worked conversions

Given the favoured convention (Yaw about Z, Pitch about Y, Roll about X, composed intrinsic
Roll→Pitch→Yaw, i.e. `EulerFormat="zyx"` evaluated **right to left** per
`tools/flightlogimport`), the matrix is:

```
Rz(ψ) = [[ cosψ, -sinψ, 0],[ sinψ,  cosψ, 0],[    0,     0, 1]]
Ry(θ) = [[ cosθ,     0, sinθ],[    0, 1,    0],[-sinθ,  0, cosθ]]
Rx(φ) = [[    1,     0,    0],[    0, cosφ, -sinφ],[  0, sinφ,  cosφ]]

R = Rz(yaw) · Ry(pitch) · Rx(roll)          # "zyx", evaluated right to left
```

Python, exactly as you would write it in a prior generator:

```python
import numpy as np

def ypr_to_matrix(yaw_deg: float, pitch_deg: float, roll_deg: float) -> np.ndarray:
    """RealityScan 'zyx' YPR -> 3x3, row-major. Convention per section 6.3;
    VERIFY with the render probe (section 6.6) before trusting on real data."""
    y, p, r = np.radians([yaw_deg, pitch_deg, roll_deg])
    Rz = np.array([[np.cos(y), -np.sin(y), 0], [np.sin(y), np.cos(y), 0], [0, 0, 1]])
    Ry = np.array([[np.cos(p), 0, np.sin(p)], [0, 1, 0], [-np.sin(p), 0, np.cos(p)]])
    Rx = np.array([[1, 0, 0], [0, np.cos(r), -np.sin(r)], [0, np.sin(r), np.cos(r)]])
    return Rz @ Ry @ Rx

def matrix_to_xcr_rotation(R: np.ndarray) -> str:
    """Row-major, space separated, exactly as xcr:Rotation wants it."""
    return ' '.join(f'{v:.15g}' for v in R.reshape(9))
```

Quaternion `q = (w, x, y, z)`, unit-normalised, to the same 3×3:

```python
def quat_to_matrix(w, x, y, z):
    n = (w*w + x*x + y*y + z*z) ** 0.5
    w, x, y, z = w/n, x/n, y/n, z/n
    return np.array([
        [1-2*(y*y+z*z),   2*(x*y-z*w),   2*(x*z+y*w)],
        [  2*(x*y+z*w), 1-2*(x*x+z*z),   2*(y*z-x*w)],
        [  2*(x*z-y*w),   2*(y*z+x*w), 1-2*(x*x+y*y)],
    ])
```

Camera-to-world ⇄ world-to-camera (the single most common sign error):

```
R_wc  = world -> camera rotation      X_cam = R_wc · X_world + t
R_cw  = camera -> world rotation      R_cw  = R_wcᵀ
C     = camera centre in world        C     = -R_wcᵀ · t     <=>   t = -R_wc · C
```

`<xcr:Position>` is the camera **centre** `C`, not `t` — it is the value that lands in
`x/y/z` ("the x camera coordinate in the output coordinate system")
[OFFICIAL: appbasics/reports_fav_cameras], whereas `tX/tY/tZ` is "the x coordinate in the
camera coordinate system w.r.t. output coordinate system", i.e. the pose translation.
The two are distinct template variables and must not be confused.
[OFFICIAL for the variable definitions; [INFERRED] that `<xcr:Position>` is `C` rather than
`t` — settled by the same numeric probe as §6.2.]

### 6.6 The empirical checks — one that was run, two that are cheap

**Run (and it failed).** `poses2flightlog.py` fits the local→UTM rigid transform between
XMP camera positions and flight-log priors. Orientations are deliberately **not** rewritten:
*"Six rotation-convention candidates were tested against the flight-log yaw/pitch/roll; none
matched (best mean error ~77°)."* Writing orientations in an unverified convention would
poison future priors, which carry weight 10.
[VERIFIED: docs/history/code-review-2026-07 Part 3, "Deliberate non-changes"]
That result is the strongest single reason to treat the export-side rotation convention as
**unestablished for this pipeline**, not merely undocumented.

**Cheapest probe — the render pair (never run; it needs a *model* in the scene but no
alignment, because `-importModel <file> [params.xml]` can supply an asymmetric test mesh
directly).** [OFFICIAL: appbasics/allcommands for `-importModel`]
`-renderMeshFromCustomPositionLookAt` takes an explicit look-at point and up vector;
`-renderMeshFromCustomPositionYPR` takes yaw/pitch/roll. Both signatures are
`fileName width height focalLength x y z …`, with LookAt taking `atX atY atZ` plus an
optional `upX upY upZ`. Render the *same* model from the *same* position both ways and
compare the images:

```bat
:: 0. a mesh to look at - any asymmetric model, no alignment required
RealityScan.exe -delegateTo RS1 -importModel "D:\probe\marker.obj"
:: 1. ground truth: camera at (0,-100,0) looking at the origin, Z up
RealityScan.exe -delegateTo RS1 -renderMeshFromCustomPositionLookAt "D:\probe\lookat.png" 1280 720 50 0 -100 0 0 0 0 0 0 1
:: 2. candidates: same position, yaw/pitch/roll that SHOULD reproduce it
RealityScan.exe -delegateTo RS1 -renderMeshFromCustomPositionYPR    "D:\probe\ypr_a.png"  1280 720 50 0 -100 0   0  90 0
RealityScan.exe -delegateTo RS1 -renderMeshFromCustomPositionYPR    "D:\probe\ypr_b.png"  1280 720 50 0 -100 0  90  90 0
```

Whichever YPR triple reproduces the LookAt image pins yaw's zero direction, pitch's sign,
and the axis mapping in one pass. Sweeping yaw in 90° steps then fixes the yaw origin
(staff says yaw 0 points the image's top toward +Y). The 90° pitch in the candidates comes
from §6.4: pitch 0 is nadir, so a horizontal look needs pitch 90.
[OPEN — see Q2; this probe is not in the repo's queue and should be.]

**The A/B against a known-good aligned scene (the definitive one for imported priors).**
Take a component whose solve is trusted (metric scale in band, low fragmentation):

1. `-exportXMP` its poses; keep them as ground truth.
2. Regenerate sidecars from *your* producer using the candidate convention, at
   `xcr:PosePrior` = locked / `inpPose=3`.
3. `-newScene`, `-add` the same imagelist, `-align`.
4. Compare solved camera positions and axes against step 1. A convention error shows up as
   a systematic axis swap or sign flip in the residuals, not as noise.

If the priors are *locked*, a wrong convention makes the align fail or produce a grossly
rotated component — a loud failure, which is what you want. If they are merely
*Position and orientation*, a wrong convention degrades quietly, which is exactly the
failure mode that produced the bow tilt (§10.6).

**Noise floor for step 4:** *align output is never pose-stable.* A free re-align of an
already-solved 118-camera smoke scene moved **all 118** cameras and can drop 1–2 marginal
ones. So the comparison must be against a *re-aligned* control from the same run, never
against the original solve, and the discriminator must be a systematic axis swap or sign
flip — not a residual magnitude. [VERIFIED: FINDINGS "U18 bonus", 2026-07-23]

---

## 7. Prior strength, accuracy, hardness, and composition

### 7.1 Accuracy vs hardness — two different knobs

| Concept | Key | Default | Meaning |
|---|---|---|---|
| Position X/Y/Z accuracy | `sfmCameraPriorAccuracyX` / `…Y` / `…Z` | `10.0` / `10.0` / `20.0` | "the range in which the calculated positions are going to be considered as **equal to** the prior values" |
| Position prior **hardness** | `sfmCameraPriorWeight` | `1.0` | "the closeness of the calculated positions to the prior positions. The greater the value, the closer… This may change the visual connections between cameras" |
| Yaw / Pitch / Roll accuracy | `sfmCameraPriorAccuracyYaw` / `…Pitch` / `…Roll` | `10.0` each | same idea, in degrees |
| Orientation prior **hardness** | `sfmCameraPriorWeightOrientation` | `1.0` | same idea, for attitude |
| Use camera priors for georeferencing | `sfmEnableCameraPrior` | `true` | pose priors participate **inside the bundle adjustment** and georeference the resulting components |

[OFFICIAL: tutorials/setkeyvaluetable for keys/types/defaults; appbasics/alignsettings for
the prose] Full `sfm*` inventory in `03-settings-keys.md`; what the solver does with them in
`07-alignment.md`.

Accuracy is a **tolerance**; hardness is a **weight**. They multiply in effect: a tight
accuracy with high hardness is a hard constraint; a loose accuracy with high hardness is a
firm pull toward a wide envelope.

Per-image overrides exist and beat the globals when enabled:
`inpPriorAccuracyInh` = `0` (use global camera prior settings) or `1` (edit custom values),
then `inpuTx/inpuTy/inpuTz` and `inpuRx/inpuRy/inpuRz`.
[OFFICIAL: tutorials/editselectioncommand] The flight-log import has the same switch:
"Accuracy settings source — *from file and edit missing definitions* … *Global camera priors
setting*". [OFFICIAL: tools/flightlogimport]

### 7.2 [VERIFIED] Two of those accuracy keys have never actually shipped in this repo

The GUI settings exporter writes the camera-prior accuracies as opaque ids —
`s235l` / `s236l` / `s237l` (and the control-point ones as `s251l`…`s254l`) — and every
workflow filters the params XML to keys beginning `sfm` or `lis`:

```bat
echo %%A| %SystemRoot%\System32\findstr.exe /b /c:"sfm" /c:"lis" >nul
if not errorlevel 1 %RealityScan% -delegateTo %RS_INSTANCE% -set "%%A=%%B"
```

So the intended non-default accuracies (5.0 / 5.0 / 0.5 m) were **never applied** — every
production run used RealityScan's defaults 10.0 / 10.0 / 20.0. This matters because
hardness was tuned on the assumption that the accuracies bounded the trust envelope.
Fix: send the documented `sfm*` names explicitly.
[VERIFIED: code reading of `AlignZone.bat` + `AlignmentParams.xml`, SURVEY_settings §11.3]

**Reading the applied accuracy back.** The report variables `priorErrorX`, `priorErrorY`,
`priorErrorZ` and `priorError3D` are defined as "a prior position X/Y/Z accuracy" per
camera. [OFFICIAL: appbasics/reports_fav_cameras] A one-line `$ExportCameras` template
therefore reports, per camera, the accuracy RealityScan *actually used* — the direct,
CLI-observable test of the claim above that the intended 5.0/5.0/0.5 never shipped (expect
10/10/20 in the affected runs). It is also the probe for Q24 (§9.3), where the same
question arises for the flight log's per-image accuracy columns. Never run. [OPEN.]

```
$ExportCameras($(imageName)$(imageExt),$(priorErrorX),$(priorErrorY),$(priorErrorZ),$(priorError3D)
)
```

### 7.2a After the solve: relative position uncertainty

The rig-quality readback after alignment is **Relative position uncertainty** — "the
uncertainty in the position of a camera relative to other cameras registered in the
component", shown per input in the Selected Input panel.
[OFFICIAL: appbasics/selectedinputs, appbasics/uncertainty] Two properties matter for
headless work:

- It exists **only for registered images**, and its units come from the **Project
  coordinate system**. [OFFICIAL: appbasics/uncertainty]
- It is reachable from a report template, so it is CLI-observable:
  `$ExportRelativeCameraPositionUncertainty(cameraImageIndex, …)` exposes
  `posUncertCovXX`, `posUncertCovXY`, `posUncertCovXZ`, `posUncertCovYY`,
  `posUncertCovYZ`, `posUncertCovZZ`, and `$CovToEllipse2D(Qxx,Qxy,Qyy, …)` turns a
  covariance triple into `ellipseRadiusMax`, `ellipseRadiusMin`, `ellipseRot`.
  [OFFICIAL: appbasics/reports_fav_cameras]

For a fixed rig this is the natural acceptance metric — a correctly declared rig should
show *small relative* uncertainty between rig-mates even when absolute uncertainty is
large. **Never exercised here**; the repo's oracles are registration counts and metric
scale, neither of which sees this. [OPEN.]

### 7.3 What overrides what

No Help page states a precedence order. What is established:

| Source | Scope | Established behaviour |
|---|---|---|
| **EXIF GPS** | per image, at import | used only when `sfmEnableCameraPrior=true`; suppressible per camera model via `GPSMode="ignore"` in `sensorsdb.xml` [OFFICIAL: tutorials/georeferencing, appbasics/cameradb] |
| **`sensorsdb.xml`** | per camera **model**, at import | fills calibration priors when EXIF is incomplete; soft by default, hard with `quality="exact"` [OFFICIAL: appbasics/cameradb] |
| **XMP sidecar** | per image, at import | "All information from the XMP file will automatically be assigned to the corresponding image" — i.e. XMP **replaces** EXIF-derived values [OFFICIAL: tools/xmpalign] |
| **Flight log (`-importFlightLog`)** | per image, on demand | matched by **basename**, finds images in subfolders; writes position, optional YPR, optional per-image accuracies, and optionally calibration columns (§9.2) [VERIFIED: NA167 #5; OFFICIAL: tools/defineimportformat] |
| **`-editInputSelection`** | current selection, on demand | last writer wins; the master per-image control [OFFICIAL + VERIFIED] |
| **`sfmDistortionModel`** | **global**, overrides every per-image model | §5.4 [VERIFIED: FINDINGS 2026-07-26] |
| **GCPs / control points** | per measured point | independent constraint family; can define origin (1 point), scale (2), full frame (3+) [OFFICIAL: tutorials/georeferencing, tutorials/scaling] — **never driven through this CLI** [OPEN] |

Ordering rule that is safe to rely on: **imports are applied in the order you issue them**,
and `-editInputSelection` after an import overrides that import for the selection.
[INFERRED from FIFO delegation semantics; not isolated by a cell.]

Two composition facts that *are* established:

- `sfmEnableCameraPrior` (per-camera, inside the bundle adjustment) and
  `sfmMergeGeoreferencedComponents` (per-component, post-solve) are **different scopes** and
  compose: (a) makes every component georeferenced, (b) then allows georeferenced
  components to fuse. **(b) without (a) is inert.**
  [INFERRED from Help prose + design reasoning; settings-evaluation §5. Not isolated by a cell.]
- A **merged** component is **not** georeferenced unless the merge scene itself holds
  constraints — imported components' own georeferencing does not carry into the fused one.
  The fix is a union flight log + CRS in the merge scene, then `-update`.
  [VERIFIED: FINDINGS 2026-07-23]

### 7.4 `-update` is a similarity fit, and it is the step that can move geometry

"Update all components and models by a rigid transformation to fit the actual constraints
and control points." [OFFICIAL: appbasics/allcommands] Measured here: `-update` is a
similarity/rigid fit applied **after** reconstruction — it can **rotate or rescale** a
component but cannot stiffen or repair its geometry. [VERIFIED: FINDINGS 2026-07-26]

That makes `-update` the *only* consumer of orientation priors in an assembly stage that
imports finished components — and therefore the prime suspect whenever a component is
correctly solved but wrongly oriented in the deliverable (§10.6).

### 7.5 Measured effects of priors — the numbers that matter

**Prior *content* can hurt.** A/B on NA167 zone_13 with priors absent (via the
`image.jpg.xmp` naming bug) versus promoted: **96.3 % → 89.6 %** registration on the Zeuss
camera. The old writer grouped cammid + camupper + camlower together as "12 mm fisheye"
when camlower is a rectilinear 17 mm — which plausibly explains the whole result. XMP prior
generation became opt-in (`batch_xmp_priors`, default off) as a consequence.
[VERIFIED: NA167 #4 / B7, 2026-07-22]
**Scope note:** the corrected per-camera values reverse the calculus (§4.4 shows the
corrected groups working). **Validate prior content per rig before trusting either
direction.** [SUPERSEDED-in-scope]

**Correct calibration priors help structurally.** Calibration XMP sidecars at align time cut
zone_1 fragmentation from **9 components to 3** at equal-or-better registration (4,405/4,540
= 97.0 % fresh vs 4,392 = 96.7 % production), same imagery, same box.
[VERIFIED: FINDINGS 2026-07-24; docs/history/FRESH_RUN_2026-07-24.md]

**Over-tight *position* priors fragment solves and corrupt scale** — the decisive 2×2 on a
665-image known-good component:

| Cell | Registered | Components | Scale of maximal |
|---|---:|---:|---:|
| brown3_loose (10/10/1 m) | 665/665 | **1** | 1.049 |
| brown3_tight (1/1/0.1 m) | 662/665 | 2 | 0.886 |
| division_loose | 656/665 | **1** | **0.989** |
| division_tight | 659/665 | 3 | 0.826 |

Registration barely moved (656–665 in every cell) — which is precisely why a
camera-counting oracle never caught it. **Lesson: the flight-log accuracy columns want
END-TO-END per-image position uncertainty (timestamp matching + nav interpolation + lever
arm + dive drift), NOT the instantaneous sensor spec.** Reverted to 10/10/1.
[VERIFIED: PRIORS_DISTORTION_TEST_PLAN "Bow 2×2", 2026-07-25]
An intermediate ladder (3/3/0.5, 5/5/1) is queued and never run — loose is *proven*, not
proven *optimal*. [OPEN]

**Over-tight *orientation* accuracy fragments too; honest accuracy gains.** On Z3 (124
images), all three cells on the same 1/1/0.1 position accuracy so that YPR accuracy is the
only variable:

| Cell | Orientation prior | Registered | Components |
|---|---|---:|---|
| PD-0a | none (position-only) | 101/124 | **1** |
| PD-0 | YPR at 3–5° | 101/124 | **4** `[62,18,11,10]` |
| PD-0b | YPR at **15°** | **109/124** | 2 `[99,10]` |

Baseline (no priors, Brown3) was 102/124 in one component. So tight orientation buys
nothing and fragments; honest orientation buys +7. Dose-response, one variable between
PD-0 and PD-0b. [VERIFIED: PRIORS_DISTORTION_TEST_PLAN PD-0 / PD-0a / PD-0b, 2026-07-25]
Note PD-0 is flagged in its own test plan as a **bad cell** (it moved position accuracy and
orientation together relative to the baseline); the clean comparison is PD-0a→PD-0b for
"does orientation help" and PD-0→PD-0b for "does its accuracy matter".

**But removing orientation priors entirely destroyed two zones.** A position-only
re-alignment of all five H2024 zones (one variable: the 7-column format
`{0E9850E2-…}` instead of the 13-column `{B438A617-…}`) gave zone_1 0.989 (5 comps vs 8),
zone_2 1.014, zone_4 0.904 (3 vs 5) — but **zone_3 and zone_5 registered NOTHING AT ALL**:
zero components, empty harvest, "Identity capture finished after 0 component(s)" after 12.7
and 32.4 minutes. **Orientation priors are load-bearing for registration on this data, not
harmful.** [VERIFIED: HANDOFF 2026-07-27; driver `testing/ab_orientation_priors.py`;
results at `F:/na156_h2024/ab_position_only/ab_results.json`]

**CONTAMINATION FLAG on every orientation conclusion.** Imported YPR is read in NED with a
**configurable Euler order evaluated right to left**, a **Camera mount** option applies
whenever YPR is included, and `FlightLogParams.xml` pins **neither** — so every orientation
cell ran through an unverified import path. **Registration counts stand as measurements; the
attribution to "orientation priors" does not.** Affected: PD-0, PD-0b, PD-1b, PD-4,
M-DIV-ORI, and the interim policy "orientation@15° is validated on sparse zones"
(downgraded validated → PROVISIONAL). Not affected: PD-6 (position-only), all scale-oracle
results, and rig-internal geometry. [VERIFIED-as-flag: FINDINGS 2026-07-26]

**Two updates to that flag from §9.3, one relieving and one aggravating.**

- *Relieving*: the Euler-order default is `EULER_ROT_ZYX`, i.e. the order the producer
  assumes, and all four Camera-mount options are nadir-facing azimuth variants — so the
  unpinned settings could not have introduced a *pitch* error, and the ZYX composition was
  almost certainly right all along. [UNDOCUMENTED-VERIFIED for the tokens; [INFERRED] that
  an unpinned import takes the compiled default.]
- *Aggravating*: `ifUsePosAcc` and `ifUseOriAcc` — the two entries that were believed to
  turn accuracy-column consumption on — **do not exist in the product**. So the accuracy at
  which every one of these cells ran is unestablished, and the "3/5/3" and "15°" labels on
  them are labels on the *file*, not necessarily on the solve. This does not change any
  registration count; it changes what the counts are evidence *about*.
  [CONTRADICTED, §9.3] [OPEN — Q24.]

**Decision in force (owner):** orientation priors **ON** at alignment, conservative **15°**
YPR accuracy, with the metric-scale oracle as the named mitigation. The concern (unpinned
Euler order + camera mount makes tight orientation a live scale risk) was raised and
overruled, and is recorded. [VERIFIED-as-decision: FINDINGS 2026-07-26]

---

## 8. Coordinate frames in play

### 8.1 The frames, named exactly as RealityScan names them

| # | Frame | RealityScan's own name / variables | Units | Notes |
|---|---|---|---|---|
| 1 | **Image / sensor** | control-point `X`,`Y` = "pixels from the **upper left** corner of the image" | px | GCP measurement import frame [OFFICIAL: tools/defineimportformat] |
| 2 | **Normalised image** | `px`, `py` = "relative offset from the center of an image"; panel calls them mm **w.r.t. 35 mm film format** | relative / mm-35eq | `xcr:PrincipalPointU/V` live here [OFFICIAL: appbasics/reports_fav_cameras, appbasics/selectedinputs] |
| 3 | **Camera** | `tX`,`tY`,`tZ` = "the x coordinate in the camera coordinate system w.r.t. output coordinate system"; `R00..R22` | m | x-right / y-down / z-forward [INFERRED §6.2] |
| 4 | **Component-local** | `aX`,`aY`,`aZ`, `aTX..aTZ`, `aR00..aR22` = "in the **components** coordinate system" | m | one frame per component; this is why two components can each look fine and disagree |
| 5 | **Local Euclidean** | `euclidX/Y/Z`, `euclidTX..TZ`, `euclidR00..R22`; `local.xml` defines `Euclidean` (`+proj=geocent +ellps=WGS84 +no_defs`) and `Laboratory` (same, `+units=mm`) | m (or mm) | the frame the render commands call "local Euclidean space" |
| 6 | **Grid-anchored local** | the frame of `-renderMeshFromCustomGridPositionYPR` / `…GridPositionLookAt` | m | **distinct** from #5 — RealityScan ships a separate command pair for it |
| 7 | **Project CRS** | *WORKFLOW / Settings / Coordinate Systems / Project coordinate system* | CRS units | "the global project coordinate system used as a reference for measuring, displaying coordinates or accuracy reports" |
| 8 | **Output CRS** | *…/ Output coordinate system*, or per-export "Coordinate system" | CRS units | `x`,`y`,`z` report variables are in **this** frame |
| 9 | **Input CRS** | `xInpCS`,`yInpCS`,`zInpCS` = "camera coordinate after alignation **in the input coordinate system**" | CRS units | the CRS the priors arrived in |
| 10 | **Geographic** | `lat`, `lon`, `alt` — "in epsg:4326 - GPS (WGS 84)" | deg / m | |

[OFFICIAL: appbasics/reports_fav_cameras for #2–#5 and #8–#10; appbasics/coordinatesystem
for #7–#8; appbasics/allcommands for #6; shipped `local.xml` for #5's definitions]

Facts about the frames established here:

- **`xcr:Position` in exported XMPs is in a GRID-ANCHORED LOCAL frame, not UTM.** Verified
  on zone_9: the values are small and local, the anchor is the grid origin, and the
  lat/long XMP attributes are **garbage** (e.g. `179.98N`). Fit local→UTM with
  `poses2flightlog.py`. [VERIFIED: NA167 B10-adjacent, 2026-07-23; docs/history/code-review-2026-07]
  [OPEN: cell U13 — re-verify on an **original** georeferenced zone scene; if positions are
  UTM there, manifests could carry true per-camera positions and better bboxes. Open since
  2026-07-23.]
- **RealityScan's native linear unit is the metre** — from `transformdb.xml`'s `scale="100"`
  for Maya/Unreal and `39.370039` for 3ds Max. [VERIFIED-by-schema]
- **Native up-axis is +Z** — from the render examples and from `transformdb.xml` applying
  `rotation="-90 -90 0"` for OBJ/Alembic but not FBX. [OFFICIAL + shipped schema]
- **"The chosen coordinate system determines the project's units of measurement."**
  RealityScan ships the EPSG database plus `local.xml`; more than one CRS can be in play at
  once and "even every ground control point can be measured with respect to a different
  coordinate system", but conversions "may bring small inaccuracies", so Epic recommends
  keeping control points in the project CRS.
  [OFFICIAL: appbasics/coordinatesystem]

### 8.2 Which commands operate in which frame

| Command | Frame it reads/writes |
|---|---|
| `-importFlightLog <log> <params.xml>` | the CRS named by `CoordinateSystemFlightLog` in the params (**input CRS**, #9) |
| `-importGroundControlPoints`, `-importControlPointsMeasurements` | GCP: a named CRS; measurements: **image pixels** (#1) |
| `-editInputSelection "inpTx=…"` etc. | the **Absolute coordinates** CRS of the selection; lat/lon accepted as DMS (`N54,49,31.25`) or prefixed decimal degrees (`N54.825347`) [OFFICIAL: tutorials/editselectioncommand]. The CRS itself is carried by four **[UNDOCUMENTED]** keys recovered from the binary: `inpPosePriorAbsoluteCs`, `inpPosePriorAbsoluteCsInput`, `inpPosePriorAbsoluteCsType`, `inpPosePriorAbsoluteCsWkt` (plus `inpPosePriorAbsoluteCsWktCheckProj`, `inpPosePriorAccuracyMode`, `inpPosePriorRelativeValid`). Value grammar untested; the `…Wkt` name implies WKT and `…Type` the `epsg:NNNNN - <name>` display form used in `FlightLogParams.xml` [INFERRED] |
| `-exportXMP` / `-exportXMPForSelectedComponent` | **grid-anchored local** (#6) for `xcr:Position` [VERIFIED] |
| `-exportRegistration <file> <params.xml>` | the export's **Coordinate system** setting (#8), plus scene transformation |
| `-update` | fits components to the scene's constraints — moves geometry **between** #4 and #7/#8 |
| `-setCamerasGravityDirection [componentID]` | rotates the **sparse cloud** of a component so −z follows `xcr:Gravity`; does **not** touch the mesh |
| `-renderMeshFromCustomPositionYPR/LookAt` | **local Euclidean** (#5) |
| `-renderMeshFromCustomGridPositionYPR/LookAt` | **grid** (#6) |
| `-setGroundPlaneFromReconstructionRegion`, `-resetGround` | the ground-plane/grid definition itself |

[OFFICIAL: appbasics/allcommands for every row except the two [VERIFIED] notes]

### 8.3 The local→UTM fit that the pipeline actually uses

Because `xcr:Position` is local, refining a flight log from solved poses needs an explicit
fit. `poses2flightlog.py` does a Umeyama least-squares fit with **scale locked at 1**:

```python
def umeyama_rigid(src, dst, with_scale=False):
    mu_s, mu_d = src.mean(0), dst.mean(0)
    src_c, dst_c = src - mu_s, dst - mu_d
    cov = dst_c.T @ src_c / len(src)
    U, D, Vt = np.linalg.svd(cov)
    S = np.eye(3)
    if np.linalg.det(U) * np.linalg.det(Vt) < 0:
        S[2, 2] = -1
    R = U @ S @ Vt
    scale = (np.trace(np.diag(D) @ S) / src_c.var(0).sum()) if with_scale else 1.0
    t = mu_d - scale * R @ mu_s
    return scale, R, t
```

Two design facts, both deliberate:

- **Scale is locked at 1.** The alignment already pins scale via the camera priors, and
  fitting scale against noise-dominated nav data collapses it — **0.50 observed on
  zone_9**. `--allow-scale` exists for diagnostics only.
  [VERIFIED: docs/history/code-review-2026-07 Part 3]
- **Orientations are not rewritten** — see §6.6.

Measured output on the zone_9 subset: residual vs prior **4.3 m median, 10 m p95** —
comfortably inside the 10 m accuracy the log claims for itself, i.e. the residual magnitude
is a usable estimate of USBL/DVL navigation error.
[VERIFIED: docs/history/code-review-2026-07]

### 8.4 Georeferencing verification is still a blind spot

**Georeferencing of a merged/assembled scene is verified ONLY in the GUI today.** Hardening
cell U7 (a CLI-observable georeference check) is the longest-standing open item in this
repo. Candidate proxies: `-exportReport` with a components params XML;
`poses2flightlog.py` local→UTM fit residuals (a georeferenced component should fit near
identity); or an exported flight-log round trip.
[OPEN: U7, open since 2026-07-23; the interim proxy is owner/GUI screenshot verification]

---

## 9. Flight-log (trajectory) priors

CRS derivation, zone tagging, the scale oracle and the georeferencing workflow as a whole
live in `06-georeferencing-flightlogs-and-scale.md`; the params-XML mechanics in
`09-xml-parameter-files.md`. This section covers only what decides *geometry*: which
formats carry orientation, what the import does to rotations, and which parameter keys
control it.

### 9.1 Formats shipped in `flightlogs.xml`

Every entry uses `reader="RealityScan.Import.CSVFlightLog"` — a current product string that
must **not** be renamed despite containing "RealityScan.Import".
All are `allowedSeparators=",; &tab;"`, `comment="#"`, `showIgnoreFirstline="true"`,
`qualifiers="&quot;optional"`.

`desc` strings are reproduced exactly as they appear in the shipped file (they are what the
GUI's File-format dropdown shows).

| GUID | descID | `desc` |
|---|---|---|
| `{45881112-C09A-49FD-92E1-5170016D9AB5}` | 8398 | `Image X/Lon Y/Lat Z/Alt` |
| `{C2B41ED1-9567-43C7-8AE6-1452EBEB9F1F}` | 8399 | `Image Y/Lat X/Lon Z/Alt` |
| `{0E9850E2-73E1-4538-B2CF-B18BEF6CECEB}` | 8433 | `Image X/Lon Y/Lat Z/Alt X/LonAccuracy Y/LatAccuracy Z/AltAccuracy` **(the position-only format this repo's A/B used)** |
| `{EFEB661F-A61E-460E-9499-386ACABBD0F6}` | 8434 | `Image Y/Lat X/Lon Z/Alt Y/LatAccuracy X/LonAccuracy Z/AltAccuracy` |
| `{35CD8B84-6573-417D-8FEE-BE8BBEEC00D3}` | 8435 | `Image X/Lon Y/Lat Z/Alt Yaw Pitch Roll` |
| `{80D679DC-DE9C-4866-883D-D2C4EFB24CC6}` | 8438 | `Image Y/Lat X/Lon Z/Alt Yaw Pitch Roll` |
| `{97F08A22-F231-4AB4-A2FD-6FA42BB6D663}` | 8436 | `Image X/Lon Y/Lat Z/Alt X/LonAccuracy Y/LatAccuracy Z/AltAccuracy Yaw Pitch Roll` **(the no-admin fallback)** |
| `{11B6FED7-9EAB-4630-BC34-4412249845C1}` | 8439 | `Image Y/Lat X/Lon Z/Alt Y/LatAccuracy X/LonAccuracy Z/AltAccuracy Yaw Pitch Roll` |
| `{E2805200-B171-41FE-B6A3-54FA0AC475CA}` | 8440 | `Image X/Lon Y/Lat Z/Alt Omega Phi Kappa` |
| `{2C4786DD-02C6-4C59-810F-AE352B283846}` | 8442 | `Image Y/Lat X/Lon Z/Alt Omega Phi Kappa` |
| `{79B6904A-F60B-4CF0-8711-027CF1B472B6}` | 8441 | `Image X/Lon Y/Lat Z/Alt X/LonAccuracy Y/LatAccuracy Z/AltAccuracy Omega Phi Kappa` |
| `{BEE6BAAD-BF18-41D3-8072-45E2228A4925}` | 8443 | `Image Y/Lat X/Lon Z/Alt Y/LatAccuracy X/LonAccuracy Z/AltAccuracy Omega Phi Kappa` |
| `{80679981-0DF8-43DE-ABF7-35CCD8563320}` | 8437 | `Custom` — also the importer's built-in default `gpsLogFileFormat` (§9.3) |
| `{B438A617-2434-5A24-C1B7-58980F28345A}` | 2345 | **NOT SHIPPED BY EPIC** — hand-added here. `desc` reads `Name,X (East), Y (North), Altitude, XAccuracy, YAccuracy, AltitudeAccuracy, YawAccuracy, PitchAccuracy, RollAccuracy` — **the desc omits Yaw/Pitch/Roll but the parser has them**: `Yaw`/`Pitch`/`Roll` at indices 7/8/9, `YawAccuracy`/`PitchAccuracy`/`RollAccuracy` at 10/11/12, 13 columns total |

[shipped schema: `C:\Program Files\Epic Games\RealityScan_2.2\flightlogs.xml`, read
directly]

**[VERIFIED] The 13-column format was never installed until 2026-07-25.**
`FlightLogParams.xml` referenced `{B438A617…}` but the app's stock `flightlogs.xml` did not
contain it, so **orientation (YPR) and per-image accuracies were silently dropped on every
import to that date**. Fixed by merging the format into Program Files — a modification of an
Epic-shipped schema file that **must be re-checked after any RealityScan update**.
[VERIFIED: PRIORS_DISTORTION_TEST_PLAN audit item 1, 2026-07-25] [OPEN: whether the
hand-merged format survives an app update]

### 9.2 The flight log can carry calibration, not just pose

Full variable set for `RealityScan.Import.CSVFlightLog`
[OFFICIAL: tools/defineimportformat]:

`Image` · `Longitude` / `LongitudeAccuracy` · `X` / `XAccuracy` · `Latitude` /
`LatitudeAccuracy` · `Y` / `YAccuracy` · `Altitude` / `AltitudeAccuracy` ·
`Yaw` / `YawAccuracy` · `Pitch` / `PitchAccuracy` · `Roll` / `RollAccuracy` ·
`Omega` / `OmegaAccuracy` · `Phi` / `PhiAccuracy` · `Kappa` / `KappaAccuracy` (the
omega/phi/kappa set is "only for georeferenced scenes") · **`FocalLength`** ·
**`PrincipalU`** · **`PrincipalV`** · **`Skew`** · **`AspectRatio`** ·
**`RadialDistortion1..4`** · **`TangentialDistortion1..2`**.

Column `format` attribute values: `value` (exact number), `degrees`
(e.g. `N65 23 12.1`), `name` (string), `name.ext` (file path/name with extension).

Each variable becomes an XML **element name** inside `<parser>`, carrying `index`
(0-based column) and `format`. The container grammar is
`<format id descID desc reader><parser separator allowedSeparators comment
showIgnoreFirstline qualifiers>…</parser></format>`.
[OFFICIAL: tools/defineimportformat]

**The bolded calibration variables are an unused channel here.** A custom format could carry
per-image focal and distortion priors without any XMP sidecar at all — worth knowing for
rigs where writing thousands of sidecars is the expensive part. Concretely, appended to
`C:\Program Files\Epic Games\RealityScan_2.2\flightlogs.xml`:

```xml
<format id="{A1B2C3D4-0000-4000-8000-000000000001}" descID="2346"
        desc="Name, X, Y, Alt, Focal35, RadialDistortion1 (character-separated)"
        reader="RealityScan.Import.CSVFlightLog">
    <parser allowedSeparators=",; &tab;" comment="#" showIgnoreFirstline="true"
            qualifiers="&quot;optional">
        <Image index="0" format="name.ext"/>
        <X index="1" format="value"/>
        <Y index="2" format="value"/>
        <Altitude index="3" format="value"/>
        <FocalLength index="4" format="value"/>
        <RadialDistortion1 index="5" format="value"/>
    </parser>
</format>
```

Never exercised. Note that a hand-added format is a modification of an Epic-shipped schema
file and is lost on update — the same maintenance burden as `{B438A617-…}` in §9.1.
[OPEN — see Q4.]

### 9.3 Import parameters (`FlightLogParams.xml`)

The repo's template, `<Configuration id="{93DBD041-AE1C-4631-89BC-D9430FCED843}">`, is
**regenerated per run** from the UTM zone tag in the flight log's filename — never
hand-edit its zone:

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

| Key | Import-dialog field it carries | Confidence |
|---|---|---|
| `gpsLogFileFormat` | **File format** (a format GUID from `flightlogs.xml`) | [VERIFIED-by-use] |
| `CoordinateSystemFlightLog` | **Coordinate system** — a proj4 string | [VERIFIED-by-use] |
| `CoordinateSystemFlightLogType` | the same CRS in `epsg:NNNNN - <name>` display form | [VERIFIED-by-use] |
| `csvFLSep` | **Values separator** | [INFERRED] |
| `csvFLIgn` | **Ignore first line** | [INFERRED] |
| `ifUsePosAcc` / `ifUseOriAcc` | **nothing — neither key exists in the product** | [CONTRADICTED — see below] |
| `ifuuInhEn` / `ifuuInh` | **Accuracy settings source** (inherit global vs from file) | [INFERRED] |
| `ifCSopt` | coordinate-system option flag | [INFERRED] |
| `ifKGrp` | **Automatically group camera calibration** | [UNDOCUMENTED-VERIFIED — see below] |
| `ifKmode` | **nothing — this key does not exist in the product** | [CONTRADICTED — see below] |

#### [CONTRADICTED] Three of this template's twelve entries name nothing

- **Repo record says**: "`ifKGrp` and `ifKmode` are the only plausible carriers of the
  *Euler angles order (YPR)* and *Camera mount* settings", and "neither string appears in
  **any** file under `C:\Program Files\Epic Games\RealityScan_2.2`"
  [VERIFIED-as-repo-record: FINDINGS 2026-07-26]; and, separately, "the production params
  point at the 13-column format with **`ifUseOriAcc=true`**, so the 2026-07-24 fresh-run
  aligns DID import orientation at 3/5/3" [VERIFIED-as-repo-record: FINDINGS 2026-07-26,
  the SCOPE correction].
- **Observed**: a string scan of
  `C:\Program Files\Epic Games\RealityScan_2.2\RealityScan.exe` (2.2.0.119430), in both
  `ascii` and `utf-16-le`, finds **`ifKmode`, `ifUsePosAcc` and `ifUseOriAcc` absent** —
  not merely rare, absent, and absent too under a case-insensitive substring search for
  `usepos`, `useori`, `posacc`, `oriacc`, `useacc`, `ifuse`. The other nine entries of the
  template (`ifuuInhEn`, `ifCSopt`, `gpsLogFileFormat`, `CoordinateSystemFlightLog`,
  `CoordinateSystemFlightLogType`, `ifKGrp`, `csvFLIgn`, `ifuuInh`, `csvFLSep`) are all
  present. The nearest real key to `ifKmode` is **`ifKModel`** (capital `M`, trailing `l`),
  which the binary pairs with the label *Internal calibration*, not with any rotation
  setting. The earlier "appears in no file" search evidently covered only the XML/config
  files or only ASCII and missed the executable's UTF-16 string table.
- **How observed**: byte scan of the shipped executable for each candidate in both
  encodings. [UNDOCUMENTED: this session]
- **Consequence, and it is load-bearing**: `<entry key="ifKmode" value="0x0"/>`,
  `<entry key="ifUsePosAcc" value="true"/>` and `<entry key="ifUseOriAcc" value="true"/>`
  are **inert**. Whether the log's accuracy columns were consumed was therefore decided by
  `ifuuInhEn` / `ifuuInh` alone. The repo sets `ifuuInhEn=true`, `ifuuInh=0`, and the
  documented per-input twin `inpPriorAccuracyInh` uses `0` = *Global camera prior settings*
  / `1` = *Edit custom values* [OFFICIAL: tutorials/editselectioncommand]. **If `ifuuInh`
  shares that encoding, `ifuuInh=0` means the file's per-image accuracy columns were
  ignored in favour of the global `sfmCameraPriorAccuracy*` values** — which §7.2 shows
  were themselves never applied, leaving RealityScan's defaults 10/10/20 m and 10/10/10°.
  [INFERRED — the `ifuuInh` enum has not been read out of the binary and the twin-key
  analogy is not proof.]
- **Escalation**: this would revise an entry already logged ESTABLISHED (the 2026-07-26
  SCOPE correction) and would put a second asterisk on every orientation-accuracy
  conclusion in §7.5 — not on whether orientation was imported (it was: the 13-column
  format carries Yaw/Pitch/Roll as *values*, independent of the accuracy question), but on
  what accuracy it was imported at. **Probe before acting**: import the smoke fixture twice
  with `ifuuInh=0` and `ifuuInh=1`, and read `priorErrorX/Y/Z` per camera out of a report
  template (§7.2). ~5 minutes; it settles the enum and the applied accuracy at once.
  [OPEN — Q24.]

The rotation settings are carried by their own key family, recovered from the same
`ImportFlightLogCommand` configuration block. Each key is preceded in the string table by
its **default value**, which is how the defaults below are read
([INFERRED] from that adjacency, [UNDOCUMENTED-VERIFIED] for the key spellings):

| Key | Dialog field | Default value token |
|---|---|---|
| `gpsLogFileName` | **File name** | — |
| `gpsLogFolder` | source folder | — |
| `gpsLogFileFormat` | **File format** | `{80679981-0DF8-43DE-ABF7-35CCD8563320}` (Custom) |
| `gpsLogCustomFormat` | **Custom format description** | `Image X/Lon Y/Lat Z/Alt Yaw Pitch Roll` |
| `gpsLogEulerAnglesOrderYPR` | **Euler angles order (YPR)** | **`EULER_ROT_ZYX`** |
| `gpsLogEulerAnglesOrderOPK` | **Euler angles order (OPK)** | **`EULER_ROT_XYZ`** |
| `gpsLogMount` | **Camera mount** | **`MOUNT_DOWNWARD_X_EASTWARD`** |
| `gpsLogCameraAxes` | **Camera coordinate system** | **`CAMERA_AXES_PHOTOGRAMMETRIC`** |

**The YPR Euler-order default is `EULER_ROT_ZYX`**, whose combo label is
`ZYX (photogrammetric YPR convention)`. That is exactly the order this repo's producer
assumes (§6.5), so the first item of the §7.5 contamination flag — "the composition may be
wrong even though each individual angle is right" — is **substantially de-risked**: the
unpinned setting was already sitting at the value the pipeline needed.
[UNDOCUMENTED-VERIFIED: binary defaults, this session] [INFERRED that the stored default is
what an unpinned params file actually gets — the alternative is that the dialog's last-used
value persists in app settings, which would make it machine-dependent. Cheap check: import
once with the key pinned to `EULER_ROT_ZYX` and once unpinned, and diff the solved
attitudes.]

The **Euler angles order** combo offers six orders, verbatim:
`ZXY` · `ZYX (photogrammetric YPR convention)` · `YXZ` · `YZX` ·
`XYZ (photogrammetric OPK convention)` · `XZY`. [UNDOCUMENTED: binary UI strings]

#### The rest of the trajectory-import key space — [UNDOCUMENTED]

The same block yields the whole import dialog, most of which the repo has never touched:

| Key | Dialog label | Binary tooltip |
|---|---|---|
| `ifKGrp` | Automatically group camera calibration | "Group camera calibrations, such as focal length and distortion parameters. This results in a better alignment quality if the captured land is flat or texture is weak." |
| `ifKModel` | **Internal calibration** | "Define how much you trust the imported calibration values." Options: *Ignore imported calibration* · *Values should be further optimized* · *Exact values* ("Imported values will be used without further optimization") |
| `ifDistortionmode` | **Camera model** | "Select lens distortion model for the imported data." |
| `ifuRotEnable` | **Use trajectory orientation** | "'Enable' or 'Disable' importing of the camera orientation." |
| `ifOfsX` / `ifOfsY` / `ifOfsZ` | **Nodal point X / Y / Z offset** | "Offset in the image X axis direction…" / "…image Y axis direction…" / "…the **look at** direction…", in coordinate-system units |
| `ifOfsRY` / `ifOfsRP` / `ifOfsRR` | **Yaw / Pitch / Roll angle offset** | "Relative rotation round image **X** axis." / "…image **Y** axis." / "…image **Z** axis." |
| `ifuPosX` / `ifuPosY` / `ifuPosZ` (+ `…l`) | global position accuracy | "Specify global position accuracy. You can also define accuracy per entry in the trajectory." |
| `ifuRotY` / `ifuRotP` / `ifuRotR` | global rotation accuracy | "Specify global rotation accuracy. You can define it per entry in the trajectory." |
| `ifuuInh` / `ifuuInhEn` | Accuracy settings source | — |
| `ifTmode` / `ifRmode` | translation / rotation mode | — |
| `CoordinateSystemFlightLogUnits` | CRS units | — |

**`ifOfs*` is a native lever-arm and boresight facility** — the dialog calls the group
"GPS/INS offset", "Define the relative offset between the camera nodal point and the
positioning system", enabled by "Compensate GPS/INS offset". This repo computes the lever
arm itself, in the **world** frame from vehicle heading (§10.3), while RealityScan expects
it in the **camera/image** frame (image X, image Y, look-at). Both are legitimate; doing
both would double-apply. Nothing in the Help mentions this facility at all.
[UNDOCUMENTED: binary UI strings, this session] [OPEN — see Q7: nobody has tested whether
`ifOfs*` in a params XML is honoured headless.]

### 9.4 Rotation semantics on import

- Imported **YPR is interpreted in NED** (North-East-Down); **OPK is the ENU variant**.
  [OFFICIAL: tools/flightlogimport]
- "**Euler angles order (YPR)** Defines the rotation order around the X (Roll), Y (Pitch),
  and Z (Yaw) axes… **The rotation order is evaluated from right to left.**"
  [OFFICIAL: tools/flightlogimport]
- "**Camera mount** Specifies how the camera is mounted relative to the coordinate system of
  the platform on which it is installed. **This option is available when Yaw-Pitch-Roll
  rotations are included in the file format.**" [OFFICIAL: tools/flightlogimport]
- "**Camera coordinate system** Specifies the convention of the coordinate system axes.
  This option is available when Omega-Phi-Kappa rotations are included."
  [OFFICIAL: tools/flightlogimport]

#### The Camera mount options — [UNDOCUMENTED], and they are all nadir-facing

The Help names the field and refuses to enumerate it. The binary's combo list has exactly
four entries:

| Option (verbatim) |
|---|
| `Nadir-facing, X-axis to nose` |
| `Nadir-facing, X-axis to right wing (RealityScan convention)` |
| `Nadir-facing, X-axis to tail` |
| `Nadir-facing, X-axis to left wing` |

and the **Camera coordinate system** combo has two:
`Photogrammetric (RealityScan convention)` · `Computer vision`.
[UNDOCUMENTED: binary UI strings, this session]

Two consequences that change the shape of the §7.5 contamination flag:

- **Camera mount is an azimuth choice, not a tilt.** All four options are nadir-facing;
  they differ only in where the image X axis points on the airframe. So a non-identity
  mount default cannot double-apply this repo's *pitch* offset. The residual hazard is a
  **yaw/heading** rotation of 0°/90°/180°/270°, which is a real failure mode but a
  different one — and it is invisible to a registration count, exactly like the scale
  errors in §7.5. [INFERRED from the option labels; not probed.]
- **There is no oblique mount option.** A rig whose cameras are not nadir-facing (Cinema at
  45° down, Port at ~0° — §10.3) *must* bake the tilt into the imported YPR, which is what
  this repo does. That is the correct choice, not a workaround.
  [INFERRED from the option list.]

The stored default token is `MOUNT_DOWNWARD_X_EASTWARD` — a world-referenced name that does
not map onto any of the four airframe-referenced labels, so which combo entry it selects is
**not** settled. [OPEN — see Q7.]

### 9.5 Behaviour of `-importFlightLog`

`-importFlightLog <flightLogFile> <params.xml>` is **[UNDOCUMENTED]** — the string does not
appear anywhere in the 2.2 offline Help; the documented name is `-importTrajectory`. It
nevertheless works and is this repo's only georeferencing import path (6 call sites).
[VERIFIED by execution on two machines] [OPEN: whether the two are the same
implementation — run both on the smoke fixture with the same params XML and diff the
resulting prior poses]

| Behaviour | Tag |
|---|---|
| Rows referencing images **not in the scene** make the import report a **failed** process (`err:18002`, `0x820000FF`) even though the present rows import fine. Verified benign by matching all 102 "not found" images against every component manifest: **zero overlap** — they are exactly the unregistered remainder | [VERIFIED: FINDINGS 2026-07-21, 2026-07-25] |
| Name matching is by **basename** and finds images in subfolders | [VERIFIED: NA167 #5, 2026-07-22] |
| The params' CRS **must** match the log's UTM zone — a wrong zone imports **silently** and misplaces everything. Derive the zone per cruise; never hand-edit the template | [VERIFIED: NA167 #6, FINDINGS 2026-07-21/22] |
| Import leaves the matched images **actively selected**; `-deselectAllImages` before any export | [VERIFIED: FINDINGS 2026-07-23] |
| A UTM zone is derived from the log filename tag by `modules/flight_logs.write_flight_log_params` (`flight_log_53N_UTM.txt` → EPSG:32653); `find_flight_log` is the **only** way any stage locates a log on disk | [VERIFIED-as-architecture: CLAUDE.md] |

---

## 10. Applied: the four-camera underwater ROV rig

### 10.1 The cameras (`modules/camera_registry.py` — the single source of truth)

| Physical camera | Optics | Calibration group | Lens group | `CalibrationPrior` | `FocalLength35mm` | `DistortionModel` (sidecar hint) |
|---|---|---:|---:|---|---:|---|
| **Zeuss** | rectilinear 23 mm full frame | `1` | `1` | `Approximate` | `23.0` | `brown3` |
| **Port** | fisheye 14 mm full frame | `2` | `2` | `Approximate` | `16.0` | `division` |
| **Cinema** | rectilinear 17 mm full frame | `3` | `3` | `Approximate` | `16.0` | `brown3` |
| **Starboard** | fisheye 14 mm full frame | `4` | `4` | `Approximate` | `16.0` | `division` |

[VERIFIED-by-inspection: `modules/camera_registry.py`; owner-confirmed 2026-07-23]
Cinema's focal moved 17.0 → 16.0 on owner confirmation ("C=16"), corroborated by the
solver's own median 16.37 mm 35-eq over 2,204 cameras. [VERIFIED: FINDINGS 2026-07-25]
Remember §5.4: the `DistortionModel` column is a **hint only** — the global
`sfmDistortionModel` decides.

`S231C*.mov` videos are Starboard and are **excluded from photogrammetry** by owner
decision. [VERIFIED: FINDINGS 2026-07-23]

### 10.2 Identifying a camera from a filename

Two era-specific naming families map onto the same four physical units. Matching is
**most specific first**: anchored WCA prefix, then anchored legacy prefix, then a
delimiter-bounded `zeuss`/`herc` token.

```python
_WCA_PREFIX  = re.compile(r'^([pcs])\d+c', re.IGNORECASE)          # P231C0003_<ts>_edt.jpg
_ZEUSS_TOKEN = re.compile(r'(^|[_\-.])(zeuss|herc)([_\-.]|$)', re.IGNORECASE)
_LEGACY_FAMILY = (('camupper', 'legacy_camupper'),
                  ('cammid',   'legacy_cammid'),
                  ('camlower', 'legacy_camlower'))
```

| Family key | Matches | Physical camera |
|---|---|---|
| `wca_port` | `P<digits>C…` | port |
| `wca_cinema` | `C<digits>C…` | cinema |
| `wca_starboard` | `S<digits>C…` | starboard |
| `legacy_cammid` | `cammid*` | port |
| `legacy_camlower` | `camlower*` | cinema |
| `legacy_camupper` | `camupper*` | starboard |
| `zeuss` | delimiter-bounded `zeuss` or `herc` | zeuss |

Two regression-pinned traps [VERIFIED: `testing/test_rig_mounts.py`]:

- **Cruise digits must not decide the family.** Literal `p231c`/`c231c` tests meant the next
  cruise's `C245C0007_*.jpg` fell through to a **zero lever arm and 0° pitch offset** —
  Cinema losing its 45° down-look — asserted at 10° claimed confidence, with one suppressed
  warning for the whole run.
- **`herc` was tested first, unanchored, and would have beaten an anchored WCA prefix**
  (`P231C0003_herc.jpg`). The token is now delimiter-bounded and runs last.

### 10.3 Mount geometry is keyed by FILENAME FAMILY, not by camera

The same Cinema unit sits **10° down** under legacy `camlower` names and **45° down** under
WCA `C###C` names. Keying geometry off the physical camera would silently rewrite every
legacy dataset by tens of degrees. `MOUNTS` in
`modules/georeference/georeference_images.py`, imported unchanged by `geoall.py`:

| Family | fwd (m) | lat (m) | down (m) | pitch (° down from vehicle forward axis) | pitch accuracy (°) |
|---|---:|---:|---:|---:|---:|
| `zeuss` | 0.5 | 0.0 | 0.5 | 30.0 | 30.0 |
| `legacy_camupper` | 1.0 | 0.0 | 0.0 | 70.0 | 10.0 |
| `legacy_cammid` | 1.0 | 0.0 | 1.0 | 20.0 | 10.0 |
| `legacy_camlower` | 1.0 | 0.0 | 1.0 | 10.0 | 5.0 |
| `wca_port` | 1.0 | 0.0 | 1.0 | 0.0 | 15.0 |
| `wca_cinema` | 1.0 | 0.0 | 0.0 | 0.0 | 15.0 |
| `wca_upper` (`U###C`) | 1.0 | 0.0 | 0.0 | 45.0 | 15.0 |
| `na168_upper` | 1.0 | 0.0 | 0.0 | 45.0 | 15.0 |
| `wca_starboard` | **`None`** — never measured | | | | |

[VERIFIED-by-inspection + pinned by `testing/test_rig_mounts.py`, values in force 2026-07-26]

**The fallback for a family with no measured mount (2026-08-31, owner-stated).**
A family that resolves to `None` above no longer writes an empty pitch. It takes
the house convention: **10° down from the vehicle forward axis, claimed at 30°
accuracy** — which lands at **80° on the nadir scale** for a level vehicle, and
composes with vehicle pitch like any measured mount. A measured `MOUNTS` entry
always **wins**; the fallback is reached only where there is none.
[SUPERSEDED 2026-08-14 for the WCA row: the 45° down-look belongs to the upper (starboard) camera,
`wca_upper`; `wca_cinema` is 0°. Legacy `camlower` at 10° is unchanged. Addenda A2.]

| | |
|---|---|
| Source of truth | `ASSUMED_MOUNT_DEFAULTS` + `assumed_pitch_prior()` in `modules/georeference/georeference_images.py`, consumed by **both** implementations |
| Config record | `modules/cameras.json` → `defaults.assumed_mount` |
| Knobs | `--assumed-pitch` / `--assumed-pitch-accuracy` (`geoall.py`); `--g_assumed_pitch` / `--g_assumed_pitch_accuracy` (module) |
| Opt-out | a **negative** assumed pitch restores the 2026-08-07 behaviour (no pitch prior at all) |
| Never applies to | `voyis_*` — poses come from the COLMAP bridge, so a vehicle-nav prior is the **wrong pipeline**, not a missing measurement, and a fallback would mask that |
| Applies to | `wca_starboard` and any unrecognised family. The unknown-camera warning still fires, so the run still SAYS the mount was never measured |
| Lever arm | **still never invented** — an unmeasured mount contributes `(0, 0, 0)` m. The Port-1 m incident was a POSITION invention; this changes only the pitch prior |

This **reverses part of** the 2026-08-07 audit, which deleted a fallback of
**0°** ("this camera looks straight ahead") asserted at **10°** accuracy. The
owner's convention is a different geometric claim — 10° *down*, not 0° *ahead* —
but the audit's other objection still stands, which is why the accuracy is 30°:
no tighter than the loosest **measured** mount (`zeuss`), because PD-0/PD-0b
measured that over-tight orientation accuracy **fragments** solves. Asserting an
assumed tilt at a measured mount's confidence would repeat the mistake the audit
was right about. [VERIFIED: FINDINGS 2026-08-31]



`wca_starboard` is deliberately `None`: the owner excludes Starboard from photogrammetry, so
it should not be reached — and if it is, **the run must say so rather than invent a zero
lever arm and a 0° tilt**. Unknown families and known-but-unmeasured mounts are both counted
through one warning path so the run summary carries a single number for "images that got no
usable prior". Inventing rig numbers is what produced the Port-1 m incident.

Lever arms are applied in the world frame, driven by vehicle heading (UTM X=East, Y=North,
heading 0°=North increasing clockwise):

```python
east_offset  = forward_m * sin(heading) + lateral_m * cos(heading)
north_offset = forward_m * cos(heading) - lateral_m * sin(heading)
adjusted_altitude = altitude - down_m          # down is negative altitude
```

**RealityScan has a native facility for exactly this and the repo does not use it.** The
trajectory-import dialog carries a "Compensate GPS/INS offset" group — "Define the relative
offset between the camera nodal point and the positioning system" — with keys
`ifOfsX`/`ifOfsY`/`ifOfsZ` (Nodal point X/Y/Z offset) and `ifOfsRY`/`ifOfsRP`/`ifOfsRR`
(Yaw/Pitch/Roll angle offset). The frames differ: the repo applies the lever arm in the
**world** frame using vehicle heading, RealityScan expects it in the **camera/image** frame
(image X, image Y, look-at direction). Both are valid; **doing both double-applies the lever
arm.** Since the repo's params XML sets no `ifOfs*` key, nothing is double-applied today —
but anyone adding one must remove the Python offset first.
[UNDOCUMENTED: binary UI strings, §9.3] [OPEN — headless behaviour of `ifOfs*` untested,
Q7.]

### 10.4 The lever-arm retraction chain — four steps, all retained

1. **Original (2026-07-23, owner-stated):** Port 0° pitch, 1 m forward + 1 m down;
   Cinema 45° down, 1 m forward. [VERIFIED-as-owner-statement, 2026-07]
   [SUPERSEDED 2026-08-14: the 45° down-look is the UPPER camera's (`wca_upper`); Cinema is 0°.
   The NA156 line was solved with Cinema at 45 — Addenda A2, FINDINGS 2026-08-14]
2. **Measured from the solve (2,169 near-simultaneous C/P pairs, zone_1 fresh run):** angle
   **47.2°** (IQR 47.0–47.4) confirmed; but |P−C| separation **0.22 m**, vertical component
   **0.00 m** ⇒ "the Port lever arm is wrong by ~1 m". [SUPERSEDED the same session]
3. **Retraction:** that measurement was taken **inside hull c0 — the 0.175-scale
   component** — so both the separation and its vertical part are meaningless
   (0.22 × 5.7 ≈ 1.25 m). Only the **angle** survived, because angles are invariant under
   scale and rotation. Re-measured on **two independent metrically-sound solves** (bow c2;
   zone_2 from PD-2b): C-vs-P optical-axis angle **47.2° / 46.8°** vs the code's 45.0°, and
   **C above P by +1.12 m / +1.03 m** vs the code's implied +1.00 m; |P−C| separation
   1.21 / 1.11 m. **The code's original values stand, corroborated twice.**
   [VERIFIED: FINDINGS 2026-07-25]
4. **Re-application and reversal:** a 2026-07-26 owner instruction ("roughly the same
   distance forward; the Z in my notes may be wrong") was implemented — Port 1.0/1.0 →
   1.17/0.0 — **quoting the already-retracted 0.22 m figures as corroboration**. A
   contradiction audit caught it and it was reverted the same day; H2024's nav, flight log
   and zones were regenerated from raw under the restored geometry.
   [SUPERSEDED: FINDINGS 2026-07-26]

**DECISION IN FORCE: Port 1.0 m forward / 1.0 m down, Cinema 1.0 / 0.0. Do NOT flatten them
on the strength of the 0.22 m / 0.00 m figures — those are scale-corrupted, and they were
retracted once and re-applied by mistake before an audit caught it.**
[VERIFIED-as-decision: HANDOFF 2026-07-27; pinned by `test_port_sits_one_metre_below_cinema`]

**Why rig-internal derivation is trusted where absolute-mount derivation is not:** relative
axis angle and relative position between two cameras on one rigid vehicle are observable in
*any* solve, regardless of how weakly the scene's absolute attitude is constrained. By
contrast, mount-angle derivation from solved scenes is unreliable — zone_3-derived offsets
(C ≈ 58° down, tight IQR) conflict with a steady zone_1 strip (C ≈ −42°, also tight IQR),
because a trajectory is near-1D and scene rotation about it is cheap under position-only
georeferencing. [VERIFIED: FINDINGS 2026-07-25]

### 10.5 The written flight log

`modules/georeference/georeference_images.py` writes a **13-column, semicolon-separated**
log matching `{B438A617-…}`:

```
filename;X (East);Y (North);Alt;X Accuracy;Y Accuracy;Alt Accuracy;Yaw;Pitch;Roll;Yaw Accuracy;Pitch Accuracy;Roll Accuracy
```

Accuracies in force: **position 10.0 / 10.0 / 1.0 m** (end-to-end per-image uncertainty, not
the DVL/Paro sensor spec — see §7.5), **yaw 15.0°, roll 15.0°, pitch per-family from
`MOUNTS['p_acc']`**. No magnetic declination is applied and that is **correct**:
`kalman_yaw_deg` comes from an Octans gyrocompass, so it is already true north and
`decl = 0` is right. The repo's `HEADING_MAG` variable name is a misnomer.
[VERIFIED-in-part: HANDOFF 2026-07-27] [OPEN: confirm the Octans true-vs-magnetic claim from
a primary source]

Georeference acceptance: H2023 4,598/4,598 (100 %, all exact time matches, zone 4Q);
H2024 8,197/8,197 (100 %, zone 4Q); NA167 29,620 images with 18,944 matched ≤ 2 s and the
10.4k out-of-dive-window WCA files correctly **rejected**.
[VERIFIED: FINDINGS 2026-07-26; HANDOFF 2026-07-22]

### 10.6 The bow tilt — what a wrong orientation prior actually looks like

Owner report: the bow model sits ~45° off the true ground plane (the site is a flat mud
floor). **The align is not the culprit.** Measured from the PD-6 harvest: the bow's solved
camera cloud matches nav to **0.8°** in best-fit-plane attitude (solved 8.1° off vertical vs
nav 7.3°), shape ratios agree to three decimals (mid/max 0.371 vs 0.370), and its optical
axes are statistically identical to the hull's (median 148.1 vs 147.7° from local up). There
is **no 45° rotation in the zone solve**. [VERIFIED: FINDINGS 2026-07-26]

Where YPR actually entered: the PD-6 align log was **7-column position-only**, while the
assembly's union log was **13-column carrying YPR at 3/5/3 accuracies** — so the **only**
consumer of orientation was `-update` in the assembly. [VERIFIED: FINDINGS 2026-07-26]

Ranked candidates [INFERRED-ranked]:

1. **`-update` rotated the bow to satisfy mis-converted orientation priors.** The Euler
   order / camera-mount convention is explicitly unverified, and a 656-camera component
   spanning 9.3 m on a near-1D track is cheap to rotate about that track (the fit trades a
   small position penalty for the orientation term), whereas the hull (3,738 cameras over
   17.9 m) is far stiffer. Predicts a clean near-rigid tilt — which matches a crisp "45
   degrees".
2. **Internal deformation of the bow.** Scale IQR width **0.444** vs the hull's 0.081
   (5.5× wider), which by the oracle's own semantics means drift/fold rather than a
   similarity error. Explains floor non-flatness but not a clean 45° plane.

**Blindness now load-bearing (escalation condition): assemble mode exports no poses, so the
assembled project — the artifact the owner actually looked at — cannot be measured.
Hypotheses can only be ranked until poses are harvested from a copy of the assembly.**
[OPEN]

**Cheap decisive test (~2 min):** re-run the assembly `-update` with a **position-only**
union log and re-measure the bow's attitude. If the tilt disappears, candidate 1 is
confirmed and the remedy is to verify the YPR convention before importing orientation
anywhere. [OPEN — queued probe (h), never run]

**Owner position (agreed, with caveats):** pitch/roll/yaw belong in the **alignment** priors,
not merely in the post-hoc georeferencing fit — that is where they would anchor absolute
attitude **and** stiffen a solve against exactly the drift measured in candidate 2. Caveats:
import at 15° accuracy (provisional, not validated), and **verify the convention first** —
importing wrong-convention YPR is itself a mechanism for this defect.
[VERIFIED-as-decision: FINDINGS 2026-07-26]

### 10.7 Cross-engine echo on the Zeuss camera

COLMAP on zone_9 **registered 710 Zeuss frames but triangulated ZERO points from them** —
they contribute nothing downstream. Independently echoing this line's NA167 zone_13 A/B,
where XMP priors cost 6.7 points of registration **specifically on Zeuss**. Two engines, two
failure shapes, one physical camera family: **treat Zeuss calibration and imagery as
suspect** and prioritise per-camera validation when Zeuss zones underperform.
[VERIFIED-in-the-other-fact-base: COLMAP C-20260721-15/Q-07, recorded here 2026-07-24; not
reproduced in RealityScan]

### 10.8 One anomaly that will self-separate

Exactly one image of the 8,197-image H2024 census, `C231C2370_20231104202628_edt.jpg`, is
**3846×2163** while the other 8,196 are **4244×2827**. A different sensor footprint means
different intrinsics, so RealityScan will group it separately regardless of its XMP
calibration group. [VERIFIED: FINDINGS 2026-07-25]

### 10.9 A complete, runnable per-zone invocation

The canonical production shape (`AlignZone.bat`, driven by `RealityScanCLI`), reduced to its
geometry-relevant steps. Paths are of the production *shape*; substitute your own volumes.

```bat
:: 0. Restore calibration sidecars stripped by a previous identity harvest.
::    (Python: camera_registry.ensure_calibration_sidecars(zone_dir))

:: 1. Fresh scene on the pinned instance.
RealityScan.exe -delegateTo RS1 -newScene

:: 2. Subfolder recursion is NOT the default in this build: without it a zone
::    tree with per-camera subfolders adds 0 layer images and the flight-log
::    import then fails err:18002 in a 25 s "successful" run.
RealityScan.exe -delegateTo RS1 -set "appIncSubdirs=true"
RealityScan.exe -delegateTo RS1 -addFolder "F:\na156_h2024\batched_images_by_zone\zone_3"

:: 3. Pose priors. Params XML is regenerated per run from the log's zone tag.
RealityScan.exe -delegateTo RS1 -importFlightLog ^
    "F:\na156_h2024\batched_images_by_zone\zone_3\flight_log_4Q_UTM.txt" ^
    "F:\na156_h2024\ab_position_only\zone_3\FlightLogParams_4Q.xml"

:: 4. -align takes NO parameters in 2.x. Apply every sfm*/lis* key first.
::    Delegated commands queue FIFO, so the sets execute before the align;
::    they are instant and need no completion wait.
RealityScan.exe -delegateTo RS1 -set "sfmEnableCameraPrior=true"
RealityScan.exe -delegateTo RS1 -set "sfmDistortionModel=Division"
RealityScan.exe -delegateTo RS1 -set "sfmCameraPriorWeight=10.0"
RealityScan.exe -delegateTo RS1 -set "sfmCameraPriorWeightOrientation=10.0"
RealityScan.exe -delegateTo RS1 -set "sfmCameraPriorAccuracyYaw=10.0"
RealityScan.exe -delegateTo RS1 -set "sfmCameraPriorAccuracyPitch=10.0"
RealityScan.exe -delegateTo RS1 -set "sfmCameraPriorAccuracyRoll=10.0"
RealityScan.exe -delegateTo RS1 -set "sfmDetectorSensitivity=Ultra"
RealityScan.exe -delegateTo RS1 -set "sfmImagesOverlap=Medium"
:: ...plus the rest of AlignmentParams.xml, sfm*/lis* only

RealityScan.exe -delegateTo RS1 -align

:: 5. Flight-log import left its matched images ACTIVELY SELECTED, and
::    selection-driven exports under -silent then export NOTHING (an XMP
::    export finished in 0.057 s instead of 20.5 s). Clear the selection
::    before EVERY export step, not just this one.
RealityScan.exe -delegateTo RS1 -deselectAllImages

:: 6. Export gate (default is 5; production uses 50), save, then the
::    pose census. XMP sidecars are written BESIDE THE IMAGES, not to the
::    project folder.
RealityScan.exe -delegateTo RS1 -setMinComponentSize 50
RealityScan.exe -delegateTo RS1 -save "F:\na156_h2024\components\zone_3.rsproj"
RealityScan.exe -delegateTo RS1 -deselectAllImages
RealityScan.exe -delegateTo RS1 -exportXMP
```

Every delegated command in production runs through the shared `:run` subroutine
(delegate → grace → `-waitCompleted` → grace → `-waitCompleted` → abort if the errors marker
is non-empty). See the CLI-fundamentals document; it is omitted here for readability, **not
because it is optional**.

Settings must cross the .bat boundary as `key:value` and be converted inside the workflow —
cmd splits unquoted `;` `,` `=` and Python's `subprocess` quotes only on whitespace, which
once meant **no flag cell had ever applied its flags** (`err:7155`, "Parsing setting
key=value … failed"). [VERIFIED: NA167 B5, 2026-07-23]

---

## 11. Undistortion and registration export

### 11.1 The undistortion pipeline, in the order the app applies it

[OFFICIAL: tools/undistort]

1. **Image cut-out** — which fraction of the image is considered for undistortion.
   `1.0` = full image, `0.5` = 50 %, `0` = nothing. **"For fish-eye lenses, we recommend
   using factor 0.8."**
2. **Fit** — which section of the undistorted image reaches the output:
   *Outer boundary*, *Inner region*, *In between*, or **Keep intrinsics** (preserves the
   camera calibration parameters).
3. **Resolution** — *Fit* (keep the resolution from step 2), *Preserve* (same as the
   original image), *Custom* (arbitrary; enables Custom width / Custom height).
4. **Downscale** — integer divisor applied to each side; `1` = no change.
5. **Max count of pixels** — `0` = no limit; otherwise the aspect ratio is preserved and the
   image resampled to fit.
6. **Undistort principal point** — `1` shifts the optical centre to the actual centre of the
   exported image; `0` no shift.

CLI: `-exportUndistortedImages <folderName> [params.xml]`.
**Beware the Help typo**: `tutorials/commandline_1` spells it `exportUndistoredImages`
(missing `t`). The master table and process id `21812 EXPORT_UNDISTORTED_IMAGES` both spell
it correctly. Do not use the typo'd spelling.
[OFFICIAL: appbasics/allcommands] [INFERRED: it is a doc typo, not a second command]

### 11.2 Registration export formats and what each does to the rotation

`-exportRegistration <fileName> [params.xml]`. **Without a params XML it blocks forever
headless** — avoid until a params file has been saved once from the GUI dialog.
[VERIFIED: FINDINGS 2026-07-21] The only way to obtain a valid params XML for any tool is to
export it from that tool's GUI dialog once. [VERIFIED-as-practice]

From the shipped `calibration.xml` — the transformation each format applies to RealityScan's
native `R`, `t`:

| Format (`desc`) | GUID | Rotation/translation transform in the shipped body |
|---|---|---|
| RealityScan Alignment Component (`.rsalign`) | `{F36B3462-…}` | opaque `rca` writer, no body |
| RealityScan XMPs with Image List | `{B95BEEA0-…}` | `RealityScan.Export.XMP` writer, no body |
| Image List | `{91058C36-…}` | paths only |
| Original / Undistorted Images with Image List | `{EB6BDCCF-…}` / `{3C5CC7F3-…}` | names only |
| `Comma-separated, Name, X/Lon, Y/Lat, Z/Alt` | `{720A2EC9-…}` | positions only (`$(x),$(y),$(z)`), `requiresGeoref="1"` |
| …`, Omega, Phi, Kappa` | `{B3EE1544-…}` | `EulerFormat="xyz"`, `$(geoOmega),$(geoPhi),$(geoKappa)`, `requiresGeoref="1"` |
| …`, Yaw, Pitch, Roll` | `{121D2018-…}` | `EulerFormat="zyx"`, `$(geoYaw),$(geoPitch),$(geoRoll)`, `requiresGeoref="1"` |
| Boujou | `{700E6EE9-…}` | `R00..R22` and `tx,ty,tz` **unchanged**, "rotation applied before translation"; focal as `$(f*scale)` in pixels |
| Bundler v0.3 | `{ECC4131A-…}` | `diag(1,−1,−1)·R·M` with a Z-up→Y-up world change; translation `tx,−ty,−tz`; points `x, −z, y` |
| Bundler v0.3 (negative Z) | `{648CB940-…}` | first matrix row unchanged, **second and third rows negated** (`−R1*`, `−R2*`); translation `tx,−ty,−tz`; points **unpermuted** `x, y, z` |
| CmpMvs _P Matrices | `{2155D4AC-…}` | builds `K[R|t]` inline from `R`, `t`, `f*scale`, `px`, `py`, `width`, `height` |
| COLMAP | `{280B11A4-…}` | `RealityScan.Export.COLMAP` writer, no body |
| Internal/External Camera Parameters | `{0CA18733-…}` | `EulerFormat="zyx"`; columns `name,x,y,alt,yaw,pitch,roll,f_35mm,px_norm,py_norm,k1,k2,k3,k4,t1,t2`; `f_35mm = $(f*36)`. **Angles, not a matrix.** |
| Maya 2013 ASCII Scene | `{93B7C9C6-…}` | `EulerFormat="zxy"`; `.rotate = (pitch, roll, −yaw)` |
| **OpenCV-compliant Internal/External** | `{B5331837-…}` | `R00..R22` and `tX,tY,tZ` **unchanged**; focal/principal in **pixels** (`$(f*scale)`, `$(px*scale+width*0.5)`); distortion reordered to OpenCV order; `supportsGeoref="0"` |
| Radiance Fields Transformation File | `{314B5F22-…}` | `$Mat44Inv` of the 4×4 built from `R00,−R02,R01,tx / R10,−R12,R11,ty / R20,−R22,R21,tz`, then columns 1 and 2 of the **inverse** sign-flipped → NeRF `transform_matrix` (camera-to-world) |
| ST Maps | `{CC3F5938-…}` | `RealityScan.Export.STMaps`, no body. CLI: `-exportSTMap <folderName> <params.xml>` |

[shipped schema: `C:\Program Files\Epic Games\RealityScan_2.2\calibration.xml`]

The **OpenCV-compliant** export is the single most useful one for validating your
understanding of RS's geometry, because it is the only format whose header states its own
convention in words. Use it as the reference when disambiguating anything in §6.

### 11.3 Export transformation settings (they apply *before* the format's own transform)

[OFFICIAL: tools/exportregistration]

- **Coordinate system** — the CRS the registration is written in.
- **Scene transformation** — Move X/Y/Z; Rotate X/Y/Z ("Euclidean scene rotation around the
  respective coordinate axis, −180…180"); Scale X/Y/Z.
- **Normal transformation** — Space = `World` / `Object` / `Tangent (Mikktspace)`;
  Range; Flip X/Y/Z. "The Object option is similar to World, except that the rotation
  specified in Scene Transformation is **not** applied to the normals."

A non-identity Scene transformation silently changes every exported rotation. If two
exports of the same component disagree, check this before suspecting the app.
[INFERRED — the mechanism is documented; no incident here]

---

## 12. Recipes and checklists

### 12.1 Setting up a new multi-camera rig for headless alignment

1. **Inspect EXIF first.** If two physical cameras are EXIF-identical, `sensorsdb.xml` and
   `appGroupCalibrationByExif` are both unusable — go straight to XMP sidecars.
2. **One calibration group and one lens group per PHYSICAL camera.** Never per lens type.
3. **Write `<stem>.xmp`, never `<stem>.<ext>.xmp`.** Verify by counting sidecars against
   images after the first write.
4. **Calibration-only sidecars** unless you deliberately want pose priors — pose sidecars
   auto-import as exact priors on any later `-add`.
5. **Choose ONE global distortion model.** Any fisheye in the rig ⇒ `Division`.
6. **Focal prior:** the 35 mm-equivalent, `Approximate`. Do not set `Fixed` unless you have a
   real calibration; `Approximate` with no coefficients does not pin distortion to zero.
7. **Pose priors** from the trajectory, position accuracies as **end-to-end per-image
   uncertainty** (10/10/1 m on this rig), orientation accuracy honest (15°).
8. **Verify the flight-log format is actually installed** in
   `C:\Program Files\Epic Games\RealityScan_2.2\flightlogs.xml` before trusting that
   orientation and accuracy columns were consumed. A missing format drops them **silently**.
9. **Pick ONE place for the lever arm** — your producer's world-frame offset *or*
   RealityScan's camera-frame `ifOfsX/Y/Z`. Never both (§10.3).
10. **Decide the XMP export mode deliberately.** `xmpCamera=3` writes *locked* pose priors
    that auto-import on any later `-add` and then forbid incremental growth (§2.5, §3.3).
    If you only want calibration out, that is `xmpPose`/`xmpCalib`, not the default.
11. **Re-check after every RealityScan update** — a hand-merged format will be overwritten.
12. **Census, don't trust exit status.** Count pose-bearing sidecars. For the *grouping*
    question specifically, `$ExportInputsGrouping` answers it directly (§4.4a).

### 12.2 Before trusting any orientation prior

- [ ] Is the flight-log format with YPR columns present in `flightlogs.xml`? (A missing
      format drops the columns **silently** — §9.1.)
- [ ] Does the params XML pin `gpsLogEulerAnglesOrderYPR` and `gpsLogMount`? (Today: **no**
      — and note `ifKmode` pins nothing; it is not a real key, §9.3.) The binary defaults
      are `EULER_ROT_ZYX` and `MOUNT_DOWNWARD_X_EASTWARD`.
- [ ] Does your producer already bake a **yaw/azimuth** offset into the angles? All four
      Camera mount options are nadir-facing azimuth variants (§9.4), so the double-apply
      risk is in heading, not pitch.
- [ ] Are your cameras non-nadir? Then the tilt **must** be baked into the imported YPR —
      there is no oblique mount option.
- [ ] Is any camera's pitch within ~5° of ±90°? If so, expect yaw/roll degeneracy.
- [ ] Has the convention been confirmed by the render probe (§6.6) on this build?
- [ ] Are you writing pose sidecars at `locked`? `xmpCamera=3` does (§2.5) — sanitise the
      image tree before any later `-add`, or the next align inherits immovable cameras.
- [ ] Is there a metric-scale oracle watching the result? Registration counts will **not**
      catch a convention error — the bow 2×2 moved scale by 20 % while registration moved by
      9 cameras out of 665.

### 12.3 Diagnosing "the model is rotated wrong"

1. Measure the **component's own** camera cloud against nav (best-fit-plane attitude, shape
   ratios, optical-axis distribution). If it matches nav, the align is exonerated.
2. Find every stage that consumed orientation. In an assemble/merge pipeline that is usually
   **only `-update`**, which is a similarity fit applied after reconstruction.
3. Re-run that stage with a **position-only** log and re-measure.
4. If the tilt survives, look for internal deformation: a scale IQR several times wider than
   a healthy component means drift/fold, not a similarity error.

---

## Open questions

Every [OPEN] in this document, with the cheapest probe that answers it.

| # | Question | Cheapest probe |
|---|---|---|
| **Q1** | **LARGELY RESOLVED (this session).** The camera-export-mode enum is `0` Do not export, `1` draft, `2` exact, `3` **locked** (binary UI resource string, §2.5), so `xmpCamera=3` = *Export as locked* and this repo's `-exportXMP` writes **locked** pose priors. Residual: whether the enum is bound to `xmpCamera` or to the adjacent `xmpPrecision`. | `findstr /c:"xcr:PosePrior" <any sidecar produced by -exportXMP>` — the value (`initial`/`exact`/`locked`) settles it in one second. Failing that, GUI save-and-diff of the params XML at each of the four modes. |
| **Q2** | Which frames do `xcr:Rotation` / `R00..R22` / `tX,tY,tZ` map between, and what are the YPR axis assignments and signs on this build? | (a) Export one component as **XMP** and as **OpenCV-compliant Internal/External Camera Parameters**; for one camera test numerically whether `t == −R·C` and whether `xcr:Rotation` equals `R` or `Rᵀ`. (b) Render the same model with `-renderMeshFromCustomPositionLookAt` (ground truth) and with `-renderMeshFromCustomPositionYPR` at candidate triples; whichever matches pins the convention. Both are headless and need no alignment. |
| **Q3** | What is the exact mathematical form of the `Division` model (normalisation of `r`, sign convention)? Needed for any cross-engine coefficient transfer. | `-exportSTMap <folder> <params.xml>` gives an explicit distorted↔undistorted pixel mapping ("U and V represent the absolute position of the source pixel, normalized between 0 and 1, where 0 is the bottom-left corner and 1 the top-right" [OFFICIAL: tools/exportregistration]); export that plus the OpenCV CSV for the same component and fit the implied radial function. Alternatively ask Epic; the Help states only "single-parameter division model". |
| **Q4** | Can a custom flight-log format carry `FocalLength` / `PrincipalU/V` / `RadialDistortion1..4` and replace XMP calibration sidecars entirely? | Add a custom format to `flightlogs.xml` with those columns, import on the 120-image smoke fixture, align, and read the solved intrinsics out of the exported XMPs. ~5 minutes. |
| **Q5** | Does Epic's documented **group → align → ungroup → re-align** refinement help on weak-texture underwater imagery? | Z3 (124 images, ~4 min/align): align grouped, then `-removeCalibrationGroups`, `-align`, compare registration, component count and solved-intrinsic spread. Two cells, ~10 minutes. |
| **Q6** | Would declaring the C/P pair as an actual **rig** improve registration or scale? Three routes now known: (a) `xcr:Rig`/`RigInstance`/`RigPoseIndex` sidecars, (b) `inpPosePriorRelative=1` (Draft) + a shared `inpPosePriorRelativeGroup`, (c) the undocumented `inpRig*` keys / GUI Rig Creation Wizard with a `#rig_#pose_#camera` pattern (§3.1). Rig-internal geometry is measured and stable to ~0.1 m. | Z3 or the 665-image bow fixture: write rig ids on near-simultaneous C/P pairs, `inpPosePriorRelative=1`, align, and compare registration + scale-oracle verdict against the same cell without rig ids. Judge with **relative position uncertainty** (§7.2a), not registration count. Note §3.3: **Exact** relative priors forbid incremental growth, so use Draft. |
| **Q7** | **LARGELY RESOLVED (this session).** `ifKGrp` = *Automatically group camera calibration*; `ifKmode` **does not exist** (the real key is `ifKModel` = *Internal calibration* trust); Euler order and Camera mount are `gpsLogEulerAnglesOrderYPR` / `gpsLogEulerAnglesOrderOPK` / `gpsLogMount` / `gpsLogCameraAxes`, defaults `EULER_ROT_ZYX` / `EULER_ROT_XYZ` / `MOUNT_DOWNWARD_X_EASTWARD` / `CAMERA_AXES_PHOTOGRAMMETRIC` (§9.3). Residual: (a) does an *unpinned* import really get the binary default, or a persisted last-used GUI value? (b) which of the four "Nadir-facing, X-axis to …" combo entries is `MOUNT_DOWNWARD_X_EASTWARD`? (c) are `ifOfs*` lever-arm/boresight offsets honoured headless? | (a) import the smoke fixture twice — once with `gpsLogEulerAnglesOrderYPR` pinned to `EULER_ROT_ZYX`, once with the key absent — and diff the solved attitudes. (b) GUI save-and-diff of the params XML at each of the four mount entries. (c) set `ifOfsZ` to a large value on the smoke fixture and check whether the prior positions shift by that amount. Each ~2 min. |
| **Q8** | Does the hand-merged 13-column format `{B438A617-…}` survive a RealityScan update? | After any update, `grep B438A617 "C:\Program Files\Epic Games\RealityScan_2.2\flightlogs.xml"`. Zero cost; must become part of the post-update checklist. |
| **Q9** | Is `xcr:Position` UTM (not grid-local) in an **original** georeferenced zone scene, as opposed to the imported-component scenes where local was observed? | Hardening cell U13: `-exportXMP` in the original zone_2 scene and compare positions against the flight-log UTM. If they are UTM, manifests can carry true per-camera positions. Open since 2026-07-23. |
| **Q10** | How do I verify georeferencing of a merged/assembled scene **from the CLI**? | Hardening cell U7. Candidates: `-exportReport` with a components params XML; `poses2flightlog.py` residuals (a georeferenced component should fit local→UTM near identity); an exported flight-log round trip. Longest-standing open item in the repo. |
| **Q11** | Is the ~45° bow tilt caused by `-update` fitting mis-converted orientation priors? | Re-run the assembly `-update` with a **position-only** union log and re-measure the bow's attitude. ~2 minutes. Queued as probe (h), never run. **Blocked upstream by the fact that assemble mode exports no poses** — port the successive-difference harvest to a dated copy of the assembly first. |
| **Q12** | What is the optimal position-accuracy setting between the proven-loose 10/10/1 and the proven-harmful 1/1/0.1? | The queued intermediate ladder (3/3/0.5, then 5/5/1) on the 665-image bow fixture, judged by the scale oracle and component count, not by registration count. ~15 min/cell on that fixture. |
| **Q13** | Does `Brown3` + explicitly-loose accuracies alone repair the hull scale, i.e. was PD-6's repair really Division? | The isolating cell on zone_1: Brown3 + 10/10/1 + intact sidecars, position-only. ~70 minutes. Never run; the corrected config was adopted either way. |
| **Q14** | Do `-importTrajectory` and `-importFlightLog` hit the same implementation? | Run both on the smoke fixture with the same params XML; diff the resulting prior poses and the `20598 IMPORT_FLIGHT_LOG` process records. |
| **Q15** | Is the **grid** frame (`-renderMeshFromCustomGridPosition*`) offset from the **local Euclidean** frame (`-renderMeshFromCustomPosition*`), and by how much? This is the frame `xcr:Position` is reported in. | Render the same model from the same numeric position with both command pairs and compare; or place a single known point and read its coordinates in both. Directly relevant to Q9. |
| **Q16** | What are the legal values of `xcr:PosePrior`, `xcr:CalibrationPrior` and `xcr:Coordinates`? Only `"initial"`, `"initial"` and `"absolute"` are attested in the Help sample; this repo additionally writes and RealityScan accepts `Approximate` in the `Camera:CalibrationPrior` element form (§2.3). `05-metadata-xmp-and-sidecars.md` asserts the token set is `{initial, exact, locked}`; the string-table scan run here found all four of `initial`/`exact`/`locked`/`draft` present as bare words, which is far too weak to confirm anything (they are common English). | Export XMP at each of the four camera-export modes and diff the written `xcr:PosePrior` (same run as Q1). |
| **Q17** | Does `_common.xmp` work through the CLI, and does it lose to a per-image sidecar or win? | Drop a `_common.xmp` with a distinctive focal into the smoke fixture, add one per-image sidecar with a different focal, `-add` the folder, align, and read both cameras' solved focals. ~3 minutes. |
| **Q18** | Does `-setCamerasGravityDirection` work headless, and what `xcr:Gravity` format does it want? | Write `xcr:Gravity` into the smoke fixture's sidecars, align, `-setCamerasGravityDirection`, and check whether the component's up-axis moved. Never attempted here. |
| **Q19** | Is `inpAspect` the real aspect-ratio key? `tutorials/editselectioncommand` gives `inpSkew` for **both** Skew and Aspect ratio, which cannot both be right; `inpAspect` is present in the binary (confirmed this session by string extraction). | `-editInputSelection "inpAspect=1.5"` on one image, then export XMP and read `xcr:AspectRatio`. Seconds. |
| **Q21** | What is the grammar of a **Rig Definition XML** file (`Rig Setup Import` / `Import Rig Definition`, §3.1)? No rig schema ships in the install root, so unlike `flightlogs.xml` there is no template to copy. | Build a two-camera rig in the GUI's Rig Creation Wizard on the smoke fixture, export/save the rig definition, and read it. Then test whether the same file can be applied headless. ~10 minutes, needs the GUI once. |
| **Q22** | Does `xmpComponentMode` = **Rigid** ("scale of the camera group is fully determined") give a metric rig baseline that survives export/re-import? If so it is the missing answer to "no stereo-rig support" (§3.3). | Export a two-camera rig component with `xmpComponentMode` at Absolute and at Rigid, re-import each into a fresh scene, align, and compare the scale-oracle verdict. The key name is known; its accepted value encoding is not — recover it by GUI save-and-diff of `XMPExportParams.xml`. |
| **Q23** | Do the recovered `inpRig*` keys work through `-editInputSelection`, and what value grammar do they take? This is the only known headless route to a declared rig, since no CLI rig command exists. | On the smoke fixture: `-selectImage` one camera's images, `-editInputSelection "inpRigId={GUID}"`, `"inpRigIndex=0"`, `"inpRigInstance={GUID}"`, then `-exportXMP` and check whether `xcr:Rig*` attributes appear in the sidecars. Seconds per key; a rejected key raises `err:7155`-class parse noise, which is itself the answer. |
| **Q24** | **HIGHEST PRIORITY.** `ifUsePosAcc` / `ifUseOriAcc` do not exist in the binary (§9.3), so what actually decided whether the flight log's accuracy columns were consumed — and at what accuracy did every historical align really run? If `ifuuInh=0` means "use the global settings", and the globals were never applied either (§7.2), then every production align used 10/10/20 m + 10/10/10°, not the per-image columns. | Import the 120-image smoke fixture twice with a 13-column log carrying distinctive accuracies (say 0.01 m), once at `ifuuInh=0` and once at `ifuuInh=1`, then read `$(priorErrorX)`/`$(priorErrorY)`/`$(priorErrorZ)` per camera from an `-exportReport` template (§7.2). Whichever run reports 0.01 identifies the "from file" value. ~5 minutes, headless, no GUI. |
| **Q25** | Does a params-XML entry naming a **non-existent** key fail loudly or silently? Three of this repo's twelve `FlightLogParams.xml` entries name nothing; none of them ever produced an error. | Add `<entry key="thisKeyDoesNotExist" value="1"/>` to a params XML, run the import, and check `RS_CLI/Errors/errors.txt` and `RealityScan.log`. If it is silent — and the historical record says it is — then **no params XML in this repo has ever been validated**, and every one should be re-checked key-by-key against the binary's string table. Seconds. |
| **Q20** | Do GCPs / control points work through this CLI at all? `controlpoints.xml` / `groundcontrol.xml` have never been driven, and with no stereo-rig support they are the sanctioned route to rig scale. | Import three synthetic GCPs on the smoke fixture with `-importGroundControlPoints` + a GUI-saved params XML, align, and read the residuals. Untouched territory. |

## Addenda — reconciled from `FINDINGS.md`, 2026-09-05

Facts established after this document was written (2026-08-04), carried here so the manual stays the document of record. Each keeps the FINDINGS date as its citation; the raw entry has the full observation.

### A1. Manufacturer approximate intrinsics as priors COLLAPSE registration (ON2026 ladder)

Clean A/B/C ladder on a zone_1 copy, one variable per rung, explicit `-addImageWithCalibration` delivery, own cache: **A** control 3,528/3,626 = 97.3 % (1 component, residual median 4.54 cm); **B** groups-only XMPs (calibration/distortion groups 5/6, no values) 97.7 %, median 1.80 cm; **C** full manufacturer priors (focal35 24.2345, PPU/PPV, division, zero-pinned distortion, approximate) **45.4 %** — collapse, reproducing the original failed cell almost exactly, solved focal steered to the prior with wild outliers. The prior VALUES, not sidecar hygiene or cache concurrency, caused the 2026-08-08 collapse (2× replicated, two delivery mechanisms; mirrors NA167 #4 at far greater severity). Production stays calibration-prior-free; value-carrying flight-log calibration columns were downgraded for the same reason. Caveat on B: both A and B exported as ONE calibration group, so flight-log import auto-grouping (`ifKGrp`) appears to stomp prior groups and B's mechanism is unclear. [VERIFIED: FINDINGS 2026-08-09]

### A2. The 45° down-look belongs to the UPPER camera, not Cinema (rig correction 2026-08-14)

Owner: "upper is 45 degrees down, cinema and mid are pointed directly forward … how they were loaded on this cruise and NA165." The registry had `wca_cinema` at pitch 45 and the upper (`wca_starboard`) with no mount at all. Corrected: `wca_cinema` pitch 0; new family `wca_upper` (`^u\d+c`, the `U###C` stills) → starboard camera at pitch 45; `wca_port` (mid) 0 as before; lever arms untouched (validated figures). **Blast radius:** the NA156 H2023/H2024 WCA line was solved with cinema at 45 (the 43.11° Cinema median in §5 is that solve); the owner vouched for NA168 and NA165 only — reprocess NA156 under a cruise-scoped family rather than moving the row back. §10's mount table is corrected in place. [VERIFIED: FINDINGS 2026-08-14]
