#!/usr/bin/env python3
"""rs - the ONE command surface for the Claude-guided lane.

    python rs.py charter   init|validate|check ...     (modules.run_charter)
    python rs.py plan      --charter C [--validate|--json]   (modules.run_plan)
    python rs.py preflight --charter C [--json]        (modules.preflight)
    python rs.py verify    --workspace W [--json]      (modules.verify)
    python rs.py status    --charter C | --workspace W [--json]   read-only
    python rs.py run       --charter C [--stages a,b] [--dry-run] [--foreground]
    python rs.py launch    --charter C [--stages a,b] [--task-name N] [--start HH:MM]

A thin facade: no logic moved. ``charter``/``plan``/``preflight``/``verify``
forward their arguments to the module they name. The three subcommands
that ARE new code:

``run``     executes the plan's commands in order, headless (stdin closed,
            stdout to ``<results>/_agent/logs/``), writing ``RUN_STATE.json``
            before and after every stage, re-resolving the export command
            at launch time, and stopping at the first failure. It refuses a
            charter that is unsigned or whose preflight is not READY (the
            owner must answer the questions first - never infer them). From
            an agent harness (``CLAUDECODE`` set) it refuses to run
            RealityScan stages in the foreground: those are scheduler-owned
            (mandate 6; a job object killed a 14.4 h run once) - use
            ``launch``. ``--foreground`` is the owner's override.
``launch``  writes a CRLF ``.cmd`` + ``.vbs`` launcher pair under
            ``<results>/_agent/launch/`` that runs ``rs run ... --foreground``
            detached, writes ``RUN_STATE.json`` (status ``prepared``), and
            PRINTS the exact ``schtasks`` commands. It never calls schtasks
            itself: registering a task is an owner-approved action (the
            ``.claude/settings.json`` ask-list), so the agent runs the
            printed command and the approval gate fires.
``status``  read-only: the verify oracle, RUN_STATE.json, the instance's
            marker files and the newest logs. Never launches, kills, or
            clears anything.

Every subcommand is ASCII-only on stdout (the cp1252 console) and returns
the exit code of the module it drove.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from uuid import uuid4

REPO = Path(__file__).resolve().parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from modules import run_charter as _charter_mod  # noqa: E402
from modules import run_plan as _plan_mod  # noqa: E402
from modules import verify as _verify_mod  # noqa: E402
from modules.preflight import preflight_charter, format_text as _preflight_text  # noqa: E402
from modules.run_charter import CharterError, RunCharter, load_charter  # noqa: E402
from modules.run_plan import (build_plan, refresh_export_command,  # noqa: E402
                              session_from_charter)
from modules.realityscan_interface.realityscan_cli import (  # noqa: E402
    CMD_METACHARACTERS, ERRORS_DIR)

RUN_STATE_NAME = "RUN_STATE.json"
#: Set by Claude Code in every Bash tool shell. Its presence means "this
#: process tree dies with the session" - the job-object kill class.
HARNESS_ENV = "CLAUDECODE"
#: Set by the .cmd launcher rs launch writes: this run IS the scheduled
#: task's run, so RUN_STATE keeps the task/.rc fields.
LAUNCHER_ENV = "RS_LAUNCHER_RC"
#: Stages whose commands boot RealityScan (run_plan marks them).
#: Status-poll cadence for scheduler-owned runs (owner: every 30 minutes).
POLL_INTERVAL_MIN = 30
EXIT_CHARTER_INVALID = 2
EXIT_NOT_READY = 1
EXIT_HARNESS_REFUSED = 3


# --------------------------------------------------------------- helpers

def _load(charter_path: str) -> tuple[Optional[RunCharter], int]:
    try:
        return load_charter(charter_path), 0
    except CharterError as exc:
        print(f"INVALID charter: {exc}", file=sys.stderr)
        return None, EXIT_CHARTER_INVALID


def _agent_ws(charter: RunCharter) -> Path:
    return Path(charter.agent_workspace or (Path(charter.results_root) / "_agent"))


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    from module_base.atomic_io import replace_file
    replace_file(tmp, path)


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _stamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def _slug(text: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in text)[:48].strip("_") or "stage"


def _stages_arg(value: Optional[str]) -> Optional[list[str]]:
    if not value:
        return None
    return [s.strip() for s in value.split(",") if s.strip()]


def _plan_for(charter: RunCharter, stages: Optional[list[str]]) -> dict:
    session = session_from_charter(charter, stages)
    return build_plan(session, charter), session


def _gate(charter: RunCharter, stages: Optional[list[str]] = None,
          allow_unsigned: bool = False) -> Optional[int]:
    """Signed + preflight READY for THESE stages, else print why + exit code."""
    if not charter.is_signed() and not allow_unsigned:
        print("REFUSED: the charter is not signed off (signed_off.by / .date). "
              "No run before the owner signs.", file=sys.stderr)
        return EXIT_NOT_READY
    report = preflight_charter(charter, stages=stages)
    if report["verdict"] != "ready":
        print(_preflight_text(report))
        print("\nREFUSED: preflight is not READY. Every 'ASK THE OWNER' line "
              "above is a question for the owner - answer them in the charter, "
              "never from a directory listing.", file=sys.stderr)
        return EXIT_NOT_READY
    return None


# ------------------------------------------------------------------- run

def execute_commands(commands: list[dict], agent_ws: Path, charter_path: str,
                     session=None, label: str = "run", resume_cmd: str = "",
                     *, control=None, observer=None) -> int:
    """Run planned commands in order; RUN_STATE.json before/after each.

    ``commands`` are run_plan records ({stage, argv, env, cwd, ...}). Each
    child gets stdin=DEVNULL (an unattended prompt must fail by name, never
    block), stdout+stderr to its own log, and the record's env overlaid on
    the process environment. Stops at the first non-zero exit.
    """
    from modules.project_runtime import (ExecutionControl, OwnershipUnconfirmed,
                                         capture_child_identity,
                                         require_runtime_release, runtime_event_cursor,
                                         wait_planned_process)

    execution_control = control if control is not None else ExecutionControl()
    logs = agent_ws / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    state_path = agent_ws / RUN_STATE_NAME
    state = _read_json(state_path)
    history = list(state.get("history") or [])
    if not os.environ.get(LAUNCHER_ENV, "").strip():
        # A direct `rs run` is not the launcher's run: an earlier launch's
        # task name and .rc file must not be reported beside this run's
        # state (review finding bugs-surface F8 - two monitors disagreeing).
        for key in ("task", "rc_file", "launcher_cmd", "launcher_vbs",
                    "prepared", "stages", "launcher_exit"):
            state.pop(key, None)
    state.update({"schema": 1, "charter": charter_path, "label": label,
                  "status": "running", "resume": resume_cmd,
                  "history": history})
    for record in commands:
        if execution_control.cancellation_requested:
            state.update(status="cancelled", ownership_released=True,
                         finished=time.strftime("%Y-%m-%d %H:%M:%S"))
            _write_json(state_path, state)
            return 130
        argv = list(record["argv"])
        if session is not None:
            argv = refresh_export_command(argv, session)
        event_cursor = runtime_event_cursor(record)
        stamp = _stamp()
        log_path = logs / f"{_slug(record['stage'])}_{stamp}_{uuid4().hex[:12]}.log"
        started = time.strftime("%Y-%m-%d %H:%M:%S")
        state.update({"stage": record["stage"], "argv": argv,
                      "env_keys": sorted(record.get("env") or {}),
                      "started": started, "log": str(log_path),
                      "pid": None, "returncode": None, "finished": None,
                      "status": "running", "ownership_released": False,
                      "launch_attempted": False, "child_identity": None,
                      "needs_realityscan": bool(record.get("needs_realityscan")),
                      "project_id": record.get("project_id"),
                      "project_attempt_id": record.get("project_attempt_id"),
                      "runtime_event_cursor": {"offset": event_cursor.offset, "identity": event_cursor.identity},
                      "runtime": {key: (record.get("env") or {}).get(key) for key in
                                  ("RS_RUN_ID", "RS_RUNTIME_ROOT", "RS_ERRORS_DIR", "RS_CONTROL_FILE", "RS_EVENT_FILE", "RS_INSTANCE", "RS_EXECUTABLE")}})
        _write_json(state_path, state)
        print(f"== {record['stage']}\n   log: {log_path}")
        env = dict(os.environ)
        env.update({k: str(v) for k, v in (record.get("env") or {}).items()})
        proc = None
        launch_attempted = False
        child_reaped = False

        def unconfirmed(cause, message):
            # Best-effort instrumentation must never replace this exception
            # with OSError/TypeError that the controller interprets as release.
            state.update(status="ownership_unconfirmed", ownership_released=False,
                         finished=None, returncode=None, error=message,
                         launch_attempted=launch_attempted)
            try:
                _write_json(state_path, state)
            except BaseException:
                pass  # The previously persisted running journal remains armed.
            raise OwnershipUnconfirmed(message, process=proc, record=record,
                                       log_path=log_path) from cause

        def await_owned():
            try:
                code = wait_planned_process(proc, record, log_path, execution_control,
                                            observer, cursor=event_cursor)
                if type(code) is not int:
                    raise RuntimeError("Monitor returned no confirmed integer exit code")
                return code
            except BaseException as exc:
                unconfirmed(exc, "Owned child termination could not be confirmed; reconcile before restarting")

        try:
            with open(log_path, "x", encoding="utf-8", errors="replace") as log:
                launch_attempted = True
                proc = subprocess.Popen(argv, cwd=record.get("cwd") or str(REPO),
                                        env=env, stdin=subprocess.DEVNULL,
                                        stdout=log, stderr=subprocess.STDOUT)
                state["pid"] = proc.pid
                state["child_identity"] = capture_child_identity(proc)
                state["launch_attempted"] = True
                _write_json(state_path, state)
                rc = await_owned()
                child_reaped = True
        except BaseException as exc:
            if isinstance(exc, OwnershipUnconfirmed):
                raise  # Never retry an unrecoverable wait in a busy loop.
            if proc is None:
                # File-not-found/access-denied Popen failures prove no child was
                # created. An interrupted/unexpected constructor does not.
                known_no_child = not launch_attempted or isinstance(exc, (FileNotFoundError, PermissionError))
                if not known_no_child:
                    unconfirmed(exc, "Launch failed before a child handle was returned; ownership must be reconciled")
                state["ownership_released"] = True
                status = "cancelled" if isinstance(exc, KeyboardInterrupt) else "failed"
                _record_abort(state, history, record, log_path, status,
                              f"{type(exc).__name__}: {exc}", state_path)
                return 130 if status == "cancelled" else 1
            if isinstance(exc, KeyboardInterrupt):
                try:
                    execution_control.request_cancel("abort_current")
                except BaseException as request_error:
                    unconfirmed(request_error, "Unable to request abort of the owned child; ownership remains unconfirmed")
                state.update(status="cancel_requested", finished=None, ownership_released=False)
                try:
                    _write_json(state_path, state)
                except BaseException:
                    pass  # Keep monitoring even if cancellation logging fails.
            # State/log instrumentation can fail after launch. One guarded
            # recovery wait suffices; its own failure becomes unconfirmed.
            if not child_reaped:
                rc = await_owned()
                child_reaped = True
        try:
            require_runtime_release(record, cursor=event_cursor)
        except BaseException as exc:
            unconfirmed(exc, "Runtime ownership release is unconfirmed; reconcile before restarting")
        finished = time.strftime("%Y-%m-%d %H:%M:%S")
        entry = {"stage": record["stage"], "started": started,
                 "finished": finished, "returncode": rc, "log": str(log_path)}
        history.append(entry)
        state.update({"returncode": rc, "finished": finished,
                      "status": "done" if rc == 0 else "failed", "ownership_released": True,
                      "history": history})
        _write_json(state_path, state)
        print(f"   exit {rc} ({'ok' if rc == 0 else 'FAILED - stopping'})")
        if rc != 0:
            return 1
    return 0


def _record_abort(state: dict, history: list, record: dict, log_path: Path,
                  status: str, error: str, state_path: Path) -> None:
    finished = time.strftime("%Y-%m-%d %H:%M:%S")
    history.append({"stage": record["stage"], "started": state.get("started"),
                    "finished": finished, "returncode": None, "error": error,
                    "log": str(log_path)})
    state.update({"returncode": None, "finished": finished, "status": status,
                  "error": error, "history": history})
    _write_json(state_path, state)


def cmd_run(args) -> int:
    charter, rc = _load(args.charter)
    if charter is None:
        return rc
    stages = _stages_arg(args.stages)
    if not args.dry_run:
        refused = _gate(charter, stages)
        if refused:
            return refused
    try:
        plan, session = _plan_for(charter, stages)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return EXIT_NOT_READY
    rejected = [c for c in plan["commands"] if c.get("parses") is False]
    if rejected:
        for c in rejected:
            print(f"REJECTED: {c.get('parse_error')}", file=sys.stderr)
        return EXIT_NOT_READY
    if not plan["commands"]:
        print("nothing to run: the plan is empty", file=sys.stderr)
        return EXIT_NOT_READY
    if args.dry_run:
        print(_plan_mod.format_text(plan))
        print("DRY RUN: nothing executed, nothing written.")
        return 0
    needs_rs = [c["stage"] for c in plan["commands"] if c.get("needs_realityscan")]
    if needs_rs and args.foreground and os.environ.get(HARNESS_ENV):
        # --foreground is the OWNER's override for a terminal THEY own. An
        # agent shell always carries CLAUDECODE, and `Bash(python rs.py *)`
        # is allow-listed, so the flag typed by an agent would boot
        # RealityScan under the harness job object with no gate at all
        # (review finding H9). The owner's own terminal has no CLAUDECODE.
        print("REFUSED: --foreground from an agent harness shell "
              f"({HARNESS_ENV} is set). The owner runs this in a terminal they "
              "own; the agent uses\n"
              f"    python rs.py launch --charter \"{charter.path}\""
              + (f" --stages {args.stages}" if args.stages else ""),
              file=sys.stderr)
        return EXIT_HARNESS_REFUSED
    if needs_rs and os.environ.get(HARNESS_ENV) and not args.foreground:
        print("REFUSED: this shell belongs to an agent harness "
              f"({HARNESS_ENV} is set) and the plan boots RealityScan for: "
              f"{', '.join(needs_rs)}. Long runs are SCHEDULER-OWNED "
              "(docs/AGENT_OPERATIONS.md mandate 6): use\n"
              f"    python rs.py launch --charter \"{charter.path}\""
              + (f" --stages {args.stages}" if args.stages else "")
              + "\nand run the printed schtasks commands. --foreground is the "
                "owner's override for a terminal they own.", file=sys.stderr)
        return EXIT_HARNESS_REFUSED
    agent_ws = _agent_ws(charter)
    resume = (f'python rs.py run --charter "{charter.path}"'
              + (f" --stages {args.stages}" if args.stages else "")
              + (" --foreground" if args.foreground else ""))
    return execute_commands(plan["commands"], agent_ws, str(charter.path),
                            session=session, label=charter.label,
                            resume_cmd=resume)


# ---------------------------------------------------------------- launch

def _assert_cmd_safe(*values: str) -> None:
    for value in values:
        bad = sorted(set(str(value)) & CMD_METACHARACTERS)
        if bad:
            raise ValueError(
                f"{value!r} contains cmd metacharacter(s) {bad}; cmd would "
                "split, eat or execute them silently (CLAUDE.md hard rule 8). "
                "Rename the path or move the charter.")
        outside = sorted({ch for ch in str(value) if not 32 <= ord(ch) <= 126})
        if outside:
            # cmd reads a batch file in the OEM code page and WSH reads a
            # .vbs as ANSI; a UTF-8 launcher naming an e-acute path simply
            # does not find it (demonstrated 2026-09-05, review finding H4).
            # Refuse, never escape.
            raise ValueError(
                f"{value!r} contains non-ASCII character(s) {outside}; the "
                "CRLF launcher pair is read in the OEM/ANSI code pages and "
                "would silently miss the path. Use an ASCII path and task name.")


def write_launcher(charter: RunCharter, charter_path: str,
                   stages: Optional[list[str]], task_name: str,
                   python: str = sys.executable) -> dict:
    """The CRLF .cmd/.vbs pair + RUN_STATE (prepared). Returns their paths."""
    # Absolute, always: Task Scheduler resolves /TR against ITS working
    # directory, and RUN_STATE.json is read from anywhere (review finding H5).
    agent_ws = _agent_ws(charter).resolve()
    launch_dir = agent_ws / "launch"
    logs = agent_ws / "logs"
    launch_dir.mkdir(parents=True, exist_ok=True)
    logs.mkdir(parents=True, exist_ok=True)
    stamp = _stamp()
    cmd_path = launch_dir / f"{_slug(task_name)}_{stamp}.cmd"
    vbs_path = launch_dir / f"{_slug(task_name)}_{stamp}.vbs"
    rc_path = launch_dir / f"{_slug(task_name)}_{stamp}.rc"
    log_path = logs / f"launch_{_slug(task_name)}_{stamp}.log"
    stage_arg = ",".join(stages) if stages else ""
    # The stage list is OUR token grammar, not a path: commas are its
    # separator and it is written quoted, so it is checked against the
    # grammar rather than the cmd metacharacter set (which lists ',').
    if stage_arg and not re.fullmatch(r"[a-z_]+(,[a-z_]+)*", stage_arg):
        raise ValueError(f"--stages {stage_arg!r}: stage names are lowercase "
                         "words separated by commas, nothing else")
    _assert_cmd_safe(str(REPO), charter_path, str(agent_ws), python, task_name)
    run_line = (f'"{python}" "{REPO / "rs.py"}" run --charter "{charter_path}"'
                + (f' --stages "{stage_arg}"' if stage_arg else "")
                + f' --foreground > "{log_path}" 2>&1')
    cmd_lines = [
        "@echo off",
        f":: rs launch {stamp} - scheduler-owned run of {charter.label}",
        f':: charter: {charter_path}',
        f'cd /d "{REPO}"',
        f'set "RS_RUN_CHARTER={charter_path}"',
        'set "RS_NO_SETTINGS_INHERITANCE=1"',
        'set "PYTHONIOENCODING=utf-8"',
        f'set "{LAUNCHER_ENV}={rc_path}"',
        run_line,
        f'echo %errorlevel% > "{rc_path}"',
        "",
    ]
    vbs_lines = [
        "' rs launch: run the .cmd hidden and synchronously (no console window)",
        'Set sh = CreateObject("WScript.Shell")',
        f'sh.Run """{cmd_path}""", 0, True',
        "",
    ]
    cmd_path.write_bytes("\r\n".join(cmd_lines).encode("utf-8"))
    vbs_path.write_bytes("\r\n".join(vbs_lines).encode("utf-8"))
    state_path = agent_ws / RUN_STATE_NAME
    state = _read_json(state_path)
    state.update({
        "schema": 1, "charter": charter_path, "label": charter.label,
        "status": "prepared", "task": task_name, "stages": stages or "all",
        "launcher_cmd": str(cmd_path), "launcher_vbs": str(vbs_path),
        "rc_file": str(rc_path), "log": str(log_path),
        "budget": charter.budget, "poll_interval_min": POLL_INTERVAL_MIN,
        "prepared": time.strftime("%Y-%m-%d %H:%M:%S"),
        "resume": f'python rs.py run --charter "{charter_path}"'
                  + (f' --stages {stage_arg}' if stage_arg else "") + " --foreground",
    })
    _write_json(state_path, state)
    return {"cmd": cmd_path, "vbs": vbs_path, "rc": rc_path, "log": log_path,
            "state": state_path}


def cmd_launch(args) -> int:
    charter, rc = _load(args.charter)
    if charter is None:
        return rc
    refused = _gate(charter)
    if refused:
        return refused
    stages = _stages_arg(args.stages)
    try:
        plan, _session = _plan_for(charter, stages)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return EXIT_NOT_READY
    if any(c.get("parses") is False for c in plan["commands"]) or not plan["commands"]:
        print("REFUSED: the plan is empty or a command is rejected by main.py's "
              "parser (see `rs plan --validate`).", file=sys.stderr)
        return EXIT_NOT_READY
    task = args.task_name or f"RS_{charter.label}_{_stamp()}"
    try:
        paths = write_launcher(charter, str(charter.path), stages, task)
    except ValueError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return EXIT_NOT_READY
    start = args.start or (datetime.now() + timedelta(minutes=2)).strftime("%H:%M")
    print(f"launcher : {paths['cmd']}")
    print(f"vbs shim : {paths['vbs']}")
    print(f"run log  : {paths['log']}")
    print(f"exit code: {paths['rc']}  (written when the run ends)")
    print(f"RUN_STATE: {paths['state']}  (status prepared -> running -> done|failed)")
    vbs = paths["vbs"]
    print("\nNOT executed by rs.py - registering a task is an owner-approved "
          "action. Run the three lines for YOUR shell, in order (Windows, the "
          "box that owns the data). The same line does not survive every shell "
          "(review finding H1): Git Bash turns a single leading slash into a "
          "path, PowerShell does not honour backslash-quote.")
    print("  cmd.exe:")
    print(f'    schtasks /Create /TN "{task}" /TR "wscript.exe //B \\"{vbs}\\"" '
          f'/SC ONCE /ST {start} /F')
    print(f'    schtasks /Run /TN "{task}"')
    print(f'    schtasks /Query /TN "{task}" /FO LIST /V')
    print("  PowerShell tool:")
    print(f"    schtasks /Create /TN \"{task}\" /TR 'wscript.exe //B \"{vbs}\"' "
          f"/SC ONCE /ST {start} /F")
    print(f'    schtasks /Run /TN "{task}"')
    print(f'    schtasks /Query /TN "{task}" /FO LIST /V')
    print("  Bash tool (Git Bash; a doubled slash survives as one):")
    print(f'    schtasks //Create //TN "{task}" //TR "wscript.exe //B \\"{vbs}\\"" '
          f'//SC ONCE //ST {start} //F')
    print(f'    schtasks //Run //TN "{task}"')
    print(f'    schtasks //Query //TN "{task}" //FO LIST //V')
    print("\nThen start the 30-minute monitor (a small read-only worker; it "
          "reports, never acts) - paste as one line:")
    print(f'  /loop 30m Poll the run with the run-monitor agent (instance '
          f'{charter.rs_instance or "<instance>"}, workspace '
          f'{charter.results_root}, charter {args.charter}); report only its '
          f'verdict block; if the verdict is failed or stalled, or a budget '
          f'line appears, stop the loop and tell the owner.')
    print(f'Manual poll:  python rs.py status --charter "{charter.path}"')
    return 0


# ---------------------------------------------------------------- status

def _tail(path: Path, n: int = 1) -> list[str]:
    try:
        data = path.read_bytes()[-4096:].decode("utf-8", errors="replace")
    except OSError:
        return []
    lines = [ln.strip() for ln in data.splitlines() if ln.strip()]
    return lines[-n:]


def _age(path: Path) -> str:
    try:
        secs = int(time.time() - path.stat().st_mtime)
    except OSError:
        return "?"
    return f"{secs // 3600}:{(secs % 3600) // 60:02d}"


def _pid_alive(pid) -> bool:
    """True when a process with this id is still running (Windows-aware)."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if os.name != "nt":
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    import ctypes  # noqa: PLC0415
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(0x1000, False, pid)   # QUERY_LIMITED_INFORMATION
    if not handle:
        return False
    try:
        code = ctypes.c_ulong()
        ok = kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        return bool(ok) and code.value == 259                 # STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def _budget_block(charter: RunCharter, workspace: str, state: Optional[dict]) -> dict:
    """The charter's budget beside what can be read now: elapsed hours and
    free disk on the results and cache volumes. The RAM line is the
    monitor's to read; this block only states the number to compare against."""
    b = charter.budget or {}
    started = (state or {}).get("started") or (state or {}).get("prepared")
    elapsed = None
    if started:
        try:
            elapsed = (time.time() - time.mktime(
                time.strptime(str(started), "%Y-%m-%d %H:%M:%S"))) / 3600.0
        except (ValueError, OverflowError):
            elapsed = None
    free: dict[str, Optional[float]] = {}
    for label, path in (("results", workspace), ("cache", charter.rs_cache_dir)):
        if not path:
            continue
        anchor = Path(path)
        while not anchor.exists() and anchor.parent != anchor:
            anchor = anchor.parent
        try:
            free[label] = round(shutil.disk_usage(anchor).free / 1024 ** 3, 1) \
                if anchor.exists() else None
        except OSError:
            free[label] = None
    try:
        expected = float(b.get("expected_hours") or 0)
    except (TypeError, ValueError):
        expected = 0.0
    return {"expected_hours": b.get("expected_hours"),
            "elapsed_hours": round(elapsed, 2) if elapsed is not None else None,
            "over_hours": bool(elapsed is not None and expected > 0 and elapsed > expected),
            "memory_peak_gb": b.get("memory_peak_gb"),
            "disk_delta_gb": b.get("disk_delta_gb"),
            "free_gb": free,
            "abort_criteria": b.get("abort_criteria")}


def _status_marker_root(workspace: str, agent_ws: Optional[Path], state: Optional[dict],
                        instance: Optional[str]) -> tuple[Path, Optional[str], str]:
    """Select read-only marker evidence; persisted runtime paths never fall back.

    Legacy state without an attempt channel can still use checkout markers.
    Runtime state must bind the requested instance and owned project/proc/tmp
    path before any marker file is read. No directory is implicitly created.
    """
    if instance is not None and (not isinstance(instance, str)
            or not re.fullmatch(r'[A-Za-z0-9_.-]+', instance) or instance in ('.', '..')):
        raise ValueError('Invalid requested marker instance')
    if state is None or 'runtime' not in state:
        if state and (state.get('project_id') or state.get('project_attempt_id')):
            raise ValueError('Project run state has no persisted runtime marker binding')
        return Path(ERRORS_DIR), instance, 'legacy'
    runtime = state['runtime']
    if not isinstance(runtime, dict) or not runtime:
        raise ValueError('Persisted runtime must be a nonempty object')
    recorded_instance = runtime.get('RS_INSTANCE')
    if recorded_instance is not None:
        if (not isinstance(recorded_instance, str) or not re.fullmatch(r'[A-Za-z0-9_.-]+', recorded_instance)
                or recorded_instance in ('.', '..')):
            raise ValueError('Invalid persisted marker instance')
        if instance is not None and recorded_instance.casefold() != instance.casefold():
            raise ValueError('Requested instance does not match persisted runtime instance')
        instance = recorded_instance
    channel_keys = ('RS_RUN_ID', 'RS_RUNTIME_ROOT', 'RS_ERRORS_DIR', 'RS_CONTROL_FILE', 'RS_EVENT_FILE')
    if (not any(runtime.get(key) is not None for key in channel_keys)
            and not state.get('project_id') and not state.get('project_attempt_id')):
        if not {'RS_RUN_ID', 'RS_RUNTIME_ROOT', 'RS_CONTROL_FILE', 'RS_EVENT_FILE',
                'RS_INSTANCE', 'RS_EXECUTABLE'}.issubset(runtime):
            raise ValueError('Persisted runtime is missing its channel fields')
        return Path(ERRORS_DIR), instance, 'legacy'
    run_id, root, markers = (runtime.get(key) for key in ('RS_RUN_ID', 'RS_RUNTIME_ROOT', 'RS_ERRORS_DIR'))
    if (not isinstance(run_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', run_id)
            or not isinstance(root, str) or not root or not Path(root).is_absolute()
            or not isinstance(markers, str) or not markers or not Path(markers).is_absolute()
            or recorded_instance is None):
        raise ValueError('Runtime marker binding requires run ID, instance and absolute root/marker paths')
    root, markers = Path(root), Path(markers)
    if ('..' in root.parts or '..' in markers.parts or root.name != run_id
            or root.parent.name.casefold() != 'tmp' or root.parent.parent.name.casefold() != 'proc'
            or markers != root / 'markers'):
        raise ValueError('Runtime marker root must match project/proc/tmp/<RS_RUN_ID>/markers')
    project = root.parent.parent.parent
    work = Path(workspace).absolute()
    if not (work == project or work.is_relative_to(project / 'proc')):
        raise ValueError('Runtime marker root belongs to a different project/workspace')
    if agent_ws is not None and not agent_ws.absolute().is_relative_to(work):
        raise ValueError('Run state is outside the requested workspace')
    for leaf in (markers, work, agent_ws):
        if leaf is None:
            continue
        for path in (leaf, *leaf.parents):
            if path.is_symlink() or path.is_junction():
                raise ValueError('Runtime marker/state paths must not be redirected')
            if path.exists() and not path.is_dir():
                raise ValueError('Runtime marker/state parent is not a directory')
    return markers, instance, 'runtime'


def status_report(workspace: str, agent_ws: Optional[Path],
                  instance: Optional[str],
                  charter: Optional[RunCharter] = None) -> dict:
    if charter is None:
        native = _project_status_report(workspace, instance)
        if native is not None:
            return native
    report: dict = {"schema": 1, "workspace": workspace}
    verify = _verify_mod.verify_workspace(workspace)
    report["verify"] = {k: verify.get(k) for k in
                        ("verdict", "counts", "blocking", "incomplete")}
    report["verify_exit"] = _verify_mod.EXIT_CODES[verify["verdict"]]
    report["stages"] = {k: v["status"] for k, v in (verify.get("stages") or {}).items()}
    state = None
    state_error = None
    if agent_ws is not None:
        state_path = agent_ws / RUN_STATE_NAME
        try:
            if (state_path.is_symlink() or state_path.is_junction()
                    or (state_path.exists() and state_path.stat().st_nlink != 1)):
                raise ValueError('Run state is redirected or hardlinked; marker ownership is unconfirmed')
            state = _read_json(state_path) if state_path.is_file() else None
            if state_path.exists() and not state:
                raise ValueError('Run state is unreadable, malformed or empty; marker ownership is unconfirmed')
        except (OSError, ValueError) as exc:
            state_error = str(exc)
            report['run_state_error'] = state_error
        if state and state.get("rc_file") and Path(state["rc_file"]).is_file():
            rc_text = _tail(Path(state["rc_file"]))
            if rc_text:
                state["launcher_exit"] = rc_text[0]
        if state and state.get("status") == "running":
            alive = _pid_alive(state.get("pid"))
            state["pid_alive"] = alive
            if not alive:
                state["status_note"] = ("STALE: RUN_STATE says running but the "
                                        "recorded Python PID is absent. RealityScan ownership "
                                        "is unconfirmed; reconcile before restarting.")
        report["run_state"] = state
        report["run_state_path"] = str(state_path)
        if charter is not None:
            report["budget"] = _budget_block(charter, workspace, state)
    try:
        if state_error:
            raise ValueError(state_error)
        errors_dir, selected_instance, marker_source = _status_marker_root(workspace, agent_ws, state, instance)
        instance = selected_instance
        if instance:
            report['instance'] = _status_markers(errors_dir, instance, marker_source)
        marker_error = None
    except (OSError, ValueError, TypeError) as exc:
        errors_dir, marker_source, marker_error = None, 'unconfirmed', str(exc)
        report['verify']['blocking'] = list(report['verify'].get('blocking') or []) + [marker_error]
        report['verify']['verdict'] = 'blocked'
        report['verify_exit'] = _verify_mod.EXIT_CODES['blocked']
    report['marker_source'] = marker_source
    if marker_error:
        report['instance'] = dict(name=instance, progress=None, progress_age=None, errors_bytes=None,
                                  errors_first_line=None, lock_held=None, marker_root=None,
                                  marker_status='unconfirmed', diagnostic=marker_error)
    newest = []
    for folder in (Path(workspace) / "logs",
                   *( [agent_ws / "logs"] if agent_ws else [] ),
                   Path(workspace) / "merged" / "logs"):
        if folder.is_dir():
            newest += [p for p in folder.iterdir() if p.is_file()]
    newest.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    report["newest_logs"] = [{"path": str(p), "age": _age(p)} for p in newest[:3]]
    return report


def _project_status_json(project, relative):
    """Read attributable launch evidence using the project's path policy."""
    path = project.resolve_path(relative)
    for parent in (path.parent, *path.parent.parents):
        if parent.is_symlink() or parent.is_junction():
            raise ValueError('Project status evidence directory is redirected')
    if (not path.is_file() or path.is_symlink() or path.is_junction()
            or path.stat().st_nlink != 1):
        raise ValueError(f'Project status evidence is missing or aliased: {relative}')
    value = _read_json(path)
    if not value:
        raise ValueError(f'Project status evidence must be a nonempty object: {relative}')
    return path, value


def _project_status_report(workspace, instance):
    """Resolve native attempts by identity, never by filesystem timestamps.

    ProjectDocument supplies schema, source/path and output validation. Launch
    bindings mirror ProjectController.recover_project; terminal RS evidence
    uses its existing require_runtime_release oracle. No recovery is performed.
    Unregistered probe/census artifacts are never stage or completion evidence.
    """
    from modules.project_workspace import ProjectDocument
    from modules.project_runtime import OwnershipUnconfirmed, require_runtime_release

    root = Path(workspace).absolute()
    documents = sorted(root.glob('*.rovscan'))
    if not documents:
        return None
    blocking, incomplete = [], []
    report = dict(schema=1, workspace=str(root), status_source='project', stages={},
                  run_state=None, run_state_path=str(root / 'proc' / '_agent' / RUN_STATE_NAME),
                  marker_source='unconfirmed', newest_logs=[], executions=[],
                  instance=dict(name=instance, marker_status='unconfirmed', lock_held=None,
                                diagnostic='No attributable runtime marker evidence'))
    counts = dict(components=0, cameras=0, modelled=0, exported=0, registered_outputs=0,
                  verified_outputs=0)
    try:
        if len(documents) != 1:
            raise ValueError('Multiple project documents at workspace root; project identity is ambiguous')
        project = ProjectDocument.load(documents[0])
        if project.root != root:
            raise ValueError('Project document belongs to a different workspace root')
        data = project.to_dict()
        report.update(project_id=project.project_id, project_document=str(documents[0]),
                      stages={name: entry['state'] for name, entry in data['stages'].items()})
        current = {entry['attempts'][-1]['id']: name for name, entry in data['stages'].items()
                   if entry['attempts'] and entry['state'] != 'invalidated'}
        running = {attempt: name for attempt, name in current.items()
                   if data['stages'][name]['state'] == 'running'}
        selected = running or current
        if not current:
            incomplete.append('No native pipeline attempt is recorded; project is pending')
        for name, entry in data['stages'].items():
            if entry['state'] in ('failed', 'interrupted'):
                blocking.append(f"{name}: {entry['state']}; controller reconciliation/restart required")
            elif entry['state'] not in ('succeeded', 'skipped'):
                incomplete.append(f"{name}: {entry['state']}")
        outputs = project.verify_outputs()
        counts['registered_outputs'] = sum(output['valid'] for output in outputs)
        counts['verified_outputs'] = sum(output['valid'] and output['status'] == 'ok' for output in outputs)
        for output in outputs:
            if output['valid'] and output['status'] != 'ok':
                blocking.append(f"Registered output {output['path']}: {output['status']}")
        report['outputs'] = outputs
        plans = {}
        # With no attempts, even plausible probe files are irrelevant.
        if selected:
            for path in sorted(project.resolve_path('metadata/plans').glob('*.json')):
                _, plan = _project_status_json(project, path)
                attempt = plan.get('project_attempt_id')
                if not isinstance(attempt, str):
                    raise ValueError('Launch record has no valid project attempt ID')
                if plan.get('project_id') != project.project_id or attempt not in selected:
                    continue
                if attempt in plans:
                    raise ValueError('Multiple launch records for the same project attempt are ambiguous')
                plans[attempt] = plan
        for attempt, stage in selected.items():
            # Inventory and review run inside the controller, without a driver.
            if attempt not in plans:
                if stage not in ('inventory', 'preprocess'):
                    blocking.append(f'{stage}: no attributable launch record; ownership unconfirmed')
                continue
            plan = plans[attempt]
            label = project.project_id + '/' + attempt
            commands = plan.get('commands')
            if (plan.get('execution_label') != label or not isinstance(commands, list) or not commands
                    or any(not isinstance(c, dict) or c.get('project_id') != project.project_id
                           or c.get('project_attempt_id') != attempt for c in commands)):
                raise ValueError('Launch record commands/label do not match the project attempt')
            if stage in ('align', 'merge', 'model', 'export') and not all(
                    c.get('needs_realityscan') is True for c in commands):
                raise ValueError('RealityScan launch cannot downgrade application ownership evidence')
            state_path, state = _project_status_json(project, plan['run_state'])
            if (state_path.name != RUN_STATE_NAME or state_path.parent.name != '_agent'
                    or not state_path.is_relative_to(root / 'proc')):
                raise ValueError('Native run state must be under project/proc in an _agent directory')
            if (state.get('label') != label or state.get('project_id') != project.project_id
                    or state.get('project_attempt_id') != attempt):
                # Shared journals can be reused by a later recorded attempt.
                # Never adopt that later state as this attempt's evidence.
                if not running and state.get('project_id') == project.project_id and any(
                        state.get('project_attempt_id') == other
                        and state.get('label') == project.project_id + '/' + other
                        and other != attempt for other in current):
                    incomplete.append(f'{stage}: executor journal was superseded; historical release not verified')
                    continue
                raise ValueError('Executor state is not bound to the selected project launch')
            active = [c for c in commands if c.get('stage') == state.get('stage')]
            if len(active) != 1 or not isinstance(active[0].get('env'), dict):
                raise ValueError('Executor command cannot be identified uniquely')
            command = active[0]
            runtime = state.get('runtime')
            keys = ('RS_RUN_ID', 'RS_RUNTIME_ROOT', 'RS_ERRORS_DIR', 'RS_CONTROL_FILE',
                    'RS_EVENT_FILE', 'RS_INSTANCE', 'RS_EXECUTABLE')
            if (not isinstance(runtime, dict) or any(key not in runtime or
                    runtime[key] != command['env'].get(key) for key in keys)):
                raise ValueError('Executor runtime does not match its launch record')
            entry = dict(stage=stage, project_attempt_id=attempt, run_state_path=str(state_path),
                         run_state=state, marker_source='unconfirmed', ownership_released=False)
            if command.get('needs_realityscan'):
                markers, selected_instance, source = _status_marker_root(str(root), state_path.parent, state, instance)
                entry.update(instance=_status_markers(markers, selected_instance, source), marker_source=source)
            if state.get('status') in ('done', 'failed', 'cancelled'):
                if type(state.get('returncode')) is not int or state.get('ownership_released') is not True:
                    raise ValueError('Executor has not confirmed terminal ownership release')
                for record in commands:
                    require_runtime_release(record)
                entry['ownership_released'] = True
            else:
                incomplete.append(f'{stage}: executor ownership is not released')
            report['executions'].append(entry)
        if len(report['executions']) == 1:
            entry = report['executions'][0]
            for key in ('run_state', 'run_state_path', 'marker_source', 'instance'):
                if key in entry:
                    report[key] = entry[key]
        elif len(report['executions']) > 1:
            report.pop('run_state_path', None)
            incomplete.append('Multiple recorded stage executions; inspect executions individually')
        if not outputs:
            incomplete.append('No registered native pipeline outputs')
    except (OSError, ValueError, TypeError, KeyError, OwnershipUnconfirmed) as exc:
        blocking.append(str(exc))
        report['run_state_error'] = str(exc)
    verdict = 'blocked' if blocking else 'incomplete' if incomplete else 'ok'
    report.update(verify=dict(verdict=verdict, counts=counts, blocking=blocking, incomplete=incomplete),
                  verify_exit=_verify_mod.EXIT_CODES[verdict])
    return report


def _status_markers(errors_dir: Path, instance: str, source: str) -> dict:
    """Read only the already-validated marker directory."""
    progress = errors_dir / f"progress_{instance}.txt"
    errors = errors_dir / f"errors_{instance}.txt"
    lock = errors_dir / f"{instance}.lock"
    if source == 'runtime':
        for path in (progress, errors, lock):
            if path.is_symlink() or path.is_junction() or (path.exists() and path.stat().st_nlink != 1):
                raise ValueError('Runtime marker file is redirected or hardlinked')
            if path.exists() and not path.is_file():
                raise ValueError('Runtime marker path is not a regular file')
    return {
        "name": instance,
        "marker_root": str(errors_dir), "marker_status": source,
        "progress": (_tail(progress) or [""])[0] if progress.is_file() else None,
        "progress_age": _age(progress) if progress.is_file() else None,
        "errors_bytes": errors.stat().st_size if errors.is_file() else None,
        "errors_first_line": (_tail(errors, 400)[:1] or [""])[0] if errors.is_file() else None,
        "lock_held": lock.is_file(),
    }


def format_status(report: dict) -> str:
    v = report["verify"]
    counts = v.get("counts") or {}
    lines = [f"workspace : {report['workspace']}",
             f"verdict   : {str(v.get('verdict')).upper()}  (verify exit {report['verify_exit']})",
             "stages    : " + "  ".join(f"{k}:{s}" for k, s in report["stages"].items()),
             f"components: {counts.get('components', 0)} / {counts.get('cameras', 0)} cameras"
             f"  modelled {counts.get('modelled', 0)}  exported {counts.get('exported', 0)}"]
    for b in v.get("blocking") or []:
        lines.append(f"  ! {b}")
    if report.get('status_source') == 'project':
        for detail in v.get('incomplete') or []:
            lines.append(f"  - {detail}")
        for entry in report.get('executions') or []:
            lines.append(f"execution : {entry['stage']}  {entry['run_state_path']}"
                         f"  status={entry['run_state'].get('status')}")
    state = report.get("run_state")
    if report.get('run_state_error'):
        lines.append(f"run state : unconfirmed ({report['run_state_error']})")
    elif state is None and report.get('status_source') == 'project':
        lines.append('run state : no single attributable native executor snapshot')
    elif state is None and "run_state_path" in report:
        lines.append(f"run state : none ({report['run_state_path']} absent)")
    elif state:
        lines.append(f"run state : {state.get('status')}  stage={state.get('stage')}"
                     f"  task={state.get('task')}  started={state.get('started')}")
        lines.append(f"            log={state.get('log')}")
        if state.get("launcher_exit") is not None:
            lines.append(f"            launcher exit code file says: {state['launcher_exit']}")
        if state.get("status_note"):
            lines.append(f"            ! {state['status_note']}")
    budget = report.get("budget")
    if budget:
        free = budget.get("free_gb") or {}
        lines.append(
            f"budget    : expected {budget.get('expected_hours')} h, elapsed "
            f"{budget.get('elapsed_hours') if budget.get('elapsed_hours') is not None else '?'} h"
            + ("  ! OVER the declared hours" if budget.get("over_hours") else "")
            + f"; free results {free.get('results', '?')} GB, cache {free.get('cache', '?')} GB;"
            f" memory line {budget.get('memory_peak_gb')} GB (read the RAM yourself)")
        lines.append(f"            abort: {budget.get('abort_criteria')}")
    inst = report.get("instance")
    if inst and inst.get('marker_status') == 'unconfirmed':
        lines.append(f"instance  : {inst['name'] or '<unconfirmed>'}  markers: unconfirmed")
        lines.append(f"            ! {inst['diagnostic']}; lock: unknown")
    elif inst:
        lines.append(f"instance  : {inst['name']}  progress: {inst['progress'] or '<no progress file>'}"
                     + (f"  (age {inst['progress_age']})" if inst["progress_age"] else ""))
        err = inst["errors_bytes"]
        lines.append(f"            errors_{inst['name']}.txt: "
                     + ("absent" if err is None else f"{err} bytes"
                        + (f" - first line: {inst['errors_first_line']}" if err else ""))
                     + f"   lock: {'held' if inst['lock_held'] else 'free'}")
    for entry in report["newest_logs"]:
        lines.append(f"log       : {entry['path']}  (age {entry['age']})")
    return "\n".join(lines)


def cmd_status(args) -> int:
    agent_ws = None
    instance = args.instance
    if args.charter:
        charter, rc = _load(args.charter)
        if charter is None:
            return rc
        workspace = charter.results_root
        agent_ws = _agent_ws(charter)
        instance = instance or charter.rs_instance or None
    else:
        workspace = args.workspace
        agent_ws = Path(workspace) / "_agent"
        instance = instance or os.environ.get("RS_INSTANCE") or None
    report = status_report(workspace, agent_ws, instance,
                           charter=charter if args.charter else None)
    print(json.dumps(report, indent=2) if args.json else format_status(report))
    return report["verify_exit"]


# ------------------------------------------------------------------ main

def _forward_charter(rest: list[str]) -> int:
    # `rs charter init P` / `validate P` / `check P ...` -> the module's flags
    rest = list(rest)
    if rest and rest[0] in ("init", "validate", "check"):
        rest[0] = "--" + rest[0]
    return _charter_mod.main(rest)


def _forward_preflight(rest: list[str]) -> int:
    from modules import preflight as _preflight_mod  # noqa: PLC0415
    return _preflight_mod.main(list(rest))


#: Subcommands that forward their arguments untouched to a module's main().
#: Dispatched BEFORE argparse: a REMAINDER positional cannot swallow a
#: leading option like ``--charter``, so these never go through the parser.
FORWARDERS = {
    "charter": _forward_charter,
    "plan": lambda rest: _plan_mod.main(list(rest)),
    "preflight": _forward_preflight,
    "verify": lambda rest: _verify_mod.main(list(rest)),
}


def main(argv: Optional[list[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in FORWARDERS:
        return FORWARDERS[argv[0]](argv[1:])

    parser = argparse.ArgumentParser(
        prog="python rs.py",
        description=__doc__.splitlines()[0],
        epilog="charter/plan/preflight/verify forward their remaining "
               "arguments to the module of the same name (see each --help).")
    sub = parser.add_subparsers(dest="command", required=True)

    for name, helptext in (("charter", "scaffold / validate / check a run charter"),
                           ("plan", "the run plan, proven against main.py's parser"),
                           ("preflight", "what the owner must still answer"),
                           ("verify", "did it actually work - census from disk")):
        sub.add_parser(name, help=helptext, add_help=False)

    p = sub.add_parser("status", help="read-only run state (never acts)")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--charter")
    g.add_argument("--workspace")
    p.add_argument("--instance", default=None)
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("run", help="execute the plan, headless, with RUN_STATE")
    p.add_argument("--charter", required=True)
    p.add_argument("--stages", default=None, help="comma-separated subset")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--foreground", action="store_true",
                   help="owner override: run RealityScan stages in THIS shell")

    p = sub.add_parser("launch", help="write a scheduler launcher; prints schtasks")
    p.add_argument("--charter", required=True)
    p.add_argument("--stages", default=None)
    p.add_argument("--task-name", default=None)
    p.add_argument("--start", default=None, help="HH:MM (default: now + 2 min)")

    args = parser.parse_args(argv)
    if args.command == "status":
        return cmd_status(args)
    if args.command == "run":
        return cmd_run(args)
    if args.command == "launch":
        return cmd_launch(args)
    parser.error(f"unknown command {args.command}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
