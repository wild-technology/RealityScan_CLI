"""Compatibility shim - the planner moved to ``modules/run_plan.py``
(2026-09-05). The TUI imports this name; nothing is implemented here.

ONE planner (CLAUDE.md invariant): every symbol below is the live one in
``modules.run_plan``. Do not add logic to this file.
"""
from __future__ import annotations

from modules.run_plan import *  # noqa: F401,F403
from modules.run_plan import (  # noqa: F401  (underscore names import * skips)
    _CHOICES_BY_NAME, _FORCED_ANSWERS, _KIND_BY_NAME, _REQUIRED,
    _detection_prefills, _module_registry, _settings)
