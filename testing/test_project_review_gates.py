"""Reviews cannot be bypassed by a GUI state change or reused after edits."""
from dataclasses import asdict
from pathlib import Path

import pytest

from modules.project_controller import ProjectController
from modules.project_reviews import ReviewStore, claim_root, digest, write_json
from modules.project_workspace import ProjectDocument
from modules.source_inventory import SourceInventory, SourceItem, approval_token


@pytest.fixture
def reviewed(tmp_path):
    project = ProjectDocument.create("NA999", "H9999", tmp_path / "project", [tmp_path / "source"])
    claim_root(project)
    image = SourceItem(str(tmp_path / "source/camupper_20250101T000000Z.jpeg"),
                       "camupper_20250101T000000Z.jpeg", "image", 1, 1,
                       camera="camupper", family="legacy_camupper", sha256="a" * 64,
                       window_status="in_window", timestamp_utc="2025-01-01T00:00:00Z")
    inventory = SourceInventory([image], source_root=tmp_path / "source", fingerprint="b" * 64)
    store = ReviewStore(project)
    saved = store.save_inventory(inventory)
    store.approve("inventory", saved["assessment_hash"], "operator")
    quality = {"input_inventory_hash": approval_token(inventory), "excluded_paths": [], "results": []}
    saved = store.put("quality", quality)
    store.approve("quality", saved["assessment_hash"], "operator")
    spatial = {"input_inventory_hash": approval_token(inventory),
               "quality_selection_hash": digest(quality), "excluded_paths": []}
    saved = store.put("spatial", spatial)
    store.approve("spatial", saved["assessment_hash"], "operator")
    return project, store, inventory


def test_batch_refuses_before_any_worker_without_review(tmp_path, monkeypatch):
    project = ProjectDocument.create("NA999", "H9999", tmp_path / "project")
    controller = ProjectController()
    calls = []
    monkeypatch.setattr(controller, "_submit", lambda *args: calls.append(args))
    with pytest.raises(FileNotFoundError):
        controller.start(project, "batch")
    assert not calls


def test_batch_requires_quality_and_density_approval(reviewed, monkeypatch):
    project, store, _ = reviewed
    controller = ProjectController()
    calls = []
    monkeypatch.setattr(controller, "_submit", lambda *args: calls.append(args))
    controller.start(project, "batch")
    assert len(calls) == 1
    store.put("quality", store.read("quality")["payload"], invalidate=("spatial",))
    with pytest.raises(ValueError, match="confirmed"):
        controller.start(project, "batch")
    assert len(calls) == 1


def test_selection_change_even_same_counts_invalidates_density(reviewed):
    _, store, _ = reviewed
    quality = store.read("quality")["payload"]
    quality["tolerances"] = {"contrast_floor": 0.01}
    saved = store.put("quality", quality)
    store.approve("quality", saved["assessment_hash"], "operator")
    with pytest.raises(ValueError, match="predates"):
        store.selection()


def test_tampered_approval_or_foreign_root_refused(reviewed):
    project, store, _ = reviewed
    value = store.read("spatial")
    value["payload"]["excluded_paths"] = ["foreign.jpeg"]
    write_json(store.path("spatial"), value)
    with pytest.raises(ValueError, match="confirmed"):
        store.selection()
    other = ProjectDocument.create("NA999", "H9998", project.root)
    with pytest.raises(ValueError, match="different project"):
        claim_root(other, adopt_existing=True)


def test_root_adoption_is_explicit_and_never_removes_files(tmp_path):
    project = ProjectDocument.create("NA999", "H9999", tmp_path / "project")
    existing = project.root / "raw/valuable.txt"
    existing.parent.mkdir(parents=True)
    existing.write_text("original")
    with pytest.raises(ValueError, match="adoption"):
        claim_root(project)
    claim_root(project, adopt_existing=True)
    assert existing.read_text() == "original"


def test_all_images_culled_is_not_a_successful_selection(reviewed):
    _, store, inventory = reviewed
    value = store.read("spatial")["payload"]
    value["excluded_paths"] = [inventory[0].path]
    saved = store.put("spatial", value)
    store.approve("spatial", saved["assessment_hash"], "operator")
    with pytest.raises(ValueError, match="no usable"):
        store.selection()


def test_settings_schema_uses_current_registry_and_locks_weight(tmp_path):
    project = ProjectDocument.create("NA999", "H9999", tmp_path / "project")
    controller = ProjectController()
    schema = {row["key"]: row for row in controller.settings_schema(project)}
    assert schema["zeuss.pitch"]["default"] == 40
    assert schema["zeuss.p_acc"]["default"] == 40
    assert schema["orientation_weight"]["min"] == schema["orientation_weight"]["max"] == 2
    with pytest.raises(ValueError, match="locked"):
        controller.apply_settings(project, "cameras", {"orientation_weight": 3})
