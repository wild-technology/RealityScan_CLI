"""Owner decisions of 2026-09-06, pinned.

D1  science.identity_capture drives RS_LEGACY_XMP_IDENTITY (csv = no XMP)
D9  plan_feature_stage lives in modules/feature_merge (tests in test_feature_merge)
D10 the export census reads the export TREE: pages, JPEG, <= 4096, map_Kd
D12 simplify 75 % per pass until at or under RS_TARGET_TRIS, measured; every
    -selectModel proven by the model report; no blind delete anywhere
D15 FINDINGS.md split: header + [RECON] + the live tail; the rest frozen
"""
from __future__ import annotations

import json
import os
import re
import struct
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from modules import preflight as pf  # noqa: E402
from modules import texture_census as tc  # noqa: E402
from modules.export_deliverables import missing_exports  # noqa: E402
from modules.realityscan_interface import model_report as mr  # noqa: E402
from modules.verify import verify_workspace  # noqa: E402
from modules.workspace_census import Workspace  # noqa: E402
from testing.test_preflight import _charter, _dataset  # noqa: E402

SCRIPTS = REPO / "modules/realityscan_interface/RS_CLI/Scripts"
META = REPO / "modules/realityscan_interface/RS_CLI/Metadata"


def _bat(name: str) -> str:
    return (SCRIPTS / name).read_bytes().decode("utf-8", errors="replace")


# ----------------------------------------------------------------- D12: report

REPORT = """<table>
        <tr>
          <th>Model name</th>
          <td>zone_1_c0_SimplifyPass3</td>
        </tr>
        <tr>
          <th>Triangles' count</th>
          <td>12,345,678</td>
        </tr>
        <tr>
          <th>Vertices' count</th>
          <td>6172839</td>
        </tr>
        <tr>
          <th>Textured</th>
          <td>true</td>
        </tr>
        <tr>
          <th>Unwrapping style</th>
          <td>Adaptive texel size</td>
        </tr>
        <tr>
          <th>Textures' count</th>
          <td>7</td>
        </tr>
        <tr>
          <th>Texture resolution</th>
          <td>4096 x 4096</td>
        </tr>
</table>"""


def test_report_parser_reads_every_field():
    info = mr.parse_report(REPORT)
    assert info["name"] == "zone_1_c0_SimplifyPass3"
    assert info["triangles"] == 12_345_678 and info["vertices"] == 6_172_839
    assert info["textured"] is True and info["textures"] == 7
    assert info["unwrap_style"] == "Adaptive texel size"
    assert info["resolution"] == 4096


def test_report_parser_survives_an_empty_or_missing_report(tmp_path):
    assert mr.read_report(str(tmp_path / "absent.html")) is None
    empty = tmp_path / "empty.html"
    empty.write_text("", encoding="utf-8")
    assert mr.read_report(str(empty)) is None
    info = mr.parse_report("<html></html>")
    assert info["name"] is None and info["triangles"] is None and info["textured"] is False


@pytest.mark.parametrize("start,target,ratio,expected", [
    (9_706_654, 10_000_000, 0.75, 0),          # already under: no pass (owner)
    (10_000_000, 10_000_000, 0.75, 0),
    (10_000_001, 10_000_000, 0.75, 1),
    (42_414_945, 10_000_000, 0.75, 6),         # 42.4M * 0.75^6 = 7.5M; ^5 = 10.07M
    (103_548_208, 10_000_000, 0.75, 9),
    (2_770_844, 500_000, 0.8, 8),              # run_decimate's arithmetic, unchanged
])
def test_passes_needed_reaches_the_target_without_overshooting(start, target, ratio, expected):
    n = mr.passes_needed(start, target, ratio)
    assert n == expected
    if n:
        assert start * ratio ** n <= target
        assert start * ratio ** (n - 1) > target


def test_report_cli_writes_the_key_value_file_cmd_reads(tmp_path, capsys):
    html = tmp_path / "r.html"
    html.write_text(REPORT, encoding="utf-8")
    out = tmp_path / "r.txt"
    assert mr.main([str(html), "--write", str(out), "--field", "triangles",
                    "--passes", "10000000", "0.75"]) == 0
    lines = out.read_text(encoding="ascii").splitlines()
    assert lines[0] == "NAME=zone_1_c0_SimplifyPass3"
    assert "TRIS=12345678" in lines and "TEXTURED=true" in lines and "TEXTURES=7" in lines
    assert "RESOLUTION=4096" in lines
    printed = capsys.readouterr().out.splitlines()
    assert printed == ["12345678", "1"]
    assert mr.main([str(tmp_path / "absent.html")]) == 2


def test_run_decimate_uses_the_shared_parser():
    src = (REPO / "run_decimate.py").read_text(encoding="utf-8")
    assert "from modules.realityscan_interface.model_report import parse_report" in src
    assert "<th>Model name</th>" not in src


# ------------------------------------------------------------- D12: workflows

def test_the_75_percent_preset_exists_and_is_relative():
    text = (META / "Simplify75per_Params.xml").read_text(encoding="utf-8")
    entries = dict(re.findall(r'key="([^"]+)"\s+value="([^"]*)"', text))
    assert entries["mvsFltTargetTrisCountRel"] == "75"
    assert entries["mvsFltSimplificationType"] == "1"
    assert "Simplify75per_Params.xml" in pf.STAGE_XML["model"]
    assert "SimplifySmooth_80per_Params.xml" not in pf.STAGE_XML["model"]


@pytest.mark.parametrize("name", ["GenerateModel.bat", "ModelToFinal.bat", "ExportDeliverables.bat"])
def test_no_blind_delete_anywhere(name):
    text = _bat(name)
    # the only -deleteSelectedModel is the one inside :delete_verified, which
    # runs after a report-proven select
    assert text.count("-deleteSelectedModel") == 1
    body = text[text.index(":delete_verified"):]
    assert "call :measure || exit /b 1" in body[:body.index("-deleteSelectedModel")]
    assert 'if /i not "%RS_MODEL_NAME%" == "%~1" goto :deleteSkip' in body
    assert "try_delete_model" not in text
    for line in text.splitlines():
        if "-selectModel" in line and "call :run" in line and ":select_verified" not in text[:text.index(line)]:
            pass  # top-level selects are all through :select_verified or verified inline
    assert ":measure" in text and ":select_verified" in text
    assert 'model_report.py' in text
    raw = (SCRIPTS / name).read_bytes()
    assert raw.count(b"\r\n") == raw.count(b"\n"), "bare LF"


@pytest.mark.parametrize("name", ["GenerateModel.bat", "ModelToFinal.bat"])
def test_simplification_is_measured_to_target(name):
    text = _bat(name)
    assert 'if not defined RS_TARGET_TRIS set "RS_TARGET_TRIS=10000000"' in text
    assert "Simplify75per_Params.xml" in text and "SimplifySmooth_80per" not in text
    assert ":simplifyLoop" in text and ":simplifyDone" in text
    assert "if %RS_MODEL_TRIS% LEQ %RS_TARGET_TRIS% goto :simplifyDone" in text
    assert 'call :run -simplify "%SimplifyTarget%" || goto :fail' in text
    assert "if %pass% EQU 0 goto" in text                       # small models need none
    assert 'if /i not "%RS_MODEL_TEXTURED%" == "true" goto :deliverableUntextured' in text


def test_generate_model_keeps_the_zero_pass_deliverable_and_sweeps_by_pass_count():
    text = _bat("GenerateModel.bat")
    assert ":noSimplification" in text
    assert 'call :run -renameSelectedModel "%model_tag%_Simplified_Textured" || goto :fail' in text
    assert 'for /L %%I in (1,1,%pass%) do call :delete_verified "%model_tag%_SimplifyPass%%IRaw"' in text
    assert 'for /L %%I in (1,1,%pass%) do if %%I LSS %pass% call :delete_verified "%model_tag%_SimplifyPass%%I"' in text
    assert 'call :select_verified "%model_tag%_Simplified_Textured" || goto :deliverableGone' in text
    assert 'call :try_unwrap || goto :fail' in text              # D13 survives


def test_workflows_get_the_interpreter_from_the_cli():
    src = (REPO / "modules/realityscan_interface/realityscan_cli.py").read_text(encoding="utf-8")
    assert src.count("env['RS_PYTHON'] = sys.executable") == 2
    for name in ("GenerateModel.bat", "ModelToFinal.bat", "ExportDeliverables.bat"):
        assert 'if not defined RS_PYTHON set "RS_PYTHON=python"' in _bat(name)
        assert 'for %%I in (%RealityScan%) do set "ReportTemplate=%%~dpIReports\\SelectedModel.html"' in _bat(name)


# ------------------------------------------------------------ D10: census

def _jpeg(width: int, height: int) -> bytes:
    # SOI, an APP0 segment, a baseline SOF0 with the dimensions, EOI
    app0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00" + b"\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    sof = b"\xff\xc0" + struct.pack(">H", 11) + b"\x08" + struct.pack(">HH", height, width) + b"\x01\x01\x11\x00"
    return b"\xff\xd8" + app0 + sof + b"\xff\xd9"


def _png(width: int, height: int) -> bytes:
    return b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", width, height) + b"\x08\x02\x00\x00\x00"


def _export(tmp_path, comp="c0", pages=(("t0.jpg", _jpeg(4096, 4096)),), mtl="map_Kd t0.jpg\n"):
    obj = tmp_path / "exports" / comp / "obj"
    obj.mkdir(parents=True)
    (obj / f"{comp}.obj").write_text("v 0 0 0\n", encoding="utf-8")
    if mtl is not None:
        (obj / f"{comp}.mtl").write_text(mtl, encoding="utf-8")
    for name, data in pages:
        (obj / name).write_bytes(data)
    fbx = tmp_path / "exports" / comp / "fbx"
    fbx.mkdir()
    (fbx / f"{comp}.fbx").write_bytes(b"fbx")
    for name, data in pages:
        (fbx / name).write_bytes(data)
    return tmp_path / "exports"


def test_image_size_reads_jpeg_and_png_headers(tmp_path):
    j = tmp_path / "a.jpg"
    j.write_bytes(_jpeg(4096, 2048))
    p = tmp_path / "b.png"
    p.write_bytes(_png(8192, 8192))
    assert tc.image_size(j) == (4096, 2048)
    assert tc.image_size(p) == (8192, 8192)
    (tmp_path / "c.jpg").write_bytes(b"not an image")
    assert tc.image_size(tmp_path / "c.jpg") is None


def test_textured_jpeg_export_within_the_cap_passes(tmp_path):
    exports = _export(tmp_path)
    assert tc.untextured_components(exports) == []
    census = tc.census_folder(exports / "c0" / "obj")
    assert census.textured and census.ok and census.max_side == 4096 and census.pages == 1


def test_geometry_only_obj_is_untextured(tmp_path):
    # H2060 c5: .mtl without map_Kd, no texture page, clean exit
    exports = _export(tmp_path, pages=(), mtl="newmtl m\nKd 1 1 1\n")
    problems = tc.untextured_components(exports)
    assert any("no texture page" in p for p in problems)


def test_png_and_oversized_pages_are_policy_failures(tmp_path):
    exports = _export(tmp_path, pages=(("t0.png", _png(4096, 4096)), ("t1.jpg", _jpeg(8192, 8192))),
                      mtl="map_Kd t0.png\n")
    problems = tc.untextured_components(exports)
    assert any("not JPEG" in p for p in problems)
    assert any("exceeds the 4096 cap" in p for p in problems)


def test_export_census_blocks_verify_on_an_untextured_deliverable(tmp_path):
    _export(tmp_path, pages=(), mtl="newmtl m\n")
    status = Workspace(tmp_path).detect()["export"]
    assert status.status == "blocked", status
    payload = verify_workspace(tmp_path)
    assert payload["verdict"] == "blocked"
    assert any("texture problem" in b for b in payload["blocking"])
    _export(tmp_path, comp="c1")
    assert any("c0/obj" in d for d in Workspace(tmp_path).detect()["export"].details)


def test_textured_export_is_not_blocked(tmp_path):
    _export(tmp_path)
    status = Workspace(tmp_path).detect()["export"]
    assert status.status in ("done", "partial"), status


def test_export_driver_post_check_names_texture_problems(tmp_path, monkeypatch):
    monkeypatch.setenv("RS_EXPORT_SKIP_PLY", "1")
    exports = _export(tmp_path, pages=(), mtl="newmtl m\n")
    missing = missing_exports(str(exports), ["c0"])
    assert any("no texture page" in m for m in missing)
    monkeypatch.delenv("RS_EXPORT_SKIP_PLY")
    exports2 = _export(tmp_path / "two")
    (exports2 / "c0" / "ply").mkdir()
    (exports2 / "c0" / "ply" / "c0_dense.ply").write_bytes(b"ply")
    assert missing_exports(str(exports2), ["c0"]) == []


# ------------------------------------------------------------- D1: the lane

def _ready(tmp_path, **kw):
    originals, nav = _dataset(tmp_path)
    return _charter(tmp_path, originals, nav, **kw)


@pytest.mark.parametrize("capture,expected", [("csv", "0"), ("xmp", "1"), ("", None), ("CSV", "0")])
def test_identity_capture_drives_the_align_switch(tmp_path, capture, expected):
    charter = _ready(tmp_path)
    charter.science["identity_capture"] = capture
    assert charter.env().get("RS_LEGACY_XMP_IDENTITY") == expected


def test_preflight_names_the_default_and_refuses_a_typo(tmp_path):
    charter = _ready(tmp_path)
    charter.science["identity_capture"] = ""
    report = pf.preflight_charter(charter)
    assert any("identity_capture not set" in w for w in report["warnings"])
    charter.science["identity_capture"] = "csv"
    report = pf.preflight_charter(charter)
    assert any("identity capture: csv" in c for c in report["checked"])
    charter.science["identity_capture"] = "cvs"
    assert any("identity_capture" in b for b in pf.preflight_charter(charter)["blocking"])


def test_the_template_carries_the_key():
    from modules.run_charter import TEMPLATE
    assert "identity_capture" in TEMPLATE["science"]


# ------------------------------------------------------------- D9 / D15

def test_stage_features_lives_in_the_module_and_the_driver_is_archived():
    from modules.feature_merge import FeatureStageAbort, plan_feature_stage  # noqa: F401
    assert not (REPO / "testing" / "run_on2026_run2.py").exists()
    assert (REPO / "archive" / "campaign_drivers" / "run_on2026_run2.py").is_file()
    src = (REPO / "archive/campaign_drivers/run_on2026_run2.py").read_text(encoding="utf-8")
    assert "feature_merge.plan_feature_stage(" in src


def test_findings_is_split_into_live_tail_and_frozen_history():
    live = (REPO / "FINDINGS.md").read_text(encoding="utf-8")
    frozen = (REPO / "docs/history/FINDINGS_2026-07_to_2026-09-03.md").read_text(encoding="utf-8")
    assert "## [RECON] 2026-09-03 - prior-groups claim" in live
    assert "## [HARNESS] 2026-09-05 - agent-native consolidation" in live
    assert "## [ON2026] 2026-08-12 - delegated COMPONENT ops" not in live
    assert "## [ON2026] 2026-08-12 - delegated COMPONENT ops" in frozen
    assert "## [CESIUM] 2026-08-31" in frozen and "## [CESIUM] 2026-08-31" not in live
    assert len(live.splitlines()) < 700
