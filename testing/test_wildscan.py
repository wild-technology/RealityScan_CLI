#!/usr/bin/env python3
"""WildScan tests: workspace detection census + a headless app smoke.

Detection is the load-bearing part - it decides what a resuming user sees
and which stage the app offers to run. Fixtures mirror the REAL artifact
contracts (batch_inputs.json, *.rsalign.manifest.json, merge_report.json,
EVALUATION_READY.txt, fused_models_report.json) rather than invented ones.

Run:  py -3.13 -m pytest testing/test_wildscan.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, REPO_ROOT)

pytest.importorskip("textual")

from wildscan.stages import build_plan, spec_for  # noqa: E402
from wildscan.workspace import Workspace  # noqa: E402


def defaults_of(spec) -> dict:
    return {f.arg: f.default for f in spec.fields}


def make_workspace(tmp_path, *, stage: str):
    """Build a workspace advanced through the pipeline up to `stage`."""
    ws = tmp_path / "cruise"
    order = ["empty", "extract", "georeference", "batch", "align",
             "merge", "model", "export"]
    upto = order.index(stage)

    if upto >= 1:
        raw = ws / "raw_images"
        raw.mkdir(parents=True)
        for i in range(4):
            (raw / f"img_{i:03d}.jpg").write_bytes(b"j")
    if upto >= 2:
        (ws / "raw_images" / "flight_log_4Q_UTM.txt").write_text(
            "filename;X (East);Y (North);Alt\n"
            "img_000.jpg;1;2;3\nimg_001.jpg;2;2;3\n", encoding="utf-8")
    if upto >= 3:
        for zone in ("zone_1", "zone_2"):
            z = ws / "batched_images_by_zone" / zone
            z.mkdir(parents=True)
            (z / "a.jpg").write_bytes(b"j")
            (z / "flight_log_4Q_UTM.txt").write_text(
                "filename;X (East);Y (North);Alt\n", encoding="utf-8")
        (ws / "batched_images_by_zone" / "batch_inputs.json").write_text(
            json.dumps({"flight_log": "flight_log_4Q_UTM.txt"}),
            encoding="utf-8")
    if upto >= 4:
        for zone, comps in (("zone_1", 2), ("zone_2", 1)):
            z = ws / "aligned_components" / zone
            z.mkdir(parents=True)
            for c in range(comps):
                name = f"{zone}_c{c}"
                (z / f"{name}.rsalign").write_bytes(b"r")
                (z / f"{name}.rsalign.manifest.json").write_text(json.dumps({
                    "schema": 1, "zone": zone, "component": name,
                    "rsalign": str(z / f"{name}.rsalign"),
                    "camera_count": 100 + c, "images": ["a.jpg"],
                    "bbox_utm": [0, 0, 10, 10],
                }), encoding="utf-8")
    if upto >= 5:
        m = ws / "final_assembly"
        (m / "assembly").mkdir(parents=True)
        (m / "assembly" / "Assembly.rsproj").write_bytes(b"p")
        (m / "EVALUATION_READY.txt").write_text("EVALUATION READY",
                                                encoding="utf-8")
        (m / "merge_report.json").write_text(json.dumps({
            "schema": 2,
            "input_scales": {"zone_1/zone_1_c0": {"status": "pass",
                                                  "median": 0.99}},
            "clusters": [{"cluster": "cluster_0",
                          "final_components": [
                              {"key": "zone_1/zone_1_c0", "camera_count": 100},
                              {"key": "zone_2/zone_2_c0", "camera_count": 100},
                          ]}],
        }), encoding="utf-8")
    if upto >= 6:
        (ws / "fused_models_report.json").write_text(json.dumps({
            "components": [
                {"component": "zone_1_c0", "success": True,
                 "duration_min": 12.0, "scale": 0.991, "status": "pass"},
                {"component": "zone_2_c0", "success": True,
                 "duration_min": 8.0},
            ]}), encoding="utf-8")
    if upto >= 7:
        for comp in ("zone_1_c0", "zone_2_c0"):
            for kind in ("obj", "fbx", "ply"):
                d = ws / "exports" / comp / kind
                d.mkdir(parents=True)
                (d / f"{comp}.{kind}").write_bytes(b"x")
    return Workspace(ws)


# ------------------------------------------------------------- detection

def test_empty_workspace_is_all_pending(tmp_path):
    ws = Workspace(tmp_path / "nowhere")
    statuses = ws.detect()
    assert all(s.status == "pending" for s in statuses.values())


def test_mid_cruise_detection(tmp_path):
    ws = make_workspace(tmp_path, stage="align")
    st = ws.detect()
    assert st["extract"].status == "done"
    assert st["georeference"].status == "done"
    assert st["batch"].status == "done"
    assert st["align"].status == "done"
    assert "3 components" in st["align"].summary
    assert st["merge"].status == "pending"
    assert st["model"].status == "pending"


def test_batch_without_fingerprint_is_partial(tmp_path):
    ws = make_workspace(tmp_path, stage="batch")
    (ws.batched / "batch_inputs.json").unlink()
    assert ws.detect()["batch"].status == "partial", (
        "unknown provenance must never read as done - the 12,679-vs-9,834 "
        "blend incident is what this glyph exists for")


def test_merge_without_gate_is_partial(tmp_path):
    ws = make_workspace(tmp_path, stage="merge")
    (ws.latest_merge() / "EVALUATION_READY.txt").unlink()
    assert ws.detect()["merge"].status == "partial"


def test_finished_workspace_reads_done_end_to_end(tmp_path):
    ws = make_workspace(tmp_path, stage="export")
    st = ws.detect()
    assert st["merge"].status == "done"
    assert st["model"].status == "done"
    assert st["export"].status == "done"


def test_components_join_scale_models_exports(tmp_path):
    ws = make_workspace(tmp_path, stage="export")
    comps = {c.key: c for c in ws.components()}
    c0 = comps["zone_1_c0"]
    assert c0.modelled and c0.model_minutes == 12.0
    assert c0.scale == pytest.approx(0.991)
    assert c0.scale_status == "pass"
    assert c0.exported == ["fbx", "obj", "ply"]


# --------------------------------------------------- forms (ask, THEN run)

def test_every_runnable_stage_asks_before_running(tmp_path):
    """The v1 failure: stages launched unattended with no data arguments and
    the modules silently inherited another project's rs_settings defaults.
    Every stage must now present a form and build its command from the
    answers."""
    ws = make_workspace(tmp_path, stage="align")
    for key in ("extract", "georeference", "preprocess", "batch",
                "align", "merge", "model", "export", "publish"):
        spec = spec_for(key, ws)
        assert spec is not None and spec.fields, f"{key} must ask for data"
        plan = build_plan(key, ws, defaults_of(spec))
        assert plan.argv, key


def test_module_forms_come_from_the_modules_own_declarations(tmp_path):
    """One source of truth: the fields ARE get_parameters()."""
    ws = make_workspace(tmp_path, stage="empty")
    spec = spec_for("extract", ws)
    args = {f.arg for f in spec.fields}
    assert "i_input" in args, "the video path must be asked for"
    video = next(f for f in spec.fields if f.arg == "i_input")
    assert video.required and video.kind == "file"

    spec = spec_for("georeference", ws)
    args = {f.arg for f in spec.fields}
    assert {"g_input", "g_flight_log"} <= args


def test_workspace_prefills_beat_settings_and_defaults(tmp_path):
    ws = make_workspace(tmp_path, stage="georeference")
    spec = spec_for("georeference", ws)
    g_input = next(f for f in spec.fields if f.arg == "g_input")
    assert g_input.default == str(ws.raw_images), (
        "detected imagery must prefill the form")


def test_user_answers_reach_the_command_line(tmp_path):
    ws = make_workspace(tmp_path, stage="empty")
    spec = spec_for("extract", ws)
    values = defaults_of(spec)
    values["i_input"] = r"D:\dive\video.mov"
    plan = build_plan("extract", ws, values)
    argv = plan.argv
    assert "--i_input" in argv
    assert argv[argv.index("--i_input") + 1] == r"D:\dive\video.mov"
    assert plan.env.get("RS_MODULES") == "Extract Images"


def test_required_field_validation_blocks_the_run(tmp_path):
    ws = make_workspace(tmp_path, stage="empty")
    spec = spec_for("extract", ws)
    video = next(f for f in spec.fields if f.arg == "i_input")
    assert video.validate("") is not None, "empty required field must fail"
    assert video.validate(r"C:\definitely\missing.mov") is not None
    fpm = next(f for f in spec.fields if f.arg == "i_output_fpm")
    assert fpm.validate("not-a-number") is not None
    assert fpm.validate("2.5") is None


def test_export_form_writes_the_names_file(tmp_path):
    """The names file is the export workflow's input contract - authored
    from the operator's (prefilled) component list, never by hand."""
    ws = make_workspace(tmp_path, stage="merge")
    spec = spec_for("export", ws)
    build_plan("export", ws, defaults_of(spec))
    names = (ws.exports / "components.names").read_text(encoding="utf-8")
    assert names.splitlines() == ["zone_1_c0", "zone_2_c0"]


def test_publish_defaults_to_dry_run_without_credentials(tmp_path, monkeypatch):
    monkeypatch.delenv("CESIUM_ION_TOKEN", raising=False)
    monkeypatch.delenv("NIRACLIENT_DIR", raising=False)
    ws = make_workspace(tmp_path, stage="export")
    spec = spec_for("publish", ws)
    plan = build_plan("publish", ws, defaults_of(spec))
    assert "--dry-run" in plan.argv, (
        "no credentials must never mean silent uploads - it means preview")


def test_merge_plan_carries_the_owner_gates(tmp_path):
    ws = make_workspace(tmp_path, stage="align")
    spec = spec_for("merge", ws)
    plan = build_plan("merge", ws, defaults_of(spec))
    argv = " ".join(plan.argv)
    assert "--pair_gate overlap" in argv
    assert "--loss_tolerance 0.0025" in argv
    assert "--scale_gate true" in argv
    assert "--assemble_only false" in argv


# ------------------------------------------------------------- app smoke

def test_app_boots_and_shows_pipeline(tmp_path):
    from wildscan.app import WildScanApp

    ws = make_workspace(tmp_path, stage="align")

    async def drive():
        app = WildScanApp(str(ws.root))
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            table = app.screen.query_one("#pipeline")
            assert table.row_count == 9
    asyncio.run(drive())


def test_stage_screen_renders_the_form_and_blocks_until_valid(tmp_path):
    """Open the extract stage on an empty workspace: the video field is
    empty and required, so a problem is shown and Run is disabled; filling
    it with a real file enables Run and puts the value in the command."""
    from wildscan.app import StageScreen, WildScanApp

    ws = make_workspace(tmp_path, stage="empty")
    ws.root.mkdir(parents=True, exist_ok=True)
    video = ws.root / "dive.mov"
    video.write_bytes(b"v")

    async def drive():
        app = WildScanApp(str(ws.root))
        async with app.run_test(size=(120, 50)) as pilot:
            await pilot.pause()
            app.push_screen(StageScreen("extract"))
            await pilot.pause()
            screen = app.screen
            run = screen.query_one("#run")
            assert run.disabled, "empty required field must block Run"
            field = screen.query_one("#field-i_input")
            field.value = str(video)
            await pilot.pause()
            assert not run.disabled, "a valid form must enable Run"
            assert screen.plan is not None
            assert str(video) in screen.plan.display_command
    asyncio.run(drive())


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
