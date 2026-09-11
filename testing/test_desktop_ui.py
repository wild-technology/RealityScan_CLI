"""Offscreen frontend tests with a fake controller and temporary raster fixtures."""
import hashlib
import os
from pathlib import Path
import threading

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QInputDialog, QMessageBox

from desktop.main_window import MainWindow, NewProjectDialog
from desktop.map_preview import MapPreview, RasterPreview, raster_rgba, read_raster
from desktop.spatial_review import track_segments
from desktop.setup_dialog import SetupDialog
from modules.project_workspace import ProjectDocument, ProjectError


class FakeController:
    def __init__(self):
        self.callback = None
        self.calls = []

    def subscribe(self, callback):
        self.callback = callback
        return lambda: self.calls.append(("unsubscribe",))

    def settings_schema(self, project):
        return [
            {"block": "operations", "key": "reserve_gib", "label": "Disk reserve (GiB)",
             "type": "float", "default": 50, "min": 0, "required": True},
            {"block": "operations", "key": "instance", "label": "Owned instance", "type": "str"},
            {"block": "operations", "key": "cache", "label": "Cache directory", "type": "path"},
            {"block": "camera", "key": "sensor.pitch_accuracy", "label": "Pitch accuracy (degrees)",
             "type": "float", "default": 10, "min": 0, "max": 180},
            {"block": "camera", "key": "sensor.enabled", "label": "Enabled", "type": "bool"},
            {"block": "camera", "key": "mode", "label": "Mode", "type": "choice", "choices": ["a", "b"]},
            {"block": "camera", "key": "count", "label": "Count", "type": "int", "min": 1},
        ]

    def save_project(self, project, path=None):
        return project.save(path)

    def adopt_workspace(self, project):
        self.calls.append(("adopt", project.project_id))

    def start(self, project, stage):
        self.calls.append(("start", project.project_id, stage))

    def stop(self, mode="after_step"):
        self.calls.append(("stop", mode))

    def scan_inventory(self, project):
        self.calls.append(("scan", project.project_id))

    def set_inventory_decision(self, project, path, included, reason):
        self.calls.append(("decision", path, included, reason))
        project.set_settings("inventory", {"path": path, "included": included, "reason": reason})

    def confirm_inventory(self, project, input_inventory_hash, confirmed_by):
        self.calls.append(("confirm_inventory", input_inventory_hash, confirmed_by))
        project.set_settings("inventory", {"confirmed_hash": input_inventory_hash, "by": confirmed_by})

    def scan_image_quality(self, project, tolerances=None):
        self.calls.append(("scan_quality", tolerances))

    def apply_image_culling(self, project, assessment_hash, excluded_paths, confirmed_by):
        self.calls.append(("quality_cull", assessment_hash, excluded_paths, confirmed_by))

    def scan_spatial_review(self, project, options=None):
        self.calls.append(("scan_spatial", options))

    def apply_spatial_culling(self, project, assessment_hash, excluded_paths, confirmed_by):
        self.calls.append(("spatial_cull", assessment_hash, excluded_paths, confirmed_by))

    def confirm_spatial_review(self, project, assessment_hash, confirmed_by):
        self.calls.append(("confirm_spatial", assessment_hash, confirmed_by))


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def window(qapp, tmp_path, monkeypatch):
    project = ProjectDocument.create("NA999", "H9999", tmp_path / "project", [tmp_path / "source"])
    controller = FakeController()
    widget = MainWindow(controller, project)
    widget.errors = []
    monkeypatch.setattr(widget, "_error", lambda message: widget.errors.append(str(message)))
    yield widget
    widget._running = False
    widget.settings.dirty = False
    widget._saved = widget.project.to_dict()
    widget.close()
    qapp.processEvents()


def test_initial_ui_is_document_only_and_does_not_approve_proposals(window):
    assert window.phases.count() == 9
    assert window.tabs.count() == 7
    assert window.settings.blocks.itemData(0) == "operations"
    assert window.settings.blocks.itemData(1) == "camera"
    assert window.settings.editors["reserve_gib"][1].text() == "50"
    assert window.project.to_dict()["settings"] == {}
    assert not window.project.root.exists()
    assert window.controller.calls == []


def test_typed_settings_apply_explicit_and_approval_stays_absent(window):
    window.settings.editors["reserve_gib"][1].setText("64.5")
    window.settings._apply()
    data = window.project.to_dict()["settings"]["operations"]
    assert data == {"values": {"reserve_gib": 64.5}, "approval": None}
    assert not window.project.root.exists()
    assert window.save_project()
    assert ProjectDocument.load(window.project.path).to_dict() == window.project.to_dict()


def test_typed_nested_fields_boolean_false_and_validation(window):
    panel = window.settings
    panel.blocks.setCurrentIndex(1)
    panel.editors["sensor.enabled"][1].setCurrentIndex(2)
    panel.editors["mode"][1].setCurrentIndex(2)
    panel.editors["count"][1].setText("4")
    values = panel.values()
    assert values == {"sensor": {"pitch_accuracy": 10.0, "enabled": False}, "mode": "b", "count": 4}
    panel.editors["count"][1].setText("4.5")
    with pytest.raises(ProjectError):
        panel.values()
    panel.editors["count"][1].setText("0")
    with pytest.raises(ProjectError):
        panel.values()
    panel.editors["count"][1].setText("4")
    panel.editors["sensor.pitch_accuracy"][1].setText("nan")
    with pytest.raises(ProjectError):
        panel.values()


def test_draft_switch_cancel_preserves_values(window, monkeypatch):
    window.settings.editors["reserve_gib"][1].setText("77")
    window.settings._mark_dirty()
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Cancel)
    window.settings.blocks.setCurrentIndex(1)
    assert window.settings.block == "operations"
    assert window.settings.editors["reserve_gib"][1].text() == "77"
    assert not window.save_project()
    assert "Apply or discard" in window.errors[-1]


def test_apply_uses_controller_hook_when_available(window):
    calls = []

    def apply(project, block, values):
        calls.append((block, values))
        project.set_settings(block, values, affects_stage="georeference")

    window.controller.apply_settings = apply
    window._apply_settings("camera", {"test": True})
    assert calls == [("camera", {"test": True})]


def test_approval_requires_review_and_name(window, monkeypatch):
    window.settings._apply()
    monkeypatch.setattr(QMessageBox, "exec", lambda self: QMessageBox.StandardButton.Ok)
    monkeypatch.setattr(QInputDialog, "getText", lambda *args, **kwargs: ("Operator", True))
    window._approve_settings("operations")
    approval = window.project.to_dict()["settings"]["operations"]["approval"]
    assert approval["by"] == "Operator"
    assert approval["content_hash"] == window.project.settings_signature(["operations"])
    window._apply_settings("operations", {"reserve_gib": 70})
    assert window.project.to_dict()["settings"]["operations"]["approval"] is None


def test_start_is_async_controller_call_and_ownership_gate(window):
    window.start_selected()
    assert window.controller.calls == [("start", window.project.project_id, "inventory")]
    assert window._running
    assert not window.restart_button.isEnabled()
    assert not window.recovery_action.isEnabled()
    window._event({"kind": "error", "message": "Stop could not be confirmed"})
    assert window._running
    window._event({"kind": "state", "state": "interrupted", "ownership_released": False})
    assert window._running
    window._event({"kind": "state", "state": "interrupted", "ownership_released": True})
    assert not window._running
    assert window.restart_button.isEnabled()


@pytest.mark.parametrize("mode", ["after_step", "abort_current"])
def test_stop_modes_do_not_release_ownership(window, monkeypatch, mode):
    window.start_selected()
    monkeypatch.setattr(QMessageBox, "exec", lambda self: QMessageBox.StandardButton.Ok)
    button_text = "After current step" if mode == "after_step" else "Abort current operation"
    monkeypatch.setattr(QMessageBox, "clickedButton", lambda self: next(b for b in self.buttons() if b.text() == button_text))
    window.stop_run()
    assert ("stop", mode) in window.controller.calls
    assert window._cancel_requested and window._running
    assert not window.restart_button.isEnabled()
    assert window.stop_button.isEnabled() is (mode == "after_step")
    window.recover_run()
    assert window._running


def test_synchronous_start_rejection_restores_idle(window):
    def rejected(*args):
        raise ValueError("Inventory review is missing")

    window.controller.start = rejected
    window.start_selected()
    assert not window._running
    assert "Inventory review" in window.errors[-1]


def test_stop_after_step_can_escalate_to_abort_without_releasing_owner(window, monkeypatch):
    window.start_selected()
    monkeypatch.setattr(QMessageBox, "exec", lambda self: QMessageBox.StandardButton.Ok)
    for mode, text in (("after_step", "After current step"), ("abort_current", "Abort current operation")):
        monkeypatch.setattr(QMessageBox, "clickedButton", lambda self: next(b for b in self.buttons() if b.text() == text))
        window.stop_run()
        assert window._running and not window.restart_button.isEnabled()
        assert window._cancel_mode == mode
        assert window.stop_button.isEnabled() is (mode == "after_step")
    assert [call for call in window.controller.calls if call[0] == "stop"] == [
        ("stop", "after_step"), ("stop", "abort_current")]


def test_camera_table_uses_actual_inventory_summary_keys(window, tmp_path):
    from modules.source_inventory import SourceItem, summarize_inventory
    items = [SourceItem(str(tmp_path / str(i) / "camupper.jpg"), f"{i}/camupper.jpg", "image", 1, 1,
                        camera="camupper", sha256=sha * 64, window_status="in_window")
             for i, sha in enumerate(("a", "a", "b"))]
    summary = summarize_inventory(items)
    window._event({"kind": "inventory", "items": [], "input_inventory_hash": "fixture",
                   "camera_summary": [{"camera_type": key, **row} for key, row in summary["cameras"].items()]})
    assert window.camera_counts.item(0, 4).text() == "1"
    assert window.camera_counts.item(0, 5).text() == "1"
    assert window.camera_counts.item(0, 6).text() == "Unknown"


def test_camera_family_summary_keeps_mixed_era_mount_profiles_separate(window, tmp_path):
    from dataclasses import asdict
    from modules.source_inventory import SourceItem, summarize_inventory
    items = [SourceItem(str(tmp_path / name), name, "image", 1, 1,
                        family=family, camera="starboard", sha256=sha * 64, window_status="in_window")
             for name, family, sha in (("camupper_20250524T010000Z.jpg", "legacy_camupper", "a"),
                                       ("s001c_20250524T010001Z.jpg", "wca_starboard", "b"))]
    summary = summarize_inventory(items)
    window._event({"kind": "inventory", "items": [asdict(item) for item in items],
        "camera_summary": [{"camera_type": key, **row} for key, row in summary["cameras"].items()],
        "camera_family_summary": [{"family": key, **row} for key, row in summary["families"].items()]})
    assert window.camera_counts.rowCount() == 2
    assert {window.camera_counts.item(row, 0).text() for row in range(2)} == {"legacy_camupper", "wca_starboard"}
    assert {window.camera_counts.item(row, 1).text() for row in range(2)} == {"starboard"}
    assert all(window.camera_counts.item(row, 2).text() == "1" for row in range(2))
    assert window.inventory.model.data(window.inventory.model.index(0, 2)) == "legacy_camupper"
    assert window.inventory.model.data(window.inventory.model.index(0, 3)) == "starboard"
    window.inventory.proxy.configure(flags_only=False, query="wca_starboard")
    assert window.inventory.proxy.rowCount() == 1


def test_quality_confirmation_replaces_gui_token_for_next_apply(window, monkeypatch):
    window._event({"kind": "image_quality", "assessment_hash": "old", "candidates": [], "tolerances": {}})
    window._event({"kind": "state", "state": "quality_confirmed", "ownership_released": True,
                   "assessment_hash": "new"})
    assert window.quality.assessment_hash == "new"
    monkeypatch.setattr(window, "_review_operator", lambda *args: "operator")
    window.apply_quality_culling("new", [])
    assert ("quality_cull", "new", [], "operator") in window.controller.calls
    before = list(window.controller.calls)
    window.apply_quality_culling("old", [])
    assert window.controller.calls == before
    assert "stale" in window.errors[-1]


def test_spatial_payload_preserves_applied_set_and_allows_empty_replacement(window, monkeypatch):
    points = [{"path": path, "x": 500000.0 + i, "y": 4000000.0, "excluded": True}
              for i, path in enumerate(("spatial.jpg", "quality.jpg"))]
    window._event({"kind": "spatial_review", "assessment_hash": "current", "points": points,
                   "spatial_excluded_paths": ["spatial.jpg"]})
    assert window.spatial.model.selected_paths == {"spatial.jpg"}
    assert not window.spatial.selection_dirty
    assert window.spatial.confirm_button.isEnabled()
    monkeypatch.setattr(window, "_review_operator", lambda *args: "operator")
    window.confirm_spatial("current")
    assert ("confirm_spatial", "current", "operator") in window.controller.calls
    window.spatial.model.setData(window.spatial.model.index(0, 0), Qt.CheckState.Unchecked,
                                 Qt.ItemDataRole.CheckStateRole)
    assert window.spatial.selection_dirty
    assert window.spatial.apply_button.isEnabled()
    assert not window.spatial.confirm_button.isEnabled()
    window.spatial.apply_button.click()
    assert ("spatial_cull", "current", [], "operator") in window.controller.calls


def test_spatial_new_selection_preserves_previously_applied_exclusions(window, monkeypatch):
    window._event({"kind": "spatial_review", "assessment_hash": "current",
                   "points": [{"path": path, "x": i, "y": 1.0} for i, path in enumerate(("a.jpg", "b.jpg"))],
                   "spatial_excluded_paths": ["a.jpg"]})
    window.spatial.model.setData(window.spatial.model.index(1, 0), Qt.CheckState.Checked,
                                 Qt.ItemDataRole.CheckStateRole)
    monkeypatch.setattr(window, "_review_operator", lambda *args: "operator")
    window.spatial.apply_button.click()
    assert ("spatial_cull", "current", ["a.jpg", "b.jpg"], "operator") in window.controller.calls


def test_save_unowned_existing_workspace_reports_adoption_error(window):
    from modules.project_controller import ProjectController
    controller = ProjectController()
    raw = window.project.root / "raw/valuable.txt"
    raw.parent.mkdir(parents=True)
    raw.write_text("retain", encoding="utf-8")
    original_controller = window.controller
    window.controller = controller
    try:
        assert window.save_project() is False
        assert "adoption" in window.errors[-1].lower()
        assert raw.read_text(encoding="utf-8") == "retain"
        assert not (window.project.root / ".rovscan-owner.json").exists()
    finally:
        window.controller = original_controller
        controller._pool.shutdown(wait=True)


def stale_run(window):
    window.project.start_stage("inventory", required_blocks=[])
    window.set_project(window.project)
    assert window._running and window._can_recover


def await_recovery(window, qapp):
    for _ in range(300):
        qapp.processEvents()
        if not window._recovering:
            break
        QTest.qWait(10)
    assert not window._recovering


def test_recovery_without_controller_api_keeps_ownership(window):
    stale_run(window)
    before = window.project.to_dict()
    window.recover_run()
    assert window.project.to_dict() == before
    assert window._running and window._can_recover
    assert not window.restart_button.isEnabled()
    assert "recover_project" in window.errors[-1]


@pytest.mark.parametrize("result", [None, {}, {"ownership_released": False, "message": "No exit evidence"},
                                     {"ownership_released": True}])
def test_recovery_requires_proof_and_completed_lifecycle(window, qapp, monkeypatch, result):
    stale_run(window)
    before = window.project.to_dict()
    window.controller.recover_project = lambda project: result
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes)
    window.recover_run()
    assert window._running and window._recovering
    await_recovery(window, qapp)
    assert window._running and window._can_recover
    assert not window.restart_button.isEnabled()
    assert window.project.to_dict() == before
    assert window.errors


def test_recovery_exception_keeps_run_active_with_actionable_error(window, qapp, monkeypatch):
    from modules.project_runtime import OwnershipUnconfirmed
    stale_run(window)
    def recover(project):
        raise OwnershipUnconfirmed("Owned child has no terminal evidence; inspect its runtime log")
    window.controller.recover_project = recover
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes)
    window.recover_run()
    await_recovery(window, qapp)
    assert window._running and not window.restart_button.isEnabled()
    assert "inspect its runtime log" in window.errors[-1]


def test_verified_controller_recovery_runs_off_qt_thread(window, qapp, monkeypatch):
    stale_run(window)
    gui_thread = threading.get_ident()
    calls = []
    def recover(project):
        calls.append((project.project_id, threading.get_ident()))
        stages = project.recover_interrupted()  # Mock controller owns the lifecycle mutation.
        return {"ownership_released": True, "recovered_stages": stages, "message": "Owned process exit verified"}
    window.controller.recover_project = recover
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes)
    window.recover_run()
    await_recovery(window, qapp)
    assert calls[0][0] == window.project.project_id and calls[0][1] != gui_thread
    assert not window._running and not window._can_recover
    assert window.project.to_dict()["stages"]["inventory"]["state"] == "interrupted"
    assert window.restart_button.isEnabled()
    assert "exit verified" in window.progress_label.text()


def test_ownership_unconfirmed_event_offers_verification_without_unlocking(window):
    window.start_selected()
    window._event({"kind": "state", "state": "ownership_unconfirmed", "ownership_released": False})
    assert window._running and window.recovery_action.isEnabled()
    assert not window.restart_button.isEnabled()


def test_background_events_marshal_to_qt(window, qapp):
    def worker():
        window.controller.callback({"kind": "progress", "current": 2, "total": 4, "message": "Halfway"})

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join()
    qapp.processEvents()
    assert window.progress.value() == 500
    assert "Halfway" in window.logs.toPlainText()


def test_wrong_project_events_ignored_and_resource_reserve_visible(window):
    window._event({"kind": "progress", "project_id": "other", "current": 1, "total": 1})
    assert window.progress.value() == 0
    window._event({"kind": "resources", "free_bytes": 25 * 1024**3,
                   "reserve_bytes": 50 * 1024**3, "memory_bytes": 3 * 1024**3})
    assert window.reserve_gauge.value() == 50
    assert window.reserve_gauge.format() == "Below reserve"
    assert "25.0 GiB" in window.resources.text()


def test_inventory_exceptions_and_explicit_decision(window, monkeypatch):
    path = "example/image.tif"
    window._event({"kind": "inventory", "items": [{"path": path, "kind": "image", "size_bytes": 12,
                                                    "included": False, "exception": "Outside dive window"}]})
    assert "1 exceptions" in window.inventory.summary.text()
    monkeypatch.setattr(QInputDialog, "getText", lambda *args, **kwargs: ("Verified timestamp correction", True))
    window.inventory.model.setData(window.inventory.model.index(0, 0), Qt.CheckState.Checked, Qt.ItemDataRole.CheckStateRole)
    assert ("decision", path, True, "Verified timestamp correction") in window.controller.calls
    assert window.project.to_dict()["settings"]["inventory"]["values"]["included"] is True


def test_cancel_inventory_decision_restores_checkbox(window, monkeypatch):
    window._event({"kind": "inventory", "items": [{"path": "example", "included": False}]})
    monkeypatch.setattr(QInputDialog, "getText", lambda *args, **kwargs: ("", False))
    window.inventory.model.setData(window.inventory.model.index(0, 0), Qt.CheckState.Checked, Qt.ItemDataRole.CheckStateRole)
    assert window.inventory.model.data(window.inventory.model.index(0, 0), Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.Unchecked
    assert window.controller.calls == []


def test_camera_counts_confirmation_bound_to_inventory_hash(window, monkeypatch):
    digest = "a" * 64
    event = {"kind": "inventory", "items": [], "input_inventory_hash": digest,
             "camera_summary": [{"camera_type": "camera-A", "total": 120, "in_window": 100,
                                 "duplicates": 5, "conflicts": 1, "unmatched": 2, "masks": 100}]}
    window._event(event)
    assert window.camera_counts.item(0, 3).text() == "100"
    window.phases.setCurrentRow(1)
    assert not window.start_button.isEnabled()
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(QInputDialog, "getText", lambda *args, **kwargs: ("Operator", True))
    window.confirm_inventory()
    assert ("confirm_inventory", digest, "Operator") in window.controller.calls
    assert window._inventory_confirmed
    assert window.start_button.isEnabled()
    window._event(event | {"input_inventory_hash": "b" * 64})
    assert not window._inventory_confirmed
    assert not window.start_button.isEnabled()


def test_new_dialog_refuses_overlapping_roots(qapp, tmp_path):
    dialog = NewProjectDialog()
    dialog.expedition.setText("NA999")
    dialog.dive.setText("H9999")
    dialog.root.setText(str(tmp_path / "root"))
    dialog.source.setText(str(tmp_path / "root"))
    dialog._accept()
    assert "overlap" in dialog.error.text()
    assert dialog.document is None
    assert not (tmp_path / "root").exists()
    dialog.source.setText(str(tmp_path / "source"))
    dialog._accept()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert not (tmp_path / "root").exists()


def test_save_as_and_open_are_explicit(window, tmp_path, monkeypatch):
    assert window.save_project()
    first = window.project.path
    second = window.project.root / "copy.rovscan"
    assert window.save_project(second)
    assert first.exists() and second.exists()
    assert window.project.path == second
    before = second.read_bytes()
    assert window.open_project(second)
    assert second.read_bytes() == before
    assert not (window.project.root / "proc").exists()


@pytest.fixture
def raster(tmp_path):
    import rasterio
    from rasterio.transform import from_origin
    path = tmp_path / "float-map.tif"
    values = np.array([[0.125, 5.75, -9999], [-2.5, np.nan, np.inf]], dtype=np.float32)
    with rasterio.open(path, "w", driver="GTiff", width=3, height=2, count=1, dtype="float32",
                       nodata=-9999, crs="EPSG:32610", transform=from_origin(500000, 4000000, 2, 2)) as dataset:
        dataset.write(values, 1)
    return path


def test_float_raster_nodata_range_and_original_unchanged(raster):
    before = hashlib.sha256(raster.read_bytes()).hexdigest()
    preview = read_raster(raster)
    assert preview.values.dtype == np.float32
    assert preview.minimum == -2.5 and preview.maximum == 5.75
    assert preview.metadata["preview_valid"] == 3
    original = preview.values.copy()
    rgba = raster_rgba(preview, -1, 4)
    assert np.count_nonzero(rgba[..., 3]) == 3
    np.testing.assert_array_equal(preview.values, original)
    assert hashlib.sha256(raster.read_bytes()).hexdigest() == before


def test_raster_preview_bounds_and_invalid_ranges(raster):
    preview = read_raster(raster, max_size=2)
    assert max(preview.values.shape) <= 2
    with pytest.raises(ValueError):
        raster_rgba(preview, 1, -1)
    with pytest.raises(ValueError):
        read_raster(raster, band=2)
    with pytest.raises(ValueError):
        raster_rgba(preview, float("nan"), 1)


def test_constant_all_nodata_and_extreme_float_preview():
    for values in [np.ma.masked_all((2, 3)), np.ma.array([[4.0, 4.0]]),
                   np.ma.array([[-1e308, 1e308]])]:
        low, high = (float(values.min()), float(values.max())) if values.count() else (0.0, 0.0)
        preview = RasterPreview("fixture", values, {}, low, high)
        rgba = raster_rgba(preview)
        assert rgba.shape == values.shape + (4,)
        assert np.count_nonzero(rgba[..., 3]) == values.count()


def test_map_widget_metadata_and_range(qapp, raster):
    widget = MapPreview()
    before = raster.read_bytes()
    widget.load_path(raster, asynchronous=False)
    assert "float32" in widget.summary.text()
    assert "EPSG:32610" in widget.summary.text()
    assert "Nodata: -9999.0" in widget.summary.text()
    assert widget._pixmap is not None
    widget.minimum.setText("bad")
    widget.apply_range()
    assert "could not convert" in widget.message.text()
    assert raster.read_bytes() == before
    widget.close()


def test_map_load_async_and_stale_result_ignored(qapp, raster):
    widget = MapPreview()
    widget.load_path(raster)
    for _ in range(100):
        qapp.processEvents()
        if widget.preview is not None:
            break
        QTest.qWait(10)
    assert widget.preview is not None
    previous = widget.preview
    widget._loaded(0, None, "stale failure")
    assert widget.preview is previous
    assert "stale failure" not in widget.message.text()
    widget.close()


def test_offscreen_window_snapshot(window, qapp, tmp_path):
    window._event({"kind": "inventory", "items": [], "input_inventory_hash": "a" * 64,
                   "camera_summary": [{"camera_type": "Sensor A", "total": 120, "in_window": 110,
                                       "duplicates": 3, "conflicts": 0, "unmatched": 1, "masks": 110}]})
    window.tabs.setCurrentIndex(2)
    window.show()
    qapp.processEvents()
    path = tmp_path / "desktop-preview.png"
    assert window.grab().save(str(path))
    assert path.stat().st_size > 10000
    print(f"UI_SNAPSHOT={path}")


def test_virtualized_150k_records_default_flags_and_full_counts(window):
    items = [{"path": f"image-{index}.jpg", "kind": "image", "included": True,
              "exception": "Duplicate" if index % 10000 == 0 else ""} for index in range(150000)]
    window.inventory.set_items(items)
    assert window.inventory.model.rowCount() == 150000
    assert window.inventory.proxy.rowCount() == 15
    assert "150,000 files" in window.inventory.summary.text()
    assert window.inventory.table.indexWidget(window.inventory.proxy.index(0, 0)) is None
    window.inventory.filter_choice.setCurrentIndex(1)
    assert window.inventory.proxy.rowCount() == 150000
    window.inventory.proxy.configure(query="image-149999")
    assert window.inventory.proxy.rowCount() == 1


def test_quality_candidates_never_auto_culled_and_tolerances_require_rerun(window):
    window._event({"kind": "image_quality", "assessment_hash": "quality-hash",
                   "candidates": [{"path": "candidate.jpg", "reason": "Low structural detail", "score": 0.9,
                                   "excluded": True}], "tolerances": {"coverage": 0.99},
                   "tolerance_schema": [{"key": "coverage", "label": "Coverage proposal", "min": 0, "max": 1}]})
    panel = window.quality
    assert panel.model.selected_paths == set()
    assert window.controller.calls == []
    panel.editors["coverage"].setText("0.98")
    panel._edited()
    assert not panel.apply_button.isEnabled()
    panel._scan()
    assert ("scan_quality", {"coverage": 0.98}) in window.controller.calls
    panel.editors["coverage"].setText("1.2")
    panel._scan()
    assert "outside" in panel.message.text()


def test_quality_apply_empty_keep_set_explicit_and_batch_gate(window, monkeypatch):
    window.phases.setCurrentRow(4)  # batch
    assert not window.start_button.isEnabled()
    window.start_selected()
    assert "Confirm image screening" in window.errors[-1]
    window._event({"kind": "inventory", "input_inventory_hash": "inventory-hash",
                   "inventory_confirmed": True, "items": []})
    monkeypatch.setattr(window, "_review_operator", lambda *args: "Operator")
    window._event({"kind": "image_quality", "assessment_hash": "quality-hash", "candidates": []})
    window.apply_quality_culling("quality-hash", [])
    assert ("quality_cull", "quality-hash", [], "Operator") in window.controller.calls
    assert not window.start_button.isEnabled()  # spatial review is still required
    window._event({"kind": "spatial_review", "assessment_hash": "spatial-hash", "points": []})
    window.confirm_spatial("spatial-hash")
    assert ("confirm_spatial", "spatial-hash", "Operator") in window.controller.calls
    assert window.start_button.isEnabled()


def test_spatial_float64_precision_layers_and_gap_breaks(window):
    points = [{"path": "a.jpg", "x": 7000000.0001, "y": 4000000.0001, "camera": "A",
               "time": "2026-01-01", "excluded": False, "outlier": False},
              {"path": "b.jpg", "x": 7000000.0002, "y": 4000000.0002, "camera": "A",
               "time": "2026-01-01", "excluded": True, "outlier": True}]
    window._event({"kind": "spatial_review", "assessment_hash": "spatial-hash", "epsg": 32610,
                   "points": points, "track": [[0, 0], [1, 1], None, [100, 100], [101, 101]],
                   "track_gap_distance": 3})
    panel = window.spatial
    assert panel.coordinates.dtype == np.float64
    assert 0 < panel.coordinates[1, 0] - panel.coordinates[0, 0] < 0.001
    assert len(panel.axes.lines) == 2
    panel.layers["Track"].setChecked(False)
    assert len(panel.axes.lines) == 0
    assert panel.confirm_button.isEnabled()
    panel.model.setData(panel.model.index(0, 0), Qt.CheckState.Checked, Qt.ItemDataRole.CheckStateRole)
    assert not panel.confirm_button.isEnabled()
    assert panel.model.selected_paths == {"a.jpg"}


def test_track_unknown_gap_threshold_does_not_join_positions():
    assert track_segments([[0, 0], [10000, 10000]]) == []
    segments = track_segments([[0, 0], [1, 0], [10000, 0], [10001, 0]], 2)
    assert len(segments) == 2
    with pytest.raises(ValueError):
        track_segments([[0, 0]], -1)


def test_controller_timestamp_segments_render_without_bridging_gap(window):
    import pandas as pd
    from modules.project_controller import track_segments as navigation_segments
    x = np.array([500000.123456789, 500001.123456789, 500100.123456789, 500101.123456789], dtype=np.float64)
    frame = pd.DataFrame({"Timestamp": pd.to_datetime([
        "2025-05-24T01:00:00Z", "2025-05-24T01:00:01Z",
        "2025-05-24T01:00:10Z", "2025-05-24T01:00:11Z"], utc=True),
        "kalman_x": x, "kalman_y": np.full(4, 4000000.987654321, dtype=np.float64)})
    segments = navigation_segments(frame, max_gap_seconds=2)
    window._event({"kind": "spatial_review", "assessment_hash": "fixture-segmented",
                   "epsg": 32618, "points": [], "track": frame[["kalman_x", "kalman_y"]].values.tolist(),
                   "track_segments": segments, "track_gap_seconds": 2.0})
    lines = window.spatial.axes.lines
    assert len(lines) == 2
    np.testing.assert_array_equal(lines[0].get_xdata(), x[:2])
    np.testing.assert_array_equal(lines[1].get_xdata(), x[2:])


def test_invalid_spatial_positions_cannot_be_confirmed(window):
    window._event({"kind": "spatial_review", "assessment_hash": "hash", "points": [
        {"path": "missing.jpg", "x": float("nan"), "y": 123}]})
    assert window.spatial.invalid_count == 1
    assert not window.spatial.confirm_button.isEnabled()


def test_spatial_cull_requires_new_assessment_before_confirmation(window, monkeypatch):
    window._event({"kind": "spatial_review", "assessment_hash": "old", "points": []})
    monkeypatch.setattr(window, "_review_operator", lambda *args: "Operator")
    window.apply_spatial_culling("old", ["example.jpg"])
    assert ("spatial_cull", "old", ["example.jpg"], "Operator") in window.controller.calls
    assert window.spatial.assessment_hash is None
    assert not window.spatial.confirm_button.isEnabled()
    assert not window._spatial_confirmed


def test_lazy_thumbnail_cannot_read_outside_declared_trees(window, tmp_path):
    window.quality.thumbnail.load_path(tmp_path / "unrelated.jpg")
    assert "outside" in window.quality.thumbnail.text()


def test_cull_draft_change_revokes_batch_gate(window):
    window._event({"kind": "inventory", "input_inventory_hash": "inventory-hash",
                   "inventory_confirmed": True, "items": []})
    window._event({"kind": "image_quality", "assessment_hash": "quality-hash", "culling_confirmed": True,
                   "candidates": [{"path": "candidate.jpg", "reason": "Candidate"}]})
    window._event({"kind": "spatial_review", "assessment_hash": "spatial-hash", "confirmed": True, "points": []})
    window.phases.setCurrentRow(4)
    assert window.start_button.isEnabled()
    window.quality.model.setData(window.quality.model.index(0, 0), Qt.CheckState.Checked, Qt.ItemDataRole.CheckStateRole)
    assert not window.start_button.isEnabled()
    assert not window._quality_confirmed and not window._spatial_confirmed
    window.start_selected()
    assert not any(call[0] == "start" for call in window.controller.calls)


def test_stale_cull_hash_and_invalid_spatial_confirmation_refused(window):
    window._event({"kind": "image_quality", "assessment_hash": "new", "candidates": []})
    window.apply_quality_culling("old", [])
    assert "stale" in window.errors[-1]
    window._event({"kind": "spatial_review", "assessment_hash": "new", "points": [
        {"path": "invalid.jpg", "x": float("nan"), "y": 1}]})
    window.confirm_spatial("new")
    assert "valid positions" in window.errors[-1]
    assert window.controller.calls == []


def test_project_switch_does_not_inherit_review_tolerances(window, tmp_path):
    window._event({"kind": "image_quality", "assessment_hash": "old", "candidates": [],
                   "tolerances": {"example": 0.99}})
    next_project = ProjectDocument.create("NA998", "H9998", tmp_path / "other", [tmp_path / "other-source"])
    window.set_project(next_project)
    assert window.quality.tolerances == {}
    assert window.quality.editors == {}
    assert window.map_preview.preview is None
    assert window.quality.assessment_hash is None


def test_offscreen_font_has_real_glyphs(window):
    from PySide6.QtGui import QFontDatabase, QRawFont
    assert "Segoe UI" in QFontDatabase.families()
    assert QRawFont.fromFont(window.font()).supportsCharacter(ord("A"))


def test_controller_review_ready_releases_only_confirmed_ownership(window):
    window.start_selected()
    window._event({"kind": "state", "state": "review_ready", "ownership_released": False})
    assert window._running
    window._event({"kind": "state", "state": "review_ready", "ownership_released": True})
    assert not window._running


def test_explicit_adoption_delegates_and_cancel_does_nothing(window, monkeypatch):
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.No)
    window.adopt_workspace()
    assert window.controller.calls == []
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes)
    window.adopt_workspace()
    assert window.controller.calls == [("adopt", window.project.project_id)]


def test_save_requires_controller_ownership_boundary(window):
    window.controller.save_project = None
    assert not window.save_project()
    assert "validate workspace ownership" in window.errors[-1]
    assert not window.project.root.exists()


def test_setup_check_is_async_read_only_by_default(window, qapp):
    calls = []

    def inspect(**kwargs):
        calls.append(kwargs)
        return {"ready": False, "checks": [{"name": "write_access", "status": "unprobed",
                                            "message": "Explicit probe needed"}],
                "dependencies": {"PySide6": {"ok": True}}, "installation": {}, "storage": {},
                "repair_choices": [{"title": "Verify writes", "description": "Use the explicit probe action"}]}

    dialog = SetupDialog(project=window.project, install_dir="fixture-install",
                         cache_root=window.project.root / "proc/tmp/cache", inspector=inspect)
    dialog.run_check()
    for _ in range(100):
        qapp.processEvents()
        if not dialog.busy:
            break
        QTest.qWait(10)
    assert calls[0]["probe_writes"] is False
    assert calls[0]["reserve_gib"] == 50
    assert dialog.report["ready"] is False
    assert "Not ready" in dialog.summary.text()
    assert "explicit probe" in dialog.repairs.toPlainText()
    assert not window.project.root.exists()
    dialog.close()


def test_write_probe_requires_explicit_confirmation(window, qapp, monkeypatch):
    calls = []
    dialog = SetupDialog(project=window.project, inspector=lambda **kw: calls.append(kw) or {"ready": True})
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.No)
    dialog.probe_writes()
    assert calls == []
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes)
    dialog.probe_writes()
    for _ in range(100):
        qapp.processEvents()
        if not dialog.busy:
            break
        QTest.qWait(10)
    assert calls[0]["probe_writes"] is True
    assert not window.project.root.exists()
    dialog.close()


def test_create_cache_requires_operating_approval_and_idle_project(window):
    calls = []
    class CacheController:
        def ensure_cache(self, project):
            calls.append(project.project_id)
    dialog = SetupDialog(project=window.project, controller=CacheController())
    assert not dialog.create_cache_button.isEnabled()
    dialog.create_cache()
    assert not calls
    window.project.set_settings("operating", {"cache_dir": str(window.project.root / "proc/tmp/cache")})
    dialog.refresh_actions()
    assert not dialog.create_cache_button.isEnabled()
    window.project.approve_settings("operating", "operator")
    dialog.refresh_actions()
    assert dialog.create_cache_button.isEnabled()
    window.project.start_stage("inventory", required_blocks=[])
    dialog.refresh_actions()
    dialog.create_cache()
    assert not dialog.create_cache_button.isEnabled()
    assert not calls
    assert not window.project.root.exists()
    dialog.close()


def test_create_approved_cache_uses_real_controller_then_readonly_check(window, qapp):
    from modules.project_controller import ProjectController
    controller = ProjectController()
    p = window.project
    cache = p.resolve_path("proc/tmp/cache")
    p.set_settings("operating", {"cache_dir": str(cache), "reserve_gib": 50})
    p.approve_settings("operating", "operator")
    document = p.to_dict()
    calls = []
    gui_thread = threading.get_ident()
    def inspect(**kwargs):
        calls.append((kwargs, threading.get_ident()))
        assert cache.is_dir()
        return {"ready": True}
    dialog = SetupDialog(project=p, controller=controller, cache_root=cache, inspector=inspect)
    try:
        assert not cache.exists()
        assert dialog.create_cache_button.isEnabled()
        dialog.create_cache()
        assert dialog.busy
        assert not dialog.create_cache_button.isEnabled()
        for _ in range(300):
            qapp.processEvents()
            if not dialog.busy:
                break
            QTest.qWait(10)
        assert not dialog.busy
        assert cache.is_dir()
        assert len(calls) == 1 and calls[0][0]["probe_writes"] is False
        assert calls[0][1] != gui_thread
        assert Path(calls[0][0]["cache_root"]) == cache
        assert dialog.report == {"ready": True}
        assert dialog.cache_label.text() == str(cache)
        assert p.to_dict() == document  # Creation does not change settings or approval.
    finally:
        dialog.close()
        controller._pool.shutdown(wait=True)


def test_cache_failure_does_not_claim_readiness_or_probe(window, qapp):
    p = window.project
    p.set_settings("operating", {"cache_dir": str(p.root / "proc/tmp/cache")})
    p.approve_settings("operating", "operator")
    calls = []
    class RefusingController:
        def ensure_cache(self, project):
            raise ValueError("Workspace belongs to another project")
    dialog = SetupDialog(project=p, controller=RefusingController(), inspector=lambda **kw: calls.append(kw))
    dialog.create_cache()
    for _ in range(100):
        qapp.processEvents()
        if not dialog.busy:
            break
        QTest.qWait(10)
    assert not dialog.busy
    assert dialog.report is None
    assert "another project" in dialog.summary.text()
    assert calls == []
    assert not p.root.exists()
    dialog.close()


def test_setup_cannot_create_cache_for_project_switched_behind_dialog(window, qapp, monkeypatch):
    p = window.project
    p.set_settings("operating", {"cache_dir": str(p.root / "proc/tmp/cache")})
    p.approve_settings("operating", "operator")
    calls = []
    monkeypatch.setattr(window.controller, "ensure_cache", lambda project: calls.append(project), raising=False)
    monkeypatch.setattr(SetupDialog, "run_check", lambda *args, **kwargs: None)
    dialog = window.show_setup()
    assert dialog.create_cache_button.isEnabled()
    try:
        window.project = None
        dialog.create_cache()
        assert calls == []
        assert not dialog.create_cache_button.isEnabled()
    finally:
        window.project = p
        dialog.close()


def test_offscreen_spatial_snapshot(window, qapp, tmp_path):
    axis = np.linspace(0, 1, 300)
    points = [{"path": f"fixture-{i}.jpg", "x": 500000 + 160 * float(t),
               "y": 4100000 + 30 * float(np.sin(t * 9)) + (120 if i == 299 else 0),
               "camera": "Sensor A", "time": f"12:00:{i % 60:02d}", "excluded": i % 40 == 0,
               "outlier": i == 299, "reason": "Review candidate" if i == 299 else ""}
              for i, t in enumerate(axis)]
    window._event({"kind": "spatial_review", "assessment_hash": "synthetic", "epsg": 32610, "points": points,
                   "track_segments": [[[p["x"], p["y"]] for p in points[:299]]]})
    window.tabs.setCurrentIndex(4)
    window.show()
    qapp.processEvents()
    window.spatial.canvas.draw()
    path = tmp_path / "spatial-preview.png"
    assert window.grab().save(str(path))
    print(f"SPATIAL_SNAPSHOT={path}")


def test_read_only_hydration_restores_applied_culls(window, qapp):
    events = [{"kind": "inventory", "input_inventory_hash": "inventory", "inventory_confirmed": True, "items": []},
              {"kind": "image_quality", "assessment_hash": "quality", "candidates": [
                  {"path": "prior-cull.jpg", "reason": "Previously reviewed", "excluded": True}]},
              {"kind": "state", "state": "quality_confirmed", "ownership_released": True},
              {"kind": "spatial_review", "assessment_hash": "spatial", "points": []},
              {"kind": "state", "state": "selection_confirmed", "ownership_released": True}]
    window.controller.load_project_state = lambda project: events
    window.set_project(window.project)
    for _ in range(100):
        qapp.processEvents()
        if not window._hydrating:
            break
        QTest.qWait(10)
    assert window.quality.model.selected_paths == {"prior-cull.jpg"}
    window.phases.setCurrentRow(4)
    assert window.start_button.isEnabled()
    assert not window.project.root.exists()


def test_stale_hydration_result_is_ignored(window):
    window._restored_project_state(-1, [{"kind": "state", "state": "quality_confirmed",
                                         "ownership_released": True}], "")
    assert not window._quality_confirmed


def test_actual_controller_schema_offscreen_render(qapp, tmp_path):
    from modules.project_controller import ProjectController
    controller = ProjectController()
    project = ProjectDocument.create("NA998", "H9998", tmp_path / "schema-project", [tmp_path / "source"])
    widget = MainWindow(controller, project)
    for _ in range(100):
        qapp.processEvents()
        if not widget._hydrating:
            break
        QTest.qWait(10)
    schema = controller.settings_schema(project)
    assert len(schema) >= 57
    assert widget.settings.blocks.findData("cameras") >= 0
    for block in dict.fromkeys(field["block"] for field in schema):
        widget.settings.blocks.setCurrentIndex(widget.settings.blocks.findData(block))
        assert len(widget.settings.editors) == sum(field["block"] == block for field in schema)
    widget.settings.blocks.setCurrentIndex(widget.settings.blocks.findData("cameras"))
    widget.tabs.setCurrentIndex(1)
    widget.show()
    qapp.processEvents()
    path = tmp_path / "actual-controller-settings.png"
    assert widget.grab().save(str(path))
    print(f"ACTUAL_SCHEMA_SNAPSHOT={path}")
    assert project.to_dict()["settings"] == {}
    assert not project.root.exists()
    widget._saved = project.to_dict()
    widget.close()
    qapp.processEvents()


def test_setup_rebind_preserves_window_and_invalidates_results(window, tmp_path, monkeypatch):
    monkeypatch.setattr(SetupDialog, "run_check", lambda *a, **kw: None)
    dialog = window.show_setup()
    dialog._result(dialog._generation, {"ready": True, "checks": ["old"]}, "")
    generation = dialog._generation
    replacement = ProjectDocument.create("NA998", "H9998", tmp_path / "other", [])
    window.set_project(replacement)  # Both New and Open finish through this entry point.
    assert window.show_setup() is dialog
    assert dialog.project is replacement and dialog.root_label.text() == str(replacement.root)
    assert dialog.report is None and dialog.checks.topLevelItemCount() == 0
    dialog._result(generation, {"ready": True}, "")
    dialog._cache_result(generation, "old-cache", "")
    assert dialog.report is None and "old-cache" not in dialog.cache_label.text()
    window._apply_settings("operations", {"install_dir": "new-install", "reserve_gib": 72,
                                         "cache": str(replacement.root / "proc/tmp/new-cache")})
    assert dialog.install_dir.text() == "new-install"
    assert dialog.reserve_label.text() == "72 GiB"
    assert dialog.cache_label.text().endswith("new-cache")
    assert dialog.report is None
    dialog.close()


def test_setup_ignores_inflight_result_after_edit(window, qapp):
    started, release = threading.Event(), threading.Event()
    def inspect(**kwargs):
        started.set()
        assert release.wait(5)
        return {"ready": True}
    dialog = SetupDialog(project=window.project, inspector=inspect)
    try:
        dialog.run_check()
        assert started.wait(3)
        dialog.install_dir.setText("changed-install")
        release.set()
        for _ in range(30):
            QTest.qWait(10)
        assert dialog.report is None
        assert "Selections changed" in dialog.summary.text()
    finally:
        release.set()
        dialog.close()


@pytest.mark.parametrize("failure", [False, True])
def test_bulk_exclusion_is_one_async_atomic_call(window, qapp, monkeypatch, failure):
    table = window.inventory
    table.set_items([
        {"path": "unknown.jpg", "kind": "image", "included": True, "exception": "unknown family"},
        {"path": "orphan.mask.png", "kind": "mask", "included": True, "exception": "orphan mask"},
        {"path": "valid.mask.png", "kind": "mask", "included": True, "exception": ""},
        {"path": "already-excluded.jpg", "kind": "image", "included": False, "exception": "unknown family"},
    ])
    table.filter_choice.setCurrentIndex(1)
    table.table.selectAll()
    assert set(table.selected_flagged_paths()) == {"unknown.jpg", "orphan.mask.png"}
    started, release = threading.Event(), threading.Event()
    calls = []
    gui_thread = threading.get_ident()
    def apply(project, paths, included, reason):
        calls.append((paths, included, reason, threading.get_ident()))
        started.set()
        assert release.wait(5)
        if failure:
            raise ValueError("One selected path changed; nothing applied")
    monkeypatch.setattr(window.controller, "set_inventory_decisions", apply, raising=False)
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **kw: ("Owner reviewed unmatched files", True))
    window._inventory_confirmed = window._quality_confirmed = window._spatial_confirmed = True
    table.exclude_selected.click()
    assert started.wait(3)
    assert window._running and not window.stop_button.isEnabled()
    assert window._inventory_confirmed  # No optimistic partial approval/selection changes.
    assert all(item["included"] for item in table.items[:3])
    release.set()
    for _ in range(100):
        qapp.processEvents()
        if not window._running:
            break
        QTest.qWait(10)
    assert len(calls) == 1 and len(calls[0][0]) == 2
    assert calls[0][1:3] == (False, "Owner reviewed unmatched files")
    assert calls[0][3] != gui_thread
    assert window._inventory_confirmed is failure
    assert window._quality_confirmed is failure and window._spatial_confirmed is failure
    assert bool(window.errors) is failure


def test_phase_summary_uses_canonical_requirements_not_future_blocks(window, monkeypatch):
    from modules.project_controller import ProjectController
    from modules.project_workspace import STAGES
    monkeypatch.setattr(window.controller, "required_settings_blocks", ProjectController.required_settings_blocks, raising=False)
    p = window.project
    p.set_settings("operating", {"reserve_gib": 50})
    p.set_settings("navigation", {"max_match_seconds": 2})
    p.set_settings("align", {"r_min_component_size": 50})
    p.set_settings("budget", {"cache_delta_gb": 0})
    p.approve_settings("operating", "operator")
    p.approve_settings("navigation", "operator")
    window.settings.set_project(p, ProjectController().settings_schema(p))
    window.settings.blocks.setCurrentIndex(window.settings.blocks.findData("merge"))
    for stage in ("inventory", "preprocess"):
        window.phases.setCurrentRow(STAGES.index(stage))
        window._refresh()
        assert f"Selected phase: {stage.title()}" == window.stage_title.text()
        assert "No settings approval required" in window.approval_status.text()
        assert "Awaiting approval" not in window.approval_status.text()
        assert "Align" not in window.current_settings.toPlainText()
        assert window.settings.block == "merge"
    window.phases.setCurrentRow(STAGES.index("navigation"))
    assert window.approval_status.text() == "Required settings approved for this phase"
    summary = window.current_settings.toPlainText()
    assert "Maximum image/navigation difference (seconds): 2" in summary
    assert "Free-space reserve (GiB): 50" in summary
    assert "cache_delta_gb" not in summary and "Budget" not in summary and "Align" not in summary


def test_phase_summary_uses_controller_override_and_typed_choice_labels(window, monkeypatch):
    from modules.project_controller import ProjectController
    p = window.project
    p.set_settings("merge", {"component_features": 0, "vertical_datum": ""})
    seen = []
    def requirements(stage):
        seen.append(stage)
        return ["merge", "navigation"]
    monkeypatch.setattr(window.controller, "required_settings_blocks", requirements, raising=False)
    window.settings.set_project(p, ProjectController().settings_schema(p))
    window._refresh()
    assert seen[-1] == "inventory"  # No independently maintained stage map in the UI.
    text = window.current_settings.toPlainText()
    assert "Feature source for imported alignments: Merge using overlapping images" in text
    assert "component_features" not in text
    assert "Navigation · not yet applied" in text
    assert "Merge, Navigation" in window.approval_status.text()


def test_real_navigation_unmatched_payload_can_exclude_retained_image(window, tmp_path):
    from dataclasses import asdict
    import pandas as pd
    from modules.navigation_quality import POSE_COLUMNS, match_images
    from modules.source_inventory import SourceItem
    item = SourceItem(str(tmp_path / "image.jpg"), "image.jpg", "image", 1, 1,
                      family="legacy_camupper", camera="starboard", included=True,
                      timestamp_utc="2025-05-24T03:00:00Z", window_status="in_window")
    frame = pd.DataFrame({name: [0.] for name in POSE_COLUMNS})
    frame["Timestamp"] = pd.to_datetime(["2025-05-24T01:00:00Z"], utc=True)
    unmatched = match_images([item], frame, 2)["unmatched"]
    assert len(unmatched) == 1 and "included" not in unmatched[0]
    window._event({"kind": "inventory", "items": [asdict(item)], "input_inventory_hash": "known"})
    window._event({"kind": "navigation", "items": unmatched})
    assert window.navigation.model.data(window.navigation.model.index(0, 0), Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.Checked
    assert window.navigation.items[0]["family"] == "legacy_camupper"
    window.navigation.table.selectAll()
    assert window.navigation.selected_flagged_paths() == [item.path]


def test_navigation_assessment_visible_without_toggling_flags_and_not_checkable(window):
    report = {"path": "navigation.csv", "structurally_valid": True, "rows": 421,
              "epsg": 32618, "start_utc": "2025-05-24T01:00:00Z", "end_utc": "2025-05-24T02:00:00Z",
              "finite_pose_rows": 421, "gaps_over_2s": 3, "max_gap_s": 12.,
              "depth_min_m": -1200., "depth_max_m": -1100., "errors": [],
              "limitations": ["Absolute accuracy is not established"]}
    window._event({"kind": "navigation", "items": [report]})
    assert "421" in window.navigation.summary.text()
    assert "32618" in window.navigation.summary.text()
    assert "12" in window.navigation.summary.text()
    assert "Absolute accuracy" in window.navigation.summary.text()
    assert window.navigation.model.rowCount() == 0


def test_new_inventory_event_retires_old_quality_and_density_ui_tokens(window):
    window._event({"kind": "inventory", "items": [], "input_inventory_hash": "old", "inventory_confirmed": True})
    window.quality.assessment_hash = "old-quality"
    window.spatial.assessment_hash = "old-spatial"
    window._quality_confirmed = window._spatial_confirmed = True
    window._event({"kind": "inventory", "items": [], "input_inventory_hash": "new", "inventory_confirmed": False})
    assert not window._quality_confirmed and not window._spatial_confirmed
    assert window.quality.assessment_hash is None and window.spatial.assessment_hash is None
    window._event({"kind": "inventory", "items": [], "input_inventory_hash": "new", "inventory_confirmed": True})
    window.phases.setCurrentRow(4)
    assert not window.start_button.isEnabled()


def test_restart_preprocess_retires_visible_review_approvals(window, monkeypatch):
    window._inventory_confirmed = window._quality_confirmed = window._spatial_confirmed = True
    window.quality.assessment_hash = "quality"
    window.spatial.assessment_hash = "spatial"
    window.phases.setCurrentRow(3)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **kw: QMessageBox.StandardButton.Yes)
    window.restart_selected()
    assert window._inventory_confirmed
    assert not window._quality_confirmed and not window._spatial_confirmed
    assert window.quality.assessment_hash is None and window.spatial.assessment_hash is None


@pytest.mark.parametrize("stage", ["navigation", "preprocess"])
def test_invalid_navigation_review_keeps_quality_but_clears_density_ready(window, stage):
    window._inventory_confirmed = window._quality_confirmed = window._spatial_confirmed = True
    window.quality.assessment_hash = "valid-quality"
    window.spatial.assessment_hash = "stale-spatial"
    window._event({"kind": "state", "state": "review_invalid", "stage": stage,
                   "message": "Navigation changed; rebuild density review"})
    assert window._quality_confirmed and window.quality.assessment_hash == "valid-quality"
    assert not window._spatial_confirmed and window.spatial.assessment_hash is None
    assert "Navigation changed" in window.progress_label.text()
    window.phases.setCurrentRow(4)
    assert not window.start_button.isEnabled()


def test_unknown_navigation_path_cannot_be_toggled_without_inventory(window):
    window._event({"kind": "navigation", "items": [{"path": "unknown.jpg", "exception": "no navigation"}]})
    model = window.navigation.model
    index = model.index(0, 0)
    assert not model.flags(index) & Qt.ItemFlag.ItemIsUserCheckable
    assert not model.setData(index, Qt.CheckState.Checked, Qt.ItemDataRole.CheckStateRole)
    assert not window.controller.calls


def test_new_schema_defaults_are_not_displayed_as_approved_saved_values(window):
    p = window.project
    p.set_settings("operations", {"instance": "approved-instance"})
    p.approve_settings("operations", "operator")
    before = p.to_dict()
    window.settings.set_project(p, window.controller.settings_schema(p))
    window._refresh()
    assert window.settings.editors["reserve_gib"][1].text() == "50"
    assert "Approved for current content" not in window.settings.approval_label.text()
    assert not window.settings.approve_button.isEnabled()
    assert p.to_dict() == before
    window.settings._apply()
    assert p.to_dict()["settings"]["operations"]["values"]["reserve_gib"] == 50
    assert not p.settings_approved(["operations"])


@pytest.mark.parametrize("operation", ["start", "scan", "settings"])
def test_ownership_unconfirmed_rejection_keeps_restart_disabled(window, monkeypatch, operation):
    from modules.project_runtime import OwnershipUnconfirmed
    def refuse(*args, **kwargs):
        raise OwnershipUnconfirmed("Persisted project worker requires verified recovery")
    if operation == "start":
        monkeypatch.setattr(window.controller, "start", refuse)
        window.start_selected()
    elif operation == "scan":
        monkeypatch.setattr(window.controller, "scan_inventory", refuse)
        window.scan_sources()
    else:
        monkeypatch.setattr(window.controller, "apply_settings", refuse, raising=False)
        window._apply_settings("operations", {"reserve_gib": 50})
    assert window.errors
    assert window._running and window._can_recover
    assert not window.restart_button.isEnabled()


def test_async_bulk_ownership_error_retains_recovery_state(window, qapp, monkeypatch):
    from modules.project_runtime import OwnershipUnconfirmed
    def refuse(*args, **kwargs):
        raise OwnershipUnconfirmed("Persisted worker ownership is unresolved")
    monkeypatch.setattr(window.controller, "set_inventory_decisions", refuse, raising=False)
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **kw: ("reviewed", True))
    window._exclude_flagged(["unknown.jpg"])
    for _ in range(100):
        qapp.processEvents()
        if not window._editing_inventory:
            break
        QTest.qWait(10)
    assert not window._editing_inventory
    assert window._running and window._can_recover
    assert not window.restart_button.isEnabled()
    assert "unresolved" in window.errors[-1]


def test_reentrant_listener_old_terminal_cannot_release_new_worker(window):
    # An earlier controller listener queues a retry while terminal sequence 10
    # is dispatching: this listener receives nested running 11 before terminal 10.
    window._event({"kind": "state", "sequence": 11, "state": "running", "ownership_released": False})
    window._event({"kind": "state", "sequence": 10, "state": "review_ready", "ownership_released": True})
    assert window._running
    assert not window.restart_button.isEnabled()
    window._event({"kind": "state", "sequence": 12, "state": "review_ready", "ownership_released": True})
    assert not window._running and window.restart_button.isEnabled()


def completed_batch(window):
    for stage in ("inventory", "navigation", "georeference", "preprocess", "batch"):
        attempt = window.project.start_stage(stage, required_blocks=[])
        window.project.complete_stage(stage, attempt_id=attempt)
    window._inventory_confirmed = window._quality_confirmed = window._spatial_confirmed = True
    window.phases.setCurrentRow(5)  # Align
    window._refresh()


def mask_event(**changes):
    event = {"kind": "occlusion_masks", "assessment_hash": "a" * 64,
            "batch_fingerprint": "b" * 64, "decision": "generated", "confirmed": False,
            "parameters": {"sample_count": 12, "tolerance": 0.05},
            "parameter_schema": [
                {"key": "sample_count", "label": "Samples per group", "type": "int", "min": 3, "max": 100},
                {"key": "tolerance", "label": "Tolerance", "type": "float", "min": 0.001, "max": 1}],
            "groups": [{"group_id": "camera-group", "status": "candidate_review_required", "blockers": []}], **changes}
    if "mappings" not in changes:
        event["mappings"] = ([{"group_id": group["group_id"]} for group in event["groups"]
                              if group.get("status") == "candidate_review_required" and not group.get("blockers")]
                             if event["decision"] == "applied" else [])
    return event


def select_mask_groups(window, ids):
    model = window.occlusion.model
    for row, group in enumerate(model.groups):
        if group["group_id"] in ids:
            assert model.setData(model.index(row, 0), Qt.CheckState.Checked, Qt.ItemDataRole.CheckStateRole)


@pytest.mark.parametrize("block,culling_valid,masks_valid", [
    ("operating", True, True), ("budget", True, True),
    ("science", True, True), ("align", True, True), ("merge", True, True),
    ("model", True, True), ("export", True, True), ("batch", True, False),
    ("navigation", False, False), ("cameras", False, False),
    ("georeference", False, False), ("preprocess", False, False),
    ("inventory", False, False), ("unknown", False, False),
])
def test_settings_save_invalidates_only_dependent_reviews(window, block, culling_valid, masks_valid):
    window.project.set_settings(block, {"value": 1})
    completed_batch(window)
    window.quality.assessment_hash = "quality-current"
    window.spatial.assessment_hash = "spatial-current"
    window._event(mask_event(decision="applied", confirmed=True))
    window._apply_settings(block, {"value": 2})
    assert not window.errors
    assert window._quality_confirmed is culling_valid
    assert window._spatial_confirmed is culling_valid
    assert window.quality.assessment_hash == ("quality-current" if culling_valid else None)
    assert window.spatial.assessment_hash == ("spatial-current" if culling_valid else None)
    assert window.occlusion.confirmed is masks_valid


@pytest.mark.parametrize("block", ["cameras", "navigation", "preprocess", "batch", "unknown"])
def test_unchanged_settings_save_preserves_current_reviews(window, block):
    window.project.set_settings(block, {"value": 1})
    completed_batch(window)
    window._event(mask_event(decision="applied", confirmed=True))
    window._apply_settings(block, {"value": 1})
    assert not window.errors
    assert window._quality_confirmed and window._spatial_confirmed
    assert window.occlusion.confirmed


@pytest.mark.parametrize("decision", ["applied", "skipped"])
def test_occlusion_generation_never_approves_and_explicit_current_decision_enables_align(window, decision):
    completed_batch(window)
    window._event(mask_event(confirmed=True))  # Even a mistaken generated=true cannot approve.
    assert not window.occlusion.confirmed and not window.start_button.isEnabled()
    window.start_selected()
    assert "Apply" in window.errors[-1] and not window.controller.calls
    window._event(mask_event(decision=decision, confirmed=True))
    assert window.occlusion.confirmed and window.start_button.isEnabled()


def test_occlusion_choice_not_available_until_batch_complete(window):
    assert not window.occlusion.scan_button.isEnabled()
    assert not window.occlusion.skip_button.isEnabled()
    window.scan_occlusion()
    window.skip_occlusion()
    assert not window.controller.calls
    completed_batch(window)
    assert window.occlusion.scan_button.isEnabled()
    assert window.occlusion.skip_button.isEnabled()


def test_occlusion_typed_parameters_require_rerun_and_do_not_change_saved_project(window, monkeypatch):
    completed_batch(window)
    window._event(mask_event(decision="applied", confirmed=True))
    snapshot = window.project.to_dict()
    window.occlusion.editors["sample_count"].setValue(24)
    window.occlusion.editors["tolerance"].setValue(0.075)
    assert window.occlusion.dirty and not window.start_button.isEnabled()
    assert not window.occlusion.apply_button.isEnabled()
    calls = []
    monkeypatch.setattr(window.controller, "scan_occlusion_masks", lambda project, options: calls.append(options), raising=False)
    window.occlusion.scan_button.click()
    assert calls == [{"sample_count": 24, "tolerance": 0.075}]
    assert type(calls[0]["sample_count"]) is int
    assert window.project.to_dict() == snapshot
    assert not window.occlusion.confirmed


def test_occlusion_apply_and_skip_require_operator_and_controller_confirmation(window, monkeypatch):
    completed_batch(window)
    calls = []
    monkeypatch.setattr(window.controller, "apply_occlusion_masks",
                        lambda *args, **kw: calls.append(("apply", *args, kw)), raising=False)
    monkeypatch.setattr(window.controller, "skip_occlusion_masks", lambda *args: calls.append(("skip", *args)), raising=False)
    window._event(mask_event())
    select_mask_groups(window, ["camera-group"])
    monkeypatch.setattr(window, "_review_operator", lambda *args: None)
    window.apply_occlusion("a" * 64, ["camera-group"])
    assert not calls
    monkeypatch.setattr(window, "_review_operator", lambda *args: "Operator")
    window.apply_occlusion("c" * 64, ["camera-group"])
    assert not calls
    window.apply_occlusion("a" * 64, ["camera-group"])
    assert calls == [("apply", window.project, "a" * 64, "Operator", {"accepted_block_ids": ["camera-group"]})]
    assert not window.occlusion.confirmed
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **kw: (" ", True))
    window.skip_occlusion()
    assert len(calls) == 1
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **kw: ("No persistent hardware", True))
    window.skip_occlusion()
    assert calls[-1] == ("skip", window.project, "No persistent hardware", "Operator")
    assert not window.occlusion.confirmed


@pytest.mark.parametrize("event", [
    {"kind": "state", "state": "running", "stage": "batch"},
    {"kind": "state", "state": "review_invalid", "stage": "occlusion_review", "message": "Batch bytes changed"},
    {"kind": "inventory", "items": [], "input_inventory_hash": "new", "inventory_confirmed": False},
    {"kind": "image_quality", "candidates": []},
    {"kind": "spatial_review", "points": []},
])
def test_batch_or_selection_change_invalidates_occlusion_decision(window, event):
    completed_batch(window)
    window._event(mask_event(decision="skipped", confirmed=True))
    window._event(event)
    assert not window.occlusion.confirmed and not window.start_button.isEnabled()


def test_occlusion_rebatch_restart_retires_decision(window, monkeypatch):
    completed_batch(window)
    window._event(mask_event(decision="applied", confirmed=True))
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **kw: QMessageBox.StandardButton.Yes)
    window.phases.setCurrentRow(4)
    window.restart_selected()
    assert not window.occlusion.confirmed
    assert not window.occlusion.scan_button.isEnabled()


def test_occlusion_old_and_foreign_confirmation_events_are_ignored(window):
    completed_batch(window)
    window._event(mask_event(sequence=21))
    window._event(mask_event(sequence=20, decision="applied", confirmed=True))
    window._event(mask_event(sequence=22, project_id="other", decision="applied", confirmed=True))
    assert not window.occlusion.confirmed


@pytest.mark.parametrize("missing", ["assessment_hash", "batch_fingerprint"])
def test_occlusion_missing_content_token_cannot_apply_or_enable_align(window, missing):
    completed_batch(window)
    event = mask_event(decision="applied", confirmed=True)
    event[missing] = None
    window._event(event)
    assert not window.occlusion.confirmed and not window.start_button.isEnabled()
    event["decision"] = "generated"
    window._event(event)
    assert not window.occlusion.apply_button.isEnabled()


def test_occlusion_preview_loads_only_selected_group_sample(window, monkeypatch):
    completed_batch(window)
    originals, overlays = [], []
    monkeypatch.setattr(window.occlusion.original, "load_path", originals.append)
    monkeypatch.setattr(window.occlusion.overlay, "load_path", overlays.append)
    groups = [{"group_id": f"camera:dimensions:time{i}", "camera": "camera", "family": "legacy_camupper",
               "image_count": 10000, "sample_count": 2, "previews": [
                   {"image_path": f"image{i}a.jpg", "overlay_path": f"overlay{i}a.png"},
                   {"image_path": f"image{i}b.jpg", "overlay_path": f"overlay{i}b.png"}]} for i in range(300)]
    window._event(mask_event(groups=groups))
    assert window.occlusion.model.rowCount() == 300
    assert originals == ["image0a.jpg"] and overlays == ["overlay0a.png"]
    window.occlusion.table.selectRow(299)
    window.occlusion.sample_choice.setCurrentIndex(1)
    assert originals[-2:] == ["image299a.jpg", "image299b.jpg"]
    assert overlays[-2:] == ["overlay299a.png", "overlay299b.png"]


def test_occlusion_project_open_resets_confirmation_without_writes(window, tmp_path):
    completed_batch(window)
    window._event(mask_event(decision="skipped", confirmed=True))
    other = ProjectDocument.create("NA888", "H8888", tmp_path / "other", [])
    window.set_project(other)
    assert not window.occlusion.confirmed
    assert not window.occlusion.batch_fingerprint
    assert not other.root.exists()


def test_offscreen_occlusion_preview_preserves_original_and_renders(window, qapp, tmp_path):
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QColor, QImage, QPainter, QPolygon
    completed_batch(window)
    source = Path(window.project.to_dict()["sources"][0])
    source.mkdir()
    original = source / "SYNTHETIC-original.png"
    overlay = source / "SYNTHETIC-excluded-overlay.png"
    image = QImage(640, 480, QImage.Format.Format_RGB32)
    image.fill(QColor("#164565"))
    painter = QPainter(image)
    painter.setBrush(QColor("#837e64"))
    painter.drawPolygon(QPolygon([QPoint(0, 340), QPoint(290, 260), QPoint(639, 325),
                                  QPoint(639, 479), QPoint(0, 479)]))
    painter.setBrush(QColor("#111c25"))
    painter.drawRect(0, 400, 639, 79)
    painter.setPen(QColor("white"))
    painter.drawText(20, 35, "SYNTHETIC REVIEW FIXTURE - NOT ENGINE OUTPUT")
    painter.end()
    assert image.save(str(original))
    before = hashlib.sha256(original.read_bytes()).hexdigest()
    painter = QPainter(image)
    painter.fillRect(0, 400, 640, 80, QColor(255, 55, 45, 170))
    painter.end()
    assert image.save(str(overlay))
    groups = [{"group_id": "camera-A:640x480:time-block-001", "camera": "Camera A",
               "family": "legacy_camupper", "image_count": 280, "sample_count": 12,
               "status": "candidate_review_required", "blockers": [],
               "excluded_fraction": 0.167, "previews": [{"image_path": str(original), "overlay_path": str(overlay)}]},
              {"group_id": "camera-B:640x480:time-block-001", "camera": "Camera B", "family": "legacy_zeuss",
               "image_count": 90, "sample_count": 6, "status": "blocked",
               "blockers": ["low_motion_or_stationary_camera", "insufficient_distinct_samples"]}]
    window._event(mask_event(groups=groups, message="SYNTHETIC FIXTURE · Candidates only; no actual data assessment."))
    window.tabs.setCurrentWidget(window.occlusion)
    window.resize(1680, 1060)
    window.show()
    for _ in range(150):
        qapp.processEvents()
        if not window.occlusion.original.pixmap().isNull() and not window.occlusion.overlay.pixmap().isNull():
            break
        QTest.qWait(10)
    assert not window.occlusion.original.pixmap().isNull()
    assert not window.occlusion.overlay.pixmap().isNull()
    assert hashlib.sha256(original.read_bytes()).hexdigest() == before
    artifact = tmp_path / "SYNTHETIC-post-batch-mask-review.png"
    assert window.grab().save(str(artifact))
    print(f"Occlusion screenshot: {artifact}")


def test_occlusion_abstention_visible_and_only_supported_groups_can_apply(window):
    completed_batch(window)
    groups = [{"group_id": "c" * 64, "camera": "camera-A", "status": "blocked",
               "blockers": ["low_motion_or_stationary_camera", "insufficient_distinct_samples"]}]
    window._event(mask_event(groups=groups))
    assert not window.occlusion.apply_button.isEnabled()
    assert "No supported candidate" in window.occlusion.summary.text()
    assert "0 masked / 1 unmasked groups" in window.occlusion.summary.text()
    model = window.occlusion.model
    assert "low motion" in model.data(model.index(0, 4))
    assert model.data(model.index(0, 0), Qt.ItemDataRole.ToolTipRole) == "c" * 64
    assert len(model.data(model.index(0, 0))) < 64
    groups.append({"group_id": "supported", "status": "candidate_review_required", "blockers": []})
    window._event(mask_event(groups=groups))
    assert not window.occlusion.apply_button.isEnabled()
    select_mask_groups(window, ["supported"])
    assert window.occlusion.apply_button.isEnabled()
    assert window.occlusion.reviewable_count == 1
    window._event(mask_event(groups=groups, decision="applied", confirmed=True))
    assert "1 masked / 1 unmasked groups" in window.occlusion.summary.text()
    window._event(mask_event(groups=groups, decision="skipped", confirmed=True))
    assert "0 masked / 2 unmasked groups" in window.occlusion.summary.text()


def test_occlusion_missing_status_cannot_silently_be_treated_as_reviewable(window):
    completed_batch(window)
    window._event(mask_event(groups=[{"group_id": "unknown"}]))
    assert not window.occlusion.apply_button.isEnabled()
    window.apply_occlusion("a" * 64, [])
    assert not window.controller.calls


def test_occlusion_apply_selects_exact_subset_and_reports_uncovered_groups(window, monkeypatch):
    completed_batch(window)
    groups = [{"group_id": key, "status": "candidate_review_required", "blockers": []}
              for key in ("upper", "lower")]
    groups.append({"group_id": "blocked", "status": "blocked", "blockers": ["insufficient_samples"]})
    window._event(mask_event(groups=groups))
    panel, model = window.occlusion, window.occlusion.model
    assert panel.selected_ids == [] and not panel.apply_button.isEnabled()
    assert "Skip" in panel.selection_label.text()
    panel.table.selectRow(1)  # Preview selection is never acceptance.
    assert panel.selected_ids == []
    assert not model.flags(model.index(2, 0)) & Qt.ItemFlag.ItemIsUserCheckable
    assert not model.setData(model.index(2, 0), Qt.CheckState.Checked, Qt.ItemDataRole.CheckStateRole)
    select_mask_groups(window, ["lower"])
    assert panel.selected_ids == ["lower"] and panel.apply_button.isEnabled()
    assert not panel.confirmed and not window.start_button.isEnabled()
    calls, prompts = [], []
    monkeypatch.setattr(window.controller, "apply_occlusion_masks",
                        lambda *a, **kw: calls.append((a, kw)), raising=False)
    monkeypatch.setattr(window, "_review_operator", lambda title, text: prompts.append(text) or "Operator")
    panel.apply_button.click()
    assert calls == [((window.project, "a" * 64, "Operator"), {"accepted_block_ids": ["lower"]})]
    assert "1 selected groups" in prompts[0] and "2 groups will remain unmasked" in prompts[0]
    assert not panel.confirmed
    assert model.setData(model.index(1, 0), Qt.CheckState.Unchecked, Qt.ItemDataRole.CheckStateRole)
    assert not panel.apply_button.isEnabled()
    window.apply_occlusion("a" * 64, [])
    assert "Skip" in window.errors[-1] and len(calls) == 1


@pytest.mark.parametrize("ids", [["other"], ["camera-group", "camera-group"], [1], "camera-group"])
def test_occlusion_apply_rejects_stale_or_invalid_group_selection(window, ids):
    completed_batch(window)
    window._event(mask_event())
    select_mask_groups(window, ["camera-group"])
    window.apply_occlusion("a" * 64, ids)
    assert "selection changed" in window.errors[-1] and not window.controller.calls


def test_occlusion_partial_applied_display_uses_canonical_mappings(window):
    completed_batch(window)
    groups = [{"group_id": key, "status": "candidate_review_required", "blockers": []}
              for key in ("upper", "lower")]
    mappings = [{"group_id": "lower", "image_id": key} for key in ("image1", "image2")]
    window._event(mask_event(groups=groups, mappings=mappings, decision="applied", confirmed=True))
    panel, model = window.occlusion, window.occlusion.model
    assert panel.confirmed and panel.selected_ids == ["lower"]
    assert model.data(model.index(0, 3)) == "Not selected · unmasked"
    assert model.data(model.index(1, 3)) == "Applied"
    assert "1 masked / 1 unmasked groups" in panel.summary.text()
    assert not model.setData(model.index(0, 0), Qt.CheckState.Checked, Qt.ItemDataRole.CheckStateRole)
    window._event(mask_event(groups=groups, assessment_hash="c" * 64))
    assert panel.selected_ids == [] and not panel.confirmed and not panel.apply_button.isEnabled()
    select_mask_groups(window, ["upper"])
    panel.editors["sample_count"].setValue(24)
    assert not panel.apply_button.isEnabled() and not window.start_button.isEnabled()
    assert not model.setData(model.index(1, 0), Qt.CheckState.Checked, Qt.ItemDataRole.CheckStateRole)
    panel.invalidate()
    assert panel.selected_ids == []


@pytest.mark.parametrize("mappings", [[], [{"group_id": "foreign"}], [{"image_id": "missing-group"}], None])
def test_occlusion_applied_without_attributable_group_mapping_is_unconfirmed(window, mappings):
    completed_batch(window)
    window._event(mask_event(decision="applied", confirmed=True, mappings=mappings))
    assert not window.occlusion.confirmed and not window.start_button.isEnabled()
    assert "Unconfirmed" in window.occlusion.model.data(window.occlusion.model.index(0, 3))


def test_project_logging_failure_is_deduplicated_persistent_and_project_bound(window, tmp_path):
    project = window.project
    event = {"kind": "progress", "logging_error": "Cannot append the project event log"}
    window._event(event)
    window._event(event)
    assert window.logs.toPlainText().count("PROJECT LOGGING FAILED") == 1
    assert not window.logging_warning.isHidden()
    window._event({"kind": "state", "state": "review_ready", "ownership_released": True})
    window._event({"kind": "progress", "message": "Normal progress", "current": 1, "total": 2})
    assert "recovery has not been confirmed" in window.logging_warning.text()
    window._event({**event, "project_id": "foreign", "logging_error": "Other project's failure"})
    assert "Other project's failure" not in window.logs.toPlainText()
    other = ProjectDocument.create("NA888", "H8888", tmp_path / "other", [])
    window.set_project(other)
    assert window.logging_warning.isHidden()
    window.set_project(project)
    assert not window.logging_warning.isHidden()
    window._event(event)
    assert window.logs.toPlainText().count("PROJECT LOGGING FAILED") == 1
    assert window.controller.calls == []


def test_actual_engine_temporal_contact_sheet_opens_scroll_zoom_without_approval(window, tmp_path, qapp):
    from PySide6.QtGui import QImageReader
    from modules import temporal_occlusion
    from testing.test_temporal_occlusion import fixture_frames, assess
    source, frames = fixture_frames(tmp_path)
    original_hashes = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in source.iterdir()}
    assessment = assess(source, frames)
    preview = temporal_occlusion.write_temporal_preview(assessment, artifact_dir=window.project.root / "proc/tmp/previews")
    sheet = Path(preview["overlay_path"])
    sheet_hash = hashlib.sha256(sheet.read_bytes()).hexdigest()
    completed_batch(window)
    group = {"group_id": "engine-block", "status": assessment["status"], "blockers": assessment["blockers"],
             "start_unix": 1735689600, "block_seconds": 900,
             "previews": [{"image_path": str(frames[0].path), "overlay_path": str(sheet)}]}
    window._event(mask_event(groups=[group]))
    before = window.project.to_dict()
    assert window.occlusion.open_review_button.isEnabled()
    window.occlusion.open_review_button.click()
    viewer = window.occlusion._review_viewer
    for _ in range(200):
        qapp.processEvents()
        if viewer.canvas.image is not None:
            break
        QTest.qWait(10)
    image = viewer.canvas.image
    assert image is not None, viewer.status.text()
    assert image.size() == QImageReader(str(sheet)).size()
    assert image.height() == 3 * (assessment["analysis_height"] + 45)
    assert "first / middle / last" in viewer.windowTitle()
    assert "2025-01-01" in viewer.windowTitle()
    viewer.zoom.setValue(400)
    qapp.processEvents()
    assert viewer.canvas.height() == image.height() * 4
    assert viewer.scroll.verticalScrollBar().maximum() > 0
    viewer.scroll.verticalScrollBar().setValue(viewer.scroll.verticalScrollBar().maximum())
    viewer.actual_button.click()
    assert viewer.canvas.size() == image.size()
    viewer.fit_button.click()
    assert viewer.zoom.value() <= 100
    assert window.project.to_dict() == before
    assert window.occlusion.selected_ids == [] and not window.occlusion.confirmed
    assert window.controller.calls == []
    assert original_hashes == {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in source.iterdir()}
    assert hashlib.sha256(sheet.read_bytes()).hexdigest() == sheet_hash
    window.occlusion.invalidate()
    assert not viewer.isVisible() and not window.occlusion.open_review_button.isEnabled()
    assert viewer.canvas.image is None  # Repeated group review must release decoded images.


def test_enlarged_review_enforces_containment_and_reader_allocation_limit(window, tmp_path, qapp):
    from PySide6.QtGui import QImage, QImageReader
    from desktop.image_review import ImageReviewDialog
    outside = ImageReviewDialog(window.project, tmp_path / "outside.png", title="Read-only test")
    assert "outside the project" in outside.status.text()
    assert outside.canvas.image is None and not outside.zoom.isEnabled()
    outside.close()
    source = Path(window.project.to_dict()["sources"][0])
    source.mkdir()
    target = source / "allocation-test.png"
    image = QImage(1024, 1024, QImage.Format.Format_RGB32)
    image.fill(Qt.GlobalColor.white)
    assert image.save(str(target))
    before = target.read_bytes()
    previous = QImageReader.allocationLimit()
    QImageReader.setAllocationLimit(1)
    viewer = None
    try:
        viewer = ImageReviewDialog(window.project, target, title="Allocation guard test")
        viewer.show()
        for _ in range(200):
            qapp.processEvents()
            if viewer.status.text().startswith("Preview unavailable"):
                break
            QTest.qWait(10)
        assert viewer.canvas.image is None and not viewer.zoom.isEnabled()
        assert viewer.status.text().startswith("Preview unavailable")
        assert QImageReader.allocationLimit() == 1
        assert target.read_bytes() == before
    finally:
        if viewer:
            viewer.close()
        QImageReader.setAllocationLimit(previous)


@pytest.mark.parametrize("start,duration,expected", [
    (1735689600, 900, "2025-01-01 00:15:00 UTC"),
    (1735775700, 900, "2025-01-02 00:10:00 UTC"),
    (None, 900, None), (float("nan"), 900, None),
    (1735689600, -1, None), (1e30, 900, None),
])
def test_occlusion_displays_canonical_utc_interval_with_safe_legacy_fallback(window, start, duration, expected):
    window._event(mask_event(groups=[{"group_id": "a" * 64, "status": "blocked", "blockers": [],
                                     "start_unix": start, "block_seconds": duration}]))
    model = window.occlusion.model
    label = model.data(model.index(0, 0))
    tooltip = model.data(model.index(0, 0), Qt.ItemDataRole.ToolTipRole)
    if expected:
        assert expected in label
        assert "End exclusive" in tooltip and "a" * 64 in tooltip
    else:
        assert tooltip == "a" * 64 and len(label) < 64


def test_failed_skip_cannot_leave_previously_applied_masks_ready(window, monkeypatch):
    completed_batch(window)
    window._event(mask_event(decision="applied", confirmed=True))
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **kw: ("Changed decision", True))
    monkeypatch.setattr(window, "_review_operator", lambda *args: "Operator")
    def fail(*args):
        raise ValueError("Batch changed before Skip completed")
    monkeypatch.setattr(window.controller, "skip_occlusion_masks", fail, raising=False)
    window.skip_occlusion()
    assert not window.occlusion.confirmed and not window.start_button.isEnabled()
    assert "Batch changed" in window.errors[-1]


def test_occlusion_actual_helper_parameter_schema_roundtrips_backend_defaults(window):
    from dataclasses import asdict
    from modules.project_occlusion import parameter_schema
    from modules.temporal_occlusion import TemporalMaskConfig
    defaults = asdict(TemporalMaskConfig())
    window._event(mask_event(parameters=defaults, parameter_schema=parameter_schema()))
    assert window.occlusion.options() == defaults
    assert not window.occlusion.dirty and not window.occlusion.confirmed


def test_occlusion_skip_without_generation_does_not_invent_zero_unmasked_groups(window):
    window._event(mask_event(decision="skipped", confirmed=True, groups=[]))
    assert "All batch images remain unmasked" in window.occlusion.summary.text()
    assert "counts unavailable" in window.occlusion.summary.text()


def test_occlusion_inconsistent_schema_refuses_instead_of_silently_clamping(window):
    completed_batch(window)
    window._event(mask_event(parameters={"sample_count": 12}, parameter_schema=[
        {"key": "sample_count", "type": "int", "min": 0, "max": 1}]))
    assert window.occlusion.schema_errors
    assert not window.occlusion.scan_button.isEnabled()
    assert not window.occlusion.apply_button.isEnabled()
    assert window.occlusion.skip_button.isEnabled()
    assert "proposed value 12" in window.occlusion.summary.text()
    with pytest.raises(ValueError, match="not changed"):
        window.occlusion.options()
    window.scan_occlusion()
    assert not window.controller.calls


@pytest.mark.parametrize("fails", [False, True])
def test_real_controller_async_mask_apply_updates_ui_only_after_terminal_release(window, monkeypatch, qapp, fails):
    from modules.project_controller import ProjectController
    from modules.project_reviews import ReviewStore
    from modules import project_occlusion
    completed_batch(window)
    controller = ProjectController()
    window._unsubscribe()
    window.controller = controller
    window._unsubscribe = controller.subscribe(window.controller_event.emit)
    payload = {key: value for key, value in mask_event().items() if key not in ("kind", "assessment_hash", "confirmed")}
    store = ReviewStore(window.project)
    saved = store.put("occlusion_review", payload)
    window._event({**mask_event(), "assessment_hash": saved["assessment_hash"]})
    select_mask_groups(window, ["camera-group"])
    monkeypatch.setattr(project_occlusion, "context", lambda *a, **kw: {"batch_fingerprint": "b" * 64})
    entered, release = threading.Event(), threading.Event()
    def apply(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        if fails:
            raise ValueError("Candidate artifact changed")
        assert kwargs["accepted_block_ids"] == ("camera-group",)
        return {**payload, "decision": "applied", "mappings": [{"group_id": "camera-group"}]}
    monkeypatch.setattr(project_occlusion, "apply", apply)
    monkeypatch.setattr(project_occlusion, "validate", lambda *a, **kw: None)
    monkeypatch.setattr(window, "_review_operator", lambda *a: "Operator")
    try:
        window.apply_occlusion(saved["assessment_hash"], ["camera-group"])
        assert entered.wait(5)
        qapp.processEvents()
        assert window._running and not window.start_button.isEnabled()
        assert not window.occlusion.confirmed
        release.set()
        controller._future.result(timeout=5)
        qapp.processEvents()
        assert not window._running
        assert window.occlusion.confirmed is (not fails)
        assert window.start_button.isEnabled() is (not fails)
    finally:
        release.set()
        controller._pool.shutdown(wait=True)
