#!/usr/bin/env python3
"""PreToolUse guard: a scheduled task may only run a launcher rs.py wrote.

Mandate 6 says long runs are scheduler-owned; `python rs.py launch` writes
the CRLF .cmd/.vbs pair under <results>/_agent/launch/ and records it in
RUN_STATE.json, then PRINTS the schtasks commands for the agent to run.
Nothing stopped an agent from registering some other command line - a
hand-written .bat, a bare driver invocation, an old launcher from another
run. This makes the contract mechanical: `schtasks /Create` is allowed only
when its /TR names an existing .vbs or .cmd that the sibling RUN_STATE.json
declares as this run's launcher.

REFUSED: `schtasks /Create` without a .vbs/.cmd path; with a path that does
not exist; or with a path RUN_STATE.json does not name.
ALLOWED: every other schtasks verb (/Run, /Query, /End, /Delete stay behind
the settings.json ask-list), and every command that is not schtasks.

Contract: PreToolUse hook. Tool call as JSON on stdin; exit 0 allows, exit 2
blocks and shows stderr to Claude. stdlib only.
"""
from __future__ import annotations

import json
import os
import re
import sys

_CREATE = re.compile(r"\bschtasks(?:\.exe)?\b.*?/create\b", re.IGNORECASE | re.DOTALL)
#: A .vbs or .cmd path: quoted (plain or \"escaped\") or a bare token.
_LAUNCHER = re.compile(
    r"""(?:\\?"|')?([A-Za-z]:[\\/][^"'<>|\n]*?\.(?:vbs|cmd)|[^\s"'<>|]+\.(?:vbs|cmd))(?:\\?"|')?""",
    re.IGNORECASE)


def launcher_path(command: str) -> str | None:
    hits = [m.group(1) for m in _LAUNCHER.finditer(command)]
    hits = [h for h in hits if not h.lower().startswith("wscript")]
    return hits[0].strip().rstrip("\\\"") if hits else None


def run_state_for(launcher: str) -> str:
    # <ws>/_agent/launch/<name>.vbs  ->  <ws>/_agent/RUN_STATE.json
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(launcher))),
                        "RUN_STATE.json")


def offence(command: str, cwd: str) -> str | None:
    if not _CREATE.search(command):
        return None
    launcher = launcher_path(command)
    if not launcher:
        return ("registers a scheduled task whose /TR names no .vbs or .cmd "
                "launcher - only launchers written by `python rs.py launch` "
                "may be scheduled")
    path = launcher if os.path.isabs(launcher) else os.path.join(cwd, launcher)
    if not os.path.isfile(path):
        return f"names a launcher that does not exist: {path}"
    state_path = run_state_for(path)
    if not os.path.isfile(state_path):
        return (f"names a launcher with no RUN_STATE.json beside its launch/ "
                f"folder ({state_path}) - it was not written by `rs.py launch`")
    try:
        state = json.load(open(state_path, encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return f"RUN_STATE.json is unreadable ({exc}); re-run `rs.py launch`"
    declared = {os.path.normcase(os.path.abspath(str(state.get(k) or "")))
                for k in ("launcher_vbs", "launcher_cmd")}
    if os.path.normcase(os.path.abspath(path)) not in declared:
        return (f"names {path}, but RUN_STATE.json declares "
                f"{state.get('launcher_vbs') or state.get('launcher_cmd')} - "
                "schedule the launcher of THIS run, or re-run `rs.py launch`")
    return None


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (ValueError, OSError) as exc:
        print(f"guard_schtasks: could not read the tool call ({exc}); "
              "no check performed", file=sys.stderr)
        return 0
    command = (payload.get("tool_input") or {}).get("command") or ""
    if not isinstance(command, str) or not command.strip():
        return 0
    reason = offence(command, payload.get("cwd") or os.getcwd())
    if not reason:
        return 0
    print("BLOCKED by .claude/hooks/guard_schtasks.py: this command "
          f"{reason}.\n\nLong runs are scheduler-owned (docs/AGENT_OPERATIONS.md "
          "mandate 6) and every scheduled run must have gone through "
          "`python rs.py launch --charter <C>`, which writes the launcher pair, "
          "RUN_STATE.json and the exact schtasks lines to run.", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
