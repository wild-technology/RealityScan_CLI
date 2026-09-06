"""The run plan - THE ONE PLANNER (CLAUDE.md invariant): a Session in,
the exact commands and environment out, proven against main.py's own
parser before anything runs.

    python -m modules.run_plan --charter RUN_CHARTER.json --validate
    python -m modules.run_plan --charter RUN_CHARTER.json --json
    python -m modules.run_plan --workspace <root> --stages merge,model
    python -m modules.run_plan --questions --stages georeference,batch

Consumers (add a consumer, never a second planner): ``rs.py``
(``rs plan`` / ``rs run`` / ``rs launch``), ``modules.preflight`` (which
answers are still missing), and the archived WildScan TUI
(``archive/wildscan_tui``, which imports this module through shims).

Merged 2026-09-05 from ``wildscan/session.py`` (the session model, raw-data
detection, the question list, command assembly) and ``wildscan/plan.py``
(the headless JSON plan + validation). Nothing here launches RealityScan
or runs a stage; it only decides WHAT would run.

Charter mode is the agent lane: the charter supplies the results root, the
RealityScan instance, the stage list and every pipeline answer, and its
env pins RS_RUN_CHARTER + RS_NO_SETTINGS_INHERITANCE onto every child - so
no stage can quietly answer itself from a previous campaign's
rs_settings.json (the wizard-prefill / stale-settings incidents, 2026-08-08).
Workspace mode (no charter) plans from the results root alone and offers
the previous run's stored answers ONLY when RS_NO_SETTINGS_INHERITANCE is
not set.

Re-deriving flags by hand is not a hypothetical cost: main.py builds its
argparse from the ENABLED modules only and rejects anything else with exit
2 - before a single stage runs (16 of 31 stage selections were rejected on
a first session, 29 of 31 on a resumed one, before ``validate_command``).
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .image_exts import ALL_IMAGE_EXTS
from .workspace_census import Workspace, _find_flight_logs, _load_json, _records

REPO = Path(__file__).resolve().parent.parent

SCHEMA = 1

_quiet = logging.getLogger("modules.run_plan")
_quiet.addHandler(logging.NullHandler())
_quiet.propagate = False

VIDEO_EXTS = {".mov", ".mp4", ".avi", ".mkv", ".mts"}
NAV_HINTS = ("datatable", "nav", "flight", "rumi")
NAV_EXTS = {".csv", ".txt", ".tsv"}
#: ONE inventory of survey-image extensions (modules.image_exts). The old
#: portal copy lacked .heif, so a HEIF dataset was imagery to the census
#: and invisible to the camera scan.
IMAGE_EXTS = ALL_IMAGE_EXTS

# Pipeline module chain, in RC_Main's order, plus the post-align stages the
# portal drives as separate commands.
CHAIN_STAGES = ["extract", "georeference", "preprocess", "batch", "align"]
POST_STAGES = ["merge", "model", "export", "publish"]
ALL_STAGES = CHAIN_STAGES + POST_STAGES

MODULE_DISPLAY = {
    "extract": "Extract Images",
    "georeference": "Georeference Images",
    "preprocess": "Preprocess Images",
    "batch": "Batch Directory",
    "align": "RealityScan Alignment",
}

# The results layout the pipeline itself creates under the results root -
# shown to the operator so "auto-created structure" is explicit, created by
# the MODULES, never by the portal.
RESULTS_LAYOUT = [
    ("raw_images/", "extracted or copied survey imagery"),
    ("preprocessed_images/", "CLAHE output (align + texture source)"),
    ("batched_images_by_zone/", "per-zone trees + batch_inputs.json"),
    ("aligned_components/", "per-zone .rsalign + identity manifests"),
    ("merged/", "merge attempts, assembly project, EVALUATION_READY"),
    ("exports/", "OBJ/FBX/PLY deliverables per component"),
    ("logs/", "driver + resource logs"),
    ("RC_projects/", "dated project copies"),
    ("_agent/", "agent working files ONLY: charter, plan, RUN_STATE, launchers, "
                "logs (docs/AGENT_OPERATIONS.md sec.2)"),
]


# ----------------------------------------------------------------- cameras

# The owner's official camera table (2026-07-29) - SUGGESTIONS offered when
# an unrecognised filename prefix matches a letter, never runtime truth.
# The pipeline's camera truth is modules/cameras.json via camera_registry;
# this table only shapes the question asked about an unknown prefix.
OFFICIAL_CAMERAS = {
    "Z": "Zeuss 24mm rectilinear zoom (Standard Science Camera)",
    "C": "Cinema (fisheye; 16mm) - Widefield Camera Array",
    "P": "Port (fisheye; 16mm) - Widefield Camera Array",
    "S": "Starboard (fisheye; 16mm) - Widefield Camera Array",
    "U": "Upper (fisheye; 16mm)",
    "M": "Mid (fisheye; 16mm)",
    "L": "Lower (24mm zoom rectilinear lens)",
}


@dataclass
class CameraScan:
    """Camera identities parsed from the imagery filenames."""
    known: dict = field(default_factory=dict)     # family -> (count, example)
    unknown: dict = field(default_factory=dict)   # prefix -> (count, example)

    def summary_lines(self) -> list[str]:
        from modules import camera_registry
        lines = []
        for fam, (count, example) in sorted(self.known.items()):
            cam = camera_registry.CAMERAS.get(
                camera_registry.FAMILY_CAMERA.get(fam, ""), None)
            desc = cam.key if cam else fam
            lines.append(f"camera {desc}: {count:,} images "
                         f"({fam}, e.g. {example}) - priors on file")
        for prefix, (count, example) in sorted(self.unknown.items()):
            suggestion = OFFICIAL_CAMERAS.get(prefix.upper()[:1])
            hint = f" - looks like {suggestion}" if suggestion else ""
            lines.append(f"UNRECOGNISED camera '{prefix}': {count:,} images "
                         f"(e.g. {example}) - will ask{hint}")
        return lines


_PREFIX_RE = None


def scan_cameras(image_dir: str | Path, sample_per_dir: int = 200) -> CameraScan:
    """Parse camera identities from filenames: the registry decides KNOWN
    (priors on file); anything else groups by its leading alpha prefix and
    becomes a question."""
    import re as _re

    from modules import camera_registry
    scan = CameraScan()
    root = Path(image_dir)
    if not root.is_dir():
        return scan
    prefix_re = _re.compile(r"^([A-Za-z]+)")
    for dirpath, _dirs, files in os.walk(root):
        taken = 0
        for name in files:
            if Path(name).suffix.lower() not in IMAGE_EXTS:
                continue
            taken += 1
            if taken > sample_per_dir:
                break
            fam = camera_registry.family(name)
            if fam:
                count, example = scan.known.get(fam, (0, name))
                scan.known[fam] = (count + 1, example)
            else:
                m = prefix_re.match(name)
                prefix = (m.group(1) if m else "?").lower()
                count, example = scan.unknown.get(prefix, (0, name))
                scan.unknown[prefix] = (count + 1, example)
    return scan


def camera_questions(scan: CameraScan, saved: dict[str, str]) -> list["Question"]:
    """One block of questions per UNRECOGNISED camera prefix: the official
    name (suggested from the owner's letter table), lens, and - always -
    lever arm and tilt. Answers are recorded for the pipeline maintainers
    (camera_registry/MOUNTS stay the runtime truth) and become the next
    session's defaults."""
    questions: list[Question] = []
    for prefix in sorted(scan.unknown):
        count, example = scan.unknown[prefix]
        letter = prefix.upper()[:1]
        suggested = OFFICIAL_CAMERAS.get(letter, "")
        base = f"cam_{prefix}"
        questions += [
            Question("cameras", f"{base}_name",
                     f"Unrecognised camera '{prefix}' ({count} images, e.g. "
                     f"{example}). Official camera name",
                     "text", saved.get(f"{base}_name", suggested),
                     required=True),
            Question("cameras", f"{base}_lens",
                     f"'{prefix}' lens (e.g. fisheye 16mm / rectilinear 24mm)",
                     "text", saved.get(f"{base}_lens", "")),
            Question("cameras", f"{base}_lever",
                     f"'{prefix}' lever arm from vehicle centre, metres "
                     "forward/lateral/down (e.g. 1.0/0.0/1.0)",
                     "text", saved.get(f"{base}_lever", ""), required=True),
            Question("cameras", f"{base}_tilt",
                     f"'{prefix}' tilt (camera pitch down from horizontal, "
                     "degrees)",
                     "number", saved.get(f"{base}_tilt", ""), required=True),
        ]
    return questions


# ---------------------------------------------------------------- detection

@dataclass
class RawDataScan:
    """What the data location actually holds - drives prefills."""
    videos: list[Path] = field(default_factory=list)
    nav_files: list[Path] = field(default_factory=list)
    image_count: int = 0
    image_dirs: list[Path] = field(default_factory=list)
    utm_logs: list[Path] = field(default_factory=list)

    def summary_lines(self) -> list[str]:
        lines = []
        if self.videos:
            lines.append(f"{len(self.videos)} video(s): "
                         + ", ".join(v.name for v in self.videos[:3])
                         + (" ..." if len(self.videos) > 3 else ""))
        if self.nav_files:
            lines.append(f"{len(self.nav_files)} nav candidate(s): "
                         + ", ".join(n.name for n in self.nav_files[:3]))
        if self.image_count:
            lines.append(f"{self.image_count:,} images in "
                         f"{len(self.image_dirs)} folder(s)")
        if self.utm_logs:
            lines.append(f"georeferenced flight log present: "
                         f"{self.utm_logs[0].name}")
        if not lines:
            lines.append("nothing recognised yet - point me at the cruise "
                         "data folder")
        return lines


def scan_raw_data(location: str | Path) -> RawDataScan:
    """Read-only census of a cruise data folder (bounded depth, cheap)."""
    scan = RawDataScan()
    root = Path(location)
    if not root.is_dir():
        return scan
    image_dirs: dict[Path, int] = {}
    for dirpath, dirnames, files in os.walk(root):
        depth = len(Path(dirpath).relative_to(root).parts)
        if depth >= 3:
            dirnames[:] = []
        images_here = 0
        for name in files:
            ext = Path(name).suffix.lower()
            low = name.lower()
            path = Path(dirpath) / name
            if ext in VIDEO_EXTS:
                scan.videos.append(path)
            elif ext in NAV_EXTS and any(h in low for h in NAV_HINTS):
                if low.startswith("flight_log") and low.endswith("_utm.txt"):
                    scan.utm_logs.append(path)
                else:
                    scan.nav_files.append(path)
            elif ext in IMAGE_EXTS:
                images_here += 1
        if images_here:
            image_dirs[Path(dirpath)] = images_here
    scan.image_count = sum(image_dirs.values())
    scan.image_dirs = sorted(image_dirs, key=lambda p: -image_dirs[p])
    # Prefer *final_datatable* nav files, mirroring geoall's own preference.
    scan.nav_files.sort(key=lambda p: ("final_datatable" not in p.name.lower(),
                                       p.name.lower()))
    return scan


# -------------------------------------------------------------- persistence

def _settings():
    from module_base.settings_store import SettingsStore  # noqa: PLC0415
    return SettingsStore()


_PERSISTED_FIELDS = ("expedition", "dive", "cruise_folder", "raw_images_dir",
                     "video_path", "processed_data", "results_base",
                     "continue_automatically")


def load_last_run() -> dict:
    """The previous session's answers - the new defaults (owner directive,
    interactive lane). EMPTY under RS_NO_SETTINGS_INHERITANCE: on the
    strict lane a plan must never carry another campaign's answers, and a
    refused inheritance is announced rather than silently absent."""
    from module_base.settings_store import inheritance_refused  # noqa: PLC0415
    if inheritance_refused():
        print("REFUSING stored 'wildscan' answers as plan defaults "
              "(RS_NO_SETTINGS_INHERITANCE is set) - supply them in the charter.")
        return {}
    store = _settings()
    out = {}
    for key in _PERSISTED_FIELDS:
        value = store.get("wildscan", key, None)
        if value not in (None, ""):
            out[key] = str(value)
    answers = store.get("wildscan", "answers", None)
    if isinstance(answers, dict):
        out["answers"] = {str(k): str(v) for k, v in answers.items()}
    return out


def save_last_run(session: "Session") -> None:
    store = _settings()
    store.set("wildscan", "expedition", session.expedition)
    store.set("wildscan", "dive", session.dive)
    store.set("wildscan", "cruise_folder", session.cruise_folder)
    store.set("wildscan", "raw_images_dir", session.raw_images_dir)
    store.set("wildscan", "video_path", session.video_path)
    store.set("wildscan", "processed_data", session.processed_data)
    store.set("wildscan", "results_base", str(Path(session.results_root).parent))
    store.set("wildscan", "continue_automatically",
              session.continue_automatically)
    store.set("wildscan", "answers", dict(session.answers))


# ------------------------------------------------------------------ session

@dataclass
class Session:
    expedition: str = ""
    dive: str = ""
    # Raw data - three separate lines (owner 2026-07-29): the cruise dive
    # folder (video + nav as delivered), a folder of raw stills, and/or a
    # specific video. Any subset may be filled.
    cruise_folder: str = ""
    raw_images_dir: str = ""
    video_path: str = ""
    # Processed data - a results-SHAPED location where ROVDataConcat has
    # already run (datatables exist) but the pipeline stages have not.
    processed_data: str = ""
    results_root: str = ""
    continue_automatically: bool = False
    enabled: list[str] = field(default_factory=list)
    answers: dict[str, str] = field(default_factory=dict)   # cli_long -> value

    @property
    def label(self) -> str:
        """The expedition_dive label the pipeline's daily saves use."""
        bits = [b for b in (self.expedition.strip(), self.dive.strip()) if b]
        return "_".join(bits).upper()

    def workspace(self) -> Workspace:
        return Workspace(self.results_root)

    def suggested_results_root(self, base: str | None) -> str:
        if not (self.expedition or self.dive):
            return base or ""
        return str(Path(base or str(REPO.parent)) / self.label.lower())


def default_session() -> Session:
    last = load_last_run()
    s = Session(
        expedition=last.get("expedition", ""),
        dive=last.get("dive", ""),
        cruise_folder=last.get("cruise_folder", ""),
        raw_images_dir=last.get("raw_images_dir", ""),
        video_path=last.get("video_path", ""),
        processed_data=last.get("processed_data", ""),
        continue_automatically=(last.get("continue_automatically", "false")
                                .lower() == "true"),
        answers=dict(last.get("answers", {})),
    )
    base = last.get("results_base", "")
    if base and s.label:
        s.results_root = str(Path(base) / s.label.lower())
    return s


def default_enabled(ws: Workspace) -> list[str]:
    """Resume-aware pre-selection: stages already DONE are unticked, the
    rest ticked - RC_Main pre-selected everything; a resumable portal
    pre-selects what remains."""
    statuses = ws.detect()
    return [k for k in ALL_STAGES
            if statuses.get(k) is None or statuses[k].status != "done"]


# ---------------------------------------------------------------- questions

@dataclass
class Question:
    stage: str                   # stage key it belongs to
    arg: str                     # cli_long
    prompt: str                  # the parameter's own description (RC_Main)
    kind: str                    # text | path | file | number | bool
    default: str = ""
    required: bool = False
    choices: tuple[str, ...] = ()

    def validate(self, value: str) -> str | None:
        value = value.strip()
        if not value:
            return "this one is required" if self.required else None
        if self.choices and value.lower() not in {c.lower()
                                                  for c in self.choices}:
            return "must be one of: " + ", ".join(self.choices)
        if self.kind == "path" and not Path(value).is_dir():
            return f"{value} is not a directory"
        if self.kind == "file" and not Path(value).is_file():
            return f"{value} is not a file"
        if self.kind == "number":
            try:
                float(value)
            except ValueError:
                return "must be a number"
        if self.kind == "bool" and value.lower() not in ("true", "false"):
            return "true or false"
        return None


_KIND_BY_NAME = {
    "image_input_video": "file",
    "geo_input_image_dir": "path",
    "geo_input_flight_log": "file",
    "pre_input_image_dir": "path",
    "batch_input_image_dir": "path",
    "batch_flight_log_path": "file",
    "rs_input_image_dir": "path",
    "rs_flight_log_path": "file",
}
# geo_input_type is REQUIRED (audit 2026-08-07): it has default_value None,
# so a blank answer used to be accepted, dropped from argv, and only
# rejected by GeoreferenceImages.validate_parameters ("No data type
# specified") after the operator had already pressed Run.
_REQUIRED = {"image_input_video", "geo_input_image_dir",
             "geo_input_flight_log", "geo_input_type"}
# Answers constrained to a fixed set - validated at the question, not four
# screens later.
_CHOICES_BY_NAME = {
    "geo_input_type": ("Zeuss", "WCA", "WCA2025", "All"),
}
# Alignment's per-zone model flags are a separate, gated stage here.
_FORCED_ANSWERS = {"r_model_generate": "false", "r_model_cull_poly": "false",
                   "r_model_texture": "false", "r_model_simplify": "false",
                   "r_display_output": "false"}

_MODULES = None


def _module_registry() -> dict:
    global _MODULES
    if _MODULES is None:
        from modules.extract_images.extract_images import ExtractImages
        from modules.georeference.georeference_images import GeoreferenceImages
        from modules.image_batcher.batch_directory import BatchDirectory
        from modules.preprocess_images.preprocess_images import PreprocessImages
        from modules.realityscan_interface.realityscan_interface import (
            RealityScanAlignment)
        _MODULES = {
            "extract": ExtractImages(_quiet),
            "georeference": GeoreferenceImages(_quiet),
            "preprocess": PreprocessImages(_quiet),
            "batch": BatchDirectory(_quiet),
            "align": RealityScanAlignment(_quiet),
        }
    return _MODULES


def chain_arg_names(chain: list[str]) -> set[str]:
    """Every ``--<cli_long>`` main.py's parser ACCEPTS for this chain.

    Mirrors main.py's initialize_parameters exactly: the two global
    parameters, plus each enabled module's parameters minus any whose
    disable_when_module_active names another enabled module. main.py builds
    its argparse from the ENABLED modules only and rejects anything else
    with exit 2, so forwarding the full persisted answer set made the
    portal's own command unrunnable on 29 of 31 stage selections - and
    default_enabled() unticks completed stages, so the SECOND session
    always landed in the broken region (audit 2026-08-07).
    """
    names = {"output_dir", "continue_automatically"}
    enabled_displays = {MODULE_DISPLAY[k] for k in chain if k in MODULE_DISPLAY}
    for key in chain:
        module = _module_registry().get(key)
        if module is None:
            continue
        for p in module.get_parameters().values():
            disabled_by = getattr(p, "disable_when_module_active", None)
            if disabled_by:
                if isinstance(disabled_by, str):
                    disabled_by = [disabled_by]
                if any(d in enabled_displays for d in disabled_by):
                    continue
            names.add(p.cli_long)
    return names


def scan_processed_data(location: str | Path) -> dict[str, list[Path]]:
    """A results-shaped location where ROVDataConcat already ran: find its
    datatables and any georeferenced flight logs (read-only)."""
    out: dict[str, list[Path]] = {"datatables": [], "utm_logs": []}
    root = Path(location)
    if not root.is_dir():
        return out
    for dirpath, dirnames, files in os.walk(root):
        depth = len(Path(dirpath).relative_to(root).parts)
        if depth >= 3:
            dirnames[:] = []
        for name in files:
            low = name.lower()
            if low.endswith(".csv") and "datatable" in low:
                out["datatables"].append(Path(dirpath) / name)
            elif low.startswith("flight_log") and low.endswith("_utm.txt"):
                out["utm_logs"].append(Path(dirpath) / name)
    # geoall's own preference: *final_datatable* first.
    out["datatables"].sort(key=lambda p: ("final_datatable" not in p.name.lower(),
                                          p.name.lower()))
    return out


def _detection_prefills(session: Session, scan: RawDataScan) -> dict[str, str]:
    """Auto-detected answers, keyed by cli_long. Only offered as defaults -
    every one still passes through its question. Source priority: the
    operator's explicit lines (video / raw images / processed data) beat the
    cruise-folder scan."""
    ws = session.workspace()
    out: dict[str, str] = {}
    if session.video_path and Path(session.video_path).is_file():
        out["i_input"] = session.video_path
    elif scan.videos:
        out["i_input"] = str(scan.videos[0])
    raw = (Path(session.raw_images_dir)
           if session.raw_images_dir and Path(session.raw_images_dir).is_dir()
           else None)
    if raw is None and ws.raw_images.is_dir():
        raw = ws.raw_images
    if raw is None and scan.image_dirs:
        raw = scan.image_dirs[0]
    if raw:
        out["g_input"] = str(raw)
        out["p_input"] = str(raw)
    processed = scan_processed_data(session.processed_data) \
        if session.processed_data else {"datatables": [], "utm_logs": []}
    if processed["datatables"]:
        out["g_flight_log"] = str(processed["datatables"][0])
    elif scan.nav_files:
        out["g_flight_log"] = str(scan.nav_files[0])
    batch_src = ws.preprocessed if ws.preprocessed.is_dir() else raw
    if batch_src:
        out["b_input"] = str(batch_src)
    logs = _find_flight_logs(ws.raw_images) or _find_flight_logs(ws.root)
    logs = [p for p in logs if ws.batched not in p.parents]
    if not logs and processed["utm_logs"]:
        logs = processed["utm_logs"]
    if not logs and scan.utm_logs:
        logs = scan.utm_logs
    if logs:
        out["b_flight_log_path"] = str(logs[0])
    out["r_project_label"] = session.label
    return out


def build_questions(session: Session, scan: RawDataScan) -> list[Question]:
    """RC_Main's question list: per enabled chain module, in order, each
    prompt_user parameter - SKIPPING any whose disable_when_module_active
    names another enabled module (the upstream module will hand the value
    over in-process, exactly as the pipeline already does)."""
    enabled_displays = {MODULE_DISPLAY[k] for k in session.enabled
                        if k in MODULE_DISPLAY}
    detected = _detection_prefills(session, scan)
    questions: list[Question] = []

    # Camera identification comes FIRST: parse the imagery's camera names;
    # recognised families carry priors on file; every unrecognised prefix
    # asks for the official name plus lever/tilt (owner directive).
    image_source = detected.get("g_input") or session.raw_images_dir
    if image_source:
        cam_scan = scan_cameras(image_source)
        questions += camera_questions(cam_scan, session.answers)

    for key in CHAIN_STAGES:
        if key not in session.enabled:
            continue
        for name, p in _module_registry()[key].get_parameters().items():
            if not p.prompt_user:
                continue
            if p.cli_long in _FORCED_ANSWERS:
                continue
            disabled_by = getattr(p, "disable_when_module_active", None)
            if disabled_by:
                if isinstance(disabled_by, str):
                    disabled_by = [disabled_by]
                if any(d in enabled_displays for d in disabled_by):
                    continue
            kind = _KIND_BY_NAME.get(name)
            if kind is None:
                kind = ("bool" if p.type is bool
                        else "number" if p.type in (int, float) else "text")
            default = (detected.get(p.cli_long)
                       or session.answers.get(p.cli_long)
                       or ("" if p.default_value is None
                           else str(p.default_value)))
            questions.append(Question(
                stage=key, arg=p.cli_long,
                prompt=(p.description or p.name).strip(),
                kind=kind, default=default,
                required=name in _REQUIRED,
                choices=_CHOICES_BY_NAME.get(name, ())))
    return questions


# ----------------------------------------------------------------- commands

@dataclass
class StageCommand:
    stage: str                   # display label for the gate screen
    argv: list[str]
    env: dict[str, str]
    needs_realityscan: bool = False

    @property
    def display(self) -> str:
        return " ".join(a if " " not in a else f'"{a}"' for a in self.argv)


def build_commands(session: Session) -> list[StageCommand]:
    """The run plan: ONE main.py invocation for every enabled chain module
    (in-process hand-off preserved - portal only), then each post stage as
    its own command with a gate between them."""
    commands: list[StageCommand] = []
    chain = [k for k in CHAIN_STAGES if k in session.enabled]
    ws = session.workspace()

    # RealityScan machine constants (RS_INSTANCE / RS_CACHE_DIR /
    # RS_HEADLESS), resolved ONCE per run plan from the settings store's
    # 'realityscan' section (module_base.settings_store.realityscan_env -
    # the single source of truth; headless defaults False = visible, owner
    # decision 2026-08-07). PRECEDENCE: a variable already set in the
    # user's environment wins over the stored default - realityscan_env
    # returns the env value unchanged in that case, so when CommandRunner
    # overlays this dict onto the inherited environment the user's
    # override survives.
    from module_base.settings_store import realityscan_env
    rs_env = realityscan_env(_settings())

    if chain:
        argv = [sys.executable, str(REPO / "main.py"),
                "--output_dir", session.results_root,
                "--continue_automatically", "true"]
        # ONLY the flags main.py's parser accepts for THIS selection.
        # session.answers is the persisted superset (it carries the whole
        # previous run's answers by design, so a resumed session keeps its
        # defaults) - forwarding all of it made argparse exit 2 with
        # "unrecognized arguments" before a single stage ran.
        accepted = chain_arg_names(chain)
        for arg, value in session.answers.items():
            # cam_* answers are the portal's camera record (persisted for
            # the maintainers + next session), never main.py arguments.
            if arg.startswith("cam_"):
                continue
            if arg not in accepted:
                continue
            if value.strip():
                argv += [f"--{arg}", value.strip()]
        # The forced model flags belong to RealityScan Alignment, so they
        # are only legal when 'align' is in the chain; they used to be
        # appended unconditionally, which alone rejected every
        # align-less selection.
        if "align" in chain:
            for arg, value in _FORCED_ANSWERS.items():
                argv += [f"--{arg}", value]
        env = {"RS_MODULES": ",".join(MODULE_DISPLAY[k] for k in chain),
               "RS_NO_INTERACTIVE": "1", "PYTHONIOENCODING": "utf-8"}
        needs_rs = "align" in chain
        if needs_rs:
            env.update(rs_env)
        commands.append(StageCommand(
            stage=" + ".join(MODULE_DISPLAY[k] for k in chain),
            argv=argv, env=env, needs_realityscan=needs_rs))

    if "merge" in session.enabled:
        argv = [sys.executable, str(REPO / "merge_zones.py"),
                "--components_root", str(ws.aligned),
                "--images_root", str(ws.batched),
                "--output", str(ws.root / "merged"),
                "--name", f"{session.label or ws.root.name}_Assembly",
                "--project_label", session.label,
                "--min_size", "50", "--target", "0.95",
                "--visible", "true", "--auto_model", "false",
                "--ladder", "merge_first", "--merge_scope", "neighbour",
                "--pair_gate", "overlap", "--assemble_only", "false",
                # 0.0025 = the owner's bounded-loss decision (2026-07-28):
                # 0.25% of input cameras, sized from the hull's real loss
                # (5-11 of 4,865) with an order of magnitude of headroom.
                # Pinned HERE deliberately (not rs_settings): drivers that
                # left merge options unpinned inherited another session's
                # stored values (final review 2026-07-29, item c), and
                # test_run_plan_session pins this flag by test. Scale band 0.90-1.10
                # is the metric-scale oracle gate (2026-07-26), set after two
                # align-time scale collapses (0.175, 0.236) shipped with
                # camera-count oracles green; known-good components measure
                # 0.937-1.119. Full provenance: merge_zones.merge_cluster's
                # loss_tolerance_frac comment.
                "--loss_tolerance", "0.0025", "--scale_gate", "true",
                "--scale_min", "0.9", "--scale_max", "1.1"]
        commands.append(StageCommand(
            stage="Merge Components", argv=argv,
            env={"PYTHONIOENCODING": "utf-8", **rs_env},
            needs_realityscan=True))

    if "model" in session.enabled:
        commands.append(StageCommand(
            stage="Generate Models",
            argv=[sys.executable, str(REPO / "run_models.py"),
                  "--workspace", session.results_root],
            env={"PYTHONIOENCODING": "utf-8", **rs_env},
            needs_realityscan=True))

    if "export" in session.enabled:
        # Through the python driver -> RealityScanCLI.run_batch_script,
        # like merge and model (hard rule 1). The old ["cmd","/c",bat,...]
        # Popen had no instance lock, no marker hygiene, no verified
        # shutdown, broke on space-containing checkout paths, and let the
        # 'start ""'-booted RealityScan GUI inherit the runner's stdout
        # PIPE (WINDOWS TRAP 2026-08-07) - run_batch_script gives the .bat
        # a log file instead. Deliverable pinning (OBJ_NiraParts /
        # FBX_Parts / dense PLY) stays in ExportDeliverables.bat and its
        # Metadata presets; the driver only carries the same three
        # arguments the .bat has always taken.
        names_file = ws.exports / "components.names"
        commands.append(StageCommand(
            stage="Export Deliverables",
            argv=[sys.executable,
                  str(REPO / "modules" / "export_deliverables.py"),
                  "--project", str(ws.assembly_project() or ""),
                  "--exports", str(ws.exports),
                  "--names", str(names_file),
                  "--log_dir", str(ws.root / "logs")],
            env={"PYTHONIOENCODING": "utf-8", **rs_env},
            needs_realityscan=True))

    if "publish" in session.enabled:
        argv = [sys.executable, str(REPO / "publish_batch.py"),
                "--workspace", session.results_root,
                "--prefix", session.label or ws.root.name]
        # Placement comes from each mesh's own .rsInfo sidecar, which records
        # what the exporter actually did. The flight log is pinned here as the
        # INDEPENDENT nav check on that reading - and pinned rather than left
        # to publish_batch for the same reason --loss_tolerance is: the portal
        # states what it ran (audit 2026-08-07). Before 2026-08-31 this passed
        # --input-crs, which the exports needed because they carry raw UTM
        # metres; that flag is gone, and the vertical it could never express
        # was the reason every published wreck sat at the sea surface.
        log = workspace_flight_log(ws)
        if log:
            argv += ["--flight-log", str(log)]
        if not (os.environ.get("CESIUM_ION_TOKEN")
                or os.environ.get("NIRACLIENT_DIR")):
            argv.append("--dry-run")
        commands.append(StageCommand(
            stage="Publish (Cesium / Nira)", argv=argv,
            env={"PYTHONIOENCODING": "utf-8"}))

    return commands


def workspace_flight_log(ws: Workspace) -> Path | None:
    """The workspace's zone-tagged flight log, or None for a local-frame
    campaign (no zone tag anywhere).

    The merge output is searched first: the exported components were built
    against the merge's union log.
    """
    from modules.flight_logs import crs_for_flight_log  # noqa: PLC0415
    candidates = list(_find_flight_logs(ws.raw_images)) or \
        list(_find_flight_logs(ws.root))
    merge = ws.latest_merge()
    if merge:
        candidates = sorted(merge.glob("flight_log*_UTM.txt")) + candidates
    for path in candidates:
        if crs_for_flight_log(str(path)):
            return path
    return None


def workspace_input_crs(ws: Workspace) -> str | None:
    """``'EPSG:32654'`` for the workspace's imagery, or None.

    No longer what places an asset - that comes from each mesh's `.rsInfo`
    sidecar - but still the quickest way to state a workspace's zone.
    """
    from modules.flight_logs import crs_for_flight_log  # noqa: PLC0415
    log = workspace_flight_log(ws)
    return crs_for_flight_log(str(log)) if log else None


def write_camera_records(session: Session) -> Path | None:
    """Persist the portal's per-camera answers beside the results.

    The wizard asks for a new camera's official name, lens, LEVER ARM and
    TILT as REQUIRED answers and then drops every cam_* key when building
    main.py's argv - by design (they are records, not pipeline arguments;
    the runtime truth is modules/cameras.json + MOUNTS). Collecting a
    required answer and leaving it only in rs_settings.json meant the
    measurement the operator just took was effectively lost
    (audit 2026-08-07). Writing them into the workspace keeps them with
    the dive they describe and gives the maintainer the exact text to port
    into cameras.json / MOUNTS.

    Returns the file path, or None when there were no camera answers.
    """
    records = {k: v for k, v in session.answers.items()
               if k.startswith("cam_") and str(v).strip()}
    if not records or not session.results_root:
        return None
    import json  # noqa: PLC0415
    root = Path(session.results_root)
    root.mkdir(parents=True, exist_ok=True)
    path = root / "camera_records.json"
    payload = {
        "_comment": [
            "Camera identities the WildScan operator supplied for filename",
            "prefixes the registry did not recognise. These are RECORDS,",
            "not runtime settings: the pipeline's camera truth is",
            "modules/cameras.json (optics/calibration groups) and",
            "modules/georeference/georeference_images.py MOUNTS (lever arm,",
            "tilt, pitch accuracy). Until a prefix is added there, its",
            "images get NO pitch prior at all - deliberately, so no run",
            "invents a mount that was never measured.",
        ],
        "expedition": session.expedition,
        "dive": session.dive,
        "cameras": records,
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True)
    return path


def prepare_results_root(session: Session) -> list[str]:
    """Create the root (only the root - modules own their subfolders) and
    return the layout description for the operator."""
    root = Path(session.results_root)
    root.mkdir(parents=True, exist_ok=True)
    return [f"{name:28s} {desc}" for name, desc in RESULTS_LAYOUT]


def export_names_file(session: Session) -> None:
    """Author exports/components.names from the merge report (BOM-free)."""
    ws = session.workspace()
    merge = ws.latest_merge()
    if not merge:
        return
    rep = _load_json(merge / "merge_report.json")
    names = [c.get("key", "").split("/")[-1]
             for rec in _records(rep, "clusters")
             for c in _records(rec, "final_components")]
    names = [n for n in names if n]
    # `if names:` is deliberate but has a sharp edge the caller must cover:
    # when the CURRENT report yields nothing this returns without touching
    # an existing components.names, so a stale list survives. The export
    # stage re-resolves both --project and --names at launch time
    # (refresh_export_command below; the archived TUI does the same) for
    # exactly that reason.
    if names:
        ws.exports.mkdir(parents=True, exist_ok=True)
        with open(ws.exports / "components.names", "w",
                  encoding="utf-8", newline="\r\n") as fh:
            fh.write("\n".join(names) + "\n")


def refresh_export_command(argv: list[str], session: Session) -> list[str]:
    """Re-resolve the Export stage's ``--project`` / ``--names`` from a FRESH
    census immediately before it launches; returns the (possibly updated)
    argv. Non-export commands are returned unchanged.

    Both values are baked in at plan time, before any stage ran, so a run
    that included Merge exported the PREVIOUS run's assembly under the new
    run's name (audit 2026-08-07, fixed in the TUI; ported here 2026-09-05
    so ``rs run`` has the same protection). Also re-authors
    ``exports/components.names`` from the current merge report.
    """
    if not any(str(a).endswith("export_deliverables.py") for a in argv):
        return argv
    export_names_file(session)
    ws = session.workspace()
    project = str(ws.assembly_project() or "")
    out = list(argv)
    for flag, value in (("--project", project),
                        ("--names", str(ws.exports / "components.names"))):
        if flag in out:
            out[out.index(flag) + 1] = value
    return out


# ==========================================================================
# The headless plan (formerly wildscan/plan.py)
# ==========================================================================


def validate_command(argv: list[str], chain: list[str]) -> Optional[str]:
    """None if main.py's own parser accepts this argv, else the reason.

    Feeds the generated arguments to the REAL parser for this RS_MODULES
    selection - built from main.initialize_parameters over the enabled
    modules, exactly as the child process builds it - rather than checking
    against a parallel list of flag names that can drift.
    """
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    import main as main_mod  # noqa: PLC0415  (repo root script)

    modules = {MODULE_DISPLAY[k]: _module_registry()[k]
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
            + " - check the flag names against `python main.py --help`")

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
        prog="python -m modules.run_plan",
        description="Emit the run plan: every command and its environment, "
                    "proven against main.py's own parser.")
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
        from .run_charter import CharterError, load_charter  # noqa: PLC0415
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
