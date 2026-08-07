"""Persistent user settings for the RealityScan pipeline scripts.

Every standalone script stores the user's last-entered values (data
locations, output folders, executable paths) in a single JSON file at the
repository root: ``rs_settings.json``. On the next run those values are
offered as defaults, so a plain <Enter> repeats the previous session's
answer.

The file is intentionally human-editable and is not committed to git.

Usage:

    from module_base.settings_store import SettingsStore

    settings = SettingsStore()
    input_dir = settings.prompt("geoall", "image_base_dir",
                                "Folder containing the images to georeference")
    settings.set("geoall", "image_base_dir", input_dir)  # prompt() already saves
"""

from __future__ import annotations

import json
import os
import sys
import tempfile

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
DEFAULT_SETTINGS_PATH = os.path.join(_REPO_ROOT, "rs_settings.json")

# ---------------------------------------------------------------------------
# The 'realityscan' section - per-machine constants
# ---------------------------------------------------------------------------
# Machine-level RealityScan constants live in ONE settings section so that no
# driver hardcodes them again. Keys:
#
#   executable    - full path to RealityScan.exe. Optional; unset falls back
#                   to the RS_EXECUTABLE env var and the standard install
#                   locations (RealityScanCLI.find_executable).
#   cache_dir     - RealityScan cache directory, exported as RS_CACHE_DIR.
#                   NO repo default: the cache drive is per-machine, so
#                   interactive drivers prompt for it once (an empty answer
#                   leaves RealityScan's own cache default in force).
#   instance_name - CLI instance name, exported as RS_INSTANCE.
#                   Default: 'RS1'.
#   headless      - boot instances without a GUI, exported as RS_HEADLESS
#                   ('1' = headless, '0' = visible). Default: False
#                   (VISIBLE) - OWNER DECISION 2026-08-07: visible by
#                   default is supervision-friendly; headless is the
#                   per-machine override. The .bat layer's own fallback when
#                   RS_HEADLESS is absent remains headless
#                   (SetVariables.bat); the Python layer always exports
#                   RS_HEADLESS explicitly, so that fallback only governs
#                   hand-run scripts.
#
# Resolve these through realityscan_env() below - the single Python source
# of truth - rather than reading the keys (or hardcoding values) in drivers.

REALITYSCAN_SECTION = "realityscan"
DEFAULT_INSTANCE_NAME = "RS1"
DEFAULT_HEADLESS = False


def headless_flag(value) -> str:
    """Normalise a stored/CLI headless value to the RS_HEADLESS wire form:
    '0' = GUI-visible, '1' = headless."""
    if isinstance(value, str):
        return "0" if value.strip().lower() in ("0", "false", "no", "n", "") \
            else "1"
    return "1" if value else "0"


def realityscan_env(store) -> dict:
    """Resolve the 'realityscan' machine constants as RS_* env values.

    ``store`` is any SettingsStore-shaped object (only ``get`` is used, so
    test doubles work). Precedence: a variable already set in the process
    environment WINS over the stored setting - stored values are machine
    defaults, the environment is the per-run override. Env values are
    returned unchanged in the dict, so callers may overlay the result onto
    a child environment (or os.environ) without demoting user overrides.

    RS_CACHE_DIR is omitted when neither the environment nor the store
    knows it - RealityScan then uses its own cache default (opt-in
    behaviour documented in startRealityScan.bat).
    """
    env = {
        "RS_INSTANCE": os.environ.get("RS_INSTANCE")
        or str(store.get(REALITYSCAN_SECTION, "instance_name",
                         DEFAULT_INSTANCE_NAME)),
        "RS_HEADLESS": os.environ.get("RS_HEADLESS")
        or headless_flag(store.get(REALITYSCAN_SECTION, "headless",
                                   DEFAULT_HEADLESS)),
    }
    cache_dir = (os.environ.get("RS_CACHE_DIR")
                 or store.get(REALITYSCAN_SECTION, "cache_dir"))
    if cache_dir:
        env["RS_CACHE_DIR"] = str(cache_dir)
    return env


class SettingsStore:
    def __init__(self, path: str = None):
        self.path = path or DEFAULT_SETTINGS_PATH
        self._data = self._load()

    def _load(self) -> dict:
        if not os.path.isfile(self.path):
            return {}
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, OSError):
            # A corrupt settings file must never block a run; start fresh
            # but keep the broken file aside for inspection.
            try:
                os.replace(self.path, self.path + ".corrupt")
            except OSError:
                pass
            return {}

    def _save(self) -> None:
        # Atomic write: never leave a half-written settings file behind if
        # the process dies mid-save.
        directory = os.path.dirname(self.path) or "."
        fd, tmp_path = tempfile.mkstemp(dir=directory, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2, sort_keys=True)
            os.replace(tmp_path, self.path)
        except OSError:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise

    def get(self, section: str, key: str, fallback=None):
        return self._data.get(section, {}).get(key, fallback)

    def set(self, section: str, key: str, value) -> None:
        self._data.setdefault(section, {})[key] = value
        self._save()

    def prompt(self, section: str, key: str, message: str, fallback=None):
        """Ask the user for a value, offering the stored value (or
        ``fallback``) as the default. The answer is persisted immediately."""
        default = self.get(section, key, fallback)

        if default is not None:
            answer = input(f"{message} [{default}]: ").strip()
            value = answer or default
        else:
            value = input(f"{message}: ").strip()
            while not value:
                value = input(f"{message} (required): ").strip()

        self.set(section, key, value)
        return value

    def ask(self, section: str, key: str, cli_value, fallback):
        """CLI-argument-aware prompt, safe for unattended runs (promoted
        from the identical grow_zone/merge_zones helpers, 2026-08-07).

        An explicit CLI value wins and is persisted; otherwise the stored
        value (or ``fallback``) is offered as the prompt default.
        Unattended runs must never block on (or crash from) input():
        without a TTY the stored/fallback value is taken silently, and a
        hidden console that reports isatty()=True with an EOF stdin
        (observed on backgrounded runs) falls back the same way.
        """
        if cli_value is not None:
            self.set(section, key, cli_value)
            return cli_value
        stored = self.get(section, key, fallback)
        # sys.stdin is None under pythonw / no-console hosts; isatty()
        # on None would raise AttributeError before the EOFError guard
        # ever gets a chance (clean-sweep 2026-08-07).
        if sys.stdin is None or not sys.stdin.isatty():
            self.set(section, key, stored)
            return stored
        try:
            value = input(f"{key} [{stored}]: ").strip() or stored
        except EOFError:
            value = stored
        self.set(section, key, value)
        return value

    def prompt_bool(self, section: str, key: str, message: str, fallback: bool = None):
        default = self.get(section, key, fallback)
        suffix = " [y/n]" if default is None else (" [Y/n]" if default else " [y/N]")

        while True:
            answer = input(f"{message}{suffix}: ").strip().lower()
            if not answer and default is not None:
                value = bool(default)
                break
            if answer in ("y", "yes"):
                value = True
                break
            if answer in ("n", "no"):
                value = False
                break

        self.set(section, key, value)
        return value
