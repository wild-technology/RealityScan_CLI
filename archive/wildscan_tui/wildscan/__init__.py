"""WildScan - Wild Technology's interactive subsea photogrammetry console.

ARCHIVED 2026-09-05 (kept functional, not developed): the pipeline is now
driven by the charter / plan / run / verify lane (``rs.py``, the ``.claude``
skills). This cross-platform Textual TUI still orchestrates the same
canonical drivers - main.py's module chain, merge_zones.py, run_models.py,
the export and publish drivers - through the ONE planner,
``modules.run_plan`` (its former ``session.py``/``plan.py`` are re-export
shims). It never grows a second way to launch or monitor RealityScan
(hard rule 1). RealityScan itself only runs on Windows; elsewhere the app
opens any workspace for inspection and exports review.

Run from the repo root:

    python -m pip install -r archive/wildscan_tui/wildscan/requirements.txt
    python archive/wildscan_tui/run_wildscan.py [workspace]
"""
from __future__ import annotations

import sys
from pathlib import Path

# The repo root, three levels up (wildscan -> wildscan_tui -> archive ->
# repo): the TUI imports the live modules from there.
_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

__version__ = "1.0.0"
APP_NAME = "WildScan"
ORG = "Wild Technology"
TAGLINE = "Subsea Photogrammetry Pipeline"
