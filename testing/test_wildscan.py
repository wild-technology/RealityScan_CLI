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

from wildscan.stages import plan_for  # noqa: E402
from wildscan.workspace import Workspace  # noqa: E402


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


# ------------------------------------------------------------------ plans

def test_every_runnable_stage_produces_a_plan(tmp_path):
    ws = make_workspace(tmp_path, stage="align")
    for key in ("extract", "georeference", "preprocess", "batch",
                "align", "merge", "model", "export", "publish"):
        plan = plan_for(key, ws)
        assert plan is not None and plan.argv, key
        assert plan.preview, f"{key} must preview before execution"


def test_export_plan_writes_the_names_file(tmp_path):
    """The names file is the export workflow's input contract - the app must
    author it from the merge report, never the operator by hand."""
    ws = make_workspace(tmp_path, stage="merge")
    plan_for("export", ws)
    names = (ws.exports / "components.names").read_text(encoding="utf-8")
    assert names.splitlines() == ["zone_1_c0", "zone_2_c0"]


def test_publish_plan_is_dry_run_without_credentials(tmp_path, monkeypatch):
    monkeypatch.delenv("CESIUM_ION_TOKEN", raising=False)
    monkeypatch.delenv("NIRACLIENT_DIR", raising=False)
    ws = make_workspace(tmp_path, stage="export")
    plan = plan_for("publish", ws)
    assert "--dry-run" in plan.argv, (
        "no credentials must never mean silent uploads - it means preview")


def test_merge_plan_carries_the_owner_gates(tmp_path):
    ws = make_workspace(tmp_path, stage="align")
    plan = plan_for("merge", ws)
    argv = " ".join(plan.argv)
    assert "--pair_gate overlap" in argv
    assert "--loss_tolerance 0.0025" in argv
    assert "--scale_gate true" in argv


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


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
