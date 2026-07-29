"""Stage registry: how each pipeline stage is previewed and launched.

Commands delegate to the CANONICAL drivers - main.py's module chain (via the
RS_MODULES / RS_NO_INTERACTIVE contract), merge_zones.py, and the RS_CLI
workflow .bats - so the app never becomes a second way to launch RealityScan
(hard rule 1). RealityScan stages are Windows-only; the registry says so
instead of failing mid-run on another OS.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .workspace import Workspace

REPO = Path(__file__).resolve().parent.parent
IS_WINDOWS = os.name == "nt"


@dataclass
class LaunchPlan:
    """Everything the confirm screen shows and the runner executes."""
    argv: list[str]
    env: dict[str, str] = field(default_factory=dict)
    cwd: str = str(REPO)
    preview: list[str] = field(default_factory=list)   # human bullet lines
    estimate: str = ""
    needs_realityscan: bool = False

    @property
    def display_command(self) -> str:
        return " ".join(a if " " not in a else f'"{a}"' for a in self.argv)


def _module_chain_plan(ws: Workspace, modules: str, preview: list[str],
                       estimate: str, extra_env: dict[str, str] | None = None,
                       needs_rs: bool = False) -> LaunchPlan:
    env = {
        "RS_MODULES": modules,
        "RS_NO_INTERACTIVE": "1",
        "PYTHONIOENCODING": "utf-8",
    }
    if needs_rs:
        env.update({"RS_INSTANCE": "RS1", "RS_CACHE_DIR": r"E:\rscache",
                    "RS_HEADLESS": "0"})
    env.update(extra_env or {})
    argv = [sys.executable, str(REPO / "main.py"),
            "--output_dir", str(ws.root)]
    return LaunchPlan(argv=argv, env=env, preview=preview,
                      estimate=estimate, needs_realityscan=needs_rs)


def plan_extract(ws: Workspace) -> LaunchPlan:
    return _module_chain_plan(
        ws, "Extract Images",
        ["Extract frames from survey video into raw_images/",
         "Prompts resolved from rs_settings.json defaults"],
        "minutes to ~1 h depending on footage length")


def plan_georeference(ws: Workspace) -> LaunchPlan:
    n = ws.detect()["extract"].summary
    return _module_chain_plan(
        ws, "Georeference Images",
        [f"Input: {n}",
         "Writes flight_log_<zone>_UTM.txt beside the imagery",
         "UTM zone derived from nav; never hand-edited (hard rule)"],
        "~5 min per 30k images (header-only image check)")


def plan_preprocess(ws: Workspace) -> LaunchPlan:
    return _module_chain_plan(
        ws, "Preprocess Images",
        ["CLAHE 2.0 / 8x8 (validated: baseline aligns to nothing on this "
         "imagery)", "Originals stay in raw_images/ for texturing decisions"],
        "~1-2 h per 10k images")


def plan_batch(ws: Workspace) -> LaunchPlan:
    return _module_chain_plan(
        ws, "Batch Directory",
        ["Density-aware zoning with symmetric overlap-donation cap",
         "Fingerprint written to batch_inputs.json (fail-closed reuse guard)",
         "Set RS_SHOW_PLOTS=1 only when a human will close the figures"],
        "~2 min of computation (plots are the only slow path)")


def plan_align(ws: Workspace) -> LaunchPlan:
    batch = ws.detect()["batch"]
    return _module_chain_plan(
        ws, "RealityScan Alignment",
        [f"Zones: {batch.summary}",
         "One scene per zone tree; calibration XMPs ensured per camera",
         "Exports every component >= 50 cameras with identity manifests"],
        "measured H2024: 13-34 min per zone (1.2k-3k images each)",
        needs_rs=True)


def plan_merge(ws: Workspace) -> LaunchPlan:
    align = ws.detect()["align"]
    out = ws.root / "merged"
    env = {"PYTHONIOENCODING": "utf-8", "RS_INSTANCE": "RS1",
           "RS_CACHE_DIR": r"E:\rscache", "RS_HEADLESS": "0"}
    argv = [sys.executable, str(REPO / "merge_zones.py"),
            "--components_root", str(ws.aligned),
            "--images_root", str(ws.batched),
            "--output", str(out),
            "--name", f"{ws.root.name}_Assembly",
            "--min_size", "50", "--target", "0.95",
            "--project_label", ws.root.name.upper(),
            "--visible", "true", "--auto_model", "false",
            "--ladder", "merge_first", "--merge_scope", "neighbour",
            "--pair_gate", "overlap", "--loss_tolerance", "0.0025",
            "--scale_gate", "true"]
    return LaunchPlan(
        argv=argv, env=env,
        preview=[f"Inputs: {align.summary}",
                 "pair_gate=overlap: unique features never share a merge scene",
                 "Merge rungs only where shared imagery SPANS the subset;"
                 " align decides the rest by content",
                 "Bounded loss 0.25% - every accepted loss is reported",
                 "Terminal state: ONE assembly project + EVALUATION_READY"],
        estimate="measured H2024: 8-70 min depending on cluster structure",
        needs_realityscan=True)


def plan_export(ws: Workspace) -> LaunchPlan:
    project = ws.assembly_project()
    merge = ws.latest_merge()
    names_file = ws.exports / "components.names"
    finals: list[str] = []
    if merge:
        from .workspace import _load_json  # noqa: PLC0415
        rep = _load_json(merge / "merge_report.json")
        finals = [c.get("key", "").split("/")[-1]
                  for rec in rep.get("clusters", [])
                  for c in rec.get("final_components", [])]
    bat = REPO / "modules/realityscan_interface/RS_CLI/Scripts/ExportDeliverables.bat"
    argv = ["cmd", "/c", str(bat), str(project or ""), str(ws.exports),
            str(names_file)]
    return LaunchPlan(
        argv=argv,
        env={"RS_INSTANCE": "RS1", "RS_CACHE_DIR": r"E:\rscache",
             "RS_HEADLESS": "0"},
        preview=[f"Project: {project}",
                 f"Components: {', '.join(finals) or 'none detected'}",
                 "Per component: OBJ by parts (Nira guidance), FBX by parts, "
                 "ultra-dense colored PLY from the raw high-poly",
                 "Sweeps residual 'Model N' entries, saves once, then exports "
                 "(vertex colors stay in memory only)"],
        estimate="minutes per small component; the hull's dense PLY dominates",
        needs_realityscan=True)


PLANS = {
    "extract": plan_extract,
    "georeference": plan_georeference,
    "preprocess": plan_preprocess,
    "batch": plan_batch,
    "align": plan_align,
    "merge": plan_merge,
    "export": plan_export,
}

RUNNABLE = set(PLANS)
# Modelling is deliberately NOT one-click in v1: it is the owner-gated,
# multi-hour step. The app shows model status and points at the driver.
MODEL_HINT = ("Models run via testing/run_h2024_final.py phase 4 or "
              "GenerateModel.bat per component - owner gate applies.")


def plan_for(key: str, ws: Workspace) -> LaunchPlan | None:
    fn = PLANS.get(key)
    if not fn:
        return None
    plan = fn(ws)
    if plan.needs_realityscan and not IS_WINDOWS:
        plan.preview.insert(
            0, "BLOCKED on this OS: RealityScan runs on Windows only - open "
               "this workspace on the processing box to run this stage.")
    return plan
