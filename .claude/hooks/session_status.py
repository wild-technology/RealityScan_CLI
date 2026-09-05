#!/usr/bin/env python3
"""SessionStart hook: one orientation block instead of three file reads.

WHY THIS EXISTS
CLAUDE.md's session-start protocol was "read HANDOFF.md, then CLAUDE.md,
then the reference index" - three tool calls and several thousand tokens
before the first useful action, every session, every resume. And CLAUDE.md
is paid on EVERY turn, so anything orientation-shaped that lives there is
the single largest recurring cost in the repo (docs/history/AGENT_NATIVE_ROADMAP.md
sec.0). This hook runs once at startup/resume, prints the current state,
and Claude Code adds its stdout to context: the CURRENT section of
HANDOFF.md (the one that says what is running and what to do next), the
working-tree status, and - when a run is chartered - whether the charter
still validates and what RUN_STATE.json says the run is doing.

WHY THE PERMISSIONS LIVE NEXT DOOR AND NOT HERE
.claude/settings.json carries the allow/ask/deny lists for the routine
loop (pytest, verify, run_charter, plan, git reads allowed; git push,
schtasks, taskkill, rm -rf, Stop-Process, Remove-Item ask; force-push,
reset --hard, clean -fd denied - AGENT_OPERATIONS sec.6). Claude Code
rejects unknown keys in settings.json, so the rationale cannot sit beside
the rules; it sits here. Data paths are deliberately NOT in settings.json:
they are per-machine and enforced from the charter by
guard_charter_writes.py (AGENT_OPERATIONS sec.7).

WHAT THIS DELIBERATELY DOES NOT DO
- No network. Nothing here fetches, pushes or polls anything remote.
- No RealityScan. It never boots, queries or delegates to an instance
  (hard rule 1); RUN_STATE.json is read as a file, nothing more.
- No writes. Read-only against the repo, the charter and the workspace;
  it neither creates nor touches a file.
- Never blocks a session. Exit 0 on every path, including a broken
  charter, a missing HANDOFF.md, or git being absent - each of those is
  REPORTED as a line of output rather than raised.

Contract: SessionStart hook. Payload as JSON on stdin (may be empty;
tolerated). Orientation on stdout, ASCII only, about 60 lines at most.
stdlib only - the box that runs this may have a bare Microsoft Store
python with no third-party packages.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

#: Lines of the HANDOFF current section shown before truncating.
HANDOFF_LINES = 45
#: Lines of git status shown.
GIT_LINES = 8
#: Lines of the charter validation shown.
CHARTER_LINES = 5
#: Seconds allowed for each child process. Orientation must be quick.
CHILD_TIMEOUT = 10

#: The repo this hook belongs to, independent of the project dir the
#: harness reports - modules.run_charter is imported from HERE.
HOOK_REPO = Path(__file__).resolve().parent.parent.parent
#: Written by pre_compact.py when the context is about to be compacted.
#: RS_COMPACT_MARKER overrides the location (tests).
COMPACT_MARKER = Path(os.environ.get("RS_COMPACT_MARKER")
                      or HOOK_REPO / ".claude" / ".last_compact")
#: A compaction older than this is another session's; say nothing.
COMPACT_MARKER_MAX_AGE_S = 2 * 60 * 60

#: Non-ASCII characters HANDOFF.md is known to use, mapped to their ASCII
#: sense rather than to "?" (the cp1252 console crashes on the originals).
#: Keyed by code point so this file is itself ASCII-only.
_ASCII_MAP = {
    0x2014: "-",      # em dash
    0x2013: "-",      # en dash
    0x2018: "'",      # left single quote
    0x2019: "'",      # right single quote
    0x201C: '"',      # left double quote
    0x201D: '"',      # right double quote
    0x2026: "...",    # ellipsis
    0x00A0: " ",      # no-break space
    0x2192: "->",     # arrow
    0x2264: "<=",     # less-or-equal
    0x2265: ">=",     # greater-or-equal
    0x00D7: "x",      # multiplication sign
}


def ascii_only(text: str) -> str:
    return text.translate(_ASCII_MAP).encode("ascii", "replace").decode()


def emit(line: str = "") -> None:
    sys.stdout.write(ascii_only(line.rstrip("\r\n")) + "\n")


def read_payload() -> dict:
    """The hook payload, or {} when stdin is empty or not JSON."""
    try:
        raw = sys.stdin.read()
    except (OSError, ValueError):
        return {}
    if not raw or not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def project_root(payload: dict) -> Path:
    """Where HANDOFF.md and .git live: the harness's project dir, else the
    payload's cwd, else the checkout this hook sits in."""
    for candidate in (os.environ.get("CLAUDE_PROJECT_DIR", ""),
                      str(payload.get("cwd") or "")):
        if candidate.strip() and Path(candidate).is_dir():
            return Path(candidate).resolve()
    return HOOK_REPO


# ------------------------------------------------------------ HANDOFF.md

def current_section(text: str) -> list[str]:
    """Lines from the first '## ' heading up to (not including) the next."""
    lines = text.splitlines()
    start = next((i for i, ln in enumerate(lines) if ln.startswith("## ")),
                 None)
    if start is None:
        return []
    end = next((i for i in range(start + 1, len(lines))
                if lines[i].startswith("## ")), len(lines))
    section = lines[start:end]
    while section and not section[-1].strip():
        section.pop()
    return section


def show_handoff(root: Path) -> None:
    handoff = root / "HANDOFF.md"
    emit(f"--- HANDOFF.md current section ({handoff}) ---")
    try:
        text = handoff.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        emit(f"HANDOFF.md not readable: {exc}")
        return
    section = current_section(text)
    if not section:
        emit("HANDOFF.md has no '## ' section heading; read it directly.")
        return
    for line in section[:HANDOFF_LINES]:
        emit(line)
    hidden = len(section) - HANDOFF_LINES
    if hidden > 0:
        emit(f"... ({hidden} more lines; read HANDOFF.md)")


# ------------------------------------------------------------ git status

def show_git(root: Path) -> None:
    emit(f"--- git status --short --branch (first {GIT_LINES} lines) ---")
    try:
        done = subprocess.run(["git", "status", "--short", "--branch"],
                              cwd=str(root), capture_output=True, text=True,
                              timeout=CHILD_TIMEOUT)
    except (OSError, subprocess.SubprocessError) as exc:
        emit(f"git unavailable: {type(exc).__name__}: {exc}")
        return
    if done.returncode != 0:
        first = (done.stderr or done.stdout).strip().splitlines()
        emit(f"git unavailable (exit {done.returncode}): "
             f"{first[0] if first else 'no output'}")
        return
    lines = done.stdout.splitlines()
    for line in lines[:GIT_LINES]:
        emit(line)
    if len(lines) > GIT_LINES:
        emit(f"... ({len(lines) - GIT_LINES} more changed paths)")
    if len(lines) == 1:
        emit("(working tree clean)")


# --------------------------------------------------- charter + RUN_STATE

def show_charter(charter_path: str) -> None:
    emit(f"--- run charter (RS_RUN_CHARTER={charter_path}) ---")
    cmd = [sys.executable, "-m", "modules.run_charter", "--validate",
           charter_path]
    try:
        done = subprocess.run(cmd, cwd=str(HOOK_REPO), capture_output=True,
                              text=True, timeout=CHILD_TIMEOUT)
    except (OSError, subprocess.SubprocessError) as exc:
        emit(f"validate did not run: {type(exc).__name__}: {exc}")
        return
    output = (done.stdout + done.stderr).splitlines()
    for line in output[:CHARTER_LINES]:
        emit(line)
    emit(f"validate exit code: {done.returncode}"
         + ("" if done.returncode == 0 else
            "  (non-zero: no writes until this is resolved)"))


def agent_workspace(charter_path: str) -> str:
    """The charter's agent workspace, mirroring modules.run_charter's
    layout: locations.agent_workspace, else <results_root>/_agent."""
    try:
        data = json.loads(Path(charter_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    locations = data.get("locations") if isinstance(data, dict) else None
    if not isinstance(locations, dict):
        return ""
    workspace = str(locations.get("agent_workspace") or "").strip()
    if workspace:
        return workspace
    results_root = str(locations.get("results_root") or "").strip()
    return str(Path(results_root) / "_agent") if results_root else ""


def show_run_state(charter_path: str) -> None:
    workspace = agent_workspace(charter_path)
    if not workspace:
        return
    state_path = Path(workspace) / "RUN_STATE.json"
    if not state_path.is_file():
        emit(f"--- RUN_STATE.json: none under {workspace} ---")
        return
    emit(f"--- RUN_STATE.json ({state_path}) ---")
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        emit(f"RUN_STATE.json not readable: {exc}")
        return
    if not isinstance(state, dict):
        emit("RUN_STATE.json is not a JSON object")
        return
    shown = False
    for key in ("status", "stage", "task", "started", "log"):
        if key in state:
            emit(f"{key}: {state[key]}")
            shown = True
    if not shown:
        emit("(none of status/stage/task/started/log present)")


def show_compaction(payload: dict) -> None:
    """After a compaction, say what may have been lost and how to check."""
    import time  # noqa: PLC0415
    source = str(payload.get("source") or payload.get("matcher") or "")
    marker = COMPACT_MARKER
    if not marker.is_file():
        return
    try:
        age = time.time() - marker.stat().st_mtime
        record = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    if age > COMPACT_MARKER_MAX_AGE_S and source != "compact":
        return
    emit("--- CONTEXT WAS COMPACTED ---")
    emit(f"at {record.get('at', '?')} ({record.get('trigger', '?')}). Anything "
         "learned before that and not yet written to FINDINGS.md or HANDOFF.md "
         "is at risk; check `git diff --stat FINDINGS.md HANDOFF.md` and flush "
         "before continuing. The block below is the current state.")


def main() -> int:
    payload = read_payload()
    root = project_root(payload)
    emit(f"=== session_status: {root} ===")
    show_compaction(payload)
    show_handoff(root)
    show_git(root)
    charter_path = os.environ.get("RS_RUN_CHARTER", "").strip()
    if charter_path:
        show_charter(charter_path)
        show_run_state(charter_path)
    else:
        emit("--- RS_RUN_CHARTER unset: no run is chartered (guards idle) ---")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001 - orientation must never block
        emit(f"session_status: failed ({type(exc).__name__}: {exc}); "
             "orient by reading HANDOFF.md directly")
        sys.exit(0)
