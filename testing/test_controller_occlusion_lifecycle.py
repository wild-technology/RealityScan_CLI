"""Controller transactions must never turn generation or failed copies into approval."""
from pathlib import Path

import pytest

from modules.project_reviews import write_json
from testing.test_project_controller_adversarial import controller, reviewed, finish, wait
from testing.test_project_occlusion import case


@pytest.fixture
def mask_project(reviewed, monkeypatch):
    from modules import project_occlusion
    project = reviewed.project
    for stage in ("preprocess", "batch"):
        finish(project, stage)
    project.save()
    context = {"batch_fingerprint": "a" * 64}
    monkeypatch.setattr(project_occlusion, "context", lambda *a, **kw: context)
    return reviewed, project_occlusion, context


def approve_skip(case):
    value = case.store.put("occlusion_review", {
        "decision": "skipped", "batch_fingerprint": "a" * 64, "reason": "No hardware"})
    case.store.approve("occlusion_review", value["assessment_hash"], "operator")


def test_failed_regeneration_revokes_old_approval(mask_project, controller, monkeypatch):
    case, helper, _ = mask_project
    approve_skip(case)
    finish(case.project, "align")
    case.project.save()
    def fail(*args, **kwargs):
        raise OSError("Image decode failed")
    monkeypatch.setattr(helper, "generate", fail)
    events = []
    controller.subscribe(events.append)
    controller.scan_occlusion_masks(case.project)
    wait(controller)
    assert case.store.read("occlusion_review")["approval"] is None
    assert case.project.to_dict()["stages"]["align"]["state"] == "invalidated"
    assert any("Image decode failed" in e.get("message", "") for e in events)


def test_invalid_tolerance_does_not_invalidate_previous_processing(mask_project, controller, monkeypatch):
    case, helper, _ = mask_project
    approve_skip(case)
    finish(case.project, "align")
    case.project.save()
    before = case.store.read("occlusion_review")
    calls = []
    monkeypatch.setattr(helper, "generate", lambda *a, **kw: calls.append(a))
    controller.scan_occlusion_masks(case.project, {"sample_count": -1})
    wait(controller)
    assert not calls
    assert case.store.read("occlusion_review") == before
    assert case.project.to_dict()["stages"]["align"]["state"] == "succeeded"


def test_native_pool_layout_rejected_before_batch_work(reviewed, controller):
    before = reviewed.project.to_dict()
    with pytest.raises(ValueError, match="copy batch layout"):
        controller.apply_settings(reviewed.project, "batch", {"b_zone_layout": "pool"})
    assert reviewed.project.to_dict() == before
    reviewed.project.set_settings("batch", {"b_zone_layout": "pool"})
    with pytest.raises(ValueError, match="copy batch layout"):
        controller._prepare_session(reviewed.project, "batch")


def test_apply_cannot_accept_stale_preview(mask_project, controller, monkeypatch):
    case, helper, _ = mask_project
    case.store.put("occlusion_review", {"decision": "generated", "batch_fingerprint": "a" * 64})
    calls = []
    monkeypatch.setattr(helper, "apply", lambda *a, **kw: calls.append(a))
    controller.apply_occlusion_masks(case.project, "b" * 64, "operator")
    wait(controller)
    assert not calls
    assert case.store.read("occlusion_review")["approval"] is None


def test_validation_failure_after_copy_cannot_approve(mask_project, controller, monkeypatch):
    case, helper, _ = mask_project
    value = case.store.put("occlusion_review", {"decision": "generated", "batch_fingerprint": "a" * 64})
    monkeypatch.setattr(helper, "apply", lambda *a, **kw: {
        "decision": "applied", "batch_fingerprint": "a" * 64})
    def fail(*args, **kwargs):
        raise ValueError("Zone mask bytes changed")
    monkeypatch.setattr(helper, "validate", fail)
    controller.apply_occlusion_masks(case.project, value["assessment_hash"], "operator")
    wait(controller)
    assert case.store.read("occlusion_review")["approval"] is None


def test_failed_skip_revokes_previous_approval(mask_project, controller, monkeypatch):
    case, helper, _ = mask_project
    approve_skip(case)
    def fail(*args, **kwargs):
        raise OSError("Owned mask cleanup incomplete")
    monkeypatch.setattr(helper, "skip", fail)
    controller.skip_occlusion_masks(case.project, "Review with no masks", "operator")
    wait(controller)
    assert case.store.read("occlusion_review")["approval"] is None


def test_successful_apply_requires_helper_validation_before_approval(mask_project, controller, monkeypatch):
    case, helper, _ = mask_project
    value = case.store.put("occlusion_review", {"decision": "generated", "batch_fingerprint": "a" * 64})
    decision = {"decision": "applied", "batch_fingerprint": "a" * 64}
    monkeypatch.setattr(helper, "apply", lambda *a, **kw: decision)
    calls = []
    def validate(*args, **kwargs):
        assert case.store.read("occlusion_review")["approval"] is None
        calls.append(args)
        return decision
    monkeypatch.setattr(helper, "validate", validate)
    events = []
    controller.subscribe(events.append)
    controller.apply_occlusion_masks(case.project, value["assessment_hash"], "operator")
    wait(controller)
    assert len(calls) == 1
    assert case.store.require_occlusion_review("a" * 64)["payload"]["decision"] == "applied"
    assert any(e["kind"] == "occlusion_masks" and e["confirmed"] for e in events)


def test_hydration_rejects_forged_saved_approval(mask_project, controller):
    case, _, _ = mask_project
    approve_skip(case)
    value = case.store.read("occlusion_review")
    value["approval"]["assessment_hash"] = "b" * 64
    write_json(case.store.path("occlusion_review"), value)
    event = controller._occlusion_event_data(case.project)
    assert event["confirmed"] is False
    assert "confirmed" in event["message"]


@pytest.mark.parametrize("accepted", [[], ["blocked"], ["unknown"], ["good", "good"]])
def test_invalid_block_selection_preserves_existing_results(mask_project, controller, monkeypatch, accepted):
    case, helper, _ = mask_project
    value = case.store.put("occlusion_review", {
        "decision": "generated", "batch_fingerprint": "a" * 64,
        "groups": [{"group_id": "good", "status": "candidate_review_required"},
                   {"group_id": "blocked", "status": "blocked"}]})
    finish(case.project, "align")
    case.project.save()
    calls = []
    monkeypatch.setattr(helper, "apply", lambda *a, **kw: calls.append(kw))
    controller.apply_occlusion_masks(case.project, value["assessment_hash"], "operator",
                                     accepted_block_ids=accepted)
    wait(controller)
    assert not calls
    assert case.store.read("occlusion_review") == value
    assert case.project.to_dict()["stages"]["align"]["state"] == "succeeded"


def test_only_explicitly_selected_blocks_reach_mask_publisher(mask_project, controller, monkeypatch):
    case, helper, _ = mask_project
    value = case.store.put("occlusion_review", {
        "decision": "generated", "batch_fingerprint": "a" * 64,
        "groups": [{"group_id": key, "status": "candidate_review_required"}
                   for key in ("upper", "lower")]})
    seen = []
    decision = {"decision": "applied", "batch_fingerprint": "a" * 64}
    def apply(*args, **kwargs):
        seen.append(kwargs["accepted_block_ids"])
        return decision
    monkeypatch.setattr(helper, "apply", apply)
    monkeypatch.setattr(helper, "validate", lambda *a, **kw: decision)
    controller.apply_occlusion_masks(case.project, value["assessment_hash"], "operator",
                                     accepted_block_ids=["lower"])
    wait(controller)
    assert seen == [("lower",)]
    assert case.store.require_occlusion_review("a" * 64)["payload"]["decision"] == "applied"


def test_real_generate_apply_skip_preserves_source_and_overlap(case, controller):
    """Run real engine, copy receipts and persisted approvals via public actions."""
    from modules import project_occlusion
    originals = {path: path.read_bytes() for path in case.source.rglob("*.png")}
    controller.scan_occlusion_masks(case.project)
    wait(controller)
    generated = case.store.read("occlusion_review")
    assert generated["payload"]["decision"] == "generated"
    assert generated["approval"] is None
    controller.apply_occlusion_masks(case.project, generated["assessment_hash"], "test operator")
    wait(controller)
    decision = project_occlusion.validate(case.project)
    assert decision["decision"] == "applied"
    copies = list(case.batch.rglob("*.mask.png"))
    assert len(copies) == 36
    overlap = case.batch / "zone_1" / case.items[6].camera / (Path(case.items[6].path).name + ".mask.png")
    peer = case.batch / "zone_2" / overlap.parent.name / overlap.name
    assert overlap.read_bytes() == peer.read_bytes()
    controller.skip_occlusion_masks(case.project, "Compare without masks", "test operator")
    wait(controller)
    assert project_occlusion.validate(case.project)["decision"] == "skipped"
    assert not list(case.batch.rglob("*.mask.png"))
    assert all(path.read_bytes() == content for path, content in originals.items())


def test_real_partial_block_approval_masks_only_accepted_images(case, controller):
    from modules import project_occlusion
    controller.scan_occlusion_masks(case.project, {
        "block_seconds": 120, "sample_count": 12, "min_samples": 12, "min_span_seconds": 100})
    wait(controller)
    generated = case.store.read("occlusion_review")
    groups = generated["payload"]["groups"]
    assert len(groups) == 2
    assert all(group["status"] == "candidate_review_required" for group in groups)
    chosen = groups[0]
    controller.apply_occlusion_masks(case.project, generated["assessment_hash"], "operator",
                                     accepted_block_ids=[chosen["group_id"]])
    wait(controller)
    decision = project_occlusion.validate(case.project)
    assert {row["group_id"] for row in decision["mappings"]} == {chosen["group_id"]}
    assert {row["image_id"] for row in decision["mappings"]} == set(chosen["image_ids"])
    mapped_names = {Path(row["image"]["path"]).name for row in decision["mappings"]}
    images = [path for path in case.batch.rglob("*.png") if not path.name.endswith(".mask.png")]
    assert len(images) == 36
    for image in images:
        assert image.with_name(image.name + ".mask.png").exists() == (image.name in mapped_names)
