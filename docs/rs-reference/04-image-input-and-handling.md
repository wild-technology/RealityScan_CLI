# Image input, image lists, selection, layers, masks

This document covers everything that happens between "images exist on disk" and "the
scene holds the inputs you intended": every RealityScan 2.2 CLI command that puts an
image, video frame, LiDAR scan or HDR frame into a scene; the exact `.imagelist` file
format; how RealityScan establishes an image's *identity* (by path) and what that means
for copies, hardlinks, junctions and cross-component merging; the image-selection command
family and every per-image property reachable from the CLI; calibration and lens groups;
image layers; masks and depth/normal map export; and the on-disk preprocessing this
repository proved is mandatory for underwater imagery.

It does **not** cover: the `-set` key space itself (`03-settings-keys.md`); flight-log /
trajectory import, CRS handling and scale (`06-georeferencing-flightlogs-and-scale.md`);
alignment behaviour (`07-alignment.md`); component semantics and `-mergeComponents`
(`08-components-and-merge.md`); XMP *pose* export, sidecar naming and the registration
census (`05-metadata-xmp-and-sidecars.md`); rigs and the full prior taxonomy
(`13-camera-rigs-priors-and-orientation.md`); the params-XML schemas as files
(`09-xml-parameter-files.md`); or model, texture and deliverable export
(`10-reconstruction-texturing-export.md`). Executable discovery, delegation and the `:run`
pattern are in `01-cli-fundamentals.md`; the full command inventory is
`02-command-reference.md`.

**Applies to:** RealityScan 2.2 (Epic Games), Windows, headless CLI operation.
**Tags:** [OFFICIAL] shipped Help · [VERIFIED] measured in production here ·
[CONTRADICTED] docs vs observation · [UNDOCUMENTED] · [INFERRED] · [OPEN]

---

## Contents

1. [What "adding an input" means](#1-what-adding-an-input-means)
2. [`-add` — single files and image lists](#2--add--single-files-and-image-lists)
3. [The `.imagelist` file format](#3-the-imagelist-file-format)
4. [`-addFolder` and `appIncSubdirs`](#4--addfolder-and-appincsubdirs)
5. [XMP sidecar auto-import on add](#5-xmp-sidecar-auto-import-on-add)
6. [`-addImageWithCalibration`](#6--addimagewithcalibration)
7. [`-importVideo` and frame extraction](#7--importvideo-and-frame-extraction)
8. [`-importLeicaBlk3D`](#8--importleicablk3d)
9. [LiDAR: `-importLaserScan` / `-importLaserScanFolder`](#9-lidar--importlaserscan---importlaserscanfolder)
10. [`-importHDRimages` — 16-bit and HDR](#10--importhdrimages--16-bit-and-hdr)
11. [`-importImageSelection`](#11--importimageselection)
12. [**Image identity is PATH identity**](#12-image-identity-is-path-identity)
13. [Selection commands](#13-selection-commands)
14. [Commands for Selected Images](#14-commands-for-selected-images)
15. [`-editInputSelection` — the master per-image control](#15--editinputselection--the-master-per-image-control)
16. [Calibration groups and lens groups](#16-calibration-groups-and-lens-groups)
17. [Image layers](#17-image-layers)
18. [Masks](#18-masks)
19. [Depth, normal and mask map export](#19-depth-normal-and-mask-map-export)
20. [Image resolution, downscale and quality settings](#20-image-resolution-downscale-and-quality-settings)
21. [Preprocessing images BEFORE import](#21-preprocessing-images-before-import)
22. [Measured scale and cost figures](#22-measured-scale-and-cost-figures)
23. [Failure-signature quick table](#23-failure-signature-quick-table)
24. [Open questions](#24-open-questions)

---

## 1. What "adding an input" means

RealityScan calls every scene member an **input**: images, video frames, LiDAR scans
(converted to `.lsp`), HDR frames (converted to `.geometry.jpg`). All of them appear in
the 1Ds view under `Images`, all of them are selectable with the same selection commands,
and all of them accept the same per-input properties.
[OFFICIAL: appbasics/selectedinputs, tutorials/laserandimages]

| Command | Adds | Notes |
|---|---|---|
| `-add <imageName>` | one image, or every path in an `.imagelist` | §2 |
| `-addFolder <folderName>` | every image in a folder; subdirectories only with `appIncSubdirs=true` | §4 |
| `-addImageWithCalibration <fileName> <xmpFileName>` | one image + one XMP, names/folders may differ | §6 |
| `-importVideo <videoFileName> <extractedVideoFramesLocation> <jumpsLength>` | extracted key frames (PNG) | §7 |
| `-importLeicaBlk3D <fileName>` | a `.cmi` BLK3D image sequence | §8 |
| `-importLaserScan <laserscanName> [params.xml]` | one LiDAR scan or scan list | §9 |
| `-importLaserScanFolder <folderName> [params.xml]` | every LiDAR scan in a folder | §9 |
| `-importHDRimages <fileName\|folderName\|imageList> [params.xml]` | 16-bit/HDR images, tone-mapped | §10 |
| `-importImageSelection <fileName>` | **nothing** — selects existing scene inputs | §11 |
| `-importCache <folderName>` | resource cache data (depth maps precomputed elsewhere) | not an input; see the cache/fundamentals document |

[OFFICIAL: appbasics/allcommands "Project and Images"; tutorials/commandline]

**Command-name spelling traps** (case matters, these are literal):
`-importHDRimages` (capital `HDR`, lowercase `images`), `-importLeicaBlk3D` (lowercase
`lk`, capital `B` and `3D`), `-addImageWithCalibration`, `-importImageSelection`.
[OFFICIAL: appbasics/allcommands]

---

## 2. `-add` — single files and image lists

```
-add <imageName>
```

> "Import one or more images from a specified file path or from an image list. The image
> list is a text file with the `.imagelist` extension, containing full paths to the
> images, each on a separate line." [OFFICIAL: appbasics/allcommands; tutorials/commandline]

Epic's own example, verbatim in shape [OFFICIAL: tutorials/commandline]:

```bat
set PATH=%PATH%;C:\Program Files\Epic Games\RealityScan\
set MyPath=C:\MyFolder
RealityScan.exe -load %MyPath%\PlainProject.rsproj ^
  -add %MyPath%\images.imagelist ^
  -add %MyPath%\Images\image_123.jpg ^
  -save %MyPath%\MyProject.rsproj -quit
```

**The Help's install path is not this machine's.** Every Help example writes
`C:\Program Files\Epic Games\RealityScan\`; the 2.2 install here is
`C:\Program Files\Epic Games\RealityScan_2.2\`. Never copy Epic's `set PATH` line
literally — resolve the executable the way `01-cli-fundamentals.md` describes.
[VERIFIED-by-inspection, 2026-08-04]

Production shape used here (delegated, one image list per zone, images referenced at
their **original** paths so components share cameras by identity) — `:run` is the shared
delegate + double-`-waitCompleted` + errors-marker subroutine every workflow uses:

```bat
:: RS_CLI\Scripts\AlignImageList.bat
call :run -newScene || goto :fail
call :run -add "F:\na156_h2024_v2\lists\zone_1.imagelist" || goto :fail
call :run -importFlightLog "F:\na156_h2024_v2\batched_images_by_zone\zone_1\flight_log_53N_UTM.txt" ^
                           "%Metadata%\FlightLogParams.xml" || goto :fail
call :run -align || goto :fail
```

Established behaviour:

- **`-add` works as documented; CRLF line endings in the list are fine.**
  [VERIFIED: NA167 wave-1 A2 cells, 2026-07-23]
- **Registration is independent of how images were added.** Folder vs image list on
  identical zones: zone_6 95.2 % (A1, `-addFolder`) vs 95.3 % (A2, `.imagelist`);
  zone_4 90.1 % vs 91.0 %. Runtime differed (61.6 vs 97.8 min on zone_6, 24.3 vs 20.8 min
  on zone_4) but in both directions — that is scene-character variance, not an input-method
  effect. [VERIFIED: NA167 A1/A2, 2026-07-23]
- **This is the mechanism for shared-path components** — the only way to build two scenes
  whose components hold the *same* camera identities without duplicating pixels. See §12.
  [VERIFIED: NA167_SESSION_NOTES §"Project & image input"]
- Adding images **auto-imports `<stem>.xmp` sidecars found next to them**; see §5.
  [VERIFIED: NA167 B7, 2026-07-22]

[OPEN] Whether `-add` accepts a directory path (i.e. behaves as `-addFolder`) is
untested. Cheapest probe: `-add "F:\...\zone_1"` on the smoke fixture and read
`Added N layer images` out of `%LOCALAPPDATA%\Temp\RealityScan.log`.

[OPEN] Whether a list file with an extension other than `.imagelist` is accepted. The
Help states the extension as part of the format. Cheapest probe: copy a working list to
`zone_1.txt`, `-add` it, and compare the added count.

---

## 3. The `.imagelist` file format

| Property | Value | Source |
|---|---|---|
| Extension | `.imagelist` | [OFFICIAL: appbasics/allcommands] |
| Content | one **full** path per line | [OFFICIAL: appbasics/allcommands] |
| Line endings | CRLF confirmed working | [VERIFIED: NA167 A2, 2026-07-23] |
| LF endings | untested against RealityScan | [OPEN] |
| Encoding used in production here | ASCII, no BOM | [VERIFIED-by-inspection: `grow_zone.py` `write_imagelist`] |
| Relative paths | untested | [OPEN] |
| Comments / blank lines | not documented, never tried | [OPEN] |
| May also contain LiDAR scans | yes, per the image-list export description | [OFFICIAL: appbasics/multiselect] |

Canonical writer in this repository (`grow_zone.py`), reproduced because the encoding and
newline choices are load-bearing:

```python
def write_imagelist(path: str, basenames: set[str],
                    basename_index: dict[str, str], logger) -> int:
    """Full image paths, one per line, ASCII + CRLF (cmd's for /f reads
    the file as ANSI bytes; every path in this pipeline is ASCII by
    convention - non-ASCII paths fail loudly here rather than corrupting
    the selection)."""
    ...
    with open(path, 'w', encoding='ascii', newline='\r\n') as f:
        f.write('\n'.join(lines) + '\n')
```

The ASCII constraint is **not** a RealityScan requirement — it is a constraint of this
repo's own consumers: the same list files are re-read by `cmd`'s `for /f` in
`GrowZone.bat :selectFromList` (§13.4), which reads bytes in the console ANSI codepage.
A non-ASCII path would corrupt the selection loop silently, so the writer raises
`UnicodeEncodeError` instead. Whether RealityScan's own list reader accepts UTF-8 is
[OPEN]. [VERIFIED-by-inspection: `grow_zone.py :: write_imagelist`, 2026-08-04]

Example content (real path shape, per-camera subfolders under a zone):

```
F:\na156_h2024_v2\batched_images_by_zone\zone_1\cinema\C231C4652_20231104213612_edt.jpg
F:\na156_h2024_v2\batched_images_by_zone\zone_1\cinema\C231C5220_20231104220104_edt.jpg
F:\na156_h2024_v2\batched_images_by_zone\zone_1\port\P231C4655_20231104213614_edt.jpg
```

**BOM trap.** Windows PowerShell 5.1 `Set-Content -Encoding utf8` writes a UTF-8 BOM.
A BOM on line 1 of a `.complist` was measured to silently invalidate the first entry
(the consumer read `\ufeffF:\...\zone_1_c6.rsalign`, found no matching manifest and
aborted); the first three bytes were confirmed as 239,187,191. Python's
`open(..., encoding='utf-8')` writes no BOM.
[VERIFIED for `.complist`: FINDINGS 2026-07-27]
[INFERRED for `.imagelist`: the same PowerShell writer produces the same byte pattern, and
this repo's `.imagelist` files are additionally re-read by `cmd`'s `for /f` in
`GrowZone.bat :selectFromList`, where a BOM would corrupt the first path. Not measured
against RealityScan's own list reader — settle it by writing a BOM'd list and comparing
the added-image count.]
Safe PowerShell writer:

```powershell
[System.IO.File]::WriteAllLines($p, $lines, (New-Object System.Text.UTF8Encoding($false)))
```

**Never pass the list contents as `.bat` arguments.** `cmd` splits unquoted `;` `,` `=`
into separate arguments and Python's `subprocess` quotes only on whitespace. Lists cross
the process boundary as **files** (`.imagelist`, `.complist`); settings cross as
`key:value` and the workflow converts the colon inside the `.bat`.
[VERIFIED: NA167 B5 / FINDINGS 2026-07-23]

---

## 4. `-addFolder` and `appIncSubdirs`

```
-addFolder <folderName>
-set "appIncSubdirs=true"
```

> "Add all images in the specified folder. In order to include also subdirectories, use
> command set with a key `appIncSubdirs` as follows: `-set "appIncSubdirs=true"`."
> [OFFICIAL: tutorials/commandline — verbatim]

The master table words the same row differently: *"Add all images **to** the specified
folder. To include subdirectories, use the command set with a key appIncSubdirs …"*
[OFFICIAL: appbasics/allcommands]. The "to" is a defect in Epic's prose — `-addFolder`
reads from the folder, it does not write to it; both pages ship in the same build.

| Key | Type | Default | Scope | Source |
|---|---|---|---|---|
| `appIncSubdirs` | bool | `false` | "relevant for: addFolder command" | [OFFICIAL: tutorials/setkeyvaluetable] |

### 4.1 The subdirectory contradiction — resolved as flag-dependent, not build-dependent

Two in-repo observations disagreed:

- **NA167 zone_13**: a `-addFolder` over a tree containing `wca\` and `zeuss\`
  subfolders imported **both** (34 + 904 images into one scene, 93.4 % registered) and
  the session notes recorded "subfolders were included **without** setting the key".
  [VERIFIED-as-observation: NA167 #5, 2026-07-22]
- **H2023 zone_1 / zone_2**: `-addFolder` over a tree whose images sat in per-camera and
  `preprocessed_images` subfolders added **`Added 0 layer images`**, after which every
  flight-log row failed `err:18002`. The run exited "successfully" in 25 s; the cause was
  visible only in the `RealityScan.log` snapshot.
  [VERIFIED: FINDINGS 2026-07-23]

[CONTRADICTED] Docs present `appIncSubdirs` as an opt-in convenience with default
`false`; one in-house run appeared to recurse without it. **Resolution adopted:** the
NA167 run had the key set by the fixed workflow — the *flag*, not the build, was the
variable. `MERGE_TEST_PLAN.md`'s earlier "recursed without the key" note is superseded.
**Set `appIncSubdirs=true` before every `-addFolder`, unconditionally.**
[VERIFIED-as-policy: FINDINGS 2026-07-23]

Production pattern (`AlignZone.bat`) — note the `-set` is fired *without* a completion
wait, because delegated commands execute FIFO and `-set` is instant:

```bat
%RealityScan% -delegateTo %RS_INSTANCE% -set "appIncSubdirs=true"
call :run -addFolder "F:\na156_h2024_v2\batched_images_by_zone\zone_1" || goto :fail
```

### 4.2 Other observed `-addFolder` facts

- **A routine successful `-addFolder` reports process result `1`** through the
  `appProcessAction=ExecuteProgram` completion hook. Result codes **0 and 1 are both
  success** and must both be whitelisted; anything else lands in the errors marker.
  [VERIFIED: FINDINGS 2026-07-21; `RS_CLI/Errors/ErrorWriter.bat`]
- The only reliable "how many did it add?" readout is the line `Added N layer images` in
  `%LOCALAPPDATA%\Temp\RealityScan.log`, which is **truncated on every instance boot** —
  snapshot it inside the driver immediately after the call returns.
  [VERIFIED: NA167 #16 / B6, 2026-07-23]
- **Per-camera zone subfolders are one alignment scene, not several.** Pre-overhaul code
  aligned each camera subfolder as a separate scene, defeating mixed-camera
  co-registration. One `-addFolder` at the zone root with `appIncSubdirs=true` is correct.
  [VERIFIED: NA167 #5 + 2026-07-22 fix pass]
- **Beware layer-token folder names.** RealityScan assigns image layers from *folder*
  names when they begin with one of the separators `.` `_` `@` `#` `!` followed by a
  layer token (`geometry`, `mask`, `labels`, `depth`, `textureNN`) — see §17. A camera
  subfolder must therefore never be named e.g. `_texture` or `.mask`. This repo's
  subfolders (`cinema`, `port`, `starboard`, `zeuss`) are safe.
  [INFERRED from the layer-naming rules in tools/imglayers; not tested — settle it by
  creating a `_mask\` subfolder of JPGs and checking whether they arrive as inputs or as
  a mask layer]

---

## 5. XMP sidecar auto-import on add

> "The XMP files are directly connected to the images. If placed in the same folder, an
> image and an XMP file with the same name will act as one when imported into RealityScan.
> All information from the XMP file will automatically be assigned to the corresponding
> image." [OFFICIAL: tools/xmpalign]

> "An image should have the same name as its XMP counterpart. For example, to assign an
> XMP file to an image named `Image01.jpg`, the XMP file should be named `Image01.xmp`."
> [OFFICIAL: tools/xmpalign]

> TIP: "You can add one XMP file named `_common.xmp` to the folder with your images to
> import all of them with the same XMP information." [OFFICIAL: tools/xmpalign]

Established here:

- **The sidecar name must be `<stem>.xmp`** — Epic states the rule, but not the
  consequence of breaking it. **`image.jpg.xmp` is ignored SILENTLY**: no warning, no
  log line, no error. A batcher bug wrote priors that way, so **no historical run before
  2026-07-22 ever loaded its calibration priors**. Discovered by an arithmetic anomaly in
  sidecar counts (871 "new" `.xmp` appeared in a folder that already held 904).
  [OFFICIAL for the rule: tools/xmpalign]
  [VERIFIED for the silent failure: NA167 #3 / B7, 2026-07-22; testing/FINDINGS.md]
- **Pose-bearing sidecars become exact-pose priors silently** on any later `-add` /
  `-addFolder` of the same images — cross-run contamination unless the tree is cleaned.
  The pipeline sanitises every sidecar back to calibration-only content after each census
  (`camera_registry.sanitize_and_census`). [VERIFIED: NA167 B7]
  [UNDOCUMENTED: the Help does not warn that an exported pose sidecar re-imports as a prior]
- **Ordinal sidecars (`00000.xmp`, `00001.xmp`, …) are inert as priors** — no image has an
  ordinal stem — and are deleted quietly by the sanitiser.
  [VERIFIED: NA167 B10, 2026-07-23]
- The GUI carries an app setting **"Prefer Exif over XMP"** ("When importing new files,
  Exif metadata takes priority over XMP metadata if this setting is enabled")
  [OFFICIAL: appbasics/appsettings]. **No `-set` key for it appears in
  `tutorials/setkeyvaluetable` or anywhere in this repo's key inventory.**
  [OPEN — cheapest probe: toggle it in the GUI, save the app settings, and diff; or dump
  the binary's key strings]
- Related import-time app keys that *do* have documented CLI names:

| Key | Type | Default | Effect | Source |
|---|---|---|---|---|
| `appGroupCalibrationByExif` | bool | `false` | group calibration automatically from EXIF at add time | [OFFICIAL: setkeyvaluetable, appbasics/appsettings] |
| `appIgnoreExifGPS` | bool | `false` | globally ignore EXIF GPS; a per-camera override exists in `sensorsdb.xml` (§16.3) | [OFFICIAL: setkeyvaluetable, appbasics/appsettings, appbasics/cameradb] |
| `appCopyImportedComponentsToCache` | bool | `false` | copy imported components into the cache (an SSD-cache speed option) | [OFFICIAL: setkeyvaluetable] |

The GUI additionally exposes **"Use relative image paths"** ("the input paths in the
project file (.rsproj) will be saved with relative paths") [OFFICIAL: appbasics/appsettings]
with no documented CLI key. [OPEN] This one matters for §12 — relative paths would change
what a relocated `.rsproj` resolves to.

XMP content shape (Epic's own sample; outer `x:xmpmeta`/`rdf:RDF` wrappers elided, the
`rdf:Description` attribute set is complete and literal) [OFFICIAL: tools/xmpalign]:

```xml
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
```

Note `xcr:DistortionCoeficients` — one `f`. That misspelling is the product's own and must
be reproduced exactly. The three `xcr:Rig*` attributes are the rig declaration; they are
out of scope here — see `13-camera-rigs-priors-and-orientation.md` for the full attribute
table and `05-metadata-xmp-and-sidecars.md` for export naming.

The calibration-only sidecar this repo writes (no pose entries, deliberately) uses the
`Camera:` namespace instead; see §16.4.

---

## 6. `-addImageWithCalibration`

```
-addImageWithCalibration <fileName> <xmpFileName>
```

> "Import an image as well as the corresponding XMP file. Use whole paths to the files."
> [OFFICIAL: appbasics/allcommands]
> "In this case, the two files don't have to have the same name or be placed in the same
> folder." [OFFICIAL: tools/xmpalign]

This is the **only** way to attach an XMP whose name or location differs from the image's.
It is the natural fit for a scheme that keeps priors out of the image tree entirely —
which would sidestep the sidecar-contamination problem in §5 and the sidecar-stripping
defect in §16.5.

```bat
%RealityScan% -delegateTo RS1 -addImageWithCalibration ^
  "F:\H2024\Images\edited\C231C4652_20231104213612_edt.jpg" ^
  "F:\H2024\priors\cinema.xmp"
```

[OPEN] Never exercised in this repository — 8,000-camera scenes are added by folder or by
image list, and one delegated command per image at ~0.1–0.3 s each (the measured cost of
`-selectImage`, §13.4) would take tens of minutes. Unknown: whether one XMP may be reused
across many images this way (the example above assumes it can), and whether it composes
with `-add`-style lists. Cheapest probe: two calls on the smoke fixture pointing at the
same `cinema.xmp`, then read the resulting calibration group off an exported pose XMP.

---

## 7. `-importVideo` and frame extraction

```
-importVideo <videoFileName> <extractedVideoFramesLocation> <jumpsLength>
```

> "Import frames extracted from a video (`videoFileName` including the path). The frames
> are extracted into a folder (`extractedVideoFramesLocation`) using an interval between
> frames defined by the `jumpsLength` (**in seconds**)." [OFFICIAL: appbasics/allcommands]

| Fact | Value | Source |
|---|---|---|
| Extraction policy | **key frames only**; interpolated (codec-synthesised, geometrically inaccurate) frames are ignored | [OFFICIAL: tools/videoimport] |
| Output frame format | **PNG** | [OFFICIAL: tools/videoimport] |
| Formats readable with the stock Windows codec pack | `.asf`, `.avi`, `.mov`, `.mpg`, `.mpeg`, `.mp4`, `.wmv` | [OFFICIAL: tools/videoimport] |
| Number of videos | unlimited | [OFFICIAL: tools/videoimport] |
| Process ID | `24848 IMPORT_VIDEO` | [OFFICIAL: tutorials/processids] |
| Frames land in | the 1Ds `Images` root, already imported | [OFFICIAL: tools/videoimport] |

Because extraction keeps only key frames, the *effective* frame spacing is
`jumpsLength` **or coarser** — the command cannot manufacture a key frame that the codec
did not write. [INFERRED from the two Help statements read together; not measured.]

**Do not confuse RealityScan's extractor with this repo's.** This pipeline extracts frames
itself (`Extract Images` module) and had its own defect: **extracted frames were
timestamped ONE OUTPUT INTERVAL EARLY** (60 s at 1 frame/minute) because frame seek and
timestamp source used different frame indices, confirmed with a synthetic per-frame-gray
video. Any dataset produced by the old `__extract_video_cv2` carries the offset.
**That is a repo bug, not a RealityScan bug** — `-importVideo` has never been driven here.
[VERIFIED: NA167 #1, 2026-07-22] [OPEN: whether `-importVideo`'s own frame timestamps are
correct is untested — same synthetic-gray-video probe would settle it]

---

## 8. `-importLeicaBlk3D`

```
-importLeicaBlk3D <fileName>
```

> "Import image sequence with `.cmi` extension (fileName including path) captured by
> Leica BLK3D." [OFFICIAL: appbasics/allcommands] Process ID `21808 IMPORT_LEICA_BLK3D`.

The BLK3D is a two-camera device with a **known baseline**, so "RealityScan can use this
kind of data to automatically scale your model without needing any further actions or
input"; other, unscaled inputs aligned together with it inherit the scale.
[OFFICIAL: tools/videoimport] The settings dialog is skipped for `.cmi` import.

Relevance here: this is the only *documented* automatic metric-scale source that is not a
GCP, a distance constraint or a locked XMP.

[CONTRADICTED — second-hand claim vs shipped schema] Epic staff are reported to have
confirmed (through Aug 2025) that RealityScan has **no stereo-rig support**, so a
fixed-baseline ROV rig cannot get BLK3D-style automatic scale
[VERIFIED-second-hand: COLMAP fact base F-20260723-27, quoted in
`docs/COLMAP_CROSSOVER.md` §4 and HANDOFF; recorded 2026-07-24, not reproduced here].
But the shipped build plainly *has* rig constructs: the XMP schema carries `xcr:Rig`,
`xcr:RigInstance` and `xcr:RigPoseIndex` [OFFICIAL: tools/xmpalign], the Selected Input
panel has a **Rigging** section (Rig ID / Prior / Model) and a **Relative coordinates**
field described as "visible only for the inputs that are connected in a rig (e.g.
individual `.lsp` files in one LiDAR scanner position, **or images with exact or locked
XMP files**)" [OFFICIAL: appbasics/selectedinputs]. The honest reading: rig *plumbing*
exists and is reachable from XMP; what is missing is an automatic
baseline-derived-scale path for image rigs. Neither has been tested here — see
`13-camera-rigs-priors-and-orientation.md` §3 for the rig attribute table and the open
probe. Never exercised in this repository.

---

## 9. LiDAR: `-importLaserScan` / `-importLaserScanFolder`

```
-importLaserScan       <laserscanName> [params.xml]
-importLaserScanFolder <folderName>    [params.xml]
```

> "Add a LiDAR scan or a LiDAR scan list using the current settings or the settings from
> the `params.xml` file (optional parameter). You can export these settings from the
> application in the LiDAR Scan Import dialog." [OFFICIAL: appbasics/allcommands]

The master table lists `params.xml` as optional for the folder form while the prose says
"using settings from the params.xml file" — treat it as optional but always supply one,
because the defaults are unknowable headless. Obtaining the XML **requires the GUI once**;
this is the general rule for every params-file-taking command in RealityScan.
[VERIFIED-as-practice: FINDINGS 2026-07-21]
Process ID `20592 IMPORT_LASER_SCAN`.

**Internal format.** Import converts scans into `.lsp` files, "an internal format which
resemble images", stored beside the original data or at a custom path. Once imported,
**do not re-import the same scans for a new project** — that overwrites the existing LSP
files; add the `.lsp` files instead. [OFFICIAL: tutorials/importlaser]
From then on an `.lsp` behaves "exactly like an ordinary image": registration, meshing,
texturing and coloring are identical. [OFFICIAL: tutorials/importlaser_2, laserandimages]

**Supported source formats** [OFFICIAL: tutorials/importlaser]:

| Class | Formats |
|---|---|
| Terrestrial (ordered, scanner acquisition pattern preserved) | PTX, E57, PLY, ZFS / ZFPRJ |
| Mobile | LAS / LAZ, E57, PLY, CSV, XYZ, ASCII PTS |

**Import settings** (all from the LiDAR Scan Import dialog; these are the fields the
`params.xml` carries) [OFFICIAL: tutorials/importlaser]:

| Setting | Values / meaning |
|---|---|
| LiDAR type | `Terrestrial LiDAR` / `Mobile LiDAR`, auto-detected from the format; Epic advises not to change it |
| Registration | **Exact** (imported poses preserved; the imported model defines the scene coordinate system) · **Draft** (roughly registered, fine-tuned during alignment) · **Unregistered** (engine computes all poses) |
| Georeferenced | Yes/No |
| Coordinate system | required when Georeferenced = Yes |
| Features source | Color (default) or Intensity — used when registering photos to scans. For Z+F, use Color if `.jpg` files sit next to the sources |
| Noise profile | `Noise free`, `ScanStationP20`, or a user profile added to `noiseprofiles.xml` |
| Import classification | LAS/LAZ only; classes appear under `LiDAR Classification` in 1Ds |
| Output path | same directory as the source, or Custom |
| Custom path | LSP destination when Output path = Custom |

Mobile-only virtual-camera settings: `Use camera poses` (from prior poses / from an
existing component / generated), `Extract from component`, `Height reference`,
`Camera height`, `Camera overlap percentage`, `Camera cluster` (1 camera / 1 + 4 off-nadir
/ 6 as for terrestrial), `Off-nadir camera angle`.

**`noiseprofiles.xml` schema** — `C:\Program Files\Epic Games\RealityScan_2.2\noiseprofiles.xml`,
read directly [VERIFIED-by-inspection, 2026-08-04]. The file ships exactly two profiles:

```xml
<NoiseProfiles>
    <profile desc="Noise free" width="1" height="1" quality="100">
        <distances>0</distances>
        <intensities>0</intensities>
        <noiseFactors>0.0</noiseFactors>
    </profile>
    <profile desc="ScanStationP20" width="8" height="8" quality="4">
        <distances> 0 1 5 10 20 30 50 150</distances>
        <intensities> 0 0.001 0.005 0.01 0.05 0.1 0.5 1.0</intensities>
        <noiseFactors> ... 8x8 matrix ... </noiseFactors>
        <qualityFactors> ... 8x8 matrix ... </qualityFactors>
    </profile>
</NoiseProfiles>
```

| Attribute / element | Meaning |
|---|---|
| `desc` | name shown in the import dialog's Noise profile list |
| `width` / `height` | dimensions of the `noiseFactors` / `qualityFactors` matrices; `width` = number of `intensities`, `height` = number of `distances` |
| `quality` | scalar quality figure for the profile (`100` for noise-free, `4` for the P20) |
| `<distances>` | distance breakpoints from the scanner station, in project distance units |
| `<intensities>` | return-intensity breakpoints, 0..1 |
| `<noiseFactors>` | `height` rows × `width` columns; noise magnitude at each (distance, intensity) cell |
| `<qualityFactors>` | same grid; per-cell weight, 0..1 |

The `width`/`height` ↔ `distances`/`intensities` mapping is [INFERRED] from the shipped
data (8 distances, 8 intensities, 8×8 matrices, `width=8 height=8`); Epic documents only
"define your own profile based on the LiDAR scanner technical documentation".

**Related `-set` key:**

| Key | Official name | Type | Documented default |
|---|---|---|---|
| `lisPreferImagesAsFeatureSource` | "Prefer images as feature source during import of Z+F scans" | bool | **`true`** |

[OFFICIAL: tutorials/setkeyvaluetable — Alignment Settings table]. The GUI control is
**Alignment settings ▸ Prefer images as feature source**; "By default, this feature is
enabled (set to 'Yes')". It lets `.zfprj` mosaic images act as the feature source, which
"might help to register the unregistered scans or to automatically find the same features
when merging scans with images". Choosing **Intensity** as the Features source suppresses
mosaic-image import from a `.zfprj` entirely. [OFFICIAL: tutorials/importlaser]

[CONTRADICTED — doc vs this repo's GUI export] The Help documents the default as `true`
in two independent places, yet the GUI-exported preset in force here,
`RS_CLI/Metadata/AlignmentParams.xml`, carries
`<entry key="lisPreferImagesAsFeatureSource" value="false"/>`
[VERIFIED-by-inspection, 2026-08-04]. Either the shipped default changed, the export
reflects a non-default profile, or the export writes a different default. It has never
mattered here (no LiDAR, no Z+F), and the key was declared a low-priority probe
(hardening cell E3) that was **never run**. Cheapest probe: export the alignment settings
from a clean GUI profile and read the value.

**Do not confuse** `lisPreferImagesAsFeatureSource` (scene-global, LiDAR-oriented) with
`-setFeatureSource` / `aligFeaturesMode` (per selected image, component-integration
strategy) — §14.1.

Nothing about LiDAR import has been exercised in this repository.

---

## 10. `-importHDRimages` — 16-bit and HDR

```
-importHDRimages <fileName|folderName|imageList> [params.xml]
```

> "Import HDR image (imageName), list of images (imageList) or all images from a folder
> (folderName) using the current settings or the settings from params.xml. You can export
> these settings from the application in the 16-bit/HDR Images Import dialog."
> [OFFICIAL: appbasics/allcommands]
Process IDs `21881 CLI_IMPORT_HDR_IMAGES` and `28677 IMPORT_HDR_IMAGES`.

Dialog fields carried by the params XML [OFFICIAL: tools/importhdr]:

| Field | Values |
|---|---|
| Tone-mapping method | **No tone mapping** (local Windows codec; converts 16-bit/HDR to 8-bit with no colour, contrast or gamma adjustment) · **RS tone mapping** (recommended, optimised for RealityScan) |
| Output path | **With original files** · **Custom** — destination for the converted files |

Behaviour:

- Import tone-maps and converts the inputs to JPEG **for processing only**; exported
  output still carries the full 16-bit/HDR information from the sources.
- The converted files are named `<original>.geometry.jpg` — i.e. **the image-layer
  geometry naming convention of §17**, which is why they attach to the originals rather
  than duplicating them.
- **The converted images are added to the open project automatically. Do not add them
  again.**
- Originals can also be processed without conversion by adding them like ordinary images
  and choosing **Original** in the prompt that appears — not usable headless, because that
  prompt is interactive.
[OFFICIAL: tools/importhdr]

[CONTRADICTED — doc-internal] `tools/importhdr` names the converted files
`.geometry.jpg` in one paragraph and `.base.jpg` two paragraphs later, in the same topic
of the same build. `.geometry.jpg` is the one consistent with `tools/imglayers`'s layer
grammar, so treat `.geometry.jpg` as correct. Cheapest probe: import one 16-bit TIFF and
list the output folder.

HDR texturing is a separate switch — **Prefer 16-bit/HDR textures generation = Yes** in
MESH & COLOR ▸ Color & Texture ▸ Settings, and **Export layer = Yes** for the *HDR Color
Layer* in the Export Model dialog. [OFFICIAL: tools/importhdr] Never exercised here.

---

## 11. `-importImageSelection`

```
-importImageSelection <fileName>
```

> "Select some scene images and/or LiDAR scans listed in a file (filename including the
> path)." [OFFICIAL: appbasics/allcommands] Process ID `20 IMPORT_IMAGE_SELECTION`.

**This command selects; it does not import.** The inputs must already be in the scene.
Its GUI twin is the **Image Selection** button in WORKFLOW ▸ Import Metadata, described as
"To import an image list (which may also contain LiDAR scans)". The matching *export* side
is ALIGNMENT ▸ Export ▸ Registration with the file type set to **Image list**, which "will
consist of all enabled or selected images and/or LiDAR scans in the project" and "creates a
new text file containing alphabetically ordered names of the images and/or LiDAR scans,
starting with their location on your drive". [OFFICIAL: appbasics/multiselect]

This is the **only documented bulk-selection primitive that does not cost one delegated
command per image**, and is therefore the obvious replacement for the per-image
`-selectImage` union loop of §13.4 — *if* it accepts a plain list of full paths.

[INFERRED] Because the Help presents export and import as the two halves of one artifact
("An image list can be exported… To import an image list…"), the accepted format is almost
certainly the export's: a plain text file, one full path per line, alphabetically ordered.
The Help never states the required **extension**, and it is not `.imagelist` by any
statement — `.imagelist` is documented only for `-add` (§3).

[OPEN] Never used here. Unknown: the accepted extension, whether it composes with a
modifier the way `-selectImage` does, and whether it replaces or unions with the current
selection. Cheapest probe (~2 min on the smoke fixture): write a 3-line file of full image
paths, `-importImageSelection` it, then `-editInputSelection "inpEnabled=false"` and
`-align`; a 3-image drop in the registered count proves the selection took.

---

## 12. Image identity is PATH identity

This is the most consequential and most expensively-learned section in this document.

### 12.1 The rule

**RealityScan identifies an image by its file path.** Everything downstream follows:

- A `.rsalign` component file **bakes the absolute image paths** of its cameras.
  Importing one from anywhere other than its original export location does not fail —
  it **hangs forever** in a `#timeout` state with no error and no minidump (≥ 6 h
  observed; in place the same import runs ~2 s per 0.7 GB).
  [VERIFIED: NA167 #11 / B1, 2026-07-23; CLAUDE.md hard rule 7]
- Two components share a *camera* exactly when the same path is present in both. That
  shared-camera set is the **deterministic** route `-mergeComponents` fuses through:
  cell D6 merged two zone_6 halves (749 + 342 cameras, **390 shared images**) in 56 min
  of real reconstruction ending "Finalizing 1 component".
  [VERIFIED: NA167 D6 / testing/MERGE_TEST_PLAN.md, 2026-07-24]
  It is **not the only** route — content overlap alone also fuses; see §12.5, which
  supersedes the "shared cameras are the ONLY mechanism" reading.
- **Basename, not path, is what the flight-log importer matches on** — bare filenames
  matched images living in `wca\` and `zeuss\` subfolders. So the two identity keys in a
  RealityScan scene are *not* the same key. [VERIFIED: NA167 #5, 2026-07-22]

### 12.2 The same basename appearing twice

Two physical files with the same basename at different paths are **two cameras** in the
scene and **one row** in the flight log. Measured consequences:

- A fused component's manifest `images` list is the **unique-basename union**, while the
  scene holds one camera per input **occurrence**: 880 cameras over 537 unique basenames
  in one measured assembly. Any per-camera arithmetic must therefore use the
  **concatenation** of the attributed input manifests' members, not the set union.
  [VERIFIED: FINDINGS 2026-07-28]
- **The 638-row flight-log gap**: a merge scene held 4,865 cameras but its union flight
  log only 4,227 rows, because the batcher **copies** overlap images into two zones —
  same basename, two physical files, one trajectory row.
  [VERIFIED: HANDOFF loose end #6]
- Importing a flight log whose rows reference images not in the scene raises
  `0x820000FF` / `err:18002` and is **benign** — verified once by matching all 102
  "not found" images against every component manifest: zero overlap, exactly the
  unregistered remainder (4,598 rows − 4,496 cameras = 102).
  [VERIFIED: FINDINGS 2026-07-25]

### 12.3 Copies vs hardlinks vs junctions

| Mechanism | Shares camera identity? | XMP sidecars written? | Recursive harvest sees them? | Verdict |
|---|---|---|---|---|
| **Separate copies** of the same pixels | **No** — different paths, different cameras | yes | yes | Works for alignment, **breaks merge-by-identity**, doubles disk, splits one trajectory row across two cameras |
| **Hardlinks** (same volume) | **Yes** — each link is a real path that resolves normally | **yes** | **yes** | **The verified fix.** 9,835 files, 35.8 GB logical, **0.05 GB actual**; `fsutil hardlink list` confirmed one inode per image |
| **Directory junctions** (reparse points) | paths resolve, but see below | **NO — silently** | **NO** (PowerShell 5.1) | **Never use.** Two independent failures, both silent |
| Symbolic links | untested | untested | untested | [OPEN] |

**The junction trap, in short** — this cost 5 h 12 min of correct GPU work plus 157 further
minutes chasing the wrong mechanism. Two independent, simultaneously true failures:

1. **WRITE side (the actual cause).** *RealityScan writes NO XMP sidecars when a scene's
   images resolve through a reparse point, and reports success.* Four baseline components
   on real paths harvested `identity_r0` = 267 files (= 116 + 94 + 57, exact); the same
   workflow on junction-rooted components harvested **zero**, silently, across 18 attempts,
   while the log said `Exporting Registration completed in 8.758 seconds`.
   [VERIFIED: FINDINGS 2026-07-27, "RESOLVED BY PROBE"] [UNDOCUMENTED: no Epic coverage of
   reparse-point behaviour]
2. **READ side (true, but not the cause).** PowerShell 5.1 `Get-ChildItem -Recurse` does
   not descend into junction **children**: 0 vs 9,835 `.xmp` on the same tree via its real
   path. It *does* resolve a junction it is pointed at directly, which is why the ALIGN
   harvest survived and the MERGE harvest died on the same tree with the same tool.
   [VERIFIED: FINDINGS 2026-07-27] [SUPERSEDED-as-cause: same day — a re-run with the real
   tree produced the identical `peel=[]` on all 18 attempts]

The full failure entry — every measurement, the false lead, the legitimate counter-case for
a junction on the *project* path, and the detection guard — is `F-57` in
`12-failure-modes-and-race-conditions.md`.

**Verified fix.** Replace per-zone junctions with **real directories of hardlinked
`.jpg`**, plus **copied** `.xmp` and flight logs. Sidecars are deliberately *not*
hardlinked — a shared inode would let a v2 write corrupt the baseline tree's sidecar.
Recursive enumeration went 0 → 9,835; a confirmation merge over three unchanged
components produced peel `[525, 392, 69, 64]` (exact subset sums) and `fused 3 → 1`
ACCEPTED. **No re-align was needed — the components were never the problem, only the paths
baked into them.** [VERIFIED: FINDINGS 2026-07-28]

Building the pool (Windows, native, no WSL):

```bat
:: hardlink every image of a zone into a real directory on the SAME VOLUME
mklink /H "F:\pool\zone_1\cinema\C231C4652_20231104213612_edt.jpg" ^
          "F:\H2024\Images\edited\C231C4652_20231104213612_edt.jpg"
:: verify one inode per image
fsutil hardlink list "F:\pool\zone_1\cinema\C231C4652_20231104213612_edt.jpg"
```

**Never** `mklink /J` (junction) or `mklink /D` for an image tree RealityScan will write
sidecars into.

Machine guard used here: `testing/run_h2024_v2.py :: assert_harvestable`, which walks the
image root recursively (a junction one level down blinds the harvest as completely as a
top-level one) and tests `st_reparse_tag`, because `os.path.islink()` is **False** for
Windows junctions on some Python builds. Reproduced in full in `F-57` of
`12-failure-modes-and-race-conditions.md`.

An **empty peel beside a non-empty export now ABORTS the run as an instrument failure**
rather than being scored as "nothing fused". [VERIFIED-as-fix: FINDINGS 2026-07-28]

### 12.4 Making one image resolvable from two components

Three routes, in decreasing order of confidence:

| Route | How | Status |
|---|---|---|
| **A. One physical tree, per-zone `.imagelist` files** | zones are *lists*, not folders; every scene `-add`s paths under one canonical root | [VERIFIED] `-add` list works, registration equals folder-mode (§2). This is `AlignImageList.bat`'s entire reason for existing |
| **B. One physical tree, per-zone folders of hardlinks** | keeps `-addFolder` ergonomics; each zone folder is a real directory of links | [VERIFIED] as an image-tree fix for the harvest chain (§12.3); **not** separately verified as a merge-identity mechanism, because a hardlink is a *distinct path* — see the warning below |
| **C. Per-zone copies** | what the batcher does today | [VERIFIED] as a **production defect** for the merge stage; queued, never applied to H2024 [OPEN: HANDOFF loose end #6] |

**Warning on route B.** A hardlink gives the same *inode* but a **different path**.
Everything in §12.1 says RealityScan keys on path, so two zones referencing the same image
through two different hardlink paths would present as two cameras, exactly like copies —
only cheaper on disk. The hardlink work in this repo solved the *sidecar/harvest* problem,
not the *identity* problem. [INFERRED — not measured. Cheapest probe: build two 60-image
scenes whose overlap is reached through two different hardlink paths, align both, import
both components into one scene and run `-mergeComponents`; a fuse (minutes of
reconstruction, "Finalizing 1 component") means inode identity is enough, an instant
success means it is not.] **Until that probe runs, route A is the only one that provably
delivers shared camera identity.**

### 12.5 What identity is *not* required for

Fusion is **content-driven** as well: the D7 probe fused two components sharing **zero
basenames and zero paths** but viewing the same wreck strip — `-mergeComponents` produced
one 120-camera component (78 + 42 exact, "Finalizing 1 component") both without any flight
log in the merge scene (70 s) and with a union log + `-update` (57 s).
Zero *content* overlap ⇒ silent no-fuse regardless of flags or logs.
[VERIFIED: FINDINGS "D7 RESOLVED", `testing/probe_d7.py`, 2026-07-24]
[SUPERSEDED: the earlier "shared cameras are the ONLY merge mechanism" and "camera
identity is path identity" conclusions — both were the correct reading of the pre-D7
evidence and are now known to be sufficient-but-not-necessary. Retained because the
shared-camera path remains the only route `-mergeComponents` can fuse through
deterministically.]

**Operational rule, the most repeated in this repository: verify every merge by pose-XMP
camera census, never by exit status.** [VERIFIED: NA167 #23]

---

## 13. Selection commands

Selection is scene state. It persists across delegated commands, it is consumed by the
whole "Commands for Selected Images" family (§14), and — critically — **it silently
constrains exports**.

| Command | Parameters | Effect | Source |
|---|---|---|---|
| `-selectImage` | `<imagePath\|regexp>` `[set\|union\|sub\|intersect\|toggle]` | select by path or regular expression | [OFFICIAL: appbasics/allcommands] |
| `-selectAllImages` | — | select all images in the project | [OFFICIAL] |
| `-deselectAllImages` | — | deselect all | [OFFICIAL] |
| `-invertImageSelection` | — | invert the current selection | [OFFICIAL] |
| `-importImageSelection` | `<fileName>` | select the inputs listed in a file (§11) | [OFFICIAL] |

Modifier semantics [OFFICIAL: tutorials/commandline]:

| Modifier | Meaning |
|---|---|
| `set` | select matches, deselect everything else. **Default when no modifier is given.** |
| `union` | add matches to the current selection |
| `sub` | deselect matches that are currently selected |
| `intersect` | keep only currently-selected images that also match |
| `toggle` | invert the selected state of every match |

Process ID `21884 CLI_SELECT_IMAGE`.

### 13.1 The `-selectImage` regexp contradiction

**Documented.** Epic gives four regexp examples, **all of them in a `g/…/` delimiter
form** [OFFICIAL: tutorials/commandline]:

```
-selectImage D:\sample\Images\IMG_0018.JPG      :: direct path
-selectImage g/DSC/                             :: name contains "DSC"
-selectImage g/2.1/                             :: "2", any char, "1"  (e.g. image_1251.jpg)
-selectImage g/[02468]\.jpg/                    :: ends with an even digit + .jpg
-selectImage g/DSC.*[02468]\.jpg/               :: contains DSC and ends with an even digit + .jpg
```

**Observed in this 2.2 build.** `-selectImage` matches **LITERAL FULL PATHS ONLY**. Bare
regexp, dot-star-wrapped regexp, glob, and regexp with an explicit `set` modifier **all
silently select nothing**; a literal full path selects exactly its image. Established by
bisection probes U-SEL2 … U-SEL8.
[CONTRADICTED: FINDINGS 2026-07-23; H2023 cells U1/U19/U2]

**The unresolved part, and it is important.** The probe series is recorded as covering
"bare regexp, dot-star-wrapped regexp, glob, and regexp with an explicit `set` modifier".
**Every one of Epic's own examples uses the `g/…/` delimiters, and the notes do not record
that form being tried.** The NA167 session notes even suggest `-selectImage "P231C.*"` —
which is precisely the bare form measured *not* to work. So the honest state is:

- [VERIFIED] bare / wrapped / glob regexp forms select nothing.
- [OPEN] whether `-selectImage g/C231C/` works. **Cheapest probe (~1 min):** on any loaded
  zone scene, `-deselectAllImages`, then `-selectImage "g/C231C/"`, then
  `-editInputSelection "inpEnabled=false"`, `-save` to a scratch `.rsproj`, and compare
  the enabled count — or run the same two forms back to back and diff. If it works, the
  per-image union loop below becomes unnecessary for whole-camera-family selections and
  the `[CONTRADICTED]` tag downgrades to "the bare form is not accepted".
- [OPEN] and prior to the above: **is the pattern matched against the full path or the
  basename?** Epic's wording is "images defined by regular expression" and every example
  is a substring of a *name*, but the same command's other argument form is a full path.
  This decides whether `^`/`$` anchors are usable at all — anchoring `^C` can never match
  `F:\...\zone_1\cinema\C231C4652_….jpg`. Until it is answered, write **unanchored**
  patterns only. The same probe settles it: run one anchored and one unanchored form of
  the same family token back to back and diff the enabled count.
- A standing forum-mining follow-up on the regexp dialect has been open since 2026-07-23.

**cmd escaping trap — this bites before RealityScan ever sees the pattern.** In a `.bat`
or at the Command Prompt, `^` is cmd's escape character and `|` is a pipe. An unquoted
`-selectImage g/^C[0-9]*C/` reaches the process as `g/C[0-9]*C/` (the `^` silently eaten),
and an unquoted alternation `g/(P|S)/` breaks the line outright. **Always pass the whole
pattern as a single double-quoted argument** — inside double quotes cmd treats `^` and `|`
literally. This is the same class of defect as the `key=value` splitting of §3.
[VERIFIED-by-reasoning from the cmd parsing rule established in NA167 B5 / FINDINGS
2026-07-23; the specific `^`-eating case has not been observed against `-selectImage`,
because no regexp form has yet been made to select anything here.]

### 13.2 Worked selection examples against this rig's real filename families

Filename families in production here — the literal patterns are
`modules/camera_registry.py`'s, matched **most specific first**: anchored WCA prefix, then
anchored legacy prefix, then the delimiter-bounded Zeuss token. All three are
case-insensitive and are applied to the **basename**, not the path.
[VERIFIED-by-inspection: `camera_registry.family`, 2026-08-04]

| Family | Repo's own regex (Python, `re.IGNORECASE`) | Physical camera | Example |
|---|---|---|---|
| WCA Port | `^([pcs])\d+c` capturing `p` | Port, fisheye 14 mm | `P231C0003_20231104202628_edt.jpg` |
| WCA Cinema | same regex capturing `c` | Cinema, rectilinear 17 mm | `C231C2370_20231104202628_edt.jpg` |
| WCA Starboard | same regex capturing `s` | Starboard, fisheye 14 mm | `S231C0117_20231104203015_edt.jpg` |
| legacy `cammid` | `name.startswith('cammid')` | Port | `cammid_20250524T103743Z.jpg` |
| legacy `camlower` | `name.startswith('camlower')` | Cinema | `camlower_20250524T103743Z.jpg` |
| legacy `camupper` | `name.startswith('camupper')` | Starboard | `camupper_20250524T103743Z.jpg` |
| Zeuss | `(^\|[_\-.])(zeuss\|herc)([_\-.]\|$)` | Zeuss, rectilinear 23 mm | `HERC_20231104_2026_0042.jpg` |

The Zeuss token is **delimiter-bounded on purpose**: an unanchored `'herc' in name` test
used to run first and would beat an anchored WCA prefix. Any regexp handed to
`-selectImage` inherits that hazard — a bare `herc` substring test is not a safe family
discriminator. [VERIFIED-by-inspection: the comment on `_ZEUSS_TOKEN`]

**Documented-syntax forms** (would select a whole camera family in one call — **[OPEN] per
§13.1: no `g/…/` form has been shown to select anything in this build**). Note every
pattern is quoted and unanchored, per the two traps in §13.1:

```bat
:: all Cinema frames
%RealityScan% -delegateTo RS1 -selectImage "g/C[0-9][0-9][0-9]C[0-9]/"
:: all fisheye frames (Port + Starboard) as a union
%RealityScan% -delegateTo RS1 -selectImage "g/P[0-9][0-9][0-9]C[0-9]/" set
%RealityScan% -delegateTo RS1 -selectImage "g/S[0-9][0-9][0-9]C[0-9]/" union
:: everything except Zeuss
%RealityScan% -delegateTo RS1 -selectAllImages
%RealityScan% -delegateTo RS1 -selectImage "g/HERC/" sub
```

Even if the `g/…/` form works, these three WCA patterns are **not safe against a full
path**: a zone tree whose per-camera subfolders are named `cinema\`, `port\`,
`starboard\` contains the letters but not the digit shape, so the discriminator survives
by luck rather than design. Verify any family selection by count before relying on it.
[INFERRED]

**Form measured to work today** — one literal full path per call, composed with `union`:

```bat
%RealityScan% -delegateTo RS1 -deselectAllImages
%RealityScan% -delegateTo RS1 -selectImage "F:\...\zone_1\cinema\C231C4652_20231104213612_edt.jpg" union
%RealityScan% -delegateTo RS1 -selectImage "F:\...\zone_1\cinema\C231C5220_20231104220104_edt.jpg" union
```

### 13.3 Selection leakage — the export killer

**`-importFlightLog` leaves the matched images ACTIVELY SELECTED**, and selection-driven
exports under `-silent` then export **NOTHING**: the "Export Selection" dialog is
auto-answered, and an XMP export that normally takes 20.5 s completed in **0.057 s**
having written nothing.
[VERIFIED: FINDINGS 2026-07-23] [UNDOCUMENTED: the Help does not warn that import leaves a
selection]

**`-deselectAllImages` before every export is mandatory.** Both production workflows do
this explicitly:

```bat
:: AlignZone.bat, immediately after -align and before every export step
call :run -deselectAllImages || goto :fail
call :run -setMinComponentSize %min_component_size% || goto :fail
```

### 13.4 Composing a selection: the union loop and its cost

With only literal-path matching available, a set selection is a per-image `union` loop.
Measured cost **0.1–0.3 s per image** — budget **minutes** for thousand-image sets.
[VERIFIED: FINDINGS 2026-07-23]

The production loop (`GrowZone.bat :: :selectFromList`) deliberately fires each
`-selectImage` **without** the usual double-`-waitCompleted`, because selection commands
are instant and delegated commands execute FIFO; a `:run`-style wait per image would add
~5 s × thousands of images. The **next** `:run` call flushes the whole queue before
checking the errors marker, so a bad path still aborts the pass there:

```bat
:selectFromList
for /f "usebackq delims=" %%L in ("%~1") do (
    %RealityScan% -delegateTo %RS_INSTANCE% -selectImage "%%~L" union
)
exit /b 0
```

### 13.5 Selection state, saves, and what the CLI cannot see

- **Disabled state persists into the save.** A component-mode grow pass disables most of
  the scene (`inpEnabled=false`); a saved zone project must always be the all-enabled
  state, since it is the authoritative artifact. Every workflow re-selects all and
  re-enables before every `-save`. [VERIFIED: FINDINGS 2026-07-24; `GrowZone.bat :save_quit`]
- **There is no CLI query for "how many images are selected".** The count is shown only in
  the GUI's Selected Inputs table. [UNDOCUMENTED / blindness]
  [OPEN — cheapest probe: export ALIGNMENT ▸ Registration as an *Image list* (which
  contains "all enabled or selected images"), using a GUI-saved params XML, and count the
  lines. That params XML does not exist here yet, and `-exportRegistration` **without** a
  params XML blocks forever headless.]
- **Sub-select "only registered" / "only unregistered" is GUI-only.**
  [OFFICIAL: appbasics/selectedinputs] No CLI equivalent is documented.
  Registered-camera membership is instead recovered from the pose-XMP census.
- GUI shortcuts, for orientation only: `ctrl+a` select all, `ctrl+d` deselect,
  `ctrl+i` invert, `c` Camera Lasso, `shift+c` Camera Rect.
  [OFFICIAL: appbasics/multiselect]

---

## 14. Commands for Selected Images

All of these operate on the **current image selection** — establish it first.
[OFFICIAL: appbasics/allcommands "Commands for Selected Images"]

| Command | Parameters | Effect | `-editInputSelection` key |
|---|---|---|---|
| `-setFeatureSource` | `0`\|`1`\|`2` | feature source mode (§14.1) | `aligFeaturesMode` |
| `-enableAlignment` | `true`\|`false` | include/exclude in registration | `inpEnabled` |
| `-enableMeshing` | `true`\|`false` | include/exclude in model computation | `inpMeshing` |
| `-enableTexturingAndColoring` | `true`\|`false` | include/exclude in colouring and texturing | `inpTexturing` |
| `-setWeightInTexturing` | `<0,1>` | weight in colouring/texturing | `inpImageColorsWeight` |
| `-enableColorNormalizationReference` | `true`\|`false` | mark as colour etalon (its colours are not changed) | `inpColorRef` |
| `-enableColorNormalization` | `true`\|`false` | include in colour normalisation | `inpColorNorm` |
| `-setDownscaleForDepthMaps` | `integer` | per-image depth-map downscale | `inpImageDepthMapDownscale` |
| `-enableInComponent` | `true`\|`false` | use this component's registration data in future alignments; **registered images only** | — |
| `-setCalibrationGroupByExif` | — | set calibration group of **all inputs** from EXIF | — |
| `-setConstantCalibrationGroups` | — | group all selected inputs into one calibration group | — |
| `-lockPoseForContinue` | `true`\|`false` | keep relative camera pose unchanged next registration; **registered images only** | `inpPosePriorRelative`, `inpPosePriorRelativeGroup` |
| `-setPriorCalibrationGroup` | `number` | `-1` = do not group; any other number groups the selection | `inpCalibrationGroup` |
| `-setPriorLensGroup` | `number` | `-1` = do not group; any other number groups the selection | `inpLensGroup` |
| `-editInputSelection` | `"key=value"` | any Selected-Inputs-panel setting (§15) | — |

Note that `-setCalibrationGroupByExif` is listed in this family but its own description
says it acts on **all inputs**, not the selection. [OFFICIAL: appbasics/allcommands]

[CONTRADICTED — doc-internal] `-enableInComponent` is described two incompatible ways in
the same build:

| Source | Description |
|---|---|
| `appbasics/allcommands`, `tutorials/commandline` | "**Enable selected images in meshing and continue.** Applicable only for the registered images." |
| `appbasics/selectedinputs` (the GUI field it maps to) | "When enabled, this option uses the **camera registration data from the selected component to optimize future alignments**. Disabling it does not affect registration data from other components or camera image priors, but restricts the use of registration data within the selected component, including for processes such as meshing and texturing. Unlike the Enable alignment option, it applies only to the selected component and not to the entire input." |

The panel text is the specific one and is almost certainly correct: this is a
**per-component** switch on whether a camera's solved registration feeds later alignments,
which incidentally gates meshing/texturing *within that component*. The CLI row's
"in meshing" reads as a partial restatement. Consequence for scripting: it is
**component-scoped state**, so it does not compose with `-selectImage` the way the rest of
this family does — a component must be selected too. Never exercised here. [INFERRED from
the two texts read together; settle it by toggling it on one image of a two-component
scene and reading the other component's state in the GUI.]

### 14.1 `-setFeatureSource 0|1|2`

> 0 – Merge using overlaps, 1 – Use component features, 2 – Use all image features.
> [OFFICIAL: appbasics/allcommands]

Semantics, from the panel description [OFFICIAL: appbasics/selectedinputs]:

| Value | Name | Uses | Cost |
|---|---|---|---|
| `0` | Merge using overlaps | only the components' images/points that are **in common** (overlapping images) | least time and memory |
| `1` | Use component features | only the points used in the alignment of the **imported component** | fastest, best under RAM shortage |
| `2` | Use all image features | all images/points | slowest, highest RAM |

"By choosing a proper strategy you can significantly reduce the amount of RAM required
during the alignment." [OFFICIAL: appbasics/selectedinputs]

[VERIFIED] This trio **is CLI-accessible** and composes with `-selectImage` /
`-selectAllImages` for per-camera merge-mode experiments. It was wrongly recorded as
GUI-only in an early merge test plan.
[SUPERSEDED: MERGE_TEST_PLAN §1 "GUI-only"] [VERIFIED: NA167 B11, 2026-07-23]

### 14.2 Behaviour established here

- **`-align` honours enable/disable exactly.** `-editInputSelection "inpEnabled=false"`
  works as a single quoted `key=value` argument.
  [VERIFIED: FINDINGS 2026-07-23, cells U1/U19/U2]
- **Pose locking is unusable as a growth anchor.** `inpPose=3` (Locked) takes effect, but
  `-align` then refuses: *"prior set to 'Exact' mode must be all aligned in a single run.
  Incremental adding is not supported."* Checkpoint/rollback stays the never-shrink
  mechanism. [VERIFIED: FINDINGS, cell U18 FAIL, 2026-07-23]
- The repo supports both call styles behind one switch (`RS_GROW_SELECT_CMDS=legacy`
  selects `-enableAlignment` / `-setFeatureSource`; the default uses
  `-editInputSelection`). The `key=value` pair is composed **inside** the `.bat` so `cmd`
  never splits the `=`. [VERIFIED-by-inspection: `GrowZone.bat :selEnable / :selFeature`]

---

## 15. `-editInputSelection` — the master per-image control

```
-editInputSelection "key=value"
```

"**Almost** every setting has two possible keys… The upper key (blue) is usually an
abbreviation of the setting, and the lower key (gray) is the whole path to the setting
based on the panel in which it can be found." Both are accepted; a few rows carry only the
short key (`inpRx`, `inpRy`, `inpRz`).
[OFFICIAL: tutorials/editselectioncommand] Process ID `21877 CLI_SET_SELECTED_INPUTS_PROPERTY`.

| Key | Panel path alias | Values |
|---|---|---|
| `inpMaskOpts` | How to use masking layer | `0` do not use · `1` only in alignment · `2` only in meshing · `3` both in alignment and meshing |
| `aligFeaturesMode` | Features source | `0` merge using overlaps · `1` use component features · `2` use all image features |
| `inpVisible` | Visible | `true` `false` (camera cone in 3Ds) |
| `inpEnabled` | Enable alignment | `true` `false` |
| `inpMeshing` | Enable meshing | `true` `false` |
| `inpTexturing` | Enable texturing and coloring | `true` `false` |
| `inpImageColorsWeight` | Weight in texturing | float 0..1 |
| `inpColorRef` | Color correction reference | `true` `false` |
| `inpColorNorm` | Color correction | `true` `false` |
| `inpImageDepthMapDownscale` | Downscale for depth maps | positive int |
| `inpPosePriorRelativeGroup` | Prior pose / Locked pose group | any alphanumeric; blank or a negative integer ungroups |
| `inpPosePriorRelative` | Prior pose / Relative pose | `0` Unknown · `1` Draft · `2` Exact |
| `inpPose` | Prior pose / Absolute pose | `0` Unknown · `1` Position · `2` Position and orientation · `3` Locked |
| `inpTx` `inpTy` `inpTz` | Prior pose / x, y, z (also Longitude, Latitude, Altitude) | float; lat/lon also accept DMS with a cardinal prefix (`N54,49,31.25`) or decimal degrees with a prefix (`E32.140328`) |
| `inpRx` `inpRy` `inpRz` | Yaw/Heading, Pitch/Elevation, Roll/Bank | −180..180 · −90..90 · −180..180 |
| `inpPriorAccuracyInh` | Prior pose / Pose accuracy / Accuracy settings source | `0` global camera prior settings · `1` edit custom values |
| `inpuTx` `inpuTy` `inpuTz` `inpuRx` `inpuRy` `inpuRz` | per-axis prior accuracies | float ≥ 0 |
| `inpCalibrationGroup` | Prior calibration / Calibration group | int ≥ 0, or `-1` groupless |
| `inpCalibration` | Prior calibration / Prior | `0` Unknown · `1` Approximate · `2` Fixed |
| `inpFocal` | Prior calibration / Focal length (35mm) | positive float |
| `inpPPX` `inpPPY` | Principal point x / y [mm] | float |
| `inpSkew` | Prior calibration / Skew **and** Prior calibration / Aspect ratio | float |
| `inpLensGroup` | Prior lens distortion / Lens group | int ≥ 0, or `-1` |
| `inpDistortion` | Prior lens distortion / Prior | `0` Unknown · `1` Approximate · `2` Fixed |
| `inpDistortionModel` | Prior lens distortion / Camera model | `0` No lens distortion · `1` Division · `2` Brown3 · `3` Brown4 · `4` Brown3 with tangential · `5` Brown4 with tangential |
| `inpRadial1`..`inpRadial4`, `inpTangential1`, `inpTangential2` | distortion coefficients | float |

[CONTRADICTED — doc-internal] The Help lists `inpSkew` as the key for **both** "Skew" and
"Aspect ratio". One of them is wrong or one setting is unreachable.
[OPEN — cheapest probe: set `inpSkew` on a single image from the GUI console view and read
both fields back in the Selected Input panel.]

**Prior-quality semantics.** The Help defines the three levels **twice, differently**, and
the difference matters [OFFICIAL: appbasics/selectedinputs]:

| Level | Prior *Calibration* wording | Prior *Lens Distortion* wording |
|---|---|---|
| Unknown | "Prior values are either missing or will not be applied during processing." | "Use for images with **significant lens distortion, wide-angle lenses** and when lens priors are not known." |
| Approximate | "Prior values are known and will be adjusted during processing." | "Starting values are known and will be adjusted." |
| Fixed | "Prior values are known and won't be changed during processing." | "Prior values are known and won't be changed during processing." |

The lens row is a *recommendation*, not a definition — Epic's advice for a fisheye is
**Unknown**, i.e. withhold the hint entirely.

- Default is lens distortion model **No lens distortion** with prior **Approximate**,
  meaning RealityScan seeks a solution with distortion as close to zero as possible.
  "This is not realistic if images suffer from a visible lens aberration" — supply
  coefficients or set the lens prior to **Unknown**. [OFFICIAL: appbasics/selectedinputs]

[SUPERSEDED] An earlier caution here — that `Approximate` with no coefficients would
assert approximately-zero distortion and be wrong for a fisheye — was **wrong**. Cinema
carried `LensDistortionPrior="Approximate"` with no coefficients from the start and still
solved k1 = −0.0524 over 2,204 cameras. `Unknown` merely withholds a hint.
[VERIFIED: FINDINGS 2026-07-25] The Help's warning is specifically about the *model* being
"No lens distortion", not about the prior quality — though note that Epic's own
Unknown-is-for-wide-angle advice still points the other way for the two 14 mm fisheyes,
and no A/B of `Approximate` vs `Unknown` on Port/Starboard has been run. [OPEN]

**Two panel fields have no documented key.** `Relative coordinates` and
`Absolute coordinate` (the coordinate-system selectors for relative and prior poses)
appear in `appbasics/selectedinputs` but not in `tutorials/editselectioncommand`'s key
table, so there is no `-editInputSelection` route to either. Scene-level CRS is set
elsewhere — see `06-georeferencing-flightlogs-and-scale.md`.
[VERIFIED-by-inspection of both topics, 2026-08-04]

**Absolute-pose semantics** [OFFICIAL: appbasics/selectedinputs]: Unknown / Position
(optimisable) / Position and orientation (both optimisable) / Locked (no change allowed).
**Relative-pose semantics**: Unknown / Draft (optimisable) / Exact (not altered).

---

## 16. Calibration groups and lens groups

### 16.1 What a group is

> "By defining a calibration group we state that all images in this group have the same
> properties, e.g. the same focal length, the same principal point or the same lens
> distortion coefficients." [OFFICIAL: appbasics/camerasettings]

Useful for fixed-optics cameras, for weak-texture scenes (grouping means fewer parameters
to solve, so fewer feature points are needed), and when you want to force a camera set to
share a focal length. Grouping costs accuracy on very high-resolution sensors where
focus/thermal/mechanical drift makes per-image calibration genuinely different.
[OFFICIAL: appbasics/camerasettings]

`-1` in a group field means **do not group**; any other integer groups every input
carrying that integer. [OFFICIAL: appbasics/camerasettings, allcommands]

### 16.2 How groups form

| Route | Command / key | Scope |
|---|---|---|
| Automatic at import, from EXIF | `-set "appGroupCalibrationByExif=true"` (default `false`) | every image as it is added |
| Retroactive, from EXIF | `-setCalibrationGroupByExif` | **all inputs** |
| One group for everything selected | `-setConstantCalibrationGroups` | current selection |
| Explicit group number | `-setPriorCalibrationGroup <n>` / `-setPriorLensGroup <n>` | current selection |
| Explicit group number, key form | `-editInputSelection "inpCalibrationGroup=3"` / `"inpLensGroup=3"` | current selection |
| Per-image XMP sidecar | `Camera:CalibrationGroup` / `Camera:LensDistortionGroup` | per image, at add time |
| Camera database | `sensorsdb.xml` entry matched on camera model (+ lens model + focal length) | per camera model |
| **Clear all groups** | `-removeCalibrationGroups` | "Clear all inputs from their calibration groups" [OFFICIAL: appbasics/allcommands] |

`-removeCalibrationGroups` takes no parameters and is scene-wide. Epic's GUI advice:
after solving with grouped parameters, **ungroup and align again** to fine-tune while the
scene stays well-conditioned. Epic scopes the advice explicitly — "**This is recommended
for scenes with weak texture or small image count.** Alignment in such case will take just
a few seconds." [OFFICIAL: appbasics/camerasettings]

[OPEN] That ungroup-and-refine pass has never been run here, and the scope qualification
argues against it: a 4,540-image zone is neither small nor a few seconds, and ungrouping
would destroy the *only* thing separating the EXIF-identical WCA cameras (§16.4). If it is
ever tried, restore the sidecar grouping before the next align.

### 16.3 The camera database (`sensorsdb.xml`)

Holds sensor size and lens-distortion priors, matched on **camera model**, optionally
**camera lens model** and **focal length**: "The system uses a camera model, a camera lens
model and a focal length to match the database entry." RealityScan "automatically reads
them when an image is imported and sets them to images."
[OFFICIAL: appbasics/cameradb]

Entry shape **as shipped** (root element `<cameras>`):

```xml
<camera model="Apple iPhone 4" ccdWidth="4.5400" GPSMode="ignore"/>
```
[VERIFIED-by-inspection: `C:\Program Files\Epic Games\RealityScan_2.2\sensorsdb.xml`
line 4, 2026-08-04]

Entry shape **with a lens block**, from **this repository's own hand-authored copy** at
the repo root — these ROV entries are *not* in the shipped database:

```xml
<!-- ZCAM F6 with 8-15mm fisheye through 3" dome - Upper position -->
<camera model="ZCAM F6 8-15mm Fisheye Upper" ccdWidth="37.09"><lens type="division" focal="13" c1="0"/></camera>
<camera model="ZCAM F6 8-15mm Fisheye Mid"   ccdWidth="37.09"><lens type="division" focal="13.5" c1="0"/></camera>
<camera model="ZCAM F7 16-35mm III Lower"    ccdWidth="37.09"><lens type="division" focal="16" c1="0"/></camera>
<camera model="Zeus Plus" ccdWidth="11.0"/>
```
[VERIFIED-by-inspection: `RealityScan_CLI/sensorsdb.xml` lines 2–12, 2026-08-04.
`grep -i zcam` over the shipped `C:\Program Files\Epic Games\RealityScan_2.2\sensorsdb.xml`
returns **nothing** — an earlier draft of this document wrongly attributed these entries to
the shipped file.]

**The repo copy is inert.** It sits at the repository root and is not deployed to either
location the app reads, so nothing in this pipeline has ever caused RealityScan to load a
ZCAM entry. It is a reference artifact, not an installed one; see
`09-xml-parameter-files.md` §"Keep a copy in the repository" for why it is kept.
[VERIFIED-by-inspection: no script in the repo copies or references `sensorsdb.xml`
(`grep -rn sensorsdb --include=*.py --include=*.bat` returns no hits), 2026-08-04]

- Priors from the database are **soft** by default (optimised during processing); add
  `quality="exact"` to the lens attributes for hard priors. [OFFICIAL: appbasics/cameradb]
- The per-camera counterpart of the global `appIgnoreExifGPS` is the attribute
  `GPSMode="ignore"`. The *capability* is documented — "If an image includes GPS
  coordinates in the exif, it is possible to turn on/off their use per camera"
  [OFFICIAL: appbasics/cameradb, appbasics/appsettings] — but the attribute spelling
  appears only in a screenshot, never in prose; it is read off the shipped file
  [VERIFIED-by-inspection, 2026-08-04].
- Add an entry when the files carry a non-35 mm-equivalent focal length, when distortion is
  visible, or when a yellow exclamation mark appears next to an image in 1Ds.
  [OFFICIAL: appbasics/cameradb]

[CONTRADICTED-adjacent — location] The Help names exactly one location: the file "is
located in ProgramData … typically `C:\ProgramData\Epic\RealityScan\sensorsdb.xml`"
[OFFICIAL: appbasics/cameradb]. **Three copies exist on this machine**, and only two of
them are the product's:

| Path | md5 | Status |
|---|---|---|
| `C:\ProgramData\Epic\RealityScan\sensorsdb.xml` | `8d426fc47b0643f388b3ac4d782e7428` | the documented one |
| `C:\Program Files\Epic Games\RealityScan_2.2\sensorsdb.xml` | `8d426fc47b0643f388b3ac4d782e7428` | **byte-identical**, undocumented |
| `RealityScan_CLI\sensorsdb.xml` (repo root) | `21c71b2ef839fce3760e3ac31d53e74b` | **different file** — repo reference copy, not installed, never read |

[VERIFIED-by-inspection, 2026-08-04] [OPEN] Which of the two product copies the running app
reads is untested, and invisible while they stay identical. Cheapest probe: add a
distinctive `<camera model="PROBE-CAM" ccdWidth="9.99"/>` entry to one copy only, import a
matching image, and see whether the prior appears.

**`sensorsdb.xml` is unusable for this rig.** The repo's hand-authored ROV entries are
keyed to NA167-era model strings ("ZCAM F6 8-15mm Fisheye Upper") that cannot match the
current EXIF (`Z CAM` / `E2-F6`, §16.4), and even a matching entry could not distinguish
two cameras with identical EXIF — matching is per *camera model*, and this rig's cameras
report the same one. Per-image XMP is the only separator; see §16.4.
[VERIFIED-by-inspection: docs/settings-evaluation-2026-07 §1, 2026-07-23]

### 16.4 The EXIF-identical-cameras case — why XMP groups are the only answer here

- **The WCA rendered JPGs are EXIF-identical across cameras**: Make `Z CAM`, Model
  `E2-F6`, same exposure data, **no focal length and no lens tag**, 4244×2827,
  Lightroom-rendered from a full-frame sensor. RealityScan cannot tell the cameras apart
  from EXIF. [VERIFIED-by-inspection: settings-evaluation §1, 2026-07-23]
- Consequently **`appGroupCalibrationByExif` is wrong in either position** on this rig:
  enabled, it collapses two physically different cameras into one calibration group;
  disabled, images calibrate without any grouping (weak).
  [VERIFIED-by-inspection: settings-evaluation §1]
- **Per-image XMP calibration sidecars with `Camera:CalibrationGroup` /
  `Camera:LensDistortionGroup` are the ONLY way to separate EXIF-identical cameras. One
  group per PHYSICAL camera, never per lens type** — Port and Starboard share a lens spec
  but are different units with different real intrinsics.
  [VERIFIED: settings-evaluation §1–§2 + the measurement below]

Sidecar content written here (`modules/camera_registry.py :: calibration_xmp`) — note it
carries **no pose entries**, deliberately, because exported pose sidecars re-import as
exact-pose priors (§5):

```xml
<?xml version="1.0" encoding="UTF-8"?>
<x:xmpmeta xmlns:x="adobe:ns:meta/" xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
  <rdf:RDF>
    <rdf:Description xmlns:Camera="http://www.capturingreality.com/ns/camera/1.0/"
                     xmlns:xcr="http://www.capturingreality.com/ns/xcr/1.0/">
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

Group assignment in force: `zeuss`=1, `port`=2, `cinema`=3, `starboard`=4, with the same
integer used for both the calibration group and the lens-distortion group.
[VERIFIED-by-inspection: `camera_registry.CAMERAS`]

**The grouping demonstrably works.** Both cameras were given the **same** 16.0 mm prior and
the solve separated them by **5.6 %** with IQRs of ±0.5 %, over 5,050 harvested pose
records:

| Camera | records | focal 35 mm-eq (IQR) | division k1 (IQR) | principal point | skew | aspect |
|---|---:|---|---|---|---|---|
| cinema | 2,558 | **16.374** (16.302–16.476) | **−0.0378** (−0.0415…−0.0336) | (−0.0071, −0.0031) | 0 | 1 |
| port | 2,492 | **15.499** (15.435–15.574) | **−0.3875** (−0.3933…−0.3832) | (+0.0027, +0.0056) | 0 | 1 |

The order-of-magnitude k1 gap is the fisheye declaring itself.
[VERIFIED: FINDINGS 2026-07-26, parsed from 5,050 PD-6 harvest records]

**Fragmentation effect.** Calibration sidecars present at align time cut zone_1 from
**9 components to 3** at equal-or-better registration (4,405/4,540 = 97.0 % vs 4,392 =
96.7 %) on the same imagery and the same box.
[VERIFIED: FINDINGS 2026-07-24; docs/FRESH_RUN_2026-07-24.md]

**But prior *content* can hurt.** An A/B on zone_13 with priors absent (the `.jpg.xmp`
naming bug) vs promoted went **96.3 % → 89.6 %** on Zeuss. The old writer grouped
`cammid`+`camupper`+`camlower` together at "12 mm fisheye" when `camlower` is actually
rectilinear 17 mm, which plausibly explains the whole result. Generation therefore became
opt-in (`batch_xmp_priors`, default **off**).
[VERIFIED: NA167 #4 / B7, 2026-07-22] [SUPERSEDED-in-scope: the corrected per-camera values
reverse the calculus — validate per rig before trusting either direction]

**Two group-related traps:**

- **`sfmDistortionModel` is GLOBAL and all-or-nothing.** The per-camera XMP
  `Camera:DistortionModel` hint does **not** switch models per camera: the cinema sidecars
  declare `brown3`, yet all 2,558 cinema pose XMPs came back
  `xcr:DistortionModel="division"` — the same model as the 2,492 port records.
  [CONTRADICTED: an earlier settings-evaluation claim that per-image XMP overrides the
  global key / observed over 5,050 records, 2026-07-26]
- **A different sensor footprint defeats the group.** Exactly one image of 8,197,
  `C231C2370_20231104202628_edt.jpg`, is 3846×2163 while the other 8,196 are 4244×2827.
  Different footprint ⇒ different intrinsics ⇒ RealityScan groups it separately regardless
  of its XMP calibration group. [VERIFIED: FINDINGS 2026-07-25]
- Exported pose XMPs carry `xcr:CalibrationGroup="-1"` / `xcr:DistortionGroup="-1"`
  **alongside** `Camera:CalibrationGroup="3"`. The `-1` is an export artifact, not a lost
  grouping. [VERIFIED: FINDINGS 2026-07-26] [UNDOCUMENTED]

### 16.5 The sidecar-stripping defect (fixed, but know the shape)

The per-component identity harvest **MOVES** every pose-bearing `.xmp` out of the image
tree into `identity_r<K>`. The last-peeled component's sidecars are never re-exported, so
those images end up with **no calibration prior at all**. Measured on fresh zone_1:
**796 of 4,540 images (17.5 %) had no sidecar** — the entire bow component (665/665), 123
of c0, 8 unregistered. Any later re-align of that folder silently runs with a partially
ungrouped camera set; two prior/distortion test cells did exactly that, so their results
are **confounded**. Fixed by `camera_registry.ensure_calibration_sidecars()`, which
recreates a calibration-only XMP for every image that has none.
[VERIFIED: FINDINGS 2026-07-25]

---

## 17. Image layers

> "In RealityScan, you can sort your images into different layers and then use them in
> different processing steps. … You do not need to load the project separately with each
> set of images, you just need to name the images properly and load them at once."
> [OFFICIAL: tools/imglayers]

**NOTE (Epic's own):** "All layers for the same image need to share the same camera and
object position. Differences in camera positions or slight movement of the object might
cause blur in the texture." [OFFICIAL: tools/imglayers]

### 17.1 Supported layer types

| Token | Meaning |
|---|---|
| `.geometry` | the alignment/meshing image — **equals an image or folder with no layer extension** |
| `.mask` | mask layer |
| `.labels` | classification labels layer (consumed by `-transferClassification`) |
| `.depth` | depth layer |
| `.texture` | texturing layer — **equals `.texture1` and `.texture01`** |
| `.textureXX` | numbered texturing layers |

[OFFICIAL: tools/imglayers]

Separators: instead of `.` you may use `_`, `@`, `#`, `!` — e.g. `_texture`, `@texture`,
`#texture`, `!texture`. [OFFICIAL: tools/imglayers]

### 17.2 Naming — per file

The layer name is the **whole original file name including its extension**, plus the layer
extension and its own image extension:

```
DSC_0001.jpg                     geometry (no layer extension)
DSC_0002.jpg.geometry.jpg        geometry, named explicitly (the whole name shows in the app)
DSC_0001.jpg.mask.png            mask
DSC_0001.jpg.texture.jpg         texture 1
DSC_0001.jpg.texture02.jpg       texture 2
DSC_0001.jpg.texture3.jpg        texture 3
```
[OFFICIAL: tools/imglayers]

### 17.3 Naming — per folder

All images must share the same names (formats may differ); the *folder* name carries the
separator + layer token:

```
…\layers\.geometry\DSC_0001.jpg
…\layers\.mask\DSC_0001.png
…\layers\.texture\DSC_0001.jpg
…\layers\.texture02\DSC_0001.jpg
…\layers\.texture3\DSC_0001.jpg
```
[OFFICIAL: tools/imglayers]

Import the parent with `-addFolder` (with `appIncSubdirs=true`, §4).

### 17.4 Custom layer names

Grammar [OFFICIAL: tools/imglayers]:

```
per file:   ImageName.($imgExt)($sep)($LayerDef)($optNum)($sep OR '')($LayerName).($imgExt)
per folder: ($sep)($LayerDef)($optNum)($sep OR ' ')($LayerName)//Images
```

The trailing `//Images` in the per-folder line is written literally in the Help. It is
almost certainly a comment marking where the image files sit, not part of the folder name
— none of Epic's four folder examples contains it. [INFERRED; settle it by creating a
folder named exactly `.geometry!Shapes` and confirming the layer name is `Shapes`.]

| Token | Meaning |
|---|---|
| `($sep)` | one of `.` `_` `@` `#` `!` |
| `($LayerDef)` | a layer type from §17.1 |
| `($optNum)` | optional number, when more than one layer of the same type is imported |
| `($LayerName)` | the name assigned to the layer |
| `($imgExt)` | image extension |

Epic's examples, verbatim:

```
Image01.png.texture03@Third.Texture.png     third texture layer named "Third.Texture"
Image02.jpg!geometry_My Geometry.jpg        geometry layer named "My Geometry"
_texture02@Light texture                    second texture layer named "Light texture" (folder)
.geometry!Shapes                            geometry layer named "Shapes" (folder)
```

### 17.5 Layer behaviour and CLI commands

- If several texture layers are present, **each** is used during texturing and a separate
  texture layer is created per source layer.
- If **no** texture layer is loaded, the Geometry layer is used for texturing and is linked
  to the Texture layer.
- Colour correction runs **per layer**, independently.
[OFFICIAL: tools/imglayers, tools/normalization]

| Command | Parameters | Effect |
|---|---|---|
| `-setImageLayer` | `index` `pathImage` `layerType` | attach the layer image at `pathImage` to the input at `index`; **`index` is the 1Ds view order, 0-based** |
| `-setImagesLayer` | `pathImage` `layerType` | same, applied to the **current image selection** |
| `-removeImageLayer` | `layerType` | remove layers of that type from the **selected** images |

[OFFICIAL: appbasics/allcommands] The GUI equivalent notes that **the Geometry layer is
not removable**. [OFFICIAL: tools/imglayers]

[OPEN] The Help gives only "e.g., `mask`, `texture`" for `layerType` and never enumerates
the accepted strings. [INFERRED] they are the §17.1 tokens **without** the leading
separator: `geometry`, `mask`, `labels`, `depth`, `texture`, `textureNN`. Cheapest probe:
issue `-setImagesLayer <path> <token>` once per candidate token from the GUI console view
and record which produce an error.

Related `-set` keys that select which layer feeds colouring/texturing:

| Key | Type | Default | Values |
|---|---|---|---|
| `ImageLayerForColoring` | string | `geometry` if no texturing layer is present, else `texture01` | `geometry/<geometry_layer>`, `texture01/<texture_layer>`, `texture2/<texture_layer2>` |
| `ImageLayerForTexturing` | string | `all` | `geometry/<geometry_layer>`, `texture01/<texture_layer>`, `texture2/<texture_layer2>`, `all` |

[OFFICIAL: tutorials/setkeyvaluetable] See `03-settings-keys.md`.

### 17.6 Status in this repository

**Image Layers has never been exercised through the CLI here.** It is the agreed eventual
mechanism for "align on originals, texture from enhanced imagery" (§21) and is
**not adopted**. [VERIFIED-as-decision: HANDOFF 2026-07-26] [OPEN]

---

## 18. Masks

### 18.1 Semantics

> "In a mask, **white areas will be used in processing, while black areas are excluded**.
> Although grayscale values up to 256 shades (or partial transparency) can be used, they
> are not recommended, as they may interfere with processing and produce inconsistent
> results." [OFFICIAL: tools/mask]

Masks may be supplied **either** as separate grayscale images (e.g. PNG) **or** embedded
in the **alpha channel** of the original images (e.g. TIFF). They are non-destructive:
they exclude image regions (windows, water, sky, shadows, vegetation, noise) from
processing, reducing unwanted geometry and downstream filtering work.
[OFFICIAL: tools/mask]

### 18.2 Generating masks

| Command | Parameters | What it does |
|---|---|---|
| `-generateAIMasks` | — | "Use AI Masking to generate masks by isolating the object of interest in your images." Automatically detects the background. **Ideal for turntable captures or environments with minimal background features.** Can run **before alignment**. |
| `-generateMaskFromMesh` | — | "Generate mask images out of the existing camera views (images) and selected model. Everything around the model as seen from the camera will be masked out." Requires a model. |

[OFFICIAL: appbasics/allcommands; tools/mask]

Both add their masks to the project automatically — "This is not needed if the images were
generated using the AI Masking or Masking from Mesh tool they are automatically added to
the project." [OFFICIAL: tools/mask]

[CONTRADICTED — doc-internal, and the polarity is what is at stake] The two topics
describe `-generateMaskFromMesh` in opposite mask-polarity language:

| Source | Wording |
|---|---|
| `appbasics/allcommands` | "Everything around the model as seen from the camera will be **masked out**." |
| `tools/mask` | "Areas outside the mesh are **unmasked** and will be ignored in further processing." |

With the §18.1 convention (white = used, black = excluded), "masked out" and "unmasked …
ignored" cannot both be literal. The *effect* both intend is the same — off-model regions
are excluded — but `tools/mask` uses "unmasked" to mean "not covered by the white area",
which is the reverse of ordinary usage. Do not infer polarity from either sentence;
inspect one generated PNG before wiring a mask into a workflow. [OPEN]

[OPEN] Neither command takes a parameter in the CLI, and neither the AI-masking model nor
any threshold is exposed. Whether `-generateAIMasks` respects the current image selection
or runs on every input is **not stated**. Cheapest probe: select 3 images, run it, and
count the resulting `.mask` layers.

**Blindness note.** Mask inspection is GUI-only: open the image in the 2D view and set
IMAGE 2D/VIEW ▸ Source ▸ Input Layer to **Mask** (the option is disabled when the image
has no mask layer); TAB cycles layers. There is no CLI readback of a mask's content or
even of its presence. [OFFICIAL: tools/mask, tools/imglayers]

### 18.3 Importing masks

Mask images "must follow the same naming principles as image layers during import"
(§17) — per file `DSC_0001.jpg.mask.png`, or per folder `…\.mask\DSC_0001.png`.
[OFFICIAL: tools/mask, tools/imglayers]
They can also be attached explicitly with `-setImageLayer` / `-setImagesLayer` (§17.5).

### 18.4 Using masks

Per-input, via `-editInputSelection "inpMaskOpts=<n>"`:

| Value | Meaning |
|---|---|
| `0` | Do not use |
| `1` | Only in alignment |
| `2` | Only in meshing |
| `3` | Both in alignment and meshing |

[OFFICIAL: tutorials/editselectioncommand]

The GUI panel exposes three independent toggles — *Enable masks for alignment*, *for
meshing*, *for texturing and coloring* [OFFICIAL: appbasics/selectedinputs] — while
`inpMaskOpts` is a **single 4-valued key covering only alignment and meshing**.
[CONTRADICTED — doc-internal / capability gap] There is no documented key for the
texturing/colouring mask toggle. [OPEN — cheapest probe: set the texturing mask toggle in
the GUI, export the settings, and diff for a new key; or search the binary's key strings.]

### 18.5 Exporting masks

Two forms, both requiring a params XML exported from the **Export Mask Images** dialog:

```
-exportMasks <folderPath> <params.xml>    :: export to a chosen folder
-exportMasks <params.xml>                 :: export next to the original images
```
[OFFICIAL: appbasics/allcommands] Process ID `14 EXPORT_MASK`.

The export writer, read from the install tree
(`C:\Program Files\Epic Games\RealityScan_2.2\masklayer.xml`)
[VERIFIED-by-inspection, 2026-08-04]:

```xml
<MaskLayer name="Mask Layer">
  <format id="{83470127-6B66-4D31-B1D3-6B60A97C5705}" mask="*.*" desc="Export Mask Images"
           writer="RealityScan.Export.MaskLayer" supportsGeoref="0"
           undistortImages="never" exportImages="never" >
    <hint>Export Mask Images.</hint>
  </format>
</MaskLayer>
```

| Attribute | Value | Reading |
|---|---|---|
| `id` | `{83470127-6B66-4D31-B1D3-6B60A97C5705}` | the format GUID a params XML must reference |
| `desc` | `Export Mask Images` | name shown in the export dialog |
| `writer` | `RealityScan.Export.MaskLayer` | writer identifier — a **current** product string, do not rename |
| `supportsGeoref` | `0` | no coordinate-system section in the dialog |
| `undistortImages` | `never` | **exported masks are never undistorted** |
| `exportImages` | `never` | this exporter writes masks only, never companion images |

`undistortImages="never"` is the operationally important one: mask export cannot produce
undistorted masks, so a consumer that wants masks aligned to undistorted imagery must go
through `-exportMapsAndMask` (§19), whose format carries `undistortImages="no"` (i.e.
*default off but settable*) rather than `never`.
[INFERRED from the two attribute values read side by side; not measured.]

Masks can also be produced as part of the maps export — §19 — but those "are **not** added
to the project. Instead, they are exported directly alongside the depth maps."
[OFFICIAL: tools/mask]

### 18.6 Status in this repository

- **No mask has ever been driven through this CLI.** No empirical RealityScan masking
  result exists here. [OPEN]
- A staff caution against **over-masking** is recorded second-hand (COLMAP fact base
  F-20260723-31, quoted in HANDOFF); it is relevant to turbid underwater imagery where a
  mask can remove the only textured pixels in a frame.
  [VERIFIED-second-hand; not reproduced here]
- **`masking.py` at the repository root is NOT a masking tool.** It renames
  `cam*_YYYYMMDDTHHMMSSZ.jpg` to a timestamp-first form and validates JPEG integrity with
  PIL. Do not mistake it for mask generation.
  [VERIFIED-by-inspection: `masking.py`, 2026-08-04]

---

## 19. Depth, normal and mask map export

```
-exportMapsAndMask <folderName> <params.xml>
```

> "Export masks generated from the camera view over the model, along with depth and normal
> maps for the selected images. If `folderName` and `params.xml` are not specified, the
> results are saved alongside the original images using the current settings."
> [OFFICIAL: appbasics/allcommands]
Process IDs `36 EXPORT_DEPTH_AND_MASK_IMAGES`, `20586 EXPORT_DEPTH_AND_MASK`,
`13 EXPORT_DEPTH_MAPS`.

[CONTRADICTED — doc-internal] The master table names it `-exportMapsAndMask`;
`tutorials/commandline_3` names it `-exportDepthAndMask`. Both ship in the same build.
Prefer the master table. [OPEN — cheapest probe: issue both from the GUI console view and
read which one errors.]

Formats: **depth maps EXR, normal maps PNG, mask images PNG.**
[OFFICIAL: tools/depthandmask, tools/mask]

Install schema (`C:\Program Files\Epic Games\RealityScan_2.2\depthnormalmaskimage.xml`)
[VERIFIED-by-inspection, 2026-08-04]:

```xml
<DepthNormalMask name="Depths Normals and Masks">
  <format id="{0ABB46B2-4FAA-4CE1-AA39-D96128D39BD9}" mask="*.*" desc="PNG and EXR"
          writer="RealityScan.Export.DepthNormalAndMaskImages" supportsGeoref="0"
          undistortImages="no" exportImages="never" requires="model" >
    <hint>Export Depth, Normal and Mask Images.</hint>
  </format>
</DepthNormalMask>
```

`requires="model"` is machine-readable confirmation that this export **cannot run before a
model exists** — unlike `-generateAIMasks`.

Dialog fields carried by the params XML [OFFICIAL: tools/depthandmask]:

| Field | Notes |
|---|---|
| File format | depth = EXR, normals and masks = PNG |
| Export location | the folder chosen in the Save-As step |
| Export Image List | Yes writes a list of depth/mask image names with format extensions next to the corresponding inputs, with full paths |
| Export Image List File Name | an existing text file to write the list to |
| Export File Naming | naming convention for depth maps and mask images |
| Export masks | Yes/No — masks generated from the currently selected model |
| Export camera depths | Yes/No |
| Distance scale | scaling factor for length values; only when camera-depth export is enabled |
| Project Distance Unit | **fixed, cannot be modified in the export dialog** |
| Near Plane Distance | anything closer is excluded from the depth map |
| Far Plane Distance | anything beyond is excluded |
| Export camera normals | Yes/No |
| Normals format | camera-space or world-space |
| Camera-space format / World-space format | engine-specific variants |

Undistortion sub-block (shared with XMP export and undistorted-image export)
[OFFICIAL: tools/depthandmask, tools/undistort]:

| Field | Values / meaning |
|---|---|
| Undistort images | Yes/No |
| **Image cut-out** | fraction of the image considered for undistortion: `1.0` = full image, `0.5` = 50 %, `0` = nothing. **For fish-eye lenses Epic recommends 0.8.** |
| **Fit** | `Outer boundary` · `Inner region` · `In between` · `Keep intrinsics` (preserves the calibration parameters) |
| **Resolution** | `Fit` (keeps the resolution produced by the Fit step) · `Preserve` (same as the original image) · `Custom` |
| Downscale | integer; each side divided by it. `1` = use the resolution from the previous step |
| Custom width / Custom height | only with Resolution = Custom |
| Undistort principal point | Yes aligns the optical centre with the actual centre of the exported image |
| Max count of pixels | final resolution ceiling; `0` = no limit |

Order of application: Image cut-out → Fit → Resolution → Downscale → Max count of pixels.
[OFFICIAL: tools/undistort]

The **fish-eye cut-out of 0.8** is directly relevant to this rig — Port and Starboard are
14 mm fisheyes solving division k1 ≈ −0.39 (§16.4) — but no undistorted export has been
run here. [OPEN]

The companion command `-exportUndistortedImages <folderName> [params.xml]` uses the same
undistortion block. Note the spelling defect: the master table spells it
`exportUndistortedImages`, `tutorials/commandline_1` spells it `exportUndistoredImages`
(missing `t`). [CONTRADICTED — doc-internal] Process ID `21812 EXPORT_UNDISTORTED_IMAGES`.

---

## 20. Image resolution, downscale and quality settings

| Key | Stage | Type | Default | Meaning | Source |
|---|---|---|---|---|---|
| `sfmImageDownscaleFactor` | alignment / feature detection | int | `1` | `1` = full resolution | [OFFICIAL: setkeyvaluetable] |
| `sfmImageDownscaleFactorDraftMode` | draft alignment | int | `2` | draft-mode downscale | [OFFICIAL] |
| `inpImageDepthMapDownscale` / `-setDownscaleForDepthMaps` | depth maps, **per image** | int | — | see the multiplication rule below | [OFFICIAL: editselectioncommand, selectedinputs] |
| `mvsPreviewDownscaleFactor` | Preview model depth maps | int | `4` | | [OFFICIAL] |
| `mvsNormalDownscaleFactor` | Normal model depth maps | int | `2` | see the High-Detail note below | [OFFICIAL] |
| `txtImageDownscaleTexture` | texturing | int | `1` | | [OFFICIAL] |
| `txtImageDownscaleColor` | colouring | int | `2` | | [OFFICIAL] |

**There is no High-Detail downscale key, by design.** "The High Detail meshing mode always
uses full resolution (value 1) and therefore does not include this option."
[OFFICIAL: appbasics/modelsettings] So `-calculateHighModel` — the only mesh command this
repo runs — is unaffected by `mvs*DownscaleFactor` entirely; the per-image
`inpImageDepthMapDownscale` multiplier is the only remaining lever, and this repo has
never set it. [VERIFIED-by-inspection of `RS_CLI/Scripts/GenerateModel.bat`, 2026-08-04]

**`Maximal depth-map pixel count`** is a further ceiling in the same panel — "This value
does not override the Image downscale value; both will be applied and may affect
resolution. The default value of 0 means the setting is ignored."
[OFFICIAL: appbasics/modelsettings] **No `-set` key for it appears in
`tutorials/setkeyvaluetable`.** [OPEN — same probe as the other keyless GUI settings:
set it in the GUI, export the settings, diff.]

**The depth-map downscale multiplication rule** [OFFICIAL: appbasics/selectedinputs]:

> "the final downscale for depth map computation is calculated as follows:
> Downscale for depth maps (defined in the 1Ds Selected input(s) panel for selected
> pictures) × Image downscale (defined in the Reconstruction settings)"

And the resolution arithmetic, in Epic's own words: "using integer 1 means no change in
the scale (100 % resolution), using integer 2 means each side of the image will be twice as
small (25 % of the original image resolution)".

**Status here:** `sfmImageDownscaleFactor=1` and `sfmImageDownscaleFactorDraftMode=2` are
pinned in `RS_CLI/Metadata/AlignmentParams.xml` and have **never been varied**.
[VERIFIED-by-inspection] [OPEN: whether downscaling helps registration or metric scale on
12 MP underwater stills is unmeasured. Cheapest probe: one zone_3-scale align (≈4 min at
124 images, ≈20 min at 1.5k) at factor 2 against the pinned factor 1, judged on registered
count **and** the scale oracle — not on keypoint counts.]

**Image quality is not a CLI-settable property.** The Selected Input panel reports
`Features` (the number detected in the last alignment) as a read-only diagnostic
[OFFICIAL: appbasics/selectedinputs]; there is no per-image quality score to set or query
headless.

**Guidance from Epic on capture, for completeness** [OFFICIAL: tutorials/takingpictures]:
do not limit image count; use the highest resolution possible; every surface point should
be clearly visible in at least two high-quality images; always move between shots (a
panorama contributes nothing); do not change viewpoint by more than 30°; coarse-to-fine;
complete loops.

---

## 21. Preprocessing images BEFORE import

### 21.1 RealityScan has no CLI-side equivalent

There is **no** RealityScan command or `-set` key that applies contrast enhancement,
CLAHE, dehazing or white balance to the pixels used for feature detection.

- The app's *Image display* settings (Automatic adjustment, Autodetection focus, Maximal
  brightness change, Maximal contrast, Brightness, Contrast) are **display-only**.
  [OFFICIAL: appbasics/appsettings]
- **Color Correction** (`-correctColors [layerName]`, GUI "Correct Colors") is a
  *post-alignment* colour-consistency pass for texturing/colouring — it corrects
  inconsistencies between pictures (different white balances, exposures, changing light) and
  is stored with the project. It is not a pre-detection enhancement.
  [OFFICIAL: tools/normalization]
- Consequently **enhancement must happen on disk, before `-add` / `-addFolder`.**
  [INFERRED from the absence of any such command in `appbasics/allcommands` and any such
  key in `tutorials/setkeyvaluetable`; the absence is the evidence.]

### 21.2 The measured effect on underwater imagery

**zone_9 (NA173) A/B, the decisive result — the complete measured grid, 400-image
subsets, one variant per row, scored on registered cameras:**

| Variant | Registered | Rate |
|---|---:|---:|
| **`clahe_c2_t8`** (CLAHE clip 2.0, 8×8 tiles) | **239 / 400** | **59.8 %** |
| `clahe_c1_t8` | 214 / 400 | 53.5 % |
| `clahe_c3_t8` | 184 / 400 | 46.0 % |
| `clahe_c2_t16` | 167 / 400 | 41.8 % |
| `wb_clahe_c2_t8` (gray-world WB, then CLAHE) | 135 / 400 | 33.8 % |
| `clahe_c4_t8` | 134 / 400 | 33.5 % |
| `clahe_c2_t4` | 124 / 400 | 31.0 % |
| **`baseline`** (no preprocessing) | **0 / 400** | **failed to form any component** |

[VERIFIED: 2026-07-21 zone_9 A/B, `testing/run_zone9_tests.py` phase 2; table reproduced
from `docs/code-review-2026-07.md` §"Preprocessing, measured then baked in"; defaults
recorded in `modules/preprocess_images/preprocess_images.py`]

Three things the full grid says that the headline does not:

1. **"Baseline aligns to nothing" is the load-bearing part.** Not a marginal improvement —
   without CLAHE the dataset does not reconstruct at all.
2. **Clip 2.0 is a sharp optimum, not a plateau.** Clip 1 → 53.5 %, clip 3 → 46.0 %,
   clip 4 → 33.5 %. Half a stop either way costs 6–26 points.
3. **Tile size is equally sharp and asymmetric.** 8×8 → 59.8 %, but 4×4 → 31.0 % and
   16×16 → 41.8 %. Neither neighbour is a safe substitute.
   Gray-world white balance **actively hurts** (33.8 % vs 59.8 % at the same clip/tile).

The variant grid (`testing/preprocess_variants.py`): round 1 = `baseline`, `clahe_c2_t8`,
`clahe_c4_t8`, `wb_clahe_c2_t8`; refinement around the winner = clip/2, clip×1.5, tile 4,
tile 16, white-balance flip. Scoring metric: **registered / total images**, read from the
pose-XMP sidecar count, with component count and runtime as tiebreakers — never keypoint
counts.

### 21.3 The transform, exactly

CLAHE on the **L channel in LAB space** — enhances local contrast without shifting colour,
which is what matters for feature matching [VERIFIED-by-inspection:
`modules/preprocess_images/preprocess_images.py`]:

```python
def clahe_lab(img: np.ndarray, clip: float, tile: int) -> np.ndarray:
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    l_channel, a_channel, b_channel = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=clip, tileGridSize=(tile, tile))
    l_channel = clahe.apply(l_channel)
    return cv2.cvtColor(cv2.merge((l_channel, a_channel, b_channel)), cv2.COLOR_LAB2BGR)
```

| Parameter | Production value |
|---|---|
| `clipLimit` | `2.0` |
| `tileGridSize` | `(8, 8)` |
| gray-world white balance | **off** |
| JPEG write quality | `95` |
| Output | `<output_dir>\preprocessed_images`, mirroring the input folder structure, **same filenames** |
| Originals | never modified |

The **same filenames** rule is deliberate: flight-log matching is by basename (§12.2), so
the enhanced copies must keep the names or every trajectory row breaks.

### 21.4 The trap this creates in a pipeline

Because the preprocessed copies carry the **same filenames** as the raw set, a downstream
batcher that skips destinations existing **by name** will silently reuse raw-pixel zones on
a CLAHE run. A fingerprint over the flight log alone is byte-identical between the two
runs. The fix in force is a cheap content signature over the image source — count, total
bytes, newest mtime, deliberately no hashing because it runs against tens of thousands of
39 MB stills. [VERIFIED-by-inspection: `modules/image_batcher/batch_directory.py ::
_input_fingerprint`, with the failure mode documented in its docstring]

### 21.5 The contested part — do not over-generalise

[CONTRADICTED — two real in-house result sets disagree]

- **zone_9 (RealityScan)**: baseline aligns to nothing; CLAHE 2.0/8×8 rescues it.
- **LilyJean stereo pairs (3,607 pairs, COLMAP)**: both adaptive enhancement **and** fixed
  backscatter subtraction **reduced registration ~30 %** vs originals
  (1,978 → 1,388 stereo frames, 55 % → 38 %; reprojection 0.549 → 0.751 px). Externally
  corroborated (Summers & Jones, arXiv:2507.21715 — enhancement generally degrades feature
  matching). Adding despeckle + open-water feature masks changed nothing further.
- Candidate explanations on record: **engine** (RealityScan applies internal tone mapping
  before detection), **detector**, or **imagery regime** (zone_9's baseline is
  catastrophically flat; LilyJean's baseline aligns well).
- [OPEN] Reconciliation matrix **Q-05**: zone_9 × COLMAP and LilyJean × RealityScan,
  judged on **REGISTRATION**, never on keypoint or pair counts. **Never run.**

**Visual verification with its cost, on H2024 output** — eight random frames read from the
pipeline's own `preprocessed_images` artifacts (not re-applied): hull plating goes from flat
grey to legible painted characters and rivet lines (`C231C4652`); encrustation texture
emerges from near-uniform murk (`C231C5220`, `C231C2970`). **Cost:** particulate is
amplified with the signal, invisible marine snow becomes distinct speckle, and
water-column haze lifts; `C231C3153` is a near-featureless frame that ends up merely
brighter and noisier. Consistent with the staff caution that a high detector sensitivity
manufactures noise points on turbid imagery — this sharpens Q-05 rather than settling it.
[VERIFIED: FINDINGS 2026-07-26]

### 21.6 Decision in force

**CLAHE stays UPSTREAM of batching and alignment until Q-05 settles** — so the imagery that
is aligned **and** textured is the CLAHE'd imagery. RealityScan **Image Layers**
(`.geometry` / `.texture` / `.mask`, §17) is agreed as the eventual mechanism for
"align on originals, texture from enhanced" but is **NOT adopted** and has never been
exercised through this CLI. Revisit if Q-05 resolves, or if an H2024 align shows CLAHE
hurting registration on this rig's imagery.
[VERIFIED-as-decision: HANDOFF 2026-07-26 §"CLAHE stays where it is"] [OPEN]

**Do not trust the module docstring on this point.** `preprocess_images.py` still says
"Align on the processed copies; **keep the originals for texturing**" — that describes the
intended end state, not the pipeline in force, which textures from the processed copies
because the batcher hands the same tree to both stages. The decision above is
authoritative. [VERIFIED-by-inspection of the docstring vs `batch_directory.__get_input_dir`,
2026-08-04]

Pipeline order in force: **Extract Images → Georeference → Preprocess Images → Batch
Directory → RealityScan Alignment.**

---

## 22. Measured scale and cost figures

Everything below is a measurement made through this CLI, not an estimate.

| Operation | Scale | Cost |
|---|---|---|
| Georeference (flight-log build) | 29,620 images | ~5 min |
| Georeference | 8,197 images | ~1 min |
| Batch into zones (target 1,000) | 18 zones | 6.6 min |
| Zone align, single scene | 124 / 852 / 976 / 1,476 / 1,596 / 2,983 / 4,540 images | ~4 min … ~87 min |
| Joint align (single `-align`, cell C_joint) | 4,131 images | 168.8 min, peak ~165 GB on a 192 GB box (27 GB commit headroom left) |
| Sequential grow through 3 zones (strategy B) | 4,131 images | 444 min, ≤ 60 GB |
| `-selectImage` literal path | per image | 0.1–0.3 s |
| Full-file image verification (PIL `.verify()`) | 18k × 39 MB stills | **≈ 720 GB of reads — untenable**; a header probe cut the georeference stage to ~5 min |
| Hardlinked image pool | 9,835 files | 35.8 GB logical, **0.05 GB actual** |
| Image decode census (full decode, not verify) | 8,197 JPGs | zero corruption, `camera_registry.identify` classified all (cinema 4,100 + port 4,097, zero unknown) |

[VERIFIED: FINDINGS.md / HANDOFF.md / testing/MERGE_TEST_PLAN.md cells B and C_joint,
2026-07-21 … 2026-07-28]

**Memory note that belongs here:** joint alignment extrapolates to **~700 GB for a
19k-image dive**, so chunking into zones is **mandatory** at production scale — this is
why the image-input strategy (zones, image lists, a shared pool) exists at all.
[VERIFIED: NA167 #19, 2026-07-24]

---

## 23. Failure-signature quick table

| Symptom | Cause | Fix |
|---|---|---|
| `-addFolder` returns in ~25 s, `Added 0 layer images` in `RealityScan.log`, then every flight-log row fails `err:18002` | subdirectories not included | `-set "appIncSubdirs=true"` before **every** `-addFolder` (§4) |
| Calibration priors have no effect at all, sidecar counts arithmetically impossible | sidecars named `image.jpg.xmp` instead of `image.xmp` | rename to `<stem>.xmp`; the wrong form is ignored **silently** (§5) |
| An "independent" re-run reproduces a previous solve suspiciously well | leftover pose-bearing sidecars re-imported as exact-pose priors | sanitise the tree to calibration-only content between runs (§5) |
| XMP export completes in 0.057 s instead of 20.5 s and writes nothing | a live image selection (typically left by `-importFlightLog`) + `-silent` auto-answering the Export Selection dialog | `-deselectAllImages` before every export (§13.3) |
| `-selectImage` with a regexp selects nothing, no error | this build matches literal full paths only (bare/wrapped/glob forms) | per-image literal `union` loop; try the documented `g/…/` form (§13.1) |
| Zero `.xmp` written after a component export, workflow reports success | scene images resolve through a **directory junction** (write side) | de-junction the tree; hardlink the `.jpg`, copy the `.xmp` (§12.3) |
| Recursive harvest finds 0 sidecars where the real path shows thousands | PowerShell 5.1 `Get-ChildItem -Recurse` does not descend into junction children | enumerate from the real path, or use Python `os.walk`; guard with `assert_harvestable` (§12.3) |
| `-importComponent` never returns, `#timeout`, no error, no minidump | `.rsalign` moved away from its original export location | import only in place; pass `.complist` of in-place paths (§12.1) |
| Merge scene has 4,865 cameras but its union flight log 4,227 rows | per-zone **copies** — same basename, two files, one trajectory row | build zones from a common pool via `.imagelist` (§12.4) |
| First path in a list file silently ignored | UTF-8 BOM written by PowerShell `Set-Content -Encoding utf8` | write with `UTF8Encoding($false)` or ASCII (§3) |
| One camera of a "grouped" set solves different intrinsics | its images have a different pixel footprint (3846×2163 vs 4244×2827) | expected; a footprint change defeats the calibration group (§16.4) |
| After an identity harvest, a re-align silently runs partly ungrouped | the harvest **moved** every pose-bearing sidecar out of the tree | `camera_registry.ensure_calibration_sidecars()` before any re-align (§16.5) |
| Preprocessed (CLAHE) run silently reuses raw-pixel zones | enhanced copies share filenames with the raw set, and copies are skipped by name | fingerprint the image **source**, not just the flight log (§21.4) |

---

## 24. Open questions

Every `[OPEN]` in this document, with the cheapest probe that closes it. Ordered by value.

| # | Question | Cheapest probe |
|---|---|---|
| 1 | **Does `-selectImage` accept Epic's documented `g/…/` delimiter form, and is the pattern matched against the full path or the basename?** The bisection probes covered bare, `.*`-wrapped, glob and explicit-`set` regexps — not the delimited form used in **every** Help example. If it works, whole-camera-family selection stops costing 0.1–0.3 s × N. The path-vs-basename half decides whether `^`/`$` anchors are usable at all (§13.1). | On a loaded zone scene: `-deselectAllImages`, `-selectImage "g/C231C/"`, `-editInputSelection "inpEnabled=false"`, save to a scratch `.rsproj`, compare the enabled count against the same run with `-selectImage "C231C.*"`. Then repeat with `"g/^C231C/"` — a match means basename matching, no match means path matching. ~2 min. Quote every pattern: unquoted `^` is eaten by cmd. |
| 2 | **Do hardlinked paths give shared camera identity for `-mergeComponents`, or only shared inodes?** Route B in §12.4 is assumed, not measured; the whole cheap-common-pool plan rests on it. | Two 60-image scenes whose overlap is reached through two different hardlink paths; align both; import both components into one scene; `-mergeComponents`. Minutes of reconstruction + "Finalizing 1 component" = identity holds; instant success = it does not. ~30 min. |
| 3 | **What file format does `-importImageSelection` accept, and does it replace or union?** It is the only documented bulk-selection primitive that is not O(N) delegated commands. | 3-line file of full paths → `-importImageSelection` → `-editInputSelection "inpEnabled=false"` → `-align`; a 3-image drop in the registered count proves it. ~2 min on the smoke fixture. |
| 4 | **Is there any CLI-observable count of the current image selection?** Selection state is currently write-only from the CLI's point of view. | Export ALIGNMENT ▸ Registration as an *Image list* (contains all enabled or selected images) with a GUI-saved params XML and count lines. Requires one GUI session to produce the params file. |
| 5 | **Does a UTF-8 BOM break a `.imagelist` for RealityScan's own reader?** Confirmed to break `.complist` for this repo's consumers; RealityScan's list reader untested. | Write the same list twice, with and without a BOM; `-add` each into a fresh scene; compare `Added N layer images`. ~2 min. |
| 6 | **Which `sensorsdb.xml` does the running app read** — `C:\ProgramData\Epic\RealityScan\` (as documented) or the install-tree copy? Both are byte-identical today, so the question is invisible until one is edited. | Add a distinctive `<camera model="PROBE-CAM" ccdWidth="9.99"/>` to one copy only, import a matching image, read the prior. ~5 min. |
| 7 | **What are the accepted `layerType` strings for `-setImageLayer` / `-setImagesLayer` / `-removeImageLayer`?** The Help gives only "e.g., mask, texture". | Issue each candidate token (`geometry`, `mask`, `labels`, `depth`, `texture`, `texture02`) once from the GUI console view and record which error. ~5 min. |
| 8 | **Is there a key for the "Enable masks for texturing and coloring" toggle?** `inpMaskOpts` covers only alignment and meshing, while the GUI has three independent toggles. | Set it in the GUI, export the input settings, diff for a new key; or dump the binary's `inp*` strings. |
| 9 | **Does `-generateAIMasks` respect the current image selection?** Not stated anywhere. | Select 3 of 120 smoke-fixture images, run it, count resulting mask layers. ~5 min. |
| 10 | **Does `-addFolder` interpret a subfolder named with a layer token (`_mask\`, `.texture\`) as a layer rather than as inputs?** Directly affects any per-camera folder naming convention. | Create `_mask\` under a fixture zone with 3 JPGs, `-addFolder` the parent with `appIncSubdirs=true`, and check whether the count rises by 3 or the images arrive as a mask layer. ~3 min. |
| 11 | **Does downscaling help registration or metric scale on 12 MP underwater stills?** `sfmImageDownscaleFactor=1` has never been varied. | One zone_3-scale align (124 images, ~4 min) at factor 2 vs the pinned 1, judged on registered count **and** the scale oracle. |
| 12 | **Q-05 — reconciling the CLAHE contradiction.** zone_9 × COLMAP and LilyJean × RealityScan, judged on REGISTRATION. Decides whether preprocessing stays default-on, becomes per-dataset, or moves to texture-only via Image Layers. | The four-cell matrix. Not cheap, but nothing smaller settles it — the two existing result sets are both real and both correct in their own regime. |
| 13 | **Has Image Layers ever worked through this CLI?** The agreed mechanism for "align on originals, texture from enhanced" is entirely untested here. | On the 120-image smoke fixture: place `<name>.jpg` (raw) and `<name>.jpg.texture.jpg` (CLAHE'd) side by side, `-addFolder`, align, texture, and confirm two layers appear and the texture came from the enhanced set. ~20 min. |
| 14 | **`-addImageWithCalibration`: can one XMP be attached to many images, and how does it scale?** It would move priors out of the image tree entirely, killing the contamination class in §5 and the stripping defect in §16.5. | Two calls on the smoke fixture pointing at one `cinema.xmp`; read the calibration group back off an exported pose XMP. ~5 min. |
| 15 | **Does `-add` accept a directory (behaving as `-addFolder`), and does a list file with a non-`.imagelist` extension work?** | `-add "F:\...\zone_1"` and `-add "zone_1.txt"` on the fixture; read `Added N layer images` each time. ~3 min. |
| 16 | **`-exportMapsAndMask` vs `-exportDepthAndMask`** — which name is real in 2.2? | Issue both from the GUI console view; one will error. ~1 min. |
| 17 | **`inpSkew` is documented as the key for both Skew and Aspect ratio.** One is wrong or one setting is unreachable. | Set `inpSkew` on one image from the console view and read both fields back in the panel. ~2 min. |
| 18 | **`.geometry.jpg` vs `.base.jpg`** for HDR-converted files — the same Help topic uses both. | Import one 16-bit TIFF via `-importHDRimages` and list the output folder. ~3 min. |
| 19 | **`lisPreferImagesAsFeatureSource` default mismatch** — the Help says the GUI control defaults to Yes; this repo's GUI-exported `AlignmentParams.xml` carries `false`. | Export alignment settings from a clean GUI profile and read the value. ~2 min. |
| 20 | **Are `-importVideo`'s frame timestamps correct?** This repo's own extractor had a one-interval offset; RealityScan's has never been checked. | The same synthetic per-frame-gray video used to find the repo bug, imported with `-importVideo` at a known `jumpsLength`. ~10 min. |
| 21 | **Is there a CLI key for "Prefer Exif over XMP" and "Use relative image paths"?** Both are real GUI app settings with no documented key; the second one changes what a relocated `.rsproj` resolves to, which is squarely §12 territory. | Toggle each in the GUI, export/diff the app settings; or dump the binary's `app*` key strings. |
| 22 | **Symbolic links (`mklink /D`, `mklink`)** — do they behave like junctions (silently fatal) or like hardlinks (fine)? | One 3-image scene rooted at a symlinked directory; align; count `.xmp` written. ~5 min. **Until answered, treat symlinks as junctions: do not use.** |
| 23 | **Does the ungroup-and-realign refinement Epic recommends help here?** "Alignment in such case will take just a few seconds" is a claim about small, well-conditioned scenes. | `-removeCalibrationGroups` + `-align` on a solved 124-image zone; compare registered count, component count and solved intrinsic spread. ~10 min. |
| 24 | **LiDAR import, masks, HDR import, BLK3D** — none has ever been driven through this CLI. Every statement about them in this document is [OFFICIAL] only. | Out of scope for this dataset class; recorded so no later agent mistakes doc coverage for verification. |
| 25 | **What polarity does `-generateMaskFromMesh` actually write?** `appbasics/allcommands` says off-model areas are "masked out"; `tools/mask` says they are "unmasked and will be ignored". Both ship in 2.2 (§18.2). | Generate one mask on the smoke fixture, open the PNG, and read whether the model region is white or black. ~5 min. Settles the polarity before any mask is wired into a workflow. |
| 26 | **Is `Approximate` or `Unknown` the right lens prior for the two 14 mm fisheyes?** Epic explicitly recommends **Unknown** "for images with significant lens distortion, wide-angle lenses" (§15), while this rig ships `Approximate` on all four cameras. The `Approximate`-works evidence (§15 SUPERSEDED) is from the *rectilinear* Cinema camera only. | A/B on the 665-image bow fixture: `Camera:LensDistortionPrior` = `Approximate` vs `Unknown` on Port/Starboard only, same box, judged on registered count and the solved k1 spread. ~30 min. |
| 27 | **Is `lisPreferImagesAsFeatureSource` really default `true`?** The Help documents `true` in two places; this repo's GUI-exported `AlignmentParams.xml` carries `false` (§9). Irrelevant while there is no LiDAR, but it means the exported preset may not be a faithful default snapshot — which would put every other value in that file in question. | Export the alignment settings from a clean GUI profile and diff the whole file against `RS_CLI/Metadata/AlignmentParams.xml`. ~5 min, and it audits far more than this one key. |
| 28 | **Is there a `-set` key for `Maximal depth-map pixel count`?** It is a real reconstruction-settings field with no row in `tutorials/setkeyvaluetable` (§20). | Same probe as #8/#21: set it in the GUI, export the settings, diff for a new key. |
