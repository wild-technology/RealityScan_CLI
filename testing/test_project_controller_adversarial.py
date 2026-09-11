"""Adversarial integration contracts: real controller, temporary data, no processes.

Only executor/scientific leaves are replaced. Failures are intentional regression
evidence for the controller owner; do not weaken gates to match current behavior.
"""
from __future__ import annotations

import csv
import json
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

import rs
from modules.project_controller import ProjectController
from modules.project_reviews import ReviewStore, claim_root, digest, write_json
from modules.project_runtime import ExecutionControl, OwnershipUnconfirmed, require_runtime_release
from modules.project_staging import materialize_selection
from modules.project_workspace import ProjectDocument
from modules.source_inventory import (
    apply_dive_window, approval_token, file_hash, hash_identities,
    scan_source, source_fingerprint, verify_images,
)
from modules.spatial_review import assess_spatial


@pytest.fixture
def controller():
    value = ProjectController()
    yield value
    value._pool.shutdown(wait=True)
    if value._project_lease is not None:
        value._project_lease.close()  # Fixture-only handles never represent a real child.


def finish(project, stage):
    # Scoped settings edits can preserve an already-completed predecessor.
    if project.to_dict()["stages"][stage]["state"] == "succeeded":
        return
    attempt = project.start_stage(stage, required_blocks=[])
    project.complete_stage(stage, attempt_id=attempt)


@pytest.fixture
def reviewed(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    photos = []
    for index, color in enumerate(("red", "green", "blue")):
        photo = source / f"camupper_20250524T01000{index}Z.jpg"
        Image.new("RGB", (16, 12), color).save(photo)
        Image.new("L", (16, 12), 255).save(photo.with_name(photo.name + ".mask.png"))
        photos.append(photo)
    duplicate = source / "duplicate" / photos[0].name
    duplicate.parent.mkdir()
    duplicate.write_bytes(photos[0].read_bytes())
    outside = source / "camupper_20250524T030000Z.jpg"
    Image.new("RGB", (16, 12), "yellow").save(outside)
    items = scan_source(source)
    apply_dive_window(items, "2025-05-24T00:00:00Z", "2025-05-24T02:00:00Z")
    for item in items:
        if item.path == str(outside):
            item.included = False
    verify_images(items)
    hash_identities(items)
    project = ProjectDocument.create("NA999", "H9999", tmp_path / "project", [source])
    claim_root(project)
    project.create_layout()
    store = ReviewStore(project)
    value = store.save_inventory(items)
    store.approve("inventory", value["assessment_hash"], "fixture operator")
    for stage in ("inventory", "navigation", "georeference"):
        finish(project, stage)
    from modules.navigation_quality import assess_navigation
    nav = navigation_file(project)
    nav_evidence = assess_navigation(nav, "NA999", "H9999")
    nav_evidence["relative_path"] = nav.relative_to(project.root).as_posix()
    store.put("navigation", nav_evidence)
    quality = {
        "input_inventory_hash": approval_token(items), "tolerances": {}, "excluded_paths": [],
        "results": [{"image_path": item.path, "image_sha256": item.sha256,
                     "assessment_complete": True, "candidate": False, "decision": "keep"}
                    for item in items if item.kind == "image" and item.included and not item.duplicate_of],
    }
    value = store.put("quality", quality)
    store.approve("quality", value["assessment_hash"], "fixture operator")
    points = [{"path": item.path, "x": 500000.123456789 + i, "y": 4000000.987654321,
               "camera": item.camera, "time": item.timestamp_utc, "excluded": not item.included or bool(item.duplicate_of)}
              for i, item in enumerate(items) if item.kind == "image"]
    spatial = {"input_inventory_hash": approval_token(items), "quality_selection_hash": digest(quality),
               "navigation_sha256": nav_evidence["sha256"], "assessment": assess_spatial(points, epsg=32618),
               "excluded_paths": []}
    value = store.put("spatial", spatial)
    store.approve("spatial", value["assessment_hash"], "fixture operator")
    project.save()
    return SimpleNamespace(project=project, store=store, items=items, photos=photos,
                           source=source, outside=outside)


def wait(controller):
    assert controller._future is not None
    controller._future.result(timeout=15)


def snapshot(root):
    return {path.relative_to(root).as_posix(): (path.read_bytes(), path.stat().st_mtime_ns)
            for path in root.rglob("*") if path.is_file()}


@pytest.mark.parametrize("bad_path", ["unknown", "valid_mask"])
def test_bulk_decision_validates_every_path_before_saving(reviewed, controller, monkeypatch, bad_path):
    f = reviewed
    before = snapshot(f.store.root)
    project_before = f.project.to_dict()
    invalid = str(f.source / "not-in-inventory.jpg") if bad_path == "unknown" else next(
        item.path for item in f.items if item.kind == "mask" and not item.exception)
    calls = []
    monkeypatch.setattr(ReviewStore, "save_inventory", lambda *a, **kw: calls.append(kw))
    with pytest.raises(ValueError):
        controller.set_inventory_decisions(f.project, [str(f.photos[1]), invalid], False, "reviewed exclusions")
    assert calls == []
    assert snapshot(f.store.root) == before
    assert f.project.to_dict() == project_before


def test_bulk_decision_saves_and_emits_once_invalidates_reviews(reviewed, controller, monkeypatch):
    f = reviewed
    saved, events = [], []
    original = ReviewStore.save_inventory
    def save(store, items, **kwargs):
        saved.append(kwargs)
        return original(store, items, **kwargs)
    monkeypatch.setattr(ReviewStore, "save_inventory", save)
    controller.subscribe(events.append)
    before_source = snapshot(f.source)
    paths = [str(f.photos[1]), str(f.photos[2])]
    controller.set_inventory_decisions(f.project, paths, False, "Reviewed together")
    assert len(saved) == 1
    assert [e["kind"] for e in events] == ["inventory_decision", "inventory"]
    assert events[0]["paths"] == sorted(paths)
    for name in ("inventory", "quality", "spatial"):
        with pytest.raises(ValueError):
            f.store.require_approved(name)
    items = f.store.inventory()
    assert all(not item.included for item in items if item.path in paths or item.mask_for in paths)
    assert snapshot(f.source) == before_source
    records = [json.loads(line) for line in f.project.resolve_path("logs/controller.jsonl").read_text().splitlines()]
    assert "items" not in records[-1] and records[-1]["items_count"] == len(items)


def test_short_mutation_switches_log_attribution(reviewed, controller, tmp_path):
    f = reviewed
    other = ProjectDocument.create("NA998", "H9998", tmp_path / "other-project", [f.source])
    claim_root(other)
    other.create_layout()
    ReviewStore(other).save_inventory(f.items)
    controller.set_inventory_decisions(f.project, [str(f.photos[1])], False, "first project")
    first_log = f.project.resolve_path("logs/controller.jsonl")
    original = first_log.read_bytes()
    controller.set_inventory_decisions(other, [str(f.photos[2])], False, "second project")
    assert first_log.read_bytes() == original
    rows = [json.loads(line) for line in other.resolve_path("logs/controller.jsonl").read_text().splitlines()]
    assert rows[0]["reason"] == "second project"
    assert rows[0]["paths"] == [str(f.photos[2])]
    assert controller._project is other


def test_reopen_does_not_restore_density_ready_for_changed_navigation(reviewed, controller):
    f = reviewed
    nav = f.project.resolve_path(f.store.read("navigation")["payload"]["relative_path"])
    nav.write_bytes(nav.read_bytes() + b"\n")
    events = controller.load_project_state(f.project)
    assert not any(event.get("state") == "selection_confirmed" for event in events)


def test_reopen_restores_navigation_assessment_for_operator_review(reviewed, controller):
    events = controller.load_project_state(reviewed.project)
    assert any(event["kind"] == "navigation" and event["items"][0]["rows"] > 0 for event in events)


def test_submit_failure_publishes_terminal_release_after_running_event(reviewed, controller, monkeypatch):
    lease = SimpleNamespace(closed=False)
    lease.close = lambda: setattr(lease, "closed", True)
    monkeypatch.setattr(controller, "_acquire_project", lambda project: lease)
    def refuse(*args, **kwargs):
        raise RuntimeError("Executor cannot accept work")
    monkeypatch.setattr(controller._pool, "submit", refuse)
    events = []
    controller.subscribe(events.append)
    with pytest.raises(RuntimeError, match="cannot accept"):
        controller._submit(reviewed.project, "inventory", lambda: None)
    assert lease.closed
    assert events[-1].get("ownership_released") is True
    assert events[-1].get("state") in ("failed", "interrupted")


def test_terminal_release_event_follows_project_lease_release(reviewed, controller, monkeypatch):
    lease = SimpleNamespace(closed=False)
    lease.close = lambda: setattr(lease, "closed", True)
    monkeypatch.setattr(controller, "_acquire_project", lambda project: lease)
    announced = []
    controller.subscribe(lambda event: announced.append(lease.closed) if event.get("ownership_released") is True else None)
    controller._submit(reviewed.project, "inventory", lambda: None)
    wait(controller)
    assert announced and all(announced)


def test_controller_can_explicitly_save_recovered_backup_without_loading_corrupt_primary(tmp_path, controller):
    project = ProjectDocument.create("NA999", "H9999", tmp_path / "backup-project", [])
    controller.save_project(project)
    project.set_settings("example", {"value": 1})
    controller.save_project(project)
    path = project.path
    path.write_text("{truncated", encoding="utf-8")
    recovered = ProjectDocument.load(path, recover_backup=True)
    assert recovered.recovered_from_backup
    before = recovered.to_dict()
    controller.save_project(recovered)
    assert ProjectDocument.load(path).to_dict() == before


@pytest.mark.parametrize("phase", ["work", "submit", "layout", "save", "review"])
def test_lease_close_failure_retains_unconfirmed_owner_and_refuses_reentrant_save(reviewed, controller, monkeypatch, phase):
    lease = SimpleNamespace(closes=0)
    def close():
        lease.closes += 1
        if lease.closes == 1:
            raise OSError("Cannot confirm workspace lease release")
    lease.close = close
    monkeypatch.setattr(controller, "_acquire_project", lambda *args, **kwargs: lease)
    events = []
    controller.subscribe(events.append)
    if phase == "submit":
        monkeypatch.setattr(controller._pool, "submit", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("submit failed")))
    if phase == "layout":
        monkeypatch.setattr(reviewed.project, "create_layout", lambda: (_ for _ in ()).throw(OSError("layout failed")))
    try:
        if phase == "save":
            controller.save_project(reviewed.project)
        elif phase == "review":
            controller.set_inventory_decisions(reviewed.project, [str(reviewed.photos[1])], False, "review")
        else:
            controller._submit(reviewed.project, "inventory", lambda: None)
            wait(controller)
    except (OSError, RuntimeError):
        pass
    assert controller._ownership_unconfirmed
    assert controller._project_lease is lease
    assert not any(event.get("ownership_released") is True for event in events)
    with pytest.raises(OwnershipUnconfirmed):
        controller.save_project(reviewed.project)


def test_direct_terminal_listener_can_queue_next_work_without_releasing_it(reviewed, controller, monkeypatch):
    leases = []
    def acquire(*args, **kwargs):
        lease = SimpleNamespace(closed=False)
        lease.close = lambda: setattr(lease, "closed", True)
        leases.append(lease)
        return lease
    monkeypatch.setattr(controller, "_acquire_project", acquire)
    entered, release, queued = threading.Event(), threading.Event(), threading.Event()
    errors = []
    def second():
        entered.set()
        assert release.wait(5)
    def retry(event):
        if event.get("state") == "review_ready" and not queued.is_set():
            queued.set()
            try:
                controller._submit(reviewed.project, "inventory", second)
            except Exception as exc:
                errors.append(exc)
    controller.subscribe(retry)
    try:
        controller._submit(reviewed.project, "inventory", lambda: None)
        assert entered.wait(5), errors
        assert not errors
        assert leases[0].closed and not leases[1].closed
        assert controller._project_lease is leases[1]
        assert not controller._operation_finished
        with pytest.raises(ValueError, match="still running"):
            controller.save_project(reviewed.project)
    finally:
        release.set()
        wait(controller)
    assert leases[1].closed and controller._project_lease is None


def test_reentrant_save_in_unconfirmed_terminal_listener_is_refused(reviewed, controller, monkeypatch):
    lease = SimpleNamespace(closed=False)
    lease.close = lambda: setattr(lease, "closed", True)
    monkeypatch.setattr(controller, "_acquire_project", lambda *a, **kw: lease)
    attempts = []
    def listener(event):
        if event.get("state") == "ownership_unconfirmed":
            try:
                controller.save_project(reviewed.project)
            except OwnershipUnconfirmed:
                attempts.append("refused")
            else:
                attempts.append("saved")
    controller.subscribe(listener)
    def operation():
        raise OwnershipUnconfirmed("Owned child release is unproven")
    controller._submit(reviewed.project, "inventory", operation)
    wait(controller)
    assert attempts == ["refused"] and not lease.closed


@pytest.mark.parametrize("review", ["quality", "spatial"])
@pytest.mark.parametrize("close_fails", [False, True])
def test_short_review_confirmation_is_published_only_after_successful_lease_close(reviewed, controller, monkeypatch, review, close_fails):
    lease = SimpleNamespace(closed=False, closes=0)
    def close():
        lease.closes += 1
        if close_fails and lease.closes == 1:
            raise OSError("lease close failed")
        lease.closed = True
    lease.close = close
    monkeypatch.setattr(controller, "_acquire_project", lambda *a, **kw: lease)
    events = []
    controller.subscribe(lambda event: events.append((event, lease.closed)))
    token = reviewed.store.read(review)["assessment_hash"]
    def confirm():
        if review == "quality":
            controller.apply_image_culling(reviewed.project, token, [], "operator")
        else:
            controller.confirm_spatial_review(reviewed.project, token, "operator")
    if close_fails:
        with pytest.raises(OwnershipUnconfirmed):
            confirm()
        assert not any(event.get("ownership_released") is True for event, _ in events)
        assert events[-1][0]["state"] == "ownership_unconfirmed"
        assert controller._project_lease is lease and controller._ownership_unconfirmed
    else:
        confirm()
        assert events and all(closed for _, closed in events)
        assert events[-1][0]["state"] == ("quality_confirmed" if review == "quality" else "selection_confirmed")


def test_failed_short_mutation_discards_queued_confirmation(reviewed, controller, monkeypatch):
    from modules.project_controller import _project_mutation
    lease = SimpleNamespace(closed=False)
    lease.close = lambda: setattr(lease, "closed", True)
    monkeypatch.setattr(controller, "_acquire_project", lambda *a, **kw: lease)
    events = []
    controller.subscribe(events.append)
    @_project_mutation
    def fails(self, project):
        self._emit("state", state="quality_confirmed", ownership_released=True)
        assert not events
        raise ValueError("post-confirmation mutation failed")
    with pytest.raises(ValueError, match="post-confirmation"):
        fails(controller, reviewed.project)
    assert not events and lease.closed and controller._project_lease is None


def test_short_mutation_terminal_listener_can_save_after_close(reviewed, controller, monkeypatch):
    leases = []
    def acquire(*a, **kw):
        lease = SimpleNamespace(closed=False)
        lease.close = lambda: setattr(lease, "closed", True)
        leases.append(lease)
        return lease
    monkeypatch.setattr(controller, "_acquire_project", acquire)
    saved = []
    def listener(event):
        if event.get("state") == "quality_confirmed":
            saved.append(leases[0].closed)
            controller.save_project(reviewed.project)
            saved.append(leases[-1].closed)
    controller.subscribe(listener)
    controller.apply_image_culling(reviewed.project, reviewed.store.read("quality")["assessment_hash"], [], "operator")
    assert saved == [True, True] and len(leases) == 2
    assert controller._project_lease is None


def test_reentrant_events_reach_all_listeners_in_monotonic_order(controller):
    received = []
    def retry(event):
        if event.get("state") == "review_ready":
            controller._emit("state", state="running", ownership_released=False)
    controller.subscribe(retry)
    controller.subscribe(received.append)
    controller._emit("state", state="review_ready", ownership_released=True)
    assert [event["state"] for event in received] == ["review_ready", "running"]
    assert [event["sequence"] for event in received] == sorted(event["sequence"] for event in received)


def test_running_listener_cannot_reenter_before_future_is_assigned(reviewed, controller, monkeypatch):
    leases = []
    def acquire(*a, **kw):
        lease = SimpleNamespace(closed=False)
        lease.close = lambda: setattr(lease, "closed", True)
        leases.append(lease)
        return lease
    monkeypatch.setattr(controller, "_acquire_project", acquire)
    attempts = []
    def listener(event):
        if event.get("state") == "running" and not attempts:
            attempts.append("attempted")
            try:
                controller.save_project(reviewed.project)
            except ValueError:
                attempts.append("refused")
            else:
                attempts.append("saved")
    controller.subscribe(listener)
    controller._submit(reviewed.project, "inventory", lambda: None)
    wait(controller)
    assert attempts == ["attempted", "refused"] and len(leases) == 1


def test_reopen_hydration_has_no_writes_and_preserves_confirmations(reviewed, controller):
    p = reviewed.project
    controller.confirm_spatial_review(p, reviewed.store.read("spatial")["assessment_hash"], "operator")
    before = snapshot(p.root)
    loaded = ProjectDocument.load(p.path)
    events = controller.load_project_state(loaded)
    assert snapshot(p.root) == before
    assert any(event.get("state") == "selection_confirmed" for event in events)


@pytest.mark.parametrize("review", ["inventory", "quality", "spatial"])
def test_batch_refuses_unapproved_review_before_executor(reviewed, controller, monkeypatch, review):
    store = reviewed.store
    store.put(review, store.read(review)["payload"])
    reached = []
    monkeypatch.setattr(controller, "_execute_stage", lambda *args: reached.append(args))
    with pytest.raises(ValueError, match="confirmed"):
        controller.start(reviewed.project, "batch")
    assert reached == []
    assert controller._future is None


def test_culling_edit_revokes_density_and_batch(reviewed, controller):
    store = reviewed.store
    controller.apply_image_culling(reviewed.project, store.read("quality")["assessment_hash"],
                                   [str(reviewed.photos[1])], "operator")
    assert store.require_approved("quality")["payload"]["excluded_paths"] == [str(reviewed.photos[1])]
    with pytest.raises(ValueError, match="confirmed"):
        controller.start(reviewed.project, "batch")


def test_inventory_decision_persists_mask_exclusion_and_revokes_batch(reviewed, controller):
    store = reviewed.store
    controller.set_inventory_decision(reviewed.project, str(reviewed.photos[1]), False, "obscured")
    items = store.inventory()
    assert all(not item.included for item in items
               if item.path == str(reviewed.photos[1]) or item.mask_for == str(reviewed.photos[1]))
    with pytest.raises(ValueError, match="confirmed"):
        controller.start(reviewed.project, "batch")
    assert store.read("inventory")["payload"]["decisions"]


def test_outside_window_cannot_be_included(reviewed, controller):
    with pytest.raises(ValueError):
        controller.set_inventory_decision(reviewed.project, str(reviewed.outside), True, "try override")


@pytest.mark.parametrize("invalidator", ["georeference", "settings"])
def test_invalidated_quality_cannot_be_resurrected_by_apply(reviewed, controller, invalidator):
    store = reviewed.store
    old_hash = store.read("quality")["assessment_hash"]
    if invalidator == "georeference":
        store.put("georeference", {"new_evidence": True}, invalidate=("quality", "spatial", "selection"))
    else:
        controller.apply_settings(reviewed.project, "navigation", {"max_match_seconds": 1.0, "clock_offset_seconds": 3.0})
    with pytest.raises(ValueError):
        controller.apply_image_culling(reviewed.project, old_hash, [], "operator")
    assert not store.read("quality")["approval"]


def test_spatial_confirmation_rechecks_navigation_binding(reviewed, controller):
    # The old plot identifies navigation aaaa; replacing current navigation must
    # never approve that plot, even if both files are structurally valid.
    reviewed.store.put("navigation", {"sha256": "b" * 64})
    with pytest.raises(ValueError):
        controller.confirm_spatial_review(reviewed.project,
            reviewed.store.read("spatial")["assessment_hash"], "operator")


def test_source_addition_refuses_confirmation(reviewed, controller):
    (reviewed.source / "new_delivery.txt").write_text("new input", encoding="utf-8")
    with pytest.raises(ValueError, match="Source tree changed"):
        controller.confirm_spatial_review(reviewed.project,
            reviewed.store.read("spatial")["assessment_hash"], "operator")


def test_foreign_namespace_cannot_be_saved_or_started(reviewed, controller, monkeypatch):
    other = ProjectDocument.create("NA999", "H9998", reviewed.project.root, [reviewed.source])
    before = snapshot(other.root)
    reached = []
    monkeypatch.setattr(controller, "_run_stage", lambda *args: reached.append(args))
    with pytest.raises(ValueError, match="different project"):
        controller.save_project(other)
    with pytest.raises(ValueError, match="different project"):
        controller.start(other, "navigation")
    assert snapshot(other.root) == before
    assert not reached


@pytest.mark.parametrize("schema", [None, 0, 2, "1"])
def test_unknown_owner_marker_schema_is_refused(reviewed, controller, schema):
    marker = reviewed.project.root / ".rovscan-owner.json"
    owner = json.loads(marker.read_text(encoding="utf-8"))
    owner["schema"] = schema
    write_json(marker, owner)
    with pytest.raises(ValueError):
        controller.save_project(reviewed.project)


class FakeProcess:
    """A handle only: no real process, thread or OS instance is launched."""
    pid = 987654321

    def __init__(self, returncode=0):
        self.returncode = returncode
        self.running = True
        self.waited = False
        self.terminated = False

    def poll(self):
        return None if self.running else self.returncode

    def wait(self, timeout=None):
        self.waited = True
        self.running = False
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.running = False


def record(tmp_path, *, realityscan=False):
    runtime = tmp_path / "proc/tmp/parent-test"
    return {"stage": "Align" if realityscan else "Navigation", "argv": ["mock-only"],
            "needs_realityscan": realityscan, "env": {"RS_RUN_ID": "parent-test",
            "RS_EVENT_FILE": str(runtime / "events.jsonl"), "RS_RUNTIME_ROOT": str(runtime),
            "RS_CONTROL_FILE": str(runtime / "control.json")}}


def test_abort_before_launch_never_creates_child(tmp_path, monkeypatch):
    control = ExecutionControl()
    control.request_cancel("abort_current")
    def unexpected(*args, **kwargs):
        pytest.fail("Cancellation pending before launch must prevent Popen")
    monkeypatch.setattr(rs.subprocess, "Popen", unexpected)
    assert rs.execute_commands([record(tmp_path)], tmp_path / "agent", "", control=control) == 130


@pytest.mark.parametrize("error_type", [OSError, ValueError, RuntimeError])
def test_post_launch_state_failure_does_not_release_live_child(tmp_path, monkeypatch, controller, error_type):
    project = ProjectDocument.create("NA999", "H9999", tmp_path / "project")
    child = FakeProcess()
    monkeypatch.setattr(rs.subprocess, "Popen", lambda *args, **kwargs: child)
    original = rs._write_json
    injected = False
    def failing_state(path, data):
        nonlocal injected
        if data.get("pid") == child.pid and not injected:
            injected = True
            raise error_type("injected post-launch instrumentation failure")
        return original(path, data)
    monkeypatch.setattr(rs, "_write_json", failing_state)
    events = []
    controller.subscribe(events.append)
    controller._submit(project, "navigation", lambda: rs.execute_commands(
        [record(tmp_path)], project.resolve_path("proc/_agent"), "", control=controller._control))
    wait(controller)
    released = [event for event in events if event.get("ownership_released") is True]
    assert not (child.running and released), f"Live child falsely released: {released}"
    assert child.waited or controller._ownership_unconfirmed


def test_interrupted_launch_without_handle_retains_ownership(tmp_path, monkeypatch, controller):
    project = ProjectDocument.create("NA999", "H9999", tmp_path / "project")
    def interrupted(*args, **kwargs):
        raise KeyboardInterrupt()
    monkeypatch.setattr(rs.subprocess, "Popen", interrupted)
    events = []
    controller.subscribe(events.append)
    controller._submit(project, "align", lambda: rs.execute_commands(
        [record(tmp_path, realityscan=True)], project.resolve_path("proc/_agent"), "", control=controller._control))
    wait(controller)
    assert controller._ownership_unconfirmed
    assert not any(e.get("ownership_released") is True for e in events)
    with pytest.raises(OwnershipUnconfirmed):
        controller.start(project, "navigation")


def test_rs_release_requires_instrumentation_when_rs_is_declared():
    with pytest.raises(OwnershipUnconfirmed):
        require_runtime_release({"needs_realityscan": True, "env": {}})


@pytest.mark.parametrize("events", [[], [{"parent_run_id": "foreign", "run_id": "child", "data": {"ownership_retained": False}}],
    [{"parent_run_id": "parent-test", "run_id": "child", "data": {"ownership_retained": True}}]])
def test_missing_foreign_or_retained_runtime_evidence_refuses_release(tmp_path, events):
    command = record(tmp_path, realityscan=True)
    path = Path(command["env"]["RS_EVENT_FILE"])
    path.parent.mkdir(parents=True)
    path.write_text("".join(json.dumps(event) + "\n" for event in events), encoding="utf-8")
    with pytest.raises(OwnershipUnconfirmed):
        require_runtime_release(command)


def test_staging_has_exact_curated_images_masks_and_precision_preserving_log(reviewed):
    store, project = reviewed.store, reviewed.project
    quality = store.read("quality")["payload"]
    quality["excluded_paths"] = [str(reviewed.photos[1])]
    value = store.put("quality", quality)
    store.approve("quality", value["assessment_hash"], "operator")
    spatial = store.read("spatial")["payload"]
    spatial["quality_selection_hash"] = digest(quality)
    value = store.put("spatial", spatial)
    store.approve("spatial", value["assessment_hash"], "operator")
    log = project.resolve_path("proc/georeferenced/flight_log_18T_UTM.txt")
    log.parent.mkdir(parents=True)
    with log.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, delimiter=";")
        writer.writerow(["filename", *[f"v{i}" for i in range(13)]])
        for image in [*reviewed.photos, reviewed.outside]:
            writer.writerow([image.name, "500000.123456789", "4000000.987654321", *["1"] * 11])
    before = source_fingerprint(reviewed.source)
    manifest, manifest_path = materialize_selection(project, log, expected_epsg=32618, reserve_bytes=0)
    root = Path(manifest["images_root"])
    retained = [reviewed.photos[0], reviewed.photos[2]]
    assert root.is_relative_to(project.root / "proc/selections")
    expected = {image.name for image in retained} | {image.name + ".mask.png" for image in retained}
    if Path(manifest["flight_log"]).is_relative_to(root):
        expected.add(log.name)
    assert {path.name for path in root.rglob("*") if path.is_file()} == expected
    for image in retained:
        target = next(root.rglob(image.name))
        assert file_hash(target) == file_hash(image)
        assert target.stat().st_nlink == 1
    selected_log = Path(manifest["flight_log"])
    with selected_log.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.reader(stream, delimiter=";"))
    assert {row[0] for row in rows[1:]} == {image.name for image in retained}
    assert all(row[1:3] == ["500000.123456789", "4000000.987654321"] for row in rows[1:])
    assert len(manifest["masks"]) == 2
    assert json.loads(manifest_path.read_text())["selection_hash"] == manifest["selection_hash"]
    assert source_fingerprint(reviewed.source) == before
    for item in reviewed.items:
        assert file_hash(project.root / "raw/imagery" / item.relative_path) == item.sha256
    # A restart must resume the exact approved selection, including its generated
    # log; it must neither treat that log as contamination nor rewrite originals.
    again, _ = materialize_selection(project, log, expected_epsg=32618, reserve_bytes=0)
    assert again == manifest


def configure(project, controller):
    """Use the production schema, preserving nested camera keys as the UI does."""
    blocks = {}
    for field in controller.settings_schema(project):
        target = blocks.setdefault(field["block"], {})
        parts = field["key"].split(".")
        for part in parts[:-1]:
            target = target.setdefault(part, {})
        target[parts[-1]] = field["default"]
    blocks["operating"]["reserve_gib"] = 1
    blocks["budget"].update(expected_hours=1, memory_peak_gb=1, disk_delta_gb=1)
    for block, values in blocks.items():
        project.set_settings(block, values)
    for block in blocks:
        project.approve_settings(block, "fixture operator")
    return blocks


def navigation_file(project, folder="original"):
    from modules.navigation_quality import POSE_COLUMNS
    from pyproj import Transformer
    x, y = Transformer.from_crs(4326, 32618, always_xy=True).transform(-75.0, 36.0)
    target = project.resolve_path(f"proc/navigation/{folder}/NA999_H9999_final_datatable.tsv")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, delimiter="\t")
        writer.writerow(["Timestamp", "utm_zone", *POSE_COLUMNS])
        for index in range(3):
            writer.writerow([f"2025-05-24T01:00:0{index}Z", "18N", x, y, -100, 0, 0, 0, 36, -75])
    return target


def test_navigation_runs_with_only_applicable_settings_approved(reviewed, controller, monkeypatch):
    project = reviewed.project
    blocks = configure(project, controller)
    # Leave later scientific settings explicitly unapproved.
    project.set_settings("science", {**blocks["science"], "min_component_size": 51})
    for block in ("operating", "navigation"):
        project.approve_settings(block, "operator")
    finish(project, "inventory")
    calls = []
    def executor(commands, *args, **kwargs):
        calls.extend(commands)
        nav = navigation_file(project, "mock-produced")
        write_json(nav.parent / "navigation_result.json", {"navigation": str(nav)})
        return 0
    monkeypatch.setattr(rs, "execute_commands", executor)
    controller.start(project, "navigation")
    wait(controller)
    assert len(calls) == 1
    assert calls[0]["needs_realityscan"] is False
    assert project.to_dict()["stages"]["navigation"]["state"] == "succeeded"
    assert all(project.resolve_path(output["path"]).is_relative_to(project.root)
               for output in project.to_dict()["outputs"])


@pytest.mark.parametrize("block", ["operating", "navigation"])
def test_navigation_rejects_unreviewed_setting_before_executor(reviewed, controller, monkeypatch, block):
    project = reviewed.project
    blocks = configure(project, controller)
    project.set_settings(block, {**blocks[block], "unreviewed_change": True})
    finish(project, "inventory")
    calls = []
    monkeypatch.setattr(rs, "execute_commands", lambda *args, **kwargs: calls.append(args))
    events = []
    controller.subscribe(events.append)
    controller.start(project, "navigation")
    wait(controller)
    assert not calls
    assert any("approval" in event.get("message", "").lower() for event in events)


@pytest.fixture
def processing_ready(reviewed, controller):
    from modules.project_controller import GEO_SETTINGS_BLOCKS
    from modules.navigation_quality import assess_navigation
    project, store = reviewed.project, reviewed.store
    # Native intake retires delivered masks; legacy staging fixtures above still
    # exercise mask preservation independently of the new desktop policy.
    quality = store.read("quality")["payload"]
    spatial = store.read("spatial")["payload"]
    value = store.save_inventory(store.inventory(), source_mask_policy="ignore_existing")
    store.approve("inventory", value["assessment_hash"], "operator")
    token = approval_token(store.inventory(approved=True))
    quality["input_inventory_hash"] = token
    value = store.put("quality", quality)
    store.approve("quality", value["assessment_hash"], "operator")
    spatial.update(input_inventory_hash=token, quality_selection_hash=digest(quality))
    store.put("spatial", spatial)
    configure(project, controller)
    for stage in ("inventory", "navigation", "georeference", "preprocess"):
        finish(project, stage)
    nav = navigation_file(project)
    nav_evidence = assess_navigation(nav, "NA999", "H9999")
    nav_evidence["relative_path"] = nav.relative_to(project.root).as_posix()
    store.put("navigation", nav_evidence)
    log = project.resolve_path("proc/geo/flight_log_18T_UTM.txt")
    log.parent.mkdir(parents=True)
    with log.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, delimiter=";")
        writer.writerow(["filename", *[f"v{i}" for i in range(13)]])
        for photo in reviewed.photos:
            writer.writerow([photo.name, *["1"] * 13])
    store.put("georeference", {"flight_log": log.relative_to(project.root).as_posix(),
        "sha256": file_hash(log), "epsg": 32618,
        "settings_scope": list(GEO_SETTINGS_BLOCKS),
        "settings_hash": project.settings_signature(GEO_SETTINGS_BLOCKS),
        "navigation_sha256": nav_evidence["sha256"],
        "input_inventory_hash": approval_token(store.inventory(approved=True))})
    spatial = store.read("spatial")["payload"]
    spatial["navigation_sha256"] = nav_evidence["sha256"]
    value = store.put("spatial", spatial)
    store.approve("spatial", value["assessment_hash"], "operator")
    project.save()
    return reviewed


def test_public_batch_uses_project_selection_and_workflow_namespace(processing_ready, controller, monkeypatch):
    from modules import verify
    p = processing_ready.project
    plans = []
    observed = []
    controller.subscribe(observed.append)
    def executor(commands, agent_ws, charter_path, **kwargs):
        plans.append((commands, agent_ws, charter_path, kwargs["session"]))
        return 0
    monkeypatch.setattr(rs, "execute_commands", executor)
    monkeypatch.setattr(verify, "verify_workspace", lambda *args, **kwargs: {"verdict": "ok"})
    controller.start(p, "batch")
    wait(controller)
    assert plans, [event for event in observed if event["kind"] in ("error", "preflight")]
    commands, agent_ws, charter_path, session = plans[0]
    assert Path(session.results_root).is_relative_to(p.root / "proc/workflows")
    assert Path(agent_ws).is_relative_to(Path(session.results_root))
    assert Path(charter_path).is_relative_to(Path(session.results_root))
    assert all(not command["needs_realityscan"] for command in commands)
    for command in commands:
        env = command["env"]
        assert Path(env["RS_CAMERA_PRIORS_FILE"]).is_relative_to(p.root / "metadata/priors")
        assert Path(env["RS_SETTINGS_PATH"]).is_relative_to(p.root / "proc/tmp")
    assert p.to_dict()["stages"]["batch"]["state"] == "succeeded"


def test_batch_rejects_navigation_replacement_after_density_confirmation(processing_ready, controller, monkeypatch):
    from modules import verify
    data = processing_ready
    nav = navigation_file(data.project, "replacement")
    # Same poses, new authoritative navigation generation: updating one position
    # and preserving valid lat/lon forces a different content hash and a new plot.
    text = nav.read_text(encoding="utf-8").replace("-100", "-101")
    nav.write_text(text, encoding="utf-8")
    from modules.navigation_quality import assess_navigation
    value = assess_navigation(nav, "NA999", "H9999")
    value["relative_path"] = nav.relative_to(data.project.root).as_posix()
    data.store.put("navigation", value)
    calls = []
    monkeypatch.setattr(rs, "execute_commands", lambda *args, **kwargs: calls.append(args) or 0)
    monkeypatch.setattr(verify, "verify_workspace", lambda *args, **kwargs: {"verdict": "ok"})
    try:
        controller.start(data.project, "batch")
    except ValueError:
        pass
    if controller._future:
        wait(controller)
    assert calls == [], "Batch executed with density approval bound to obsolete navigation"


def test_initial_save_failure_does_not_leave_nonstarted_stage_running(reviewed, controller, monkeypatch):
    project = reviewed.project
    configure(project, controller)
    finish(project, "inventory")
    calls = []
    monkeypatch.setattr(controller, "_execute_stage", lambda *args: calls.append(args))
    def failed_save(*args, **kwargs):
        raise OSError("fixture disk unavailable before child launch")
    monkeypatch.setattr(project, "save", failed_save)
    controller.start(project, "navigation")
    wait(controller)
    assert not calls
    assert project.to_dict()["stages"]["navigation"]["state"] != "running"


@pytest.mark.parametrize("mutation", ["settings", "inventory_confirmation", "spatial_confirmation", "quality_culling"])
def test_lost_root_ownership_refuses_review_mutations(reviewed, controller, mutation):
    p, store = reviewed.project, reviewed.store
    foreign = ProjectDocument.create("NA999", "H9998", p.root)
    marker = p.root / ".rovscan-owner.json"
    owner = json.loads(marker.read_text(encoding="utf-8"))
    owner["project_id"] = foreign.project_id
    write_json(marker, owner)
    before, document_before = snapshot(p.root), p.to_dict()
    with pytest.raises(ValueError):
        if mutation == "settings":
            controller.apply_settings(p, "navigation", {"max_match_seconds": 1.0, "clock_offset_seconds": 0.0})
        elif mutation == "inventory_confirmation":
            controller.confirm_inventory(p, approval_token(store.inventory()), "operator")
        elif mutation == "spatial_confirmation":
            controller.confirm_spatial_review(p, store.read("spatial")["assessment_hash"], "operator")
        else:
            controller.apply_image_culling(p, store.read("quality")["assessment_hash"], [], "operator")
    assert snapshot(p.root) == before
    assert p.to_dict() == document_before


@pytest.mark.parametrize("review", ["quality", "spatial"])
def test_apply_refuses_payload_changed_behind_assessment_hash(reviewed, controller, review):
    store = reviewed.store
    stale = store.read(review)
    old_hash = stale["assessment_hash"]
    if review == "quality":
        stale["payload"]["tolerances"] = {"unreviewed": 999}
    else:
        stale["payload"]["assessment"]["points"][0]["x"] += 1000
    write_json(store.path(review), stale)  # Simulate a stale/corrupt on-disk sidecar.
    with pytest.raises(ValueError):
        if review == "quality":
            controller.apply_image_culling(reviewed.project, old_hash, [], "operator")
        else:
            controller.apply_spatial_culling(reviewed.project, old_hash, [], "operator")
    assert store.read(review) == stale


@pytest.mark.parametrize("stale", ["inventory_hash", "settings_hash", "source_addition", "navigation_bytes"])
def test_batch_rechecks_cached_georeference_and_inputs(processing_ready, controller, monkeypatch, stale):
    from modules import verify
    p, store = processing_ready.project, processing_ready.store
    if stale in ("inventory_hash", "settings_hash"):
        geo = store.read("georeference")["payload"]
        geo["input_inventory_hash" if stale == "inventory_hash" else "settings_hash"] = "0" * 64
        store.put("georeference", geo)
    elif stale == "source_addition":
        (processing_ready.source / "late_nav_delivery.txt").write_text("new content", encoding="utf-8")
    else:
        nav = p.resolve_path(store.read("navigation")["payload"]["relative_path"])
        nav.write_text(nav.read_text().replace("-100", "-102"), encoding="utf-8")
    calls = []
    monkeypatch.setattr(rs, "execute_commands", lambda *args, **kwargs: calls.append(args) or 0)
    monkeypatch.setattr(verify, "verify_workspace", lambda *args, **kwargs: {"verdict": "ok"})
    try:
        controller.start(p, "batch")
    except ValueError:
        pass
    if controller._future:
        wait(controller)
    assert not calls, f"Batch executor accepted stale {stale} evidence"


@pytest.mark.parametrize("failure", ["repeated_monitor_error", "abort_state_write_error"])
def test_secondary_monitor_failure_cannot_release_unconfirmed_owner(tmp_path, controller, monkeypatch, failure):
    p = ProjectDocument.create("NA999", "H9999", tmp_path / "project")
    child = FakeProcess()
    def failed_wait(timeout=None):
        raise OSError("cannot monitor child handle")
    if failure == "repeated_monitor_error":
        monkeypatch.setattr(child, "wait", failed_wait)
        monkeypatch.setattr(rs.subprocess, "Popen", lambda *args, **kwargs: child)
    else:
        def interrupted(*args, **kwargs):
            raise KeyboardInterrupt()
        monkeypatch.setattr(rs.subprocess, "Popen", interrupted)
        original = rs._write_json
        def failed_abort_record(path, value):
            if value.get("status") == "cancel_requested":
                raise OSError("abort instrumentation unavailable")
            original(path, value)
        monkeypatch.setattr(rs, "_write_json", failed_abort_record)
    events = []
    controller.subscribe(events.append)
    controller._submit(p, "navigation", lambda: rs.execute_commands([record(tmp_path)],
        p.resolve_path("proc/_agent"), "", control=controller._control))
    wait(controller)
    assert not any(event.get("ownership_released") is True for event in events), events
    assert controller._ownership_unconfirmed


def test_second_controller_cannot_rescan_live_project(reviewed, controller, monkeypatch):
    from integrations.rovdataconcat import navigation
    p = reviewed.project
    configure(p, controller)
    finish(p, "inventory")
    entered, release = threading.Event(), threading.Event()
    def held_leaf(*args):
        entered.set()
        if not release.wait(10):
            raise RuntimeError("fixture worker was not released")
        return {"fixture": "completed"}
    monkeypatch.setattr(controller, "_execute_stage", held_leaf)
    monkeypatch.setattr(navigation, "source_window", lambda *args: {
        "launch_utc": "2025-05-24T00:00:00Z", "recovery_utc": "2025-05-24T02:00:00Z"})
    controller.start(p, "navigation")
    other = ProjectController()
    try:
        assert entered.wait(5)
        reopened = ProjectDocument.load(p.path)
        original = reviewed.store.read("inventory")
        try:
            other.start(reopened, "inventory")
        except (ValueError, OwnershipUnconfirmed):
            pass
        if other._future:
            wait(other)
        assert reviewed.store.read("inventory") == original, (
            "Another controller replaced approved inventory during a persisted live navigation attempt")
    finally:
        release.set()
        wait(controller)
        other._pool.shutdown(wait=True)


def test_controller_inventory_resumes_without_sensor_scan_or_approval(reviewed, controller, monkeypatch):
    from integrations.rovdataconcat import navigation
    from modules import inventory_checkpoint
    project = reviewed.project
    monkeypatch.setattr(navigation, "source_window", lambda *args: {
        "launch_utc": "2025-05-24T00:00:00Z", "recovery_utc": "2025-05-24T02:00:00Z"})
    def forbidden(*args, **kwargs):
        raise AssertionError("inventory must not scan all navigation records")
    monkeypatch.setattr(navigation, "source_plan", forbidden)
    events = []
    controller.subscribe(events.append)
    controller.scan_inventory(project)
    wait(controller)
    assert not [e for e in events if e.get("type") == "error"], events
    first = reviewed.store.inventory()
    assert first.hashing_complete and first.verification_complete
    assert not reviewed.store.read("inventory")["approval"]
    checkpoint = project.resolve_path("proc/tmp/inventory_checkpoint")
    assert (checkpoint / "state.json").is_file()
    assert project.resolve_path("metadata/navigation_window.json").is_file()
    assert not project.resolve_path("metadata/navigation_plan.json").exists()
    # The second scan must exercise the same persistent checkpoint and remain
    # unapproved; a cache hit never transfers an old user's review decision.
    controller.scan_inventory(project)
    wait(controller)
    second = reviewed.store.inventory()
    assert second.hashing_complete and second.verification_complete
    assert approval_token(first) == approval_token(second)
    assert not reviewed.store.read("inventory")["approval"]


@pytest.mark.parametrize("event", [[], "unexpected string", {"parent_run_id": "parent-test", "run_id": [], "data": {}},
    {"parent_run_id": "parent-test", "run_id": "child", "data": None}])
def test_malformed_runtime_structure_is_unconfirmed_not_generic_failure(tmp_path, event):
    command = record(tmp_path, realityscan=True)
    path = Path(command["env"]["RS_EVENT_FILE"])
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(event) + "\n", encoding="utf-8")
    with pytest.raises(OwnershipUnconfirmed):
        require_runtime_release(command)


@pytest.mark.parametrize("mode", ["after_step", "abort_current"])
def test_stop_uses_owned_control_channel_and_prevents_next_command(tmp_path, monkeypatch, mode):
    control = ExecutionControl()
    command = record(tmp_path, realityscan=True)
    child = FakeProcess()
    starts = []
    def fake_launch(*args, **kwargs):
        starts.append(args)
        control.request_cancel(mode)
        return child
    def fake_wait(timeout=None):
        control_path = Path(command["env"]["RS_CONTROL_FILE"])
        value = json.loads(control_path.read_text(encoding="utf-8"))
        assert value["run_id"] == "parent-test"
        assert value["mode"] == mode
        events = Path(command["env"]["RS_EVENT_FILE"])
        events.write_text("".join(json.dumps({"parent_run_id": "parent-test", "run_id": "child",
            "sequence": sequence, "kind": kind, "data": data}) + "\n"
            for sequence, kind, data in [(1, "prepared", {}), (2, "done", {"ownership_retained": False})]),
            encoding="utf-8")
        child.running = False
        child.waited = True
        return 0
    monkeypatch.setattr(rs.subprocess, "Popen", fake_launch)
    monkeypatch.setattr(child, "wait", fake_wait)
    assert rs.execute_commands([command, command], tmp_path / "agent", "", control=control) == 130
    assert len(starts) == 1
    assert child.waited and not child.terminated


@pytest.fixture
def recoverable(tmp_path, controller):
    p = ProjectDocument.create("NA999", "H9999", tmp_path / "project")
    claim_root(p)
    p.create_layout()
    for stage in ("inventory", "navigation", "georeference", "preprocess", "batch"):
        finish(p, stage)
    attempt = p.start_stage("align", required_blocks=[])
    p.save()
    command = record(p.resolve_path("proc/tmp/proof"), realityscan=True)
    events = Path(command["env"]["RS_EVENT_FILE"])
    events.parent.mkdir(parents=True)
    events.write_text("".join(json.dumps({"parent_run_id": "parent-test", "run_id": "child",
        "sequence": sequence, "kind": kind, "data": data}) + "\n"
        for sequence, kind, data in [(1, "prepared", {}), (2, "done", {"ownership_retained": False})]), encoding="utf-8")
    workspace = p.resolve_path("proc/workflow/_agent")
    label = controller._record_execution_plan(p, "align", {"commands": [command]}, workspace)
    state_path = workspace / "RUN_STATE.json"
    write_json(state_path, {"label": label, "status": "done", "returncode": 0, "ownership_released": True})
    plan_path = next(p.resolve_path("metadata/plans").glob("*.json"))
    return SimpleNamespace(project=p, attempt=attempt, plan_path=plan_path, state_path=state_path,
                           events=events, command=command)


def test_real_recovery_requires_proof_not_manual_core_assertion(tmp_path, controller):
    p = ProjectDocument.create("NA999", "H9999", tmp_path / "project")
    p.start_stage("inventory", required_blocks=[])
    p.save()
    before = p.to_dict()
    with pytest.raises(OwnershipUnconfirmed):
        controller.recover_project(p)
    assert p.to_dict() == before
    assert ProjectDocument.load(p.path).to_dict() == before


def test_real_recovery_persists_attributable_terminal_attempt(recoverable, controller):
    p = recoverable.project
    result = controller.recover_project(p)
    assert result["ownership_released"] is True
    assert result["recovered_stages"] == ["align"]
    assert p.to_dict()["stages"]["align"]["state"] == "interrupted"
    assert ProjectDocument.load(p.path).to_dict() == p.to_dict()
    assert controller._project_lease is None


@pytest.mark.parametrize("status,code", [("running", 0), ("done", None), ("done", True), ("done", "0")])
def test_real_recovery_refuses_nonterminal_or_malformed_exit(recoverable, controller, status, code):
    case = recoverable
    state = json.loads(case.state_path.read_text(encoding="utf-8"))
    state.update(status=status, returncode=code)
    write_json(case.state_path, state)
    before = case.project.to_dict()
    with pytest.raises(OwnershipUnconfirmed):
        controller.recover_project(case.project)
    assert case.project.to_dict() == before


@pytest.mark.parametrize("mutation", ["foreign_project", "foreign_attempt", "foreign_label", "missing_release", "empty_commands", "list_plan", "non_rs_align"])
def test_real_recovery_refuses_unattributable_or_incomplete_plan(recoverable, controller, mutation):
    case = recoverable
    plan = json.loads(case.plan_path.read_text(encoding="utf-8"))
    if mutation == "foreign_project":
        plan["project_id"] = "foreign-project"
    elif mutation == "foreign_attempt":
        plan["project_attempt_id"] = "foreign-attempt"
    elif mutation == "foreign_label":
        plan["execution_label"] = "foreign-label"
    elif mutation == "empty_commands":
        plan["commands"] = []
    elif mutation == "list_plan":
        plan = []
    elif mutation == "non_rs_align":
        plan["commands"][0]["needs_realityscan"] = False
        case.events.write_text("", encoding="utf-8")
    else:
        case.events.write_text("", encoding="utf-8")
    write_json(case.plan_path, plan)
    before = case.project.to_dict()
    with pytest.raises(OwnershipUnconfirmed):
        controller.recover_project(case.project)
    assert case.project.to_dict() == before


def test_real_recovery_cannot_release_another_windows_held_project(recoverable, controller):
    from modules.realityscan_interface.realityscan_cli import _OSLock
    case = recoverable
    before = case.project.to_dict()
    lease = _OSLock(str(case.project.root / ".rovscan-operation.lock"))
    try:
        with pytest.raises(OwnershipUnconfirmed):
            controller.recover_project(case.project)
        assert case.project.to_dict() == before
    finally:
        lease.close()


def test_real_recovery_cannot_adopt_a_foreign_namespace(recoverable, controller):
    p = recoverable.project
    owner = json.loads((p.root / ".rovscan-owner.json").read_text(encoding="utf-8"))
    owner["project_id"] = "foreign-project"
    write_json(p.root / ".rovscan-owner.json", owner)
    before = p.to_dict()
    with pytest.raises((ValueError, OwnershipUnconfirmed)):
        controller.recover_project(p)
    assert p.to_dict() == before


def test_actual_track_segments_preserves_exact_gap_boundary_and_float64():
    import pandas as pd
    from modules.project_controller import track_segments
    start = pd.Timestamp("2025-05-24T01:00:00Z")
    coordinates = [[500000.123456789, 4000000.987654321],
                   [500001.123456789, 4000001.987654321],
                   [500002.123456789, 4000002.987654321]]
    frame = pd.DataFrame({
        "Timestamp": [start, start + pd.Timedelta(seconds=2),
                      start + pd.Timedelta(seconds=4, microseconds=1)],
        "kalman_x": [point[0] for point in coordinates],
        "kalman_y": [point[1] for point in coordinates],
    })
    assert track_segments(frame, max_gap_seconds=2) == [coordinates[:2], coordinates[2:]]


@pytest.mark.parametrize("seconds", [(1, 1), (2, 1)], ids=["duplicate", "reversed"])
def test_actual_track_segments_refuses_unordered_timestamps(seconds):
    import pandas as pd
    from modules.project_controller import track_segments
    start = pd.Timestamp("2025-05-24T01:00:00Z")
    frame = pd.DataFrame({"Timestamp": [start + pd.Timedelta(seconds=value) for value in seconds],
                          "kalman_x": [500000.0, 500001.0], "kalman_y": [4000000.0, 4000001.0]})
    with pytest.raises(ValueError, match="strictly increasing"):
        track_segments(frame)


@pytest.fixture
def nonterminal_recovery(recoverable):
    case = recoverable
    plan = json.loads(case.plan_path.read_text(encoding="utf-8"))
    command = plan["commands"][0]
    state = json.loads(case.state_path.read_text(encoding="utf-8"))
    channel_keys = ("RS_RUN_ID", "RS_RUNTIME_ROOT", "RS_ERRORS_DIR", "RS_CONTROL_FILE", "RS_EVENT_FILE", "RS_INSTANCE", "RS_EXECUTABLE")
    state.update(status="ownership_unconfirmed", returncode=None, ownership_released=False,
                 project_id=case.project.project_id, project_attempt_id=case.attempt,
                 stage=command["stage"], needs_realityscan=True, launch_attempted=True,
                 pid=987654321, child_identity={"pid": 987654321, "create_time": 123.0, "executable": "fixture-only"},
                 runtime={key: command["env"].get(key) for key in channel_keys},
                 runtime_event_cursor={"offset": 0, "identity": None})
    write_json(case.state_path, state)
    return case


def test_controller_nonterminal_recovery_passes_exact_binding_to_real_inspector(nonterminal_recovery, controller, monkeypatch):
    from modules import project_runtime
    case = nonterminal_recovery
    state = json.loads(case.state_path.read_text(encoding="utf-8"))
    command = json.loads(case.plan_path.read_text(encoding="utf-8"))["commands"][0]
    calls, identities = [], []
    inspector = project_runtime.inspect_recovery
    def record_inspection(record, saved_state, **bindings):
        calls.append((record, saved_state, bindings))
        return inspector(record, saved_state, **bindings)
    def absent_child(identity):
        identities.append(identity)
        return {"confirmed_not_running": True, "status": "gone"}
    monkeypatch.setattr(project_runtime, "inspect_recovery", record_inspection)
    monkeypatch.setattr(project_runtime, "inspect_owned_process", absent_child)
    result = controller.recover_project(case.project)
    assert result["ownership_released"] is True
    assert calls == [(command, state, {"expected_project_id": case.project.project_id,
                                      "expected_attempt_id": case.attempt})]
    assert identities == [state["child_identity"]]
    assert ProjectDocument.load(case.project.path).to_dict()["stages"]["align"]["state"] == "interrupted"


@pytest.mark.parametrize("mutation", ["state_project", "state_attempt", "command_project", "runtime_channel",
                                     "child_running", "stale_event_cursor", "ambiguous_command"])
def test_controller_nonterminal_recovery_refuses_bad_binding_or_missing_proof(nonterminal_recovery, controller, monkeypatch, mutation):
    from modules import project_runtime
    case = nonterminal_recovery
    state = json.loads(case.state_path.read_text(encoding="utf-8"))
    plan = json.loads(case.plan_path.read_text(encoding="utf-8"))
    if mutation == "state_project":
        state["project_id"] = "another-project"
    elif mutation == "state_attempt":
        state["project_attempt_id"] = "another-attempt"
    elif mutation == "command_project":
        plan["commands"][0]["project_id"] = "another-project"
    elif mutation == "runtime_channel":
        state["runtime"]["RS_RUN_ID"] = "another-runtime"
    elif mutation == "stale_event_cursor":
        state["runtime_event_cursor"]["offset"] = case.events.stat().st_size
    elif mutation == "ambiguous_command":
        plan["commands"].append(dict(plan["commands"][0]))
    write_json(case.state_path, state)
    write_json(case.plan_path, plan)
    monkeypatch.setattr(project_runtime, "inspect_owned_process", lambda identity: {
        "confirmed_not_running": mutation != "child_running",
        "status": "same_process_running" if mutation == "child_running" else "gone"})
    before = case.project.to_dict()
    with pytest.raises(OwnershipUnconfirmed):
        controller.recover_project(case.project)
    assert case.project.to_dict() == before
    assert ProjectDocument.load(case.project.path).to_dict() == before


def test_terminal_recovery_requires_explicit_executor_ownership_release(recoverable, controller):
    case = recoverable
    state = json.loads(case.state_path.read_text(encoding="utf-8"))
    state["ownership_released"] = False
    write_json(case.state_path, state)
    before = case.project.to_dict()
    with pytest.raises(OwnershipUnconfirmed):
        controller.recover_project(case.project)
    assert case.project.to_dict() == before


@pytest.mark.parametrize("stage", ["georeference", "batch"])
def test_forwardflow_approves_only_current_stage_blocks(processing_ready, controller, monkeypatch, stage):
    """Exercise real planning/preflight without submitting work or taking locks."""
    from modules import verify
    from modules.project_workspace import STAGES
    from modules.realityscan_interface import realityscan_cli
    case = processing_ready
    p = case.project
    science = p.to_dict()["settings"]["science"]["values"]
    p.set_settings("science", {**science, "min_component_size": science["min_component_size"] + 1})
    for block in ("align", "budget"):
        values = p.to_dict()["settings"][block]["values"]
        key = "r_min_component_size" if block == "align" else "cache_delta_gb"
        p.set_settings(block, {**values, key: values[key] + 1})
    required = ["operating", "navigation", "cameras", "science", stage]
    for block in required:
        p.approve_settings(block, "operator")
    assert not p.settings_approved()
    assert p.to_dict()["settings"]["align"]["approval"] is None
    assert p.to_dict()["settings"]["budget"]["approval"] is None
    for predecessor in STAGES[:STAGES.index(stage)]:
        finish(p, predecessor)
    if p.to_dict()["stages"][stage]["state"] == "succeeded":
        p.restart_stage(stage, "Exercise current-stage approval requirements")
    calls = []
    def executor(commands, *args, **kwargs):
        calls.extend(commands)
        if stage == "georeference":
            target = Path(kwargs["session"].results_root) / "images/flight_log_18T_UTM.txt"
            with target.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.writer(stream, delimiter=";")
                writer.writerow(["filename", *[f"v{i}" for i in range(13)]])
                for photo in case.photos:
                    writer.writerow([photo.name, *["1"] * 13])
        return 0
    def no_lock(*args, **kwargs):
        pytest.fail("Forwardflow fixture must never acquire an operation or attach lock")
    monkeypatch.setattr(realityscan_cli, "_OSLock", no_lock)
    monkeypatch.setattr(rs, "execute_commands", executor)
    monkeypatch.setattr(verify, "verify_workspace", lambda *args, **kwargs: {"verdict": "ok"})
    controller._run_stage(p, stage)
    assert calls and all(not command["needs_realityscan"] for command in calls)
    assert p.to_dict()["stages"][stage]["state"] == "succeeded"
    assert not p.settings_approved(["align", "budget"])


@pytest.mark.parametrize("orphan", [True, False], ids=["orphan", "flagged-paired"])
def test_mask_can_be_explicitly_excluded_without_changing_parent_or_source(reviewed, controller, orphan):
    case = reviewed
    if orphan:
        mask_path = case.source / "orphan.jpg.mask.png"
        Image.new("L", (16, 12), 255).save(mask_path)
    else:
        mask_path = case.photos[0].with_name(case.photos[0].name + ".mask.png")
        Image.new("L", (2, 2), 255).save(mask_path)  # A flagged dimension mismatch in fixture data.
    items = scan_source(case.source)
    apply_dive_window(items, "2025-05-24T00:00:00Z", "2025-05-24T02:00:00Z")
    for item in items:
        if item.path == str(case.outside):
            item.included = False
    verify_images(items)
    hash_identities(items)
    case.store.save_inventory(items)
    original_mask = next(item for item in items if item.path == str(mask_path))
    images_before = {item.path: item.included for item in items if item.kind == "image"}
    fingerprint = source_fingerprint(case.source)
    with pytest.raises(ValueError):
        controller.set_inventory_decision(case.project, str(mask_path), True, "try unresolved include")
    controller.set_inventory_decision(case.project, str(mask_path), False, "Explicitly omit this mask")
    current = case.store.inventory()
    mask = next(item for item in current if item.path == str(mask_path))
    assert not mask.included and mask.mask_for == original_mask.mask_for
    assert {item.path: item.included for item in current if item.kind == "image"} == images_before
    controller.confirm_inventory(case.project, approval_token(current), "operator")
    assert case.store.require_approved("inventory")
    assert source_fingerprint(case.source) == fingerprint


def test_valid_mask_cannot_be_excluded_independently(reviewed, controller):
    case = reviewed
    path = str(case.photos[0].with_name(case.photos[0].name + ".mask.png"))
    before = case.store.read("inventory")
    with pytest.raises(ValueError):
        controller.set_inventory_decision(case.project, path, False, "Try stripping a valid mask")
    assert case.store.read("inventory") == before
    mask = next(item for item in case.store.inventory() if item.path == path)
    assert mask.included and mask.mask_for == str(case.photos[0])
