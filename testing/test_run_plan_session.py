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

Run:  python -m pytest testing/test_run_plan_session.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, REPO_ROOT)

import modules.run_plan as session_mod  # noqa: E402
from modules.run_plan import (Session, build_commands, build_questions,  # noqa: E402
                              default_enabled, scan_raw_data)
from modules.workspace_census import Workspace  # noqa: E402


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
        # Cover ALL four images: the census's coverage rule (2026-08-07,
        # workspace_census._detect_georeference) reports 'partial' when the
        # log covers under half of raw_images - a 1-row log here made the
        # 'georeference is done' premise of the resume tests false. The
        # rule is deliberate (silence-is-not-success); the fixture was
        # stale, dormant while textual was uninstalled on this box.
        (ws / "raw_images" / "flight_log_4Q_UTM.txt").write_text(
            "filename;X (East);Y (North);Alt\n"
            + "".join(f"img_{i:03d}.jpg;1;2;3\n" for i in range(4)),
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
                cruise_folder=str(data) if data else "",
                results_root=str(tmp_path / "results"))
    s.enabled = enabled
    return s


def test_questions_follow_module_order_and_use_descriptions(tmp_path):
    s = _session(tmp_path, ["extract", "georeference"],
                 make_raw_data(tmp_path))
    qs = [q for q in build_questions(s, scan_raw_data(s.cruise_folder))
          if q.stage != "cameras"]
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


def test_explicit_lines_beat_the_cruise_scan(tmp_path):
    """The separate Raw Images / Video / Processed Data lines take priority
    over anything found by scanning the cruise folder."""
    raw = make_raw_data(tmp_path)
    stills = tmp_path / "stills"
    stills.mkdir()
    (stills / "Z231_0001.jpg").write_bytes(b"j")
    other_video = tmp_path / "special.mov"
    other_video.write_bytes(b"v")
    processed = tmp_path / "processed"
    processed.mkdir()
    (processed / "H2024_final_datatable.csv").write_text("t,x,y\n",
                                                         encoding="utf-8")
    s = _session(tmp_path, ["extract"], raw)
    s.video_path = str(other_video)
    qs = build_questions(s, scan_raw_data(raw))
    assert next(q for q in qs if q.arg == "i_input").default == str(other_video)

    # georeference WITHOUT extract enabled: its input question is asked (an
    # enabled extract would answer it in-process - RC_Main semantics) and the
    # explicit lines win the prefills.
    s2 = _session(tmp_path, ["georeference"], raw)
    s2.raw_images_dir = str(stills)
    s2.processed_data = str(processed)
    qs2 = build_questions(s2, scan_raw_data(raw))
    assert next(q for q in qs2 if q.arg == "g_input").default == str(stills)
    assert next(q for q in qs2 if q.arg == "g_flight_log").default == \
        str(processed / "H2024_final_datatable.csv"), (
        "Processed Data's ROVDataConcat output must win the nav prefill")


def test_camera_parsing_recognises_registry_families(tmp_path):
    from modules.run_plan import scan_cameras
    stills = tmp_path / "stills"
    stills.mkdir()
    (stills / "P231C0001_x.jpg").write_bytes(b"j")   # WCA Port - known
    (stills / "C231C0002_x.jpg").write_bytes(b"j")   # WCA Cinema - known
    (stills / "U9990001_x.jpg").write_bytes(b"j")    # Upper - NOT in registry
    scan = scan_cameras(stills)
    assert "wca_port" in scan.known and "wca_cinema" in scan.known
    assert "u" in scan.unknown, "unrecognised prefixes must surface"


def test_unknown_camera_asks_name_lever_and_tilt(tmp_path):
    """Owner directive: unknown camera string -> ask official name; lever
    and tilt MUST be asked; the letter table suggests the official name."""
    stills = tmp_path / "stills"
    stills.mkdir()
    (stills / "U9990001_x.jpg").write_bytes(b"j")
    s = _session(tmp_path, ["georeference"])
    s.raw_images_dir = str(stills)
    qs = build_questions(s, scan_raw_data(""))
    cam_qs = {q.arg: q for q in qs if q.stage == "cameras"}
    assert "cam_u_name" in cam_qs and cam_qs["cam_u_name"].required
    assert cam_qs["cam_u_name"].default == "Upper (fisheye; 16mm)", (
        "the owner's letter table must suggest the official name")
    assert "cam_u_lever" in cam_qs and cam_qs["cam_u_lever"].required
    assert "cam_u_tilt" in cam_qs and cam_qs["cam_u_tilt"].required


def test_known_cameras_ask_nothing(tmp_path):
    stills = tmp_path / "stills"
    stills.mkdir()
    (stills / "P231C0001_x.jpg").write_bytes(b"j")
    s = _session(tmp_path, ["georeference"])
    s.raw_images_dir = str(stills)
    qs = build_questions(s, scan_raw_data(""))
    assert not [q for q in qs if q.stage == "cameras"], (
        "recognised families have priors on file - no questions")


def test_camera_answers_never_reach_main_py(tmp_path):
    s = _session(tmp_path, ["georeference"])
    s.answers = {"g_input": "D:/x", "cam_u_name": "Upper (fisheye; 16mm)",
                 "cam_u_lever": "1.0/0.0/1.0", "cam_u_tilt": "45"}
    chain = build_commands(s)[0]
    argv = " ".join(chain.argv)
    assert "--g_input" in argv
    assert "cam_u" not in argv, (
        "camera records are portal data, not pipeline arguments")


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


def test_export_runs_through_the_python_driver(tmp_path):
    """Hard rule 1: every RealityScan launch goes through RealityScanCLI.
    The export stage used to Popen the .bat via raw ["cmd","/c",...] - no
    lock, no marker hygiene, no verified shutdown, and the booted GUI
    inherited the runner's stdout pipe (WINDOWS TRAP 2026-08-07)."""
    ws = make_workspace(tmp_path, stage="model")
    s = _session(tmp_path, ["export"])
    s.results_root = str(ws.root)
    export = build_commands(s)[0]
    assert export.stage == "Export Deliverables"
    assert export.needs_realityscan
    assert "cmd" not in export.argv, "raw cmd /c launches are banned"
    assert export.argv[0] == sys.executable
    assert export.argv[1].endswith("export_deliverables.py")
    joined = " ".join(export.argv)
    assert "--project" in joined
    assert str(ws.assembly_project()) in export.argv
    assert str(ws.exports) in export.argv
    assert str(ws.exports / "components.names") in export.argv
    assert str(ws.root / "logs") in export.argv, (
        "driver logs belong in the workspace logs/ dir like every stage")
    assert export.env.get("PYTHONIOENCODING") == "utf-8"


def test_export_driver_goes_through_the_execution_layer(tmp_path, monkeypatch):
    """run_export must delegate to RealityScanCLI.run_batch_script with the
    .bat's own three-argument contract - never spawn cmd itself."""
    from modules import export_deliverables as ed

    calls = {}

    class FakeCLI:
        def __init__(self, logger, settings=None, instance_name=None):
            pass

        def run_batch_script(self, script_name, args, log_dir, **kwargs):
            calls["script"] = script_name
            calls["args"] = list(args)
            calls["log_dir"] = log_dir

            class R:
                success = True
            return R()

    monkeypatch.setattr(ed, "RealityScanCLI", FakeCLI)
    # Keep the test hermetic: run_export overlays realityscan_env onto
    # os.environ (env wins in production); a real overlay would leak
    # RS_* into every later test in this process.
    monkeypatch.setattr(ed, "realityscan_env", lambda store: {})

    project = tmp_path / "Assembly.rsproj"
    project.write_bytes(b"p")
    exports = tmp_path / "exports"
    exports.mkdir()
    names = exports / "components.names"
    names.write_text("zone_1_c0\n", encoding="utf-8")

    res = ed.run_export(str(project), str(exports), str(names),
                        settings=FakeStore())
    assert res.success
    assert calls["script"] == "ExportDeliverables.bat"
    assert calls["args"] == [str(project), str(exports), str(names)], (
        "argument order is the .bat contract: project, out dir, name list")
    assert calls["log_dir"] == str(tmp_path / "logs"), (
        "default log dir is <exports parent>/logs - the workspace logs/")


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
    """Smoke test of the ARCHIVED TUI (archive/wildscan_tui): it must still
    walk its first two screens over the live planner. Skipped without
    textual - the UI is archived, so it is not a pipeline dependency."""
    pytest.importorskip("textual")
    tui_root = os.path.join(REPO_ROOT, "archive", "wildscan_tui")
    if tui_root not in sys.path:
        sys.path.insert(0, tui_root)
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
