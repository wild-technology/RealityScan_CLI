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
# Refusing to INHERIT persisted answers
# ---------------------------------------------------------------------------
# Offering the last run's answer as a default is exactly right for an
# operator at a keyboard: they see it and press enter. It is exactly wrong
# for an unattended/agent-driven run, where the same mechanism silently
# carries one campaign's locations into another campaign's run - the
# wizard-prefill and stale-settings incidents of 2026-08-08, and the
# reason docs/AGENT_OPERATIONS.md sec.8 says "no rs_settings inheritance
# unattended".
#
# With RS_NO_SETTINGS_INHERITANCE truthy, the STORE stops supplying
# values: prompt/ask/prompt_bool fall back to the caller's own explicit
# `fallback` (which is code, not history) and otherwise fail by name.
# Writing still happens, so a strict run's answers are recorded for the
# humans; they just never come back as an unexamined default.
#
# modules.run_charter sets this for every child of a charter-driven run.
NO_INHERIT_ENV = "RS_NO_SETTINGS_INHERITANCE"

_TRUTHY = ("1", "true", "yes", "y", "on")

#: Where the store lives when no explicit path is given. Set by the test
#: suite (testing/conftest.py) so no test ever writes the repo root, and
#: usable by an operator who wants a run's answers recorded beside its
#: results instead of in the checkout.
SETTINGS_PATH_ENV = "RS_SETTINGS_PATH"

#: Strict-unattended switches. RS_NO_INTERACTIVE is main.py's "never
#: prompt" contract; RS_RUN_CHARTER marks a charter-driven (agent) run.
#: Under either, a prompt NEVER blocks on input(): it takes the value it is
#: allowed to take and SAYS so, or fails by name (PRODUCT_READINESS 11).
NO_INTERACTIVE_ENV = "RS_NO_INTERACTIVE"
CHARTER_ENV = "RS_RUN_CHARTER"


def inheritance_refused() -> bool:
    """True when persisted answers must not be reused as defaults."""
    return os.environ.get(NO_INHERIT_ENV, "").strip().lower() in _TRUTHY


def unattended() -> bool:
    """True when no prompt may wait for a human (RS_NO_INTERACTIVE truthy,
    or a run charter is active). A hidden console reports isatty()=True
    with an EOF stdin, so this is decided by declaration, never by TTY."""
    return (os.environ.get(NO_INTERACTIVE_ENV, "").strip().lower() in _TRUTHY
            or bool(os.environ.get(CHARTER_ENV, "").strip()))


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
#
# DELIBERATE OMISSION - gpu_devices: the section also carries a
# 'gpu_devices' key (README documents it), but it is resolved inside
# RealityScanCLI.run_batch_script (realityscan_cli.py), NOT here, because
# GPU pinning is a BOOT-time property of the instance the CLI layer owns:
# attach mode must never export it, and run_batch_script's own
# gpu_devices= argument has to win over the stored value. Every driver
# reaches RealityScan through that layer, so nothing loses the pin by
# using realityscan_env() for the rest (audit 2026-08-07).

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
        # `or DEFAULT_INSTANCE_NAME` on the STORED value too: a stored
        # empty string used to be exported verbatim as RS_INSTANCE='',
        # which every .bat then interpolates into an empty
        # -delegateTo/-getStatus argument (audit 2026-08-07).
        "RS_INSTANCE": os.environ.get("RS_INSTANCE")
        or str(store.get(REALITYSCAN_SECTION, "instance_name",
                         DEFAULT_INSTANCE_NAME) or DEFAULT_INSTANCE_NAME),
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
        self.path = (path or os.environ.get(SETTINGS_PATH_ENV, "").strip()
                     or DEFAULT_SETTINGS_PATH)
        self._data = self._load()

    def _load(self) -> dict:
        if not os.path.isfile(self.path):
            return {}
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return {}
            # The file is advertised as human-editable, so a section may
            # come back as a scalar/null/list after a hand edit. get()/set()
            # assume dicts, so such a section used to crash every driver at
            # startup with AttributeError/TypeError - and the corrupt-file
            # quarantine above never fired, because the JSON parses fine
            # (audit 2026-08-07). Drop the bad sections loudly instead.
            bad = sorted(k for k, v in data.items() if not isinstance(v, dict))
            if bad:
                print(f"WARNING: {self.path}: ignoring non-object settings "
                      f"section(s) {bad} - each section must be a JSON "
                      f"object. Fix or delete them to stop losing those "
                      f"values.")
                data = {k: v for k, v in data.items() if isinstance(v, dict)}
            return data
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

    # Defense in depth behind _load's normalisation: an in-process
    # mutation (or a test double) can still put a non-dict in a section.
    def get(self, section: str, key: str, fallback=None):
        sec = self._data.get(section)
        return sec.get(key, fallback) if isinstance(sec, dict) else fallback

    def default_for(self, section: str, key: str, fallback):
        """Public name for ``_default_for`` - the value a prompt MAY offer.

        Drivers that build their own prompts (main.parse_arguments, the
        batcher's _prompt_int) must resolve their defaults through this,
        never through ``get``: ``get`` bypasses the inheritance refusal,
        and that bypass is how a charter-driven run could still inherit a
        previous campaign's ``main``/``batch`` answers (audit 2026-09-05).
        """
        return self._default_for(section, key, fallback)

    def _default_for(self, section: str, key: str, fallback):
        """The default a PROMPT may offer for this key.

        Identical to ``get`` except under RS_NO_SETTINGS_INHERITANCE, where
        the persisted value is discarded (loudly - a refused inheritance
        must not look like an absent one) and the caller's own explicit
        fallback stands in. ``get`` itself is deliberately NOT gated: code
        that reads a stored machine constant on purpose (realityscan_env's
        cache_dir, the portal's last-run fields) is not the hazard; the
        hazard is a PROMPT silently answering itself from history.
        """
        if not inheritance_refused():
            return self.get(section, key, fallback)
        stored = self.get(section, key, None)
        if stored is not None and stored != fallback:
            print(f"REFUSING stored default {section}.{key}={stored!r} "
                  f"({NO_INHERIT_ENV} is set) - supply it explicitly.")
        return fallback

    def set(self, section: str, key: str, value) -> None:
        if not isinstance(self._data.get(section), dict):
            self._data[section] = {}
        self._data[section][key] = value
        self._save()

    @staticmethod
    def _input_or_default(message: str, default):
        """input() that never raises on an EOF stdin.

        Unattended runs are the norm here (hidden consoles report
        isatty()=True with an EOF stdin - Windows trap registry), and a
        bare input() then aborts the driver with an EOFError traceback.
        ``ask()`` has always guarded this; ``prompt``/``prompt_bool`` did
        not, so geoall.py and organize_by_date.py could not run unattended
        at all (audit 2026-08-07). Returns ``default`` on EOF; raises a
        NAMED error when there is no default to fall back to.
        """
        if unattended():
            # Declared unattended (RS_NO_INTERACTIVE / RS_RUN_CHARTER): never
            # wait on input(), even on a console that looks interactive -
            # a scheduled task's console is exactly that. Say what was
            # taken, so a self-answered prompt is visible in the log.
            if default is None:
                raise ValueError(
                    f'UNATTENDED run ({NO_INTERACTIVE_ENV}/{CHARTER_ENV}) and '
                    f'no value for this prompt: "{message.strip()}". Supply '
                    f'it on the command line or in the run charter.')
            print(f'UNATTENDED: taking {default!r} for "{message.strip()}"')
            return ''
        try:
            return input(message).strip()
        except EOFError:
            # Without this, prompt()'s `while not value` retry loop spins
            # FOREVER on an EOF stdin (input() keeps returning '') - the
            # named error is what turns an unattended hang into a message.
            if default is None:
                raise ValueError(
                    f'Non-interactive run and no stored default for this '
                    f'prompt: "{message.strip()}". Supply the value on the '
                    f'command line, or run once interactively so it is '
                    f'persisted in rs_settings.json.') from None
            return ''

    def prompt(self, section: str, key: str, message: str, fallback=None):
        """Ask the user for a value, offering the stored value (or
        ``fallback``) as the default. The answer is persisted immediately.

        EOF-safe (see _input_or_default): unattended runs take the stored
        default silently and fail with a named ValueError when none exists.
        """
        default = self._default_for(section, key, fallback)

        if default is not None:
            answer = self._input_or_default(f"{message} [{default}]: ", default)
            value = answer or default
        else:
            value = self._input_or_default(f"{message}: ", None)
            while not value:
                value = self._input_or_default(f"{message} (required): ", None)

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
        stored = self._default_for(section, key, fallback)
        if stored is None and inheritance_refused():
            # Strict mode with nothing explicit to fall back on. Returning
            # None here would hand the caller a value it never chose and
            # push the failure into whatever dereferences it first - the
            # exact "unattended run died on a None" shape RSModule.
            # validate_parameters was written to name. Name it here too.
            raise ValueError(
                f'{NO_INHERIT_ENV} is set and no explicit value was given '
                f'for "{section}.{key}". Pass it on the command line (or in '
                f'the run charter) - stored answers from previous runs are '
                f'refused on this lane.')
        if unattended():
            # Declared unattended: never input(). Nothing to take is a
            # named failure, not a None handed downstream; a value taken
            # is announced (PRODUCT_READINESS 11: no silent self-answer).
            if stored is None:
                raise ValueError(
                    f'UNATTENDED run ({NO_INTERACTIVE_ENV}/{CHARTER_ENV}) and '
                    f'no explicit value for "{section}.{key}". Pass it on '
                    f'the command line or in the run charter.')
            print(f'UNATTENDED: {section}.{key} = {stored!r} '
                  f'({"code default" if stored == fallback else "stored answer"})')
            self.set(section, key, stored)
            return stored
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
        default = self._default_for(section, key, fallback)
        suffix = " [y/n]" if default is None else (" [Y/n]" if default else " [y/N]")

        while True:
            answer = self._input_or_default(
                f"{message}{suffix}: ",
                None if default is None else default).lower()
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
