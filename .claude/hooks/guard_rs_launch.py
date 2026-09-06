#!/usr/bin/env python3
"""PreToolUse guard: no second way to launch RealityScan (hard rule 1).

CLAUDE.md's first hard rule is that every RealityScan invocation goes
through ``RealityScanCLI`` and the ``:run`` pattern - because that layer
owns executable discovery, per-instance lock files, marker-file hygiene
for the getStatus/teardown handle race, progress tailing and verified
shutdown. A shell command that runs RealityScan.exe directly has none of
that, and the failure is silent: the run looks fine and leaves a corrupt
instance behind.

The rule was prose, so it held only while it was remembered. This makes it
mechanical.

REFUSED: a shell command that invokes the RealityScan executable, or the
workflow .bat files, directly.
ALLOWED: the same work through a Python driver, and every read-only query
about those files (grep, cat, ls, git) - the guard looks for INVOCATION,
not for the string appearing somewhere in a command.

Contract: PreToolUse hook. Reads the tool call as JSON on stdin; exit 0
allows, exit 2 blocks and shows stderr to Claude.
"""
from __future__ import annotations

import json
import re
import sys

#: Executable names that must never be invoked from a shell here.
_EXECUTABLES = ("realityscan.exe", "realitycapture.exe")

#: Workflow scripts that must be launched through RealityScanCLI.
#: run_batch_script gives them a log file, an instance lock and marker
#: hygiene; a bare `cmd /c AlignZone.bat` gets none of it and lets the
#: booted GUI inherit the caller's stdout pipe (Windows trap 2026-08-07).
_WORKFLOW_BAT = re.compile(
    r"\b(startrealityscan|alignzone|mergezonecomponents|generatemodel|"
    r"exportdeliverables|saveprojectcopy|modeltofinal|growzone|nightgrow|"
    r"computemodel|calibcellalign|flushcache|guiworkbench|"
    r"alignimagesfromfolder|probecalibgroups\d*|probeflightlog\d*|"
    r"probeexportsettings)\.bat\b"
    # Anything else under RS_CLI/Scripts is a workflow too, whatever it is
    # called - a new script must not slip past the guard by being new; the
    # archived probes and legacy workflows are boot-capable as well.
    r"|rs_cli[\\/]+scripts[\\/]+[^\s\"']+\.bat\b"
    r"|archive[\\/]+(?:probes|legacy_scripts)[\\/]+[^\s\"']+\.bat\b")

#: Commands that only READ - naming a .bat here is inspection, not
#: execution. Anchored at the start of the command (or of a pipeline
#: segment) so `grep AlignZone.bat` passes and `AlignZone.bat` does not.
_READ_ONLY = re.compile(
    r"^\s*(sudo\s+)?(grep|rg|cat|bat|head|tail|less|more|type|ls|dir|find|"
    r"fd|wc|diff|git|sed|awk|echo|printf|py|python|python3|pytest|"
    r"select-string|get-content|get-childitem|test-path)\b",
    re.IGNORECASE)


def segments(command: str) -> list[str]:
    """The command split into independently-executed segments.

    A backslash-escaped pipe (``grep "a\\|b"``) is a regex alternation
    inside one argument, not a shell pipe, so it does not start a new
    segment - otherwise a read-only grep whose pattern mentions a .bat
    name is refused.
    """
    return [s for s in re.split(r"\|\||&&|(?<!\\)\||;|\n", command)
            if s.strip()]


def offence(command: str) -> str | None:
    """The reason this command is refused, or None."""
    for segment in segments(command):
        low = segment.lower()
        if _READ_ONLY.match(segment):
            continue
        for exe in _EXECUTABLES:
            if exe in low:
                return (f"invokes {exe} directly")
        hit = _WORKFLOW_BAT.search(low)
        if hit:
            return f"invokes the workflow script {hit.group(0)} directly"
    return None


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (ValueError, OSError) as exc:
        # Nothing identifiable to guard. Say so rather than pretending a
        # check happened.
        print(f"guard_rs_launch: could not read the tool call ({exc}); "
              "no check performed", file=sys.stderr)
        return 0

    command = (payload.get("tool_input") or {}).get("command") or ""
    if not isinstance(command, str) or not command.strip():
        return 0

    reason = offence(command)
    if not reason:
        return 0

    print(
        f"BLOCKED by .claude/hooks/guard_rs_launch.py: this command "
        f"{reason}.\n\n"
        "CLAUDE.md hard rule 1: never add a second way to launch or monitor "
        "RealityScan. Every invocation goes through "
        "modules/realityscan_interface/realityscan_cli.py "
        "(RealityScanCLI.run_batch_script), which owns executable "
        "discovery, the per-instance lock, marker-file hygiene for the "
        "getStatus/teardown handle race, progress tailing and verified "
        "shutdown. A direct launch has none of that and fails silently.\n\n"
        "Use the Python driver for this workflow (merge_zones.py, "
        "run_models.py, finish_model.py, modules/export_deliverables.py, "
        "main.py), or extend RealityScanCLI.",
        file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
