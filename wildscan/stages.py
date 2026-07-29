"""Stage registry: forms first, then commands.

The redesign after the v1 failure (owner, 2026-07-29): v1 launched the
canonical drivers UNATTENDED - RS_NO_INTERACTIVE=1 and no data arguments -
so no stage ever asked the operator for anything and the modules fell back
to rs_settings.json defaults from whatever project last ran. An interactive
console must do the opposite: ASK, prefilled, then pass everything
explicitly.

The forms are not invented here. Module-backed stages INTROSPECT the
pipeline's own `get_parameters()` declarations (names, CLI flags, types,
defaults, prompt_user), so the app asks exactly what the CLI would ask -
one source of truth, no drift. Prefills come from, in order: what the
workspace census already knows (a found flight log, the preprocessed tree),
the operator's saved answers in rs_settings.json, then the module default.

Commands still delegate to the canonical entry points only - main.py's
module chain, merge_zones.py, the RS_CLI workflow .bats, run_models.py,
publish_batch.py. Never a second way to launch RealityScan (hard rule 1).
"""
from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .workspace import Workspace, _load_json

REPO = Path(__file__).resolve().parent.parent
IS_WINDOWS = os.name == "nt"

_quiet = logging.getLogger("wildscan.introspect")
_quiet.addHandler(logging.NullHandler())
_quiet.propagate = False


@dataclass
class Field:
    """One question the stage asks before it runs."""
    arg: str                    # --<arg> on the command line
    label: str
    kind: str = "text"          # text | path | file | number | bool
    default: str = ""
    required: bool = False
    help: str = ""

    def validate(self, value: str) -> str | None:
        """None = fine, else a human problem statement."""
        value = value.strip()
        if not value:
            return f"{self.label} is required" if self.required else None
        if self.kind == "path" and not Path(value).is_dir():
            return f"{value} is not a directory"
        if self.kind == "file" and not Path(value).is_file():
            return f"{value} is not a file"
        if self.kind == "number":
            try:
                float(value)
            except ValueError:
                return f"{self.label} must be a number"
        if self.kind == "bool" and value.lower() not in ("true", "false"):
            return f"{self.label} must be true or false"
        return None


@dataclass
class LaunchPlan:
    argv: list[str]
    env: dict[str, str] = field(default_factory=dict)
    cwd: str = str(REPO)
    needs_realityscan: bool = False

    @property
    def display_command(self) -> str:
        return " ".join(a if " " not in a else f'"{a}"' for a in self.argv)


@dataclass
class StageSpec:
    key: str
    intro: list[str]            # what this stage does / decisions in force
    fields: list[Field]
    estimate: str
    needs_realityscan: bool


# ----------------------------------------------------------- module stages

_MODULE_CLASSES = None


def _module_registry() -> dict:
    """The pipeline's own module objects, imported once. Instantiating a
    module runs no pipeline code - get_parameters() is declarative."""
    global _MODULE_CLASSES
    if _MODULE_CLASSES is None:
        from modules.extract_images.extract_images import ExtractImages
        from modules.georeference.georeference_images import GeoreferenceImages
        from modules.image_batcher.batch_directory import BatchDirectory
        from modules.preprocess_images.preprocess_images import PreprocessImages
        from modules.realityscan_interface.realityscan_interface import (
            RealityScanAlignment)
        _MODULE_CLASSES = {
            "extract": ExtractImages(_quiet),
            "georeference": GeoreferenceImages(_quiet),
            "preprocess": PreprocessImages(_quiet),
            "batch": BatchDirectory(_quiet),
            "align": RealityScanAlignment(_quiet),
        }
    return _MODULE_CLASSES


MODULE_DISPLAY = {
    "extract": "Extract Images",
    "georeference": "Georeference Images",
    "preprocess": "Preprocess Images",
    "batch": "Batch Directory",
    "align": "RealityScan Alignment",
}

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

# Data inputs the operator genuinely must supply for a fresh dataset.
_REQUIRED = {"image_input_video", "geo_input_image_dir",
             "geo_input_flight_log"}

# Alignment's model flags are dead weight in this pipeline (models are a
# separate, gated stage); pass false rather than asking. Keys are PARAMETER
# names as declared by get_parameters().
_FORCED = {"align": {"rs_model_generate": "false",
                     "rs_model_cull_poly": "false",
                     "rs_model_texture": "false",
                     "rs_model_simplify": "false",
                     "rs_display_output": "false"}}


def _settings_answers() -> dict:
    """The operator's previous CLI answers (rs_settings.json 'main')."""
    data = _load_json(REPO / "rs_settings.json")
    return data.get("main", {}) if isinstance(data, dict) else {}


def _workspace_prefills(key: str, ws: Workspace) -> dict[str, str]:
    """What the census already knows, per stage."""
    from .workspace import _find_flight_logs  # noqa: PLC0415
    out: dict[str, str] = {}
    raw = ws.raw_images if ws.raw_images.is_dir() else None
    logs = (_find_flight_logs(ws.raw_images) or _find_flight_logs(ws.root))
    logs = [p for p in logs if ws.batched not in p.parents]
    if key == "georeference" and raw:
        out["geo_input_image_dir"] = str(raw)
    if key == "preprocess" and raw:
        out["pre_input_image_dir"] = str(raw)
    if key == "batch":
        src = ws.preprocessed if ws.preprocessed.is_dir() else raw
        if src:
            out["batch_input_image_dir"] = str(src)
        if logs:
            out["batch_flight_log_path"] = str(logs[0])
    if key == "align":
        if ws.batched.is_dir():
            out["rs_input_image_dir"] = ""      # chain iterates the zones
        out["rs_project_label"] = ws.root.name.upper()
    return out


def _module_fields(key: str, ws: Workspace) -> list[Field]:
    params = _module_registry()[key].get_parameters()
    saved = _settings_answers()
    prefills = _workspace_prefills(key, ws)
    forced = _FORCED.get(key, {})
    fields = []
    for name, p in params.items():
        if name in forced:
            continue
        kind = _KIND_BY_NAME.get(name)
        if kind is None:
            kind = ("bool" if p.type is bool
                    else "number" if p.type in (int, float) else "text")
        if name in prefills:
            default = prefills[name]
        elif p.cli_long in saved and saved[p.cli_long] not in (None, ""):
            default = str(saved[p.cli_long])
        elif p.default_value is not None:
            default = str(p.default_value)
        else:
            default = ""
        fields.append(Field(
            arg=p.cli_long, label=p.name, kind=kind, default=default,
            required=name in _REQUIRED,
            help=(p.description or "").strip()))
    return fields


def _module_plan(key: str, ws: Workspace, values: dict[str, str]) -> LaunchPlan:
    argv = [sys.executable, str(REPO / "main.py"),
            "--output_dir", str(ws.root)]
    for arg, value in values.items():
        value = value.strip()
        if value:
            argv += [f"--{arg}", value]
    params = _module_registry()[key].get_parameters()
    for name, value in _FORCED.get(key, {}).items():
        if name in params:
            argv += [f"--{params[name].cli_long}", value]
    env = {"RS_MODULES": MODULE_DISPLAY[key], "RS_NO_INTERACTIVE": "1",
           "PYTHONIOENCODING": "utf-8"}
    needs_rs = key == "align"
    if needs_rs:
        env.update({"RS_INSTANCE": "RS1", "RS_CACHE_DIR": r"E:\rscache",
                    "RS_HEADLESS": "0"})
    return LaunchPlan(argv=argv, env=env, needs_realityscan=needs_rs)


# ------------------------------------------------------------ other stages

def _epsg_prefill(ws: Workspace) -> str:
    """EPSG from the detected flight log's UTM zone tag, e.g. 4Q -> 32604."""
    try:
        from modules.flight_logs import (epsg_for_utm_zone,
                                         utm_zone_from_flight_log_name)
    except ImportError:
        return ""
    from .workspace import _find_flight_logs  # noqa: PLC0415
    logs = _find_flight_logs(ws.batched) or _find_flight_logs(ws.root)
    for log in logs:
        zone_band = utm_zone_from_flight_log_name(str(log))
        if zone_band:
            try:
                return f"EPSG:{epsg_for_utm_zone(*zone_band)}"
            except (TypeError, ValueError):
                continue
    return ""


def _merge_fields(ws: Workspace) -> list[Field]:
    return [
        Field("name", "Assembly name", "text",
              f"{ws.root.name}_Assembly", required=True),
        Field("project_label", "Project label (RC_projects saves)", "text",
              ws.root.name.upper()),
        Field("min_size", "Minimum component size (cameras)", "number", "50"),
        Field("loss_tolerance", "Bounded loss (fraction of input cameras)",
              "number", "0.0025",
              help="0 = exact only. 0.0025 accepted the hull's 5-of-4865 "
                   "camera loss."),
        Field("pair_gate", "Pair gate (overlap | border)", "text", "overlap",
              help="overlap = unique features never share a merge scene "
                   "(owner criterion 2026-07-28)"),
        Field("visible", "GUI-visible RealityScan (true | false)", "bool",
              "true"),
    ]


def _merge_plan(ws: Workspace, values: dict[str, str]) -> LaunchPlan:
    argv = [sys.executable, str(REPO / "merge_zones.py"),
            "--components_root", str(ws.aligned),
            "--images_root", str(ws.batched),
            "--output", str(ws.root / "merged"),
            "--name", values.get("name", "").strip() or "Assembly",
            "--project_label", values.get("project_label", "").strip(),
            "--min_size", values.get("min_size", "50").strip() or "50",
            "--target", "0.95",
            "--visible", values.get("visible", "true").strip() or "true",
            "--auto_model", "false",
            "--ladder", "merge_first", "--merge_scope", "neighbour",
            "--pair_gate", values.get("pair_gate", "overlap").strip() or "overlap",
            "--assemble_only", "false",
            "--loss_tolerance",
            values.get("loss_tolerance", "0.0025").strip() or "0.0025",
            "--scale_gate", "true",
            "--scale_min", "0.9", "--scale_max", "1.1"]
    return LaunchPlan(argv=argv,
                      env={"PYTHONIOENCODING": "utf-8", "RS_INSTANCE": "RS1",
                           "RS_CACHE_DIR": r"E:\rscache", "RS_HEADLESS": "0"},
                      needs_realityscan=True)


def _final_component_names(ws: Workspace) -> list[str]:
    merge = ws.latest_merge()
    if not merge:
        return []
    rep = _load_json(merge / "merge_report.json")
    return [c.get("key", "").split("/")[-1]
            for rec in rep.get("clusters", [])
            for c in rec.get("final_components", [])]


def _model_fields(_ws: Workspace) -> list[Field]:
    return [Field("force", "Re-model already-successful components "
                  "(true | false)", "bool", "false")]


def _model_plan(ws: Workspace, values: dict[str, str]) -> LaunchPlan:
    argv = [sys.executable, str(REPO / "run_models.py"),
            "--workspace", str(ws.root)]
    if values.get("force", "").strip().lower() == "true":
        argv.append("--force")
    return LaunchPlan(argv=argv,
                      env={"PYTHONIOENCODING": "utf-8", "RS_INSTANCE": "RS1",
                           "RS_CACHE_DIR": r"E:\rscache", "RS_HEADLESS": "0"},
                      needs_realityscan=True)


def _export_fields(ws: Workspace) -> list[Field]:
    finals = _final_component_names(ws)
    return [Field("components", "Components (comma-separated)", "text",
                  ", ".join(finals), required=True,
                  help="prefilled from the merge report")]


def _export_plan(ws: Workspace, values: dict[str, str]) -> LaunchPlan:
    names = [n.strip() for n in values.get("components", "").split(",")
             if n.strip()]
    names_file = ws.exports / "components.names"
    ws.exports.mkdir(parents=True, exist_ok=True)
    with open(names_file, "w", encoding="utf-8", newline="\r\n") as fh:
        fh.write("\n".join(names) + "\n")
    bat = REPO / ("modules/realityscan_interface/RS_CLI/Scripts/"
                  "ExportDeliverables.bat")
    argv = ["cmd", "/c", str(bat), str(ws.assembly_project() or ""),
            str(ws.exports), str(names_file)]
    return LaunchPlan(argv=argv,
                      env={"RS_INSTANCE": "RS1", "RS_CACHE_DIR": r"E:\rscache",
                           "RS_HEADLESS": "0"},
                      needs_realityscan=True)


def _publish_fields(ws: Workspace) -> list[Field]:
    return [
        Field("prefix", "Asset name prefix", "text", ws.root.name,
              required=True),
        Field("input_crs", "Input CRS (EPSG of georeferenced exports)",
              "text", _epsg_prefill(ws)),
        Field("dry_run", "Dry run (true | false)", "bool",
              "false" if (os.environ.get("CESIUM_ION_TOKEN")
                          or os.environ.get("NIRACLIENT_DIR")) else "true",
              help="uploads need CESIUM_ION_TOKEN and/or NIRACLIENT_DIR"),
    ]


def _publish_plan(ws: Workspace, values: dict[str, str]) -> LaunchPlan:
    argv = [sys.executable, str(REPO / "publish_batch.py"),
            "--workspace", str(ws.root),
            "--prefix", values.get("prefix", "").strip() or ws.root.name]
    crs = values.get("input_crs", "").strip()
    if crs:
        argv += ["--input-crs", crs]
    if values.get("dry_run", "").strip().lower() == "true":
        argv.append("--dry-run")
    return LaunchPlan(argv=argv, env={"PYTHONIOENCODING": "utf-8"},
                      needs_realityscan=False)


# --------------------------------------------------------------- registry

_INTROS = {
    "extract": ["Extract frames from survey video into raw_images/"],
    "georeference": ["Match imagery to the nav trajectory; writes "
                     "flight_log_<zone>_UTM.txt beside the images",
                     "UTM zone derives from the nav - never hand-edited"],
    "preprocess": ["CLAHE 2.0 / 8x8 - on this imagery the baseline aligns "
                   "to NOTHING (decision in force until Q-05)"],
    "batch": ["Density-aware zoning; overlap donation capped against the "
              "donor pool", "Fingerprinted (batch_inputs.json) - reuse "
              "fails closed on changed inputs"],
    "align": ["One RealityScan scene per zone tree; calibration XMPs "
              "ensured per camera", "Exports every component >= 50 cameras "
              "with identity manifests"],
    "merge": ["pair_gate=overlap: unique features never share a merge scene",
              "Merge rungs only where shared imagery SPANS the subset; "
              "align decides the rest by content",
              "Terminal state: ONE assembly project + EVALUATION_READY"],
    "model": ["Scale-gated (stem verdicts + quantile-ratio for fused "
              "components), smallest-first",
              "Max 4 adaptive 16K textures; one dated copy at the END"],
    "export": ["Per component: OBJ by parts (Nira guidance), FBX by parts, "
               "dense colored PLY", "Sweeps default-named residual models, "
               "saves once, then exports"],
    "publish": ["Uploads the OBJ-by-parts exports - the format both "
                "platforms recommend", "Nira refuses PLY point clouds "
                "(LAS/LAZ/E57 only); scripted Nira needs Enterprise"],
}

_ESTIMATES = {
    "extract": "minutes to ~1 h depending on footage",
    "georeference": "~5 min per 30k images",
    "preprocess": "~1-2 h per 10k images",
    "batch": "seconds of computation (plots are opt-in via RS_SHOW_PLOTS)",
    "align": "measured H2024: 13-34 min per zone",
    "merge": "measured H2024: 8-70 min depending on cluster structure",
    "model": "measured H2024: 40 min (133 cams) to 5.6 h (4,860 cams)",
    "export": "~2 min per small component; dense PLY dominates on large ones",
    "publish": "upload-bound; ion tiling continues server-side",
}

_FIELD_BUILDERS = {
    "merge": _merge_fields, "model": _model_fields,
    "export": _export_fields, "publish": _publish_fields,
}
_PLAN_BUILDERS = {
    "merge": _merge_plan, "model": _model_plan,
    "export": _export_plan, "publish": _publish_plan,
}
_NEEDS_RS = {"align", "merge", "model", "export"}

RUNNABLE = set(MODULE_DISPLAY) | set(_FIELD_BUILDERS)


def spec_for(key: str, ws: Workspace) -> StageSpec | None:
    if key in MODULE_DISPLAY:
        fields = _module_fields(key, ws)
    elif key in _FIELD_BUILDERS:
        fields = _FIELD_BUILDERS[key](ws)
    else:
        return None
    intro = list(_INTROS.get(key, []))
    if key in _NEEDS_RS and not IS_WINDOWS:
        intro.insert(0, "BLOCKED on this OS: RealityScan runs on Windows "
                        "only - open this workspace on the processing box "
                        "to run this stage.")
    return StageSpec(key=key, intro=intro, fields=fields,
                     estimate=_ESTIMATES.get(key, ""),
                     needs_realityscan=key in _NEEDS_RS)


def build_plan(key: str, ws: Workspace, values: dict[str, str]) -> LaunchPlan:
    if key in MODULE_DISPLAY:
        return _module_plan(key, ws, values)
    return _PLAN_BUILDERS[key](ws, values)
