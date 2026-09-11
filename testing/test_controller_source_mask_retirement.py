"""Source-mask retirement cannot be bypassed by restoring an image selection."""
import pytest

from modules.project_controller import ProjectController
from testing.test_project_controller_adversarial import controller, reviewed


def test_native_processing_rejects_legacy_source_masks(reviewed):
    with pytest.raises(ValueError, match="Rescan inventory"):
        ProjectController._require_retired_source_masks(reviewed.store, reviewed.items)


def test_native_processing_accepts_retired_policy(reviewed):
    reviewed.store.save_inventory(reviewed.items, source_mask_policy="ignore_existing")
    current = reviewed.store.inventory()
    ProjectController._require_retired_source_masks(reviewed.store, current)
    assert all(not item.included for item in current if item.kind == "mask")


def test_reinclude_image_cannot_revive_retired_mask(reviewed, controller):
    reviewed.store.save_inventory(reviewed.items, source_mask_policy="ignore_existing")
    path = str(reviewed.photos[1])
    before = {p: p.read_bytes() for p in reviewed.source.rglob("*.mask.png")}
    controller.set_inventory_decision(reviewed.project, path, False, "Review image")
    controller.set_inventory_decision(reviewed.project, path, True, "Retain useful scene")
    items = reviewed.store.inventory()
    assert next(item for item in items if item.path == path).included
    assert all(not item.included for item in items if item.kind == "mask")
    assert all(p.read_bytes() == content for p, content in before.items())
