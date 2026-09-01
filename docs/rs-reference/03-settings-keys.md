# Complete settings-key reference (`-set` / `-preset`)

This document is the exhaustive reference for RealityScan's application-settings
namespace: the `key=value` pairs accepted by the `-set` and `-preset` commands, and the
same key names as they appear inside `<Configuration>` parameter XML files. It covers
the mechanics (quoting, delegation ordering, restart-requiring keys, persistence,
read-back, failure signatures), every key with a concrete documented or file-level
source, the binary-derived candidate namespace, the keys this repository pins in
production and why, the dead/deprecated names, and the keys measured as inert. It does
**not** cover: the commands themselves (see `02-command-reference.md`), the structure and
authoring of parameter XML files (see `09-xml-parameter-files.md`), what the alignment
keys mean for registration quality (see `07-alignment.md`), flight-log import parameters
in their georeferencing context (see `06-georeferencing-flightlogs-and-scale.md`),
per-image priors set through `-editInputSelection` (see
`13-camera-rigs-priors-and-orientation.md`), or process/exit-code semantics (see
`01-cli-fundamentals.md` and `12-failure-modes-and-race-conditions.md`).

**Applies to:** RealityScan 2.2 (Epic Games), Windows, headless CLI operation.
Build under test: `RealityScan.exe` FileVersion `2.2.0.119430.RS`, installed at
`C:\Program Files\Epic Games\RealityScan_2.2\`.

**Tags:** [OFFICIAL] shipped Help · [VERIFIED] measured in production here ·
[CONTRADICTED] docs vs observation · [UNDOCUMENTED] · [INFERRED] · [OPEN]

**Verification pass.** Every [OFFICIAL] citation in this document was re-read against the
named Help topic, every [VERIFIED] citation against the named repo file, and the
binary-presence claims were re-run against `RealityScan.exe` (UTF-16LE at both byte
alignments **and** ASCII) rather than inherited from the survey. The substantive
corrections it produced are marked in place:

- merge fusion is **content**-driven, not identity-driven — the earlier "fuses only through
  shared camera identity" reading is refuted (§12.2, §13.4);
- the registry `appConfig` blob is **readable**, not opaque, and stores key names the
  executable does not contain, which weakens every read-back oracle (§1.6, §1.8, §12.1);
- the merge ladder has two ladders and different rung labels from the earlier draft (§10.4);
- **eight** `RealityScan.FeatureDetector.*` ids exist, not two (§13.2);
- no `RealityCapture`-prefixed *settings* key exists, but three `RealityCapture*`
  non-setting identifiers do (§11);
- the enum-ordinal mapping is proven for `appProcessAction` only; the `unwrapStyle=1`
  example does **not** establish it (§1.4);
- ten live `ifu*` flight-log accuracy keys were missing from the key census (§8.5, §14).

---

## Table of contents

- [1. Mechanics of `-set` and `-preset`](#1-mechanics-of--set-and--preset)
- [2. Prefix map](#2-prefix-map)
- [3. `app*` — application, cache, import, notification](#3-app--application-cache-import-notification)
- [4. `sfm*` — alignment / registration](#4-sfm--alignment--registration)
- [5. `lis*` — LiDAR / laser-scan import](#5-lis--lidar--laser-scan-import)
- [6. `mvs*` / `Mvs*` — reconstruction, depth maps, meshing](#6-mvs--mvs--reconstruction-depth-maps-meshing)
- [7. `unwrap*`, `txt*`, `col*`, `ImageLayerFor*` — unwrap, coloring, texturing](#7-unwrap-txt-col-imagelayerfor--unwrap-coloring-texturing)
- [8. Tool parameter-XML key families](#8-tool-parameter-xml-key-families)
- [9. Key spaces that are NOT `-set`](#9-key-spaces-that-are-not--set)
- [10. Settings you should always pin explicitly](#10-settings-you-should-always-pin-explicitly)
- [11. Dead and deprecated keys](#11-dead-and-deprecated-keys)
- [12. Inert keys — configured but with no effect](#12-inert-keys--configured-but-with-no-effect)
- [13. Contradictions and doc defects](#13-contradictions-and-doc-defects)
- [14. Complete alphabetical checklist](#14-complete-alphabetical-checklist)
- [Open questions](#open-questions)

---

## 1. Mechanics of `-set` and `-preset`

### 1.1 The two commands

```bat
RealityScan.exe -set "key=value"
RealityScan.exe -preset "key=value"
```

| Command | Help description | Notes |
|---|---|---|
| `-set` | "Set an application state variable." (tutorials/commandline_4, tutorials/commandline_5) — **but** "Change an application setting." (appbasics/allcommands). The Help gives the command two different one-liners. | The universal form. Used everywhere in this repo. [OFFICIAL: all three topics, wordings as attributed] |
| `-preset` | "Change an application setting during the setup phase. Ideal for changes that require a reset of the application." | Identical wording in all three topics. Never used in this repo; no empirical data. [OFFICIAL: tutorials/commandline_4, tutorials/commandline_5, appbasics/allcommands] |

The documented signature of both is a **single** required parameter, `"key=value"`.
[OFFICIAL: appbasics/allcommands, tutorials/commandline_4/_5 — the Required Parameter
column holds exactly one pair] Every worked example in the Help repeats the flag rather
than listing several pairs, so a multi-pair form and a `-set key value` (unquoted, split)
form are both assumed not to exist. [INFERRED — no probe was run; a `-set "a=1" "b=2"`
attempt would settle it in seconds]

The Help's "Learn more about how to use this command here" link on the `-preset` row
points back at `tutorials/setkeyvaluetable.htm` — the same key/value table that documents
`-set`. **There is therefore no document anywhere in the shipped Help that says which
keys require `-preset` rather than `-set`.**
[VERIFIED: `<a href="../tutorials/setkeyvaluetable.htm">` in the `tr_seco_preset` row of
`Help\en-US\tutorials\commandline_4.htm`, read directly] [OPEN — see Open questions]

**Spell key names exactly as this document spells them, including case.** The 2.2 binary
contains *both* spellings of three keys — `mvsDecimationFactor` **and**
`MvsDecimationFactor`, `mvsPreviewDownscaleFactor` **and** `MvsPreviewDownscaleFactor`,
`mvsImportMaxTrianglesPerPart` **and** `MvsImportMaxTrianglesPerPart` — as separate
strings, and the lowercase spelling is the one the Help documents. Whether the *parser* is
case-sensitive has not been tested; the safe rule follows from the fact that two distinct
strings exist either way.
[VERIFIED: UTF-16LE extraction from `RealityScan.exe` 2.2.0.119430, all six spellings
present, re-run this session] [INFERRED: parser case-sensitivity — probe by
`-set "APPINCSUBDIRS=true"` and watching for `err:7155` or for no effect]

### 1.2 Quoting and the cmd/subprocess boundary — the #1 practical failure

`=` is a cmd token delimiter. cmd splits unquoted `;` `,` `=` into separate `.bat`
arguments, and Python's `subprocess` quotes only on whitespace. An unquoted `key=value`
that crosses a `.bat` argument boundary therefore arrives as **two** arguments, and
RealityScan logs:

```
Parsing setting key=value 'sfmMergeGeoreferencedComponents' failed [err:7155]
Parsing setting key=value 'false' failed [err:7155]
```

Three consequences, all observed together:

1. **The setting is silently never applied.** Nothing in the CLI surface says the flag
   did not take; the operation runs on whatever the instance already had.
2. The parse failure is a process failure, so it lands in the errors marker file and
   **aborts the enclosing workflow** through the `:run` error gate.
3. Because of (1), an entire wave of flag-comparison test cells produced results that
   were all measuring the same unflagged configuration —
   "no flag cell before wave 1f ever applied its flags", and wave 1e's merge-cell results
   were declared void and re-run.

[VERIFIED: NA167 B5; FINDINGS 2026-07-23; testing/FINDINGS.md item 15;
testing/MERGE_TEST_PLAN §5 item 7 — the two log lines above are quoted from
testing/FINDINGS.md item 15]

Two mandatory mitigations, both in force in this repo:

**(a) Write the pair with the quotes inside the RealityScan invocation.** Never pass a
`key=value` pair as a `.bat` argument.

```bat
%RealityScan% -delegateTo %RS_INSTANCE% -set "appIncSubdirs=true"
```

**(b) When a pair must cross a `.bat` boundary, encode it as `key:value` and convert
inside the script.** `MergeZoneComponents.bat` accepts up to four `key:value` arguments
(`%6`..`%9`) and converts the colon:

```bat
:applySet
set "kv=%~1"
set "kv=%kv::==%"
echo Setting %kv%
%RealityScan% -delegateTo %RS_INSTANCE% -set "%kv%"
exit /b 0
```

[VERIFIED: `modules/realityscan_interface/RS_CLI/Scripts/MergeZoneComponents.bat` lines
131–142; `merge_zones.py` passes `'sfmMergeGeoreferencedComponents:true'` etc.]

A value containing spaces or embedded quotes needs escaped inner quotes. The production
example is the completion hook, where an unquoted executable path silently disabled **all**
error detection on any checkout whose path contained a space:

```bat
-set "appProcessExecCmd=wscript.exe //B \"%ErrorPath%\ErrorWriterLaunch.vbs\" $(processResult) $(processId) $(processDuration:d) %RS_INSTANCE%"
```

[VERIFIED: HANDOFF overhaul item 4, 2026-07-21; `startRealityScan.bat` line 61]
[OFFICIAL: appbasics/appsettings — "If the file path contains spaces, it must be in
double quotation marks"]

### 1.3 Ordering under delegation — `-set` is instant and FIFO

Delegated commands (`-delegateTo <instance> <cmd>`) are **queued FIFO**, and the
delegating process returns at hand-over, not at completion. `-set` is an instant command,
so a `-set` delegated before a long queued operation is guaranteed to execute first.
**No `-waitCompleted` is needed between a `-set` and the operation it configures.**
[VERIFIED: `AlignZone.bat` lines 67–73 (the `appIncSubdirs` case, with the comment "Instant
-set, FIFO-ordered before the queued addFolder, no wait needed") and 80–91 (the settings
replay followed directly by `call :run -align`); every production run since 2026-07-21]

```bat
:: instant -set, FIFO-ordered before the queued addFolder, no wait needed
%RealityScan% -delegateTo %RS_INSTANCE% -set "appIncSubdirs=true"
call :run -addFolder "%input_dir%"
```

The same pattern applies to the alignment settings replay: `AlignZone.bat` fires **28**
`-set` commands back to back with no waits, then a single `:run -align`. 28 is exactly the
`sfm`/`lis` subset of `AlignmentParams.xml`'s 35 entries (27 `sfm*` + 1 `lis*`); the other
seven are the `s<NNN>l` ids the filter drops (§13.3).
[VERIFIED-by-inspection: `AlignmentParams.xml` entry census]

### 1.4 Value encodings accepted

| Form | Example | Evidence |
|---|---|---|
| `true` / `false` | `-set "appQuitOnError=false"` | [OFFICIAL: tutorials/commandline_5] |
| decimal int | `-set "appProcessActionTime=0"` | [OFFICIAL: tutorials/commandline_5] |
| **hex int `0x…`** | `-set "sfmMaxFeaturesPerImage=0xc350"` (= 50000) | [UNDOCUMENTED] The GUI settings exporter writes alignment ints in hex; `AlignZone.bat` replays them verbatim through `-set` and production zone aligns completed with no `err:7155` |
| float | `-set "sfmMaxFeatureReprojectionError=1.29999995"` | [UNDOCUMENTED: same route] |
| enum by name | `-set "sfmDistortionModel=Brown3"` | [OFFICIAL: tutorials/commandline_4] |
| **enum by ordinal** | `-set "unwrapStyle=1"`; "Setting `appProcessAction` to 2 stands for … Execute a program" | [OFFICIAL: tutorials/commandline_4 and tutorials/commandline_5 — Epic's own examples use ordinals for keys whose value table lists only names] |
| path string | `-set "appCacheCustomLocation=D:\cr-tmp"` | [OFFICIAL: tutorials/commandline_5] |
| empty | `appCacheCustomLocation`, `appProcessExecCmd`, `UserInterfaceLanguageId` ship empty | [OFFICIAL: tutorials/setkeyvaluetable] |
| `0x0` / `0x1` as booleans | `unwrapFillTextures=0x1`, `MvsExportIsGeoreferenced=0x1` | [UNDOCUMENTED: GUI-exported params XML; `true`/`false`, `0`/`1` and `0x1` all appear for the same key across files] |

**Enum ordinals — accepted, but the mapping is only proven for one key.**

- **That ordinals are accepted at all** is [OFFICIAL]: `tutorials/commandline_4` sets
  `-set "unwrapStyle=1"` for a key whose value table lists only names.
- **The mapping name→ordinal** is proven only for `appProcessAction`, where
  `tutorials/commandline_5` states it in prose: "Setting `appProcessAction` to 2 stands for
  setting it to Execute a program", and the table order is `None`, `PlaySound`,
  `ExecuteProgram` — so 0/1/2 by row order. [OFFICIAL]
- For **every other** string enum, "ordinal = 0-based row order in `setkeyvaluetable.htm`"
  is [INFERRED]. It is *not* confirmed by the `unwrapStyle=1` example: Epic never says
  which style `1` selects, and in that same command they also set
  `unwrapMaximalTexCount=1`, a key the Help marks "relevant for:
  `unwrapStyle=MaxTexturesCount`" — which would be pointless if `1` meant `FixedTexelSize`.
  Read the example as evidence of *syntax*, not of *mapping*.

Settled by: set the ordinal, then export the settings panel from the GUI and read back the
name. Until then, **prefer the name form** (`-set "unwrapStyle=MaxTexturesCount"`) for every
enum except `appProcessAction` — the repo's own params XMLs use names, and a name cannot be
silently off by one.

### 1.5 Settings that require an application restart

Some settings need a reset. `appQuitOnReset=true` suppresses the modal — **and the
application then quits after the setting is changed**, so each such setting needs its own
invocation:

```bat
RealityScan.exe -set "appQuitOnReset=true" -set "appCacheLocation=Custom"
RealityScan.exe -set "appQuitOnReset=true" -set "appCacheCustomLocation=D:\cr-tmp"
RealityScan.exe -newScene
```

[OFFICIAL: tutorials/commandline_5, "Quit on Restart"]

The Help never enumerates which keys are restart-requiring; the cache pair is the only
worked example. [OPEN]

This repo does **not** use `appQuitOnReset`. It passes the cache keys on the boot command
line of a fresh instance, which achieves the same thing with no restart cycle:

```bat
set "RS_CACHE_ARGS=-set "appCacheLocation=Custom" -set "appCacheCustomLocation=%RS_CACHE_DIR%""
```

[VERIFIED: `startRealityScan.bat` line 54, in production since 2026-07-26]

### 1.6 Scope and persistence — what survives, what resets

| Question | Answer | Source |
|---|---|---|
| Does a `-set` value survive `-newScene`? | Yes. The namespace is application-global, not per-scene. | [INFERRED from global storage + persistence across restarts; no cell isolated it] |
| Does a `-set` value survive an instance restart? | **Yes.** `testing/MERGE_TEST_PLAN` §3 lists "swept `-set` keys are pinned in every cell (values persist across instance restarts)" as a standing contamination control, i.e. the persistence was treated as established and designed around. Corroborated independently below: the settings live in a **registry** blob, not in process memory. | [VERIFIED-as-control-in-force: testing/MERGE_TEST_PLAN §3, 2026-07-23 — no cell isolated persistence as its measured variable] + [VERIFIED: registry read, below] |
| Where is the state stored? | `HKCU\Software\EpicGames.RealityScan\RealityScan\Workspace`, values `appConfig` (REG_BINARY, 33,325 bytes on this machine) and `appSharedConfig` (REG_BINARY, 158 bytes). **`appConfig` is a UTF-16LE key/value serialisation and the key names ARE readable** — decoding it yields `appCacheLocation`, `appQuitOnError`, `appProcessAction`, `appProcessActionTime`, `appProcessExecCmd`, `appCacheCustomLocation`, `appCacheImageMetadata`, `appQuitOnReset`, `s235l`/`s236l`/`s237l`/`s250`…, `ifCSopt`, `ifuuInh`, `ifuuInhEn`, `ifKmode`, `mvsFlt*`, `reprojectionTool_*`, `gpsLogFileFormat`, `csvFLSep`, and ~460 more tokens. `appSharedConfig` holds only `appVersion` / `appSubVersion` / `appMinorVersion` / `appBuildVersion`. | [UNDOCUMENTED: read-only registry read + UTF-16LE decode of the blob, this build] — **corrects an earlier claim in this document that the blobs were opaque** |
| How do I wipe it? | `-reset cfg` (settings), `-reset ui`, `-reset cfgui`, `-reset all` (clean-install equivalent). **Works only from a batch file and never with delegation.** | [OFFICIAL: appbasics/allcommands, tutorials/commandline_4] |
| Do two concurrent instances share settings? | Unknown. Never exercised — multi-instance parallelism has never been run here. | [OPEN] |

**The config blob stores keys the executable does not contain.** `ifKmode` is present in
this machine's `appConfig` blob, yet the string `ifKmode` does **not** occur anywhere in
`RealityScan.exe` 2.2.0.119430 — checked as UTF-16LE at both byte alignments and as ASCII
over the whole 45,211,352-byte image. The settings layer therefore **persists key names
the engine never looks up**. Two consequences, both load-bearing:

1. Reading a key back out of the config (or, by extension, out of
   `-exportGlobalSettings`) proves the value was **stored**, not that it was **honoured**.
   The export/diff probe in §1.8 is therefore a weaker oracle than it looks: it can
   distinguish "the pair parsed" from "the pair was rejected", but not "the engine reads
   this key" from "the engine ignores this key".
2. It is the exact mechanism by which a dead key looks alive — see §12.1.

[VERIFIED: registry read + exhaustive binary scan, this session] [INFERRED: that the
storage path is params-XML import or the GUI dialog writing through to the config; not
isolated]

**Operational consequence of persistence (the trap).** `startRealityScan.bat` reuses an
already-running instance instead of relaunching it:

```bat
%RealityScan% -getStatus %RS_INSTANCE% >nul 2>&1
IF /I "%ERRORLEVEL%"=="0" (
    %RealityScan% -delegateTo %RS_INSTANCE% -newScene -deleteAutosave
    goto :eof
)
```

On the reuse path **the boot `-set` line never executes**. The boot-time pins
(`appAutoSaveMode`, `appQuitOnError`, `appProcessActionTime`, `appProcessAction`,
`appProcessExecCmd`, cache keys) are inherited from whatever that instance was launched
with. They normally match, because those values also persist in the registry — but an
interactive GUI session or another driver that changed them between runs would not be
corrected. [VERIFIED-by-code-reading: `startRealityScan.bat` lines 16–22]
[INFERRED: the failure mode; never observed]

### 1.7 When a key must be set, relative to the operation it affects

| Key(s) | Must be set | Why | Source |
|---|---|---|---|
| `appIncSubdirs` | **before every** `-addFolder` | Without it this build adds 0 layer images from a tree whose images live in subfolders | [VERIFIED: FINDINGS 2026-07-23] |
| all `sfm*` / `lis*` | **before** `-align` | `-align` accepts no parameter file; an XML passed to it is silently ignored | [VERIFIED: FINDINGS 2026-07-21; `AlignZone.bat` lines 81–84] |
| `PrecomputeDepthmaps=true` | before `-calculatePreviewModel` / `-calculateNormalModel` / `-calculateHighModel`; **reset to `false` afterwards** | With it set, those commands compute depth maps into the cache and build no model | [OFFICIAL: tutorials/commandline_2] |
| `appCacheLocation`, `appCacheCustomLocation` | at instance boot (or via `appQuitOnReset` restart cycle) | Restart-class settings | [OFFICIAL: tutorials/commandline_5] + [VERIFIED: `startRealityScan.bat`] |
| `appProcessAction`, `appProcessActionTime`, `appProcessExecCmd` | at instance boot, before any operation whose completion must be reported | They are the authoritative per-operation result channel | [VERIFIED: `startRealityScan.bat`; hook liveness re-tested FINDINGS 2026-07-25] |
| `appQuitOnError` | at instance boot | Changes exit-code semantics for the whole session | [OFFICIAL: tutorials/commandline_5] |
| `appAutoSaveCliHandling` | before `-load` | It defines what `-load` does when an `.autosave` exists | [OFFICIAL: tutorials/setkeyvaluetable] |
| `appGroupCalibrationByExif`, `appIgnoreExifGPS` | before the `-addFolder` / `-add` that imports the images | They are import-time settings | [INFERRED from the Help's "Import settings" grouping] |
| `txtImportDefaultTexResolution`, `mvsImportMaxTrianglesPerPart` | before `-importModel` | Import-time settings | [INFERRED] |
| `mvs*` reconstruction keys | before `-calculate*Model` | | [INFERRED] |
| `unwrap*` / `txt*` / `col*` | before `-unwrap` / `-calculateTexture` / `-calculateColoring` | This repo passes a params XML to those commands instead | [INFERRED] |
| `appMaxPointsToDisplay`, `appThemeZoom`, `appUIAnim`, `UserInterfaceLanguageId` | any time | Render/UI only; no operational ordering | [INFERRED] |

### 1.8 Reading the current value

**There is no per-key read-back command.** A sweep of `appbasics/allcommands` finds
exactly one `get*` command in the whole CLI — `-getStatus` — and it reports instance
liveness, not settings.
[VERIFIED: full read of `appbasics/allcommands`]

The only known read-back mechanisms:

| Mechanism | Command | Notes |
|---|---|---|
| Export all global settings | `-exportGlobalSettings settings.rcconfig` | Cheapest CLI oracle for "did my `-set` take?" — export, `-set`, export again, diff. **Not yet exercised in this repo.** [OPEN] |
| Import all global settings | `-importGlobalSettings settings.rcconfig` | Round-trips the same file |
| **Read the registry blob directly** | none — `HKCU\Software\EpicGames.RealityScan\RealityScan\Workspace` value `appConfig`, decoded UTF-16LE | Needs no running instance and no command. Verified readable this session (§1.6). Same caveat as the export: shows storage, not consumption |
| Per-panel export from the GUI | Settings panel → export to `.xml` | Produces the `<Configuration id="{GUID}">` files described in `09-xml-parameter-files.md`; this is how `AlignmentParams.xml` was produced |

**Every read-back path answers a weaker question than you want.** Because the config layer
stores unrecognised key names verbatim (§1.6), a key that appears in the export or the blob
after a `-set` has proved only that the pair parsed and was written. Establishing that the
*engine* reads a key still requires a behavioural A/B on real data.

Extension conflict: `.rcconfig` in `appbasics/allcommands` and `appbasics/appsettings`
(the GUI's Global Settings panel says "export … to .rcconfig file"), `.rsconfig` in
`tutorials/commandline_4`. [CONTRADICTED, internal to the Help] Two topics against one
favours `.rcconfig`, but the product rename makes `.rsconfig` the plausible *newer* name,
so the majority is not decisive. [INFERRED] Do not guess — run
`-exportGlobalSettings <path-with-no-extension>` once and read the filename the app
produces.

**Silence is not success.** An unknown-but-parseable key produces no error and no effect.
`err:7155` fires on a *malformed pair*, not on an *unrecognised key name*. Nothing in the
CLI confirms that a key name was recognised or that a value was honoured. This is the
single most important epistemic limit in this document: for keys tagged [UNDOCUMENTED],
"the repo sets it and the run succeeded" is evidence the string parses, **not** evidence
the setting was applied. [VERIFIED: err:7155 semantics, NA167 B5] [OPEN: neither read-back
path closes this — see the caveat above; only a behavioural A/B does]

### 1.9 Parameter XML files use the same namespace

Commands that take a `params.xml` consume a `<Configuration id="{GUID}">` file of
`<entry key="…" value="…"/>` rows drawn from this same global namespace:

```xml
<Configuration id="{54A4029C-DE57-43F6-8F81-75C62E159021}">
  <entry key="unwrapCheckerBoardCellSize" value="64"/>
  <entry key="unwrapButtonDisabled" value="0"/>
  <entry key="unwrapGutter" value="2"/>
  <entry key="unwrapStyle" value="MaxTexturesCount"/>
  <entry key="unwrapMaximalTexCount" value="1"/>
  <entry key="unwrapFillTextures" value="0x1"/>
  <entry key="unwrapMaxTexResolution" value="8192"/>
  <entry key="unwrapLargeTriangleRemovalThr" value="1000"/>
</Configuration>
```

(`RS_CLI/Metadata/Texturing_MaxTextureCount1_8k.xml`, verbatim.)

The `{GUID}` identifies the owning settings panel and matches an
`HKCU\Software\EpicGames.RealityScan\RealityScan\Workspace\SP-{GUID}` registry subkey.
24 `SP-{GUID}` subkeys exist on this machine, and all seven GUIDs used by this repo's
params XMLs are among them:

| GUID | Panel / params file |
|---|---|
| `{E377B69D-FB4B-4833-9CBE-FF747B7AF6D9}` | Alignment Settings — `AlignmentParams.xml` |
| `{54A4029C-DE57-43F6-8F81-75C62E159021}` | Unwrap / texturing — `Texturing_*.xml`, `Unwrapping_*.xml` |
| `{033AEF62-8421-47A4-81CB-203741113577}` | Simplify — `Simplify*_Params.xml`, Epic's `simplify.xml` |
| `{585E749B-DC69-4D8C-9114-FA8CBB6F88F3}` | Smooth — `Smoothing*_Params.xml`, Epic's `smooth.xml` |
| `{8F3517E3-5632-40FE-BD10-9967EA8F299F}` | Texture reprojection — `ReprojectionParams.xml`, Epic's `reprojectTexture.xml` |
| `{93DBD041-AE1C-4631-89BC-D9430FCED843}` | Import Trajectory — `FlightLogParams.xml` |
| `{EC40D990-B2AF-42A4-9637-1208A0FD1322}` | XMP export — `XMPExportParams.xml` |

**The `SP-{GUID}` subkeys are not a read-back path.** Each holds a single `state` DWORD
(UI state; `16777216` for the alignment panel here) and no key/value data. The values
themselves live in the flat `appConfig` blob (§1.6).
[UNDOCUMENTED: registry enumeration, read-only, this session]

Whether every params-XML key is *also* accepted by `-set` is [OPEN] for the export/tool
families. It is [VERIFIED] for the `sfm*`/`lis*` subset, because `AlignZone.bat` reads
`AlignmentParams.xml` and replays each such row through `-set`:

```bat
for /f usebackq^ tokens^=2^,4^ delims^=^" %%A in ("%AlignmentParams%") do (
    echo %%A| %SystemRoot%\System32\findstr.exe /b /c:"sfm" /c:"lis" >nul
    if not errorlevel 1 %RealityScan% -delegateTo %RS_INSTANCE% -set "%%A=%%B"
)
```

### 1.10 `-align` takes no parameter file

`-align` accepts **no** `params.xml`; one passed to it is silently ignored. This is the
reason the `-set` replay above exists, and the reason repo policy is "never align on
instance defaults" — an instance carries whatever the previous session set.
[CONTRADICTED: older repo scripts and pre-2.x lore passed `-align "%AlignmentParams%"` /
observed: argument ignored, confirmed against `appbasics/allcommands` and the online
docs, 2026-07-21] [VERIFIED: FINDINGS 2026-07-21]

### 1.11 Failure signatures to watch

| Symptom | Meaning | Source |
|---|---|---|
| `err:7155` in `RealityScan.log`, non-empty errors marker | The `key=value` pair was split by cmd — **setting NOT applied**, workflow aborted | [VERIFIED: NA167 B5] |
| result `2147549183` = `0x8000FFFF` | Generic "unexpected program state". A broken `-set` and a genuine align failure emit the **identical** code. The real reason line exists only in `%LOCALAPPDATA%\Temp\RealityScan.log`, which is truncated on the next instance boot — snapshot it immediately | [VERIFIED: NA167 B6] |
| No error, no effect | Unknown-but-parseable key, or a known key given an unhonoured value | [OPEN: `-exportGlobalSettings` diff] |
| Errors marker contains only a number | The marker carries ErrorWriter's numeric process result, never the `err:NNNN` text — tolerant handlers must match codes, not strings | [VERIFIED: FINDINGS 2026-07-23] |

---

## 2. Prefix map

Fastest way to locate a key's family and its GUI home.

| Prefix | Governs | GUI home | In the Help key table? |
|---|---|---|---|
| `app*` | Application-global: logging, autosave, cache, import defaults, UI, process-end notification, CLI error handling | WORKFLOW → Application → Settings | Yes (20 keys) |
| `operationLog`, `allowReadOnly`, `suppressErrors`, `UserInterfaceLanguageId` | app-family keys without the `app` prefix | same | Yes |
| `sfm*` | Structure-from-motion: alignment/registration, camera priors, control-point priors, draft mode, distortion model | ALIGNMENT → Registration → Settings | Yes (29 keys) |
| `lis*` | LiDAR / laser-scan **import** feature sourcing | ALIGNMENT → Settings → Advanced | Yes (1 key) |
| `mvs*` (lowercase) | Multi-view stereo: depth maps, mesh calculation, LiDAR meshing, mesh filtration | MESH & COLOR → Create Mesh → Settings | Yes (subset) |
| `Mvs*` (capital) | Same engine, internal/dialog-facing spellings; **all** model export/import; snapshot/flyover/ortho render | Export dialogs, Mesh settings | Rarely |
| `mvsFlt*` | Mesh **filter tools**: simplify, smooth, marginal/large-triangle marking, part preservation | Simplify / Smooth / Filter tools | No |
| `mvsPpt*` | Mesh post-processing internals (DTM generation, ortho push-pull, part extension, topology inspection) | mostly not exposed | No |
| `mvsRR_*` | Reconstruction-region placement and coordinate fields | MESH & COLOR → Reconstruction Region | No |
| `unwrap*` | UV unwrap: gutter, texture resolution, texel-size strategy | MESH & COLOR → Color & Texture → Settings | Yes (subset) |
| `txt*` | Texturing/coloring behaviour (downscale, fill-in, recolor, method, style) | same panel | Yes |
| `col*` | Coloring style (`colStyle` only) | same panel | Yes |
| `ImageLayerFor*` | Which image layer feeds coloring / texturing | same panel | Yes |
| `simpl*` | Simplify-tool options that are not `mvsFlt*` | Simplify tool | No |
| `smooth*` | Smooth-tool iterations / weight | Smooth tool | No |
| `reprojectionTool_*` | Texture Reprojection tool | Texture Reprojection tool | No |
| `xmp*` | XMP metadata **export** options | XMP metadata export dialog | No |
| `ortho*` / `Ortho*` | Ortho projection: geometry, mosaicking, isolines, volumes | ORTHO tab | No |
| `lod*` / `Lod*` | Level-of-Detail / 3D Tiles export | Export LoD dialog | No |
| `classification_*` / `Classification*` | AI Classify tool and classification formats | Classify tool | No |
| `gpsLog*` | Flight-log / trajectory **import** source options | Import Trajectory dialog | No |
| `if*` | Import-flightlog field mapping, offsets, calibration grouping mode | Import Trajectory dialog | No |
| `csv*` | CSV delimiter / ignore-rows for flight log, GCP, CP measurements, distance definitions | corresponding import dialogs | No |
| `colmap*` | COLMAP import/export | COLMAP dialogs | No |
| `CoordinateSystem*` | Coordinate-system selection state (project, flight log, LRU list) | WORKFLOW → Settings → Coordinate Systems | No |
| `cache*`, `Cache*` | Cache readback/state (not the `app*` settings) | — | No |
| `inp*` | **Not `-set`.** `-editInputSelection "key=value"` | 1Ds Selected input(s) panel | Yes (tutorials/editselectioncommand) |
| `gp*` | **Not `-set`.** `-editControlPointSelection "key=value"` | Selected control point(s) panel | Yes (same) |
| `cName`,`cA`,`cB`,`cEnabled`,`cValue1`,`cValue1Acc` | **Not `-set`.** `-editConstraintSelection "key=value"` | Selected constraint(s) panel | Yes (same) |
| `orthoProjectionName` | **Not `-set`.** `-editOrthoProjectionSelection "key=value"` | Selected ortho photo(s) panel | Yes (same) |
| `aligFeaturesMode` | **Not `-set`.** `-editInputSelection`, or the `-setFeatureSource 0\|1\|2` command | Selected input(s) panel | Yes (same) |
| `alig*`, `align_*`, `gpu_*`, `unwrap_*` (snake_case) | **Not settings.** Report variables and operation-log telemetry field names | reports / operation log | see appbasics/reports_functions_and_variables |
| `s<NNN>l` | Auto-generated internal ids emitted by the settings-panel XML exporter for keys with no exported friendly name | — | No |

---

## 3. `app*` — application, cache, import, notification

GUI home: **WORKFLOW tab → Application → Settings**.
[OFFICIAL: appbasics/appsettings, tutorials/setkeyvaluetable]

### 3.1 Documented keys (20 App + 3 Error-handling)

| Key | Type | Default | Allowed values | GUI label / what it controls | Pinned here? |
|---|---|---|---|---|---|
| `appIncSubdirs` | bool | `false` | `true` `false` | **Include subdirectories** — applies to the `-addFolder` command only | **YES — `true`, before every `-addFolder`.** See §13.1 |
| `appLog` | bool | `true` | `true` `false` | **Log file** — Epic: "write and save the log file in the Windows Temp folder". The concrete path on this build is `%LOCALAPPDATA%\Temp\RealityScan.log` [VERIFIED: every post-mortem snapshot in FINDINGS] | no (left at default; the log is load-bearing for post-mortems and must not be disabled) |
| `operationLog` | bool | `true` | `true` `false` | **Operation log data** — uploads feature/settings/process telemetry to Epic. Epic states no input data or project files are sent | no |
| `appAutoSaveMode` | bool | `true` | `true` `false` | **Auto save mode** — writes `<project>.autosave` beside the project; for a new project, into the cache folder | **YES — `false`** at boot |
| `appAutoSaveCliHandling` | enum | `delete` | `delete` `recover` `abort` `ask` | **Handling of autosaved projects** — what `-load` does when an `.autosave` exists (global equivalent of `-load … recoverAutosave\|deleteAutosave`) | no |
| `appMaxPointsToDisplay` | integer | `10000000` | any int | **Max points to display** in the 3Ds view (render only) | no |
| `appCacheLocation` | enum | `SystemTemp` | `SystemTemp` `Custom` | **Cache location** | **YES — `Custom`** when `RS_CACHE_DIR` is defined |
| `appCacheCustomLocation` | path | *(empty)* | absolute path | **Cache custom location**; relevant only with `appCacheLocation=Custom` | **YES — `%RS_CACHE_DIR%`** |
| `appAutoClearCache` | enum (days) | `7` | `999999` do not clear · `0` clear all · `3` · `7` · `14` · `30` · `90` (items older than) | **Clear cache on exit** | no — **deliberately untouched**, retention is owner policy |
| `appCacheImageMetadata` | bool | `true` | `true` `false` | **Cache image metadata** — hidden `crmeta.db` with EXIF-derived metadata beside inputs | no |
| `allowReadOnly` | bool | `false` | `true` `false` | **Allow Read Only** — lets the same project open in two instances | no |
| `appThemeZoom` | enum | `0` | `0` Windows setting · `1` 100% · `1.25` · `1.5` · `2` (4K/200%) · `3` (300%) | **Zoom** — size of UI elements except ribbons | no |
| `appUIAnim` | bool | `true` | `true` `false` | **Animated UI** | no |
| `UserInterfaceLanguageId` | int (LCID) | *(empty)* | `2052` zh-Hans · `1028` zh-Hant · `1029` cs · `1033` en · `1036` fr · `1031` de · `1040` it · `1041` ja · `1042` ko · `3082` es | **UI language** (Help included) | no |
| `appGroupCalibrationByExif` | bool | `false` | `true` `false` | **Group calibration by exif** at import | no — and it is **unusable in either position** on this rig, see below |
| `appCopyImportedComponentsToCache` | bool | `false` | `true` `false` | **Copy imported components to cache** — Epic: set Yes when the cache is on an SSD, to speed component access | no |
| `appIgnoreExifGPS` | bool | `false` | `true` `false` | **Ignore exif GPS** globally (per-camera override lives in `sensorsdb.xml`) | no |
| `appProcessActionTime` | int (seconds) | `15` | `0`..n | **Minimal process duration** before the end-of-process action fires. `0` = fire for every process | **YES — `0`** |
| `appProcessAction` | enum | `None` | `None`(0) `PlaySound`(1) `ExecuteProgram`(2) | **Action** on process end | **YES — `ExecuteProgram`** |
| `appProcessExecCmd` | string | *(empty)* | command line; substitutions `$(processResult)` `$(processId)` `$(processDuration:d)` `$(sceneName)` | **Command-line process**, used when `appProcessAction=ExecuteProgram`. Quote the exe path if it contains spaces | **YES** — the `wscript.exe` ErrorWriter shim |
| `appQuitOnError` | bool | `false` | `true` `false` | **Quit on error**; with it set, the process exit code is the error's decimal code | **YES — `false`** |
| `appQuitOnReset` | bool | `false` | `true` `false` | **Quit on required restart** — suppresses the restart dialog and quits after the setting changes | no |
| `suppressErrors` | bool | `false` | `true` `false` | **Suppress error messages** | no — `-silent <path>` is used instead |

Sources for the table: [OFFICIAL: tutorials/setkeyvaluetable] for every key/type/default;
[OFFICIAL: appbasics/appsettings] for the prose descriptions; [OFFICIAL:
tutorials/commandline_5] for the error-handling trio and the `appProcessAction=2` ordinal;
[VERIFIED: `startRealityScan.bat` line 61 and `AlignZone.bat` line 72] for every "pinned
here" entry.

**Empirical notes on individual keys**

- `appIncSubdirs` — documented as a convenience, is in practice **mandatory**. See §13.1.
- `appProcessActionTime` — `appbasics/appsettings` says "For practical reasons, this value
  should be greater than 60", while `tutorials/commandline_5`'s own worked example uses
  `0` and explains it as "we are actually interested in every single process". This repo
  uses `0` in production. The cost of `0` is real: **RealityScan 2.2 fires the trigger for
  periodic internal heartbeat processes too**, so "the results log grew" does not mean
  "our command finished" — a completion check built on results-log growth raced ahead of a
  running `-align` and was removed entirely. [OFFICIAL, self-conflicting]
  [VERIFIED: HANDOFF 2026-07-21]
- `appProcessExecCmd` — the hook must be launched through a **GUI-subsystem** host. A
  console-subsystem child (`cmd /c …`) pops a visible console window on every fired
  trigger when the parent has none — hundreds of flashing windows over a long run. The
  production form runs `wscript.exe //B` on a VBS shim that invokes `ErrorWriter.bat`
  hidden and synchronously. [VERIFIED: FINDINGS 2026-07-23; `startRealityScan.bat`
  comment]
- `appProcessExecCmd` — an **unquoted** executable path silently disabled all error
  detection when the checkout path contained a space; found by adversarial review, fixed
  with escaped quotes. [VERIFIED: HANDOFF overhaul item 4, 2026-07-21]
- `appQuitOnError=false` is deliberate: warning-class results (`0x820000FF`, e.g.
  `err:18002` from `-importFlightLog` when the log references images not in the scene) are
  routine, and the orchestrator must decide, not the app. [VERIFIED: FINDINGS 2026-07-21]
- `appAutoSaveMode=false` is deliberate: autosave would race the destructive in-session
  identity loop, and a modal recovery dialog hangs a headless box forever. No stale
  autosaves appeared in any test run after this was pinned.
  [VERIFIED: HANDOFF verification checklist item 7, 2026-07-21]
- `appCacheLocation` / `appCacheCustomLocation` — **the cache is placed by the drive of the
  path given and does NOT move when the project moves.** `D:\rccache` reached 1,089 GB and
  refilled 197 GB of freshly-cleaned space within one run, killing a hull model three
  times, while the *project* drive showed 773.9 GB free. Two of those kills were reported
  only as result `2147942512` (`0x80070070`, `ERROR_DISK_FULL`) until the instance log was
  snapshotted and read "Processing failed: Out of disk space." Epic's guidance is
  explicitly **not** to hand-delete cache files — "don't delete the files from your cache
  folder since this may lead to some failures in the project" — but to free space on the
  cache disk or change the cache disk, so relocation is the sanctioned lever. The supported
  emptying route is the CLI command `-clearCache`, which **requires the project to be saved
  first**. [VERIFIED: FINDINGS 2026-07-26] [OFFICIAL: Epic "Out of Disk Space" page /
  appbasics/outofdisk]
- `appGroupCalibrationByExif` — **wrong in both positions** on an EXIF-identical rig.
  Enabled, it would collapse two physically different cameras (Make `Z CAM`, Model
  `E2-F6`, no focal length, no lens tag, identical exposure block) into ONE calibration
  group. Left `false`, images calibrate without EXIF grouping, which is weak. The answer
  is per-image XMP `Camera:CalibrationGroup` sidecars, one group per **physical** camera.
  [VERIFIED-by-inspection: docs/settings-evaluation-2026-07 §1, 2026-07-23]
- `appCopyImportedComponentsToCache` — never swept. Worth a probe because it may interact
  with the hard rule that a **relocated** `.rsalign` import hangs forever (`#timeout`,
  observed 6 h+). [OPEN]

### 3.2 `app*` strings in the 2.2 binary with no Help coverage

All [UNDOCUMENTED], known from UTF-16LE string extraction over `RealityScan.exe`
2.2.0.119430 plus the matching GUI control in `appbasics/appsettings`. Defaults unknown.
None used here. **Presence of a string is evidence of a namespace member, not proof that
`-set` accepts it.**

| Key | Likely GUI control | Note |
|---|---|---|
| `appTutorialMode` | Tutorial mode | shows contextual Help per tool |
| `appNavigationStyle` | Navigation style | Default / Autodesk / Leica |
| `appAutomaticUpdate`, `appAutoUpdate` | updater | two spellings both present |
| `appAutoRenew`, `appLicenseAutoRenew`, `appRenewT` | licensing | |
| `appActivTokenCLI`, `appActivTokenCLIValid` | CLI activation token | relevant to headless licensing [OPEN] |
| `appLic`, `appLicDel`, `appLicDelMachine` | license management | |
| `appEnableBadCps` | control points | plausibly "admit low-quality CPs" [INFERRED from the name] |
| `appExportSettings`, `appImportSettings` | Global Settings export/import | the `.rcconfig` buttons |
| `appOutputErrorStack` | diagnostics | would be high value against the generic `0x8000FFFF` problem [OPEN] |
| `appProcessEmailAddres` *(sic, one `s`)*, `appProcessEmailTempl` | Progress End Notification by e-mail | not described in `appsettings` |
| `appProcessSoundTheme` | sound used when `appProcessAction=PlaySound` | |
| `appTheme` | visual style | |
| `appBtnGPUs` | **GPUs to use** button | see the GPU note below |
| `appRootDir`, `appStartDir` | path state | |
| `appName`, `appVersion`, `appType`, `appInt`, `appLanguage`, `appInfMouse` | app identity / misc | probably read-only |

Also present but **not settings**: `appConfig`, `appSharedConfig` — the opaque registry
blobs holding serialised settings (§1.6).

**GUI controls in `appbasics/appsettings` with no key in the table and no obvious binary
key** — all [OPEN]:

| GUI control | Why it matters here | Binary candidates found |
|---|---|---|
| **GPUs to use** ("If your computer has multiple GPUs, you can select which one to use here") | This repo pins GPUs with `CUDA_VISIBLE_DEVICES` (from `RS_GPU_DEVICES`) instead, because no `-set` key was found | `appBtnGPUs`, `gpuId`, `gpuUn` — none confirmed as a `-set` key |
| **Max triangles to display (Max GPU memory)** — 20% / 40% (default) / 80% of VRAM | render only | `mvsMaxTrianglesToDisplay` |
| **Use relative image paths** — saves `.rsproj` input paths relative | would matter for project portability | none found |
| **Prefer Exif over XMP** — "Exif metadata takes priority over XMP metadata if this setting is enabled" | **directly load-bearing for this pipeline**, which drives calibration and pose entirely through XMP sidecars | none found |
| Screen Grabber block (output folder, prefix, fps, resolution, bit rate, audio) | irrelevant headless | none extracted |
| Control-point editor brightness enhancement block | GUI-only | none extracted |
| Real-time assistance / Epic Games account blocks | GUI-only | none extracted |

---

## 4. `sfm*` — alignment / registration

GUI home: **ALIGNMENT tab → Registration → Settings**.
[OFFICIAL: appbasics/alignsettings, tutorials/setkeyvaluetable]

Production values below are from `RS_CLI/Metadata/AlignmentParams.xml`, which
`AlignZone.bat`, `AlignImagesFromFolder.bat`, `GrowZone.bat`, `ProbeLockAlign.bat`,
`ProbeSubsetAlign.bat` and `ProbeSubsetAlign2.bat` replay row-by-row through `-set`
(filter: key must start with `sfm` or `lis`).

### 4.1 Documented keys (29)

| Key | Type | Default | Allowed values | GUI label / what it controls | Value pinned here |
|---|---|---|---|---|---|
| `sfmFeatureDetectionQuality` | enum | `High` | `High` `Normal` | **Feature detection quality** — High improves detection at the cost of time and RAM | `RealityScan.FeatureDetector.RSa1` — **not a documented value**, see §13.2 |
| `sfmMaxFeaturesPerMpx` | int | `10000` | positive int | **Max features per mpx** — "Using more features may slow processing but can result in less components" | `0x36b0` (14000) |
| `sfmMaxFeaturesPerImage` | int | `40000` | positive int | **Max features per image** | `0xc350` (50000) |
| `sfmImagesOverlap` | enum | `Medium` | `Low` `Medium` `High` | **Images' overlap** — breadth of the candidate-pair search. Epic: set Low below 20% overlap; >60% is best quality | `Medium` (raised from legacy `Low`); `High` is merge-ladder rung 3 and **that rung is judged not defensible**, see §10.4 |
| `sfmImageDownscaleFactor` | int | `1` | `1`,`2`,`4`,… | **Image downscale factor** before feature detection; 1 = full resolution | `1` |
| `sfmMaxFeatureReprojectionError` | float | `2.0` | Epic recommends ≤ `3` px | **Max feature reprojection error** — internal precision during alignment | `1.29999995` |
| `sfmEnableCameraPrior` | bool | `true` | `true` `false` | **Use camera priors for georeferencing** — Epic: "prior positions for the images are used in the alignment process and for georeferencing the scene". (This repo's settings evaluation restates that as "participate **inside** the bundle adjustment"; that stronger reading is repo prose, not Help text — [INFERRED]) | `true`, always |
| `sfmCameraPriorAccuracyX` | float | `10.0` | ≥ 0 | **Position X accuracy** — the range within which a solved position counts as equal to the prior | **never applied**, see §13.3 |
| `sfmCameraPriorAccuracyY` | float | `10.0` | ≥ 0 | **Position Y accuracy** | **never applied**, §13.3 |
| `sfmCameraPriorAccuracyZ` | float | `20.0` | ≥ 0 | **Position Z accuracy** | **never applied**, §13.3 |
| `sfmCameraPriorWeight` | float | `1.0` | ≥ 0 | **Position prior hardness** — higher pulls solved positions harder to the priors, and "may change the visual connections between cameras" | `10.0` |
| `sfmCameraPriorAccuracyYaw` | float | `10.0` | ≥ 0 | **Yaw accuracy** | `10.0` |
| `sfmCameraPriorAccuracyPitch` | float | `10.0` | ≥ 0 | **Pitch accuracy** | `10.0` |
| `sfmCameraPriorAccuracyRoll` | float | `10.0` | ≥ 0 | **Roll accuracy** | `10.0` |
| `sfmCameraPriorWeightOrientation` | float | `1.0` | ≥ 0 | **Orientation prior hardness** | `2.0` (was `10.0` until 2026-09-01) |
| `sfmControPointImageMeasAccuracy` *(Epic's typo: no `l` in "Control")* | float | `2.0` | ≥ 0 | **Image measurement accuracy [px]** for control points | `4.0` |
| `sfmControlPointXAccuracy` | float | `0.05` | ≥ 0 | **Control point position X accuracy** | **never applied**, §13.3 |
| `sfmControlPointYAccuracy` | float | `0.05` | ≥ 0 | **Control point position Y accuracy** | **never applied**, §13.3 |
| `sfmControlPointZAccuracy` | float | `0.10` | ≥ 0 | **Control point position Z accuracy** | **never applied**, §13.3 |
| `sfmDefinedDistanceAccuracy` | float | `0.10` | ≥ 0 | **Defined distance accuracy** (scale constraint) | **never applied**, §13.3 |
| `sfmImagesOverlapDraftMode` | enum | `Medium` | `Low` `Medium` `High` | **Draft → Image overlap** | `Medium` (draft path unused) |
| `sfmImageDownscaleFactorDraftMode` | integer | `2` | `1`,`2`,`4`,… | **Draft → Image downscale factor** | `2` |
| `sfmFinalModelOptimizationDraftMode` | bool | `false` | `true` `false` | **Draft → Final model optimization** (final bundle adjustment) | `false` |
| `sfmAutoReconRegionAfterAlignment` | bool | `true` | `true` `false` | **Advanced → Add a reconstruction region after alignment** | `false` — the merge/model stages set the region explicitly |
| `sfmForceComponentRematch` | bool | `false` | `true` `false` | **Advanced → Force component rematch** — "realigns images and cameras … uses existing camera poses to search for new matches" | `false` in pass-1 zone aligns; `true` on merge-ladder rungs 2–3 |
| `sfmPreselectorFeatures` | int | `10000` | positive int; Epic: "1/4–1/2 of the detected features" | **Advanced → Preselector features** | `0x4e20` (20000) |
| `sfmDetectorSensitivity` | enum | `Medium` | `Low` `Medium` `High` `Ultra` | **Advanced → Detector sensitivity** — Ultra detects more features in weak texture but "may also include less reliable points caused by image noise" | `Ultra` |
| `sfmMergeGeoreferencedComponents` | bool | `false` | `true` `false` | **Advanced → Merge georeferenced components** — "When multiple components are created and each is georeferenced, enabling this setting allows them to be merged even without visual overlap" | `false` in pass-1 zone aligns; `true` on every merge-ladder rung. **Never observed to work headless** — §12 and §13.4 |
| `sfmDistortionModel` | enum | `Brown3` | `Division` `Brown3` `Brown4` `Brown3WithTangential2` `Brown4WithTangential2` `KplusBrown3WithTangential2` `KplusBrown4WithTangential2` | **Advanced → Distortion model** | `Division` in the current `AlignmentParams.xml`; `Brown3` is the documented target for a rectilinear rig. **The key is global and all-or-nothing** — §13.5 |

[OFFICIAL: tutorials/setkeyvaluetable] for every key/type/default/enum;
[OFFICIAL: appbasics/alignsettings] for the prose; [VERIFIED-by-inspection:
`RS_CLI/Metadata/AlignmentParams.xml`, 35 entries: 27 `sfm*`, 1 `lis*`, 7 `s<NNN>l`] for
every pinned value.

**The params file's own comment on `sfmDistortionModel` is stale.** `AlignmentParams.xml`
carries, inline above the entry, "Global fallback only: mixed rig, so the real distortion
model is per-camera via XMP sidecars (fisheye Port/Starboard: division; rectilinear
Cinema/Zeuss: brown3)." That premise was **refuted** on 2026-07-26 — the global key owns
the model outright and the per-image XMP hint does not switch it (§13.5). Read the comment
as history, not as behaviour. [VERIFIED: FINDINGS 2026-07-26 vs the file's own comment]

### 4.2 Distortion-model semantics

| Value | Model | When to use |
|---|---|---|
| `Division` | single-parameter division model | "reliably covers simple distortions but works very well also for fish-eyes optics (for example GoPro)" |
| `Brown3` | polynomial radial, 3 coefficients | the default; "works for optics with less than 180°" |
| `Brown4` | polynomial radial, 4 coefficients | different distortion in the middle vs the borders |
| `Brown3WithTangential2` / `Brown4WithTangential2` | + 2 tangential coefficients | compensates lens offset; "majority of current optics has negligibly small tangential distortion" |
| `KplusBrown3WithTangential2` / `KplusBrown4WithTangential2` | + optimises **Skew and Aspect ratio** | without `K+`, RealityScan assumes skew 0 and aspect 1 |

[OFFICIAL: appbasics/settings_distortion_models]

The Help states the ≥180° constraint only **negatively**, on `Brown3` ("works for optics
with less than 180°"), and never says Division is the only ≥180°-capable model. That
`Division` is the sole option for ≥180° optics is a reading of the list, not a Help claim.
[INFERRED — settled by asking Epic, or by an A/B of Division vs Brown4 on the 14 mm
fisheye]

Epic's own recommended workflow — "starting with a simpler Division model first, and later
change it to Brown and click Align Images (F6) to optimize data" — is quoted approvingly in
this repo's settings evaluation §3. [OFFICIAL: same topic]
[VERIFIED-by-inspection: docs/settings-evaluation-2026-07 §3]

**Measured, Division vs Brown3, on underwater imagery through a dome port:**

| Cell | Dataset | Result |
|---|---|---|
| PD-1 | Z3, 124 images | Division registered **112/124** vs the baseline's 102, and **both** cameras solved division — the rectilinear camera did not degrade |
| PD-6 | Z1, 4,540 images, loose priors, intact sidecars | Division: **4,394/4,540 in TWO components, hull scale 0.981**. Brown3 baseline: 4,405 in THREE components, hull scale 0.175 |

[VERIFIED: PD-1, PD-6, 2026-07-25/26]

**Caveat, do not over-attribute:** PD-6 differs from the fresh-run baseline in **three**
ways — (a) Brown3→Division, (b) the accuracy columns being imported for the first time,
(c) orientation priors removed (its cell used a 7-column position-only flight-log format).
The scale repair cannot be attributed to Division alone. The isolating cell (Brown3 +
explicit-loose priors on zone_1, ~70 min) was never run; the corrected configuration was
adopted anyway. [VERIFIED-as-caveat: FINDINGS 2026-07-26] [OPEN]

### 4.3 `sfm*` keys in the binary or the GUI-exported XML with no Help coverage

| Key | Type (observed) | Value pinned here | GUI control | Source |
|---|---|---|---|---|
| `sfmGPUAcceleration` | bool | `true` | Advanced → **GPU acceleration** | [UNDOCUMENTED: GUI-exported `AlignmentParams.xml` + binary strings]. This is the key behind "RealityScan uses every CUDA GPU by default" |
| `sfmBackgroundDetectFeatures` | bool | `false` | Advanced → **Background feature detection** | [UNDOCUMENTED: same]. Pinned off — no idle-time detection on a batch box |
| `sfmBackgroundDetectThreadPriority` | enum | `Low` | Advanced → **Background thread priority** (`Low` \| `Normal` per the alignsettings prose) | [UNDOCUMENTED: same]. Inert while the above is `false` |
| `sfmEnableAutoSuggestions` | bool | `true` | Advanced → **Enable measurement suggestions** | [UNDOCUMENTED: same]. GUI-only effect |
| `sfmCameraDepthmapWeight` | float | `0.05` | no GUI control identified | [UNDOCUMENTED: same]. **Effect unknown** [OPEN] |
| `sfmFinalModelOptimization` | bool | — | the **non-draft** counterpart of `sfmFinalModelOptimizationDraftMode`; the Help documents only the draft variant | [UNDOCUMENTED: binary] |
| `sfmAlgorithm` | ? | — | — | [UNDOCUMENTED: binary] |
| `sfmMergeComponenetsOnly` *(sic)* | bool? | — | plausibly the engine flag behind `-mergeComponents` ("no new images are added") | [UNDOCUMENTED: binary] [INFERRED from the name] |
| `sfmSBPTRemoveCameras` | ? | — | — | [UNDOCUMENTED: binary] |
| `sfmGeoRef`, `sfmMetric`, `sfmVisible`, `sfmFinalOpt` | ? | — | short forms, probably report/UI variables rather than `-set` keys | [UNDOCUMENTED: binary] [INFERRED] |

### 4.4 The `s<NNN>l` exporter ids

The GUI settings exporter writes some alignment-panel controls under auto-generated ids
instead of their documented key names. `AlignmentParams.xml` carries seven:

| Id | Value in the repo file | Slot it occupies | RealityScan default for that slot |
|---|---|---|---|
| `s235l` | `5.0` | camera prior **X** accuracy | `10.0` |
| `s236l` | `5.0` | camera prior **Y** accuracy | `10.0` |
| `s237l` | `0.5` | camera prior **Z** accuracy | `20.0` |
| `s251l` | `0.05` | control point **X** accuracy | `0.05` |
| `s252l` | `0.05` | control point **Y** accuracy | `0.05` |
| `s253l` | `0.1` | control point **Z** accuracy | `0.10` |
| `s254l` | `0.001` | defined distance accuracy | `0.10` |

[UNDOCUMENTED: no Help coverage; known only from the exported XML and binary strings]
[INFERRED: the slot mapping, from slot order and default magnitudes]

Because every repo workflow filters the replay to keys beginning `sfm`/`lis`, **these
seven rows are silently dropped and the intended accuracies have never been applied in
production**. Full analysis in §13.3.

Cheapest probe to settle the mapping: `-set "sfmCameraPriorAccuracyZ=99"`, re-export the
Alignment Settings panel from the GUI, and read which entry became `99`.

---

## 5. `lis*` — LiDAR / laser-scan import

| Key | Type | Default | Allowed values | GUI label / what it controls | Pinned here |
|---|---|---|---|---|---|
| `lisPreferImagesAsFeatureSource` | bool | `true` | `true` `false` | **Prefer images as feature source during import of Z+F scans** (ALIGNMENT → Settings → Advanced). Epic: "Set to Yes to import .zfprj mosaic images and use them as feature source during the alignment process… Applies only for the Z+F scans" | `false` — no LiDAR in this pipeline; pinned explicitly rather than left to the default |

[OFFICIAL: tutorials/setkeyvaluetable, appbasics/alignsettings]

This is the **only** `lis*` key in the Help and the only one found in the 2.2 binary. The
rest of the LiDAR import surface is params-XML only, through
`-importLaserScan <name> <params.xml>` and `-importLaserScanFolder <folder> <params.xml>`.
[OFFICIAL: appbasics/allcommands]

Repo status: declared a low-priority probe (wave-3 cell E3) and **never executed**.
[OPEN]

---

## 6. `mvs*` / `Mvs*` — reconstruction, depth maps, meshing

GUI home: **MESH & COLOR tab → Create Mesh → Settings**.
[OFFICIAL: appbasics/modelsettings, tutorials/setkeyvaluetable]

**None of these are set by this repo.** `GenerateModel.bat` runs `-calculateHighModel` and
the model tools on whatever the instance's current values are. That is a standing gap, not
a decision. [VERIFIED-by-code-reading: `RS_CLI/Scripts/GenerateModel.bat`]

### 6.1 Documented keys (22 + `PrecomputeDepthmaps`)

| Key | Type | Default | Allowed values | GUI label / what it controls |
|---|---|---|---|---|
| `mvsPreviewDownscaleFactor` | int | `4` | `1`,`2`,`4`,… | **Image depth map calculation → Preview model → Image downscale**. 2 means each side halved = 25% of the pixels |
| `mvsNormalDownscaleFactor` | int | `2` | `1`,`2`,`4`,… | **… → Normal model → Image downscale**. High Detail always uses 1 and has no such option |
| `mvsMinSampleDistanceLaserScan` | float | `0.002` | ≥ 0 | **LiDAR scans → Minimal distance between two points** |
| `mvsMaxSampleDistanceLaserScan` | float | `150.0` | ≥ 0 | **LiDAR scans → Point-cloud cropping radius** from the scanner |
| `mvsMinIntensityLaserScan` | float | `0.03` | ≥ 0 | **LiDAR scans → Minimal intensity** |
| `MvsGeometryGpuAccel` | bool | `true` | `true` `false` | **Mesh calculation → GPU acceleration** |
| `MvsGeometryMarginStyle` | bool | `false` | `true` `false` | **Mesh calculation → Remove marginal triangles** (produces a non-watertight mesh) |
| `mvsMinSampleDistance` | float | `0.0` | ≥ 0, in project CRS units | **Mesh calculation → Minimal distance between two vertices** = final model density. Epic warns: use only when the scale is known; on a georeferenced scene the number is metres/feet |
| `mvsPreviewMeshStrategy` | enum | `sfm` | `sfm` (use sparse point cloud) · `vertexCount` (max vertex count) | **Mesh calculation → Preview model → Mesh Calculation Strategy** (`setkeyvaluetable` prints the label as "Mesh calculaton strategy" *(sic)*). With `sfm`, the Preview Image-downscale and Max-vertex-count controls become irrelevant and are hidden |
| `mvsPreviewMaxVetrexCountInModel` *(sic: "Vetrex")* | int | `10000000` | positive int | **Preview → Max vertex count**; relevant only when `mvsPreviewMeshStrategy=vertexCount` |
| `mvsMaxVertexCountInPart` | int | `5000000` | positive int | **Advanced → Maximal vertex count per part.** Epic: "We do not recommend changing this value" |
| `mvsDecimationFactor` | float | `1.0` | > 0 | **Advanced → Detail decimation factor.** Bigger = lower detail, fewer triangles |
| `MvsDepthMapsLibVersion` | enum | `1` | `0` Version 1 (legacy) · `1` Version 2 | **Advanced → Depth map algorithm version** |
| `mvsAdaptiveBlendingStart` | float | `0.45` | 0..1 | **Advanced → Adaptive blending start.** Higher = greater detail. Epic: "not recommended to use a non-default value (0.45)" |
| `mvsSmoothingWeight` | float | `1.5` | ≥ 0 | **Advanced → Smoothing.** Higher = smoother |
| `mvsDefaultGroupingFactor` | float | `1.0` | > 0 | **Advanced → Photogrammetry → Default grouping factor** (vertex density; 2 → ~4× fewer vertices). Raising it also **prioritises laser scans over images** in mixed meshing |
| `mvsLowTextureGroupingFactor` | float | `0.25` | > 0 | **… → Low texture grouping factor** |
| `mvsDefaultNoiseFactor` | float | `1.0` | > 0 | **… → Default noise factor** (mesh smoothness) |
| `mvsLowTextureNoiseFactor` | float | `2.0` | > 0 | **… → Low texture noise factor** |
| `mvsFilteringRadius` | float | `3.0` | > 0 | **Advanced → Mesh filtration → Filter radius** (depth-map stage). Epic: "should not be modified" |
| `mvsFilteringStrength` | int | `2` | int | **Advanced → Mesh filtration → Filter strength.** Epic: "should not be modified" |
| `mvsImportMaxTrianglesPerPart` | int | `100000000` | positive int | **Advanced → Model import → Maximal vertices' count per part** for imported models |
| `PrecomputeDepthmaps` | bool | `false` | `true` `false` | **Not in the key table.** When `true`, `-calculatePreviewModel` / `-calculateNormalModel` / `-calculateHighModel` only compute depth maps into the cache and build **no model**; when `false`, already-cached depth maps are reused and only the meshing runs. **Must be reset to `false` afterwards.** [OFFICIAL: tutorials/commandline_2] |

[OFFICIAL: tutorials/setkeyvaluetable] for the 22; [OFFICIAL: appbasics/modelsettings] for
the prose; [OFFICIAL: tutorials/commandline_2] for `PrecomputeDepthmaps`.

`PrecomputeDepthmaps` is the documented mechanism for splitting GPU depth-map work from
CPU meshing across two machines (align + precompute on the GPU box, move project and
cache, `-importCache` + mesh on the CPU box). Epic advises against sharing a cache over a
network drive; copy between local SSDs. [OFFICIAL: tutorials/commandline_2]

**Empirical note.** `MvsGeometryMarginStyle` is left at `false` here and marginal
triangles are removed **post hoc** with `-selectMarginalTriangles` +
`-removeSelectedTriangles`, which keeps the removal an inspectable, orderable step in
`GenerateModel.bat` rather than a mesh-time side effect.
[VERIFIED: docs/settings-evaluation-2026-07 §7]

**GUI control with no documented key:** *Maximal depth-map pixel count* (Preview and
Normal), described in `appbasics/modelsettings` (default `0` = ignored; does not override
Image downscale — both apply) but absent from `setkeyvaluetable`. Binary candidates:
`MvsPreviewUndistMaxPixels`, `MvsNormalUndistMaxPixels`. [INFERRED] — settle by changing
the GUI field and diffing an exported `.rcconfig`. [OPEN]

Another documented GUI control with no key: **LiDAR → Filtering based on classification**
(which LiDAR classes are included in mesh creation). [OPEN]

### 6.2 Reconstruction-adjacent `Mvs*` / `mvs*` strings in the binary

All [UNDOCUMENTED: binary string extraction]; none used here; none confirmed as `-set`
keys. Grouped by what the names plainly govern.

**Quality levels and depth maps** — `MvsPreviewQualityLevel`, `MvsNormalQualityLevel`,
`MvsHighQualityLevel`, `MvsDepthMapQualityPreview`, `MvsDepthMapQualityNormal`,
`MvsDepthMapQualityHigh`, `MvsDepthMapAlgorithm`, `MvsDepthMapLayerProcessingType`,
`MvsPreviewUndistMaxPixels`, `MvsNormalUndistMaxPixels`, `MvsPreviewDownscaleFactor`,
`MvsPreviewDecimationFactor`, `mvsRefineDepthMapsHigh`, `mvsFilterModelCachedDepthMap`,
`mvsShowDepthMapLayer`, `mvs_estimateDepthmapScale`, `mvsComputeDepthMapNomal` *(sic)*,
`mvsComputeDepthMapHigh`.

**Geometry engine (capitalised twins of the documented keys)** —
`MvsGeometryMinimalSampleDistance`, `MvsGeometryFilteringRadius`,
`MvsGeometryFilteringStrength`, `MvsGeometryDetailMode`,
`MvsGeometryDetailAdaptationStart`, `MvsGeometryDetailAdaptationScale`,
`MvsGeomterySmoothingWeight` *(sic)*, `MvsGeomterySmoothingDiscontinuity` *(sic)*,
`MvsGeometryPhotoDepthmapQuality`, `MvsGeometryPhotoDepthmapNoise`,
`MvsGeometryGroupingFactorOfLowTexturedAreas`, `MvsGeometryNoiseFactorOfLowTexturedAreas`,
`MvsGeometryLaserScanMinSamplingDistance`, `MvsGeometryLaserScanMaxSampleDistance`,
`MvsGeometryLaserScanMinIntenity` *(sic)*, `MvsGeometryIntermediateResultsPath`,
`MvsDecimationFactor`, `MvsLargeScaleDecimationFactor`,
`MvsLargeScalePointsCountInCluster`, `MvsLimitedScaleDecimationFactor`,
`MvsLimitedScaleMaxVertexCount`, `mvsMergedDownscaleCutoff`, `mvsSpaceSigma`,
`MvsImageSmoothing`, `MvsVisibilityRegionRange`, `mvsGPUAcceleration`.

**Continue / cache / texture state** — `mvsContinueCalculation`, `mvsCloneAndTexture`,
`mvsDeleteIntermediateTextures`, `mvsRemoveTextures`, `mvsPreferOldRasterizer`,
`mvsNormalizeImages`, `mvsExtractCpPatch`.

**Rendering caps** (render-side twins of `appMaxPointsToDisplay`) —
`mvsMaxPointsToDisplay`, `mvsMaxTrianglesToDisplay`.

**Reconstruction region (`mvsRR_*`)** — `mvsRR_PosX/Y/Z`, `mvsRR_PosLat`, `mvsRR_PosLon`,
`mvsRR_RotX/Y/Z`, `mvsRR_ScaleX/Y/Z`, `mvsRR_OffsetX/Y/Z`, `mvsRR_OffsetBtn`,
`mvsRR_UseRelativeVals`, `mvsRR_COORD`, `mvsRR_COORDInput`, `mvsRR_COORDType`,
`mvsRR_COORDUnits`, `mvsRR_COORDProjection`, `mvsRR_COORDPrimeMeridian`, `mvsRR_COORDWkt`,
`mvsRR_COORDWktCheckProj`, `mvsRR_displayCoordSystem`.
The region is normally driven by dedicated commands
(`-setReconstructionRegionAuto`, `-setReconstructionRegion box.rsbox`,
`-scaleReconstructionRegion`, `-moveReconstructionRegion`, `-rotateReconstructionRegion`,
`-offsetReconstructionRegion`, `-exportReconstructionRegion`), not by these keys.
[OFFICIAL: tutorials/commandline_2]

**Post-processing internals (`mvsPpt*`, 38 strings)** — `mvsPptClean`, `mvsPptCloseHoles`,
`mvsPptColorizeGridBoundary`, `mvsPptColorizeModelByTexelSize`,
`mvsPptCreatePartExternalTriangles`, `mvsPptDecomposeModel`, `mvsPptduplicate`,
`mvsPptGenerateDtm`, `mvsPptGenerateDtmAncestorRatio`, `mvsPptGenerateDtmChildRatio`,
`mvsPptGenerateDtmDoGrid`, `mvsPptGenerateDtmGridSize`, `mvsPptGenerateDtmMaxArea`,
`mvsPptGenerateDtmMinArea`, `mvsPptHardCrash`, `mvsPptIIUClusters`,
`mvsPptInflateFraction`, `mvsPptInspectTopology`, `mvsPptMaxTrisPerPart`,
`mvsPptMergeSiblingParts`, `mvsPptOrthoColorFromMosaicing`, `mvsPptOrthoDilateColor`,
`mvsPptOrthoDilateDepth`, `mvsPptOrthoErodeColor`, `mvsPptOrthoErodeDepth`,
`mvsPptOrthoPushPullColorSource`, `mvsPptOrthoPushPullColorTiled`,
`mvsPptOrthoPushPullDepthSource`, `mvsPptOrthoPushPullDepthTiled`,
`mvsPptPartExtenderAllCriteria`, `mvsPptSpreadDistance`, `mvsPptSpreadFactor`,
`mvsPptTargetTrisCount`, `mvsPptTexelSize`, `mvsPptTopologicalDistance`, `mvsPptTrisMos`,
`mvsPptUndercut`, `mvsPptUnwrapCheck`, `mvsPptVetMos`, `mvsPptVetVis`.

`mvsPptInspectTopology` is notable: this repo established that **Check Integrity / Check
Topology have no CLI commands** (their fix action maps to `-cleanModel` + `-closeHoles`),
yet a settings-level string exists. [VERIFIED: mapping exercise, 2026-07-23]
[UNDOCUMENTED: the string] [OPEN]

---

## 7. `unwrap*`, `txt*`, `col*`, `ImageLayerFor*` — unwrap, coloring, texturing

GUI home: **MESH & COLOR tab → Color & Texture → Settings**.
[OFFICIAL: appbasics/modelsettings "Coloring and Texturing", tutorials/setkeyvaluetable]

This repo sets none of these globally; it passes the equivalent values as params XML to
`-unwrap` and `-calculateTexture` (see §8.1 and `09-xml-parameter-files.md`).

### 7.1 Documented keys (24)

| Key | Type | Default | Allowed values | GUI label / what it controls | Repo params-XML values |
|---|---|---|---|---|---|
| `unwrapGutter` | int | `2` | positive int | **Default unwrap parameters → Gutter** (texel padding) | `2` in the MaxTexturesCount presets, `10` in the FixedTexelSize presets |
| `unwrapMinTexResolution` | enum | `512` | `512` `1024` `2048` `4096` `8192` `16384` | **Minimal texture resolution** | `512` in `Unwrapping_Simplified*.xml` |
| `unwrapMaxTexResolution` | enum | `8192` | `512` `1024` `2048` `4096` `8192` `16384` | **Maximal texture resolution** | `8192` or `16384` per preset |
| `unwrapLargeTriangleRemovalThr` | int | `10` | positive int | **Large triangle removal threshold** | `10` / `400` / `1000` per preset |
| `unwrapStyle` | enum | `MaxTexturesCount` | `MaxTexturesCount` `FixedTexelSize` `AdaptiveTexelSize` (row order; ordinals accepted but the mapping is **not** established — see §1.4) | **Style** — Epic's own example uses an ordinal: `-set "unwrapStyle=1"` | `MaxTexturesCount` or `FixedTexelSize` (name form, in every repo preset) |
| `unwrapMaximalTexCount` | int | `1` | positive int | **Maximal textures' count**; relevant when `unwrapStyle=MaxTexturesCount` | `1`, `2` or `4` per preset |
| `unwrapFixedTexelSizeType` | enum | `0` | `0` Optimal · `1` 2× optimal (50% quality) · `2` 4× (25%) · `3` 10× (10%) · `4` 100× (1%) · `5` Custom | **Texel size**; relevant when `unwrapStyle=FixedTexelSize` | `0` or `1` |
| `unwrapFixedTexelSize` | float | `0.01` | > 0 | **Custom texel size**; relevant when `unwrapFixedTexelSizeType=5` | not used |
| `unwrapMinTexelSize` | enum `0`..`5` **and** float | `0` / `0.01` | see §13.6 | **Minimal required texel size** and **Custom minimal required texel size** — the Help gives one key name for two different controls | not used |
| `unwrapMaxTexelSize` | enum `0`..`5` **and** float | `4` / `10` | see §13.6 | **Maximal required texel size** and **Custom maximal required texel size** — same defect | not used |
| `txtImportDefaultTexResolution` | enum | `8192` | `512` `1024` `2048` `4096` `8192` `16384` | **Imported model default texture resolution** | not used |
| `txtMethod` | enum | `MultiBand` | `Linear` `MultiBand` | **Coloring method** | not used |
| `colStyle` | enum | `VisibilityBased` | `PhotoConsistencyBased` `VisibilityBased` | **Coloring style** | not used |
| `ImageLayerForColoring` | string | `geometry` if no texturing layer is present, else `texture01` | `geometry/<geometry_layer>` · `texture01/<texture_layer>` · `texture2/<texture_layer2>` | **Coloring image layer** | not used |
| `txtStyle` | enum | `VisibilityBased` | `PhotoConsistencyBased` `VisibilityBased` `MosaicingBased` `MaximalIntensity` `MinimalIntensity` `AverageIntensity` | **Texturing style** | not used |
| `ImageLayerForTexturing` | string | `all` | `geometry/<geometry_layer>` · `texture01/<texture_layer>` · `texture2/<texture_layer2>` · `all` | **Texturing image layer** | not used |
| `txtImageDownscaleTexture` | int | `1` | `1`,`2`,`4`,… | **Downscale images before texturing** | not used |
| `txtImageDownscaleColor` | int | `2` | `1`,`2`,`4`,… | **Downscale images before coloring** | not used |
| `txtFillInUncoloredParts` | bool | `true` | `true` `false` | **Fill in uncolored parts** | not used |
| `txtFillInUntextoredParts` *(Epic's typo: "Untextored")* | bool | `true` | `true` `false` | **Fill in untextured parts** | not used — and see §13.7 |
| `txtRecolorAfterTexturing` | bool | `true` | `true` `false` | **Recolor model after texturing** | not used |
| `MvsDoCorrectColors` | bool | `false` | `true` `false` | **Correct colors** | not used |
| `MvsIgnoreCorrectColors` | bool | `false` | `true` `false` | **Ignore color correction** | not used |
| `MvsGeometryTexturingDoHdr` | bool | `true` | `true` `false` | **Prefer 16-bit/HDR texture generation** | not used |

[OFFICIAL: tutorials/setkeyvaluetable] throughout; [VERIFIED-by-inspection:
`RS_CLI/Metadata/Texturing_*.xml` and `Unwrapping_*.xml`] for the repo values.

`ImageLayerForColoring` / `ImageLayerForTexturing` are the CLI face of RealityScan **Image
Layers** (`.geometry` / `.texture` / `.mask`). Image Layers is the agreed eventual
mechanism for "align on originals, texture from enhanced imagery" in this pipeline but has
**never been exercised through this CLI**. [VERIFIED-as-decision: HANDOFF 2026-07-26]
[OPEN]

### 7.2 `unwrap*` / texturing strings in the binary or repo XML with no Help coverage

| Key | Observed values | Meaning | Source |
|---|---|---|---|
| `unwrapMinTexelSizeType` | — | the **enum selector** (0..5) for minimal required texel size — the key the Help table should have named, see §13.6 | [UNDOCUMENTED: binary] |
| `unwrapMaxTexelSizeType` | — | same for maximal required texel size | [UNDOCUMENTED: binary] |
| `unwrapMethod` | `Geometric` | unwrap method | [UNDOCUMENTED: `Unwrapping_Simplified*.xml` + binary] |
| `unwrapFillTextures` | `0x0`, `0x1` | fill textures (checkerboard fill flag) | [UNDOCUMENTED: repo XML + binary] |
| `unwrapButtonDisabled` | `0` | exported UI state; carries no effect as a setting | [UNDOCUMENTED: repo XML + binary] [INFERRED from the name] |
| `unwrapCheckerBoardCellCount` | — | checkerboard cell count | [UNDOCUMENTED: binary] |
| `unwrapFillTexWithCheckerboard`, `unwrapFillTexWithCheckerboardYesNo` | — | checkerboard fill toggles | [UNDOCUMENTED: binary] |
| `unwrapOptimalTexelSize`, `unwrapCsUnitsLongName`, `unwrapCalc`, `unwrapFChecks` | — | derived / read-back values | [UNDOCUMENTED: binary] |
| `unwrapUseLegacyAlgorithm`, `unwrapUseLegacyUnwrapAlgorithm`, `unwrapUseLegacySimplifyAlgorithm` | — | legacy-algorithm switches | [UNDOCUMENTED: binary] |
| `unwrap_fill_with_charts`, `unwrap_grid_size_cells` | — | snake_case ⇒ report/telemetry variables, not settings | [UNDOCUMENTED: binary] [INFERRED from naming convention] |
| `MvsColoringStyle`, `MvsTexturingStyle`, `MvsColoringTexturingType`, `MvsImageLayerForColoring`, `MvsImageLayerForTexturing`, `MvsColorReference`, `MvsDoColorNormalization` | — | capitalised engine twins of `colStyle` / `txtStyle` / `ImageLayerFor*` | [UNDOCUMENTED: binary] |
| `MvsGeometryColoringDoFillIn`, `MvsGeometryColoringImagesDownScale`, `MvsGeometryTexturingDoFillIn`, `MvsGeometryTexturingDoRecolor`, `MvsGeometryTexturingPhotoconsistencyBias` | — | engine twins of the `txt*` fill/recolor/downscale keys | [UNDOCUMENTED: binary] |
| `mvsTextureResolution`, `mvsTexture`, `mvsTexture2`, `mvsCNCurrentTexture`, `mvsColorize`, `mvsColorizePreview` | — | texture / colorize state | [UNDOCUMENTED: binary] |
| `txtCount` | — | texture-count read-back | [UNDOCUMENTED: binary] |
| `txtFillInUntexturedParts` (correctly spelled) | — | present in the binary **alongside** the typo'd `txtFillInUntextoredParts`; which one is live is [OPEN] | [UNDOCUMENTED: binary] |

`unwrapCheckerBoardCellSize`, present with value `64` in **six** of the eight repo
`Texturing_*.xml` presets (`HighPolyTexture`, `MaxTextureCount1_8k`, `MaxTextureCount1_16k`,
`MaxTextureCount4_8k`, `MaxTextureCount4_16k`, `SimplifiedTexture` — the two
`FixedTexelSize*` presets omit it), is **inert** — see §12.
[VERIFIED-by-inspection: `RS_CLI/Metadata/Texturing_*.xml`]

---

## 8. Tool parameter-XML key families

These are the key spaces of `params.xml` files consumed by specific commands. Every one is
[UNDOCUMENTED] by the Help's key table; the *commands* that consume them are documented in
`appbasics/allcommands`. **Whether `-set` also accepts them is [OPEN] for all of them.**
File authoring is covered in `09-xml-parameter-files.md`.

Two source classes are distinguished below: **shipped** = present in an Epic-authored file
under `C:\Program Files\Epic Games\RealityScan_2.2\Settings\SimplifiedExport\`; **exported**
= present in a GUI-exported file under `RS_CLI/Metadata/`.

### 8.1 `mvsFlt*` / `simpl*` — `-simplify <params.xml>`

Shipped: `Settings\SimplifiedExport\simplify.xml` (Configuration id
`{033AEF62-8421-47A4-81CB-203741113577}`).
Exported: `Simplify500k_Params.xml`, `Simplify25per_Params.xml`, `Simplify50Per_Params.xml`,
`SimplifyNoise_Params.xml`, `SimplifySmooth_80per_Params.xml`, `SimplifyAutomationParams.xml`.

| Key | Type | Observed values | Meaning | Source |
|---|---|---|---|---|
| `mvsFltSimplificationType` | enum int | `0` (absolute), `1` (relative %), `3` (Epic's shipped preset) | which target the simplifier honours | shipped + exported — repo files pair `0` with `…TargetTrisCountAbs` and `1` with `…Rel` |
| `mvsFltTargetTrisCountAbs` | int | `500000`, `1000000` | absolute target triangle count | shipped + exported |
| `mvsFltTargetTrisCountRel` | int (percent) | `10`, `50`, `70`, `80` | relative target as a percentage | shipped + exported |
| `mvsFltMinEdgeLength` | float | `0.0` | minimum edge-length floor | shipped + exported |
| `mvsFltBorderDecimationStyle` | enum int | `1` | how borders are decimated | shipped + exported |
| `mvsFltReprojectColor` | bool | `false` | reproject vertex colors onto the simplified mesh | shipped + exported |
| `mvsFltReprojectNormal` | int | `0` | reproject normals | shipped + exported |
| `mvsFltUnwrapTexCount` | int | `0` | unwrap texture count for the result | shipped + exported |
| `mvsFltUnwrapTexSide` | int | `0` | unwrap texture side length | shipped + exported |
| `simplPreserveParts` | enum int | `0` (Epic shipped), `2` (repo) | preserve model parts through simplification | shipped + exported |
| `simplEqualizeDensity` | bool | `true` | equalize vertex density | **exported only** — absent from Epic's shipped `simplify.xml` |

Which repo preset carries which target, verbatim:

| File | `mvsFltSimplificationType` | Target key + value |
|---|---|---|
| `Simplify500k_Params.xml` | `0` | `mvsFltTargetTrisCountAbs` = `500000` |
| `Simplify25per_Params.xml` | `0` | `mvsFltTargetTrisCountAbs` = `500000` — **see defect below** |
| `Simplify50Per_Params.xml` | `1` | `mvsFltTargetTrisCountRel` = `50` |
| `SimplifyNoise_Params.xml` | `1` | `mvsFltTargetTrisCountRel` = `70` |
| `SimplifyAutomationParams.xml` | `1` | `mvsFltTargetTrisCountRel` = `70` |
| `SimplifySmooth_80per_Params.xml` | `1` | `mvsFltTargetTrisCountRel` = `80` |
| Epic `simplify.xml` | `3` | both `…Abs` = `1000000` and `…Rel` = `10` present |

**Repo defect: `Simplify25per_Params.xml` does not simplify to 25%.** Its content is
identical to `Simplify500k_Params.xml` — type `0` (absolute) with a 500,000-triangle
target, and no `mvsFltTargetTrisCountRel` entry at all. Anything selecting it by name gets
an absolute half-million target regardless of input size.
[VERIFIED-by-inspection: both files, this session]

Note also that Epic's shipped preset uses `mvsFltSimplificationType=3`, a third value the
repo never uses and whose meaning is [OPEN]; the repo only ever pairs `0`↔`…Abs` and
`1`↔`…Rel`.

Binary-only siblings [UNDOCUMENTED]: `mvsFltTargetTrisCount`, `mvsFltEqualizeDensity`,
`mvsFltPreserveParts`, `mvsFltMinComponentSize`, `mvsFltAverageEdgeLength`,
`mvsFltAverageEdgeLengthThr`, `mvsFltMarkLargeTriangles`, `mvsFltMarkMarginalTriangles`,
`mvsFltMarkSmallTriangles`, `mvsFltOpCalculate`, `mvsFltOpEstimate`, `mvsFltProcessing`,
`mvsFltSimplify`, `mvsFltUnwrapMaxTexSideCustom`, `mvsFltUnwrapMinTexSideCustom`,
`mvsFltUnwrapTexCountCustom`, `simplTargetTrisCount`, `simplType`, `simplValueAbs`,
`simplValueRel`, `simplUseLegacyAlgorithm`, `simplifyChecked`, `simplifyEx`.

### 8.2 `smooth*` / `mvsFltSmoothing*` — `-smooth <params.xml>`

Shipped: `Settings\SimplifiedExport\smooth.xml` (id `{585E749B-DC69-4D8C-9114-FA8CBB6F88F3}`).
Exported: `Smoothing_02_2_Params.xml`, `SmoothingSurface_02_2_Params.xml`,
`SmoothingPeaks_05_5_Params.xml`.

| Key | Type | Observed values | Meaning | Source |
|---|---|---|---|---|
| `smoothIterations` | int | `2` (repo), `5` (repo peaks, Epic shipped) | number of smoothing iterations | shipped + exported |
| `smoothWeight` | float | `0.2`, `0.5` | smoothing weight per iteration | shipped + exported |
| `mvsFltSmoothingType` | enum int | `0` (repo), `1` (Epic shipped) | smoothing algorithm | shipped + exported |
| `mvsFltSmoothingStyle` | enum int | `1` (surface), `3` (peaks) | which features are smoothed | shipped + exported |
| `mvsSmoothing_useIntelligentSmoothing` | — | `0` | present in Epic's own shipped `smooth.xml` **and absent from the 2.2 binary — inert**, see §12 | [CONTRADICTED] |

Binary-only siblings: `mvsFltSmoothingWeight`, `mvsFltSmootingIters` *(sic)*, `mvsFltSmoth`
*(sic)*, `smoothFactor`. [UNDOCUMENTED]

### 8.3 `reprojectionTool_*` — `-reprojectTexture <src> <dst> <params.xml>`

Shipped: `Settings\SimplifiedExport\reprojectTexture.xml` (id
`{8F3517E3-5632-40FE-BD10-9967EA8F299F}`). Exported: `ReprojectionParams.xml`.

| Key | Type | Epic shipped | Repo | Meaning |
|---|---|---|---|---|
| `reprojectionTool_supersampling` | tri-state int | `-1` | `-1` | supersampling |
| `reprojectionTool_enableDisplacement` | bool | `false` | `false` | displacement reprojection |
| `reprojectionTool_allowColor` | bool | `false` | `true` | color reprojection permitted |
| `reprojectionTool_normal` | int | `1` | `2` | normal-map reprojection mode |
| `reprojectionTool_useCustomDistance` | bool/int | `0` | `0` | use a custom search distance |
| `reprojectionTool_enableColor` | tri-state int | — | `-1` | reproject the color layer |
| `reprojectionTool_sourceColorLayer` | string | — | `Color8_0` | which source color layer |
| `reprojectionTool_colorSampling` | int | — | `0` | color sampling mode |
| `reprojectionTool_customDistance` | float | — | — | the custom distance value [UNDOCUMENTED: binary] |
| `reprojectionTool_sourceModel`, `reprojectionTool_resultModel`, `reprojectionTool_reprojectModelBtn` | string / UI | — | — | dialog fields [UNDOCUMENTED: binary] |

**Empirical limit:** `reprojectionTool_colorSampling` and `_supersampling` affect sampling
quality, **not unseen-area synthesis** — reprojection samples the source surface and cannot
invent color for surface no camera ever saw. This is why the production recipe textures
*after* `-closeHoles` + `-cleanModel` (so `-calculateTexture` projects from the source
images with multi-band blending) rather than texturing a holey model and reprojecting onto
the filled one. [VERIFIED: docs/settings-evaluation-2026-07 §7]

### 8.4 `xmp*` — `-exportXMP <params.xml>`

Exported: `RS_CLI/Metadata/XMPExportParams.xml` (id `{EC40D990-B2AF-42A4-9637-1208A0FD1322}`).

| Key | Type | Repo value | Meaning |
|---|---|---|---|
| `xmpCamera` | int | `3` | which camera-parameter set is written |
| `xmpRig` | bool | `true` | write rig relations |
| `xmpMerge` | bool | `true` | merge into existing sidecars rather than overwrite |
| `xmpExGps` | bool | `true` | export GPS |
| `xmpFlags` | bool | `true` | export per-image flags |
| `xmpCalibGroups` | bool | `true` | export calibration / lens group ids |
| `xmpPose`, `xmpCalib`, `xmpPrecision`, `xmpComponentMode`, `xmpEnabledOnly`, `xmpImageList`, `xmpPath`, `xmpalign` | — | — | further XMP-export dialog fields [UNDOCUMENTED: binary] |

All [UNDOCUMENTED: exported XML + binary].

Two hard constraints are independent of these keys and cannot be configured away:
RealityScan reads and writes `<stem>.xmp` **only** (`image.jpg.xmp` is ignored *silently*);
and export naming is determined by the **command**, not by these settings —
`-exportXMP` writes stem-named sidecars while `-exportXMPForSelectedComponent` writes
ordinal sidecars (`00000.xmp`, `00001.xmp`, …) in every observed context.
[VERIFIED: NA167 B7 "XMP sidecar conventions"; the ordinal-export behaviour is the
*second* B11-adjacent entry numbered B10 in `NA167_SESSION_NOTES.md` — that file reuses
B10 and B11 for both an INT- and an RS-series bug, so cite by title, not number —
observed NA156 smoke merge 2026-07-23]
Full treatment in `05-metadata-xmp-and-sidecars.md`.

### 8.5 Flight-log / trajectory import — `-importFlightLog` / `-importTrajectory <log> <params.xml>`

Exported: `RS_CLI/Metadata/FlightLogParams.xml` (id `{93DBD041-AE1C-4631-89BC-D9430FCED843}`),
generated per cruise by `modules/flight_logs.py::write_flight_log_params`.

| Key | Type | Repo value (NA173_H2103a) | Meaning |
|---|---|---|---|
| `gpsLogFileFormat` | GUID | `{B438A617-2434-5A24-C1B7-58980F28345A}` | selects a reader from `flightlogs.xml`. The reader ids are current product strings, e.g. `reader="RealityScan.Import.CSVFlightLog"` |
| `CoordinateSystemFlightLog` | PROJ string | `+proj=utm +zone=57 +south +datum=WGS84 +units=m +no_defs` | flight-log CRS |
| `CoordinateSystemFlightLogType` | string | `epsg:32757 - WGS 84 / UTM zone 57S` | human-readable CRS label |
| `ifCSopt` | int | `1` | coordinate-system option |
| `ifKGrp` | int | `2` | calibration-group mode on import |
| `ifuuInh` | int | `0` | accuracy-inheritance value |
| `ifuuInhEn` | bool | `true` | accuracy inheritance enabled |
| `csvFLSep` | int | `1` | CSV separator for the flight log |
| `csvFLIgn` | bool | `true` | ignore-rows flag for the flight log |
| `ifKmode` | — | `0x0` | **not present in the 2.2 binary — inert**, §12 |
| `ifUsePosAcc` | — | `true` | **not present in the 2.2 binary — inert**, §12 |
| `ifUseOriAcc` | — | `true` | **not present in the 2.2 binary — inert**, §12 |

All [UNDOCUMENTED: exported XML + binary].

`ifKGrp` and `ifKmode` are the only plausible carriers of the dialog's *Euler angles order
(YPR)* and *Camera mount* settings, and their value mapping is **undocumented anywhere**:
the Help documents the settings but not their config keys, `flightlogs.xml` defines only
column mapping, and neither key string appears in any file under the RealityScan install
— both are compiled into the binary. [UNDOCUMENTED: FINDINGS 2026-07-26] [OPEN]

**The live prior-accuracy family the params file does not use.** `ifUsePosAcc` and
`ifUseOriAcc` in `FlightLogParams.xml` are inert (they do not exist in the binary), but the
Import Trajectory dialog's accuracy block does have live keys — all present **both** in
`RealityScan.exe` 2.2.0.119430 and in this machine's persisted `appConfig` blob:

| Key | Plausible role |
|---|---|
| `ifuPosX`, `ifuPosY`, `ifuPosZ` | per-axis **position** prior accuracy applied at import |
| `ifuPosXl`, `ifuPosYl`, `ifuPosZl` | the label/units twins of the three above |
| `ifuRotY`, `ifuRotP`, `ifuRotR` | per-axis **orientation** (yaw/pitch/roll) prior accuracy |
| `ifuRotEnable` | enables the orientation-accuracy block — the plausible real counterpart of the inert `ifUseOriAcc` |
| `ifuuInh`, `ifuuInhEn` | accuracy **inheritance** value / enable (both already in `FlightLogParams.xml`) |

[UNDOCUMENTED: binary strings + `appConfig` registry blob, this session]
[INFERRED: every role above, from the names and from the dialog layout — none probed]
This matters because §13.3 shows the *global* `sfmCameraPriorAccuracy*` keys are also never
applied here: if neither the global keys nor the import-time `ifu*` keys are set, the priors
carry RealityScan's defaults end to end.

Binary-only siblings [UNDOCUMENTED]: `gpsLogFileName`, `gpsLogFolder`, `gpsLogCustomFormat`,
`gpsLogCameraAxes`, `gpsLogMount`, `gpsLogEulerAnglesOrderYPR`, `gpsLogEulerAnglesOrderOPK`,
`ifKModel`, `ifDistortionmode`, `ifRmode`, `ifTmode`, `ifOfsX`, `ifOfsY`, `ifOfsZ`,
`ifOfsRR`, `ifOfsRP`, `ifOfsRY`, `ifOfsifuUseOffset`.
The `ifOfs*` set is the **lever-arm / mount-angle offset** block applied at import; this
repo instead applies those offsets upstream in `geoall.py` and the georeference module.
[INFERRED from the names + repo architecture]

Other CSV import families [UNDOCUMENTED: binary]: `csvGCSep` / `csvGCIgn` (ground control),
`csvCPMSep` / `csvCPMIgn` (control-point measurements), `csvDDIgn` (distance definitions).

### 8.6 Model export / import — `-exportModel`, `-exportSelectedModel`, `-importModel`

Exported: `ModelExportParams.xml`, `ModelExportParamsObj.xml`,
`ModelExportParamsFBX_U1V1.xml`, `…FBX_U1V1_material.xml`, `…FBX_UV.xml`, `…FBX_UDIM.xml`,
`…FBX_UDIM_material.xml`, `…FBX_Parts.xml`, `ModelExportParamsGLB.xml`,
`ModelExportParamsOBJ_NiraParts.xml`, `ModelExportParamsPLY_DensePoints.xml`.

Structural rules observed across all ten files [VERIFIED-by-inspection]:

- `ModelExportFormatVersion` (`0` or `13`) is the schema version of the rest of the file.
- Per-texture-layer keys carry a **layer suffix**: `MvsMeshExportTexturing_Color8_0`,
  `MvsMeshExportTexImgFormat_Color8_0`, `MvsMeshExportTexPixFormat_Color8_0`, and the
  `_Normal_0` and `_no_alpha` variants. The unsuffixed base keys also exist.
- `…Allowed` keys (`MvsMeshExportTexturingAllowed`, `…NormalsAllowed`, `…CamerasAllowed`,
  `…MaterialsAllowed`, `…ClassificationAllowed`, `…NumberFormatAllowed`,
  `…EmbeddTxrsAllowed`, `…ByPartsAllowed`, `…ColorsAllowed`, `…ColorInByteAllowed`) use
  `-1` = allowed/inherit and `0` = not allowed. They gate what the target format supports.
- Booleans appear as `true`/`false`, `0`/`1` and `0x1` **interchangeably for the same key
  across files** (e.g. `MvsExportIsGeoreferenced` appears as both `1.0` and `0x1`).

| Key | Type | Observed values | Meaning |
|---|---|---|---|
| `MvsExportcoordinatesystemtype` | int | `0`, `3` | export CRS mode |
| `MvsExportIsGeoreferenced` | bool | `0x1`, `1.0` | export in world coordinates |
| `MvsExportIsModelCoordinates` | bool | `0` | export in model-local coordinates |
| `MvsExportScaleX/Y/Z` | float | `1.0`, `10.0`, `100.0` | export scale (100 = metres → centimetres for Unreal) |
| `MvsExportMoveX/Y/Z` | float | `0.0` | export translation |
| `MvsExportRotationX/Y/Z` | float | `0.0`, `-90.0` | export rotation (the GLB preset uses X = −90) |
| `MvsExportTransformationPreset` | string | `Maya + Arnold, Unreal`, `Unreal`, `Custom`, `[[Custom]]` | named transform preset |
| `MvsExportNormalSpace` | string | `Mikktspace` | tangent-space convention |
| `MvsExportNormalRange` | string | `ZeroToOne` | normal encoding range |
| `MvsExportNormalFlipX/Y/Z` | bool | `false`/`true` (Y = `true` in every repo file) | normal channel flips |
| `MvsMeshExportNormals` | bool | `true` | write normals |
| `MvsMeshExportColors` | bool | `false`, `true`, `0` | write vertex colors (the PLY dense-points preset uses `true`) |
| `MvsMeshExportTexturing` | tri-state | `-1`, `0`, `true` | write textures |
| `MvsMeshExportTexOneFile` | int | `0` | one texture file for the whole model |
| `MvsMeshExportTexAlpha` | bool | `false`, `0` | alpha channel in textures |
| `MvsMeshExportTexImgFormat[_<layer>]` | string | `jpg`, `png`, `jpeg` | texture image format |
| `MvsMeshExportTexPixFormat[_<layer>]` | string | `24bppBGR`, `32bppBGRA` | texture pixel format |
| `MvsMeshExportTileType` | int | `0` single, `1` UV, `2` UDIM | UV tiling scheme |
| `MvsMeshExportByParts` | int | `0`, `1` | split export by model parts |
| `MvsMeshExportMaterials` | bool | `true`, `false` | write materials |
| `MvsMeshExportEmbeddTxrs` *(sic)* | bool | `true` (GLB), `false` | embed textures in the container |
| `MvsMeshExportCameras` | bool/int | `false`, `0` | export camera objects |
| `MvsMeshExportCamerasAsModelPart` | bool | `false` | cameras as a model part |
| `MvsMeshExportInfoFile` | bool | `true` | write the sidecar info file |
| `MvsMeshExportNumberFormat` | int | `5` (OBJ) | numeric precision format |
| `MvsMeshExportFileTypeSelectionDisplay` | int | `0` | dialog state |

Binary-only export siblings [UNDOCUMENTED]: `MvsExportFileType`, `MvsExportAtlasDownscale`,
`MvsExportRandomPartColor`, `MvsExportTransformationPresetSelector`,
`MvsExportcoordinatesystemtypeString`, `MvsMeshExportColorSpace`,
`MvsMeshExportColorInByte`, `MvsMeshExportColorsHaveQuality`,
`MvsMeshExportColorsMapQuality`, `MvsMeshExportClassificationLayer`,
`MvsMeshExportCamerasVisible`, `MvsMeshExportOneFileUsePow2TexSize`,
`MvsMeshExportTexOneFileMaxResolution`, `MvsMeshExportTexToneMap`,
`MvsMeshExportTextureLayersSubpanel`, `MvsMeshExportShowTileType`,
`mvsExportTriangleMosStats`, `MvsMeshExportByPartsAllowed`.

Model **import** twins [UNDOCUMENTED: binary]: `MvsImportcoordinatesystemtype`,
`MvsImportMaxTrianglesPerPart`, `MvsImportMoveX/Y/Z`, `MvsImportRotationX/Y/Z`,
`MvsImportScaleX/Y/Z`, `MvsImportNormalFlipX/Y/Z`, `MvsImportNormalRange`,
`MvsImportNormalSpace`, `MvsModelImportColorSpace`.

### 8.7 Ortho, LoD, classification, snapshots, flyover, COLMAP, coordinate systems

All [UNDOCUMENTED: binary string extraction]; none used in this repo; none confirmed as
`-set` keys. Listed so an agent can find the right identifier fast.

**Ortho geometry / state** — `orthoWidth`, `orthoHeight`, `orthoPixelSize`, `orthoArea`,
`orthoArea2D`, `orthoArea3D`, `orthoColorType`, `orthoBackfaceColor`,
`orthoBackFaceColorType`, `orthoBackfaceColorTransparency`, `orthoIsGeoreferenced`,
`orthoModelIsTextured`, `orthoModelIsClassified`, `orthoSamplingDistance`,
`orthoSamplingCoordinateSystem`, `orthoSamplingPointsCount`, `orthoSamplingRawSize`,
`orthoProjName`, `OrthoDirection`.

**Ortho projection object** (the `-editOrthoProjectionSelection` space) —
`orthoProjectionName` (the only documented one), `orthoProjectionType`,
`orthoProjectionWidth`, `orthoProjectionHeight`, `orthoProjectionUPPX`,
`orthoProjectionUPPY`, `orthoProjectionColorType`, `orthoProjectionIsGeoreferenced`,
`orthoProjectionIsMosaic`, `orthoProjectionHasDtm`, `orthoProjectionCutVolume`,
`orthoProjectionFillVolume`, `orthoProjectionArea2D`, `orthoProjectionArea3D`,
`orthoProjectionCount`, `orthoProjectionDeleteEmpty`, `orthoProjectionRenderEmpty`,
`orthoProjectionRenderEmptyPanel`, `orthoProjectionMorePhases`, `orthoProjectionTimeDtm`,
`orthoProjectionTimeMosaic`, `orthoProjectionTimeRasterize`, `orthoProjectionTimeTotal`,
`orthoprojectiondistance`.

**Isolines / contours** — `orthoIsolinesCompute`, `orthoIsolinesInterval`,
`orthoIsolinesMin`, `orthoIsolinesMax`, `orthoIsolinesLayer`,
`orthoIsolinesLayerAlternative`, `orthoIsolinesUnits`, `orthoIsolinesUnitsAlternative`,
`OrthoIsolinesPixelType`.

**Volumes** — `orthoVolumeCut`, `orthoVolumeFill`, `orthoVolumeState`,
`orthoVolumePossible`, `orthoVolumeSubtype`, `orthoVolumeObpType`, `orthoVolumeObpsOption`,
`orthoVolume1obpOption`, `orthoVolumeUserHeight`, `orthoVolumeUserHeightMode`,
`orthoVolumeUserHeightUnits`, `orthoVolumeUserHeightValue`, `OrthoVolumeUserHeightCommand`,
`OrthoVolumeVisibilityCommand`.

**Mosaicking** — `OrthoMosaicingAlgorithm`, `OrthoMosaicingLayerCount`,
`OrthoMosaicContextAddCameras`, `OrthoMosaicCorrectionToolConsumer`,
`OrthoMeasurementsToolConsumer`, `mvsOrthoColormap`, `mvsOrthoColormapOthersAllWhite`,
`MvsOrthoCreateDtm`.

**Ortho export** — `MvsExportOrthoPhotoColorType`, `MvsExportOrthoPhotoBackfaceColor`,
`MvsExportOrthoPhotoBackFaceColorType`, `MvsExportOrthoPhotoBackfaceColorTransparency`,
`MvsExportOrthoProjectionCommandType`, `MvsExportOrtoPhotoWidth` *(sic, "Orto")*,
`MvsExportOrtoPhotoHeight`, `MvsExportOrtoPhotoPixelSize`, `MvsExportOrtoPhotoShow`.

**LoD / 3D Tiles export** (`-exportLod`, `-export3dTiles`) — `LodType`, `lodPath`,
`lodFilename`, `lodPrimitive`, `lodCriterion`, `lodAltitude`, `lodBandwidthScale`,
`lodModelCount`, `lodMinTriangles`, `lodMinTrianglesEnabled`, `lodMaxTriangles`,
`lodMaxNodeTriangleCount`, `lodSimplificationType`, `lodSimplificationPercentage`,
`lodInitialSimplType`, `lodInitialSimplTargetPercentage`, `lodIterativeSimplType`,
`lodIterativeSimplTargetPercentage`, `lodLargeTriangleRemovalThresh`, `lodTexelSize`,
`lodTexelSizeCustom`, `lodTexelSizeOptimal`, `lodTextureFormat`,
`lodColorInputTextureLayer`, `lodIsModelTextured`, `lodExportTexturingFalse`, `lodGzip`,
`LodSuffix`, `LodSuffixNumbering`, `lodSuffixType`.

**Classification** (`-dtmClassify`, `-transferClassification`, and the dedicated
`-exportClassificationSettings` / `-importClassificationSettings` XML round trip) —
`classification_classificationName`, `classification_formatName`,
`classification_formatIsEditable`, `classification_classifyModelKey`,
`classification_aiOverrideKey`, `classification_colorFromClassification`,
`classification_groundSegmentVotingPowerKey`, `classification_presetTypeKey`,
`classification_presetPostprocessKey`, `ClassificationModelType`, `ClassificationLayer`,
`ClassificationLayerId`, `ClassificationParams`, `ClassificationColorSourceParams`,
`ClassificationPostprocessorType`, `ClassificationPostprocessorSensitivity`,
`ClassificatorType`, `ClassificationFormat`, `classificationFormatExportPath`,
`classificationFormatExportExtension`, `MvsDtmClasificationLayers` *(sic)*,
`MvsDtmClassificationColorLayers`.

**Camera snapshots / renders** (`-exportCameraSnapshots`,
`-exportSelectedCamerasSnapshots`, `-renderMeshFromCustomPosition*`) — `MvsSnapshotType`,
`MvsSnapshotFileFormat`, `MvsSnapshotResolution`, `MvsSnapshotResolutionWidth`,
`MvsSnapshotResolutionHeight`, `MvsSnapshotColorType`, `MvsSnapshotShadingType`,
`MvsSnapshotBackgroundColor`, `MvsSnapshotRandomPartColor`, `MvsSnapshotFocalLength35mm`,
`MvsSnapshotCenterX/Y/Z`, `MvsSnapshotLookAtX/Y/Z`, `MvsSnapshotUpVectorX/Y/Z`,
`MvsSnapshotYaw`, `MvsSnapshotPitch`, `MvsSnapshotRoll`, `MvsSnapshotRotationInputType`.

**Flyover video** — `MvsFlyoverVideoType`, `MvsFlyoverVideoResolution`,
`MvsFlyoverVideoFPS`, `MvsFlyoverVideoBitRate`, `MvsFlyoverVideoMaxFramesCount`,
`MvsFlyoverVideoFramesCountBetwTwoViews`, `MvsFlyoverVideoRandomPartColor`,
`MvsFlyoverBackgroundColor`, `MvsFlyoverColorType`, `MvsFlyoverShadingType`.

**COLMAP import/export** — `colmapDirStructure`, `colmapFileType`, `colmapExportMasks`,
`colmapMaskExtension`, `colmapPointFiltering`.

**Coordinate systems** — `CoordinateSystemDatabaseLruName`,
`CoordinateSystemDatabaseLruName0`..`5`, `CoordinateSystemDatabaseLruFile`,
`CoordinateSystemDatabaseLruFile0`..`5`, `CoordinateSystemFlightLogUnits`.
The **project** and **output** CRS are set by dedicated commands, not by a `-set` key:

```bat
RealityScan.exe -setProjectCoordinateSystem Local:1 ^
                -setOutputCoordinateSystem epsg:4326
```

[OFFICIAL: appbasics/allcommands, tutorials/commandline_4]

**Cache state** (read-back, not the `app*` settings) — `cacheLocation`, `cacheFolder`,
`CacheCustomIsCDisk`, `CacheSwitchedToCustom`, `CacheSwitchedToSysTemp`.

---

## 9. Key spaces that are NOT `-set`

Included because agents routinely try to reach these with `-set`, and because this repo
depends on the first of them. **Almost** every setting has two accepted keys — a short
abbreviation and the full "panel path" — but not all: `inpRx`, `inpRy` and `inpRz` are
printed with no long alias. [OFFICIAL: tutorials/editselectioncommand — "Almost every
setting has two possible keys that can be used. The upper key … is usually an abbreviation
…, and the lower key … is the whole path to the setting based on the panel in which it can
be found."]

### 9.1 `-editInputSelection "key=value"` — per-selected-image settings

Operates on the **current image selection**. Full semantics in
`13-camera-rigs-priors-and-orientation.md`.

| Key | Long alias | Values |
|---|---|---|
| `inpMaskOpts` | `How to use masking layer` | `0` do not use · `1` alignment only · `2` meshing only · `3` both |
| `aligFeaturesMode` | `Features source` | `0` merge using overlaps · `1` use component features · `2` use all image features |
| `inpVisible` | `Visible` | `true` `false` |
| `inpEnabled` | `Enable alignment` | `true` `false` |
| `inpMeshing` | `Enable meshing` | `true` `false` |
| `inpTexturing` | `Enable texturing and coloring` | `true` `false` |
| `inpImageColorsWeight` | `Weight in texturing` | float 0..1 |
| `inpColorRef` | `Color correction reference` | `true` `false` |
| `inpColorNorm` | `Color correction` | `true` `false` |
| `inpImageDepthMapDownscale` | `Downscale for depth maps` | positive int |
| `inpPosePriorRelativeGroup` | `Prior pose/Locked pose group` | alphanumeric |
| `inpPosePriorRelative` | `Prior pose/Relative pose` | `0` Unknown · `1` Draft · `2` Exact |
| `inpPose` | `Prior pose/Absolute pose` | `0` Unknown · `1` Position · `2` Position and orientation · `3` Locked |
| `inpTx` / `inpTy` / `inpTz` | `Prior pose/x`,`/y`,`/z` (also `/Longitude`,`/Latitude`,`/Altitude`) | float; lat/lon also accept DMS with a cardinal prefix (`N54,49,31.25`) or prefixed decimal degrees (`E32.140328`) |
| `inpRx` / `inpRy` / `inpRz` | Yaw/Heading · Pitch/Elevation · Roll/Bank | −180..180 / −90..90 / −180..180 |
| `inpPriorAccuracyInh` | `Prior pose/Pose accuracy/Accuracy settings source` | `0` global camera prior settings · `1` edit custom values |
| `inpuTx` `inpuTy` `inpuTz` `inpuRx` `inpuRy` `inpuRz` | per-axis prior accuracies | float ≥ 0 |
| `inpCalibrationGroup` | `Prior calibration/Calibration group` | int ≥ 0, or `-1` groupless |
| `inpCalibration` | `Prior calibration/Prior` | `0` Unknown · `1` Approximate · `2` Fixed |
| `inpFocal` | `Prior calibration/Focal length (35mm)` | positive float, mm |
| `inpPPX` / `inpPPY` | principal point x / y [mm] | float |
| `inpSkew` | `Prior calibration/Skew` **and** `Prior calibration/Aspect ratio` — the Help lists one key for both, see §13.8 | float |
| `inpLensGroup` | `Prior lens distortion/Lens group` | int ≥ 0, or `-1` |
| `inpDistortion` | `Prior lens distortion/Prior` | `0` Unknown · `1` Approximate · `2` Fixed |
| `inpDistortionModel` | `Prior lens distortion/Camera model` | `0` No lens distortion · `1` Division · `2` Brown3 · `3` Brown4 · `4` Brown3 with tangential distortion · `5` Brown4 with tangential distortion. **Note the numbering differs from `sfmDistortionModel`, which is a name enum with `Division` first and no "no distortion" member** |
| `inpRadial1`..`inpRadial4`, `inpTangential1`, `inpTangential2` | distortion coefficients | float |

Binary siblings not in the Help [UNDOCUMENTED]: `inpAspect`, `inpPosePriorAbsoluteCs`,
`inpPosePriorAbsoluteCsInput`, `inpPosePriorAbsoluteCsType`, `inpPosePriorAbsoluteCsWkt`,
`inpPosePriorAccuracyMode`, `inpRig`, `inpRigId`, `inpRigIndex`, `inpRigInstance`.

Repo-relevant empirical notes:

- `-editInputSelection` works headless; `"inpEnabled=false"` works as a single quoted
  `key=value` argument and `-align` honours enable/disable exactly.
  [VERIFIED: ALIGN_MERGE_HARDENING cells U1 / U19 / U2, 2026-07-23]
- `inpPose=3` **takes effect but makes an incremental align refuse outright**, so
  checkpoint/rollback stayed the never-shrink mechanism rather than pose-locking. The
  refusal text is worth knowing verbatim: "prior set to 'Exact' mode must be all aligned in
  a single run. Incremental adding is not supported."
  [VERIFIED: FINDINGS 2026-07-23, ALIGN_MERGE_HARDENING U18 FAIL]
  Note the naming mismatch: `tutorials/editselectioncommand` labels `inpPose=3` **`Locked`**
  (and reserves `Exact` for `inpPosePriorRelative=2`), while RealityScan's own error message
  calls the resulting state **'Exact'**. [CONTRADICTED: Help label vs runtime message —
  observed in the U18 log, 2026-07-23]
- Related, from the same probe: **align output is never pose-stable.** A free re-align moved
  all 118 cameras of an already-solved smoke scene and can drop 1–2 marginal ones — so "same
  settings, same images" does not mean "same poses".
  [VERIFIED: FINDINGS 2026-07-23, U18 bonus]
- The default lens prior is **"No lens distortion" with prior "Approximate"**, which drives
  the solver toward zero distortion — wrong for visibly distorted optics. Use `Unknown` or
  supply coefficients. [OFFICIAL: appbasics/camerasettings_priors]
- Related but separate: `LensDistortionPrior="Approximate"` **with no coefficients
  supplied does not pin distortion to zero** — a camera carrying exactly that still solved
  k1 = −0.0524 over 2,204 cameras. An earlier caution to the contrary was wrong.
  [SUPERSEDED → VERIFIED: FINDINGS 2026-07-25]
- `aligFeaturesMode` is also reachable as the standalone command
  `-setFeatureSource 0|1|2` on the current image selection — the trio was wrongly believed
  GUI-only. [SUPERSEDED → VERIFIED: NA167 B11, 2026-07-23]
- **`-selectImage` matches literal full paths only in this build**, so composing the
  selection these keys act on is a per-image union loop (~0.1–0.3 s per image).
  [CONTRADICTED: the Help documents `selectImage <imagePath|regexp> [set|union|sub|intersect|toggle]`
  / observed: bare regexp, dot-star-wrapped regexp, glob, and regexp with an explicit `set`
  modifier all silently select nothing, bisected across probes U-SEL2…U-SEL8, 2026-07-23]

### 9.2 `-editControlPointSelection "key=value"`

`gpName`, `gpEnabled` (`true`/`false`), `gpType` (`0` tie point · `1` ground control ·
`2` ground test), `gpWeight` (float), `gpP1`/`gpP2`/`gpP3` = x/y/z (also
Longitude/Latitude/Altitude, DMS or prefixed decimal degrees), `gpuP1`/`gpuP2`/`gpuP3` =
per-axis position accuracies (float ≥ 0). [OFFICIAL: tutorials/editselectioncommand]

### 9.3 `-editConstraintSelection "key=value"`

`cName` (string), `cA` / `cB` (existing control-point names), `cEnabled` (`true`/`false`),
`cValue1` (defined distance, positive float), `cValue1Acc` (defined distance accuracy,
positive float). [OFFICIAL: tutorials/editselectioncommand]

### 9.4 `-editOrthoProjectionSelection "key=value"`

`orthoProjectionName` (string) — the only documented key.
[OFFICIAL: tutorials/editselectioncommand]

---

## 10. Settings you should always pin explicitly

**The rule.** Swept `-set` values **persist across instance restarts**, and there is no
per-key read-back command. An instance therefore carries whatever the last session — GUI
or CLI, yours or someone else's — left in it. Defaults are also undocumented for a large
part of the namespace and have changed across builds. Consequently: **every run pins every
key it depends on, and never relies on a default.**
[VERIFIED: testing/MERGE_TEST_PLAN §3 contamination controls, 2026-07-23; repo policy
"never align on instance defaults", `AlignZone.bat` header]

### 10.1 At instance boot

`RS_CLI/Scripts/startRealityScan.bat` line 61, verbatim shape:

```bat
start "" %RealityScan% %RS_HEADLESS_FLAG% -silent "%ErrorPath%" ^
  -setInstanceName %RS_INSTANCE% %RS_CACHE_ARGS% ^
  -set "appAutoSaveMode=false" ^
  -set "appQuitOnError=false" ^
  -set "appProcessActionTime=0" ^
  -set "appProcessAction=ExecuteProgram" ^
  -set "appProcessExecCmd=wscript.exe //B \"%ErrorPath%\ErrorWriterLaunch.vbs\" $(processResult) $(processId) $(processDuration:d) %RS_INSTANCE%" ^
  -writeProgress "%ErrorPath%\progress_%RS_INSTANCE%.txt" 600
```

with, when `RS_CACHE_DIR` is defined:

```bat
set "RS_CACHE_ARGS=-set "appCacheLocation=Custom" -set "appCacheCustomLocation=%RS_CACHE_DIR%""
```

| Key | Value | Why |
|---|---|---|
| `appAutoSaveMode` | `false` | Autosave would race the destructive in-session identity loop, and a modal recovery dialog hangs a headless box forever |
| `appQuitOnError` | `false` | Warning-class results (`0x820000FF`, e.g. `err:18002`) are routine; the orchestrator decides, not the app |
| `appProcessActionTime` | `0` | Every operation, however short, must fire the completion hook |
| `appProcessAction` | `ExecuteProgram` | The hook is the authoritative per-operation result channel |
| `appProcessExecCmd` | `wscript.exe //B "<ErrorPath>\ErrorWriterLaunch.vbs" …` | A GUI-subsystem host is required — a console-subsystem child pops a visible window when the parent has none. The escaped quotes are mandatory: an unquoted path with a space silently disabled all error detection |
| `appCacheLocation` / `appCacheCustomLocation` | `Custom` / `%RS_CACHE_DIR%` | The cache does not move with the project; a full cache disk aborts the operation and loses its progress. Epic forbids hand-deleting cache files, so relocation is the sanctioned lever |
| `appAutoClearCache` | *deliberately NOT set* | Retention is owner policy, not a per-run decision |
| `appLog` | *deliberately NOT set* (stays `true`) | `RealityScan.log` is the only place the real reason behind a generic `0x8000FFFF` exists |

[VERIFIED: `startRealityScan.bat` + FINDINGS 2026-07-21 / 2026-07-25 / 2026-07-26]

### 10.2 Before every `-addFolder`

```bat
%RealityScan% -delegateTo %RS_INSTANCE% -set "appIncSubdirs=true"
call :run -addFolder "%input_dir%"
```

Present in `AlignZone.bat` (line 72), `AlignImagesFromFolder.bat` (line 133) and the
legacy `archive/legacy_scripts/AlignZonesSequentially.bat` (line 108). Rationale in §13.1.

### 10.3 Before every `-align`

Replayed row-by-row from `RS_CLI/Metadata/AlignmentParams.xml` (filter `sfm`/`lis`) by
`AlignZone.bat`, `AlignImagesFromFolder.bat`, `GrowZone.bat`, `ProbeLockAlign.bat`,
`ProbeSubsetAlign.bat`, `ProbeSubsetAlign2.bat`.

| Key | Value | Rationale |
|---|---|---|
| `sfmEnableCameraPrior` | `true` | The GUI's "use camera priors for georeferencing"; required for georeferenced components |
| `sfmCameraPriorWeight` | `10.0` | Proven on this data class (NA167 zone_13, 93.4%); documented fallback `1.0` if a zone under-registers — never exercised |
| `sfmCameraPriorWeightOrientation` | `2.0` | Same |
| `sfmCameraPriorAccuracyYaw` / `Pitch` / `Roll` | `10.0` each | Defaults retained explicitly |
| `sfmControPointImageMeasAccuracy` | `4.0` | Loosened from the `2.0` default |
| `sfmDistortionModel` | `Division` | NA167 fisheye-through-dome legacy; the documented target for a rectilinear rig is `Brown3`. §13.5 makes the choice consequential |
| `sfmDetectorSensitivity` | `Ultra` | Weak underwater texture; the CLAHE A/B was validated at this setting |
| `sfmMaxFeaturesPerMpx` | `0x36b0` (14000) | More features ⇒ fewer components on low-texture seabed |
| `sfmMaxFeaturesPerImage` | `0xc350` (50000) | Same |
| `sfmPreselectorFeatures` | `0x4e20` (20000) | Epic: ¼–½ of detected |
| `sfmMaxFeatureReprojectionError` | `1.29999995` | Tightened from `2.0`; Epic caps the recommendation at `3` |
| `sfmImagesOverlap` | `Medium` | Raised from legacy `Low`: 2–3 s frame spacing, interleaved cameras, track revisits need the broader pair search for loop closures |
| `sfmImageDownscaleFactor` | `1` | Full resolution |
| `sfmForceComponentRematch` | `false` | Merge-stage tool; wasted per zone |
| `sfmMergeGeoreferencedComponents` | `false` | Per-zone components must stay honest; fusion is the merge stage's explicit, inspectable job |
| `sfmAutoReconRegionAfterAlignment` | `false` | The region is set explicitly downstream |
| `sfmGPUAcceleration` | `true` | Uses every CUDA GPU by default [UNDOCUMENTED key] |
| `sfmBackgroundDetectFeatures` | `false` | No idle-time detection on a batch box [UNDOCUMENTED key] |
| `sfmBackgroundDetectThreadPriority` | `Low` | Inert while the above is `false` [UNDOCUMENTED key] |
| `sfmEnableAutoSuggestions` | `true` | GUI-only effect [UNDOCUMENTED key] |
| `sfmCameraDepthmapWeight` | `0.05` | [UNDOCUMENTED key], effect unknown |
| `sfmFeatureDetectionQuality` | `RealityScan.FeatureDetector.RSa1` | Detector id string; §13.2 |
| `sfmImagesOverlapDraftMode` | `Medium` | Draft path unused in production, pinned anyway |
| `sfmImageDownscaleFactorDraftMode` | `2` | Same |
| `sfmFinalModelOptimizationDraftMode` | `false` | Same |
| `lisPreferImagesAsFeatureSource` | `false` | No LiDAR in this pipeline; pinned rather than defaulted |
| `s235l`/`s236l`/`s237l`, `s251l`..`s254l` | `5.0`/`5.0`/`0.5`, `0.05`/`0.05`/`0.1`/`0.001` | **Filtered out by the `sfm`/`lis` prefix test and never applied** — §13.3 |

[VERIFIED-by-inspection: `AlignmentParams.xml`; rationale from
docs/settings-evaluation-2026-07 §4 unless noted]

### 10.4 The merge ladder

`merge_zones.py` → `MergeZoneComponents.bat`, settings crossing the `.bat` boundary as
`key:value` (§1.2). `MergeZoneComponents.bat` accepts at most **four** such pairs (`%6`..`%9`),
which is exactly what the longest rung needs.

There are **two** ladders in `LADDERS`; `--ladder` / the `rs_settings` key `merge.ladder`
selects one, default `merge_first`.
[VERIFIED-by-code-reading: `merge_zones.py` lines 81–110 (`LADDERS`), 1022–1023
(`--ladder`), 1077–1078 (default `merge_first`)]

`merge_first` (default) — each rung's `settings` list in full, exactly as passed:

| Rung | `label` | `mode` | `settings` |
|---|---|---|---|
| 1 | `merge_georef` | `merge` (`-mergeComponents`) | `sfmMergeGeoreferencedComponents:true`, `sfmEnableCameraPrior:true` |
| 2 | `align_rematch` | `align` (`-align`) | the two above **+** `sfmForceComponentRematch:true` |
| 3 | `align_rematch_high_overlap` | `align` | the three above **+** `sfmImagesOverlap:High` |

`content_first` is the same three rungs reordered `align_rematch` →
`align_rematch_high_overlap` → `merge_georef`, for zones where align-rematch is the only
content-capable mechanism.

**Rungs are filtered before use.** `effective_ladder_for` admits `merge` rungs only when
the shared-image graph **spans** the subset; otherwise the ladder is reduced to its `align`
rungs. Rationale in the code: "merge fuses through camera identity and otherwise
rigid-glues everything in the scene."
[VERIFIED-by-code-reading: `merge_zones.py` lines 316–323]

**Rung 3 is judged not defensible on the evidence.** `sfmImagesOverlap` only widens
candidate-pair search, so it can help only where components share content the matcher
skipped. Both observed cases fall outside that: components with zero **content** overlap
never fuse under any flag (§12.2), and the hull case that did fuse fused on every rung — so
matching was never the constraint. The proposed replacement is orphan inclusion (which
requires an `-align` rung, since `-mergeComponents` never adds images) with the orphans set
to **all image features** (`-setFeatureSource 2` / `aligFeaturesMode=2`), because
component-features and overlaps give an orphan nothing. Note the structural blocker
recorded with it: `MergeZoneComponents.bat` has **no `-addFolder` at all**, so the merge
scene cannot currently contain an orphan. [VERIFIED: FINDINGS 2026-07-27]

### 10.5 The minimum pin list for a new agent

If you are writing a new workflow, pin at least these before the corresponding operation.
Everything else in this document is optional; these have a recorded failure behind them.

```bat
:: boot
-set "appAutoSaveMode=false"
-set "appQuitOnError=false"
-set "appProcessActionTime=0"
-set "appProcessAction=ExecuteProgram"
-set "appProcessExecCmd=wscript.exe //B \"<ErrorPath>\ErrorWriterLaunch.vbs\" $(processResult) $(processId) $(processDuration:d) <instance>"
-set "appCacheLocation=Custom"
-set "appCacheCustomLocation=<big fast disk>"

:: before every -addFolder
-set "appIncSubdirs=true"

:: before every -align, all of them, every time
-set "sfmEnableCameraPrior=..."          -set "sfmCameraPriorWeight=..."
-set "sfmCameraPriorWeightOrientation=..." -set "sfmDistortionModel=..."
-set "sfmDetectorSensitivity=..."         -set "sfmImagesOverlap=..."
-set "sfmMaxFeaturesPerMpx=..."           -set "sfmMaxFeaturesPerImage=..."
-set "sfmPreselectorFeatures=..."         -set "sfmMaxFeatureReprojectionError=..."
-set "sfmImageDownscaleFactor=..."        -set "sfmForceComponentRematch=..."
-set "sfmMergeGeoreferencedComponents=..." -set "sfmAutoReconRegionAfterAlignment=..."
-set "sfmCameraPriorAccuracyX=..."        -set "sfmCameraPriorAccuracyY=..."
-set "sfmCameraPriorAccuracyZ=..."        -set "sfmCameraPriorAccuracyYaw=..."
-set "sfmCameraPriorAccuracyPitch=..."    -set "sfmCameraPriorAccuracyRoll=..."

:: before -calculate*Model, if you care about the result being reproducible
-set "PrecomputeDepthmaps=false"
```

The three `sfmCameraPriorAccuracy*` position keys are in this list precisely because the
existing pipeline **omits** them by accident — see §13.3.

### 10.6 Families this repo never touches

`mvs*` reconstruction (mesh runs on instance defaults — a standing gap, not a decision),
`txt*` / `col*` / `ImageLayerFor*` coloring and texturing globals, `ortho*`, `lod*`,
`classification*`, snapshot / flyover, `colmap*`, and `-preset` entirely.

---

## 11. Dead and deprecated keys

| Key(s) | Status | Evidence |
|---|---|---|
| `RealityCapture*` — the entire legacy application-settings key family | **DEAD in 2.x.** An exhaustive scan of `RealityScan.exe` 2.2.0.119430 for `RealityCapture[A-Za-z0-9_]{2,40}` returns exactly three identifiers, all ASCII and none a settings key: `RealityCaptureDmp`, `RealityCaptureDmpMeta`, `RealityCaptureModalDialog` (crash-dump / window-class names). The UTF-16LE string space contains no `RealityCapture`-prefixed identifier at all, only the bare word. Replacements: `appQuitOnError`, `appProcessAction`, `appProcessExecCmd`, `appProcessActionTime` | [VERIFIED: binary scan re-run this session, both encodings] + [VERIFIED: HANDOFF overhaul item 2 — "legacy `RealityCapture*` `-set` keys replaced with the `app*` keys RealityScan 2.x actually uses", 2026-07-21] |
| `sfmControlPointImageMeasAccuracy` (corrected spelling) | **Does not exist.** The live key keeps Epic's typo: `sfmControPointImageMeasAccuracy` — no `l` in "Control". The typo is load-bearing — spell it wrong | [VERIFIED: binary scan re-run this session — corrected spelling absent as UTF-16LE (both alignments) and ASCII, typo'd spelling present as UTF-16LE] |
| `appProcessEmailAddres` | Not deprecated, but note the single `s` — the string in the binary is misspelled | [UNDOCUMENTED: binary] |
| `-setMinComponentSize <n>` | Not a settings key, but the adjacent identifier most likely to bite: **deprecated in 2.2** ("will be removed in the next release") and yet still **required** — without it, components below the default threshold 5 are silently excluded from selection AND from XMP export | [VERIFIED: deprecation warning read from a per-cell `RealityScan.log` snapshot, NA167 #22 / B11, 2026-07-24] |
| `-selectAllComponents` | **Does not exist in 2.2**; fails as unknown/invalid `0x82000060`. It had lived unnoticed in `AlignZonesSequentially.bat`. Only `selectComponent`, `selectMaximalComponent` and `selectComponentWithLeastReprojectionError` exist | [VERIFIED: NA167 #13 / B2, 2026-07-23] |
| `-stdConsole` | Live in the product, **removed from this repo**: it allocates a console window per instance boot and nothing reads instance stdout (progress comes from `-writeProgress`, results from the ErrorWriter hook) | [VERIFIED: `startRealityScan.bat` comment, 2026-07-23] |
| `unwrapButtonDisabled` | Not a setting — exported UI state. Harmless, carries no effect | [INFERRED from the name; present in repo XML and the binary] |

**The 2.2 Help contains no deprecation markers on any settings key.** Every "deprecated"
statement above comes from a runtime warning or from this repo's testing, not from the
documentation. [VERIFIED: full read of tutorials/setkeyvaluetable]

---

## 12. Inert keys — configured but with no effect

Two different kinds of inertness. Both matter: in each case a config file *looks* like it
is controlling something and is not.

### 12.1 Keys absent from the 2.2 binary (the string does not exist)

| Key | Where it appears | Nearest real key | Source |
|---|---|---|---|
| `ifKmode` | `RS_CLI/Metadata/FlightLogParams.xml` (`0x0`) | the binary has `ifKModel` | [CONTRADICTED: exported XML vs binary] |
| `ifUsePosAcc` | `FlightLogParams.xml` (`true`) | — | [CONTRADICTED: same] |
| `ifUseOriAcc` | `FlightLogParams.xml` (`true`) | — | [CONTRADICTED: same] |
| `unwrapCheckerBoardCellSize` | six repo `Texturing_*.xml` presets (`64`) | the binary has `unwrapCheckerBoardCellCount` | [CONTRADICTED: same] |
| `mvsSmoothing_useIntelligentSmoothing` | **Epic's own shipped** `Settings\SimplifiedExport\smooth.xml` (`0`) | — | [CONTRADICTED: shipped preset vs binary] |

**Method, re-run this session.** Each of the five was searched for in
`RealityScan.exe` 2.2.0.119430 (45,211,352 bytes) as UTF-16LE at **both** byte alignments
and as ASCII; all five are absent, and the "nearest real key" column entries
(`ifKModel`, `unwrapCheckerBoardCellCount`) are present as UTF-16LE. The mis-spelled live
key `sfmControPointImageMeasAccuracy` is present and its corrected spelling is absent by the
same test. [VERIFIED: exhaustive binary scan, this session]

The last row is the sharpest: a key in a file Epic ships does not exist in the executable
Epic ships. Do not treat presence in a vendor preset as proof a key is live.

**And do not treat presence in the app's own persisted config as proof either.** `ifKmode`
— absent from the executable by the test above — **is** present in this machine's
`appConfig` registry blob (§1.6). The settings layer stores key names the engine never
resolves, so a key can survive a full write/read round trip while doing nothing. This is the
mechanism that makes a dead key indistinguishable from a live one through every read-back
path currently known. [VERIFIED: registry read + binary scan, this session]

### 12.2 Keys that exist but were measured as having no effect headless

| Key | Claim | What was observed |
|---|---|---|
| `sfmMergeGeoreferencedComponents=true` | [OFFICIAL: appbasics/alignsettings] "When multiple components are created and each is georeferenced, enabling this setting allows them to be merged even without visual overlap" | **The documented "without visual overlap" behaviour has never been observed headless.** Cell D1 (`-mergeComponents`, flag on, zone_6+zone_4, no shared content) → no fuse; the result count `1,533` was zone_6 alone. Cell D2 (`-align`, georef `true` + rematch `true`, same pair) → no fuse, `1,533`. Cell D3 (shared-path pair, both flags pinned `false`) → no fuse, `1,534`. In each case the workflow exits SUCCESS and the components stay separate, silently. See the correction immediately below for what this does **not** mean. [CONTRADICTED: NA167 wave-2 cells D1/D2/D3, 2026-07-24, testing/MERGE_TEST_PLAN §4 "Wave 2"] |
| `sfmBackgroundDetectThreadPriority` | — | Inert **by composition** whenever `sfmBackgroundDetectFeatures=false`, which is the production setting [INFERRED] |
| `sfmEnableAutoSuggestions` | measurement suggestions in the 3Ds view | GUI-only effect; no headless consequence [INFERRED from the Help's description] |
| `sfmMergeGeoreferencedComponents` without `sfmEnableCameraPrior` | — | Inert by composition: (a) `sfmEnableCameraPrior` is per-camera during alignment and is what makes components georeferenced; (b) `sfmMergeGeoreferencedComponents` is per-component and post-solve. (b) without (a) has nothing to act on [INFERRED from Help prose + design reasoning, docs/settings-evaluation-2026-07 §5; **not isolated by a cell**] |

**CORRECTION — fusion is CONTENT-driven, not identity-driven.** An earlier version of this
document (and of the surveys behind it) concluded from D1–D3 that "`-mergeComponents` fuses
only through cameras shared by identity (the same image path in more than one component)".
**That conclusion is refuted.** The D7 probe wave (2026-07-24, `testing/probe_d7.py`, smoke
fixture) fused `zone_c` (78 cams) + `zone_d_c0` (42 cams) — **zero shared basenames, zero
shared paths** — into one 120-camera component ("Finalizing 1 component", 70 s), both with
no flight log in the merge scene (`D7b`) and with union log + `-update` (`D7a`); `-align` +
rematch fused the 118+62 overlap pair to 180 with no log (`Q9a`). What those pairs did share
was **image content** — they view the same wreck strip. The reconciliation with D1–D3 is
that z6+z4 never see the same seafloor, i.e. they had zero **content** overlap, not merely
zero path overlap. One rule explains every observation to date:

> **content overlap ⇒ fusable by either mechanism, with or without scene georef
> constraints; no content overlap ⇒ silent no-fuse regardless of flags or log.**

Corollaries recorded with it: the union flight log is still **required** to georeference the
merged result but plays no part in fusion; bbox border gating is the correct candidate
filter, since content overlap requires spatial adjacency.
[VERIFIED: FINDINGS 2026-07-24 "D7 RESOLVED"; testing/MERGE_TEST_PLAN "D7 probe wave"]
[SUPERSEDED: the identity-only reading]

**Do not close the `sfmMergeGeoreferencedComponents` question yet.** A superseded-risk flag
is recorded against D1/D2: those cells fed the flag components georeferenced from
**position-only priors at 10 m claimed accuracy**, so the feature's documented premise
("each is georeferenced") was arguably never met — RealityScan may distinguish
prior-weighted georeferencing from ground-control-locked georeferencing. A re-test with
priors-v2 components is queued and has never been run.
[SUPERSEDED-RISK: FINDINGS 2026-07-25 RECON] [OPEN]

**Aggravating observation on the same key — the flag's failure mode is not "no fuse", it is
"fake fuse".** Three accepted `merge_georef` attempts (`-mergeComponents` +
`sfmMergeGeoreferencedComponents`) on H2024 `cluster_1` scored as exact-sum fusions with
**zero camera loss** while RealityScan's own log reported "Finalizing 3", then "7", then "8"
components — the resulting 3,615-camera container held eight disjoint objects. Of
cluster_1's 28 component pairs, exactly one shared any imagery (343 shared basenames); the
rest related only through transitive bbox adjacency. Contrast the hull, whose accepted rung
was `align`: "Finalizing 1" and a **loss of 5 cameras** — the signature of real joint
solving.

> **Zero camera loss on a zero-shared-imagery "fusion" is the signature of co-location, not
> registration.** Verify merges by camera count *and* by the `Finalizing N` line, never by
> exit status. `GenerateModel`'s keep-largest-connected-component step would have deleted
> every smaller object from a model of such a container.

Consequent gate rework (owner uniqueness criterion): components belong in one merge scene
only when they share imagery or their bboxes truly overlap — `pair_gate=overlap` is now the
default, `border` retains the old 10 m-margin adjacency for comparison.
[VERIFIED: FINDINGS 2026-07-28] [OPEN: the exact semantics of `Finalizing N` are not
established — recorded per attempt as `rs_finalizing`, probe queued]

---

## 13. Contradictions and doc defects

The highest-value entries in this document. Each states what the docs claim, what was
observed, and how.

### 13.1 `appIncSubdirs` — documented as a convenience, mandatory in practice

- **Docs:** "Add all images in the specified folder. In order to include also
  subdirectories, use command set with a key `appIncSubdirs`."
  [OFFICIAL: tutorials/commandline, appbasics/allcommands]
- **Observed:** on this 2.2 build, `-addFolder` over a zone tree whose images sit in
  per-camera / `preprocessed_images` subfolders added **0 layer images**, every subsequent
  flight-log row failed `err:18002`, and the run "succeeded" in 25 s. The cause was visible
  only in the `RealityScan.log` snapshot (`Added 0 layer images`).
- **Internal contradiction, resolved:** an earlier NA167 zone_13 run *did* import camera
  subfolders (34 wca + 904 zeuss into one scene, 93.4% registered) and
  `NA167_SESSION_NOTES` records "subfolders were included WITHOUT setting the key", while
  `FINDINGS` records the opposite for H2023. Reconciliation adopted: **the flag, not the
  build, was the variable** — the NA167 run had `appIncSubdirs` set by the fixed workflow.
  `testing/MERGE_TEST_PLAN.md` line 26 preserves the superseded observation.
- **Resolution:** `-set "appIncSubdirs=true"` before **every** `-addFolder`, no exceptions.
  [VERIFIED: FINDINGS 2026-07-23]

### 13.2 `sfmFeatureDetectionQuality` — the documented values are not the values the app writes

- **Docs:** `High` | `Normal`, default `High`. [OFFICIAL: tutorials/setkeyvaluetable]
- **Observed:** the Alignment Settings panel exported from the GUI writes
  `<entry key="sfmFeatureDetectionQuality" value="RealityScan.FeatureDetector.RSa1"/>`.
  Neither `High` nor `Normal` ever appears as the exported value.
  [UNDOCUMENTED: `RS_CLI/Metadata/AlignmentParams.xml` line 3, verbatim]
- **How many detector ids exist — corrected.** An earlier version of this document said
  "exactly two". That was an artefact of scanning only the UTF-16LE string pool. The 2.2
  binary actually contains **eight** `RealityScan.FeatureDetector.*` identifiers:

  | Id | UTF-16LE | ASCII |
  |---|---|---|
  | `RealityScan.FeatureDetector.RSa1` | yes | yes |
  | `RealityScan.FeatureDetector.TB` | yes | yes |
  | `RealityScan.FeatureDetector.TBa1` | no | yes |
  | `RealityScan.FeatureDetector.TBa2` | no | yes |
  | `RealityScan.FeatureDetector.TBv2` | no | yes |
  | `RealityScan.FeatureDetector.TBv3` | no | yes |
  | `RealityScan.FeatureDetector.TBv3CSSs2` | no | yes |
  | `RealityScan.FeatureDetector.TBv3NoCSS` | no | yes |

  Only `RSa1` and `TB` are present in the UTF-16LE pool that the settings layer uses, which
  is consistent with those two being the pair the `High`/`Normal` dropdown selects between
  and the other six being internal algorithm registrations. [VERIFIED: regex
  `RealityScan\.FeatureDetector\.[A-Za-z0-9_]+` over the whole binary in both encodings,
  this session] [INFERRED: the "settings-layer pair" reading]
- **Status:** the repo pushes the detector-id form through `-set` in every zone align and
  those aligns complete with no `err:7155` — evidence the form *parses*, **not** evidence
  the key was honoured. [INFERRED]
- **[OPEN]:** which of `RSa1`/`TB` corresponds to `High` and which to `Normal` — and whether
  `-set "sfmFeatureDetectionQuality=High"` and the id form are even interchangeable. Probe:
  toggle the GUI dropdown, re-export the Alignment panel, read the value both ways.
- Naming rule: these ids are current product strings and must not be renamed away from
  `RealityScan.*` (CLAUDE.md hard rule).

### 13.3 Camera-prior and control-point accuracies are configured but never shipped

The Help documents `sfmCameraPriorAccuracyX/Y/Z`, `sfmControlPointXAccuracy/Y/Z` and
`sfmDefinedDistanceAccuracy` as `-set` keys, and all **seven** exist in the 2.2 binary
(re-verified this session; so do the seven `s<NNN>l` ids). But the
GUI's settings exporter writes them as `s235l`/`s236l`/`s237l` and
`s251l`/`s252l`/`s253l`/`s254l`, and every repo workflow filters the replay to keys
beginning `sfm` or `lis`:

```bat
echo %%A| %SystemRoot%\System32\findstr.exe /b /c:"sfm" /c:"lis" >nul
if not errorlevel 1 %RealityScan% -delegateTo %RS_INSTANCE% -set "%%A=%%B"
```

**Consequence: the intended non-default accuracies — 5.0 / 5.0 / 0.5 metres for camera
priors, 0.001 for defined distance — have never been applied in production. Every run used
RealityScan's defaults (10.0 / 10.0 / 20.0 and 0.10).** This matters because prior
*hardness* (`sfmCameraPriorWeight=10.0`) was tuned on the assumption that the accuracies
bounded the trust envelope; hardness and accuracy are different levers and only one of them
was actually set.

Only **four** of the seven dropped rows would have changed anything: the three
control-point rows (`s251l`/`s252l`/`s253l` = `0.05`/`0.05`/`0.1`) already equal
RealityScan's defaults, so their loss is inert. The live loss is camera-prior X/Y/Z
(`5.0`/`5.0`/`0.5` vs defaults `10.0`/`10.0`/`20.0`) and defined-distance accuracy
(`0.001` vs `0.10`) — and, since this pipeline has no control points or distance
constraints, in practice it is the three camera-prior rows.

**Fix:** emit the documented `sfm*` names explicitly rather than relying on the exporter's
generated ids, e.g. `-set "sfmCameraPriorAccuracyZ=0.5"`. Also note the **second**, separate
place these accuracies could be set and are not: the flight-log import's own `ifu*` block
(§8.5), which is likewise absent from `FlightLogParams.xml` in usable form.
[VERIFIED: code reading of `AlignZone.bat` line 86 + `AlignmentParams.xml`;
defaults from tutorials/setkeyvaluetable]

### 13.4 `sfmMergeGeoreferencedComponents` — a documented capability never observed headless

Full treatment in §12.2. Summary in three lines:

- **Docs:** "When multiple components are created and each is georeferenced, enabling this
  setting allows them to be merged even without visual overlap."
  [OFFICIAL: appbasics/alignsettings]
- **Observed:** no mechanism × flag × path-form combination has produced an overlap-free
  merge headless (D1/D2/D3). What *does* fuse is **image content**, path identity
  irrelevant (D7 probe wave) — so the feature's own selling point, fusion *without* visual
  overlap, is the one thing never seen. Where the flag "succeeded" on content-disjoint
  inputs it produced a container of disjoint objects at exact-sum camera counts —
  co-location, not registration.
- **Status:** [CONTRADICTED] on the documented capability; the premise ("each is
  georeferenced") may not have been met by the test components, so a superseded-risk flag
  stands. [OPEN — see Open questions #5]

### 13.5 `sfmDistortionModel` is global and all-or-nothing

- **Docs:** describe the global setting and, separately, per-image lens-distortion priors
  including a per-image **Model**.
  [OFFICIAL: appbasics/settings_distortion_models, appbasics/camerasettings_priors]
- **Observed:** cinema-camera XMP sidecars declared `brown3`, yet **all 2,558 cinema pose
  XMPs came back `xcr:DistortionModel="division"`** — identical to the 2,492 port records.
  Aggregated from 5,050 PD-6 harvest records.
- **Consequence:** a mixed-optics rig gets **one** distortion model; only the coefficients
  differ per calibration group. The "per-camera model via XMP" plan in
  `docs/settings-evaluation-2026-07 §3` is not achievable — choose one global model and
  supply measured coefficients per group.
- The grouping itself demonstrably works: given the **same** 16.0 mm prior, the solve
  separated the two cameras by 5.6% with IQRs of ±0.5% (cinema focal 35 mm-eq 16.374,
  division k1 −0.0378; port focal 15.499, division k1 −0.3875 — an order-of-magnitude k1
  gap, the fisheye declaring itself).
- [CONTRADICTED: settings-evaluation §3 asserted "per-image XMP overrides the global key" /
  observed: the global key owns the model, 2026-07-26] [VERIFIED: FINDINGS 2026-07-26; PD-2]

### 13.6 `unwrapMinTexelSize` / `unwrapMaxTexelSize` are each listed twice with different types

`setkeyvaluetable.htm` gives, for the AdaptiveTexelSize style:

| Help row | Key printed | Type printed | Default |
|---|---|---|---|
| "Minimal required texel size" | `unwrapMinTexelSize` | enum `0`..`5` | `0` |
| "Custom minimal required texel size" | `unwrapMinTexelSize` | float | `0.01` |
| "Maximal required texel size" | `unwrapMaxTexelSize` | enum `0`..`5` | `4` |
| "Custom maximal required texel size" | `unwrapMaxTexelSize` | float | `10` |

One key cannot be both. The 2.2 binary contains `unwrapMinTexelSizeType` and
`unwrapMaxTexelSizeType`, mirroring the `unwrapFixedTexelSize` / `unwrapFixedTexelSizeType`
pair exactly. **Reading:** the enum rows should say `unwrapMinTexelSizeType` /
`unwrapMaxTexelSizeType`; the float rows are correct as printed.
[CONTRADICTED: Help vs binary] [INFERRED] — confirm by exporting an AdaptiveTexelSize
preset from the GUI.

The same rows carry a second, independent copy-paste error: the *Custom minimal/maximal
required texel size* rows say `"unwrapStyle=FixedTexelSize"` and
`"unwrapFixedTexelSizeType =5"` in their "relevant for" notes, while their parent rows say
`"unwrapStyle=AdaptiveTexelSize"`. [OFFICIAL, self-contradictory]

### 13.7 `txtFillInUntextoredParts` — both spellings exist in the binary

The Help documents the typo'd `txtFillInUntextoredParts`. The 2.2 binary contains **both**
that string and the correctly spelled `txtFillInUntexturedParts`. Which one the engine
reads is [OPEN]. Prefer the documented (typo'd) spelling until a probe says otherwise.
[UNDOCUMENTED: binary]

### 13.8 `inpSkew` is listed for both Skew and Aspect ratio

`tutorials/editselectioncommand` gives `inpSkew` for `Prior calibration/Skew` **and** for
`Prior calibration/Aspect ratio`. The binary contains `inpAspect`. **Reading:** aspect ratio
is `inpAspect`. [CONTRADICTED: Help vs binary] [INFERRED]

### 13.9 Global-settings file extension

`.rcconfig` in `appbasics/allcommands` ("Export application global settings to the
settings.rcconfig file") **and** `appbasics/appsettings` (the GUI's own Global Settings
panel wording) vs `.rsconfig` in `tutorials/commandline_4` (same sentence, `.rsconfig`
substituted throughout). [CONTRADICTED, internal to the Help] Two topics to one favours
`.rcconfig`; the product rename makes `.rsconfig` the plausible newer name; neither
argument is decisive. [INFERRED] Settle it by exporting once. See §1.8 and Open
questions #2.

### 13.10 `appProcessActionTime` guidance conflicts with the CLI example

`appbasics/appsettings`: "For practical reasons, this value should be greater than 60."
`tutorials/commandline_5`: worked example sets `0` and explains "we are actually interested
in every single process." Production here uses `0`, with the known cost that internal
heartbeat processes also fire the trigger. [OFFICIAL, self-conflicting] [VERIFIED-as-policy]

### 13.11 `-preset` has no documentation of its own

The "Learn more about how to use this command here" link on the `-preset` row resolves to
`tutorials/setkeyvaluetable.htm` — the shared key table. No document states which keys
require `-preset`, and the only restart-requiring examples in the Help
(`appCacheLocation`, `appCacheCustomLocation`) are shown with `-set` + `appQuitOnReset`,
not with `-preset`. [VERIFIED: `<a href="../tutorials/setkeyvaluetable.htm">here</a>` read
directly from the `tr_seco_preset` row of `Help\en-US\tutorials\commandline_4.htm`] [OPEN]

### 13.12 `inpPose=3` is "Locked" in the Help and "Exact" in the runtime

`tutorials/editselectioncommand` maps `inpPose` `0`/`1`/`2`/`3` to Unknown / Position /
Position and orientation / **Locked**, and uses **Exact** only for
`inpPosePriorRelative=2`. But an `-align` on a scene whose cameras carry `inpPose=3`
refuses with: "prior set to **'Exact'** mode must be all aligned in a single run.
Incremental adding is not supported." The two vocabularies collide on the same state.
[CONTRADICTED: Help label vs runtime message] [VERIFIED: FINDINGS 2026-07-23, U18 FAIL]

### 13.13 `-set` has two different one-line descriptions in the Help

`appbasics/allcommands`: "Change an application setting." —
`tutorials/commandline_4` and `tutorials/commandline_5`: "Set an application state
variable." Harmless, but it is why the same command appears under two names in derived
notes. [OFFICIAL, self-inconsistent]

---

## 14. Complete alphabetical checklist

Completeness index. Four tiers, each independently exhaustive over its source, each list
alphabetised and de-duplicated **case-sensitively**. Tiers 1 and 2 are the keys with a
concrete file behind them. Tier 3 is the binary-derived candidate namespace — inclusion is
**not** proof that `-set` accepts the key. Tier 4 is a different command family entirely.

Note on case: several keys exist in both a lowercase and a capitalised form
(`mvsDecimationFactor` / `MvsDecimationFactor`, `mvsPreviewDownscaleFactor` /
`MvsPreviewDownscaleFactor`, `mvsImportMaxTrianglesPerPart` /
`MvsImportMaxTrianglesPerPart`). These are **distinct entries**, not duplicates — the
lowercase spelling is the one the Help documents.

### Tier 1 — documented `-set` keys (RealityScan 2.2 Help) — 100

99 in `tutorials/setkeyvaluetable` (App 20, Alignment 29, LiDAR-import 1,
Reconstruction 22, Color/Texture 24, Error-handling 3) plus `PrecomputeDepthmaps` from
`tutorials/commandline_2`.

```
allowReadOnly
appAutoClearCache
appAutoSaveCliHandling
appAutoSaveMode
appCacheCustomLocation
appCacheImageMetadata
appCacheLocation
appCopyImportedComponentsToCache
appGroupCalibrationByExif
appIgnoreExifGPS
appIncSubdirs
appLog
appMaxPointsToDisplay
appProcessAction
appProcessActionTime
appProcessExecCmd
appQuitOnError
appQuitOnReset
appThemeZoom
appUIAnim
colStyle
ImageLayerForColoring
ImageLayerForTexturing
lisPreferImagesAsFeatureSource
MvsDepthMapsLibVersion
MvsDoCorrectColors
MvsGeometryGpuAccel
MvsGeometryMarginStyle
MvsGeometryTexturingDoHdr
MvsIgnoreCorrectColors
mvsAdaptiveBlendingStart
mvsDecimationFactor
mvsDefaultGroupingFactor
mvsDefaultNoiseFactor
mvsFilteringRadius
mvsFilteringStrength
mvsImportMaxTrianglesPerPart
mvsLowTextureGroupingFactor
mvsLowTextureNoiseFactor
mvsMaxSampleDistanceLaserScan
mvsMaxVertexCountInPart
mvsMinIntensityLaserScan
mvsMinSampleDistance
mvsMinSampleDistanceLaserScan
mvsNormalDownscaleFactor
mvsPreviewDownscaleFactor
mvsPreviewMaxVetrexCountInModel
mvsPreviewMeshStrategy
mvsSmoothingWeight
operationLog
PrecomputeDepthmaps
sfmAutoReconRegionAfterAlignment
sfmCameraPriorAccuracyPitch
sfmCameraPriorAccuracyRoll
sfmCameraPriorAccuracyX
sfmCameraPriorAccuracyY
sfmCameraPriorAccuracyYaw
sfmCameraPriorAccuracyZ
sfmCameraPriorWeight
sfmCameraPriorWeightOrientation
sfmControPointImageMeasAccuracy
sfmControlPointXAccuracy
sfmControlPointYAccuracy
sfmControlPointZAccuracy
sfmDefinedDistanceAccuracy
sfmDetectorSensitivity
sfmDistortionModel
sfmEnableCameraPrior
sfmFeatureDetectionQuality
sfmFinalModelOptimizationDraftMode
sfmForceComponentRematch
sfmImageDownscaleFactor
sfmImageDownscaleFactorDraftMode
sfmImagesOverlap
sfmImagesOverlapDraftMode
sfmMaxFeatureReprojectionError
sfmMaxFeaturesPerImage
sfmMaxFeaturesPerMpx
sfmMergeGeoreferencedComponents
sfmPreselectorFeatures
suppressErrors
txtFillInUncoloredParts
txtFillInUntextoredParts
txtImageDownscaleColor
txtImageDownscaleTexture
txtImportDefaultTexResolution
txtMethod
txtRecolorAfterTexturing
txtStyle
unwrapFixedTexelSize
unwrapFixedTexelSizeType
unwrapGutter
unwrapLargeTriangleRemovalThr
unwrapMaxTexelSize
unwrapMaxTexResolution
unwrapMaximalTexCount
unwrapMinTexelSize
unwrapMinTexResolution
unwrapStyle
UserInterfaceLanguageId
```

### Tier 2 — keys with a concrete `<Configuration>` XML source, not in Tier 1 — 106

Sources: `RS_CLI/Metadata/*.xml` (34 GUI-exported files) and
`C:\Program Files\Epic Games\RealityScan_2.2\Settings\SimplifiedExport\*.xml` (3
Epic-shipped files). Those files carry 136 distinct `key=` names; 30 are already in
Tier 1, leaving the 106 below.

```
CoordinateSystemFlightLog
CoordinateSystemFlightLogType
csvFLIgn
csvFLSep
gpsLogFileFormat
ifCSopt
ifKGrp
ifKmode
ifUseOriAcc
ifUsePosAcc
ifuuInh
ifuuInhEn
ModelExportFormatVersion
MvsExportIsGeoreferenced
MvsExportIsModelCoordinates
MvsExportMoveX
MvsExportMoveY
MvsExportMoveZ
MvsExportNormalFlipX
MvsExportNormalFlipY
MvsExportNormalFlipZ
MvsExportNormalRange
MvsExportNormalSpace
MvsExportRotationX
MvsExportRotationY
MvsExportRotationZ
MvsExportScaleX
MvsExportScaleY
MvsExportScaleZ
MvsExportTransformationPreset
MvsExportcoordinatesystemtype
MvsMeshExportByParts
MvsMeshExportCameras
MvsMeshExportCamerasAllowed
MvsMeshExportCamerasAsModelPart
MvsMeshExportClassificationAllowed
MvsMeshExportColors
MvsMeshExportEmbeddTxrs
MvsMeshExportEmbeddTxrsAllowed
MvsMeshExportFileTypeSelectionDisplay
MvsMeshExportInfoFile
MvsMeshExportMaterials
MvsMeshExportMaterialsAllowed
MvsMeshExportNormals
MvsMeshExportNormalsAllowed
MvsMeshExportNumberFormat
MvsMeshExportNumberFormatAllowed
MvsMeshExportTexAlpha
MvsMeshExportTexImgFormat_Color8_0
MvsMeshExportTexImgFormat_Normal_0
MvsMeshExportTexImgFormat_no_alpha
MvsMeshExportTexOneFile
MvsMeshExportTexPixFormat_Color8_0
MvsMeshExportTexPixFormat_Normal_0
MvsMeshExportTexPixFormat_no_alpha
MvsMeshExportTexturing
MvsMeshExportTexturingAllowed
MvsMeshExportTexturing_Color8_0
MvsMeshExportTexturing_Normal_0
MvsMeshExportTileType
mvsFltBorderDecimationStyle
mvsFltMinEdgeLength
mvsFltReprojectColor
mvsFltReprojectNormal
mvsFltSimplificationType
mvsFltSmoothingStyle
mvsFltSmoothingType
mvsFltTargetTrisCountAbs
mvsFltTargetTrisCountRel
mvsFltUnwrapTexCount
mvsFltUnwrapTexSide
mvsSmoothing_useIntelligentSmoothing
reprojectionTool_allowColor
reprojectionTool_colorSampling
reprojectionTool_enableColor
reprojectionTool_enableDisplacement
reprojectionTool_normal
reprojectionTool_sourceColorLayer
reprojectionTool_supersampling
reprojectionTool_useCustomDistance
s235l
s236l
s237l
s251l
s252l
s253l
s254l
sfmBackgroundDetectFeatures
sfmBackgroundDetectThreadPriority
sfmCameraDepthmapWeight
sfmEnableAutoSuggestions
sfmGPUAcceleration
simplEqualizeDensity
simplPreserveParts
smoothIterations
smoothWeight
unwrapButtonDisabled
unwrapCheckerBoardCellSize
unwrapFillTextures
unwrapMethod
xmpCalibGroups
xmpCamera
xmpExGps
xmpFlags
xmpMerge
xmpRig
```

### Tier 3 — additional key-shaped identifiers in `RealityScan.exe` 2.2.0.119430 — 476

Not in Tier 1 or Tier 2. [UNDOCUMENTED] throughout: presence proves the string exists in
the build, nothing more. Report variables and identifiable UI ids were excluded where
recognisable, but some almost certainly remain.

**Amendment (verification pass):** ten `ifu*` flight-log prior-accuracy keys —
`ifuPosX`/`Y`/`Z`, `ifuPosXl`/`Yl`/`Zl`, `ifuRotY`/`P`/`R`, `ifuRotEnable` — were missing
from the original 466 and are added below. All ten were confirmed present in the executable
(UTF-16LE, both byte alignments) **and** in this machine's `appConfig` registry blob. See
§8.5. The tier is therefore **not** proven exhaustive; treat it as a floor.

```
appActivTokenCLI
appActivTokenCLIValid
appAutomaticUpdate
appAutoRenew
appAutoUpdate
appEnableBadCps
appExportSettings
appImportSettings
appInfMouse
appLanguage
appLic
appLicDel
appLicDelMachine
appLicenseAutoRenew
appName
appNavigationStyle
appOutputErrorStack
appProcessEmailAddres
appProcessEmailTempl
appProcessSoundTheme
appRenewT
appRootDir
appStartDir
appTheme
appTutorialMode
appType
appVersion
CacheCustomIsCDisk
cacheFolder
cacheLocation
CacheSwitchedToCustom
CacheSwitchedToSysTemp
ClassificationColorSourceParams
ClassificationFormat
classificationFormatExportExtension
classificationFormatExportPath
ClassificationLayer
ClassificationLayerId
ClassificationModelType
ClassificationParams
ClassificationPostprocessorSensitivity
ClassificationPostprocessorType
ClassificatorType
classification_aiOverrideKey
classification_classificationName
classification_classifyModelKey
classification_colorFromClassification
classification_formatIsEditable
classification_formatName
classification_groundSegmentVotingPowerKey
classification_presetPostprocessKey
classification_presetTypeKey
colmapDirStructure
colmapExportMasks
colmapFileType
colmapMaskExtension
colmapPointFiltering
CoordinateSystemDatabaseLruFile
CoordinateSystemDatabaseLruFile0
CoordinateSystemDatabaseLruFile1
CoordinateSystemDatabaseLruFile2
CoordinateSystemDatabaseLruFile3
CoordinateSystemDatabaseLruFile4
CoordinateSystemDatabaseLruFile5
CoordinateSystemDatabaseLruName
CoordinateSystemDatabaseLruName0
CoordinateSystemDatabaseLruName1
CoordinateSystemDatabaseLruName2
CoordinateSystemDatabaseLruName3
CoordinateSystemDatabaseLruName4
CoordinateSystemDatabaseLruName5
CoordinateSystemFlightLogUnits
csvCPMIgn
csvCPMSep
csvDDIgn
csvGCIgn
csvGCSep
gpsLogCameraAxes
gpsLogCustomFormat
gpsLogEulerAnglesOrderOPK
gpsLogEulerAnglesOrderYPR
gpsLogFileName
gpsLogFolder
gpsLogMount
ifDistortionmode
ifKModel
ifOfsRP
ifOfsRR
ifOfsRY
ifOfsX
ifOfsY
ifOfsZ
ifOfsifuUseOffset
ifRmode
ifTmode
ifuPosX
ifuPosXl
ifuPosY
ifuPosYl
ifuPosZ
ifuPosZl
ifuRotEnable
ifuRotP
ifuRotR
ifuRotY
LodSuffix
LodSuffixNumbering
LodType
lodAltitude
lodBandwidthScale
lodColorInputTextureLayer
lodCriterion
lodExportTexturingFalse
lodFilename
lodGzip
lodInitialSimplTargetPercentage
lodInitialSimplType
lodIsModelTextured
lodIterativeSimplTargetPercentage
lodIterativeSimplType
lodLargeTriangleRemovalThresh
lodMaxNodeTriangleCount
lodMaxTriangles
lodMinTriangles
lodMinTrianglesEnabled
lodModelCount
lodPath
lodPrimitive
lodSimplificationPercentage
lodSimplificationType
lodSuffixType
lodTexelSize
lodTexelSizeCustom
lodTexelSizeOptimal
lodTextureFormat
MvsColoringStyle
MvsColoringTexturingType
MvsColorReference
MvsDecimationFactor
MvsDepthMapAlgorithm
MvsDepthMapLayerProcessingType
MvsDepthMapQualityHigh
MvsDepthMapQualityNormal
MvsDepthMapQualityPreview
MvsDoColorNormalization
MvsDtmClasificationLayers
MvsDtmClassificationColorLayers
MvsExportAtlasDownscale
MvsExportFileType
MvsExportOrthoPhotoBackFaceColorType
MvsExportOrthoPhotoBackfaceColor
MvsExportOrthoPhotoBackfaceColorTransparency
MvsExportOrthoPhotoColorType
MvsExportOrthoProjectionCommandType
MvsExportOrtoPhotoHeight
MvsExportOrtoPhotoPixelSize
MvsExportOrtoPhotoShow
MvsExportOrtoPhotoWidth
MvsExportRandomPartColor
MvsExportTransformationPresetSelector
MvsExportcoordinatesystemtypeString
MvsFlyoverBackgroundColor
MvsFlyoverColorType
MvsFlyoverShadingType
MvsFlyoverVideoBitRate
MvsFlyoverVideoFPS
MvsFlyoverVideoFramesCountBetwTwoViews
MvsFlyoverVideoMaxFramesCount
MvsFlyoverVideoRandomPartColor
MvsFlyoverVideoResolution
MvsFlyoverVideoType
MvsGeometryColoringDoFillIn
MvsGeometryColoringImagesDownScale
MvsGeometryDetailAdaptationScale
MvsGeometryDetailAdaptationStart
MvsGeometryDetailMode
MvsGeometryFilteringRadius
MvsGeometryFilteringStrength
MvsGeometryGroupingFactorOfLowTexturedAreas
MvsGeometryIntermediateResultsPath
MvsGeometryLaserScanMaxSampleDistance
MvsGeometryLaserScanMinIntenity
MvsGeometryLaserScanMinSamplingDistance
MvsGeometryMinimalSampleDistance
MvsGeometryNoiseFactorOfLowTexturedAreas
MvsGeometryPhotoDepthmapNoise
MvsGeometryPhotoDepthmapQuality
MvsGeometryTexturingDoFillIn
MvsGeometryTexturingDoRecolor
MvsGeometryTexturingPhotoconsistencyBias
MvsGeomterySmoothingDiscontinuity
MvsGeomterySmoothingWeight
MvsHighQualityLevel
MvsImageLayerForColoring
MvsImageLayerForTexturing
MvsImageSmoothing
MvsImportMaxTrianglesPerPart
MvsImportMoveX
MvsImportMoveY
MvsImportMoveZ
MvsImportNormalFlipX
MvsImportNormalFlipY
MvsImportNormalFlipZ
MvsImportNormalRange
MvsImportNormalSpace
MvsImportRotationX
MvsImportRotationY
MvsImportRotationZ
MvsImportScaleX
MvsImportScaleY
MvsImportScaleZ
MvsImportcoordinatesystemtype
MvsLargeScaleDecimationFactor
MvsLargeScalePointsCountInCluster
MvsLimitedScaleDecimationFactor
MvsLimitedScaleMaxVertexCount
MvsMeshExportByPartsAllowed
MvsMeshExportCamerasVisible
MvsMeshExportClassificationLayer
MvsMeshExportColorInByte
MvsMeshExportColorInByteAllowed
MvsMeshExportColorSpace
MvsMeshExportColorsAllowed
MvsMeshExportColorsHaveQuality
MvsMeshExportColorsMapQuality
MvsMeshExportOneFileUsePow2TexSize
MvsMeshExportShowTileType
MvsMeshExportTexImgFormat
MvsMeshExportTexOneFileMaxResolution
MvsMeshExportTexPixFormat
MvsMeshExportTexToneMap
MvsMeshExportTextureLayersSubpanel
MvsModelImportColorSpace
MvsNormalQualityLevel
MvsNormalUndistMaxPixels
MvsOrthoCreateDtm
MvsPreviewDecimationFactor
MvsPreviewDownscaleFactor
MvsPreviewQualityLevel
MvsPreviewUndistMaxPixels
MvsSnapshotBackgroundColor
MvsSnapshotCenterX
MvsSnapshotCenterY
MvsSnapshotCenterZ
MvsSnapshotColorType
MvsSnapshotFileFormat
MvsSnapshotFocalLength35mm
MvsSnapshotLookAtX
MvsSnapshotLookAtY
MvsSnapshotLookAtZ
MvsSnapshotPitch
MvsSnapshotRandomPartColor
MvsSnapshotResolution
MvsSnapshotResolutionHeight
MvsSnapshotResolutionWidth
MvsSnapshotRoll
MvsSnapshotRotationInputType
MvsSnapshotShadingType
MvsSnapshotType
MvsSnapshotUpVectorX
MvsSnapshotUpVectorY
MvsSnapshotUpVectorZ
MvsSnapshotYaw
MvsTexturingStyle
MvsVisibilityRegionRange
mvsCNCurrentTexture
mvsCloneAndTexture
mvsColorize
mvsColorizePreview
mvsComputeDepthMapHigh
mvsComputeDepthMapNomal
mvsContinueCalculation
mvsDeleteIntermediateTextures
mvsExportTriangleMosStats
mvsExtractCpPatch
mvsFilterModelCachedDepthMap
mvsFltAverageEdgeLength
mvsFltAverageEdgeLengthThr
mvsFltEqualizeDensity
mvsFltMarkLargeTriangles
mvsFltMarkMarginalTriangles
mvsFltMarkSmallTriangles
mvsFltMinComponentSize
mvsFltOpCalculate
mvsFltOpEstimate
mvsFltPreserveParts
mvsFltProcessing
mvsFltSimplify
mvsFltSmoothingWeight
mvsFltSmootingIters
mvsFltSmoth
mvsFltTargetTrisCount
mvsFltUnwrapMaxTexSideCustom
mvsFltUnwrapMinTexSideCustom
mvsFltUnwrapTexCountCustom
mvsGPUAcceleration
mvsMaxPointsToDisplay
mvsMaxTrianglesToDisplay
mvsMergedDownscaleCutoff
mvsNormalizeImages
mvsOrthoColormap
mvsOrthoColormapOthersAllWhite
mvsPptClean
mvsPptCloseHoles
mvsPptColorizeGridBoundary
mvsPptColorizeModelByTexelSize
mvsPptCreatePartExternalTriangles
mvsPptDecomposeModel
mvsPptGenerateDtm
mvsPptGenerateDtmAncestorRatio
mvsPptGenerateDtmChildRatio
mvsPptGenerateDtmDoGrid
mvsPptGenerateDtmGridSize
mvsPptGenerateDtmMaxArea
mvsPptGenerateDtmMinArea
mvsPptHardCrash
mvsPptIIUClusters
mvsPptInflateFraction
mvsPptInspectTopology
mvsPptMaxTrisPerPart
mvsPptMergeSiblingParts
mvsPptOrthoColorFromMosaicing
mvsPptOrthoDilateColor
mvsPptOrthoDilateDepth
mvsPptOrthoErodeColor
mvsPptOrthoErodeDepth
mvsPptOrthoPushPullColorSource
mvsPptOrthoPushPullColorTiled
mvsPptOrthoPushPullDepthSource
mvsPptOrthoPushPullDepthTiled
mvsPptPartExtenderAllCriteria
mvsPptSpreadDistance
mvsPptSpreadFactor
mvsPptTargetTrisCount
mvsPptTexelSize
mvsPptTopologicalDistance
mvsPptTrisMos
mvsPptUndercut
mvsPptUnwrapCheck
mvsPptVetMos
mvsPptVetVis
mvsPptduplicate
mvsPreferOldRasterizer
mvsRR_COORD
mvsRR_COORDInput
mvsRR_COORDPrimeMeridian
mvsRR_COORDProjection
mvsRR_COORDType
mvsRR_COORDUnits
mvsRR_COORDWkt
mvsRR_COORDWktCheckProj
mvsRR_OffsetBtn
mvsRR_OffsetX
mvsRR_OffsetY
mvsRR_OffsetZ
mvsRR_PosLat
mvsRR_PosLon
mvsRR_PosX
mvsRR_PosY
mvsRR_PosZ
mvsRR_RotX
mvsRR_RotY
mvsRR_RotZ
mvsRR_ScaleX
mvsRR_ScaleY
mvsRR_ScaleZ
mvsRR_UseRelativeVals
mvsRR_displayCoordSystem
mvsRefineDepthMapsHigh
mvsRemoveTextures
mvsShowDepthMapLayer
mvsSpaceSigma
mvsTexture
mvsTexture2
mvsTextureResolution
mvs_estimateDepthmapScale
OrthoDirection
OrthoIsolinesPixelType
OrthoMosaicContextAddCameras
OrthoMosaicCorrectionToolConsumer
OrthoMosaicingAlgorithm
OrthoMosaicingLayerCount
OrthoMeasurementsToolConsumer
OrthoVolumeUserHeightCommand
OrthoVolumeVisibilityCommand
orthoArea
orthoArea2D
orthoArea3D
orthoBackFaceColorType
orthoBackfaceColor
orthoBackfaceColorTransparency
orthoColorType
orthoHeight
orthoIsGeoreferenced
orthoIsolinesCompute
orthoIsolinesInterval
orthoIsolinesLayer
orthoIsolinesLayerAlternative
orthoIsolinesMax
orthoIsolinesMin
orthoIsolinesUnits
orthoIsolinesUnitsAlternative
orthoModelIsClassified
orthoModelIsTextured
orthoPixelSize
orthoProjName
orthoProjectionArea2D
orthoProjectionArea3D
orthoProjectionColorType
orthoProjectionCount
orthoProjectionCutVolume
orthoProjectionDeleteEmpty
orthoProjectionFillVolume
orthoProjectionHasDtm
orthoProjectionHeight
orthoProjectionIsGeoreferenced
orthoProjectionIsMosaic
orthoProjectionMorePhases
orthoProjectionRenderEmpty
orthoProjectionRenderEmptyPanel
orthoProjectionTimeDtm
orthoProjectionTimeMosaic
orthoProjectionTimeRasterize
orthoProjectionTimeTotal
orthoProjectionType
orthoProjectionUPPX
orthoProjectionUPPY
orthoProjectionWidth
orthoSamplingCoordinateSystem
orthoSamplingDistance
orthoSamplingPointsCount
orthoSamplingRawSize
orthoVolume1obpOption
orthoVolumeCut
orthoVolumeFill
orthoVolumeObpType
orthoVolumeObpsOption
orthoVolumePossible
orthoVolumeState
orthoVolumeSubtype
orthoVolumeUserHeight
orthoVolumeUserHeightMode
orthoVolumeUserHeightUnits
orthoVolumeUserHeightValue
orthoWidth
orthoprojectiondistance
reprojectionTool_customDistance
reprojectionTool_reprojectModelBtn
reprojectionTool_resultModel
reprojectionTool_sourceModel
sfmAlgorithm
sfmFinalModelOptimization
sfmMergeComponenetsOnly
sfmSBPTRemoveCameras
simplTargetTrisCount
simplType
simplUseLegacyAlgorithm
simplValueAbs
simplValueRel
simplifyChecked
simplifyEx
smoothFactor
txtCount
txtFillInUntexturedParts
unwrapCalc
unwrapCheckerBoardCellCount
unwrapCsUnitsLongName
unwrapFChecks
unwrapFillTexWithCheckerboard
unwrapFillTexWithCheckerboardYesNo
unwrapMaxTexelSizeType
unwrapMinTexelSizeType
unwrapOptimalTexelSize
unwrapUseLegacyAlgorithm
unwrapUseLegacySimplifyAlgorithm
unwrapUseLegacyUnwrapAlgorithm
```

A small number of binary strings named in prose above are deliberately **excluded** from
Tier 3 as recognisable UI-element ids rather than settings: `appBtnGPUs`, `gpuId`, `gpuUn`,
`appConfig`, `appSharedConfig`, and the snake_case report variables (`align_*`,
`unwrap_fill_with_charts`, `unwrap_grid_size_cells`, `gpu_count`, `gpu_names`).

### Tier 4 — selection-edit key spaces (different commands) — 68

`-editInputSelection` (49 documented + binary siblings), `-editControlPointSelection`,
`-editConstraintSelection`, `-editOrthoProjectionSelection`. See §9. **These are not `-set`
keys.**

```
aligFeaturesMode
cA
cB
cEnabled
cName
cValue1
cValue1Acc
gpEnabled
gpName
gpP1
gpP2
gpP3
gpType
gpWeight
gpuP1
gpuP2
gpuP3
inpAspect
inpCalibration
inpCalibrationGroup
inpColorNorm
inpColorRef
inpDistortion
inpDistortionModel
inpEnabled
inpFocal
inpImageColorsWeight
inpImageDepthMapDownscale
inpLensGroup
inpMaskOpts
inpMeshing
inpPPX
inpPPY
inpPose
inpPosePriorAbsoluteCs
inpPosePriorAbsoluteCsInput
inpPosePriorAbsoluteCsType
inpPosePriorAbsoluteCsWkt
inpPosePriorAccuracyMode
inpPosePriorRelative
inpPosePriorRelativeGroup
inpPriorAccuracyInh
inpRadial1
inpRadial2
inpRadial3
inpRadial4
inpRig
inpRigId
inpRigIndex
inpRigInstance
inpRx
inpRy
inpRz
inpSkew
inpTangential1
inpTangential2
inpTexturing
inpTx
inpTy
inpTz
inpVisible
inpuRx
inpuRy
inpuRz
inpuTx
inpuTy
inpuTz
orthoProjectionName
```

### Totals

| Tier | What | Count |
|---|---|---|
| 1 | Settings keys documented as usable with `-set` in the RealityScan 2.2 Help | **100** |
| 2 | Additional keys with a concrete `<Configuration>` XML source (Epic-shipped presets or GUI-exported params files) | **106** |
| 3 | Additional key-shaped identifiers in `RealityScan.exe` 2.2.0.119430 | **476** (466 + the 10-key `ifu*` amendment) |
| — | **Settings-namespace subtotal (Tiers 1–3, case-sensitive unique)** | **682** |
| 4 | Selection-edit keys (a different command family) | **68** |
| — | **Grand total, all key spaces (case-sensitive unique)** | **750** |

Tiers 1 and 2 are exhaustive over their sources and were re-counted against them in this
verification pass. **Tier 3 is a floor, not a census** — the `ifu*` amendment proves the
extraction missed at least one whole family, and a second evidence layer (the `appConfig`
registry blob, §1.6) contains tokens that appear in no tier at all, e.g. `appBtn1`.

Of the 100 documented keys, **31 are set in production by this repo**: 8 `app*`
(`appAutoSaveMode`, `appQuitOnError`, `appProcessActionTime`, `appProcessAction`,
`appProcessExecCmd`, `appCacheLocation`, `appCacheCustomLocation`, `appIncSubdirs`),
22 `sfm*`, and 1 `lis*` — plus 5 undocumented `sfm*` keys (`sfmGPUAcceleration`,
`sfmBackgroundDetectFeatures`, `sfmBackgroundDetectThreadPriority`,
`sfmEnableAutoSuggestions`, `sfmCameraDepthmapWeight`). `AlignmentParams.xml` holds 35
entries: 27 `sfm*`, 1 `lis*`, and 7 `s<NNN>l` entries that are configured but **filtered
out and never applied** (§13.3).

---

## Open questions

Every [OPEN] item in this document, with the cheapest probe that would answer it. Ordered
by value.

| # | Question | Cheapest probe |
|---|---|---|
| 1 | **Is there any oracle for "the engine READ this key"?** Two storage read-backs now exist — `-exportGlobalSettings` and the `appConfig` registry blob (§1.6) — but neither answers the question, because the config layer demonstrably persists key names the executable does not contain (`ifKmode`). `err:7155` fires only on a malformed pair | Storage question (cheap, minutes): `-exportGlobalSettings a.rcconfig` → `-set "<key>=<value>"` → `-exportGlobalSettings b.rcconfig` → diff; or just re-read `appConfig` before/after. **Consumption question (the one that matters): per-key behavioural A/B on the miniature fixture.** Downgraded from the previous claim that the diff probe would settle dozens of rows — it settles only that they parse |
| 2 | Is the exported global-settings extension `.rcconfig` or `.rsconfig`? Two topics say `.rcconfig` (`appbasics/allcommands`, `appbasics/appsettings`), one says `.rsconfig` (`tutorials/commandline_4`) | Run the export with no extension and read the produced filename. Seconds |
| 2a | Does the exported `.rcconfig` contain readable key names, i.e. is it the same serialisation as `appConfig`? If so it is directly diffable and no parser is needed | Export once and open the file |
| 3 | Which keys actually require `-preset` rather than `-set`, and does `-preset` behave differently at all? | Run `-preset "appCacheLocation=Custom"` at startup and compare against the documented `appQuitOnReset` + `-set` dance: does the app quit? |
| 4 | Which settings beyond `appCacheLocation` / `appCacheCustomLocation` are restart-class? | Set candidates with `appQuitOnReset=true` and see which invocations quit |
| 5 | **`sfmMergeGeoreferencedComponents` — was the feature's premise ever met?** D1/D2 fed it components georeferenced from position-only priors at 10 m claimed accuracy; RS may distinguish prior-weighted from control-locked georeferencing | Re-run the D1/D2 pair with priors-v2 (orientation + tight accuracies) components. Queued as a PD follow-on cell, never run |
| 6 | What exactly does RealityScan's `Finalizing N` log line count? (It disagreed with a "successful, zero-loss" merge — 8 disjoint objects) | Construct a scene with a known component count, merge, read the line |
| 7 | Which detector id corresponds to Help's `High` and which to `Normal`? Only `RealityScan.FeatureDetector.RSa1` and `…TB` are in the UTF-16LE settings pool, but **eight** detector ids exist in the binary (§13.2) — so "there are only two to choose from" is itself unproven | Toggle the GUI dropdown, re-export the Alignment panel, read the value; then try `-set "sfmFeatureDetectionQuality=High"` and re-export to see whether the name form is accepted at all |
| 8 | Do the `s<NNN>l` ids really occupy the camera-prior / control-point accuracy slots? | `-set "sfmCameraPriorAccuracyZ=99"`, re-export the panel, see which entry became `99` |
| 9 | Does applying the *intended* accuracies (5.0 / 5.0 / 0.5 m) change registration, now that §13.3 shows they never shipped? | Add the three `-set "sfmCameraPriorAccuracy{X,Y,Z}=…"` lines and re-run one zone (~70 min) against the recorded baseline |
| 10 | Is `sfmCameraPriorWeight=10.0` right? Never A/B'd | Two runs of the miniature fixture at `1.0` and `10.0`, judged on registered-camera census |
| 11 | Is `sfmDetectorSensitivity=Ultra` right on turbid imagery? A staff caution exists that Ultra manufactures noise points; no Ultra-vs-High A/B has been run on this rig | Miniature-fixture A/B at `Ultra` vs `High` |
| 12 | Does `sfmImageDownscaleFactor` > 1 help or hurt on 12 MP underwater stills? Pinned at `1` and never varied | Miniature-fixture A/B at `1` vs `2` |
| 13 | PD-6 attribution: Division vs the accuracy columns vs orientation-prior removal — which caused the scale repair? | A Brown3 + explicit-loose-priors isolation cell on zone_1 (~70 min); designed, never run |
| 14 | What does `sfmCameraDepthmapWeight` (pinned `0.05`, undocumented) weight? | A/B on the smoke fixture at `0.05` vs `0.5`; or probe #1 to confirm the key is even read |
| 15 | Are the params-XML key families (`mvsFlt*`, `xmp*`, `if*`, `Mvs*Export*`, `ortho*`, `lod*`, `classification*`) accepted by `-set` at all? | Probe #1 on one key from each family |
| 16 | Which of `txtFillInUntextoredParts` (documented, typo'd) and `txtFillInUntexturedParts` (binary, correct) is live? | Probe #1 on both |
| 17 | Are the AdaptiveTexelSize enum selectors really `unwrapMinTexelSizeType` / `unwrapMaxTexelSizeType`? | Export an AdaptiveTexelSize preset from the GUI Unwrap dialog and read the key names |
| 18 | Is aspect ratio `inpAspect` rather than the Help's duplicated `inpSkew`? | `-editInputSelection "inpAspect=1.01"` on one image, `-exportXMP`, read the aspect back |
| 19 | What are the value mappings for `ifKGrp` (calibration group mode) and `ifKmode` — the flight-log dialog's *Euler angles order* and *Camera mount*? Neither string is in any install file; `ifKmode` is not even in the binary | (a) Set both dropdowns in the GUI Import Trajectory dialog, save params, diff against the current template — one minute, needs the GUI. (b) Headless: align the smoke fixture at several `ifKmode` values and read camera attitudes out of the pose XMPs (~2 min/cell). Neither run |
| 20 | Is there a `-set` key for **GPUs to use**? The GUI has the control; only `appBtnGPUs` / `gpuId` were found | Change the GUI selection and diff an exported `.rcconfig` |
| 21 | Is there a `-set` key for **Prefer Exif over XMP**? Directly load-bearing for a sidecar-driven pipeline | Same GUI-diff probe |
| 22 | Is there a `-set` key for **Use relative image paths**? | Same GUI-diff probe |
| 23 | Is *Maximal depth-map pixel count* `MvsPreviewUndistMaxPixels` / `MvsNormalUndistMaxPixels`? | Same GUI-diff probe |
| 24 | Is there a key for the LiDAR *Filtering based on classification* control? | Same GUI-diff probe |
| 25 | Does `mvsPptInspectTopology` expose Check Topology, which has no CLI command? | Probe #1 on the key, then run a model op and look for a topology report |
| 26 | Does `appCopyImportedComponentsToCache=true` interact with the relocated-component hang (hard rule 7)? | Set it, import a component from its original location, then from a copy; watch for `#timeout` |
| 27 | Can headless RS 2.2 hit a licence prompt or expiry that manifests as a silent hang? `appActivTokenCLI` / `appActivTokenCLIValid` exist; two years of production recorded no licensing interaction — absence of evidence only | No probe designed. Watch for a boot that never reaches `-getStatus` ready |
| 28 | Would `appOutputErrorStack=true` de-genericise `0x8000FFFF`? | Set it, trigger a known failure (a deliberately malformed `-set`), read `RealityScan.log` |
| 29 | Do two concurrent instances share settings state, and does one instance's `-quit` clobber the other's `-set` values on write-back? | Boot RS1 and RS2, `-set "sfmDetectorSensitivity=Low"` on RS1 only, `-exportGlobalSettings` from each, diff |
| 30 | Does a `-set` value survive `-newScene`? (Assumed yes from global storage, never isolated) | `-set`, `-newScene`, probe #1 |
| 31 | `lisPreferImagesAsFeatureSource` — pinned `false`, never probed (wave-3 cell E3) | Only matters if LiDAR enters the pipeline; skip until then |
| 32 | Image Layers (`ImageLayerForColoring` / `ImageLayerForTexturing`) has never been exercised through this CLI, yet it is the agreed eventual mechanism for "align on originals, texture from enhanced" | Build a two-layer scene on the miniature fixture and set the two keys |
| 33 | The `mvs*` reconstruction family is never pinned — `GenerateModel.bat` meshes on instance defaults. Standing gap, not a decision | Pin the 22 documented `mvs*` keys in a params replay analogous to `AlignmentParams.xml` |
| 34 | `-selectImage` regexp dialect: the Help documents regexp + set operators; only literal full paths select anything here. This gates how selections for `-editInputSelection` are composed | Forum-mine for a staff reply (standing follow-up since 2026-07-23); or bisect the dialect further |
| 35 | What does `mvsFltSimplificationType=3` mean? Epic's shipped `simplify.xml` uses it and carries **both** `…TargetTrisCountAbs` and `…TargetTrisCountRel`; this repo only ever uses `0`↔Abs and `1`↔Rel | Run `-simplify` with Epic's shipped preset on the miniature model and count output triangles against 1,000,000 and against 10% |
| 36 | Do the `ifu*` import-accuracy keys (`ifuPosX/Y/Z`, `ifuRotY/P/R`, `ifuRotEnable`) actually carry the Import Trajectory accuracy block, and do they override or compose with the global `sfmCameraPriorAccuracy*` keys? Both families are currently unset in production (§8.5, §13.3) | Set the Import Trajectory accuracy fields in the GUI, save the params, and diff against the current `FlightLogParams.xml` — one minute, needs the GUI |
| 37 | How did `ifKmode` get into `appConfig` when the string is not in the executable — params-XML import, GUI dialog, or a runtime-composed name? Determines whether the storage layer accepts *arbitrary* keys | Re-read `appConfig`, `-set "zzTestKeyNotReal=1"` on a live instance, re-read. If it appears, the storage layer accepts anything and no read-back is ever evidence of consumption |
| 38 | **Does ordinal `N` really mean the `N`-th row of a string enum?** Proven only for `appProcessAction`. Epic's `unwrapStyle=1` example is weak counter-evidence (it co-occurs with `unwrapMaximalTexCount=1`, a key relevant only to `MaxTexturesCount`) | `-set "unwrapStyle=1"`, export the Unwrap panel from the GUI, read whether it says `FixedTexelSize` or `MaxTexturesCount`. Until then use the **name** form |
