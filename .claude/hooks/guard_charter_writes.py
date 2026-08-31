#!/usr/bin/env python3
"""PreToolUse guard: the run charter's touch rules, enforced.

docs/AGENT_OPERATIONS.md sec.1: source data is read-only forever,
protected paths are never touched, and agent working files live in ONE
declared tree. modules/run_charter.py turns that into a check; this hook
runs the check on every file-modifying tool call, so it applies to writes
the drivers never see - the ones an agent makes directly.

Active only when RS_RUN_CHARTER names a charter. Without one this exits 0
immediately: the owner's own interactive sessions have a human in the
loop, and this must not get in their way.

Contract: PreToolUse hook. Reads the tool call as JSON on stdin; exit 0
allows, exit 2 blocks and shows stderr to Claude.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO))

#: Shell redirections and file-mutating commands, with the target path.
#: Deliberately a small, high-confidence set: a shell guard that tries to
#: understand every command reliably misreads some of them, and a guard
#: that cries wolf gets switched off. The Write/Edit path below is the
#: precise one; this catches the obvious shell equivalents.
_SHELL_WRITES = (
    re.compile(r">>?\s*([^\s|&;<>]+)"),
    re.compile(r"\b(?:rm|del|mv|move|cp|copy|touch|mkdir|rmdir)\s+"
               r"(?:-[a-zA-Z]+\s+)*([^\s|&;<>]+)", re.IGNORECASE),
    re.compile(r"\b(?:tee|Out-File|Set-Content|Add-Content)\s+"
               r"(?:-\w+\s+)*([^\s|&;<>]+)", re.IGNORECASE),
)

_WRITE_TOOLS = {"Write", "Edit", "NotebookEdit", "MultiEdit"}
_SHELL_TOOLS = {"Bash", "PowerShell"}


def _targets(tool_name: str, tool_input: dict) -> list[str]:
    """Every filesystem path this tool call would modify."""
    if tool_name in _WRITE_TOOLS:
        path = tool_input.get("file_path") or tool_input.get("notebook_path")
        return [str(path)] if path else []

    if tool_name in _SHELL_TOOLS:
        command = tool_input.get("command") or ""
        if not isinstance(command, str):
            return []
        found: list[str] = []
        for pattern in _SHELL_WRITES:
            for match in pattern.finditer(command):
                target = match.group(1).strip().strip("'\"")
                # Redirections to a device or a descriptor are not writes.
                if target and not target.startswith(("/dev/", "&", "$", "%")):
                    found.append(target)
        return found
    return []


def main() -> int:
    if not os.environ.get("RS_RUN_CHARTER", "").strip():
        return 0

    try:
        payload = json.load(sys.stdin)
    except (ValueError, OSError) as exc:
        print(f"guard_charter_writes: could not read the tool call ({exc}); "
              "no check performed", file=sys.stderr)
        return 0

    try:
        from modules.run_charter import CharterError, active_charter
    except ImportError as exc:
        print(f"BLOCKED: RS_RUN_CHARTER is set but the charter module could "
              f"not be imported ({exc}), so the charter's touch rules "
              f"cannot be enforced. Fix the checkout or unset "
              f"RS_RUN_CHARTER deliberately.", file=sys.stderr)
        return 2

    try:
        charter = active_charter()
    except CharterError as exc:
        # A set-but-broken charter is the dangerous state: the agent
        # believes it is constrained and nothing is checking.
        print(f"BLOCKED: RS_RUN_CHARTER is set but the charter is not "
              f"usable: {exc}", file=sys.stderr)
        return 2

    if charter is None:
        return 0

    tool_name = payload.get("tool_name") or ""
    tool_input = payload.get("tool_input") or {}
    cwd = payload.get("cwd") or os.getcwd()

    refusals = []
    for target in _targets(tool_name, tool_input):
        absolute = target if os.path.isabs(target) else os.path.join(cwd,
                                                                     target)
        reason = charter.why_forbidden(absolute)
        if reason:
            refusals.append(f"  {absolute}\n    {reason}")

    if not refusals:
        return 0

    print("BLOCKED by .claude/hooks/guard_charter_writes.py - the signed run "
          f"charter ({charter.path}) forbids writing:\n"
          + "\n".join(refusals)
          + "\n\nSource data and nav are read-only forever; protected paths "
            "are never touched, cleaned or reorganised; everything else the "
            f"run produces belongs under the results root "
            f"({charter.results_root}).\n"
            "If this path genuinely should be writable, that is an owner "
            "decision: amend the charter and have them sign it, do not work "
            "around the guard.",
          file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
