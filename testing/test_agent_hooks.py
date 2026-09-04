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
    "cmd /c ProbeCalibGroups2.bat",
    r"modules\realityscan_interface\RS_CLI\Scripts\ProbeFlightlog5.bat a b",
    "AlignImagesFromFolder.bat D:/zone",
    # A script that does not exist yet must not slip past by being new.
    r"modules\realityscan_interface\RS_CLI\Scripts\BrandNewWorkflow.bat",
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
    "cat modules/realityscan_interface/RS_CLI/Scripts/ProbeFlightlog5.bat",
    "grep -n delegateTo modules/realityscan_interface/RS_CLI/Scripts/NightGrow.bat",
    # A backslash-escaped pipe is regex alternation, not a shell pipe.
    r'grep -n "delegateTo\|waitCompleted" modules/realityscan_interface/RS_CLI/Scripts/AlignZone.bat',
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


# ------------------------------------------- SessionStart: orientation

STATUS_HOOK = os.path.join(HOOKS, "session_status.py")


def run_status(stdin="", env=None, cwd=None):
    """Run the status hook with raw stdin (it must tolerate an empty
    payload, so this bypasses run_hook's json.dumps)."""
    child = dict(os.environ)
    child.pop("RS_RUN_CHARTER", None)
    child.pop("CLAUDE_PROJECT_DIR", None)
    child.update(env or {})
    return subprocess.run([sys.executable, STATUS_HOOK], input=stdin,
                          text=True, capture_output=True, env=child,
                          cwd=cwd or REPO)


def test_session_status_runs_with_empty_stdin():
    """Empty stdin, exit 0, the repo's HANDOFF heading in the output, and
    nothing outside ASCII - the cp1252 console crashes on anything else."""
    result = run_status(stdin="")
    assert result.returncode == 0, result.stderr
    with open(os.path.join(REPO, "HANDOFF.md"), encoding="utf-8") as fh:
        heading = next(ln for ln in fh if ln.startswith("## "))
    # The heading is emitted ASCII-folded; its leading words survive.
    assert heading.split()[1] in result.stdout
    assert "HANDOFF.md current section" in result.stdout
    assert "git status" in result.stdout
    assert "RS_RUN_CHARTER unset" in result.stdout
    result.stdout.encode("ascii")            # raises if anything slipped
    assert len(result.stdout.splitlines()) <= 65


def test_session_status_shows_only_the_current_handoff_section(tmp_path):
    (tmp_path / "HANDOFF.md").write_text(
        "# HANDOFF\n\n## 2026-09-03 - CURRENT, read this first\n\n"
        "current line one\ncurrent line two\n\n"
        "## 2026-09-02 - OLDER\n\nstale line\n", encoding="utf-8")
    result = run_status(stdin="{}", env={"CLAUDE_PROJECT_DIR": str(tmp_path)})
    assert result.returncode == 0, result.stderr
    assert "CURRENT, read this first" in result.stdout
    assert "current line two" in result.stdout
    assert "OLDER" not in result.stdout
    assert "stale line" not in result.stdout
    # tmp_path is not a git repo: the failure is reported, not raised.
    assert "git unavailable" in result.stdout


def test_session_status_truncates_a_long_section(tmp_path):
    body = "\n".join(f"line {i}" for i in range(80))
    (tmp_path / "HANDOFF.md").write_text(
        f"## NOW\n{body}\n\n## LATER\nx\n", encoding="utf-8")
    result = run_status(stdin="{}", env={"CLAUDE_PROJECT_DIR": str(tmp_path)})
    assert result.returncode == 0
    assert "more lines; read HANDOFF.md" in result.stdout
    assert "line 79" not in result.stdout


def test_session_status_survives_a_missing_handoff(tmp_path):
    result = run_status(stdin="not json",
                        env={"CLAUDE_PROJECT_DIR": str(tmp_path)})
    assert result.returncode == 0
    assert "HANDOFF.md not readable" in result.stdout


def _scaffolded_charter(tmp_path):
    """A charter from --init with the placeholders that validation needs
    filled in, the way test_run_charter's fixtures shape one."""
    from modules.run_charter import main as charter_main
    path = tmp_path / "results" / "_agent" / "RUN_CHARTER.json"
    assert charter_main(["--init", str(path)]) == 0
    data = json.loads(path.read_text(encoding="utf-8"))
    data["campaign"], data["dive"] = "T", "D"
    data["locations"].update({
        "originals": [str(tmp_path / "src")],
        "nav": [str(tmp_path / "nav")],
        "results_root": str(tmp_path / "results"),
        "agent_workspace": str(tmp_path / "results" / "_agent"),
        "protected": [{"path": str(tmp_path / "results" / "final"),
                       "why": "delivered"}],
    })
    data["ownership"]["rs_instance"] = "RSAGENT"
    data["signed_off"] = {"by": "owner", "date": "2026-09-03", "quote": ""}
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


def test_session_status_reports_the_charter_validation(tmp_path):
    charter = _scaffolded_charter(tmp_path)
    result = run_status(stdin="{}", env={"RS_RUN_CHARTER": str(charter)})
    assert result.returncode == 0, result.stderr
    assert "VALID" in result.stdout
    assert "validate exit code: 0" in result.stdout
    assert "RUN_STATE.json: none under" in result.stdout


def test_session_status_reports_run_state_fields(tmp_path):
    charter = _scaffolded_charter(tmp_path)
    (charter.parent / "RUN_STATE.json").write_text(json.dumps({
        "stage": "align", "task": "RS_T_D_align", "started": "2026-09-03T10:00",
        "log": str(tmp_path / "results" / "_agent" / "align.log"),
        "pid_file": "ignored"}), encoding="utf-8")
    result = run_status(stdin="{}", env={"RS_RUN_CHARTER": str(charter)})
    assert result.returncode == 0, result.stderr
    assert "stage: align" in result.stdout
    assert "task: RS_T_D_align" in result.stdout
    assert "started: 2026-09-03T10:00" in result.stdout
    assert "align.log" in result.stdout
    assert "pid_file" not in result.stdout


def test_session_status_never_blocks_on_a_broken_charter(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    result = run_status(stdin="{}", env={"RS_RUN_CHARTER": str(bad)})
    assert result.returncode == 0
    assert "INVALID" in result.stdout
    assert "validate exit code: 2" in result.stdout


def test_settings_json_wires_session_status_and_permissions():
    """The permission tiers are the cheapest layer for the rules Claude
    could break by accident (AGENT_OPERATIONS sec.6); a tier that is not
    in the file is a rule nobody enforces."""
    with open(os.path.join(REPO, ".claude", "settings.json"),
              encoding="utf-8") as fh:
        settings = json.load(fh)
    assert set(settings) == {"permissions", "hooks"}   # no unknown keys
    starts = settings["hooks"]["SessionStart"]
    assert any("session_status.py" in h["command"]
               for entry in starts for h in entry["hooks"])
    assert all(entry["matcher"] == "startup|resume" for entry in starts)
    assert os.path.isfile(STATUS_HOOK)

    perms = settings["permissions"]
    assert "Bash(python -m pytest *)" in perms["allow"]
    assert "Bash(python -m modules.verify *)" in perms["allow"]
    assert "Bash(git status*)" in perms["allow"]
    for rule in ("Bash(git push*)", "Bash(schtasks *)", "Bash(taskkill *)",
                 "Bash(rm -rf *)", "PowerShell(Stop-Process *)",
                 "PowerShell(Remove-Item *)"):
        assert rule in perms["ask"], rule
    for rule in ("Bash(git push --force*)", "Bash(git push -f *)",
                 "Bash(git reset --hard*)", "Bash(git clean -fd*)"):
        assert rule in perms["deny"], rule
    # Data paths are per-machine and belong to the charter, never here.
    assert not any(":/" in r or ":\\" in r
                   for tier in perms.values() for r in tier)
