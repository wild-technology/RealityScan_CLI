---
name: status
description: Read-only state of a run - use whenever the owner asks "where are we", "is it done", "did it work", "status", "what is running", "is it stuck", or wants a verdict on a results workspace. Runs the verify oracle, reads RUN_STATE.json and the instance marker files, reports RAM/disk. Never kills, deletes, clears or launches anything.
---

# Status - read, report, never act

`python` = the interpreter with the deps. Say what you are about to do in
one line, run the steps, report the block in sec.4.

## 1. The oracle and the run state (one command)

```bash
python rs.py status --charter <C>            # or: --workspace <ws> [--instance <inst>]
```

Prints the verify verdict (`ok|incomplete|blocked|absent`, exit code =
verify's), stage statuses, component/camera counts, every `blocking` line,
`RUN_STATE.json` (`status` prepared|running|done|failed, stage, task,
started, log, launcher exit code when the run ended), the instance's marker
files (`progress_<inst>.txt` last line + age; `errors_<inst>.txt` size and
FIRST line - it is STICKY for the session; lock held or free) and the three
newest logs. `--json` for the raw payload.

**`blocked` is stop-and-ask.** Quote each line verbatim; never re-run, "fix"
or push past it. `incomplete` = not done yet, not failed. A progress line
ending in `#timeout` means the instance hung. Never issue `-getStatus`
yourself - the launch guard refuses the executable; the marker files are
the read.

## 2. Processes and the scheduled task (identify, never touch) - Windows

```powershell
Get-CimInstance Win32_Process -Filter "Name LIKE 'RealityScan%'" | Select-Object ProcessId,CreationDate,CommandLine
schtasks /Query /TN "<task from RUN_STATE>" /FO LIST /V
```

The command line shows `-setInstanceName <name>`; anything not the charter's
instance is the owner's. Do not write the executable name with its `.exe`
suffix in a command (the launch guard blocks it).

## 3. RAM and disk against the charter budget - Windows

```powershell
Get-CimInstance Win32_OperatingSystem | Select-Object @{n='RAM_free_GB';e={[math]::Round($_.FreePhysicalMemory/1MB,1)}},@{n='RAM_total_GB';e={[math]::Round($_.TotalVisibleMemorySize/1MB,1)}}; Get-CimInstance Win32_LogicalDisk -Filter "DriveType=3" | Select-Object DeviceID,@{n='Free_GB';e={[math]::Round($_.FreeSpace/1GB,1)}}
```

A trend projecting past `budget.memory_peak_gb` / the disk floor is an
escalation, not a note (`docs/AGENT_OPERATIONS.md`, "Escalate").

## 4. Report

```
verdict   : <ok|incomplete|blocked|absent>  (verify exit <n>)
stages    : <key:status ...>   components <n> / cameras <n>  modelled <n>  exported <n>
blocking  : <each line verbatim, or none>
run state : <status> stage=<..> task=<..> started=<..> log=<..>  | none
instance  : <inst>  progress: <last line> (age)  errors: <bytes, first line>  lock: <held|free>
processes : <pid instance start | none>   task: <schtasks status | none>
resources : RAM <free>/<total> GB   disk <drive> <free> GB   vs budget <...>
```

## This skill must NEVER

kill, quit, pause, abort or delegate to any process or instance; delete,
move or clear anything (`progress_*`/`errors_*`/`results_*` are cleared only
by `RealityScanCLI`); launch a stage, a task or RealityScan; flip
`confirmed: false`, edit a charter or write into `<ws>`; turn a `blocked`
verdict into a recommendation to proceed.
