"""Post-batch optional masking requires an explicit content-bound decision."""
import pytest

from modules.project_reviews import ReviewStore, digest, write_json
from modules.project_workspace import ProjectDocument
from modules.source_inventory import SourceInventory, SourceItem, approval_token


@pytest.fixture
def store(tmp_path):
    return ReviewStore(ProjectDocument.create("NA999", "H9999", tmp_path / "project", []))


def decision(store, mode="skipped", **extra):
    payload = {"batch_fingerprint": digest({"batch": "one"}), "decision": mode,
               "reason": "Operator elected to process without optional masks", **extra}
    value = store.put("occlusion_review", payload)
    store.approve("occlusion_review", value["assessment_hash"], "operator")
    return value


@pytest.mark.parametrize("mode", ["applied", "skipped"])
def test_explicit_decision_bound_to_current_batch(store, mode):
    value = decision(store, mode)
    assert store.require_occlusion_review(value["payload"]["batch_fingerprint"])["approval"]["by"] == "operator"
    with pytest.raises(ValueError, match="content changed"):
        store.require_occlusion_review(digest({"batch": "changed image bytes"}))


def test_read_gate_creates_nothing_when_review_missing(store):
    with pytest.raises(ValueError, match="explicitly skip"):
        store.require_occlusion_review("a" * 64)
    assert not store.project.root.exists()


@pytest.mark.parametrize("payload", [
    {"decision": "generated", "batch_fingerprint": "a" * 64},
    {"decision": "skipped", "batch_fingerprint": "a" * 64, "reason": " "},
    {"decision": "skipped", "batch_fingerprint": "unknown", "reason": "chosen"},
])
def test_generated_or_incomplete_decisions_cannot_be_approved(store, payload):
    value = store.put("occlusion_review", payload)
    with pytest.raises(ValueError):
        store.approve("occlusion_review", value["assessment_hash"], "operator")


@pytest.mark.parametrize("upstream", ["inventory", "navigation", "georeference", "quality", "spatial", "selection", "workflow"])
def test_upstream_update_retires_mask_decision_without_deleting_artifacts(store, upstream):
    value = decision(store)
    artifact = store.project.resolve_path("proc/masks/retained.png")
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"historical output")
    store.put(upstream, {"changed": True})
    with pytest.raises(ValueError, match="confirmed"):
        store.require_occlusion_review(value["payload"]["batch_fingerprint"])
    assert artifact.read_bytes() == b"historical output"


def test_tampered_decision_fails_closed(store):
    value = decision(store)
    altered = store.read("occlusion_review")
    altered["payload"]["decision"] = "applied"
    write_json(store.path("occlusion_review"), altered)
    with pytest.raises(ValueError, match="confirmed"):
        store.require_occlusion_review(value["payload"]["batch_fingerprint"])


def masked_inventory(store):
    image = SourceItem(str(store.project.root.parent / "source/image.jpg"), "image.jpg", "image", 1, 1,
                       sha256="a" * 64, included=True)
    mask = SourceItem(str(store.project.root.parent / "source/image.mask.png"), "image.mask.png", "mask", 1, 1,
                      sha256="b" * 64, included=True, mask_for=image.path)
    return SourceInventory([image, mask], source_root=store.project.root.parent / "source", fingerprint="c" * 64)


def test_source_mask_retirement_persists_across_fresh_inventory_scan(store):
    initial = masked_inventory(store)
    value = store.save_inventory(initial, source_mask_policy="ignore_existing")
    assert initial[0].included and not initial[1].included
    assert "retired" in value["payload"]["decisions"][initial[1].path]["reason"]
    fresh = masked_inventory(store)
    saved = store.save_inventory(fresh)
    assert saved["payload"]["source_mask_policy"] == "ignore_existing"
    assert not fresh[1].included
    assert not store.inventory()[1].included
    assert saved["payload"]["input_inventory_hash"] == approval_token(fresh)


def test_legacy_first_inventory_save_preserves_mask_selection(store):
    store.save_inventory(masked_inventory(store))
    assert store.inventory()[1].included


def test_retired_mask_cannot_be_revived_even_with_recomputed_hash(store):
    store.save_inventory(masked_inventory(store), source_mask_policy="ignore_existing")
    value = store.read("inventory")
    value["payload"]["items"][1]["included"] = True
    value["payload"]["input_inventory_hash"] = approval_token(masked_inventory(store))
    value["assessment_hash"] = digest(value["payload"])
    write_json(store.path("inventory"), value)
    with pytest.raises(ValueError, match="Retired source masks"):
        store.inventory()


def test_unknown_policy_refused_before_inventory_write(store):
    with pytest.raises(ValueError, match="Unsupported source mask"):
        store.save_inventory(masked_inventory(store), source_mask_policy="auto_invert")
    assert not store.project.root.exists()
