"""rs.py - the one command surface: forwarding, run, launch, status.

Nothing here boots RealityScan. ``run`` is exercised with trivial python
commands through ``execute_commands``; the harness refusal is proven with a
real plan (align stage) and CLAUDECODE set, so no driver ever starts.
"""
from __future__ import annotations

import json
import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import rs as rs_mod  # noqa: E402
from testing.test_preflight import _charter, _dataset  # noqa: E402


@pytest.fixture
def ready(tmp_path):
    originals, nav = _dataset(tmp_path)
    return _charter(tmp_path, originals, nav)


def test_help_lists_every_subcommand(capsys):
    with pytest.raises(SystemExit) as exc:
        rs_mod.main(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    for name in ("charter", "plan", "preflight", "verify", "status", "run", "launch"):
        assert name in out


def test_charter_and_plan_and_preflight_forward(tmp_path, ready, capsys):
    scaffold = tmp_path / "new" / "RUN_CHARTER.json"
    assert rs_mod.main(["charter", "init", str(scaffold)]) == 0
    assert scaffold.is_file()
    assert rs_mod.main(["charter", "validate", str(ready.path)]) == 0
    assert rs_mod.main(["plan", "--charter", str(ready.path), "--validate"]) == 0
    assert "main.py" in capsys.readouterr().out
    assert rs_mod.main(["preflight", "--charter", str(ready.path), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["verdict"] == "ready"
    assert rs_mod.main(["verify", "--workspace", str(tmp_path / "absent")]) == 3


def test_run_dry_run_writes_nothing(ready, capsys):
    before = sorted(str(p) for p in ready.path.parent.rglob("*"))
    assert rs_mod.main(["run", "--charter", str(ready.path), "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "DRY RUN" in out and "main.py" in out
    assert sorted(str(p) for p in ready.path.parent.rglob("*")) == before


def test_run_refuses_unsigned_and_not_ready(tmp_path, capsys):
    originals, nav = _dataset(tmp_path)
    unsigned = _charter(tmp_path, originals, nav, signed=False)
    assert rs_mod.main(["run", "--charter", str(unsigned.path)]) == 1
    assert "not signed" in capsys.readouterr().err
    asks = _charter(tmp_path, originals, nav, instance="*",
                    path=tmp_path / "asks.json")
    assert rs_mod.main(["run", "--charter", str(asks.path)]) == 1
    captured = capsys.readouterr()
    assert "ASK THE OWNER" in captured.out and "preflight is not READY" in captured.err
    assert not (tmp_path / "results" / "_agent" / "RUN_STATE.json").exists()


def test_run_refuses_realityscan_stages_from_the_harness(ready, monkeypatch, capsys):
    monkeypatch.setenv(rs_mod.HARNESS_ENV, "1")
    assert rs_mod.main(["run", "--charter", str(ready.path)]) == rs_mod.EXIT_HARNESS_REFUSED
    err = capsys.readouterr().err
    assert "SCHEDULER-OWNED" in err and "rs.py launch" in err
    assert not (ready.path.parent / "results" / "_agent" / "RUN_STATE.json").exists()


def test_execute_commands_writes_state_logs_and_stops_at_failure(tmp_path):
    agent_ws = tmp_path / "results" / "_agent"
    ok = {"stage": "Extract Images", "argv": [sys.executable, "-c", "print('hello')"],
          "env": {"RS_TEST_MARK": "1"}, "cwd": str(tmp_path)}
    bad = {"stage": "Georeference", "argv": [sys.executable, "-c",
                                             "import sys; print('boom'); sys.exit(4)"],
           "env": {}, "cwd": str(tmp_path)}
    never = {"stage": "Batch", "argv": [sys.executable, "-c", "print('never')"],
             "env": {}, "cwd": str(tmp_path)}
    rc = rs_mod.execute_commands([ok, bad, never], agent_ws, "C.json",
                                 label="T", resume_cmd="python rs.py run ...")
    assert rc == 1
    state = json.loads((agent_ws / "RUN_STATE.json").read_text(encoding="utf-8"))
    assert state["status"] == "failed" and state["stage"] == "Georeference"
    assert state["returncode"] == 4 and state["resume"].startswith("python rs.py run")
    assert [h["stage"] for h in state["history"]] == ["Extract Images", "Georeference"]
    logs = sorted((agent_ws / "logs").iterdir())
    assert len(logs) == 2
    assert "hello" in logs[0].read_text(encoding="utf-8")
    assert "boom" in logs[1].read_text(encoding="utf-8")


def test_execute_commands_closes_stdin(tmp_path):
    agent_ws = tmp_path / "_agent"
    probe = {"stage": "probe", "argv": [sys.executable, "-c",
             "import sys; sys.exit(0 if sys.stdin.read() == '' else 9)"],
             "env": {}, "cwd": str(tmp_path)}
    assert rs_mod.execute_commands([probe], agent_ws, "C.json") == 0


def test_launch_writes_crlf_launchers_and_prints_schtasks(ready, capsys):
    assert rs_mod.main(["launch", "--charter", str(ready.path),
                        "--task-name", "RS_T", "--start", "03:00"]) == 0
    out = capsys.readouterr().out
    assert 'schtasks /Create /TN "RS_T"' in out and "/SC ONCE /ST 03:00" in out
    assert 'schtasks /Run /TN "RS_T"' in out
    agent_ws = ready.path.parent / "results" / "_agent"
    cmds = list((agent_ws / "launch").glob("*.cmd"))
    vbss = list((agent_ws / "launch").glob("*.vbs"))
    assert len(cmds) == 1 and len(vbss) == 1
    for f in cmds + vbss:
        data = f.read_bytes()
        assert data.count(b"\r\n") == data.count(b"\n") and data.count(b"\r\n") > 0
    text = cmds[0].read_text(encoding="utf-8")
    assert "rs.py" in text and "--foreground" in text and "RS_RUN_CHARTER=" in text
    assert "RS_NO_SETTINGS_INHERITANCE=1" in text
    state = json.loads((agent_ws / "RUN_STATE.json").read_text(encoding="utf-8"))
    assert state["status"] == "prepared" and state["task"] == "RS_T"
    assert state["budget"]["expected_hours"] == 4


def test_launch_refuses_cmd_metacharacters(tmp_path, monkeypatch, capsys):
    originals, nav = _dataset(tmp_path)
    ready = _charter(tmp_path, originals, nav)
    monkeypatch.setattr(rs_mod, "REPO", type(rs_mod.REPO)(str(tmp_path / "a&b")))
    assert rs_mod.main(["launch", "--charter", str(ready.path)]) == 1
    assert "metacharacter" in capsys.readouterr().err


def test_launch_never_calls_schtasks(ready, monkeypatch):
    calls = []
    monkeypatch.setattr(rs_mod.subprocess, "run",
                        lambda *a, **k: calls.append(a) or None)
    monkeypatch.setattr(rs_mod.subprocess, "Popen",
                        lambda *a, **k: calls.append(a) or None)
    assert rs_mod.main(["launch", "--charter", str(ready.path)]) == 0
    assert calls == []


def test_status_is_read_only_and_reports(tmp_path, ready, capsys):
    results = ready.path.parent / "results"
    results.mkdir(exist_ok=True)
    before = sorted(str(p) for p in tmp_path.rglob("*"))
    rc = rs_mod.main(["status", "--charter", str(ready.path)])
    out = capsys.readouterr().out
    assert rc == 0                       # empty workspace: nothing started, verify ok
    assert "verdict" in out and "instance  : RSAGENT" in out and out.isascii()
    assert "run state : none" in out
    assert sorted(str(p) for p in tmp_path.rglob("*")) == before
    assert rs_mod.main(["status", "--workspace", str(results), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["verify"]["verdict"] == "ok"
