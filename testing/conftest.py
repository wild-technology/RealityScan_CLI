"""Suite-wide hermeticity for the ExportDeliverables switches.

WHY THIS EXISTS. modules/export_deliverables.py reads its behaviour switches
(RS_EXPORT_SUFFIX, RS_EXPORT_SKIP_PLY, ...) from the environment, because
that is how they reach ExportDeliverables.bat. Only two test files cleared
them, so a shell running a dive driver's environment - NA165 exports
RS_EXPORT_SUFFIX=_L - turned three pre-existing census tests red (review
2026-09-27: "3 failed, 919 passed"; RS_EXPORT_SKIP_PLY=1 alone, 2 failed).

setenv before delenv: monkeypatch then RECORDS the original (usually unset)
value and restores it at teardown even when the code under test writes
os.environ directly (apply_switches does) - a bare delenv of an absent key
records nothing, and the write leaks into every later test.
"""
from __future__ import annotations

import os

import pytest

EXPORT_SWITCHES = ('RS_EXPORT_SUFFIX', 'RS_EXPORT_TEXTURES', 'RS_EXPORT_NO_SAVE',
                   'RS_EXPORT_SKIP_PLY', 'RS_EXPORT_ONLY_PLY',
                   'RS_EXPORT_TARGET_LOG', 'RS_EXPORT_TARGET_PARAMS',
                   'RS_EXPORT_REGISTRATION_DIR')


@pytest.fixture(autouse=True)
def _no_inherited_export_switches(monkeypatch):
    names = set(EXPORT_SWITCHES) | {k for k in os.environ
                                    if k.upper().startswith('RS_EXPORT_')}
    for key in sorted(names):
        monkeypatch.setenv(key, 'x')
        monkeypatch.delenv(key)
