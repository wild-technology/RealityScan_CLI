# Failure modes, race conditions, error codes, diagnostics

This document is the catalogue of everything that goes wrong when RealityScan 2.2 is
driven headless from the command line, and of everything that goes wrong in the Windows
harness that drives it. Each entry states the symptom, the root cause (or says the cause
is not established), how it was actually detected, the mitigation in force, and a
detection test that can be run to prove the entry applies to a given run. It also carries
the complete known table of exit codes, process-trigger result codes, `err:NNNN` codes and
process IDs, and it ends with an ordered diagnostic playbook keyed by symptom. It does
**not** teach the commands themselves (see `02-command-reference.md`), the settings keys
(`03-settings-keys.md`), the correct merge semantics (`08-components-and-merge.md`), the
model recipe (`10-reconstruction-texturing-export.md`) or the synchronisation patterns
that avoid these failures in the first place (`11-automation-patterns.md`,
`01-cli-fundamentals.md`). Entries here are numbered `F-nn` so a skill can cite one.

**Applies to:** RealityScan 2.2 (Epic Games), Windows, headless CLI operation.
**Tags:** [OFFICIAL] shipped Help · [VERIFIED] measured in production here ·
[CONTRADICTED] docs vs observation · [UNDOCUMENTED] · [INFERRED] · [OPEN]

---

## Contents

1. [The governing rule: exit status is not evidence](#1-the-governing-rule-exit-status-is-not-evidence)
2. [Codes: exit codes, process-result codes, err:NNNN, process IDs](#2-codes-exit-codes-process-result-codes-errnnnn-process-ids)
3. [F-01…F-17, F-79 — Silent-success failures at the RealityScan boundary](#3-f-01f-17-f-79--silent-success-failures-at-the-realityscan-boundary)
4. [F-18…F-26, F-82 — Instrument blindness: when the oracle is the thing that broke](#4-f-18f-26-f-82--instrument-blindness-when-the-oracle-is-the-thing-that-broke)
5. [F-27…F-34 — Delegation, wait and teardown races](#5-f-27f-34--delegation-wait-and-teardown-races)
6. [F-35…F-38, F-78 — `#timeout` stalls and other hangs](#6-f-35f-38-f-78--timeout-stalls-and-other-hangs)
7. [F-39…F-40 — `RealityScan.log` truncation and the snapshot protocol](#7-f-39f-40--realityscanlog-truncation-and-the-snapshot-protocol)
8. [F-41…F-46 — Solver bugs, crashes and unstable re-solves](#8-f-41f-46--solver-bugs-crashes-and-unstable-re-solves)
9. [F-47…F-52, F-83…F-84 — XMP / sidecar bug classes](#9-f-47f-52-f-83f-84--xmp--sidecar-bug-classes)
10. [F-53…F-56, F-80…F-81 — Component and model identity collisions, and workflow guards](#10-f-53f-56-f-80f-81--component-and-model-identity-collisions-and-workflow-guards)
11. [F-57…F-61 — Filesystem traps that break RealityScan specifically](#11-f-57f-61--filesystem-traps-that-break-realityscan-specifically)
12. [F-62…F-70 — Windows / cmd traps that break the harness](#12-f-62f-70--windows--cmd-traps-that-break-the-harness)
13. [F-71…F-77 — Resource exhaustion](#13-f-71f-77--resource-exhaustion)
14. [The NA167 B1–B11 bug list, mapped](#14-the-na167-b1b11-bug-list-mapped)
15. [Diagnostic playbook](#15-diagnostic-playbook)
16. [Open questions](#open-questions)

Numbering note: `F-01`…`F-77` were assigned first and are **stable** — later entries were
appended as `F-78`…`F-84` inside the topically correct section rather than renumbering, so
a section's range is not always contiguous. Cite the `F-nn`, not the position.

---

## 1. The governing rule: exit status is not evidence

Every failure class in this document shares one shape: **RealityScan reports success and
the thing you asked for did not happen.** That is not an occasional accident of this
build — it is the dominant failure mode. Across two years of production use the repo
records silent non-merges, silent no-op selections, silently-inert settings, silently
ignored sidecars, exports that write zero files while logging a duration, an error channel
that was itself dead for a day, and a measurement harness that reported `0` for a sound
4,496-camera result. [VERIFIED: FINDINGS "Process conventions"; NA167 #23]

Three operational rules follow, and they are stated in `CLAUDE.md`, `HANDOFF.md` and
`MERGE_STRATEGY_REPORT.md` in identical terms:

| Rule | Statement | Source |
|---|---|---|
| R1 | **Verify every merge and every growth pass by pose-XMP camera census, never by exit status.** | [VERIFIED: NA167 #23] |
| R2 | **Never infer completion from an event you cannot attribute to your own command** — not process names (`tasklist`), not results-log growth. | [VERIFIED: docs/code-review-2026-07 §3] |
| R3 | **A metric that reads zero is instrumentation-suspect until the instrument is verified against a known-good and a known-bad case.** | [VERIFIED: docs/code-review-2026-07 §5] |

A corollary that cost this repo two full production runs: **an oracle that cannot see its
subject must not publish a number under a name that claims it did.** [VERIFIED: FINDINGS
2026-07-25] See F-19.

---

## 2. Codes: exit codes, process-result codes, `err:NNNN`, process IDs

There are **four distinct code channels** in headless operation, and confusing them is
itself a diagnostic failure. Know which one you are reading.

| Channel | Where it appears | What it carries | Survives the run? |
|---|---|---|---|
| **A. Process exit code** | `%errorlevel%` of the `RealityScan.exe` invocation | 0 / decimal error code (only with `appQuitOnError=true`) / 3 on crash | yes |
| **B. `$(processResult)`** | `errors_<inst>.txt` / `results_<inst>.log` via the `appProcessAction=ExecuteProgram` hook | decimal result code **only** — never the `err:NNNN` text | yes (marker files on disk) |
| **C. `err:NNNN` + reason text** | `%LOCALAPPDATA%\Temp\RealityScan.log` | the human-readable reason (`[Internal error MSS_STR001]`, `Out of disk space..`, `Parsing setting … failed`) | **NO — truncated at every instance boot** (F-39) |
| **D. Progress stream** | `progress_<inst>.txt` written by `-writeProgress` | `algId progress duration estimation #eventType` | yes, but overwritten per run by the orchestrator |

The single most important consequence: **the errors marker carries only the numeric result
code, never the `err:NNNN` text.** Any tolerant handler must match on the decimal code, and
any diagnosis of *why* a code appeared requires channel C, which the next boot destroys.
[VERIFIED: FINDINGS 2026-07-23]

### 2.1 Process exit codes (channel A)

| Exit code | Meaning | Tag |
|---|---|---|
| `0` | Process finished successfully | [OFFICIAL: tutorials/commandline_5] |
| decimal error code | The specific error's decimal code — **only produced when `-set "appQuitOnError=true"`** | [OFFICIAL: tutorials/commandline_5] |
| `3` | Crash with minidump; the dump is written to the `-silent <crashReportPath>` directory | [OFFICIAL: tutorials/commandline_5] |
| `1` from a `.bat` | The workflow's own abort (`:run` saw a non-empty errors marker, or `-delegateTo` failed) — **not** a RealityScan code | [VERIFIED: RS_CLI/Scripts/*.bat] |

`appQuitOnError` is `bool`, **default `false`** [OFFICIAL: tutorials/setkeyvaluetable], and
this repo pins it to `false` deliberately, so channel A is almost always 0 and carries no
information: warning-class results such as `0x820000FF` are routine and the orchestrator,
not the app, decides what is fatal. [VERIFIED: `startRealityScan.bat` boot line]
Two sibling keys exist and are also `false` by default: `appQuitOnReset` (quit instead of
showing the "restart required" dialog after a setting that needs a reset) and
`suppressErrors` (suppress error messages). [OFFICIAL: tutorials/commandline_5;
tutorials/setkeyvaluetable] Neither is set here.

**Consequence for a skill:** with `appQuitOnError=false` you cannot read failure off the
process. Channel B (the marker files) is the only per-operation success signal, and
channel C is the only place its *reason* lives.

### 2.2 Process-trigger result codes (channel B)

The hook is armed at boot with the documented settings quartet and fires for **every**
completed process:

```bat
-set "appProcessActionTime=0"
-set "appProcessAction=ExecuteProgram"
-set "appProcessExecCmd=wscript.exe //B \"%ErrorPath%\ErrorWriterLaunch.vbs\" $(processResult) $(processId) $(processDuration:d) %RS_INSTANCE%"
```

`$(processResult)`, `$(processId)` and `$(processDuration:d)` are real substitutions
carrying the result code, the process ID and the duration in seconds.
[OFFICIAL: tutorials/commandline_5] [VERIFIED: in production since 2026-07-21]

Full table of result codes observed here. Decimal is what lands in `errors_<inst>.txt`;
hex is what appears in `RealityScan.log`.

| Decimal | Hex | Meaning as established | How known | Tag |
|---:|---|---|---|---|
| `0` | — | Success | Epic states `processResult == 0` means the process finished correctly | [OFFICIAL: tutorials/commandline_5] |
| `1` | — | **Also routine success.** Ordinary successful operations (e.g. `-addFolder`) report `1` through the trigger | Epic's own sample `ErrorWriter.bat` whitelists both `0` and `1`; confirmed in production | [OFFICIAL: tutorials/commandline_5] + [VERIFIED: FINDINGS 2026-07-21] |
| `2181038335` | `0x820000FF` | **Warning class.** Seen for `err:18002` — `-importFlightLog` where the log references images not in the scene. The trajectory still imports for every image that *is* present | Cross-checked against every component manifest: the 102 "not found" images were exactly the unregistered remainder, zero overlap with any component | [VERIFIED: FINDINGS 2026-07-21, 2026-07-25] — Epic's own sample output in the Help prints this exact decimal, but for process `20599` = `IMPORT_GCP`, not the flight-log import [OFFICIAL: tutorials/commandline_5 + tutorials/processids], so the code is a *class*, not a flight-log signature |
| `2147942487` | `0x80070057` | `E_INVALIDARG`. Empty / no-op selection paths: `err:5605` "no component selected" after `-renameSelectedComponent` on an emptied scene; `err:5601` "model name not found" from `-selectModel`; `-selectModel <tag>_HighPoly` in every model cleanup loop | Marker artifacts `expected_peelend_RS1.txt` (process `21859`, "in 0 seconds") and `expected_select_RS1_*.txt` (process `21856`) | [VERIFIED: FINDINGS 2026-07-24, 2026-07-29; docs/code-review-2026-07] |
| `2147549183` | `0x8000FFFF` | **Generic "unexpected program state".** Ambiguous by design: a broken `-set` argument and the zone_14 alignment solver bug emit the identical code | Two unrelated failures, same code; the discriminating text was only in `RealityScan.log` | [VERIFIED: NA167 #16 / B6] |
| `2147942512` | `0x80070070` | `ERROR_DISK_FULL` — **RealityScan's cache disk**, not necessarily the project disk | The hull-model retry died with this after 143.5 min; the instance log later said `Processing failed: Out of disk space..` | [VERIFIED: FINDINGS 2026-07-26] |
| `2181038176` | `0x82000060` | **Unknown / invalid command.** Emitted by `-selectAllComponents`, which does not exist in 2.2 | Command taken from an older repo script; Help lists only `selectComponent` / `selectMaximalComponent` / `selectComponentWithLeastReprojectionError` | [VERIFIED: NA167 #13 / B2] — decimal is the arithmetic conversion of the logged hex, not itself observed in a marker |
| `2181038103` | `0x82000017` | Warning-class load complaint raised by a stale `<name>.rsproj.new` beside the project. The load still completes | An interrupted GUI save left the temp file; the next headless `-load` warned and the error channel then aborted the workflow | [VERIFIED: FINDINGS 2026-07-29] — decimal is the arithmetic conversion of the logged hex |
| `3` | — | Crash; minidump `RealityScanCrash-YYYYMMDD-HHMMSS.dmp` in the `-silent` directory | The *code* is Epic's; what this repo observed is the minidump plus a dead instance (F-42). **The value `3` has never been read off a process here**, because the crashing process is the delegated headless instance, not the `.bat` that the orchestrator launches — that `.bat` sees `ERROR: Failed to delegate command` and exits `1` | [OFFICIAL: tutorials/commandline_5] for the code; [VERIFIED: FINDINGS 2026-07-26] for the dump + dead-instance signature only |

Codes that appear only in `RealityScan.log` (channel C), with no distinct marker value:

| `err:` code | Meaning | Tag |
|---|---|---|
| `err:7155` | `Parsing setting key=value '<key>' failed` — a `-set` argument arrived split across the cmd boundary. The flag was **never applied** | [VERIFIED: NA167 #15 / B5] |
| `err:18002` | "The file contains N images which are not in the current scene" (flight-log import); surfaces as `0x820000FF` | [VERIFIED: FINDINGS 2026-07-21] |
| `err:5601` | Model name not found (`-selectModel` on a renamed-away model); surfaces as `0x80070057` | [VERIFIED: FINDINGS 2026-07-29] |
| `err:5605` | No component selected; surfaces as `0x80070057` | [VERIFIED: docs/code-review-2026-07] |
| `MSS_STR001` | Internal reconstruction error, printed as `Processing failed: Unexpected program state. [Internal error MSS_STR001]`; surfaces as `0x8000FFFF` | [VERIFIED: NA167 B8; `testing/results/z14_forensic_rslog.txt` line 1491-1493] |

**When a code is ambiguous — and `0x8000FFFF` always is — the only remedy is to snapshot
`%LOCALAPPDATA%\Temp\RealityScan.log` inside the driver, immediately after the failing
call returns, before anything can boot another instance.** See F-39/F-40 for the protocol
and its own failure mode.

### 2.3 Process IDs worth recognising in a marker line

`$(processId)` is the `algId` from the official process-ID table, so a marker line
identifies *which* operation failed even though it never names it. The full table is in
`tutorials/processids` [OFFICIAL]; these are the ones that actually appear in this repo's
`results_<inst>.log` / `errors_<inst>.txt` artifacts and in stall diagnosis.

| algId | Name | Where you see it |
|---:|---|---|
| `65537` | `ALIGN_NORMAL` | the align itself; `progress_RS2.txt` shows `65537 0.51 401.68 386.54 #progress` |
| `65538` | `ALIGN_DRAFT` | draft-mode align |
| `65539` | `SFM_FEATURES_DETECTION` | feature detection phase |
| `77824` | `SFM_MATCHING` | matching phase |
| `77840` | `SFM_ALIGNMENT_MAIN` | main bundle phase |
| `20532` | `PROJECT_LOAD` | `-load`; 41 s on a real assembly |
| `20533` | `PROJECT_SAVE` | `-save`; 732 s on a six-component assembly |
| `20534` | `PROJECT_AUTOSAVE` | should never appear here — this repo boots with `appAutoSaveMode=false`. Its appearance proves the instance was **not** booted by this harness, because the app default is `true` (F-79) |
| `20594` | `IMPORT_COMPONENT` | `-importComponent`; the process that hangs in F-36 |
| `20598` | `IMPORT_FLIGHT_LOG` | `expected_18002_RS1.txt` records `process 20598 … result code 2181038335 in 3 seconds` |
| `20599` | `IMPORT_GCP` | never fired here; it is the id in **Epic's own sample error line**, which is why that sample must not be read as documenting the flight-log case |
| `20584` | `EXPORT_XMP` | `-exportXMP` |
| `20576` | `EXPORT_REGISTRATION` | documented; **does not appear in any marker artifact in this repo** |
| `41061` / `41062` / `41063` / `41064` | `EXPORT_REGISTRATION_FILE`, `_COMPONENT`, `_PREPROCESS`, `_FINALIZE` | **the "heartbeat" family.** `41061/41063/41064` recur constantly at zero duration whether or not an export is running — 106/105/99 occurrences in this repo's `results_RS1.log`, `41062` zero. [CONTRADICTED: the official table names them as export-registration sub-phases [OFFICIAL: tutorials/processids]; observed, they fire continuously with no export in progress and are what broke log-growth completion detection (F-25)] |
| `6` | `EXPORT_MODEL` | observed at result `0` in `results_RS1.log` during deliverable export |
| `21861` | `CLI_CLEAR_CACHE` | `-clearCache`; not used here (see F-71 on why hand-clearing the cache is not a remedy) |
| `21845` | `CLI_PARSE_PARAMS` | where a malformed `-set` surfaces |
| `21857` | `CLI_SELECT_COMPONENT` | `-selectComponent` |
| `21859` | `CLI_RENAME_SELECTED_COMPONENT` | the peel-terminal `0x80070057` in `expected_peelend_RS1.txt` |
| `21863` | `CLI_DELETE_SELECTED_COMPONENT` | `-deleteSelectedComponent` |
| `21884` | `CLI_SELECT_IMAGE` | `-selectImage` |
| `20562` | `CALCULATE_MODEL_HIGH` | `-calculateHighModel`, model step [1/8] |
| `25` / `26` | `CLEAN_MODEL` / `CLOSE_HOLES` | model step [5/8]; the crash site in F-42 |
| `11` | `SIMPLIFY` | model step [6/8]; the `ERROR_DISK_FULL` site in F-71 |
| `7` | `MODEL_TEXTURE` | `-calculateTexture` |
| `21040` | `REPROJECT_TEXTURE` | `-reprojectTexture`, model step [8/8] |
| `21028` / `21029` / `21030` | `SELECT_MARGINAL_TRIANGLES` / `SELECT_TRIANGLES_BY_EDGE_SIZE` / `SELECT_MAX_CONNECTED_COMPONENTS` | the model cleanup filters |
| `21856` | **not in the official table** — empirically the process fired by `-selectModel`. Every `expected_select_<inst>_<model>.txt` artifact records `An error occurred: process 21856 finished with result code 2147942487 in 0 seconds.` from a `-selectModel` call in `GenerateModel.bat` / `ExportDeliverables.bat`; 101 occurrences in `results_RS1.log`, all `2147942487` | [UNDOCUMENTED] [INFERRED: it is `CLI_SELECT_MODEL`, sitting in the gap between the documented `21845 CLI_PARSE_PARAMS` and `21857 CLI_SELECT_COMPONENT`] |
| `21896` | **not in the official table**; observed at result `0`, 8× in `results_RS1.log` and 2× in `results_RS2.log`, always at a boot/teardown boundary | [UNDOCUMENTED] [OPEN] |

### 2.4 Progress-stream event types

`-writeProgress <file> <timeout>` writes five columns: `algId progress duration estimation
eventType`, where `algId` is the process ID, `progress` is a fraction in `<0,1>`,
`duration` is elapsed seconds, `estimation` is estimated remaining seconds, and
`eventType ∈ {started, progress, timeout, completed}` is rendered in the file as
`#started` / `#progress` / `#timeout` / `#completed`.
[OFFICIAL: tutorials/commandline_5]

Real lines from this repo's `progress_RS2.txt` (a merge-scene align, algId `65537`
`ALIGN_NORMAL`, which ran to `1.00` in 566.68 s) and `progress_RS1.txt` (a model/export
session, where the `-selectModel` process `21856` starts and completes inside 0.03 s):

```
65537 0.51 401.68 386.54 #progress
65537 1.00 566.68 0.65 #progress
21856 0.00 0.03 0.00 #started
21856 1.00 0.03 0.00 #completed
```

The Help documents the *existence* of `timeout` as an event type and says nothing about
what it means. Everything in §6 about `#timeout` is [UNDOCUMENTED] behaviour established
here.

The `<timeout>` argument's semantics are also undocumented beyond "during a defined period
of time (timeout in seconds)". Production passes `600`
(`startRealityScan.bat`: `-writeProgress "%ErrorPath%\progress_%RS_INSTANCE%.txt" 600`) and
multi-hour runs keep emitting lines, so it plainly does not stop the stream after 600 s.
[VERIFIED: `startRealityScan.bat` + every long run] [OPEN: O-10 — what it *does* bound]

---

## 3. F-01…F-17, F-79, F-85…F-88 — Silent-success failures at the RealityScan boundary

Each entry: **Symptom / Cause / Detected by / Mitigation / Detection test.**

### F-01 — `-mergeComponents` exits SUCCESS and leaves the components separate
- **Symptom.** Workflow exit 0, no errors marker, "merge" completes in seconds to a few
  minutes; the maximal component afterwards is byte-for-byte one of the inputs.
- **Cause.** Fusion is **content-driven**. Zero content overlap ⇒ silent no-fuse,
  regardless of mechanism, flags or path form. [VERIFIED: NA167 #26; FINDINGS "D7 RESOLVED"]
- **Detected by.** Camera census of the result: the maximal component was exactly
  zone_6's 1,533/1,534 cameras in every cell of a mechanism × flag × path-form matrix.
- **Mitigation.** Gate merge candidates on shared imagery or true bbox overlap before
  spending a merge; verify by census afterwards (R1).
- **Detection test.** A working merge takes **real time** — ~56 min for a 1–4 k-camera
  pair with shared cameras. *Instant completion is the no-fuse signature.*
  [VERIFIED: NA167 #23/#30/#31 / D6]

### F-02 — `-mergeComponents` with a single component is a no-op that also clears the selection
- **Symptom.** `-renameSelectedComponent "Merged"` immediately afterwards fails
  `No component selected [err:5605]` → `0x80070057`.
- **Cause.** With one component the merge does nothing but still triggers an
  **asynchronous re-reconstruction**, leaving nothing selected.
- **Detected by.** Repeated failure of the rename in the smoke workflow after the
  completion-detection bug (F-25) was already fixed.
- **Mitigation.** Use `-selectMaximalComponent` (no parameters) before the rename; do not
  use `-mergeComponents` as a "select the merged thing" idiom.
  [VERIFIED: HANDOFF 2026-07-21; docs/code-review-2026-07 §4]
- **Detection test.** Issue `-selectMaximalComponent` then `-renameSelectedComponent X`;
  if the rename succeeds where it failed before, the selection was the problem.

### F-03 — Settings silently never applied (`err:7155`), and the parse errors then abort the workflow
- **Symptom.** Two failures at once: (a) every swept flag behaved as if unset; (b) the
  workflow aborted at its next synchronisation point for no visible reason.
- **Cause.** `cmd` splits unquoted `;` `,` `=` into separate `.bat` arguments and Python's
  `subprocess` quotes only on whitespace, so `-set "key=value"` arrived as two arguments.
  RealityScan logged `Parsing setting key=value 'sfmMergeGeoreferencedComponents' failed
  [err:7155]` and `'false' failed`, and those parse failures landed in the errors marker.
- **Detected by.** Reading a per-cell `RealityScan.log` snapshot after an unexplained
  abort — **no flag cell before wave 1f had ever applied its flags.**
- **The same boundary bug in its other shape.** A **semicolon-joined component list**
  arrived as two `.bat` arguments and the merge cell failed reporting "found 1" — same
  cause, different delimiter, and it fails loudly instead of silently. Both shapes are B5.
  [VERIFIED: NA167 #15 / B5]
- **Mitigation.** Never pass delimited data as `.bat` arguments. Settings cross the
  process boundary as `key:value` and the workflow converts the colon; lists cross as
  files (`.complist`, `.imagelist`).
  [VERIFIED: NA167 #15 / B5, 2026-07-23; `CLAUDE.md` hard rule 8]
- **Detection test.**
  ```bat
  findstr /c:"err:7155" "%LOCALAPPDATA%\Temp\RealityScan.log"
  ```
  Run before the next instance boots. Any hit means the run executed on defaults.

### F-04 — `-align "<params>.xml"` is accepted and the argument is ignored
- **Symptom.** None. Latent. Alignment silently runs on instance defaults.
- **Cause.** `-align` takes **no parameters** in 2.x. Its row in the command table is
  literally `align | | Align images using the current settings.` — an empty
  required-parameter cell [OFFICIAL: appbasics/allcommands]. Commands that *do* take a
  params XML document it explicitly (`-exportXMP`, `-exportRegistration`, `-loadBundler`,
  `-simplify`, `-calculateTexture`, `-unwrap`, `-reprojectTexture`, `-exportModel`,
  `-importFlightLog`).
- **Blast radius when it bit.** All 28 tuned keys in `AlignmentParams.xml` were being
  discarded — camera-prior enablement and weights, `Ultra` detector sensitivity, the
  `Division` distortion model, feature caps. Zone alignments ran on stock settings.
  [VERIFIED: docs/code-review-2026-07 §6]
- **Detected by.** Code reading during a settings evaluation, cross-checked against
  `appbasics/allcommands` and Epic's online docs.
  [CONTRADICTED: pre-2.x repo scripts and lore passed a params file / observed: the
  argument is ignored] [VERIFIED: FINDINGS 2026-07-21]
- **Mitigation.** Parse the `sfm*`/`lis*` entries out of `AlignmentParams.xml` and apply
  each as a delegated `-set` before a plain `-align`. Delegated commands queue FIFO, so
  ordering is guaranteed and the `-set`s need no completion wait.
- **Detection test.** Grep the workflow for `-align "` with any following argument. Then
  confirm in the app log that each intended key appears in an
  `Executing command 'set' with parameter '<key>=<value>'` line.

### F-05 — `-addFolder` does not recurse; the align "succeeds" in 25 seconds on nothing
- **Symptom.** Align completes in ~25 s reporting success; every flight-log row then fails
  `err:18002`; registration is zero.
- **Cause.** `appIncSubdirs` is `bool` with **default `false`**
  [OFFICIAL: tutorials/setkeyvaluetable — "*relevant for: addFolder command* |
  `appIncSubdirs` | bool | false"], so a zone directory laid out as per-camera subfolders
  (`zone_1\cinema\`, `zone_1\port\`) contributes **`Added 0 layer images`**. The
  `addFolder` row itself says so: "To include subdirectories, use the command set with a
  key appIncSubdirs as follows: `-set "appIncSubdirs=true"`."
  [OFFICIAL: appbasics/allcommands]
- **Detected by.** A live H2023 run failing in 25 s; the `RealityScan.log` snapshot showed
  the literal `Added 0 layer images`.
- **Mitigation.** `-set "appIncSubdirs=true"` before **every** `-addFolder`, always,
  explicitly. An earlier NA167 run *did* recurse — because that workflow had already set
  the key. **The flag, not the build, is the variable.**
  [CONTRADICTED-internally, resolved as flag-dependent: NA167 §1 `-addFolder` claims "in
  our 2.2 build subfolders were included **without** setting the key (zone_13: wca/ +
  zeuss/ both imported)"; FINDINGS 2026-07-23 records the same build adding 0 images
  without it, and adds the nuance that the NA167 run had the key set by its workflow.
  The Help's documented default settles it.]
- **Detection test.**
  ```bat
  findstr /c:"Added" "%LOCALAPPDATA%\Temp\RealityScan.log"
  ```
  and compare the count against the on-disk `.jpg` count for the folder.

### F-06 — Calibration priors never loaded: `image.jpg.xmp` is ignored silently
- **Symptom.** Alignment behaves as if no calibration priors exist; no warning anywhere.
- **Cause.** RealityScan reads and writes `<stem>.xmp` **only**. A batcher bug wrote
  `image.jpg.xmp`, so **no historical run before 2026-07-22 ever loaded its priors.**
- **Detected by.** An arithmetic anomaly in sidecar counts after aligning zone_13 — 871
  "new" `.xmp` appeared in a folder that already held 904.
- **Mitigation.** Enforce the stem convention at write time; census sidecars by stem.
  [VERIFIED: NA167 #3 / B7, 2026-07-22]
- **Detection test.** `dir /b <images>\*.jpg.xmp` — any hit means those priors are inert.

### F-07 — Exports silently skip components below `setMinComponentSize`
- **Symptom.** A workflow reports success, exports a component, saves the project — and
  registers **0 of 32** images. Zero `.xmp` sidecars exist. A direct probe
  (`-load … -selectMaximalComponent -exportXMP -quit`) exits **0** and writes nothing.
- **Cause.** `-exportXMP` covers "camera metadata of components created in the last
  alignment" and "The components must fulfill the condition defined by the command
  `setMinComponentSize`", whose row reads "Specify the minimal component size for export
  when using the `exportLatestComponents` and `exportXMP` commands. **The default value is
  5.**" It is not scoped to the selected component. Components under the threshold are
  silently excluded from export. [OFFICIAL: appbasics/allcommands]
- **Detected by.** Disbelieving a 0% registration reading on imagery known to align.
- **Mitigation.** `-setMinComponentSize 1` **before** the export, and
  `-exportXMPForSelectedComponent` placed after component selection rather than
  immediately after `-align`.
- **Two thresholds that are easy to confuse — do not.**
  - `setMinComponentSize` (CLI, default **5**) gates `exportXMP` and
    `exportLatestComponents`. [OFFICIAL: appbasics/allcommands]
  - The Small Components panel's "Include smaller than" (GUI, default **3**) only decides
    which components are *grouped* under "Small components" in the 1Ds view and are
    therefore reachable by "Delete all small components". It has nothing to do with
    export. [OFFICIAL: appbasics/smallcomponents]
- **Deprecation — NOT a documented fact.** `-setMinComponentSize` emits a runtime warning
  "will be removed in the next release" into `RealityScan.log`; it is still required. The
  shipped Help contains **no** deprecation notice for it (or for anything else — the
  string "deprecat" does not occur anywhere in the 2.2 Help tree).
  [UNDOCUMENTED] [VERIFIED: NA167 #22 / B11, from a per-cell `RealityScan.log` snapshot]
- **The formal scope of the gate is narrower than the folklore.** `allcommands` attaches
  the `setMinComponentSize` condition to `exportXMP` and `exportLatestComponents` only —
  the `exportXMPForSelectedComponent` row carries no such clause.
  [OFFICIAL: appbasics/allcommands] Whether selection commands are also gated is
  [OPEN: fire `-setMinComponentSize 1` vs `5` on a scene holding a 3-camera component and
  see whether `-selectMaximalComponent` → peel can reach it; hardening cell U5].
- **Why this one is dangerous.** It is a **measurement** bug wearing the costume of a
  reconstruction failure. The obvious next move — tuning alignment parameters against a
  metric structurally incapable of reporting success — is the trap.
- **Detection test.** Re-run the export with `-setMinComponentSize 1` and compare sidecar
  counts. A jump proves the threshold was the filter.

### F-08 — A stray selection plus `-silent` makes a selection-driven export write nothing
- **Symptom.** `Exporting Registration completed in 0.057 seconds` (against 20.5 s for the
  real thing) and no files on disk.
- **Cause.** `-importFlightLog` leaves the matched images **actively selected**. Under
  `-silent` the "Export Selection" dialog is auto-answered, and the export scopes to that
  selection.
- **Detected by.** A two-order-of-magnitude duration anomaly in the app log.
- **Mitigation.** `-deselectAllImages` before every export. Mandatory.
  [VERIFIED: FINDINGS 2026-07-23] [UNDOCUMENTED: the Help does not warn that flight-log
  import leaves a selection]
- **Detection test.** Compare the export's logged duration against a known-good run of the
  same size; sub-second is the signature.

### F-09 — `-exportXMPForSelectedComponent` completes in a merge scene and writes nothing
- **Symptom.** The log says `Exporting Registration completed in 8.758 seconds`; a sweep
  of the entire drive finds **zero** `.xmp` written and zero sidecars carrying
  `xcr:Position`.
- **Cause.** The scene's images resolved through a **directory junction** — see F-57. The
  hypotheses "an imported component carries no images" and "restored calibration sidecars
  broke it" were both eliminated by measurement (the merge scene reported
  `Added 1407 images` / `1217` / `2241`).
- **Detected by.** A whole-volume `.xmp` mtime sweep after the harvest read `[]`.
- **Mitigation.** Never hand RealityScan an images root whose components' baked paths pass
  through a reparse point.
- **Detection test.** After any export, count files whose content contains `xcr:Position`
  and whose mtime is after the run start. Zero beside a non-empty component is an
  instrument failure, not a negative result.
  [VERIFIED: FINDINGS 2026-07-27]

### F-10 — `-selectMaximalComponent` / `-renameSelectedComponent` / `-deleteSelectedComponent` silently no-op on an empty scene
- **Symptom.** A peel loop runs past its terminal condition with no error.
- **Cause.** These commands no-op rather than fail when there is nothing to act on. There
  is **no CLI query for "how many components remain"** [UNDOCUMENTED], so the loop has no
  positive terminal signal.
- **Detected by.** Building the destructive identity-harvest loop and watching it not stop.
- **Mitigation.** Loop terminals must be **file-existence checks**, not error checks. The
  one exception that *is* usable: on an emptied scene the `-selectMaximalComponent` no-ops
  and the **following** `-renameSelectedComponent` fails `E_INVALIDARG 0x80070057
  (2147942487) "in 0 seconds"` — that tolerated failure **is** the exhaustion signal,
  filed as evidence in `expected_peelend_<inst>.txt`.
  [VERIFIED: FINDINGS 2026-07-23, 2026-07-24]
- **Detection test.** The literal artifact:
  ```
  An error occurred: process 21859 finished with result code 2147942487 in 0 seconds.
  ```

### F-11 — `-selectComponent <name>` resolves only where the component was renamed BEFORE the save
- **What is measured [VERIFIED].** In an **assembled** project it works:
  `-selectComponent "pd6_zone_1_c0"` and `"pd6_zone_1_c1"` both selected and modelled
  correctly, because those components were imported from `.rsalign` files renamed before
  export, so the manifest name, the file stem and the in-scene name are one string.
  Discovered by running the real `--auto_model` path and reading the per-component workflow
  logs. [VERIFIED: FINDINGS 2026-07-26]
- **What is NOT measured [INFERRED].** The corresponding worry for **zone** scenes — that
  manifest component names never match the in-scene names because the zone scene was saved
  *pre*-rename, so a name-based `-selectComponent` silently no-ops — is a design conclusion
  carried in `HANDOFF` (SHOULD-FIX: "cleanup_stale `selectComponent` silently no-ops") and
  `docs/MERGE_REWORK_RECOMMENDATIONS.md` §Q6. It has **not** been reproduced as an
  observation, and the 2026-07-26 finding explicitly scopes itself away from zone scenes.
  It is plausible because selection commands no-op rather than fail on nothing to act on
  (F-10). [INFERRED — what would settle it: `-selectComponent` a known manifest name in a
  zone scene, then `-renameSelectedComponent` and check for `0x80070057`.]
- **Mitigation in force regardless.** Select by name only where the rename provably
  preceded the save; correlate manifest ↔ scene by **image set**, never by name, before any
  deletion; use `-selectMaximalComponent` plus the successive-difference peel in zone
  scenes.
- **Detection test.** Follow the select with an operation that fails on an empty selection
  (e.g. `-renameSelectedComponent`) and watch for `0x80070057` / `err:5605`.

### F-12 — `-selectImage` regexp silently selects nothing [CONTRADICTED]
- **Docs claim.** `selectImage <imagePath|regexp> [set|union|sub|intersect|toggle]`
  [OFFICIAL: appbasics/allcommands].
- **Observed.** In this build **only literal full paths select anything.** Bare regexp,
  dot-star-wrapped regexp, glob, and regexp with an explicit `set` modifier all silently
  select **nothing**; a literal full path selects exactly its image.
- **Detected by.** Bisection probes U-SEL2 … U-SEL8, 2026-07-23.
- **Mitigation.** Selection composition is a per-image literal union loop at ~0.1–0.3 s
  per image — budget minutes for thousand-image sets.
  [VERIFIED: FINDINGS 2026-07-23]
- **Detection test.** `-selectImage "P231C.*"` then any selection-scoped command; a no-op
  confirms the dialect mismatch.
- **[OPEN]** Forum-mine the regexp dialect; a staff reply may explain the discrepancy.

### F-13 — `sfmMergeGeoreferencedComponents=true` never manifested headless [CONTRADICTED]
- **Docs claim.** "Merge georeferenced components — When multiple components are created
  and **each is georeferenced**, enabling this setting allows them to be merged **even
  without visual overlap**." Key `sfmMergeGeoreferencedComponents`, `bool`, default
  `false`. [OFFICIAL: appbasics/alignsettings; tutorials/setkeyvaluetable]
- **Observed.** No fusion in **any** mechanism × flag × path-form combination.
  D1 (`-mergeComponents`, flag on, zero-overlap pair) → no fuse, maximal = zone_6 alone
  (1,533). D2 (`-align`, georef true + rematch true) → no fuse.
- **Detected by.** NA167 wave-1f cells D1/D2, 2026-07-24.
- **Mitigation.** Do not build a merge ladder rung on this flag alone.
- **[SUPERSEDED-RISK]** Those cells fed the flag components georeferenced from
  **position-only priors at 10 m claimed accuracy** — the feature's documented premise
  ("each is georeferenced") was arguably never met, and RealityScan may distinguish
  prior-weighted from ground-control-locked georeferencing. **Do not treat D1/D2 as final.**
  [OPEN: re-test with priors-v2 components; queued, never run]
- **Detection test.** Census after the merge; instant completion + maximal == one input is
  the no-fuse signature (F-01).

### F-14 — A wrong UTM zone imports silently and misplaces everything
- **Symptom.** No error at any stage; georeferenced output lands in the wrong zone and
  possibly the wrong hemisphere.
- **Cause.** `FlightLogParams.xml` carried `+proj=utm +zone=4 +datum=WGS84` / EPSG:32604
  from an earlier project while the cruise was UTM 57S (EPSG:32757).
- **Detected by.** Reading the params file during a first-machine validation, not by any
  failure.
- **Mitigation.** Derive the zone **per cruise** from the flight log's filename tag
  (`flight_log_53N_UTM.txt` → EPSG:32653) and regenerate the params XML per run; never
  hand-edit the template's zone.
  [VERIFIED: NA167 #6; FINDINGS 2026-07-21/22]
- **Detection test.** Read `CoordinateSystemFlightLogType` out of the generated params and
  compare against the log's tag before the import runs.

### F-15 — A flight-log format GUID that is not installed drops columns silently
- **Symptom.** Orientation (YPR) and per-image accuracies simply do not exist in the
  solve; the import reports success.
- **Cause.** `FlightLogParams.xml` referenced `{B438A617-2434-5A24-C1B7-58980F28345A}` (the
  custom 13-column format) but the app's `flightlogs.xml` did not contain it, so **every
  import to 2026-07-25 silently dropped YPR and the accuracy columns.**
- **Detected by.** Auditing the two params files against the installed schema instead of
  assuming they matched.
- **Mitigation.** The format was merged into
  `C:\Program Files\Epic Games\RealityScan_2.2\flightlogs.xml` — a hand edit of an
  Epic-shipped schema file that **must be re-checked after any app update.** It is present
  in the install as of this writing. [VERIFIED: PRIORS_DISTORTION_TEST_PLAN audit item 1,
  2026-07-25; re-checked against the installed `flightlogs.xml`]
- **Trap inside the trap: `desc` is a LABEL, not the column list.** The entry reads

  ```xml
  <format id="{B438A617-2434-5A24-C1B7-58980F28345A}" descID="2345"
           desc="Name,X (East), Y (North), Altitude, XAccuracy, YAccuracy, AltitudeAccuracy, YawAccuracy, PitchAccuracy, RollAccuracy"
           reader="RealityScan.Import.CSVFlightLog">
  ```

  — ten names — while the `<parser>` children it actually parses with are **thirteen**,
  indices `0..12`: `Image`(0) `X`(1) `Y`(2) `Altitude`(3) `XAccuracy`(4) `YAccuracy`(5)
  `AltitudeAccuracy`(6) **`Yaw`(7) `Pitch`(8) `Roll`(9)** `YawAccuracy`(10)
  `PitchAccuracy`(11) `RollAccuracy`(12). **Never audit a flight-log format by its `desc`
  string; read the `<parser>` element.** [UNDOCUMENTED — established by reading the
  installed `flightlogs.xml` directly]
  (`reader="RealityScan.Import.CSVFlightLog"` is the *current* 2.2 identifier and is not a
  legacy-name leak — see `CLAUDE.md` naming rule.)
- **Detection test.**
  ```bat
  findstr /c:"B438A617" "C:\Program Files\Epic Games\RealityScan_2.2\flightlogs.xml"
  ```
- **[OPEN]** Whether the hand-merged format survives an app update.

### F-16 — `-update` silently re-orients or re-scales a weakly-constrained component
- **Symptom.** The delivered model sits ~45° off the true ground plane on a flat mud site,
  while the alignment that produced it is provably correct.
- **Cause (ranked, not established).** `-update` is a similarity/rigid fit to the scene's
  imported constraints applied **after** reconstruction: it can rotate or rescale a
  component but cannot stiffen or repair geometry. Candidate 1: `-update` rotated the bow
  to satisfy mis-converted orientation priors (Euler order / camera-mount convention are
  explicitly unverified; a 656-camera component spanning 9.3 m on a near-1D track is cheap
  to rotate, whereas the 3,738-camera / 17.9 m hull is far stiffer). Candidate 2: internal
  deformation of the bow (scale IQR width 0.444 vs the hull's 0.081).
- **Detected by.** Owner GUI inspection; then measurement of the align, which exonerated
  it — the bow's solved camera cloud matches nav to **0.8°** in best-fit-plane attitude.
- **Mitigation.** None in force. The blindness is load-bearing: assemble mode exports no
  poses, so the artifact the owner looked at cannot be measured.
  [INFERRED-ranked: FINDINGS 2026-07-26] [OPEN]
- **Detection test (cheapest, ~2 min).** Re-run the assembly `-update` with a
  **position-only** union log and re-measure the bow's attitude.

### F-17 — Registration looks perfect while metric scale collapses
- **Symptom, H2024.** `Success: True` on every zone, 82–93 % registration per zone,
  8,709 cameras — and `zone_3_c0` (1,192 cameras) at **0.236 of true scale**, IQR
  0.217–0.253 (a faithful 1:4.24 model). A camera-counting gate passes this dataset
  outright. Locally everything "looks good"; a uniform scale error is **invisible in the
  viewer.** [VERIFIED: FINDINGS 2026-07-26]
- **Symptom, H2023 (the first instance).** Fresh-run zone_1 `c0` (hull main, 3,026 cams)
  = **0.175** (IQR 0.168–0.186) and `c1` (714) = **0.220**, while `c2` (bow, 665) = 1.011
  and the other zones were 0.90–0.99. Two components holding 82 % of the delivered
  assembly's cameras were ~5.7× and ~4.5× smaller than reality.
  [VERIFIED: FINDINGS 2026-07-25]
- **Cause.** **Not established** for either instance, and not established for either
  repair. Ranked candidates for the H2023 repair (PD-6, which restored `c0` to 0.981):
  Brown3 → Division for the fisheye, the accuracy columns finally importing, and
  orientation priors being absent from PD-6's 7-column log. Three variables changed at
  once. [VERIFIED-as-unattributed: FINDINGS 2026-07-25, 2026-07-26] The H2024 repair (v2
  re-align: `zone_3_c0` 0.236 → 0.969, `zone_1_c2` 1.127 → 1.081, `zone_4_c2` 1.196 →
  0.919, all 14 components inside the 0.90–1.10 band) likewise changed several things at
  once — restored calibration sidecars, a fresh solve, code changes — and align
  fragmentation is separately on record as nondeterministic.
  [VERIFIED-as-unattributed: FINDINGS 2026-07-27]
- **What IS established: it is a pure similarity error, not drift.** The ratio is constant
  across nav-distance bins (H2023 hull: 0.197 / 0.181 / 0.185 / 0.179 / 0.174 / 0.174
  across 1–2, 2–4, 4–8, 8–16, 16–32, 32–64 m) and the H2024 IQR is narrow (0.217–0.253) —
  a whole-component scale collapse, not accumulating error or a fold.
  [VERIFIED: FINDINGS 2026-07-25, 2026-07-26]
- **Detected by.** A purpose-built metric-scale oracle (`testing/scale_oracle.py`,
  median solved-vs-nav pairwise-distance ratio per component, invariant to translation and
  rotation), validated against a known-good **and** a known-bad case before use. Three
  independent confirmations on the H2023 hull: scale-band invariance (above ⇒ similarity,
  not drift), implied ROV speed 0.01 m/s vs nav 0.08 m/s (bow: solve 0.22 vs nav
  0.21 m/s), and the rig itself as a ruler (fixed C–P baseline 1.11–1.21 m in metrically
  sound components, 0.22 m inside the shrunk hull — 0.20×, agreeing with the nav-derived
  0.175× **without using nav at all**).
- **Mitigation.** A scale gate on every component before it is modelled; for fused
  components, the correspondence-free quantile-ratio measurement (the stem oracle cannot
  join ordinal sidecars — F-49).
- **Related, decisive.** Over-tight position priors fragment solves and worsen scale while
  **registration barely moves** — which is precisely why a camera-counting oracle never
  caught it:

  | cell (665-image known-good component) | registered | components | scale |
  |---|---:|---:|---:|
  | `brown3_loose` (10/10/1) | 665/665 | **1** | 1.049 |
  | `brown3_tight` (1/1/0.1) | 662/665 | 2 | 0.886 |
  | `division_loose` | 656/665 | **1** | **0.989** |
  | `division_tight` | 659/665 | 3 | 0.826 |

  [VERIFIED: PRIORS_DISTORTION_TEST_PLAN "Bow 2×2", 2026-07-25; FINDINGS 2026-07-25/26/27]
- **Detection test.** Run the scale oracle per component and demand the 0.90–1.10 band. A
  count-based oracle alone cannot see this failure.

### F-79 — Autosave is ON by default and a headless `-load` DELETES an autosave by default
- **Symptom (potential; not hit here, because this repo pins the key).** An unpinned
  headless instance writes autosave data into the resource cache — the same disk that
  killed three model runs (F-71) — and a later `-load` of a project that has an
  `.autosave` beside it silently discards it.
- **Official behaviour.** [OFFICIAL: tutorials/setkeyvaluetable; appbasics/autosave]

  | Key | Values | Default |
  |---|---|---|
  | `appAutoSaveMode` | bool | **`true`** |
  | `appAutoSaveCliHandling` | `delete` \| `recover` \| `abort` \| `ask` | **`delete`** |

  Autosave writes **two** parts: the first into the resource cache
  (`%LOCALAPPDATA%\Temp\RealityScan`, or `RealityScan-1` / `-2` / `-3` for instances 2–4),
  the second into the project folder as `"project_name".autosave`. It fires 30 s after any
  change to a project (the interval "currently cannot be changed") and **immediately** on
  Align Images, Normal-Detail reconstruction, or any other high-computation feature. Epic
  explicitly recommends against `SystemTemp` as the cache location when autosave is on,
  because that folder then needs real storage. `appAutoSaveCliHandling` is what decides how
  the `load` command treats an existing autosave.
- **The same decision also exists as a `load` parameter — and this is where an identifier
  error hides.** The command row is
  `load | MyProject.rsproj | recoverAutosave|deleteAutosave` — "Use optional parameters to
  define the action if there is an autosaved file present for this project. Using
  `recoverAutosave` will open the autosaved project, while `deleteAutosave` will delete the
  autosaved project and load the original one." [OFFICIAL: appbasics/allcommands]
  So `deleteAutosave` is a **parameter of `load`**, not a command in its own right.
- **[INFERRED — a live defect in this repo's own boot script, found by reading the Help.]**
  `startRealityScan.bat`'s instance-reuse branch issues
  `%RealityScan% -delegateTo %RS_INSTANCE% -newScene -deleteAutosave`, i.e. it passes
  `-deleteAutosave` **as a standalone command**. Nothing in `appbasics/allcommands` defines
  it as one, so the expected outcome is the unknown/invalid-command class `0x82000060` —
  the same shape as B2's `-selectAllComponents` (§2.2). It has never surfaced, most likely
  because the reuse branch is rarely taken (the Python layer shuts pre-existing instances
  down instead — F-30) and because `-newScene` is delegated in the same call and does the
  useful part. **This is reasoning from the documentation, not an observation.**
  [OPEN: take the reuse branch once with a live instance and read
  `errors_<inst>.txt` for `2181038176`. Seconds. If confirmed, the correct forms are either
  `-load <proj> deleteAutosave` or the `appAutoSaveCliHandling` key.]
- **Why each value matters headless.** `delete` (the default) throws away recovery data
  without asking; `abort` fails the load loudly; `ask` would block an unattended run on a
  dialog; `recover` silently loads a *different scene state* than the `.rsproj` on disk —
  the last is the dangerous one for a pipeline that hashes or diffs projects.
  [INFERRED from the documented value semantics; none of the four has been exercised here.]
- **Mitigation in force.** `startRealityScan.bat` boots with `-set "appAutoSaveMode=false"`,
  so `20534 PROJECT_AUTOSAVE` should never appear in a marker file. Its appearance means
  the instance was not booted by this harness (F-30). The instance-reuse branch of the same
  script additionally fires `-delegateTo %RS_INSTANCE% -newScene -deleteAutosave`, so an
  attached instance at least starts from a clean scene with no autosave attached —
  but it does **not** re-pin `appAutoSaveMode` (F-30). [VERIFIED: `startRealityScan.bat`]
- **Detection test.** `findstr /c:"process 20534" "…\Errors\results_RS1.log"` — any hit is
  an unpinned instance. And `dir /b "<project dir>\*.autosave"` before a `-load`.

---

### F-85 — A published mesh sits N metres off vertically, and every check passes
- **Symptom.** The asset tiles to `COMPLETE`, lands at the right latitude and longitude,
  looks right in plan view, and is **wrong in depth by a fixed amount** — 72.7 m at NA168
  H2080, 70.4 m in the Solomon Sea, 27.1 m the *other* way in the Gulf of Mexico.
- **Cause.** The exported Z is a depth below the **sea surface** (`geoall.py:320` writes
  `-abs(kalman_depth)`), i.e. an orthometric height on the geoid. Cesium — and any
  ellipsoid-referenced consumer — reads it as height above the **WGS84 ellipsoid**. Every
  CRS in the chain is 2D, so nothing ever declares which. The gap is the geoid undulation N.
  [VERIFIED: FINDINGS 2026-08-31] See `06-…` §3.5.
- **Detected by.** Decoding `root.transform` from the published asset's own `tileset.json`
  and comparing the implied height against `-depth + N`. Nothing inside RealityScan can see
  it: the error is a rigid translation along the ellipsoid normal, so scale oracles, merge
  censuses and visual inspection are all blind to it.
- **Mitigation.** `h = H + N` with `H = -depth`, per site, before upload
  (`modules/cesium_placement.py`). Never a project-wide constant — N moves ~23.6 m along
  the Hawaiian chain alone.
- **Detection test.** Republish and read the tileset back; the residual must be under 1 m.
  *If the residual equals N, the correction was computed and then dropped.*

### F-86 — PROJ reports a successful vertical transform and applies ZERO correction
- **Symptom.** `Transformer.from_crs('EPSG:9518','EPSG:4979').transform(lon, lat, -1200)`
  returns `-1200.000` — unchanged — with no exception and no warning.
- **Cause.** The geoid grid (`us_nga_egm08_25.tif`, ~80 MB) is absent, so PROJ falls back to
  a *"ballpark vertical transformation, without ellipsoid height to vertical height
  correction"*, which is `+proj=noop` on the vertical. pyproj does not enable network grid
  access by default, so **the default posture on a fresh machine is the silent no-op.**
  [VERIFIED: FINDINGS 2026-08-31]
- **Detected by.** `Transformer.description` contains `ballpark`; or
  `TransformerGroup(...).unavailable_operations` is non-empty and names the missing grid.
- **Mitigation.** Build every vertical transformer with `allow_ballpark=False`, which raises
  `ProjError` instead. Enable `PROJ_NETWORK=ON` or install the grid with
  `projsync --file us_nga_egm08_25.tif`.
- **Detection test.** Transform a point at a known-non-zero undulation and assert the delta
  is non-zero — e.g. `(-157.08, 18.81)` must return roughly `+6.6 m`. *A clean `0.000` is
  the fallback's signature, not a correct answer.*

### F-87 — "Share to Cesium ion" produces an asset at the sea surface
- **Symptom.** A deep-water site appears on the globe at roughly ellipsoidal height 0.
  Measured on three pre-existing assets: **+2.1 m**, **+0.0 m**, **+23.7 m**.
- **Cause.** Not a bug — documented behaviour. "Model does not have to be georeferenced to
  be uploaded, since it is possible to upload a model and later define its approximate
  position" [OFFICIAL: tools/cesiumion]. The Share button ships no placement, so the asset
  lands wherever it is hand-placed. The exact `+0.0 m` on one asset is the signature of a
  height that was defaulted rather than carried.
- **Detected by.** `GET /v1/assets/<id>/endpoint` → the signed `tileset.json` →
  decode `root.transform`'s translation from ECEF. No human or globe required.
- **Mitigation.** Publish through the REST API with `options.position`. **ion is not the
  problem** — a probe asked for `-512.46 m` and read back `-512.46 m`, error `-0.000 m`
  (asset `5171554`). And note there is **no way to reposition after tiling**:
  `PATCH /v1/assets/{id}` accepts only name/description/attribution, so a wrong placement
  means re-uploading from source.
- **Detection test.** Any deep-water asset whose read-back height is within a few metres of
  zero was never georeferenced. [VERIFIED: FINDINGS 2026-08-31]

### F-88 — Publishing on the flight-log CRS alone relocates the asset by hundreds of kilometres
- **Symptom.** A mesh uploaded with a correct `EPSG:326xx` lands in open ocean, far from the
  dive.
- **Cause.** **Exported vertices are not necessarily in the declared CRS.** The NA168 H2080
  OBJ has a vertex bbox of X −47972…−47960, Y 396903…396915, Z −348956…−348926 while the
  site is really at E ~348355, N ~396318, −585 m — the export applied a DCC transformation
  preset (`settingsRotation="-90 -90 0"`, `exportCoordinateSystemType="2"`) and the frame is
  local. The `.rsInfo`'s `transformToModel` is what puts it back.
  [VERIFIED: FINDINGS 2026-08-31] See `06-…` §3.6.
- **Detected by.** Transform the vertices and test them against the CRS's own area of use;
  a wrong reading falls outside it. A dive's flight-log envelope is the tighter oracle.
- **Mitigation.** Read the frame from the sidecar and **derive** the correct reading of the
  16-value matrix rather than assuming one — it has no single obvious layout. Reject any
  reading whose composed 3×3 has a **negative determinant**: on this site easting (~348 355)
  and northing (~396 318) are each plausible as the other, so an East/North swap passes a
  CRS-bounds check, but a single axis swap is a reflection and no rigid transform between
  right-handed frames can produce one. Fail when zero, or more than one, reading survives.
- **Detection test.** `publish_cesium.py --dry-run` prints the derived lat/lon/depth in
  seconds. *If it does not match where the dive was, stop.*

## 4. F-18…F-26, F-82 — Instrument blindness: when the oracle is the thing that broke

A broken oracle looks **exactly** like a negative result. Every entry here cost hours or
days precisely because the failure was indistinguishable from a legitimate "nothing
happened".

### F-18 — The peel harvest measured nothing across two full merge runs (5 h 12 m)
- **Symptom.** Every merge attempt scored as a clean "nothing fused" no-op:
  `attribution: ambiguous, adopted_count: 0, camera_delta: null`, 18 attempts, all
  `identity_r<K>` directories created and empty.
- **Cause.** The junction, on the **write** side (F-57): RealityScan wrote no sidecars for
  a scene whose images resolve through a reparse point.
- **Detected by.** A baseline probe on real image paths through the *unchanged* workflow:
  `identity_r0` = 267 files = 116+94+57 exactly, attribution EXACT, `cluster_0: fused
  3 → 1` ACCEPTED. The chain was sound; only the paths were not.
- **Mitigation.** `assert_harvestable()` refuses to start when the images root has
  reparse-point children **at any depth** (`os.stat(..., follow_symlinks=False).st_reparse_tag`;
  `os.path.islink()` is False for Windows junctions on some Python builds). Plus an
  **empty-peel invariant**: an empty peel beside a non-empty export now aborts the run as
  an instrument failure instead of scoring as "nothing fused".
  [VERIFIED: FINDINGS 2026-07-27/28]
- **Detection test.** Before the run: walk the images root and assert no child has a
  reparse tag. After each export: assert the harvest moved a non-zero number of sidecars
  whenever the exported component is non-empty.

### F-19 — A census that could not see its subject published `0` for a sound result
- **Symptom.** `merge_report.json` showed `census_after_update: 0` next to
  `workflow_success: true` for a **4,496-camera** assembly.
- **Cause.** Assemble mode exports no XMPs by design, so `sanitize_and_census(images_root)`
  scanned pose sidecars that assembly never wrote.
- **Detected by.** Disbelieving a `0` next to a success flag.
- **Mitigation.** **A census that cannot see its subject must not be published under a
  name that claims it did.** The field was removed rather than "fixed".
  [VERIFIED-and-fixed: FINDINGS 2026-07-25]
- **Detection test.** For every published metric, name the artifact it reads and assert
  that artifact exists before reporting the number.

### F-20 — Exact-subset-sum attribution hides a real fusion
- **Symptom.** A genuine three-way fusion of `cluster_0` (zone_2 1,407 + zone_3 1,217 +
  zone_5 2,241 = 4,865) was reported as three unfused input components on **all three
  rungs**. RealityScan fused it every time: rung 1 peeled
  `[4860, 2241, 1407, 1217]`; rungs 2–3 peeled `[4851, 2241, 1407, 1217, 5]`.
  The three parents each attributed to themselves exactly, so the attempt recorded
  `adopted=3, delta=0` — a rejection that reads as a clean no-op.
- **Cause.** `fused` was inferred from the same arithmetic that fails on a lossy fusion:
  4,860 is not an exact subset sum of {2241, 1407, 1217}, so attribution returned
  `ambiguous`, no adopted entry had ≥2 inputs, and `fused` evaluated False. **A 5-camera
  loss out of 4,865 (0.10 %) is enough to hide a fusion entirely.** Contrast cluster_1,
  where both fusions were exact and both were accepted: peel `[1767, 1634, 69, 64]`
  (1634+69+64 = 1767) and `[1456, 576, 358, 345, 177]` (576+358+345+177 = 1456).
- **Two independent rejection terms, and they are easy to confuse.** In the later
  `merged5` run the same cluster's rung 1 peeled `[4854, 2241, 1407, 1217, 5]` — an
  11-camera loss **inside** the 12-camera budget, yet still rejected, because the stray
  5-camera fragment made attribution `ambiguous`. Rung 2 peeled
  `[4860, 2241, 1407, 1217]`, `exact`, 5-camera loss, **accepted**. A loss budget alone
  does not rescue an attribution failure. [VERIFIED: FINDINGS 2026-07-28]
- **Detected by.** Reading RealityScan's own `Finalizing 1 component` line out of a
  snapshot that had first been validated against a run-unique token (F-40).
- **Mitigation.** A signed **bounded-loss** tolerance — owner decision in force: 0.25 % of
  input cameras, default 0 (exact only), passed explicitly, warned at startup, recorded
  per attempt.
  [VERIFIED: FINDINGS 2026-07-28; HANDOFF 2026-07-29]
- **Also.** The **never-shrink invariant was dead code and never fired** — `adopted_cams ==
  input_cams` identically, so the clause could neither reject nor see a camera *gain*
  (exactly what `sfmForceComponentRematch` and `sfmImagesOverlap:High` exist to produce).
  Every earlier attribution of the hull rejection to never-shrink is wrong.
  [SUPERSEDED: FINDINGS 2026-07-27 adversarial review, 35 confirmed / 11 refuted, 9 agents]
- **Detection test.** For any rejected merge, compare the peel's maximal count against the
  input sum. A near-miss (within a fraction of a percent) is a hidden fusion, not a no-op.

### F-21 — A truncated peel is indistinguishable from a complete one
- **Symptom.** A partial harvest scores as a complete one.
- **Cause.** The reader breaks on the first missing or empty `identity_r<K>`, while the
  workflow **creates that directory before knowing a component remains**; both the lap cap
  and a missing export fall through to `exit /b 0`. `expected_peelend_<inst>.txt` is
  written and never read.
- **Detected by.** Adversarial review of the acceptance path, 2026-07-27.
- **Mitigation.** Treat the peel-terminal evidence file as a required artifact; assert the
  loop reached it. **Not fully closed.**
- **Detection test.** Assert `expected_peelend_<inst>.txt` exists and contains
  `2147942487` for every completed harvest.

### F-22 — The peel instrument is never asserted, so `+N` inflation can cancel `−N` loss
- **Symptom.** `confidence == "exact"`, `lost == 0`, **and a manifest naming basenames the
  component does not contain** — a false ACCEPT.
- **Cause.** Nothing sanitizes the image tree before an attempt, and `census_leftover` is
  recorded but never checked (and reads ~0 by construction, since the harvest already
  moved the sidecars out). The peel count is the sole evidence for membership, for
  `camera_count`, **and** for the invariant.
- **Detected by.** Adversarial review, 2026-07-27.
- **Mitigation.** Sanitize the tree before every attempt and check `census_leftover`.
  **Open as a defect.**
- **Detection test.** Count pose-bearing sidecars in the tree immediately before an
  attempt; anything non-zero is contamination.

### F-23 — The scale gate blocked exactly the components the ladder produced
- **Symptom (a), a bug.** Every merged component was refused a model regardless of its
  real scale: `final_components` never carried an `inputs` key, so the gate fell back to
  the synthetic fused key, found no scale record, and returned `unmeasured` → block.
  [VERIFIED-and-fixed: FINDINGS 2026-07-27]
- **Symptom (b), not a bug.** Even after the fix, all three fused components came back
  `UNMEASURED` while every unfused original passed — **by construction**: merge-scene
  `-exportXMPForSelectedComponent` writes ordinal sidecars with no image identity, so a
  stem-pairing oracle has nothing to join on. *The gate did its job — silence is not
  evidence — but it would have left the hull unmodelled.*
- **Mitigation.** Correspondence-free quantile-ratio scale measurement for fused
  components, validated both directions (known-good `zone_1_c1` 1.045 vs the stem oracle's
  1.023; the 0.236-shrunk hull measures 0.235).
  [VERIFIED: FINDINGS 2026-07-28]
- **Two traps inside that measurement.** (a) `xcr:Position` is an **element**
  (`<xcr:Position>x y z</xcr:Position>`) in current exports and an **attribute** in older
  ones — parse both. (b) A fused manifest's `images` is the unique-basename **union** while
  the scene holds one camera per input **occurrence** (880 cameras over 537 unique
  basenames), so the nav multiset must be the **concatenation** of the attributed input
  manifests' members.

### F-24 — The error channel itself was dead for about a day
- **Symptom.** Zero errors reported. Everything "succeeded".
- **Cause.** Malformed quoting in `ErrorWriterLaunch.vbs` produced a bad command line, so
  `ErrorWriter.bat` **never ran** and the errors-marker system was inert.
  Related earlier variant: an **unquoted** `appProcessExecCmd` path silently disabled all
  error detection when the checkout path contained spaces.
- **Detected by.** Adversarial review, not by a failure. Completed results stayed
  trustworthy only because they were independently validated by census/manifest data.
- **Mitigation.** Compose VBS strings with `Chr(34)`, never nested quote literals; escape
  the quotes around every path inside `appProcessExecCmd`.
- **Detection test — run this at the start of every session that depends on the hook.**
  The trigger fires for **every** completed process including heartbeats, so:
  > **An active `progress_<inst>.txt` with a `results_<inst>.log` that is NOT growing is
  > proof the hook is dead.**

  After any hook-chain change, verify `results_<inst>.log` grows during the next run. Two
  such self-tests are on record: the 2026-07-24 D7 probe (`results_RS1.log` grew after the
  CRLF normalisation) and the 2026-07-25 test during the H2023 model run, which logged
  **six completions between 22:17:02 and 22:17:12**.
  [VERIFIED: FINDINGS 2026-07-24 (D7 probe), 2026-07-25 (six-completion test)]

### F-25 — Completion inferred from results-log growth raced ahead of a running `-align`
- **Symptom.** Intermittent, non-deterministic failures; commands appearing to execute out
  of order; `-renameSelectedComponent` failing `No component selected [err:5605]`;
  sometimes the same script succeeding.
- **Cause.** `:run` treated growth of `results_<instance>.log` as proof the delegated
  command had finished. RealityScan 2.2 fires the same
  `appProcessAction=ExecuteProgram` trigger for **periodic internal heartbeat processes**
  — PIDs `41061`/`41063`/`41064` recur constantly at zero duration. The wait loop exited on
  the first heartbeat, typically within milliseconds.
- **Detected by.** Reading a real `results_*.log`:
  ```
  8:55:27.87 process 41063 finished with result code 0 in 0 seconds
  8:55:28.01 process 41061 finished with result code 0 in 0 seconds
  8:55:28.04 process 41064 finished with result code 0 in 0 seconds
  8:55:47.16 process 20598 finished with result code 2181038335 in 17 seconds
  ```
- **Mitigation.** The log-growth gate was removed entirely; `:run` is
  delegate → grace → `-waitCompleted` → grace → `-waitCompleted` → check errors marker.
- **The lesson.** The log-growth mechanism was *introduced by a previous adversarial
  review* as a fix for the pickup race. It was a reasonable inference from the
  documentation and it was wrong, because it depended on an undocumented property of a
  closed-source binary. **Code review cannot validate a contract with a third-party
  executable; only execution can.**
  [VERIFIED: docs/code-review-2026-07 §3; FINDINGS 2026-07-21]

### F-26 — The orchestrator reported exit 0 while modules refused or raised
- **Symptom.** Process exit 0 with real failures inside.
- **Causes, three distinct instances.**
  (a) `main.py` used a bare `return` when `validate_parameters()` was False, where the
  module-*failure* branch used `sys.exit(1)` — so a module that correctly **refused** to
  run reported success. Discovered when the batcher's new fingerprint guard refused and
  the process still exited 0.
  (b) A zone that **raised** vanished from the align tally — neither Succeeded nor Failed
  — so nine raising zones out of ten still produced exit 0.
  (c) `--scale_min` / `--scale_max` never reached the verdict: every band was baked at
  0.90/1.10 while the report **printed the operator's values.**
  A dependency shows the same shape: `ROVDataConcat`'s `main_kalman.py` prints
  `kalman_offset FAILED` / `Aborting` and returns 0.
- **Mitigation.** A raise records a failed zone; refusal is a failure; parameters are
  pinned end-to-end by a test.
  [VERIFIED-and-fixed: FINDINGS 2026-07-26, audit #5/#7 2026-07-28]
- **Detection test.** Inject a known failure into each reporting path and prove the
  detector fires **before** trusting it.

### F-82 — `Success: True` from a stage whose output is a DIRECTORY means nothing
- **Symptom.** Five H2024 zones were silently a **blend of two zonings** and were about to
  be aligned: **12,679 `.jpg` on disk against 9,834 reported** (zone_2 1,537 → 3,497,
  zone_5 2,623 → 3,497), i.e. ~2,845 stale images — with the module reporting
  `Success: True`.
- **Cause.** After a lever-arm correction changed every Port position, the re-batch reused
  the existing `batched_images_by_zone` folder on the premise that "zone recomputation is
  deterministic for the same log+parameters". That premise was true and **never verified**.
  The flight log had changed, so zone membership changed, and the copy routine skips files
  already present but has no way to remove a member the new zoning dropped.
- **Detected by.** Counting files per zone instead of trusting the summary.
- **Mitigation.** Make the premise mechanical, not a comment: `batch_inputs.json` records
  the flight log's sha256 plus the six zoning parameters, and reuse is **refused** with the
  remedy named when they differ. It fired in anger on the very next re-batch.
  [VERIFIED-and-fixed: FINDINGS 2026-07-26, 2026-07-28]
- **Generalisation worth carrying.** A reuse/resume path needs an **input fingerprint**,
  and any newly added parameter must be added to that fingerprint — a later review caught
  `batch_overlap_max_distance_m` missing from it, which would have silently reused zones
  built without a ceiling: the exact fail-open the guard exists to close.
  [VERIFIED-and-fixed: FINDINGS 2026-07-29]
- **Detection test.** After any stage whose deliverable is a directory, count the directory
  and compare against the stage's own reported total. Never accept the report alone.

---

## 5. F-27…F-34 — Delegation, wait and teardown races

### F-27 — Delegated commands are QUEUED; the delegating process returns at hand-over
- **What the Help says.** `-delegateTo <instanceName> <commandsDefinition>` delegates "a
  command or a sequence of commands to an already opened instance". It says nothing about
  when the delegating process returns, and nothing about queue ordering. Instead it shows
  the pattern — a `for` loop firing 20 `-delegateTo * -add`, then `-align`, `-save`,
  `-quit`. [OFFICIAL: tutorials/commandline_deleg]
- **Behaviour, established here.** The delegating process returns at **hand-over**, not at
  completion, and the queue is **FIFO**. [UNDOCUMENTED] [VERIFIED: every production run;
  `CLAUDE.md` "RealityScan 2.2 CLI facts"]
- **Consequence, useful.** Instant commands such as `-set` can be fired without a
  completion wait, because FIFO guarantees they are applied before the next queued
  operation. This is what makes the F-04 mitigation (parse `AlignmentParams.xml`, apply
  each key as a delegated `-set`, then a bare `-align`) safe without 28 waits.
- **Consequence, dangerous.** Any script that treats `-delegateTo` returning as completion
  is racing the instance.
- **`*` is a loaded gun.** "Instead of `instanceName`, you can use the star symbol (`*`).
  In this case, the command is delegated to the **first instance found**."
  [OFFICIAL: tutorials/commandline_deleg] With more than one instance alive that is
  nondeterministic targeting; every workflow here names the instance explicitly (F-31).
- **Documented ceiling.** "RealityScan allows you to open up to **4 instances** at once."
  [OFFICIAL: tutorials/commandline_deleg] Consistent with the four autosave cache paths
  (`RealityScan`, `RealityScan-1`, `-2`, `-3`) in F-79.

### F-28 — `-waitCompleted` returns PREMATURELY when it beats the instance to the queue [CONTRADICTED]
- **Docs claim.** `waitCompleted` is for "pausing the execution of other commands until the
  current process is finished… the following commands are executed **only once the process
  is finished** in the instance that the command is referring to."
  [OFFICIAL: tutorials/commandline_deleg] Read literally, one `-waitCompleted` after one
  `-delegateTo` is sufficient — which is exactly the pattern Epic's own example shows.
- **Observed.** A single `-waitCompleted` is **not** sufficient. It blocks until the
  *current* process finishes; if the instance has not yet dequeued the command you just
  delegated, there is no current process, so it returns immediately and the next command
  runs against an untouched scene. Symptom: commands appear to execute out of order, and
  `-renameSelectedComponent` fails `No component selected [err:5605]` — intermittently,
  which is what made it expensive to find.
- **How it was detected.** Non-deterministic smoke-test failures on the first real-machine
  run; the same script sometimes succeeded. [VERIFIED: docs/code-review-2026-07 §3;
  HANDOFF 2026-07-21]
- **Mitigation — the `:run` contract, reproduced literally in every workflow:**
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
  `ping -n N 127.0.0.1` is the grace delay — `timeout` needs a console and a headless
  parent has none. The grace makes the **first** wait land after pickup; the **second**
  wait is the one that is actually load-bearing.
  [VERIFIED: FINDINGS 2026-07-21; abort contract probed live 2026-07-24]
- **Detection test.** Probe `:run` with a deliberately non-empty errors marker (must exit
  1) and with an empty one (must continue). This was done; the contract is **live**.

### F-29 — `-getStatus` says "gone" seconds before the process releases its file handles
- **Symptom.** The next workflow's marker clearing fails with a sharing violation on
  `progress_<inst>.txt`.
- **Cause.** `-getStatus <instance>` returns errorlevel 0 iff the instance exists, and it
  flips to "gone" while the process is still tearing down and still holding handles.
- **Note on what `-getStatus` is documented to do.** The Help describes it as returning
  *progress*: "in the console of that specific instance, you will get the result in the
  form of the progress ID, progress percentage of the current process, elapsed time, and
  estimated time", e.g.
  `id:0x10001 progress:57.5% runtime:4.26sec endEstimation:3.40sec`, redirectable with
  `RealityScan.exe -getStatus * > D:\statusreport.txt`.
  [OFFICIAL: tutorials/commandline_deleg] **The errorlevel semantics this whole harness
  depends on are nowhere in the Help** — "errorlevel 0 iff the instance exists" is
  [UNDOCUMENTED], established here and used for boot readiness, shutdown verification and
  orphan detection. [VERIFIED: `startRealityScan.bat`, `realityscan_cli.py`]
- **Mitigation.** `RealityScanCLI._clear_markers` retries **per file for 60 s**, then
  raises with an explicit "most likely held by a running instance" message. Windows cannot
  delete a file another process holds open, so the retry — not a forced delete — is the
  correct shape.
  [VERIFIED: NA167 #14 / B3, 2026-07-23]
- **Detection test.** Time `-getStatus` reporting gone against the handle actually
  releasing; the gap is seconds.

### F-30 — A leftover instance from a crashed run attaches and mixes its results into yours
- **Symptom.** New work queues behind hours-old work; results from two runs interleave in
  the same marker files.
- **Cause.** `startRealityScan.bat` **reuses** a running instance when `-getStatus` returns
  errorlevel 0:
  ```bat
  %RealityScan% -getStatus %RS_INSTANCE% >nul 2>&1
  IF /I "%ERRORLEVEL%"=="0" (
      echo RealityScan instance %RS_INSTANCE% is already running - reusing it with a fresh scene
      %RealityScan% -delegateTo %RS_INSTANCE% -newScene -deleteAutosave
      goto :eof
  )
  ```
  Correct for a healthy instance, wrong for an orphan mid-operation with our hooks still
  armed. [VERIFIED: `startRealityScan.bat` lines 17–23]
- **Second, sharper consequence of the same branch [UNDOCUMENTED, established by reading
  the script].** The reuse path `goto :eof`s **without re-applying the boot settings** —
  no `appProcessActionTime`, no `appProcessAction=ExecuteProgram`, no `appProcessExecCmd`,
  no `appAutoSaveMode=false`, no `-writeProgress`, no `-silent`, no cache pinning. A reused
  instance inherits whatever settings it was started with. **If the instance you attach to
  was not booted by this harness, your run has no error channel and no progress stream, and
  every operation will "succeed".** This is the same class as F-24 (a dead hook), reached
  by a completely different route, and it is exactly why the Python layer shuts a
  pre-existing instance down rather than attaching to it.
- **Mitigation.** The Python layer shuts down any pre-existing instance **before** starting
  a workflow and refuses to continue if it does not respond to `-quit`. After the workflow
  it verifies shutdown via `-getStatus` before the next workflow may start.
  Bounds: `SHUTDOWN_VERIFY_TIMEOUT_SECONDS = 900`, `STATUS_CALL_TIMEOUT_SECONDS = 60`.
  A hung `-getStatus` is treated as *running* so callers stay conservative.
  [VERIFIED: `realityscan_cli.py`]
- **Note a live doc discrepancy.** `CLAUDE.md` documents the shutdown bound as 300 s while
  the code uses 900 s. **The code is authoritative for behaviour; the doc is stale.**
  [VERIFIED: realityscan_cli.py lines 190–191 vs CLAUDE.md hard rule 3]

### F-31 — Two orchestrators on one instance name; and `RS_INSTANCE` that was never an input
- **Symptom.** A probe session believed it was isolated on `RS2` and ran on `RS1` — the
  production instance. It could have `-quit` a live production run.
- **Cause.** `realityscan_cli.py` resolved the instance from constructor arg →
  `rs_settings.json` → default and only ever **wrote** `RS_INSTANCE` for the `.bat` layer.
  Every driver exporting `RS_INSTANCE` was decorative; it "worked" only because the
  settings file happened to say `RS1`. The same session also overwrote the `merge` section
  of `rs_settings.json` with probe paths.
- **Mitigation.** `RS_INSTANCE` now resolves **between** the constructor argument and the
  settings file. A per-instance lock file (`<instance>.lock`, `O_EXCL`, PID inside, stale
  detection via an exact `tasklist /FO CSV` PID-field comparison — a substring check would
  match PID 123 against 1234) prevents two orchestrators driving one instance name.
  [VERIFIED: FINDINGS 2026-07-28]
- **Detection test.** Before any probe, log the resolved instance name from the CLI object
  itself, not from the environment you think you set.

### F-32 — The delete race on model names: a short wait targeted the deliverable
- **Symptom.** The cleanup loop could delete the **final textured model**.
- **Cause.** `:try_delete_model` used a single short wait, so a no-op `-selectModel` on a
  missing intermediate returned before the instance picked it up — leaving the
  **previous** selection live, which at loop entry is the final textured model — and the
  `-deleteSelectedModel` that followed targeted it. Both error moves also laundered *all*
  codes, and 12 iterations overwrote the same evidence file.
- **Mitigation.** The same double-wait shape as every other subroutine, plus per-model
  evidence names (`expected_select_<inst>_<model>.txt`).
  [VERIFIED-and-fixed: audit #4, FINDINGS 2026-07-28]
- **Detection test.** After the cleanup loop, assert the kept model names still resolve
  (`-selectModel <tag>_Simplified_Textured`).

### F-33 — Concurrent instances and the marker namespace
- **Behaviour.** Marker files are namespaced per instance — `progress_<inst>.txt`,
  `errors_<inst>.txt`, `results_<inst>.log` — and cleared before every run, so parallel
  instances and previous runs can never be misread as the current run's state.
  [VERIFIED: `realityscan_cli.py`]
- **Not exercised.** **Multi-GPU parallel instances have never been run.** Single-instance
  GPU pinning via `RS_GPU_DEVICES` → `CUDA_VISIBLE_DEVICES` is exercised; two concurrent
  instances on different GPUs is untested.
  [OPEN: boot RS1 on GPU 0 and RS2 on GPU 1, align two small zones simultaneously, confirm
  marker-file isolation and no cache contention — NA167 loose end #2]
- **Known real cost of overlap.** Two merge drivers running at once produced a **spliced**
  `RealityScan.log` snapshot — see F-40. Note that channel C is *global and per-launch*,
  so it is the one shared resource the per-instance marker namespace does **not** protect.
- **One relevant official key, never exercised here.** `allowReadOnly`, `bool`, default
  `false`: "when set to true, it is possible to open the same project in 2 instances."
  [OFFICIAL: tutorials/setkeyvaluetable] With the default, a second instance opening the
  same `.rsproj` is not a supported configuration.
  [OPEN: what the second instance actually reports — never probed here.]

### F-34 — `ERROR: Failed to delegate command` is the signature of a **dead** instance
- **Symptom.** A `-delegateTo` fails outright instead of an operation being rejected.
- **Cause.** The instance is gone — typically after a crash (F-42).
- **Mitigation.** Distinguish the two in triage: a *rejected operation* writes a result
  code to the errors marker; a *dead instance* fails at delegation with nothing in the
  marker at all.
  [VERIFIED: FINDINGS 2026-07-26]
- **Detection test.** `RealityScan.exe -getStatus RS1` — non-zero errorlevel confirms the
  instance is gone. Then look for a `.dmp` in the `-silent` directory.

---

## 6. F-35…F-38, F-78 — `#timeout` stalls and other hangs

`#timeout` is an official `-writeProgress` **eventType** [OFFICIAL: tutorials/commandline_5]
with no documented meaning. Everything below is [UNDOCUMENTED] behaviour established here.

### F-35 — `#timeout` progress lines defeat naive stall detection
- **Symptom.** A monitor watching for "the progress line stopped changing" sees a **live**
  instance for six hours during a total hang.
- **Cause.** In the `#timeout` state the **elapsed counter keeps ticking** and `remaining`
  becomes garbage, so every emitted line differs from the last. Line-change activity
  detection counts a hang as activity.
- **Detected by.** The relocated-`-importComponent` hang (F-36) producing **zero** stall
  warnings across 6 h+.
- **Mitigation.** `_monitor_until_exit` refuses to treat a `#timeout`-suffixed line as
  activity:
  ```python
  if not line.rstrip().endswith('#timeout'):
      last_activity = time.monotonic()
      stall_warned = False
  ```
  [VERIFIED: NA167 #12 / B4, 2026-07-23]
- **Detection test.** `tail` the progress file: identical `algId`, frozen fraction,
  monotonically rising elapsed, `#timeout` suffix.

### F-36 — A **relocated** `.rsalign` hangs `-importComponent` forever
- **Symptom.** `#timeout` state, no error, no minidump, observed **6 h+**. In-place
  imports run at ~2 s per 0.7 GB, so the contrast is stark.
- **Cause.** Not established. Reproducible: importing a component `.rsalign` from anywhere
  other than its original export location hangs the instance permanently.
- **Mitigation.** `CLAUDE.md` hard rule 7: **import components ONLY from their original
  export location.** The `.complist` workflow input (a file of original absolute
  `.rsalign` paths) exists for exactly this. Merge-class operations are watchdogged at
  45 min while alignment stays unbounded.
  This is also why superseded merge trees holding original export locations are **kept**
  even when hundreds of GB could be reclaimed.
  [VERIFIED: NA167 #11 / B1, 2026-07-23]
- **Detection test.** `#timeout` on `algId 20594` (`IMPORT_COMPONENT`) from fraction 0.00.

### F-37 — `#timeout` does NOT always mean hung
- **Behaviour.** Heavy alignment phases legitimately freeze the progress fraction for
  20+ minutes: a **successful** 94.6 % run emitted **40** `#timeout` lines.
- **Pathological signature.** `#timeout` from fraction **0.00** with an ever-growing ETA.
- **Policy adopted.** Stall-**warn** on `#timeout` at 2 h (`STALL_WARNING_SECONDS =
  2*60*60` in `realityscan_cli.py`); **never auto-kill an align.** There is deliberately
  **no overall timeout** on any RealityScan operation — 10+ hour runs are normal; startup
  (120 s, `startRealityScan.bat`'s `startTries GEQ 120` loop) and shutdown are the only
  bounds. [VERIFIED: NA167 #28, 2026-07-24; `realityscan_cli.py`; `CLAUDE.md` hard rule 3]
- **If you ever do need to stop one, do it properly.** RealityScan documents
  `-pauseInstance <name>`, `-unpauseInstance <name>` and `-abortInstance <name>` for
  exactly this, "beneficial mainly when processing on servers or render farms"
  [OFFICIAL: tutorials/commandline_deleg]. None of the three is used by this repo and none
  has been exercised here. [OPEN: does `-abortInstance` leave the scene loadable, and does
  it produce a marker line? Cheap: abort a small align and read the marker + reload.]

### F-38 — Near-OOM is a third, indistinguishable cause of persistent `#timeout`
- **Symptom.** Identical to a hang in the progress feed.
- **Cause.** Near memory exhaustion RealityScan **slows to a crawl without crashing and
  without spilling to NVMe.**
- **Mitigation.** The monitor samples available physical RAM via `GlobalMemoryStatusEx`
  and warns once per workflow below `LOW_MEMORY_WARN_GB = 4.0`, and includes the RAM
  figure in the stall warning so a later `#timeout` can be attributed correctly.
  [VERIFIED: FINDINGS 2026-07-24]
- **Detection test.** Available RAM at the moment of the stall. Three causes must be
  separated before intervening: hung operation (F-36), legitimate heavy phase (F-37),
  memory pressure (F-38).

### F-78 — `-exportRegistration` with NO params XML blocks forever headless
- **Symptom.** The workflow never returns. No error, no marker, no progress.
- **Cause.** Not established. The strong suspicion is that the command falls back to its
  GUI dialog and waits for input that a headless instance can never supply — the same shape
  as the "Export Selection" dialog in F-08, except that dialog is auto-answered under
  `-silent` and this one is not. [INFERRED — what would settle it: run it under
  `RS_HEADLESS=0` and look at the screen.]
- **Mitigation.** **Never call `-exportRegistration` without a params file.** Save one from
  the GUI's registration-export dialog first and pass it explicitly. The XMP path
  (`-exportXMP <params.xml>` / `-exportXMPForSelectedComponent`) is what this pipeline uses
  instead. [VERIFIED: FINDINGS 2026-07-21, "RealityScan 2.2 CLI behavior"]
- **Fourth cause of an apparent hang.** Add this to the F-36 / F-37 / F-38 triage: a
  command waiting on a dialog. Distinguishing signature — it hangs from the **very
  beginning**, with no `#started` line for the operation at all, whereas F-36 emits
  `#started` and then `#timeout` from fraction 0.00.
  [INFERRED from the progress-stream semantics; not measured for this command.]

---

## 7. F-39…F-40 — `RealityScan.log` truncation and the snapshot protocol

### F-39 — The app log is TRUNCATED at every instance boot
- **Symptom.** A post-failure log capture contains almost nothing — a **91-byte** capture
  was recorded once.
- **Cause.** RealityScan truncates `%LOCALAPPDATA%\Temp\RealityScan.log` on every launch.
  Any snapshot taken after another instance has started loses the race.
- **Why it matters.** Channel C is the **only** place the reason text lives: `err:NNNN`,
  `[Internal error MSS_STR001]`, `Processing failed: Out of disk space..`,
  `Parsing setting … failed`, `Added 0 layer images`, `Finalizing N component`,
  `Trajectory imported successfully.`, and the `-setMinComponentSize` deprecation warning.
  With `0x8000FFFF` being generic, **no diagnosis of an ambiguous code is possible without
  a valid snapshot.**
- **Mitigation — the snapshot protocol.**
  1. Copy the log **inside the driver, immediately after the failing call returns**, before
     anything can boot another instance.
  2. Write it to the attempt's own directory (`<attempt>/rslog.txt`).
  3. Tolerate copy failure loudly — a snapshot that fails with `[Errno 28] No space left
     on device` is itself a finding (that is how the disk-full root cause became
     unmissable).
  ```python
  def snapshot_rs_log(dest: str, logger) -> None:
      src = os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Temp', 'RealityScan.log')
      try:
          shutil.copyfile(src, dest)
      except (OSError, shutil.Error) as exc:
          logger.warning('Could not snapshot RealityScan.log: %s', exc)
  ```
  [VERIFIED: NA167 #16 / B6, 2026-07-23]
- **The log can also be switched off entirely.** `appLog` is `bool`, **default `true`**;
  `operationLog` ("Operation log data") likewise. [OFFICIAL: tutorials/setkeyvaluetable]
  Neither is set by this repo, so channel C exists — but a skill inheriting someone else's
  instance settings must not assume it does. If `RealityScan.log` is absent rather than
  truncated, check `appLog` before concluding anything about the run.

### F-40 — A saved snapshot can be a DIFFERENT run's log, spliced mid-file
- **Symptom.** An H2023 attempt's `rslog.txt` — filed beside an unambiguously H2023
  complist and an H2023 identity harvest (3,737 / 3,026 / 714) — records
  `importComponent` of **eleven H2024 components**. The reciprocal case exists in the same
  run: another attempt's `rslog.txt` contains **no** `importComponent` line at all.
- **Cause.** Two merge drivers overlapped. `snapshot_rs_log` copies the **global,
  per-launch** log after the workflow returns; the second instance's launch truncated the
  shared file mid-run, so head and tail of one snapshot belong to different runs.
- **Detected by.** Reading an attempt directory whose artifacts disagreed with each other.
- **Mitigation — mandatory.** **Validate a snapshot against a run-unique token before
  reading any number out of it.** The token in use is the attempt's own complist paths:
  ```python
  imported = set(re.findall(r"importComponent' with parameter '([^']+)'", text))
  out['valid'] = {os.path.normcase(p) for p in expected_rsaligns} <= \
                 {os.path.normcase(p) for p in imported}
  out['counts'] = [int(n) for n in re.findall(r'Finalizing (\d+) component', text)]
  ```
  A count read from an unvalidated snapshot is worthless.
  [VERIFIED: FINDINGS 2026-07-27]
- **Consequence for an open question.** The plan "settle the 2 missing cameras by reading
  RealityScan's own registered count out of the attempt's `rslog.txt`" is **not trustworthy
  on those artifacts**. Re-importing `cluster_*_m_c0.rsalign` **from its original export
  location** (hard rule 7) and censusing it remains valid.

---

## 8. F-41…F-46 — Solver bugs, crashes and unstable re-solves

### F-41 — zone_14 fails standalone alignment DETERMINISTICALLY: internal error `MSS_STR001`
- **Symptom.** 4/4 reproduction at different elapsed times and different path forms
  (recorded cell timings: **54.6 min** for A1 on duplicated-path zone folders, **30.8 min**
  for A2 on shared-path imagelists). Marker code `0x8000FFFF`. The app log, from the
  fourth reproduction, which was the one captured in-driver:
  ```
  Feature detection completed in 9 seconds.
  Reconstruction failed after 1449.365 seconds.
  Processing failed: Unexpected program state.
    [Internal error MSS_STR001]
    [\0x13011\0x13010\0x10001\0x4999\0x10001]
  Reconstruction failed after 1452.842 seconds.
  ```
  (`testing/results/z14_forensic_rslog.txt` lines 1490–1496; the bracketed trace line is
  emitted twice, and the `quit` follows immediately.) Note the reproduction count rose as
  the cells ran and the sources were written at different moments —
  `NA167_SESSION_NOTES` B8 says 2/2, `testing/FINDINGS` #17 says 3/3, #27 is the fourth,
  and `MERGE_STRATEGY_REPORT` and `FINDINGS.md` both settle on **4/4**. Cite 4/4.
- **Cause.** A RealityScan solver bug. The **data is formally exonerated**: full-pixel
  decode of all 1,476 frames, zero MD5 duplicates, zero near-black/featureless frames by
  Laplacian, clean nav, normal motion profile, bracketed by healthy neighbours. The same
  images align **fine inside a larger scene** — the sequential 3-zone grow reached 94.6 %
  through them.
- **Detected by.** Repeated failure with escalating exoneration of every input hypothesis.
- **Mitigation — the production rule.** **When a zone fails alignment solo, GROW IT FROM AN
  ALIGNED NEIGHBOUR; do not retry solo.**
  [VERIFIED: NA167 #17/#18/#27 / B8]
- **Detection test.** `findstr /c:"MSS_STR001"` in a valid log snapshot. Failure at the
  reconstruction phase **after** feature detection completes is the shape.
- **[OPEN]** The internal reason is unknown and the bug has never been reported to Epic
  (HANDOFF P1 item 8).

### F-42 — Crash: minidump plus a dead instance
- **Symptom.** The workflow's next command cannot be delegated at all
  (`ERROR: Failed to delegate command: -renameSelectedModel "…_Manifold"`), which is the
  **signature of a dead instance rather than a rejected operation** (F-34).
- **Artifacts.** `RealityScanCrash-YYYYMMDD-HHMMSS.dmp` (+ a binary `.dmp.metadata`
  companion) in the `-silent` directory — in this repo,
  `modules\realityscan_interface\RS_CLI\Errors\`. Epic documents exit code `3` for "crash
  with minidump" [OFFICIAL: tutorials/commandline_5], but **that code belongs to the
  crashing process**, which here is the delegated headless instance, not the `.bat` the
  orchestrator launched. What the orchestrator actually sees is `ERROR: Failed to delegate
  command` → `exit /b 1`, plus a `.dmp` on disk and nothing in the errors marker.
  [VERIFIED: FINDINGS 2026-07-26]
- **Real instance.** `RealityScanCrash-20260726-054742.dmp`, written during step **[5/8]**
  (`-closeHoles` / `-cleanModel`) on the 3,738-camera hull — the largest mesh in the
  deliverable. The `merge_zones` driver recorded `success: false` for that component and
  carried on; bow and torpedo were unaffected.
- **Attribution warning — a three-step supersession chain for one failure.**
  1. "Contention from a concurrent CLAHE run + zone copy" — **refuted by file mtimes**
     (CLAHE spanned 3 minutes, the copy 78 seconds; neither was running at the crash).
  2. "Intrinsic memory exhaustion at this mesh size" — **refuted by the retry's exit code**
     (`ERROR_DISK_FULL`).
  3. "The project disk filled" — **refuted by the instance log naming the cache.**
  Each superseding step was cheaper than the last and none required a re-run.
  [SUPERSEDED ×3: FINDINGS 2026-07-26] See F-71.
- **Mitigation.** `:fail` quits **without saving**, so a failed model run leaves the
  assembly intact (verified: parses clean, no zero-byte files, previously-built models
  present). The driver records `success: false` for that component and carries on.
- **Detection test.** `dir "<silent dir>\*.dmp"` sorted by time, cross-referenced with the
  workflow log's last successful step.

### F-43 — Incremental growth is state-sensitive and can DEGRADE existing structure
- **Symptom.** A two-zone grow (z6→z14) fragmented to an 870-camera maximal — **smaller
  than z6's solo 1,533** — while a three-zone grow through the same stages held 3,906.
- **Cause.** Growth outcomes are not order- or subset-invariant.
- **Mitigation.** **Verify camera counts after every grow step**; checkpoint before every
  mutating attempt. Checkpoint = a plain **file copy of the `.rsproj` bundle**; restore =
  copy back. Battle-tested in anger (a growth run killed mid-pass was fully recovered).
  **Component reimport is NOT a valid checkpoint** — it drops non-member images.
  [VERIFIED: NA167 #29; FINDINGS 2026-07-23/24]

### F-44 — Pose locking is unusable as a growth anchor
- **Symptom.** `-editInputSelection inpPose=3` (Exact/Locked) takes effect, and `-align`
  then **refuses**: *"prior set to 'Exact' mode must be all aligned in a single run.
  Incremental adding is not supported."*
- **Mitigation.** Checkpoint/rollback remains the primary never-shrink mechanism.
  [VERIFIED: FINDINGS cell U18 FAIL, 2026-07-23]

### F-45 — A free re-align is never pose-stable and can shrink components
- **Behaviour.** `-align` with components already in the scene is align/**update**: it adds
  new images to existing components and can fuse components — and it can also **drop
  marginal cameras** (H2023 3,860 → 3,855; zone_1 c7's pass lost 51 previously-registered
  images) and **move every camera** (all 118 of a solved smoke scene).
- **Consequence.** A 1–2 camera deficit after any re-solve is normal, which is exactly why
  a small merge deficit cannot be attributed to the solver without independent evidence
  (F-46).
  [VERIFIED: FINDINGS 2026-07-23/24, cell U18 bonus]

### F-46 — The 2–3 "missing cameras" after a fusion are still not distinguishable from a harvest artifact
- **For real loss.** The deficit **varies by mechanism** (−2 merge, −1/−1 align) where
  deterministic bookkeeping would give a constant deficit, and F-45 establishes that
  re-solves drop marginal cameras normally.
- **Against.** The peel harvest is a single PowerShell
  `Get-ChildItem -Recurse | Move-Item -Force` line; **Windows PowerShell 5.1 exits 0 on
  non-terminating pipeline errors**, so `if errorlevel 1` cannot see a partial move and two
  locked sidecars are a silent −2. A flat `-Force` move also collapses same-stem **ordinal**
  sidecars arriving from different folders. The ICP follow-up matched identity by nearest
  position over those same peel poses, so it is **not independent evidence**.
- **Also weaker than recorded.** The peel of the 2-input merge yielded **three** components
  (3,737 / 3,026 / 714) — `-mergeComponents` **retains its inputs** alongside the fused one
  — so 3,737 is the fused component's own size measured while both parents were still in
  the scene.
  [VERIFIED: FINDINGS 2026-07-25, 2026-07-27]
- **[OPEN] — settleable from artifacts already on disk.** Re-import
  `cluster_*_m_c0.rsalign` **from its original export location** into a spare instance and
  census it: 3,740 means accounting artifact, 3,738 means real loss. Do **not** use the
  attempt's `rslog.txt` for this (F-40).

---

## 9. F-47…F-52, F-83…F-84 — XMP / sidecar bug classes

### F-47 — `image.jpg.xmp` is ignored silently
See **F-06**. RealityScan reads and writes `<stem>.xmp` only.

### F-48 — Ordinal sidecars destroy per-camera identity
- **Behaviour.** **The COMMAND determines the naming, not the scene**: `-exportXMP` writes
  **stem-named** sidecars; `-exportXMPForSelectedComponent` writes **ordinal** sidecars
  (`00000.xmp`, `00001.xmp`, …) in every observed context. Four consistent datapoints.
  [SUPERSEDED: an earlier session-based hypothesis — "stems require the live aligning
  session" — was WRONG] [VERIFIED: FINDINGS 2026-07-23, B10 final form]
- **Consequences.**
  - Count remains a valid registration census; **per-camera identity is only available from
    the original aligning scene.**
  - Per-component membership must be derived by **successive difference** of `-exportXMP`
    stem harvests as components are deleted.
  - Any stem-pairing oracle (e.g. the scale gate) has nothing to join on in a merge scene
    (F-23).
  - Ordinal sidecars are **inert as priors** (no image has an ordinal stem);
    `camera_registry.sanitize_and_census` deletes them quietly.
- **Directory semantics differ by scene type.** **ALIGN-scene `identity_r<K>` directories
  are CUMULATIVE** (rK = laps K..end); **MERGE-scene rK is component K alone.** Component
  K's own sidecars in an align scene are the stem difference rK minus rK+1.
  [VERIFIED: FINDINGS 2026-07-28]

### F-84 — The per-camera `Camera:DistortionModel` sidecar hint is SILENTLY OVERRIDDEN by the global key
- **Symptom.** A mixed-optics rig writes `division` for its fisheye and `brown3` for its
  rectilinear cameras in the calibration sidecars, and **every solved camera comes back
  with the same model.**
- **Cause.** `sfmDistortionModel` is **global and all-or-nothing**. Under the PD-6 config
  the cinema sidecars declared `brown3`, yet all **2,558** cinema pose XMPs came back
  `xcr:DistortionModel="division"` — the same model as the 2,492 port records.
- **Detected by.** Aggregating solved intrinsics out of an identity harvest, not by any
  error. The earlier reading — "the fisheye is being solved as brown3 *despite* its
  division sidecar" — had the polarity reversed but the same root: the global key wins in
  whichever direction it is set.
  [VERIFIED: FINDINGS 2026-07-26; supersedes PRIORS_DISTORTION_TEST_PLAN audit item 3's
  hypothesis by settling it]
- **What the sidecar grouping DOES still do.** Calibration/distortion **groups** work: with
  both cameras given the same 16.0 mm prior, the solve separated them by 5.6 % (cinema
  focal 35 mm-eq **16.374**, IQR 16.302–16.476, division k1 **−0.0378**; port **15.499**,
  IQR 15.435–15.574, k1 **−0.3875**) with IQRs of about ±0.5 %. Since the JPGs are
  EXIF-identical, the XMP groups are the only mechanism that could have separated them.
  So: **one distortion model per project, coefficients per group.**
  [VERIFIED: FINDINGS 2026-07-26]
- **Mitigation.** Choose the global model for the camera that needs it most and verify the
  other tolerates it (here the rectilinear camera tolerated `division` fine: k1 −0.038,
  tight IQR, hull scale 0.982). Supplying *measured* coefficients remains per-group and
  therefore still useful.
- **Detection test.** Parse `xcr:DistortionModel` out of the exported pose XMPs and assert
  it matches what each camera's calibration sidecar asked for. A single distinct value
  across a mixed-optics rig proves the override.

### F-49 — `xcr:Position` has two on-disk forms
- **Behaviour.** Current exports write an **element**
  (`<xcr:Position>x y z</xcr:Position>`); older ones write an **attribute**. Both forms
  must be parsed or a whole harvest silently reads as unregistered.
  [VERIFIED: FINDINGS 2026-07-28]
- **Related.** Exported pose XMPs carry `xcr:CalibrationGroup="-1"` /
  `DistortionGroup="-1"` **alongside** `Camera:CalibrationGroup="3"` — the `-1` is an
  export artifact, not a lost grouping. [UNDOCUMENTED]

### F-50 — Cross-run prior contamination: exported poses become exact-pose priors
- **Symptom.** A "clean" re-run silently inherits the previous run's solution.
- **Cause.** Adding images auto-imports `<stem>.xmp` sidecars found next to them, and
  pose-bearing sidecars silently become **exact-pose priors**. Exports land beside the
  images.
- **Mitigation.** Sanitize the tree to calibration-only content after every census, before
  any run that must be independent.
  [VERIFIED: NA167 B7, 2026-07-22]
- **Detection test.** Count sidecars containing `xcr:Position` under the images root
  immediately before a run; non-zero means contamination.

### F-51 — The identity harvest permanently STRIPPED calibration sidecars
- **Symptom.** A re-align of an already-harvested zone silently runs with a partially
  ungrouped camera set.
- **Cause.** The harvest PowerShell **moves** every pose-bearing `.xmp` into
  `identity_r<K>`, and the last-peeled component's sidecars are never re-exported. Measured
  on fresh zone_1: **796 of 4,540 images (17.5 %) had no sidecar** — the entire bow
  component (665/665), 123 of c0, 8 unregistered.
- **Blast radius.** **PD-4 and PD-4a both re-aligned zone_1 in this state, so their
  "collapse" results (669 and 782 of 4,540) are CONFOUNDED.**
- **Mitigation.** `camera_registry.ensure_calibration_sidecars()`.
  [VERIFIED: FINDINGS 2026-07-25]
- **Detection test.** Compare the sidecar count against the image count per zone before
  every align.

### F-52 — Prior CONTENT is not automatically beneficial
- **Observation.** An A/B on zone_13 with priors absent (because of F-06) vs promoted
  measured **96.3 % → 89.6 %** on Zeuss.
- **Probable cause.** The old writer grouped `cammid`+`camupper`+`camlower` together at
  "12 mm fisheye" when `camlower` is actually rectilinear 17 mm.
- **Mitigation.** Prior generation became opt-in (`batch_xmp_priors`, default off);
  corrected per-camera values must be validated **per rig**.
  [VERIFIED: NA167 #4 / B7]
  [SUPERSEDED-in-scope: with corrected per-camera values the calculus reverses — calibration
  sidecars cut zone_1 fragmentation from 9 components to 3 at equal-or-better registration.
  Validate per rig before trusting either direction.]

### F-83 — Re-importing a previously fused component makes the next harvest read ZERO
- **Symptom.** `identity_r0: 0` for `cluster_1` attempts 2–4, whose merge scenes contained
  `cluster_1_m_c0.rsalign` exported by attempt 1. Attempts 1 and 5 — neither of which
  contained a previously fused export — harvested normally.
- **Cause.** Not established. Consistent with the B10 rule that identity is only
  harvestable from the original aligning scene (F-48), but that rule does not obviously
  predict *zero* rather than *ordinal*.
- **Detected by.** Reading the per-attempt harvest counts across one run.
- **Mitigation.** None specific. The empty-peel invariant (F-18) now aborts rather than
  scoring such an attempt as "nothing fused", so it cannot masquerade as a result.
- **[OPEN] — do not build on this.** Did not recur in the later `merged5` run.
  Cheapest probe: import two small components, merge, export the fused `.rsalign`, then in
  a fresh scene import that fused file alongside a third component, merge, and check
  whether any `xcr:Position`-bearing sidecar appears. ~10 min.
  [OPEN: FINDINGS 2026-07-28; HANDOFF loose end #5]

---

## 10. F-53…F-56, F-80…F-81 — Component and model identity collisions, and workflow guards

This class is the quietest and the most dangerous: counts stay correct, names collide, and
a downstream operation silently targets the wrong object.

### F-53 — `-importComponent X.rsalign` names the in-scene component `X` — duplicate names in one assembly
- **Symptom.** Two components in one assembly both called `cluster_1_m_c0`.
- **Cause.** The in-scene name is the **file stem**, and `peel_index` restarted each
  attempt, so two accepted fusions in one cluster both exported the same stem. Camera
  counts were correct; the defect was purely identity.
- **Consequence.** A per-component model run targets whichever component RealityScan
  resolves first — **silently**.
- **Mitigation.** Export naming `<tag>_a<attempt>_c<K>`.
  [VERIFIED-and-fixed: FINDINGS 2026-07-28; HANDOFF 2026-07-29]
- **Detection test.** Assert component-name uniqueness across the assembly's manifests
  before any per-component operation.

### F-54 — `GenerateModel.bat` used FIXED model names while running once per component against ONE shared project
- **Symptom.** None at run time — clean exit status.
- **Cause.** From the second component onward the scene held duplicate model names, and
  step [8/8] resolves operands by name: the bow's `-reprojectTexture` could map the
  **hull's** texture onto the bow's mesh. The cleanup loop could also delete another
  component's models.
- **Detected by.** **Reading the workflow before the second component started** — not by a
  failure.
- **Mitigation.** All 19 references namespaced by `%model_tag%`.
  [VERIFIED-and-fixed: FINDINGS 2026-07-25]

### F-55 — Model names silently leave the project mid-recipe
- **Symptom.** `-selectModel <comp>_HighPoly_Raw` → `err:5601 'not found'`; and
  `-selectModel <tag>_HighPoly` returns the whitelisted empty-selection code
  `2147942487` in **every** component's cleanup loop, six for six.
- **Cause.** Step [2/8] **renames** the selected model to `_Cleanup1` when the marginal
  filter fires, so the raw name leaves the project. The models that actually persist per
  component are `_HighPoly_Textured`, `_Simplified_Textured`, plus **one** default-named
  residual (`Model 1`) in the whole project — not one per component.
- **Consequence.** The docstring's "models kept" list was wrong from 2026-07-23 to
  2026-07-29, and the dense PLY export falls back to `_HighPoly_Textured`, the densest
  model guaranteed to exist.
- **[CONTRADICTED, inside this repo's own record — do not smooth this over.]**
  `FINDINGS 2026-07-28` states "the H2023 PD6 deliverable confirms it empirically: its
  cleanup ran and all three kept models (`_HighPoly_Raw`, `_HighPoly_Textured`,
  `_Simplified_Textured`) survived", and `HANDOFF 2026-07-29`'s deliverable table repeats
  "Three kept models each: `_HighPoly_Raw`, `_HighPoly_Textured`, `_Simplified_Textured`".
  The same day's **direct export probe** on the real assembly got
  `-selectModel cluster_4_a1_c0_HighPoly_Raw` → `err:5601 'not found'`. The probe is the
  stronger evidence (it queried the project; the other two are inherited claims), so the
  raw model should be assumed **absent** — but the discrepancy is unresolved and could
  mean the two datasets differ. [OPEN: enumerate the model list per component in the GUI
  or with a probe, and settle whether `_HighPoly_Raw` survives on *any* component.]
- **Mitigation.** `-duplicateSelectedModel` after step [1/8] would preserve
  `_HighPoly_Raw`. The command exists: "`duplicateSelectedModel` | | Duplicate the
  selected model (including textures)." [OFFICIAL: appbasics/allcommands]
  [INFERRED: not tested in this recipe.]
  [VERIFIED: FINDINGS 2026-07-29 export probe]
- **Not a prefix hazard.** `-selectModel` matches on the **exact** name — "`selectModel`
  modelName | Select a model with the specified name (modelName)"
  [OFFICIAL: appbasics/allcommands] — so deleting `<tag>_HighPoly` cannot collaterally
  take `<tag>_HighPoly_Textured`. Checked explicitly because the cleanup loop depends on
  it. [VERIFIED: FINDINGS 2026-07-28]
- **[OPEN]** The `_HighPoly` select-miss cause is not investigated; the
  `GenerateModel` error-whitelist redesign is queued behind it. Six for six across every
  modelled component. [OPEN: HANDOFF 2026-07-29 loose end #3]

### F-56 — Component numbering is unstable across runs
- **Behaviour.** New components are named `Component N` with **unstable N** (observed 5, 9,
  0, 3, 4 across two zones). Alignment **fragmentation** is strongly nondeterministic while
  total **registration** is not: zone_1 (4,540 images, identical settings, sidecars,
  inputs) aligned to 2 components / 4,391 cameras in one run and 9 components / 4,392 in
  another.
- **Mitigation.** **Component structure cannot be relied on across runs — only
  manifest-tracked image sets can.** Rename immediately after selection; key everything on
  image basenames.
  [VERIFIED: FINDINGS 2026-07-24]
- **[OPEN]** Whether align **updates** an existing component in place, keeping its name,
  when it only grows (hardening cell U6, never run).

### F-80 — A workflow that disables images and never re-enables them SAVES a crippled scene
- **Symptom.** None at run time. The saved `.rsproj` silently holds most of its imagery
  disabled for alignment.
- **Cause.** `GrowZone.bat` component mode disables all images, enables the target subset,
  aligns — and falls through to `:save_quit` with **no re-enable**. Each of the eight
  zone_1 component passes therefore saved a crippled scene.
- **Why it did not reach the deliverable.** Pure luck of policy: every component pass was
  **rejected and rolled back** by the driver, so the checkpoint restore undid the save each
  time. Timestamp evidence: `zone_1.rsproj` mtime `03:31:57` equals the `merge` pass's
  save, while all eight component passes ran 03:31→03:54.
  **A single ACCEPTED component pass would have persisted it.**
- **Detected by.** Reading the workflow while reconstructing which artifact was
  authoritative — not by any failure. [VERIFIED-as-defect: FINDINGS 2026-07-24]
- **Mitigation.** The defect stands as a queued fix, not a closed one. Operationally:
  checkpoint/rollback is what contained it, which is the general argument for F-43's
  "checkpoint before every mutating attempt".
- **Detection test.** After any workflow that manipulates `-editInputSelection
  "inpEnabled=false"`, re-open the saved scene and assert the enabled-image count equals
  the scene's image count before trusting the save.

### F-81 — A guard written for one mode applied to all of them: `assemble` refused 1 component
- **Symptom.** `ERROR: need at least 2 components, found 1`, and `merge_zones.py` exited 1
  **after a completely successful ladder**. The ladder had fused 3 → 1, which is the
  correct outcome; the assembly stage then refused to build the deliverable from it.
- **Cause.** `MergeZoneComponents.bat`'s `component_count LSS 2` validation was applied to
  every mode, including `assemble`, where a single component is a perfectly valid input
  (import, georeference, save).
- **Latency.** Invisible on multi-cluster runs — N clusters yield ≥ N final components, so
  two clusters can never trip it. It only bites a fully-converged single-feature dive,
  which is the *best* possible outcome.
- **Mitigation.** `assemble` now requires ≥ 1; every other mode still requires ≥ 2.
  Verified three ways via `cmd /c` with nothing else running: 1 + `assemble` proceeds past
  validation and boots; 1 + `merge` exits 1 with "need at least 2 components to merge,
  found 1"; 0 + `assemble` exits 1. Both reject paths return **1, not 0**, because they use
  a top-level `goto :argfail` rather than an `exit /b` inside a parenthesised block (F-63).
  File re-verified pure CRLF (**342 CRLF, 0 bare LF**).
  [VERIFIED-and-fixed: FINDINGS 2026-07-28]
- **Detection test.** Exercise every mode of a shared workflow at its **boundary** input
  count, not just at typical counts.

---

## 11. F-57…F-61 — Filesystem traps that break RealityScan specifically

### F-57 — Directory junctions (reparse points): RealityScan writes NO XMP sidecars, and PowerShell hides the children
- **This entry cost two full production runs (5 h 12 m of correct GPU work, discarded).**
- **Symptom A (write side).** RealityScan reports success and writes **zero** `.xmp` when a
  scene's images resolve through a reparse point. `-exportXMPForSelectedComponent` logs
  `Exporting Registration completed in 8.758 seconds` and produces nothing (F-09).
- **Symptom B (read side).** Windows PowerShell 5.1 `Get-ChildItem -Recurse` **does not
  descend into junction CHILDREN**, at any depth. Measured on the same tree:
  **0** `.xmp` through the junction-holding parent vs **9,835** through the real path.
- **Why only the merge harvest died.** `AlignZone.bat` is handed the **zone folder itself**
  — the junction IS the enumeration root, and PowerShell resolves a junction it is pointed
  at directly — so every align manifest was complete. `MergeZoneComponents.bat` is handed
  the **PARENT** of the zone folders, so the junctions are children and are skipped. *Same
  tree, same tool, opposite outcome depending on where enumeration starts.* Python's
  `os.walk` crosses junctions in **both** directions, which is why the Python-side sidecar
  coverage check reported everything fine and gave no warning.
- **The false lead worth keeping.** "The empty peel was caused by junction enumeration (the
  READ side)" is **SUPERSEDED**: a re-run with the real image tree produced the identical
  `peel=[]` on all 18 attempts. The re-run cleared only the read side — the components were
  still *exported* from junction paths, so the scene's images still resolved through the
  junction and the **write** side was never tested. 157 further minutes were spent on a
  confirmed mechanism that was never linked to the symptom.
- **Root cause, resolved by probe.** Four baseline components on **real** image paths, same
  workflow, same harvest root, same 9,835 restored sidecars → `identity_r0` = 267 files
  (= 116+94+57 exactly), attribution EXACT, `fused 3 → 1` ACCEPTED. The only difference
  from the failed runs was that the failing components' `.rsalign` files had junction paths
  baked into them.
- **Choosing a mechanism instead.** The copies / hardlinks / junctions comparison — what
  each one does to camera identity, sidecar writes and recursive harvest, plus the
  `mklink /H` + `fsutil hardlink list` build recipe — is `04-image-input-and-handling.md`
  §12.3.
- **Fix, verified.** Replace per-zone junctions with real directories:
  **`.jpg` HARDLINKED** (9,835 files, 35.8 GB logical, 0.05 GB actual, same volume),
  **`.xmp` and flight logs COPIED** — deliberately *not* hardlinked, so a v2 write cannot
  corrupt the baseline's sidecar. Recursive enumeration went 0 → 9,835; `fsutil hardlink
  list` confirmed one inode per image. **No re-align was needed** — the components were
  never the problem, only the paths baked into them.
- **Note.** The junction was never necessary: `--r_input` and `--output_dir` are
  independent, so aligning **from** the real tree **into** a separate output protects a
  baseline just as well.
- **Counter-case where a junction is legitimate.** `D:\na156_h2023_fresh` is a junction to
  `F:\na156_h2023_fresh` precisely because saved `.rsproj` files store **absolute** image
  paths and hard rule 7 (F-36) means a bare move would break both. If it is ever deleted:
  ```powershell
  New-Item -ItemType Junction -Path 'D:\na156_h2023_fresh' -Target 'F:\na156_h2023_fresh'
  ```
  **The distinction that matters: a junction on the path RealityScan *reads a project
  through* is survivable; a junction on the path a scene's images *resolve through* is not.**
  [VERIFIED: FINDINGS 2026-07-27/28; HANDOFF 2026-07-27] [UNDOCUMENTED: no Epic coverage
  of reparse-point behaviour]
- **Detection test (cheap, run before every harvest-dependent run).** This is
  `assert_harvestable()` in `testing/run_h2024_v2.py`, reproduced in essence:
  ```python
  def is_reparse(path: str) -> bool:
      if os.path.islink(path):
          return True
      # islink() is False for Windows junctions on some Python builds;
      # the reparse attribute is the reliable test.
      try:
          return bool(os.stat(path, follow_symlinks=False).st_reparse_tag)
      except (AttributeError, OSError):
          return False

  reparse = []
  for dirpath, dirnames, _files in os.walk(images_root):
      for name in list(dirnames):
          full = os.path.join(dirpath, name)
          if is_reparse(full):
              reparse.append(os.path.relpath(full, images_root))
              dirnames.remove(name)   # do not descend into the link
  if reparse:
      raise RuntimeError(f'images_root {images_root} has reparse-point children {reparse}')
  ```
  Two things this gets right that a naive version does not: `os.path.islink()` alone is
  **False** for Windows junctions on some Python builds, so `st_reparse_tag` is the load-
  bearing check; and the scan must be **recursive** — the guard originally checked only
  top-level children, and a junction one level down (`zone_1\cinema` as a link) reproduces
  the blindness just as completely. [VERIFIED-and-fixed: FINDINGS 2026-07-29 final review
  item (f)]

### F-58 — A stale `<name>.rsproj.new` beside the project makes a load report `0x82000017`
- **Symptom.** A headless `-load` completes but emits warning-class `0x82000017`; the error
  channel then aborts the workflow.
- **Cause.** An interrupted GUI save leaves the `.rsproj.new` temp beside the project.
- **Mitigation.** Rename the temp aside (reversible) and re-load.
  [VERIFIED: FINDINGS 2026-07-29]
- **Detection test.** `dir /b "<project dir>\*.rsproj.new"`.

### F-59 — A BOM invalidates the first line of a `.complist`
- **Symptom.** `merge_zones` read `\ufeffF:\...\zone_1_c6.rsalign`, found no manifest, and
  aborted with "complist entries without manifests".
- **Cause.** `Set-Content -Encoding utf8` in Windows PowerShell 5.1 writes a **BOM**.
  Python's `encoding='utf-8'` does not, so only hand- or PowerShell-authored lists are
  affected.
- **Mitigation.**
  ```powershell
  [System.IO.File]::WriteAllLines($p, $lines, (New-Object System.Text.UTF8Encoding($false)))
  ```
- **Detection test.** Read the first three bytes; `239,187,191` is the BOM.
  [VERIFIED: FINDINGS 2026-07-27]

### F-60 — The cache lives on the drive of the path you gave and does NOT move with the project
See **F-71**. Filed here because it presents as a filesystem surprise: the project disk can
show 773.9 GB free for an entire run while the cache disk hits zero.

### F-61 — Duplicate physical copies of the same image defeat identity-based merges
- **Symptom.** Components that ought to share cameras share none; a union flight log has
  fewer rows than the scene has cameras (cluster_0: 4,865 cameras, 4,227 log rows).
- **Cause.** The batcher writes per-zone **copies** of overlap images, so a copied image is
  two physical files with one trajectory row and no shared-path identity.
- **Mitigation (queued, never applied).** A common image pool — imagelists or hardlinks.
  [OPEN: HANDOFF loose end #6]
- **Note.** Since D7, path identity is known to be **sufficient but not necessary**:
  content overlap fuses regardless of path. Copies still cost the `-mergeComponents`
  mechanism, which fuses through camera identity.

---

## 12. F-62…F-70 — Windows / cmd traps that break the harness

Native Windows only — the production box has no WSL; `cmd`, `.bat`, PowerShell and VBS are
the substrate. Every trap below was hit in practice.

### F-62 — LF-only `.bat` files break `cmd`'s label search NONDETERMINISTICALLY
- **Symptom.** `The system cannot find the batch label specified - run` — **after the same
  `call :run` had already resolved ten times in the same file.**
- **Cause.** `cmd` searches for labels by **byte offset**; LF-only endings shift offsets so
  the failure depends on where in the file the call site sits.
- **Mitigation.** All `.bat` and `.vbs` must be CRLF. `.gitattributes` pins
  `*.bat text eol=crlf` and `*.vbs text eol=crlf`. **Re-normalize after any scripted edit
  and re-verify** (e.g. "342 CRLF, 0 bare LF").
  [VERIFIED: NA167 #21 + H2023, independently hit on BOTH machines, 2026-07-23]
- **Corollary policy.** **Review agents run review-only while live processes hold files** —
  `cmd` reads a `.bat` by byte offset, so a mid-run edit corrupts execution. The
  coordinator applies fixes in safe windows.

### F-63 — `exit /b N` inside a nested parenthesized block returns 0 — but only in ONE configuration
- **Refined by direct measurement** (four probe `.bat` files via `cmd //c`, before/after on
  a real workflow). The code is lost in **exactly one** configuration: `exit /b` inside an
  outer **multi-line** parenthesized block (an `if (…)` body or a `for … do (…)` body) in
  the body of the script that **is the process entry point**.

  | shape | propagated code |
  |---|---|
  | top-level `( echo … & exit /b 1 )` (single-line chain) | **1** correct |
  | top-level multi-line `if … ( … exit /b 1 )` | **1** correct — the original review finding **over-reached** here |
  | `exit /b 1` in an `if`-block nested inside `if defined … (` | **0** ✗ |
  | `exit /b 1` in an `if`-block nested inside `for /f … do (` | **0** ✗ |
  | the same nested shapes inside a `call :label` **subroutine** | **1** correct |
  | the same nested shape in a `call`ed **child** `.bat` | **1** correct |

- **Consequences verified rather than assumed.** (a) The shared `:run` abort contract is
  **LIVE**. (b) `startRealityScan.bat`'s nested boot-timeout `exit /b 1` propagates
  correctly through `call`. (c) The only genuinely broken sites were
  `MergeZoneComponents.bat`'s **top-level complist validations**, which returned 0 — an
  unreadable component list would have been reported and then **ignored**. Fixed by routing
  every validation to a top-level `:argfail`.
  [VERIFIED: FINDINGS 2026-07-24, superseding the broader 2026-07-23 statement]
- **Detection test.** `cmd //c probe.bat & echo %errorlevel%` on the exact nesting shape in
  question. Do not reason about it; measure it.

### F-64 — Git Bash / MSYS mangles cmd switches
- **Symptom.** `cmd /c foo.bat` under MSYS converts `/c` to `C:\` and launches an
  **interactive** cmd that exits **0** silently — a test that proves nothing.
- **Mitigation.** Use `cmd //c` or PowerShell for `.bat` invocation tests.
  [VERIFIED: FINDINGS 2026-07-23]
- **Related, same family.** `RealityScanCLI` invokes the `.bat` **by absolute path without
  an explicit `cmd /c`**: a bare script name fails to resolve under
  `NoDefaultCurrentDirectoryInExePath` (e.g. Git Bash), and a self-built
  `cmd /c "path with spaces.bat"` has its quotes stripped by cmd. The `:run` line-count
  also had to be fully qualified as `%SystemRoot%\System32\find.exe`, because a bare `find`
  resolves to **GNU find** when launched from Git Bash and scans the whole disk.
  [VERIFIED: HANDOFF 2026-07-21; docs/code-review-2026-07 §2]

### F-65 — cp1252 console crashes on non-ASCII
- **Symptom.** A `UnicodeEncodeError` kills a stage at a `print`/log call, not at the work.
- **Cause.** The Windows console codepage is cp1252 on this box; any non-ASCII character
  routed to stdout raises.
- **Mitigation.** ASCII-only console output everywhere; `PYTHONIOENCODING=utf-8` when
  parsing UTF-8 sources. Hit twice, once on each research line.
  [VERIFIED: FINDINGS "Windows & automation traps"; `CLAUDE.md` §8]
- **Note for readers of the app log.** `RealityScan.log` itself is not ASCII — its banner
  line contains a non-ASCII copyright glyph (`RealityScan 2.2.0.119430 ... 2026 Epic Games,
  Inc.`), so a parser that opens it in the console codepage can fail on line 1. Read it
  with an explicit encoding and `errors='replace'`.
  [VERIFIED: `testing/results/z14_forensic_rslog.txt` line 1]

### F-66 — `isatty()` LIES under hidden consoles
- **Symptom, in its full three-supersession form.** "The batcher spends ~3 h in zone
  computation" → SUPERSEDED "it was `plt.show()` blocking; a gated re-run took 28.9 min" →
  RE-OPENED "a third run with plots gated off still spent 2 h 53 min between two figure
  saves, so the original finding stands and 28.9 min is an unexplained outlier" → FINAL:
  **actual compute measured at 1.35 s for 8,197 points; the `stdin.isatty()` gate did not
  work because `isatty()` reports True with an EOF stdin under a hidden console.**
- **Mitigation.** Wrap `input()` in `try/except EOFError` with a stored-default fallback
  for anything that may run unattended; make blocking UI opt-in (`RS_SHOW_PLOTS=1`), never
  opt-out.
- **Method lesson recorded.** *A faster run is not a control unless it did equivalent work.
  A blocking UI call is indistinguishable from slow compute if you only look at elapsed
  time.*
  [SUPERSEDED ×3, RESOLVED: FINDINGS 2026-07-26 → 2026-07-28]

### F-67 — Console-subsystem children pop visible windows when the parent has none
- **Symptom.** Hundreds of flashing terminal windows stealing focus over a long run.
- **Cause.** `tasklist`, `cmd`, `powershell` are console-subsystem executables.
- **Mitigation, two layers.** (a) `CREATE_NO_WINDOW` on **every** helper subprocess
  (`_NO_WINDOW` in `realityscan_cli.py`). (b) The RealityScan completion hook goes through
  a **GUI-subsystem** host: `wscript.exe //B ErrorWriterLaunch.vbs`, which shells
  `ErrorWriter.bat` hidden and **synchronously** (`shell.Run …, 0, True`) to preserve
  marker-file write ordering. A direct `cmd /c` in `appProcessExecCmd` pops a window for
  every completed process, heartbeats included.
  [VERIFIED: `realityscan_cli.py`; FINDINGS 2026-07-23]

### F-68 — VBS quote escaping in string literals
- **Symptom.** A malformed command line that launches nothing, silently (F-24).
- **Mitigation.** Compose with `Chr(34)`:
  ```vbscript
  q = Chr(34)
  shell.Run "cmd /c " & q & q & bat & q & args & q, 0, True
  ```
  Then **verify the composed line actually executes.**
  [VERIFIED: FINDINGS 2026-07-24]

### F-69 — Piped stdin: BOM and CRLF corrupt scripted prompts
- **Symptom.** `input()` returned `"a\r"`; the first prompt answer was corrupted outright.
- **Cause.** PowerShell native piping prepends a **BOM** and delivers **CRLF**.
- **Mitigation.** `.strip()` everywhere; drivers answer prompts via a scripted `input`, not
  stdin pipes; every driver subprocess gets `stdin=DEVNULL` and every option is pinned —
  on a console a child's `input()` blocked forever on an invisible prompt, and detached it
  silently inherited another session's `rs_settings.json` values.
  [VERIFIED: NA167 #10 / B9, 2026-07-22; FINDINGS 2026-07-29]

### F-70 — One-off, unexplained: `%RealityScan%` expanded EMPTY
- **Symptom.** After D6's 56-minute merge block, `%RealityScan%` expanded to nothing
  (`'-delegateTo' is not recognized`) and the export step died.
- **Frequency.** Single occurrence across ~10 identical workflows.
- **Cause.** Not established.
  [OPEN: NA167 #31 note, 2026-07-24 — watch for recurrence]
- **Detection test.** Echo `%RealityScan%` at each phase boundary in long workflows.

---

## 13. F-71…F-77 — Resource exhaustion

### F-71 — The CACHE disk fills, the operation aborts, and the code says only `0x80070070`
- **Symptom.** Three consecutive failures of one model, each presenting differently:
  crash at `closeHoles`/`cleanModel` — step **[5/8]** (F-42); then 143.5 min to a failure
  in step **[6/8]** with result `2147942512` = `0x80070070` = `ERROR_DISK_FULL`; the
  instance log finally said it outright: **`Processing failed: Out of disk space..`**
  during `simplify`, *after* `closeHoles` (125 s) and `cleanModel` (230 s) had both
  **succeeded**.
- **Why [6/8] is recorded as both "texture generation" and "simplify".** Step [6/8] of
  `GenerateModel.bat` is a single labelled block, "Noise-reduction simplify + texture",
  containing `-simplify "%SimplifyNoise%"` → rename → `-calculateTexture
  "%HighModelTexture%"` → rename. The step label and the app-log text name different
  commands inside the same step; they are not in conflict.
  [VERIFIED: `RS_CLI/Scripts/GenerateModel.bat` lines 121–125]
- **True root cause.** RealityScan's **cache disk**, not the project disk. The cache lived
  at `D:\rccache` (1,089 GB) and refilled 197 GB of freshly-cleaned space within a single
  run. Moving the **project** to another drive did nothing, because **the cache does not
  move with the project — it is placed by the drive of the path given.** The project drive
  read 773.9 GB free for the entire run.
- **Fix.** `RS_CACHE_DIR=E:\rscache` → attempt 4 succeeded in 384.1 min. **The only
  variable changed.**
- **Official behaviour.** Epic: processing cannot continue without freeing space on the
  cache disk; using Cancel stops the free-space check and "will eventually give out an Out
  of disk space error", after which "the process that was running will be aborted and the
  progress will be lost". And: **"don't delete the files from your cache folder since this
  may lead to some failures in the project."** Hand-clearing the cache is therefore **not**
  a legitimate remedy — the sanctioned levers are freeing space on the cache disk or
  changing the cache disk. [OFFICIAL: appbasics/outofdisk]
- **Settings, exact.** [OFFICIAL: tutorials/setkeyvaluetable]

  | Key | Values | Default |
  |---|---|---|
  | `appCacheLocation` | `SystemTemp` \| `Custom` | `SystemTemp` |
  | `appCacheCustomLocation` | path (used when `appCacheLocation=Custom`) | *(empty)* |
  | `appAutoClearCache` | `999999` do not clear · `0` clear all · `3` · `7` · `14` · `30` · `90` (items older than N days) | **`7`** |

  `appAutoClearCache` is deliberately left untouched here — retention is owner policy.
  `-clearCache` exists as a CLI command: "Clear the application cache. **You must save the
  project before clearing the application cache.**" [OFFICIAL: appbasics/allcommands]
  (process id `21861` `CLI_CLEAR_CACHE`). Changing `appCacheLocation` needs an application
  restart, which is what `-set "appQuitOnReset=true"` is for — Epic's own worked example is
  exactly a cache-directory change followed by a fresh `-newScene` invocation
  [OFFICIAL: tutorials/commandline_5].
- **How this repo applies it.** `startRealityScan.bat` honours an opt-in `RS_CACHE_DIR`:
  when set it boots with `-set "appCacheLocation=Custom" -set
  "appCacheCustomLocation=%RS_CACHE_DIR%"`; unset keeps RealityScan's own default so
  nothing changes silently. [VERIFIED: `startRealityScan.bat`]
- **METHOD LESSON, the sharpest in the log.** *A resource trace built hours earlier
  instrumented CPU and memory **because memory was the hypothesis**. It faithfully recorded
  RAM falling to 3.1 GB and was silent about the disk that actually killed the run. A
  monitor built around one hypothesis will confirm or refute that hypothesis and tell you
  nothing else.* Free space on **both** the project drive and the cache drive are now trace
  columns with peak-minimums in the summary line.
  [VERIFIED: FINDINGS 2026-07-26]
- **Detection test.** Sample `shutil.disk_usage()` on the project directory **and** on
  `RS_CACHE_DIR` every 30 s, flushed per sample.

### F-72 — Near-OOM: a crawl, not a crash
See **F-38**. RealityScan slows drastically without crashing and without spilling to NVMe;
in the progress feed it is indistinguishable from a hang.

### F-73 — Commit charge, not just physical RAM
- **Measured on the 3,738-camera hull.** `-calculateHighModel` drove available RAM from
  79.4 GB to 3.1 GB within **3 minutes**; commit charge went 19.6 → 105 GB; **Windows grew
  the commit limit from 99.5 GB to ~120 GB** to absorb it; the run then oscillated at
  87–105 GB committed with 7–32 GB free for half an hour. RealityScan's working set peaked
  at 62.5 GB. Verified doing **real work** (9.1 cores busy, 33 % GPU over a 20 s window),
  not hanging.
- **These figures are a MEMORY PROFILE and NOT the cause of any failure**
  [SUPERSEDED: the reading "memory exhaustion intrinsic to this mesh"].
- **Mitigation.** Sample commit *and* physical RAM — a run can exhaust commit while
  physical RAM still looks comfortable (`ullAvailPageFile` in `MEMORYSTATUSEX` is the
  system commit availability, not a paging-file-only figure).
  [VERIFIED: FINDINGS 2026-07-26]

### F-74 — The ~5,000-camera model envelope does NOT plateau
| component | cameras | model wall clock | peak commit | min available RAM |
|---|---:|---:|---:|---:|
| `cluster_0_a2_c0` (hull) | 4,860 | 338.3 min | **148.7 GB** | **0.9 GB** |
| `zone_1_c0` | 1,634 | 249.3 min | 139.9 GB | 2.0 GB |
| `cluster_1_a1_c0` | 880 | 122.8 min | 138.6 GB | 2.8 GB |
| `zone_4_c0` | 576 | 106.1 min | 116.8 GB | 3.0 GB |
| `zone_1_c1` | 392 | 97.4 min | 107.1 GB | 3.5 GB |
| `cluster_4_a1_c0` | 133 | 40.1 min | 96.2 GB | 25.9 GB |
| `pd6_zone_1_c0` (H2023 hull) | 3,738 | 384.1 min | 142.3 GB | 0.3 GB |

The apparent plateau at ~140 GB across 392–1,634 cameras was an artifact of that range; the
hull pushed ~9 GB past it and completed with **under a gigabyte of headroom on a 93.6 GB
box**. **Treat anything materially larger as at risk, not covered by precedent.**
[VERIFIED: FINDINGS 2026-07-29]

### F-75 — Alignment memory scales badly enough that chunking is mandatory
Per-zone aligns (~1.5 k images) peak ≤ ~60 GB; a joint 4,131-image align peaked ~165 GB on
a 192 GB box (27 GB commit headroom left). **Joint alignment extrapolates to ~700 GB for a
19 k-image dive.** Sequential growth and joint align give identical quality and differ
2.6× in time and 2.7× in memory, with opposite winners (B: 94.6 %, 444 min, ≤60 GB;
C: 94.5 %, 169 min, ~165 GB).
Also: **alignment runtime varies ~3× with scene character at equal image count** (61.6/97.8
min vs 24.3/20.8 min, both ~1.5 k frames, same GPU, both run twice) — **budget by zone, not
by image count.**
[VERIFIED: NA167 #19/#20]

### F-76 — Memory readings are confounded by multiple `RealityScan.exe` processes
Workflows run a **persistent instance plus transient helpers**. A "2.2 GB during a
4,540-image align" reading was a 30 MB transient; the real instance was ~11 GB + 4 GB VRAM.
**Identify the instance by largest working set or tracked PID before quoting any memory
number.** [VERIFIED: FINDINGS 2026-07-24, owner-caught]

### F-77 — Saving is a resource event in its own right
`GenerateModel.bat` took **two** `RC_projects` copies per component, one of them
**mid-recipe with every intermediate model live**: `zone_1_c0`'s saves consumed ~81 GB.
With `RS_PROJECTS_DIR` unset (which skips both) `cluster_4_a1_c0` cost 6.8 GB end to end,
and one dated copy of the finished six-component project took **13.1 min / 95.2 GB**.
Saving with ~15 models live is the "inordinate save" case. The **per-component scene save
must stay** (the workflow loads/models/quits per component); the dated copy is deferred to
one end-of-project call.
[VERIFIED: FINDINGS 2026-07-29]

---

## 14. The NA167 B1–B11 bug list, mapped

`testing/NA167_SESSION_NOTES.md` §2 is the original numbered list. **Note the source file
REUSES B10 and B11 for two different findings each.** RS = RealityScan-side, INT =
integration-side.

| ID | Class | Finding | Entry here |
|---|---|---|---|
| **B1** | RS | Relocated `-importComponent` hangs forever (`#timeout`, 6 h+, no error, no dump) | F-36 |
| **B2** | RS | `-selectAllComponents` does not exist (`0x82000060`). `appbasics/allcommands` lists only `selectComponent`, `selectMaximalComponent` and `selectComponentWithLeastReprojectionError`; the dead command had lived unnoticed in `AlignZonesSequentially.bat` | §2.2 (`0x82000060` row) |
| **B3** | RS | `getStatus`/teardown race — instance reports gone while holding `progress_<inst>.txt` | F-29 |
| **B4** | RS | `#timeout` progress defeats stall detection | F-35 |
| **B5** | INT | cmd splits unquoted `;` `,` `=`; Python quotes only on whitespace → flags silently never applied **and** parse errors abort the workflow | F-03 |
| **B6** | RS | `0x8000FFFF` is generic; the app log is truncated per boot | §2.2, F-39 |
| **B7** | RS | XMP sidecar conventions: `<stem>.xmp` only; exports auto-import as exact-pose priors; prior content is not automatically beneficial | F-06, F-50, F-52 |
| **B8** | RS *(partially resolved)* | zone_14 standalone align fails `0x8000FFFF`, localized to `MSS_STR001`; data exonerated; grows fine inside a larger scene | F-41 |
| **B9** | INT | Piped-stdin quirks (BOM + CRLF) | F-69 |
| **B10** *(first use)* | INT | LF-only `.bat` files break `call :label` nondeterministically | F-62 |
| **B10** *(second use)* | RS | XMP export of an imported-component scene writes **ordinal** sidecars | F-48 |
| **B11** *(first use)* | RS | In-place `-importComponent` ~2 s per 0.7 GB; `-setMinComponentSize` deprecated; `-mergeComponents` on two zero-overlap components logged "Finalizing 9 components" | F-01, F-07, F-36 |
| **B11** *(second use)* | RS | The merge feature-source trio **is** CLI-accessible (`-setFeatureSource 0\|1\|2`, `-selectImage`), plus `-exportLatestComponents`, `-selectComponentWithLeastReprojectionError`, `-deleteComponent <idx>`, `-deleteAllComponents` | see `02-command-reference.md` |

---

## 15. Diagnostic playbook

Ordered checks per symptom. **Stop at the first check that explains the symptom** — the
supersession chains in this log all came from asserting a cause before cheaper checks were
exhausted.

### P-1. "The workflow reported success but nothing happened"
1. **Was the operation instant?** Compare the logged duration against a known-good run of
   the same size. Sub-second on an export → F-08. Minutes on a merge that should take an
   hour → F-01.
2. **Census the result.** Count pose-bearing sidecars / component members. Never accept
   exit status (R1).
3. **Is the census instrument alive?** Before believing a `0`, prove the oracle can see its
   subject on a known-good case → F-19, F-18, R3.
4. **Snapshot the app log NOW** (F-39) and grep for `Added 0 layer images` (F-05),
   `err:7155` (F-03), `Finalizing` (F-20).
5. **Check the images root for reparse points** (F-57).
6. **Check `setMinComponentSize`** — default 5 silently excludes small components from
   `-exportXMP` / `-exportLatestComponents` (F-07).
7. **If the stage's output is a directory, COUNT the directory** and compare against the
   stage's own reported total (F-82).

### P-2. "The instance looks hung"
1. `tail progress_<inst>.txt`. Frozen fraction + rising elapsed + `#timeout` → go to 2.
   No new lines at all → go to 5.
2. **Which `algId`?** `20594` (`IMPORT_COMPONENT`) from fraction 0.00 → F-36, relocated
   component; kill it, import in place.
3. **Available RAM?** Below ~4 GB → F-38/F-72, a near-OOM crawl; it will finish, slowly.
4. **Otherwise assume a legitimate heavy align phase** (F-37). 40 `#timeout` lines appeared
   in a successful run. **Never auto-kill an align.**
5. `RealityScan.exe -getStatus <inst>` — non-zero errorlevel means the instance is gone
   (F-34); look for a `.dmp` in the `-silent` directory (F-42).
6. **Instance alive, but no `#started` line for the operation at all?** Suspect a command
   waiting on a dialog a headless instance can never answer — `-exportRegistration` with no
   params XML is the known case (F-78).

### P-3. "There is a code in `errors_<inst>.txt` I don't recognise"
1. Look it up in §2.2. `0` and `1` are **not** errors.
2. `2181038335` (`0x820000FF`) after a flight-log import (process `20598`) is the
   documented warning class — cross-check the "not in scene" images against every component
   manifest before treating it as benign.
3. `2147942487` (`0x80070057`) after `21856`/`21857`/`21859` is an empty/no-op selection —
   expected at a peel terminal (F-10) and in the model cleanup loop (F-55).
4. `2147942512` (`0x80070070`) → **cache disk**, not project disk (F-71).
5. `2147549183` (`0x8000FFFF`) is **generic and ambiguous**: it means *either* a broken
   `-set` argument *or* the reconstruction solver bug. The only way to tell is the app log
   — snapshot it immediately (F-39) and grep for `err:7155` vs `MSS_STR001`.
6. `2181038103` (`0x82000017`) after `20532` (`PROJECT_LOAD`) → a stale
   `<name>.rsproj.new` beside the project; the load completed anyway (F-58).
7. Anything else: convert the decimal to hex, record it, and snapshot the log. Remember the
   marker names the **process id**, so §2.3 tells you *which operation* failed even when
   the code is generic — and `21856`/`21857`/`21859` empty-selection codes are routine
   noise, not failures.

### P-4. "`ERROR: Failed to delegate command`"
This is a **dead instance**, not a rejected operation (F-34). Check `-getStatus`, then the
`-silent` directory for a minidump, then the app log for the last successful step.

### P-5. "`The system cannot find the batch label specified`"
Line endings (F-62). Check the file for bare LF; re-normalize to CRLF; re-verify the count.
Do **not** conclude the label is missing — it resolved ten times earlier in the same file.

### P-6. "The merge produced no fusion"
1. **How long did it take?** Instant → genuine no-fuse (F-01). ~1 h for a 1–4 k pair →
   it fused and the accounting failed.
2. **Is the peel empty?** Empty peel beside a non-empty export is an **instrument failure**
   and must abort the run (F-18).
3. **Is the peel maximal a near-miss of the input sum?** 4,860 of 4,865 is a fusion hidden
   by exact-subset-sum attribution (F-20).
4. **Validate the `rslog.txt` against the attempt's own complist** before reading
   `Finalizing N` out of it (F-40).
5. **Do the inputs share content at all?** Zero content overlap ⇒ no mechanism can fuse
   them; that is a correct terminal state, not a failure (see `08-components-and-merge.md`).

### P-7. "The harvest / peel is empty"
1. Reparse points on the images root, **at any depth** (F-57) — both the write side and the
   read side.
2. Did an earlier peel already move the sidecars out? The align harvest leaves the tree
   pose-free, so a later merge starts with nothing to harvest (F-51).
3. Is the scene a merge scene? Then the sidecars are **ordinal** and stem-based tooling
   sees nothing (F-48).
4. PowerShell 5.1 exits 0 on non-terminating pipeline errors, so a partial move is invisible
   to `if errorlevel 1` (F-46).

### P-8. "A model built on the wrong component, or with the wrong texture"
1. Are component names unique across the assembly? (F-53)
2. Are model names namespaced per component? (F-54)
3. Did an intermediate name leave the project mid-recipe? (F-55)
4. Was a `-selectModel` no-op followed by a `-deleteSelectedModel`? (F-32)
5. Not a prefix collision: `-selectModel` matches the exact name
   [OFFICIAL: appbasics/allcommands], so `<tag>_HighPoly` cannot take
   `<tag>_HighPoly_Textured` with it (F-55).

### P-9a. "A workflow reported a validation error that cannot be right"
1. Is the guard scoped to the mode you are running? A `component_count LSS 2` check written
   for merge fired on `assemble` and failed a fully-converged run (F-81).
2. Did the reject path actually return non-zero, or did `exit /b` inside a parenthesised
   block launder it to 0? (F-63)
3. Did the workflow save a scene with most images disabled? (F-80)

### P-9. "Registration looks fine but the geometry is the wrong size or orientation"
1. **Run the scale oracle.** A uniform similarity error is invisible in the viewer and in
   every count-based metric (F-17).
2. If the component is **fused**, the stem oracle cannot measure it — use the
   correspondence-free quantile-ratio method, and watch for both `xcr:Position` forms and
   the union-vs-occurrence multiset trap (F-23, F-49).
3. Check the prior accuracies: over-tight positions fragment solves and shrink scale while
   registration barely moves (F-17 table).
4. If only the **assembled** artifact is wrong, suspect `-update` fitting mis-converted
   orientation priors (F-16); the cheap decisive test is a position-only re-`-update`.
5. Check the flight-log format GUID is actually installed (F-15) and the UTM zone is the
   cruise's (F-14).

### P-10. "The run died and there is nothing in the error channel"
1. **Is the hook alive?** Active `progress_<inst>.txt` + non-growing `results_<inst>.log`
   = dead hook (F-24). Verify by injecting a known failure.
2. Is `appProcessExecCmd` quoted for a path with spaces? (F-24)
3. **Did you ATTACH to an instance instead of booting one?** The reuse branch never
   re-applies the hook settings, so an instance booted by anything else has no error
   channel at all (F-30).
4. Did the orchestrator swallow a refusal or a raise? (F-26)
5. Was the process entry point's `exit /b` inside a nested parenthesized block? (F-63)

### P-11. "Everything is slow / the box is thrashing"
1. Available RAM and **commit charge** (F-73), sampled every 30 s.
2. Free space on the **cache** drive as well as the project drive (F-71).
3. Identify the real instance by largest working set before quoting a number (F-76).
4. Check whether a save with many models live is in progress (F-77).
5. Compare against the envelope table (F-74); above ~5,000 cameras you are outside
   precedent.

### P-12. Session-start monitor liveness check (run before any long run)
1. Prove the errors channel fires: trigger a known-bad operation and confirm the code
   reaches `errors_<inst>.txt` (F-24).
2. Prove the `:run` abort contract: probe with a non-empty marker (must exit 1) and an
   empty one (must continue) (F-28).
3. Prove the harvest instrument: `assert_harvestable(images_root)`, recursively (F-57).
4. Prove the census oracle against a known-good **and** a known-bad case (R3).
5. Confirm `.bat`/`.vbs` are pure CRLF after any edit (F-62).
6. Confirm the instance you are about to drive is the one you think: read the resolved
   instance name off the CLI object, not off the environment you believe you set (F-31),
   and confirm the per-instance lock is yours.
7. Confirm the boot pinned `appAutoSaveMode=false`; a `20534 PROJECT_AUTOSAVE` line in any
   marker means it did not (F-79).
8. Confirm free space on the **cache** drive, not only the project drive (F-71).

---

## Open questions

Every `[OPEN]` in this document, with the cheapest probe that would settle it.

| # | Question | Entry | Cheapest probe |
|---|---|---|---|
| O-1 | What is the internal reason for `MSS_STR001`? | F-41 | Not settleable locally — **report to Epic** with `testing/results/z14_forensic_rslog.txt`. Never done (HANDOFF P1 item 8). |
| O-2 | Is the 2–3 camera deficit after a fusion a real solver drop or a harvest artifact? | F-46 | Re-import `cluster_*_m_c0.rsalign` **from its original export location** into a spare instance and census it. 3,740 = artifact; 3,738 = real loss. Artifacts already on disk; do **not** use `rslog.txt` (F-40). |
| O-3 | What are the exact semantics of `Finalizing N component(s)`? | F-20 | Two tiny imports, one `-mergeComponents`, count the result. Queued probe (a); never run. |
| O-4 | Is `merged5`'s `cluster_1_a3_c0` a single component or a rigid glue container of 8 objects? | F-20 family | Re-import it from its original location and census. Queued probe (b). |
| O-5 | Can the rigid-glue behaviour be reproduced on demand? | §4 | Two zero-shared components + `merge_georef`; expect glue. Queued probe (c). |
| O-6 | Does `sfmMergeGeoreferencedComponents` work when the components are *properly* georeferenced (not prior-weighted at 10 m)? | F-13 | Re-run D1/D2 with priors-v2 components. Queued; never run. |
| O-7 | What regexp dialect (if any) does `-selectImage` accept? | F-12 | Forum-mine for a staff reply; a bisection over dialects has already failed. |
| O-8 | Does the hand-merged 13-column flight-log format survive a RealityScan update? | F-15 | `findstr /c:"B438A617" "C:\Program Files\Epic Games\RealityScan_2.2\flightlogs.xml"` after every update. Seconds. |
| O-9 | What are `21856` and `21896` in the process-ID space? | §2.3 | Fire `-selectModel` alone and read the marker's process id (confirms 21856); bracket a boot/quit and read `21896`'s neighbours. Minutes. |
| O-10 | What does the `timeout` argument of `-writeProgress <file> <timeout>` actually bound? | §2.4 | Production passes `600` and multi-hour runs keep emitting progress, so it clearly does not stop writing after 600 s [INFERRED-by-consequence]. Settle by passing `5` and watching whether lines stop. Minutes. |
| O-11 | Why does `-selectModel <tag>_HighPoly` return the empty-selection code in every cleanup loop? | F-55 | Dump the model list at that point in the recipe (GUI or a probe) and see which name exists. Blocks the `GenerateModel` error-whitelist redesign (queued probe (e)). |
| O-12 | Do two concurrent instances on different GPUs stay isolated (markers, cache)? | F-33 | Boot RS1 on GPU 0 and RS2 on GPU 1, align two small zones simultaneously, check marker isolation and cache contention. NA167 loose end #2. |
| O-13 | Can headless RS 2.2 hit a licensing/activation prompt that manifests as a silent hang? | §1 | No probe designed. Two years of headless production recorded no licensing interaction — absence of evidence, not evidence of absence. |
| O-14 | What is the shutdown bound on a very large scene? | F-30 | Time `-quit` → `-getStatus` gone on a 4,000+ camera scene once. Costs one teardown. Only verified on small scenes; code allows 900 s, `CLAUDE.md` still says 300 s. |
| O-15 | Why did `%RealityScan%` expand empty once after a 56-minute blocked wait? | F-70 | None designed. Echo the variable at phase boundaries and watch for recurrence. |
| O-16 | Is the truncated-peel / unasserted-instrument defect closed? | F-21, F-22 | Assert `expected_peelend_<inst>.txt` is read, and sanitize + check `census_leftover` before each attempt. Both are **open defects**, not just unknowns. |
| O-17 | Does `-update` explain the 45° bow tilt? | F-16 | Re-run the assembly `-update` with a **position-only** union log and re-measure the bow's attitude (~2 min). Queued probe (h). |
| O-18 | Does `appCopyImportedComponentsToCache` interact with the relocated-component hang? | F-36 | Never swept. Set it true and import a relocated `.rsalign` with a 45-min watchdog. |
| O-19 | Why does an attempt whose scene contains a previously fused `.rsalign` harvest **zero** sidecars? | F-83 | Import two small components, merge, export; in a fresh scene import that fused file plus a third component, merge, export, and sweep for `xcr:Position`. ~10 min. Did not recur in `merged5`, so it may not reproduce. |
| O-20 | Does `-exportRegistration` with no params XML block on a GUI dialog, or on something else? | F-78 | Run it once under `RS_HEADLESS=0` and look at the screen. Minutes. Currently [INFERRED]. |
| O-21 | Does `setMinComponentSize` gate **selection** as well as export? | F-07 | The Help attaches the condition only to `exportXMP` / `exportLatestComponents`. Align a scene that yields a sub-5-camera component, then try to reach it by peel at `1` vs `5`. Hardening cell U5. |
| O-22 | Does `<comp>_HighPoly_Raw` survive the model recipe on *any* component? | F-55 | The 2026-07-29 export probe says no (`err:5601`); FINDINGS 2026-07-28 and HANDOFF 2026-07-29 both say yes. Enumerate the model list per component in the GUI or with a probe. Minutes, settles a live internal contradiction. |
| O-23 | What does a second instance do when it opens a project already open, with `allowReadOnly=false` (the default)? | F-33 | Boot RS1, `-load` a project, boot RS2, `-load` the same project, read the marker. Minutes. |
| O-24 | Which of `delete` / `recover` / `abort` / `ask` does a headless `-load` actually exhibit for `appAutoSaveCliHandling`? | F-79 | Create an autosave (enable autosave, make a change, kill the instance), then `-load` under each of the four values and observe. The `ask` case is the one that could hang an unattended run. |
| O-25 | Do `-pauseInstance` / `-unpauseInstance` / `-abortInstance` leave a loadable scene, and do they emit a marker line? | F-37 | Abort a small align, read `errors_<inst>.txt` / `results_<inst>.log`, then reload the project. Minutes. Documented but never exercised here. |
| O-26 | Is `startRealityScan.bat`'s reuse-branch `-deleteAutosave` an invalid command? | F-79 | The Help defines `deleteAutosave` only as an optional parameter of `load`. Take the reuse branch once with a live instance and grep `errors_<inst>.txt` for `2181038176` (`0x82000060`). Seconds. |
| O-27 | Does an instance reused by `startRealityScan.bat` really run without the error hook? | F-30 | The reuse branch `goto :eof`s before the `-set` quartet. Boot an instance by hand with no hook, take the reuse branch, run a known-bad operation and check whether `errors_<inst>.txt` is written at all. Minutes; would confirm a silent-total-blindness path. |
