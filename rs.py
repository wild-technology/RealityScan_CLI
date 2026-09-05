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
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

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
#: Stages whose commands boot RealityScan (run_plan marks them).
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
    os.replace(tmp, path)


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


def _gate(charter: RunCharter, allow_unsigned: bool = False) -> Optional[int]:
    """Signed + preflight READY, else print why and return an exit code."""
    if not charter.is_signed() and not allow_unsigned:
        print("REFUSED: the charter is not signed off (signed_off.by / .date). "
              "No run before the owner signs.", file=sys.stderr)
        return EXIT_NOT_READY
    report = preflight_charter(charter)
    if report["verdict"] != "ready":
        print(_preflight_text(report))
        print("\nREFUSED: preflight is not READY. Every 'ASK THE OWNER' line "
              "above is a question for the owner - answer them in the charter, "
              "never from a directory listing.", file=sys.stderr)
        return EXIT_NOT_READY
    return None


# ------------------------------------------------------------------- run

def execute_commands(commands: list[dict], agent_ws: Path, charter_path: str,
                     session=None, label: str = "run", resume_cmd: str = "") -> int:
    """Run planned commands in order; RUN_STATE.json before/after each.

    ``commands`` are run_plan records ({stage, argv, env, cwd, ...}). Each
    child gets stdin=DEVNULL (an unattended prompt must fail by name, never
    block), stdout+stderr to its own log, and the record's env overlaid on
    the process environment. Stops at the first non-zero exit.
    """
    logs = agent_ws / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    state_path = agent_ws / RUN_STATE_NAME
    state = _read_json(state_path)
    history = list(state.get("history") or [])
    state.update({"schema": 1, "charter": charter_path, "label": label,
                  "status": "running", "resume": resume_cmd,
                  "history": history})
    for record in commands:
        argv = list(record["argv"])
        if session is not None:
            argv = refresh_export_command(argv, session)
        stamp = _stamp()
        log_path = logs / f"{_slug(record['stage'])}_{stamp}.log"
        started = time.strftime("%Y-%m-%d %H:%M:%S")
        state.update({"stage": record["stage"], "argv": argv,
                      "env_keys": sorted(record.get("env") or {}),
                      "started": started, "log": str(log_path),
                      "pid": None, "returncode": None, "finished": None,
                      "status": "running"})
        _write_json(state_path, state)
        print(f"== {record['stage']}\n   log: {log_path}")
        env = dict(os.environ)
        env.update({k: str(v) for k, v in (record.get("env") or {}).items()})
        with open(log_path, "w", encoding="utf-8", errors="replace") as log:
            proc = subprocess.Popen(argv, cwd=record.get("cwd") or str(REPO),
                                    env=env, stdin=subprocess.DEVNULL,
                                    stdout=log, stderr=subprocess.STDOUT)
            state["pid"] = proc.pid
            _write_json(state_path, state)
            rc = proc.wait()
        finished = time.strftime("%Y-%m-%d %H:%M:%S")
        entry = {"stage": record["stage"], "started": started,
                 "finished": finished, "returncode": rc, "log": str(log_path)}
        history.append(entry)
        state.update({"returncode": rc, "finished": finished,
                      "status": "done" if rc == 0 else "failed",
                      "history": history})
        _write_json(state_path, state)
        print(f"   exit {rc} ({'ok' if rc == 0 else 'FAILED - stopping'})")
        if rc != 0:
            return 1
    return 0


def cmd_run(args) -> int:
    charter, rc = _load(args.charter)
    if charter is None:
        return rc
    stages = _stages_arg(args.stages)
    if not args.dry_run:
        refused = _gate(charter)
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
    if needs_rs and os.environ.get(HARNESS_ENV) and not args.foreground:
        print("REFUSED: this shell belongs to an agent harness "
              f"({HARNESS_ENV} is set) and the plan boots RealityScan for: "
              f"{', '.join(needs_rs)}. Long runs are SCHEDULER-OWNED "
              "(docs/AGENT_OPERATIONS.md mandate 6): use\n"
              f"    python rs.py launch --charter {args.charter}"
              + (f" --stages {args.stages}" if args.stages else "")
              + "\nand run the printed schtasks commands. --foreground is the "
                "owner's override for a terminal they own.", file=sys.stderr)
        return EXIT_HARNESS_REFUSED
    agent_ws = _agent_ws(charter)
    resume = (f"python rs.py run --charter {args.charter}"
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


def write_launcher(charter: RunCharter, charter_path: str,
                   stages: Optional[list[str]], task_name: str,
                   python: str = sys.executable) -> dict:
    """The CRLF .cmd/.vbs pair + RUN_STATE (prepared). Returns their paths."""
    agent_ws = _agent_ws(charter)
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
    _assert_cmd_safe(str(REPO), charter_path, str(agent_ws), python, stage_arg)
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
        "budget": charter.budget, "prepared": time.strftime("%Y-%m-%d %H:%M:%S"),
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
    print("\nNOT executed by rs.py - registering a task is an owner-approved "
          "action. Run these, in order (Windows, the box that owns the data):")
    print(f'  schtasks /Create /TN "{task}" /TR "wscript.exe //B \\"{paths["vbs"]}\\"" '
          f'/SC ONCE /ST {start} /F')
    print(f'  schtasks /Run /TN "{task}"')
    print(f'  schtasks /Query /TN "{task}" /FO LIST /V')
    print("\nThen poll with:  python rs.py status --charter "
          f"{args.charter}   (or the run-monitor agent)")
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


def status_report(workspace: str, agent_ws: Optional[Path],
                  instance: Optional[str]) -> dict:
    report: dict = {"schema": 1, "workspace": workspace}
    verify = _verify_mod.verify_workspace(workspace)
    report["verify"] = {k: verify.get(k) for k in
                        ("verdict", "counts", "blocking", "incomplete")}
    report["verify_exit"] = _verify_mod.EXIT_CODES[verify["verdict"]]
    report["stages"] = {k: v["status"] for k, v in (verify.get("stages") or {}).items()}
    if agent_ws is not None:
        state_path = agent_ws / RUN_STATE_NAME
        state = _read_json(state_path) if state_path.is_file() else None
        if state and state.get("rc_file") and Path(state["rc_file"]).is_file():
            rc_text = _tail(Path(state["rc_file"]))
            if rc_text:
                state["launcher_exit"] = rc_text[0]
        report["run_state"] = state
        report["run_state_path"] = str(state_path)
    if instance:
        errors_dir = Path(ERRORS_DIR)
        progress = errors_dir / f"progress_{instance}.txt"
        errors = errors_dir / f"errors_{instance}.txt"
        lock = errors_dir / f"{instance}.lock"
        report["instance"] = {
            "name": instance,
            "progress": (_tail(progress) or [""])[0] if progress.is_file() else None,
            "progress_age": _age(progress) if progress.is_file() else None,
            "errors_bytes": errors.stat().st_size if errors.is_file() else None,
            "errors_first_line": (_tail(errors, 400)[:1] or [""])[0] if errors.is_file() else None,
            "lock_held": lock.is_file(),
        }
    newest = []
    for folder in (Path(workspace) / "logs",
                   *( [agent_ws / "logs"] if agent_ws else [] ),
                   Path(workspace) / "merged" / "logs"):
        if folder.is_dir():
            newest += [p for p in folder.iterdir() if p.is_file()]
    newest.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    report["newest_logs"] = [{"path": str(p), "age": _age(p)} for p in newest[:3]]
    return report


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
    state = report.get("run_state")
    if state is None and "run_state_path" in report:
        lines.append(f"run state : none ({report['run_state_path']} absent)")
    elif state:
        lines.append(f"run state : {state.get('status')}  stage={state.get('stage')}"
                     f"  task={state.get('task')}  started={state.get('started')}")
        lines.append(f"            log={state.get('log')}")
        if state.get("launcher_exit") is not None:
            lines.append(f"            launcher exit code file says: {state['launcher_exit']}")
    inst = report.get("instance")
    if inst:
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
    report = status_report(workspace, agent_ws, instance)
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
