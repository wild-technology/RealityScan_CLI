"""Atomic metadata replacement tolerant of short Windows reader/AV locks."""
from __future__ import annotations

import os
import time


def replace_file(source, target):
    """Retry sharing/access errors briefly; never delete the previous record.

    The caller owns temporary-file cleanup and any conflict/identity checks.
    Disk-full, missing-path and other errors propagate immediately. A permanent
    permission failure still fails after one second, preserving the old target.
    """
    for attempt in range(21):
        try:
            os.replace(source, target)
            return
        except PermissionError as exc:
            if (os.name != "nt" or getattr(exc, "winerror", None) not in (5, 32, 33)
                    or attempt == 20):
                raise
            time.sleep(0.05)
