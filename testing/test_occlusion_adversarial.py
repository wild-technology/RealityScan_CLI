"""Read-only production audit; all mutations are confined to imported tmp fixtures."""
from pathlib import Path

import pytest

from modules import project_occlusion as masks
from modules import source_inventory
from modules.project_reviews import write_json
from testing.test_project_occlusion import case, approve, generate
from testing.test_desktop_ui import qapp
from testing.test_project_controller_adversarial import controller, reviewed, processing_ready


@pytest.mark.parametrize("explicit_project", [True, False])
def test_native_mask_gate_survives_legitimate_save_as_of_same_project(case, monkeypatch, explicit_project):
    context = masks.context(case.project)
    decision = masks.skip(case.project, context, "Explicit no-mask review", "operator")
    approve(case, decision)
    case.project.save(case.project.root / "alternate.rovscan")
    assert len(list(case.project.root.glob("*.rovscan"))) == 2
    monkeypatch.delenv("RS_PROJECT_FILE", raising=False)
    if explicit_project:
        monkeypatch.setenv("RS_PROJECT_FILE", str(case.project.path))
    else:
        with pytest.raises(ValueError, match="unambiguous|ambiguous|explicit"):
            masks.validate_external(case.project.resolve_path(decision["canonical_manifest"]),
                                     decision["canonical_sha256"], case.selection, case.batch)
        return
    result = masks.validate_external(case.project.resolve_path(decision["canonical_manifest"]),
                                     decision["canonical_sha256"], case.selection, case.batch)
    assert result["decision"] == "skipped"


def test_abort_during_selection_validation_stops_before_hashing_all_images(case, monkeypatch):
    stop = False
    hashed_images = []
    original = source_inventory.file_hash

    def track(path, *, cancelled=None):
        nonlocal stop
        result = original(path, cancelled=cancelled)
        if Path(path).suffix.lower() == ".png":
            hashed_images.append(str(path))
        if Path(path).name == "flight_log_4Q_UTM.txt":
            stop = True
        return result

    monkeypatch.setattr(source_inventory, "file_hash", track)
    with pytest.raises(InterruptedError):
        masks.context(case.project, cancelled=lambda: stop)
    assert hashed_images == [], "Abort was ignored while every selected source copy was hashed"


@pytest.mark.parametrize("foreign", ["uuid", "root", "relative"])
def test_explicit_active_document_cannot_borrow_other_project_mask_approval(case, monkeypatch, foreign):
    from uuid import uuid4
    context = masks.context(case.project)
    decision = masks.skip(case.project, context, "Explicit no-mask review", "operator")
    approve(case, decision)
    document = case.project.root / "foreign.rovscan"
    raw = case.project.to_dict()
    if foreign == "uuid":
        raw["id"] = str(uuid4())
    elif foreign == "root":
        raw["root"] = str(case.project.root.parent / "different-project")
    write_json(document, raw)
    monkeypatch.setenv("RS_PROJECT_FILE", document.name if foreign == "relative" else str(document))
    with pytest.raises(ValueError):
        masks.validate_external(case.project.resolve_path(decision["canonical_manifest"]),
                                decision["canonical_sha256"], case.selection, case.batch)


def test_ui_respects_odd_window_schema_step(qapp):
    from desktop.occlusion_review import OcclusionReview
    from dataclasses import asdict
    widget = OcclusionReview()
    try:
        widget.set_assessment({"parameters": asdict(masks.engine.TemporalMaskConfig()),
                               "parameter_schema": masks.parameter_schema()})
        assert widget.editors["structure_window"].singleStep() == 2
        assert widget.editors["shape_close_pixels"].singleStep() == 2
    finally:
        widget.close()
        qapp.processEvents()


def test_legacy_unknown_camera_time_help_is_truthful_without_changing_flags(qapp):
    from PySide6.QtCore import Qt
    from desktop.main_window import SourceTable
    widget = SourceTable()
    original = "Unrecognised camera; assign a camera or explicitly exclude; No valid UTC timestamp; explicit correction or exclusion required"
    item = {"path": "unknown.jpg", "camera": "", "family": "", "kind": "image",
            "included": True, "exception": original}
    try:
        widget.set_items([item])
        shown = widget.model.data(widget.model.index(0, 6))
        tooltip = widget.model.data(widget.model.index(0, 6), Qt.ItemDataRole.ToolTipRole)
        assert "assign a camera" not in shown + tooltip
        assert "explicit correction" not in shown + tooltip
        assert "cannot include" in shown and "corrected separate delivery" in shown
        assert item["exception"] == original and item["included"] is True
        assert widget.model.items[0] is item
        assert "1 included" in widget.summary.text() and "1 exceptions" in widget.summary.text()
        widget.proxy.configure(query="unsupported")
        assert widget.proxy.rowCount() == 1
    finally:
        widget.close()


def test_failed_first_copy_write_does_not_strand_unowned_mask_and_block_retry(case, monkeypatch):
    context, proposal = generate(case)
    original_open = Path.open
    failed_paths = []

    class FailingWriter:
        def __init__(self, stream):
            self.stream = stream

        def __getattr__(self, name):
            return getattr(self.stream, name)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return self.stream.__exit__(*args)

        def write(self, content):
            self.stream.write(content[:8])
            self.stream.flush()
            raise OSError("Injected disk write failure after partial PNG")

    def broken_copy(path, mode="r", *args, **kwargs):
        stream = original_open(path, mode, *args, **kwargs)
        # Copies are now written to owned temporaries before exclusive
        # promotion. Other callers still need Path.open's real file protocol.
        if (mode == "xb" and path.suffix == ".partial"
                and path.is_relative_to(case.project.root / "proc/masks/occlusion")):
            failed_paths.append(path)
            return FailingWriter(stream)
        return stream

    with monkeypatch.context() as patch:
        patch.setattr(Path, "open", broken_copy)
        with pytest.raises(OSError, match="Injected disk write"):
            masks.apply(case.project, context, proposal, "operator")
    assert len(failed_paths) == 1
    assert not failed_paths[0].exists()
    # A known process-created partial must be cleaned or durably attributed so
    # explicit Skip can restore the workflow, without treating it as foreign.
    skipped = masks.skip(case.project, context, "Recover failed publication", "operator")
    assert skipped["decision"] == "skipped"
    assert not list(case.batch.rglob("*.mask.png"))


def test_controller_real_helper_lifecycle_reopen_rerun_skip_and_rebatch(case, monkeypatch):
    from modules.project_controller import ProjectController
    from modules.project_workspace import ProjectDocument
    controller = ProjectController()
    events = []
    controller.subscribe(events.append)
    monkeypatch.setenv("RS_PROJECT_FILE", str(case.project.path))
    originals = {p: p.read_bytes() for p in case.source.iterdir() if p.is_file()}

    def wait():
        controller._future.result(timeout=20)
        assert events[-1].get("ownership_released") is True
        assert events[-1].get("state") == "review_ready", events[-1]

    def external(decision):
        return masks.validate_external(case.project.resolve_path(decision["canonical_manifest"]),
                                       decision["canonical_sha256"], case.selection, case.batch)

    try:
        controller.scan_occlusion_masks(case.project)
        wait()
        proposal = case.store.read("occlusion_review")
        assert proposal["approval"] is None
        controller.apply_occlusion_masks(case.project, proposal["assessment_hash"], "operator")
        wait()
        first = case.store.read("occlusion_review")["payload"]
        assert external(first)["decision"] == "applied"
        canonical = case.project.resolve_path(first["canonical_manifest"])
        canonical_bytes = canonical.read_bytes()
        # Simulate only the outputs/state transitions; never launch RealityScan.
        next(case.batch.rglob("frame000.png")).with_suffix(".xmp").write_text("solved pose")
        for stage in ("align", "merge"):
            attempt = case.project.start_stage(stage)
            case.project.save()
            assert external(first)["decision"] == "applied"
            case.project.complete_stage(stage, attempt_id=attempt)
            case.project.save()
        controller.scan_occlusion_masks(case.project)
        wait()
        assert case.project.to_dict()["stages"]["align"]["state"] == "invalidated"
        assert case.project.to_dict()["stages"]["merge"]["state"] == "invalidated"
        with pytest.raises(ValueError, match="confirmed|review|decision"):
            external(first)
        proposal = case.store.read("occlusion_review")
        controller.apply_occlusion_masks(case.project, proposal["assessment_hash"], "operator")
        wait()
        second = case.store.read("occlusion_review")["payload"]
        assert external(second)["decision"] == "applied"
        assert canonical.read_bytes() == canonical_bytes
        controller.skip_occlusion_masks(case.project, "Review without hardware masks", "operator")
        wait()
        skipped = case.store.read("occlusion_review")["payload"]
        assert external(skipped)["decision"] == "skipped"
        reopened = ProjectDocument.load(case.project.path)
        restored = controller.load_project_state(reopened)
        assert next(e for e in restored if e["kind"] == "occlusion_masks")["confirmed"] is True
        assert not list(case.batch.rglob("*.mask.png"))
        assert {p: p.read_bytes() for p in case.source.iterdir() if p.is_file()} == originals
        case.project.restart_stage("batch", "New batching attempt")
        attempt = case.project.start_stage("batch")
        case.project.complete_stage("batch", attempt_id=attempt)
        case.project.save()
        with pytest.raises(ValueError, match="changed|stale"):
            external(skipped)
    finally:
        controller._pool.shutdown(wait=True)


def test_public_alignment_setting_edit_does_not_trap_unchanged_georeference(processing_ready, controller, monkeypatch):
    import rs
    from modules import verify
    from modules.project_controller import GEO_SETTINGS_BLOCKS
    case = processing_ready
    project, store = case.project, case.store
    geo_before = store.read("georeference")["payload"]
    reviews_before = {name: store.read(name) for name in ("quality", "spatial")}
    global_before = project.settings_hash
    log = project.resolve_path(geo_before["flight_log"])
    original_log = log.read_bytes()
    values = project.to_dict()["settings"]["align"]["values"]
    controller.apply_settings(project, "align", {**values, "r_min_component_size": 51})
    assert project.to_dict()["stages"]["georeference"]["state"] == "succeeded"
    assert project.settings_hash != global_before
    assert project.settings_signature(GEO_SETTINGS_BLOCKS) == geo_before["settings_hash"]
    assert project.settings_approved(["navigation", "cameras", "georeference", "budget"])
    assert not project.settings_approved(["align"])
    project.approve_settings("align", "operator")
    project.save()
    assert {name: store.read(name) for name in reviews_before} == reviews_before
    assert log.read_bytes() == original_log
    assert store.read("georeference")["payload"] == geo_before
    calls, events = [], []
    controller.subscribe(events.append)
    monkeypatch.setattr(rs, "execute_commands", lambda *a, **kw: calls.append(a) or 0)
    monkeypatch.setattr(verify, "verify_workspace", lambda *a, **kw: {"verdict": "ok"})
    controller.start(project, "batch")
    controller._future.result(timeout=15)
    assert calls, [e.get("message") for e in events if e["kind"] == "error"]


def test_public_resource_budget_edit_preserves_completed_science_stages(processing_ready, controller):
    project = processing_ready.project
    reviews_before = {name: processing_ready.store.read(name) for name in ("georeference", "quality", "spatial")}
    values = project.to_dict()["settings"]["budget"]["values"]
    controller.apply_settings(project, "budget", {**values, "cache_delta_gb": values["cache_delta_gb"] + 1})
    assert {name: project.to_dict()["stages"][name]["state"]
            for name in ("inventory", "navigation", "georeference", "preprocess")} == {
                name: "succeeded" for name in ("inventory", "navigation", "georeference", "preprocess")}
    assert not project.settings_approved(["budget"])
    assert project.settings_approved(["navigation", "cameras", "align"])
    assert {name: processing_ready.store.read(name) for name in reviews_before} == reviews_before


@pytest.mark.parametrize("edit_alignment", [False, True], ids=["unchanged-global", "changed-global"])
def test_legacy_georeference_requires_exact_global_settings_match(processing_ready, controller, monkeypatch, edit_alignment):
    import rs
    from modules import verify
    project, store = processing_ready.project, processing_ready.store
    legacy = store.read("georeference")["payload"]
    legacy.pop("settings_scope")
    legacy["settings_hash"] = project.settings_hash
    store.put("georeference", legacy)
    if edit_alignment:
        values = project.to_dict()["settings"]["align"]["values"]
        controller.apply_settings(project, "align", {**values, "r_min_component_size": 51})
        project.approve_settings("align", "operator")
    project.save()
    calls, events = [], []
    controller.subscribe(events.append)
    monkeypatch.setattr(rs, "execute_commands", lambda *a, **kw: calls.append(a) or 0)
    monkeypatch.setattr(verify, "verify_workspace", lambda *a, **kw: {"verdict": "ok"})
    controller.start(project, "batch")
    controller._future.result(timeout=15)
    assert store.read("georeference")["payload"] == legacy
    errors = [event.get("message", "") for event in events if event["kind"] == "error"]
    if edit_alignment:
        assert not calls
        assert any("Georeference inputs/settings changed; rerun georeferencing" in error for error in errors)
    else:
        assert calls, errors
