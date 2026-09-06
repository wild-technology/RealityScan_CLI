"""Entry point:  py -3.13 -m wildscan [workspace]"""
from __future__ import annotations

import sys

try:
    from .app import main
except ImportError as exc:
    raise SystemExit(
        f"missing dependency: {exc.name}. WildScan needs Textual:\n"
        "    py -3.13 -m pip install textual rich") from exc

if __name__ == "__main__":
    sys.exit(main())
