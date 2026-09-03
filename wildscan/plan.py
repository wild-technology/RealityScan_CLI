"""Headless run planner - the portal's command assembly, as JSON.

``wildscan.session.build_commands`` has always been a pure planner: a
Session in, a list of StageCommand(argv, env, needs_realityscan) out. The
TUI and ``wildscan.runner`` are just two consumers of it. This module is
the third: it emits the SAME plan as JSON so an unattended driver - or an
agent - reads what to run instead of re-deriving flags in prose.

    py -3.13 -m wildscan.plan --charter RUN_CHARTER.json --json
    py -3.13 -m wildscan.plan --workspace <root> --stages merge,model
    py -3.13 -m wildscan.plan --charter RUN_CHARTER.json --validate

Re-deriving flags is not a hypothetical cost. main.py builds its argparse
from the ENABLED modules only and rejects anything else with exit 2, so a
hand-written command line is wrong in a way that surfaces only after the
process starts - which is the defect testing/test_wildscan_commands_
runnable.py was written for (16 of 31 stage selections rejected on a first
session, 29 of 31 on a resumed one). ``validate_command`` here is that
test's check, promoted to a public function so the plan can be proven
runnable BEFORE it is handed to anyone.

Charter mode is the intended agent lane: the charter supplies the results
root, the RealityScan instance, the stage list and every pipeline answer,
and its env pins RS_RUN_CHARTER + RS_NO_SETTINGS_INHERITANCE onto every
child - so no stage can quietly answer itself from a previous campaign's
rs_settings.json.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Optional

from .session import (ALL_STAGES, CHAIN_STAGES, MODULE_DISPLAY, Session,
                      build_commands, default_session)

SCHEMA = 1

REPO = Path(__file__).resolve().parent.parent

_QUIET = logging.getLogger("wildscan.plan")
_QUIET.addHandler(logging.NullHandler())
_QUIET.propagate = False


def validate_command(argv: list[str], chain: list[str]) -> Optional[str]:
    """None if main.py's own parser accepts this argv, else the reason.

    Feeds the generated arguments to the REAL parser for this RS_MODULES
    selection - built from main.initialize_parameters over the enabled
    modules, exactly as the child process builds it - rather than checking
    against a parallel list of flag names that can drift.
    """
    import main as main_mod  # noqa: PLC0415  (repo root script)
    from . import session as session_mod  # noqa: PLC0415

    modules = {MODULE_DISPLAY[k]: session_mod._module_registry()[k]
               for k in chain if k in MODULE_DISPLAY}
    parser = main_mod.build_arg_parser(main_mod.initialize_parameters(modules))
    try:
        parser.parse_args(argv[2:])          # drop [python, main.py]
    except SystemExit as exc:
        return (f"main.py's own parser REJECTED this command (exit "
                f"{exc.code}); argv: {' '.join(argv[2:])}")
    return None


def session_from_charter(charter, stages: Optional[list[str]] = None
                         ) -> Session:
    """A Session built entirely from a signed charter - no stored answers.

    Every value comes from the charter file: results root, label, stage
    selection and the pipeline answers. Nothing is read from
    rs_settings.json, which is the point.
    """
    pipeline = charter.raw.get("pipeline", {}) or {}
    answers = {str(k): str(v) for k, v in
               (pipeline.get("answers", {}) or {}).items()}
    enabled = list(stages or pipeline.get("stages", []) or [])
    return Session(
        expedition=charter.campaign,
        dive=charter.dive,
        results_root=charter.results_root,
        continue_automatically=True,
        enabled=enabled,
        answers=answers,
    )


def unreached_answers(session: Session, commands: list[dict]) -> list[str]:
    """Answer keys that appear in NO generated command line.

    ``cam_*`` keys are excluded: the portal collects them as camera
    RECORDS and deliberately never passes them to main.py
    (session.write_camera_records owns them). Anything else that reaches
    no command was either misnamed or aimed at a stage that is not in this
    plan - both silent losses worth naming.
    """
    used: set[str] = set()
    for cmd in commands:
        for token in cmd["argv"]:
            if isinstance(token, str) and token.startswith("--"):
                used.add(token[2:])
    return sorted(key for key, value in session.answers.items()
                  if str(value).strip()
                  and not key.startswith(("cam_", "_"))
                  and key not in used)


def build_plan(session: Session, charter=None,
               validate: bool = True) -> dict:
    """The full run plan for a session, as the emitted JSON payload."""
    warnings: list[str] = []
    unknown = [s for s in session.enabled if s not in ALL_STAGES]
    if unknown:
        raise ValueError(
            f"unknown stage(s) {unknown}; valid stages: {list(ALL_STAGES)}")
    if not session.enabled:
        warnings.append("no stages selected - the plan is empty")
    if not session.results_root:
        raise ValueError("no results root: pass --workspace or a charter "
                         "whose locations.results_root is set")

    charter_env = charter.env() if charter is not None else {}
    if charter is not None and not charter.is_signed():
        warnings.append(
            f"charter {charter.path} is NOT SIGNED OFF (signed_off.by / "
            ".date) - no writes until the owner signs")

    chain = [k for k in CHAIN_STAGES if k in session.enabled]
    commands = []
    for cmd in build_commands(session):
        # The charter is the authority over the machine constants
        # build_commands resolved from the settings store, and it adds the
        # two variables that keep a child on the strict lane.
        env = {**cmd.env, **charter_env}
        record = {
            "stage": cmd.stage,
            "argv": list(cmd.argv),
            "env": env,
            "cwd": str(REPO),
            "needs_realityscan": cmd.needs_realityscan,
            "display": cmd.display,
        }
        if validate and str(cmd.argv[1]).endswith("main.py"):
            reason = validate_command(cmd.argv, chain)
            record["parses"] = reason is None
            if reason:
                record["parse_error"] = reason
                warnings.append(reason)
        commands.append(record)

    dropped = unreached_answers(session, commands)
    if dropped:
        # build_commands filters the answer set against the flags main.py
        # accepts for THIS chain, which is right for the portal (it
        # forwards a persisted superset by design) and wrong for a
        # charter: an argument the owner wrote down and signed off must
        # never be dropped in silence. Naming it here is the difference
        # between "the run used my settings" and "the run used the
        # defaults and said nothing".
        warnings.append(
            "answers reached NO command and were silently dropped: "
            + ", ".join(dropped)
            + " - check the flag names against `py -3.13 main.py --help`")

    return {
        "schema": SCHEMA,
        "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "label": session.label,
        "results_root": session.results_root,
        "charter": str(charter.path) if charter is not None else None,
        "stages": list(session.enabled),
        "commands": commands,
        "warnings": warnings,
    }


def format_text(plan: dict) -> str:
    """ASCII-only human rendering."""
    lines = [f"label   : {plan['label'] or '<unnamed>'}",
             f"results : {plan['results_root']}",
             f"charter : {plan['charter'] or '<none - stored answers in use>'}",
             f"stages  : {', '.join(plan['stages']) or '<none>'}", ""]
    for i, cmd in enumerate(plan["commands"], 1):
        flag = ""
        if cmd.get("parses") is False:
            flag = "  [REJECTED BY main.py's PARSER]"
        elif cmd.get("parses") is True:
            flag = "  [parses]"
        rs = " (needs RealityScan)" if cmd["needs_realityscan"] else ""
        lines.append(f"{i}. {cmd['stage']}{rs}{flag}")
        lines.append(f"   {cmd['display']}")
        if cmd["env"]:
            env = " ".join(f"{k}={v}" for k, v in sorted(cmd["env"].items()))
            lines.append(f"   env: {env}")
        lines.append("")
    if plan["warnings"]:
        lines.append("WARNINGS:")
        lines += [f"  ! {w}" for w in plan["warnings"]]
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="py -3.13 -m wildscan.plan",
        description="Emit the portal's run plan without the portal.")
    parser.add_argument("--charter", default=None,
                        help="RUN_CHARTER.json - supplies results root, "
                             "stages, answers and instance (no stored "
                             "settings are read)")
    parser.add_argument("--workspace", "-w", default=None,
                        help="results root, when not using a charter")
    parser.add_argument("--stages", default="",
                        help="comma-separated stages to plan. Valid: "
                             + ",".join(ALL_STAGES))
    parser.add_argument("--json", action="store_true",
                        help="emit JSON only (default: human text)")
    parser.add_argument("--out", default=None,
                        help="also write the JSON to this path")
    parser.add_argument("--validate", action="store_true",
                        help="exit non-zero if any command would be "
                             "rejected by main.py's parser")
    args = parser.parse_args(argv)

    stages = [s.strip() for s in args.stages.split(",") if s.strip()]
    charter = None

    if args.charter and args.workspace:
        print("ERROR: --workspace and --charter are mutually exclusive; the "
              "charter's results_root is the authority.", file=sys.stderr)
        return 2

    if args.charter:
        from modules.run_charter import CharterError, load_charter  # noqa: PLC0415
        try:
            charter = load_charter(args.charter)
        except CharterError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2
        session = session_from_charter(charter, stages or None)
    else:
        if not args.workspace:
            parser.error("one of --charter or --workspace is required")
        session = default_session()
        session.results_root = args.workspace
        session.continue_automatically = True
        session.enabled = stages

    try:
        plan = build_plan(session, charter)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(plan, indent=2) if args.json else format_text(plan))
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(plan, indent=2), encoding="utf-8")

    rejected = [c for c in plan["commands"] if c.get("parses") is False]
    if rejected:
        return 1
    if args.validate and plan["warnings"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
