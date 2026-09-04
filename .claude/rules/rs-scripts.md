---
paths:
  - "modules/realityscan_interface/RS_CLI/**"
---

# Rules for the workflow scripts (`RS_CLI/Scripts`, `Errors`, `Metadata`)

- **CRLF, always.** cmd resolves `call :label` by byte offset; an LF `.bat`
  found `:run` ten times, then "cannot find the batch label". `.gitattributes`
  pins it, `normalize_crlf.py` repairs it. [rs-reference 12 `F-62`]
- **Every operation goes through the shared `:run` subroutine**: `-delegateTo
  %RS_INSTANCE%` -> grace -> `-waitCompleted` -> grace -> `-waitCompleted` ->
  size test on `errors_%RS_INSTANCE%.txt`. A `-waitCompleted` issued before
  the instance dequeues the command returns at once, hence the double wait.
  [CLAUDE.md hard rule 1; rs-reference 11 sec. 2.1-2.2]
- **One command per `-delegateTo`.** It hands ONE operation to the FIFO queue
  and returns at hand-over; its exit code says nothing, and chaining hides
  which command failed. [rs-reference 11 sec. 2.2]
- **Never gate completion on `results_<inst>.log` growing.** Heartbeat
  processes write it; a growth check raced ahead of a running `-align`.
  [rs-reference 11 sec. 2.2; README "How RealityScan execution works" item 3]
- **Lists cross the boundary as files, settings as `key:value`.** cmd splits
  unquoted `; , =`; `subprocess` quotes only on whitespace; RealityScan logs
  `err:7155` and applies nothing. `.complist`/`.imagelist` for lists;
  `key:value` -> `-set "key=value"` inside. [CLAUDE.md hard rule 8; NA167 B5]
- **Clear `progress_*` / `errors_*` / `results_*` only via `RealityScanCLI`.**
  Never `del` them in a script; an expected failure MOVES the errors file to
  `expected_<reason>_<inst>.txt` (`try_delete_model`). [CLAUDE.md hard rule
  4; rs-reference 11 sec. 2.3]
- **The errors file is STICKY.** It holds the last error from ANY source all
  session, so `:run` blames whatever ran last and one tolerated failure fails
  every later `:run`. An optional step is a SKIP or an `expected_*` move,
  never a caught error. [FINDINGS `[NA165] 2026-09-02`; HANDOFF loose end 1]
- **`ModelToFinal.bat` is the one attach exception**: no `startRealityScan.bat`
  (it would `-newScene -deleteAutosave` the scene being finished), delegates
  to `%RS_TARGET%`, accepts `*`, gates on `-getStatus` `lastError:`/`rev:` as
  a GUI instance writes no `errors_<inst>.txt`. Copy it nowhere. [ARCHITECTURE]
- **Test structurally, never by booting**: extend the stub-exe, no-subprocess
  assertions in `testing/test_cmd_boundary_guards.py`. [its header, 2026-08-07]
