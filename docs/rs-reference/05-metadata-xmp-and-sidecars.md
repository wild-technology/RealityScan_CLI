# Metadata, XMP sidecars, EXIF, calibration priors

This document covers everything RealityScan 2.2 reads from and writes to per-image
metadata: the `.xmp` sidecar naming contract, the complete `xcr:` attribute schema,
pose/calibration/lens prior semantics, the auto-import trap that silently contaminates
re-runs, the XMP export commands and their parameter keys, EXIF fields RealityScan
actually consumes, and the sensor database `sensorsdb.xml`. It does **not** cover flight
logs, coordinate systems, GCPs or scale (see `06-georeferencing-flightlogs-and-scale.md`),
the `sfm*` alignment keys that govern how priors are weighted (see `03-settings-keys.md`
and `07-alignment.md`), how images get into a scene at all (see
`04-image-input-and-handling.md`), the component/merge machinery that consumes the XMP
census (see `08-components-and-merge.md`), or the structure of `params.xml` files in
general (see `09-xml-parameter-files.md`). Command syntax and exit codes are in
`02-command-reference.md` and `01-cli-fundamentals.md`.

**Applies to:** RealityScan 2.2 (Epic Games), Windows, headless CLI operation.
**Tags:** [OFFICIAL] shipped Help · [VERIFIED] measured in production here ·
[CONTRADICTED] docs vs observation · [UNDOCUMENTED] · [INFERRED] · [OPEN]

Build under description: `RealityScan.exe` FileVersion `2.2.0.119430.RS`, ProductVersion
`2.2.0.119430`, 45,211,352 bytes, installed at
`C:\Program Files\Epic Games\RealityScan_2.2\`. Several facts below are established by
scanning that binary for both **single-byte ASCII** and **UTF-16LE** string literals
(re-measured 2026-08-04); those are tagged `[UNDOCUMENTED: RealityScan.exe string pool]`
and carry two standing caveats: the presence of a string proves the identifier exists in
the build, **not** that a given parser accepts it; and a *count* of a short string is
meaningless unless it is NUL-delimited, because it also matches inside longer words.
Counts quoted below are NUL-delimited unless stated otherwise.

---

## Contents

1. [The sidecar naming contract](#1-the-sidecar-naming-contract)
2. [Document structure and namespaces](#2-document-structure-and-namespaces)
3. [The complete `xcr:` attribute set](#3-the-complete-xcr-attribute-set)
4. [Value enumerations](#4-value-enumerations)
5. [Rotation and Position: conventions and frames](#5-rotation-and-position-conventions-and-frames)
6. [Prior semantics: what each mode actually fixes](#6-prior-semantics-what-each-mode-actually-fixes)
7. [Calibration groups and lens groups](#7-calibration-groups-and-lens-groups)
8. [The production calibration sidecar in this repo — and the doubt about it](#8-the-production-calibration-sidecar-in-this-repo--and-the-doubt-about-it)
9. [Exporting XMP](#9-exporting-xmp)
10. [The auto-import trap and the cleaning protocol](#10-the-auto-import-trap-and-the-cleaning-protocol)
11. [Measured effect of priors](#11-measured-effect-of-priors)
12. [EXIF handling](#12-exif-handling)
13. [The sensor database `sensorsdb.xml`](#13-the-sensor-database-sensorsdbxml)
14. [Undistortion and registration-export interactions](#14-undistortion-and-registration-export-interactions)
15. [Silent-failure catalogue](#15-silent-failure-catalogue)
16. [Runnable recipes](#16-runnable-recipes)
17. [Open questions](#open-questions)

---

## 1. The sidecar naming contract

### 1.1 `<stem>.xmp` and nothing else

An image and an XMP file of the **same base name** in the **same folder** are treated as
one input; everything in the XMP is assigned to the image on import.
[OFFICIAL: tools/xmpalign] The Help's own example: to attach metadata to `Image01.jpg`,
the file must be `Image01.xmp`.

| image file | sidecar RealityScan reads | sidecar RealityScan ignores |
|---|---|---|
| `C231C1034_20231104201530_edt.jpg` | `C231C1034_20231104201530_edt.xmp` | `C231C1034_20231104201530_edt.jpg.xmp` |

The binding is to the **stem alone, not the image extension** — Epic's reuse-alignment
tutorial says so explicitly, assuming that "the corresponding images from Images1 and
Images2 have the same names, but may differ in their extension" and copying one set of
`.xmp` files across. [OFFICIAL: tutorials/commandline_1] That is precisely why
`image.jpg.xmp` cannot work: its stem is `image.jpg`, and no image is named `image.jpg.jpg`.

**`image.jpg.xmp` is ignored SILENTLY — no warning, no log line, no error code.**
[VERIFIED: NA167 #3 / B7, 2026-07-22] This is a real and expensive bug class, not a
theoretical one: an image batcher in this repo wrote sidecars as
`f"{image_filename}.xmp"`, so **every calibration prior written before 2026-07-22 was
never loaded by any run.** The defect was invisible for months because nothing fails —
alignment simply proceeds without the priors. It was finally caught by an *arithmetic
anomaly in a file count*: after aligning zone_13, 871 "new" `.xmp` files appeared in a
folder that already contained 904 of them. Those 904 were the never-read `*.jpg.xmp`
priors; the 871 were RealityScan's own stem-named pose exports.

Detection rule for any pipeline: **`count(*.xmp) == count(images)` is the invariant.**
A folder holding both naming forms will show roughly 2× the image count.

```bat
:: Audit of a batched zone tree (Windows PowerShell 5.1). Run-verified 2026-08-04
:: on a fixture of a.jpg b.jpg a.xmp b.jpg.xmp -> "images=2 xmp=2 doubleext=1".
powershell -NoProfile -Command ^
  "$r='F:\na156_h2024\batched_images_by_zone\zone_1'; " ^
  "$f=@(Get-ChildItem -LiteralPath $r -Recurse -File); " ^
  "$img=$f.Where({ $_.Extension -in '.jpg','.jpeg','.png' }).Count; " ^
  "$xmp=$f.Where({ $_.Extension -eq '.xmp' }).Count; " ^
  "$bad=$f.Where({ $_.Name -like '*.*.xmp' }).Count; " ^
  "Write-Output \"images=$img xmp=$xmp doubleext=$bad\""
```

**Three cmd/PowerShell traps are already defused in that snippet; a naive version of it
lies to you.** All three run-verified 2026-08-04:

| trap | what happens | fix used above |
|---|---|---|
| `Get-ChildItem -LiteralPath <dir> -Recurse -Include *.jpg` | `-Include` is **silently ignored** when the path carries no wildcard: on the 4-file fixture it returned **5** (every file plus the directory) instead of 2. And `-LiteralPath "$r\*"` cannot fix it — `-LiteralPath` does not expand wildcards, so it errors with `Cannot find path …\*`. | `-File`, then filter on `.Extension` |
| `^` used to continue a line **inside** a quoted string | the caret is passed through verbatim to the child process (`SyntaxError: invalid syntax` from Python; a PowerShell parser error) | carets only ever appear **after** the closing quote |
| `^|` inside a quoted argument | cmd does not treat `\|` as special inside quotes, so the caret survives and PowerShell reports `Unexpected token '^'` | use `.Where({…})` and avoid the pipe entirely |

`-Filter` *is* reliable here: `-Filter *.xmp` and `-Filter *.*.xmp` both returned the right
counts on the fixture. `-Include` is the broken one.

Note the second trap in that snippet: `Get-ChildItem -Recurse` in Windows PowerShell 5.1
does **not** descend into the children of a directory junction, so a zone tree assembled
out of junctions reports `0` sidecars while Python's `os.walk` over the same path reports
all of them (0 vs 9,835 on the same tree). [VERIFIED: FINDINGS 2026-07-27] The decisive
detail is **where enumeration starts**: PowerShell *does* resolve a junction it is pointed
at directly, so `AlignZone.bat` — handed the zone folder itself — enumerated correctly,
while `MergeZoneComponents.bat` — handed the *parent* of the zone folders — saw the
junctions as children and skipped them. Same tree, same tool, opposite outcome.
[VERIFIED: FINDINGS 2026-07-27] See §9.5 and §15.

### 1.2 `_common.xmp` — folder-wide defaults

A single file named `_common.xmp` placed in the image folder applies the same XMP
information to **all** images in that folder. [OFFICIAL: tools/xmpalign, "TIP"] The
literal string `_common.xmp` is present in `RealityScan.exe` (UTF-16LE, one occurrence, in
a filename/mask run reading `… .imagelist | *.* | _common.xmp | .rclicense | …`),
confirming it is a real compiled-in filename and not a doc artifact.
[UNDOCUMENTED: RealityScan.exe string pool]

The Help does not state the precedence rule when both `_common.xmp` and `<stem>.xmp`
exist, nor whether `_common.xmp` recurses into subfolders.
[OPEN — see [Open questions](#open-questions), Q1/Q2]

Practical use: a rig with per-camera subfolders can carry one `_common.xmp` per camera
folder instead of one sidecar per image. For the four-camera rig this repo drives, that
would be 4 files instead of 9,835. It has never been exercised here.

```
F:\na156_h2024\batched_images_by_zone\zone_1\
    cinema\   _common.xmp        <- calibration group 3, focal 16.0
    port\     _common.xmp        <- calibration group 2, focal 16.0
```

### 1.3 `-addImageWithCalibration` — decoupled naming

```bat
RealityScan.exe -delegateTo RS1 -addImageWithCalibration ^
  "F:\images\C231C1034_20231104201530_edt.jpg" ^
  "F:\priors\cinema_group3.xmp"
```

Imports one image plus one XMP; the two files need **not** share a name or a folder. Use
whole paths for both. [OFFICIAL: appbasics/allcommands; tools/xmpalign] This is the only
mechanism that breaks the name/location coupling, and it is the correct answer when
priors must live outside a read-only or hard-linked image tree.

Cost note: it is one command per image. At 8,000+ images that is 8,000 delegated
commands; the repo has never used it and has no timing for it.
[OPEN — Q3]

### 1.4 Auto-import on every add

`-add`, `-addFolder` and (by construction) `-addImageWithCalibration` all consume the
sidecar. The critical, undocumented consequence: **any `<stem>.xmp` sitting beside an
image at add time becomes a prior, including pose priors left behind by an earlier
export.** [VERIFIED: NA167 B7, 2026-07-22] See §10 for the full trap and the cleaning
protocol.

---

## 2. Document structure and namespaces

### 2.1 The canonical sample

Reproduced from the shipped Help, which is the only official statement of the schema
[OFFICIAL: tools/xmpalign]:

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

### 2.2 Namespaces and the parse path

| prefix | URI | source |
|---|---|---|
| `x` | `adobe:ns:meta/` | [OFFICIAL: tools/xmpalign] + present in binary |
| `rdf` | `http://www.w3.org/1999/02/22-rdf-syntax-ns#` | [OFFICIAL] |
| `xcr` | `http://www.capturingreality.com/ns/xcr/1.1#` | [OFFICIAL] |

`http://www.capturingreality.com/ns/xcr/1.1#` is **the only** `capturingreality.com/ns/…`
URI present anywhere in `RealityScan.exe` — one occurrence, ASCII, zero in UTF-16LE. In
particular there is **no** `.../ns/xcr/1.0/` and **no** `.../ns/camera/1.0/`.
[UNDOCUMENTED: RealityScan.exe string pool] Honest caveat: that single occurrence sits in
the *licence-certificate* writer's string group (beside `<certificates>`, `xmlns:xcr` and
`<xcr:Cert id="%s">`, see §3), not in a distinct XMP-sidecar string group — the same URI
constant is evidently shared. The Help sample is what fixes it for sidecars
[OFFICIAL: tools/xmpalign]; the binary only establishes that no *other* xcr URI exists.

The binary also contains the literal element path `x:xmpmeta\rdf:RDF\rdf:Description`
(ASCII, immediately adjacent to the XMP value-token pool of §4), which is the reader's
navigation target: RealityScan looks for its attributes on the `rdf:Description` element
beneath `x:xmpmeta/rdf:RDF`. [UNDOCUMENTED: RealityScan.exe string pool]

Note that the URI ends in `#`, not `/`. Anything a producer writes bound to a different
URI is, under any conforming XMP/RDF parser, a *different* property.

### 2.3 Attribute form vs element form

Everything except `Position` appears as an **attribute** on `rdf:Description` in Epic's
sample and in RealityScan's own writer. `Position` is written as a **child element**:

```xml
<xcr:Position>0.262424 -2.263975 7.038790</xcr:Position>
```

However, **older exports of this same product wrote `xcr:Position` as an attribute**
(`xcr:Position="x y z"`), so any parser that must read historical sidecars has to accept
both forms. [VERIFIED: FINDINGS 2026-07-28] This bit an in-repo scale oracle; the fix is
the alternation used in `modules/scale_oracle.py`:

```python
POS_RE = re.compile(r'<xcr:Position>([^<]+)</xcr:Position>|xcr:Position="([^"]+)"')
```

`poses2flightlog.py` has **not** been given the alternation — its
`POSITION_RE = re.compile(r'<xcr:Position>([^<]+)</xcr:Position>')` matches element form
only, so it silently sees zero cameras in a directory of legacy attribute-form sidecars
and exits on the `MIN_CAMERAS = 3` guard.
[VERIFIED-by-inspection: poses2flightlog.py, 2026-08-04]

#### [CONTRADICTED 2026-08-23] RealityScan 2.2 writes `xcr:Rotation` as an ELEMENT too

The rule above — "everything except `Position` is an attribute" — holds for Epic's sample
(`xcr:Version="3"`), but **not** for what RealityScan 2.2.0.119430 actually writes.
Sidecars produced by `-exportXMP` in 15 arms of a 2026-08-23 session are
`xcr:Version="4"` and put **both** `Position` and `Rotation` in element form:

```xml
<rdf:Description xmlns:xcr="..." xcr:Version="4" xcr:ExportCoordinateSystemType="3"
    xcr:PosePrior="initial" xcr:Coordinates="absolute" xcr:DistortionModel="perspective"
    xcr:FocalLength35mm="16.5836" ...>
  <xcr:Position>0.440450977 -1.629441201 -0.349711727</xcr:Position>
  <xcr:Rotation>-0.536007698 -0.843529554 ... -0.995891934</xcr:Rotation>
</rdf:Description>
```

A parser that expects `xcr:Rotation="..."` as an attribute therefore reads **zero
rotations** from current sidecars, the same class of silent-zero bug §2.3 already records
for `Position` in `poses2flightlog.py`. The safe alternation for both:

```python
POS_RE = re.compile(r'<xcr:Position>([^<]+)</xcr:Position>|xcr:Position="([^"]+)"')
ROT_RE = re.compile(r'<xcr:Rotation>([^<]+)</xcr:Rotation>|xcr:Rotation="([^"]+)"')
```

[VERIFIED: onr2 arms A_opk / L_all_levers / E_overlap_high, sidecars written by
RealityScan with no input sidecar present, 2026-08-23]

#### [Q4 — PARTIALLY ANSWERED 2026-08-23] the reader DOES accept attribute form for `Rotation`

Q4 asked whether the *reader* accepts element form for attributes other than `Position`.
The converse direction is now settled for `Rotation`: sidecars written by hand with
`xcr:Rotation="r00 r01 ... r22"` as an **attribute** and `<xcr:Position>` as an **element**
were parsed correctly — RealityScan built a single 392-camera component from them and
echoed the rotations back unchanged to twelve decimal places. So the reader is tolerant of
attribute-form `Rotation` even though its own writer uses element form.

Still open: element form for the *other* attributes (`FocalLength35mm`, `CalibrationGroup`,
…), which was not exercised — every sidecar in that session wrote those as attributes.
[VERIFIED for `Rotation`: onr2 arm N_colmap_locked, 2026-08-23] [OPEN — Q4, remainder]

#### [VERIFIED 2026-08-23] a rewritten sidecar comes back in a different form than it went in

When RealityScan re-exports over a sidecar that was supplied to it, the forms are not
preserved: input `<xcr:Position>` element + `xcr:Rotation` attribute came back as
`xcr:Position` **attribute** + `<xcr:Rotation>` **element**. Do not assume a round-trip
preserves shape — only values. Values themselves survived bit-for-bit
(`Position`, `Rotation`, `FocalLength35mm`), while `CalibrationGroup` and
`DistortionGroup` were reset to `-1` and `DistortionModel` to `perspective` despite a
global `sfmDistortionModel=Brown3`.

### 2.4 Encoding

The Help sample carries no XML declaration. The sidecars this repo writes begin with
`<?xml version="1.0" encoding="UTF-8"?>` and are written UTF-8 **without BOM**
(`open(..., 'w', encoding='utf-8')` in `modules/camera_registry.py`). No BOM-related
sidecar failure has been observed — but a BOM on line 1 of a `.complist` **does** silently
invalidate the first entry, and Windows PowerShell 5.1's `Set-Content -Encoding utf8`
emits one, so never author sidecars with `Set-Content -Encoding utf8`.
[VERIFIED: FINDINGS 2026-07-27] Use
`[System.IO.File]::WriteAllLines($p,$lines,(New-Object System.Text.UTF8Encoding($false)))`
if PowerShell must write them.

---

## 3. The complete `xcr:` attribute set

The table below is the **union** of (a) Epic's sample, (b) the `xcr:`-prefixed identifier
table extracted from `RealityScan.exe`, and (c) attributes referenced elsewhere in the
Help. The binary holds **29** distinct `xcr:` identifiers in total. **26** of them form one
contiguous, NUL-separated ASCII pool — the XMP reader/writer name table — verbatim in
order (each also present once as UTF-16LE):

```
xcr:Rig  xcr:Version  xcr:RigPoseIndex  xcr:RigInstance  xcr:InMeshing  xcr:InTexturing
xcr:ComponentId  xcr:PosePrior  xcr:Rotation  xcr:Coordinates  xcr:DistortionModel
xcr:Position  xcr:FocalLength35mm  xcr:DistortionCoeficients  xcr:AspectRatio  xcr:Skew
xcr:PrincipalPointV  xcr:PrincipalPointU  xcr:CalibrationGroup  xcr:CalibrationPrior
xcr:ExportCoordinateSystemType  xcr:DistortionGroup  xcr:longitude  xcr:latitude
xcr:altitude  xcr:version
```

The other three — `xcr:Gravity`, `xcr:InColoring` (both UTF-16LE only) and `xcr:Cert`
(ASCII only, 4 occurrences) — live elsewhere in the binary and are **not** members of that
pool. [UNDOCUMENTED: RealityScan.exe string pool]

Immediately adjacent to the reader's navigation string `x:xmpmeta\rdf:RDF\rdf:Description`
is a second contiguous ASCII pool holding the XMP **value** tokens, in order:

```
perspective  brown4  brown3t2  division  brown3  rationalP2D1T2
[x:xmpmeta\rdf:RDF\rdf:Description]  brown4t2  rationalP2D1
relative  rigid  locked  absolute
```

That is the whole XMP value vocabulary the writer can emit for `xcr:DistortionModel`
(8 tokens, §4.3) and `xcr:Coordinates` (`relative` / `rigid` / `absolute`), plus `locked`
for the prior fields. `initial` and `exact` are a separate adjacent pair in the
project-XML serializer's pool (§4.1). [UNDOCUMENTED: RealityScan.exe string pool]

| Attribute (exact spelling) | Form | Type / shape | Meaning | Source |
|---|---|---|---|---|
| `xcr:Version` | attr | int; `3` observed | Sidecar schema version. Both `xcr:Version` and `xcr:version` exist in the binary; only the capitalised form appears in Epic's sample. | [OFFICIAL: tools/xmpalign] + [UNDOCUMENTED: binary] |
| `xcr:PosePrior` | attr | enum `initial` \| `exact` \| `locked` | How hard the pose in this file constrains alignment. See §4.1 and §6. | [OFFICIAL: sample value `initial`]; enum [INFERRED] |
| `xcr:Coordinates` | attr | enum `absolute` \| `relative` \| `rigid` | Whether `Position`/`Rotation` are in the scene's absolute (project/geo) frame or in a rig-relative frame. | `absolute` [OFFICIAL: sample]; `relative`/`rigid` [UNDOCUMENTED: binary value pool] |
| `xcr:Rotation` | attr | 9 space-separated floats — 3×3 matrix | Camera orientation. Row-major, world→camera by strong analogy with the shipped export templates; see §5.1. | [OFFICIAL: sample]; convention [INFERRED], §5.1 |
| `xcr:Position` | **element** (attr in legacy files) | 3 space-separated floats | Camera position. In exports from this pipeline it is a **grid-anchored local Euclidean frame, not UTM**. See §5.2. | [OFFICIAL: sample]; frame [VERIFIED: NA167_SESSION_NOTES §1, poses2flightlog.py] |
| `xcr:DistortionModel` | attr | enum, lowercase; 8 tokens: `perspective` `division` `brown3` `brown3t2` `brown4` `brown4t2` `rationalP2D1` `rationalP2D1T2` | Lens distortion model for this camera. **In practice the global `sfmDistortionModel` key owns the model — see §7.5.** | `division` [OFFICIAL: sample]; full token set [UNDOCUMENTED: binary value pool]; override [CONTRADICTED], §7.5 |
| `xcr:DistortionCoeficients` | attr | 6 space-separated floats | Distortion coefficients. **Note Epic's misspelling — one `f`. Reproduce it exactly** (the correctly spelled `DistortionCoefficients` occurs nowhere in the binary). Slot order almost certainly `k1 k2 k3 k4 t1 t2`; see §4.3a. | [OFFICIAL: sample]; order [INFERRED from shipped `calibration.xml`], §4.3a |
| `xcr:FocalLength35mm` | attr | float, mm | 35 mm-equivalent focal length prior. | [OFFICIAL: sample] |
| `xcr:Skew` | attr | float; `0` typical | Image-plane skew. Only optimised under the `Kplus…` distortion models. | [OFFICIAL: sample] + [OFFICIAL: appbasics/settings_distortion_models] |
| `xcr:AspectRatio` | attr | float; `1` typical | Pixel aspect ratio. Only optimised under `Kplus…` models. | same |
| `xcr:PrincipalPointU` | attr | float, **normalised**, not mm — the Help's GUI label disagrees, see §4.4 | Principal point x offset from image centre. | [OFFICIAL: sample]; units [CONTRADICTED], §4.4 |
| `xcr:PrincipalPointV` | attr | float, **normalised** | Principal point y offset from image centre. | same |
| `xcr:CalibrationPrior` | attr | enum `initial` \| `exact` (\| `locked`) | Hardness of the intrinsic-calibration prior; maps to the GUI's Unknown/Approximate/Fixed. | [OFFICIAL: sample value `initial`]; mapping [INFERRED], §4.2 |
| ~~`FocalPrior`, `PrincipalPrior`, `SkewPrior`, `AspectRatioPrior`, `DistortionPrior`~~ | — | — | **NOT XMP attributes — listed here so they are not mistaken for some.** They exist in the binary **without any `xcr:` prefix**, inside the `.rsproj` `<input>` serializer's format strings (` FocalLength35mm="%f" FocalPrior="%s"`, ` PrincipalPointU="%f" PrincipalPointV="%f" PrincipalPrior="%s"`, ` Skew="%f" SkewPrior="%s"`, ` AspectRatio="%f" AspectRatioPrior="%s"`, ` DistortionModel="%s" DistortionCoeficients="%f %f %f %f %f %f" DistortionPrior="%s"`). That pool also holds `calibrationGroup`, `distortionGroup`, `rigId`, `rigInstance`, `rigCameraIndex`, `absX/absY/absZ`, `absRX/absRY/absRZ`, `absuX…`, `insOfsX…`, `absPrior`, `relPrior`, `absCs`, `relCs`, `relGroup`, `xmpPath`, `width`, `height`. Project-file attributes, not sidecar ones. | [UNDOCUMENTED: RealityScan.exe string pool] |
| `xcr:CalibrationGroup` | attr | int; `-1` = ungrouped | Images sharing a value >= 0 share one set of intrinsics after alignment. | [OFFICIAL: sample] + [OFFICIAL: appbasics/camerasettings] |
| `xcr:DistortionGroup` | attr | int; `-1` = ungrouped | Images sharing a value >= 0 share one set of lens-distortion parameters. | [OFFICIAL: sample] |
| `xcr:Rig` | attr | GUID `{…}` | Rig identity. | [OFFICIAL: sample] |
| `xcr:RigInstance` | attr | GUID `{…}` | One firing/station of the rig. | [OFFICIAL: sample] |
| `xcr:RigPoseIndex` | attr | int | Which camera slot within the rig this image is. | [OFFICIAL: sample] |
| `xcr:InTexturing` | attr | `0` \| `1` | Include this image in texturing/coloring. Written when "Include editor options" is enabled on export. | [OFFICIAL: sample + tools/xmpalign] |
| `xcr:InMeshing` | attr | `0` \| `1` | Include this image in meshing. | same |
| `xcr:InColoring` | attr | `0` \| `1` | Include this image in coloring. Present in the binary but absent from Epic's sample and from the reader/writer name pool. | [UNDOCUMENTED: binary] |
| `xcr:ComponentId` | attr | id/GUID | Which component the exported pose belongs to. Not in Epic's sample. | [UNDOCUMENTED: binary] |
| `xcr:ExportCoordinateSystemType` | attr | string | CRS label the export was written in (mirrors the export dialog's "Coordinate system"). Not in Epic's sample. | [UNDOCUMENTED: binary] |
| `xcr:Gravity` | attr | 3 floats (vector) | Gravity direction. **Consumed by `-setCamerasGravityDirection [componentID]`: the component is rotated so the `-z` vector follows the gravity vector. Sparse cloud only — the mesh is not affected.** | [OFFICIAL: appbasics/allcommands, tutorials/commandline_1] |
| `xcr:latitude`, `xcr:longitude`, `xcr:altitude` | attr | — | Geographic position fields. **Observed to be garbage in this pipeline's exports** — the useful position is `xcr:Position` in the local frame. | [UNDOCUMENTED: binary]; garbage [VERIFIED: poses2flightlog.py docstring, zone_9] |
| `xcr:Cert` | **element** | `<xcr:Cert id="%s">…</xcr:Cert>` | **Nothing to do with image sidecars.** It is the licence-certificate element: the binary carries the writer strings `<certificates>`, `xmlns:xcr`, `<xcr:Cert id="%s">`, `</xcr:Cert>`, `</certificates>`, adjacent to `importLicense` / `exportLicense` / `"certificate file"` / `certificates\`. Never write it into an image XMP. | [UNDOCUMENTED: RealityScan.exe string pool, resolved 2026-08-04] |

### 3.1 Names that are NOT in the schema

The following occur **zero** times in `RealityScan.exe` — scanned as both single-byte ASCII
and UTF-16LE, with and without a prefix:

| absent string | occurrences (ASCII, UTF-16LE) |
|---|---|
| `LensDistortionGroup` | 0, 0 |
| `LensDistortionPrior` | 0, 0 |
| `DistortionCoefficients` (correctly spelled) | 0, 0 |
| `http://www.capturingreality.com/ns/camera/1.0/` | 0, 0 |
| `http://www.capturingreality.com/ns/xcr/1.0/` | 0, 0 |
| any identifier matching `Camera:[A-Za-z0-9]+` | 0, 0 |

For contrast, `DistortionCoeficients` (Epic's spelling) occurs 3× ASCII + 1× UTF-16LE.
[UNDOCUMENTED: RealityScan.exe string pool, measured 2026-08-04] This is load-bearing for
§8.

---

## 4. Value enumerations

### 4.1 `xcr:PosePrior`

| value | Meaning (Help, XMP export dialog wording) |
|---|---|
| `initial` | **draft** — absolute camera positions are used but *are adjusted* during alignment. |
| `exact` | camera **relative** positions are preserved; suitable when spatial relationships between cameras must be kept. |
| `locked` | both relative and absolute positions preserved; positions are **fixed and not adjusted** during alignment. |

The three GUI export modes are literally named "Export as draft", "Export as exact",
"Export as locked". [OFFICIAL: tools/xmpalign]

What the binary actually supports for these three words, measured as NUL-delimited ASCII
C strings [UNDOCUMENTED: RealityScan.exe string pool, 2026-08-04]:

| token | where it sits | reading |
|---|---|---|
| `locked` | in the XMP value pool, beside `relative` / `rigid` / `absolute` (§3) | an XMP-writer token |
| `initial`, `exact` | an adjacent pair in the `.rsproj` `<input>` serializer's pool, beside `FocalPrior` / `PrincipalPrior` / `absPrior` and the pose words `pose` `oriented` `registered` `fixed` `disabled` | the prior-hardness vocabulary shared by the project file and (per Epic's sample) the XMP |
| `draft` | one occurrence, in an unrelated part of the binary | **not** an XMP token |

So the XMP prior vocabulary is `{initial, exact, locked}` and the mapping draft→`initial`
is [INFERRED] — Epic's sample uses `initial` for a pose that is "subject to adjustment",
which is exactly the draft semantics, and no `draft` token exists in the XMP pools.

Corroborating: the Selected Input panel documents a "Relative coordinates" field that is
visible "only for the inputs that are connected in a rig (e.g. individual `.lsp` files in
one LiDAR scanner position, **or images with exact or locked XMP files**)".
[OFFICIAL: appbasics/selectedinputs] So `exact`/`locked` sidecars promote a set of images
into a rig-like relative-pose relationship; `initial` does not.

### 4.2 `xcr:CalibrationPrior` and the GUI's Unknown / Approximate / Fixed

The Selected Input panel exposes three levels for both Prior Calibration and Prior Lens
Distortion [OFFICIAL: appbasics/camerasettings_priors, appbasics/selectedinputs]:

| GUI level | Meaning | `-editInputSelection` value | probable XMP token |
|---|---|---|---|
| Unknown | prior values missing or not applied; RealityScan calculates them | `inpCalibration=0` / `inpDistortion=0` | *(attribute omitted)* [INFERRED] |
| Approximate | starting values known, **will be adjusted** during processing | `inpCalibration=1` / `inpDistortion=1` | `initial` [INFERRED] |
| Fixed | values known and **will not be changed** | `inpCalibration=2` / `inpDistortion=2` | `exact` [INFERRED] |

`Approximate` occurs **exactly once** in `RealityScan.exe`, inside a UTF-16LE UI label run
that reads `… Unknown | Approximate | Fixed | No lens distortion | Division | Brown3 |
Brown4 | Brown3 with tangential distortion | Brown4 …` — i.e. it is the dropdown caption,
sitting next to the other dropdown captions, not a serialisation token. Lowercase
`approximate` occurs once and only as the tail of the English word "approximately" in an
unrelated progress message. Neither appears in the XMP value pool or the project-XML prior
pool (§4.1). [UNDOCUMENTED: RealityScan.exe string pool, measured 2026-08-04] Do **not**
write `Approximate` as an XMP value on this evidence. [OPEN — Q6]

**Critical and counter-intuitive:** the default lens-distortion state is model *"No lens
distortion"* with prior *"Approximate"*, which means **RealityScan actively searches for a
near-zero-distortion solution** — wrong for any visibly distorted optic. The documented
remedies are to supply real coefficients or to set the lens prior to **Unknown**.
[OFFICIAL: appbasics/camerasettings_priors; appbasics/selectedinputs]

However — and this is a repo finding that supersedes an earlier caution in the same
session — **`Approximate` with NO coefficients supplied does not pin distortion to zero in
practice.** The Cinema camera carried exactly that state and still solved
k1 = −0.0524 over 2,204 cameras. `Unknown` merely withholds a hint.
[VERIFIED: FINDINGS 2026-07-25] [SUPERSEDED: the earlier claim that `Approximate` asserts
approximately-zero distortion]

### 4.3 `xcr:DistortionModel` — four different spellings of the same models

**RealityScan spells its distortion models four different ways depending on the interface.
Do not interchange them.**

**(1) XMP `xcr:DistortionModel` — lowercase, 8 tokens**, taken verbatim from the writer's
value pool (§3) [UNDOCUMENTED: RealityScan.exe string pool]; `division` is the one Epic's
sample shows [OFFICIAL: tools/xmpalign]:

| XMP token | corresponds to |
|---|---|
| `perspective` | "No lens distortion" |
| `division` | Division |
| `brown3` | Brown3 |
| `brown3t2` | Brown3 with tangential2 |
| `brown4` | Brown4 |
| `brown4t2` | Brown4 with tangential2 |
| `rationalP2D1` | rational model — **no** GUI, `-set` or `-editInputSelection` exposure anywhere in the Help; reachable, if at all, only through XMP. Never tried here |
| `rationalP2D1T2` | ditto, with tangential2 |

The correspondence column is [INFERRED] from the names; only `division` is confirmed by a
document. Note two structural facts that fall out of the list: there is **no XMP token for
the `K+` variants** (consistent with `K+` being an optimise-skew-and-aspect flag on top of
a Brown model rather than a distinct model), and there are **two rational models with no
documented interface at all**. [UNDOCUMENTED: binary value pool]

**(2) The global setting `sfmDistortionModel` — capitalised, 7 values.** Both the Help and
the binary's enum pool (`Division | Brown3 | Brown4 | Brown3WithTangential2 |
Brown4WithTangential2 | KplusBrown3WithTangential2 | KplusBrown4WithTangential2`, one
contiguous UTF-16LE run) agree exactly:

| `sfmDistortionModel` value | Coefficients | Notes |
|---|---|---|
| `Division` | single parameter | covers simple distortion **and fish-eye optics**; the only model the Help endorses for >= 180° |
| `Brown3` | 3 radial | **application default**; polynomial radial, works for optics under 180° |
| `Brown4` | 4 radial | different distortion at centre vs border |
| `Brown3WithTangential2` | 3 radial + 2 tangential | tangential compensates lens offset |
| `Brown4WithTangential2` | 4 radial + 2 tangential | |
| `KplusBrown3WithTangential2` | + Skew, Aspect | `K+` variants also optimise skew and aspect ratio; without `K+` RealityScan assumes skew 0, aspect 1 |
| `KplusBrown4WithTangential2` | + Skew, Aspect | |

Default `Brown3`. [OFFICIAL: appbasics/settings_distortion_models for the descriptions;
tutorials/setkeyvaluetable for the key, type and default] The seven literal spellings are
independently confirmed as one contiguous UTF-16LE run in the binary.
[UNDOCUMENTED: RealityScan.exe string pool, 2026-08-04]

**(3) `-editInputSelection "inpDistortionModel=<n>"` — integers 0–5:**
`0` No lens distortion, `1` Division, `2` Brown3, `3` Brown4, `4` Brown3 with tangential
distortion, `5` Brown4 with tangential distortion.
[OFFICIAL: tutorials/editselectioncommand] Note there is no `K+` option in the per-image
key — `K+` is global-only.

**(4) The camera DB (`sensorsdb.xml`) `<lens type="…">`:** the parser's own string pool —
a contiguous ASCII run reading `cameras | ignore | /cameras | GPSAccuracy | ccdWidth |
brownr4t2 | brownr4 | orientationAccuracy | /camera | GPSMode | brownr3 | lens |
brownr3t2 | brown | focus | /lens | distance` — supplies `brown`, `brownr3`, `brownr3t2`,
`brownr4`, `brownr4t2`. [UNDOCUMENTED: RealityScan.exe string pool] `division` is not in
that run (it lives in the XMP value pool) but is the value every `<lens>` in the shipped
`sensorsdb.xml` uses, so it is certainly accepted.
[VERIFIED-by-inspection of the shipped file, 2026-08-04]

### 4.3a Coefficient slot order in `xcr:DistortionCoeficients`

`xcr:DistortionCoeficients` carries **six** floats regardless of model (Epic's sample:
`"0 0 0 0 0 0"`). The Help never states the slot order, but three shipped export templates
in `C:\Program Files\Epic Games\RealityScan_2.2\calibration.xml` do, and they agree:

| format id / desc | emits | order |
|---|---|---|
| `{0CA18733-1EBC-4254-9974-17197EB409BD}` "Internal/External Camera Parameters" | header `#name,x,y,alt,yaw,pitch,roll,f_35mm,px_norm,py_norm,k1,k2,k3,k4,t1,t2` | **`k1 k2 k3 k4 t1 t2`** |
| `{93B7C9C6-2D00-4A4F-B3E7-FBFBFF5C2895}` "Maya 2013 ASCII Scene" | `setAttr -k on ".lensDistortion" -type doubleArray 6 $(k1) $(k2) $(k3) $(k4) $(t1) $(t2);` | **`k1 k2 k3 k4 t1 t2`** |
| `{B5331837-609D-4B12-A931-2863653d19F7}` "OpenCV-compliant Internal/External Camera Parameters" | `…,k1,k2,t2,t1,k3,k4`, header note "Brown lens distortion model coefficients provided in OpenCV ordering" | permuted **for OpenCV**, which is the point |

[OFFICIAL: shipped `calibration.xml`] The native six-slot order is therefore
`k1 k2 k3 k4 t1 t2`, exactly six slots, exactly the width of
`xcr:DistortionCoeficients`. That the XMP attribute uses the *same* order is [INFERRED] —
strongly, but no document says so and no probe here has read a sidecar with non-zero
tangential terms. [OPEN — Q7]

### 4.4 `PrincipalPointU/V` units

**[CONTRADICTED — the Help's GUI label says millimetres, the shipped export templates say
normalised.]**

- **Docs claim:** the Selected Input panel labels the fields "Principal point x **[mm]**"
  / "Principal point y [mm]", "the position of the center of projection on the x axis in
  millimetres"; `-editInputSelection` documents the same keys as
  `inpPPX` / `inpPPY` "Principal point x [mm]".
  [OFFICIAL: appbasics/camerasettings_priors, appbasics/selectedinputs,
  tutorials/editselectioncommand]
- **Shipped templates say otherwise.** In `calibration.xml` the "Internal/External Camera
  Parameters" format `{0CA18733-1EBC-4254-9974-17197EB409BD}` names its columns
  `f_35mm,px_norm,py_norm` and fills them with `$(f*36)`, `$(px)`, `$(py)` — i.e. the
  internal `f` is normalised such that `f*36` is the 35 mm-equivalent millimetre value,
  and `px`/`py` are written **raw** under a column literally named `_norm`. The OpenCV and
  Radiance-Fields templates convert the same variables to pixels with
  `$(px*scale+width*0.5)` / `$(py*scale+height*0.5)`, using the *same* `scale` that turns
  `f` into pixels (`$(f*scale)`). Both are only consistent if `px`/`py` are normalised in
  the same units as `f`. [OFFICIAL: shipped `calibration.xml`]
- **Measured here, consistent with normalised:** cinema median `(−0.0071, −0.0031)`, port
  `(+0.0027, +0.0056)` over 5,050 harvest records
  [VERIFIED: FINDINGS 2026-07-26]. As millimetres on a 36 mm frame that would be a
  7-micron principal-point offset holding across 5,050 independently solved cameras —
  implausible. As a fraction of frame width it is a 0.7 % offset, which is ordinary.

Treat the "[mm]" label as applying to the GUI field's *presentation* and the XMP / export
value as normalised. What is still unproven is only the arithmetic bridge — whether the
GUI divides by 36, and whether `scale` is image width or the larger image dimension.
[OPEN — Q8]

---

## 5. Rotation and Position: conventions and frames

### 5.1 `xcr:Rotation`

Nine floats. The Help gives one example, `"-1 0 0 0 0 -1 0 -1 0"`, and says nothing about
row/column order, handedness, or whether it is world→camera or camera→world.

What can be said with a source:

- The shipped `calibration.xml` export template for **OpenCV-compliant
  Internal/External Camera Parameters** documents its own matrix explicitly: *"R = [Rij]
  provided in row major ordering and t = (tx,ty,tz) are the rotation matrix R and the
  translation vector t of the pose (R,t) of the camera"*. That is a world→camera pose in
  row-major order. [OFFICIAL: shipped `calibration.xml`, format
  `{B5331837-609D-4B12-A931-2863653d19F7}`]
- The **Boujou** template restates it independently: *"Camera Rotation Matrix (9 numbers -
  1st row, 2nd row, 3rd row)"* followed by *"rotation applied before translation"*, then
  emits `$(R00) $(R01) $(R02) $(R10) … $(R22) $(tx) $(ty) $(tz)`.
  [OFFICIAL: shipped `calibration.xml`, format `{700E6EE9-C942-41E8-A624-E97BAE13CEA0}`]
- The **CmpMvs `_P` matrices** template is decisive about the direction, because it builds
  a projection matrix in closed form: row 0 is
  `R00*f*scale + R20*(px*scale+0.5*width)`, …, row 2 is `R20 R21 R22 tz` — literally
  `P = K·[R|t]`. A projection matrix maps *world* points to image points, so `R,t` is the
  world→camera pose and `R` is indexed row-major.
  [OFFICIAL: shipped `calibration.xml`, format `{2155D4AC-11BA-421F-8BE8-385EA329EF3B}`]
- Epic's XMP sample matrix `"-1 0 0 0 0 -1 0 -1 0"` is a **proper rotation** — read
  row-major its rows are (−1,0,0), (0,0,−1), (0,−1,0) and its determinant is +1 — so the
  nine floats are a rotation matrix, not a scaled or affine block. (Read column-major it is
  the transpose, determinant also +1, so this check does not settle the ordering.)
- **Nothing states that `xcr:Rotation` uses the same convention as the export variables
  `R00…R22`.** They are different serialisers. [OPEN — Q9]

**This repo has never validated the XMP rotation convention.** `poses2flightlog.py` says
so in its own docstring and deliberately refuses to rewrite orientations for that reason:
registered images get transformed positions, while "yaw/pitch/roll and their accuracies
are carried over from the original log (the XMP rotation convention has not been validated
against the flight-log convention, so orientations are deliberately NOT rewritten)".
[VERIFIED-as-practice: poses2flightlog.py]

Treat "row-major 3×3, world→camera" as [INFERRED] and do not build orientation-critical
logic on it without running the probe in Q9.

### 5.2 `xcr:Position` frame

`xcr:Position` in this pipeline's exports is in a **grid-anchored local Euclidean frame,
not UTM**. The anchor is the project's grid origin. The `xcr:latitude` / `xcr:longitude`
attributes in the same files are garbage.
[VERIFIED: NA167_SESSION_NOTES §1 and poses2flightlog.py, on zone_9]

The consequence is the whole reason `poses2flightlog.py` exists: to recover UTM you must
fit a rigid local→UTM transform (Umeyama, **scale locked at 1**) between the XMP positions
and the matching flight-log rows, then apply it. Fitting scale as well collapses it toward
zero against noise-dominated nav data (0.5 observed on zone_9), so `--allow-scale` is a
diagnostics-only flag. [VERIFIED: poses2flightlog.py, zone_9]

```bat
py -3 C:\Users\jonat\Desktop\CoyoteThings\RealityScan_CLI\poses2flightlog.py ^
   --images-dir "F:\na156_h2024\batched_images_by_zone\zone_1\cinema" ^
   --flight-log "F:\na156_h2024\batched_images_by_zone\zone_1\flight_log_4Q_UTM.txt" ^
   --position-accuracy 1.0 --registered-only
```

That run also prints the residual distribution (mean / median / p95 / max, metres), which
is a direct estimate of the USBL/DVL navigation error, and writes a per-image residual CSV.

Because `Position` is local, distance **ratios** are still meaningful — that invariance is
what makes the correspondence-free scale oracle possible for fused components whose
sidecars are ordinal and carry no image identity.
[VERIFIED: FINDINGS 2026-07-28] Details in `06-georeferencing-flightlogs-and-scale.md`.

Whether `xcr:Position` is UTM in a scene that was georeferenced *before* export has never
been re-tested — hardening cell U13 was written for exactly this and never run.
[OPEN — Q10]

The `xcr:ExportCoordinateSystemType` attribute presumably records which frame was used,
which would make the question answerable from the file itself. Never inspected.
[INFERRED from the attribute name]

---

## 6. Prior semantics: what each mode actually fixes

### 6.1 The two orthogonal prior families

RealityScan splits "what we know before alignment" into three panels — Prior Pose, Prior
Calibration, Prior Lens Distortion [OFFICIAL: appbasics/camerasettings_priors] — but
operationally there are two families with different plumbing:

| family | what it carries | how it reaches RealityScan here | consumed when |
|---|---|---|---|
| **Pose priors** | per-image X/Y/Z (+ optional yaw/pitch/roll) and their accuracies | flight log via `-importFlightLog` (see `06-…`), or `xcr:Position`/`xcr:Rotation` in a sidecar | during bundle adjustment, gated by `sfmEnableCameraPrior=true` |
| **Calibration / lens priors** | focal, principal point, skew, aspect, distortion model + coefficients, and the **group ids** | `<stem>.xmp` sidecars, `sensorsdb.xml`, EXIF, or `-editInputSelection` | at import (priors set) and during alignment (as constraints) |

`sfmEnableCameraPrior` **is** the GUI's "use camera priors for georeferencing": pose priors
participate *inside* the bundle adjustment and georeference the resulting components.
It stays `true` in every production align here. [VERIFIED: docs/settings-evaluation-2026-07 §4/§5]

### 6.2 Absolute pose modes

| Absolute pose | `inpPose` | Semantics |
|---|---|---|
| Unknown | `0` | nothing known; solve freely |
| Position | `1` | position known to some precision; RealityScan searches for the closest position, **orientation may differ** |
| Position and orientation | `2` | rough position *and* orientation known; both optimisable |
| Locked | `3` | **no changes in camera position or orientation allowed** |

[OFFICIAL: appbasics/camerasettings_priors, appbasics/selectedinputs,
tutorials/editselectioncommand]

### 6.3 Relative pose modes

| Relative pose | `inpPosePriorRelative` | Semantics |
|---|---|---|
| Unknown | `0` | relative position between cameras undefined |
| Draft | `1` | relative position known to some precision, optimisable |
| Exact | `2` | relative position known and **not altered** during alignment |

Plus `inpPosePriorRelativeGroup` (string, "Locked pose group"): a positive integer sets a
group; blank or a negative integer ungroups. [OFFICIAL: same]

### 6.4 The hard constraint on Exact/Locked priors

**Pose-locking cannot be used as an incremental growth anchor.**
`-editInputSelection "inpPose=3"` takes effect, but the following `-align` refuses
outright:

> *"prior set to 'Exact' mode must be all aligned in a single run. Incremental adding is
> not supported."*

[VERIFIED: FINDINGS, hardening cell U18 FAIL, 2026-07-23] The practical consequence for a
chunked pipeline is that checkpoint/rollback (copying the `.rsproj` bundle) remains the
only never-shrink mechanism; you cannot freeze a solved component and grow around it.

This is the single most important operational fact about `exact`/`locked` XMP export
modes: **re-importing a `locked` sidecar set and then adding more images will fail the
align.**

### 6.5 Accuracy sources

Per-image accuracies can come from two places, selected by `inpPriorAccuracyInh`:

| `inpPriorAccuracyInh` | source |
|---|---|
| `0` | **Global camera prior settings** — the `sfmCameraPriorAccuracy*` values in Alignment settings |
| `1` | **Edit custom values** — the per-input `inpuTx/inpuTy/inpuTz/inpuRx/inpuRy/inpuRz` values |

[OFFICIAL: tutorials/editselectioncommand, appbasics/camerasettings_priors]

The flight-log import path has its own inheritance switches (`ifuuInhEn`, `ifuuInh`) —
see `06-georeferencing-flightlogs-and-scale.md`. The measured lesson from this repo is
worth repeating here because it is a *prior-content* lesson, not a plumbing one:

> **The accuracy columns want END-TO-END per-image position uncertainty** (timestamp
> matching + nav interpolation + lever arm + dive drift), **not the instantaneous sensor
> spec.** Over-tight position priors fragment solves and wreck metric scale while barely
> moving the registration count — which is exactly why a camera-counting oracle never
> caught it. On a 665-image known-good component: loose 10/10/1 gave **1 component at
> scale 1.049**; tight 1/1/0.1 gave **2 components at 0.886**. Under Division: loose
> **1 component at 0.989**, tight **3 components at 0.826**. Registration moved only
> 656→665 across all four cells. [VERIFIED: PRIORS_DISTORTION_TEST_PLAN "Bow 2×2", 2026-07-25]

### 6.6 Full `-editInputSelection` prior key table

This is the CLI equivalent of everything the XMP schema expresses, and the only way to set
priors on images already in a scene. Usage: select images, then one `-editInputSelection`
per key. [OFFICIAL: tutorials/editselectioncommand]

| Key | Panel path | Values |
|---|---|---|
| `inpPosePriorRelativeGroup` | Prior pose/Locked pose group | string; positive int groups, blank/negative ungroups |
| `inpPosePriorRelative` | Prior pose/Relative pose | `0` Unknown, `1` Draft, `2` Exact |
| `inpPose` | Prior pose/Absolute pose | `0` Unknown, `1` Position, `2` Position and orientation, `3` Locked |
| `inpTx` / `inpTy` / `inpTz` | Prior pose/x,y,z | float. In a geographic CRS these become Longitude/Latitude/Altitude and accept DMS (`E32,08,25.18`) or prefixed decimal degrees (`N54.825347`) |
| `inpRx` / `inpRy` / `inpRz` | Yaw / Pitch / Roll | float; yaw −180..180, pitch −90..90, roll −180..180 |
| `inpPriorAccuracyInh` | Pose accuracy/Accuracy settings source | `0` global, `1` custom |
| `inpuTx` / `inpuTy` / `inpuTz` | Position X/Y/Z accuracy | float >= 0 |
| `inpuRx` / `inpuRy` / `inpuRz` | Yaw / Pitch / Roll accuracy | float >= 0 |
| `inpCalibrationGroup` | Prior calibration/Calibration group | int >= 0, or `-1` groupless |
| `inpCalibration` | Prior calibration/Prior | `0` Unknown, `1` Approximate, `2` Fixed |
| `inpFocal` | Prior calibration/Focal length (35mm) | float > 0 |
| `inpPPX` / `inpPPY` | Principal point x / y [mm] | float — the Help's "[mm]" is contested, see §4.4 |
| `inpSkew` | Prior calibration/Skew | float |
| `inpAspect` | Prior calibration/**Aspect ratio** | float — **the Help lists `inpSkew` for BOTH Skew and Aspect ratio.** [CONTRADICTED: `tutorials/editselectioncommand` prints `inpSkew` twice, once under "Skew" and once under "Aspect ratio", and documents no aspect key / the binary's `inp*` key pool contains `inpAspect` sitting directly between `inpPPX` and `inpSkew` — `… inpFocal \| inpCalibration \| inpPPY \| inpPPX \| inpAspect \| inpSkew \| inpDistortionModel …`. The Help entry is a copy-paste error; `inpAspect` is the key. UTF-16LE, 1 occurrence; `inpAspectRatio` occurs 0 times.] [UNDOCUMENTED: RealityScan.exe string pool, 2026-08-04] [OPEN — Q11: acceptance untested] |
| `inpLensGroup` | Prior lens distortion/Lens group | int >= 0, or `-1` |
| `inpDistortion` | Prior lens distortion/Prior | `0` Unknown, `1` Approximate, `2` Fixed |
| `inpDistortionModel` | Prior lens distortion/Camera model | `0` No lens distortion, `1` Division, `2` Brown3, `3` Brown4, `4` Brown3+tangential, `5` Brown4+tangential |
| `inpRadial1`..`inpRadial4` | Radial 1..4 | float |
| `inpTangential1`, `inpTangential2` | Tangential 1..2 | float |

Related non-prior keys on the same command: `inpEnabled` (enable alignment),
`inpMeshing`, `inpTexturing`, `inpImageColorsWeight` (0..1), `inpVisible`, `inpColorRef`,
`inpColorNorm`, `inpImageDepthMapDownscale`, `inpMaskOpts` (`0` do not use, `1` alignment
only, `2` meshing only, `3` both), `aligFeaturesMode` (`0` merge using overlaps,
`1` use component features, `2` use all image features).
[OFFICIAL: tutorials/editselectioncommand]

`"inpEnabled=false"` is confirmed working as a single quoted `key=value` argument, and
`-align` honours enable/disable exactly. [VERIFIED: FINDINGS 2026-07-23, cell U1]

The full `inp*` key pool in the binary holds **80** identifiers — the Help documents about
half. Undocumented members that matter for priors and rigs:
`inpAspect` (above), `inpCamModel`, `inpLensModel`, `inpPosePriorAbsoluteCs`,
`inpPosePriorAbsoluteCsType`, `inpPosePriorAbsoluteCsWkt`, `inpPosePriorAbsoluteCsInput`,
`inpPosePriorAbsoluteCsWktCheckProj`, `inpPosePriorAccuracyMode`,
`inpPosePriorRelativeValid`, `inpRig`, `inpRigId`, `inpRigIndex`, `inpRigInstance`,
`inpRigValid`, `inpInsOfsX/Y/Z`, `inpInsOfsRX/RY/RZ`, `inpEnableInsOffset`,
`inpAlignMask`, `inpMeshingMask`, `inpTexturingMask`, `inpAlignDepth`, `inpMeshingDepth`,
`inpImageDepthsWeight`, `inpPointCouldFeatureDetectionQuality` (Epic's typo, reproduced
exactly), plus read-only-looking `inpFile`, `inpShortName`, `inpWidth`, `inpHeight`,
`inpFeatures`, `inpMaxErr`, `inpMeanErr`, `inpMedErr`, `inpMeasCnt`, `inpPtsOverlap`,
`inpWicPixelFormat`, `inpIsLy`, `inpLy`, `inpLya`, `inpIsMask`, `inpIsDepth`, `inpPPILic`.
**Presence proves the identifier exists in the build, not that `-editInputSelection`
accepts it.** [UNDOCUMENTED: RealityScan.exe string pool, 2026-08-04]

**Delivery warning.** `key=value` cannot cross a cmd/subprocess boundary as a bare
argument: cmd splits unquoted `;` `,` `=` into separate `.bat` arguments and Python's
`subprocess` quotes only on whitespace. The observed symptom is
`Parsing setting key=value 'X' failed [err:7155]`, the flag silently never applying, and
the parse error landing in the errors marker and aborting the workflow.
[VERIFIED: NA167 #15 / B5, 2026-07-23] See `01-cli-fundamentals.md` for the `key:value`
convention this repo uses to cross that boundary.

### 6.7 Selection-related prior commands

| Command | Effect | Source |
|---|---|---|
| `-setPriorCalibrationGroup <number>` | prior calibration group for the selection; `-1` = do not group | [OFFICIAL: appbasics/allcommands] |
| `-setPriorLensGroup <number>` | prior lens group for the selection; `-1` = do not group | [OFFICIAL] |
| `-setCalibrationGroupByExif` | set calibration groups of **all inputs** from EXIF (not just the selection, per the Help wording) | [OFFICIAL] |
| `-setConstantCalibrationGroups` | group all selected inputs into one calibration group | [OFFICIAL] |
| `-removeCalibrationGroups` | clear **all** inputs from their calibration groups | [OFFICIAL] |
| `-lockPoseForContinue true\|false` | keep relative pose unchanged for the selection in the next registration; registered images only | [OFFICIAL] |
| `-setCamerasGravityDirection [componentID]` | rotate the component so `-z` follows the images' `xcr:Gravity`; applies to the selected component, or to the one named by the id; **sparse cloud (alignment) only — the mesh/dense cloud is not affected** | [OFFICIAL: appbasics/allcommands] — but note the Help's own table prints `componentID` in the **Required Parameter** column while its prose calls it "the optional parameters (component ID)". [CONTRADICTED-internally: appbasics/allcommands] Treat as optional; untested here. |

**`-selectImage` caveat:** in this build `-selectImage` matches **literal full paths only**.
Bare regexp, dot-star-wrapped regexp, glob, and regexp with an explicit `set` modifier all
silently select nothing, despite the Help documenting
`selectImage <imagePath|regexp> [set|union|sub|intersect|toggle]`. Cost is ~0.1–0.3 s per
image, so composing a thousand-image selection is a multi-minute per-image union loop.
[CONTRADICTED: appbasics/allcommands documents a regexp form / observed: only literal full
paths select anything, bisected across probes U-SEL2…U-SEL8, 2026-07-23] This makes
per-camera prior editing via `-editInputSelection` far more expensive than it looks, and
is a large part of why this pipeline uses sidecars instead.

---

## 7. Calibration groups and lens groups

### 7.1 What a group is

Declaring a calibration group asserts that all images in it share the same intrinsics —
focal length, principal point, distortion coefficients. Groups are useful for fixed-optics
cameras, for **weak-texture / low-feature-count scenes** (fewer parameters to estimate
means fewer feature points needed per camera), and whenever a set of cameras must be
forced to a common focal length. [OFFICIAL: appbasics/camerasettings]

`-1` in either the Calibration group or the Lens group field means *do not group*; any
other integer groups. Images sharing a number share the parameters after alignment.
[OFFICIAL: appbasics/camerasettings, appbasics/selectedinputs]

Epic's own refinement tip: after solving a grouped scene, **ungroup and re-align** to
fine-tune per-camera parameters while the scene is still well-conditioned; the second
align takes seconds. Recommended for weak-texture or small-image-count scenes.
[OFFICIAL: appbasics/camerasettings, "TIP"] This has never been exercised in this
pipeline. [OPEN — Q12]

### 7.2 Automatic grouping and why it is unusable here

`appGroupCalibrationByExif` (bool, default `false`) groups camera parameters automatically
from EXIF at import. [OFFICIAL: tutorials/setkeyvaluetable, appbasics/appsettings]

For the rig this repo drives, **neither setting is correct**:

- The WCA rendered JPGs are **EXIF-identical across physical cameras**: `Make="Z CAM"`,
  `Model="E2-F6"`, matching exposure data, **no focal length tag and no lens tag**,
  4244×2827, Lightroom-rendered from a full-frame sensor. RealityScan cannot tell the
  cameras apart from EXIF at all.
  [VERIFIED-by-inspection: docs/settings-evaluation-2026-07 §1, 2026-07-23]
- Enabled, `appGroupCalibrationByExif=true` would collapse two cameras with different
  lenses (fisheye 14 mm and rectilinear 17 mm) into **one** calibration group.
- Left `false`, images calibrate without any grouping — every camera self-calibrates
  independently, which is weak on low-texture underwater imagery.

**Per-image XMP calibration sidecars are therefore the only mechanism that can separate
EXIF-identical cameras. One group per PHYSICAL camera, never per lens type** — Port and
Starboard share a lens *spec* but are different units with different real intrinsics.
[VERIFIED: docs/settings-evaluation-2026-07 §1–§2]

### 7.3 The rig table this repo encodes

`modules/camera_registry.py` is the single source of truth. Groups, priors and focals are
owner-confirmed 2026-07-23/25.

| Physical camera | Filename families | Optics | CalibrationGroup | LensGroup | Prior | FocalLength35mm | model |
|---|---|---|---|---|---|---|---|
| Zeuss | `zeuss` / `herc` (delimiter-bounded token) | rectilinear 23 mm FF | `1` | `1` | Approximate | `23.0` | `brown3` |
| Port | `cammid*`, WCA `P###C*` | fisheye 14 mm FF | `2` | `2` | Approximate | `16.0` | `division` |
| Cinema | `camlower*`, WCA `C###C*` | rectilinear 17 mm FF | `3` | `3` | Approximate | `16.0` | `brown3` |
| Starboard | `camupper*`, WCA `S###C*` | fisheye 14 mm FF | `4` | `4` | Approximate | `16.0` | `division` |

Matching is most-specific-first: anchored WCA prefix `^([pcs])\d+c`, then anchored legacy
prefix, then a delimiter-bounded `zeuss|herc` token. The delimiter bounding exists because
an earlier unanchored `'herc' in name` test ran first and would beat an anchored WCA
prefix. [VERIFIED-by-inspection: modules/camera_registry.py]

Mount geometry (pitch offsets, lever arms) is deliberately **not** in this table — the
same physical Cinema unit sits 10° down under legacy `camlower` names and 45° down under
WCA names, so geometry keys off the *family*, not the camera. Keying mount geometry off
the camera would silently change every legacy dataset by tens of degrees.
[VERIFIED-as-design: modules/camera_registry.py]

### 7.4 Solved intrinsics — the two cameras do separate

Both cameras were given the **same** 16.0 mm focal prior. Over 5,050 harvest records
(4,394 unique cameras; bow members appear in two laps by the successive-difference
design), the solve separated them by 5.6 % with interquartile ranges of about ±0.5 %:

| camera | records | focal 35mm-eq (median) | IQR | division k1 | k1 IQR | principal point | skew | aspect |
|---|---:|---:|---|---:|---|---|---|---|
| cinema (group 3) | 2,558 | **16.374** | 16.302–16.476 | **−0.0378** | −0.0415…−0.0336 | (−0.0071, −0.0031) | 0 | 1 |
| port (group 2) | 2,492 | **15.499** | 15.435–15.574 | **−0.3875** | −0.3933…−0.3832 | (+0.0027, +0.0056) | 0 | 1 |

[VERIFIED: FINDINGS 2026-07-26, parsed from the PD-6 identity harvest]

The order-of-magnitude k1 gap is the fisheye declaring itself. The findings log reads this
as "independent confirmation that the sidecar grouping works, not just that it is
written". **Read the caveat in §8 before treating it that way** — an equally consistent
explanation is that each image self-calibrated independently and physics did the
separating. The discriminating measurement is the *within-camera spread*, not the
between-camera gap: a real group forces one focal per group, so the IQR would collapse to
numerical noise rather than the ±0.5 % actually observed. That the IQRs are non-zero is,
if anything, mild evidence **against** the groups having been honoured. Nobody has run the
controlled cell. [INFERRED] [OPEN — Q13]

Exported pose XMPs from that run carry `xcr:CalibrationGroup="-1"` and
`xcr:DistortionGroup="-1"` **alongside** `Camera:CalibrationGroup="3"`. The findings log
records the `-1` as "an export artifact, not a lost grouping"; that interpretation is
itself untested. [VERIFIED-as-observation: FINDINGS 2026-07-26] [UNDOCUMENTED]

### 7.5 `sfmDistortionModel` is GLOBAL and all-or-nothing

**The most consequential contradiction in this document.**

- **Docs claim:** the distortion model is selectable per image through the Prior Lens
  Distortion panel / `inpDistortionModel`, and per image via XMP `DistortionModel`; the
  global setting lives in Alignment Settings → Advanced.
  [OFFICIAL: appbasics/settings_distortion_models, appbasics/camerasettings_priors]
- **Observed, twice, in both directions:**
  - Under global `sfmDistortionModel=Brown3`, **every** exported Port (fisheye) XMP read
    `xcr:DistortionModel="brown3"` despite a `division` sidecar declaration — recorded at
    the time as the prime residuals suspect.
    [VERIFIED: PRIORS_DISTORTION_TEST_PLAN item 3, 2026-07-25]
  - Under global `sfmDistortionModel=Division`, **all 2,558** cinema pose XMPs from PD-6
    came back `xcr:DistortionModel="division"` — identical to the 2,492 port records —
    despite the cinema sidecars declaring `brown3`.
    [VERIFIED: FINDINGS 2026-07-26, aggregated over 5,050 harvest records; test cell PD-2]
  [CONTRADICTED: docs/settings-evaluation-2026-07 §3 asserted "per-image XMP overrides the
  global key" / observed: the global key owns the model, in both directions]

**Scope caveat that must travel with this finding.** What was declared per image in both
runs was `<Camera:DistortionModel>brown3</Camera:DistortionModel>` — the repo's
**non-schema element** under a namespace URI that does not exist in the binary (§8). §8's
standing doubt and §7.5's contradiction are therefore entangled: "the global key wins" and
"the repo's sidecar was never parsed at all" predict *exactly* the same observation. The
**documented** form — `xcr:DistortionModel="brown3"` as an attribute under
`.../ns/xcr/1.1#` — has never been tested here.
[VERIFIED-as-observation; attribution [OPEN — Q13]]

**Consequence, on the evidence available:** plan for a mixed-optics rig getting **one**
distortion model for the whole scene, with only the *coefficients* differing per
calibration group. Choosing that one model is a global decision. Supplying measured
coefficients remains per-group and therefore still useful. If Q13 shows the documented
attribute form *is* honoured, revisit this.

Measured, on this rig: `Division` globally did **not** degrade the rectilinear cameras.
On Z3 (124 images) Division gave the best registration of the cell series (112/124 vs 102
baseline) and both cameras solved division. On Z1 (4,540) Division produced 4,394/4,540 in
**two** components at hull scale 0.981, against a Brown3 baseline's 4,405 in **three**
components at hull scale 0.175. [VERIFIED: PD-1, PD-6, 2026-07-25] PD-6's attribution is
not clean — it changed three things at once (Brown3→Division, accuracy columns importing
for the first time, orientation priors removed) — so do not attribute the scale repair to
Division alone. [VERIFIED-as-caveat: FINDINGS 2026-07-26]

Epic's own strategy note is compatible: start with the simpler Division model, then switch
to Brown and re-align to optimise. [OFFICIAL: appbasics/settings_distortion_models, "TIP"]

---

## 8. The production calibration sidecar in this repo — and the doubt about it

### 8.1 What is actually written

`modules/camera_registry.calibration_xmp()` produces, per image:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<x:xmpmeta xmlns:x="adobe:ns:meta/" xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
  <rdf:RDF>
    <rdf:Description xmlns:Camera="http://www.capturingreality.com/ns/camera/1.0/" xmlns:xcr="http://www.capturingreality.com/ns/xcr/1.0/">
      <Camera:CalibrationGroup>3</Camera:CalibrationGroup>
      <Camera:CalibrationPrior>Approximate</Camera:CalibrationPrior>
      <xcr:FocalLength35mm>16.0</xcr:FocalLength35mm>
      <Camera:LensDistortionGroup>3</Camera:LensDistortionGroup>
      <Camera:LensDistortionPrior>Approximate</Camera:LensDistortionPrior>
      <Camera:DistortionModel>brown3</Camera:DistortionModel>
    </rdf:Description>
  </rdf:RDF>
</x:xmpmeta>
```

It carries **no pose entries by design** — exported pose sidecars auto-import as priors
(§10), and pose priors measurably reduced registration on NA167 (§11).

### 8.2 Five ways this diverges from the documented schema

| # | Divergence | Evidence |
|---|---|---|
| 1 | **Element form**, not attribute form, for everything | Epic's sample uses attributes on `rdf:Description` for all fields except `Position` [OFFICIAL: tools/xmpalign] |
| 2 | Prefix `Camera:` bound to `http://www.capturingreality.com/ns/camera/1.0/` | Neither the prefix `Camera:` nor the URI `.../ns/camera/1.0/` occurs anywhere in `RealityScan.exe` [UNDOCUMENTED: binary string pool] |
| 3 | `xcr` bound to `.../ns/xcr/**1.0/**` | The only `xcr` URI in the binary is `.../ns/xcr/**1.1#**` [UNDOCUMENTED: binary] |
| 4 | Names `LensDistortionGroup` / `LensDistortionPrior` | Neither string occurs in the binary in any form; the schema's names are `DistortionGroup` and (probably) `CalibrationPrior`-style `…Prior` tokens [UNDOCUMENTED: binary] |
| 5 | Value `Approximate` for the prior fields | `approximate` (lowercase) occurs 0 times in the binary; `Approximate` once, as a UI label. The XMP prior token set is `{initial, exact, locked}` [UNDOCUMENTED: binary] |

Under any conforming XMP/RDF parser, divergences 2–5 mean the `Camera:*` elements resolve
to properties RealityScan has no name for. Under divergence 3, even `xcr:FocalLength35mm`
resolves to a *different* property than `.../xcr/1.1#FocalLength35mm`.

**Cheapest diagnostic that has never been run:** the binary carries the format strings
`Skipping unexpected attribute, %s=%S` and `Skipping unexpected tag %s`. If the XMP reader
shares the app's XML diagnostics, a single align over one image with a repo-form sidecar
would leave those lines in `%LOCALAPPDATA%\Temp\RealityScan.log` — and their absence, with
a `Camera:CalibrationGroup` element present, would be equally informative. Snapshot the log
immediately; the next instance boot truncates it (NA167 B6).
[UNDOCUMENTED: RealityScan.exe string pool] [INFERRED — the strings were found in the
project-XML parser's neighbourhood, not a distinct XMP one]

### 8.3 But something is being read — the counter-evidence

Two measured results say the sidecars are not inert:

1. **Fragmentation.** A fresh end-to-end run with calibration sidecars gave zone_1
   **3 components at 4,405/4,540 (97.0 %)** against the pre-sidecar production run's
   **9 components at 4,392 (96.7 %)** on the same imagery and the same box.
   [VERIFIED: FINDINGS 2026-07-24; docs/history/FRESH_RUN_2026-07-24.md]
2. **Sidecar loss is treated as a defect.** When the identity harvest stripped 796 of
   4,540 sidecars (§9.6), the pipeline gained a repair function rather than shrugging.

Both are weaker than they look:

- The 9→3 comparison is **fresh run vs production run**, not a controlled A/B. The zone
  boundaries differed (the bow landed inside zone_1 "this time"), and *alignment
  fragmentation is independently established as strongly nondeterministic* — the same
  4,540 images with identical settings and inputs produced 2 components / 4,391 cameras in
  one run and 9 components / 4,392 in another. [VERIFIED: FINDINGS 2026-07-24]
- The 5.6 % focal separation in §7.4 is fully explained by physics alone: a fisheye and a
  rectilinear lens self-calibrating independently *should* separate, with or without
  groups.
- `Camera:*` tags appearing "echoed back in exports" was read as evidence the tags are
  honoured [VERIFIED-as-observation: PRIORS_DISTORTION_TEST_PLAN item 4, 2026-07-25]. It
  is not. The XMP exporter has a *"Merge with existing XMP files"* option
  [OFFICIAL: tools/xmpalign], and **unrecognised content surviving an export is exactly
  what a merging writer does** — a byte-preserving passthrough proves nothing about
  comprehension. Note the mechanism carefully: the repo's `XMPExportParams.xml`
  (`xmpMerge=true`) is passed to **nothing** (§9.7), so the merge state in force was the
  unpinned instance default. The observed file — `xcr:CalibrationGroup="-1"` written by
  RealityScan **alongside** a surviving `Camera:CalibrationGroup="3"` written by this repo
  [VERIFIED: FINDINGS 2026-07-26] — is itself the evidence that the default preserves
  pre-existing XMP content. [INFERRED, from that co-presence]

### 8.4 Standing conclusion

**The production sidecar format is not the documented format, the divergences are
mechanically significant, and no experiment in this repo isolates the sidecars from
everything else that changed.** Do not copy this format into new work. Write the
documented attribute form under `.../ns/xcr/1.1#` unless and until Q13 settles it.

For a new rig, the format that has *documentation* behind it is:

```xml
<x:xmpmeta xmlns:x="adobe:ns:meta/">
    <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
        <rdf:Description xmlns:xcr="http://www.capturingreality.com/ns/xcr/1.1#"
            xcr:Version="3"
            xcr:CalibrationPrior="initial" xcr:CalibrationGroup="3" xcr:DistortionGroup="3"
            xcr:FocalLength35mm="16.0" xcr:Skew="0" xcr:AspectRatio="1"
            xcr:PrincipalPointU="0" xcr:PrincipalPointV="0"
            xcr:DistortionModel="brown3" xcr:DistortionCoeficients="0 0 0 0 0 0"/>
    </rdf:RDF>
</x:xmpmeta>
```

(No `xcr:PosePrior`, no `xcr:Position`, no `xcr:Rotation` — a calibration-only sidecar, so
that nothing here can become a pose prior on a later add.)

**Two traps in that template.** (1) `xcr:DistortionCoeficients="0 0 0 0 0 0"` is copied
from Epic's sample, where it is filler. Written for real under
`xcr:CalibrationPrior="initial"` it *asserts* zero distortion as a starting value — which
is the same trap as the app's own "No lens distortion + Approximate" default (§4.2).
**Omit the attribute entirely unless you have measured coefficients**, and measure them
under the distortion model that will actually be in force (a Division λ is not a Brown3
k1). [VERIFIED-as-principle: FINDINGS 2026-07-25] (2) Per §7.5, `xcr:DistortionModel` may
be ignored in favour of the global `sfmDistortionModel`; set the global key to match rather
than relying on this attribute.

**A completely independent, doc-sanctioned alternative that avoids the whole question:**
put the intrinsics in `sensorsdb.xml` instead (§13) — but that only works if the cameras
are distinguishable by `tiff:Model` / `aux:Lens`, which this rig's EXIF-identical JPGs are
not. The other alternative is `-editInputSelection` with `inpCalibrationGroup` /
`inpLensGroup` / `inpFocal` / `inpDistortionModel` after import (§6.6), which is fully
documented but requires per-image selection and therefore pays the `-selectImage`
literal-path cost.

---

## 9. Exporting XMP

### 9.1 The two commands

| Command | Scope | Sidecar naming | Source |
|---|---|---|---|
| `-exportXMP [params.xml]` | camera metadata of components created in **the last alignment**; gated by `-setMinComponentSize` | **stem-named** `<stem>.xmp` | [OFFICIAL: appbasics/allcommands] + [VERIFIED: FINDINGS 2026-07-23] |
| `-exportXMPForSelectedComponent` | camera metadata of the **selected component**, using current settings (no params argument) | **ordinal** `00000.xmp`, `00001.xmp`, … | [OFFICIAL: appbasics/allcommands] + [CONTRADICTED/UNDOCUMENTED], see §9.3 |

Both write **next to the respective images**, wherever those live — the Help states this
explicitly for both commands ("XMP files are stored in the same folder as the respective
images"). [OFFICIAL: appbasics/allcommands] There is no output-directory argument.

`-exportXMP` accepts an optional params XML exported from the XMP metadata export dialog;
`-exportXMPForSelectedComponent` accepts none and always uses "the current settings" —
i.e. whatever the instance's XMP export dialog state happens to be.

Process ids, for `-writeProgress` / `appProcessExecCmd` filtering:
**`20584 EXPORT_XMP`** and **`20568 EXPORTING_RIGGING_XMP_FILES`**.
[OFFICIAL: tutorials/processids]

### 9.2 The naming rule: the COMMAND decides, not the scene

An earlier hypothesis in this repo held that stem naming required a live aligning session.
That was **wrong** and is superseded. Four consistent datapoints establish:
`-exportXMP` → stems; `-exportXMPForSelectedComponent` → ordinals, in every observed
context. [SUPERSEDED: the session-based hypothesis] [VERIFIED: FINDINGS 2026-07-23,
NA167 B10 final form]

Note the in-repo tension: `testing/NA167_SESSION_NOTES.md` §1 still describes
`-exportXMPForSelectedComponent` as writing `<stem>.xmp`, while the same file's **B10**
entry and `FINDINGS.md` record ordinals. The B10/FINDINGS reading is the current one and
the workflows are built on it. [CONTRADICTED-in-repo: NA167_SESSION_NOTES §1 vs B10]

This is why per-component membership is derived by **successive difference**: each lap
`-exportXMP` writes stems for all remaining components, the harvest moves them to
`identity_r<K>`, then the maximal component is renamed, exported and deleted.
`members(c_K) = stems(r_K) − stems(r_{K+1})`.
[VERIFIED-by-inspection: `RS_CLI/Scripts/AlignZone.bat`]

Worked example, zone_1: lap sidecar counts `2619 / 985 / 593 / 248 / 133 / 64 / 0` →
successive differences `1634 / 392 / 345 / 115 / 69 / 64`, reproducing all six component
sizes to the camera. [VERIFIED: FINDINGS 2026-07-27]

**Directory semantics differ between scene types:** in an ALIGN scene, `identity_r<K>` is
**cumulative** (lap K holds laps K..end); in a MERGE scene, `r<K>` is component K alone.
Component K's own sidecars in an align scene are the stem difference `r_K` minus `r_{K+1}`.
[VERIFIED: FINDINGS 2026-07-28]

Ordinal sidecars are **inert as priors** (no image has an ordinal stem), which is why
`camera_registry.sanitize_and_census` deletes them quietly rather than restoring them.
[VERIFIED: B10, 2026-07-23]

### 9.3 Ordinal naming and imported components

`-exportXMPForSelectedComponent` on a component built from `-importComponent`-ed
`.rsalign` files writes `00000.xmp`, `00001.xmp`, … beside the images.
[VERIFIED: NA167 B10, NA156 smoke merge 2026-07-23] The count is still a valid
registration census; **per-camera identity is only available from `-exportXMP` in the
original aligned scene.**

Practical consequence for the scale oracle: fused components come back UNMEASURED under a
stem-pairing oracle because there is nothing to join on. The correspondence-free quantile
oracle exists specifically to work around this. [VERIFIED: FINDINGS 2026-07-28]

### 9.4 Two preconditions that silently produce nothing

**(a) Clear the selection first.** Flight-log import leaves its matched images **actively
selected**, and selection-driven exports under `-silent` then export **nothing** — the
"Export Selection" dialog is auto-answered. The signature is a suspiciously fast
completion: **0.057 s instead of 20.5 s**. `-deselectAllImages` before every export step is
mandatory. [VERIFIED: FINDINGS 2026-07-23] [UNDOCUMENTED: the Help does not warn that
import leaves a selection]

**(b) Set `-setMinComponentSize 1`.** The default is **5**, and components below the
threshold are silently excluded from `-exportXMP` **and** from `-exportLatestComponents`
**and** from selection. [OFFICIAL: appbasics/allcommands for the gate and the default]
[VERIFIED: HANDOFF 2026-07-21] The command is officially **deprecated** in 2.2 — the app
log carries "will be removed in the next release" — but remains required.
[VERIFIED: NA167 #22 / B11, 2026-07-24]

```bat
call :run -deselectAllImages          || goto :fail
call :run -setMinComponentSize 1      || goto :fail
call :run -exportXMP                  || goto :fail
```

### 9.5 The reparse-point silent no-write

**RealityScan writes NO XMP sidecars when a scene's images resolve through a reparse point
(directory junction), and reports success.**

Measured: four baseline components on real paths harvested `identity_r0` = 267 files
(= 116 + 94 + 57, the exact camera count), ordinal-named, all pose-bearing; `r1` 116,
`r2` 94, `r3` 57, `r4` 0. The same workflow on junction-rooted components harvested
**zero**, silently. The instance log read "Exporting Registration completed in 8.758
seconds" and a sweep of the entire drive found zero `.xmp` written and zero sidecars
carrying `xcr:Position` — the exact string the harvest filters on.
[VERIFIED: FINDINGS 2026-07-27, "RESOLVED BY PROBE"] [UNDOCUMENTED: no Epic coverage of
reparse-point behaviour]

Cost of the misdiagnosis, exactly: **155 min** of GPU work discarded on the first run
(blamed on the read-side junction trap, §1.1), then **157 min** more across **18 attempts**
(cluster_0 ×3, cluster_1 ×15) on a re-run that cleared only the read side — the components
were still exported from junction paths, so the write side was never tested until the
baseline probe. [VERIFIED: FINDINGS 2026-07-27]

Ruled out by measurement: "an imported component carries no images" — the merge scene
reported `Added 1407 images` / `1217` / `2241`.

The fix that was verified: replace per-zone junctions with **real directories of
hard-linked `.jpg`** (9,835 files, 35.8 GB logical, 0.05 GB actual) plus **copied** `.xmp`
and flight logs. Sidecars are deliberately not hard-linked so a v2 write cannot corrupt the
baseline's. No re-align was needed — the components were never the problem, only the paths
baked into them. [VERIFIED: FINDINGS 2026-07-28]

There is a *separate*, also-true junction fact that was mistaken for the cause for 157
minutes: PowerShell 5.1's `Get-ChildItem -Recurse` does not descend into junction
*children* (0 vs 9,835 `.xmp` on the same tree via its real path), while Python's
`os.walk` crosses junctions in both directions. That is a **read**-side trap; the export
failure was on the **write** side. [SUPERSEDED-as-cause; VERIFIED-as-fact: FINDINGS 2026-07-27]

**Rule:** never hand a RealityScan workflow — or a harvest — a path whose components are
reparse points. An empty harvest beside a non-empty component export must abort the run as
an instrument failure, not be scored as "nothing fused". [VERIFIED-as-fix: FINDINGS 2026-07-28]

### 9.6 The harvest strips calibration sidecars — and the required repair

The identity harvest **moves** every pose-bearing `.xmp` into `identity_r<K>`:

```bat
powershell -NoProfile -Command "Get-ChildItem -LiteralPath '%input_dir%' -Recurse -Filter *.xmp | Where-Object { Select-String -LiteralPath $_.FullName -Pattern 'xcr:Position' -Quiet } | Move-Item -Destination '%output_dir%\identity_r%comp_index%' -Force"
```

The last-peeled component's sidecars are never re-exported, so those images are left with
**no calibration prior at all**. Measured on fresh zone_1: **796 of 4,540 images (17.5 %)
had no sidecar** — the entire bow component (665/665), 123 of c0, and 8 unregistered
images. Any re-align of an already-harvested zone then silently runs with a partially
ungrouped camera set. **Test cells PD-4 and PD-4a both re-aligned zone_1 in that state, so
their "collapse" results (669 and 782 of 4,540) are CONFOUNDED.**
[VERIFIED: FINDINGS 2026-07-25]

The repair is `camera_registry.ensure_calibration_sidecars(image_root)`, called after every
zone align: it walks the tree and recreates a calibration-only XMP for every
`.jpg/.jpeg/.png/.heif` that has none, returning `(created, unknown_camera_skipped)`.

Two further hazards in that one PowerShell line, both recorded:

- PowerShell 5.1 exits 0 on non-terminating pipeline errors, so `if errorlevel 1` cannot
  see a partial move — two locked sidecars are a silent −2.
- A flat `-Force` move **collapses same-stem ordinal sidecars arriving from different
  folders**. [VERIFIED: FINDINGS 2026-07-27]

Together these mean a small camera deficit after a fusion (e.g. 3,740 → 3,738) is **not
distinguishable from a harvest artifact** on the current instrument. [OPEN — Q14]

### 9.7 XMP export settings (`xmp*` keys)

`-exportXMP` takes an optional params XML exported from the XMP metadata export dialog.
The repo carries `RS_CLI/Metadata/XMPExportParams.xml`:

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

**This file is referenced by no script in the repository** — `AlignZone.bat` calls bare
`-exportXMP` and `MergeZoneComponents.bat` calls `-exportXMPForSelectedComponent`, which
takes no params at all. Production exports therefore run on **whatever the instance's
current XMP dialog state is**, which is unpinned.
[VERIFIED-by-inspection, 2026-08-04]

**No `xmp*` key is documented anywhere in the shipped Help.** `allcommands` and
`tutorials/commandline_1` both say of `-exportXMPForSelectedComponent` that *"an example
is available in the paragraph 'Metadata (XMP) Export Settings' below"* — **that paragraph
does not exist in the shipped Help**; a full-text grep over
`C:\Program Files\Epic Games\RealityScan_2.2\Help\en-US\*\*.htm` finds only the two
references and no target, and finds zero occurrences of `xmpMerge`, `xmpCamera`,
`xmpExGps`, `xmpFlags`, `xmpCalibGroups` or `xmpRig`.
[CONTRADICTED: the Help promises a worked XMP-export-settings example / no such section
ships, verified by grep 2026-08-04]

Everything below therefore comes from the binary. Two adjacent UTF-16LE runs exist — a
**key** run and a **label** run:

```
keys:    xmpRig  xmpCalib  xmpEnabledOnly  xmpMerge  xmpFlags  xmpCalibGroups
         xmpImageList  xmpExGps  xmpPrecision  xmpPose        [+ xmpCamera, xmpComponentMode, xmpPath]
labels:  CameraExportMode  xmpCamera  EnabledCamerasOnly  MergeWithExistingFiles
         precision_int  Precision  pose_int  Pose  ComponentMode  xmpComponentMode
         Calibration  component_mode_int  Rig  CalibrationGroups  ReplaceGPSExif
         UseConfigFlags  .xmp  .bak
```

[UNDOCUMENTED: RealityScan.exe string pool, 2026-08-04] Only `CameraExportMode` ↔
`xmpCamera` and `ComponentMode` ↔ `xmpComponentMode` are adjacent; the rest of the
key↔label pairing below is by name correspondence and by matching the label set against
the dialog fields the Help does document [OFFICIAL: tools/xmpalign], i.e. [INFERRED]:

| Key | Internal label | Export dialog field | Repo value |
|---|---|---|---|
| `xmpCamera` | `CameraExportMode` | **Camera export mode** — draft / exact / locked | `3` |
| `xmpMerge` | `MergeWithExistingFiles` | **Merge with existing XMP files** (new files replace existing ones when off) | `true` |
| `xmpRig` | `Rig` | **Export rigging setup** (position+orientation only when off) | `true` |
| `xmpCalibGroups` | `CalibrationGroups` | **Export camera calibration groups** | `true` |
| `xmpFlags` | `UseConfigFlags` | **Include editor options** — writes `xcr:InTexturing` / `xcr:InMeshing` | `true` |
| `xmpExGps` | `ReplaceGPSExif` | **Replace GPS Exif with optimized values** — use alignment-computed coordinates instead of EXIF | `true` |
| `xmpEnabledOnly` | `EnabledCamerasOnly` | limit export to enabled cameras | — |
| `xmpPose` | `Pose` (`pose_int`) | pose export selector | — |
| `xmpCalib` | `Calibration` | calibration export toggle | — |
| `xmpPrecision` | `Precision` (`precision_int`) | numeric precision | — |
| `xmpComponentMode` | `ComponentMode` (`component_mode_int`) | which components are covered | — |
| `xmpImageList` | — | image-list companion file | — |
| `xmpPath` | — | export path | — |

**`xmpCamera=3` is unexplained.** The dialog offers three modes; if the enum is
`1`=draft, `2`=exact, `3`=locked then the repo's (unused) preset asks for **locked**
export — which, re-imported, would refuse any incremental align (§6.4). A `0`-based enum
with a fourth "no pose" state is equally possible. The mapping is not established.
[OPEN — Q15]

One further, low-confidence read of the same pool: `.xmp` and `.bak` are adjacent string
constants in the XMP-export label run, which would be consistent with the writer keeping a
`.bak` of a sidecar it overwrites. No `.bak` file has ever been observed beside an image in
this pipeline. [INFERRED, weak]

### 9.8 The registration-export route

The other way to produce XMP is the Registration export: set the save type to
**"RealityScan XMPs with Image List"**, which is format id
`{B95BEEA0-5E3C-49FC-9823-97AAD709D1BF}`, mask `*.imagelist`, writer
`RealityScan.Export.XMP`, `requires="component"`.
[OFFICIAL: shipped `C:\Program Files\Epic Games\RealityScan_2.2\calibration.xml`]
The CLI equivalent is `-exportRegistration <fileName> [params.xml]`.

**`-exportRegistration` without a params XML BLOCKS FOREVER headless.**
[VERIFIED: FINDINGS 2026-07-21] The only way to obtain a valid params file is to export it
once from that tool's GUI dialog; no such file exists in this repo, so the command is
unusable here. See `09-xml-parameter-files.md`.

That dialog adds settings the `-exportXMP` dialog does not have: undistortion settings,
image export, and **Export transformation settings** (coordinate system, scene move /
rotate / scale, normal transformation). [OFFICIAL: tools/exportregistration]

### 9.9 Sidecar counting IS the registration census

**Only registered cameras get pose entries.** Counting pose-bearing sidecars is therefore a
reliable registration census and is this pipeline's primary oracle.
[VERIFIED: NA167_SESSION_NOTES §1]

The filter is the literal string `xcr:Position` — which is exactly why the
element-vs-attribute form matters (§2.3) and why a component `.rsalign` (opaque `TBSM`
binary, ~0.7 GB per ~1.5k cameras, no readable camera list) cannot substitute.
[VERIFIED: NA167_SESSION_NOTES §1]

Census implementation, returning `(pose_count, restored, removed)`:

```python
# modules/camera_registry.py — sanitize_and_census(image_root)
if 'xcr:Position' not in content:
    continue                        # already calibration-only; NOT counted
pose_count += 1
camera = identify(filename)
if camera is not None:
    write(calibration_xmp(camera))  # restore calibration-only content
    restored += 1
    continue
os.remove(path)                     # unrecognised camera: the pose file goes
if os.path.splitext(filename)[0].isdigit():
    continue                        # ordinal sidecar - expected, warn about nothing
removed += 1                        # anything else is a real surprise; log it
```

Note the third counter's meaning: **every** unrecognised-camera sidecar is deleted, but
only *non-ordinal* ones increment `removed` and trigger the warning — an ordinal stem is
the expected shape after `-exportXMPForSelectedComponent` (§9.3), so it is deleted
silently. A non-zero `removed` means a real image whose filename `camera_registry.identify`
could not classify. [VERIFIED-by-inspection: modules/camera_registry.py]

**Read the census BEFORE sanitising** — sanitising destroys the evidence.
`modules/component_manifest.py` documents this ordering constraint explicitly.

---

## 10. The auto-import trap and the cleaning protocol

### 10.1 The trap

`-add` and `-addFolder` **auto-import any `<stem>.xmp` sitting next to an image**, and a
pose-bearing sidecar silently becomes a pose prior. [VERIFIED: NA167 B7, 2026-07-22]
Because RealityScan's own exports land beside the images (§9.1), the default lifecycle is:

```
run 1:  -addFolder  ->  -align  ->  -exportXMP   (writes poses beside every image)
run 2:  -addFolder  ->  the run-1 poses are now priors
```

Run 2 is no longer an independent measurement of anything. Epic documents this as a
*feature* — the "Export XMP to reuse alignment" tutorial copies `Images1/*.xmp` into
`Images2/` precisely so that the second project inherits camera positions and calibration:

```bat
RealityScan.exe -load %MyPath%\Project1.rsproj -exportXMP -quit
copy Images1\*.xmp Images2\
RealityScan.exe -addFolder %MyPath%\Images2\ -align -save %MyPath%\Project2.rsproj -quit
```

[OFFICIAL: tutorials/commandline_1] It becomes a trap only when it is not intended, which
in an automated multi-run pipeline is nearly always.

The strength of the inherited prior is whatever `xcr:PosePrior` the export wrote, which is
governed by the unpinned `xmpCamera` export mode (§9.7). This repo's B7 entry records the
inherited priors as **exact-pose** priors; the actual token in the exported files has never
been read. [VERIFIED-as-effect: NA167 B7] [OPEN — Q16]

### 10.2 The cleaning protocol in force

After every census, the image tree is restored to **calibration-only** content:

1. `sanitize_and_census(image_root)` — walk every `.xmp`; skip files without
   `xcr:Position`; for pose-bearing files, count them, then either rewrite the file with
   `calibration_xmp(camera)` (recognised camera) or delete it (unrecognised camera, e.g.
   ordinal sidecars). Returns `(pose_count, restored, removed)`.
2. `ensure_calibration_sidecars(image_root)` — recreate a calibration-only XMP for every
   image left without one, because the harvest **moved** files out of the tree rather than
   rewriting them (§9.6). Returns `(created, unknown_camera_skipped)`.

Invariants worth asserting in any pipeline that does this:

| Invariant | Why |
|---|---|
| `count(*.xmp) == count(images)` after step 2 | catches both the `image.jpg.xmp` bug class and harvest stripping |
| `0 == count(files containing 'xcr:Position')` after step 1 | proves no pose prior survives into the next run |
| harvest moved > 0 sidecars whenever the exported component was non-empty | an empty harvest is otherwise indistinguishable from a legitimately empty scene [VERIFIED-as-fix: FINDINGS 2026-07-28] |

A verified end-to-end example of the whole chain working (smoke `mini_a`): align → save →
destructive harvest loop → quit-without-saving produced `.rsalign` + manifest (118 members
by real basename, UTM bbox), census from manifests equal to the original registration, and
**zero pose sidecars left beside images**. [VERIFIED: FINDINGS 2026-07-23]

### 10.3 Why quit-without-saving is safe here

`-quit` without saving leaves the `.rsproj` bundle **byte-stable** across load / delete /
export cycles — hash-verified twice. That is what makes the destructive in-memory identity
harvest safe. [VERIFIED: FINDINGS, cells U15/U16, 2026-07-23]

---

## 11. Measured effect of priors

### 11.1 Priors are not automatically beneficial

**96.3 % → 89.6 %** on Zeuss, zone_13, NA167. The A/B compared priors *absent* (because
they had been written as `image.jpg.xmp` and were therefore never loaded — see §1.1)
against priors *promoted* to the correct `<stem>.xmp` naming. Adding the priors **cost
6.7 points of registration.** Sidecar generation became opt-in
(`batch_xmp_priors`, default off) as a direct result.
[VERIFIED: NA167 #4 / B7, 2026-07-22]

**The conditions matter and largely explain the result.** The writer of that era grouped
`cammid` + `camupper` + `camlower` into one group at "12 mm fisheye", when `camlower` is
in fact a **rectilinear 17 mm** camera. Wrong focal, wrong model, wrong grouping — a
confidently-asserted lie is worse than silence.
[VERIFIED: docs/settings-evaluation-2026-07 §2]
[SUPERSEDED-in-scope: the corrected per-camera values reverse the calculus; validate per
rig before trusting either direction]

**Standing rule: a calibration prior is a claim about physics. Validate the claim before
shipping it, and treat "priors improve alignment" as a hypothesis per rig, not a law.**

### 11.2 The counter-result

With corrected per-camera groups and focals, sidecars at align time were associated with
zone_1 going from **9 components at 4,392 (96.7 %)** to **3 components at 4,405/4,540
(97.0 %)** — same imagery, same box. [VERIFIED: FINDINGS 2026-07-24] Attribution caveats
in §8.3.

### 11.3 Pose-prior effects (flight-log route)

Full treatment is in `06-georeferencing-flightlogs-and-scale.md`; the headlines that bear
on prior *content*:

| result | numbers | source |
|---|---|---|
| Configuration alone, no data change, rescued a zone | zone_2 **101/852 (11.9 %) → 812/852 (95.3 %)** with Division + orientation @15° + real accuracies | [VERIFIED: PD-2b, 2026-07-25] |
| Over-tight position priors fragment and shrink scale | see the 2×2 in §6.5 | [VERIFIED: 2026-07-25] |
| Removing orientation priors **destroyed** two zones | position-only re-align: zone_3 and zone_5 registered **nothing at all** — zero components after 12.7 and 32.4 minutes | [VERIFIED: HANDOFF 2026-07-27] |
| Orientation-prior attribution is contaminated | Euler order and "Camera mount" are unpinned in `FlightLogParams.xml`; counts stand, attribution does not | [VERIFIED-as-flag: FINDINGS 2026-07-26] |

**Unresolved tension between rows 1 and 2, stated rather than smoothed over.** PD-2b's
zone_2 rescue ran at accuracies **1/1/0.1** — exactly the "tight" setting that fragmented
the bow and pushed its scale to 0.886 in §6.5. Both results are real; each changed more
than one thing (PD-2b also switched to Division and added orientation priors, the bow 2×2
did not). The reconciliation the findings log offers is that the accuracy column should
carry *end-to-end* per-image uncertainty, and that 1/1/0.1 is honest for one dataset and
dishonest for another — but no cell isolates it. Do not read "tight priors are bad" as a
law. [OPEN — attribution]

### 11.4 A cross-engine echo worth knowing

COLMAP on zone_9 **registered** 710 Zeuss frames but **triangulated zero points** from
them. Two engines, two failure shapes, one physical camera family — treat Zeuss
calibration and imagery as suspect.
[VERIFIED-in-the-other-fact-base: COLMAP C-20260721-15/Q-07, recorded 2026-07-24; not
reproduced in RealityScan]

---

## 12. EXIF handling

### 12.1 Which metadata fields RealityScan actually consumes

Extracted from the binary's XMP/EXIF property-name pool. These are the standard-namespace
fields the application knows by name [UNDOCUMENTED: RealityScan.exe string pool]:

| Namespace | Fields |
|---|---|
| `exif:` | `DateTimeOriginal`, `FocalLength`, `FocalLengthIn35mmFilm`, `FocalPlaneResolutionUnit`, `FocalPlaneXResolution`, `FocalPlaneYResolution`, `GPSAltitude`, `GPSAltitudeRef`, `GPSLatitude`, `GPSLongitude`, `PixelXDimension`, `PixelYDimension` |
| `tiff:` | `Make`, `Model`, `Orientation` |
| `aux:` | `Lens`, `SerialNumber` |
| `xmp:` | `CreateDate`, `CreatorTool`, `MetadataDate`, `ModifyDate` |

`tiff:Make` + `tiff:Model` are what `sensorsdb.xml` matches on; `aux:Lens` is the "camera
lens model" the camera DB uses for per-lens-body entries (§13.4). The Help says a camera
DB entry is unnecessary when the image "stores the 35mm equivalent focal length … (e.g.
EXIF or XMP)" [OFFICIAL: appbasics/cameradb] but never names the tag; `FocalLengthIn35mmFilm`
is the only 35 mm-equivalent field in the pool, so that is the one.
[INFERRED, from the pool + the Help]

Encoding split, for anyone re-deriving this: the `exif:`, `tiff:Make`, `tiff:Model` and
`aux:` names are UTF-16LE; `tiff:Orientation` and all four `xmp:` names are single-byte
ASCII. A scan of one encoding only will miss half the table.
[UNDOCUMENTED: RealityScan.exe string pool, 2026-08-04]

### 12.2 Focal-length resolution order

[OFFICIAL: appbasics/cameradb, paraphrased]

1. If the image carries a **35 mm-equivalent focal length** (EXIF or XMP), it is read
   directly and no database entry is needed.
2. If the image carries a focal length relative to its chip size **and** a chip size, the
   35 mm equivalent is computed without a database entry.
3. Otherwise the **camera database** is consulted by camera model (plus lens model and
   focal length) to supply `ccdWidth` and lens priors.
4. If none of the above resolves, the 1Ds panel shows a **yellow exclamation mark** next to
   the image — "the system has incomplete camera information".

For this rig, step 1–3 all fail: the WCA JPGs carry `Make`/`Model` and exposure data but
**no focal length and no lens tag**, and the model string does not match any DB entry.
[VERIFIED-by-inspection: docs/settings-evaluation-2026-07 §1]

### 12.3 GPS EXIF

| Control | Key | Default | Effect |
|---|---|---|---|
| Ignore exif GPS (global) | `appIgnoreExifGPS` | `false` | globally turn EXIF GPS coordinates on/off |
| Ignore exif GPS (per camera) | `sensorsdb.xml` attribute `GPSMode="ignore"` | per entry | same, scoped to one camera model |

[OFFICIAL: tutorials/setkeyvaluetable, appbasics/appsettings, appbasics/cameradb]

In the shipped `sensorsdb.xml`, `GPSMode="ignore"` appears on **exactly 13** of the 785
entries, all of them Apple iPhone models (`Apple iPhone 3GS`, `4`, `4s`, `4S`, `5`, `5s`,
`5S`, `6s`, `6S`, `6s Plus`, `6S Plus`, `7 Plus`, `X`); `ignore` is the only value present
in the shipped file, and it is also a standalone string in the DB parser's token run. The
binary also contains the attribute name `GPSAccuracy`, which no shipped entry uses.
[VERIFIED-by-inspection of the shipped file + binary, 2026-08-04]
[UNDOCUMENTED: `GPSAccuracy`]

XMP sidecars are one of the four documented routes for georeferencing a scene: "ground
control points, or directly to the camera using the camera priors, flight logs, or XMP
files". To use **EXIF GPS** as camera priors you must "enable the camera priors for
georeferencing in the alignment settings … for the EXIF data to be used".
[OFFICIAL: tutorials/georeferencing] That setting is `sfmEnableCameraPrior=true`.
[VERIFIED: docs/settings-evaluation-2026-07 §4/§5]

**On export, "Replace GPS Exif with optimized values" (`xmpExGps`) writes the
alignment-computed coordinates instead of the EXIF ones.** [OFFICIAL: tools/xmpalign]
The repo's (unused) preset sets it `true`. Note that in this pipeline the exported
`xcr:latitude`/`longitude`/`altitude` were observed to be garbage while `xcr:Position` in
the local frame was correct (§5.2) — so do not trust the geographic fields on this
evidence. [VERIFIED: poses2flightlog.py, zone_9]

### 12.4 EXIF vs XMP precedence

The application setting **"Prefer Exif over XMP"** exists: "When importing new files, Exif
metadata takes priority over XMP metadata if this setting is enabled."
[OFFICIAL: appbasics/appsettings] Its key is **not** in the published
`setkeyvaluetable` list, and the Help never names one.

The binary contains `AppPreferExif` (UTF-16LE, one occurrence) inside a capital-`App`
run — `… AppGroupCalibrationsExif | AppForceEqualCalibration | AppIgnoreExifGPS |
AppPreferExif` — which is a **separate naming family** from the documented lowercase
`-set` keys: `appIgnoreExifGPS` and `appGroupCalibrationByExif` both exist lowercase
elsewhere in the binary and are the forms `setkeyvaluetable` publishes, and note
`AppGroupCalibrationsExif` ≠ `appGroupCalibrationByExif`. Lowercase `appPreferExif` occurs
**zero** times. [UNDOCUMENTED: RealityScan.exe string pool, 2026-08-04] So the settable
key, if there is one, is as likely `appPreferExif` (never observed, matching the
documented convention) as `AppPreferExif` (observed, matching the internal convention);
a probe must try both. [OPEN — Q17]

This matters for any XMP-prior pipeline: if the setting is on and the images carry EXIF
focal data, the sidecar's `FocalLength35mm` may be overridden.

### 12.5 The metadata cache

`appCacheImageMetadata` (bool, **default `true`**) — "Cache image metadata" writes a hidden
system file with EXIF-derived metadata (resolution and so on) next to input images, to
speed up access. [OFFICIAL: tutorials/setkeyvaluetable, appbasics/appsettings — the latter
names the file `crmeta.db`] The binary contains the format strings for **both**
`%srsmeta.db` and `%scrmeta.db`, adjacent and in that order, so the 2.2-era filename is
likely `rsmeta.db` with `crmeta.db` retained for legacy trees.
[UNDOCUMENTED: RealityScan.exe string pool] Related and undocumented: the cache **location**
is `appCacheLocation` with enum `SystemTemp` \| `ProjectFolder` \| `Custom`.
[UNDOCUMENTED: binary]

Operational note: these files appear inside image directories and will be swept up by any
naive "copy the image folder" step. They are not sidecars and carry no priors.

### 12.6 This pipeline reads no EXIF at all

`modules/file_metadata_parser.py` derives timestamps from **filenames**, not EXIF:
`(?:camlower_|cammid_|camupper_)?(\d{8}T\d{6}Z|\d{14})`, defaulting to
`19700101T000000Z` when nothing matches. Frame numbers come from `frame(\d+)`.
[VERIFIED-by-inspection: modules/file_metadata_parser.py]

Full-file image verification is untenable at scale here — PIL `.verify()` walks every byte,
≈720 GB of reads over 18k 39 MB stills; a header probe cut the georeference stage to
~5 min. [VERIFIED: NA167 #7, 2026-07-22]

One dimension anomaly is on record and is a metadata fact with real consequences: of 8,197
H2024 JPGs, exactly one — `C231C2370_20231104202628_edt.jpg` — is **3846×2163** while the
other 8,196 are **4244×2827**. A different sensor footprint means different intrinsics, so
RealityScan will group it separately **regardless of its XMP calibration group**.
[VERIFIED: FINDINGS 2026-07-25]

---

## 13. The sensor database `sensorsdb.xml`

### 13.1 Location and the actual state of this machine

| Path | Role |
|---|---|
| `C:\ProgramData\Epic\RealityScan\sensorsdb.xml` | **the file the application reads** [OFFICIAL: appbasics/cameradb] |
| `C:\Program Files\Epic Games\RealityScan_2.2\sensorsdb.xml` | install-tree copy |
| `<repo>\sensorsdb.xml` | this project's modified copy |

Measured 2026-08-04: the ProgramData file and the install-tree file are **byte-identical**
(SHA-256 `FA3D6EED…BAC01A37`, 47,925 bytes, 785 `<camera>` entries). The repo's copy is
48,580 bytes and prepends four hand-authored ROV entries that are **not present on this
machine**:

```xml
<camera model="ZCAM F6 8-15mm Fisheye Upper" ccdWidth="37.09"><lens type="division" focal="13"   c1="0"/></camera>
<camera model="ZCAM F6 8-15mm Fisheye Mid"   ccdWidth="37.09"><lens type="division" focal="13.5" c1="0"/></camera>
<camera model="ZCAM F7 16-35mm III Lower"    ccdWidth="37.09"><lens type="division" focal="16"   c1="0"/></camera>
<camera model="Zeus Plus"                    ccdWidth="11.0"/>
```

[VERIFIED-by-inspection, 2026-08-04] Those entries are inert for two independent reasons:
they are not installed, and their `model` strings cannot match this rig's EXIF
(`Make="Z CAM"`, `Model="E2-F6"`) anyway. The database also **cannot distinguish two
cameras with identical EXIF**, which is the rig's actual problem.
[VERIFIED-by-inspection: docs/settings-evaluation-2026-07 §1]

Note the same install-tree/ProgramData duality applies to `flightlogs.xml`, which **was**
hand-edited in Program Files to add a 13-column format; that edit must be re-checked after
any app update. See `06-georeferencing-flightlogs-and-scale.md`.
[VERIFIED: PRIORS_DISTORTION_TEST_PLAN, 2026-07-25]

### 13.2 Schema

```xml
<cameras>
  <camera model="Apple iPhone 5s" ccdWidth="4.8900" GPSMode="ignore"/>
  <camera model="Gopro HD3"><lens type="division" focal="15" c1="-0.3143"/></camera>
</cameras>
```

| Element / attribute | Meaning | Source |
|---|---|---|
| `<cameras>` … `</cameras>` | root | shipped file + binary parser strings |
| `<camera model="…">` | one entry; `model` matches the camera model string RealityScan displays in the 1D/1Ds panels (from `tiff:Make` + `tiff:Model`) | [OFFICIAL: appbasics/cameradb] |
| `ccdWidth="…"` | sensor width in mm — supplies the missing chip size so a 35 mm equivalent can be computed. **"Define a ccdWidth to get rid of the yellow exclamation mark."** | [OFFICIAL: appbasics/cameradb] |
| `GPSMode="ignore"` | per-camera EXIF GPS suppression | [OFFICIAL: appbasics/cameradb] |
| `GPSAccuracy="…"` | present in the parser's string pool; unused by any shipped entry | [UNDOCUMENTED: binary] |
| `orientationAccuracy="…"` | present in the parser's string pool; unused by any shipped entry | [UNDOCUMENTED: binary] |
| `<lens type="…" focal="…" c1="…"/>` | lens prior for a given focal length; multiple `<lens>` elements per camera define different focal lengths | [OFFICIAL: appbasics/cameradb] + shipped file |
| `<lens … quality="exact"/>` | makes it a **hard** prior — the system will not change the value. Recommended for fixed setups. Without it, DB priors are **soft**: RealityScan optimises them. | [OFFICIAL: appbasics/cameradb] |
| `focus="…"`, `distance="…"` | present in the parser's string pool; not in any shipped entry and not documented | [UNDOCUMENTED: binary] |

The DB parser's own contiguous ASCII token run is, verbatim in order:
`cameras | ignore | /cameras | GPSAccuracy | ccdWidth | brownr4t2 | brownr4 |
orientationAccuracy | /camera | GPSMode | brownr3 | lens | brownr3t2 | brown | focus |
/lens | distance`. So the `type` vocabulary it carries is `brown`, `brownr3`, `brownr3t2`,
`brownr4`, `brownr4t2` — note these are the DB's **own** spellings, distinct from both the
XMP tokens and the `sfmDistortionModel` names (§4.3). `division` is not in that run (it is
in the XMP value pool) yet is the value both shipped `<lens>` entries use, so it is
certainly accepted. [UNDOCUMENTED: RealityScan.exe string pool + shipped file inspection,
2026-08-04] Note also what is **absent** from the run: no `model`, `focal`, `c1` or
`quality` — those are stored differently and were not recoverable this way, but all four
are documented or present in the shipped file.

Shipped content census, 2026-08-04: **785 camera entries, of which exactly 2 carry a
`<lens>` prior** — `Gopro HD3` and `GoPro Hero3-Black Edition`, both
`type="division" focal="15" c1="-0.3143"`. Everything else is a bare `ccdWidth`
(+ sometimes `GPSMode="ignore"`). [VERIFIED-by-inspection, 2026-08-04]

### 13.3 When to add an entry

[OFFICIAL: appbasics/cameradb]

- The image files carry a focal length that is **not** the 35 mm equivalent (e.g. relative
  to chip size).
- Lens distortion is **directly noticeable** in the input images — priors help register
  more precisely.
- A **yellow exclamation mark** appears in the 1Ds panel next to an image.

It is explicitly *not* necessary to add every camera. Epic's own caution: add or modify
entries only "if you know what you are doing", in a controlled environment.

### 13.4 The documented procedure for a high-distortion lens

[OFFICIAL: appbasics/cameradb, condensed]

1. Photograph a heavily-textured object (a box covered in newspaper) and load the images
   into a new project.
2. Set **Prior lens distortion / Prior = Unknown**, since great distortion is expected.
3. **Group** the cameras (Inputs panel → Group) so the scene is better conditioned.
4. Select the **Division** model (ALIGNMENT → Settings → Advanced → Distortion model) —
   one parameter to estimate. For *hard* (exact-quality) priors, use a richer model
   instead: Brown3, Brown4, Brown3 with tangential2, or Brown4 with tangential2.
5. Align (F6).
6. Read the solved optics: focal and λ in a 2Ds image view, or 1Ds/2Ds/1D panel →
   Registration → Calibration.
7. Add an entry to `C:\ProgramData\Epic\RealityScan\sensorsdb.xml` with the camera model
   name plus the `focal` and `c1` from step 6. Save.

From then on the system sets those camera priors automatically.

Additional documented behaviours:

- **Per-lens-body entries.** The system matches on **camera model + camera lens model +
  focal length**, so cameras with interchangeable lenses can have distinct priors. The
  lens model is readable in the 1D/1Ds view when an image is selected (it is `aux:Lens`).
- **Interpolation.** If an image with the same camera and lens model but a *different*
  focal length is imported, RealityScan **automatically computes** the distortion values
  from the other data available in the database.
- **Soft by default.** DB priors are soft — the system optimises them, so a rough estimate
  suffices and a single-parameter division model is a very good choice. Add
  `quality="exact"` to the `<lens>` attributes for hard priors.

### 13.5 Precedence relative to XMP

Not documented. Where an image has both a `sensorsdb.xml` match and an XMP sidecar
carrying `FocalLength35mm` / `DistortionModel`, which wins is unstated in the Help and
untested here. The only adjacent documented control is "Prefer Exif over XMP" (§12.4),
which governs EXIF vs XMP, not DB vs XMP. [OPEN — Q18]

---

## 14. Undistortion and registration-export interactions

XMP export from the Registration-export route can write **undistorted** values and images.
The pipeline, in the order the application applies it [OFFICIAL: tools/undistort]:

1. **Image cut-out** — which fraction of the image is considered for undistortion.
   `1.0` = full image, `0.5` = 50 %, `0` = nothing. **For fish-eye lenses Epic recommends
   0.8.**
2. **Fit** — which section of the undistorted image is output: `Outer boundary`,
   `Inner region`, `In between`, or `Keep intrinsics` (preserves the camera calibration
   parameters).
3. **Resolution** — `Fit` (keep the resolution from step 2), `Preserve` (same as the
   original image), or `Custom` (arbitrary width/height).
4. **Downscale** — integer divisor applied to each side. `1` = no change.
5. **Max count of pixels** — `0` = no limit; otherwise the aspect ratio from the previous
   steps is preserved and the image resampled to fit that pixel budget.
6. **Undistort principal point** — `1` shifts the optical centre to the actual centre of
   the exported image; `0` = no shift.

Relevant CLI commands [OFFICIAL: appbasics/allcommands]:

| Command | Parameters | Note |
|---|---|---|
| `-exportUndistortedImages` | `folderName` required, `params.xml` optional | falls back to "the current settings" |
| `-exportSTMap` | **both** `folderName` and `params.xml` optional | "If folderName and params.xml are not specified, results are stored along with the original images using the current settings" |

**Spelling trap.** `appbasics/allcommands.htm` writes `exportUndistortedImages`;
`tutorials/commandline_1.htm` writes `exportUndistoredImages` (no `t`) for the same row.
Only one can be the accepted switch and neither has been tried here — the correctly spelled
form is the one on the canonical command page.
[CONTRADICTED: two Help pages disagree on the command's spelling, verified by grep over
`Help\en-US\*\*.htm`, 2026-08-04] [OPEN — Q19]

The undistortion/registration-export settings keys are the `calex*` family. Full inventory
from the binary [UNDOCUMENTED: RealityScan.exe string pool, 2026-08-04]:

```
calexFilePath  calexFileName  calexFolder  calexFolderCustom  calexFolderDefault
calexFileFormat  calexFileFormatId  calexExporterProps  calexHasCustomProps  calexLRU
calexExportImages  calexExportUndistorted  calexExportDisabled  calexHasDisabled
calexHasImageExport  calexHasUndistort  calexRequiresColorCorrection
calexRequiresEqualResolution  calexRequiresUndistortPrincipal  calexCorrectColors
calexUndistCutOut  calexUndistFitMode  calexUndistResMode  calexUndistResWidth
calexUndistResHeight  calexDownscale  calexUndistMaxPixels  calexUndistPrincipal
calexUndistBackColor  calexUndistortImageFormat  calexUndistortPixelFormat
calexUndistortNaming  calexImageLayerType  calexImageLayerOptions  calexImageLayerSuffix
calexInputHasLayers  calexTrans
```

The names map onto the dialog fields above transparently (`calexUndistCutOut` ↔ Image
cut-out, `calexUndistFitMode` ↔ Fit, `calexUndistResMode`/`ResWidth`/`ResHeight` ↔
Resolution/Custom width/Custom height, `calexDownscale` ↔ Downscale,
`calexUndistMaxPixels` ↔ Max count of pixels, `calexUndistPrincipal` ↔ Undistort principal
point, `calexTrans` ↔ Export transformation settings) — [INFERRED] from the names. Value
encodings are unknown; these are `<entry key=… value=…>` rows in a params XML, not `-set`
keys. See `09-xml-parameter-files.md`.

**Nothing in this repo has ever exported undistorted images or ST maps**, and no valid
Export Registration params XML exists here (§9.8). [OPEN — Q19, blocked on Q20]

---

## 15. Silent-failure catalogue

Every row here fails **without an error code**, which is why this document exists.

| # | Failure | Signature | Fix |
|---|---|---|---|
| 1 | `image.jpg.xmp` naming | priors never applied; `count(*.xmp) ≈ 2 × count(images)` | write `<stem>.xmp`; assert the 1:1 count [VERIFIED: NA167 #3/B7] |
| 2 | Leftover pose sidecars become priors on the next `-add` | second run's registration differs with "no changes made" | `sanitize_and_census` after every census [VERIFIED: NA167 B7] |
| 3 | Images selected at export time | export "completes" in **0.057 s** instead of 20.5 s; no files | `-deselectAllImages` before every export [VERIFIED: FINDINGS 2026-07-23] |
| 4 | `-setMinComponentSize` left at default 5 | small components missing from XMP export *and* from `-exportLatestComponents` *and* from selection | `-setMinComponentSize 1` before exports [VERIFIED: HANDOFF 2026-07-21] |
| 5 | Images resolve through a directory junction | export logs success ("completed in 8.758 seconds"); **zero** `.xmp` written | real directories + hard-linked images [VERIFIED: FINDINGS 2026-07-27/28] |
| 6 | `Get-ChildItem -Recurse` over a junction **parent** | reports `0` sidecars where `os.walk` reports 9,835 — but the *same* command pointed **at** the junction works, so an align harvest can pass while a merge harvest silently returns nothing | enumerate the real path, or use Python [VERIFIED: FINDINGS 2026-07-27] |
| 7 | Identity harvest strips calibration sidecars | 796/4,540 images (17.5 %) left with no prior; later re-aligns run partially ungrouped | `ensure_calibration_sidecars` after every align [VERIFIED: FINDINGS 2026-07-25] |
| 8 | PowerShell 5.1 exits 0 on non-terminating pipeline errors | a partial `Move-Item` is a silent −N in the census | assert the moved count; never trust `if errorlevel 1` on a PS pipeline [VERIFIED: FINDINGS 2026-07-27] |
| 9 | Flat `-Force` move collapses same-stem ordinal sidecars from different folders | census undercounts | per-source subdirectories, or rename on move [VERIFIED: FINDINGS 2026-07-27] |
| 10 | `xcr:Position` attribute form in legacy files | regex tuned to element form silently matches nothing | accept both forms [VERIFIED: FINDINGS 2026-07-28] |
| 11 | Per-image `DistortionModel` believed to override the global key | every camera comes back with the global model, in both directions tested | choose one global `sfmDistortionModel` [CONTRADICTED: FINDINGS 2026-07-26; caveat §7.5 — the per-image form under test was the non-schema `Camera:` element] |
| 16 | `-editInputSelection "inpSkew=…"` used for **aspect ratio** because the Help lists `inpSkew` under both fields | the aspect prior silently never changes; skew is overwritten instead | use `inpAspect` [UNDOCUMENTED: binary, §6.6] |
| 17 | A `.xmp` written by `Set-Content -Encoding utf8` (PowerShell 5.1) | emits a UTF-8 BOM; harmless for sidecars so far, **fatal on line 1 of a `.complist`** | `[System.IO.File]::WriteAllLines(…, UTF8Encoding($false))` [VERIFIED: FINDINGS 2026-07-27] |
| 18 | `Get-ChildItem -LiteralPath <dir> -Recurse -Include *.jpg` used to count images | `-Include` silently ignored; returns **every** entry, so a sidecar-count audit passes when it should fail | `-File` then filter on `.Extension` [VERIFIED-by-probe, 2026-08-04, §1.1] |
| 19 | `^` line-continuation used **inside** a quoted `-c` / `-Command` argument | caret reaches the child process as text; Python raises `SyntaxError`, PowerShell raises `Unexpected token '^'` | one physical line, or carets only outside quotes [VERIFIED-by-probe, 2026-08-04, §1.1/§16.1] |
| 12 | `appGroupCalibrationByExif=true` on EXIF-identical cameras | two different lenses collapse into one calibration group | leave `false`; separate with XMP groups [VERIFIED-by-inspection: settings-evaluation §1] |
| 13 | `-exportRegistration` with no params XML | **blocks forever** headless | never call it without a GUI-exported params file [VERIFIED: FINDINGS 2026-07-21] |
| 14 | `-selectImage` with a regexp | selects nothing, silently | literal full paths only in this build [CONTRADICTED: allcommands, 2026-07-23] |
| 15 | `exact`/`locked` pose priors + incremental add | `-align` refuses: *"prior set to 'Exact' mode must be all aligned in a single run"* | do not use pose locking as a growth anchor [VERIFIED: cell U18, 2026-07-23] |

---

## 16. Runnable recipes

### 16.1 Write calibration-only sidecars for a batched zone tree

**Must be one physical line.** cmd's `^` line-continuation is inert *inside* a quoted
string — the caret is passed through to Python verbatim and yields
`SyntaxError: invalid syntax`. Verified by execution, 2026-08-04.

```bat
py -3 -c "import sys; sys.path.insert(0, r'C:\Users\jonat\Desktop\CoyoteThings\RealityScan_CLI'); from modules import camera_registry as cr; print(cr.ensure_calibration_sidecars(r'F:\na156_h2024\batched_images_by_zone\zone_1'))"
```

Prints `(created, unknown_camera_skipped)`. Idempotent: images that already have a sidecar
are skipped, so this is safe to run before every align. Note it walks with `os.walk`, so
unlike the PowerShell harvest it **does** cross directory junctions in both directions
(§1.1) — which is why it reported correct coverage throughout the reparse-point incident
and raised no warning. [VERIFIED: FINDINGS 2026-07-27]

### 16.2 The canonical per-zone align + identity harvest

Abbreviated from `RS_CLI/Scripts/AlignZone.bat`. Every operation goes through the shared
`:run` subroutine (`-delegateTo` → grace → `-waitCompleted` → grace → `-waitCompleted` →
abort if `RS_CLI/Errors/errors.txt` is non-empty); see `01-cli-fundamentals.md`.

```bat
call :run -newScene                                        || goto :fail
:: -set is INSTANT and FIFO-ordered ahead of the queued -addFolder, so it is
:: fired directly, NOT through :run (no completion to wait for). Inside a .bat
:: the "key=value" form is correct; the repo's "key:value" convention exists
:: only for settings crossing a Python -> cmd argument boundary (see 01-...).
%RealityScan% -delegateTo %RS_INSTANCE% -set "appIncSubdirs=true"
call :run -addFolder "%input_dir%"                         || goto :fail
call :run -importFlightLog "%flight_log_dir%" "%flight_log_params_dir%" || goto :fail
:: sfm*/lis* keys parsed out of AlignmentParams.xml and pushed one -set at a
:: time, also fired directly for the same reason
call :run -align                                           || goto :fail
call :run -deselectAllImages                               || goto :fail
call :run -setMinComponentSize %min_component_size%        || goto :fail
call :run -save "%output_dir%\%scene_name%.rsproj"         || goto :fail

:: destructive in-memory identity loop; the scene is already saved
set /a comp_index=0
:identityLoop
if %comp_index% GEQ 20 goto :identityDone
if not exist "%output_dir%\identity_r%comp_index%" mkdir "%output_dir%\identity_r%comp_index%"
call :run -deselectAllImages                               || goto :fail
call :run -exportXMP                                       || goto :fail
powershell -NoProfile -Command "Get-ChildItem -LiteralPath '%input_dir%' -Recurse -Filter *.xmp | Where-Object { Select-String -LiteralPath $_.FullName -Pattern 'xcr:Position' -Quiet } | Move-Item -Destination '%output_dir%\identity_r%comp_index%' -Force"
set "have_poses="
for %%F in ("%output_dir%\identity_r%comp_index%\*.xmp") do set have_poses=1
if not defined have_poses goto :identityDone
call :run -selectMaximalComponent                          || goto :fail
call :run -renameSelectedComponent "%scene_name%_c%comp_index%" || goto :fail
call :run -exportSelectedComponentDir "%output_dir%"       || goto :fail
if not exist "%output_dir%\%scene_name%_c%comp_index%.rsalign" goto :identityDone
call :run -deleteSelectedComponent                         || goto :fail
set /a comp_index+=1
goto :identityLoop
:identityDone
%RealityScan% -delegateTo %RS_INSTANCE% -quit
```

The loop terminal is a **file-existence check**, not an error check:
`-selectMaximalComponent`, `-renameSelectedComponent` and `-deleteSelectedComponent` all
silently no-op on an empty scene, and there is no CLI query for "how many components
remain". [VERIFIED: FINDINGS 2026-07-23/24]

### 16.3 Census then sanitise (order matters)

Again one physical line (see §16.1):

```bat
py -3 -c "import sys; sys.path.insert(0, r'C:\Users\jonat\Desktop\CoyoteThings\RealityScan_CLI'); from modules import camera_registry as cr; root=r'F:\na156_h2024\batched_images_by_zone\zone_1'; print('pose_count, restored, removed =', cr.sanitize_and_census(root)); print('created, unknown =', cr.ensure_calibration_sidecars(root))"
```

`sanitize_and_census` returns the registration census **and** destroys the evidence in the
same call — read the return value; there is no second chance.

### 16.4 Prove a prior actually landed

There is no CLI query for an image's current priors. The only headless read-back is to
align and export:

```bat
RealityScan.exe -setInstanceName RS1 -headless -silent "D:\rs\errors" ^
  -set "appIncSubdirs=true" -add "D:\probe\probe.imagelist" -align ^
  -deselectAllImages -setMinComponentSize 1 -exportXMP -quit
```

then read `xcr:FocalLength35mm`, `xcr:DistortionModel`, `xcr:CalibrationGroup` out of the
resulting `<stem>.xmp` files. This is the mechanism every probe in
[Open questions](#open-questions) uses.

---

## Open questions

Every [OPEN] item raised above, with the cheapest experiment that closes it. None of these
have been run.

| # | Question | Cheapest probe |
|---|---|---|
| **Q1** | When both `_common.xmp` and `<stem>.xmp` exist in a folder, which wins — and do they merge per-field? | Smoke fixture (120 images, ~2 min align). `_common.xmp` with `FocalLength35mm=20`, one image's `<stem>.xmp` with `FocalLength35mm=30`. Align, `-exportXMP`, read that image's solved focal against its neighbours. |
| **Q2** | Does `_common.xmp` apply recursively to subfolders, or only to its own folder? | Same fixture with per-camera subfolders; place `_common.xmp` at the zone root only, align, and check whether cameras in `cinema\` and `port\` both received the group. |
| **Q3** | What does `-addImageWithCalibration` cost per image at 8k scale, and does it accept delegation? | Time 100 delegated `-addImageWithCalibration` calls on the smoke fixture; extrapolate. ~3 min. |
| **Q4** | Does the XMP reader accept **element** form for attributes other than `Position`? | Two sidecars for one image on the smoke fixture, one attribute-form and one element-form, differing only in `FocalLength35mm`. Align each, compare exported solved focal. ~5 min. |
| ~~Q5~~ | ~~What is `xcr:Cert`?~~ | **CLOSED 2026-08-04.** It is the licence-certificate element `<xcr:Cert id="%s">` inside `<certificates>`, not an image-sidecar attribute (§3). Settled from the binary's string neighbourhood — `importLicense`, `exportLicense`, `"certificate file"`, `certificates\`. No probe needed. |
| **Q6** | Are the XMP prior tokens exactly `{initial, exact, locked}`, and does an unrecognised value (e.g. `Approximate`) fail loudly or silently? | Smoke fixture; one sidecar with `xcr:CalibrationPrior="Approximate"` and one with `"initial"`, both with `FocalLength35mm` far from truth. Compare solved focals and grep `%LOCALAPPDATA%\Temp\RealityScan.log` for the literals **`Skipping unexpected attribute`** and **`Skipping unexpected tag`** — both are format strings in the binary (`Skipping unexpected attribute, %s=%S`), so if the XMP reader shares the app's XML diagnostics they are the loudest signal available. Caveat: they were found in the **project-XML** parser's string neighbourhood, so their firing on a sidecar is not guaranteed. ~5 min. |
| **Q7** | **Narrowed 2026-08-04.** The *native* six-slot order is `k1 k2 k3 k4 t1 t2` — two shipped `calibration.xml` templates emit it literally (§4.3a). What remains open is only whether `xcr:DistortionCoeficients` uses that same order. | Align the smoke fixture under `Brown3WithTangential2` (so `t1 ≠ t2 ≠ 0`), `-exportXMP`, and cross-read the same cameras through `-exportRegistration` in the **Internal/External Camera Parameters** format (`{0CA18733-…}`, header `…,k1,k2,k3,k4,t1,t2`). Requires a GUI-exported registration params XML first — see Q20. |
| **Q8** | **Narrowed 2026-08-04.** The Help's GUI label says "[mm]"; the shipped `{0CA18733-…}` template names the same quantity `px_norm`/`py_norm` and writes `$(px)` raw beside `f_35mm = $(f*36)` (§4.4). Treat as normalised. What remains open is the exact divisor — image width, or the larger image dimension. | One camera, cross-read: `px_norm` from `{0CA18733-…}` and `px_pix` from the OpenCV format `{B5331837-…}` (`px*scale+width*0.5`). `scale = (px_pix − width/2) / px_norm` settles the divisor arithmetically. Blocked on Q20. |
| **Q9** | `xcr:Rotation` convention: row-major? world→camera? handedness? — the export variables `R00…R22` are settled (row-major, world→camera; the CmpMvs template builds `P = K·[R|t]`, §5.1), but `xcr:Rotation` is a different serialiser. | Same cross-read: compare one camera's nine `xcr:Rotation` floats against its `R00…R22` from `{0CA18733-…}` or Boujou. Decisive, needs no new alignment. Blocked on Q20. |
| **Q10** | Is `xcr:Position` UTM in a scene georeferenced **before** export, or always local? | Hardening cell U13: export XMP in an original georeferenced zone scene and compare positions to the flight-log UTM. ~5 min on zone_3 (124 images). Also read `xcr:ExportCoordinateSystemType` from the same files. |
| **Q11** | **Largely answered 2026-08-04: the key is `inpAspect`**, found in the binary's `inp*` pool between `inpPPX` and `inpSkew` (§6.6); the Help's duplicate `inpSkew` row is a copy-paste error. What remains is only whether `-editInputSelection` *accepts* it. | `-editInputSelection "inpAspect=1.5"` on a selected image, then check `%LOCALAPPDATA%\Temp\RealityScan.log` for `err:7155` ("Parsing setting … failed"). Seconds; no align needed. Confirm positively with an align + `-exportXMP` read of `xcr:AspectRatio`. |
| **Q12** | Does Epic's ungroup-and-re-align refinement (group → align → ungroup → align) improve this rig? | Z3 fixture (124 images, ~4 min/align): align grouped, then `-removeCalibrationGroups` + `-align`, compare registration, component count and solved focal spread. ~10 min total. |
| **Q13** | **Does the repo's `Camera:`-namespaced element-form sidecar do anything at all?** Also settles §7.5's attribution: cell (c) declaring `xcr:DistortionModel="brown3"` under a global `sfmDistortionModel=Division` distinguishes "the global key wins" from "the repo's sidecar was never parsed". | Z3 fixture (124 images, ~4 min/align), three cells, one variable each: (a) no sidecars, (b) current repo-form sidecars, (c) documented attribute form under `.../ns/xcr/1.1#` with `xcr:CalibrationPrior="initial"`, `xcr:CalibrationGroup`, `xcr:DistortionGroup`, `xcr:FocalLength35mm`, `xcr:DistortionModel`. Compare registration, component count, the exported `xcr:DistortionModel`, and the **spread** of solved focal within each camera (a real group forces one focal; ungrouped self-calibration does not — the ±0.5 % IQR of §7.4 is the number to beat). Grep each run's `RealityScan.log` snapshot for `Skipping unexpected attribute` / `Skipping unexpected tag`. ~15 min total. **Highest-value probe in this document.** |
| **Q14** | Is the 3,740→3,738 fusion deficit a real solver drop or a harvest artifact? | Re-import `cluster_*_m_c0.rsalign` **from its original export location** into a spare instance and census it: 3,740 means accounting artifact, 3,738 means real loss. Uses artifacts already on disk. (Reading the count from `rslog.txt` is **not** trustworthy on these artifacts — see the log-splice finding in `01-cli-fundamentals.md`.) |
| **Q15** | What do the `xmpCamera` integers mean, and what does the default (unpinned) export mode write? | Export XMP three times from the smoke fixture with `xmpCamera` 1/2/3 in a params XML, and once with no params; read `xcr:PosePrior` from the results. ~4 min. Settles Q16 as a side effect. |
| **Q16** | What `xcr:PosePrior` value does this pipeline's production export actually write — and therefore how hard is the contamination in §10? | Covered by Q15's "no params" cell; or simply grep any existing `identity_r*` directory on the data drives for `PosePrior`. Zero cost if those artifacts still exist. |
| **Q17** | Is "Prefer Exif over XMP" settable from the CLI, under which spelling, and what is its default? The binary has `AppPreferExif` (capital `A`, matching an internal family) but not `appPreferExif` (lowercase, matching every documented `-set` key). | Boot once with both: `-set "AppPreferExif=false" -set "appPreferExif=false"`, then read `%LOCALAPPDATA%\Temp\RealityScan.log` for `err:7155` — whichever spelling does **not** produce a parse failure is the key. Seconds. Snapshot the log immediately: the next boot destroys it (NA167 B6). |
| **Q18** | Precedence between a `sensorsdb.xml` entry and an XMP sidecar for the same image | Add a DB entry for the smoke fixture's camera model with a deliberately wrong `focal`, plus a sidecar with the right one; align and read the solved value. ~5 min plus a ProgramData edit (back the file up first). |
| **Q19** | Does `-exportUndistortedImages` / `-exportSTMap` work headless, and at what cost — and which spelling of the undistort command does the parser accept (`exportUndistortedImages` per `allcommands` vs `exportUndistoredImages` per `commandline_1`, §14)? | The spelling half is free: issue both at boot on an empty scene and read `RealityScan.log` — an unknown command is reported, a known one is not. The functional half is blocked on Q20 (`-exportSTMap` alone may run with no params at all, since the Help says both of its arguments are optional). |
| **Q20** | Obtain a valid Export Registration params XML | One GUI session: open any aligned project, Export Registration → "RealityScan XMPs with Image List" → configure → save the params. Unblocks Q7, Q8, Q9, Q19 and makes `-exportRegistration` usable headless at all. **Cheapest single action with the widest unblocking effect in this document.** |

## Addenda — reconciled from `FINDINGS.md`, 2026-09-05

Facts established after this document was written (2026-08-04), carried here so the manual stays the document of record. Each keeps the FINDINGS date as its citation; the raw entry has the full observation.

### A1. Same-name sidecar auto-import is reliable enough to poison a run and not reliable enough to deliver a prior

Owner field finding (2026-08-08), matched by this repo's own record (NA167 #3 sidecars never loaded; H2023 harvest gap left 17.5% of a zone sidecar-less; the 2026-08-08 hygiene collision): implicit `<stem>.xmp` pairing depends on add/import-time state (`appGroupCalibrationByExif`, the GUI's "Prefer Exif over XMP") and fails silently. §10 still holds — leftover pose sidecars DO auto-import as priors. Decision: calibration priors, when used, ride explicit commands (`-addImageWithCalibration <image> <xmp>` from a separate directory; groups via `-setPrior*`), never same-name auto-import. [VERIFIED: FINDINGS 2026-08-08]

### A2. Exported XMPs write `CalibrationPrior="exact"` regardless of the input prior

The export field reflects the export mode, not the prior that drove the solve (B7 semantics). Never census prior MODE from exported sidecars; census the group echo and solved-focal equality. [VERIFIED: FINDINGS 2026-08-08]
