"""Compatibility shim - the census implementation moved to
modules/workspace_census.py (2026-08-07, consolidation step 8).

WHY: run_models.py (a repo-root driver) needed the Workspace census, and
the layering rule is that wildscan may import modules, never the reverse -
so the implementation lives in modules/ and this module re-exports it for
the TUI package and any older imports. The private helpers are re-exported
too because wildscan.session imports them (_find_flight_logs, _load_json).
"""
from __future__ import annotations

from modules.workspace_census import (  # noqa: F401
    IMAGE_EXTS,
    STAGE_ORDER,
    STAGE_TITLES,
    ComponentInfo,
    StageStatus,
    Workspace,
    _count_images,
    _find_flight_logs,
    _load_json,
)

__all__ = [
    "IMAGE_EXTS", "STAGE_ORDER", "STAGE_TITLES",
    "ComponentInfo", "StageStatus", "Workspace",
]
