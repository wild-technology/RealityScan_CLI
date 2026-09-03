# Complete command reference

Every command-line command of RealityScan 2.2 (`RealityScan.exe`), grouped by function,
with its exact spelling, required and optional parameters, the shipped-Help description,
the `-writeProgress` process ID where known, and — where this repository has driven it in
production — what it actually does as opposed to what the documentation claims. This
document covers **commands only**. The `-set` / `-preset` key inventory lives in
`03-settings-keys.md`; the invocation/delegation/lifecycle model in
`01-cli-fundamentals.md`; XML parameter-file schemas in `09-xml-parameter-files.md`; error
codes and races in `12-failure-modes-and-race-conditions.md`; workflow recipes in
`11-automation-patterns.md`; and the per-stage deep treatments in
`04-image-input-and-handling.md`, `05-metadata-xmp-and-sidecars.md`,
`06-georeferencing-flightlogs-and-scale.md`, `07-alignment.md`,
`08-components-and-merge.md`, `10-reconstruction-texturing-export.md` and
`13-camera-rigs-priors-and-orientation.md`.
Commands that do **not** exist but are commonly assumed to, legacy
and typo spellings that appear only in Help prose, and deprecated commands with their
replacements are all documented here rather than omitted, so that no later reader
re-derives them.

**Applies to:** RealityScan 2.2 (Epic Games), Windows, headless CLI operation.

**Tags:** [OFFICIAL] shipped Help · [VERIFIED] measured in production here ·
[CONTRADICTED] docs vs observation · [UNDOCUMENTED] · [INFERRED] · [OPEN]

---

## Contents

1. [How to read this reference](#1-how-to-read-this-reference)
2. [Universal syntax and invocation rules](#2-universal-syntax-and-invocation-rules)
3. [Group 1 — Project, application and image input](#3-group-1--project-application-and-image-input)
4. [Group 2 — Commands for selected images](#4-group-2--commands-for-selected-images)
5. [Group 3 — Delegation and instance control](#5-group-3--delegation-and-instance-control)
6. [Group 4 — Alignment, components, control points, constraints](#6-group-4--alignment-components-control-points-constraints)
7. [Group 5 — Reconstruction region and model calculation](#7-group-5--reconstruction-region-and-model-calculation)
8. [Group 6 — Model tools, ortho, export, render, report](#8-group-6--model-tools-ortho-export-render-report)
9. [Group 7 — Classification](#9-group-7--classification)
10. [Group 8 — Settings and error handling](#10-group-8--settings-and-error-handling)
11. [Commands documented only in Help prose](#11-commands-documented-only-in-help-prose)
12. [Undocumented and hidden commands](#12-undocumented-and-hidden-commands)
13. [Commands that do NOT exist](#13-commands-that-do-not-exist)
14. [Deprecated commands and their replacements](#14-deprecated-commands-and-their-replacements)
15. [Commands unusable under delegation or headless](#15-commands-unusable-under-delegation-or-headless)
16. [Instant vs long-running commands](#16-instant-vs-long-running-commands)
17. [RSNode.exe and the HTTP command channel](#17-rsnodeexe-and-the-http-command-channel)
18. [Production usage map of this repository](#18-production-usage-map-of-this-repository)
19. [Alphabetical command index](#19-alphabetical-command-index)
20. [Open questions](#20-open-questions)

---

## 1. How to read this reference

Command counts catalogued here [VERIFIED: SURVEY_commands, sweep of
`appbasics/allcommands` + all `tutorials/commandline*` pages, 2026-08-04]:

| category | count |
|---|---:|
| distinct commands in the master Help table (`appbasics/allcommands`) | 208 |
| further `RealityScan.exe` command names appearing only in Help prose | 7 |
| commands present in the shipped Help **source** but commented out of the rendered table | 1 (`-undercut`) |
| undocumented commands proven to work in production | 1 (`-importFlightLog`) |
| commands proven **not** to exist | 1 (`-selectAllComponents`) |
| **distinct `RealityScan.exe` command names catalogued** | **218** |
| flags belonging to `RSNode.exe`, not `RealityScan.exe` | 3 |
| commands used by this repository in production | 52 |

The 208 figure is a mechanical count: `appbasics/allcommands.htm` holds 209
`<td class="command">` rows, of which `defineDistance` appears twice (two parameter forms)
[VERIFIED: row count over the installed Help HTML, 2026-08-04]. `SURVEY_commands.md` totals
217 because `-undercut` (§12.2) was found only after that survey was written.

**Required vs optional parameters in this document are taken from the HTML, not the text
conversion.** The plain-text conversion of the Help collapses adjacent empty table cells, so
a row like `| detectMarkers | params.xml | …` is ambiguous about which column the parameter
sits in. Every parameter column in this reference was resolved by reading the two
`<td class="parameter">` cells of the corresponding `<tr>` in
`C:\Program Files\Epic Games\RealityScan_2.2\Help\en-US\appbasics\allcommands.htm`
[VERIFIED: 2026-08-04]. Several earlier "the table says required but the text says optional"
readings turned out to be artifacts of that collapse and have been removed.

Each group below is presented as:

- a **complete table** of every command in that group — exact spelling, required
  parameters, optional parameters, compressed official description, and the
  `-writeProgress` `algId` where the Help's process-ID table gives one; then
- **detail blocks** (`### \`-command\``) for the commands where there is something real to
  add: gotchas, sequencing requirements, silent no-ops, prerequisites, cost, contradictions
  with the documentation, and runnable examples.

A command with no detail block has nothing established beyond its table row. That is a
statement about this repository's evidence, not a claim that the command is trivial.

Notation in tables and signatures:

| notation | meaning |
|---|---|
| `a\|b\|c` | one of these literal alternatives |
| `<name>` | a value you supply |
| `[x]` | optional |
| — | no parameters |
| ▶ | a detail block for this command follows the table |

Product-name rule: everything is **RealityScan** / RS. The strings `.rcproj`, `.rcalign`,
`.rccmd` and `.rcconfig` are legacy extensions that the 2.2 binary still accepts and that
still appear in the shipped Help; they are reproduced verbatim where they are literal
[OFFICIAL: appbasics/allcommands]. Setting keys named `RealityCapture*` are **dead** — see
`03-settings-keys.md`.

---

## 2. Universal syntax and invocation rules

These apply to every command in this document.

**Invocation.** Commands are passed as arguments of `RealityScan.exe` and executed in
sequence, left to right. Every command begins with a single hyphen; its parameters follow,
space-separated [OFFICIAL: tutorials/commandline].

```bat
"C:\Program Files\Epic Games\RealityScan_2.2\RealityScan.exe" -load C:\MyFolder\MyProject.rsproj -selectMaximalComponent -calculateNormalModel -simplify 1000000 -save C:\MyFolder\MyProject.rsproj -quit
```

The executable on this machine is
`C:\Program Files\Epic Games\RealityScan_2.2\RealityScan.exe`. The pipeline's discovery list
is exactly five paths, in this order [VERIFIED: `realityscan_cli.py` `EXECUTABLE_CANDIDATES`]:

```
C:\Program Files\Epic Games\RealityScan_2.2\RealityScan.exe
C:\Program Files\Capturing Reality\RealityScan 2.2\RealityScan.exe
C:\Program Files\Epic Games\RealityScan_2.1\RealityScan.exe
C:\Program Files\Capturing Reality\RealityScan 2.1\RealityScan.exe
C:\Program Files\Epic Games\RealityScan_2.0\RealityScan.exe
```

An explicit `realityscan.executable` setting or the `RS_EXECUTABLE` environment variable is
tried ahead of the list [VERIFIED: same file]. Epic's own Help examples use the
unversioned `C:\Program Files\Epic Games\RealityScan\RealityScan.exe`
[OFFICIAL: tutorials/commandline].

**Four places a command can be issued** [OFFICIAL: tutorials/commandline,
tutorials/commandline_rscmd, tools/commandsequence, tools/apiproject]:

1. the Windows Command Prompt or a `.bat` file, as arguments of `RealityScan.exe`;
2. an `.rscmd` (or legacy `.rccmd`) file, executed with `-execRSCMD` /
   `-execRSCMDIndirect` or by drag-and-drop onto the application;
3. the GUI console view's command field — same syntax, ENTER executes, TAB cycles
   completions of the typed prefix and shows a tooltip listing every parameter form;
4. over HTTP through `RSNode.exe` — see §17.

**Line continuation** in `.bat` and `.rscmd` is `^` at end of line. Lines beginning with
`#`, `//`, `REM` or `rem` are comments [OFFICIAL: tutorials/commandline,
tutorials/commandline_rscmd].

**Quoting.** Any parameter containing spaces must be quoted. A `key=value` pair passed to
`-set`, `-preset`, `-editInputSelection`, `-editControlPointSelection`,
`-editConstraintSelection` or `-editOrthoProjectionSelection` must be **one quoted
argument**: `-set "appIncSubdirs=true"`.

**Never pass delimited data as a `.bat` argument.** cmd splits unquoted `;` `,` `=` into
separate arguments and Python's `subprocess` quotes only on whitespace. A `key=value`
setting that crosses a `.bat`/`subprocess` boundary unquoted arrives as two arguments;
RealityScan then logs `Parsing setting key=value … failed [err:7155]`, applies **nothing**,
and writes the parse failure into the error channel, aborting any workflow gated on it.
Lists cross the boundary as **files** (`.imagelist`, `.complist`); settings cross as
`key:value` and the workflow converts the colon to `=` inside the `.bat`
[VERIFIED: NA167 B5 / FINDINGS 2026-07-23; CLAUDE.md hard rule 8].

```bat
:: WRONG - arrives as two arguments, silently applies nothing
call Workflow.bat "sfmMergeGeoreferencedComponents=true"

:: RIGHT - colon crosses the boundary intact, converted inside the workflow
call Workflow.bat "sfmMergeGeoreferencedComponents:true"
```

**Delegation changes the timing of everything.** `-delegateTo <instance> <cmd>` **queues**
the command; the delegating `RealityScan.exe` process returns at hand-over, not at
completion. Queued commands run FIFO, so instant commands (`-set`, selection, rename) can
be fired without a completion wait — ordering is guaranteed before the next queued
operation [VERIFIED: NA167_SESSION_NOTES §1]. Long-running commands need the double-wait
pattern of §5.

**Exit codes** [OFFICIAL: tutorials/commandline_5]: `0` on success; with
`-set "appQuitOnError=true"` the decimal code of the error; `3` on a crash, with a minidump
written to the `-silent` directory.

**`.bat` files must be CRLF.** cmd's label search is byte-offset sensitive; with LF endings
the same `call :run` resolved ten times and then failed with "cannot find the batch label"
at a later call site [VERIFIED: NA167 #21, hit independently on two machines, 2026-07-23].

---

## 3. Group 1 — Project, application and image input

[OFFICIAL: appbasics/allcommands "Project and Images"; duplicated with minor wording
differences in tutorials/commandline]

| Command | Required | Optional | Official description (compressed) | algId | ▶ |
|---|---|---|---|---|---|
| `-headless` | — | — | Hide the user interface; a system-tray icon replaces it. | — | ▶ |
| `-hideUI` | — | — | Hide the UI. Unlike `-headless`, not restricted to startup, and does **not** suppress actions requiring user interaction. | — | |
| `-showUI` | — | — | Show a hidden UI. Not restricted to startup. | — | |
| `-newScene` | — | — | Create a new empty scene. | — | ▶ |
| `-load` | `MyProject.rsproj` | `recoverAutosave` \| `deleteAutosave` | Load an existing project. The optional parameter decides autosave handling: `recoverAutosave` opens the autosaved project, `deleteAutosave` deletes it and loads the original. | `20532 PROJECT_LOAD` | ▶ |
| `-save` | — | `MyProject.rsproj` | Save the current project to its original location, or save-as the given path. | `20533 PROJECT_SAVE` | ▶ |
| `-start` | — | — | Run the processes configured for the Start button. | `20735 INTERACT_START_BUTTON` | ▶ |
| `-unlockPPIProject` | `myProject.rcproj` | — | Save and unlock a PPI project for use with current RealityScan versions. Give the whole path including name and extension. | — | |
| `-add` | `imageName` | — | Import one or more images from a file path or from an image list — a text file with the `.imagelist` extension containing full paths, one per line. | `65536 IMPORT_IMAGES` | ▶ |
| `-addFolder` | `folderName` | — | Add all images in the folder. To include subdirectories use `-set "appIncSubdirs=true"`. | `65536 IMPORT_IMAGES` | ▶ |
| `-importVideo` | `videoFileName` `extractedVideoFramesLocation` `jumpsLength` | — | Extract frames from a video into a folder at an interval of `jumpsLength` seconds and import them. | `24848 IMPORT_VIDEO` | ▶ |
| `-importLeicaBlk3D` | `fileName` | — | Import a Leica BLK3D `.cmi` image sequence. | `21808 IMPORT_LEICA_BLK3D` | |
| `-importLaserScan` | `laserscanName` | `params.xml` | Add a LiDAR scan or scan list using current settings or `params.xml` (exported from the LiDAR Scan Import dialog). | `20592 IMPORT_LASER_SCAN` | |
| `-importLaserScanFolder` | `folderName` | `params.xml` | Add all LiDAR scans in the folder using settings from `params.xml`. | `20592 IMPORT_LASER_SCAN` | |
| `-importHDRimages` | `fileName`\|`folderName`\|`imageList` | `params.xml` | Import a 16-bit/HDR image, image list, or all images in a folder, using current settings or `params.xml`. | `21881 CLI_IMPORT_HDR_IMAGES`, `28677 IMPORT_HDR_IMAGES` | ▶ |
| `-addImageWithCalibration` | `fileName` `xmpFileName` | — | Import an image together with its corresponding XMP file. Use whole paths. | — | ▶ |
| `-importImageSelection` | `fileName` | — | Select scene images and/or LiDAR scans listed in a file. | `20 IMPORT_IMAGE_SELECTION` | ▶ |
| `-selectImage` | `imagePath`\|`regexp` | `set` \| `union` \| `sub` \| `intersect` \| `toggle` | Select an image by path, or images by regular expression. The modifier composes with the current selection; `set` is the default. | `21884 CLI_SELECT_IMAGE` | ▶ |
| `-selectAllImages` | — | — | Select all images in the project. | `21798 SELECT_ALL_CAMERAS` | |
| `-deselectAllImages` | — | — | Deselect all images in the project. | — | ▶ |
| `-invertImageSelection` | — | — | Invert the current image selection. | `21799 INVERT_CAMERAS_SELECTION` | |
| `-removeCalibrationGroups` | — | — | Clear all inputs from their calibration groups. | — | |
| `-generateAIMasks` | — | — | Use AI Masking to generate masks by isolating the object of interest. | — | |
| `-exportMasks` | `folderPath` `params.xml` | — | **Form 1.** Export the project's current mask images to the given folder using the XML export parameters (exported from the Export Mask Images dialog). | `14 EXPORT_MASK` | |
| `-exportMasks` | `params.xml` | — | **Form 2.** Export the mask images to the folder holding the original images. | `14 EXPORT_MASK` | |
| `-setImageLayer` | `index` `pathImage` `layerType` | — | Attach the layer image at `pathImage` to the image at `index` (1Ds-view order, 0-based). `layerType` selects the layer (e.g. `mask`, `texture`). | — | ▶ |
| `-setImagesLayer` | `pathImage` `layerType` | — | Attach the layer image to the whole current image selection. | — | ▶ |
| `-removeImageLayer` | `layerType` | — | Remove layers of the given type from the selected images. | — | |
| `-importCache` | `folderName` | — | Import resource cache data from a folder. | — | ▶ |
| `-clearCache` | — | — | Clear the application cache. The project must be saved first. | `21861 CLI_CLEAR_CACHE` | ▶ |
| `-execRSCMD` | `Commands.rscmd` | up to nine arguments → `$(arg1)`…`$(arg9)` | Execute the commands listed in an `.rscmd` (or `.rccmd`) file, optionally with report parameters. | `21882 CLI_RCCMD_EXEC` | ▶ |
| `-quit` | — | — | Quit the application. | — | ▶ |

### `-headless`

**Signature** `-headless`
**Official** Hide the user interface; a Windows system-tray icon appears instead. Up to four
instances, each with its own numbered tray icon [OFFICIAL: tutorials/headless]. The
startup-only requirement is stated **indirectly**: the `-hideUI` and `-showUI` rows of the
master table both read "Unlike headless, this command doesn't need to be run at startup"
[OFFICIAL: appbasics/allcommands]. The right-click tray menu offers **Show App** (toggling it
off re-enters headless), **About** and **Exit** [OFFICIAL: tutorials/headless].

**Behavior notes**

- RealityScan **leaves** headless mode when user interaction is required, any pop-up window
  opens, or an error is displayed. `-silent` and `-set "appQuitOnError=true"` suppress most
  of these, but some (e.g. a log-in window) still demand interaction
  [OFFICIAL: tutorials/headless].
- The tray icon is a status display: a blue arc shows process progress, a yellow background
  means paused, a red background means an error occurred [OFFICIAL: tutorials/headless].
- Production boot in this repo appends `-headless` conditionally so an instance can be
  brought up GUI-visible for inspection without changing anything else — delegation and
  monitoring behave identically either way [VERIFIED: `SetVariables.bat`
  `RS_HEADLESS_FLAG`, honours `RS_HEADLESS=0`].
- Nothing in two years of headless production recorded a licensing or activation
  interaction. That is absence of evidence, not evidence of absence
  [OPEN: whether headless RS 2.2 can hit a licence prompt that manifests as a silent hang].

**Example — the production boot line** [VERIFIED: `RS_CLI/Scripts/startRealityScan.bat`]

```bat
start "" %RealityScan% %RS_HEADLESS_FLAG% -silent "%ErrorPath%" -setInstanceName %RS_INSTANCE% ^
  %RS_CACHE_ARGS% -set "appAutoSaveMode=false" -set "appQuitOnError=false" ^
  -set "appProcessActionTime=0" -set "appProcessAction=ExecuteProgram" ^
  -set "appProcessExecCmd=wscript.exe //B \"%ErrorPath%\ErrorWriterLaunch.vbs\" $(processResult) $(processId) $(processDuration:d) %RS_INSTANCE%" ^
  -writeProgress "%ErrorPath%\progress_%RS_INSTANCE%.txt" 600
```

### `-newScene`

**Behavior notes**

- Usually unnecessary at launch — the application starts with a new scene — but it is the
  way to reset an instance without relaunching it [OFFICIAL: tutorials/commandline].
- This repo reuses a live instance rather than re-launching, by delegating
  `-newScene -deleteAutosave` to it [VERIFIED: `startRealityScan.bat`]. Note that
  `deleteAutosave` there is a **parameter of `-load`** in the Help's grammar but is accepted
  in this position; the pattern has run in production since 2026-07-21 [UNDOCUMENTED].

```bat
%RealityScan% -delegateTo RS1 -newScene -deleteAutosave
```

### `-load`

**Signature** `-load <MyProject.rsproj> [recoverAutosave|deleteAutosave]`
**Official** Load an existing project. The optional parameter decides what happens when an
autosave exists for it. The global equivalent is `-set "appAutoSaveCliHandling=…"`
[OFFICIAL: appbasics/allcommands].

**Behavior notes**

- Legacy `.rcproj` projects are still readable; new saves use `.rsproj`.
- `-load project.rsproj recoverAutosave` is the documented prerequisite for
  `-continueModelCalculation` after a crash [OFFICIAL: tutorials/commandline_2].
- [VERIFIED] A stale `<name>.rsproj.new` left beside the project by an interrupted GUI save
  makes `-load` emit warning-class `0x82000017` **while still completing**. That is enough
  to abort any workflow gated on a non-empty error marker. Setting the temp file aside
  (rename — reversible) cleans the load [FINDINGS 2026-07-29].
- Loading a large assembled project is the expensive part of any per-component loop; this
  is why `ExportDeliverables.bat` loads once and exports every component inside one session
  [VERIFIED: `ExportDeliverables.bat`].

### `-save`

**Behavior notes**

- The parameter is effectively optional: with no path the project is saved in place.
- [VERIFIED] Quitting **without** saving leaves the `.rsproj` bundle byte-stable across
  load / delete / export cycles — hash-verified twice. This is what makes the destructive
  in-session identity harvest safe: save first, peel destructively in memory, quit without
  saving [FINDINGS cells U15/U16, 2026-07-23].
- Save cost scales with the number of live models, not just geometry. `GenerateModel.bat`
  originally took two dated copies per component, one of them mid-recipe with ~15
  intermediate models live: `zone_1_c0`'s saves consumed **~81 GB**. With the dated copies
  disabled, `cluster_4_a1_c0` cost **6.8 GB** end to end, and one dated copy of the finished
  six-component project took **13.1 min / 95.2 GB** [VERIFIED: FINDINGS 2026-07-29].
- Checkpoint/rollback in this pipeline is a plain **file copy of the `.rsproj` bundle**, and
  restore is a copy back. Battle-tested in anger on a killed growth run. Component reimport
  is *not* a valid checkpoint — it drops non-member images
  [VERIFIED: FINDINGS 2026-07-23/24].

### `-start`

**Behavior notes**

- The recipe it runs is configured in the GUI's Start Button Settings (AI mask, alignment
  precision, component choice, reconstruction region and mode, mesh filtration, colours and
  texturing, smooth, simplify, reprojection) — a **GUI-only prerequisite**
  [OFFICIAL: appbasics/startbutton]. Never exercised by this repo.

### `-add`

**Signature** `-add <imageFile|list.imagelist>`

**Behavior notes**

- [VERIFIED] Works as documented. CRLF line endings in the `.imagelist` are fine; full
  paths, one per line [NA167 wave-1 A2, 2026-07-23].
- This is the mechanism for **shared-path components** — the same image path present in
  more than one scene's components — which is what lets `-mergeComponents` fuse by camera
  identity [VERIFIED: NA167 §Project & image input].
- [VERIFIED] Adding images **auto-imports `<stem>.xmp` sidecars sitting next to them**, and
  pose-bearing sidecars silently become exact-pose priors. Clean the image tree before any
  run that must be independent of a previous solve [NA167 B7, 2026-07-22].
- [VERIFIED] Registration is independent of how images were added: folder vs imagelist on
  identical zones gave 95.2 % vs 95.3 % (zone_6) and 90.1 % vs 91.0 % (zone_4)
  [NA167 wave-1 A1 vs A2, 2026-07-23].
- [VERIFIED] `<stem>.xmp` only. `image.jpg.xmp` files are ignored **silently** — a batcher
  bug wrote priors that way, so no historical run before 2026-07-22 ever loaded its
  calibration priors [NA167 #3 / B7].

**Example**

```bat
%RealityScan% -delegateTo RS1 -add "F:\na156_h2024\lists\zone_1.imagelist"
%RealityScan% -delegateTo RS1 -add "F:\na156_h2024\images\zone_1\C231C1034.jpg"
```

### `-addFolder`

**Signature** `-addFolder <folderName>`

**Behavior notes**

- [VERIFIED — the Help is right, and an earlier contrary reading is SUPERSEDED] The Help
  says subdirectories require `-set "appIncSubdirs=true"`, and in this 2.2 build they do. An
  H2023 run with the key unset added **"0 layer images"**, and every subsequent flight-log
  row then failed `err:18002` inside a 25-second run that reported success; the evidence is a
  `RealityScan.log` snapshot reading `Added 0 layer images` [FINDINGS 2026-07-23]. The
  `NA167_SESSION_NOTES` entry "in our 2.2 build subfolders were included **without** setting
  the key (zone_13: `wca/` + `zeuss/` both imported)" is **SUPERSEDED**: that run had
  `appIncSubdirs` set by the fixed workflow, so the flag — not the build — was the variable
  [FINDINGS 2026-07-23, "Nuance" clause]. Operational rule unchanged and unconditional: emit
  `-set "appIncSubdirs=true"` immediately before every `-addFolder`.
- [VERIFIED] A routine `-addFolder` reports process **result 1** through the
  `appProcessExecCmd` completion trigger. 0 and 1 are both success; only other codes are
  failures [FINDINGS 2026-07-21].
- [VERIFIED] Per-camera zone subfolders are **one alignment scene**, not several. Aligning
  each camera subfolder separately defeats mixed-camera co-registration — a pre-overhaul
  defect [NA167 #5 + 2026-07-22 fix pass].
- [VERIFIED] RealityScan writes **no XMP sidecars at all** when a scene's images resolve
  through a **reparse point** (directory junction), and reports success. Controlled probe:
  baseline components exported from real image paths harvested `identity_r0` = **267**
  sidecars (= 116+94+57, the exact camera count), attribution EXACT; the same workflow over
  components whose `.rsalign` files had baked in junction paths harvested **zero**, silently,
  on **all 18 attempts** (cluster_0 ×3, cluster_1 ×15). Use real directories of hardlinked
  images, not junctions
  [FINDINGS 2026-07-27] [UNDOCUMENTED: no Epic coverage of reparse-point behaviour].
- [VERIFIED — the harness half of the same trap, distinct cause] PowerShell 5.1
  `Get-ChildItem -Recurse` does **not** descend into junction **children** (it does resolve a
  junction it is pointed at directly). Enumerating a directory of per-zone junctions returned
  0 `.xmp`; the same tree through its real path returned 9,835. This discarded **155 minutes**
  of correct GPU work, and a re-run that cleared only the read side burned **157 more**
  before the write-side cause above was found. Both halves must be fixed; neither implies the
  other [FINDINGS 2026-07-27, the second entry marked SUPERSEDED AS A CAUSE].

**Example** [VERIFIED: `AlignZone.bat`]

```bat
:: instant -set, FIFO-ordered ahead of the queued addFolder, so no wait is needed
%RealityScan% -delegateTo RS1 -set "appIncSubdirs=true"
call :run -addFolder "F:\na156_h2024\zones\zone_1"
```

### `-importVideo`

**Signature** `-importVideo <videoFileName> <extractedVideoFramesLocation> <jumpsLength>`

**Behavior notes**

- `jumpsLength` is the inter-frame interval in **seconds** [OFFICIAL].
- Adjacent finding, not about this command: this repo's own OpenCV frame extractor
  timestamped frames **one output interval early** (60 s at 1 fpm) because frame seek and
  timestamp source used different frame indices. Any dataset extracted with the old
  `__extract_video_cv2` carries the offset [VERIFIED: NA167 #1, 2026-07-22]. RealityScan's
  own extraction has not been checked for an equivalent offset
  [OPEN: extract a synthetic per-frame-gray video through `-importVideo` and read the
  resulting EXIF/XMP timestamps].

### `-importHDRimages`

Note the lowercase `i` in `images` — the literal spelling is `-importHDRimages`. The
`params.xml` comes from the 16-bit/HDR Images Import dialog (GUI-only prerequisite)
[OFFICIAL: appbasics/allcommands].

### `-addImageWithCalibration`

**Signature** `-addImageWithCalibration <fileName> <xmpFileName>`

**Behavior notes**

- The two files need **not** share a name or a folder. This is the only way to attach an
  XMP whose name or location differs from the image's [OFFICIAL: tools/xmpalign]. Every
  other path — `-add`, `-addFolder` — requires the strict `<stem>.xmp` convention beside the
  image [VERIFIED: NA167 B7].
- Not used by this repo: the pipeline writes `<stem>.xmp` sidecars beside the images
  instead, through `camera_registry.ensure_calibration_sidecars()`.

### `-importImageSelection`

This **selects**, it does not import. It is the file-driven counterpart of `-selectImage`
and, unlike `-selectImage` in this build, it takes a list rather than one path per call
[OFFICIAL: appbasics/allcommands]. Never exercised here
[OPEN: whether `-importImageSelection` accepts the same literal-path list an `.imagelist`
holds, which would replace the per-image `-selectImage union` loop below at a fraction of
the cost — probe: write 100 paths to a file, run it, export XMP and count].

### `-selectImage`

**Signature** `-selectImage <imagePath|regexp> [set|union|sub|intersect|toggle]`
**Official** Select an image by path or images by regular expression. Modifiers:
`set` (default — select matches, deselect everything else), `union` (add matches to the
selection), `sub` (deselect matching images), `intersect` (keep only already-selected
matches), `toggle` (invert the selection state of matches)
[OFFICIAL: appbasics/allcommands, tutorials/commandline].

Documented regexp forms [OFFICIAL: tutorials/commandline]:

| example | intent per the Help |
|---|---|
| `-selectImage D:\sample\Images\IMG_0018.JPG` | select one image by direct path |
| `-selectImage g/DSC/` | images with `DSC` in the name |
| `-selectImage g/2.1/` | `2`, any character, `1` (e.g. `image_1251.jpg`) |
| `-selectImage g/[02468]\.jpg/` | names ending in an even digit with `.jpg` |
| `-selectImage g/DSC.*[02468]\.jpg/` | both conditions |

**Behavior notes**

- [CONTRADICTED — high severity] In this 2.2 build **only literal full paths select
  anything.** Bare regexp, `.*`-wrapped regexp, glob, and regexp with an explicit `set`
  modifier all silently select **nothing**; a literal full path selects exactly its image.
  Established by bisection probes U-SEL2…U-SEL8 [FINDINGS 2026-07-23; H2023 U1/U19/U2].
  [OPEN: forum-mine the regexp dialect — a staff reply may explain the discrepancy;
  standing follow-up since 2026-07-23.]
- Consequence: selection composition is a **per-image literal union loop** at roughly
  0.1–0.3 s per image, i.e. minutes for thousand-image sets [VERIFIED: same].
- Selection commands are instant and delegated commands run FIFO, so the loop fires without
  a per-image completion wait; the next `:run` call flushes the whole queue before checking
  the error marker, so a bad path still aborts the pass there
  [VERIFIED: `GrowZone.bat` `:selectFromList`].

**Example — the production selection loop** [VERIFIED: `GrowZone.bat`]

```bat
:selectFromList
for /f "usebackq delims=" %%L in ("%~1") do (
    %RealityScan% -delegateTo %RS_INSTANCE% -selectImage "%%~L" union
)
exit /b 0
```

### `-deselectAllImages`

**Behavior notes — load-bearing**

- [VERIFIED] Flight-log import leaves the matched images **actively selected**, and
  selection-driven exports under `-silent` then export **nothing**: the "Export Selection"
  dialog is auto-answered, and an XMP export that should take 20.5 s finished in 0.057 s
  having written no files. `-deselectAllImages` before **every** export is mandatory
  [FINDINGS 2026-07-23] [UNDOCUMENTED: the Help does not warn that import leaves a
  selection].
- Every export step in every production workflow here is preceded by it
  [VERIFIED: `AlignZone.bat`, `MergeZoneComponents.bat`, `GrowZone.bat`].

### `-setImageLayer` / `-setImagesLayer` / `-removeImageLayer`

**Signatures**
`-setImageLayer <index> <pathImage> <layerType>` — `index` is the image's position in the
1Ds view, 0-based.
`-setImagesLayer <pathImage> <layerType>` — applies to the whole current image selection.
`-removeImageLayer <layerType>` — removes that layer type from the selected images.

**Behavior notes**

- The Help's command table only exemplifies `mask` and `texture` for `layerType`. The
  Image Layers page enumerates the layer types RealityScan detects automatically:
  `.geometry` (equivalent to an image or folder with no layer extension), `.mask`,
  `.labels`, `.depth`, `.textureXX` (`.texture` = `.texture1` = `.texture01`). Folder-name
  separators may be `.` `_` `@` `#` or `!` [OFFICIAL: tools/imglayers].
- The custom-layer naming grammar the GUI parses is
  `ImageName.($imgExt)($sep)($LayerDef)($optNum)($sep OR '')($LayerName).($imgExt)`, where
  `($sep)` ∈ `.` `_` `@` `#` `!` and `($optNum)` distinguishes several layers of one type.
  Documented examples: `Image01.png.texture03@Third.Texture.png`,
  `Image02.jpg!geometry_My Geometry.jpg`, `DSC_0001.jpg.mask.png`
  [OFFICIAL: tools/imglayers].
- [OFFICIAL] The **Geometry layer cannot be removed** — it is not even offered in the GUI's
  Remove-image-layer list [tools/imglayers]. `-removeImageLayer .geometry` therefore has no
  meaningful target [INFERRED from that statement; untested].
- [OPEN] Whether `-setImageLayer` accepts those strings with the leading dot, without it, or
  only a subset. Cheapest probe: type each name once into the GUI console view and read the
  error/no-error, or set one layer and check the Selected input table.
- Image Layers is the agreed eventual mechanism for aligning on original imagery while
  texturing from CLAHE-enhanced imagery, but it has **never been exercised through this
  CLI** [VERIFIED-as-decision: HANDOFF 2026-07-26] [OPEN].

### `-importCache`

Used in the split GPU-PC/CPU-PC depth-map precomputation workflow: precompute depth maps on
the GPU box with `-set "PrecomputeDepthmaps=true"`, move the project and cache, then
`-importCache` on the CPU box and compute the model with the flag back to `false`
[OFFICIAL: tutorials/commandline_2]. Epic recommends against sharing the cache on a network
drive; keep it on a local SSD on both machines and copy between them
[OFFICIAL: tutorials/commandline_2].

### `-clearCache`

**Behavior notes**

- The project must be **saved** before clearing [OFFICIAL].
- Cache retention is otherwise governed by the `appCacheLocation` /
  `appCacheCustomLocation` / `appAutoClearCache` keys — see `03-settings-keys.md`
  [VERIFIED: FINDINGS 2026-07-26].
- [VERIFIED] The cache is placed by the **drive of the path given** and does **not** move
  when the project moves. `D:\rccache` reached 1,089 GB and refilled 197 GB of
  freshly-cleaned space within one run, killing the same model three times, while the
  **project** drive showed 773.9 GB free [FINDINGS 2026-07-26, "TRUE ROOT CAUSE"].
- Epic's own guidance: do **not** hand-delete cache files; free space on the cache disk or
  change the cache disk. A cache-full abort loses the operation's progress
  [OFFICIAL: Epic "Out of Disk Space", quoted in FINDINGS 2026-07-26].

### `-execRSCMD`

**Signature** `-execRSCMD <Commands.rscmd> [arg …]`

**Behavior notes**

- [CONTRADICTED] `appbasics/allcommands` says "up to nine arguments … reference these
  using `$(arg1)`–`$(arg9)`". `tutorials/commandline_rscmd` says "you can pass up to 10
  arguments - the first argument and path to the executed file is required" and documents
  `$(arg0) $(arg1) ... $(arg9)`. Both pages ship in the same build. The contradiction is
  **internal to one page**: `commandline_rscmd`'s own "Additionally, you can use these global
  variables" list ends at "`$(arg1)`, ..., `$(arg9)` - variables passed to execrscmd command"
  — `$(arg0)` never reappears.
  [OPEN: an `.rscmd` containing `-tag $(arg0)`, invoked with one argument, settles it.]
- The all-lowercase spelling `-execrscmd` is used throughout
  `tutorials/commandline_rscmd`; the master table spells it `-execRSCMD`. Both presumably
  work, which is the only evidence that command parsing is case-insensitive
  [INFERRED] [OPEN: run `-EXECRSCMD` on a trivial file, or `-QUIT`].
- Additional `.rscmd` syntax [OFFICIAL: tutorials/commandline_rscmd]: global variables
  `$(appRootDir)` (installation folder), `$(appStartDir)` (folder `RealityScan.exe` was
  executed from), `$(cmdStartDir)` (folder holding the `.rscmd`); and a loop construct
  `$For( "i", from, step, to, … )` over the right-open interval. Quote variables used as
  path arguments — unquoted paths with spaces split into separate parameters.

**Example** [OFFICIAL: tutorials/commandline_rscmd]

```bat
:: sample.bat
"C:\Program Files\Epic Games\RealityScan_2.2\RealityScan.exe" -execrscmd D:\MyFolder\addFolder.rscmd "D:\MyFolder\Images"
```

```
:: addFolder.rscmd
-addFolder $(arg1)
```

### `-quit`

**Behavior notes**

- [VERIFIED] Verify shutdown by polling `-getStatus`, not by assuming: large scenes close
  slowly and the process outlives its `getStatus` visibility. The execution layer uses
  `SHUTDOWN_VERIFY_TIMEOUT_SECONDS = 900` and `STATUS_CALL_TIMEOUT_SECONDS = 60`
  [NA167 §`-quit`, B3; `realityscan_cli.py`]. `CLAUDE.md` documents the shutdown bound as
  300 s — the code is authoritative for behaviour, the doc is stale.
- Shutdown timing has only been verified on **small** scenes
  [OPEN: time `-quit` → `-getStatus` gone once on a 4,000+ camera scene; costs one
  teardown].
- Every workflow here ends with a bare delegated `-quit` (not routed through `:run`,
  because the instance disappears before a completion wait could return):

```bat
%RealityScan% -delegateTo %RS_INSTANCE% -quit
```

---

## 4. Group 2 — Commands for selected images

[OFFICIAL: appbasics/allcommands "Commands for Selected Images"; duplicated in
tutorials/commandline]

**Every command in this group operates on the current image selection.** Establish it first
with `-selectImage`, `-selectAllImages` or `-importImageSelection`; clear it afterwards with
`-deselectAllImages` before any export (see §3). Each of these commands has an equivalent
`-editInputSelection` key, given in the last column — the key form is preferred in this
repo because it is one quoted `key=value` argument that cmd cannot split.

| Command | Required | Optional | Official description (compressed) | `-editInputSelection` key | ▶ |
|---|---|---|---|---|---|
| `-setFeatureSource` | `0`\|`1`\|`2` | — | Feature-source mode for the selected images: `0` merge using overlaps, `1` use component features, `2` use all image features. | `aligFeaturesMode` | ▶ |
| `-enableAlignment` | `true`\|`false` | — | Enable/disable the selected images in the registration process. | `inpEnabled` | ▶ |
| `-enableMeshing` | `true`\|`false` | — | Enable/disable the selected images in model computation/meshing. | `inpMeshing` | |
| `-enableTexturingAndColoring` | `true`\|`false` | — | Enable/disable the selected images during colouring and texture calculation. | `inpTexturing` | |
| `-setWeightInTexturing` | `<0,1>` | — | Weight of the selected images in colouring/texturing. | `inpImageColorsWeight` | |
| `-enableColorNormalizationReference` | `true`\|`false` | — | Mark the selected images as colour references; their colours are not changed. | `inpColorRef` | |
| `-enableColorNormalization` | `true`\|`false` | — | Enable/disable the selected images in colour normalization. | `inpColorNorm` | |
| `-setDownscaleForDepthMaps` | `integer` | — | Depth-map computation downscale factor for the selected images. | `inpImageDepthMapDownscale` | |
| `-enableInComponent` | `true`\|`false` | — | Enable the selected images in meshing and continue. Registered images only. | — | |
| `-setCalibrationGroupByExif` | — | — | Set the calibration group of **all inputs** from their Exif. | — | ▶ |
| `-setConstantCalibrationGroups` | — | — | Group all selected inputs into a single calibration group. | — | |
| `-lockPoseForContinue` | `true`\|`false` | — | Keep the relative camera pose unchanged for the selected images during the next registration. Registered images only. | `inpPosePriorRelative`, `inpPosePriorRelativeGroup` | ▶ |
| `-setPriorCalibrationGroup` | `number` | — | Prior calibration group: `-1` = do not group; any other number groups the selection together. | `inpCalibrationGroup` | ▶ |
| `-setPriorLensGroup` | `number` | — | Prior lens (distortion) group: `-1` = do not group; any other number groups the selection. | `inpLensGroup` | |
| `-editInputSelection` | `"key=value"` | — | Edit any Selected-Inputs-panel setting of the current selection, by key. | (itself) | ▶ |

### `-editInputSelection`

**Signature** `-editInputSelection "<key>=<value>"`
**Official** Edit the settings of the selected inputs based on the value in the Selected
Inputs panel, or on its key [OFFICIAL: appbasics/allcommands]. The full key table is
`tutorials/editselectioncommand`.

This is the **master per-image control** and it reaches settings that have no dedicated
command of their own — most importantly the per-image prior pose, prior calibration and
lens-distortion priors.

| group | key | values |
|---|---|---|
| masking | `inpMaskOpts` | `0` do not use · `1` only in alignment · `2` only in meshing · `3` both |
| features | `aligFeaturesMode` | `0` merge using overlaps · `1` use component features · `2` use all image features |
| view | `inpVisible` | `true` \| `false` (camera cone in the 3Ds view) |
| enable | `inpEnabled` | `true` \| `false` (alignment) |
| enable | `inpMeshing` | `true` \| `false` |
| enable | `inpTexturing` | `true` \| `false` |
| texturing | `inpImageColorsWeight` | float 0–1 |
| colour | `inpColorRef` | `true` \| `false` |
| colour | `inpColorNorm` | `true` \| `false` |
| depth | `inpImageDepthMapDownscale` | positive int |
| prior pose | `inpPosePriorRelativeGroup` | string (locked pose group) |
| prior pose | `inpPosePriorRelative` | `0` Unknown · `1` Draft · `2` Exact |
| prior pose | `inpPose` | `0` Unknown · `1` Position · `2` Position and orientation · `3` Locked |
| prior pose | `inpTx` `inpTy` `inpTz` | float — x/y/z; also Longitude/Latitude/Altitude. DMS with a cardinal prefix (`N54,49,31.25`) or decimal degrees with a cardinal prefix (`N54.825347`) are accepted for lat/long |
| prior pose | `inpRx` | float −180…180 (Yaw / Heading) |
| prior pose | `inpRy` | float −90…90 (Pitch / Elevation) |
| prior pose | `inpRz` | float −180…180 (Roll / Bank) |
| pose accuracy | `inpPriorAccuracyInh` | `0` global camera prior settings · `1` edit custom values |
| pose accuracy | `inpuTx` `inpuTy` `inpuTz` | float ≥ 0 — position X/Y/Z, also Longitude/Latitude/Altitude accuracy |
| pose accuracy | `inpuRx` `inpuRy` `inpuRz` | float ≥ 0 — yaw/pitch/roll accuracy |
| prior calibration | `inpCalibrationGroup` | int ≥ 0, or `-1` (groupless) |
| prior calibration | `inpCalibration` | `0` Unknown · `1` Approximate · `2` Fixed |
| prior calibration | `inpFocal` | float > 0 — focal length, 35 mm equivalent |
| prior calibration | `inpPPX` `inpPPY` | float — principal point x/y in mm |
| prior calibration | `inpSkew` | float — **the Help lists `inpSkew` for both Skew and Aspect ratio**; treat the aspect-ratio row as a documentation defect |
| prior lens | `inpLensGroup` | int ≥ 0, or `-1` (groupless) |
| prior lens | `inpDistortion` | `0` Unknown · `1` Approximate · `2` Fixed |
| prior lens | `inpDistortionModel` | `0` no lens distortion · `1` Division · `2` Brown3 · `3` Brown4 · `4` Brown3 with tangential · `5` Brown4 with tangential |
| prior lens | `inpRadial1` … `inpRadial4` | float |
| prior lens | `inpTangential1` `inpTangential2` | float |

[OFFICIAL: tutorials/editselectioncommand]

Every setting also has a long "path" key spelling (e.g.
`Prior lens distortion/Camera model`); the short keys above are the ones used here
[OFFICIAL: same page].

**Behavior notes**

- [VERIFIED] `"inpEnabled=false"` works as a single quoted `key=value` argument, and
  `-align` honours the enable/disable state exactly [FINDINGS 2026-07-23, cells U1/U19/U2].
- [VERIFIED — hard limit] `inpPose=3` (Locked/Exact) **takes effect but makes `-align`
  refuse to run incrementally**: *"prior set to 'Exact' mode must be all aligned in a single
  run. Incremental adding is not supported."* Pose-locking is therefore unusable as a
  growth anchor; checkpoint/rollback stays the primary never-shrink mechanism
  [FINDINGS cell U18 FAIL, 2026-07-23].
- [VERIFIED — must re-enable before saving] A component-mode growth pass disables most of
  the scene, and that state **persists into the save**. A saved zone project must always be
  the all-enabled state, since it is the authoritative artifact. `GrowZone.bat` originally
  fell through to `:save_quit` without re-enabling; every component pass would have saved a
  crippled scene [FINDINGS 2026-07-24].
- [CONTRADICTED — global vs per-image distortion] `sfmDistortionModel` is **global and
  all-or-nothing**; a per-camera XMP `Camera:DistortionModel` hint does **not** switch
  models per camera. All 2,558 cinema pose XMPs from PD-6 came back
  `xcr:DistortionModel="division"` despite their sidecars declaring `brown3`, identical to
  the 2,492 port records. Whether `inpDistortionModel` set through this command can override
  per-image where the XMP cannot is **not established**
  [FINDINGS 2026-07-26; PD-2] [OPEN].
- Process ID `21877 CLI_SET_SELECTED_INPUTS_PROPERTY`.

**Example — enable a subset, disable everything else** [VERIFIED: `ProbeSubsetAlign.bat`]

```bat
call :run -selectAllImages
call :run -editInputSelection "inpEnabled=false"
call :run -deselectAllImages
call :selectFromList "F:\na156_h2024\lists\primary.imagelist"
call :run -editInputSelection "inpEnabled=true"
call :run -align
```

### `-setFeatureSource`

**Behavior notes**

- [VERIFIED] This trio (`-setFeatureSource`, `-selectImage`, `-editInputSelection`) was
  wrongly recorded as GUI-only in an earlier test plan. It **is** CLI, and it composes with
  `-selectImage` for per-camera merge-mode experiments
  [SUPERSEDED: MERGE_TEST_PLAN §1 "GUI-only", corrected 2026-07-23; VERIFIED: NA167 B11].
- What the three modes mean for component integration [OFFICIAL: appbasics/components]:
  `0` **Merge using overlaps** uses only the images/points common to the components — much
  faster and far lower memory; `1` **Use component features** uses only the points that were
  used in the imported component's own alignment — the most common and fastest type,
  beneficial under RAM shortage; `2` **Use all image features** is the slowest, recommended
  only for a small number of camera poses.
- [VERIFIED — the setting is consumed by `-align`, not by `-mergeComponents`] The Features
  source field lives in the Selected Inputs panel and feeds the **alignment** solver's
  component-integration strategy; `-mergeComponents` is a separate mechanism and does not read
  it. Read `0` "images/points common to the components" as **shared-path images**, not
  duplicate copies of the same picture — see the identity rule under `-add`
  [FINDINGS 2026-07-23, caveat added at the 2026-07-24 reconciliation].

### `-enableAlignment`

`-enableAlignment true|false` is the legacy equivalent of
`-editInputSelection "inpEnabled=true|false"`. `GrowZone.bat` keeps it as an opt-in fallback
behind `RS_GROW_SELECT_CMDS=legacy`; the key form is the default because the pair is
composed inside the `.bat` and cmd can never split it
[VERIFIED: `GrowZone.bat` `:selEnable` / `:selEnableLegacy`].

### `-setCalibrationGroupByExif`

**Behavior notes**

- The Help's wording says it sets the calibration group of **all inputs**, not just the
  selection, despite appearing in the selected-images group [OFFICIAL].
- [VERIFIED-by-inspection] Unusable for this rig in either position: the WCA rendered JPGs
  are **EXIF-identical across cameras** (Make `Z CAM`, Model `E2-F6`, no focal length, no
  lens tag, 4244×2827). RealityScan cannot tell the cameras apart from EXIF, so grouping by
  Exif would merge two physically different cameras into one calibration group. Per-image
  XMP sidecars carrying `Camera:CalibrationGroup` / `Camera:LensDistortionGroup` are the
  only mechanism that separates them — one group per **physical camera**, never per lens
  type [settings-evaluation §1–§2, 2026-07-23].
- That the sidecar grouping works is demonstrable: given the **same** 16.0 mm prior, the
  solve separated the two cameras by 5.6 % with IQRs of ±0.5 % — cinema focal 16.374
  (IQR 16.302–16.476), division k1 −0.0378; port focal 15.499 (IQR 15.435–15.574),
  division k1 −0.3875. The order-of-magnitude k1 gap is the fisheye declaring itself
  [VERIFIED: FINDINGS 2026-07-26, 5,050 harvest records].

### `-setPriorCalibrationGroup` / `-setPriorLensGroup` / `-lockPoseForContinue`

Never exercised through the CLI here — the equivalent state is written into `<stem>.xmp`
sidecars by `camera_registry.py` before the images are added. `-lockPoseForContinue` maps to
`inpPosePriorRelative` (`0` Unknown / `1` Draft / `2` Exact) plus
`inpPosePriorRelativeGroup`, which is the **relative** pose lock and a different setting
from the absolute `inpPose=3` that `-align` refuses to grow incrementally
[OFFICIAL: tutorials/editselectioncommand; VERIFIED for `inpPose=3`: FINDINGS U18]
[OPEN: whether relative locking (`inpPosePriorRelative=2`) is subject to the same
"single run" restriction — probe: set it on a solved component, add one image, `-align`,
read the error].

---

## 5. Group 3 — Delegation and instance control

[OFFICIAL: appbasics/allcommands "Delegate commands"; tutorials/commandline_deleg]

Up to **four** concurrent instances. Instance names **cannot contain spaces**. `*` targets
the first instance found.

| Command | Required | Optional | Official description (compressed) | ▶ |
|---|---|---|---|---|
| `-setInstanceName` | `instanceName` | — | Assign a name to this RealityScan instance. | ▶ |
| `-delegateTo` | `instanceName`\|`*` | the command sequence follows | Delegate a command or a sequence of commands to a named instance, or to the first available instance with `*`. | ▶ |
| `-waitCompleted` | `instanceName`\|`*` | — | Pause execution of further commands until the current process finishes in that instance. | ▶ |
| `-getStatus` | `instanceName`\|`*` | — | Return the progress status of the running process in that instance. | ▶ |
| `-pauseInstance` | `instanceName`\|`*` | — | Pause the currently running process in that instance. | ▶ |
| `-unpauseInstance` | `instanceName`\|`*` | — | Resume a paused process. | |
| `-abortInstance` | `instanceName`\|`*` | — | Abort the currently running process. When processing is driven by CLI commands, **all subsequent processes are aborted too**. | ▶ |
| `-execRSCMDIndirect` | `instanceName`\|`*` `commands.rscmd` | up to nine arguments → `$(arg1)`…`$(arg9)` | Execute the commands listed in an `.rscmd`/`.rccmd` file inside the named instance. | |

### `-setInstanceName`

```bat
RealityScan.exe -setInstanceName RS1
```

**Behavior notes**

- It names **the process it is passed to**, so it is a startup argument of the instance being
  launched — it is not something you delegate at a running instance. Every other command in
  this group takes an already-named instance as its parameter
  [OFFICIAL: tutorials/commandline_deleg; VERIFIED: `startRealityScan.bat` passes it on the
  `start ""` line].
- Multi-GPU pinning is done **around** this command, not by it: RealityScan uses all CUDA
  GPUs by default, so the instance is launched with `CUDA_VISIBLE_DEVICES` exported from
  `RS_GPU_DEVICES`, one instance name per GPU set
  [VERIFIED: `startRealityScan.bat`; CLAUDE.md].
- Multi-GPU **parallel** instances have never been run here. Single-instance pinning is
  exercised; two concurrent instances on different GPUs is untested
  [OPEN: boot RS1 on GPU 0 and RS2 on GPU 1, align two small zones simultaneously, confirm
  marker-file isolation and no cache contention].
- [VERIFIED — incident] `RS_INSTANCE` was **not** an input to the Python execution layer
  until 2026-07-28: it resolved the instance from constructor arg → `rs_settings.json` →
  default and only ever *wrote* the env var for the `.bat` layer, so every driver exporting
  `RS_INSTANCE` was decorative. A cross-session incident ran a probe on RS1 believing it was
  on RS2, and could have `-quit` a live production instance [FINDINGS 2026-07-28].

### `-delegateTo`

**Signature** `-delegateTo <instanceName|*> <command> [parameters …]`

**Behavior notes**

- [VERIFIED] Delegated commands are **queued FIFO**, and the delegating process returns at
  hand-over, not at completion. Instant commands such as `-set` therefore need no
  completion wait — FIFO guarantees they execute before the next queued operation
  [NA167_SESSION_NOTES §1; HANDOFF 2026-07-21].
- A failure to hand the command over (dead instance) makes the delegating process exit
  non-zero with "Failed to delegate command". [VERIFIED] After a **crash**, that is the
  signature seen on the *next* delegated command — a dead instance, not a rejected operation
  [FINDINGS 2026-07-26].
- Every operation in every production workflow here goes through `-delegateTo %RS_INSTANCE%`
  inside the shared `:run` subroutine [VERIFIED: `RS_CLI/Scripts/*.bat`].

### `-waitCompleted`

**Behavior notes**

- [CONTRADICTED] The Help implies it blocks until the running process is done. Observed: it
  **returns prematurely** when issued before the instance has picked up the queued command.
  The mitigation baked into every workflow is grace delay → wait → grace → wait
  [NA167 §`-waitCompleted`; FINDINGS 2026-07-21; CLAUDE.md hard rule].
- Do **not** infer completion any other way. In particular, do not gate on growth of the
  results log: RealityScan 2.2 emits periodic internal **heartbeat** processes through the
  same completion trigger, so "the results log grew" does not mean "our command finished".
  A completion check built that way raced ahead of a running `-align` and was removed
  entirely [VERIFIED: HANDOFF 2026-07-21].
- Do **not** infer completion from process names (`tasklist`) — the pre-2.x code did that
  and silently broke [CLAUDE.md hard rule 2].

**The `:run` contract — reproduced literally in every workflow** [VERIFIED: measured live,
with a non-empty error marker (aborts, exit 1) and an empty one (continues), 2026-07-24]

```bat
:run
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
        echo ERROR: RealityScan reported a failure during: %*
        exit /b 1
    )
)
exit /b 0
```

`ping -n N 127.0.0.1` is the grace delay — `timeout` needs a console, which a headless
parent does not have.

### `-getStatus`

**Console output form** [OFFICIAL: tutorials/commandline_deleg]

```
id:0x10001 progress:57.5% runtime:4.26sec endEstimation:3.40sec
```

It is redirectable: `RealityScan.exe -getStatus * > D:\statusreport.txt`.

**Behavior notes**

- [UNDOCUMENTED] `errorlevel` is **0 iff the instance exists**. This is the repo's readiness
  test at boot and its shutdown verification, and it is the only instance-liveness query
  there is.
- [VERIFIED] "Gone" precedes process teardown by **seconds**: file handles — notably the
  `-writeProgress` marker — are released **after** `getStatus` already reports the instance
  dead. Marker deletion must retry for up to ~60 s [NA167 #14 / B3, 2026-07-23].
- Boot readiness is polled at ~1 s intervals up to 120 tries (120 s) before the boot script
  gives up [VERIFIED: `startRealityScan.bat`].

**Example — reuse a live instance, otherwise launch one**

```bat
%RealityScan% -getStatus %RS_INSTANCE% >nul 2>&1
IF /I "%ERRORLEVEL%"=="0" (
    %RealityScan% -delegateTo %RS_INSTANCE% -newScene -deleteAutosave
    goto :eof
)
```

### `-pauseInstance` / `-unpauseInstance` / `-abortInstance`

Intended for render-farm priority juggling: pause a running process so a higher-priority job
can run, then unpause it [OFFICIAL: tutorials/commandline_deleg]. `-abortInstance` also
aborts every process queued after the running one when processing is CLI-driven
[OFFICIAL].

**Behavior notes**

- None of the three has ever been exercised in this repo. The standing policy is to
  **stall-warn, never auto-kill** an alignment: `#timeout` in the progress stream does not
  reliably mean hung (a successful 94.6 % run emitted 40 `#timeout` lines), and there is
  deliberately no overall timeout on any RealityScan operation
  [VERIFIED: NA167 #28, 2026-07-24; `realityscan_cli.py` `STALL_WARNING_SECONDS = 2*60*60`;
  CLAUDE.md hard rule 3].
- [OPEN] Whether `-abortInstance` leaves the project in a recoverable state, and whether
  `-continueModelCalculation` can resume from it. Cheapest probe: abort a preview model on
  the smoke fixture, then `-load` + `-continueModelCalculation` and see whether it finds the
  partial model.

---

## 6. Group 4 — Alignment, components, control points, constraints

[OFFICIAL: appbasics/allcommands "Alignment"; tutorials/commandline_1]

### 6.1 Alignment and components

| Command | Required | Optional | Official description (compressed) | algId | ▶ |
|---|---|---|---|---|---|
| `-align` | — | — | Align images using the current settings. | `65537 ALIGN_NORMAL`, `77840 SFM_ALIGNMENT_MAIN`, `77824 SFM_MATCHING` | ▶ |
| `-draft` | — | — | Align images in draft mode using the current settings. | `65538 ALIGN_DRAFT` | ▶ |
| `-update` | — | — | Update all components and models by a rigid transformation to fit the actual constraints and control points. | `65542 UPDATE_CONSTRAINTS` | ▶ |
| `-detectFeatures` | — | — | Run feature detection according to the alignment settings. Detected features are saved in the application cache. | `65539 SFM_FEATURES_DETECTION` | ▶ |
| `-mergeComponents` | — | — | Merge already created components. No new images are added to existing components. | — | ▶ |
| `-exportXMP` | — | `params.xml` | Export camera metadata of components created in the last alignment, in XMP format, using current settings or `params.xml` (from the XMP metadata export dialog). Components must satisfy `-setMinComponentSize`. XMP files are stored in the same folder as the respective images. | `20584 EXPORT_XMP` | ▶ |
| `-exportXMPForSelectedComponent` | — | — | Export camera metadata of the **selected** component in XMP format using current settings. XMP files are stored beside the respective images. | `20584 EXPORT_XMP` | ▶ |
| `-importComponent` | `component.rsalign` | — | Import a component from the `.rsalign` file. | `20594 IMPORT_COMPONENT`, `20597 IMPORT_COMPONENT_STRUCTURE` | ▶ |
| `-loadBundler` | `filePath` | `params.xml` | Import a Bundler project; the optional configuration file defines scene transformation / coordinate-system settings saved from the import dialog. | — | |
| `-loadColmap` | `filePath` | `params.xml` | Import a COLMAP project (path to any of the three text files); optional configuration file as above. | — | ▶ |
| `-exportLatestComponents` | `folderName` | — | Export components created in the last alignment as `.rsalign` into the given folder. Components must satisfy `-setMinComponentSize`. | — | ▶ |
| `-setMinComponentSize` | `size` | — | Minimal component size for export when using `-exportLatestComponents` and `-exportXMP`. Default **5**. | — | ▶ |
| `-exportSelectedComponentDir` | `folderName` | — | Export the selected component into a folder as a `.rsalign`. | — | ▶ |
| `-exportSelectedComponentFile` | `fileName` | — | Export the selected component into a named `.rsalign` file. | — | ▶ |
| `-exportRegistration` | `fileName` | `params.xml` | Export registration to a file using current settings or `params.xml` (from the Export Registration dialog). | `20576 EXPORT_REGISTRATION`, `41061`–`41064` | ▶ |
| `-exportUndistortedImages` | `folderName` | `params.xml` | Export undistorted images into a folder using current settings or `params.xml` (Export Registration dialog). | `21812 EXPORT_UNDISTORTED_IMAGES` | ▶ |
| `-exportSTMap` | — | `folderName` `params.xml` | Export ST maps for the selected images. With neither parameter, results are stored beside the original images using current settings. | `43 EXPORT_ST_MAPS` | |
| `-exportSparsePointCloud` | `fileName` | `params.xml` | Export 3D tie points (sparse point cloud) to a file — path plus format extension — using current settings or `params.xml` (Export Point Cloud dialog). | `20585 EXPORT_POINT_CLOUD` | |
| `-selectComponent` | `componentName` | — | Select a component with the specified name for further processing. | `21857 CLI_SELECT_COMPONENT` | ▶ |
| `-selectMaximalComponent` | — | — | Select the largest component for further processing. | — | ▶ |
| `-selectComponentWithLeastReprojectionError` | — | — | Select the component with the smallest reprojection error, based on the calculated Mean error [pixels]. | — | ▶ |
| `-renameSelectedComponent` | `newComponentName` | — | Rename the currently selected component. | `21859 CLI_RENAME_SELECTED_COMPONENT` | ▶ |
| `-deleteSelectedComponent` | — | — | Delete the currently selected component. | `21863 CLI_DELETE_SELECTED_COMPONENT` | ▶ |
| `-deleteComponent` | `index` | — | Delete a component by index. Index numbers start at 0. | — | ▶ |
| `-deleteAllComponents` | — | — | Delete all components. | — | |
| `-setCamerasGravityDirection` | — | `componentID` | If the images' XMP contains `xcr:Gravity`, rotate the component so `-z` points along gravity. Applies to the selected component, or the one given by ID. Affects the sparse point cloud (alignment) only, not the mesh. | — | ▶ |

### `-align`

**Signature** `-align` — **no parameters**.

**Behavior notes**

- [CONTRADICTED] `-align "<AlignmentParams.xml>"` is not supported in 2.x: an XML argument
  is **silently ignored**. Alignment settings must be applied as `-set` commands *before* a
  plain `-align`. Older repo scripts and pre-2.x lore passed a params file
  [FINDINGS 2026-07-21, confirmed against `appbasics/allcommands`].
- [OFFICIAL — `-align` is the *first* of four documented merge mechanisms, and the only one
  that can register new imagery] `tutorials/mergecomponents` lists the options for connecting
  a split scene, in its own order: (1) **run alignment again** — "RealityScan will first use
  special algorithms designed for merging components"; (2) the **Merge Components** tool
  (= `-mergeComponents`), which adds no new images; (3) **control points**, which manually
  link images across components so transformations can be estimated; (4) **ground control
  points**, georeferencing every component into a common space; (5) **adding more images**,
  called "one of the faster options". Re-running alignment is also the documented remedy for
  individually unaligned images: "RealityScan will continue from the previous state and it
  will try a different strategy to register these images"
  [OFFICIAL: tutorials/mergecomponents, tutorials/mergecomponents_images]. Only mechanisms
  (1) and (5) are reachable from this repo's workflows; (3) and (4) have never been driven
  through this CLI (§6.2).
- [VERIFIED] With components already in the scene, `-align` is align/**update**: it adds
  newly added images to existing components and can fuse components
  [NA167_SESSION_NOTES §1; corroborated by the D7 probe wave].
- [VERIFIED] `-align` can **shrink** components — re-optimization drops marginal cameras
  (3,860 → 3,855; one component's pass lost 51 previously-registered images). A free
  re-align is never pose-stable: it moved all 118 cameras of a solved smoke scene
  [FINDINGS 2026-07-23/24, U18 bonus].
- [VERIFIED] Alignment **fragmentation** is strongly nondeterministic; total **registration**
  is not. zone_1 (4,540 images, identical settings, sidecars and inputs) aligned to 2
  components / 4,391 cameras in one run and 9 components / 4,392 in another. Component
  structure cannot be relied on across runs — only manifest-tracked image sets can
  [FINDINGS 2026-07-24].
- [VERIFIED] Runtime varies **~3×** with scene character at equal image count (zone_6
  61.6 / 97.8 min vs zone_4 24.3 / 20.8 min, both ~1.5k frames, same GPU, each run twice).
  Budget by zone, not by image count [NA167 #20].
- [VERIFIED] Memory: per-zone aligns of ~1.5k images stayed ≤ ~60 GB; a joint 4,131-image
  align peaked ~165 GB on a 192 GB box. Joint alignment extrapolates to ~700 GB for a
  19k-image dive — chunking is mandatory at production scale [NA167 #19].
- [VERIFIED] Sequential growth and joint alignment give **identical quality** and differ
  2.6× in time and 2.7× in memory, with opposite winners: 94.6 % / 444 min / ≤60 GB versus
  94.5 % / 169 min / ~165 GB [NA167 #19].
- [VERIFIED — failure mode] One zone (NA167 zone_14, 1,476 images) fails standalone
  alignment **deterministically** (4/4) with fully clean data: RealityScan internal error
  `MSS_STR001` in the reconstruction phase, surfacing as generic `0x8000FFFF`. Data was
  exonerated by full-pixel decode, MD5 de-duplication and Laplacian checks. Its images align
  fine inside a larger scene. **Production rule: when a zone fails alignment solo, grow it
  from an aligned neighbour — do not retry solo**
  [NA167 #17/#18/#27 / B8, 2026-07-23/24] [OPEN: never reported to Epic].
- [VERIFIED] Incremental growth is state-sensitive and can **degrade** existing structure: a
  two-zone grow fragmented to an 870-camera maximal (below one input zone's solo 1,533),
  while a three-zone grow through the same stages held 3,906. Verify camera counts after
  every grow step [NA167 #29].

**Example — apply settings from a GUI-exported params file, then align**
[VERIFIED: `AlignZone.bat`]

```bat
for /f usebackq^ tokens^=2^,4^ delims^=^" %%A in ("%Metadata%\AlignmentParams.xml") do (
    echo %%A| %SystemRoot%\System32\findstr.exe /b /c:"sfm" /c:"lis" >nul
    if not errorlevel 1 %RealityScan% -delegateTo %RS_INSTANCE% -set "%%A=%%B"
)
call :run -align
```

### `-draft`

Draft-mode alignment. Governed by the same settings with the draft-specific keys
(`sfmImageDownscaleFactorDraftMode`, `sfmImagesOverlapDraftMode`,
`sfmFinalModelOptimizationDraftMode` — see `03-settings-keys.md`). Documented workflow: draft
first without `-quit`, inspect, then load and run a full `-align`
[OFFICIAL: tutorials/commandline_1]. Never exercised in production here.

### `-update`

**Behavior notes**

- [VERIFIED] It is a **similarity/rigid fit to the scene's imported constraints**, applied
  after reconstruction: it can rotate or rescale a component but cannot stiffen or repair
  its geometry [FINDINGS 2026-07-26].
- [VERIFIED] It is the step that actually georeferences a **merged** component. A merged
  component is a *new* component and does **not** inherit its parents' georeferencing;
  without constraints in the merge scene RealityScan has nothing to register it against.
  The production pattern is: import components → import the **union** flight log → merge →
  `-update` [FINDINGS 2026-07-23, owner GUI inspection called the missing step a
  "showstopper"; `MergeZoneComponents.bat`].
- [VERIFIED — risk] Because it fits to nav constraints, `-update` is also the step that can
  **set scale** and the step that will **rotate geometry to satisfy mis-converted
  orientation priors**. It is the leading ranked candidate for an observed ~45° tilt of one
  delivered component, whose *alignment* was measured to match nav to 0.8°
  [FINDINGS 2026-07-25/26/27].
- [OPEN/BLINDNESS] The result of `-update` in an assembled project is not measurable by this
  pipeline today — assemble mode exports no poses, so scale and attitude are measured on the
  assembly's *inputs* while `-update` runs afterwards unobserved. Closing it means porting
  the successive-difference harvest to a dated **copy** of the assembly project
  [FINDINGS 2026-07-25/26].

### `-detectFeatures`

Runs feature detection per the alignment settings and caches the features
[OFFICIAL]. Never invoked explicitly here — `-align` performs it. Relevant settings:
`sfmBackgroundDetectFeatures`, `sfmBackgroundDetectThreadPriority`,
`sfmFeatureDetectionQuality`, `sfmDetectorSensitivity`, `sfmMaxFeaturesPerImage`,
`sfmMaxFeaturesPerMpx` (see `03-settings-keys.md`).
[OPEN: whether a cached feature set from `-detectFeatures` is reused across instances and
across `-newScene`, which would make it a cheap pre-pass — probe: `-detectFeatures`, quit,
relaunch, `-align`, compare wall clock against a cold align.]

### `-mergeComponents`

**Signature** `-mergeComponents` — no parameters, and **no pre-selection**: it operates on
the scene's components. There is no "select all components" command (§13).

**Where it sits among the alternatives.** It is option (2) of five documented ways to connect
a split scene, and Epic's own page puts "run alignment again" **first**
[OFFICIAL: tutorials/mergecomponents; full list under `-align`]. Measured here, both
mechanisms obey the same governing rule — content overlap fuses, zero content overlap does
not (below) — with merge mode about **25 % faster** than align mode on the D7 probe, and
`-align` additionally able to register images that no component holds, which
`-mergeComponents` by definition cannot [VERIFIED: FINDINGS "D7 RESOLVED", 2026-07-24].

**Behavior notes — the most consequential set in this document**

- [OFFICIAL + VERIFIED-as-consequence] "No new images are added" is **true and
  load-bearing**: orphans can never be picked up by a merge. Only `-align` can add images
  [appbasics/allcommands; FINDINGS 2026-07-27].
- [VERIFIED — the governing rule] **Fusion is content-driven.** Content overlap ⇒ fusable by
  either mechanism, with or without georeferencing constraints in the scene. **Zero content
  overlap ⇒ silent no-fuse regardless of flags or logs.** The D7 probe: two components
  sharing *zero* basenames and zero paths but viewing the same wreck strip fused to one
  120-camera component (78+42 exact) both without any flight log in the scene (70 s) and
  with a union log plus `-update` (57 s) [FINDINGS "D7 RESOLVED", `testing/probe_d7.py`,
  2026-07-24].
- [VERIFIED — positive proof through shared cameras] A split-zone fixture — one zone divided
  into two 1,000-image halves sharing 390 images, each aligned solo (749 and 342 cameras),
  imported into a fresh scene — merged with both flags pinned false in **56 minutes** of
  merge reconstruction ending in "Finalizing 1 component" [NA167 #31 / D6, 2026-07-24].
- [VERIFIED — the silent failure] With zero content overlap it **exits SUCCESS and leaves
  the components separate**, under every mechanism × flag × path-form combination tested.
  Instant completion is the no-fuse signature; a real merge takes ~1 h for 1–4k-camera pairs
  [NA167 #23/#26/#30].
- **Verify every merge by pose-XMP camera census, never by exit status.** This is the single
  most repeated operational rule in this repository [NA167 #23; CLAUDE.md; HANDOFF;
  MERGE_STRATEGY_REPORT].
- [CONTRADICTED] `sfmMergeGeoreferencedComponents=true` — documented as merging
  georeferenced components even without visual overlap — **never manifested headless**, in
  any mechanism × flag × path form [NA167 wave-1f / D1 / D2, 2026-07-24].
  [SUPERSEDED-RISK: those cells fed the flag components georeferenced from **position-only**
  priors at 10 m claimed accuracy, so the feature's documented premise arguably was never
  met. Do not treat D1/D2 as final.] [OPEN: re-test with priors-v2 components.]
- [VERIFIED] It **retains its input components** alongside the fused one. Controlled case:
  a peel of `[267, 116, 94, 57]` = the fusion plus all three unconsumed parents. Any
  all-components export of a merge scene contains residual source copies — consumers must
  **attribute**, not enumerate [FINDINGS 2026-07-24 and 2026-07-27].
- [VERIFIED] It is a **no-op with a single component**, and its asynchronous
  re-reconstruction can clear the selection — replaced by `-selectMaximalComponent` in the
  smoke workflow [HANDOFF 2026-07-21].
- [VERIFIED] Fusion can **drop a small number of cameras**: 3,026+714 = 3,740 fused to 3,738
  (merge mode) and 3,739 (both align-mode rungs). A 5-camera loss out of 4,865 (0.10 %) was
  enough to hide a fusion entirely from exact-subset-sum attribution
  [FINDINGS 2026-07-25 / 2026-07-28].
- [VERIFIED — rigid-glue signature] Zero camera loss on a fusion between components with
  **zero shared imagery** is the signature of a rigid glue rather than a joint solve: one
  accepted `merge_georef` fusion packed **eight disjoint objects** into a single 3,615-camera
  container, RealityScan logging "Finalizing 3", then "7", then "8" components while the
  arithmetic scored each step as an exact-sum fusion with zero loss. By contrast a real
  joint solve of the hull ran under `-align`, logged "Finalizing 1", and **lost 5 cameras**.
  A keep-largest-connected-component model step would delete every smaller object from such
  a container [FINDINGS 2026-07-28].
- [VERIFIED] As a rigid **consolidation** pass it does consolidate: one zone went 9
  components → 4 in a 38-minute accepted pass over the same 4,392-image union
  [FINDINGS 2026-07-24].
- [CONTRADICTED-in-part] An Epic staff claim (2021, pre-rename, outside the 4-year trust
  window) describes Merge Components as a rigid best-fit with no re-optimization and no
  repositioning. What stands: merge cannot shrink the image set and cannot register orphans
  (corroborated by current 2.2 Help). What is **unverified**: "no re-optimization" — the
  observed 56-minute merge reconstruction and varying finalized component counts argue
  against it [FINDINGS RECON 2026-07-24].
- [OPEN] The exact semantics of "Finalizing N component(s)" in the log are not established.
  Cheapest probe: two tiny imports, one merge, count the result.
- [OPEN] `-exportLatestComponents` after `-mergeComponents` — a merge is not an alignment,
  so "components created in the last alignment" may be empty. Untested (hardening cell U9);
  the production workflow only exports all components in **align** mode for this reason.

**Example — the production merge scene** [VERIFIED: `MergeZoneComponents.bat`]

```bat
call :run -newScene
for /f "usebackq delims=" %%F in ("F:\na156_h2024\merged\cluster_0.complist") do (
    call :run -importComponent "%%~F"
)
%RealityScan% -delegateTo RS1 -set "sfmMergeGeoreferencedComponents=true"
%RealityScan% -delegateTo RS1 -set "sfmEnableCameraPrior=true"
call :run_geoimport -importFlightLog "F:\na156_h2024\merged\union_flight_log_04Q_UTM.txt" "F:\na156_h2024\merged\FlightLogParams.xml"
call :run -mergeComponents
call :run -update
call :run -deselectAllImages
call :run -setMinComponentSize 1
call :run -selectMaximalComponent
call :run -renameSelectedComponent "cluster_0_m_c0"
call :run -exportSelectedComponentDir "F:\na156_h2024\merged"
```

### `-exportXMP`

**Behavior notes**

- [VERIFIED — the naming rule] **The command determines the naming, not the scene.**
  `-exportXMP` writes **stem-named** `<stem>.xmp` sidecars beside the images; four
  consistent datapoints. An earlier session-based hypothesis ("stems require the live
  aligning session") is **SUPERSEDED** [FINDINGS 2026-07-23; NA167 B10 final form].
- [OFFICIAL + VERIFIED] It covers only "the last alignment", and silently skips components
  below `-setMinComponentSize` [HANDOFF 2026-07-21].
- [VERIFIED] Only **registered** cameras get pose entries, so counting pose-bearing sidecars
  is a reliable registration census — this is the pipeline's primary oracle
  [NA167_SESSION_NOTES §1].
- [VERIFIED] `xcr:Position` appears as an **element** (`<xcr:Position>x y z</xcr:Position>`)
  in current exports and in **attribute** form in older ones. Both forms must be parsed
  [FINDINGS 2026-07-28].
- [VERIFIED] `xcr:Position` is in a **grid-anchored local frame, not UTM**; fit local→UTM
  with `poses2flightlog.py`. The exports' lat/long XMP attributes are unusable per that
  analysis [NA167, 2026-07-23] [OPEN: cell U13 — re-verify on an *original* georeferenced
  zone scene; if positions are UTM there, manifests could carry true per-camera positions].
- [VERIFIED] Exported pose sidecars carry `xcr:CalibrationGroup="-1"` /
  `DistortionGroup="-1"` **alongside** `Camera:CalibrationGroup="3"` — the `-1` is an export
  artifact, not a lost grouping [FINDINGS 2026-07-26] [UNDOCUMENTED].
- [VERIFIED — contamination] Exported pose sidecars are auto-imported as **exact-pose
  priors** on any later `-add` of the same images. The pipeline sanitizes the tree back to
  calibration-only content after every census [NA167 B7].
- [VERIFIED — defect, fixed] The identity harvest **moves** every pose-bearing `.xmp` into
  `identity_r<K>`, and the last-peeled component's sidecars are never re-exported: measured
  on a fresh zone, **796 of 4,540 images (17.5 %) were left with no sidecar at all**,
  including an entire 665-image component. Any re-align of an already-harvested zone then
  silently runs with a partially ungrouped camera set — two prior-test cells were confounded
  this way. Fixed by `camera_registry.ensure_calibration_sidecars()`
  [FINDINGS 2026-07-25].

**Example — successive-difference membership harvest** [VERIFIED: `AlignZone.bat`]

```bat
:identityLoop
call :run -deselectAllImages
call :run -exportXMP
powershell -NoProfile -Command "Get-ChildItem -LiteralPath '%input_dir%' -Recurse -Filter *.xmp | Where-Object { Select-String -LiteralPath $_.FullName -Pattern 'xcr:Position' -Quiet } | Move-Item -Destination '%output_dir%\identity_r%comp_index%' -Force"
:: empty harvest = exhaustion terminal
call :run -selectMaximalComponent
call :run -renameSelectedComponent "%scene_name%_c%comp_index%"
call :run -exportSelectedComponentDir "%output_dir%"
call :run -deleteSelectedComponent
```

`members(c<K>) = stems(r<K>) − stems(r<K+1>)`. In an **align** scene the `identity_r<K>`
directories are cumulative (rK = laps K..end); in a **merge** scene rK is component K alone,
because merge-scene exports are ordinal [VERIFIED: FINDINGS 2026-07-28].

### `-exportXMPForSelectedComponent`

**Behavior notes**

- [CONTRADICTED] The Help gives no naming rule. Observed: it writes **ordinal** sidecars
  `00000.xmp`, `00001.xmp`, … in every observed context, never `<stem>.xmp`. The count is
  still a valid registration census, but per-camera **identity** requires `-exportXMP` in the
  original aligned scene [NA167 B10; FINDINGS 2026-07-23].
- [VERIFIED] Ordinal sidecars are **inert as priors** — no image has an ordinal stem — and
  `camera_registry.sanitize_and_census` deletes them quietly [B10, 2026-07-23].
- [VERIFIED] It can complete in a merge scene and write **nothing**: the log said "Exporting
  Registration completed in 8.758 seconds" while a sweep of the whole drive found zero
  `.xmp` written. Root cause was the **reparse-point write path** (see `-addFolder`), not
  "an imported component carries no images" — the merge scene had reported
  `Added 1407 images` [FINDINGS 2026-07-27].
- [OPEN, do not build on it] Attempts that **re-import a previously fused component**
  harvested nothing (three attempts, `identity_r0: 0`), while sibling attempts harvested
  normally. Consistent with the ordinal/identity rule but unexplained; did not recur later
  [FINDINGS 2026-07-28].

### `-importComponent`

**Signature** `-importComponent <component.rsalign>`

**Behavior notes**

- [VERIFIED — highest-severity trap] Import **only from the component's original export
  location.** A relocated copy imports into a permanent `#timeout` stall: ≥6 h observed, no
  error, no minidump, and — because `#timeout` lines keep ticking their elapsed counter —
  **zero stall warnings**. In place it is ~2 s per 0.7 GB component. The repo mitigation is
  a `.complist` of in-place paths [NA167 B1/B4; FINDINGS 2026-07-23; CLAUDE.md hard rule 7].
- [VERIFIED] `-importComponent X.rsalign` names the in-scene component `X` — the **file
  stem**. Two attempt directories exporting the same stem therefore put two identically
  named components into one assembly, and every name-resolved operation downstream becomes
  ambiguous [FINDINGS 2026-07-28].
- [VERIFIED] Component `.rsalign` files are ~0.7 GB per ~1.5k cameras and are opaque `TBSM`
  binary — there is **no readable camera list**. Membership must come from the XMP census
  [NA167_SESSION_NOTES §1].
- [VERIFIED] Component reimport does **not** carry non-member images: orphans are absent
  from a components-only project and carry no trajectory until a flight log is imported.
  Checkpoint/rollback must therefore use `.rsproj` **file copies**, not component reimport
  [FINDINGS 2026-07-23].
- [OFFICIAL] Components may contain duplicate images and points; control points placed on a
  component are exported and imported with it; an imported component is marked with a star
  icon in the 1Ds view [appbasics/components].
- [OFFICIAL, adopted as the rollback pattern] The fix-and-reimport round trip is sanctioned:
  export the faulty part → fix it in a spare scene → reimport → `-align`, which "applies
  fixes" [appbasics/components].
- `appCopyImportedComponentsToCache` exists and has never been swept here
  [OPEN: it may interact with the relocated-component hang].

### `-loadColmap`

Takes the path to any of the three COLMAP text files [OFFICIAL]. Repo context:
`archive/colmap/` holds retired COLMAP scripts and must not be resurrected into the active
pipeline [CLAUDE.md]. Cross-engine fact worth carrying: COLMAP on one zone **registered**
710 frames of the Zeuss camera family but triangulated **zero** points from them — two
engines, two failure shapes, one physical camera family
[VERIFIED-in-the-other-fact-base, recorded 2026-07-24; not reproduced in RealityScan].

### `-exportLatestComponents`

**Behavior notes**

- [VERIFIED] It exports **ALL** components of the last alignment (subject to
  `-setMinComponentSize`), not just the maximal one. An older maximal-only export pattern
  was unnecessary loss — underwater zones routinely fragment and every pocket is input to
  the merge stage [FINDINGS 2026-07-23].
- Exports are selection-driven: `-deselectAllImages` first, or they silently produce nothing
  under `-silent` [VERIFIED: `GrowZone.bat`, `MergeZoneComponents.bat`].
- [OPEN] Behaviour after `-mergeComponents` (no "last alignment") is untested — hardening
  cell U9. Cheapest probe: run merge mode on the smoke fixture, then export, then count
  files.

```bat
call :run -setMinComponentSize 50
call :run -deselectAllImages
call :run -exportLatestComponents "F:\na156_h2024\components\zone_1"
```

### `-setMinComponentSize`

**Signature** `-setMinComponentSize <size>` — default **5** [OFFICIAL].

**Behavior notes**

- **DEPRECATED**: the application logs that it "will be removed in the next release"
  [VERIFIED: read out of a per-cell `RealityScan.log` snapshot, NA167 #22 / B11,
  2026-07-24]. No replacement is documented.
- **Still required.** Without it, components below the default threshold of 5 are silently
  excluded from **selection and from XMP export**. Production sets it to 1 before any export
  and to the zone's minimum (e.g. 50) before an all-components export
  [VERIFIED: HANDOFF 2026-07-21; `AlignZone.bat`, `MergeZoneComponents.bat`].
- Related but separate: the GUI's **Small Components** grouping threshold (default: fewer
  than 3 cameras) only affects 1Ds-view grouping and the "Delete all small components"
  button [OFFICIAL: appbasics/smallcomponents]; it is not this setting.

### `-exportSelectedComponentDir` / `-exportSelectedComponentFile`

**Behavior notes**

- [VERIFIED] `-exportSelectedComponentDir` names the file after the **component**, not the
  scene (a component called `Merged` produces `Merged.rsalign`). Rename the component first,
  or snapshot the directory before and after to identify the new file. Rename → export
  writes `<newname>.rsalign` [NA167 §`-exportSelectedComponentDir`; FINDINGS U15/U16,
  2026-07-23].
- `-exportSelectedComponentFile` takes an explicit filename and would avoid the rename step;
  it has **never been exercised here** [OPEN: one smoke-fixture call settles whether it
  accepts a path with no `.rsalign` extension and whether the in-scene component keeps its
  name].

```bat
call :run -selectMaximalComponent
call :run -renameSelectedComponent "zone_1_c0"
call :run -exportSelectedComponentDir "F:\na156_h2024\components\zone_1"
:: -> F:\na156_h2024\components\zone_1\zone_1_c0.rsalign
```

### `-exportRegistration`

**Behavior notes**

- [VERIFIED] **Without a params XML it blocks forever headless.** Avoid it until a params
  file saved from the GUI Export Registration dialog exists [FINDINGS 2026-07-21].
- This is the GUI path by which a component is exported as a `.rsalign` ("RealityScan
  alignment component — only this one preserves all features of the application")
  [OFFICIAL: appbasics/components]. A complete component is exported when the current
  selection is empty or is a single-camera selection.

### `-exportUndistortedImages`

Correct spelling is `-exportUndistortedImages` (master table, and process ID
`21812 EXPORT_UNDISTORTED_IMAGES`). `tutorials/commandline_1` spells it
`-exportUndistoredImages`, missing the `t` — a documentation typo, not a second command
[INFERRED; see §11].

### `-selectComponent`

**Behavior notes**

- [VERIFIED] It **does** resolve manifest component names in an **assembled** project —
  `-selectComponent "pd6_zone_1_c0"` worked — because components imported from `.rsalign`
  files had been renamed *before* export. It silently no-ops in **zone** scenes, which were
  saved before the rename [FINDINGS 2026-07-26].
- New components are named `Component N` with **unstable N** (observed 5, 9, 0, 3, 4 across
  two zones), so name-based selection of a freshly aligned component is not reliable
  [VERIFIED-as-observation; OPEN: cell U6 — whether `-align` updates an existing component
  in place, keeping its name, when it only grows].

### `-selectMaximalComponent` / `-renameSelectedComponent` / `-deleteSelectedComponent`

**Behavior notes**

- `-selectMaximalComponent` is the **reliable selection primitive** — see §13 for the
  command that does not exist.
- [VERIFIED] All three **silently no-op on an empty scene** (no error marker). Loop
  terminals must therefore be **file-existence checks**, not error checks
  [FINDINGS 2026-07-23].
- [VERIFIED — the one exception that is usable] At the peel loop's terminal state,
  `-selectMaximalComponent` on an empty scene silently no-ops and the **following**
  `-renameSelectedComponent` fails `E_INVALIDARG 0x80070057` (2147942487) "in 0 seconds".
  Since there is **no CLI query for how many components remain**, that tolerated rename
  failure *is* the exhaustion signal; the evidence file is preserved as
  `expected_peelend_<inst>.txt` [FINDINGS 2026-07-24] [UNDOCUMENTED: no component-count
  query exists].
- `-selectMaximalComponent` selects by **size**; whether it is affected by component names
  at all is untested [OPEN: hardening cell U5].
- [OPEN] Whether `-deleteSelectedComponent` frees its images back to the unregistered pool
  in a way a subsequent `-align` can use is untested (hardening cell U4).

### `-selectComponentWithLeastReprojectionError`

[VERIFIED] Exists in this build [NA167 B11; FINDINGS 2026-07-23]. Not used here — component
choice is by camera count, because the deliverable criterion is coverage, not residual.
[OPEN: per-component reprojection error is not otherwise readable headless — hardening cell
U14; `-exportReport` with `<install>\Reports\ComponentAccuracyReport.html` is the candidate,
§8.5.]

### `-deleteComponent`

`-deleteComponent <index>`, indices 0-based [OFFICIAL]. [VERIFIED] Exists in this build
[FINDINGS 2026-07-23]. Index stability across a session is unknown, and component numbering
is observed to be unstable across alignments — prefer `-selectComponent` /
`-selectMaximalComponent` + `-deleteSelectedComponent` [INFERRED].

### `-setCamerasGravityDirection`

Requires `xcr:Gravity` in the images' XMP. Affects the **sparse cloud only**, not the mesh.
`componentID` is genuinely **optional** — it sits in the Optional column of the master
table's HTML, matching the prose ("Will apply to the selected component or to the component
defined with the optional parameters"); an earlier reading of a "required column" was an
artifact of the text conversion, see §1
[OFFICIAL: appbasics/allcommands, tutorials/commandline_1]. Never exercised here; the rig's
attitude comes from flight-log orientation priors instead.

### 6.2 Trajectory, ground control, control points, constraints, markers

| Command | Required | Optional | Official description (compressed) | algId | ▶ |
|---|---|---|---|---|---|
| `-importTrajectory` | `flFileName` | `params.xml` | Import a trajectory file using current settings or `params.xml` (from the Import Trajectory dialog). | `20598 IMPORT_FLIGHT_LOG` | ▶ |
| `-importGroundControlPoints` | `gcpFileName` | `params.xml` | Import ground control points using current settings or `params.xml`. | `20599 IMPORT_GCP` | ▶ |
| `-importControlPointsMeasurements` | `cpmFileName` | `params.xml` | Import measurements of control points using current settings or `params.xml` (Import Control Points Measurements dialog). | `20600 IMPORT_CP_MEASUREMENTS` | |
| `-editControlPointSelection` | `"key=value"` | — | Edit the settings of the selected control points by key. | — | ▶ |
| `-listControlPoints` | `fileName` | — | Export a list of control points to the given file path; each control point is listed with its index. | — | |
| `-selectControlPoint` | `controlPointName` | — | Select a control point by its name. | — | |
| `-invertControlPointSelection` | — | (`controlPointName` per tutorials/commandline_1) | Invert the control-point selection. If none are selected, all are selected. | — | ▶ |
| `-renameControlPoint` | `controlPointName` `newName` | — | Rename a control point identified by its current name. | — | |
| `-renameSelectedControlPoint` | `newName` | — | Rename the selected control point. | — | |
| `-deleteControlPoint` | — | `index` | Delete the selected control point; with `index` (0-based, 1Ds order) delete that one. | `22530 REMOVE_CONTROL_POINT` | ▶ |
| `-selectMeasurementByError` | `errorValue` | `controlPointName` | Select any measurement with a position error (pixels) ≥ `errorValue`. Without a control-point name, applies to all measurements. | — | |
| `-selectMeasurementByIndex` | `controlPointName` `index` | — | Select a control-point measurement by its index within that control point. | — | |
| `-deleteControlPointMeasurement` | — | — | Remove the selected control-point measurements (images assigned to a control point). | — | ▶ |
| `-exportGroundControlPoints` | `gcpFileName` | `params.xml` | Export ground control points using current settings or `params.xml`. | `21814 EXPORT_GCP` | |
| `-exportControlPointsMeasurements` | `cpmFileName` | `params.xml` | Export measurements of control points using current settings or `params.xml`. | `20569 EXPORT_CP_MEASUREMENTS` | ▶ |
| `-defineDistance` | `PointNameA` `PointNameB` `distance` | `constraintName` | **Form 1.** Define a distance constraint between two control points. The name is generated automatically if omitted. | `21809 DEFINE_DISTANCE` | ▶ |
| `-defineDistance` | `fileName` | `params.xml` | **Form 2.** Import distance constraints from a file using current settings or `params.xml` (Import Distance Definitions dialog). | `21809 DEFINE_DISTANCE` | ▶ |
| `-editConstraintSelection` | `"key=value"` | — | Edit the settings of the selected constraints by key. | — | ▶ |
| `-deleteConstraint` | — | `index` | Remove the selected distance constraints; with `index` (0-based, 1Ds order) remove that one. | — | ▶ |
| `-detectMarkers` | — | `params.xml` | Detect markers in images using current settings or `params.xml` (from the Detect Markers tool). | `30 DETECT_MARKERS` | |

### `-importTrajectory`

**This is the documented name for flight-log import. This repository does not use it** — it
uses the undocumented `-importFlightLog` (§12), which hits the same process ID
`20598 IMPORT_FLIGHT_LOG`.

**Behavior notes**

- The `params.xml` comes from the Import Trajectory dialog and pins the log's coordinate
  system, column mapping selection, separator, accuracy handling and Euler/mount options
  [OFFICIAL: appbasics/allcommands]. The keys actually in force in this repo's
  `FlightLogParams.xml` are `gpsLogFileFormat`, `CoordinateSystemFlightLog` (a proj4
  string), `CoordinateSystemFlightLogType` (shape:
  `epsg:32757 - WGS 84 / UTM zone 57S`), `ifCSopt=1`, `ifuuInhEn=true`, `ifuuInh=0`,
  `csvFLSep=1`, `csvFLIgn=true`, `ifUsePosAcc=true`, `ifUseOriAcc=true`, `ifKGrp=2`,
  `ifKmode=0x0` [VERIFIED-by-inspection: `RS_CLI/Metadata/FlightLogParams.xml`].
- Custom log formats are defined in `flightlogs.xml` in the install folder, with
  `reader="RealityScan.Import.CSVFlightLog"` — a **current** product string that must not be
  renamed [OFFICIAL: tools/defineimportformat; CLAUDE.md].
- [OPEN] Whether `-importTrajectory` and `-importFlightLog` are aliases of one
  implementation. Cheapest probe: run both on the smoke fixture with the same params XML and
  diff the resulting prior poses and the `20598` process records.

### `-importGroundControlPoints`

Documentation defect worth knowing: the master table says the params file comes from the
"**Export** Ground Control Points dialog"; `tutorials/commandline_1` says the **Import**
dialog. The Import dialog is the correct source [OFFICIAL: appbasics/allcommands vs
tutorials/commandline_1].

**Behavior notes**

- **Nothing empirical exists here.** `controlpoints.xml` / `groundcontrol.xml` have never
  been driven through this CLI. The only relevant recorded fact is staff-confirmed **absence
  of stereo-rig support** in RealityScan (through Aug 2025), which implies that rig-derived
  metric scale must come from GCPs, distance constraints, or locked XMP poses
  [OPEN: no GCP has ever been imported through this CLI]
  [VERIFIED-second-hand: COLMAP fact base F-20260723-27].

### `-editControlPointSelection`

**Signature** `-editControlPointSelection "<key>=<value>"`

| key | values |
|---|---|
| `gpName` | string |
| `gpEnabled` | `true` \| `false` (in the alignment process) |
| `gpType` | `0` tie point · `1` ground control · `2` ground test |
| `gpWeight` | float |
| `gpP1` `gpP2` `gpP3` | float — x/y/z; also Longitude/Latitude/Altitude. DMS with a cardinal prefix (`N54,49,31.25`) or decimal degrees with a cardinal prefix (`N54.825347`) accepted for lat/long |
| `gpuP1` `gpuP2` `gpuP3` | float ≥ 0 — position X/Y/Z accuracy, also Longitude/Latitude/Altitude accuracy |

[OFFICIAL: tutorials/editselectioncommand]

### `-invertControlPointSelection`

[CONTRADICTED] Confirmed at the HTML level, not inferred from the text conversion:
`appbasics/allcommands.htm` gives this row **two empty** `<td class="parameter">` cells — no
parameter at all — while `tutorials/commandline_1.htm` puts `controlPointName` in the
**Required** cell and leaves Optional empty. Both pages ship in the same build
[VERIFIED-by-inspection of the installed Help HTML, 2026-08-04].
[OPEN: type it bare into the GUI console view — the tooltip lists every parameter form and
answers immediately.]

### `-deleteControlPoint` / `-deleteConstraint`

In both, `index` sits in the **Optional** column of the master table's HTML, matching the
prose — there is no documentation defect here (an earlier draft claimed one; see §1 on the
text-conversion artifact). With `index` omitted both act on the current 1Ds-view selection;
`-deleteConstraint`'s text adds that "the constraints must be selected in the 1Ds view",
which is a GUI-state prerequisite with no CLI constraint-selection command to satisfy it
[OFFICIAL: appbasics/allcommands]. Indices are 0-based and follow 1Ds-view order.

### `-deleteControlPointMeasurement`

GUI-state prerequisite: the images must be selected in the 1Ds view *under* the
corresponding control point [OFFICIAL]. Reachable from the CLI only via
`-selectMeasurementByError` / `-selectMeasurementByIndex` [INFERRED].

### `-exportControlPointsMeasurements`

GUI-only prerequisite for its params file: **Shift** + the **Control Points** button in the
Export part of the ALIGNMENT tab [OFFICIAL: appbasics/allcommands].

### `-defineDistance`

**Form 1** `-defineDistance <PointNameA> <PointNameB> <distance> [constraintName]`
**Form 2** `-defineDistance <fileName> [params.xml]`

Supported import formats are listed in `distancedefinitions.xml` in the installation folder
[OFFICIAL]. Distance constraints are the CLI-reachable mechanism for imposing metric scale
without GCPs — relevant here because a uniform scale error is invisible in the viewer and
was measured at 0.175× on a 3,026-camera component
[VERIFIED: FINDINGS 2026-07-25]. Never exercised through this CLI [OPEN].

### `-editConstraintSelection`

| key | values |
|---|---|
| `cName` | string |
| `cA` | name of an existing control point |
| `cB` | name of an existing control point |
| `cEnabled` | `true` \| `false` |
| `cValue1` | float > 0 — defined distance |
| `cValue1Acc` | float > 0 — defined-distance accuracy |

[OFFICIAL: tutorials/editselectioncommand]

---

## 7. Group 5 — Reconstruction region and model calculation

[OFFICIAL: appbasics/allcommands "Reconstruction"; tutorials/commandline_2]

| Command | Required | Optional | Official description (compressed) | algId | ▶ |
|---|---|---|---|---|---|
| `-resetGround` | — | — | Set the ground plane back to its original orientation and position. | `21776 RESET_GROUND_PLANE` | |
| `-setGroundPlaneFromReconstructionRegion` | — | — | Centre a model in the middle of the grid using the reconstruction region, adjusting both rotation and translation. | `21778 SET_GROUND_PLANE_BY_RECONSTRUCTION_REGION` | |
| `-setReconstructionRegionAuto` | — | — | Set a reconstruction region automatically. | `21785 SET_RECONSTRUCTION_REGION_AUTO` | |
| `-setReconstructionRegion` | `box.rsbox` | — | Import a reconstruction region from a `.rsbox` file. | `21779 IMPORT_RECONSTRUCTION_REGION` | ▶ |
| `-setReconstructionRegionOnCPs` | `controlPoint` `controlPoint` `controlPoint` `controlPoint`\|`heightValue` | — | Set a region on existing control points: three define the base, the height comes from a fourth control point or a numeric value. | `21786 SET_RECONSTRUCTION_REGION_CP` | ▶ |
| `-setReconstructionRegionByDensity` | — | — | Set the region to the part of the sparse point cloud with the highest density. | — | |
| `-scaleReconstructionRegion` | `scaleX` `scaleY` `scaleZ` | `origin`\|`center` `absolute`\|`factor` | Scale the region per axis, as absolute values or factors, from its centre or its origin. Defaults: `absolute` and `center`. | — | ▶ |
| `-moveReconstructionRegion` | `moveX` `moveY` `moveZ` | — | Move the region along its own axes, in coordinate-system units. | — | ▶ |
| `-rotateReconstructionRegion` | `rotateX` `rotateY` `rotateZ` | — | Rotate the region around its axes; values in degrees. The axes rotate with it. | — | |
| `-offsetReconstructionRegion` | `offsetX` `offsetY` `offsetZ` | — | Offset the region along its axes by multiples of its own side lengths. | — | ▶ |
| `-exportReconstructionRegion` | `box.rsbox` | — | Export the reconstruction region to a `.rsbox` file. | `21800 EXPORT_RECONSTRUCTION_REGION` | ▶ |
| `-calculatePreviewModel` | — | — | Calculate a 3D mesh in preview quality. | `20560 CALCULATE_MODEL_PREVIEW` | ▶ |
| `-calculateNormalModel` | — | — | Calculate a 3D mesh in normal quality. | `20561 CALCULATE_MODEL_NORMAL` | ▶ |
| `-calculateHighModel` | — | — | Calculate a 3D mesh in the highest quality. | `20562 CALCULATE_MODEL_HIGH` | ▶ |
| `-continueModelCalculation` | — | — | Continue calculation of a model left unfinished by a pause or a crash. | `20601 CONTINUE_MODEL_CALCULATION` | ▶ |

Related process IDs seen in the progress stream during meshing: `8208 DEPTH_MAPS`,
`8240 MESHING`, `8242 CLUSTERING`, `20736 COMPUTING_MODEL_PARAMS`
[OFFICIAL: tutorials/processids].

### `-setReconstructionRegion` / `-exportReconstructionRegion`

A `.rsbox` is exported from the GUI (MESH & COLOR ▸ Export ▸ Reconstruction Region) and is
hand-editable, which is the documented way to build a custom region for CLI use
[OFFICIAL: tutorials/commandline_2]. Its XML shape — `<ReconstructionRegion>` with
`widthHeightDepth`, `CentreEuclid/centre`, `Residual R/t/s`, `globalCoordinateSystem`,
`yawPitchRoll` — is visible inside a `.rsortho` parameter file
[OFFICIAL: tools/xmlparamsfiles].

### `-setReconstructionRegionOnCPs`

At least three control points are required. The **first two** define the width, the **third**
the length; the height comes from a fourth control point or a numeric value in
coordinate-system units, which **may be negative**. The order of the control points defines
the region's axes: a right-handed system with its origin at the first control point and X
running from it through the second [OFFICIAL: tutorials/commandline_2].

```bat
RealityScan.exe -delegateTo * -setReconRegionOnCPs CP1 CP2 CP3 50
```

Note that the Help's own example uses the abbreviated alias `-setReconRegionOnCPs` — see
§11.

### `-scaleReconstructionRegion` / `-moveReconstructionRegion` / `-offsetReconstructionRegion`

```bat
RealityScan.exe -delegateTo * -scaleReconstructionRegion 1.1 1.1 1.2 center factor
RealityScan.exe -delegateTo * -moveReconstructionRegion 10 10 10
RealityScan.exe -delegateTo * -rotateReconstructionRegion 45 45 45
RealityScan.exe -delegateTo * -offsetReconstructionRegion 1 2 0.5
```

`origin` means the first control point when the region was set with
`-setReconstructionRegionOnCPs`. `-offsetReconstructionRegion`'s parameters are **relative
multipliers**: `1 2 0.5` offsets by one depth, two widths and half a height
[OFFICIAL: tutorials/commandline_2].

**Behavior note.** All commands that alter the region's side lengths work in
coordinate-system units (factor scaling excepted), and **behaviour is undefined for
non-georeferenced projects** — scale the coordinate system manually with distance
constraints first [OFFICIAL: tutorials/commandline_2].

### `-calculatePreviewModel` / `-calculateNormalModel` / `-calculateHighModel`

**Behavior notes**

- All three honour `-set "PrecomputeDepthmaps=true"`, in which case they **only precompute
  depth maps into the cache and create no model**. With the default `false`, previously
  precomputed depth maps in the cache are reused and only the model computation runs. The
  Help explicitly warns to set it back to `false` afterwards
  [OFFICIAL: tutorials/commandline_2].
- Production here calls `-calculateHighModel` once, on the merged/assembled component, never
  per zone [VERIFIED: `GenerateModel.bat`; CLAUDE.md].
- **Measured cost of `-calculateHighModel` plus the full 8-step recipe**, on a 93.6 GB
  dual-5090 box [VERIFIED: FINDINGS 2026-07-26 and 2026-07-29]:

| component | cameras | wall clock | peak commit | min available RAM |
|---|---:|---:|---:|---:|
| `cluster_0_a2_c0` (hull) | 4,860 | 338.3 min | **148.7 GB** | **0.9 GB** |
| `pd6_zone_1_c0` (hull, other dive) | 3,738 | 384.1 min | 142.3 GB | 0.3 GB |
| `zone_1_c0` | 1,634 | 249.3 min | 139.9 GB | 2.0 GB |
| `cluster_1_a1_c0` | 880 | 122.8 min | 138.6 GB | 2.8 GB |
| `zone_4_c0` | 576 | 106.1 min | 116.8 GB | 3.0 GB |
| `zone_1_c1` | 392 | 97.4 min | 107.1 GB | 3.5 GB |
| `cluster_4_a1_c0` | 133 | 40.1 min | 96.2 GB | 25.9 GB |

- [VERIFIED] The ~5,000-camera envelope does **not** plateau. The apparent plateau at
  ~140 GB across 392–1,634 cameras was an artifact of that range; the hull pushed ~9 GB past
  it and ran with under a gigabyte of headroom. Treat anything materially larger as at risk
  [FINDINGS 2026-07-29].
- [VERIFIED] On 3,738 cameras, `-calculateHighModel` drove available RAM from 79.4 GB to
  3.1 GB within three minutes; commit charge went 19.6 → 105 GB and Windows grew the commit
  limit from 99.5 to ~120 GB to absorb it. RealityScan's working set peaked at 62.5 GB. It
  was verified doing real work (9.1 cores busy, 33 % GPU over a 20 s window), not hanging.
  **These figures are a memory profile, not the cause of any failure**
  [FINDINGS 2026-07-26; SUPERSEDED: the reading "memory exhaustion intrinsic to this mesh"].
- [VERIFIED — the real failure cause] Three failures of one hull model were all the **cache
  disk**: a crash at `closeHoles`/`cleanModel` (minidump
  `RealityScanCrash-20260726-054742.dmp`), then a 143.5-minute run failing at texture with
  `0x80070070 ERROR_DISK_FULL`, with the instance log finally saying "Processing failed: Out
  of disk space." during `-simplify`. Attempt 4 with the cache relocated succeeded in
  384.1 min — the only variable changed [FINDINGS 2026-07-26].
- Near-OOM is a **third** cause of persistent `#timeout` in the progress stream: RealityScan
  slows to a crawl without crashing and without spilling to NVMe, indistinguishable from a
  hang. Mitigated here by sampling available RAM and warning below 4 GB free
  [VERIFIED: FINDINGS 2026-07-24; `realityscan_cli.py` `LOW_MEMORY_WARN_GB = 4.0`].

### `-continueModelCalculation`

Scans for unfinished models **from the last component backwards, and within a component from
the last model backwards** [OFFICIAL: tutorials/commandline_2].

```bat
:: after a pause, with the project saved before closing
RealityScan.exe -load project.rsproj -continueModelCalculation

:: after a crash - autosave must have been enabled beforehand
RealityScan.exe -load project.rsproj recoverAutosave -continueModelCalculation
```

**Behavior note.** This repo sets `appAutoSaveMode=false` at boot, so the crash path is
**not** available to it by construction; a failed model run instead quits without saving and
leaves the assembly intact [VERIFIED: `startRealityScan.bat`; FINDINGS 2026-07-26].

---

## 8. Group 6 — Model tools, ortho, export, render, report

[OFFICIAL: appbasics/allcommands "Model Tools"; tutorials/commandline_3]

### 8.1 Model selection, naming, colour and texture

| Command | Required | Optional | Official description (compressed) | algId | ▶ |
|---|---|---|---|---|---|
| `-selectModel` | `modelName` | — | Select a model with the specified name. | — | ▶ |
| `-deleteSelectedModel` | — | — | Delete the currently selected model. | — | ▶ |
| `-duplicateSelectedModel` | — | — | Duplicate the selected model, including textures. | `29 DUPLICATE_MODEL` | ▶ |
| `-renameSelectedModel` | `newModelName` | — | Rename the currently selected model. | — | ▶ |
| `-correctColors` | — | `layerName` | Run colour correction for all layers, or for the named layer, in the selected component. | `20563 CORRECT_COLORS`, `50 MODEL_BASED_COLORNORMALIZATION` | |
| `-unwrap` | — | `params.xml` | Calculate the unwrap of a model using current settings or `params.xml` (from the Unwrap tool). | `20737`–`20741 UNWRAP_MODEL` | ▶ |
| `-calculateTexture` | — | `params.xml` | Calculate texture using current settings or `params.xml` (from the Color and Texture Settings panel). | `7 MODEL_TEXTURE`, `20742 FILL_TEXTURES` | ▶ |
| `-calculateQualityTexture` | — | — | Calculate texture from mesh quality values (Quality Analysis). The values need not exist beforehand. | — | |
| `-reprojectTexture` | `sourceModel` `resultModel` | `params.xml` | Reproject texture from a textured model onto an unwrapped model. Both names are project model names. | `21040 REPROJECT_TEXTURE` | ▶ |
| `-calculateVertexColors` | — | — | Calculate colouring using current settings. | `8 MODEL_COLORIZE` | ▶ |
| `-calculatePreviewVertexColors` | — | — | Calculate draft colouring using current settings. | `8 MODEL_COLORIZE` | |
| `-calculateQualityColors` | — | — | Calculate vertex colours from mesh quality values. The values need not exist beforehand. | — | |

### 8.2 Mesh cleanup and triangle selection

| Command | Required | Optional | Official description (compressed) | algId | ▶ |
|---|---|---|---|---|---|
| `-simplify` | — | `targetTriangleCount` or `params.xml` | Simplify the selected model: with no parameter use current settings, else to a target triangle count, else per `params.xml` (Simplify tool). | `11 SIMPLIFY`, `44 SIMPLIFY_GROUP` | ▶ |
| `-smooth` | — | `params.xml` | Smooth the selected model using current settings or `params.xml` (Smooth tool). | `12 SMOOTH` | |
| `-closeHoles` | — | `maxEdgesCount` | Close model holes using current settings or a maximum number of edges. | `26 CLOSE_HOLES` | ▶ |
| `-cleanModel` | — | — | Clean the selected model: remove non-manifold edges and vertices, close small holes, etc. | `25 CLEAN_MODEL` | ▶ |
| `-selectTrianglesInsideReconReg` | — | — | Select triangles inside the reconstruction region. | `9 MARK_TRIANGLES` | |
| `-selectTrianglesOutsideReconReg` | — | — | Select triangles outside the reconstruction region. | `9 MARK_TRIANGLES` | |
| `-selectMarginalTriangles` | — | — | Select triangles that enclose the volume but are not part of the current reconstruction. | `21028 SELECT_MARGINAL_TRIANGLES` | ▶ |
| `-selectLargeTrianglesAbs` | `edgeSizeThreshold` | — | Select triangles with an edge length larger than the absolute threshold. | `21029 SELECT_TRIANGLES_BY_EDGE_SIZE` | |
| `-selectLargeTrianglesRel` | `edgeSizeThreshold` | — | Select triangles with an edge length larger than `threshold × average edge length`. | `21029 SELECT_TRIANGLES_BY_EDGE_SIZE` | ▶ |
| `-selectLargestModelComponent` | — | — | Select triangles belonging to the largest connected component of the model. | `21030 SELECT_MAX_CONNECTED_COMPONENTS` | ▶ |
| `-invertTrianglesSelection` | — | — | Invert the triangle selection. | — | ▶ |
| `-deselectModelTriangles` | — | — | Deselect all model triangles. | — | ▶ |
| `-removeSelectedTriangles` | — | — | Create a new model with the selected triangles left out — the same behaviour as the Filter Selection tool. | `10 FILTER_SELECTED_TRIANGLES` | ▶ |
| `-cutByBox` | `inner`\|`outer` | `fillHoles` (`true`\|`false`) | Filter out the triangles inside or outside the reconstruction region. `fillHoles` defaults to `true` (Yes). Creates a new model. | — | |
| `-undercut` | — | — | **Commented out of the shipped Help table; see §12.2.** "Undercut the selected model so that each part contains geometry just in its cluster box." | `27 UNDERCUT_MODEL_PARTS` | ▶ |

Note the abbreviated `ReconReg` spelling in `-selectTrianglesInsideReconReg` /
`-selectTrianglesOutsideReconReg` — it is not `ReconstructionRegion` there.

### `-undercut`

Listed above for completeness only. The row is present in the shipped Help **source** but
commented out of the rendered table, so it appears in no reader-visible Epic documentation.
Full account, provenance and the probe that would settle whether it still parses: **§12.2**.
Do not put it in a workflow until that probe runs.

### 8.3 Model import and export

| Command | Required | Optional | Official description (compressed) | algId | ▶ |
|---|---|---|---|---|---|
| `-exportModel` | `modelName` `fileName` | `params.xml` | Export a named project model to a file (path plus extension) using current settings or `params.xml` (Export model dialog). | `6 EXPORT_MODEL`, `21876 CLI_EXPORT_MODEL` | ▶ |
| `-exportSelectedModel` | `fileName` | `params.xml` | Export the currently selected model. | `6 EXPORT_MODEL` | ▶ |
| `-exportModelToZip` | `filePath` | `modelFormat` | Export the selected model into a compressed archive. The archive extension is optional; the model format (e.g. `.obj`, `.fbx`) is an optional parameter. | — | |
| `-importModel` | `fileName` | `params.xml` | Import a model from a file — full path, name and format extension — optionally with a settings file exported from the import dialog. | `17 IMPORT_MODEL` | ▶ |
| `-exportLod` | `fileName` | `params.xml` | Export the selected model as a **linear** Level-of-Detail model. For Cesium 3D Tiles use `-export3dTiles`. | `28672 EXPORT_LOD` | |
| `-export3dTiles` | `fileName` | `params.xml` | Export the selected model as a **hierarchical** LoD model into a `.json` (Cesium 3D Tiles). | `21813 EXPORT_CESIUM` | |
| `-generateMaskFromMesh` | — | — | Generate mask images from the existing camera views and the selected model; everything around the model as seen from the camera is masked out. | — | |
| `-exportMapsAndMask` | — | `folderName` `params.xml` | Export masks generated from the camera view over the model, plus depth and normal maps, for the selected images. With neither parameter, results go beside the original images. | `36 EXPORT_DEPTH_AND_MASK_IMAGES`, `20586 EXPORT_DEPTH_AND_MASK`, `13 EXPORT_DEPTH_MAPS` | ▶ |
| `-uploadToSketchfab` | `APIToken` | — | Upload the model to Sketchfab using the API token from the account settings. | `21802 EXPORT_SKETCHFAB`, `24576 UPLOAD_TO_SKETCHFAB` | ▶ |

### `-selectModel`

**Behavior notes**

- [VERIFIED] Matching is on the **exact** name — the prefix hazard is not real:
  `<tag>_HighPoly` does **not** match `<tag>_HighPoly_Textured`, confirmed on a real
  deliverable where the cleanup loop ran and all three kept models survived
  [FINDINGS 2026-07-28].
- [VERIFIED] Model names are mutated by the workflow. `-renameSelectedModel` at any step
  removes the old name from the project, so a later `-selectModel <oldname>` fails
  `err:5601 'not found'` [FINDINGS 2026-07-29].
- [VERIFIED] A no-op select on a missing name **leaves the previous selection live**. If the
  wait is too short to detect the miss, a following `-deleteSelectedModel` deletes whatever
  was selected before — which at cleanup-loop entry is the final textured deliverable. The
  mitigation is the full double-wait in `:try_delete_model`, plus per-model evidence
  filenames so twelve iterations cannot overwrite each other's records
  [FINDINGS 2026-07-29, GenerateModel audit #4].
- A missing name reports `2147942487` (`E_INVALIDARG`, empty selection) through the error
  channel, which is the code the tolerant wrappers whitelist
  [VERIFIED: `GenerateModel.bat`, `ExportDeliverables.bat`].
- [OPEN] Benign and unexplained: `-selectModel <tag>_HighPoly` reports the empty-selection
  code in **every** component's cleanup loop, six for six. The name is the one intermediate
  that is both renamed and immediately re-textured, so the texture step may consume it
  [HANDOFF 2026-07-29 loose end #3].

### `-renameSelectedModel` / `-deleteSelectedModel` / `-duplicateSelectedModel`

**Behavior notes**

- [VERIFIED — defect class] Fixed model names in a per-component loop against **one shared
  project** created duplicate names, and name-resolved steps (`-reprojectTexture`,
  delete-by-name) then crossed components **with a clean exit status**: one component's
  texture could be reprojected onto another's mesh silently. Every model name in
  `GenerateModel.bat` now carries a per-component `%model_tag%` prefix — 19 references
  namespaced. Discovered by reading the workflow before the second component started, not by
  a failure [FINDINGS 2026-07-25].
- [VERIFIED] A filter or simplify step can leave a **default-named residual** behind
  (`Model 1`, `Model 2`, …). Default names carry no component prefix, so they are swept
  separately; residuals from earlier components persist in a shared project. Exactly **one**
  such residual existed across a whole six-component project, not one per component as
  hypothesised [FINDINGS 2026-07-29].
- [VERIFIED] `-duplicateSelectedModel` exists in this build. It is the identified fix for
  retaining `<tag>_HighPoly_Raw`, which does **not** survive the recipe: step [2/8] renames
  the selected model to `_Cleanup1` when the marginal filter fires, so the raw name leaves
  the project. The models that actually persist per component are `_HighPoly_Textured`,
  `_Simplified_Textured`, plus one default-named residual
  [FINDINGS 2026-07-29] [INFERRED: that duplicating after step [1/8] would preserve the raw
  model; not tested].

### `-unwrap` / `-calculateTexture` / `-reprojectTexture`

**Behavior notes**

- [CONTRADICTED] `appbasics/allcommands` lists an optional `params.xml` for
  `-calculateTexture`; `tutorials/commandline_3` lists **no** parameter at all. The master
  table is correct — this repo passes a params XML in production
  [VERIFIED: `GenerateModel.bat`].
- [VERIFIED — sequencing, with mechanism] `-calculateTexture` projects **from the source
  images** with multi-band blending, so hole-fill triangles that any camera saw receive real
  blended colour. Therefore texture **after** `-closeHoles` + `-cleanModel`, never before:
  texturing a holey model and then closing holes and reprojecting produces nodata patches,
  because reprojection samples the source **surface**. The final reprojection then maps
  manifold → manifold and introduces no nodata. Residual limitation: fill areas no camera
  ever saw come out untextured under any strategy
  [docs/settings-evaluation-2026-07 §7, 2026-07-23].
- [VERIFIED] `-reprojectTexture` resolves both operands **by name**; with duplicate names in
  a shared project it silently maps the wrong component's texture
  [FINDINGS 2026-07-25].
- Texture budget in force here: **max 4 adaptive 16K textures** in both texture passes.
  `unwrapStyle=MaxTexturesCount` *is* the adaptive mode — texel size adapts to fit the count
  — so 4 × 16K caps the budget while small components use fewer and smaller textures
  [VERIFIED-as-config: HANDOFF 2026-07-29].
- Params files for all three are obtained by exporting them once from the corresponding GUI
  dialog. That is the only way to obtain a valid params XML for any tool
  [VERIFIED-as-practice: FINDINGS 2026-07-21].

```bat
call :run -calculateTexture "%Metadata%\Texturing_MaxTextureCount4_16k.xml"
call :run -unwrap "%Metadata%\Unwrapping_Simplified_4x16k.xml"
call :run -reprojectTexture "%model_tag%_HighPoly_Textured" "%model_tag%_Simplified" "%Metadata%\ReprojectionParams.xml"
```

### `-calculateVertexColors`

Used here to colour the densest surviving model **in memory only**, export a PLY with
per-vertex colour, then quit without saving so the colours never enter the project
[VERIFIED: `ExportDeliverables.bat`].

```bat
call :run -selectModel "%comp%_HighPoly_Raw"
call :run -calculateVertexColors
call :run -exportModel "%comp%_HighPoly_Raw" "%out_dir%\%comp%\ply\%comp%_dense.ply" "%Metadata%\ModelExportParamsPLY_DensePoints.xml"
```

[VERIFIED] In practice the dense PLY export falls back to `_HighPoly_Textured`, because
`_HighPoly_Raw` does not survive the model recipe [FINDINGS 2026-07-29].

### `-simplify`

**Signature** `-simplify [targetTriangleCount | params.xml]`

**Behavior notes**

- Three usable forms: no parameter (current settings), an integer target triangle count, or
  a GUI-exported params XML [OFFICIAL].
- Production passes params XMLs for a 70 %-relative "noise" pass and four 80 %-relative
  "smooth" passes with a `-cleanModel` between each
  [VERIFIED: `GenerateModel.bat`; docs/settings-evaluation-2026-07].
- [OPEN] `SimplifyNoise_Params.xml` (70 % rel) and `SimplifySmooth_80per_Params.xml`
  (80 % rel) are **placeholders derived from the 50 % template**. If owner GUI presets exist
  they should be exported over these files [standing self-audit item 5, unresolved].

### `-closeHoles` / `-cleanModel`

**Behavior notes**

- [VERIFIED] The GUI's **Check Integrity** and **Check Topology** have **no CLI commands**;
  their fix action maps to `-cleanModel` + `-closeHoles` [FINDINGS 2026-07-23]. Process IDs
  `23 CHECK_MODEL_INTEGRITY` and `28 CHECK_MODEL_TOPOLOGY` exist in the progress-ID table
  but no command drives them [OFFICIAL: tutorials/processids].
- Measured on a 3,738-camera hull: `-closeHoles` 125 s, `-cleanModel` 230 s, both succeeding
  — the failure that followed was the cache disk, not these steps
  [VERIFIED: FINDINGS 2026-07-26].
- `-closeHoles` accepts a `maxEdgesCount`; production calls it bare
  [VERIFIED: `GenerateModel.bat`].

### `-selectMarginalTriangles` / `-selectLargeTrianglesRel` / `-selectLargestModelComponent` / `-invertTrianglesSelection` / `-removeSelectedTriangles`

**Behavior notes**

- [VERIFIED] `-removeSelectedTriangles` removes the **SELECTED** set — it is the Filter
  Selection tool. So the marginal-triangle and large-triangle steps filter **directly**, and
  only the keep-largest-connected-component step needs `-invertTrianglesSelection` first
  [FINDINGS 2026-07-23].
- [VERIFIED] `-selectLargeTrianglesRel`'s threshold is in **multiples of the average edge
  length, not pixels**. The GUI's "30 px" intuition does not transfer; a visual check is
  required [FINDINGS 2026-07-23; docs/settings-evaluation-2026-07]
  [OPEN: the value `30` in `GenerateModel.bat` has never been visually validated on a real
  model].
- A selection step that finds nothing, or a remove on an empty selection, reports
  `2147942487` or `2181038335` through the error channel. Production whitelists exactly
  those two codes, skips the step and continues — a clean mesh with no marginal or large
  triangles must not abort the recipe [VERIFIED: `GenerateModel.bat` `:try_filter`].
- There is no `-selectAllTriangles`; `-deselectModelTriangles` followed by
  `-invertTrianglesSelection` is the equivalent [INFERRED — not tested].

**Example — the production filter chain** [VERIFIED: `GenerateModel.bat`]

```bat
call :try_filter -selectMarginalTriangles
call :try_filter -selectLargeTrianglesRel 30
call :run -selectLargestModelComponent
call :run -invertTrianglesSelection
call :try_remove
call :run -closeHoles
call :run -cleanModel
```

### `-exportModel` / `-exportSelectedModel`

**Signature** `-exportModel <modelName> <fileName> [params.xml]`

**Behavior notes**

- The params XML can be built by copying the `ModelExport` tag out of an exported `.rsInfo`
  into an empty `.xml` [OFFICIAL: tools/export].
- [VERIFIED] By-parts export on a real assembly produced: **OBJ** — 4 parts + per-part MTL +
  `u1_v1` textures + `.rsInfo` (exactly Nira's expected layout); **FBX** — 4 parts +
  textures; ~35–38 s each on a 133-camera component [FINDINGS 2026-07-29].
- External platform facts carried alongside: Nira recommends OBJ over FBX and **refuses PLY
  point clouds** (LAS/LAZ/E57 instead); neither Nira nor Cesium ion has a scriptable in-app
  share [VERIFIED-second-hand: vendor guidance, HANDOFF 2026-07-29].

```bat
call :run -exportModel "%comp%_Simplified_Textured" "%out_dir%\%comp%\obj\%comp%.obj" "%Metadata%\ModelExportParamsOBJ_NiraParts.xml"
call :run -exportModel "%comp%_Simplified_Textured" "%out_dir%\%comp%\fbx\%comp%.fbx" "%Metadata%\ModelExportParamsFBX_Parts.xml"
```

### `-importModel`

[CONTRADICTED] `tutorials/commandline_3` shows **no** optional `params.xml`;
`appbasics/allcommands` does. Prefer the master table. Documented pattern: select a
component first, then import — `-load … -selectMaximalComponent -importModel "%%s" -save …`
inside a `for` loop over a folder of `.obj` files [OFFICIAL: tutorials/commandline_3].

### `-exportMapsAndMask`

The master-table name is `-exportMapsAndMask` and it covers masks **plus depth and normal
maps**. `tutorials/commandline_3` documents the same row as `-exportDepthAndMask` with a
narrower description (depth maps and/or masks). See §11 — treat `-exportMapsAndMask` as the
2.2 name [INFERRED].

### `-uploadToSketchfab`

Requires the Sketchfab account's API token as its only parameter [OFFICIAL].
[INFERRED] It requires online communication and is therefore incompatible with
`-disableOnlineCommunication`; not stated in the Help, and settled by running both in one
sequence.

### 8.4 Ortho projections, cross sections, contours, shapes

None of these are used by this repository.

| Command | Required | Optional | Official description (compressed) | algId | ▶ |
|---|---|---|---|---|---|
| `-calculateOrthoProjection` | — | `rsorthoFile` `rsboxFile` | Calculate an orthographic projection with current settings; optionally a `.rsortho` parameter file, and a `.rsbox` bounding the area included. | `20564 CREATE_ORTHO_PROJECTION` | ▶ |
| `-selectOrthoProjection` | `orthoName` | — | Select an orthographic projection by name. | — | |
| `-editOrthoProjectionSelection` | `"key=value"` | — | Edit the settings of the selected ortho projections by key. | — | ▶ |
| `-exportOrthoProjection` | `orthoName` `fullPath` `params.xml` | — | **Form 1.** Export the orthophoto / DSM / DTM using settings from `params.xml`. Omitting the extension on `fullPath` produces a TIFF. | `20578`/`20579`/`20583 EXPORT_ORTHO_PHOTO` | ▶ |
| `-exportOrthoProjection` | `orthoName` `folderPath` `exportName` `params.xml` | — | **Form 2.** As above, with directory and output name given separately. Omitting the extension on `exportName` produces a TIFF. | as above | |
| `-exportOrthoProjection` | `fullPath` `params.xml` | — | **Form 3.** As above, for the currently selected projection. | as above | |
| `-calculateCrossSections` | — | `step` `axis` | Calculate cross sections with current settings, or by axis (a local axis of the reconstruction region) and step. | — | |
| `-exportCrossSections` | `fileName` | `params.xml` | Export the selected cross sections using current settings or `params.xml`. | `20744 EXPORT_MODEL_CUTS` | |
| `-renameCrossSections` | `crossSectionsName` | — | Rename the selected cross sections. | — | |
| `-selectCrossSections` | `crossSectionsName` | — | Select cross sections by name. | — | |
| `-computeContours` | — | `params.xml` | Compute contours for the selected ortho using current settings or `params.xml` (Contours tool). | — | |
| `-exportContours` | `fileName` | `params.xml` | Export the selected contours using current settings or `params.xml`. | — | |
| `-renameContours` | `contoursName` | — | Rename the selected contours. | — | |
| `-selectContours` | `contoursName` | — | Select contours by name. | — | |
| `-exportShapes` | `fileName` | `params.xml` | Export the selected shapes to a `.json` file using current settings or `params.xml`. | — | |
| `-importShapesToSelectedOrtho` | `fileName` `mosaicing`\|`measurements` | — | Import shapes into the selected ortho; their type follows the active shape-creating tool (Measure or Enhance Mosaic). | — | |
| `-importShapesToOrtho` | `fileName` `orthoProjectionName` `mosaicing`\|`measurements` | — | Import shapes into a named ortho. | — | |
| `-selectShape` | `shapeName` | — | Select a shape by name. | — | |
| `-addShapeToSelection` | `shapeName` | — | Add a shape to the current selection by name. | — | |

### `-calculateOrthoProjection`

The `.rsortho` parameter file is produced by exporting an ortho from the GUI with
**Export projection parameters file = True** [OFFICIAL: tools/xmlparamsfiles,
tutorials/commandline_3]. Its documented content:

| element / attribute | meaning |
|---|---|
| `OrthoProjection width` / `height` | projection size in pixels |
| `name` | projection name |
| `modelName` | the model to project |
| `boxSideConerIndex` | 0–23 — which side of the reconstruction region is the projected plane and which corner is upper-left. Not derivable analytically; obtain it by making one projection manually and exporting the parameters file (Epic's spelling of the attribute, `Coner`, is as shown) |
| `colorType` | `texturing` \| `coloring` |
| `bEmpty` | `0` calculate now (Render) · `1` do not calculate (Add to batch). Leave at `0` |
| `backFaceColorType` | `0` None · `1` FixedColor |
| `backFaceColor` | colour of the inner parts of the model |
| `ReconstructionRegion` block | the region whose side is the projected plane; obtained by setting the region manually and exporting it |
| `DTMParams classificationLayerId` | classification layer to build the DTM from; `-1` calculates a new classification during rendering, which then requires `ClassificationParams` |
| `ClassificationParams modelType` | `industrial_complex` \| `mixed` \| `city` \| `nature` \| `meadows` \| `countryside` \| `mountains` |
| `postprocessType` | `none` \| `soft_edges` \| `hard_edges` |
| `sensitivity` | 0–1; `0` classifies everything as Artificial object, `1` as Ground |

[OFFICIAL: tools/xmlparamsfiles]

```bat
RealityScan.exe .... -calculateNormalModel -calculateOrthoProjection %MyPath%\params.rsortho -exportOrthoProjection %MyPath%\ortho.tiff exportOrthoParams.xml -save %MyPath%\MyProject.rsproj -quit
```

### `-editOrthoProjectionSelection`

The only documented key is `orthoProjectionName` (string)
[OFFICIAL: tutorials/editselectioncommand].

### `-exportOrthoProjection`

Three parameter forms, distinguished only by arity — there is no mode flag. In every form
the `params.xml` is mandatory and comes from the corresponding GUI export dialog. Omitting
the format extension yields a **TIFF** [OFFICIAL: appbasics/allcommands].

### 8.5 Reports, renders and camera snapshots

| Command | Required | Optional | Official description (compressed) | algId | ▶ |
|---|---|---|---|---|---|
| `-exportReport` | `outputFileName` `templateFileName` | `true`\|`false` | Export an HTML report from a template. The default templates live in `<install>\Reports`. The boolean exports a file with the reports found in the template. | `20567 EXPORT_REPORT` | ▶ |
| `-printReport` | `reportString` | — | Write report text into the Command Prompt. Usable when RealityScan is run from a batch file. **Does not work with delegation.** | — | ▶ |
| `-exportCameraSnapshots` | `folderName` | `params.xml` | Render images of the model from camera positions — all images when none or only one is selected, otherwise only the selected ones. | `15 EXPORT_RENDER` | |
| `-exportSelectedCamerasSnapshots` | `folderName` `fileFormat` | `params.xml` | Render images of the model from the **selected** camera positions. `fileFormat` e.g. `jpg`, `png`. | `15 EXPORT_RENDER` | ▶ |
| `-renderMeshFromCustomPositionYPR` | `fileName` `params.xml` — **or** — `fileName` `width` `height` `focalLength` `x` `y` `z` `yaw` `pitch` `roll` | — | Render the model from a camera pose defined by yaw/pitch/roll. | — | ▶ |
| `-renderMeshFromCustomPositionLookAt` | `fileName` `params.xml` — **or** — `fileName` `width` `height` `focalLength` `x` `y` `z` `atX` `atY` `atZ` | `upX` `upY` `upZ` | Render the model from a camera position looking at a target position, with an optional up vector. | — | ▶ |
| `-renderMeshFromCustomGridPositionYPR` | same two forms as above | — | Render from a custom **grid** position with yaw/pitch/roll. | — | |
| `-renderMeshFromCustomGridPositionLookAt` | same two forms as above | `upX` `upY` `upZ` | Render from a custom **grid** position looking at a target. | — | |

### `-exportReport`

**Signature** `-exportReport <outputFileName> <templateFileName> [true|false]`

`templateFileName` is an **`.html` template**, not an XML. The nine templates shipped in
`C:\Program Files\Epic Games\RealityScan_2.2\Reports\` are
[VERIFIED-by-inspection of the install tree, 2026-08-04]:

| template | subject |
|---|---|
| `Overview.html` | whole project |
| `ComponentAccuracyReport.html` | per-component accuracy — the candidate for the georeferencing/residual question below |
| `SelectedComponent.html` | the selected component |
| `SelectedComponentsTiePointsStats.html` | tie-point statistics of the selected component(s) |
| `SelectedModel.html` | the selected model |
| `SelectedOrtho.html` | the selected ortho projection |
| `AlignmentView.html` | alignment view render |
| `MapView.html` | map view |
| `Misalignment.html` | misalignment report |

The sibling `en-US\`, `de-DE\`, … folders hold `loc_*.xml` **localization string tables**
(`loc_compaccrep.xml`, `loc_overview.xml`, `loc_selcomp.xml`, `loc_selcomptps.xml`,
`loc_selmodel.xml`, `loc_selortho.xml`, `loc_mapview.xml`) consumed by the templates. They
are **not** templates and must not be passed as `templateFileName`
[VERIFIED-by-inspection]. `images\`, `scripts\` and `styles\` hold the templates' assets.

```bat
RealityScan.exe -delegateTo RS1 -exportReport "F:\na156_h2024\reports\zone_1_accuracy.html" ^
  "C:\Program Files\Epic Games\RealityScan_2.2\Reports\ComponentAccuracyReport.html" true
```

**Behavior notes**

- **[RESOLVED 2026-09-03 — it runs headless and does NOT block.]** Probed on the
  119 GB NA165/H2060 master under `-headless`, delegated to a loaded instance:
  `-exportReport <out> "<install>\Reports\SelectedModel.html"` returned in
  **3.87 s**, wrote a 14,864-byte file and left `lastError:0`, with the instance
  idle at `progress:0.0%`. It does **not** block the way `-exportRegistration`
  does. This closes the longest-open instrument question (hardening cells
  U7/U14, open since 2026-07-23).

  This makes `-exportReport` the repo's **model measurement primitive**.
  `SelectedModel.html` renders `$(modelTriangleCount)`, `$(modelVertexCount)`,
  `$(modelTextureCount)` and `$(modelTexelSize)` for whatever `-selectModel`
  last selected, so a script can now *measure* a mesh instead of inferring its
  size from a `.dat` byte count. `DecimateComponent.bat`'s pass count is derived
  this way. Parse it from the HTML by anchoring on the label row — the value is
  in the `<td>` on the **next** line:

  ```
  <th>Triangles' count</th>
  <td>103548208</td>
  ```

- **A custom template is NOT a drop-in.** A hand-written minimal template
  containing only `$(modelTriangleCount)` produced a **0-byte file** and
  `lastError:-2147467259` (`0x80004005`, E_FAIL) — while the shipped template
  succeeded against the same selected model seconds later. Templates evidently
  need scaffolding the docs do not describe (localization table, assets, or a
  required header). Use the shipped templates and parse them; do not hand-roll
  one without probing it first. [OPEN: what exactly a custom template requires]

- The third parameter is a boolean, not a params XML, so the
  `-exportRegistration` mitigation (supply a GUI-exported params file) does not
  exist here. Passing `true` did not rescue the custom template.

- [OPEN] Whether it can emit **georeferencing status and residuals** is still
  unanswered — only the model-level report was exercised. Georeferencing of a
  merged scene is still verified only in the GUI.
- Report templates use the same variable and function syntax as `.rscmd` files
  [OFFICIAL: tutorials/commandline_rscmd, appbasics/reports_functions_and_variables].

### `-printReport`

**Does not work with delegation** [OFFICIAL: appbasics/allcommands, tutorials/commandline_3]
— therefore unusable in this repository's `-delegateTo` architecture (§15).

### `-exportSelectedCamerasSnapshots`

Present in `appbasics/allcommands` only; absent from `tutorials/commandline_3`. Requires an
explicit `fileFormat` argument, which `-exportCameraSnapshots` does not
[OFFICIAL: appbasics/allcommands].

### `-renderMeshFromCustomPositionYPR` / `-renderMeshFromCustomPositionLookAt`

Both accept either a params XML or a fully inline parameter list.

```bat
:: from above a model at 0,0,0 in local Euclidean space
RealityScan.exe -renderMeshFromCustomPositionYPR "D:/Project/render.png" 1280 720 100 0 0 150 0 0 0

:: side view, vertical axis up +Z
RealityScan.exe -renderMeshFromCustomPositionLookAt "D:/Project/render.png" 1280 720 50 0 -100 0 0 0 10 0 0 1
```

[OFFICIAL: appbasics/allcommands — note the Help's own examples use forward slashes in the
output path, which the application accepts.]

---

## 9. Group 7 — Classification

[OFFICIAL: appbasics/allcommands "Classification Commands"; tutorials/commandline_3]
**None of these commands are used by this repository, and none have been exercised here.**
Everything below is [OFFICIAL] only.

| Command | Required | Optional | Official description (compressed) | algId |
|---|---|---|---|---|
| `-dtmClassify` | — | `params.xml` | Classify the vertices of the selected model into pre-defined classes, using current settings or `params.xml`. | `42 AI_CLASSIFY` |
| `-selectClassification` | `classificationName` | — | Select a classification by name. | — |
| `-renameSelectedClassification` | `newClassificationName` | — | Rename the selected classification. | — |
| `-transferClassification` | — | `params.xml` | Transfer classification from the labels layer images; optional params from the AI Classify tool panel. | `47 TRANSFER_IMAGE_LABELS` |
| `-exportClassificationSettings` | `XMLfilePath` | — | Export the AI Classify tool panel settings to an `.xml` (full path incl. name and extension). | — |
| `-importClassificationSettings` | `XMLfilePath` | — | Import AI Classify tool panel settings from an `.xml`. | — |
| `-overrideSelectedVertices` | — | `className` | Change the selected vertices to the currently selected class, or to the named class. | `48 OVERRIDE_CLASSIFICATION`, `51 AI_OVERRIDE_CLASSIFICATION` |
| `-selectClass` | `className` | — | Select a class within the selected classification. | — |
| `-deselectClass` | — | — | Deselect all selected classes. | — |
| `-renameSelectedClass` | `newClassName` | — | Rename the selected class. | — |
| `-setSelectedClassAsGroundForDTM` | `true`\|`false` | — | Toggle "Use as ground for DTM" for the selected class. | — |
| `-setSelectedClassAsGroundForExport` | — | — | Set the class's "Export class LAS" setting to Ground (2). | — |
| `-setSelectedClassLasFormat` | `0` – `12` | — | Set the "Export class LAS" value to a number from 0 to 12. | — |
| `-selectVerticesOfSelectedClass` | — | — | Select model vertices belonging to the selected class. | — |
| `-selectClassificationFormat` | `classificationFormatName` | — | Select a classification format by name. | — |
| `-renameSelectedClassificationFormat` | `newClassificationFormatName` | — | Rename the selected classification format. | — |
| `-exportSelectedClassificationFormat` | `filePath` | — | Export the selected classification format to a `.cfd` file. | — |
| `-exportClassificationFormat` | `classificationFormatName` `filePath` | — | Export a named classification format to a `.cfd` file. | — |
| `-importClassificationFormat` | `filePath` | — | Import a classification format from a `.cfd` file. | — |
| `-colorModelBySelectedClassification` | — | — | Colorize the model according to the classes of the selected classification. | — |
| `-deleteSelectedClassification` | — | — | Delete the selected classification. | — |

Documentation discrepancy in this group: `appbasics/allcommands` says `-dtmClassify`'s
params come from the "Classify tool" while `tutorials/commandline_3` says the "AI Classify
tool" [OFFICIAL, both pages]. `-overrideSelectedVertices`' `className` is genuinely optional
in both the table's HTML and its text — an earlier draft reported a required/optional
mismatch here, which was a text-conversion artifact (§1).

---

## 10. Group 8 — Settings and error handling

[OFFICIAL: appbasics/allcommands "Settings' and Error-handling Commands";
tutorials/commandline_4, tutorials/commandline_5]

| Command | Required | Optional | Official description (compressed) | algId | ▶ |
|---|---|---|---|---|---|
| `-set` | `"key=value"` | — | Change an application setting (state variable). | `21845 CLI_PARSE_PARAMS` | ▶ |
| `-preset` | `"key=value"` | — | Change an application setting during the **setup phase** — for settings that require an application reset. | — | ▶ |
| `-reset` | `ui` \| `cfg` \| `cfgui` \| `all` | — | Reset the user interface, the settings, or both; `all` makes it like a clean install. **Batch-file only; does not work with delegation.** | — | ▶ |
| `-silent` | `crashReportPath` | — | Suppress warning dialogs and crash-report uploads; store reports in the given folder instead of showing the upload wizard. Must be used at startup. | — | ▶ |
| `-writeProgress` | `fileName` | `timeout` (seconds) | Write every new progress change into the given file; the optional timeout also emits records over that period. | — | ▶ |
| `-printProgress` | — | `timeout` (seconds) | Print every progress change into the Windows Command Prompt. | — | |
| `-tag` | `string` | — | Write the string into the Windows Command Prompt. Respects command order — it runs only after the preceding process finishes. | — | ▶ |
| `-stdConsole` | — | — | Enable console redirection to the application's standard output; the application console is mirrored in the Windows console, which also enables further redirection. | — | ▶ |
| `-disableOnlineCommunication` | — | — | Disable any online communication. | — | |
| `-importGlobalSettings` | `settings.rcconfig` | — | Import application global settings from a config file. | `21001 IMPORT_GLOBAL_CONFIG` | ▶ |
| `-exportGlobalSettings` | `settings.rcconfig` | — | Export application global settings to a config file. | `21000 EXPORT_GLOBAL_CONFIG` | ▶ |
| `-setProjectCoordinateSystem` | `authority:id` | — | Set the project coordinate system by authority and ID (see `epsg.xml`, `local.xml`). | `20640 CHANGE_COORDINATE_SYSTEM` | ▶ |
| `-setOutputCoordinateSystem` | `authority:id` | — | Set the output coordinate system by authority and ID. | `20640 CHANGE_COORDINATE_SYSTEM` | ▶ |

### `-set`

**Signature** `-set "<key>=<value>"` — always one quoted argument.

The key inventory is `03-settings-keys.md`. What belongs here is the command's behaviour:

- [VERIFIED] An **unquoted** pair splits into two `.bat` arguments and RealityScan logs
  `Parsing setting key=value 'sfmMergeGeoreferencedComponents' failed [err:7155]` and
  `'false' failed`, applying nothing — while the parse errors land in the error marker and
  spuriously abort the workflow that carried them. Before this was found, **no flag cell in
  the merge matrix had ever applied its flags** [NA167 B5, 2026-07-23].
- [VERIFIED] Swept `-set` values **persist across instance restarts**, so every experiment
  must pin every key it depends on rather than assuming a default
  [MERGE_TEST_PLAN §3 contamination controls, 2026-07-23].
- [VERIFIED] Legacy `RealityCapture*` key names are **dead**; RealityScan 2.x uses `app*`
  [overhaul commit 2, 2026-07-21].
- `-set` is instant. Delegated FIFO ordering guarantees it takes effect before the next
  queued operation, so production fires it without a completion wait
  [VERIFIED: `AlignZone.bat`, `MergeZoneComponents.bat`].

```bat
%RealityScan% -delegateTo RS1 -set "appIncSubdirs=true"
%RealityScan% -delegateTo RS1 -set "sfmDistortionModel=Division"
```

### `-preset`

For settings that need an application reset. Pair it with `-set "appQuitOnReset=true"` to
suppress the restart dialog — the application **quits** after the setting changes, so the
documented pattern is one invocation per such setting followed by a fresh launch
[OFFICIAL: appbasics/allcommands, tutorials/commandline_5]:

```bat
RealityScan.exe -set "appQuitOnReset=true" -set "appCacheLocation=Custom"
RealityScan.exe -set "appQuitOnReset=true" -set "appCacheCustomLocation=E:\rscache"
RealityScan.exe -newScene
```

This repo instead passes the cache keys as ordinary `-set` arguments on the boot line, which
works because they are applied at startup
[VERIFIED: `startRealityScan.bat` `RS_CACHE_ARGS`].

### `-reset`

`ui` resets the user interface, `cfg` the application settings, `cfgui` both, `all` makes it
like a clean install. **Works only in a batch file and does not work with delegation**
[OFFICIAL] — therefore unusable in this repository's architecture (§15).

### `-silent`

**Signature** `-silent <crashReportPath>` — must be used at startup.

Three shipped descriptions, of decreasing completeness — take the first as authoritative:

| page | what it says |
|---|---|
| `appbasics/allcommands` | "Suppress warning dialogs and uploading of the crash reports… **This command has to be used at the startup.**" |
| `tutorials/commandline_5` | Suppresses warning dialogs and crash-report uploads; stores reports at the path. **No startup requirement stated.** |
| `tutorials/commandline_4` | "Set a location for storing crash reports." **Dialog suppression not mentioned at all.** |

Only `appbasics/allcommands` carries the startup requirement, and only it and
`commandline_5` mention dialog suppression at all [OFFICIAL, all three pages, quoted from
the shipped Help].

**Behavior notes**

- [VERIFIED] Under `-silent`, dialogs such as "Export Selection" are **auto-answered** —
  which is the mechanism by which a selection-driven export silently exports nothing when a
  stray selection is active [FINDINGS 2026-07-23]. This is the single most important
  consequence of running silent.
- Exit code `3` means a crash; the minidump is written to this path as
  `RealityScanCrash-YYYYMMDD-HHMMSS.dmp`. After a crash, the **next** delegated command
  fails with "Failed to delegate command" — the signature of a dead instance rather than a
  rejected operation [VERIFIED: FINDINGS 2026-07-26].

### `-writeProgress`

**Signature** `-writeProgress <fileName> [timeout]` — `timeout` in seconds.

**File format** — five whitespace-separated columns [OFFICIAL: tutorials/commandline_5]:

| column | meaning |
|---|---|
| `algId` | process ID — see the per-command `algId` values throughout this document, and `tutorials/processids` for the full table |
| `progress` | number in ⟨0,1⟩ indicating the stage of the process |
| `duration` | elapsed time in seconds |
| `estimation` | estimated remaining time in seconds |
| `eventType` | one of `#started`, `#progress`, `#timeout`, `#completed` |

```
20561 0.00 0.04 404.08 #started
20561 0.45 0.10 0.22 #progress
20561 1.00 17.13 0.00 #completed
```

**Behavior notes**

- [VERIFIED] `#timeout` lines are **not progress**. The operation is internally stalled, yet
  `duration` keeps ticking and `estimation` becomes garbage — so line-change stall detection
  counts a 6-hour hang as activity. The relocated-`-importComponent` hang produced **zero**
  stall warnings [NA167 #12 / B4, 2026-07-23].
- [VERIFIED] `#timeout` does **not** always mean hung. Heavy alignment phases legitimately
  freeze the progress fraction for 20+ minutes; a *successful* 94.6 % run emitted 40
  `#timeout` lines. The pathological signature is `#timeout` **from fraction 0.00 with an
  ever-growing ETA**. Policy adopted: stall-**warn** at 2 h, never auto-kill an alignment
  [NA167 #28, 2026-07-24].
- Production uses a 600 s timeout and tails the file from the Python execution layer
  [VERIFIED: `startRealityScan.bat`, `realityscan_cli.py`].
- The marker file is namespaced per instance (`progress_<inst>.txt`) and cleared before every
  run, with a 60 s retry because of the `getStatus`/teardown handle race
  [VERIFIED: `realityscan_cli.py`; NA167 B3].

### `-tag`

Ordered echo into the Command Prompt: it runs only after the process started by the
preceding command finishes [OFFICIAL]. Useful as a sequencing marker in a `.bat`, and as the
cheapest probe for `.rscmd` argument expansion (§3, `-execRSCMD`).

### `-stdConsole`

**RETIRED IN THIS REPO.** [VERIFIED] It allocates a **console window per instance boot**,
and nothing reads instance stdout here — progress comes from `-writeProgress` and process
results from the `appProcessExecCmd` hook. Removed from the boot line on 2026-07-23
[`startRealityScan.bat` comment + FINDINGS]. It is not deprecated by Epic; it is simply
wrong for headless multi-instance operation.

### `-importGlobalSettings` / `-exportGlobalSettings`

[CONTRADICTED] `appbasics/allcommands` writes the extension as **`.rcconfig`** (legacy);
`tutorials/commandline_4` writes it as **`.rsconfig`**. Both pages ship in the same build.
[OPEN: run `-exportGlobalSettings D:\probe\settings` and look at what the application
actually writes.]

### `-setProjectCoordinateSystem` / `-setOutputCoordinateSystem`

**Signature** `-setProjectCoordinateSystem <authority:id>`

```bat
RealityScan.exe -setProjectCoordinateSystem Local:1 ^
                -setOutputCoordinateSystem epsg:4326
```

Authorities and IDs come from the databases in the installation folder — `epsg.xml`,
`local.xml` [OFFICIAL: appbasics/allcommands, tutorials/commandline_4].

**Behavior notes**

- This repo does **not** use these commands: the per-cruise coordinate system is carried by
  the flight-log import params XML instead, whose `CoordinateSystemFlightLog` /
  `CoordinateSystemFlightLogType` keys are generated from the UTM zone tag in the flight
  log's filename (`flight_log_53N_UTM.txt` → EPSG:32653) by
  `modules/flight_logs.write_flight_log_params` [VERIFIED-as-architecture: CLAUDE.md].
- [VERIFIED — why that matters] The UTM zone must be **derived per cruise, never hand-edited**.
  A template carrying 4N (EPSG:32604) from an earlier project was used on a cruise that is
  57S (EPSG:32757). **A wrong zone imports silently and misplaces everything**
  [NA167 #6; FINDINGS 2026-07-21/22].

---

## 11. Commands documented only in Help prose

These names appear somewhere in the shipped Help but **not** in the master table
`appbasics/allcommands`. Two are legacy names, one is a typo, one is a spelling variant, one
is an apparent alias, one is a localization mode, and three belong to a different
executable.

A separate category, easy to confuse with this one: `-undercut` **is** in
`appbasics/allcommands` — in the file, inside an HTML comment, so it renders nowhere. See
§12.2.

| Name | Where it appears | Verdict | Use instead |
|---|---|---|---|
| `-exportComponent` | tutorials/commandline_1 examples: `-selectMaximalComponent -exportComponent %MyPath%\max` and `-minComponentSize 5 -exportComponent %MyPath%\` | [INFERRED] legacy RealityCapture-era name left in an un-updated tutorial | `-exportLatestComponents`, `-exportSelectedComponentDir`, `-exportSelectedComponentFile` |
| `-minComponentSize` | tutorials/commandline_1 example | [INFERRED] legacy name | `-setMinComponentSize` (itself deprecated — §14) |
| `-exportDepthAndMask` | tutorials/commandline_3 table | [INFERRED] pre-rename name; the process-ID list contains both `20586 EXPORT_DEPTH_AND_MASK` and `36 EXPORT_DEPTH_AND_MASK_IMAGES` | `-exportMapsAndMask` (wider description: masks **plus depth and normal** maps) |
| `-exportUndistoredImages` | tutorials/commandline_1 table | [INFERRED] documentation typo (missing `t`); the master table and process ID `21812 EXPORT_UNDISTORTED_IMAGES` both spell it correctly | `-exportUndistortedImages` |
| `-execrscmd` | tutorials/commandline_rscmd, throughout | [INFERRED] all-lowercase spelling of the same command; the only evidence that parsing is case-insensitive | `-execRSCMD` |
| `-setReconRegionOnCPs` | tutorials/commandline_2 example, on the same page that documents the long form | [INFERRED] a genuine short alias — the Help would not run a broken example — but unverified | `-setReconstructionRegionOnCPs` |
| `-translatorMode` | appbasics/localization | [OFFICIAL] real startup mode: shows numeric string IDs on panels and windows as a translation aid | — |
| `-hostAddress`, `-port`, `-landingPage` | tools/api | **Flags of `RSNode.exe`, not `RealityScan.exe`** | see §17 |

```bat
:: translator mode - startup only
"C:\Program Files\Epic Games\RealityScan_2.2\RealityScan.exe" -translatorMode
```

Also documented as syntax rather than as commands, and easy to mistake for commands:
the `.rscmd` variable set `$(arg0)`–`$(arg9)`, `$(appRootDir)`, `$(appStartDir)`,
`$(cmdStartDir)` and the `$For("i", from, step, to, …)` loop
[OFFICIAL: tutorials/commandline_rscmd]; and the `appProcessExecCmd` substitution variables
`$(processResult)`, `$(processId)`, `$(processDuration:d)`
[OFFICIAL: tutorials/commandline_5].

---

## 12. Undocumented and hidden commands

### 12.1 `-importFlightLog` — undocumented, proven in production

**Signature** `-importFlightLog <flightLogFile> [params.xml]`
**Official description** — none. The string `importFlightLog` does **not** appear anywhere in
the RealityScan 2.2 offline Help. The documented name for the operation is
`-importTrajectory` (§6.2), and both drive process ID `20598 IMPORT_FLIGHT_LOG`
[UNDOCUMENTED].

It nevertheless works, and it is this repository's **only** georeferencing import path — six
call sites across `AlignZone.bat`, `AlignImageList.bat`, `GrowZone.bat`,
`MergeZoneComponents.bat`, `SequentialAlignGrow.bat` and `AlignImagesFromFolder.bat`. Known
by execution on two independent machines [VERIFIED: FINDINGS 2026-07-21 onward].

**Behavior notes**

- [VERIFIED] Rows referencing images **not in the scene** make the import report a **failed
  process** (`err:18002`, result `0x820000FF` = 2181038335) even though every present row
  imports fine. Filter logs to the scene's images, or tolerate exactly that code. Confirmed
  benign by matching all 102 "not found in the current scene" images against every component
  manifest: **zero overlap** — they were exactly the unregistered remainder
  (4,598 log rows − 4,496 cameras = 102) [FINDINGS 2026-07-21 and 2026-07-25].
- [VERIFIED] Name matching is by **basename**, and it finds images in subfolders — bare
  filenames matched images living in `wca/` and `zeuss/` [NA167 #5, 2026-07-22].
- [VERIFIED] It leaves the matched images **actively selected**. `-deselectAllImages` before
  any export (§3) [FINDINGS 2026-07-23].
- [VERIFIED] The params XML's `CoordinateSystemFlightLog` / `CoordinateSystemFlightLogType`
  must match the log's UTM zone — a wrong zone imports **silently** and misplaces everything
  [NA167 #6].
- [VERIFIED] Format definitions live in `flightlogs.xml` in the install folder. The custom
  13-column format used here (`{B438A617-2434-5A24-C1B7-58980F28345A}`, YPR at indices
  7/8/9, per-image position **and** orientation accuracies) was **never installed** until
  2026-07-25: `FlightLogParams.xml` referenced it but the stock `flightlogs.xml` did not
  contain it, so **orientation and per-image accuracies were silently dropped on every
  import** to that date. The file in Program Files is now hand-edited and must be re-checked
  after any application update [PRIORS_DISTORTION_TEST_PLAN audit item 1, 2026-07-25]
  [OPEN: whether the hand-merged format survives an app update].
- Other format GUIDs in play: `{0E9850E2-…}` a 7-column position-only format;
  `{97F08A22-…}` the stock 10-column format (X, Y, Alt, three accuracies, YPR), kept as the
  no-admin fallback [VERIFIED: FINDINGS 2026-07-26].
- [UNDOCUMENTED] `ifKGrp` and `ifKmode` in the params XML are the only plausible carriers of
  the "Euler angles order (YPR)" and "Camera mount" import settings. Their value mapping is
  undocumented, and **neither string appears in any file under the RealityScan install** —
  both are compiled into the binary. Current values, unchanged since the template was
  written: `ifKGrp=2`, `ifKmode=0x0` [FINDINGS 2026-07-26]
  [OPEN: (1) set the two dropdowns in the GUI import dialog, save params, diff against the
  template — one minute, needs the GUI; (2) headless — align the smoke fixture at several
  `ifKmode` values and read camera attitudes out of the pose XMPs, ~2 min per cell].

**Example — tolerant import wrapper** [VERIFIED: `MergeZoneComponents.bat` `:run_geoimport`]

```bat
call :run_geoimport -importFlightLog "F:\na156_h2024\merged\union_flight_log_04Q_UTM.txt" "F:\na156_h2024\merged\FlightLogParams.xml"
```

The wrapper is the standard `:run` with one addition: if the error marker is non-empty it
searches for `2181038335`; on a match it **moves** the marker to
`expected_18002_<instance>.txt` — preserving the evidence while leaving a clean marker for
later steps — and continues. Any other content is still a hard failure.

### 12.2 `-undercut` — present in the Help source, hidden from the rendered page

**Signature** `-undercut` — no parameters.
**Description, verbatim from the shipped Help source** "Undercut the selected model so that
each part contains geometry just in its cluster box."

[UNDOCUMENTED — how it is known] The row exists in
`C:\Program Files\Epic Games\RealityScan_2.2\Help\en-US\appbasics\allcommands.htm`, in the
Model Tools table, **inside an HTML comment** (`<!-- <tr> <td class="command">undercut</td> …
</tr>-->`). It is the **only** commented-out command row in the whole file, so it does not
appear on the rendered Help page, in the plain-text conversion, or in `SURVEY_commands.md`.
Corroboration that the feature is real and shipped: the public process-ID table lists
`27 UNDERCUT_MODEL_PARTS` [OFFICIAL: tutorials/processids] — a process ID with no visible
command driving it, exactly like `23 CHECK_MODEL_INTEGRITY` and `28 CHECK_MODEL_TOPOLOGY`
(§13). [VERIFIED-by-inspection of the installed Help HTML and process-ID list, 2026-08-04.]

Semantics, from the description: it is the per-**part** counterpart of `-cutByBox` — after a
model has been split into cluster parts (the same parts `-exportModel` writes when "Save mesh
by parts" is on), each part is trimmed to its own cluster box, removing the overlap that
by-parts exports otherwise carry [INFERRED from the one-sentence description; nothing here
has driven it].

[OPEN] Whether the command still parses in 2.2. Cheapest probe: type `-under` in the GUI
console view and press TAB — completion answers immediately (the console's completion list
comes from the binary, not from the Help). Second cheapest: `-undercut` on the smoke
fixture's model and watch for `algId 27` in `-writeProgress`. Until one of those runs,
**do not put it in a workflow**: a commented-out doc row is as likely to mean "withdrawn" as
"internal".

---

## 13. Commands that do NOT exist

### `-selectAllComponents` — does not exist in RealityScan 2.2

[VERIFIED] Fails as an unknown/invalid command, process result `0x82000060`. It had lived
unnoticed in a legacy workflow script [NA167 #13 / B2, 2026-07-23; testing/FINDINGS #13].

**Use instead:** `-selectComponent <name>`, `-selectMaximalComponent`, or
`-selectComponentWithLeastReprojectionError` — those are the only three component-selection
commands that exist. `-mergeComponents` and `-align` need **no** pre-selection: they operate
on all components in the scene. `-deleteAllComponents` covers the delete-everything case
without a selection.

### Other capabilities commonly assumed, and what actually exists

| assumed | reality | use instead |
|---|---|---|
| a params XML argument to `-align` | silently **ignored** [VERIFIED: FINDINGS 2026-07-21] | `-set` each `sfm*`/`lis*` key first, then a bare `-align` |
| a query for "how many components remain" | none exists [UNDOCUMENTED, VERIFIED by exhaustion] | peel until `-renameSelectedComponent` fails `0x80070057` on the empty scene; or count exported `.rsalign` files |
| a query for per-component camera counts | none exists; component files are opaque `TBSM` binary | XMP pose census (`-exportXMP` / `-exportXMPForSelectedComponent`) |
| a CLI "Check Integrity" / "Check Topology" | no commands, although process IDs `23 CHECK_MODEL_INTEGRITY` and `28 CHECK_MODEL_TOPOLOGY` exist | `-cleanModel` + `-closeHoles` [VERIFIED: FINDINGS 2026-07-23] |
| a per-part trim after a by-parts export | `-undercut` exists in the Help **source** but is commented out of the rendered table; process ID `27 UNDERCUT_MODEL_PARTS` is public | §12.2 — unverified, do not use in a workflow yet |
| `-selectAllTriangles` | not in the command table | `-deselectModelTriangles` then `-invertTrianglesSelection` [INFERRED] |
| `-selectAllModels` | not in the command table | select by name in a loop |
| regexp selection with `-selectImage` | documented, but **selects nothing** in this build | one `-selectImage "<full path>" union` call per image [VERIFIED: FINDINGS 2026-07-23] |
| per-camera distortion model via XMP | `sfmDistortionModel` is global and all-or-nothing [CONTRADICTED: FINDINGS 2026-07-26] | one global model; separate cameras by calibration/lens **group** instead |
| stereo-rig support | staff-confirmed **absent** through Aug 2025 | GCPs, distance constraints, or locked XMP poses for metric scale |

---

## 14. Deprecated commands and their replacements

| Command | Status | Evidence | Replacement |
|---|---|---|---|
| `-setMinComponentSize` | **Deprecated by Epic** — the application logs "will be removed in the next release" | [VERIFIED: read from a per-cell `RealityScan.log` snapshot, NA167 #22 / B11, 2026-07-24] | **None documented, and it is still required** — without it components below the default 5 are silently excluded from selection and from XMP export |
| `-exportComponent` | Legacy name, absent from the master table | [INFERRED: §11] | `-exportLatestComponents` / `-exportSelectedComponentDir` / `-exportSelectedComponentFile` |
| `-minComponentSize` | Legacy name, absent from the master table | [INFERRED: §11] | `-setMinComponentSize` |
| `-exportUndistoredImages` | Typo spelling | [INFERRED: §11] | `-exportUndistortedImages` |
| `-stdConsole` | Not deprecated by Epic; **retired in this repo** | [VERIFIED: allocates a console window per instance boot, 2026-07-23] | `-writeProgress` + the `appProcessExecCmd` completion hook |
| `RealityCapture*` setting keys | **Dead** in 2.x | [VERIFIED: overhaul commit 2, 2026-07-21] | the `app*` keys — see `03-settings-keys.md` |
| `AlignImagesFromFolder.bat` (this repo) | Deprecated workflow, kept only for one legacy test driver | [VERIFIED: CLAUDE.md] | `AlignZone.bat` |

Legacy **file extensions** that are still accepted and are not deprecated spellings to be
"fixed": `.rcproj` (`-unlockPPIProject` requires it), `.rcalign`, `.rccmd`, `.rcconfig`
[OFFICIAL: appbasics/allcommands].

---

## 15. Commands unusable under delegation or headless

| Command | Restriction | Source |
|---|---|---|
| `-printReport` | "does not work with delegation" | [OFFICIAL: appbasics/allcommands, tutorials/commandline_3] |
| `-reset` | "works only when used in a batch file, and it won't work with delegation commands" | [OFFICIAL: appbasics/allcommands, tutorials/commandline_4, tutorials/commandline_5 — identical wording on all three] |
| `-headless` | must be given at startup | [OFFICIAL: stated **indirectly** — `appbasics/allcommands`' own `-headless` row only links out, but its `-hideUI` and `-showUI` rows both read "Unlike headless, this command doesn't need to be run at startup"] |
| `-silent` | "has to be used at the startup" | [OFFICIAL: appbasics/allcommands **only** — `tutorials/commandline_5` and `commandline_4` state no such requirement, see §10] |
| `-translatorMode` | startup mode | [OFFICIAL: appbasics/localization] |
| `-exportRegistration` **without** a params XML | blocks forever headless | [VERIFIED: FINDINGS 2026-07-21] |
| `-tag`, `-printProgress`, `-stdConsole` | write to a Command Prompt; under delegation the output belongs to the instance's console, not the delegating process | [INFERRED — not stated in the Help; settled by delegating `-tag` and looking for the string] |
| any selection-driven export while a selection is active, under `-silent` | exports **nothing**, silently | [VERIFIED: FINDINGS 2026-07-23] |
| `-continueModelCalculation` after a crash | requires `appAutoSaveMode` to have been enabled and `-load … recoverAutosave` | [OFFICIAL: tutorials/commandline_2] |
| anything requiring interaction (e.g. a log-in window) | forces the application out of headless mode | [OFFICIAL: tutorials/headless] |

---

## 16. Instant vs long-running commands

Classification as used by this repository's workflows. "Instant" means the command is fired
delegated **without** a completion wait, relying on FIFO ordering; "waited" means it goes
through the `:run` double-wait [VERIFIED: `RS_CLI/Scripts/*.bat`].

| class | commands | notes |
|---|---|---|
| startup-only (never delegated) | `-headless`, `-silent`, `-setInstanceName`, `-writeProgress`, `-translatorMode`, `-stdConsole`, `-reset` | arguments of the launching `RealityScan.exe`, not operations on a live instance; `-reset` and `-printReport` are documented as incompatible with delegation (§15) |
| instant (delegated, no wait needed) | `-set`, `-selectImage` | `-set` before a queued `-addFolder`/`-align`; `-selectImage` in a per-image union loop where a wait would add ~5 s × thousands of images |
| fast but waited | `-newScene`, `-load`, `-save`, `-deselectAllImages`, `-selectAllImages`, `-setMinComponentSize`, `-selectMaximalComponent`, `-selectComponent`, `-renameSelectedComponent`, `-deleteSelectedComponent`, `-selectModel`, `-renameSelectedModel`, `-deleteSelectedModel`, `-editInputSelection`, `-exportSelectedComponentDir` | `-load` and `-save` are fast only relative to compute; a dated copy of a six-component project took 13.1 min / 95.2 GB |
| long-running | `-align`, `-draft`, `-mergeComponents`, `-update`, `-calculate*Model`, `-calculateTexture`, `-unwrap`, `-simplify`, `-smooth`, `-closeHoles`, `-cleanModel`, `-reprojectTexture`, `-calculateVertexColors`, `-exportModel`, `-exportXMP`, `-importComponent`, `-importFlightLog` | 10+ hour runs are normal. **No overall timeout is set on any of them**; only startup (120 s) and shutdown (900 s in code) are bounded [CLAUDE.md hard rule 3; `realityscan_cli.py`] |

Reference points for "long": `-importComponent` ~2 s per 0.7 GB **in place**; a real
`-mergeComponents` ~1 h for 1–4k-camera pairs; `-align` 4–444 min depending on scene and
size; the full model recipe 40–384 min [VERIFIED: FINDINGS, various 2026-07].

---

## 17. RSNode.exe and the HTTP command channel

`RSNode.exe` is a separate executable in the same installation folder — a system service
bridging a custom application and RealityScan, exposing a REST-like API for managing
sessions, uploading/downloading session files, and **running CLI commands**
[OFFICIAL: tools/api].

**Its flags are not `RealityScan.exe` commands:**

| flag | parameter | meaning |
|---|---|---|
| `-hostAddress` | `ipAddress` | bind address |
| `-port` | `portNumber` | bind port |
| `-landingPage` | e.g. `"\/static/MyApp.html"` | landing page served by the static HTTP server |

```bat
"C:\Program Files\Epic Games\RealityScan_2.2\RSNode.exe" -hostAddress 192.168.0.74 -port 7878 -landingPage "\/static/MyApp.html"
```

Authentication is a Bearer HTTP Authorization header carrying a GUID token, sent as a GET
parameter when the landing page opens; it is required by every API call except the static
HTTP server. **The connection is not secure and assumes a private, secured LAN**
[OFFICIAL: tools/api].

**The command endpoints** [OFFICIAL: tools/apiproject]:

| endpoint | method(s) | purpose |
|---|---|---|
| `/project/command?name=<cmd>&param1=…&param9=…` | **GET and POST** | send one CLI command |
| `/project/commandgroup` | **POST only** | send a group of commands; **execution stops if any command fails**, and the task error code is set to that error's value |
| `/project/condcommand` | **GET and POST** | conditional CLI command; "if the tag is not set, a CLI command will be sent" — `tag` is required |
| `/project/condcommandgroup` | **POST only** | conditional command group; `tag` required |
| `/project/status` | GET | returns `restarted`, `progress`, `timeTotal`, `timeEstimation`, `errorCode`, `changeCounter`, `processID` for the session |
| `/project/tasks` | GET | per-task `state` ∈ `"scheduled"`, `"started"`, `"finished"`, `"failed"`, plus `errorCode` / `errorMessage` |

[OFFICIAL: tools/apiproject — method availability read off the endpoint list, where only
`postProjectCommandGroup` and the `condcommandgroup` POST variant exist for the group forms.]

Header parameters `clientId` (UUID), `appToken` (string) and `Session` (UUID) are required.
`name` is required; `param1`…`param9` are optional — **a maximum of nine positional
parameters per call**, which is the hard limit of this channel. POST variants add an
`encoded` query parameter (`"base64"`, raw by default). Documented examples:

```
/project/command?name=align
/project/command?name=calculateHighModel
/project/command?name=simplify
/project/command?name=exportModel&param1=Model%201&param2=model_name.obj
/project/command?name=exportSelectedModel&param1=model_name.obj
/project/command?name=add&param1=image_name.jpg
/project/command?name=simplify&param1=simplification_config.xml
/project/command?name=exportReport&param1=report.txt&param2=template.txt
```

Note that command names are given **without** the leading hyphen in this channel
[OFFICIAL: tools/apiproject]. A command call returns **HTTP 202 Accepted** with a
`Task Handle { taskID }` — it is asynchronous, like `-delegateTo`, and completion is read
back from `/project/tasks`. `/project/disconnect`'s description states that "the session will
automatically terminate once it has no more CLI commands to run"
[OFFICIAL: tools/apiproject].

This channel has **never been used by this repository** — all execution goes through
`-delegateTo`. It is nevertheless the only documented mechanism that exposes a **per-task
terminal state** (`finished` / `failed` with an `errorCode`), which is exactly what
`-waitCompleted` fails to provide reliably (§5)
[OPEN: whether the HTTP channel reports completion more reliably than `-waitCompleted`; a
cheap probe would be one `align` call on the smoke fixture, polling `/project/tasks` for the
returned `taskID` and recording the response timing].

---

## 18. Production usage map of this repository

52 commands are exercised in production, all of them from
`modules/realityscan_interface/RS_CLI/Scripts/*.bat`
[VERIFIED-by-inspection of every `%RealityScan%` / `call :run*` call site, 2026-08-04].
Everything that acts on a live instance goes through `-delegateTo %RS_INSTANCE%` inside the
shared `:run` subroutine; the exceptions are the boot arguments (`-headless`, `-silent`,
`-setInstanceName`, `-set`, `-writeProgress` on the `start ""` line), the readiness/teardown
probes (`-getStatus`), and the bare delegated `-quit` that ends every workflow.

| workflow | commands, in order of use |
|---|---|
| `startRealityScan.bat` | `-getStatus`, `-delegateTo`, `-newScene` (+`-deleteAutosave`), `-headless`, `-silent`, `-setInstanceName`, `-set`, `-writeProgress` |
| `AlignZone.bat` (canonical per-zone align) | `-newScene`, `-set "appIncSubdirs=true"`, `-addFolder`, `-importFlightLog`, `-set` (each `sfm*`/`lis*` key), `-align`, `-deselectAllImages`, `-setMinComponentSize`, `-save`, then the destructive identity loop: `-exportXMP`, `-selectMaximalComponent`, `-renameSelectedComponent`, `-exportSelectedComponentDir`, `-deleteSelectedComponent`; `-quit` **without saving** |
| `MergeZoneComponents.bat` | `-newScene`, `-importComponent` (from a `.complist` of in-place paths), `-set`, `-importFlightLog`, `-mergeComponents` \| `-align`, `-update`, `-deselectAllImages`, `-setMinComponentSize`, `-exportLatestComponents` (align mode only), `-save`, `-selectMaximalComponent`, `-renameSelectedComponent`, `-exportSelectedComponentDir`, `-exportXMPForSelectedComponent`, `-deleteSelectedComponent`, `-quit` |
| `GenerateModel.bat` | `-load`, `-selectComponent` \| `-selectMaximalComponent`, `-calculateHighModel`, `-renameSelectedModel`, `-selectMarginalTriangles`, `-selectLargeTrianglesRel`, `-selectLargestModelComponent`, `-invertTrianglesSelection`, `-removeSelectedTriangles`, `-closeHoles`, `-cleanModel`, `-simplify`, `-calculateTexture`, `-unwrap`, `-reprojectTexture`, `-selectModel`, `-deleteSelectedModel`, `-save`, `-quit` |
| `ExportDeliverables.bat` | `-load`, `-selectModel`, `-deleteSelectedModel`, `-save`, `-calculateVertexColors`, `-exportModel` (OBJ by parts, FBX by parts, dense PLY), `-quit` **without saving** |
| `AlignImageList.bat` | `-newScene`, `-add`, `-importFlightLog`, `-align`, `-setMinComponentSize`, `-selectMaximalComponent`, `-renameSelectedComponent`, `-exportSelectedComponentDir`, `-exportXMPForSelectedComponent`, `-save`, `-quit` |
| `SequentialAlignGrow.bat` | `-newScene`, then per pair: `-add`, `-importFlightLog`, `-align`; then the export block above |
| `GrowZone.bat` | `-load`, `-deselectAllImages`, `-selectAllImages`, `-editInputSelection` (`inpEnabled`, `aligFeaturesMode`, `inpPose`), `-enableAlignment` / `-setFeatureSource` (legacy fallback), `-selectImage … union`, `-add`, `-importFlightLog`, `-align`, `-setMinComponentSize`, `-exportLatestComponents`, `-exportXMP`, `-mergeComponents`, `-selectComponent`, `-deleteSelectedComponent`, `-save`, `-quit` |
| `ProbeLockAlign.bat` | `-load`, `-selectAllImages`, `-editInputSelection`, `-setMinComponentSize`, `-align`, `-deselectAllImages`, `-exportXMP`, `-quit` (no `-selectImage`, no `-deleteAllComponents`) |
| `ProbeSubsetAlign.bat`, `ProbeSubsetAlign2.bat` | as above **plus** `-selectImage … union` and `-deleteAllComponents` — the **only** two scripts that call `-deleteAllComponents` |
| `SaveProjectCopy.bat` | `-load`, `-save`, `-quit` |
| `AlignImagesFromFolder.bat` (**deprecated**) | the `AlignZone.bat` vocabulary with `-exportXMPForSelectedComponent` instead of the identity loop, **and** a full inline model recipe: `-calculateHighModel`, `-selectLargeTrianglesRel`, `-removeSelectedTriangles`, `-cleanModel`, `-simplify`, `-unwrap`, `-calculateTexture`, `-reprojectTexture`, `-renameSelectedModel`, `-selectModel`, `-deleteSelectedModel`. This is why it is deprecated: align and model in one non-restartable pass |

Commands used in production, alphabetically:

```
-add -addFolder -align -calculateHighModel -calculateTexture -calculateVertexColors
-cleanModel -closeHoles -delegateTo -deleteAllComponents -deleteSelectedComponent
-deleteSelectedModel -deselectAllImages -editInputSelection -enableAlignment
-exportLatestComponents -exportModel -exportSelectedComponentDir -exportXMP
-exportXMPForSelectedComponent -getStatus -headless -importComponent -importFlightLog
-invertTrianglesSelection -load -mergeComponents -newScene -quit -removeSelectedTriangles
-renameSelectedComponent -renameSelectedModel -reprojectTexture -save -selectAllImages
-selectComponent -selectImage -selectLargeTrianglesRel -selectLargestModelComponent
-selectMarginalTriangles -selectMaximalComponent -selectModel -set -setFeatureSource
-setInstanceName -setMinComponentSize -silent -simplify -unwrap -update -waitCompleted
-writeProgress
```

Retired from production: `-stdConsole` (removed 2026-07-23).
Removed as non-existent: `-selectAllComponents`.
`deleteAutosave` and `recoverAutosave` appear in the scripts as **parameters of `-load`**,
not as commands.

---

## 19. Alphabetical command index

Every catalogued name, with the section that documents it. `§` numbers refer to this
document. `*` marks a command used in production by this repository.

```
-abortInstance                              §5
-add                                     *  §3
-addFolder                               *  §3
-addImageWithCalibration                    §3
-addShapeToSelection                        §8.4
-align                                   *  §6.1
-calculateCrossSections                     §8.4
-calculateHighModel                      *  §7
-calculateNormalModel                       §7
-calculateOrthoProjection                   §8.4
-calculatePreviewModel                      §7
-calculatePreviewVertexColors               §8.1
-calculateQualityColors                     §8.1
-calculateQualityTexture                    §8.1
-calculateTexture                        *  §8.1
-calculateVertexColors                   *  §8.1
-cleanModel                              *  §8.2
-clearCache                                 §3
-closeHoles                              *  §8.2
-colorModelBySelectedClassification         §9
-computeContours                            §8.4
-continueModelCalculation                   §7
-correctColors                              §8.1
-cutByBox                                   §8.2
-defineDistance                             §6.2   two parameter forms
-deleteAllComponents                     *  §6.1
-deleteComponent                            §6.1
-deleteConstraint                           §6.2
-deleteControlPoint                         §6.2
-deleteControlPointMeasurement              §6.2
-deleteSelectedClassification               §9
-deleteSelectedComponent                 *  §6.1
-deleteSelectedModel                     *  §8.1
-delegateTo                              *  §5
-deselectAllImages                       *  §3
-deselectClass                              §9
-deselectModelTriangles                     §8.2
-detectFeatures                             §6.1
-detectMarkers                              §6.2
-disableOnlineCommunication                 §10
-draft                                      §6.1
-dtmClassify                                §9
-duplicateSelectedModel                     §8.1
-editConstraintSelection                    §6.2
-editControlPointSelection                  §6.2
-editInputSelection                      *  §4
-editOrthoProjectionSelection               §8.4
-enableAlignment                         *  §4
-enableColorNormalization                   §4
-enableColorNormalizationReference          §4
-enableInComponent                          §4
-enableMeshing                              §4
-enableTexturingAndColoring                 §4
-execRSCMD                                  §3
-execRSCMDIndirect                          §5
-execrscmd                                  §11    Help-prose lowercase spelling of -execRSCMD
-export3dTiles                              §8.3
-exportCameraSnapshots                      §8.5
-exportClassificationFormat                 §9
-exportClassificationSettings               §9
-exportComponent                            §11    Help-prose only; legacy
-exportContours                             §8.4
-exportControlPointsMeasurements            §6.2
-exportCrossSections                        §8.4
-exportDepthAndMask                         §11    Help-prose only; use -exportMapsAndMask
-exportGlobalSettings                       §10
-exportGroundControlPoints                  §6.2
-exportLatestComponents                  *  §6.1
-exportLod                                  §8.3
-exportMapsAndMask                          §8.3
-exportMasks                                §3     two parameter forms
-exportModel                             *  §8.3
-exportModelToZip                           §8.3
-exportOrthoProjection                      §8.4   three parameter forms
-exportReconstructionRegion                 §7
-exportRegistration                         §6.1   blocks forever headless without a params XML
-exportReport                               §8.5
-exportSTMap                                §6.1
-exportSelectedCamerasSnapshots             §8.5
-exportSelectedClassificationFormat         §9
-exportSelectedComponentDir              *  §6.1
-exportSelectedComponentFile                §6.1
-exportSelectedModel                        §8.3
-exportShapes                               §8.4
-exportSparsePointCloud                     §6.1
-exportUndistoredImages                     §11    Help-prose typo; do not use
-exportUndistortedImages                    §6.1
-exportXMP                               *  §6.1
-exportXMPForSelectedComponent           *  §6.1
-generateAIMasks                            §3
-generateMaskFromMesh                       §8.3
-getStatus                               *  §5
-headless                                *  §3
-hideUI                                     §3
-importCache                                §3
-importClassificationFormat                 §9
-importClassificationSettings               §9
-importComponent                         *  §6.1
-importControlPointsMeasurements            §6.2
-importFlightLog                         *  §12    UNDOCUMENTED; repo-critical
-importGlobalSettings                       §10
-importGroundControlPoints                  §6.2
-importHDRimages                            §3
-importImageSelection                       §3
-importLaserScan                            §3
-importLaserScanFolder                      §3
-importLeicaBlk3D                           §3
-importModel                                §8.3
-importShapesToOrtho                        §8.4
-importShapesToSelectedOrtho                §8.4
-importTrajectory                           §6.2   documented name for -importFlightLog
-importVideo                                §3
-invertControlPointSelection                §6.2
-invertImageSelection                       §3
-invertTrianglesSelection                *  §8.2
-listControlPoints                          §6.2
-load                                    *  §3
-loadBundler                                §6.1
-loadColmap                                 §6.1
-lockPoseForContinue                        §4
-mergeComponents                         *  §6.1
-minComponentSize                           §11    Help-prose only; legacy
-moveReconstructionRegion                   §7
-newScene                                *  §3
-offsetReconstructionRegion                 §7
-overrideSelectedVertices                   §9
-pauseInstance                              §5
-preset                                     §10
-printProgress                              §10
-printReport                                §8.5   does NOT work with delegation
-quit                                    *  §3
-removeCalibrationGroups                    §3
-removeImageLayer                           §3
-removeSelectedTriangles                 *  §8.2
-renameContours                             §8.4
-renameControlPoint                         §6.2
-renameCrossSections                        §8.4
-renameSelectedClass                        §9
-renameSelectedClassification               §9
-renameSelectedClassificationFormat         §9
-renameSelectedComponent                 *  §6.1
-renameSelectedControlPoint                 §6.2
-renameSelectedModel                     *  §8.1
-renderMeshFromCustomGridPositionLookAt     §8.5   two parameter forms
-renderMeshFromCustomGridPositionYPR        §8.5   two parameter forms
-renderMeshFromCustomPositionLookAt         §8.5   two parameter forms
-renderMeshFromCustomPositionYPR            §8.5   two parameter forms
-reprojectTexture                        *  §8.1
-reset                                      §10    batch file only; no delegation
-resetGround                                §7
-rotateReconstructionRegion                 §7
-save                                    *  §3
-scaleReconstructionRegion                  §7
-selectAllComponents                        §13    DOES NOT EXIST (0x82000060)
-selectAllImages                         *  §3
-selectClass                                §9
-selectClassification                       §9
-selectClassificationFormat                 §9
-selectComponent                         *  §6.1
-selectComponentWithLeastReprojectionError  §6.1
-selectContours                             §8.4
-selectControlPoint                         §6.2
-selectCrossSections                        §8.4
-selectImage                             *  §3     literal full paths only in this build
-selectLargeTrianglesAbs                    §8.2
-selectLargeTrianglesRel                 *  §8.2
-selectLargestModelComponent             *  §8.2
-selectMarginalTriangles                 *  §8.2
-selectMaximalComponent                  *  §6.1
-selectMeasurementByError                   §6.2
-selectMeasurementByIndex                   §6.2
-selectModel                             *  §8.1
-selectOrthoProjection                      §8.4
-selectShape                                §8.4
-selectTrianglesInsideReconReg              §8.2
-selectTrianglesOutsideReconReg             §8.2
-selectVerticesOfSelectedClass              §9
-set                                     *  §10
-setCalibrationGroupByExif                  §4
-setCamerasGravityDirection                 §6.1
-setConstantCalibrationGroups               §4
-setDownscaleForDepthMaps                   §4
-setFeatureSource                        *  §4
-setGroundPlaneFromReconstructionRegion     §7
-setImageLayer                              §3
-setImagesLayer                             §3
-setInstanceName                         *  §5
-setMinComponentSize                     *  §6.1   DEPRECATED but still required
-setOutputCoordinateSystem                  §10
-setPriorCalibrationGroup                   §4
-setPriorLensGroup                          §4
-setProjectCoordinateSystem                 §10
-setReconRegionOnCPs                        §11    Help-prose alias
-setReconstructionRegion                    §7
-setReconstructionRegionAuto                §7
-setReconstructionRegionByDensity           §7
-setReconstructionRegionOnCPs               §7
-setSelectedClassAsGroundForDTM             §9
-setSelectedClassAsGroundForExport          §9
-setSelectedClassLasFormat                  §9
-setWeightInTexturing                       §4
-showUI                                     §3
-silent                                  *  §10
-simplify                                *  §8.2
-smooth                                     §8.2
-start                                      §3
-stdConsole                                 §10    retired in this repo
-tag                                        §10
-transferClassification                     §9
-translatorMode                             §11    Help-prose only; startup mode
-undercut                                   §8.2, §12.2   HIDDEN: commented out of the Help table
-unlockPPIProject                           §3
-unpauseInstance                            §5
-unwrap                                  *  §8.1
-update                                  *  §6.1
-uploadToSketchfab                          §8.3
-waitCompleted                           *  §5
-writeProgress                           *  §10
```

`RSNode.exe` only — **not** `RealityScan.exe` commands (§17):

```
-hostAddress
-landingPage
-port
```

---

## 20. Open questions

Every [OPEN] item raised in this document, with the cheapest probe that would settle it.
Ordered by cost, cheapest first. Items marked **GUI** need a human at the application; the
rest are headless and scriptable.

### Answerable from the GUI console view in under a minute

| # | Question | Probe |
|---|---|---|
| Q1 | Does `-invertControlPointSelection` take a `controlPointName` parameter? `appbasics/allcommands` says no, `tutorials/commandline_1` says yes. | **GUI** Type `-invertControlPointSelection` into the console view; the tooltip lists every parameter form. |
| Q2 | Is `-setReconRegionOnCPs` a real alias of `-setReconstructionRegionOnCPs`? | **GUI** Type `-setReconRegion` and press TAB; completion answers immediately. |
| Q3 | What `layerType` strings do `-setImageLayer` / `-setImagesLayer` / `-removeImageLayer` accept — with or without the leading dot? | **GUI** Try `.geometry`, `geometry`, `.mask`, `mask`, `.labels`, `.depth`, `.texture`, `.texture02` once each from the console view and read the error/no-error. |
| Q4 | Is `-exportDepthAndMask` a live alias or only a stale doc name? | **GUI** Type `-exportDepth` and press TAB. |
| Q4b | Does `-undercut` (§12.2) still parse in 2.2? Its Help row is commented out, but process ID `27 UNDERCUT_MODEL_PARTS` is public. | **GUI** Type `-under` and press TAB — the console's completion list comes from the binary, not the Help, so it answers whether the command exists. |
| Q5 | What do `ifKGrp` and `ifKmode` in `FlightLogParams.xml` actually control ("Euler angles order (YPR)" and "Camera mount")? Both strings are compiled into the binary and appear in no install file. | **GUI** Save three params files from the Import Trajectory dialog: defaults, Euler-order changed only, camera-mount changed only. Diff them. One minute; **load-bearing for orientation-prior attribution**, open since 2026-07-26. |

### Answerable headless in under ten minutes

| # | Question | Probe |
|---|---|---|
| Q6 | Is `-execRSCMD` limited to 9 or 10 arguments — is `$(arg0)` real? | An `.rscmd` containing `-tag $(arg0)`, invoked with one argument. |
| Q7 | Is command parsing case-insensitive (`-execrscmd` vs `-execRSCMD`)? | Run `-QUIT`, or `-EXECRSCMD` on a trivial file. |
| Q8 | `.rcconfig` or `.rsconfig` for global settings? | `-exportGlobalSettings D:\probe\settings` and look at what is written. |
| Q9 | Do `-importTrajectory` and `-importFlightLog` hit the same implementation? | Run both on the smoke fixture with the same params XML; diff the resulting prior poses and the `20598 IMPORT_FLIGHT_LOG` process records. |
| Q10 | Does `-exportSelectedComponentFile` accept a path without the `.rsalign` extension, and does it leave the in-scene component's name untouched? | One smoke-fixture call. |
| Q11 | Does `-importImageSelection` accept the same literal-path list an `.imagelist` holds? If so it replaces the per-image `-selectImage union` loop at a fraction of the cost. | Write 100 paths to a file, run it, `-exportXMP`, count. |
| Q12 | What does "Finalizing N component(s)" in the log actually mean? | Two tiny imports, one `-mergeComponents`, count the result. |
| Q13 | Does `-exportLatestComponents` produce anything after `-mergeComponents` (there is no "last alignment")? | Hardening cell U9: merge mode on the smoke fixture, then export, then count files. |
| Q14 | Does `-align` update an existing component **in place**, keeping its name, when it only grows? Component names (`Component N`) are observed unstable. | Hardening cell U6: align, note names, add one image, align, compare. |
| Q15 | Does `-deleteSelectedComponent` free its images back into the unregistered pool for a subsequent `-align`? | Hardening cell U4. |
| Q16 | Does `-selectMaximalComponent` ignore component names entirely? | Hardening cell U5: rename the smallest component to something alphabetically first and re-select. |
| Q17 | Is `inpPosePriorRelative=2` (relative Exact lock) subject to the same "must be all aligned in a single run" restriction that blocks `inpPose=3`? | Set it on a solved component, add one image, `-align`, read the error. |
| Q18 | Can `-abortInstance` leave a model recoverable by `-continueModelCalculation`? | Abort a preview model on the smoke fixture, then `-load` + `-continueModelCalculation`. |

### Answerable headless, but at real cost

| # | Question | Probe / cost |
|---|---|---|
| Q19 | Does `-exportReport` run headless without blocking, and does it emit georeferencing status and residuals? **The longest-standing instrument gap** — georeferencing of a merged or assembled scene is verified only in the GUI today. | Hardening cells U7/U14: delegate `<install>\Reports\ComponentAccuracyReport.html` with a watchdog. Risk being tested: that it blocks the way `-exportRegistration` does — and unlike `-exportRegistration` there is no params-file escape, since `-exportReport` takes a boolean as its third parameter, not an XML. |
| Q20 | Are cached features from `-detectFeatures` reused across `-newScene` and across instances? | `-detectFeatures`, quit, relaunch, `-align`; compare wall clock against a cold align. One zone. |
| Q21 | Does `sfmMergeGeoreferencedComponents=true` work when the components are georeferenced by something stronger than 10 m position-only priors? The D1/D2 negative results may never have met the feature's documented premise. | Re-test the georef-flag path with priors-v2 components. Queued as a PD follow-on cell, never run. |
| Q22 | Can `inpDistortionModel` set through `-editInputSelection` override the global `sfmDistortionModel` per image, where the per-image XMP hint demonstrably cannot? | One zone, two camera families, compare solved `xcr:DistortionModel` per family. |
| Q23 | Is a merge's small camera deficit real solver loss or a harvest artifact? | Re-import an accepted fused `.rsalign` **from its original export location** into a spare instance and census it. 3,740 means accounting artifact, 3,738 means real loss. (Reading RealityScan's own count from the attempt's log snapshot is **not** trustworthy on these artifacts — see the log-splice finding.) |
| Q24 | Does the hand-merged 13-column flight-log format in `flightlogs.xml` survive a RealityScan update? | Re-check the file after any update. Standing item. |
| Q25 | How long does `-quit` → `-getStatus` gone take on a 4,000+ camera scene? The shutdown bound is verified only on small scenes. | One teardown. |
| Q26 | Do two concurrent instances on different GPUs stay isolated (marker files, cache)? Never run. | Boot RS1 on GPU 0 and RS2 on GPU 1, align two small zones simultaneously. |
| Q27 | Does RealityScan's own `-importVideo` frame extraction carry a timestamp offset like this repo's retired OpenCV extractor did (one output interval early)? | Extract a synthetic per-frame-gray video and read the resulting timestamps. |
| Q28 | Does the `RSNode.exe` HTTP channel report completion more reliably than `-waitCompleted`? | One `align` call on the smoke fixture with response timing recorded. |
| Q29 | Does `appCopyImportedComponentsToCache` interact with the relocated-`-importComponent` hang (hard rule 7)? | Copy a component elsewhere, set the key, `-importComponent`, watchdog at 45 min. |
| Q30 | Has the `-selectLargeTrianglesRel 30` threshold ever been visually validated on a real model? No. | Render before/after at two thresholds and look. **GUI** for the judgement. |

### Not answerable by a probe — reporting or decisions

| # | Item |
|---|---|
| Q31 | The deterministic standalone-alignment failure `MSS_STR001` (generic `0x8000FFFF`) on one 1,476-image zone with fully exonerated data has **never been reported to Epic**. Forensic log at `testing/results/z14_forensic_rslog.txt`. |
| Q32 | `-setMinComponentSize` is deprecated with **no documented replacement** while remaining required. What replaces it in the next release is unknown; nothing in the 2.2 Help says. |
| Q33 | Whether "no re-optimization" still describes `-mergeComponents` in the current build. The staff claim is from 2021, pre-rename and outside the trust window; the observed 56-minute merge reconstruction argues against it. |
