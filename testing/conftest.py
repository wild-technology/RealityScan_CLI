"""Suite-wide hygiene, enforced mechanically (.claude/rules/testing.md).

1. The settings store never touches the repo root. Every test gets an
   isolated ``rs_settings.json`` under ``tmp_path`` - both for in-process
   ``SettingsStore()`` constructions (module attribute) and for child
   processes the tests spawn (``RS_SETTINGS_PATH``). The suite used to
   write the root file through ``main.parse_arguments`` (section "main")
   and ``BatchDirectory.__init__``; a persisted answer from one test could
   feed the next through the same path that caused the stored-merge-
   options incident (AGENT_OPERATIONS sec.5, 2026-07-29).
2. No test inherits the developer's own ``RS_*`` environment: an exported
   ``RS_RUN_CHARTER`` or ``RS_NO_SETTINGS_INHERITANCE`` would arm guards
   the fixture-based tests do not expect.
3. At session end the repo root is checked: a stray ``rs_settings.json``
   fails the run loudly instead of being silently gitignored.

Known platform-bound failures off Windows (not defects): the alignment
tests in test_align_and_rollback_safety.py need the RealityScan install
tree, and the basename-matching tests in test_batch_copy_accounting.py /
test_feature_merge.py feed Windows drive-letter paths through os.path on POSIX. On the
Windows box the suite is expected fully green (CLAUDE.md, "Baseline").
"""
from __future__ import annotations

import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

import module_base.settings_store as _settings_store  # noqa: E402

_ISOLATED_ENV = ("RS_RUN_CHARTER", "RS_NO_SETTINGS_INHERITANCE",
                 "RS_NO_INTERACTIVE", "RS_SETTINGS_PATH", "RS_INSTANCE",
                 "RS_CACHE_DIR", "RS_HEADLESS", "RS_MODULES")


@pytest.fixture(autouse=True)
def _isolate_settings_store(tmp_path, monkeypatch):
    path = str(tmp_path / "rs_settings.json")
    monkeypatch.setattr(_settings_store, "DEFAULT_SETTINGS_PATH", path)
    for name in _ISOLATED_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("RS_SETTINGS_PATH", path)
    yield



def pytest_sessionfinish(session, exitstatus):
    stray = os.path.join(REPO, "rs_settings.json")
    if os.path.isfile(stray):
        sys.stderr.write(
            f"\nHYGIENE FAILURE: the suite wrote {stray}. No test may write "
            "the repo root (testing/conftest.py isolates the store; a test "
            "that constructs SettingsStore(path=...) explicitly, or a child "
            "process that clears RS_SETTINGS_PATH, escaped it).\n")
        session.exitstatus = 1
