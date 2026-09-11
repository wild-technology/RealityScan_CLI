"""Export regression checks using disk fixtures and cmd stubs, never RealityScan."""
from __future__ import annotations

import os
import runpy
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from modules import export_deliverables, run_plan, texture_census
from modules.realityscan_interface.realityscan_cli import RealityScanCLI, WorkflowResult
from modules.workspace_census import Workspace
from testing.export_fixture import textured_deliverable
from testing.test_census_and_postconditions import _merged

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "modules/realityscan_interface/RS_CLI/Scripts/ExportDeliverables.bat"


def test_export_script_entry_point_checks_successful_output(tmp_path, monkeypatch):
    """The planner executes a file, so package-only imports are insufficient."""
    project = tmp_path / "Assembly.rsproj"
    project.write_bytes(b"project")
    names = tmp_path / "components.names"
    names.write_text("c0\n", encoding="utf-8")
    exports = tmp_path / "exports"

    def export_stub(self, script, args, log_dir):
        assert script == "ExportDeliverables.bat"
        for kind in export_deliverables.EXPORT_KINDS:
            textured_deliverable(exports / "c0" / kind, "c0", kind)
        return WorkflowResult(True, 0, "stub.log", "", [], 1.0)

    monkeypatch.setattr(RealityScanCLI, "run_batch_script", export_stub)
    monkeypatch.setenv("RS_INSTANCE", "TEST_EXPORT")
    monkeypatch.setenv("RS_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(sys, "argv", [str(REPO / "modules/export_deliverables.py"),
                        "--project", str(project), "--exports", str(exports),
                        "--names", str(names), "--crs", "epsg:32702"])
    with pytest.raises(SystemExit) as result:
        runpy.run_path(sys.argv[0], run_name="__main__")
    assert result.value.code == 0


@pytest.mark.parametrize("report_state", ["empty", "malformed", "absent"])
def test_current_merge_cannot_reuse_stale_export_names(tmp_path, report_state):
    if report_state != "absent":
        merge = _merged(tmp_path, {"clusters": []})
        if report_state == "malformed":
            (merge / "merge_report.json").write_text("{broken", encoding="utf-8")
    names = tmp_path / "exports/components.names"
    names.parent.mkdir()
    names.write_text("previous_run_c0\n", encoding="utf-8")
    session = SimpleNamespace(workspace=lambda: Workspace(tmp_path))
    argv = ["python", "modules/export_deliverables.py", "--project", "old.rsproj",
            "--names", str(names)]
    refreshed = run_plan.refresh_export_command(argv, session)
    assert export_deliverables.read_component_names(
        refreshed[refreshed.index("--names") + 1]) == []


def test_current_merge_writes_fresh_bom_free_names(tmp_path):
    _merged(tmp_path)
    session = SimpleNamespace(workspace=lambda: Workspace(tmp_path))
    run_plan.export_names_file(session)
    assert (tmp_path / "exports/components.names").read_bytes() == (
        b"zone_1_c0\r\nzone_2_c0\r\n")


@pytest.mark.parametrize("mtl", [None, "# map_Kd c0_u1_v1_0.jpg\n",
                                "map_Kd missing.jpg\n", "map_Kd\n",
                                "map_Kd c0_u1_v1_0.jpg\nmap_Kd missing.jpg\n"])
def test_obj_census_rejects_missing_or_broken_texture_links(tmp_path, mtl):
    folder = tmp_path / "obj"
    textured_deliverable(folder, "c0", "obj")
    material = folder / "c0.mtl"
    if mtl is None:
        material.unlink()
    else:
        material.write_text(mtl, encoding="utf-8")
    assert not texture_census.census_folder(folder).ok


def test_obj_census_accepts_quoted_page_names_with_spaces(tmp_path):
    textured_deliverable(tmp_path, "c0", "obj")
    (tmp_path / "c0_u1_v1_0.jpg").rename(tmp_path / "texture page.jpg")
    (tmp_path / "c0.mtl").write_text('map_Kd "texture page.jpg"\n', encoding="utf-8")
    assert texture_census.census_folder(tmp_path).ok


def _cmd_fixture(tmp_path, body, env):
    shutil.copyfile(SCRIPT.parent / "RuntimeAbortGuard.bat", tmp_path / "RuntimeAbortGuard.bat")
    path = tmp_path / "export_stub.cmd"
    path.write_bytes(body.replace("\r\n", "\n").replace("\n", "\r\n").encode("utf-8"))
    return subprocess.run(["cmd", "/d", "/c", str(path)], cwd=tmp_path,
                          env={**os.environ, **env}, capture_output=True,
                          text=True, timeout=20)


@pytest.mark.skipif(sys.platform != "win32", reason="executes Windows batch control flow")
@pytest.mark.parametrize("selected", ["c0_HighPoly_Raw", "previous_model"])
def test_ply_colors_only_the_verified_raw_model(tmp_path, selected):
    """Run the REAL export and selection subroutines with stubbed RS I/O."""
    source = SCRIPT.read_text(encoding="utf-8")
    export = source[source.index("\n:export_component\n"):source.index("\n:emptyList\n")]
    select = source[source.index("\n:select_verified\n"):source.index("\n:delete_verified\n")]
    body = ('@echo off\nset "RS_EXPORT_SKIP_PLY="\nset "out_dir=%CD%"\n'
            'call :export_component c0\nexit /b %errorlevel%\n' + export + select +
            '\n:run\necho RUN %*\nexit /b 0\n'
            ':measure\nset "RS_MODEL_NAME=%STUB_SELECTED%"\nexit /b 0\n')
    result = _cmd_fixture(tmp_path, body, {"STUB_SELECTED": selected})
    if selected == "previous_model":
        assert result.returncode == 1, result.stdout + result.stderr
        assert "RUN -calculateVertexColors" not in result.stdout
    else:
        assert result.returncode == 0, result.stdout + result.stderr
        assert "RUN -calculateVertexColors" in result.stdout
        assert 'RUN -exportModel "c0_HighPoly_Raw"' in result.stdout


@pytest.mark.skipif(sys.platform != "win32", reason="executes Windows batch control flow")
def test_residual_cleanup_failure_prevents_save(tmp_path):
    source = SCRIPT.read_text(encoding="utf-8")
    sweep = source[source.index("echo Sweeping default-named"):source.index(":: Output CRS.")]
    body = ('@echo off\n' + sweep + '\nexit /b 0\n'
            ':delete_verified\nexit /b 1\n'
            ':run\necho RUN %*\nexit /b 0\n'
            ':fail\nexit /b 1\n')
    result = _cmd_fixture(tmp_path, body, {})
    assert result.returncode == 1, result.stdout + result.stderr
    assert "RUN -save" not in result.stdout


@pytest.mark.skipif(sys.platform != "win32", reason="executes Windows batch control flow")
def test_absent_residual_is_skipped_without_measuring_or_deleting(tmp_path):
    source = SCRIPT.read_text(encoding="utf-8")
    delete = source[source.index("\n:delete_verified\n"):source.index("\n:run\n")]
    # Both waits remain; only their wall-clock grace periods are elided.
    delete = delete.replace("ping -n 3 127.0.0.1 >nul", "rem stub grace")
    delete = delete.replace("ping -n 2 127.0.0.1 >nul", "rem stub grace")
    body = ('@echo off\nset "RealityScan=call :rs_stub"\n'
            'set "ErrorsFile=%CD%\\errors_TEST.txt"\nset "ErrorPath=%CD%"\n'
            'set "RS_INSTANCE=TEST"\ncall :delete_verified "Model 1"\n'
            'exit /b %errorlevel%\n' + delete +
            '\n:rs_stub\necho select refused>"%ErrorsFile%"\nexit /b 0\n'
            ':measure\necho UNEXPECTED_MEASURE\nexit /b 1\n'
            ':run\necho UNEXPECTED_DELETE\nexit /b 1\n')
    result = _cmd_fixture(tmp_path, body, {})
    assert result.returncode == 0, result.stdout + result.stderr
    assert "UNEXPECTED_" not in result.stdout
    assert (tmp_path / "expected_select_TEST_Model 1.txt").is_file()
    assert not (tmp_path / "errors_TEST.txt").exists()
