"""Offline ownership/recovery tests; no application launches or shared markers."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

import rs
from modules import project_runtime as runtime


class Child:
    pid = 123456789

    def __init__(self, action=None):
        self.action = action
        self.waits = 0
        self.terminations = 0

    def wait(self, timeout=None):
        self.waits += 1
        return self.action(self.waits) if self.action else 0

    def poll(self):
        raise AssertionError("Polling is not release evidence; use the exact child wait")

    def terminate(self):
        self.terminations += 1


@pytest.fixture(autouse=True)
def isolate_retained_handles():
    before = set(runtime._RETAINED_PROCESSES)
    yield
    # These are fake handles created by this file; never clear another owner.
    for key in set(runtime._RETAINED_PROCESSES) - before:
        runtime._RETAINED_PROCESSES.pop(key)


@pytest.fixture
def record(tmp_path):
    root = tmp_path / "proc/tmp/attempt"
    root.mkdir(parents=True)
    return {"stage": "fixture", "argv": ["not-a-real-executable"], "needs_realityscan": True,
            "env": {"RS_RUNTIME_ROOT": str(root), "RS_RUN_ID": "attempt",
                    "RS_CONTROL_FILE": str(root / "control.json"), "RS_EVENT_FILE": str(root / "runtime.jsonl")}}


def event(seq=1, kind="prepared", *, run_id="child", parent="attempt", retained=None):
    return {"parent_run_id": parent, "run_id": run_id, "kind": kind, "sequence": seq,
            "data": {} if retained is None else {"ownership_retained": retained}}


def append(record, *events):
    path = Path(record["env"]["RS_EVENT_FILE"])
    with path.open("ab") as stream:
        for value in events:
            stream.write((json.dumps(value) + "\n").encode())


def finished(record, run_id="child"):
    append(record, event(run_id=run_id), event(2, "done", run_id=run_id, retained=False))


@pytest.mark.parametrize("value", [[], "text", None, 7,
    {"parent_run_id": "attempt", "run_id": [], "data": {}},
    {"parent_run_id": "attempt", "run_id": "child", "data": None},
    event(True), event(0), event(2, "done", retained=0), event(2, "done", retained="false")])
def test_invalid_event_structure_is_always_unconfirmed(record, value):
    append(record, value)
    with pytest.raises(runtime.OwnershipUnconfirmed):
        runtime.require_runtime_release(record)


@pytest.mark.parametrize("field", ["RS_RUN_ID", "RS_RUNTIME_ROOT", "RS_EVENT_FILE"])
def test_missing_channel_cannot_release(record, field):
    finished(record)
    record["env"].pop(field)
    with pytest.raises(runtime.OwnershipUnconfirmed):
        runtime.require_runtime_release(record)


def test_event_file_must_be_in_selected_runtime_root(record, tmp_path):
    record["env"]["RS_EVENT_FILE"] = str(tmp_path / "foreign.jsonl")
    finished(record)
    with pytest.raises(runtime.OwnershipUnconfirmed):
        runtime.require_runtime_release(record)


@pytest.mark.parametrize("tail", [b'{"partial":', b"\xff\n", json.dumps(event(3, "done", retained=False)).encode()])
def test_bad_or_unterminated_tail_cannot_hide_behind_terminal_event(record, tail):
    finished(record)
    with Path(record["env"]["RS_EVENT_FILE"]).open("ab") as stream:
        stream.write(tail)
    with pytest.raises(runtime.OwnershipUnconfirmed):
        runtime.require_runtime_release(record)


@pytest.mark.parametrize("events", [
    [event(1, "done", retained=False)],
    [event(), event(3, "done", retained=False)],
    [event(), event(1, "done", retained=False)],
    [event(), event(2, "cancel_requested", retained=False)],
    [event(), event(2, "done", retained=False), event(3, "progress")],
    [event(), event(2, "done", retained=True)],
])
def test_only_complete_ordered_terminal_release_counts(record, events):
    append(record, *events)
    with pytest.raises(runtime.OwnershipUnconfirmed):
        runtime.require_runtime_release(record)


def test_all_parallel_children_must_release(record):
    append(record, event(run_id="one"), event(run_id="two"), event(2, "done", run_id="one", retained=False))
    with pytest.raises(runtime.OwnershipUnconfirmed):
        runtime.require_runtime_release(record)
    append(record, event(2, "cancelled", run_id="two", retained=False))
    runtime.require_runtime_release(record)


def test_previous_stage_events_do_not_release_silent_new_child(record, tmp_path, monkeypatch):
    finished(record, "previous")
    child = Child()
    monkeypatch.setattr(rs.subprocess, "Popen", lambda *a, **kw: child)
    with pytest.raises(runtime.OwnershipUnconfirmed):
        rs.execute_commands([record], tmp_path / "agent", "")
    assert child.waits == 1
    state = json.loads((tmp_path / "agent/RUN_STATE.json").read_text())
    assert state["status"] == "ownership_unconfirmed" and state["ownership_released"] is False
    assert state["finished"] is None


def test_fresh_release_after_prelaunch_cursor_is_valid(record):
    finished(record, "previous")
    cursor = runtime.runtime_event_cursor(record)
    finished(record, "current")
    runtime.require_runtime_release(record, cursor=cursor)


@pytest.mark.parametrize("change", ["truncate", "replace"])
def test_channel_identity_change_refuses_release(record, change):
    finished(record, "previous")
    cursor = runtime.runtime_event_cursor(record)
    path = Path(record["env"]["RS_EVENT_FILE"])
    if change == "replace":
        path.rename(path.with_suffix(".old"))
    else:
        path.write_bytes(b"")
    with pytest.raises(runtime.OwnershipUnconfirmed):
        runtime.require_runtime_release(record, cursor=cursor)


@pytest.mark.parametrize("failure", [OSError, ValueError, RuntimeError])
def test_wait_failure_retains_exact_handle_without_busy_retry(record, tmp_path, failure):
    def fail(_): raise failure("broken handle")
    child = Child(fail)
    with pytest.raises(runtime.OwnershipUnconfirmed) as error:
        runtime.wait_planned_process(child, record, tmp_path / "log", runtime.ExecutionControl())
    assert child.waits == 1
    assert error.value.process is child
    assert runtime._RETAINED_PROCESSES[id(child)][0] is child


def test_wrapper_wait_error_and_failing_journal_still_raise_unconfirmed(tmp_path, monkeypatch):
    command = {"stage": "test", "argv": ["mock"]}
    def fail(_): raise OSError("handle unavailable")
    child = Child(fail)
    monkeypatch.setattr(rs.subprocess, "Popen", lambda *a, **kw: child)
    original = rs._write_json
    def write(path, value):
        if value["status"] == "ownership_unconfirmed":
            raise OSError("cannot record ambiguity")
        original(path, value)
    monkeypatch.setattr(rs, "_write_json", write)
    with pytest.raises(runtime.OwnershipUnconfirmed):
        rs.execute_commands([command], tmp_path / "agent", "")
    assert child.waits == 1
    assert json.loads((tmp_path / "agent/RUN_STATE.json").read_text())["status"] == "running"


def test_interrupt_before_handle_and_failed_abort_record_cannot_escape(tmp_path, monkeypatch):
    def launch(*a, **kw): raise KeyboardInterrupt()
    monkeypatch.setattr(rs.subprocess, "Popen", launch)
    original = rs._write_json
    def write(path, value):
        if value["status"] in {"cancel_requested", "ownership_unconfirmed"}:
            raise OSError("abort recording failed")
        original(path, value)
    monkeypatch.setattr(rs, "_write_json", write)
    with pytest.raises(runtime.OwnershipUnconfirmed):
        rs.execute_commands([{"stage": "test", "argv": ["mock"]}], tmp_path / "agent", "")


@pytest.mark.parametrize("failure", [KeyboardInterrupt, OSError, ValueError])
def test_postlaunch_instrumentation_failure_uses_guarded_recovery(tmp_path, monkeypatch, failure):
    child = Child()
    monkeypatch.setattr(rs.subprocess, "Popen", lambda *a, **kw: child)
    original = rs._write_json
    injected = False
    def write(path, value):
        nonlocal injected
        if value.get("pid") and not injected:
            injected = True
            raise failure("instrumentation")
        if value["status"] == "cancel_requested":
            raise OSError("also cannot record abort request")
        original(path, value)
    monkeypatch.setattr(rs, "_write_json", write)
    assert rs.execute_commands([{"stage": "test", "argv": ["mock"]}], tmp_path / "agent", "") == 0
    assert child.waits == 1


def test_failed_control_write_is_retried_while_owned_child_waits(record, tmp_path, monkeypatch):
    control = runtime.ExecutionControl()
    control.request_cancel("abort_current")
    original = rs._write_json
    writes = []
    def write(path, value):
        writes.append(value.copy())
        if len(writes) == 1:
            raise OSError("temporary sharing violation")
        original(path, value)
    monkeypatch.setattr(rs, "_write_json", write)
    def wait(count):
        if count == 1: raise subprocess.TimeoutExpired("owned", .5)
        return 0
    child = Child(wait)
    assert runtime.wait_planned_process(child, record, tmp_path / "log", control) == 0
    assert len(writes) == 2 and all(v["mode"] == "abort_current" for v in writes)
    assert child.terminations == 0  # RS child never terminated through Python process APIs.


def test_control_cannot_overwrite_event_file(record, tmp_path):
    record["env"]["RS_CONTROL_FILE"] = record["env"]["RS_EVENT_FILE"]
    finished(record)
    before = Path(record["env"]["RS_EVENT_FILE"]).read_bytes()
    control = runtime.ExecutionControl()
    control.request_cancel("abort_current")
    child = Child()
    runtime.wait_planned_process(child, record, tmp_path / "log", control)
    assert Path(record["env"]["RS_EVENT_FILE"]).read_bytes() == before
    assert child.terminations == 0 and child.waits == 1


def test_partial_utf8_event_is_replayed_after_completion(record, tmp_path):
    path = Path(record["env"]["RS_EVENT_FILE"])
    value = event()
    value["data"]["message"] = "caf\u00e9"
    encoded = (json.dumps(value, ensure_ascii=False) + "\n").encode()
    index = encoded.index(b"\xc3") + 1
    path.write_bytes(encoded[:index])
    observed = []
    def wait(_):
        with path.open("ab") as stream: stream.write(encoded[index:])
        append(record, event(2, "done", retained=False))
        return 0
    assert runtime.wait_planned_process(Child(wait), record, tmp_path / "log", runtime.ExecutionControl(), observed.append) == 0
    assert [v["event"]["sequence"] for v in observed if v["kind"] == "runtime"] == [1, 2]


def test_final_event_backlog_is_drained_and_malformed_ui_data_is_not_forwarded(record, tmp_path):
    append(record, [], event())
    append(record, *[event(i, "progress") for i in range(2, 230)])
    append(record, event(230, "done", retained=False))
    observed = []
    runtime.wait_planned_process(Child(), record, tmp_path / "log", None, observed.append)
    events = [v["event"] for v in observed if v["kind"] == "runtime"]
    assert len(events) == 230 and events[-1]["kind"] == "done"


def test_observer_error_cannot_abandon_child(record, tmp_path):
    finished(record)
    def broken(_): raise RuntimeError("window destroyed")
    child = Child()
    assert runtime.wait_planned_process(child, record, tmp_path / "log", None, broken) == 0
    assert child.waits == 1


def test_control_strengthening_is_sticky():
    control = runtime.ExecutionControl()
    control.request_cancel("after_step")
    control.request_cancel("abort_current")
    control.request_cancel("after_step")
    assert control.snapshot() == (True, "abort_current")


@pytest.fixture
def identity():
    return {"schema": 1, "kind": "windows_process", "pid": 123,
            "created_filetime": 999999, "image_path": sys.executable, "host": runtime.platform.node()}


@pytest.mark.parametrize("status,creation,expected,safe", [
    ("running", 999999, "same_process_running", False),
    ("exited", 999999, "same_process_exited", True),
    ("running", 1000000, "pid_reused", True),
    ("absent", None, "absent", True),
])
def test_readonly_identity_distinguishes_pid_reuse(identity, monkeypatch, status, creation, expected, safe):
    observed = {"status": status, "identity": identity | {"created_filetime": creation}, "evidence": "fixture complete snapshot"}
    monkeypatch.setattr(runtime, "_windows_process_snapshot", lambda pid: observed)
    report = runtime.inspect_owned_process(identity)
    assert report["status"] == expected and report["confirmed_not_running"] is safe


@pytest.mark.parametrize("failure", [PermissionError, OSError, ValueError])
def test_readonly_query_failures_are_not_absence(identity, monkeypatch, failure):
    def query(pid): raise failure("query unavailable")
    monkeypatch.setattr(runtime, "_windows_process_snapshot", query)
    assert runtime.inspect_owned_process(identity)["status"] == "unconfirmed"


@pytest.mark.parametrize("field,value", [("pid", True), ("created_filetime", None), ("host", "another-host"), ("image_path", "relative"), ("kind", "legacy_pid")])
def test_invalid_creation_identity_cannot_certify_recovery(identity, field, value):
    identity[field] = value
    assert not runtime.inspect_owned_process(identity)["confirmed_not_running"]


@pytest.mark.skipif(os.name != "nt", reason="Windows read-only process-handle API")
def test_windows_native_identity_read_current_process_only():
    current = runtime._windows_process_snapshot(os.getpid())
    assert current["status"] == "running"
    assert current["identity"]["created_filetime"] > 0
    assert runtime.inspect_owned_process(current["identity"])["status"] == "same_process_running"


@pytest.mark.skipif(os.name != "nt", reason="Windows exact Popen handle identity")
def test_executor_persists_real_owned_python_creation_identity(tmp_path):
    command = {"stage": "python-fixture", "argv": [sys.executable, "-I", "-B", "-c", "import time; time.sleep(0.2)"],
               "project_id": "project", "project_attempt_id": "attempt"}
    assert rs.execute_commands([command], tmp_path / "agent", "") == 0
    state = json.loads((tmp_path / "agent/RUN_STATE.json").read_text())
    assert state["child_identity"]["kind"] == "windows_process"
    assert state["child_identity"]["pid"] == state["pid"]
    report = runtime.inspect_recovery(command, state, expected_project_id="project", expected_attempt_id="attempt")
    assert report["can_recover"] and report["automatic_changes"] is False


@pytest.fixture
def recovery(record, identity, monkeypatch):
    record.update(project_id="project", project_attempt_id="attempt")
    monkeypatch.setattr(runtime, "_windows_process_snapshot", lambda pid: {"status": "exited", "identity": identity})
    keys = ("RS_RUN_ID", "RS_RUNTIME_ROOT", "RS_ERRORS_DIR", "RS_CONTROL_FILE", "RS_EVENT_FILE", "RS_INSTANCE", "RS_EXECUTABLE")
    state = {"project_id": "project", "project_attempt_id": "attempt", "stage": record["stage"],
             "needs_realityscan": True, "launch_attempted": True, "pid": identity["pid"], "child_identity": identity,
             "runtime": {key: record["env"].get(key) for key in keys}, "runtime_event_cursor": {"offset": 0, "identity": None}}
    return record, state


def test_recovery_requires_runtime_release_even_when_python_is_gone(recovery):
    record, state = recovery
    args = {"expected_project_id": "project", "expected_attempt_id": "attempt"}
    state["operator_says_no_worker_running"] = True
    assert not runtime.inspect_recovery(record, state, **args)["can_recover"]
    finished(record)
    before = Path(record["env"]["RS_EVENT_FILE"]).read_bytes()
    assert runtime.inspect_recovery(record, state, **args)["can_recover"]
    assert Path(record["env"]["RS_EVENT_FILE"]).read_bytes() == before


@pytest.mark.parametrize("key,value", [("project_id", "foreign"), ("project_attempt_id", "old"),
    ("pid", 444), ("launch_attempted", False), ("needs_realityscan", False), ("runtime", {}),
    ("runtime_event_cursor", {"offset": -1, "identity": None})])
def test_recovery_refuses_mismatched_or_ambiguous_persisted_binding(recovery, key, value):
    record, state = recovery
    finished(record)
    state[key] = value
    assert not runtime.inspect_recovery(record, state, expected_project_id="project", expected_attempt_id="attempt")["can_recover"]
