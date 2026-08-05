# CLI fundamentals: invocation, instances, delegation, lifecycle

This document covers everything needed to *start* RealityScan from a command line and keep
deterministic control of it: executable discovery, command-line grammar and quoting, startup
switches, the headless/GUI distinction, named instances and the delegation model, the
`-waitCompleted` / `-getStatus` synchronisation contract, verified shutdown, the progress-file
format, the process-completion trigger, exit codes and crash artifacts, RealityScan's own log,
licensing constraints, multi-GPU pinning, and cache/disk behaviour. It does **not** cover what the
individual work commands do — alignment, components, merging, georeferencing, reconstruction,
export — nor the `-set` key space beyond the handful of `app*` keys that govern process lifecycle.
For those see the sibling documents in this reference set: the command inventory
(`02-command-reference.md`), the settings-key inventory (`03-settings-keys.md`), and the
XML parameter-file reference (`09-xml-parameter-files.md`). The harness patterns built on
top of this execution model — `:run`, marker-file ownership, stall detection, checkpoint
and rollback — are in `11-automation-patterns.md`; the numbered failure catalogue that
cites this document's codes and races is `12-failure-modes-and-race-conditions.md`.

**Applies to:** RealityScan 2.2 (Epic Games), Windows, headless CLI operation.
Build actually measured here: `RealityScan.exe` FileVersion `2.2.0.119430.RS`,
ProductVersion `2.2.0.119430`
[VERIFIED-by-inspection: `(Get-Item 'C:\Program Files\Epic Games\RealityScan_2.2\RealityScan.exe').VersionInfo`,
2026-08-04].

**Tags:** [OFFICIAL] shipped Help · [VERIFIED] measured in production here ·
[CONTRADICTED] docs vs observation · [UNDOCUMENTED] · [INFERRED] · [OPEN]

---

## Contents

1. [The executable](#1-the-executable)
2. [Command-line grammar](#2-command-line-grammar)
3. [Startup switches](#3-startup-switches)
4. [Headless vs GUI-visible](#4-headless-vs-gui-visible)
5. [Named instances and the delegation model](#5-named-instances-and-the-delegation-model)
6. [Synchronisation: `-waitCompleted`, `-getStatus`, and the `:run` pattern](#6-synchronisation--waitcompleted--getstatus-and-the-run-pattern)
7. [Instance lifecycle: boot, reuse, verified shutdown](#7-instance-lifecycle-boot-reuse-verified-shutdown)
8. [The progress file (`-writeProgress`)](#8-the-progress-file--writeprogress)
9. [The process-completion trigger (`appProcessAction` family)](#9-the-process-completion-trigger-appprocessaction-family)
10. [Result codes, exit codes, crash artifacts](#10-result-codes-exit-codes-crash-artifacts)
11. [RealityScan's own log](#11-realityscans-own-log)
12. [Licensing, accounts, online communication](#12-licensing-accounts-online-communication)
13. [Multi-GPU and instance pinning](#13-multi-gpu-and-instance-pinning)
14. [Cache location and disk behaviour](#14-cache-location-and-disk-behaviour)
15. [Minimum viable headless session](#15-minimum-viable-headless-session)
16. [Annotated production boot sequence](#16-annotated-production-boot-sequence)
17. [Failure-signature quick reference](#17-failure-signature-quick-reference)
18. [Open questions](#18-open-questions)

---

## 1. The executable

### 1.1 Location and discovery

There is one binary for everything: `RealityScan.exe`. The Help's examples use
`C:\Program Files\Epic Games\RealityScan\RealityScan.exe` (unversioned)
[OFFICIAL: tutorials/commandline]; real installs of 2.2 are versioned.

Discovery order used in production here, newest first — this exact list is the one that has been
exercised on the production box [VERIFIED: `modules/realityscan_interface/realityscan_cli.py`
`EXECUTABLE_CANDIDATES`; `RS_CLI/Scripts/SetVariables.bat`]:

| # | Candidate path |
|---|---|
| 1 | `C:\Program Files\Epic Games\RealityScan_2.2\RealityScan.exe` |
| 2 | `C:\Program Files\Capturing Reality\RealityScan 2.2\RealityScan.exe` |
| 3 | `C:\Program Files\Epic Games\RealityScan_2.1\RealityScan.exe` |
| 4 | `C:\Program Files\Capturing Reality\RealityScan 2.1\RealityScan.exe` |
| 5 | `C:\Program Files\Epic Games\RealityScan_2.0\RealityScan.exe` |

Override order in the Python layer: `realityscan.executable` in `rs_settings.json` → `RS_EXECUTABLE`
environment variable → the table above. The `.bat` layer checks `RS_EXECUTABLE` first, then the same
table [VERIFIED: `realityscan_cli.py:find_executable`, `SetVariables.bat`].

Install root of the measured build: `C:\Program Files\Epic Games\RealityScan_2.2\`. Notable contents
used elsewhere in this reference: `Help\en-US\**` (the shipped documentation), the schema XMLs
(`flightlogs.xml`, `sensorsdb.xml`, `epsg.xml`, `calibration.xml`, …), `Settings\SimplifiedExport\*.xml`,
`Reports\`, `Templates\`, and `RSNode.exe`.

### 1.2 Putting it on PATH

```bat
set PATH=%PATH%;C:\Program Files\Epic Games\RealityScan_2.2\
RealityScan.exe -load ... -quit
```

The `set PATH` addition lasts only for that command-line session [OFFICIAL: tutorials/commandline].

### 1.3 Related executables — and the absence of `-listen`

`RealityScan.exe` has **no** `-listen` switch, and no listening/daemon switch of any name. The
substring `listen` occurs in exactly two places in the whole shipped Help text — both in
`tools/apinode`, describing the RSNode connection-info schema fields ("Local IPv4 address on which
RSNode listens", "Port on which RSNode listens"). It appears in no command table.
[OFFICIAL-absence: exhaustive `grep -ri listen` over the converted 2.2 Help tree, 2026-08-04]
[OPEN, §18-Q14: absence from the Help is not proof the parser rejects it; the decisive probe is one
`RealityScan.exe -listen` invocation, checking `errors_<inst>.txt` for an `0x82000060`
unknown-command result.]

Network-driving RealityScan is done by a *separate* binary, `RSNode.exe`, a system service that
exposes a REST-like API and can run CLI commands inside a RealityScan session
[OFFICIAL: tools/api]:

```bat
"C:\Program Files\Epic Games\RealityScan_2.2\RSNode.exe" -hostAddress 192.168.0.74 -port 7878 -landingPage "\/static/MyApp.html"
```

Auth is a Bearer HTTP Authorization header carrying a GUID token, which is delivered as a GET
parameter when the landing page is opened; the connection is not secured, so Epic scopes it to a
private LAN [OFFICIAL: tools/api]. CLI commands are issued as
`GET /project/command?name=<cmd>&param1=…&param9=…` — nine optional positional parameters, and the
call returns `202 Accepted` with a `taskID`, i.e. it is asynchronous like `-delegateTo`. A
conditional variant `GET /project/condcommand` also exists. Both are GET only in 2.2; no POST form
is documented. [OFFICIAL: tools/apiproject] **RSNode has never been used in this repository** — every
fact about it here is [OFFICIAL] only, none is [VERIFIED].

---

## 2. Command-line grammar

### 2.1 Shape

```
"<path>\RealityScan.exe" -command1 [param …] -command2 [param …] … -quit
```

- Every command starts with a **single** hyphen; parameters follow, space-separated
  [OFFICIAL: tutorials/commandline].
- Commands execute **in sequence, left to right**, as arguments of one process; the effect is the
  same as invoking the same features from the GUI [OFFICIAL: tutorials/commandline].
- The same command set is available in the GUI's console view command field (ENTER executes,
  TAB cycles completions, a tooltip shows required/optional parameters), and from a `.rscmd` file
  [OFFICIAL: tools/commandsequence, tutorials/commandline_rscmd].

Command-name case: the Help itself is inconsistent — `appbasics/allcommands` prints `execRSCMD`
while `tutorials/commandline_rscmd` prints `execrscmd`, and `-exportUndistortedImages`
(master table) appears as `-exportUndistoredImages` in `tutorials/commandline_1`
[CONTRADICTED, internal to the shipped Help]. Whether the parser is case-insensitive is
untested here — **always type the exact camelCase spelling from the master table**
(see `02-command-reference.md`). That the Help ships a working example using `-execrscmd`
while the master table spells it `execRSCMD` is weak evidence that parsing is case-insensitive
(Epic would not ship a broken example), but it is an inference, not a test. [INFERRED] [OPEN, §18-Q1]

### 2.2 Line continuation and comments

- `.bat` and `.rscmd`: `^` at end of line continues one RealityScan command sequence onto the next
  line (with or without a space before `^`) [OFFICIAL: tutorials/commandline, commandline_rscmd].
- Lines beginning with `#`, `//`, `REM`, `rem` are skipped
  [OFFICIAL: tutorials/commandline, commandline_rscmd].
- In an `.rscmd` file, commands may be one per line with no continuation character at all
  [OFFICIAL: tutorials/commandline_rscmd].

### 2.3 `.rscmd` files, arguments, and variables

```bat
"C:\Program Files\Epic Games\RealityScan_2.2\RealityScan.exe" -execRSCMD D:\MyFolder\addFolder.rscmd "D:\MyFolder\Images"
```
```
:: addFolder.rscmd
-addFolder $(arg1)
```

- `.rscmd` (legacy `.rccmd` also accepted) files can also be drag-and-dropped onto the application
  [OFFICIAL: tutorials/commandline_rscmd].
- Argument count is **contradicted inside the Help**: `appbasics/allcommands` says "up to nine
  arguments … `$(arg1)`–`$(arg9)`"; `tutorials/commandline_rscmd` says "up to 10 arguments … the
  first argument and path to the executed file is required", referencing `$(arg0)`–`$(arg9)`.
  Both pages ship in the same build. [CONTRADICTED] [OPEN, §18-Q2]
- Global variables inside an `.rscmd`: `$(appRootDir)` (install folder), `$(appStartDir)` (folder the
  `RealityScan.exe` was launched from, e.g. the `.bat`'s folder), `$(cmdStartDir)` (folder holding the
  `.rscmd`), `$(arg1)`…`$(arg9)`. Quote them when used as path arguments — an unquoted path with
  spaces is split into separate parameters [OFFICIAL: tutorials/commandline_rscmd].
- A loop construct exists: `$For( "i", 1, 1, 3, … )` — right-open interval, given step
  [OFFICIAL: tutorials/commandline_rscmd].
- `-execRSCMDIndirect <instance|*> <commands.rscmd>` is the delegated twin
  [OFFICIAL: appbasics/allcommands].

**This repository does not use `.rscmd` at all** — every workflow is a `.bat` file issuing
`-delegateTo` commands one at a time, because per-command error checking and the double-wait pattern
(§6.3) need control flow between commands.

### 2.4 Quoting — the single most expensive trap

`=` , `;` and `,` are cmd token delimiters. A `key=value` pair that reaches a `.bat` file **as an
argument** is split into two arguments, and Python's `subprocess` quotes only on whitespace, so the
pair silently arrives split. RealityScan then logs
`Parsing setting key=value 'sfmMergeGeoreferencedComponents' failed [err:7155]` and `'false' failed`,
**applies nothing**, and the parse failures land in the errors marker file — aborting the workflow
that carried them. Consequence in this repo: no flag-sweep cell before wave 1f had ever applied its
flags. [VERIFIED: NA167 B5 / FINDINGS 2026-07-23]

Rules that follow, all mandatory here:

1. Write `-set "key=value"` with the quotes **inside** the RealityScan invocation. Never pass the
   pair as a `.bat` argument.
2. When a pair must cross a `.bat` boundary, encode it `key:value` and convert inside the script:
   ```bat
   :applySet
   set "kv=%~1"
   set "kv=%kv::==%"
   %RealityScan% -delegateTo %RS_INSTANCE% -set "%kv%"
   exit /b 0
   ```
   [VERIFIED: `RS_CLI/Scripts/MergeZoneComponents.bat`]
3. Lists never cross as arguments — they cross as **files**: `.complist` (component paths, one per
   line) and `.imagelist` (image paths, one per line). This is codified as hard rule 8 in
   `CLAUDE.md`. [VERIFIED: NA167 B5]
4. Quote any path that may contain spaces, including inside `appProcessExecCmd`. An unquoted exe
   path in that key silently disabled **all** error detection when the checkout path contained
   spaces. [VERIFIED: HANDOFF overhaul item 4, 2026-07-21]

A related encoding trap on the file side: `Set-Content -Encoding utf8` in Windows PowerShell 5.1
writes a BOM, and a BOM on line 1 of a `.complist` silently invalidates the first entry. Write such
files from Python (`encoding='utf-8'`, no BOM) or with
`[System.IO.File]::WriteAllLines($p,$lines,(New-Object System.Text.UTF8Encoding($false)))`.
[VERIFIED: FINDINGS 2026-07-27]

### 2.5 `.bat` mechanics that bite (Windows substrate)

| Trap | Effect | Mitigation |
|---|---|---|
| LF-only line endings in a `.bat` | cmd's `call :label` search is byte-offset sensitive; the same `call :run` resolved ten times then failed with "The system cannot find the batch label specified - run" | All workflow `.bat` files must be CRLF; this repo's `.gitattributes` pins `*.bat text eol=crlf` **and** `*.vbs text eol=crlf` (the hook shim is edited by tooling too) [VERIFIED: NA167 B10; `.gitattributes`] |
| `exit /b N` inside a multi-statement parenthesised block | returns 0 to the process caller | single-line chains or `goto :fail` |
| MSYS/Git Bash invoking a `.bat` | mangles cmd switches (`/c` → `C:\`) | invoke via PowerShell, `cmd //c`, or (as the Python layer does) `subprocess.Popen([script_path] + args)` with no explicit `cmd /c` prefix [VERIFIED: `realityscan_cli.py` comment] |
| Console-subsystem children under a windowless parent | each pops a visible console window — hundreds over a long run | `CREATE_NO_WINDOW` on every helper subprocess; a GUI-subsystem host (`wscript.exe`) for hooks fired by RealityScan [VERIFIED: FINDINGS 2026-07-23] |

### 2.6 What happens on argument errors

There is no documented behaviour for malformed arguments. Observed:

| Situation | Observed behaviour | Tag |
|---|---|---|
| Unknown command (e.g. `-selectAllComponents`, which does not exist in 2.2) | process result `0x82000060`, reported through the completion hook; the sequence continues | [VERIFIED: NA167 #13 / B2, 2026-07-23] |
| `-set` pair split by cmd | `err:7155` in `RealityScan.log`, setting **not** applied, failure result code in the errors marker | [VERIFIED: NA167 B5] |
| Extra/unsupported parameter on a command that takes none (e.g. `-align "params.xml"`) | argument **silently ignored**, command runs on current settings | [VERIFIED: FINDINGS 2026-07-21] |
| Selection command with a name that does not resolve (e.g. `-selectModel` on a renamed-away model) | `2147942487` = `0x80070057` `E_INVALIDARG`, "in 0 seconds"; `err:5601` in the log | [VERIFIED: FINDINGS 2026-07-29] |
| Selection/rename/delete command on an empty scene | **silent no-op**, no errors marker at all (except the rename, which reports `E_INVALIDARG`) | [VERIFIED: FINDINGS 2026-07-23/24] |
| Delegating to an instance that has died | the *delegating* process exits non-zero and the `.bat` prints `ERROR: Failed to delegate command: …` — this is the signature of a dead instance, not a rejected operation | [VERIFIED: FINDINGS 2026-07-26] |

**Design consequence:** loop terminals must be file-existence checks, never error checks, because
the most common terminal states are silent. [VERIFIED: FINDINGS 2026-07-23]

---

## 3. Startup switches

### 3.1 Reference table

| Switch | Parameters | Startup-only? | What it does | Source |
|---|---|---|---|---|
| `-headless` | — | **Yes** | Hides the UI; a system-tray icon replaces it, one per instance, numbered | [OFFICIAL: tutorials/headless, appbasics/allcommands] |
| `-hideUI` | — | No | Hides the UI; does **not** suppress actions requiring user interaction | [OFFICIAL: appbasics/allcommands] |
| `-showUI` | — | No | Shows a hidden UI | [OFFICIAL: appbasics/allcommands] |
| `-setInstanceName` | `instanceName` | Not stated; [INFERRED: effectively yes] | Names this instance for delegation. Name cannot contain spaces. The Help's own example is a bare `RealityScan.exe -setInstanceName RS1`, i.e. a launch | [OFFICIAL: tutorials/commandline_deleg, appbasics/allcommands] |
| `-silent` | `crashReportPath` | **Yes** — "This command has to be used at the startup" | Suppresses warning dialogs and crash-report uploads; writes minidumps to the given folder | [OFFICIAL: appbasics/allcommands] |
| `-writeProgress` | `fileName` `[timeout]` | No, but used at boot | Appends every progress change to a file; the optional timeout (seconds) also emits periodic records | [OFFICIAL: tutorials/commandline_5, commandline_4, appbasics/allcommands] |
| `-printProgress` | `[timeout]` | No | Same, to the Command Prompt | [OFFICIAL: tutorials/commandline_5, commandline_4] |
| `-stdConsole` | — | No | Mirrors the application console to the standard Windows console; "enables further redirections for CLI purposes" | [OFFICIAL: tutorials/commandline_5, commandline_4] |
| `-tag` | `string` | No | Writes the string to the Command Prompt, ordered after the preceding process completes | [OFFICIAL: tutorials/commandline_5, appbasics/allcommands] |
| `-newScene` | — | No | Creates a new empty scene. Usually unnecessary at launch — the app starts with one | [OFFICIAL: tutorials/commandline] |
| `-load` | `MyProject.rsproj` `[recoverAutosave\|deleteAutosave]` | No | Loads a project; the optional parameter decides autosave handling | [OFFICIAL: appbasics/allcommands] |
| `-save` | `[MyProject.rsproj]` | No | Saves in place, or save-as to the given path | [OFFICIAL: appbasics/allcommands] |
| `-quit` | — | No | Quits the application | [OFFICIAL: appbasics/allcommands] |
| `-disableOnlineCommunication` | — | [INFERRED: yes] | Disables any online communication | [OFFICIAL: tutorials/commandline_4, appbasics/allcommands] |
| `-importGlobalSettings` / `-exportGlobalSettings` | `settings.rcconfig` | No | Import/export application global settings | [OFFICIAL: appbasics/allcommands] |
| `-set` | `"key=value"` | No | Set an application state variable | [OFFICIAL: tutorials/commandline_4, commandline_5, appbasics/allcommands] |
| `-preset` | `"key=value"` | **Yes** — "during the setup phase" | Change a setting that would otherwise require an application reset. **Unused here; no key list is documented** | [OFFICIAL: tutorials/commandline_4, commandline_5] [OPEN, §18-Q13] |
| `-reset` | `ui\|cfg\|cfgui\|all` | Not stated | Resets UI / settings / both / to clean-install state. **"Works only when used in a batch file, and it won't work with delegation commands"** — the Help says batch-only, *not* startup-only | [OFFICIAL: appbasics/allcommands, tutorials/commandline_4, commandline_5] |

Global-settings file extension is [CONTRADICTED] inside the Help: `.rcconfig`
(`appbasics/allcommands` command table, `appbasics/appsettings` GUI description) vs `.rsconfig`
(`tutorials/commandline_4` command table). Both pages ship in this build. Untested here — the
`-exportGlobalSettings` probe in §18-Q9 settles it as a side effect.

One error-handling **setting** belongs beside these switches and is easy to miss because it has no
`app` prefix: `suppressErrors` (bool, default `false`) — "Suppress error messages"
[OFFICIAL: tutorials/commandline_5, tutorials/setkeyvaluetable]. It is **not** used in this
repository: suppressing the message would not suppress the non-zero result code that the completion
hook records, and untested interactions with headless mode are not worth the risk. [VERIFIED-as-absent:
`startRealityScan.bat` sets only `appAutoSaveMode`, `appQuitOnError`, `appProcessActionTime`,
`appProcessAction`, `appProcessExecCmd` and optionally the two cache keys]

### 3.2 `-silent <dir>`

`-silent` does three things that matter headless:

1. Redirects crash-report minidumps to `<dir>` instead of opening the upload wizard
   [OFFICIAL: tutorials/commandline_5].
2. Suppresses warning dialogs [OFFICIAL: appbasics/allcommands]. `tutorials/commandline_4` describes
   only the report-location half; treat the fuller description as correct.
   [CONTRADICTED-adjacent, internal to the Help]
3. **Auto-answers modal prompts that would otherwise block** — including ones whose default answer
   changes the outcome. A selection-driven XMP export under `-silent` completed in 0.057 s instead of
   20.5 s and exported **nothing**, because the "Export Selection" dialog was auto-answered while a
   flight-log import had left images selected. `-deselectAllImages` before exports is therefore
   mandatory. [VERIFIED: FINDINGS 2026-07-23] [UNDOCUMENTED: the Help does not warn that `-silent`
   silently changes export scope]

Verification that minidumps really land at the `-silent` path: `RealityScanCrash-20260726-054742.dmp`
(1,477,291 bytes) plus a sibling `RealityScanCrash-20260726-054742.dmp.metadata` are present in
`modules/realityscan_interface/RS_CLI/Errors/`, which is exactly the `%ErrorPath%` passed to
`-silent` at boot. [VERIFIED-by-inspection, 2026-08-04]

### 3.3 `-writeProgress <file> <timeout>`

See §8 for the file format. Production boot value here:

```bat
-writeProgress "%ErrorPath%\progress_%RS_INSTANCE%.txt" 600
```

The file is namespaced per instance, so parallel instances can never read each other's state
[VERIFIED: `startRealityScan.bat`, `realityscan_cli.py:_marker`].

### 3.4 `-stdConsole` — present, deliberately unused here

`-stdConsole` was **removed from this repo's boot line on 2026-07-23**: it allocates a console
window per instance boot and nothing reads the instance's stdout — progress comes from
`-writeProgress`, per-operation results from the completion hook. [VERIFIED: `startRealityScan.bat`
comment + FINDINGS]. The switch itself is live in the product; the removal is a local policy, not a
defect.

### 3.5 `-newScene`, `-load`, and autosave handling

- `-load <project> deleteAutosave` deletes an existing `.autosave` and loads the original;
  `recoverAutosave` opens the autosave instead [OFFICIAL: appbasics/allcommands, appbasics/autosave].
- The global equivalent is `-set "appAutoSaveCliHandling=delete|recover|abort|ask"`, default `delete`
  [OFFICIAL: tutorials/setkeyvaluetable]. Note `abort` and `ask` have no `-load` parameter
  counterpart — the parameter form offers only `recoverAutosave` and `deleteAutosave`
  [OFFICIAL: appbasics/allcommands]. `ask` is the value that will hang a headless run: it opens the
  Recover / Delete / Ignore dialog [OFFICIAL: appbasics/autosave]. Never set it on an unattended box.
- **`appAutoSaveMode` is a bool whose app default is `true`** [OFFICIAL: tutorials/setkeyvaluetable] —
  i.e. autosave is ON unless you turn it off, which is why the boot line below pins it to `false`
  rather than relying on a default.
- A stale `<name>.rsproj.new` sitting beside a project makes `-load` emit warning-class
  `0x82000017` while still completing — enough to abort an errors-marker-gated workflow.
  [VERIFIED: FINDINGS 2026-07-29]
- Autosave writes `<project_name>.autosave` next to the project **plus** a part in the resource
  cache; for a never-saved project everything goes to the cache at
  `C:\Users\<user>\AppData\Local\Temp\RealityScan` (instance 1), `RealityScan-1` (instance 2),
  `RealityScan-2`, `RealityScan-3` [OFFICIAL: appbasics/autosave]. Autosave fires 30 s after a change
  (interval not configurable), or immediately when a high-cost operation such as Align Images or
  Normal Detail reconstruction starts, which overrides the 30 s interval. During reconstruction it
  additionally autosaves each completed model part to the resource cache 15 minutes after that part
  finishes. It recovers only *completed* processes — a run killed mid-texturing recovers nothing.
  [OFFICIAL: appbasics/autosave]
- Production policy here: `-set "appAutoSaveMode=false"` at boot. Reasons: autosave would race the
  destructive in-session identity loop, and a modal recovery dialog hangs a headless box. No stale
  autosaves appeared in any test run under this setting.
  [VERIFIED: HANDOFF verification checklist item 7, 2026-07-21]

---

## 4. Headless vs GUI-visible

`-headless` must be given at startup. The Help never says so in the `headless` row itself — it says so
by contrast, in the `hideUI` and `showUI` rows: "Unlike headless, this command doesn't need to be run
at startup" [OFFICIAL: appbasics/allcommands, tutorials/commandline]. Up to four instances can run at
once, each with its own numbered tray icon. Tray icon states: a blue arc around the icon = active
process with percentage progress; yellow background = paused; red background = an error occurred.
Right-click gives Show App / About / Exit — and "Show App" toggles the mode back on at will, so a
headless instance is one click away from being a visible one. [OFFICIAL: tutorials/headless]

**RealityScan *leaves* headless mode when:** user interaction is needed, any pop-up window opens, or
an error is displayed. Most of these can be suppressed with `-silent` or
`-set "appQuitOnError=true"` — **but some cannot, explicitly including the log-in window.**
[OFFICIAL: tutorials/headless]

What that means operationally:

- Headless is a *UI-visibility* mode, not a *no-interaction guarantee*. A machine driven headless can
  still end up with a modal on screen and an instance that never completes its queued command.
- The CLI has no way to observe that state. Detecting it requires a human glance or a screenshot.
  This is the single largest item on this pipeline's blindness list: **semantic and modal state is
  invisible to the CLI while every command still "succeeds"**. [VERIFIED-as-policy: CLAUDE.md,
  research working agreement §1.2]

GUI-visible operation for debugging: this repo's boot script honours `RS_HEADLESS=0`, which blanks
the `-headless` flag; delegation and monitoring work identically with the UI visible
[VERIFIED: `SetVariables.bat`]:

```bat
set RS_HEADLESS_FLAG=-headless
if /I "%RS_HEADLESS%"=="0" set RS_HEADLESS_FLAG=
```

`-hideUI` / `-showUI` toggle visibility at any time but do **not** suppress interaction-requiring
actions, so they are not substitutes for `-headless` in an unattended run
[OFFICIAL: appbasics/allcommands].

---

## 5. Named instances and the delegation model

### 5.1 The instance model

| Fact | Detail | Source |
|---|---|---|
| Max concurrent instances | **4** | [OFFICIAL: tutorials/commandline_deleg, tutorials/headless] |
| Naming | `-setInstanceName RS1`; **name cannot contain spaces** | [OFFICIAL: tutorials/commandline_deleg] |
| Wildcard target | `*` = the first instance found | [OFFICIAL: tutorials/commandline_deleg] |
| Same project in two instances | requires `-set "allowReadOnly=true"` | [OFFICIAL: tutorials/setkeyvaluetable] |
| Delegate commands | `-setInstanceName`, `-delegateTo`, `-waitCompleted`, `-getStatus`, `-pauseInstance`, `-unpauseInstance`, `-abortInstance`, `-execRSCMDIndirect` | [OFFICIAL: appbasics/allcommands] |
| Commands that do **not** work with delegation | `-reset` ("works only when used in a batch file, and it won't work with delegation commands"), `-printReport` ("can be used when RealityScan is run with a batch file. It does not work with delegation") | [OFFICIAL: appbasics/allcommands; `-reset` also tutorials/commandline_4 + commandline_5; `-printReport` also tutorials/commandline_3] |
| Instance-name collision | not documented. Two processes given the same `-setInstanceName` — behaviour unknown | [OPEN, §18-Q15] |

### 5.2 What delegation actually does

```bat
RealityScan.exe -delegateTo RS1 -add D:\datasets\test\img001.JPG
RealityScan.exe -delegateTo * -align
```

Each `-delegateTo` invocation is a **separate, short-lived `RealityScan.exe` process** that hands a
command to the named running instance and exits. Two properties govern everything built on it:

- **Delegated commands are QUEUED, FIFO.** The delegating process returns at hand-over, **not** at
  completion. [VERIFIED: NA167_SESSION_NOTES §1; HANDOFF 2026-07-21; corroborated by every production
  run]
- **FIFO ordering is guaranteed**, so an instant command (`-set`) delegated immediately before a long
  one is guaranteed to execute first — no wait is needed between them. This is why the repo can fire
  `-set "appIncSubdirs=true"` and then `-addFolder` without synchronising in between.
  [VERIFIED: `AlignZone.bat`; production runs]

The Help does not state the queueing/return semantics at all; it only says "delegate a command or a
sequence of commands". [UNDOCUMENTED]

**Epic's own worked example omits synchronisation entirely** — and it is worth understanding why it
appears to work. `tutorials/commandline_deleg` EXAMPLE 3 is, in full:

```bat
start RealityScan.exe
TIMEOUT 2
for /l %%A in (1,5,100) do (
RealityScan.exe -delegateTo * -add D:\datasets\test\img%%A.JPG
)
RealityScan.exe -delegateTo * -align
RealityScan.exe -delegateTo * -save d:\datasets\test\processed\scene.rsproj
RealityScan.exe -delegateTo * -quit
```

There is no `-waitCompleted` anywhere, no error check, and readiness is a fixed `TIMEOUT 2`. It
survives only because the queue is FIFO — `-save` executes after `-align` because it was queued
after it, not because anything waited. Two consequences for real work: (a) the `TIMEOUT 2`
readiness assumption fails on any machine where startup takes longer, which is why this repo polls
`-getStatus` for up to 120 s instead (§7.2); (b) the sample gives the calling script **no** way to
learn that `-align` failed — the `.bat` exits believing it succeeded. Do not use this shape for
anything unattended. [OFFICIAL: tutorials/commandline_deleg] [VERIFIED-as-inadequate: the `:run`
pattern in §6.3 exists precisely because this shape was the starting point]

### 5.3 Instance identity is load-bearing — a real incident

`RS_INSTANCE` was **not** an input to the Python execution layer until 2026-07-28: `RealityScanCLI`
resolved the instance from constructor arg → `rs_settings.json` → default, and only ever *wrote* the
env var for the `.bat` layer. A cross-session probe therefore ran on `RS1` while believing it was
isolated on `RS2`, and could have `-quit` a live production instance.
[VERIFIED: FINDINGS 2026-07-28]

Current resolution order (fixed): constructor argument → `RS_INSTANCE` env var →
`rs_settings.json` `realityscan.instance_name` → `RS1`
[VERIFIED-by-inspection: `realityscan_cli.py:__init__`].

**Rule:** before any mutating command, prove which instance you are on. `-getStatus <name>` is the
only query available (§6.4).

### 5.4 One orchestrator per instance name

The Python layer takes a per-instance lock file `RS_CLI/Errors/<instance>.lock` containing the
holder's PID, created with `O_EXCL`. A stale lock is removed only after the recorded PID is proven
dead by `tasklist /FI "PID eq <pid>" /NH /FO CSV` with an exact field comparison — a substring check
would match PID 123 against 1234 and silently steal a live lock.
[VERIFIED-by-inspection: `realityscan_cli.py:_acquire_lock`, `_pid_alive`]

---

## 6. Synchronisation: `-waitCompleted`, `-getStatus`, and the `:run` pattern

### 6.1 `-waitCompleted <instance|*>` — documented vs observed

- **Docs:** "Pause execution of other commands until the current process is finished in a specified
  instance." [OFFICIAL: tutorials/commandline_deleg]
- **Observed:** it returns **prematurely** when issued *before* the instance has picked the queued
  command up. The delegating process has already returned (§5.2), so a `-waitCompleted` fired
  immediately after can find the instance idle and return at once, and the workflow races ahead of an
  operation that has not started. Hit in production. [CONTRADICTED / VERIFIED: FINDINGS
  "RealityScan 2.2 CLI behavior", 2026-07-21; NA167_SESSION_NOTES §1]

### 6.2 Why a single wait cannot be repaired by a longer sleep

The failure is a *pickup* race, not a *duration* race: no fixed delay is provably long enough,
because pickup latency depends on what the instance is currently doing. The mitigation is
structural — wait twice, with grace periods, so that the second wait is guaranteed to be issued
after the instance has certainly picked the command up. [VERIFIED-as-design: CLAUDE.md hard rules;
`RS_CLI/Scripts/*.bat`]

### 6.3 The `:run` pattern — the canonical synchronisation primitive

Every operation in every workflow script goes through this subroutine. Reproduced verbatim from
`RS_CLI/Scripts/AlignZone.bat` [VERIFIED-by-inspection]:

```bat
:: :run - delegate one operation to %RS_INSTANCE%, wait for it to finish,
:: and fail if RealityScan reported an error. Delegated commands are
:: queued and -waitCompleted can return prematurely when it runs before
:: the instance picks the queued command up: grace delay, then two
:: -waitCompleted calls with a second grace between them. Do NOT gate on
:: results log growth (heartbeat processes also write it).
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

Element by element:

| Line | Purpose |
|---|---|
| `-delegateTo %RS_INSTANCE% %*` | hand the command over; non-zero errorlevel here means the instance is **dead**, not that the command failed |
| `ping -n 3 127.0.0.1 >nul` | ~2 s grace (cmd has no sub-second sleep; `ping -n N` sleeps N−1 s) so the instance can pick the command up |
| first `-waitCompleted` | blocks; may still return early |
| `ping -n 2 127.0.0.1 >nul` | ~1 s grace |
| second `-waitCompleted` | the load-bearing wait |
| errors-marker size check | the per-operation success oracle (§9); a non-empty `errors_<instance>.txt` aborts the workflow |

**Never gate completion on the results log growing** — RealityScan emits periodic internal heartbeat
processes through the same completion trigger, so "the results log grew" does not mean "our command
finished". A completion check built on results-log growth raced ahead of a running `-align` and was
removed entirely. [VERIFIED: HANDOFF 2026-07-21; FINDINGS]

**Never infer completion from process names.** The pre-2.x code polled `tasklist` for
`RealityCapture.exe` and silently matched nothing once the executable became `RealityScan.exe`.
[VERIFIED: CLAUDE.md hard rule 2]

Tolerant variants of `:run` exist for operations with a **known, expected** failure code; they match
the specific numeric code, **move** (not delete) the errors marker to a named evidence file, and
continue. Two are in production [VERIFIED-by-inspection: `MergeZoneComponents.bat`]:

| Subroutine | Tolerated code | Meaning | Evidence file |
|---|---|---|---|
| `:run_geoimport` | `2181038335` (`0x820000FF`) | flight-log rows reference images not in the scene (`err:18002`); the trajectory still imports for every present image | `expected_18002_<instance>.txt` |
| `:run_peelrename` | `2147942487` (`0x80070057`) | `-renameSelectedComponent` on an emptied scene — the *terminal signal* of the component peel loop; exits `2`, not `1` | `expected_peelend_<instance>.txt` |

Moving rather than deleting preserves the evidence while leaving a clean marker for the next `:run`.
This is the correct pattern for any expected-failure tolerance: match the exact code, never a
wildcard.

**A third tolerant handler in this repo does not follow that rule, and you should know before you
copy it.** `ExportDeliverables.bat:try_delete_model` wraps a `-selectModel` / `-deleteSelectedModel`
pair and, on *any* non-empty errors marker, moves it to
`expected_select_<instance>_<model>.txt` / `expected_delete_<instance>_<model>.txt` and continues —
it never inspects the code. That is deliberate (the residual-model sweep probes names that may or may
not exist, and the expected miss is `E_INVALIDARG`), but it means a genuine failure inside that
sweep is filed as "expected" and never surfaces. It also flattens spaces in the model name into `_`
so nine sweep iterations cannot overwrite each other's evidence files.
[VERIFIED-by-inspection: `ExportDeliverables.bat` lines 114–143] [OPEN, §18-Q16]

### 6.4 `-getStatus <instance|*>`

Two distinct uses, one documented and one not:

- **Documented:** returns the progress status of the running process, printed in the form
  `id:0x10001 progress:57.5% runtime:4.26sec endEstimation:3.40sec`, and redirectable:
  `RealityScan.exe -getStatus * > D:\statusreport.txt` [OFFICIAL: tutorials/commandline_deleg].
  Note the Help says the result appears "in the console of that specific instance" while also giving
  a redirect example on the *calling* process — the two statements are hard to reconcile.
  [CONTRADICTED-adjacent] This repository has never parsed `-getStatus` stdout (it is sent to
  `DEVNULL`), so the redirect behaviour is untested here. [OPEN, §18-Q3]
  **The `id:` field is printed in HEX while the progress file writes the same identifier in
  DECIMAL.** The Help's own example prints `id:0x10001`; `0x10001` = 65537 = `ALIGN_NORMAL`, and
  `65537` is exactly what appears in the first column of a real `progress_<instance>.txt` during an
  alignment. Do not compare the two representations without converting.
  [OFFICIAL: tutorials/commandline_deleg example + tutorials/processids]
  [VERIFIED-by-inspection: `RS_CLI/Errors/progress_RS2.txt` contains 29 records with algId `65537`]
- **Undocumented and load-bearing:** **errorlevel is 0 if and only if the instance exists.** This is
  the readiness test at boot and the shutdown verification at teardown.
  [UNDOCUMENTED / VERIFIED: `startRealityScan.bat`, `realityscan_cli.py:is_instance_running`]
  Note for anyone reading the repo's own notes: `testing/NA167_SESSION_NOTES.md` §1 presents this
  errorlevel contract under the label "Official". It is not — the shipped Help documents `-getStatus`
  only as returning a progress status, and says nothing about the exit code. The behaviour is real,
  the provenance label in that file is wrong. [CONTRADICTED, internal to this repo]

**The teardown/file-handle race.** `-getStatus` reports an instance "gone" **seconds before** the
process actually exits and releases its file handles — specifically the `-writeProgress` marker.
The next workflow's marker clear raced that teardown and failed to delete a file Windows still
considered open. [VERIFIED: NA167 #14 / B3, 2026-07-23]

Mitigation, per marker file, in `RealityScanCLI._clear_markers`: retry deletion for up to **60 s**,
sleeping 2 s between attempts, and only then raise
[VERIFIED-by-inspection: `realityscan_cli.py:_clear_markers`]:

```python
for kind in ('progress', 'errors', 'results'):
    deadline = time.monotonic() + 60
    path = self._marker(kind)
    while os.path.isfile(path):
        try:
            os.remove(path); break
        except OSError:
            if time.monotonic() > deadline:
                raise RuntimeError(f'Cannot clear marker file {path} - it is still held open after 60s …')
            time.sleep(2)
```

A `-getStatus` call that itself hangs is treated as "instance exists" (conservative), with a 60 s
subprocess timeout: `STATUS_CALL_TIMEOUT_SECONDS = 60`
[VERIFIED-by-inspection: `realityscan_cli.py`].

### 6.5 Process control: pause, unpause, abort

`-pauseInstance`, `-unpauseInstance`, `-abortInstance`, each taking `instanceName|*`. Intended for
render-farm priority juggling. **`-abortInstance` aborts not only the running process but every
subsequent process in a CLI-driven sequence** [OFFICIAL: tutorials/commandline_deleg,
appbasics/allcommands]. None of the three is used in this repository — no empirical data.

---

## 7. Instance lifecycle: boot, reuse, verified shutdown

### 7.1 Boot

One long-lived headless instance is started, then every operation is delegated into it. Boot is a
single `start ""` invocation carrying the switches and the `app*` settings (§16), followed by a
readiness poll.

### 7.2 Readiness polling

```bat
set /a startTries=0
:waitStart
%RealityScan% -getStatus %RS_INSTANCE% >nul 2>&1
IF /I "%ERRORLEVEL%" NEQ "0" (
    set /a startTries+=1
    if %startTries% GEQ 120 (
        echo ERROR: RealityScan instance %RS_INSTANCE% did not become ready within 120 seconds
        exit /b 1
    )
    ping -n 2 127.0.0.1 >nul
    goto :waitStart
)
```

Bound: **120 tries at ~1 s = ~120 s**. This is one of only two time bounds in the whole system.
[VERIFIED-by-inspection: `startRealityScan.bat`]

### 7.3 Reuse of a running instance

`startRealityScan.bat` branches on `-getStatus` errorlevel 0 and, if the instance is alive, reuses it:

```bat
%RealityScan% -delegateTo %RS_INSTANCE% -newScene -deleteAutosave
```

Two notes on this branch:

- When workflows are driven through `RealityScanCLI.run_batch_script`, this branch is **effectively
  unreachable**: the Python layer shuts down any pre-existing instance *before* launching the `.bat`,
  precisely because a leftover instance may be hours into an old operation with the marker hooks
  still armed. Attaching would queue behind that work and mix its results into the new run.
  [VERIFIED-by-inspection: `realityscan_cli.py:run_batch_script`]
- `-deleteAutosave` is passed here as a **standalone command**. The Help documents `deleteAutosave`
  only as an optional *parameter of `-load`*, and there is no `-deleteAutosave` command in the master
  table. Whether it is accepted, ignored, or reported as an unknown command has never been observed —
  the branch is not exercised in the Python-driven path. [OPEN, §18-Q4]

### 7.4 Shutdown and shutdown verification

Every workflow ends by delegating `-quit`, both on the success path and in `:fail`:

```bat
%RealityScan% -delegateTo %RS_INSTANCE% -quit
exit /b 0
```

`:fail` quits **without saving**, so a failed run leaves the project on disk intact
[VERIFIED: FINDINGS 2026-07-26]. Quit-without-save leaves an `.rsproj` bundle **byte-stable** across
load/delete/export cycles — hash-verified twice; this is what makes the destructive in-session
identity harvest safe. [VERIFIED: FINDINGS, cells U15/U16, 2026-07-23]

Shutdown is then **verified**, not assumed: poll `-getStatus` until it reports the instance gone.
The orchestrator refuses to start the next workflow if verification fails, because a live instance
may still hold the scene. [VERIFIED-by-inspection: `realityscan_cli.py:wait_for_instance_shutdown`,
`run_batch_script`]

### 7.5 Time bounds — the complete list

| Bound | Value | Where | Status |
|---|---|---|---|
| Startup readiness | 120 s (120 tries × ~1 s) | `startRealityScan.bat` | [VERIFIED] |
| Shutdown verification | `SHUTDOWN_VERIFY_TIMEOUT_SECONDS = 900` (overridable via `rs_settings.json` `realityscan.shutdown_timeout`) | `realityscan_cli.py` | [VERIFIED] |
| `-getStatus` subprocess call | `STATUS_CALL_TIMEOUT_SECONDS = 60` | `realityscan_cli.py` | [VERIFIED] |
| Stall **warning** (not a kill) | `STALL_WARNING_SECONDS = 2 * 60 * 60` | `realityscan_cli.py` | [VERIFIED] |
| Progress poll interval | `PROGRESS_POLL_SECONDS = 2.0` | `realityscan_cli.py` | [VERIFIED] |
| Resource-trace sample interval | `RESOURCE_SAMPLE_SECONDS = 30.0` | `realityscan_cli.py` | [VERIFIED] |
| Low-memory warning threshold | `LOW_MEMORY_WARN_GB = 4.0` | `realityscan_cli.py` | [VERIFIED] |
| **Overall operation timeout** | **none, by design** | CLAUDE.md hard rule 3 | [VERIFIED] |

10+ hour operations are normal at production scale: the eight-step model recipe on the 3,738-camera
H2023 hull component completed in **384.1 min** [VERIFIED: FINDINGS 2026-07-26], and the sequential
three-zone grow to 4,131 images (strategy B, 3,906 registered = 94.6 %) took **444 min** against
**169 min** for the equivalent joint align (strategy C) [VERIFIED: NA167 #19, FINDINGS 2026-07-24].
Startup and shutdown are the only bounds. [CLAUDE.md hard rule 3]

**Internal inconsistency to be aware of:** `CLAUDE.md` documents the shutdown bound as 300 s while
the code uses 900 s. The code is authoritative for behaviour; the prose is stale.
[CONTRADICTED, internal to this repo: `realityscan_cli.py` lines 190–191 vs `CLAUDE.md` hard rule 3]

Shutdown timing has only ever been verified on **small** scenes. The bound for a 4,000+ camera scene
is untested. [OPEN, §18-Q5]

---

## 8. The progress file (`-writeProgress`)

### 8.1 Format

Five whitespace-separated columns, one record per line [OFFICIAL: tutorials/commandline_5]:

```
algId  progress  duration  estimation  eventType
```

| Column | Meaning |
|---|---|
| `algId` | process ID — the numeric identifier of the running algorithm; full table in [OFFICIAL: tutorials/processids] |
| `progress` | number in ⟨0,1⟩ indicating the stage of the process |
| `duration` | elapsed time in seconds |
| `estimation` | estimated remaining time in seconds |
| `eventType` | one of `#started`, `#progress`, `#timeout`, `#completed` |

The Help's own sample and the production files agree exactly on shape: five space-separated fields,
the fifth carrying a leading `#`. The Help writes the eventType set as `{started, progress, timeout,
completed}` in prose but every literal record shows the `#` prefix [OFFICIAL: tutorials/commandline_5].

Real production output — the exact first four and last four lines of
`RS_CLI/Errors/progress_RS1.txt` (algId `20532` = `PROJECT_LOAD`)
[VERIFIED-by-inspection, 2026-08-04]:

```
20532 0.00 0.00 20.22 #started
20532 0.01 1.87 184.42 #progress
20532 0.02 1.98 97.49 #progress
20532 0.03 2.10 67.45 #progress
... (595 lines omitted)
41064 0.00 0.02 0.00 #started
41064 1.00 0.02 0.00 #completed
21856 0.00 0.03 0.00 #started
21856 1.00 0.03 0.00 #completed
```

Note the shape of a *fast* process: `#started` at fraction 0.00 immediately followed by `#completed`
at 1.00, with no `#progress` records at all. Only long processes produce a `#progress` stream — in
this 603-line file, 252 processes produced 252 `#started` + 252 `#completed` records and just 99
`#progress` records, all 99 belonging to the single `PROJECT_LOAD`.

**`#completed` does NOT mean the process succeeded.** In this file all 62 `21856` processes emit
`#started` at 0.00 and `#completed` at fraction **1.00**, while the completion hook records every
single one of that algId's 101 runs in the same session set with result code `2147942487`
(`E_INVALIDARG`) — i.e. total failures. The progress stream carries **no** result channel at all;
success/failure exists only in `results_<instance>.log` / `errors_<instance>.txt` (§9).
Any monitor that treats `#completed` as "operation succeeded" is wrong.
[UNDOCUMENTED — the Help never states what eventType means for a failed process]
[VERIFIED-by-inspection: `progress_RS1.txt` × `results_RS1.log`, 2026-08-04]

Two `algId` values appearing in these real files are **absent from the shipped process-ID table**:
`21856` (immediately below the documented `21857 CLI_SELECT_COMPONENT`; it appears 101 times in
`results_RS1.log`, every occurrence paired with result code `2147942487`, i.e. the failing
`-selectModel` calls — so `21856` is almost certainly `CLI_SELECT_MODEL`) and `21896` (8
occurrences, always result 0, always at session boundaries).
[UNDOCUMENTED: absent from tutorials/processids]
[INFERRED: the `21856` = select-model identification, from co-occurrence with `-selectModel`
failures; settled by delegating a single `-selectModel` to an idle instance and reading the one
new progress line]

algIds actually observed in this repo's two shipped progress files, with their documented names
[OFFICIAL: tutorials/processids unless marked]:

| algId | Name | Where seen |
|---|---|---|
| `20532` | `PROJECT_LOAD` | `progress_RS1.txt` |
| `20533` | `PROJECT_SAVE` | `results_RS1.log` |
| `20594` | `IMPORT_COMPONENT` | `progress_RS2.txt` (182 records) |
| `20598` | `IMPORT_FLIGHT_LOG` | `progress_RS2.txt`; the `expected_18002_RS1.txt` evidence file |
| `21856` | *(undocumented; inferred `CLI_SELECT_MODEL`)* | both |
| `21859` | `CLI_RENAME_SELECTED_COMPONENT` | `expected_peelend_RS1.txt` |
| `21896` | *(undocumented; session-boundary)* | `results_RS1.log` |
| `41061` / `41063` / `41064` | `EXPORT_REGISTRATION_FILE` / `_PREPROCESS` / `_FINALIZE` | both |
| `65537` | `ALIGN_NORMAL` | `progress_RS2.txt` (29 records) |
| `6` | `EXPORT_MODEL` | `results_RS1.log` |

### 8.2 What `#timeout` actually means

Mechanism, from the switch's own definition: the optional `timeout` argument makes RealityScan emit
a periodic record even when nothing changed. A `#timeout` record therefore means *"the timeout window
elapsed with no progress change"* — with this repo's boot value `600`, one `#timeout` line = 600 s of
no reported progress. [INFERRED-strong: tutorials/commandline_5 wording + the literal `600` argument
in `startRealityScan.bat`; consistent with every observation below]

Empirically established consequences, all [VERIFIED]:

1. **`#timeout` lines are not activity.** Elapsed keeps ticking and `estimation` becomes garbage, so
   every `#timeout` line differs from the last — which defeats naive line-change stall detection. A
   6-hour `-importComponent` hang produced **zero** stall warnings because the monitor counted each
   new `#timeout` line as progress. [VERIFIED: NA167 #12 / B4, 2026-07-23]
2. **`#timeout` does not always mean hung.** Heavy alignment phases legitimately freeze the progress
   fraction for 20+ minutes; a *successful* 94.6 % run emitted **40** `#timeout` lines.
   [VERIFIED: NA167 #28, 2026-07-24]
3. **The pathological signature is `#timeout` from fraction `0.00` with an ever-growing ETA.**
   [VERIFIED: NA167 #28]
4. **There is a third cause: near-OOM.** RealityScan slows to a crawl *without* crashing and *without*
   spilling to NVMe — in the progress feed this is indistinguishable from a hang.
   [VERIFIED: FINDINGS 2026-07-24]

**Policy in force:** stall-**warn** on `#timeout` after 2 h; **never auto-kill an alignment**.
[VERIFIED-as-decision: NA167 #28]

Implementation of the "not activity" rule [VERIFIED-by-inspection: `realityscan_cli.py:_monitor_loop`]:

```python
if not line.rstrip().endswith('#timeout'):
    last_activity = time.monotonic()
    stall_warned = False
```

and the memory disambiguation that runs alongside it: available physical RAM is sampled via
`GlobalMemoryStatusEx` and a one-shot warning fires below `LOW_MEMORY_WARN_GB = 4.0`, so a later
`#timeout` can be attributed to memory pressure rather than a hang.

### 8.3 Tailing discipline

The monitor reads only the **last 4 KiB** of the progress file and takes the last non-empty line —
the file grows unboundedly over a long run and must never be read whole
[VERIFIED-by-inspection: `realityscan_cli.py:_tail_line`].

Marker files are cleared before every workflow (§6.4) so a previous run's lines can never be
misread as the current run's state. Whether `-writeProgress` **appends to or truncates** an existing
file at instance boot has never been *deliberately* observed here, because the file is always
deleted first. [OPEN, §18-Q6]

**Do not cross-validate the progress file against the results log — on the shipped samples they do
not reconcile.** `progress_RS1.txt` and `results_RS1.log` were produced by the same instance name
over the same period, yet the progress file records 252 process completions while the results log
records 434, and the results log contains algIds (`20533 PROJECT_SAVE`, `21896`, `6 EXPORT_MODEL`)
that appear in the progress file **zero** times. The progress file also contains exactly one
`PROJECT_LOAD` where the results log records eight. That pattern is consistent with `-writeProgress`
truncating at boot while the ErrorWriter marker accumulates across boots — but it is not proof: the
per-algId counts do not line up with any single boot boundary either. Treat the two channels as
independent, partial views. [OPEN, §18-Q6]
[VERIFIED-by-inspection of the counts: `RS_CLI/Errors/progress_RS1.txt`, `results_RS1.log`, 2026-08-04]

---

## 9. The process-completion trigger (`appProcessAction` family)

### 9.1 The three keys

| Key | Type | Default | Value used here | Meaning |
|---|---|---|---|---|
| `appProcessActionTime` | int (seconds) | `15` | `0` | Minimal process duration before the action fires. `0` = every process, however short |
| `appProcessAction` | enum | `None` | `ExecuteProgram` | `None` \| `PlaySound` \| `ExecuteProgram` (ordinal `2` = ExecuteProgram) |
| `appProcessExecCmd` | string | *(empty)* | see below | Command line run when the action is `ExecuteProgram` |

[OFFICIAL: tutorials/commandline_5, tutorials/setkeyvaluetable, appbasics/appsettings]
[VERIFIED-as-used: `startRealityScan.bat`]

The Help notes that for practical (GUI) reasons `appProcessActionTime` "should be greater than 60"
[OFFICIAL: appbasics/appsettings]. For CLI error detection the opposite is required: `0`, so that
**every** operation reports.

### 9.2 Substitution variables

Available inside `appProcessExecCmd` [OFFICIAL: tutorials/commandline_5, appbasics/appsettings]:

| Variable | Value |
|---|---|
| `$(processResult)` | numeric result of the finished process (0 = finished correctly) |
| `$(processId)` | process ID (same namespace as the progress file's `algId`, decimal) |
| `$(processDuration:d)` | duration in seconds |
| `$(sceneName)` | scene name |

`$(processResult)`, `$(processId)` and `$(processDuration:d)` have been in continuous production use
here since 2026-07-21 and demonstrably substitute — every line of `results_RS1.log` is their output
[VERIFIED: `startRealityScan.bat` + `ErrorWriter.bat` + `RS_CLI/Errors/results_RS1.log`].
`$(sceneName)` is documented with a worked example and a worked output line
("Process 020735 has finished with result code 00 after 120 seconds on scene New scene")
[OFFICIAL: appbasics/appsettings] but **has never been used in this repository** — untested here.

Positional arguments of your own may be appended freely; Epic's own sample passes an output-file path
as a fourth argument, and this repo passes the instance name for the same reason
[OFFICIAL: tutorials/commandline_5; VERIFIED: `startRealityScan.bat`].

**If the exe path contains spaces it must be double-quoted** [OFFICIAL: appbasics/appsettings] — and
here it must be *escape*-quoted, because the whole command line is itself the value of a quoted
`-set` pair. Unquoted, the trigger silently launches nothing and all error detection vanishes.
[VERIFIED: HANDOFF overhaul item 4, 2026-07-21]

### 9.3 This repo's hook chain

```
RealityScan instance
  └─ appProcessExecCmd → wscript.exe //B "…\RS_CLI\Errors\ErrorWriterLaunch.vbs"
                              $(processResult) $(processId) $(processDuration:d) <instance>
       └─ ErrorWriterLaunch.vbs  (GUI-subsystem host, no console)
            └─ cmd /c ""…\ErrorWriter.bat" <args>"   (hidden, synchronous)
                 ├─ append every completion → results_<instance>.log
                 └─ append non-{0,1} results → errors_<instance>.txt
```

Why the VBS shim exists: the trigger fires for **every** completed process, including RealityScan's
periodic internal heartbeats. Invoking `cmd /c ErrorWriter.bat` directly pops a visible console
window each time — hundreds of flashing terminals over a long run. `wscript.exe` is a GUI-subsystem
host, so the shim runs with no console and shells the real `.bat` hidden and **synchronously**
(`shell.Run …, 0, True`) to preserve marker-file write ordering.
[VERIFIED: FINDINGS 2026-07-23; `ErrorWriterLaunch.vbs`]

A quoting hazard already paid for once: the shim's **first** version composed the command line with
literal escaped quotes inside VBS string constants, producing a malformed line — `ErrorWriter.bat`
never ran, and **the errors-marker system was inert for every run between the shim's introduction and
the fix**. The working composition uses `Chr(34)`:
[VERIFIED: FINDINGS 2026-07-24 review finding]

```vbs
q = Chr(34)
bat = Replace(WScript.ScriptFullName, "ErrorWriterLaunch.vbs", "ErrorWriter.bat")
shell.Run "cmd /c " & q & q & bat & q & args & q, 0, True
```

`ErrorWriter.bat` itself, verbatim [VERIFIED-by-inspection]:

```bat
@echo off
set "instance=%~4"
if "%instance%" == "" set "instance=RS1"
echo %date% %time% process %~2 finished with result code %~1 in %~3 seconds >> "%~dp0results_%instance%.log"
if /i "%~1" NEQ "0" (
    if /i "%~1" NEQ "1" (
        echo An error occurred: process %~2 finished with result code %~1 in %~3 seconds. >> "%~dp0errors_%instance%.txt"
    )
)
```

Design points worth copying:

- Marker files are written **next to the script** (`%~dp0`), so no path containing spaces ever has to
  survive the `appProcessExecCmd` command line.
- Marker files are **namespaced per instance** (`results_RS1.log`, `errors_RS1.txt`,
  `progress_RS1.txt`), so parallel instances can never read each other's state.
- Result codes `0` **and** `1` are both treated as success (the whitelist comes from Epic's own sample
  script and matches observation: routine `-addFolder` reports result `1`).
  [OFFICIAL: tutorials/commandline_5 sample; VERIFIED: FINDINGS 2026-07-21]

### 9.4 Real marker-file content

`results_<instance>.log` — one line per completed process. Four real, **non-contiguous** lines from
`RS_CLI/Errors/results_RS1.log` [VERIFIED-by-inspection, 2026-08-04]:

```
Wed 07/29/2026  8:01:37.87 process 21896 finished with result code 0 in 0 seconds
Wed 07/29/2026  8:02:24.16 process 20532 finished with result code 0 in 41 seconds
Wed 07/29/2026  8:14:38.00 process 20533 finished with result code 0 in 732 seconds
Wed 07/29/2026 11:13:36.15 process 20532 finished with result code 2181038103 in 0 seconds
Wed 07/29/2026 13:03:53.33 process 21856 finished with result code 2147942487 in 0 seconds
```

The date/time prefix is `%date% %time%` verbatim from cmd, so its **format follows the machine's
Windows regional settings** — a log written on a differently-configured box will not parse with the
same pattern. Every line ends with a trailing space (the `echo` before the `>>`). Anything parsing
these files must be tolerant of both. [VERIFIED-by-inspection: `ErrorWriter.bat`, `results_RS1.log`]

Whole-file census of that one file, which is what a real long session looks like
[VERIFIED-by-inspection, 2026-08-04]:

| | count |
|---|---|
| total completion lines | 434 |
| result `0` | 332 |
| result `2147942487` (`E_INVALIDARG`, all algId `21856`) | 101 |
| result `2181038103` (`0x82000017`, algId `20532 PROJECT_LOAD`) | 1 |
| algId `41063` / `41064` / `41061` (registration-export internals) | 106 / 105 / 99 |
| algId `21856` / `21896` / `20532` / `20533` / `6` | 101 / 8 / 8 / 3 / 4 |

That single `2181038103` line is the stale-`<name>.rsproj.new` load warning of §3.5 and §10.2,
caught in the wild — the only non-`21856` failure in 434 completions.

`errors_<instance>.txt` — one line per non-whitelisted result
[VERIFIED-by-inspection: `RS_CLI/Errors/expected_peelend_RS1.txt`, an errors marker moved aside by
`:run_peelrename`]:

```
An error occurred: process 21859 finished with result code 2147942487 in 0 seconds.
```

**The errors marker carries only the numeric result code — never the `err:NNNN` text.** That text
exists only in `RealityScan.log`. Any tolerant handler must therefore match *codes*, not messages.
[VERIFIED: FINDINGS 2026-07-23]

### 9.5 The heartbeat problem

RealityScan 2.2 emits periodic internal processes through the same trigger. In the sampled run,
`41061` / `41063` / `41064` (`EXPORT_REGISTRATION_FILE` / `_PREPROCESS` / `_FINALIZE`) account for
**310 of 434** recorded completions (99 + 106 + 105), and `21896` fires at session boundaries with no
corresponding delegated command. Fewer than one line in four is attributable to a command the
orchestrator issued. [VERIFIED-by-inspection: `results_RS1.log`, 2026-08-04;
VERIFIED-as-behaviour: HANDOFF 2026-07-21]

Consequences:

- **"The results log grew" ≠ "our command finished."** Never build a completion oracle on it (§6.3).
- The results log **is** useful as an event-driven record of what ran and how long it took, and the
  Python layer returns its lines in `WorkflowResult.completed_processes`.
- Markers are read **after** verified shutdown, not when the `.bat` exits, because the final
  operations may still be running during the shutdown window and a late error would otherwise be
  missed. [VERIFIED-by-inspection: `realityscan_cli.py:run_batch_script`]

---

## 10. Result codes, exit codes, crash artifacts

### 10.1 Process **exit** codes of `RealityScan.exe`

| Exit code | Meaning | Source |
|---|---|---|
| `0` | the process finished successfully | [OFFICIAL: tutorials/commandline_5] |
| decimal error code | the specific error's decimal code — **only when `-set "appQuitOnError=true"`** | [OFFICIAL: tutorials/commandline_5] |
| `3` | crash with minidump; the dump is written to the `-silent` path | [OFFICIAL: tutorials/commandline_5] |

This repo sets `appQuitOnError=false`, so exit codes are **not** the error channel here: warning-class
results are routine and the orchestrator, not the app, decides what is fatal. The error channel is the
completion hook (§9). [VERIFIED-as-decision: `startRealityScan.bat`]

### 10.2 Process **result** codes seen through the completion hook

| decimal | hex | meaning as established here |
|---|---|---|
| `0`, `1` | — | routine success (both) [VERIFIED: FINDINGS 2026-07-21] |
| `2181038103` | `0x82000017` | warning-class load complaint, e.g. a stale `<name>.rsproj.new` beside the project [VERIFIED: FINDINGS 2026-07-29; observed once in `results_RS1.log`] |
| `2181038335` | `0x820000FF` | warning class; `-importFlightLog` `err:18002` (log rows not in the scene). Benign, verified by manifest cross-check [VERIFIED: FINDINGS 2026-07-21/25] |
| `2147549183` | `0x8000FFFF` | **generic** "unexpected program state" — broken `-set` args *and* the zone_14 align failure emit the identical code [VERIFIED: NA167 #16 / B6] |
| `2147942487` | `0x80070057` | `E_INVALIDARG` — empty/no-op selection paths (`-renameSelectedComponent` on an emptied scene, `-selectModel` on a missing name) [VERIFIED: FINDINGS 2026-07-24/29] |
| `2147942512` | `0x80070070` | `ERROR_DISK_FULL` — RealityScan's **cache** disk, not necessarily the project disk [VERIFIED: FINDINGS 2026-07-26] |
| `2181038176` | `0x82000060` | unknown/invalid command (e.g. `-selectAllComponents`) [VERIFIED: NA167 #13 / B2; decimal computed from the hex, not read off a log] |
| `3` | — | crash; minidump at the `-silent` path [OFFICIAL + VERIFIED: FINDINGS 2026-07-26] |

Arithmetic that lets you recognise the family in a decimal-only marker file: `0x82000000` =
**2181038080**, so any decimal in 2181038080–2181038335 is an `0x820000xx` code. The three observed
members are base + `0x17` (load complaint), + `0x60` (unknown command), + `0xFF` (flight-log rows not
in scene). **Membership in that band does not mean "warning class"** — `0x82000060` is a hard
unknown-command failure and sits in the same band as the two benign ones. There is no way to tell
severity from the number alone; you have to know the code. [VERIFIED-arithmetic; the
code→meaning mapping is [VERIFIED] per row above]

Codes are `HRESULT`-shaped: the `0x8007xxxx` entries are Win32 errors wrapped by
`HRESULT_FROM_WIN32` (`0x80070057` = `E_INVALIDARG`, `0x80070070` = `ERROR_DISK_FULL`), and
`0x8000FFFF` is the standard `E_UNEXPECTED`. The `0x8200xxxx` block is RealityScan's own facility.
[INFERRED from standard Windows HRESULT layout; Epic documents none of these codes anywhere]

`err:NNNN` codes that appear **only** in `RealityScan.log`, never in the markers:
`err:7155` (setting parse failure), `err:18002` (flight-log rows not in scene),
`err:5601` (model name not found), and the internal `MSS_STR001` reconstruction failure.
[VERIFIED: FINDINGS 2026-07-23/29]

### 10.3 Crash artifacts

A crash writes `RealityScanCrash-YYYYMMDD-HHMMSS.dmp` plus a sibling
`RealityScanCrash-YYYYMMDD-HHMMSS.dmp.metadata` into the `-silent` directory. The `.metadata` file is
**binary, not text** — 192 bytes beginning with the ASCII magic `MCRM` — so do not expect to read a
reason out of it. The dump on hand is 1,477,291 bytes, i.e. a mini-dump, not a full-memory dump.
[VERIFIED-by-inspection: `RS_CLI/Errors/RealityScanCrash-20260726-054742.dmp{,.metadata}`,
2026-08-04; FINDINGS 2026-07-26]

**The timestamp in the filename is UTC, not local time.** The artifact on disk is
`RealityScanCrash-20260726-054742.dmp`; its NTFS CreationTime is `2026-07-26 01:47:42` local and its
LastWriteTime `01:47:43` — a 4-hour offset exactly matching UTC−4 (US Eastern daylight time) on that
date, and matching the findings log's "written at 01:47:42 local" to the second.
[VERIFIED-by-inspection of filename vs. file timestamps, 2026-08-04 — but on **one** artifact from
**one** machine, so it remains [INFERRED] that the format is UTC rather than a fixed offset baked in
elsewhere; the next dump on a differently-offset machine settles it at zero cost]

Practical consequence: **you cannot correlate a dump with a log window by filename alone** unless you
convert. On a UTC−4 box a crash at 21:00 local is filed under the *next* day's date.

**After a crash, the next delegated command fails at delegation** — `ERROR: Failed to delegate
command: …` — which is the signature of a dead instance rather than a rejected operation.
[VERIFIED: FINDINGS 2026-07-26]

---

## 11. RealityScan's own log

| Property | Value | Tag |
|---|---|---|
| Path | `%LOCALAPPDATA%\Temp\RealityScan.log` | [VERIFIED: NA167 #16 / B6] |
| Enabled by | `appLog` (bool, default `true`) — "Log file: enable to write and save the log file in the Windows Temp folder" | [OFFICIAL: appbasics/appsettings, tutorials/setkeyvaluetable] |
| Lifetime | **truncated on every instance boot** | [VERIFIED: NA167 #16 / B6, 2026-07-23] |
| Scope | one shared file, **not** per instance | [VERIFIED: FINDINGS 2026-07-27, by the splice below] |

Two consequences that have each cost a session:

1. **Post-failure snapshots lose the race to the next boot.** A 91-byte capture was recorded once.
   Log copies must happen inside the driver **immediately** after the failing call returns, not at
   the end of the run. [VERIFIED: NA167 #16 / B6]
2. **A saved `rslog.txt` snapshot can be a *different run's* log, spliced mid-file.** Two merge
   drivers overlapped; RealityScan truncated the shared log when the second instance launched, so one
   snapshot's head and tail belong to different runs — an H2023 attempt's snapshot recorded
   `importComponent` of eleven H2024 components. **A snapshot must be validated against a run-unique
   token — e.g. the attempt's own `.complist` paths — before any number is read out of it.**
   [VERIFIED: FINDINGS 2026-07-27]

The log is nonetheless the *only* place the human-readable reason for a failure exists (§10.2), so
it stays load-bearing for post-mortems and `appLog` is deliberately left at its default `true`.

---

## 12. Licensing, accounts, online communication

- RealityScan 2.2 is signed in with an **Epic Games account**; the Application Settings panel shows
  "Signed in as", Sign out, and "Sign in with Epic Games" if sign-in was skipped
  [OFFICIAL: appbasics/appsettings].
- **The log-in window is explicitly named as a pop-up that `-silent` and `appQuitOnError=true` cannot
  suppress, and that forces RealityScan out of headless mode.**
  [OFFICIAL: tutorials/headless] — this is the one documented way a headless run can stop dead with
  no CLI-visible symptom.
- `-disableOnlineCommunication` disables any online communication
  [OFFICIAL: tutorials/commandline_4]. Never used here; its interaction with sign-in state and with
  online-dependent commands (`-uploadToSketchfab`) is untested. [OPEN, §18-Q7]
- The 2.2 binary contains the UTF-16 strings `appActivTokenCLI` and `appActivTokenCLIValid`, plus
  `appLic`, `appLicDel`, `appLicDelMachine`, `appAutoRenew`, `appLicenseAutoRenew`, `appRenewT` —
  none of which appear in the Help's settings tables. A CLI activation-token path plausibly exists.
  [UNDOCUMENTED: direct UTF-16 string scan of
  `C:\Program Files\Epic Games\RealityScan_2.2\RealityScan.exe` (2.2.0.119430), re-run 2026-08-04;
  see also `03-settings-keys.md`] [INFERRED: that `appActivTokenCLI` is the headless-activation
  lever; nothing has been set or observed. Being a key-shaped string in the binary is not evidence
  that `-set` accepts it]
- **Empirically: two years of headless production here recorded no licensing/activation interaction,
  prompt, or failure.** That is absence of evidence, not evidence of absence.
  [VERIFIED-as-absence; OPEN, §18-Q8]

Also in the same family: `operationLog` (bool, default `true`) uploads feature/settings/process
telemetry to Epic; `-set "operationLog=false"` disables it. Left at default here.
[OFFICIAL: appbasics/appsettings, tutorials/setkeyvaluetable]

---

## 13. Multi-GPU and instance pinning

- **RealityScan uses every CUDA GPU by default.** The GUI exposes a "GPUs to use" selector —
  "If your computer has multiple GPUs, you can select which one to use here"
  [OFFICIAL: appbasics/appsettings]. **No `-set` key for GPU *selection* appears anywhere in the
  Help's key tables.** The only GPU key documented at all is the boolean `MvsGeometryGpuAccel`
  (default `true`, mesh calculation) [OFFICIAL: tutorials/setkeyvaluetable]. A second boolean,
  `sfmGPUAcceleration=true`, is carried in this repo's `RS_CLI/Metadata/AlignmentParams.xml` but is
  **absent from every Help table** [UNDOCUMENTED: `AlignmentParams.xml` line 15]. Neither is a
  selector — both are on/off switches. [OPEN, §18-Q9]
- The working lever is therefore the CUDA environment: export `CUDA_VISIBLE_DEVICES` **before**
  launching the instance, and give each instance a unique name. One instance name per GPU set.
  [VERIFIED-as-design: `startRealityScan.bat`, `realityscan_cli.py`; CLAUDE.md]

```bat
:: startRealityScan.bat — optional GPU pinning
if defined RS_GPU_DEVICES set CUDA_VISIBLE_DEVICES=%RS_GPU_DEVICES%
```

The Python layer sets both variables for the child environment from
`rs_settings.json` `realityscan.gpu_devices` (or the `gpu_devices` argument):

```python
env['RS_GPU_DEVICES'] = str(gpu_devices)
env['CUDA_VISIBLE_DEVICES'] = str(gpu_devices)
```

- **Single-instance GPU pinning is exercised. Two concurrent instances on different GPUs has never
  been run.** Marker-file isolation is in place by construction (per-instance names) and the lock file
  is per instance name, but cache contention and licensing behaviour under concurrency are unmeasured.
  [OPEN, §18-Q10]
- Memory is the real constraint at scale, not GPU count: a 4,131-image joint alignment peaked ~165 GB
  on a 192 GB box; a 4,860-camera model run peaked 148.7 GB committed with 0.9 GB available RAM
  remaining. Per-zone aligns stay ≤ ~60 GB. Budget by scene, not by image count — alignment runtime
  varies ~3× with scene character at equal image count. [VERIFIED: NA167 #19/#20; FINDINGS 2026-07-29]
- **Identify the instance before quoting memory numbers**: a workflow runs multiple `RealityScan.exe`
  processes (the persistent instance plus transient delegation helpers). A "2.2 GB during a
  4,540-image align" reading was a 30 MB transient. Use largest working set or a tracked PID.
  [VERIFIED: FINDINGS 2026-07-24]

---

## 14. Cache location and disk behaviour

### 14.1 Keys

| Key | Type | Default | Values | Notes |
|---|---|---|---|---|
| `appCacheLocation` | enum | `SystemTemp` | `SystemTemp`, `Custom` | [OFFICIAL: tutorials/setkeyvaluetable] |
| `appCacheCustomLocation` | path | *(empty)* | absolute path | relevant only with `appCacheLocation=Custom` [OFFICIAL] |
| `appAutoClearCache` | enum (days) | `7` | `999999` (never), `0` (all), `3`, `7`, `14`, `30`, `90` | "Clear cache on exit" [OFFICIAL] — deliberately **untouched** here; retention is owner policy [VERIFIED] |
| `appCacheImageMetadata` | bool | `true` | — | writes a hidden `crmeta.db` beside inputs to speed EXIF access [OFFICIAL: appbasics/appsettings] |
| `appCopyImportedComponentsToCache` | bool | `false` | — | "set to Yes if your cache is on an SSD and you want faster component access" [OFFICIAL]; never swept here [OPEN, §18-Q11] |

`-clearCache` is a CLI command and **requires the project be saved first** ("You must save the project
before clearing the application cache") [OFFICIAL: appbasics/allcommands]. Its process id is
`21861 CLI_CLEAR_CACHE` [OFFICIAL: tutorials/processids].

**Epic's default cache location contradicts Epic's own advice.** `appCacheLocation` defaults to
`SystemTemp` [OFFICIAL: tutorials/setkeyvaluetable], while the autosave page says "we do not
recommend using system temp as target cache location — this folder will require storage as with Auto
Save mode enabled" [OFFICIAL: appbasics/autosave]. Both ship in the same build.
[CONTRADICTED, internal to the shipped Help] Practical reading: if autosave is on, move the cache; if
you keep the default, turn autosave off — which is what this repo does
(`appAutoSaveMode=false`, cache moved only when `RS_CACHE_DIR` is set).

Some settings require an application reset. The documented pattern is `appQuitOnReset=true` plus a
`-set` per invocation — the app quits after each such change [OFFICIAL: tutorials/commandline_5]:

```bat
RealityScan.exe -set "appQuitOnReset=true" -set "appCacheLocation=Custom"
RealityScan.exe -set "appQuitOnReset=true" -set "appCacheCustomLocation=D:\cr-tmp"
RealityScan.exe -newScene
```

This repo does **not** use that dance — it passes both cache keys on the boot command line, which
works without a restart cycle. [VERIFIED: `startRealityScan.bat`]

### 14.2 The disk behaviour that actually kills runs

- **The cache is placed by the drive of the path given and does NOT move when the project moves.**
  `D:\rccache` reached 1,089 GB and refilled 197 GB of freshly-cleaned space within one run, killing
  a model three times, while the **project** drive showed 773.9 GB free.
  [VERIFIED: FINDINGS 2026-07-26]
- A cache-full condition surfaces as result code `2147942512` = `0x80070070` `ERROR_DISK_FULL`
  through the completion hook — **indistinguishable from any other failure** without a cache-drive
  free-space column in the monitor. The instance log said it outright:
  `Processing failed: Out of disk space..` [VERIFIED: FINDINGS 2026-07-26]
- **Epic's guidance: do not hand-delete cache files; free space on the cache disk or change the cache
  disk instead.** Cancelling the warning aborts the running process and its progress is lost.
  [OFFICIAL: appbasics/outofdisk]
- Monitoring consequence, implemented here: the resource trace records free space on **both** the
  trace/project drive and the cache drive (`RS_CACHE_DIR`), sampled every 30 s and flushed per row,
  because a trace that is not durable as it is written is lost when RealityScan dies.
  [VERIFIED-by-inspection: `realityscan_cli.py:_sample_resources`]

Trace columns written per sample:
`iso_time,elapsed_s,cpu_pct,ram_avail_gb,ram_total_gb,mem_load_pct,commit_used_gb,commit_total_gb,disk_free_gb,cache_free_gb,progress`.

---

## 15. Minimum viable headless session

### 15.1 One-shot, no delegation (simplest possible correct run)

Everything in a single process; commands execute in order; the process exits when `-quit` runs.
No instance name, no progress file, no error hook — suitable only for short, low-risk work.

```bat
@echo off
set "RS=C:\Program Files\Epic Games\RealityScan_2.2\RealityScan.exe"
set "WORK=F:\na156_h2024\zone_3"
if not exist "%WORK%\crash" mkdir "%WORK%\crash"

"%RS%" -headless ^
  -silent "%WORK%\crash" ^
  -set "appIncSubdirs=true" ^
  -newScene ^
  -addFolder "%WORK%\images" ^
  -align ^
  -setMinComponentSize 1 ^
  -deselectAllImages ^
  -exportLatestComponents "%WORK%\components" ^
  -save "%WORK%\zone_3.rsproj" ^
  -quit

echo RealityScan.exe returned with %errorlevel%.
```

### 15.2 Delegated session with full observability (the production shape)

This is the minimum that gives per-operation success/failure, a progress stream, crash capture, and
verified shutdown. Everything here is exercised in production; the only simplification versus §16 is
that the cache keys and the daily project-copy machinery are omitted.

```bat
@echo off
setlocal
set "RS=C:\Program Files\Epic Games\RealityScan_2.2\RealityScan.exe"
set "INST=RS1"
set "ERRPATH=%~dp0Errors"
set "WORK=F:\na156_h2024\zone_3"
if not exist "%ERRPATH%" mkdir "%ERRPATH%"

:: Fresh markers. A leftover errors marker would abort the first :run.
del /q "%ERRPATH%\errors_%INST%.txt"   2>nul
del /q "%ERRPATH%\results_%INST%.log"  2>nul
del /q "%ERRPATH%\progress_%INST%.txt" 2>nul

:: --- boot -----------------------------------------------------------
start "" "%RS%" -headless -silent "%ERRPATH%" -setInstanceName %INST% ^
  -set "appAutoSaveMode=false" ^
  -set "appQuitOnError=false" ^
  -set "appProcessActionTime=0" ^
  -set "appProcessAction=ExecuteProgram" ^
  -set "appProcessExecCmd=wscript.exe //B \"%ERRPATH%\ErrorWriterLaunch.vbs\" $(processResult) $(processId) $(processDuration:d) %INST%" ^
  -writeProgress "%ERRPATH%\progress_%INST%.txt" 600

set /a tries=0
:wait
"%RS%" -getStatus %INST% >nul 2>&1
if /I "%ERRORLEVEL%" NEQ "0" (
    set /a tries+=1
    if %tries% GEQ 120 ( echo ERROR: %INST% not ready in 120 s & exit /b 1 )
    ping -n 2 127.0.0.1 >nul
    goto :wait
)

:: --- work -----------------------------------------------------------
"%RS%" -delegateTo %INST% -set "appIncSubdirs=true"
call :run -newScene                                   || goto :fail
call :run -addFolder "%WORK%\images"                  || goto :fail
call :run -align                                      || goto :fail
call :run -deselectAllImages                          || goto :fail
call :run -setMinComponentSize 1                      || goto :fail
call :run -exportLatestComponents "%WORK%\components" || goto :fail
call :run -save "%WORK%\zone_3.rsproj"                || goto :fail

"%RS%" -delegateTo %INST% -quit
call :verifyDown
exit /b 0

:fail
echo ERROR: workflow failed - see %ERRPATH%\errors_%INST%.txt
"%RS%" -delegateTo %INST% -quit
call :verifyDown
exit /b 1

:: --- verified shutdown ----------------------------------------------
:verifyDown
set /a downTries=0
:down
"%RS%" -getStatus %INST% >nul 2>&1
if /I "%ERRORLEVEL%"=="0" (
    set /a downTries+=1
    if %downTries% GEQ 900 ( echo ERROR: %INST% did not shut down & exit /b 1 )
    ping -n 2 127.0.0.1 >nul
    goto :down
)
exit /b 0

:: --- the synchronisation primitive ----------------------------------
:run
"%RS%" -delegateTo %INST% %*
if errorlevel 1 ( echo ERROR: Failed to delegate command: %* & exit /b 1 )
ping -n 3 127.0.0.1 >nul
"%RS%" -waitCompleted %INST%
ping -n 2 127.0.0.1 >nul
"%RS%" -waitCompleted %INST%
if exist "%ERRPATH%\errors_%INST%.txt" (
    for %%A in ("%ERRPATH%\errors_%INST%.txt") do if %%~zA GTR 0 (
        echo ERROR: RealityScan reported a failure during: %*
        exit /b 1
    )
)
exit /b 0
```

**Save this file with CRLF line endings.** LF-only `.bat` files break `call :label` resolution
nondeterministically (§2.5).

---

## 16. Annotated production boot sequence

### 16.1 `SetVariables.bat` — shared variables

Called by every workflow before anything else. The parts that matter for lifecycle
[VERIFIED-by-inspection: `RS_CLI/Scripts/SetVariables.bat`]:

```bat
@echo off

:: Executable: RS_EXECUTABLE wins, else the newest-first candidate list.
if defined RS_EXECUTABLE (
    set RealityScan="%RS_EXECUTABLE%"
    goto :exeResolved
)
for %%P in (
    "C:\Program Files\Epic Games\RealityScan_2.2\RealityScan.exe"
    "C:\Program Files\Capturing Reality\RealityScan 2.2\RealityScan.exe"
    "C:\Program Files\Epic Games\RealityScan_2.1\RealityScan.exe"
    "C:\Program Files\Capturing Reality\RealityScan 2.1\RealityScan.exe"
    "C:\Program Files\Epic Games\RealityScan_2.0\RealityScan.exe"
) do (
    if not defined RealityScan if exist %%P set RealityScan=%%P
)
:exeResolved
if not defined RealityScan (
    echo ERROR: RealityScan.exe not found in any standard install location.
    exit /b 1
)

:: Instance name. Override RS_INSTANCE to run several in parallel (one per GPU).
if not defined RS_INSTANCE set RS_INSTANCE=RS1

:: Headless toggle: RS_HEADLESS=0 boots with the GUI visible; anything else
:: (or unset) keeps the headless boot. Delegation is identical either way.
set RS_HEADLESS_FLAG=-headless
if /I "%RS_HEADLESS%"=="0" set RS_HEADLESS_FLAG=

set RootFolder=%~dp0..\
set Metadata=%RootFolder%Metadata
set ErrorPath=%RootFolder%Errors
if not exist "%ErrorPath%" mkdir "%ErrorPath%"
```

`%ErrorPath%` is the single directory that receives: the `-silent` minidumps, the `-writeProgress`
file, the ErrorWriter markers, the per-instance lock, and the moved-aside expected-error evidence
files. Keeping them together is what makes "write markers next to the script (`%~dp0`)" work.

Two conventions in that file are easy to break by accident:

- **`%RealityScan%` carries its own quotes.** `set RealityScan="%RS_EXECUTABLE%"` quotes the value,
  and the `for %%P in ("…")` loop hands over an already-quoted token. That is why every call site
  writes `%RealityScan% -delegateTo …` with **no** surrounding quotes. Adding quotes at a call site
  produces `""C:\…\RealityScan.exe""` and cmd fails to find the program.
  [VERIFIED-by-inspection: `SetVariables.bat` lines 10–22]
- **`ErrorsFile` is *not* set here.** Each workflow script defines
  `set "ErrorsFile=%ErrorPath%\errors_%RS_INSTANCE%.txt"` itself
  (`AlignZone.bat` line 35, `MergeZoneComponents.bat`, `ExportDeliverables.bat` line 42,
  `AlignImageList.bat` line 21, `AlignImagesFromFolder.bat` line 34). A new workflow that calls
  `SetVariables.bat` and then uses `:run` without defining `ErrorsFile` gets an empty path, the
  `if exist` test never fires, and **every operation reports success regardless of what happened.**
  [VERIFIED-by-inspection, 2026-08-04]

### 16.2 `startRealityScan.bat` — boot or attach

```bat
@echo off

if not defined RealityScan call "%~dp0SetVariables.bat"
if not defined RealityScan exit /b 1

:: (1) Is our instance already up? errorlevel 0 == it exists.
%RealityScan% -getStatus %RS_INSTANCE% >nul 2>&1
IF /I "%ERRORLEVEL%"=="0" (
    echo RealityScan instance %RS_INSTANCE% is already running - reusing it with a fresh scene
    %RealityScan% -delegateTo %RS_INSTANCE% -newScene -deleteAutosave
    goto :eof
)

echo Starting new RealityScan instance %RS_INSTANCE%

:: (2) Optional GPU pinning. Unset = use all CUDA GPUs.
if defined RS_GPU_DEVICES set CUDA_VISIBLE_DEVICES=%RS_GPU_DEVICES%

:: (3) Optional cache relocation. The cache does NOT follow the project.
set "RS_CACHE_ARGS="
if defined RS_CACHE_DIR (
    if not exist "%RS_CACHE_DIR%" mkdir "%RS_CACHE_DIR%"
    set "RS_CACHE_ARGS=-set "appCacheLocation=Custom" -set "appCacheCustomLocation=%RS_CACHE_DIR%""
    echo Cache location: %RS_CACHE_DIR%
)

:: (4) THE BOOT LINE.
start "" %RealityScan% %RS_HEADLESS_FLAG% -silent "%ErrorPath%" -setInstanceName %RS_INSTANCE% %RS_CACHE_ARGS% -set "appAutoSaveMode=false" -set "appQuitOnError=false" -set "appProcessActionTime=0" -set "appProcessAction=ExecuteProgram" -set "appProcessExecCmd=wscript.exe //B \"%ErrorPath%\ErrorWriterLaunch.vbs\" $(processResult) $(processId) $(processDuration:d) %RS_INSTANCE%" -writeProgress "%ErrorPath%\progress_%RS_INSTANCE%.txt" 600

echo Waiting until the RealityScan instance %RS_INSTANCE% is ready

:: (5) Readiness poll, 120 s bound.
set /a startTries=0
:waitStart
%RealityScan% -getStatus %RS_INSTANCE% >nul 2>&1
IF /I "%ERRORLEVEL%" NEQ "0" (
    set /a startTries+=1
    if %startTries% GEQ 120 (
        echo ERROR: RealityScan instance %RS_INSTANCE% did not become ready within 120 seconds
        exit /b 1
    )
    ping -n 2 127.0.0.1 >nul
    goto :waitStart
)

:eof
```

Every element of the boot line, and why:

| Element | Why | Tag |
|---|---|---|
| `start ""` | launch detached; the `.bat` must not block on the instance's lifetime. The empty `""` is the window title cmd otherwise steals from the quoted exe path | [VERIFIED-by-inspection] |
| `%RS_HEADLESS_FLAG%` | `-headless`, or empty when `RS_HEADLESS=0` | [VERIFIED] |
| `-silent "%ErrorPath%"` | suppress dialogs, redirect minidumps into the marker directory | [OFFICIAL + VERIFIED] |
| `-setInstanceName %RS_INSTANCE%` | delegation target; one name per GPU set | [OFFICIAL] |
| `%RS_CACHE_ARGS%` | `appCacheLocation=Custom` + `appCacheCustomLocation` when `RS_CACHE_DIR` is set. Opt-in: unset keeps RealityScan's default | [VERIFIED: FINDINGS 2026-07-26] |
| `-set "appAutoSaveMode=false"` | autosave would race the destructive in-session identity loop; a recovery modal hangs a headless box | [VERIFIED] |
| `-set "appQuitOnError=false"` | warning-class results are routine; the orchestrator decides what is fatal, not the app | [VERIFIED] |
| `-set "appProcessActionTime=0"` | fire the completion hook for **every** process, however short | [VERIFIED] |
| `-set "appProcessAction=ExecuteProgram"` | the hook is the authoritative per-operation result channel | [VERIFIED] |
| `-set "appProcessExecCmd=wscript.exe //B \"…\ErrorWriterLaunch.vbs\" $(processResult) $(processId) $(processDuration:d) %RS_INSTANCE%"` | GUI-subsystem host (no console flash); escaped quotes because checkout paths contain spaces; instance name namespaces the markers | [VERIFIED] |
| `-writeProgress "%ErrorPath%\progress_%RS_INSTANCE%.txt" 600` | the progress stream the Python layer tails; 600 s periodic `#timeout` records | [VERIFIED] |
| *(absent)* `-stdConsole` | removed 2026-07-23 — allocates a console window per boot and nothing reads instance stdout | [VERIFIED] |
| *(absent)* `appAutoClearCache` | deliberately untouched — retention is owner policy | [VERIFIED] |

### 16.3 What the Python layer adds around the `.bat`

`RealityScanCLI.run_batch_script` owns the orchestration-level concerns the `.bat` cannot
[VERIFIED-by-inspection: `realityscan_cli.py`]:

1. Resolve the executable and export `RS_EXECUTABLE`, `RS_INSTANCE`, and (if configured)
   `RS_GPU_DEVICES` + `CUDA_VISIBLE_DEVICES` into the child environment.
2. Acquire the per-instance lock (`RS_CLI/Errors/<instance>.lock`, `O_EXCL`, PID inside).
3. **Shut down any pre-existing instance** of that name — a leftover from a crashed run may be hours
   into an old operation with the hooks still armed.
4. Clear the three marker files, with the 60 s per-file retry for the teardown/handle race.
5. Launch the `.bat` with `CREATE_NO_WINDOW` (or `CREATE_NEW_CONSOLE` when `display_output=True`),
   capturing stdout+stderr to `output_<timestamp>.txt` in the log directory.
6. Monitor: tail the progress file every 2 s, relay changed lines, treat `#timeout`-suffixed lines as
   non-activity, warn once on low RAM, warn once at the 2 h stall threshold, and write a
   CPU/RAM/commit/disk/cache-free CSV trace every 30 s, flushed per row.
7. After the `.bat` exits: **verify shutdown**, and only then read the markers (late errors arrive
   during the shutdown window).
8. Return `WorkflowResult(success, return_code, log_path, errors, completed_processes, duration_seconds)`
   where `success = (return_code == 0 and not errors)`.
9. Release the lock in a `finally`.

---

## 17. Failure-signature quick reference

| Symptom | Most likely cause | First action |
|---|---|---|
| `ERROR: Failed to delegate command: …` | the instance is dead (crashed, or quit early) | check the `-silent` directory for a `.dmp`; check `-getStatus` errorlevel |
| Operation "succeeds" in seconds that should take an hour | a dialog was auto-answered under `-silent` (e.g. a stale selection turned an export into a no-op), or a merge silently did not fuse | verify by artifact count/camera census, never by exit status |
| `#timeout` lines from fraction `0.00`, ETA growing | hung operation (classically `-importComponent` on a **relocated** `.rsalign`) | kill and re-run from the component's original export path |
| `#timeout` lines mid-run at a non-zero fraction | normal for heavy align phases; or a near-OOM crawl | check available RAM in the resource trace before intervening |
| Result code `2147942512` / `0x80070070` | **cache** disk full (not necessarily the project disk) | free space on the cache drive or repoint `RS_CACHE_DIR`; never hand-delete cache files |
| Result code `2147549183` / `0x8000FFFF` | generic "unexpected program state" — could be a split `-set` pair or a genuine solver failure | snapshot `RealityScan.log` **immediately**; look for `err:7155` |
| Nothing in `errors_<inst>.txt` and nothing happened | the hook is inert (malformed `appProcessExecCmd`), or the command silently no-opped on an empty scene | inject a known failure and prove the detector fires before trusting silence |
| Marker file cannot be deleted | `-getStatus`/teardown race — the dying process still holds the handle | retry for 60 s before concluding the instance is alive |
| `The system cannot find the batch label specified - run` | LF line endings in a `.bat` | normalise to CRLF |
| Settings appear not to apply | `key=value` split by cmd across a `.bat` boundary | check `RealityScan.log` for `err:7155`; cross the boundary as `key:value` |
| Progress file shows `#completed` at 1.00 but the artifact is missing | `#completed` carries **no** success semantics (§8.1) | read the result code from `results_<inst>.log` for that algId; never treat `#completed` as success |
| A new workflow `.bat` reports success for everything | `ErrorsFile` was never defined, so `:run`'s `if exist` never fires (§16.1) | `set "ErrorsFile=%ErrorPath%\errors_%RS_INSTANCE%.txt"` in the script; then inject a known failure and prove `:run` aborts |
| Crash dump timestamp does not match the log window | the filename is UTC, the log is local (§10.3) | convert before correlating |

---

## 18. Open questions

Each item is stated as a question plus the cheapest probe that would answer it.
In-text citations of the form `§18-Q<n>` point at the numbered rows below.

**Q1 — Are RealityScan command names case-sensitive?**
The shipped Help spells the same commands two ways (`execRSCMD`/`execrscmd`,
`exportUndistortedImages`/`exportUndistoredImages`). *Probe:* delegate `-getstatus RS1` and
`-GETSTATUS RS1` to an idle instance and compare errorlevels (seconds, no scene state touched).

**Q2 — Does `-execRSCMD` support nine or ten arguments, and is `$(arg0)` real?**
`appbasics/allcommands` and `tutorials/commandline_rscmd` disagree in the same build.
*Probe:* an `.rscmd` containing `-tag $(arg0)` and `-tag $(arg9)`, invoked with ten arguments,
run with `-stdConsole` so `-tag` output is visible (~1 min).

**Q3 — Where does `-getStatus` output actually go, and is it parseable?**
The Help says the result appears in the *instance's* console yet shows a redirect on the *calling*
process. This repo has never read it. *Probe:* `RealityScan.exe -getStatus RS1 > status.txt` during a
long align, then read `status.txt` (seconds). Payoff: a real progress query independent of the
progress file — a second, independent monitor.

**Q4 — Is `-deleteAutosave` valid as a standalone command?**
`startRealityScan.bat`'s reuse branch passes it as one, but the Help documents it only as a parameter
of `-load`. *Probe:* delegate `-deleteAutosave` alone to an idle instance and check whether
`errors_<inst>.txt` gains an `0x82000060` line (seconds).

**Q5 — How long does `-quit` take on a very large scene?**
The 900 s verification bound has only been exercised on small scenes.
*Probe:* time `-quit` → `-getStatus` gone once on a 4,000+ camera scene; costs one teardown that was
going to happen anyway.

**Q6 — Does `-writeProgress` append to or truncate an existing file at instance boot?**
Never observed, because the file is always deleted first.
*Probe:* boot an instance twice against a pre-populated progress file and check whether the old lines
survive (~2 min).

**Q7 — What does `-disableOnlineCommunication` break?**
Never used here. It presumably conflicts with `-uploadToSketchfab` and possibly with sign-in refresh.
*Probe:* boot with the flag, run a trivial align, and check for any new prompt or failure (~5 min);
a second cell adds `-uploadToSketchfab` with a dummy token and reads the result code.

**Q8 — Can a headless RealityScan 2.2 hit a licence/sign-in prompt that manifests as a silent hang?**
The Help explicitly names the log-in window as unsuppressable; two years here have never seen one.
*Probe (partial, cheap):* sign out in the GUI, then boot headless and delegate `-newScene`; observe
whether the instance appears via `-getStatus` and whether a window opens. Note this deliberately puts
the box into the failure state, so run it when no production work is queued.

**Q9 — Is there a `-set` key for GPU *selection* (the GUI's "GPUs to use")?**
None appears in the Help key tables; `CUDA_VISIBLE_DEVICES` is the working lever.
*Probe:* set the GPU selector in the GUI, export global settings
(`-exportGlobalSettings settings.rcconfig`), change the selector, export again, diff (~5 min, needs
the GUI). This also settles the `.rcconfig`/`.rsconfig` extension contradiction.

**Q10 — Do two concurrent instances on different GPUs interfere?**
Untested. Marker files and locks are already per instance; cache and log are shared (§11, §14).
*Probe:* boot `RS1` on GPU 0 and `RS2` on GPU 1, align two small zones simultaneously, confirm marker
isolation, compare wall clock against the same zones run sequentially, and check whether the shared
`RealityScan.log` splices (it will — see §11).

**Q11 — What does `appCopyImportedComponentsToCache` change?**
Unmeasured, and potentially relevant to the relocated-component hang (hard rule 7).
*Probe:* import the same small `.rsalign` in place with the key `false` then `true`, timing both, and
then repeat with a relocated copy under a watchdog (~15 min total, small components only).

**Q12 — Is the crash-dump filename timestamp UTC, or a hard-coded offset?**
Re-measured 2026-08-04: the one dump on disk has filename `…-20260726-054742` and NTFS CreationTime
`2026-07-26 01:47:42` local on a UTC−4 machine — exactly 4 h, so "UTC" fits. One machine, one
timezone, one artifact cannot distinguish "UTC" from any other rule that happens to produce +4 h here.
*Probe:* compare the next dump's filename against its CreationTime, ideally after a DST change or on
a differently-offset machine — zero cost, just look.

**Q13 — Which settings genuinely require `-preset` rather than `-set`?**
`-preset` is documented but unused here, and no document lists its key set. The only
restart-requiring examples in the Help use `-set` + `appQuitOnReset`.
*Probe:* `-preset "appCacheLocation=Custom"` at startup versus the documented `appQuitOnReset` dance;
observe whether the app quits (~2 min).

**Q14 — Does the parser reject `-listen`, or is it an undocumented switch?**
The substring `listen` appears in the entire 2.2 Help only in `tools/apinode`, describing RSNode's
own bind address/port. Absence from the docs is not absence from the parser.
*Probe:* boot an instance, delegate `-listen`, and check whether `errors_<inst>.txt` gains an
`0x82000060` unknown-command line (seconds). The same probe form settles any suspected switch.

**Q15 — What happens when two processes claim the same `-setInstanceName`?**
Undocumented. The repo prevents it with a PID lock file (§5.4) rather than relying on RealityScan.
*Probe:* boot `RS1`, boot a second instance also named `RS1`, then `-getStatus RS1` and
`-delegateTo RS1 -newScene`; observe which instance responds (~2 min, no scene state at risk).
Payoff: tells you whether the lock file is defence-in-depth or the only defence.

**Q16 — Should `ExportDeliverables.bat:try_delete_model` match a specific code?**
It currently files *any* error as expected (§6.3), so a real failure inside the residual-model sweep
is invisible. The expected miss is `2147942487`.
*Probe:* none needed — this is a code change, not an experiment: add the
`findstr /c:"2147942487"` guard used by `:run_peelrename`. Left as an open item because changing it
without a run to validate against would be an untested edit to a production workflow.
