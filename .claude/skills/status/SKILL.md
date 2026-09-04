---
name: status
description: Read-only state of a run - use whenever the owner asks "where are we", "is it done", "did it work", "status", "what is running", "is it stuck", or wants a verdict on a results workspace. Runs the verify oracle, reads run state and the newest logs, checks the instance marker files, and reports RAM/disk. Never kills, deletes, clears, or launches anything.
---

# Status - read, report, never act

Inputs: `<ws>` = the results root (`locations.results_root` of the charter
named by `RS_RUN_CHARTER`; otherwise ask); `<inst>` = the agent's instance
(`ownership.rs_instance`, else `RS_INSTANCE`). `python` = the interpreter
with the deps (CLAUDE.md "Environment"). Run every step; report the block
in sec.7. A stage's exit status proves nothing - only sec.1 does.

## 1. The oracle - "did it actually work"

```bash
python -m modules.verify --workspace <ws> --json
```

Exit 0 ok / 1 incomplete / 2 blocked / 3 absent. Read from the JSON:
`verdict`, `required[]`, `blocking[]`, `incomplete[]`,
`stages.<key>.{status,summary}` (extract, georeference, preprocess, batch,
align, merge, model, export, publish), `counts.{components,cameras,
modelled,exported,scale_unmeasured,zones_without_fingerprint}`,
`provenance.frame_unanimous`. Omit `--json` for the ASCII table; add
`--require align,merge` to gate specific stages.

**`blocked` is stop-and-ask.** Quote every `blocking[]` line verbatim; do
not re-run, "fix", or push past it. `incomplete` = not done yet, not failed.

## 2. Run state

`<ws>/_agent/RUN_STATE.json` is not yet produced by any driver (roadmap
Phase 2, `modules/launch.py`). If it exists, print it raw and say which
tool wrote it; if absent say "no RUN_STATE.json (not yet produced by any
driver; roadmap Phase 2)". Do not invent fields. Also show, if present,
the tail of `<ws>/_agent/RUN_LOG.md`, and whether the charter is signed:
`python -m modules.run_charter --validate <charter>` (exit 0 = signed).

## 3. Newest logs

Drivers write `<ws>/logs/` (`output_<stamp>.txt` from `RealityScanCLI`),
`<ws>/models_driver.log` (`run_models.py`) and `<ws>/merged/logs/` (merge).

```powershell
Get-ChildItem <ws>\logs,<ws>\merged\logs -File -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 3 FullName,LastWriteTime,Length
Get-Content <newest file> -Tail 30
```

`%LOCALAPPDATA%\Temp\RealityScan.log` is global and truncated on every
instance boot - quote it if it helps, never assume it is this run's.

## 4. Instance marker files

`modules/realityscan_interface/RS_CLI/Errors/`, per instance:
`progress_<inst>.txt` (last line = live progress; ending in `#timeout`
means the instance hung), `errors_<inst>.txt` (non-empty = a recorded
error; STICKY within a session, FINDINGS 2026-09-02, so read the first
line, not only the last), `results_<inst>.log`, `<inst>.lock` (held while
a driver owns the instance).

```powershell
Get-ChildItem modules\realityscan_interface\RS_CLI\Errors -Filter "*<inst>*" | Select-Object Name,LastWriteTime,Length
Get-Content modules\realityscan_interface\RS_CLI\Errors\progress_<inst>.txt -Tail 3
Get-Content modules\realityscan_interface\RS_CLI\Errors\errors_<inst>.txt -TotalCount 5
```

No marker set but a live process = a GUI/Launcher instance the pipeline
never booted: report it as the owner's. Never issue `-getStatus` yourself -
that invokes the executable and `guard_rs_launch.py` refuses it (hard
rule 1); the marker files are the read.

## 5. What is running (identify, never touch)

```powershell
Get-Process RealityScan -ErrorAction SilentlyContinue | Select-Object Id,StartTime,WorkingSet64
Get-CimInstance Win32_Process -Filter "Name LIKE 'RealityScan%'" | Select-Object ProcessId,CommandLine
Get-ScheduledTask | Where-Object {$_.State -eq 'Running'} | Select-Object TaskName,State
```

The command line shows `-setInstanceName <name>`; anything not `<inst>` is
the owner's. Do not write the executable name with its `.exe` suffix in a
command - the launch guard blocks the call.

## 6. RAM and disk

```powershell
Get-CimInstance Win32_OperatingSystem | Select-Object @{n='RAM_free_GB';e={[math]::Round($_.FreePhysicalMemory/1MB,1)}},@{n='RAM_total_GB';e={[math]::Round($_.TotalVisibleMemorySize/1MB,1)}}; Get-CimInstance Win32_LogicalDisk -Filter "DriveType=3" | Select-Object DeviceID,@{n='Free_GB';e={[math]::Round($_.FreeSpace/1GB,1)}},@{n='Size_GB';e={[math]::Round($_.Size/1GB,1)}}
```

Compare with the charter `budget` (`memory_peak_gb`, `disk_delta_gb`,
`abort_criteria`). A trend projecting past a line is an escalation
(`docs/AGENT_OPERATIONS.md`, "Working practices": escalate rather than work
around), not a note.

## 7. Report

```
verdict   : <ok|incomplete|blocked|absent>  (verify exit <n>)
stages    : <key:status ...>   components <n> / cameras <n>  modelled <n>  exported <n>
blocking  : <each line verbatim, or none>
run state : <RUN_STATE.json contents | not yet produced (roadmap Phase 2)>
instance  : <inst>  progress: <last line>  errors: <empty | first line>  lock: <held|free>
processes : <pid instance start | none>   tasks running: <names | none>
resources : RAM <free>/<total> GB   disk <drive> <free>/<size> GB   vs budget <...>
newest log: <path> <mtime>  (tail quoted above)
```

## This skill must NEVER

- kill, quit, pause, abort, or delegate to any process or instance;
- delete, move, or clear anything - `progress_*`/`errors_*`/`results_*`
  are cleared only by `RealityScanCLI` pre-run (hard rule 4);
- launch a stage, a scheduled task, or RealityScan;
- flip `confirmed: false`, edit a charter, or write into `<ws>`;
- turn a `blocked` verdict into a recommendation to proceed.
