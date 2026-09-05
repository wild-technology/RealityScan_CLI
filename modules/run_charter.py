"""The run charter as DATA, and the guard that enforces it.

docs/AGENT_OPERATIONS.md defines the charter a driving agent must agree
with the owner before its first write, and docs/RUN_CHARTER.template.md is
the prose form of it. Prose is the problem: it holds only as long as the
agent remembers it, and the incidents it was written to prevent
(cross-campaign settings reuse, writes into source trees, driving the
user's RealityScan instance) are all forgetting-shaped.

This module makes the charter a JSON file the CODE reads, and turns the
three touch rules into mechanical checks:

    RUN_CHARTER.json                                  (schema below)
    python -m modules.run_charter --init  <path>    scaffold one
    python -m modules.run_charter --validate <path> check it
    python -m modules.run_charter --check <path> --path <target>

A driver opts in by calling ``guard_write(target)`` before any mutating
operation; the charter is located through the ``RS_RUN_CHARTER``
environment variable, so an unattended run carries its own contract.

WRITE POLICY - the only writable trees are:
  * the RESULTS ROOT (everything the run produces), and
  * the REPO (code, docs and tests intended for commit).
Everything else is refused. Within those, PROTECTED paths, the ORIGINALS
and the NAV are refused as well - protection wins over containment, so a
protected tree nested inside the results root stays protected.

No charter configured = no enforcement (guard_write is a no-op). That is
deliberate: this module hardens the agent lane without breaking the
owner's own interactive runs, which have a human in the loop instead.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from module_base.settings_store import NO_INHERIT_ENV

SCHEMA = 1

#: Environment variable naming the active charter file.
CHARTER_ENV = "RS_RUN_CHARTER"

REPO_ROOT = Path(__file__).resolve().parent.parent


class CharterError(Exception):
    """The charter file is missing, malformed, or incomplete."""


class CharterViolation(Exception):
    """An operation the charter forbids. Never catch this to continue."""


def _norm(path: str | Path) -> str:
    """Absolute, normalised, case-folded - the Windows-safe comparison key.

    ``Path.resolve()`` alone is not enough here: NTFS is case-insensitive,
    so ``M:\\Data`` and ``m:\\data`` are the same tree and a case-sensitive
    prefix test would wave the second one through.
    """
    return os.path.normcase(os.path.abspath(str(path)))


def _contains(parent: str | Path, child: str | Path) -> bool:
    """True when ``child`` is ``parent`` or lies underneath it."""
    p, c = _norm(parent), _norm(child)
    if p == c:
        return True
    return c.startswith(p.rstrip(os.sep) + os.sep)


@dataclass
class RunCharter:
    """A signed-off run contract."""

    path: Optional[Path] = None
    campaign: str = ""
    dive: str = ""
    originals: list[str] = field(default_factory=list)
    nav: list[str] = field(default_factory=list)
    results_root: str = ""
    agent_workspace: str = ""
    protected: list[dict] = field(default_factory=list)
    rs_instance: str = ""
    rs_cache_dir: str = ""
    user_instances: list[str] = field(default_factory=list)
    budget: dict = field(default_factory=dict)
    science: dict = field(default_factory=dict)
    signed_off: dict = field(default_factory=dict)
    raw: dict = field(default_factory=dict)

    # ------------------------------------------------------------- queries
    @property
    def label(self) -> str:
        return "_".join(b for b in (self.campaign, self.dive) if b) or "run"

    @property
    def protected_paths(self) -> list[str]:
        return [str(entry.get("path", "")) for entry in self.protected
                if str(entry.get("path", "")).strip()]

    @property
    def read_only_paths(self) -> list[str]:
        """Everything that must never be written: sources, nav, protected."""
        return [p for p in (list(self.originals) + list(self.nav)
                            + self.protected_paths) if p]

    @property
    def writable_roots(self) -> list[str]:
        return [p for p in (self.results_root, str(REPO_ROOT)) if p]

    def is_signed(self) -> bool:
        return bool(self.signed_off.get("by")
                    and self.signed_off.get("date"))

    # ------------------------------------------------------------- guards
    def why_forbidden(self, target: str | Path) -> Optional[str]:
        """The reason writing ``target`` is refused, or None if allowed."""
        for entry in self.protected:
            path = str(entry.get("path", "")).strip()
            if path and _contains(path, target):
                why = str(entry.get("why", "")).strip()
                return (f"PROTECTED path (charter): {path}"
                        + (f" - {why}" if why else ""))
        for src in self.originals:
            if src and _contains(src, target):
                return (f"SOURCE DATA is read-only, forever (charter "
                        f"originals): {src}")
        for nav in self.nav:
            if nav and _contains(nav, target):
                return f"NAV is read-only (charter nav): {nav}"
        if not any(_contains(root, target) for root in self.writable_roots):
            roots = " | ".join(self.writable_roots)
            return (f"outside every writable root declared by the charter "
                    f"({roots})")
        return None

    def assert_writable(self, target: str | Path) -> None:
        reason = self.why_forbidden(target)
        if reason:
            raise CharterViolation(
                f"charter {self.path or '<inline>'} forbids writing "
                f"{os.path.abspath(str(target))}: {reason}")

    def assert_instance(self, name: str) -> None:
        """Refuse to drive an instance the charter did not assign."""
        if not self.rs_instance:
            return
        if name == self.rs_instance:
            return
        if name in self.user_instances:
            raise CharterViolation(
                f"RealityScan instance {name!r} is declared USER-OWNED in "
                f"{self.path or '<inline>'} - never delegate to, pause, or "
                f"abort it. The agent's instance is {self.rs_instance!r}.")
        raise CharterViolation(
            f"RealityScan instance {name!r} is not the charter's instance "
            f"({self.rs_instance!r}). Own your instance before you run "
            f"anything.")

    def env(self) -> dict[str, str]:
        """RS_* environment this charter pins for its child processes."""
        out = {CHARTER_ENV: str(self.path) if self.path else "",
               NO_INHERIT_ENV: "1"}
        if self.rs_instance:
            out["RS_INSTANCE"] = self.rs_instance
        if self.rs_cache_dir:
            out["RS_CACHE_DIR"] = self.rs_cache_dir
        return {k: v for k, v in out.items() if v}


def _require(data: dict, key: str, kind: type, where: str) -> Any:
    if key not in data:
        raise CharterError(f"{where}: missing required key {key!r}")
    value = data[key]
    if not isinstance(value, kind):
        raise CharterError(
            f"{where}: {key!r} must be {kind.__name__}, got "
            f"{type(value).__name__}")
    return value


def parse_charter(data: dict, path: Optional[Path] = None) -> RunCharter:
    """Validate a charter mapping and build the object. Raises CharterError.

    Validation is strict on the fields the guards depend on and lenient on
    the documentary ones - a charter that cannot answer "where may I
    write" is useless, a charter with a vague budget note is merely thin.
    """
    where = str(path or "<inline>")
    if not isinstance(data, dict):
        raise CharterError(f"{where}: top level must be a JSON object")
    schema = data.get("schema")
    if schema != SCHEMA:
        raise CharterError(
            f"{where}: schema {schema!r} is not supported (expected {SCHEMA})")

    locations = _require(data, "locations", dict, where)
    results_root = str(_require(locations, "results_root", str, where)).strip()
    if not results_root:
        raise CharterError(f"{where}: locations.results_root must not be empty")

    protected = locations.get("protected", [])
    if not isinstance(protected, list) or any(
            not isinstance(e, dict) for e in protected):
        raise CharterError(
            f"{where}: locations.protected must be a list of "
            '{"path": ..., "why": ...} objects')

    def _strlist(container: dict, key: str) -> list[str]:
        value = container.get(key, [])
        if isinstance(value, str):
            value = [value]
        if not isinstance(value, list) or any(
                not isinstance(v, str) for v in value):
            raise CharterError(
                f"{where}: locations.{key} must be a string or list of "
                "strings")
        return [v.strip() for v in value if v.strip()]

    ownership = data.get("ownership", {})
    if not isinstance(ownership, dict):
        raise CharterError(f"{where}: ownership must be an object")

    # The pipeline block is what makes "every science argument explicit"
    # enforceable rather than aspirational: modules.run_plan builds its whole
    # Session from it and reads NOTHING from rs_settings.json.
    pipeline = data.get("pipeline", {})
    if not isinstance(pipeline, dict):
        raise CharterError(f"{where}: pipeline must be an object")
    answers = pipeline.get("answers", {})
    if not isinstance(answers, dict) or any(
            not isinstance(k, str) for k in answers):
        raise CharterError(
            f"{where}: pipeline.answers must be an object of "
            "cli_long -> value")
    stage_list = pipeline.get("stages", [])
    if not isinstance(stage_list, list) or any(
            not isinstance(s, str) for s in stage_list):
        raise CharterError(f"{where}: pipeline.stages must be a list of "
                           "stage names")

    agent_workspace = str(locations.get("agent_workspace", "")).strip()
    if not agent_workspace:
        agent_workspace = str(Path(results_root) / "_agent")
    if not _contains(results_root, agent_workspace):
        raise CharterError(
            f"{where}: locations.agent_workspace ({agent_workspace}) must "
            f"live under the results root ({results_root}) - agent working "
            "files belong in ONE place")

    charter = RunCharter(
        path=path,
        campaign=str(data.get("campaign", "")).strip(),
        dive=str(data.get("dive", "")).strip(),
        originals=_strlist(locations, "originals"),
        nav=_strlist(locations, "nav"),
        results_root=results_root,
        agent_workspace=agent_workspace,
        protected=[e for e in protected if str(e.get("path", "")).strip()],
        rs_instance=str(ownership.get("rs_instance", "")).strip(),
        rs_cache_dir=str(ownership.get("rs_cache_dir", "")).strip(),
        user_instances=[str(v).strip() for v in
                        ownership.get("user_instances", []) or []
                        if str(v).strip()],
        budget=data.get("budget", {}) or {},
        science=data.get("science", {}) or {},
        signed_off=data.get("signed_off", {}) or {},
        raw=data,
    )

    # A source tree that CONTAINS the results root would make every output
    # write a source write - catch it here rather than at the first refusal.
    for src in charter.originals + charter.nav:
        if _contains(src, results_root):
            raise CharterError(
                f"{where}: results_root ({results_root}) is inside the "
                f"read-only source tree {src} - outputs would be writes into "
                "source data. Declare a results root outside the originals.")
    return charter


def load_charter(path: str | Path) -> RunCharter:
    p = Path(path)
    if not p.is_file():
        raise CharterError(f"charter not found: {p}")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CharterError(f"charter {p} could not be read: {exc}") from exc
    return parse_charter(data, p.resolve())


def active_charter() -> Optional[RunCharter]:
    """The charter named by RS_RUN_CHARTER, or None when unset.

    A SET-but-broken charter raises: an agent lane that silently loses its
    contract because of a typo is the failure this whole module exists to
    prevent.
    """
    configured = os.environ.get(CHARTER_ENV, "").strip()
    if not configured:
        return None
    return load_charter(configured)


def guard_write(target: str | Path,
                charter: Optional[RunCharter] = None) -> None:
    """Refuse a write the active charter forbids. No charter = no-op."""
    charter = charter or active_charter()
    if charter is not None:
        charter.assert_writable(target)


def guard_instance(name: str,
                   charter: Optional[RunCharter] = None) -> None:
    """Refuse to drive an instance the active charter did not assign."""
    charter = charter or active_charter()
    if charter is not None:
        charter.assert_instance(name)


TEMPLATE: dict = {
    "schema": SCHEMA,
    "campaign": "<expedition>",
    "dive": "<dive>",
    "locations": {
        "originals": ["<path to the imagery - READ ONLY from this moment>"],
        "nav": ["<path to the flight log / datatables - READ ONLY>"],
        "results_root": "<path where every output goes>",
        "agent_workspace": "<results_root>/_agent",
        "protected": [
            {"path": "<path>", "why": "<why it must never be touched>"}
        ],
    },
    "ownership": {
        "rs_instance": "<the AGENT's RealityScan instance name>",
        "rs_cache_dir": "<the agent's cache dir>",
        "user_instances": ["<instances the agent must never touch>"],
    },
    "budget": {
        "expected_hours": 0,
        "memory_peak_gb": 0,
        "disk_delta_gb": 0,
        "free_disk_gb_now": 0,
        "abort_criteria": "<disk floor / silence window / memory line>",
    },
    "science": {
        "frame": "<utm:54N | local_euclidean>",
        "align_settings_xml": "<path>",
        "min_component_size": 50,
        "notes": "<every science argument explicit - no stored defaults>",
    },
    "pipeline": {
        "_comment": "answers are cli_long -> value, as main.py accepts "
                    "them. modules.run_plan builds the run plan from THIS, so "
                    "nothing is inherited from rs_settings.json.",
        "stages": ["georeference", "preprocess", "batch", "align"],
        "answers": {},
    },
    "signed_off": {"by": "", "date": "", "quote": ""},
}


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m modules.run_charter",
        description="Scaffold, validate and test a run charter.")
    parser.add_argument("--init", metavar="PATH",
                        help="write a charter template to PATH")
    parser.add_argument("--validate", metavar="PATH",
                        help="validate a charter file")
    parser.add_argument("--check", metavar="PATH",
                        help="charter to check --path against")
    parser.add_argument("--path", metavar="TARGET",
                        help="a path to test for writability")
    parser.add_argument("--instance", metavar="NAME",
                        help="an instance name to test for ownership")
    args = parser.parse_args(argv)

    if args.init:
        out = Path(args.init)
        if out.exists():
            print(f"ERROR: refusing to overwrite {out}", file=sys.stderr)
            return 2
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(TEMPLATE, indent=2), encoding="utf-8")
        print(f"wrote charter template: {out}")
        print("Fill it in WITH the owner, then have them sign it off "
              "(signed_off.by / .date) before the first write.")
        return 0

    target_charter = args.validate or args.check
    if not target_charter:
        parser.error("one of --init, --validate or --check is required")

    try:
        charter = load_charter(target_charter)
    except CharterError as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        return 2

    if args.validate:
        print(f"VALID   : {charter.path}")
        print(f"label   : {charter.label}")
        print(f"results : {charter.results_root}")
        print(f"agent ws: {charter.agent_workspace}")
        print(f"instance: {charter.rs_instance or '<unset>'}")
        print(f"readonly: {len(charter.read_only_paths)} path(s)")
        if not charter.is_signed():
            print("WARNING : NOT SIGNED OFF - no writes until the owner "
                  "signs (signed_off.by / signed_off.date)")
            return 1
        return 0

    rc = 0
    if args.path:
        reason = charter.why_forbidden(args.path)
        print(f"{'REFUSED ' if reason else 'ALLOWED '}: {args.path}"
              + (f"\n  {reason}" if reason else ""))
        rc = max(rc, 2 if reason else 0)
    if args.instance:
        try:
            charter.assert_instance(args.instance)
            print(f"ALLOWED : instance {args.instance}")
        except CharterViolation as exc:
            print(f"REFUSED : {exc}")
            rc = max(rc, 2)
    if not (args.path or args.instance):
        parser.error("--check needs --path and/or --instance")
    return rc


if __name__ == "__main__":
    sys.exit(main())
