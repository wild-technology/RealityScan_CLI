#!/usr/bin/env python3
"""Compatibility shim - the metric-scale oracle now lives in modules/.

It was promoted out of testing/ on 2026-07-26 because merge_zones calls it as
a DELIVERABLE GATE before generating any model, and a gate must not live beside
the unit tests. This shim exists only so the command recorded throughout
FINDINGS.md and HANDOFF.md keeps working:

    py -3.13 testing/scale_oracle.py <components_dir> <flight_log>

There is exactly ONE implementation (modules/scale_oracle.py); nothing is
duplicated here. Prefer importing `modules.scale_oracle` in new code.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(__file__))))

from modules.scale_oracle import (  # noqa: E402,F401
    DEFAULT_SCALE_MAX,
    DEFAULT_SCALE_MIN,
    component_members,
    load_nav_positions,
    load_solved_positions,
    report,
    scale_for_images,
    scale_ratio,
    verdict,
)

if __name__ == '__main__':
    if len(sys.argv) != 3:
        print('usage: scale_oracle.py <components_dir> <flight_log>')
        raise SystemExit(2)
    for row in report(sys.argv[1], sys.argv[2]):
        status, why = verdict(row)
        print('c{component}: {cameras:5d} cams  scale {median:.3f}  '
              'IQR {iqr_low:.3f}-{iqr_high:.3f}'.format(**row)
              + f'  [{status.upper()}] {why}')
