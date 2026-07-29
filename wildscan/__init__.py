"""WildScan - Wild Technology's interactive subsea photogrammetry console.

A cross-platform (Windows / macOS / Linux) Textual TUI over this repo's
canonical pipeline drivers. It ORCHESTRATES the existing entry points -
main.py's module chain, merge_zones.py, the RS_CLI workflow .bats, the
publish_* scripts - and never grows a second way to launch or monitor
RealityScan (hard rule 1). RealityScan itself only runs on Windows; on other
platforms the app still opens any workspace for inspection, previews, exports
review and publishing.

Run:  py -3.13 -m wildscan [workspace]
"""
from __future__ import annotations

__version__ = "1.0.0"
APP_NAME = "WildScan"
ORG = "Wild Technology"
TAGLINE = "Subsea Photogrammetry Pipeline"
