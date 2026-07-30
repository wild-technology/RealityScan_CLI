#!/usr/bin/env python3
"""WildScan portal tests: RC_Main's interaction, preserved.

The portal contract under test:
    - raw-data auto-detection (videos, nav, imagery) feeding prefills
    - stage checkbox with resume-aware pre-selection
    - RC_Main's question order and disable_when_module_active semantics
    - last-run answers becoming the next session's defaults
    - command assembly: one main.py invocation for the chain (in-process
      hand-off preserved - the portal never changes data handling), post
      stages as separate gated commands

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

import wildscan.session as session_mod  # noqa: E402
from wildscan.session import (Session, build_commands, build_questions,  # noqa: E402
                              default_enabled, scan_raw_data)
from wildscan.workspace import Workspace  # noqa: E402


class FakeStore:
    """SettingsStore stand-in so tests never touch the repo's rs_settings."""

    def __init__(self):
        self.data = {}

    def get(self, section, key, fallback=None):
        return self.data.get(section, {}).get(key, fallback)

    def set(self, section, key, value):
        self.data.setdefault(section, {})[key] = value


@pytest.fixture
def store(monkeypatch):
    fake = FakeStore()
    monkeypatch.setattr(session_mod, "_settings", lambda: fake)
    return fake


def make_workspace(tmp_path, *, stage: str) -> Workspace:
    """A results root advanced through the pipeline up to `stage`."""
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
            "filename;X (East);Y (North);Alt\nimg_000.jpg;1;2;3\n",
            encoding="utf-8")
    if upto >= 3:
        for zone in ("zone_1", "zone_2"):
            z = ws / "batched_images_by_zone" / zone
            z.mkdir(parents=True)
            (z / "a.jpg").write_bytes(b"j")
            (z / "flight_log_4Q_UTM.txt").write_text(
                "filename;X (East);Y (North);Alt\n", encoding="utf-8")
        (ws / "batched_images_by_zone" / "batch_inputs.json").write_text(
            "{}", encoding="utf-8")
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
                    "bbox_utm": [0, 0, 10, 10]}), encoding="utf-8")
    if upto >= 5:
        m = ws / "final_assembly"
        (m / "assembly").mkdir(parents=True)
        (m / "assembly" / "Assembly.rsproj").write_bytes(b"p")
        (m / "EVALUATION_READY.txt").write_text("READY", encoding="utf-8")
        (m / "merge_report.json").write_text(json.dumps({
            "input_scales": {},
            "clusters": [{"cluster": "cluster_0", "final_components": [
                {"key": "zone_1/zone_1_c0", "camera_count": 100},
                {"key": "zone_2/zone_2_c0", "camera_count": 100}]}],
        }), encoding="utf-8")
    if upto >= 6:
        (ws / "fused_models_report.json").write_text(json.dumps({
            "components": [
                {"component": "zone_1_c0", "success": True},
                {"component": "zone_2_c0", "success": True}]}),
            encoding="utf-8")
    if upto >= 7:
        for comp in ("zone_1_c0", "zone_2_c0"):
            d = ws / "exports" / comp / "obj"
            d.mkdir(parents=True)
            (d / f"{comp}.obj").write_bytes(b"o")
    return Workspace(ws)


def make_raw_data(tmp_path):
    raw = tmp_path / "cruise_data"
    (raw / "video").mkdir(parents=True)
    (raw / "nav").mkdir()
    (raw / "video" / "dive_A.mov").write_bytes(b"v")
    (raw / "video" / "dive_B.mov").write_bytes(b"v")
    (raw / "nav" / "H2024_final_datatable.csv").write_text("t,x,y\n",
                                                           encoding="utf-8")
    (raw / "nav" / "raw_nav.csv").write_text("t,x,y\n", encoding="utf-8")
    return raw


# -------------------------------------------------------------- detection

def test_raw_data_scan_finds_video_nav_imagery(tmp_path):
    raw = make_raw_data(tmp_path)
    (raw / "stills").mkdir()
    (raw / "stills" / "a.jpg").write_bytes(b"j")
    scan = scan_raw_data(raw)
    assert len(scan.videos) == 2
    assert scan.nav_files[0].name == "H2024_final_datatable.csv", (
        "final_datatable must be preferred, mirroring geoall")
    assert scan.image_count == 1


def test_resume_aware_stage_preselection(tmp_path):
    ws = make_workspace(tmp_path, stage="align")
    enabled = default_enabled(ws)
    for done in ("extract", "georeference", "batch", "align"):
        assert done not in enabled, f"{done} is done - must start unticked"
    for todo in ("merge", "model", "export", "publish"):
        assert todo in enabled


# -------------------------------------------------------------- questions

def _session(tmp_path, enabled, data=None) -> Session:
    s = Session(expedition="NA156", dive="H2024",
                data_location=str(data) if data else "",
                results_root=str(tmp_path / "results"))
    s.enabled = enabled
    return s


def test_questions_follow_module_order_and_use_descriptions(tmp_path):
    s = _session(tmp_path, ["extract", "georeference"],
                 make_raw_data(tmp_path))
    qs = build_questions(s, scan_raw_data(s.data_location))
    stages = [q.stage for q in qs]
    assert stages == sorted(stages, key=["extract", "georeference"].index), (
        "questions must arrive in module order (RC_Main)")
    video = next(q for q in qs if q.arg == "i_input")
    assert video.required and video.kind == "file"
    assert "video" in video.prompt.lower(), (
        "the prompt is the parameter's own description")


def test_detection_prefills_the_answers(tmp_path):
    raw = make_raw_data(tmp_path)
    s = _session(tmp_path, ["extract", "georeference"], raw)
    qs = build_questions(s, scan_raw_data(raw))
    video = next(q for q in qs if q.arg == "i_input")
    assert video.default == str(raw / "video" / "dive_A.mov")
    nav = next(q for q in qs if q.arg == "g_flight_log")
    assert nav.default == str(raw / "nav" / "H2024_final_datatable.csv")


def test_disable_when_module_active_suppresses_redundant_questions(tmp_path):
    """RC_Main semantics: an enabled upstream module answers for you."""
    with_batch = _session(tmp_path, ["batch", "align"])
    qs = {q.arg for q in build_questions(with_batch, scan_raw_data(""))}
    assert "r_input" not in qs, "Batch Directory hands alignment its input"
    assert "r_flight_log" not in qs

    align_alone = _session(tmp_path, ["align"])
    qs = {q.arg for q in build_questions(align_alone, scan_raw_data(""))}
    assert "r_input" in qs, "without batch, alignment must ask"


def test_last_run_answers_are_the_new_defaults(tmp_path, store):
    s = _session(tmp_path, ["extract"])
    s.answers["i_output_fpm"] = "2.5"
    session_mod.save_last_run(s)
    reloaded = session_mod.default_session()
    assert reloaded.expedition == "NA156"
    assert reloaded.dive == "H2024"
    assert reloaded.answers.get("i_output_fpm") == "2.5"
    qs = build_questions(_session_with_answers(tmp_path, reloaded.answers),
                         scan_raw_data(""))
    fpm = next(q for q in qs if q.arg == "i_output_fpm")
    assert fpm.default == "2.5", "the last run must prefill the next"


def _session_with_answers(tmp_path, answers) -> Session:
    s = _session(tmp_path, ["extract"])
    s.answers = dict(answers)
    return s


# --------------------------------------------------------------- commands

def test_chain_runs_as_one_invocation_preserving_handoff(tmp_path):
    s = _session(tmp_path, ["georeference", "batch", "align"])
    s.answers = {"g_input": "D:/x", "g_flight_log": "D:/nav.csv"}
    commands = build_commands(s)
    chain = commands[0]
    assert chain.env["RS_MODULES"] == (
        "Georeference Images,Batch Directory,RealityScan Alignment"), (
        "chained modules MUST share one main.py process - the in-process "
        "hand-off is the pipeline's current data handling")
    argv = " ".join(chain.argv)
    assert "--g_input D:/x" in argv
    assert "--r_model_generate false" in argv, "model flags forced off"
    assert chain.needs_realityscan


def test_post_stages_are_separate_gated_commands(tmp_path):
    s = _session(tmp_path, ["merge", "model", "export", "publish"])
    commands = build_commands(s)
    assert [c.stage for c in commands] == [
        "Merge Components", "Generate Models", "Export Deliverables",
        "Publish (Cesium / Nira)"]
    merge = " ".join(commands[0].argv)
    assert "--pair_gate overlap" in merge
    assert "--loss_tolerance 0.0025" in merge
    assert "--scale_gate true" in merge


def test_publish_defaults_to_dry_run_without_credentials(tmp_path, monkeypatch):
    monkeypatch.delenv("CESIUM_ION_TOKEN", raising=False)
    monkeypatch.delenv("NIRACLIENT_DIR", raising=False)
    s = _session(tmp_path, ["publish"])
    publish = build_commands(s)[0]
    assert "--dry-run" in publish.argv


# ---------------------------------------------------------------- census

def test_empty_workspace_is_all_pending(tmp_path):
    ws = Workspace(tmp_path / "nowhere")
    assert all(s.status == "pending" for s in ws.detect().values())


def test_batch_without_fingerprint_is_partial(tmp_path):
    ws = make_workspace(tmp_path, stage="batch")
    (ws.batched / "batch_inputs.json").unlink()
    assert ws.detect()["batch"].status == "partial", (
        "unknown provenance must never read as done - the "
        "12,679-vs-9,834 blend incident is what this glyph exists for")


def test_merge_without_gate_is_partial(tmp_path):
    ws = make_workspace(tmp_path, stage="merge")
    (ws.latest_merge() / "EVALUATION_READY.txt").unlink()
    assert ws.detect()["merge"].status == "partial"


def test_components_join_scale_models_exports(tmp_path):
    ws = make_workspace(tmp_path, stage="export")
    comps = {c.key: c for c in ws.components()}
    assert comps["zone_1_c0"].modelled
    assert comps["zone_1_c0"].exported == ["obj"]


# ------------------------------------------------------------- app smoke

def test_portal_walks_session_to_stage_pick(tmp_path, store):
    from wildscan.app import StagePickScreen, WildScanApp

    results = tmp_path / "results"

    async def drive():
        app = WildScanApp()
        async with app.run_test(size=(120, 50)) as pilot:
            await pilot.pause()
            screen = app.screen
            screen.query_one("#s-expedition").value = "NA156"
            screen.query_one("#s-dive").value = "H2024"
            screen.query_one("#s-results").value = str(results)
            await pilot.pause()
            await pilot.click("#s-continue")
            await pilot.pause()
            assert isinstance(app.screen, StagePickScreen)
            picker = app.screen.query_one("#stage-pick")
            assert picker.option_count == 9
            assert results.is_dir(), "the results root must be auto-created"
    asyncio.run(drive())


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
