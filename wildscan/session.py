"""Session model for the WildScan portal - RC_Main's interaction, preserved.

The portal mirrors the flow the pipeline has had since RC_Main:

    1. expedition / dive / data location / results root   (this module)
    2. checkbox stage selection, everything sensible pre-selected
    3. ONE question at a time, in module order, each parameter's own
       DESCRIPTION as the prompt, honouring disable_when_module_active
    4. parameter summary, then run - with gates between stages

This file owns the non-UI halves: raw-data auto-detection, results-root
structure, last-run persistence, the question list, and command assembly.
It is a PORTAL ONLY - the pipeline scripts are untouched, and chained
modules run in a single main.py invocation exactly as they always have
(the in-process hand-off between Batch Directory and Alignment IS the
current data handling; splitting them would change behaviour).

Last-run answers persist via the pipeline's own SettingsStore under the
'wildscan' section of rs_settings.json, so the next session opens with the
previous expedition, dive, data location and results root as defaults.
"""
from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .workspace import Workspace, _find_flight_logs

REPO = Path(__file__).resolve().parent.parent

_quiet = logging.getLogger("wildscan.session")
_quiet.addHandler(logging.NullHandler())
_quiet.propagate = False

VIDEO_EXTS = {".mov", ".mp4", ".avi", ".mkv", ".mts"}
NAV_HINTS = ("datatable", "nav", "flight", "rumi")
NAV_EXTS = {".csv", ".txt", ".tsv"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}

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
]


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
    from module_base.settings_store import SettingsStore
    return SettingsStore()


def load_last_run() -> dict:
    """The previous session's answers - the new defaults (owner directive)."""
    store = _settings()
    out = {}
    for key in ("expedition", "dive", "data_location", "results_base",
                "continue_automatically"):
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
    store.set("wildscan", "data_location", session.data_location)
    store.set("wildscan", "results_base", str(Path(session.results_root).parent))
    store.set("wildscan", "continue_automatically",
              session.continue_automatically)
    store.set("wildscan", "answers", dict(session.answers))


# ------------------------------------------------------------------ session

@dataclass
class Session:
    expedition: str = ""
    dive: str = ""
    data_location: str = ""
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
        data_location=last.get("data_location", ""),
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

    def validate(self, value: str) -> str | None:
        value = value.strip()
        if not value:
            return "this one is required" if self.required else None
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
_REQUIRED = {"image_input_video", "geo_input_image_dir",
             "geo_input_flight_log"}
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


def _detection_prefills(session: Session, scan: RawDataScan) -> dict[str, str]:
    """Auto-detected answers, keyed by cli_long. Only offered as defaults -
    every one still passes through its question."""
    ws = session.workspace()
    out: dict[str, str] = {}
    if scan.videos:
        out["i_input"] = str(scan.videos[0])
    raw = ws.raw_images if ws.raw_images.is_dir() else None
    if raw is None and scan.image_dirs:
        raw = scan.image_dirs[0]
    if raw:
        out["g_input"] = str(raw)
        out["p_input"] = str(raw)
    if scan.nav_files:
        out["g_flight_log"] = str(scan.nav_files[0])
    batch_src = ws.preprocessed if ws.preprocessed.is_dir() else raw
    if batch_src:
        out["b_input"] = str(batch_src)
    logs = _find_flight_logs(ws.raw_images) or _find_flight_logs(ws.root)
    logs = [p for p in logs if ws.batched not in p.parents]
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
                required=name in _REQUIRED))
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

    if chain:
        argv = [sys.executable, str(REPO / "main.py"),
                "--output_dir", session.results_root,
                "--continue_automatically", "true"]
        for arg, value in session.answers.items():
            if value.strip():
                argv += [f"--{arg}", value.strip()]
        for arg, value in _FORCED_ANSWERS.items():
            argv += [f"--{arg}", value]
        env = {"RS_MODULES": ",".join(MODULE_DISPLAY[k] for k in chain),
               "RS_NO_INTERACTIVE": "1", "PYTHONIOENCODING": "utf-8"}
        needs_rs = "align" in chain
        if needs_rs:
            env.update({"RS_INSTANCE": "RS1", "RS_CACHE_DIR": r"E:\rscache",
                        "RS_HEADLESS": "0"})
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
                "--loss_tolerance", "0.0025", "--scale_gate", "true",
                "--scale_min", "0.9", "--scale_max", "1.1"]
        commands.append(StageCommand(
            stage="Merge Components", argv=argv,
            env={"PYTHONIOENCODING": "utf-8", "RS_INSTANCE": "RS1",
                 "RS_CACHE_DIR": r"E:\rscache", "RS_HEADLESS": "0"},
            needs_realityscan=True))

    if "model" in session.enabled:
        commands.append(StageCommand(
            stage="Generate Models",
            argv=[sys.executable, str(REPO / "run_models.py"),
                  "--workspace", session.results_root],
            env={"PYTHONIOENCODING": "utf-8", "RS_INSTANCE": "RS1",
                 "RS_CACHE_DIR": r"E:\rscache", "RS_HEADLESS": "0"},
            needs_realityscan=True))

    if "export" in session.enabled:
        bat = REPO / ("modules/realityscan_interface/RS_CLI/Scripts/"
                      "ExportDeliverables.bat")
        names_file = ws.exports / "components.names"
        commands.append(StageCommand(
            stage="Export Deliverables",
            argv=["cmd", "/c", str(bat), str(ws.assembly_project() or ""),
                  str(ws.exports), str(names_file)],
            env={"RS_INSTANCE": "RS1", "RS_CACHE_DIR": r"E:\rscache",
                 "RS_HEADLESS": "0"},
            needs_realityscan=True))

    if "publish" in session.enabled:
        argv = [sys.executable, str(REPO / "publish_batch.py"),
                "--workspace", session.results_root,
                "--prefix", session.label or ws.root.name]
        if not (os.environ.get("CESIUM_ION_TOKEN")
                or os.environ.get("NIRACLIENT_DIR")):
            argv.append("--dry-run")
        commands.append(StageCommand(
            stage="Publish (Cesium / Nira)", argv=argv,
            env={"PYTHONIOENCODING": "utf-8"}))

    return commands


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
    from .workspace import _load_json  # noqa: PLC0415
    rep = _load_json(merge / "merge_report.json")
    names = [c.get("key", "").split("/")[-1]
             for rec in rep.get("clusters", [])
             for c in rec.get("final_components", [])]
    if names:
        ws.exports.mkdir(parents=True, exist_ok=True)
        with open(ws.exports / "components.names", "w",
                  encoding="utf-8", newline="\r\n") as fh:
            fh.write("\n".join(names) + "\n")
