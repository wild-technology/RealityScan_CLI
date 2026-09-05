#!/usr/bin/env python3
"""PreCompact: record that the context is about to be compacted.

The model cannot act between this hook and the compaction, and PreCompact
stdout is not documented to reach the model's context, so the protection is
split in two: this hook writes a marker (`.claude/.last_compact`, gitignored)
and prints a reminder for the transcript; `session_status.py`, which also
runs on the `compact` SessionStart source, reads the marker and tells the
model that anything learned before compaction and not yet in FINDINGS.md
or HANDOFF.md is at risk, with the command that shows what is unflushed.

Exit 0 always; never blocks. stdlib only.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

HOOK_REPO = Path(__file__).resolve().parent.parent.parent
MARKER = Path(os.environ.get("RS_COMPACT_MARKER") or HOOK_REPO / ".claude" / ".last_compact")


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (ValueError, OSError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    record = {"at": time.strftime("%Y-%m-%d %H:%M:%S"),
              "trigger": str(payload.get("trigger") or payload.get("matcher") or "unknown"),
              "cwd": str(payload.get("cwd") or os.getcwd())}
    try:
        MARKER.write_text(json.dumps(record), encoding="utf-8")
    except OSError as exc:
        print(f"pre_compact: could not write {MARKER}: {exc}", file=sys.stderr)
    print("pre_compact: context is being compacted. Facts not yet in "
          "FINDINGS.md / HANDOFF.md survive only if written; the session-start "
          "hook will flag this after compaction.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
