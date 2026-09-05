"""Preflight - what is still MISSING before a run may start, as data.

The one question an agent must answer before its first write is "do I
have everything this dataset needs, or must I ask?" - and answering it in
prose produced the recorded incidents: locations inferred from directory
listings (wizard-prefill, 2026-08-08), a camera mount invented for an
unknown prefix (fabricated-provenance risk, PRODUCT_READINESS 17), zones
aligned in a frame nobody confirmed (C-20260805-01). This module makes the
answer deterministic:

    python -m modules.preflight --charter <RUN_CHARTER.json> [--json]

Exit 0  ready       - nothing missing, nothing blocking
Exit 1  not ready   - ``missing`` names every answer the OWNER must give
                      (each with the question to ask, verbatim), and/or
                      ``blocking`` names a fact that makes the run unsafe
Exit 2  invalid     - the charter does not parse

RULE FOR THE CALLER: every ``missing`` entry is a question for the owner.
Never fill one in from a listing, a previous campaign, or a plausible
guess; never proceed while the list is non-empty (``rs run`` refuses).

What is checked, in order (every check is read-only):
  charter    signed off; every declared originals/nav path exists; the
             results root is creatable; protected list present
  ownership  a real agent instance name (not '*', not a placeholder, not
             an owner instance); a cache dir
  budget     hours / memory / disk / abort criterion declared when a
             RealityScan stage is planned (mandate 6)
  science    frame declared for align; settings XML exists when named
  pipeline   at least one valid stage; every REQUIRED answer of the
             enabled chain modules present and valid (the modules' own
             Parameter declarations decide what is required - see
             run_plan.build_questions); every path/file answer exists
  cameras    every filename prefix in the imagery is a known family
             (modules/cameras.json); unknown prefixes are QUESTIONS;
             known families without a measured mount are warnings
  frame      a zone-tagged flight log agrees with science.frame
  machine    RealityScan executable and installed flight-log format
             (Windows only; reported as unchecked elsewhere); free disk
             against the declared delta
  plan       the plan builds and every command parses (run_plan)
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Optional

from .run_charter import CharterError, RunCharter, load_charter
from .run_plan import (ALL_STAGES, CHAIN_STAGES, RawDataScan, Session,
                       build_plan, build_questions, scan_cameras,
                       session_from_charter)

SCHEMA = 1

EXIT_CODES = {"ready": 0, "not_ready": 1, "invalid": 2}

#: Stages that boot RealityScan and therefore need a budget declaration.
RS_STAGES = ("align", "merge", "model", "export")

#: Disk floor every driver honours (run_models.MIN_FREE_GB).
MIN_FREE_GB = 50.0

#: Charter answers that name the imagery, most specific first.
_IMAGERY_KEYS = ("g_input", "p_input", "b_input", "r_input")
#: Charter answers that name a georeferenced FLIGHT LOG (zone-tagged
#: filename). g_flight_log is deliberately absent: it is the raw ROV nav
#: TABLE the georeference stage consumes, and never carries a zone tag.
_NAV_KEYS = ("b_flight_log_path", "r_flight_log")


def _placeholder(value: Any) -> bool:
    """True for the template's ``<fill me in>`` values and empties."""
    text = str(value if value is not None else "").strip()
    return not text or (text.startswith("<") and text.endswith(">"))


class Preflight:
    """Accumulates the report; one instance per charter."""

    def __init__(self, charter: RunCharter):
        self.charter = charter
        self.missing: list[dict] = []
        self.blocking: list[str] = []
        self.warnings: list[str] = []
        self.checked: list[str] = []

    # ------------------------------------------------------------ helpers
    def ask(self, key: str, question: str, why: str) -> None:
        self.missing.append({"key": key, "question": question, "why": why})

    def block(self, text: str) -> None:
        self.blocking.append(text)

    def warn(self, text: str) -> None:
        self.warnings.append(text)

    def ok(self, text: str) -> None:
        self.checked.append(text)

    @property
    def stages(self) -> list[str]:
        pipeline = self.charter.raw.get("pipeline") or {}
        return [str(s) for s in (pipeline.get("stages") or [])]

    @property
    def answers(self) -> dict[str, str]:
        pipeline = self.charter.raw.get("pipeline") or {}
        return {str(k): str(v) for k, v in (pipeline.get("answers") or {}).items()}

    def needs_realityscan(self) -> bool:
        return any(s in RS_STAGES for s in self.stages)

    # ------------------------------------------------------------- checks
    def check_charter(self) -> None:
        c = self.charter
        if not c.is_signed():
            self.ask("signed_off",
                     "Sign off this charter? Name and date, in your own words.",
                     "no writes before the owner signs (mandate 1)")
        else:
            self.ok(f"signed off by {c.signed_off.get('by')} on "
                    f"{c.signed_off.get('date')}")
        for label, paths in (("originals", c.originals), ("nav", c.nav)):
            if not paths:
                self.ask(f"locations.{label}",
                         f"Where is the {label.upper()} "
                         f"({'imagery tree' if label == 'originals' else 'flight log / datatables'})? "
                         "It is read-only from that moment.",
                         "declared read-only source data (mandate 2)")
                continue
            for p in paths:
                if _placeholder(p):
                    self.ask(f"locations.{label}",
                             f"Where is the {label.upper()}? The charter still "
                             f"holds a placeholder ({p}).",
                             "declared read-only source data (mandate 2)")
                elif not os.path.exists(p):
                    self.ask(f"locations.{label}",
                             f"The declared {label} path does not exist: {p}. "
                             "Where is it really?",
                             "a path nobody can read cannot be declared read-only")
                else:
                    self.ok(f"{label}: {p} exists")
        root = c.results_root
        if _placeholder(root):
            self.ask("locations.results_root",
                     "Where should OUTPUTS go (the results root)?",
                     "everything the run produces lives under it (mandate 4)")
        else:
            anchor = Path(root)
            while not anchor.exists() and anchor.parent != anchor:
                anchor = anchor.parent
            if not anchor.exists():
                self.block(f"results_root {root}: no existing ancestor - the "
                           "volume is not mounted")
            else:
                self.ok(f"results_root: {root} (nearest existing: {anchor})")
        if not c.protected:
            self.warn("no PROTECTED paths declared - confirm with the owner "
                      "that nothing on this machine must be kept off-limits "
                      "(in-progress transfers, other campaigns, GUI project "
                      "dirs, prior deliverables)")
        else:
            self.ok(f"{len(c.protected)} protected path(s) declared")

    def check_ownership(self) -> None:
        c = self.charter
        inst = c.rs_instance
        if _placeholder(inst) or inst == "*":
            self.ask("ownership.rs_instance",
                     "Which RealityScan instance name is the agent's? "
                     "(a plain token, never '*', never the owner's RS1 unless assigned)",
                     "own instance, own processes (mandate 5)")
        elif inst in c.user_instances:
            self.block(f"ownership.rs_instance {inst!r} is also listed in "
                       "ownership.user_instances - the agent may not drive an "
                       "owner instance")
        else:
            self.ok(f"agent instance {inst!r}; owner instances "
                    f"{c.user_instances or 'none declared'}")
        if _placeholder(c.rs_cache_dir):
            self.ask("ownership.rs_cache_dir",
                     "Which cache directory may the agent's RealityScan "
                     "instance use? (the cache reached 1.2 TB once and filled "
                     "the box; it grows ~72 GB per modelled component)",
                     "cache location is a per-run budget decision")
        else:
            self.ok(f"cache dir {c.rs_cache_dir}")

    def check_budget(self) -> None:
        if not self.needs_realityscan():
            self.ok("no RealityScan stage planned - budget not required")
            return
        b = self.charter.budget or {}
        numeric = [k for k in ("expected_hours", "memory_peak_gb",
                               "disk_delta_gb") if not _number(b.get(k))]
        if numeric:
            self.ask("budget",
                     "What is the budget for this run: expected duration "
                     "(h), expected memory peak (GB), expected disk delta "
                     f"(GB)? Missing: {', '.join(numeric)}.",
                     "a budget declared before launch makes 'is it stuck?' a "
                     "lookup (mandate 6)")
        if _placeholder(b.get("abort_criteria")):
            self.ask("budget.abort_criteria",
                     "What are the abort criteria (disk floor, silence "
                     "window, memory line)?",
                     "monitors need a line to compare against (mandate 6)")
        if not numeric and not _placeholder(b.get("abort_criteria")):
            self.ok("budget declared")

    def check_science(self) -> None:
        s = self.charter.science or {}
        if "align" in self.stages:
            if _placeholder(s.get("frame")):
                self.ask("science.frame",
                         "Which coordinate frame is the trajectory in "
                         "(e.g. utm:54N, or local_euclidean)?",
                         "never import a trajectory in an unconfirmed frame "
                         "(mandate 7)")
            else:
                self.ok(f"frame {s.get('frame')}")
        xml = s.get("align_settings_xml")
        if _placeholder(xml):
            self.warn("science.align_settings_xml not set - AlignZone applies "
                      "the canonical Metadata/AlignmentParams.xml")
        elif not os.path.isfile(str(xml)):
            self.ask("science.align_settings_xml",
                     f"The alignment settings XML does not exist: {xml}. "
                     "Which file should be applied?",
                     "settings are science; a missing file must not fall "
                     "back silently")
        else:
            self.ok(f"alignment settings {xml}")

    def check_pipeline(self) -> tuple[Optional[Session], bool]:
        stages = self.stages
        if not stages:
            self.ask("pipeline.stages",
                     "Which stages should this run execute? "
                     f"(any of: {', '.join(ALL_STAGES)})",
                     "an empty plan runs nothing")
            return None, False
        unknown = [s for s in stages if s not in ALL_STAGES]
        if unknown:
            self.ask("pipeline.stages",
                     f"Unknown stage(s) {unknown}. Valid: {', '.join(ALL_STAGES)}.",
                     "the plan cannot be built")
            return None, False
        session = session_from_charter(self.charter)
        chain = [s for s in CHAIN_STAGES if s in stages]
        if not chain:
            self.ok("no chain stages - no pipeline answers required")
            return session, True
        answers = self.answers
        complete = True
        # No RawDataScan: a directory listing is not an answer (ask, never
        # infer). The questions come from the modules' own Parameters.
        for q in build_questions(session, RawDataScan()):
            value = answers.get(q.arg, "").strip()
            if not value:
                if q.required or q.kind in ("path", "file"):
                    complete = False
                    self.ask(f"pipeline.answers.{q.arg}",
                             f"{q.prompt}?",
                             f"required by the {q.stage} stage "
                             f"(main.py --{q.arg})")
                continue
            problem = q.validate(value)
            if problem:
                complete = False
                self.ask(f"pipeline.answers.{q.arg}",
                         f"{q.prompt}? The charter says {value!r}, but: {problem}.",
                         f"{q.stage} stage (main.py --{q.arg})")
        if complete:
            self.ok(f"every required answer present for {', '.join(chain)}")
        return session, complete

    def imagery_root(self) -> Optional[str]:
        answers = self.answers
        for key in _IMAGERY_KEYS:
            value = answers.get(key, "").strip()
            if value and os.path.isdir(value):
                return value
        for p in self.charter.originals:
            if p and os.path.isdir(p):
                return p
        return None

    def check_cameras(self) -> None:
        if not any(s in ("georeference", "batch", "align") for s in self.stages):
            return
        root = self.imagery_root()
        if root is None:
            self.warn("camera families not checked: no existing imagery "
                      "directory among the answers/originals")
            return
        scan = scan_cameras(root)
        for prefix, (count, example) in sorted(scan.unknown.items()):
            self.ask(f"cameras.{prefix}",
                     f"Unrecognised camera filename prefix {prefix!r} "
                     f"({count:,} sampled images, e.g. {example}). Which "
                     "physical camera is it (official name), what lens, and "
                     "is its mount MEASURED (lever arm fwd/lat/down in m, "
                     "pitch in deg)? If unknown, say so - nothing is invented.",
                     "unknown camera = unknown priors; a mount is never "
                     "assumed silently (PRODUCT_READINESS 17)")
        if scan.known:
            try:
                from .georeference.georeference_images import MOUNTS  # noqa: PLC0415
            except Exception as exc:  # noqa: BLE001 - optional deps
                MOUNTS = {}
                self.warn(f"mount table not loaded ({type(exc).__name__}); "
                          "mount coverage unchecked")
            for fam, (count, example) in sorted(scan.known.items()):
                if MOUNTS and not MOUNTS.get(fam):
                    self.warn(f"camera family {fam!r} ({count:,} sampled, e.g. "
                              f"{example}) has NO measured mount - the assumed "
                              "mount convention applies (10 deg down at 30 deg "
                              "accuracy, cameras.json defaults) unless the "
                              "georeference answers say otherwise")
                else:
                    self.ok(f"camera family {fam!r}: {count:,} sampled, mount on file")
        if not scan.known and not scan.unknown:
            self.warn(f"no imagery found under {root} (extensions: "
                      "modules.image_exts.ALL_IMAGE_EXTS)")

    def check_frame(self) -> None:
        if "align" not in self.stages:
            return
        try:
            from .flight_logs import utm_zone_from_flight_log_name  # noqa: PLC0415
        except Exception as exc:  # noqa: BLE001
            self.warn(f"frame check skipped ({type(exc).__name__})")
            return
        frame = str((self.charter.science or {}).get("frame") or "").lower()
        logs = [self.answers.get(k, "").strip() for k in _NAV_KEYS]
        logs = [p for p in logs if p and os.path.isfile(p)]
        for p in logs:
            tag = utm_zone_from_flight_log_name(p)
            if tag and frame.startswith("local"):
                self.block(f"flight log {os.path.basename(p)} carries UTM zone "
                           f"tag {tag[0]}{tag[1]} but science.frame says "
                           f"{frame!r} - frames disagree (mandate 7)")
            elif not tag and frame.startswith("utm"):
                self.ask("science.frame",
                         f"science.frame says {frame!r} but the flight log "
                         f"{os.path.basename(p)} carries no UTM zone tag (the "
                         "pipeline reads the zone from the filename). Which is "
                         "right - is this a local-frame campaign?",
                         "a wrong frame imports silently (2026-08-07 incident)")
            else:
                self.ok(f"flight log {os.path.basename(p)} agrees with frame "
                        f"{frame or 'unspecified'}")

    def check_machine(self) -> None:
        if os.name != "nt":
            self.warn("RealityScan executable / flight-log format not checked "
                      "(non-Windows host)")
        else:
            try:
                from .realityscan_interface.realityscan_cli import RealityScanCLI  # noqa: PLC0415
                import logging  # noqa: PLC0415
                exe = RealityScanCLI(logging.getLogger("preflight")).find_executable()
                self.ok(f"RealityScan executable {exe}")
            except Exception as exc:  # noqa: BLE001
                if self.needs_realityscan():
                    self.block(f"RealityScan executable not found: {exc}")
            if "align" in self.stages:
                try:
                    from . import flightlog_format  # noqa: PLC0415
                    installed = flightlog_format.installed_flightlogs()
                    if installed:
                        self.ok(f"installed flightlogs.xml: {installed}")
                    else:
                        self.block("RealityScan's installed flightlogs.xml not "
                                   "found - the flight-log FORMAT cannot be "
                                   "verified (columns would drop silently)")
                except Exception as exc:  # noqa: BLE001
                    self.warn(f"flight-log format check failed: {exc}")
        root = Path(self.charter.results_root) if not _placeholder(
            self.charter.results_root) else None
        if root is not None:
            anchor = root
            while not anchor.exists() and anchor.parent != anchor:
                anchor = anchor.parent
            if anchor.exists():
                try:
                    free = shutil.disk_usage(anchor).free / 1024 ** 3
                except OSError:
                    free = None
                delta = (self.charter.budget or {}).get("disk_delta_gb")
                if free is not None:
                    if _number(delta) and free < float(delta) + MIN_FREE_GB:
                        self.block(f"{free:.0f} GB free on {anchor} but the "
                                   f"charter expects a {float(delta):.0f} GB "
                                   f"delta plus the {MIN_FREE_GB:.0f} GB floor")
                    else:
                        self.ok(f"{free:.0f} GB free on {anchor}")

    def check_plan(self, session: Optional[Session]) -> Optional[dict]:
        if session is None:
            return None
        try:
            plan = build_plan(session, self.charter)
        except ValueError as exc:
            self.block(f"plan does not build: {exc}")
            return None
        for cmd in plan["commands"]:
            if cmd.get("parses") is False:
                self.block(cmd.get("parse_error") or
                           f"{cmd['stage']}: rejected by main.py's parser")
        for w in plan["warnings"]:
            if "silently dropped" in w:
                self.block(w)
            elif "NOT SIGNED" not in w:
                self.warn(w)
        if not any(c.get("parses") is False for c in plan["commands"]):
            self.ok(f"plan builds: {len(plan['commands'])} command(s)")
        return plan

    # -------------------------------------------------------------- run
    def run(self) -> dict:
        self.check_charter()
        self.check_ownership()
        self.check_budget()
        self.check_science()
        session, _complete = self.check_pipeline()
        self.check_cameras()
        self.check_frame()
        self.check_machine()
        plan = self.check_plan(session)
        verdict = "ready" if not (self.missing or self.blocking) else "not_ready"
        return {
            "schema": SCHEMA,
            "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
            "charter": str(self.charter.path) if self.charter.path else None,
            "label": self.charter.label,
            "stages": self.stages,
            "verdict": verdict,
            "missing": self.missing,
            "blocking": self.blocking,
            "warnings": self.warnings,
            "checked": self.checked,
            "plan_commands": len(plan["commands"]) if plan else 0,
        }


def _number(value: Any) -> bool:
    try:
        return float(value) > 0
    except (TypeError, ValueError):
        return False


def preflight_charter(charter: RunCharter) -> dict:
    return Preflight(charter).run()


def format_text(report: dict) -> str:
    """ASCII-only rendering; the missing list is written as QUESTIONS."""
    lines = [f"charter : {report['charter']}",
             f"label   : {report['label']}",
             f"stages  : {', '.join(report['stages']) or '<none>'}",
             f"verdict : {report['verdict'].upper()}"]
    if report["missing"]:
        lines += ["", "ASK THE OWNER (never infer these):"]
        for i, m in enumerate(report["missing"], 1):
            lines.append(f"  {i}. [{m['key']}] {m['question']}")
            lines.append(f"     why: {m['why']}")
    if report["blocking"]:
        lines += ["", "BLOCKING (stop and report):"]
        lines += [f"  ! {b}" for b in report["blocking"]]
    if report["warnings"]:
        lines += ["", "WARNINGS:"]
        lines += [f"  - {w}" for w in report["warnings"]]
    if report["checked"]:
        lines += ["", "CHECKED:"]
        lines += [f"  ok {c}" for c in report["checked"]]
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m modules.preflight",
        description="What is still missing before a chartered run may start.")
    parser.add_argument("--charter", required=True, help="RUN_CHARTER.json")
    parser.add_argument("--json", action="store_true",
                        help="emit JSON only (default: human text)")
    parser.add_argument("--out", default=None,
                        help="also write the JSON to this path")
    args = parser.parse_args(argv)
    try:
        charter = load_charter(args.charter)
    except CharterError as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        return EXIT_CODES["invalid"]
    report = preflight_charter(charter)
    print(json.dumps(report, indent=2) if args.json else format_text(report))
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return EXIT_CODES[report["verdict"]]


if __name__ == "__main__":
    sys.exit(main())
