#!/usr/bin/env python3
"""PostToolUse: .bat and .vbs must be CRLF, always.

The Windows trap registry's first entry: cmd searches for batch labels by
BYTE OFFSET, so an LF-only .bat breaks ``goto`` nondeterministically with
"cannot find the batch label". Every workflow in RS_CLI/Scripts is built
on the shared ``:run`` subroutine, i.e. on labels.

.gitattributes pins the line endings in GIT. It does not pin what is on
DISK after a tool writes the file, and the scripted edit that introduces
an LF is exactly the edit nobody inspects afterwards. This hook rewrites
the file in place after any Write/Edit that touches one.

Contract: PostToolUse hook. The edit has already happened; this repairs
it and reports on stdout. Exit 0 always - there is nothing to block.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

SUFFIXES = {".bat", ".cmd", ".vbs"}


def normalize(path: Path) -> bool:
    """Rewrite ``path`` with CRLF endings. True if it changed."""
    original = path.read_bytes()
    # Collapse to LF first so CRLF and stray CR both land on one form,
    # then expand once - this is idempotent, where a bare LF->CRLF
    # replacement would turn existing CRLF into CRCRLF.
    unified = original.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    crlf = unified.replace(b"\n", b"\r\n")
    if crlf == original:
        return False
    path.write_bytes(crlf)
    return True


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (ValueError, OSError) as exc:
        print(f"normalize_crlf: could not read the tool call ({exc}); "
              "no check performed", file=sys.stderr)
        return 0

    raw = (payload.get("tool_input") or {}).get("file_path")
    if not raw:
        return 0

    path = Path(str(raw))
    if path.suffix.lower() not in SUFFIXES or not path.is_file():
        return 0

    try:
        if normalize(path):
            print(f"normalize_crlf: rewrote {path.name} with CRLF endings "
                  "(cmd finds batch labels by byte offset; LF breaks goto).")
    except OSError as exc:
        # Loud, but not fatal: the edit already landed, and a failure to
        # repair it must be visible rather than silently assumed done.
        print(f"normalize_crlf: FAILED to normalise {path}: {exc} - check "
              "the line endings by hand before running this script.",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
