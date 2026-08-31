"""The .claude/ hooks - liveness tests for the mechanical guards.

CLAUDE.md sec.1.1: after modifying any error-detection channel, inject a
known failure and prove the detector fires before trusting it. A guard
hook that silently stopped matching is worse than no hook, because the
rule it replaced is no longer being remembered either.

These run the hook scripts as the harness runs them - a JSON tool call on
stdin, a verdict as the exit code (0 allows, 2 blocks) - so what is tested
is the real contract, not a Python function behind it.
"""
import json
import os
import subprocess
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

HOOKS = os.path.join(REPO, ".claude", "hooks")
LAUNCH_GUARD = os.path.join(HOOKS, "guard_rs_launch.py")
CHARTER_GUARD = os.path.join(HOOKS, "guard_charter_writes.py")
CRLF_HOOK = os.path.join(HOOKS, "normalize_crlf.py")


def run_hook(script, payload, env=None):
    """Invoke a hook exactly as the harness does."""
    child = dict(os.environ)
    child.update(env or {})
    return subprocess.run([sys.executable, script], input=json.dumps(payload),
                          text=True, capture_output=True, env=child)


def bash(command):
    return {"tool_name": "Bash", "tool_input": {"command": command}}


# --------------------------------------------- hard rule 1: launch guard

@pytest.mark.parametrize("command", [
    r'"C:\Program Files\Epic Games\RealityScan_2.2\RealityScan.exe" -align',
    r"cmd /c RS_CLI\Scripts\AlignZone.bat zone_1",
    "& RealityCapture.exe -getStatus RS1",
    "cd RS_CLI/Scripts && MergeZoneComponents.bat x.complist",
    "GenerateModel.bat",
])
def test_direct_realityscan_launches_are_blocked(command):
    result = run_hook(LAUNCH_GUARD, bash(command))
    assert result.returncode == 2, result.stdout
    assert "hard rule 1" in result.stderr


@pytest.mark.parametrize("command", [
    "grep -rn RealityScan.exe modules/",
    "cat RS_CLI/Scripts/AlignZone.bat",
    "rg AlignZone.bat --files-with-matches",
    "py -3.13 merge_zones.py --components_root X",
    "py -3.13 -m pytest testing -q",
    "git status --short",
])
def test_reading_about_realityscan_is_allowed(command):
    """The guard looks for INVOCATION, not for the string appearing."""
    assert run_hook(LAUNCH_GUARD, bash(command)).returncode == 0


def test_launch_guard_reports_when_it_cannot_check():
    """Silence is not success: an unreadable call says so."""
    result = subprocess.run([sys.executable, LAUNCH_GUARD], input="not json",
                            text=True, capture_output=True)
    assert result.returncode == 0
    assert "no check performed" in result.stderr


# ------------------------------------------- charter guard: touch rules

@pytest.fixture
def charter(tmp_path):
    path = tmp_path / "RUN_CHARTER.json"
    path.write_text(json.dumps({
        "schema": 1, "campaign": "T", "dive": "D",
        "locations": {
            "originals": [str(tmp_path / "src")],
            "nav": [str(tmp_path / "nav")],
            "results_root": str(tmp_path / "results"),
            "agent_workspace": str(tmp_path / "results" / "_agent"),
            "protected": [{"path": str(tmp_path / "results" / "final"),
                           "why": "delivered"}],
        },
        "ownership": {"rs_instance": "RSAGENT", "user_instances": ["RS1"]},
        "signed_off": {"by": "owner", "date": "2026-08-31"},
    }), encoding="utf-8")
    return path


def _write_call(path, cwd):
    return {"tool_name": "Write", "tool_input": {"file_path": str(path)},
            "cwd": str(cwd)}


def test_writes_into_source_and_protected_are_blocked(tmp_path, charter):
    env = {"RS_RUN_CHARTER": str(charter)}
    for target in (tmp_path / "src" / "IMG.jpg",
                   tmp_path / "nav" / "log.txt",
                   tmp_path / "results" / "final" / "hull.obj",
                   tmp_path / "elsewhere" / "x.txt"):
        result = run_hook(CHARTER_GUARD, _write_call(target, tmp_path), env)
        assert result.returncode == 2, f"{target} was allowed"
        assert "run charter" in result.stderr


def test_writes_into_results_and_repo_are_allowed(tmp_path, charter):
    env = {"RS_RUN_CHARTER": str(charter)}
    for target in (tmp_path / "results" / "aligned" / "z.json",
                   os.path.join(REPO, "modules", "verify.py")):
        assert run_hook(CHARTER_GUARD, _write_call(target, tmp_path),
                        env).returncode == 0, f"{target} was blocked"


def test_shell_writes_into_protected_trees_are_blocked(tmp_path, charter):
    env = {"RS_RUN_CHARTER": str(charter)}
    src, final = tmp_path / "src", tmp_path / "results" / "final"
    for command in (f'echo x > "{src / "note.txt"}"',
                    f'rm -rf "{final}"',
                    f'cp a.txt "{src / "b.txt"}"'):
        payload = bash(command)
        payload["cwd"] = str(tmp_path)
        assert run_hook(CHARTER_GUARD, payload, env).returncode == 2, command


def test_shell_reads_are_allowed(tmp_path, charter):
    payload = bash(f'cat "{tmp_path / "src" / "IMG.jpg"}"')
    payload["cwd"] = str(tmp_path)
    assert run_hook(CHARTER_GUARD, payload,
                    {"RS_RUN_CHARTER": str(charter)}).returncode == 0


def test_no_charter_means_no_enforcement(tmp_path):
    """The owner's own interactive sessions must not be constrained by a
    contract they never signed."""
    assert run_hook(CHARTER_GUARD, _write_call(tmp_path / "anything", tmp_path),
                    {"RS_RUN_CHARTER": ""}).returncode == 0


def test_set_but_broken_charter_blocks(tmp_path):
    """Believing you are constrained while nothing checks is the
    dangerous state - refuse rather than proceed unguarded."""
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    result = run_hook(CHARTER_GUARD, _write_call(tmp_path / "x", tmp_path),
                      {"RS_RUN_CHARTER": str(bad)})
    assert result.returncode == 2
    assert "not usable" in result.stderr


# ----------------------------------------------- CRLF: the Windows trap

def _crlf_call(path):
    return {"tool_name": "Write", "tool_input": {"file_path": str(path)}}


@pytest.mark.parametrize("suffix", [".bat", ".cmd", ".vbs"])
def test_lf_script_is_rewritten_as_crlf(tmp_path, suffix):
    script = tmp_path / f"T{suffix}"
    script.write_bytes(b"@echo off\ngoto :run\n:run\nexit /b 0\n")
    assert run_hook(CRLF_HOOK, _crlf_call(script)).returncode == 0
    data = script.read_bytes()
    assert data.count(b"\r\n") == data.count(b"\n")
    assert b"\r\r\n" not in data


def test_normalisation_is_idempotent(tmp_path):
    script = tmp_path / "T.bat"
    script.write_bytes(b"@echo off\ngoto :run\n")
    run_hook(CRLF_HOOK, _crlf_call(script))
    once = script.read_bytes()
    result = run_hook(CRLF_HOOK, _crlf_call(script))
    assert script.read_bytes() == once
    assert result.stdout.strip() == ""       # nothing to report


def test_mixed_endings_are_repaired(tmp_path):
    script = tmp_path / "T.bat"
    script.write_bytes(b"@echo off\r\ngoto :run\n:run\r\nexit /b 0\n")
    run_hook(CRLF_HOOK, _crlf_call(script))
    data = script.read_bytes()
    assert data.count(b"\r\n") == data.count(b"\n")
    assert b"\r\r\n" not in data


def test_other_files_are_untouched(tmp_path):
    source = tmp_path / "T.py"
    source.write_bytes(b"x = 1\ny = 2\n")
    run_hook(CRLF_HOOK, _crlf_call(source))
    assert source.read_bytes() == b"x = 1\ny = 2\n"


# ------------------------------------------------------------ wiring

def test_settings_json_wires_every_hook():
    """A hook nobody registered is a rule nobody enforces."""
    with open(os.path.join(REPO, ".claude", "settings.json"),
              encoding="utf-8") as fh:
        settings = json.load(fh)
    registered = json.dumps(settings)
    for script in ("guard_rs_launch.py", "guard_charter_writes.py",
                   "normalize_crlf.py"):
        assert script in registered, f"{script} is not wired in settings.json"
        assert os.path.isfile(os.path.join(HOOKS, script))
