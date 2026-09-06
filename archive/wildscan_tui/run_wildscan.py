#!/usr/bin/env python3
"""Launch the archived WildScan TUI: python archive/wildscan_tui/run_wildscan.py [workspace]"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))              # the wildscan package
sys.path.insert(0, str(HERE.parents[1]))   # the repo root (modules, main.py)

from wildscan.__main__ import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
