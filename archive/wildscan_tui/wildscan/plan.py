"""Compatibility shim - ``python -m wildscan.plan`` became
``python -m modules.run_plan`` (2026-09-05). Forwards unchanged."""
from __future__ import annotations

import sys

from modules.run_plan import (  # noqa: F401
    build_plan, format_text, main, session_from_charter, unreached_answers,
    validate_command)

if __name__ == "__main__":
    sys.exit(main())
