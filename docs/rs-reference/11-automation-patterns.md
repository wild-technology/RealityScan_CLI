# Large-scale automation patterns and end-to-end recipes

This document is the harness half of the manual: how to build a production pipeline that
drives RealityScan 2.2 headless, unattended, for hours to days, at 8,000+ camera scale,
without lying to itself about what happened. It covers instance lifecycle, the
synchronisation contract, the completion-trigger hook, marker-file ownership, the
cmd/.bat data boundary, multi-GPU isolation, progress/stall monitoring, checkpoint and
rollback, census-based verification, log snapshotting, four complete end-to-end recipes,
and an anti-pattern list. It does **not** re-document individual commands or `-set` keys
(see `02-command-reference.md` and `03-settings-keys.md`), the semantics of alignment and
component merging (see `07-alignment.md` and `08-components-and-merge.md`), XML
parameter-file schemas (see `09-xml-parameter-files.md`), georeferencing/flight-log
formats (see `06-georeferencing-flightlogs-and-scale.md`), or the per-failure catalogue
with its `F-nn` entries (see `12-failure-modes-and-race-conditions.md`). The startup
switches, progress-file format and result codes this document builds on are in
`01-cli-fundamentals.md`. Where a fact about a command is load-bearing *for the harness*,
it is repeated here with its tag rather than cross-referenced away.

**Applies to:** RealityScan 2.2 (Epic Games), Windows, headless CLI operation.
**Tags:** [OFFICIAL] shipped Help · [VERIFIED] measured in production here ·
[CONTRADICTED] docs vs observation · [UNDOCUMENTED] · [INFERRED] · [OPEN]

**Citation keys used here.** `FINDINGS <date>` = the repo-root `FINDINGS.md` entry with
that date. `NA167 #n` = the frozen numbered log `testing/FINDINGS.md` (#1–31).
`NA167 Bn` = the bug list in `testing/NA167_SESSION_NOTES.md` §2 — **note that source
reuses `B10` and `B11` for two different findings each**, so every `Bn` citation in this
document names its subject (e.g. "NA167 B10 (LF endings)" vs "NA167 B10 (ordinal XMP)").
`HANDOFF <item>` = `HANDOFF.md`. Help topics are cited by their converted path, e.g.
`appbasics/allcommands` = `Help/en-US/appbasics/allcommands.htm`.

---

## Contents

1. [The persistent-instance pattern](#1-the-persistent-instance-pattern)
2. [The canonical `:run` subroutine](#2-the-canonical-run-subroutine)
3. [The completion-trigger pattern (ErrorWriter)](#3-the-completion-trigger-pattern-errorwriter)
4. [Marker-file hygiene](#4-marker-file-hygiene)
5. [Crossing the cmd/.bat boundary](#5-crossing-the-cmdbat-boundary)
6. [Multi-GPU and multi-instance](#6-multi-gpu-and-multi-instance)
7. [Progress monitoring and stall detection](#7-progress-monitoring-and-stall-detection)
8. [Checkpoint, rollback, and verification by census](#8-checkpoint-rollback-and-verification-by-census)
9. [Log snapshotting](#9-log-snapshotting)
10. [End-to-end recipes](#10-end-to-end-recipes)
11. [Anti-patterns](#11-anti-patterns)
12. [Environment-variable contract](#12-environment-variable-contract)
13. [Open questions](#open-questions)

---

## 1. The persistent-instance pattern

### 1.1 The shape

One long-lived, named, headless `RealityScan.exe` process per GPU set. Every operation is
handed to it with `-delegateTo <instance> <command>`. The orchestrating `.bat` and the
Python driver above it are short-lived clients that never hold scene state.

```
Python driver (RealityScanCLI)
  └─ launches ONE .bat workflow per unit of work, blocks, monitors
       └─ .bat calls startRealityScan.bat  → boots or reuses instance RS1
       └─ .bat runs :run <cmd> ... :run <cmd>   (each = delegate + double wait + error gate)
       └─ .bat ends with  -delegateTo RS1 -quit
  └─ Python verifies the instance is GONE via -getStatus before the next workflow
```

### 1.2 Why this beats one process per operation

| Concern | Persistent instance | One process per operation |
|---|---|---|
| Scene state | Lives in the instance; `-addFolder`, `-align`, `-exportXMP` see the same scene | Every process starts a new scene; a scene must be `-save`/`-load` round-tripped between every step |
| Feature cache | Warm across operations in one session | Cold every time |
| Load cost | One `PROJECT_LOAD` (`20532`) per workflow | One per operation; a 95 GB six-component assembly takes 13.1 min to save [VERIFIED: FINDINGS 2026-07-29] |
| Destructive in-memory loops (the identity harvest) | Possible — save once, peel in memory, quit without saving | Impossible |
| Error channel | One `appProcessExecCmd` hook armed once at boot, covering everything | Must be re-armed per process |
| GPU pinning | One `CUDA_VISIBLE_DEVICES` decision at boot | Per-process, and RS uses all CUDA GPUs by default [VERIFIED: startRealityScan.bat] |

The single hard requirement it imposes: **completion must be synchronised explicitly**,
because delegated commands are queued FIFO and the delegating process returns at
hand-over, not at completion [VERIFIED: NA167_SESSION_NOTES §1; HANDOFF 2026-07-21].
That is what §2 exists for.

Ceiling: **4 concurrent instances** [OFFICIAL: tutorials/commandline_deleg,
tutorials/headless]. Instance names cannot contain spaces [OFFICIAL: same].

### 1.3 The boot script, annotated

`modules/realityscan_interface/RS_CLI/Scripts/startRealityScan.bat`, verbatim in the
load-bearing parts:

```bat
:: Test whether our instance is already running
%RealityScan% -getStatus %RS_INSTANCE% >nul 2>&1
IF /I "%ERRORLEVEL%"=="0" (
    echo RealityScan instance %RS_INSTANCE% is already running - reusing it with a fresh scene
    %RealityScan% -delegateTo %RS_INSTANCE% -newScene -deleteAutosave
    goto :eof
)

:: Optional GPU pinning: RS_GPU_DEVICES (e.g. "0" or "0,1")
if defined RS_GPU_DEVICES set CUDA_VISIBLE_DEVICES=%RS_GPU_DEVICES%

set "RS_CACHE_ARGS="
if defined RS_CACHE_DIR (
    if not exist "%RS_CACHE_DIR%" mkdir "%RS_CACHE_DIR%"
    set "RS_CACHE_ARGS=-set "appCacheLocation=Custom" -set "appCacheCustomLocation=%RS_CACHE_DIR%""
    echo Cache location: %RS_CACHE_DIR%
)

start "" %RealityScan% %RS_HEADLESS_FLAG% -silent "%ErrorPath%" -setInstanceName %RS_INSTANCE% %RS_CACHE_ARGS% -set "appAutoSaveMode=false" -set "appQuitOnError=false" -set "appProcessActionTime=0" -set "appProcessAction=ExecuteProgram" -set "appProcessExecCmd=wscript.exe //B \"%ErrorPath%\ErrorWriterLaunch.vbs\" $(processResult) $(processId) $(processDuration:d) %RS_INSTANCE%" -writeProgress "%ErrorPath%\progress_%RS_INSTANCE%.txt" 600

echo Waiting until the RealityScan instance %RS_INSTANCE% is ready

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

Every element, and why:

| Element | Reason |
|---|---|
| `-getStatus %RS_INSTANCE%` first | `-getStatus` returns errorlevel 0 **iff the instance exists** — this is the readiness *and* liveness test. [UNDOCUMENTED: the Help documents only that it prints progress; the errorlevel contract is established here] [VERIFIED: startRealityScan.bat, in production since 2026-07-21] |
| Reuse branch `-newScene -deleteAutosave` | Attaching to a live instance is cheaper than a boot, but the scene must be reset or the previous workflow's components contaminate this one. **Caveat:** `deleteAutosave` is documented only as an *optional parameter of `-load`* (`load MyProject.rsproj recoverAutosave\|deleteAutosave`), and `-newScene` is documented as taking **no** parameters [OFFICIAL: appbasics/allcommands]. Whether it does anything after `-newScene` is [OPEN — see A16]; it has never produced an error, and no stale autosave has been observed since `appAutoSaveMode=false` was pinned [VERIFIED: HANDOFF verification item 7, 2026-07-21] |
| `start ""` | Detaches the instance from the .bat; the .bat must return so `:run` can begin delegating |
| `%RS_HEADLESS_FLAG%` = `-headless`, empty when `RS_HEADLESS=0` | `-headless` must be given at startup [OFFICIAL: tutorials/headless]. A GUI-visible instance behaves identically for delegation and monitoring [VERIFIED: SetVariables.bat + all merge/model runs of 2026-07-28/29 ran `RS_HEADLESS=0`] |
| `-silent "%ErrorPath%"` | Suppresses warning dialogs and redirects crash minidumps to that folder [OFFICIAL: appbasics/allcommands, tutorials/commandline_5]. **Side effect that bites:** under `-silent` the "Export Selection" dialog is auto-answered, so a selection-driven export with a stray active selection exports *nothing* and reports success (0.057 s instead of 20.5 s) [VERIFIED: FINDINGS 2026-07-23] |
| `-setInstanceName %RS_INSTANCE%` | The delegation address |
| `-set "appAutoSaveMode=false"` | Default is **true** [OFFICIAL: tutorials/setkeyvaluetable], so this must be turned off explicitly. Autosave would race the destructive in-session identity loop, and a modal recovery dialog hangs a headless box forever. No stale autosaves appeared in any test run afterwards [VERIFIED: HANDOFF verification item 7, 2026-07-21] |
| `-set "appQuitOnError=false"` | Warning-class results (`0x820000FF`, e.g. `err:18002`) are routine here; the orchestrator decides what is fatal, not the app [VERIFIED-as-decision: startRealityScan.bat] |
| `-set "appProcessActionTime=0"` | Default is **15** seconds [OFFICIAL: tutorials/commandline_5, setkeyvaluetable]. `0` means the completion hook fires for *every* process however short — without it, fast failures are invisible |
| `-set "appProcessAction=ExecuteProgram"` | Arms the hook (§3). Ordinal `2` is equivalent [OFFICIAL: tutorials/commandline_5] |
| `-set "appProcessExecCmd=…"` with `\"` around the VBS path | Unquoted paths silently disabled **all** error detection when the checkout path contained spaces [VERIFIED: HANDOFF overhaul item 4, 2026-07-21] |
| `-writeProgress "…\progress_%RS_INSTANCE%.txt" 600` | Per-instance progress marker; the `600` timeout also emits periodic records [OFFICIAL: tutorials/commandline_5] |
| `RS_CACHE_ARGS` opt-in | The cache is placed by the **drive of the path given** and does **not** move when the project moves. `D:\rccache` reached 1,089 GB and killed the hull model three times while the project drive showed 773.9 GB free [VERIFIED: FINDINGS 2026-07-26]. Keys: `appCacheLocation` = `SystemTemp` \| `Custom`; `appCacheCustomLocation` = path (used when `Custom`) [OFFICIAL: tutorials/setkeyvaluetable] |
| 120 × ~1 s readiness poll | Literal `if %startTries% GEQ 120` [VERIFIED: startRealityScan.bat]. This is the only startup bound |
| `-stdConsole` **absent** | Removed 2026-07-23: it allocates a console window per instance boot and nothing reads instance stdout [VERIFIED: startRealityScan.bat comment] |
| `appAutoClearCache` **untouched** | Retention is owner policy, not a per-run decision [VERIFIED-as-decision: startRealityScan.bat]. Values are a retention age in days; `999999` = never clear, `0` = clear all, default **`7` (items older than one week)** [OFFICIAL: tutorials/setkeyvaluetable] |
| `appQuitOnReset` **not used at boot** | Some settings need an application restart; `-set "appQuitOnReset=true"` suppresses the restart dialog **and quits the app** after the setting changes [OFFICIAL: tutorials/commandline_5]. Cache location is one such setting, which is why this pipeline sets it **at boot** in the same command line instead of on a live instance [INFERRED from the Help's own cache-change example, which uses three sequential process launches; not measured here] |

### 1.4 Verified shutdown, before anything else starts

Every workflow ends `%RealityScan% -delegateTo %RS_INSTANCE% -quit` — including the
`:fail` path, so a failed run never leaves an instance holding the scene. The Python layer
then *proves* it is gone:

```python
SHUTDOWN_VERIFY_TIMEOUT_SECONDS = 900
STATUS_CALL_TIMEOUT_SECONDS = 60

def wait_for_instance_shutdown(self, timeout=None):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not self.is_instance_running():   # -getStatus, errorlevel 0 == exists
            return True
        time.sleep(PROGRESS_POLL_SECONDS)    # 2.0
    return False
```

- A `-getStatus` call that *times out* is treated as **running**, not dead — callers stay
  conservative [VERIFIED-by-inspection: `realityscan_cli.is_instance_running`].
- Failure to shut down is a hard stop: `run_batch_script` returns `success=False` with
  `errors='instance did not shut down'` and refuses to continue "while it may still hold
  the scene."
- A leftover instance found *before* a workflow starts is shut down first, not attached
  to: it may be hours into an old operation with the marker hooks still armed, so
  attaching would queue behind that work and mix its results into ours
  [VERIFIED-as-design: realityscan_cli.py].
- **[CONTRADICTED — internal]** `CLAUDE.md` hard rule 3 documents the shutdown bound as
  300 s; the code uses `SHUTDOWN_VERIFY_TIMEOUT_SECONDS = 900` and `HANDOFF.md`
  verification item 5 calls it "the 15-min bound". Two of three agree at 900 s and the
  code is authoritative for behavior; `CLAUDE.md` is stale
  [VERIFIED: realityscan_cli.py lines 190–191; HANDOFF verification item 5].
- The bound is **overridable without editing code**: `wait_for_instance_shutdown` reads
  `realityscan`/`shutdown_timeout` from `rs_settings.json` and falls back to 900 s
  [VERIFIED-by-inspection: realityscan_cli.py].
- Shutdown timing has only been verified on **small** scenes
  [VERIFIED: HANDOFF verification item 5, 2026-07-21].
  [OPEN: how long `-quit` → `-getStatus`-gone takes on a 4,000+ camera scene — see A2.]

---

## 2. The canonical `:run` subroutine

### 2.1 The literal text

Reproduced **byte-for-byte identically** in all twelve workflow scripts: `AlignZone.bat`,
`MergeZoneComponents.bat`, `GenerateModel.bat`, `ExportDeliverables.bat`, `GrowZone.bat`,
`AlignImageList.bat`, `SequentialAlignGrow.bat`, `SaveProjectCopy.bat`,
`ProbeLockAlign.bat`, `ProbeSubsetAlign.bat`, `ProbeSubsetAlign2.bat`, and the deprecated
`AlignImagesFromFolder.bat` (kept only for `testing/run_zone9_tests.py`)
[VERIFIED-by-inspection: RS_CLI/Scripts/*.bat, 2026-08-04]. Only the leading comment
differs between files. Copying it into a new workflow is the sanctioned way to add one —
there is deliberately no shared include, because a `call`ed child `.bat` would add a
process per operation:

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

Call sites use `call :run <cmd> <args> || goto :fail`.

### 2.2 Line by line — each element maps to a real failure

| Line | What it does | The failure it prevents |
|---|---|---|
| `%RealityScan% -delegateTo %RS_INSTANCE% %*` | Hands one operation to the instance's FIFO queue | — |
| `if errorlevel 1` → `ERROR: Failed to delegate command` | Catches a **dead instance**. After a crash, the next delegated command fails with exactly this signature, and a minidump `RealityScanCrash-YYYYMMDD-HHMMSS.dmp` is in the `-silent` folder [VERIFIED: FINDINGS 2026-07-26, hull `closeHoles`/`cleanModel` crash] | Silently continuing to delegate into nothing |
| `ping -n 3 127.0.0.1 >nul` | Grace delay before the first wait. `ping -n N` waits ~N−1 s between packets. `timeout /t N` is not used [INFERRED: Windows `timeout` aborts with "ERROR: Input redirection is not supported" when stdin is redirected, which is exactly how `run_batch_script` launches the `.bat` — never separately measured here; what would settle it is running `timeout /t 2` inside a workflow `.bat` launched by the Python driver] | `-waitCompleted` firing before the instance has dequeued the command |
| `%RealityScan% -waitCompleted %RS_INSTANCE%` (1st) | Blocks until the current process finishes [OFFICIAL: appbasics/allcommands] | — |
| `ping -n 2 127.0.0.1 >nul` | Second grace | Same race, one level deeper |
| `%RealityScan% -waitCompleted %RS_INSTANCE%` (2nd) | **The fix.** `-waitCompleted` returns *prematurely* when issued before the instance picks the queued command up — hit in production [CONTRADICTED: Help implies it blocks until done / observed: premature return; VERIFIED: FINDINGS 2026-07-21] | A workflow racing ahead of a running `-align` and exporting from an unaligned scene |
| `if exist "%ErrorsFile%"` + `if %%~zA GTR 0` | Size-based, not existence-based, gate on `errors_<instance>.txt` | An empty file left by a previous clear aborting a healthy run |
| `exit /b 1` inside the `for … do (…)` body | Propagates because it is inside a `call`ed **subroutine** — see §2.4 | — |

**Why the errors marker and not the exit code:** `-delegateTo` returns at hand-over, so its
exit code says nothing about the operation. `appQuitOnError=false` means the instance does
not die on error. The hook file is the only per-operation result channel
[VERIFIED-as-architecture: realityscan_cli.py module docstring].

**Why not gate on the results log growing:** RealityScan 2.2 emits **periodic internal
heartbeat processes** through the same trigger. "The results log grew" does not mean "our
command finished." A completion check built on results-log growth raced ahead of a running
`-align` and **was removed entirely**
[VERIFIED: FINDINGS 2026-07-21; HANDOFF verification item 2, 2026-07-21].

The abort contract was probed live, not assumed: a probe `.bat` replicating `:run` aborts
(exit 1) with a non-empty errors marker and continues with an empty one — so
`call :run … || goto :fail` really does detect RealityScan errors in every workflow
[VERIFIED: FINDINGS 2026-07-24, consequence (a) of the `exit /b` measurement].

### 2.3 Tolerant variants — the only sanctioned way to whitelist an error

A tolerant variant exists for each *known, benign, reproducible* result code. Every one of
them **moves** the errors marker to a named evidence file rather than deleting it, so the
next `:run` sees a clean marker and the evidence survives.

| Subroutine | File | Whitelisted code | Meaning | Terminal behaviour |
|---|---|---|---|---|
| `:run_geoimport` | `MergeZoneComponents.bat` | `2181038335` (`0x820000FF`) | `-importFlightLog` warning-class: log rows reference images not in the scene; the trajectory imports fine for every image present [VERIFIED: FINDINGS 2026-07-21, 2026-07-25] | continue; marker → `expected_18002_<inst>.txt` |
| `:run_peelrename` | `MergeZoneComponents.bat` | `2147942487` (`0x80070057`, `E_INVALIDARG`) | `-renameSelectedComponent` on an emptied scene — the **peel-exhaustion signal**, because there is no CLI query for "how many components remain" [VERIFIED: FINDINGS 2026-07-24] [UNDOCUMENTED] | `exit /b 2` = loop terminal; marker → `expected_peelend_<inst>.txt` |
| `:try_filter` / `:try_remove` | `GenerateModel.bat` | `2147942487`, `2181038335` | empty triangle selection — a clean mesh with no marginal/large triangles must not abort the recipe | sets `step_skipped=1`, continues; marker → `expected_select_<inst>.txt` |
| `:try_delete_model` | `GenerateModel.bat`, `ExportDeliverables.bat` | any (tolerant delete of an absent intermediate) | missing intermediates from skipped filter steps | continue; marker → `expected_select_<inst>_<name>.txt` / `expected_delete_<inst>_<name>.txt` |

Two rules learned the hard way here:

1. **The errors marker carries only the numeric result code**, never the `err:NNNN` text —
   that exists only in `RealityScan.log`. Tolerant handlers must match **decimal codes**
   with `findstr /c:"2181038335"` [VERIFIED: FINDINGS 2026-07-23].
2. **`:try_delete_model` must use the full double-wait shape.** A single short wait could
   return before the instance picked the `-selectModel` up; a no-op select on a missing
   name then left the *previous* selection live — which at loop entry is the final textured
   model — and the following `-deleteSelectedModel` targeted the deliverable
   [VERIFIED-as-defect-and-fix: GenerateModel audit #4, FINDINGS 2026-07-29].

Evidence filenames must be unique per iteration: a twelve-iteration cleanup loop with one
shared evidence name overwrites its own record [VERIFIED-as-fix: ExportDeliverables.bat
final review; names are `%evname%` with spaces flattened to `_`].

### 2.4 The cmd traps that shape `:run`

These are Windows facts, not RealityScan facts, and every one was hit in production here.

- **`.bat` and `.vbs` must be CRLF.** cmd's label search is byte-offset sensitive: with LF
  endings the same `call :run` resolved ten times and then failed
  (`The system cannot find the batch label specified - run`) at a later call site.
  `.gitattributes` pins `*.bat` and `*.vbs` to `eol=crlf`; re-normalise and re-verify after
  any scripted edit [VERIFIED: NA167 #21 + H2023, independently hit on both machines,
  2026-07-23].
- **`exit /b N` loss — measured, not assumed.** Four probe `.bat`s run via `cmd //c`
  established that the code is lost in exactly one configuration: `exit /b` inside an outer
  **multi-line parenthesised block** (`if (…)` or `for … do (…)`) in the body of the script
  that **is the process entry point**. Measured results:

  | shape | propagated code |
  |---|---|
  | top-level `( echo … & exit /b 1 )` (single line) | **1** — correct |
  | top-level multi-line `if … ( … exit /b 1 )` | **1** — correct |
  | `exit /b 1` in an `if`-block nested inside `if defined … (` | **0** — LOST |
  | `exit /b 1` nested inside `for /f … do (` | **0** — LOST |
  | the same nested shapes inside a `call :label` **subroutine** | **1** — correct |
  | the same inside a `call`ed **child .bat** | **1** — correct |

  Consequence, verified rather than assumed: **the shared `:run` abort contract is live**
  (it is a subroutine), and `startRealityScan.bat`'s nested boot-timeout `exit /b 1`
  propagates correctly. The only genuinely broken sites were `MergeZoneComponents.bat`'s
  top-level complist validations, which returned 0 — an unreadable component list would
  have been reported and then ignored. Fixed by routing every validation to a top-level
  `:argfail` label [VERIFIED: FINDINGS 2026-07-24, superseding a broader 2026-07-23
  statement].

  ```bat
  :: The pattern that works for argument validation at top level
  if [%1] == [] ( echo ERROR: components folder argument required & goto :argfail )
  ...
  goto :args_ok
  :argfail
  exit /b 1
  :args_ok
  ```

- **Fully qualify Windows utilities.** Every workflow writes
  `%SystemRoot%\System32\findstr.exe`, never a bare `findstr`. The measured incident was
  the sibling case: `:run`'s old line-count used a bare `find`, which resolves to **GNU
  `find`** when the workflow is launched from a Git Bash environment, and GNU `find`
  proceeds to scan the whole disk; it was fully qualified to
  `%SystemRoot%\System32\find.exe` [VERIFIED: HANDOFF verification item 2, 2026-07-21].
  `findstr` has no GNU twin on `PATH`, so qualifying it is defence in depth against a
  shadowing script or alias rather than a reproduced failure [INFERRED].
- **Git Bash mangles cmd switches:** `cmd /c foo.bat` under MSYS converts `/c` to `C:\` and
  launches an interactive cmd that exits 0 silently. Use `cmd //c` or PowerShell to test a
  `.bat` [VERIFIED: FINDINGS 2026-07-23].
- **Invoke the `.bat` by absolute path with no `cmd /c` prefix** from Python. A bare script
  name fails to resolve under `NoDefaultCurrentDirectoryInExePath`; a self-built
  `cmd /c "path with spaces.bat"` gets its quotes stripped by cmd. `subprocess` handles
  `.bat` quoting correctly on its own [VERIFIED-as-fix: realityscan_cli.py, HANDOFF
  2026-07-21]:

  ```python
  process = subprocess.Popen([script_path] + list(args), cwd=SCRIPTS_DIR, env=env,
                             stdout=log_file, stderr=subprocess.STDOUT,
                             creationflags=subprocess.CREATE_NO_WINDOW)
  ```

- **`CREATE_NO_WINDOW` on every helper subprocess.** Console-subsystem children
  (`tasklist`, `cmd`, `powershell`) each pop a visible window when the parent has none —
  hundreds of flashing windows stealing focus over a long run
  [VERIFIED: `_NO_WINDOW` in realityscan_cli.py, owner report 2026-07-23].

---

## 3. The completion-trigger pattern (ErrorWriter)

### 3.1 The chain

```
RealityScan.exe  (process finishes, any process, including internal heartbeats)
   │  appProcessAction=ExecuteProgram, appProcessActionTime=0
   ▼
wscript.exe //B  ErrorWriterLaunch.vbs  $(processResult) $(processId) $(processDuration:d) RS1
   │  GUI-subsystem host → no console window
   ▼
cmd /c ""…\ErrorWriter.bat" 0 20599 3 RS1"
   │
   ├─► results_RS1.log    every completion, always
   └─► errors_RS1.txt     only when the result code is not 0 and not 1
```

[VERIFIED: startRealityScan.bat + ErrorWriter.bat + ErrorWriterLaunch.vbs, in production
since 2026-07-21; hook liveness re-tested 2026-07-25]

The `$(…)` substitutions are real and carry result code, process id and duration in
seconds [OFFICIAL: tutorials/commandline_5]. The repo appends a fourth, **its own**,
argument — the instance name — exactly as the Help's example appends a report path
[OFFICIAL: same page shows `… $(processDuration:d) c:\ErrorReportFolder\ErrorReport.txt`].

### 3.2 `ErrorWriter.bat` — verbatim

```bat
:: Process-completion hook invoked by RealityScan itself (appProcessAction=
:: ExecuteProgram / appProcessExecCmd). Arguments:
::   %1 = $(processResult)      result code of the finished process
::   %2 = $(processId)          process id
::   %3 = $(processDuration:d)  duration in seconds
::   %4 = instance name (used to namespace the marker files so parallel
::        instances never read each other's state)
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

Design points:

- **`%~dp0`, not a passed path.** Marker files are written next to the script, so no path
  containing spaces ever has to survive the `appProcessExecCmd` command line
  [VERIFIED-as-design: ErrorWriter.bat header].
- **`>>` not `>`.** The Help's sample uses `>` and overwrites [OFFICIAL:
  tutorials/commandline_5]; a run that produces two failures must keep both.
- **0 and 1 are both success.** Routine successful operations (e.g. `-addFolder`) report
  result **1** through the trigger [VERIFIED: FINDINGS 2026-07-21]. The Help's own sample
  whitelists both [OFFICIAL: tutorials/commandline_5].
- **Instance-namespaced filenames** — see §6.

### 3.3 `ErrorWriterLaunch.vbs` — why the launcher exists

The trigger fires for **every** completed process including internal heartbeats. Invoking
`cmd /c ErrorWriter.bat` directly from `appProcessExecCmd` pops a visible console window
each time — hundreds of flashing terminals over a long run (owner report, 2026-07-23).
`wscript.exe` is a **GUI-subsystem** host: it has no console, so the shim runs the real
`.bat` hidden and synchronously, preserving marker-file write ordering.

```vbs
' Quote composition via Chr(34) - literal escaped quotes in VBS string
' constants caused the original malformed command line. Final shape:
'   cmd /c ""<bat>" <args>"
Dim shell, bat, args, i, q
q = Chr(34)
Set shell = CreateObject("WScript.Shell")
bat = Replace(WScript.ScriptFullName, "ErrorWriterLaunch.vbs", "ErrorWriter.bat")
args = ""
For i = 0 To WScript.Arguments.Count - 1
    args = args & " " & WScript.Arguments(i)
Next
shell.Run "cmd /c " & q & q & bat & q & args & q, 0, True
```

- `//B` on `wscript.exe` = batch mode, no script errors/dialogs.
- `shell.Run …, 0, True` = window style 0 (hidden), `bWaitOnReturn` True (synchronous),
  so two completions cannot interleave their appends.
- **Compose quotes with `Chr(34)`.** The original version used nested literal quotes inside
  VBS string constants, produced a malformed command line, and `ErrorWriter.bat`
  **never ran** — the errors-marker system was **inert for roughly a day of runs**
  [VERIFIED: FINDINGS 2026-07-24]. Completed results from that window stayed trustworthy
  only because they had independent census/manifest validation.

### 3.4 The mandatory liveness self-test

Because the hook is a monitor, it must be verified end-to-end after any change to the
chain, before it is trusted:

> **Diagnostic:** the hook fires for every completed process including heartbeats, so an
> active `progress_<inst>.txt` **without** a growing `results_<inst>.log` is proof the hook
> is dead.

Procedure: start any workflow, watch `results_<inst>.log`. A healthy chain grew with six
completions in ten seconds during a live run [VERIFIED: FINDINGS 2026-07-25, after the
2026-07-24 CRLF normalisation]. Run this at session start for every monitor a long run
depends on.

### 3.5 Result codes seen in production

| decimal | hex | established meaning |
|---:|---|---|
| `0`, `1` | — | routine success (both) [VERIFIED: FINDINGS 2026-07-21] |
| `2181038335` | `0x820000FF` | warning class; `-importFlightLog` `err:18002` (rows not in scene); verified benign by manifest cross-check [VERIFIED: FINDINGS 2026-07-25] |
| `2147942487` | `0x80070057` | `E_INVALIDARG` — empty/no-op selection paths (`-renameSelectedComponent` on an emptied scene, `-selectModel` on a missing name) [VERIFIED: FINDINGS 2026-07-24] |
| `2147549183` | `0x8000FFFF` | generic "unexpected program state" — broken `-set` args **and** the zone_14 align failure emit the identical code. The real reason line (`Internal error MSS_STR001` for zone_14) exists **only** in `RealityScan.log` [VERIFIED: NA167 #16 / B6, #27] |
| `2147942512` | `0x80070070` | `ERROR_DISK_FULL` — RealityScan's **cache** disk, not necessarily the project disk [VERIFIED: FINDINGS 2026-07-26] |
| `2181038176` [INFERRED: arithmetic] | `0x82000060` | unknown/invalid command (e.g. `-selectAllComponents`, which does not exist in 2.2) [VERIFIED: NA167 #13 / B2] |
| `2181038103` [INFERRED: arithmetic] | `0x82000017` | warning-class load complaint from a stale `<name>.rsproj.new` beside the project [VERIFIED: FINDINGS 2026-07-29] |
| `3` | — | crash; minidump written to the `-silent` path [OFFICIAL: tutorials/commandline_5] |

Two decimal values in that table are **converted, not observed** — `0x82000060` and
`0x82000017` were recorded in hex in the findings log, and the marker file carries decimal.
Confirm the decimal against a real `errors_<inst>.txt` before writing a `findstr /c:`
whitelist for either. The conversion base is exact for the family:
`0x82000000` = `2181038080`, and `0x820000FF` = `2181038335` is independently confirmed
against a real marker [VERIFIED: FINDINGS 2026-07-25].

Error codes seen only in `RealityScan.log` (never in the errors marker, because the marker
carries only the process result code):

| token | meaning |
|---|---|
| `err:7155` | `Parsing setting key=value '<key>' failed` — a `-set` that crossed a `.bat` argument boundary and got split [VERIFIED: NA167 #15 / B5] |
| `err:18002` | flight-log rows reference images not in the scene; surfaces as result `0x820000FF` [VERIFIED: FINDINGS 2026-07-21, 2026-07-25] |
| `err:5601` | `'not found'` from `-selectModel` on a name that is not in the project [VERIFIED: FINDINGS 2026-07-29 export probe] |
| `Internal error MSS_STR001` | solver bug in the reconstruction phase; zone_14, 4/4 deterministic, data formally exonerated [VERIFIED: NA167 #27] |
| `Processing failed: Out of disk space..` | the cache-disk failure behind result `0x80070070` [VERIFIED: FINDINGS 2026-07-26] |
| `Finalizing N component(s)` | recorded as a cross-check, never gated on — semantics not established [OPEN — A5] |
| `Added N layer images` | the only place a silently non-recursive `-addFolder` is visible [VERIFIED: FINDINGS 2026-07-23] |

The process-exit-code contract (`0` success, the error's decimal code with
`appQuitOnError=true`, `3` on crash) is [OFFICIAL: tutorials/commandline_5]; this pipeline
keeps `appQuitOnError=false` and reads the hook instead.

---

## 4. Marker-file hygiene

### 4.1 The three markers and who owns them

| File | Written by | Read by | Lifetime |
|---|---|---|---|
| `RS_CLI/Errors/progress_<instance>.txt` | RealityScan (`-writeProgress`) | Python monitor (tail) | cleared before every workflow; held open by the instance while it lives |
| `RS_CLI/Errors/errors_<instance>.txt` | `ErrorWriter.bat` | `:run` (size gate) and the Python monitor | cleared before every workflow; **moved** by tolerant subroutines |
| `RS_CLI/Errors/results_<instance>.log` | `ErrorWriter.bat` | Python (`completed_processes`), hook-liveness test | cleared before every workflow |
| `RS_CLI/Errors/<instance>.lock` | Python `_acquire_lock` | Python | held for the duration of one `run_batch_script` |
| `RS_CLI/Errors/expected_*_<instance>*.txt` | tolerant `:run` variants | humans / post-run audit | persists as evidence |

**These files are the source of truth while a run is live.** Hard rule: clear
`progress` / `errors` / `results` **only** through `RealityScanCLI`, which does it once
pre-run [VERIFIED-as-rule: CLAUDE.md hard rule 4]. Nothing else may touch them mid-run —
a `:run` gate reading a marker someone else just truncated cannot distinguish "no error"
from "error erased."

### 4.2 The 60-second clear retry, and the race it closes

`-getStatus` reports an instance **gone seconds before the process releases its
marker-file handles**. The next workflow's marker clear then races the teardown and fails
with a Windows sharing violation [VERIFIED: NA167 #14 / B3, 2026-07-23].

```python
def _clear_markers(self) -> None:
    for kind in ('progress', 'errors', 'results'):
        deadline = time.monotonic() + 60
        path = self._marker(kind)
        while os.path.isfile(path):
            try:
                os.remove(path)
                break
            except OSError:
                # Windows cannot delete a file another process holds open;
                # give a shutting-down instance time to release it, then
                # treat it as genuinely still running.
                if time.monotonic() > deadline:
                    raise RuntimeError(
                        f'Cannot clear marker file {path} - it is still held '
                        f'open after 60s, most likely by a running RealityScan '
                        f'instance "{self.instance_name}". Shut it down before '
                        'starting a new workflow.')
                time.sleep(2)
```

The retry is **per file** and the timeout is a hard error, not a warning: a marker that
cannot be cleared means an instance is alive, and starting a workflow anyway would read
another run's state.

### 4.3 Ordering: read the markers *after* verified shutdown

```python
return_code = process.returncode
shutdown_ok = self.wait_for_instance_shutdown()
# Read the markers only AFTER shutdown: the final operations can still be
# running when the batch script exits, so an error from them may arrive
# during the shutdown window.
errors  = self._read_marker('errors')
results = [l for l in self._read_marker('results').splitlines() if l.strip()]
success = return_code == 0 and not errors
```

Both conditions are required: exit code **and** empty errors marker. Either alone has been
observed to lie — a `.bat` can `exit /b 0` from a path that never ran the work, and an
instance can report an error after its driving `.bat` has exited.

### 4.4 Preserve evidence, do not delete it

`move /y "%ErrorsFile%" "%ErrorPath%\expected_<reason>_%RS_INSTANCE%.txt"` is the only
sanctioned way to clear a marker mid-run. Deleting it destroys the record of a
whitelisted-but-real event. `expected_peelend_<inst>.txt` in particular *is* the
peel-exhaustion evidence, since no CLI query for component count exists
[VERIFIED: FINDINGS 2026-07-24] — though note it is currently written and never read back
[VERIFIED-as-defect: FINDINGS 2026-07-27].

---

## 5. Crossing the cmd/.bat boundary

### 5.1 The rule

> **Never pass delimited data as a `.bat` argument.** cmd splits unquoted `;` `,` `=` into
> separate arguments, and Python's `subprocess` quotes only on whitespace. **Lists cross
> as files** (`.imagelist`, `.complist`); **settings cross as `key:value`** and the
> workflow converts the colon to `=` inside cmd, where it is safe.
> [VERIFIED: NA167 B5, 2026-07-23; CLAUDE.md hard rule 8]

### 5.2 The failure this prevents — three simultaneous consequences

A merge cell passed `sfmMergeGeoreferencedComponents=false` as an argument. What actually
happened:

1. cmd split it into two arguments at the `=`.
2. RealityScan logged
   `Parsing setting key=value 'sfmMergeGeoreferencedComponents' failed [err:7155]` and
   `'false' failed` — so **the flag was never applied**. Every flag cell before wave 1f had
   silently been running on whatever the instance's persisted value was.
3. The parse errors were reported through the completion hook, landed in
   `errors_<instance>.txt`, and **spuriously aborted the very workflow that carried them**
   at the next `:run` gate.

One quoting mistake produced a silently unapplied setting, a corrupted experiment, and a
false failure at once [VERIFIED: NA167 #15 / B5, 2026-07-23].

Compounding fact: **swept `-set` values persist across instance restarts**, so a cell that
"failed to apply" a flag was not running at the default — it was running at whatever the
last successful `-set` left behind. Every cell must pin every key it depends on
[VERIFIED: MERGE_TEST_PLAN §3 contamination controls, 2026-07-23].

### 5.3 Lists cross as files

**`.imagelist`** — full image paths, one per line, consumed by `-add <file.imagelist>`
[OFFICIAL: appbasics/allcommands]. CRLF is fine [VERIFIED: NA167 wave-1 A2, 2026-07-23].

```
F:\na156_h2024_v2\batched_images_by_zone\zone_1\C231C1034_20231104202628_edt.jpg
F:\na156_h2024_v2\batched_images_by_zone\zone_1\P231C1034_20231104202628_edt.jpg
```

**`.complist`** — a repo convention (not a RealityScan file type): one `.rsalign` path per
line, consumed by `MergeZoneComponents.bat`, which loops
`for /f "usebackq delims=" %%F in ("%components_dir%") do call :run -importComponent "%%~F"`.
The paths must be the components' **original export locations**: a relocated `.rsalign`
imports into a permanent `#timeout` stall (≥6 h observed, no error, no dump)
[VERIFIED: NA167 #11 / B1; CLAUDE.md hard rule 7].

**BOM trap:** `Set-Content -Encoding utf8` in Windows PowerShell 5.1 writes a BOM, and a
BOM on line 1 of a `.complist` silently invalidates the first entry (`merge_zones` read
`\ufeffF:\...\zone_1_c6.rsalign`, found no manifest, aborted). Python's
`encoding='utf-8'` writes no BOM. From PowerShell use
`[System.IO.File]::WriteAllLines($p,$lines,(New-Object System.Text.UTF8Encoding($false)))`
[VERIFIED: FINDINGS 2026-07-27, confirmed by reading bytes 239,187,191].

Writer used in production (Python, CRLF, no BOM):

```python
with open(complist, 'w', encoding='utf-8', newline='\r\n') as f:
    f.write('\n'.join(m['rsalign'] for m in subset) + '\n')
```

### 5.4 Settings cross as `key:value`

Driver side (`merge_zones.LADDERS`):

```python
{'label': 'align_rematch', 'mode': 'align',
 'settings': ['sfmMergeGeoreferencedComponents:true',
              'sfmEnableCameraPrior:true',
              'sfmForceComponentRematch:true']}
```

Workflow side (`MergeZoneComponents.bat`), where `%kv::==%` is cmd substring replacement of
`:` by `=`:

```bat
if not [%6] == [] call :applySet "%~6"
if not [%7] == [] call :applySet "%~7"
if not [%8] == [] call :applySet "%~8"
if not [%9] == [] call :applySet "%~9"
goto :afterSets

:applySet
set "kv=%~1"
set "kv=%kv::==%"
echo Setting %kv%
%RealityScan% -delegateTo %RS_INSTANCE% -set "%kv%"
exit /b 0
:afterSets
```

The `-set` is fired **without** a `:run` wait: `-set` is instant, and delegated commands
execute FIFO, so it is guaranteed to be applied before the queued `-align`/`-mergeComponents`
that follows [VERIFIED-as-design: AlignZone.bat and MergeZoneComponents.bat comments;
FIFO ordering VERIFIED: NA167_SESSION_NOTES §1].

The same trick is what lets `-editInputSelection "key=value"` work: the pair is composed
**inside** the `.bat` as one quoted argument, so cmd never sees a bare `=` at an argument
boundary [VERIFIED: FINDINGS 2026-07-23, cell U19]:

```bat
:selEnable
if /i "%RS_GROW_SELECT_CMDS%" == "legacy" goto :selEnableLegacy
call :run -editInputSelection "inpEnabled=true"
goto :eof
:selEnableLegacy
call :run -enableAlignment true
```

`-editInputSelection` is the master per-image control and it operates on the **current
image selection**: enable-alignment (`inpEnabled`), features source (`aligFeaturesMode`
`0|1|2`), per-image prior pose (`inpPose` `0`–`3` plus translation/rotation accuracies and
locked-pose groups), and full calibration/lens priors (`inpCalibrationGroup`,
`inpCalibration` `Unknown|Approximate|Fixed`, `inpFocal`, principal point,
`inpDistortionModel` `0`–`5`, coefficients)
[OFFICIAL: tutorials/editselectioncommand; VERIFIED: FINDINGS 2026-07-23, cell U19].
`GrowZone.bat` keeps `-enableAlignment true|false` / `-setFeatureSource N` as a verified
fallback behind `RS_GROW_SELECT_CMDS=legacy`.

### 5.4a Building the selection is the expensive part — and the docs are wrong about how

> **[CONTRADICTED]** The Help gives `-selectImage <imagePath|regexp> [set|union|sub|
> intersect|toggle]` [OFFICIAL: appbasics/allcommands]. **Observed in 2.2: `-selectImage`
> matches LITERAL FULL PATHS ONLY.** Bare regexp, dot-star-wrapped regexp, glob, and
> regexp with an explicit `set` modifier **all silently select nothing**; a literal full
> path selects exactly its image. Established by bisection probes U-SEL2 through U-SEL8
> [VERIFIED: FINDINGS 2026-07-23, cells U1/U19/U2].
>
> **Harness consequence:** a selection is composed by a per-image literal `-selectImage`
> union loop at roughly **0.1–0.3 s per image** — budget *minutes* for a thousand-image
> set, and prefer `.imagelist`-driven scene construction over in-scene selection whenever
> the choice exists. "Silently select nothing" also means a selection-driven operation
> reports success having touched zero images, which is another entry on the
> silent-success list in §11.

### 5.5 Reading settings out of an XML and applying them one at a time

`-align` takes **no parameters** in 2.x — a params XML passed to it is silently ignored
[CONTRADICTED: pre-2.x lore and older repo scripts passed a params file / observed:
argument ignored, confirmed against `appbasics/allcommands`; VERIFIED: FINDINGS
2026-07-21]. So `AlignmentParams.xml` is *parsed* and each `sfm*`/`lis*` entry is applied
as its own delegated `-set`:

```bat
for /f usebackq^ tokens^=2^,4^ delims^=^" %%A in ("%AlignmentParams%") do (
    echo %%A| %SystemRoot%\System32\findstr.exe /b /c:"sfm" /c:"lis" >nul
    if not errorlevel 1 %RealityScan% -delegateTo %RS_INSTANCE% -set "%%A=%%B"
)
```

`delims=^"` splits the XML line on double quotes; tokens 2 and 4 are the attribute name and
its value. The caret escapes are required because `for /f` options containing `=` and `"`
must be escaped when written inline. Policy: **never align on instance defaults** — an
instance carries whatever the last GUI or CLI session set
[VERIFIED-as-policy: FINDINGS 2026-07-21/23].

### 5.6 What does not fit in `%1..%9` goes in the environment

`MergeZoneComponents.bat` exhausts its nine positional slots on
`complist, out_dir, name, mode, min_size, set1..set4`, so the flight log, harvest mode and
image root travel as environment variables set by the driver immediately before launch:

```python
os.environ['RS_MERGE_FLIGHT_LOG']        = flight_log
os.environ['RS_MERGE_FLIGHT_LOG_PARAMS'] = params or ''
os.environ['RS_MERGE_HARVEST']           = '1'
os.environ['RS_MERGE_IMAGES_ROOT']       = images_root
args = [complist_path, out_dir, name, mode, '1'] + settings
return cli.run_batch_script('MergeZoneComponents.bat', args, logs_dir)
```

Variables are **popped**, not left stale, when the feature is off — a leftover
`RS_MERGE_HARVEST` from a previous attempt would silently change the next one's behaviour
[VERIFIED-by-inspection: `run_merge_workflow`].

### 5.7 Argument contracts of the shipped workflows

| Script | `%1` | `%2` | `%3` | `%4` | `%5` | `%6`–`%9` |
|---|---|---|---|---|---|---|
| `AlignZone.bat` | zone image dir | component output dir | flight log or `""` | flight-log params xml or `""` | scene name | `%6` min component size (default 50) |
| `MergeZoneComponents.bat` | `.complist` **or** folder of `.rsalign` | output dir | merged name | mode `merge`\|`align`\|`assemble` | min component size (default 50) | up to four `key:value` settings |
| `GenerateModel.bat` | `.rsproj` path | component name (`""` = maximal) | large-triangle threshold (default 30) | — | — | — |
| `ExportDeliverables.bat` | `.rsproj` path | output dir | component-name list file | — | — | — |
| `GrowZone.bat` | scene `.rsproj` | mode `global`\|`component`\|`merge`\|`export`\|`cleanup`\|`addgrow` | payload file or `-` | features source `0`\|`1`\|`2` or `-` | export dir | `%6` min size, `%7` secondary `.imagelist` or `-` |
| `AlignImageList.bat` | `.imagelist` | flight log or `""` | flight-log params or `""` | output dir | scene/component name | — |
| `SequentialAlignGrow.bat` | flight-log params xml | output dir | scene name | imagelist 1 | flight log 1 | `%6`–`%9` = imagelist 2/log 2, imagelist 3/log 3 |
| `SaveProjectCopy.bat` | source `.rsproj` | destination `.rsproj` | — | — | — | — |

[VERIFIED-by-inspection: RS_CLI/Scripts/*.bat, 2026-08-04]

Not in the table and deliberately so: `AlignImagesFromFolder.bat` (`%1` input dir, `%2`
component output dir, `%3` flight log, `%4` flight-log params, `%5` generate model, `%6`
cull polygons, `%7` scene name, `%8` texture model, `%9` simplify model) is **DEPRECATED**
— it is the pre-consolidation workflow, exhausts all nine slots on booleans, and survives
only because `testing/run_zone9_tests.py` still calls it. Do not build on it; `AlignZone.bat`
plus `GenerateModel.bat` is the supported split [VERIFIED: FINDINGS 2026-07-28 deprecation
sweep; CLAUDE.md architecture section].

Three shapes recur across all of them and are worth copying:

```bat
:: required argument - single-line paren + & is a MEASURED-SAFE exit /b site (§2.4)
if [%1] == [] ( echo ERROR: zone input directory required & exit /b 1 )
:: optional argument with a default
set "min_component_size=%~6"
if "%min_component_size%" == "" set "min_component_size=50"
:: every path checked BEFORE the instance is booted - a typo costs a second, not a boot
if not exist "%input_dir%" ( echo ERROR: input directory not found: %input_dir% & exit /b 1 )
```

`AlignZone.bat`, `GenerateModel.bat`, `ExportDeliverables.bat` and `SaveProjectCopy.bat`
use exactly that `& exit /b 1` form, which the measurement in §2.4 shows propagates
correctly at top level. `MergeZoneComponents.bat` routes to `goto :argfail` instead —
**not** because the single-line form is unsafe, but because its complist validations sit
inside a `for /f … do (…)` body, which is one of the two measured code-losing shapes
[VERIFIED: FINDINGS 2026-07-24].

---

## 6. Multi-GPU and multi-instance

### 6.1 Pinning

RealityScan uses **all** CUDA GPUs by default. One instance per GPU set:

```bat
if defined RS_GPU_DEVICES set CUDA_VISIBLE_DEVICES=%RS_GPU_DEVICES%
```

```python
gpu_devices = gpu_devices if gpu_devices is not None else self.settings.get('realityscan', 'gpu_devices')
if gpu_devices:
    env['RS_GPU_DEVICES']      = str(gpu_devices)
    env['CUDA_VISIBLE_DEVICES'] = str(gpu_devices)
```

Give each concurrent instance a **unique** `instance_name` [VERIFIED-as-design:
realityscan_cli.py module docstring; startRealityScan.bat].

### 6.2 The lock file — one orchestrator per instance name

`RS_CLI/Errors/<instance>.lock` holds the driving PID. Acquisition is `O_CREAT|O_EXCL`, so
the check-then-create window is closed; a stale lock whose PID is gone is removed with a
warning; a live PID raises and names the holder:

```python
if holder_pid and self._pid_alive(holder_pid):
    raise RuntimeError(
        f'RealityScan instance "{self.instance_name}" is already being driven by '
        f'PID {holder_pid} (lock: {lock_path}). Use a different instance_name to '
        'run workflows in parallel, or wait for the other run to finish.')
```

`_pid_alive` uses `tasklist /FI "PID eq <pid>" /NH /FO CSV` and compares the **PID field
exactly** — a substring check would match PID 123 against 1234 (or a memory column) and
treat a stale lock as live [VERIFIED-as-design: realityscan_cli.py]. The `tasklist` call
carries `CREATE_NO_WINDOW`.

Note this is a lock on *driving an instance name*, **not** a completion signal: never infer
completion from process names. The pre-2.x code polled `tasklist` for
`RealityCapture.exe`, which silently matched nothing once the executable became
`RealityScan.exe` [VERIFIED-as-history: CLAUDE.md hard rule 2].

### 6.3 Marker namespacing

Every marker is per instance, so two instances can never read each other's state:

```python
names = {'progress': f'progress_{self.instance_name}.txt',
         'errors':   f'errors_{self.instance_name}.txt',
         'results':  f'results_{self.instance_name}.log'}
```

and the instance name is passed to `ErrorWriter.bat` as `%4` so the *writer* namespaces
too. Both halves are required — namespacing only the reader would still let two instances
append to one errors file.

### 6.4 What is and is not safe to run concurrently

| Combination | Verdict |
|---|---|
| Two named instances, distinct `RS_INSTANCE`, distinct `RS_GPU_DEVICES`, distinct workspaces | [INFERRED] designed for and structurally isolated (lock + markers + GPU), but **never run**. [OPEN — see §Open questions] |
| Two drivers on the **same** instance name | Refused by the lock file [VERIFIED-as-design] |
| Two instances sharing one **cache directory** | [OPEN] — untested; the cache is per-path, not per-instance |
| Two instances writing pose XMPs into the **same image tree** | **Unsafe.** Sidecars are written beside the images by stem; two runs would overwrite each other's census and each other's calibration priors [INFERRED from the sidecar rules in §8.4; not measured] |
| Two instances while one snapshots `RealityScan.log` | **Unsafe and observed:** the log is global and truncated per boot, so a snapshot became a splice of two runs (an H2023 attempt's snapshot recorded `importComponent` of eleven H2024 components) [VERIFIED: FINDINGS 2026-07-27] — see §9 |
| A GUI session holding the deliverable project open while a workflow `-load`s it | **Blocks in practice.** An owner GUI session holding `H2024_Final_Assembly` open blocked the export probe [VERIFIED-as-incident: HANDOFF 2026-07-29] |

### 6.5 The `RS_INSTANCE` resolution defect — read this before writing a driver

Until 2026-07-28 `realityscan_cli.py` resolved the instance from *constructor arg →
`rs_settings.json` → default* and only ever **wrote** the `RS_INSTANCE` environment
variable for the `.bat` layer. Every driver that exported `RS_INSTANCE=RS2` for isolation
was **decorative**: a cross-session incident ran a probe on RS1 believing it was on RS2 and
could have `-quit` a live production instance. The fixed order is:

```python
self.instance_name = (instance_name
                      or os.environ.get('RS_INSTANCE')
                      or self.settings.get('realityscan', 'instance_name')
                      or DEFAULT_INSTANCE_NAME)     # 'RS1'
```

[VERIFIED-and-fixed: FINDINGS 2026-07-28, audit #19]

**Lesson for any harness:** an isolation knob that is only ever written and never read is
indistinguishable from a working one until it costs you a production instance.

---

## 7. Progress monitoring and stall detection

### 7.1 The progress file

`-writeProgress <fileName> [timeout]` appends every progress change; the optional timeout
also emits periodic records [OFFICIAL: appbasics/allcommands]. Five whitespace-separated
columns [OFFICIAL: tutorials/commandline_5]:

```
algId  progress  duration  estimation  eventType
20561  0.00      0.04      404.08      #started
20561  0.45      0.10        0.22      #progress
20561  1.00     17.13        0.00      #completed
```

- `algId` — process id; the table is in `tutorials/processids`
  (`20562 CALCULATE_MODEL_HIGH`, `65537 ALIGN_NORMAL`, `77840 SFM_ALIGNMENT_MAIN`,
  `20598 IMPORT_FLIGHT_LOG`, `20584 EXPORT_XMP`, `20594 IMPORT_COMPONENT`, …).
- `progress` — fraction in ⟨0,1⟩.
- `eventType` ∈ `#started`, `#progress`, `#timeout`, `#completed`.

### 7.2 `#timeout` — three causes, one appearance

`#timeout` is one of the four documented `eventType` values
[OFFICIAL: tutorials/commandline_5, which lists `{started, progress, timeout, completed}`
and says nothing further about it]. That it means "no progress produced within the
`-writeProgress` timeout window" is [INFERRED] from the timeout parameter's own definition;
what is measured here is the consequence: the elapsed counter **keeps ticking** across
`#timeout` records and `estimation` becomes garbage, so **`#timeout` lines are not
progress — treat them as stall evidence**
[VERIFIED: NA167 #12 / B4 and NA167_SESSION_NOTES §1, 2026-07-23].

| Cause | Signature | Response |
|---|---|---|
| Genuine hang | `#timeout` **from fraction 0.00** with an ever-growing ETA. The canonical case is `-importComponent` on a relocated `.rsalign`: 6 h+, no error, no dump [VERIFIED: NA167 #11 / B1, 2026-07-23; the from-0.00 signature is NA167 #28, 2026-07-24] | Intervene |
| Legitimate heavy phase | `#timeout` at a non-zero fraction. A **successful** 94.6 % align emitted **40** `#timeout` lines and froze the fraction 20+ minutes [VERIFIED: NA167 #28, 2026-07-24] | Warn, never auto-kill |
| Near-OOM crawl | Indistinguishable in the feed. RealityScan slows to a crawl **without crashing and without spilling to NVMe** [VERIFIED: FINDINGS 2026-07-24] | Cross-check available RAM |

**The trap that made this matter:** naive stall detection compares the last progress line to
the previous one. Because `#timeout` lines differ on every tick, a 6-hour hang counted as
continuous activity and produced **zero** stall warnings. The fix is one condition:

```python
line = self._tail_line(progress_path)
if line and line != last_progress_line:
    last_progress_line = line
    self.logger.info('RealityScan [%s]: %s', self.instance_name, line)
    # '#timeout'-tagged progress is RealityScan reporting a stalled operation:
    # the elapsed counter keeps ticking, so treating those lines as activity
    # muted the stall warning for 6 h while -importComponent hung (2026-07-23).
    if not line.rstrip().endswith('#timeout'):
        last_activity = time.monotonic()
        stall_warned = False
```

### 7.3 The monitor contract

```python
PROGRESS_POLL_SECONDS   = 2.0
STALL_WARNING_SECONDS   = 2 * 60 * 60      # warn only
LOW_MEMORY_WARN_GB      = 4.0
RESOURCE_SAMPLE_SECONDS = 30.0
```

- **No overall timeout on any RealityScan operation, by design.** 10+ hour runs are normal
  (the hull model took 338.3 min; an H2023 hull attempt 384.1 min). Startup (120 s) and
  shutdown (900 s) are the only bounds [VERIFIED-as-rule: CLAUDE.md hard rule 3;
  realityscan_cli.py].
- The stall warning is **differentiated**: if the last line ends `#timeout` it names the two
  known causes (relocated-component hang, near-OOM crawl) and reports available RAM;
  otherwise it says long silences are normal for very large datasets.
- The low-memory warning fires **once** per workflow below 4.0 GB available so that a later
  stall can be *attributed* rather than guessed at.
- Errors are surfaced the moment the marker changes, even though the `.bat` aborts itself:
  `self.logger.error('RealityScan [%s] reported an error: %s', …)`.
- `_tail_line` reads the last 4 KB of the file and takes the last non-empty line — cheap at
  any file size, and tolerant of a partially written trailing line.

### 7.4 The resource trace — instrument what you do *not* suspect

Every workflow gets a CSV beside its log, sampled every 30 s and **flushed per sample**:

```
iso_time,elapsed_s,cpu_pct,ram_avail_gb,ram_total_gb,mem_load_pct,commit_used_gb,commit_total_gb,disk_free_gb,cache_free_gb,progress
```

- Flushing per sample is the point: when RealityScan dies it takes its own log with it (the
  next instance truncates `Temp\RealityScan.log`), so the trace across a crash has to be
  durable as it is written [VERIFIED-as-design: realityscan_cli.py].
- CPU comes from `GetSystemTimes` and memory from `GlobalMemoryStatusEx` — two ctypes
  syscalls, no subprocess. `wmic`/`typeperf`/`Get-Counter` would cost 50–200 ms each **and
  pop a console window** under a hidden parent.
- **Two disk columns, deliberately.** `disk_free_gb` watches the drive holding the trace
  (project + scratch); `cache_free_gb` watches `RS_CACHE_DIR`. The first read 773.9 GB free
  for a whole run while the second hit zero and killed the hull model
  [VERIFIED: FINDINGS 2026-07-26]. **Method lesson, recorded as such:** the first version of
  this trace was built around a memory hypothesis and was silent about the disk that
  actually killed the run — instrument the resource you suspect *and* the ones you do not,
  and the right *instance* of it [VERIFIED-as-fix + lesson: HANDOFF 2026-07-27].
- Sampling is deliberately tolerant — a failed sample is skipped, never raised: an
  instrument must not take down a multi-hour run.
- **Identify the instance before quoting memory.** Workflows run multiple
  `RealityScan.exe` processes (the persistent instance plus transient helpers); a
  "2.2 GB during a 4,540-image align" reading was a 30 MB transient. Identify by largest
  working set or tracked PID [VERIFIED-as-caveat: FINDINGS 2026-07-24].

Known envelope (93.6 GB box, model generation):

| component | cameras | wall clock | peak commit | min available RAM |
|---|---:|---:|---:|---:|
| `cluster_0_a2_c0` (hull) | 4,860 | 338.3 min | **148.7 GB** | **0.9 GB** |
| `zone_1_c0` | 1,634 | 249.3 min | 139.9 GB | 2.0 GB |
| `cluster_1_a1_c0` | 880 | 122.8 min | 138.6 GB | 2.8 GB |
| `zone_4_c0` | 576 | 106.1 min | 116.8 GB | 3.0 GB |
| `zone_1_c1` | 392 | 97.4 min | 107.1 GB | 3.5 GB |
| `cluster_4_a1_c0` | 133 | 40.1 min | 96.2 GB | 25.9 GB |

The apparent plateau at ~140 GB was an artifact of the 392–1,634 camera range; the hull
pushed ~9 GB past it. **Treat anything materially larger as at risk, not covered by
precedent** [VERIFIED: FINDINGS 2026-07-29].

Alignment memory, for budgeting: per-zone aligns of ~1.5k images ≤ ~60 GB; a joint
4,131-image align peaked ~165 GB on a 192 GB box. Joint alignment extrapolates to ~700 GB
for a 19k-image dive — **chunking is mandatory at production scale**
[VERIFIED: NA167 #19, 2026-07-24]. Alignment runtime varies ~3× with scene character at
equal image count, so **budget by zone, not by image count** [VERIFIED: NA167 #20].

### 7.5 What must never be used as a completion signal

| Signal | Why it lies |
|---|---|
| Process names (`tasklist` for `RealityScan.exe`) | The pre-2.x code did this with `RealityCapture.exe` and silently broke at rename [VERIFIED-as-history: CLAUDE.md hard rule 2] |
| `results_<inst>.log` growth | Internal heartbeat processes write it too [VERIFIED: HANDOFF 2026-07-21] |
| A single `-waitCompleted` | Returns prematurely before the queue is picked up [VERIFIED: FINDINGS 2026-07-21] |
| `.bat` exit code alone | Some failure paths lose it (§2.4); some operations report through the hook after the `.bat` exits (§4.3) |
| Wall-clock elapsed | Runtime varies ~3× at equal image count [VERIFIED: NA167 #20] |
| Absence of an error | Multiple silent-success channels exist (§11) |

---

## 8. Checkpoint, rollback, and verification by census

### 8.1 Checkpoint = plain file copy of the project bundle

A RealityScan save produces the `.rsproj` **plus a sibling directory named exactly after
the project stem** holding the bulky state as flat `.dat` blobs (`sfmN.dat`,
`appConfig0.dat`, `controlpoints0.dat`, …) [VERIFIED-by-inspection:
`D:/na156_h2023/aligned_components`, 2026-07-23]. Both must be copied.

```python
def scene_bundle(scene_path: str) -> list[str]:
    stem = os.path.splitext(scene_path)[0]
    candidates = [scene_path, stem, stem + '.Data', scene_path + '.data']
    return [p for p in candidates if os.path.exists(p)]
```

The extra candidates are defensive against a future build renaming the folder
[VERIFIED-as-design: module_base/scene_checkpoint.py].

`restore_scene` **removes the rejected bundle first**, so stale sidecar data can never mix
with the restored snapshot, then copies the snapshot back to the **same path**.
`prune_checkpoints` keeps only the initial and most recent snapshots — bundles are
multi-GB.

Checkpoint/rollback was validated in anger: a growth run killed mid-pass was fully
recovered by copying the "initial" bundle back over the scene
[VERIFIED: FINDINGS 2026-07-24].

### 8.2 Why component reimport is **not** a checkpoint

The officially sanctioned round trip — export the faulty part → fix it in a spare scene →
reimport → align "applies fixes" — is real [OFFICIAL: appbasics/components] and is kept as
a manual fallback. It is **not** a rollback mechanism, because:

- **Component reimport does not carry non-member images.** Orphans (never-registered
  images) are simply absent from a components-only project and carry no trajectory until a
  flight log is imported [VERIFIED: FINDINGS 2026-07-23, owner-confirmed]. Those orphans
  are exactly what a growth stage exists to register.
- **A relocated `.rsalign` import hangs the instance forever** (hard rule 7).

The bundle copy avoids both hazards [VERIFIED-as-design: scene_checkpoint.py header].

### 8.3 The oracle: census, not exit status

> **VERIFY EVERY MERGE AND EVERY GROW BY POSE-XMP CAMERA CENSUS, NEVER BY EXIT STATUS.**
> — the single most repeated operational rule in this repository
> [VERIFIED: NA167 #23; restated in CLAUDE.md, HANDOFF, MERGE_STRATEGY_REPORT]

Basis: **only registered cameras get pose entries**, so counting pose-bearing `.xmp`
sidecars is a reliable registration census [VERIFIED: NA167_SESSION_NOTES §1]. A
pose-bearing sidecar is one containing `xcr:Position` — which appears as an **element**
(`<xcr:Position>x y z</xcr:Position>`) in current exports and in **attribute** form in
older ones; both forms must be parsed [VERIFIED: FINDINGS 2026-07-28].

Why exit status cannot substitute:

- `-mergeComponents` exits **SUCCESS** and silently leaves components separate when it
  cannot fuse; the zero-overlap non-merge is universal across mechanism × flag × path form
  [VERIFIED: NA167 #23/#26].
- A real merge takes **real time** (~1 h for 1–4k-camera pairs). **Instant completion is the
  no-fuse signature** [VERIFIED: NA167 #23/#30].
- `-selectMaximalComponent`, `-renameSelectedComponent` and `-deleteSelectedComponent` all
  **silently no-op on an empty scene** with no errors marker — so loop terminals must be
  file-existence checks, not error checks [VERIFIED: FINDINGS 2026-07-23].

### 8.4 The identity harvest — the only way to get per-component membership

Component `.rsalign` files are opaque `TBSM` binary; there is no readable camera list
[VERIFIED: NA167_SESSION_NOTES §1]. Membership must be *derived*, and the derivation rests
on one naming fact:

> **The command determines the sidecar naming, not the scene.** `-exportXMP` writes
> **stem-named** `<stem>.xmp`; `-exportXMPForSelectedComponent` writes **ordinal**
> `00000.xmp`, `00001.xmp`, … in every observed context. Four consistent datapoints.
> [VERIFIED: FINDINGS 2026-07-23, NA167 B10 (ordinal XMP) final form]
> [SUPERSEDED: the earlier session-based hypothesis that stems require the live aligning
> session]

Two scope facts constrain which harvest is even possible:

- **`-exportXMP` covers "components created in the last alignment"** and the components
  must satisfy `setMinComponentSize` [OFFICIAL: appbasics/allcommands]. That is why the
  stem harvest works in an align scene (the align just ran) and is unavailable in a merge
  scene built by `-importComponent` [VERIFIED: HANDOFF verification item 2, 2026-07-21].
- **`-exportXMPForSelectedComponent` completes in a merge scene and can write NOTHING**
  while reporting success — measured: "Exporting Registration completed in 8.758 seconds"
  with **zero** `.xmp` written anywhere on the volume. Ruled out by measurement: the merge
  scene *did* contain images (`Added 1407 images`), so "an imported component carries no
  images" is not the reason. The cause was the reparse-point write path (§8.5)
  [VERIFIED: FINDINGS 2026-07-27].

Two consequences, two different harvests:

**Align scenes (stems available) — successive difference.** `AlignZone.bat` saves the
project **first**, then runs a destructive in-memory loop and quits **without saving**:

```bat
set /a comp_index=0
:identityLoop
if %comp_index% GEQ 20 goto :identityDone
if not exist "%output_dir%\identity_r%comp_index%" mkdir "%output_dir%\identity_r%comp_index%"
call :run -deselectAllImages || goto :fail
call :run -exportXMP || goto :fail
powershell -NoProfile -Command "Get-ChildItem -LiteralPath '%input_dir%' -Recurse -Filter *.xmp | Where-Object { Select-String -LiteralPath $_.FullName -Pattern 'xcr:Position' -Quiet } | Move-Item -Destination '%output_dir%\identity_r%comp_index%' -Force"
set "have_poses="
for %%F in ("%output_dir%\identity_r%comp_index%\*.xmp") do set have_poses=1
if not defined have_poses goto :identityDone
call :run -selectMaximalComponent || goto :fail
call :run -renameSelectedComponent "%scene_name%_c%comp_index%" || goto :fail
call :run -exportSelectedComponentDir "%output_dir%" || goto :fail
if not exist "%output_dir%\%scene_name%_c%comp_index%.rsalign" goto :identityDone
call :run -deleteSelectedComponent || goto :fail
set /a comp_index+=1
goto :identityLoop
:identityDone
echo Identity capture finished after %comp_index% component(s)
```

`members(c<K>) = stems(r<K>) − stems(r<K+1>)`, computed by the Python orchestrator
(`capture_component_identities`). This is exactly correct and provably so: zone_1's laps
2619/985/593/248/133/64/0 have successive differences 1634/392/345/115/69/64, reproducing
all six component sizes to the camera [VERIFIED: FINDINGS 2026-07-27].

**Merge scenes (ordinals only) — count-based peel.** Stems carry no identity, but each lap
exports the **selected** (maximal) component's sidecars, so the per-lap **file count** is
that component's exact camera count. `MergeZoneComponents.bat`'s `:harvest` block does
this; `merge_zones.peel_counts_from` reads it.

**Directory semantics differ between the two and it matters:** align-scene `identity_r<K>`
is **cumulative** (laps K..end); merge-scene `identity_r<K>` is component K **alone**
[VERIFIED: FINDINGS 2026-07-28].

Safety properties of the loop:

- The project is saved **before** the loop, and `-quit` **without saving** leaves the
  `.rsproj` bundle byte-stable across load/delete/export cycles (hash-verified twice)
  [VERIFIED: FINDINGS, cells U15/U16, 2026-07-23].
- `-deselectAllImages` precedes every export: flight-log import leaves matched images
  actively selected and selection-driven exports under `-silent` then export **nothing**
  [VERIFIED: FINDINGS 2026-07-23].
- `-setMinComponentSize 1` before exports: without it, components under the default
  threshold **5** are silently excluded from selection *and* from XMP export. The command
  is **deprecated** in 2.2 ("will be removed in the next release") and still required
  [VERIFIED: NA167 #22 / B11 (deprecation), 2026-07-24; default 5 is
  OFFICIAL: appbasics/allcommands].
- The loop is bounded (`GEQ 20` in align, `GEQ 40` in merge) against a pathological scene.
- **Sidecar hygiene afterwards is mandatory.** Exported pose sidecars are auto-imported as
  **exact-pose priors** on any later `-add` of the same images — cross-run contamination
  unless cleaned [VERIFIED: NA167 B7]. The harvest *moves* every pose-bearing `.xmp` out of
  the tree, which also strips the calibration sidecars: measured on fresh zone_1, **796 of
  4,540 images (17.5 %) had no sidecar at all** afterwards, confounding two later test
  cells. `camera_registry.ensure_calibration_sidecars()` repairs it after every harvest
  [VERIFIED-and-fixed: FINDINGS 2026-07-25].
- Ordinal sidecars (`00000.xmp`) are inert as priors (no image has an ordinal stem) and are
  deleted quietly by `camera_registry.sanitize_and_census`
  [VERIFIED: NA167 B10 (ordinal XMP), 2026-07-23].

### 8.5 Instrument invariants — an oracle that cannot see must stop the run

The most expensive failure in this repository's history was a **working pipeline with a
blind instrument**: RealityScan writes **no XMP sidecars when a scene's images resolve
through a reparse point (directory junction)** and reports success. Four baseline
components on real paths harvested `identity_r0` = 267 files (=116+94+57, exact); the same
workflow on junction-rooted components harvested **zero**, silently, across 18 attempts and
**5 h 12 m** of correct GPU work, every attempt scoring as a clean "nothing fused"
[VERIFIED: FINDINGS 2026-07-27] [UNDOCUMENTED: no Epic coverage of reparse-point behaviour].

Two mechanical guards were added, and both belong in any harness of this shape:

```python
# 1. An empty peel next to a non-empty export is a BROKEN INSTRUMENT, not a result.
first_export = os.path.join(adir, f'{export_name}_c0.rsalign')
if result.success and not sizes and os.path.isfile(first_export):
    raise RuntimeError(
        f'{tag} attempt {attempt_no}: peel harvest returned EMPTY but {first_export} '
        'exists - the measurement channel is broken (pose sidecars were never written '
        'or never moved). Aborting the run instead of mis-scoring it.')
```

```python
# 2. Refuse to start on an image tree the harvest cannot cross.
for dirpath, dirnames, _files in os.walk(images_root):
    for name in list(dirnames):
        full = os.path.join(dirpath, name)
        if is_reparse(full):
            reparse.append(os.path.relpath(full, images_root))
            dirnames.remove(name)
if reparse:
    raise RuntimeError(
        f"images_root {images_root} has reparse-point children {reparse}; "
        "the peel harvest cannot cross them. Pass the real image tree.")
```

Related Windows fact worth knowing: **PowerShell 5.1 `Get-ChildItem -Recurse` does not
descend into junction children** (0 vs 9,835 `.xmp` on the same tree by its real path),
while Python's `os.walk` crosses junctions in both directions. The align harvest survived
because it is handed the zone folder itself (the junction *is* the enumeration root); the
merge harvest died because it is handed the parent [VERIFIED: FINDINGS 2026-07-27].

[SUPERSEDED, retained: "the empty peel was caused by junction *enumeration* (the read
side)". A re-run with the real image tree produced the identical `peel=[]` on all 18
attempts. The junction enumeration fact is true and reproducible; it was not the
explanation. The real cause was the **write** side. 157 further minutes were spent on a
confirmed mechanism that was never linked to the symptom.]

### 8.6 Acceptance arithmetic: never-shrink, and its bounded-loss successor

The growth loop's invariant is textbook:

```python
def evaluate(tag, before, after, workflow_ok):
    """Never-shrink invariant: no previously registered image lost AND camera count >= before."""
    lost = sorted(before - after)
    ok = workflow_ok and not lost and len(after) >= len(before)
    return ok, lost
```

Accept → new baseline + new checkpoint. Reject → `restore_scene(...)`. Three exits:
converged (no real gain), budget cap (`--max_passes`), invariant violation (stop and
report).

Three hard-won accounting rules:

1. **Growth passes are align-UPDATES that refresh every component.** A census after an
   "isolated" component pass covers the whole zone; per-component before/after accounting
   produced *phantom gains*. Judge gains against the **zone-level baseline census**
   [VERIFIED: FINDINGS 2026-07-24].
2. **A free re-align is never pose-stable** and can shrink: it moved all 118 cameras of a
   solved smoke scene and routinely drops 1–2 marginal cameras (H2023 3,860 → 3,855;
   zone_1 c7's pass lost 51 previously-registered images) [VERIFIED: FINDINGS 2026-07-23/24].
3. **Pose-locking is unusable as a growth anchor.** `-editInputSelection inpPose=3`
   (Exact/Locked) takes effect, but `-align` then refuses: *"prior set to 'Exact' mode must
   be all aligned in a single run. Incremental adding is not supported."*
   Checkpoint/rollback stays the primary never-shrink mechanism
   [VERIFIED: cell U18 FAIL, FINDINGS 2026-07-23].

On the merge side the same idea failed in an instructive way. `merge_zones.py`'s
never-shrink clause was **dead code that never fired**: every adopted entry's
`camera_count` equalled its matched subset's sum by construction, each input popped exactly
once, and `confidence == "exact"` required the remaining set to be empty — so
`adopted_cams == input_cams` identically and `lost == 0` always. The clause could neither
reject nor see a camera *gain*, which is exactly what `sfmForceComponentRematch` and
`sfmImagesOverlap:High` exist to produce.

The real gate was **exact subset-sum attribution**, and it rejected a genuine three-way
fusion on every rung of cluster_0 (`zone_2_c0` 1,407 + `zone_3_c0` 1,217 + `zone_5_c0`
2,241 = 4,865):

| rung | peel | why it was rejected |
|---|---|---|
| 1 (`merge_georef`) | `[4860, 2241, 1407, 1217]` | 4,860 is not a subset sum of {2241, 1407, 1217} → `ambiguous`, `fused` False |
| 2–3 (`align_rematch`, `…_high_overlap`) | `[4851, 2241, 1407, 1217, 5]` | same, plus a stray 5-camera fragment |

The three parents each attributed to themselves exactly, so the attempt still recorded
`adopted=3, delta=0` — **a rejection that reads as a clean no-op in the report**.
**A 5-camera loss out of 4,865 (0.10 %) is enough to hide a fusion entirely**
[VERIFIED: FINDINGS 2026-07-27/28] [SUPERSEDED: all prior "never-shrink rejected the hull"
attributions]. Note the findings log's own summary of this run says "4,860 … every time",
which the peel arrays it quotes do not support — read the arrays, not the summary.

Contrast the attempts that *were* accepted, all exact: `[1767, 1634, 69, 64]`
(1634+69+64 = 1767) and `[1456, 576, 358, 345, 177]` (576+358+345+177 = 1456)
[VERIFIED: FINDINGS 2026-07-28]. **Exact fuses are visible; lossy ones are not** — which is
the whole reason the bounded-loss successor exists.

The successor is explicit, bounded, operator-supplied, and recorded:

```python
def loss_budget(input_cams: int, loss_tolerance_frac: float) -> int:
    return int(input_cams * loss_tolerance_frac)

def acceptance_verdict(workflow_success, adopted_count, fused, confidence, lost, tol):
    accept = bool(workflow_success and adopted_count and fused
                  and confidence == 'exact'
                  and lost is not None and lost <= tol)
    rejection = None
    if workflow_success and adopted_count and lost and lost > tol:
        rejection = 'shrink'
    if workflow_success and fused and confidence != 'exact':
        rejection = 'ambiguous_attribution'
    return accept, rejection
```

Default remains `0` (exact only); `--loss_tolerance 0.0025` (0.25 %) is passed explicitly,
warned at startup, and recorded per attempt and in `EVALUATION_READY`
[VERIFIED-as-decision: HANDOFF 2026-07-29].

**Make the decision a pure function and have the tests drive it.** Two of one session's own
regression tests re-implemented the accept arithmetic and would have kept passing had the
driver regressed; the fix was extracting `acceptance_verdict`, `loss_budget`,
`fused_export_name` and `effective_ladder_for` and calling them from both the driver and
the suite [VERIFIED-as-fix: FINDINGS 2026-07-29].

---

## 9. Log snapshotting

### 9.1 The fact that forces it

`RealityScan.log` lives at `%LOCALAPPDATA%\Temp\RealityScan.log` and is **truncated on
every instance boot**. A post-failure snapshot taken by a later step loses the race to the
next boot — a 91-byte capture was recorded once. **The copy must happen inside the driver,
immediately after the failing call returns** [VERIFIED: NA167 #16 / B6, 2026-07-23].

This matters because the errors marker carries **only the numeric result code**. The
`err:NNNN` text, the deprecation warnings, the `Finalizing N component` lines, the
`Processing failed: Out of disk space..` line — all of that exists **only** in
`RealityScan.log` [VERIFIED: FINDINGS 2026-07-23].

### 9.2 The snapshot

```python
def snapshot_rs_log(dest: str, logger) -> None:
    src = os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Temp', 'RealityScan.log')
    try:
        shutil.copyfile(src, dest)
    except (OSError, shutil.Error) as exc:
        logger.warning('Could not snapshot RealityScan.log: %s', exc)
```

Called unconditionally after **every** merge attempt (not only failures), writing
`<attempt_dir>/rslog.txt`. A crash is never predictable in advance.

### 9.3 Validate a snapshot before reading numbers out of it

A saved `rslog.txt` can be a **different run's log, spliced mid-file**. Two merge drivers
overlapped; RealityScan truncated the shared global log at the second instance's launch, so
one snapshot's head and tail belonged to different runs — an H2023 attempt's snapshot
recorded `importComponent` of eleven H2024 components [VERIFIED: FINDINGS 2026-07-27].

**A snapshot must be validated against a run-unique token before any number is read out of
it.** Here the token is the attempt's own complist paths:

```python
def rs_finalizing_counts(rslog_path: str, expected_rsaligns: list[str]) -> dict:
    out = {'valid': False, 'counts': []}
    ...
    imported = set(re.findall(r"importComponent' with parameter '([^']+)'", text))
    expected = {os.path.normcase(p) for p in expected_rsaligns}
    seen     = {os.path.normcase(p) for p in imported}
    out['valid']  = expected <= seen
    out['counts'] = [int(n) for n in re.findall(r'Finalizing (\d+) component', text)]
    if not out['valid']:
        out['missing'] = sorted(expected - seen)
    return out
```

Even when valid, `Finalizing N component(s)` is **recorded as a cross-check and never gated
on** — its exact semantics are not established [OPEN, §Open questions].

### 9.4 Minidumps

A crash writes `RealityScanCrash-YYYYMMDD-HHMMSS.dmp` (plus a `.dmp.metadata`) into the
`-silent` directory, and the **next delegated command fails with "Failed to delegate
command"** — the signature of a dead instance rather than a rejected operation
[VERIFIED: FINDINGS 2026-07-26]. Both the dump and the snapshot must be collected before
the next boot.

---

## 10. End-to-end recipes

All four are the production paths, with real path *shapes*. `%RS%` stands for
`"C:\Program Files\Epic Games\RealityScan_2.2\RealityScan.exe"`.

### 10.1 Single zone: new scene → add images → import flight log → align → export components + XMP census

Driven by `AlignZone.bat`; the whole flow in one place:

```bat
:: === boot ===
call "%~dp0startRealityScan.bat"          :: -headless -silent -setInstanceName RS1 -writeProgress + hook
if errorlevel 1 exit /b 1

:: === scene ===
call :run -newScene || goto :fail

:: === images (appIncSubdirs default is FALSE - set it before EVERY addFolder) ===
%RS% -delegateTo RS1 -set "appIncSubdirs=true"
call :run -addFolder "F:\na156_h2024_v2\batched_images_by_zone\zone_1" || goto :fail

:: === alignment settings FIRST: -align takes NO params, so push every key the XML names ===
:: (settings before the trajectory - the sfmCameraPrior* keys govern how the incoming
::  priors are weighted; order fixed 2026-08-14. Gate on the KEY token, never token 1:
::  cmd reads the leading "<" of an entry line as a redirection - FINDINGS 2026-08-15.)
for /f usebackq^ tokens^=2^,4^ delims^=^" %%A in ("%Metadata%\AlignmentParams.xml") do (
    echo %%A| %SystemRoot%\System32\findstr.exe /r /b /c:"[a-zA-Z]" >nul
    if not errorlevel 1 %RS% -delegateTo RS1 -set "%%A=%%B"
)

:: === trajectory + CRS (project + output scope pinned BEFORE the import, 2026-09-02) ===
call :run -setProjectCoordinateSystem epsg:32604 || goto :fail
call :run -setOutputCoordinateSystem epsg:32604 || goto :fail
call :run -importFlightLog ^
    "F:\na156_h2024_v2\batched_images_by_zone\zone_1\flight_log_4Q_UTM.txt" ^
    "F:\na156_h2024_v2\logs\FlightLogParams_4Q.xml" || goto :fail
call :run -align || goto :fail

:: === export gates ===
call :run -deselectAllImages   || goto :fail      :: flight-log import left a selection
call :run -setMinComponentSize 50 || goto :fail   :: default 5 silently drops the rest

:: === save BEFORE the destructive harvest ===
call :run -save "F:\na156_h2024_v2\aligned_components\zone_1\zone_1.rsproj" || goto :fail

:: === identity harvest (see §8.4), then: ===
%RS% -delegateTo RS1 -quit     :: NO save after the loop
```

**[CONTRADICTED — internal, RESOLVED] on `appIncSubdirs`.** The NA167 revised-docs entry
for `-addFolder` reads "in our 2.2 build subfolders were included **without** setting the
key (zone_13: `wca/` + `zeuss/` both imported)" [testing/NA167_SESSION_NOTES §1] and is
still on file that way; the H2023 line observed the opposite on the same product version —
`Added 0 layer images` in the log snapshot, every flight-log row failing `err:18002`, the
run finishing "successfully" in 25 s. **The reconciliation is recorded and settles it:**
the NA167 zone_13 run had `appIncSubdirs` set by the already-fixed workflow, "the flag, not
the build, is the variable" [VERIFIED: FINDINGS 2026-07-23, nuance clause]. The official
default is `false` [OFFICIAL: tutorials/setkeyvaluetable], so set it explicitly, always,
and read `Added N layer images` out of `RealityScan.log` when a zone aligns suspiciously
fast — that line is the only place the failure is visible.

Preconditions the driver enforces around the `.bat`:

| Step | Why |
|---|---|
| Clear the output folder before a re-run | `-exportLatestComponents` reuses names like `Component 0.rsalign`; stale exports would poison the before/after file diff [VERIFIED-as-design: realityscan_interface.py] |
| Regenerate `FlightLogParams.xml` from the **zone tag in the flight log's filename** (`flight_log_53N_UTM.txt` → EPSG:32653) | The template's zone belongs to whatever cruise last edited it; a wrong UTM zone imports **silently** and misplaces everything [VERIFIED: NA167 #6 + FINDINGS 2026-07-21/22] |
| Write one calibration `.xmp` per image beforehand | EXIF-identical cameras cannot be separated any other way; sidecars cut zone_1 fragmentation from 9 components to 3 at equal-or-better registration [VERIFIED: FINDINGS 2026-07-24] |
| `sanitize_and_census(input_folder)` **even on failure** | A partial harvest leaves pose sidecars beside the images, which the next run auto-imports as exact-pose priors (B7) |
| `ensure_calibration_sidecars(input_folder)` after the harvest | The harvest moved them out; 17.5 % of zone_1 was left ungrouped once [VERIFIED: FINDINGS 2026-07-25] |
| Verify the `.rsproj` exists and is non-empty | Do not trust exit status alone |
| Build manifests from `identity_r<K>` | `AlignZone.bat` writes the harvest but **not** the manifests — only the alignment *module* does, and the feature-aware merge refuses unmanifested components. "Success" from a direct `.bat` driver is a weaker claim than success from the module [VERIFIED-as-lesson: FINDINGS 2026-07-25] |

Expected outcome shape: **several components per zone**, with an **unstable count across
identical runs** (2 vs 9 observed on identical inputs). *Which* images register is stable;
*how they clump* is not — so everything downstream tracks image sets, never component
names or counts [VERIFIED: FINDINGS 2026-07-24].

### 10.2 Batched large survey: N zones aligned independently, then merged

**Why per-zone copies break the merge STAGE — and why the fix is a canonical image pool.**
(Not "why copies make fusion impossible" — that stronger claim is refuted; see item 1.)

The batcher cuts spatial zones with an overlap band shared by neighbours. If it *copies*
the band images into both zone folders, the same photograph exists as two files at two
paths. Consequences, in order of severity:

1. **Copies remove the deterministic merge mechanism, but they do NOT make fusion
   impossible — and getting this backwards has cost real time in this repo.** The
   established picture is three facts, not one:
   - **Zero *content* overlap never fuses**, under any mechanism × flag × path form:
     `-mergeComponents` flags-off, `-mergeComponents` + `sfmMergeGeoreferencedComponents`,
     `-align` + georef + rematch, duplicate-path and shared-path — every cell exits
     SUCCESS with the "merged" component being exactly the biggest input
     [VERIFIED: NA167 #23–#26, 2026-07-24].
   - **Content overlap fuses under BOTH mechanisms, with or without shared paths.** Probe
     D7 (`testing/probe_d7.py`, smoke fixture): `zone_c` (78 cams) + `zone_d_c0` (42 cams),
     **zero shared basenames and zero shared paths**, same seafloor strip → one
     120-camera component ("Finalizing 1") both *without* any flight log in the merge
     scene and *with* union log + `-update`; `-align` + rematch fused the 118+62 pair to
     180 with no log [VERIFIED: FINDINGS 2026-07-24, "D7 RESOLVED"].
   - **[CONTRADICTED — internal, SUPERSEDED]** The earlier reconciliation entry
     "camera identity is (at minimum) path identity — zones built as per-zone COPIES
     provide no shared-camera identity for merging" [FINDINGS 2026-07-24, RECON] was
     **refuted the same day** by D7. Any harness built on "copies cannot merge" is built
     on a retracted fact. What survives is the *engineering* case against copies —
     items 2–4 below, plus the fact that shared-path identity is the only merge glue that
     is deterministic and inspectable ahead of the run.
2. **Flight-log arithmetic goes wrong.** A copied image is two physical files with one
   trajectory row: cluster_0's scene had 4,865 cameras but its union flight log only 4,227
   rows — a 638-row gap that looks like missing nav [VERIFIED-as-symptom: HANDOFF loose
   end #6].
3. **A fused manifest's `images` is the unique-basename union while the scene holds one
   camera per input *occurrence*** (880 cameras over 537 unique basenames), so any
   nav-vs-solved comparison must use the **concatenation** of the attributed input
   manifests' members [VERIFIED: FINDINGS 2026-07-28].
4. **Duplicate copies inflate storage** — 918 duplicate copies (20.0 %) across one H2023
   tree [VERIFIED: FINDINGS 2026-07-28].

**The fix, verified end to end:** replace per-zone copies with per-zone **real directories
of hardlinked `.jpg`** back to one canonical image tree. Measured on H2024: 9,835 files,
**35.8 GB logical, 0.05 GB actual**. Sidecars (`.xmp`) and flight logs are **copied, not
hardlinked**, so a v2 write cannot corrupt the baseline's. This restored the whole
export → harvest → attribute → accept chain; **no re-align was needed — the components were
never the problem, only the paths baked into them** [VERIFIED: FINDINGS 2026-07-28].

**Do not use junctions.** Per-zone directory junctions were tried and silently broke the
merge in both directions (RealityScan writes no XMP behind a reparse point; PowerShell
does not enumerate through one), costing two full merge runs [VERIFIED: FINDINGS
2026-07-27/28]. `assert_harvestable()` (§8.5) refuses to start on a tree with reparse-point
children.

The equivalent alternative is `.imagelist` input: `AlignImageList.bat` references images at
their **original paths**, so components produced from overlapping imagelists share cameras
by identity. Registration is **independent of how images were added** — folder vs imagelist
on identical zones: **zone_6** 95.2 % (1,533/1,610, A1 folder) vs 95.3 % (1,534, A2
imagelist); **zone_4** 90.1 % (1,438/1,596) vs 91.0 % (1,453)
[VERIFIED: MERGE_TEST_PLAN cells A1/A2, 2026-07-23]. So the choice of pooling mechanism is
free at the registration level and is decided entirely by the merge and accounting
consequences above.

Driver skeleton (the shape of `testing/run_h2024_v2.py`):

```python
V2_ROOT         = r"F:\na156_h2024_v2"
IMAGES_ROOT     = os.path.join(V2_ROOT, "batched_images_by_zone")   # hardlinks, never junctions
COMPONENTS_ROOT = os.path.join(V2_ROOT, "aligned_components")
ZONES           = ["zone_1", "zone_2", "zone_3", "zone_4", "zone_5"]
MIN_FREE_GB_CACHE, MIN_FREE_GB_PROJECT = 50.0, 50.0

for zone in ZONES:
    if not check_space(logger):            # abort BEFORE a zone, not during
        report["aborted"] = f"insufficient disk before {zone}"; flush(); return 1
    if zone_already_done(zone) and not args.force:   # resumable
        continue
    camera_registry.ensure_calibration_sidecars(os.path.join(IMAGES_ROOT, zone))
    env = dict(os.environ)
    env.update(RS_MODULES="RealityScan Alignment", RS_NO_INTERACTIVE="1",
               RS_HEADLESS="0", RS_INSTANCE="RS1",
               RS_CACHE_DIR=r"E:\rscache", PYTHONIOENCODING="utf-8")
    proc = subprocess.run([sys.executable, os.path.join(REPO, "main.py"),
                           "--output_dir", V2_ROOT,
                           "--r_input", os.path.join(IMAGES_ROOT, zone),
                           "--r_flight_log", os.path.join(IMAGES_ROOT, zone, "flight_log_4Q_UTM.txt"),
                           "--r_project_label", "NA156_H2024_V2",
                           "--r_model_generate", "false"],
                          cwd=REPO, env=env, capture_output=True, text=True,
                          stdin=subprocess.DEVNULL)      # never inherit a console's stdin
    report["zones"][zone] = {...}; flush()               # flush after EVERY zone
```

Non-negotiable driver properties, each traceable to an incident:

| Property | Incident it prevents |
|---|---|
| `stdin=subprocess.DEVNULL` on every child | On a console, a child's `input()` blocked forever on an invisible prompt; detached, it silently inherited another session's `rs_settings.json` values [VERIFIED: FINDINGS 2026-07-29] |
| **Every** `ask()`-backed option passed explicitly | Same — an unpinned option makes the child prompt |
| `PYTHONIOENCODING=utf-8`, ASCII-only console output | cp1252 console crashes on non-ASCII, hit twice |
| `input()` wrapped in `try/except EOFError` with a stored default | `isatty()` **lies** under hidden consoles — it reports True with an EOF stdin [VERIFIED: FINDINGS 2026-07-24/28] |
| Report flushed after every zone | A crash mid-run must not lose the completed zones' record |
| Free-space check before each zone, hard abort below the floor | `ERROR_DISK_FULL` on the **cache** drive killed the hull model twice |
| A zone that **raises** must be counted | Nine raising zones out of ten still reported exit 0 because a raise landed in neither the Succeeded nor Failed tally [VERIFIED-and-fixed: audit #7, FINDINGS 2026-07-28] |
| An input **fingerprint**, not a comment, gates reuse | `batch_inputs.json` records the flight log's sha256 plus the zoning parameters; reuse is refused with the remedy named when they differ. Before it, five zones were silently a **blend of two zonings** — 12,679 jpgs on disk against 9,834 reported — while the module said `Success: True` [VERIFIED-and-fixed: FINDINGS 2026-07-26] |

### 10.3 Merge escalation loop

The loop's shape, from `merge_zones.merge_cluster`:

```
for each spatial cluster (twin-drop → relatedness graph → connected components):
    if 1 component: converged, zero attempts          ← a saturated feature is SUCCESS
    while a target remains:
        subset = target + everything related to it
        ladder = effective_ladder_for(subset)          ← merge rungs only if shared-image graph SPANS
        for rung in ladder:
            write attempt_<n>_<label>/cluster.complist  (CRLF, no BOM, ORIGINAL paths)
            run MergeZoneComponents.bat  (mode, key:value settings, union log + params via env)
            snapshot RealityScan.log  →  attempt dir            ← immediately
            sanitize_and_census(images_root)                    ← sidecar hygiene
            sizes = peel_counts_from(attempt dir)
            INSTRUMENT INVARIANT: empty peel + non-empty export → RAISE, do not score
            rs_finalizing_counts(rslog, complist paths)         ← cross-check only, validated
            attributed, confidence = attribute_result(subset, sizes, tol)
            accept, rejection      = acceptance_verdict(...)
            if accept: splice results in place of subset, RESTART the ladder on the new state
        else: mark target exhausted
converged = a full ladder cycle with no fusion
```

The ladder (`merge_zones.LADDERS`), one variable per rung:

| ladder | rung 1 | rung 2 | rung 3 |
|---|---|---|---|
| `merge_first` (default) | `merge_georef` — mode `merge`, `sfmMergeGeoreferencedComponents:true`, `sfmEnableCameraPrior:true` | `align_rematch` — mode `align`, + `sfmForceComponentRematch:true` | `align_rematch_high_overlap` — + `sfmImagesOverlap:High` |
| `content_first` | `align_rematch` | `align_rematch_high_overlap` | `merge_georef` |

[VERIFIED-by-inspection: merge_zones.py]

Evidence written **per attempt**, all of it: `cluster.complist`, the workflow log, the
resource CSV, `rslog.txt`, `identity_r<K>/` harvest directories, the exported
`<tag>_a<N>_c<K>.rsalign`, and a `merge_report.json` entry carrying `peel_sizes`,
`attribution`, `adopted_count`, `residual_count`, `camera_delta`, `cameras_lost`,
`loss_tolerance`, `rs_finalizing`, `duration_s`, and `rejected` when applicable.

Loop-design facts that cost real time to learn:

- **`-mergeComponents` retains its input components alongside the fused one.** A peel of a
  fused 78+42 pair reads `[120, 78, 42]`; H2023's hull peel read `[3737, 3026, 714]`. Any
  all-components export of a merge scene contains residual source copies — consumers must
  **attribute**, not enumerate [VERIFIED: FINDINGS 2026-07-24 and 2026-07-27].
  `attribute_result` therefore matches largest-first and marks unmatched entries equal to an
  already-consumed input's count as **residuals**.
- **An accepted rung short-circuits the rest of the ladder — worth half the wall clock**
  (merged5 68 min vs merged4 122 min) [VERIFIED: FINDINGS 2026-07-28].
- **Memoise attempted subsets.** Without it a symmetric pair costs six attempts instead of
  three (target A yields {A,B}; target B yields the identical set)
  [VERIFIED-and-fixed: FINDINGS 2026-07-27].
- **Export names must be unique per attempt.** `peel_index` restarts at 0 every attempt, so
  two accepted fusions in one cluster both claimed `<tag>_m_c0`: one run died on a
  duplicate-identity check after two good fusions, and the second silently clobbered the
  first's lineage. Fixed by `fused_export_name(tag, attempt_no)` → `<tag>_a<N>_c<K>`
  [VERIFIED-and-fixed: FINDINGS 2026-07-28; HANDOFF 2026-07-29].
- **Admit `-mergeComponents` rungs only when the shared-image graph SPANS the subset**
  (`effective_ladder_for` → `shared_graph_spans`; align rungs are always admitted).
  The failure this closes: merged5's `cluster_1_a3_c0` (3,615 cams) packed **eight
  disjoint objects** into one container — of its 28 component pairs exactly **one**
  (`zone_1_c2` ↔ `zone_4_c1`, 343 shared basenames) shared any imagery, the rest related
  only by transitive bbox adjacency — while the arithmetic scored each of the three
  accepted `merge_georef` attempts as an exact-sum fusion with **zero loss**, and
  RealityScan's own log reported "Finalizing 3", then "7", then "8" components.
  **Zero camera loss on a "fusion" between components with zero shared imagery is the
  rigid-glue signature.** Contrast the hull: an `align` fusion, "Finalizing 1", and it
  **lost 5 cameras** — real joint solving. `GenerateModel`'s keep-largest-connected-
  component step would have deleted every smaller object out of a model of that container
  [VERIFIED: FINDINGS 2026-07-28].
  **Scope this rule honestly:** it is a *conservative admission policy*, not a statement
  that `-mergeComponents` requires shared paths — D7 showed it fusing zero-shared-path
  components that share content (§10.2). The policy exists because a merge rung acts on
  **every component in the scene indiscriminately**, so the cheapest way to keep a merge
  rung from gluing unrelated objects is to only run it on identity-connected subsets
  [VERIFIED-as-design: merge_zones.shared_graph_spans docstring; FINDINGS 2026-07-28].
- **The companion gate is `pair_gate`.** `overlap` (default) admits a pair into one merge
  scene only when they share imagery or their bboxes **truly overlap**; `border` retains
  the older 10 m-margin adjacency for comparison. The margin is applied to **both**
  bboxes, so `DEFAULT_BORDER_MARGIN_M = 10.0` treats components up to **20 m** apart as
  bordering — every description of it as a "10 m-expanded bbox" understates the reach by
  2× [VERIFIED: FINDINGS 2026-07-27, pinned by testing/test_merge_scope.py].
- **`-mergeComponents` never adds images, and `MergeZoneComponents.bat` has no
  `-addFolder` at all** — so a merge scene structurally cannot contain an orphan
  (never-registered) image, and no merge rung can ever register one. Orphan inclusion
  requires an `-align` rung *and* a workflow change [VERIFIED: FINDINGS 2026-07-27].
- **`-mergeComponents` is a no-op with a single component, and its asynchronous
  re-reconstruction can clear the selection** — which is why every export path selects
  with `-selectMaximalComponent` *after* the merge rather than relying on a selection
  that predates it [VERIFIED: HANDOFF verification item 2, 2026-07-21].
- **`assemble` mode is exempt from the ≥ 2 component guard.** Every other mode requires
  ≥ 2; assemble requires ≥ 1, because a fully-converged single-feature dive still has to
  produce its assembly project. Before the exemption a completely successful ladder that
  fused 3 → 1 aborted with `ERROR: need at least 2 components` and the driver exited 1
  [VERIFIED-and-fixed: FINDINGS 2026-07-28, re-verified three ways via `cmd /c`].
- **A multi-component terminal state is a correct outcome.** Zones are cut on image
  **density** and are blind to feature boundaries; H2023 contains two discrete physical
  features. No deletion/export/success logic may be size-based — only containment-based
  (no unique images) deletion is legal, and a maximal-fraction success target misreads
  disjoint features as merge failure [VERIFIED-as-owner-intent: FINDINGS 2026-07-24].
- **Georeference the merge scene explicitly.** A merged component is a **new** component and
  is **not** georeferenced unless the merge scene itself holds constraints: import the
  union flight log **before** the merge, then `-update` after it
  [VERIFIED: FINDINGS 2026-07-23]. Importing a union log that covers unregistered images
  always raises `0x820000FF` and it is benign — verified by matching all 102 "not found"
  images against every component manifest: **zero overlap**
  [VERIFIED: FINDINGS 2026-07-25]. That is what `:run_geoimport` tolerates.

### 10.4 Model + texture + export for a chosen component

`GenerateModel.bat`, run **once per component against the same saved project**. The
owner-specified eight-step recipe, with the literal model names:

| step | commands | resulting model name |
|---|---|---|
| [1/8] | `-calculateHighModel` → `-renameSelectedModel` | `<tag>_HighPoly_Raw` |
| [2/8] | `-selectMarginalTriangles` + `-removeSelectedTriangles` | `<tag>_Cleanup1` |
| [3/8] | `-selectLargeTrianglesRel 30` + `-removeSelectedTriangles` | `<tag>_Cleanup2` |
| [4/8] | `-selectLargestModelComponent` + `-invertTrianglesSelection` + `-removeSelectedTriangles` | `<tag>_Cleanup3` |
| [5/8] | `-closeHoles` → `-cleanModel` | `<tag>_Manifold` |
| [6/8] | `-simplify SimplifyNoise_Params.xml` → `<tag>_HighPoly` → `-calculateTexture Texturing_MaxTextureCount4_16k.xml` | `<tag>_HighPoly_Textured` |
| [7/8] | 4 × (`-simplify SimplifySmooth_80per_Params.xml` + `-cleanModel`) | `<tag>_Simplified` |
| [8/8] | `-unwrap Unwrapping_Simplified_4x16k.xml` → `-reprojectTexture <tag>_HighPoly_Textured <tag>_Simplified ReprojectionParams.xml` → rename | `<tag>_Simplified_Textured` |

`%model_tag%` = the component name (or `maximal`). **Every model name is namespaced by the
component being modelled**, and this is the single most important line in the workflow: it
is run once per component against **one shared project**, so fixed names collide across
runs. Step [8/8] resolves its operands **by name** — with a second component's
`HighPoly_Textured` in the scene, `-reprojectTexture` can map one component's texture onto
another's mesh **with a clean exit status**. The cleanup loop could also delete another
component's models. All 19 references were namespaced. **Discovered by reading the workflow
before the second component started, not by a failure**
[VERIFIED-and-fixed: FINDINGS 2026-07-25].

Selection semantics that shape the chain: `-removeSelectedTriangles` removes the
**selected** set (it is the Filter Selection tool), so the edge and large-triangle steps
filter directly and only the largest-component step needs `-invertTrianglesSelection`
first [VERIFIED: FINDINGS 2026-07-23]. `-selectLargeTrianglesRel`'s threshold is in
**multiples of average edge length**, not pixels — the GUI's "30 px" intuition does not
transfer [VERIFIED: FINDINGS 2026-07-23].

Texture ordering, with the mechanism: `-calculateTexture` projects from the **source
images** with multi-band blending, so hole-fill triangles that any camera saw get real
blended colour — hence texture **after** `-closeHoles`/`-cleanModel`, and the final
`-reprojectTexture` maps manifold → manifold and introduces no nodata. Texturing the holey
model, then closing holes and reprojecting, produces nodata patches because reprojection
samples the source **surface** [VERIFIED-as-design-decision with mechanism:
settings-evaluation §7].

Save discipline, measured:

- **No save before the cleanup loop.** Saving with ~15 models live is inordinate:
  `zone_1_c0`'s saves consumed ~81 GB with the extra write in place; with `RS_PROJECTS_DIR`
  unset (which skips both dated copies) `cluster_4_a1_c0` cost 6.8 GB end to end
  [VERIFIED: FINDINGS 2026-07-29].
- The deliverable is protected instead by the **double-wait in `:try_delete_model`**.
- **Defer the dated copy.** Drivers run the model workflow with `RS_PROJECTS_DIR` **unset**
  and call `SaveProjectCopy.bat` once at the end: one dated copy of the finished
  six-component project took **13.1 min / 95.2 GB** [VERIFIED: FINDINGS 2026-07-29].
- `:fail` quits **without saving**, so a failed model run leaves the assembly intact
  [VERIFIED: FINDINGS 2026-07-26].

Two naming facts that make the loop safe, and one that does not:

- **`-selectModel` matches on EXACT name — the prefix hazard is not real.** Deleting
  `<tag>_HighPoly` in the cleanup loop cannot take `<tag>_HighPoly_Textured` with it:
  "selectModel modelName — Select a model with the specified name"
  [OFFICIAL: appbasics/allcommands], confirmed empirically because the H2023 deliverable's
  cleanup ran and all its kept models survived [VERIFIED: FINDINGS 2026-07-28].
- **[CONTRADICTED — internal] `<comp>_HighPoly_Raw` does NOT survive the recipe.**
  `GenerateModel.bat`'s own docstring and the "H2024 MODELS COMPLETE" entry both list
  three kept models per component including `_HighPoly_Raw`
  [FINDINGS 2026-07-29, models table]. The export probe of the same day proved otherwise:
  `-selectModel cluster_4_a1_c0_HighPoly_Raw` → `err:5601 'not found'`. Mechanism: step
  [2/8] **renames** the selected model to `_Cleanup1` when the marginal filter fires, so
  the raw name leaves the project; the same rename chain is why
  `-selectModel <tag>_HighPoly` misses in every component's cleanup loop (it became
  `_HighPoly_Textured` at [6/8]). **The models that actually persist per component are
  `_HighPoly_Textured`, `_Simplified_Textured`, plus one default-named residual.** The
  docstring was wrong from 2026-07-23 to 2026-07-29
  [VERIFIED-and-corrected: FINDINGS 2026-07-29 export probe].
  *Queued recipe fix if raw retention is wanted:* `-duplicateSelectedModel` after [1/8],
  before the filter chain touches it [OPEN — not run].

Export (`ExportDeliverables.bat`) — one session for everything, because the project load is
the expensive part:

```bat
call :run -load "%scene_path%" || goto :fail
:: sweep default-named residuals first, then save ONCE
for %%M in ("Model 1" "Model 2" ... "Model 9") do call :try_delete_model %%M
call :run -save "%scene_path%" || goto :fail

:: per component, from a name list file (one per line)
call :run -exportModel "%comp%_Simplified_Textured" "%out_dir%\%comp%\obj\%comp%.obj" "%ObjParams%" || exit /b 1
call :run -exportModel "%comp%_Simplified_Textured" "%out_dir%\%comp%\fbx\%comp%.fbx" "%FbxParams%" || exit /b 1
call :run -selectModel "%comp%_HighPoly_Raw"        || exit /b 1
call :run -calculateVertexColors                    || exit /b 1
call :run -exportModel "%comp%_HighPoly_Raw" "%out_dir%\%comp%\ply\%comp%_dense.ply" "%PlyParams%" || exit /b 1

%RealityScan% -delegateTo %RS_INSTANCE% -quit    :: NOT saving - the vertex colors stay in memory
```

Verified output shape on the real assembly: OBJ **4 parts + per-part MTL + `u1_v1`
textures + `.rsInfo`** (exactly Nira's expected layout), FBX **4 parts + textures**,
~35–38 s each on a 133-camera component. Exactly **one** default-named residual existed in
the whole six-component project ("Model 1"), not one per component as hypothesised
[VERIFIED: FINDINGS 2026-07-29].

> **LIVE DEFECT — read before copying that snippet.** The PLY block above is
> `ExportDeliverables.bat` **as shipped**, and it selects `<comp>_HighPoly_Raw`, a model
> the export probe proved does not exist after the recipe (above). Under `:run` a missing
> model writes the errors marker, `:run` returns 1, and `call :export_component "%%N" ||
> goto :fail` aborts the whole export session — so the OBJ and FBX of every *later*
> component are lost too. Only the OBJ and FBX steps are on the verified-output record;
> the dense-PLY step is not. The fix recorded in the findings is to fall back to
> `<comp>_HighPoly_Textured`, "the densest model guaranteed to exist"
> [VERIFIED-as-defect: FINDINGS 2026-07-29 export probe; the `.bat` at
> `RS_CLI/Scripts/ExportDeliverables.bat` still carries `_HighPoly_Raw` as of 2026-08-04].

A pre-flight worth having: **a stale `<name>.rsproj.new` beside the project** (from an
interrupted GUI save) makes `-load` emit warning-class `0x82000017` while still completing —
enough to abort an errors-marker-gated workflow. Setting the temp aside (rename,
reversible) cleans the load [VERIFIED: FINDINGS 2026-07-29].

---

## 11. Anti-patterns

Each of these looks reasonable and is wrong. Every one was either done here or narrowly
avoided.

| # | Anti-pattern | Why it is wrong |
|---|---|---|
| 1 | Gate completion on `results_<inst>.log` growing | Internal heartbeat processes write it; a check built on it raced ahead of a running `-align` [VERIFIED: HANDOFF 2026-07-21] |
| 2 | Poll `tasklist` for the executable name | Silently matched nothing when `RealityCapture.exe` became `RealityScan.exe` [VERIFIED-as-history: CLAUDE.md hard rule 2] |
| 3 | One `-waitCompleted` after a delegated command | Returns prematurely before the queue is picked up [VERIFIED: FINDINGS 2026-07-21] |
| 4 | Treat any progress-line change as activity | `#timeout` lines tick their elapsed counter; a 6 h hang produced zero warnings [VERIFIED: NA167 B4] |
| 5 | Auto-kill on `#timeout` | A successful 94.6 % align emitted 40 of them [VERIFIED: NA167 #28] |
| 6 | Put an overall timeout on an align or a model | 10+ hour runs are normal; the hull model ran 338.3 min [VERIFIED-as-rule: CLAUDE.md hard rule 3] |
| 7 | Pass `key=value` as a `.bat`/`subprocess` argument | cmd splits it → `err:7155`, flag silently unapplied, **and** the parse error aborts the workflow [VERIFIED: NA167 B5] |
| 8 | Pass a component or image list as a delimited argument | Same splitting; "found 1" for a whole list. Lists cross as files [VERIFIED: NA167 B5] |
| 9 | Write a `.complist` with PowerShell `Set-Content -Encoding utf8` | BOM on line 1 silently invalidates the first entry [VERIFIED: FINDINGS 2026-07-27] |
| 10 | `-importComponent` a **copied** `.rsalign` | Permanent `#timeout` stall, ≥6 h, no error, no dump [VERIFIED: NA167 B1; CLAUDE.md hard rule 7] |
| 11 | Judge a merge by exit status | `-mergeComponents` exits SUCCESS and leaves components separate; instant completion is the no-fuse signature [VERIFIED: NA167 #23/#30] |
| 12 | Treat "no error" as "it worked" | Silent channels on record: silent non-merge, silent no-op selects on an empty scene, selection-emptied exports under `-silent`, an inert error hook, a blind peel harvest |
| 13 | Export while a selection is active | Under `-silent` the auto-answered dialog exports **nothing** in 0.057 s [VERIFIED: FINDINGS 2026-07-23] |
| 14 | Export without `-setMinComponentSize` | Components under the default **5** are silently excluded from selection *and* export [OFFICIAL: appbasics/allcommands for the default; VERIFIED: NA167 #22 / B11 (deprecation)] |
| 15 | Assume `-addFolder` recurses | `appIncSubdirs` defaults to **`false`** [OFFICIAL: tutorials/setkeyvaluetable, appbasics/allcommands]; without it a zone tree with per-camera subfolders adds "0 layer images", every flight-log row then fails `err:18002`, and the whole thing is a 25 s "successful" run. Set `appIncSubdirs=true` before **every** `-addFolder` [VERIFIED: FINDINGS 2026-07-23] |
| 16 | Pass a params XML to `-align` | Silently ignored in 2.x; push `sfm*`/`lis*` via `-set` [CONTRADICTED/VERIFIED: FINDINGS 2026-07-21] |
| 17 | Rely on instance defaults for alignment settings | Swept `-set` values **persist across instance restarts**; the instance carries whatever the last session set [VERIFIED: MERGE_TEST_PLAN §3] |
| 18 | Track components by name or index across runs | Fragmentation is strongly nondeterministic (2 vs 9 components on identical inputs); new components are named "Component N" with unstable N [VERIFIED: FINDINGS 2026-07-24] |
| 19 | Use component reimport as a checkpoint | Silently drops every never-registered orphan image [VERIFIED: FINDINGS 2026-07-23] |
| 20 | Copy overlap images into each zone folder | Destroys shared-camera identity, breaks flight-log arithmetic, inflates storage. Use hardlinks or `.imagelist` against one pool [VERIFIED: FINDINGS 2026-07-28] |
| 21 | Use directory junctions for the per-zone view | RealityScan writes **no** XMP behind a reparse point and PowerShell will not enumerate through one — 5 h 12 m scored as "nothing fused" [VERIFIED: FINDINGS 2026-07-27/28] |
| 22 | Read a number out of `RealityScan.log` without validating the snapshot | The log is global and truncated per boot; a snapshot became a splice of two runs [VERIFIED: FINDINGS 2026-07-27] |
| 23 | Snapshot the log "later" | Truncated at the next boot; a 91-byte capture is on record [VERIFIED: NA167 B6] |
| 24 | Use fixed model names in a per-component loop over one shared project | `-reprojectTexture` resolves operands by name and can map one component's texture onto another's mesh with a clean exit [VERIFIED: FINDINGS 2026-07-25] |
| 25 | Let `peel_index` alone name an export | Two accepted fusions in a cluster both claim `<tag>_m_c0` [VERIFIED: FINDINGS 2026-07-28] |
| 26 | Save the project mid-recipe with all intermediates live | ~81 GB of saves for one component [VERIFIED: FINDINGS 2026-07-29] |
| 27 | Delete the errors marker to clear it | Destroys the record of a whitelisted-but-real event; `move /y` to `expected_*.txt` instead |
| 28 | Whitelist an error class by string-matching `err:NNNN` in the marker | The marker carries only the **decimal** result code [VERIFIED: FINDINGS 2026-07-23] |
| 29 | Write `.bat`/`.vbs` with LF endings | cmd's label search is byte-offset sensitive; `call :run` fails nondeterministically [VERIFIED: NA167 #21] |
| 30 | `exit /b N` from a nested parenthesised block in a script's top-level body | Returns 0 to the caller — measured. Route validations to a top-level `:argfail` [VERIFIED: FINDINGS 2026-07-24] |
| 31 | Compose the VBS hook command with nested literal quotes | Malformed command line; `ErrorWriter.bat` never ran and error detection was inert for a day. Use `Chr(34)` [VERIFIED: FINDINGS 2026-07-24] |
| 32 | Leave `appProcessExecCmd` paths unquoted | Silently disabled all error detection when the checkout path contained spaces [VERIFIED: HANDOFF 2026-07-21] |
| 33 | Gate an unattended prompt on `isatty()` | It **lies** under hidden consoles — True with an EOF stdin. Wrap `input()` in `try/except EOFError` [VERIFIED: FINDINGS 2026-07-24/28] |
| 34 | Let a child driver prompt (unpinned options) | On a console the prompt goes into the captured pipe and blocks forever; detached it silently inherits another session's `rs_settings.json` [VERIFIED: FINDINGS 2026-07-29] |
| 35 | Spawn helper subprocesses without `CREATE_NO_WINDOW` | Hundreds of flashing console windows stealing focus |
| 36 | Watch only the project disk | The **cache** disk is a different drive and is what killed the hull model three times [VERIFIED: FINDINGS 2026-07-26] |
| 37 | Hand-delete cache files when the cache disk fills | "don't delete the files from your cache folder since this may lead to some failures in the project"; the sanctioned levers are freeing space on the cache disk or changing the cache disk. `-clearCache` exists but "You must save the project before clearing the application cache" [OFFICIAL: appbasics/outofdisk, appbasics/allcommands] |
| 38 | Quote instance memory from `tasklist` without identifying the process | Workflows run multiple `RealityScan.exe`; a "2.2 GB" reading was a 30 MB transient [VERIFIED: FINDINGS 2026-07-24] |
| 39 | Score an empty measurement as a negative result | An empty peel beside a non-empty export is a **broken instrument**; abort [VERIFIED-as-fix: FINDINGS 2026-07-28] |
| 40 | Publish a census under a name it cannot measure | `census_after_update` reported 0 for a sound 4,496-camera assembly because assemble mode exports no XMPs by design [VERIFIED-and-fixed: FINDINGS 2026-07-25] |
| 41 | Re-implement the driver's decision logic in its tests | Two tests would have kept passing had the driver regressed; extract pure functions and call them from both [VERIFIED-as-fix: FINDINGS 2026-07-29] |
| 42 | Reuse an output folder on the premise that recomputation is deterministic | Five zones became a silent **blend of two zonings** — 12,679 files against 9,834 reported — with `Success: True`. Fingerprint the inputs [VERIFIED-and-fixed: FINDINGS 2026-07-26] |
| 43 | `return` instead of `sys.exit(1)` when a module refuses to run | A bare return exits 0, so an unattended caller reads a refused run as success [VERIFIED-and-fixed: FINDINGS 2026-07-26] |
| 44 | Edit a `.bat` while a workflow is running | cmd reads the file by byte offset; a mid-run edit corrupts execution. Review-only during live runs [VERIFIED-as-policy: HANDOFF 2026-07-27] |
| 45 | Assume an isolation env var is read because it is set | `RS_INSTANCE` was written-only for months; a probe ran on RS1 believing it was RS2 [VERIFIED: FINDINGS 2026-07-28] |
| 46 | Retry a zone that failed to align solo | Deterministic solo failure is on record (zone_14, 4/4, internal `MSS_STR001`), and the same images align **fine inside a larger scene**. Grow it from an aligned neighbour [VERIFIED-as-workaround: NA167, 2026-07-24] |
| 47 | Deploy a hook or monitor without an end-to-end liveness test | The inert-ErrorWriter day. An active progress file without a growing results log is proof the hook is dead |
| 48 | Call `-exportRegistration` (or any export) without its params XML headless | `-exportRegistration` with no params XML **blocks forever** headless — there is no dialog to answer and no timeout. Save a params file from the GUI dialog once, then pass it [VERIFIED: FINDINGS 2026-07-21] |
| 49 | Use `-printReport` to get results out of a delegated workflow | "It does not work with delegation" [OFFICIAL: appbasics/allcommands]. `-exportReport` is the candidate, still unprobed headless [OPEN — A7] |
| 50 | Build an in-scene selection with a `-selectImage` regexp | Regexp/glob forms silently select **nothing** in 2.2 despite the documented `imagePath\|regexp` parameter; only literal full paths match, at ~0.1–0.3 s each [CONTRADICTED/VERIFIED: FINDINGS 2026-07-23, §5.4a] |
| 51 | Assume `-mergeComponents` can register an orphan image | Merge never adds images, and `MergeZoneComponents.bat` has no `-addFolder`, so a merge scene structurally cannot hold one [VERIFIED: FINDINGS 2026-07-27] |
| 52 | Treat "the components have zero shared paths" as "they cannot merge" | Refuted by probe D7: zero shared basenames **and** zero shared paths fused to an exact 78+42=120 under `-mergeComponents`, with and without a flight log. Content overlap is the real predicate [VERIFIED: FINDINGS 2026-07-24, D7 RESOLVED; supersedes the RECON "path identity" entry of the same day] |
| 53 | Read a fused component's zero camera loss as proof of a good fusion | Zero loss between components with zero shared imagery is the **rigid-glue** signature — eight disjoint objects in one container, scored as an exact-sum fusion [VERIFIED: FINDINGS 2026-07-28] |

---

## 12. Environment-variable contract

Every knob the harness honours, in one place. All are read by the `.bat` layer, the Python
layer, or both.

| Variable | Read by | Values | Effect |
|---|---|---|---|
| `RS_EXECUTABLE` | `SetVariables.bat`, `RealityScanCLI.find_executable` | full path | Overrides executable discovery (which otherwise tries `C:\Program Files\Epic Games\RealityScan_2.2\…` first, then Capturing Reality 2.2, then 2.1/2.0) |
| `RS_INSTANCE` | `SetVariables.bat`, `RealityScanCLI.__init__` | name, no spaces | Instance to boot/delegate to. Default `RS1` |
| `RS_GPU_DEVICES` | `startRealityScan.bat` | e.g. `0`, `0,1` | Exported as `CUDA_VISIBLE_DEVICES` before launch |
| `CUDA_VISIBLE_DEVICES` | RealityScan / CUDA | — | Set by the above and by `run_batch_script` |
| `RS_HEADLESS` | `SetVariables.bat` | `0` = GUI visible | Any other value or unset ⇒ `-headless` |
| `RS_CACHE_DIR` | `startRealityScan.bat`, resource trace | path | `-set "appCacheLocation=Custom"` + `appCacheCustomLocation`; also adds the `cache_free_gb` trace column |
| `RS_PROJECTS_DIR` | all workflows | path or **unset** | Dated `RC_projects` copies. **Unset skips them** — the deferral that saves ~10× on save cost |
| `RS_PROJECT_LABEL` | all workflows | e.g. `NA156_H2024_V2` | `{label}_{scene}_{date}.rsproj` |
| `RS_PROJECT_DATE` | all workflows | `YYYYMMDD` | Set by `set_project_save_env`; same-day re-saves overwrite, a new day starts a fresh copy |
| `RS_ALIGN_PARAMS` | `AlignZone.bat` | path | Test-cell override pointing at a variant `AlignmentParams.xml` without touching the canonical Metadata copy |
| `RS_MERGE_FLIGHT_LOG` / `RS_MERGE_FLIGHT_LOG_PARAMS` | `MergeZoneComponents.bat` | paths | Union log + CRS for the merge scene; required for a georeferenced result |
| `RS_MERGE_HARVEST` | `MergeZoneComponents.bat` | `1` | Enables the count-based peel loop |
| `RS_MERGE_IMAGES_ROOT` | `MergeZoneComponents.bat` | path | Tree the peel harvest sweeps for pose sidecars |
| `RS_GROW_SELECT_CMDS` | `GrowZone.bat` | `editsel` (default) \| `legacy` | `-editInputSelection "key=value"` vs `-enableAlignment`/`-setFeatureSource` |
| `RS_GROW_LOCK_ANCHOR` | `GrowZone.bat` | `1` | Locks the primary component's poses (`inpPose=3`) — **off by default; U18 FAILED, `-align` refuses incremental adds with Exact priors** |
| `RS_GROW_FLIGHT_LOG` / `RS_GROW_FLIGHT_LOG_PARAMS` | `GrowZone.bat` `addgrow` mode | paths | Re-import the union log after adding images |
| `RS_MODULES` | `main.py` | comma-separated display names | Select pipeline modules without a TTY; unknown names exit 1 |
| `RS_NO_INTERACTIVE` | `main.py` | truthy | Enable all modules (or the `RS_MODULES` selection) without prompting |
| `RS_SHOW_PLOTS` | batcher | `1` | Opt into blocking matplotlib figures (default off — `plt.show()` under a hidden console blocks forever) |
| `PYTHONIOENCODING` | Python children | `utf-8` | Required when parsing UTF-8 sources; the console itself stays ASCII-only |

[VERIFIED-by-inspection: RS_CLI/Scripts/*.bat, realityscan_cli.py, main.py, merge_zones.py,
grow_zone.py, run_models.py, testing/run_h2024_v2.py, 2026-08-04; individual behaviours
tagged in the sections above]

Four knobs are **not** environment variables — they live in `rs_settings.json` (repo root,
gitignored) under the `realityscan` section and are read by `RealityScanCLI`
[VERIFIED-by-inspection: realityscan_cli.py, 2026-08-04]:

| key | consumed by | effect |
|---|---|---|
| `executable` | `find_executable` | Tried **before** `RS_EXECUTABLE`, then before the built-in install-location list |
| `instance_name` | `__init__` | Third in the resolution order: constructor arg → `RS_INSTANCE` → this → `RS1` |
| `gpu_devices` | `run_batch_script` | Default for the `gpu_devices` argument; exported as both `RS_GPU_DEVICES` and `CUDA_VISIBLE_DEVICES` |
| `shutdown_timeout` | `wait_for_instance_shutdown` | Overrides the 900 s verified-shutdown bound |

`SettingsStore` also persists last-entered prompt answers as defaults for every
user-facing path prompt — which is precisely why an unattended child driver that leaves an
option unpinned does not fail, it **silently inherits another session's value** (§10.2,
anti-pattern 34).

---

## Open questions

Every [OPEN] item raised in this document, with the cheapest probe that would close it.

| # | Question | Cheapest probe |
|---|---|---|
| A1 | **Are two concurrent instances on different GPUs actually safe?** Single-instance GPU pinning is exercised; two instances at once has **never been run**, so lock/marker isolation and cache contention are unverified in practice. | Boot RS1 on GPU 0 and RS2 on GPU 1 with distinct workspaces and distinct `RS_CACHE_DIR`s, align two small zones simultaneously, then check: both `errors_RS*.txt` empty, both peel harvests non-empty and correct, no cross-contamination in either `results_RS*.log`. ~15 min. (NA167 loose end #2.) |
| A2 | **How long does `-quit` → `-getStatus`-gone take on a large scene?** The 900 s bound has only been exercised on small scenes; a 4,000+ camera scene may exceed it and trip the "did not shut down" hard stop. | Time one teardown of an existing 4,860-camera assembly. Costs one teardown. |
| A3 | **Can two instances share one cache directory?** `appCacheCustomLocation` is a path, not an instance property. | Point RS1 and RS2 at the same `RS_CACHE_DIR`, run two small aligns, compare registration against solo runs and watch for cache-side errors. Folds into A1. |
| A4 | **Is the pose-sidecar write path safe when two instances target the same image tree?** Inferred unsafe from the stem-naming rule; not measured. | Two instances aligning overlapping subsets of one tree; census both and check for lost/overwritten sidecars. Do not run this on production imagery. |
| A5 | **What exactly does `Finalizing N component(s)` count** — new components, or the scene total? It is recorded per attempt as `rs_finalizing` and deliberately never gated on. | Queued probe (a): import two tiny components, run one merge, count the result against the logged N. Minutes. |
| A6 | **Does `-exportLatestComponents` produce anything after `-mergeComponents`** (there is no "last alignment")? `MergeZoneComponents.bat` only calls it in `align` mode, on the assumption that it does not. | Hardening cell U9: merge mode on the smoke fixture, then `-exportLatestComponents`, then count files. |
| A7 | **Can `-exportReport` run headless without blocking, and does it emit georeferencing status/residuals?** This is the standing candidate for a CLI-observable georeference check (cell U7 — the longest-open item, since 2026-07-23; today georeferencing of an assembled scene is verified **only in the GUI**). | Export a components report params XML from the GUI once, then delegate `-exportReport "<out>.html" "<template>" true` under a watchdog. Two known hazards to respect: `-printReport` "does not work with delegation" [OFFICIAL: appbasics/allcommands], and `-exportRegistration` **without** a params XML blocks forever headless [VERIFIED: FINDINGS 2026-07-21] — so run the probe with a watchdog and a params file, never bare. |
| A8 | **Is the 2-camera / 5-camera merge deficit a real solver loss or a harvest artifact?** The peel harvest is a single PowerShell `Get-ChildItem -Recurse \| Move-Item -Force` line; PowerShell 5.1 exits 0 on non-terminating pipeline errors, so `if errorlevel 1` cannot see a partial move — two locked sidecars are a silent −2. A flat `-Force` move also collapses same-stem ordinal sidecars from different folders. | Re-import `cluster_*_m_c0.rsalign` **from its original export location** into a spare instance and census it: 3,740 means accounting artifact, 3,738 means real loss. Do **not** try to settle it from `rslog.txt` — the log-splice finding makes those snapshots untrustworthy on these artifacts. |
| A9 | **A truncated peel is currently indistinguishable from a complete one.** The reader breaks on the first missing or empty `identity_r<K>`, while the workflow creates that directory *before* knowing a component remains; both the lap cap (`GEQ 20`/`GEQ 40`) and a missing export fall through to `exit /b 0`; `expected_peelend_<inst>.txt` is written and never read. | Make the peel emit an explicit terminal record the reader must find (or have the reader require `expected_peelend_<inst>.txt`), then force a truncation by capping the loop at 1 and confirm the run refuses to score. Code change plus one smoke run. |
| A10 | **The peel count is the sole evidence for membership, camera_count and the invariant, and its instrument is never asserted.** Nothing sanitizes the image tree before an attempt, and `census_leftover` is recorded but never checked — so an inflation of +N can exactly cancel a real loss of −N, yielding `confidence == "exact"`, `lost == 0`, and a **false accept** whose manifest names basenames the component does not contain. | Assert `census_leftover == 0` before each attempt and fail loudly otherwise; validate by seeding a stray pose sidecar into the tree and confirming the attempt refuses to start. |
| A11 | **Why does `-selectModel <tag>_HighPoly` return the whitelisted empty-selection code in every cleanup loop?** Six components for six. Benign today; it leaves one cosmetic intermediate behind, and the whitelist that tolerates it is broader than the known cause. | Queued probe (e): the GenerateModel error-whitelist redesign, which needs (a)-style probing of the exact benign select-miss code first. |
| A12 | **Attempts that RE-IMPORT a previously fused component harvest nothing.** cluster_1 attempts 2–4, whose scenes contained `cluster_1_m_c0.rsalign` from attempt 1, all recorded `identity_r0: 0`, while attempts 1 and 5 harvested normally. Consistent with the ordinal/identity rule but not established; did not recur in merged5. **Do not build on it without a probe.** | Import one previously fused `.rsalign` from its original location into a fresh scene, run one peel lap, count sidecars. Minutes. |
| A13 | **A one-off, unexplained cmd anomaly:** after D6's 56-minute merge block, `%RealityScan%` expanded **empty** ("'-delegateTo' is not recognized") and the export step died. Single occurrence across ~10 identical workflows. | No probe designed; watch for recurrence. If it recurs, log `%RealityScan%` immediately before every `:run` for the affected workflow. |
| A14 | **Can headless RS 2.2 hit a licensing/activation prompt that manifests as a silent hang?** Nothing in two years of headless production recorded one — absence of evidence, not evidence of absence. The Help states some pop-ups (a log-in window is named) still demand interaction even under `-silent` [OFFICIAL: tutorials/headless]. | No cheap probe designed. Mitigation meanwhile: the 2 h stall warning plus the `#timeout`-from-0.00 signature. |
| A15 | **Does the hand-merged 13-column flight-log format survive an app update?** `C:\Program Files\Epic Games\RealityScan_2.2\flightlogs.xml` was hand-edited to add `{B438A617-2434-5A24-C1B7-58980F28345A}`; an update that replaces the file silently drops orientation and per-image accuracies from every import. | After any RealityScan update, grep the installed `flightlogs.xml` for the GUID before the first run. Seconds — but it must be in the update checklist, not remembered. |
| A16 | **Does `-deleteAutosave` do anything when appended to `-newScene`?** It is documented only as an optional parameter of `-load`, and `-newScene` is documented as taking none [OFFICIAL: appbasics/allcommands]. `startRealityScan.bat`'s instance-reuse branch has issued `-newScene -deleteAutosave` in production since 2026-07-21 with no error and no observed stale autosave — but `appAutoSaveMode=false` is also pinned, so the two mitigations are confounded. | Boot an instance with `appAutoSaveMode=true`, force an autosave, then reuse the instance with `-newScene -deleteAutosave` and check whether the autosave file is gone. If not, move the reset to `-load <path> deleteAutosave` or clear the autosave from the driver. Minutes. |
| A17 | **Is `-selectImage`'s regexp form broken, or does 2.2 expect a different regexp dialect?** Only "silently selects nothing" is established, not why; the Help's `imagePath\|regexp` wording promises more. The forum-mining follow-up is open [FINDINGS 2026-07-23]. | On the smoke fixture, try the same selection as: literal full path (known-good control), bare stem, `.*` -wrapped, ECMAScript `^.*P231C.*$`, and a backslash-escaped Windows path pattern — one `-selectImage` each followed by a selection-visible operation. Under 10 minutes and it either finds a working dialect or converts the [CONTRADICTED] into a hard "regexp is dead in 2.2". |

## Addenda — reconciled from `FINDINGS.md`, 2026-09-05

Facts established after this document was written (2026-08-04), carried here so the manual stays the document of record. Each keeps the FINDINGS date as its citation; the raw entry has the full observation.

### A1. The errors file is STICKY for the whole session

`:run` decides success by testing whether `errors_<instance>.txt` is non-empty after each delegated command. That file persists for the entire instance session and only `RealityScanCLI` clears it, pre-run. Two consequences, both observed on NA165/H2060: (1) **misattribution** — the file holds the last error from ANY source, so `:run` blames whatever it just issued (a failed `-selectModel` was reported against a model NAME for hours); (2) **no tolerated failures** — one optional step that fails poisons every later `:run`, so one missing format killed a 20-component export. The tolerated-failure primitive already exists: `try_delete_model` / `try_filter` / `run_peelrename` MOVE the file to `expected_<reason>_<instance>.txt`, preserving the evidence without deleting it (hard rule 4). It is applied ad hoc per call site; a shared `:try_run <tag> <cmd…>` is the open design note (`HANDOFF` loose end 1). An optional step is a SKIP or an `expected_*` move, never a caught error. [VERIFIED: FINDINGS 2026-09-02]

### A2. Order of operations in the align workflow

Settings (`-set` from the params XML, every key it names) → pin project and output CRS → `-importFlightLog` → `-align`. The flight log goes in AFTER the `sfm*` settings because `sfmEnableCameraPrior`, `sfmCameraPriorWeight` and `sfmCameraPriorAccuracy*` decide how the priors are weighted at import; the CRS goes in BEFORE the import per Epic's own instruction and because an unpinned project CRS leaves the export label arbitrary (`06` §3.2). The §10 recipe above was corrected to this order. [VERIFIED: FINDINGS 2026-08-14, 2026-09-02]

### A3. `schtasks /End` does not kill the run

Ending a scheduled task stops the task's process, not the driver python or its `.bat` / RealityScan children. Enumerate by `Win32_Process CommandLine` and stop them explicitly; a hard-killed instance then needs the recovery recipe in `01` A2. [VERIFIED: FINDINGS 2026-08-09]
