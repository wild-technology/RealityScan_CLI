"""Review fixes of 2026-09-06 (the agent-lane review after the D13 commit),
each pinned by the case that found it.

bugs-surface F1  the charter's align_settings_xml reaches the run (RS_ALIGN_PARAMS)
bugs-surface F2  rs run/launch --stages preflight the SUBSET they will run
bugs-surface F3  an answer colliding with a pinned flag is refused, not doubled
bugs-surface F4  a JSON null answer is "not answered", never the token "None"
bugs-surface F5  a merge flag does not make a same-named answer look consumed
bugs-surface F7  a stage that never starts leaves RUN_STATE failed, not running
bugs-surface F8  a direct rs run drops an earlier launch's task/.rc fields
bugs-surface F12 science.min_component_size reaches align and merge
na173-probe  F2  a charter zone that disagrees with the log's tag BLOCKS
na173-probe  F3  the charter template parses as scaffolded
na173-probe  F4  a placeholder protected entry is a question
na173-probe  F6  a log whose width is not the pinned format's is named
na173-probe  F7  b_zone_layout=pool sets RS_ALIGN_POOL_DIR
hooks H1/H4/H5   launcher: absolute paths, ASCII only, one line per shell
hooks H2/H3      launch guard: heredocs to read-only verbs pass, `&` splits,
                 bare executable / PATHEXT-resolved workflow names block
hooks H6         charter-write guard honours a quoted target with a space
hooks H8         schtasks /Change ... /TR is inspected like /Create
hooks H9         rs run --foreground is refused under CLAUDECODE
d13-bat F1       ModelToFinal's fallback moves its own errors marker first
"""
from __future__ import annotations

import json
import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import rs as rs_mod  # noqa: E402
from modules import preflight as pf  # noqa: E402
from modules import run_plan  # noqa: E402
from modules.run_charter import TEMPLATE, parse_charter  # noqa: E402
from testing.test_agent_hooks import bash, run_hook  # noqa: E402
from testing.test_preflight import _charter, _dataset  # noqa: E402

HOOKS = os.path.join(REPO, ".claude", "hooks")
LAUNCH_GUARD = os.path.join(HOOKS, "guard_rs_launch.py")
CHARTER_GUARD = os.path.join(HOOKS, "guard_charter_writes.py")
SCHTASKS_GUARD = os.path.join(HOOKS, "guard_schtasks.py")
SCRIPTS = os.path.join(REPO, "modules", "realityscan_interface", "RS_CLI", "Scripts")


def _ready(tmp_path, **kw):
    originals, nav = _dataset(tmp_path)
    return _charter(tmp_path, originals, nav, **kw)


# ---------------------------------------------------------- charter -> run

def test_align_settings_xml_reaches_the_run(tmp_path):
    variant = tmp_path / "AlignmentParams_variant.xml"
    variant.write_text('<Configuration id="{x}"><entry key="sfmX" value="1"/></Configuration>',
                       encoding="utf-8")
    charter = _ready(tmp_path)
    charter.science["align_settings_xml"] = str(variant)
    assert charter.env()["RS_ALIGN_PARAMS"] == str(variant)
    plan = run_plan.build_plan(run_plan.session_from_charter(charter), charter)
    assert all(c["env"].get("RS_ALIGN_PARAMS") == str(variant) for c in plan["commands"])


def test_placeholder_settings_xml_is_not_exported(tmp_path):
    charter = _ready(tmp_path)
    charter.science["align_settings_xml"] = "<path>"
    assert "RS_ALIGN_PARAMS" not in charter.env()


def test_preflight_judges_the_stage_subset(tmp_path):
    # georeference+batch+align is READY; an align-only run needs r_input /
    # r_flight_log, which batch normally hands over in-process.
    charter = _ready(tmp_path)
    assert pf.preflight_charter(charter)["verdict"] == "ready"
    subset = pf.preflight_charter(charter, stages=["align"])
    assert subset["stages"] == ["align"]
    assert subset["verdict"] == "not_ready"
    keys = [m["key"] for m in subset["missing"]] + subset["blocking"]
    assert any("r_input" in k or "r_flight_log" in k for k in keys), keys


def test_rs_run_gates_the_subset_it_will_run(tmp_path, capsys):
    charter = _ready(tmp_path)
    rc = rs_mod.main(["run", "--charter", str(charter.path), "--stages", "align"])
    assert rc == rs_mod.EXIT_NOT_READY
    assert "preflight is not READY" in capsys.readouterr().err


def test_colliding_answers_are_refused(tmp_path):
    charter = _ready(tmp_path, answers={
        "g_input": str(tmp_path / "originals"), "g_flight_log": str(tmp_path / "nav" / "H2060_final_datatable.csv"),
        "g_type": "WCA", "b_input": str(tmp_path / "originals"),
        "r_model_generate": "true", "output_dir": str(tmp_path / "elsewhere")})
    session = run_plan.session_from_charter(charter)
    with pytest.raises(ValueError) as exc:
        run_plan.build_commands(session)
    assert "output_dir" in str(exc.value) and "r_model_generate" in str(exc.value)
    report = pf.preflight_charter(charter)
    assert report["verdict"] == "not_ready"
    assert any("collide" in b for b in report["blocking"])


def test_null_answers_are_not_answered(tmp_path):
    charter = _ready(tmp_path)
    charter.raw["pipeline"]["answers"]["r_project_label"] = None
    charter.raw["pipeline"]["answers"]["b_use_z"] = False
    session = run_plan.session_from_charter(charter)
    assert "r_project_label" not in session.answers
    assert session.answers["b_use_z"] == "false"
    argv = [c for c in run_plan.build_commands(session) if "main.py" in str(c.argv[1])][0].argv
    assert "None" not in argv


def test_min_component_size_reaches_align_and_merge(tmp_path):
    charter = _ready(tmp_path, stages=("georeference", "batch", "align", "merge"))
    charter.science["min_component_size"] = 20
    session = run_plan.session_from_charter(charter)
    cmds = run_plan.build_commands(session)
    chain = [c for c in cmds if str(c.argv[1]).endswith("main.py")][0].argv
    merge = [c for c in cmds if str(c.argv[1]).endswith("merge_zones.py")][0].argv
    assert chain[chain.index("--r_min_component_size") + 1] == "20"
    assert merge[merge.index("--min_size") + 1] == "20"
    plan = run_plan.build_plan(session, charter)
    assert not any("silently dropped" in w for w in plan["warnings"])


def test_merge_flag_does_not_hide_an_unreached_answer(tmp_path):
    charter = _ready(tmp_path, stages=("georeference", "batch", "align", "merge"))
    charter.raw["pipeline"]["answers"]["min_size"] = "20"
    session = run_plan.session_from_charter(charter)
    plan = run_plan.build_plan(session, charter)
    assert any("silently dropped" in w and "min_size" in w for w in plan["warnings"])


def test_dropped_answer_names_the_disabling_module(tmp_path):
    charter = _ready(tmp_path, stages=("georeference", "preprocess", "batch", "align"))
    charter.raw["pipeline"]["answers"]["p_input"] = str(tmp_path / "originals")
    plan = run_plan.build_plan(run_plan.session_from_charter(charter), charter)
    dropped = [w for w in plan["warnings"] if "silently dropped" in w]
    assert dropped and "b_input" in dropped[0] and "DISABLED while Preprocess Images" in dropped[0]


def test_pool_layout_sets_the_pool_root(tmp_path):
    charter = _ready(tmp_path)
    charter.raw["pipeline"]["answers"]["b_zone_layout"] = "pool"
    session = run_plan.session_from_charter(charter)
    chain = [c for c in run_plan.build_commands(session) if str(c.argv[1]).endswith("main.py")][0]
    assert chain.env["RS_ALIGN_POOL_DIR"] == str(tmp_path / "originals")


def test_template_scaffold_parses_and_asks(tmp_path):
    path = tmp_path / "RUN_CHARTER.json"
    path.write_text(json.dumps(TEMPLATE, indent=2), encoding="utf-8")
    charter = parse_charter(json.loads(path.read_text(encoding="utf-8")), path)
    assert charter.agent_workspace.endswith("_agent")
    report = pf.preflight_charter(charter)
    keys = [m["key"] for m in report["missing"]]
    for key in ("signed_off", "locations.originals", "locations.nav",
                "locations.results_root", "locations.protected", "campaign", "dive",
                "ownership.rs_instance", "budget", "science.frame"):
        assert key in keys, (key, keys)


def test_placeholder_protected_entry_is_a_question(tmp_path):
    charter = _ready(tmp_path)
    charter.protected = [{"path": "<path>", "why": "<why>"}]
    keys = [m["key"] for m in pf.preflight_charter(charter)["missing"]]
    assert "locations.protected" in keys


def test_relative_results_root_is_a_question(tmp_path, monkeypatch):
    charter = _ready(tmp_path)
    charter.results_root = "results"
    monkeypatch.chdir(tmp_path)
    keys = [m["key"] for m in pf.preflight_charter(charter)["missing"]]
    assert "locations.results_root" in keys


# ---------------------------------------------------------------- frames

def _log(tmp_path, name, header):
    log = tmp_path / name
    log.write_text(header + "\n", encoding="utf-8")
    return log


HEADER13 = ("filename;X (East);Y (North);Alt;X Accuracy;Y Accuracy;Alt Accuracy;"
            "Yaw;Pitch;Roll;Yaw Accuracy;Pitch Accuracy;Roll Accuracy")


@pytest.mark.parametrize("frame,verdict", [("utm:57L", "ready"), ("utm:54N", "blocked"),
                                           ("utm", "asked")])
def test_zone_must_match_the_log_tag(tmp_path, frame, verdict):
    log = _log(tmp_path, "flight_log_57L_UTM.txt", HEADER13 + ";FocalLength")
    charter = _ready(tmp_path, frame=frame)
    charter.raw["pipeline"]["answers"]["b_flight_log_path"] = str(log)
    report = pf.preflight_charter(charter)
    blocks = [b for b in report["blocking"] if "zones disagree" in b]
    asks = [m for m in report["missing"] if m["key"] == "science.frame"]
    if verdict == "ready":
        assert not blocks and not asks
    elif verdict == "blocked":
        assert blocks and "57L" in blocks[0]
    else:
        assert asks and "utm:57L" in asks[0]["question"]


def test_log_width_is_compared_with_the_format_the_run_uses(tmp_path):
    """A SHORTER log is fine (measured 2026-09-06: the 13-column NA173 log
    under the 14-column format landed every column); a WIDER one is still
    unmeasured and warns; a charter's own r_flight_log_params is what is
    compared, not the canonical template."""
    log = _log(tmp_path, "flight_log_57L_UTM.txt", HEADER13)
    charter = _ready(tmp_path, frame="utm:57L")
    charter.raw["pipeline"]["answers"]["b_flight_log_path"] = str(log)
    report = pf.preflight_charter(charter)
    assert any("13 columns" in c and "shorter log" in c for c in report["checked"]),         report["checked"]
    assert not any("13 columns" in w for w in report["warnings"])

    wide = _log(tmp_path, "flight_log_57L_UTM.txt",
                HEADER13 + ";FocalLength;Extra")
    charter.raw["pipeline"]["answers"]["b_flight_log_path"] = str(wide)
    report = pf.preflight_charter(charter)
    hits = [w for w in report["warnings"] if "15 columns" in w and "EXTRA" in w]
    assert hits, report["warnings"]

    custom = tmp_path / "FlightLogParams_custom.xml"
    canon = (pf.Path(pf.METADATA_DIR) / "FlightLogParams.xml").read_text(encoding="utf-8")
    custom.write_text(canon.replace("{D1F2A3B4-5C6D-4E7F-8A9B-0C1D2E3F4A5B}",
                                    "{0E9850E2-73E1-4538-B2CF-B18BEF6CECEB}"),
                      encoding="utf-8")
    charter.raw["pipeline"]["answers"]["b_flight_log_path"] = str(log)
    charter.raw["pipeline"]["answers"]["r_flight_log_params"] = str(custom)
    report = pf.preflight_charter(charter)
    lines = report["warnings"] + report["checked"]
    assert any("FlightLogParams_custom.xml" in ln and "0E9850E2" in ln for ln in lines), lines


# ----------------------------------------------------------------- rs.py

def test_stage_that_never_starts_is_recorded_failed(tmp_path):
    agent_ws = tmp_path / "_agent"
    cmd = {"stage": "Extract Images", "argv": [str(tmp_path / "no_such_python.exe"), "-c", "1"]}
    assert rs_mod.execute_commands([cmd], agent_ws, "C.json") == 1
    state = json.loads((agent_ws / "RUN_STATE.json").read_text(encoding="utf-8"))
    assert state["status"] == "failed"
    assert "no_such_python" in state["error"] or "FileNotFound" in state["error"]
    assert state["history"][-1]["returncode"] is None


def test_direct_run_drops_an_earlier_launch(tmp_path, monkeypatch):
    charter = _ready(tmp_path)
    monkeypatch.delenv(rs_mod.LAUNCHER_ENV, raising=False)
    paths = rs_mod.write_launcher(charter, str(charter.path), None, "RS_OLD")
    paths["rc"].write_text("0\n", encoding="utf-8")
    agent_ws = rs_mod._agent_ws(charter)
    cmd = {"stage": "Publish", "argv": [sys.executable, "-c", "import sys; sys.exit(3)"]}
    assert rs_mod.execute_commands([cmd], agent_ws, str(charter.path)) == 1
    state = json.loads((agent_ws / "RUN_STATE.json").read_text(encoding="utf-8"))
    assert "task" not in state and "rc_file" not in state
    report = rs_mod.status_report(charter.results_root, agent_ws, None, charter=charter)
    assert "launcher_exit" not in report["run_state"]
    assert report["budget"]["expected_hours"] == 4


def test_status_flags_a_stale_running_state(tmp_path):
    charter = _ready(tmp_path)
    agent_ws = rs_mod._agent_ws(charter)
    agent_ws.mkdir(parents=True)
    (agent_ws / "RUN_STATE.json").write_text(json.dumps(
        {"schema": 1, "status": "running", "pid": 999999999,
         "started": "2026-09-05 00:00:00"}), encoding="utf-8")
    report = rs_mod.status_report(charter.results_root, agent_ws, None, charter=charter)
    assert report["run_state"]["pid_alive"] is False
    assert "STALE" in report["run_state"]["status_note"]
    text = rs_mod.format_status(report)
    assert "STALE" in text and "budget" in text


def test_launcher_paths_are_absolute_and_ascii(tmp_path, monkeypatch):
    charter = _ready(tmp_path)
    monkeypatch.chdir(tmp_path)
    paths = rs_mod.write_launcher(charter, str(charter.path), None, "RS_T")
    state = json.loads(paths["state"].read_text(encoding="utf-8"))
    assert os.path.isabs(state["launcher_vbs"]) and os.path.isabs(state["launcher_cmd"])
    cmd_text = paths["cmd"].read_bytes().decode("utf-8")
    assert f'set "{rs_mod.LAUNCHER_ENV}=' in cmd_text
    with pytest.raises(ValueError) as exc:
        rs_mod.write_launcher(charter, str(charter.path), None, "RS_caf\u00e9")
    assert "non-ASCII" in str(exc.value)


def test_launch_prints_one_form_per_shell(tmp_path, capsys):
    charter = _ready(tmp_path)
    assert rs_mod.main(["launch", "--charter", str(charter.path), "--task-name", "RS_T",
                        "--start", "03:00"]) == 0
    out = capsys.readouterr().out
    assert 'schtasks /Create /TN "RS_T" /TR "wscript.exe //B \\"' in out          # cmd.exe
    assert "schtasks /Create /TN \"RS_T\" /TR 'wscript.exe //B \"" in out        # PowerShell
    assert 'schtasks //Create //TN "RS_T" //TR "wscript.exe //B \\"' in out       # Git Bash
    assert 'status --charter "' in out


def test_foreground_is_refused_under_the_harness(tmp_path, monkeypatch, capsys):
    charter = _ready(tmp_path)
    monkeypatch.setenv(rs_mod.HARNESS_ENV, "1")
    rc = rs_mod.main(["run", "--charter", str(charter.path), "--foreground"])
    assert rc == rs_mod.EXIT_HARNESS_REFUSED
    assert "owner" in capsys.readouterr().err.lower()


# ----------------------------------------------------------------- hooks

@pytest.mark.parametrize("command", [
    "python - <<'EOF'\nprint('AlignZone.bat has 3 labels')\nEOF",
    "cat > /tmp/note.txt <<'EOF'\nGenerateModel.bat sets texel 4096\nEOF",
    "PYTHONIOENCODING=utf-8 python -c \"print(open('modules/realityscan_interface/RS_CLI/Scripts/AlignZone.bat').read()[:80])\"",
    "file modules/realityscan_interface/RS_CLI/Scripts/AlignZone.bat",
    "grep -n -e RS_ALIGN_PARAMS modules/realityscan_interface/RS_CLI/Scripts/AlignZone.bat",
    "git log --oneline -- modules/realityscan_interface/RS_CLI/Scripts/ModelToFinal.bat",
])
def test_read_only_work_naming_a_workflow_is_allowed(command):
    result = run_hook(LAUNCH_GUARD, bash(command))
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("command", [
    "echo start & modules/realityscan_interface/RS_CLI/Scripts/AlignZone.bat zone_1",
    "echo $(modules/realityscan_interface/RS_CLI/Scripts/AlignZone.bat zone_1)",
    "cd modules/realityscan_interface/RS_CLI/Scripts && cmd //c AlignZone zone_1",
    "bash <<'EOF'\nmodules/realityscan_interface/RS_CLI/Scripts/AlignZone.bat zone_1\nEOF",
    "Start-Process 'C:\\Program Files\\Epic Games\\RealityScan_2.2\\RealityScan' -ArgumentList '-help'",
    "call GenerateModel scene.rsproj",
])
def test_hidden_launches_are_blocked(command):
    result = run_hook(LAUNCH_GUARD, bash(command))
    assert result.returncode == 2, result.stdout


def test_log_and_install_paths_are_not_the_executable():
    for command in ("Get-Content $env:LOCALAPPDATA/Temp/RealityScan.log -Tail 20",
                    "mkdir realityscan_probe && cd realityscan_probe"):
        assert run_hook(LAUNCH_GUARD, bash(command)).returncode == 0, command


def test_quoted_redirect_into_a_root_with_a_space_is_allowed(tmp_path):
    root = tmp_path / "res root"
    charter = _ready(tmp_path)
    originals = tmp_path / "originals"
    data = json.loads(charter.path.read_text(encoding="utf-8"))
    data["locations"]["results_root"] = str(root)
    data["locations"]["agent_workspace"] = str(root / "_agent")
    charter_path = tmp_path / "space.json"
    charter_path.write_text(json.dumps(data), encoding="utf-8")
    env = {"RS_RUN_CHARTER": str(charter_path)}
    target = root / "_agent" / "x.txt"
    ok = run_hook(CHARTER_GUARD, bash(f'echo hi > "{target}"'), env=env)
    assert ok.returncode == 0, ok.stderr
    bad = run_hook(CHARTER_GUARD, bash(f'echo hi > "{originals / "x.txt"}"'), env=env)
    assert bad.returncode == 2


def test_schtasks_change_of_the_command_line_is_inspected(tmp_path):
    result = run_hook(SCHTASKS_GUARD, bash('schtasks /Change /TN "RS_T" /TR "C:\\anything\\else.bat"'))
    assert result.returncode == 2
    trigger_only = run_hook(SCHTASKS_GUARD, bash('schtasks /Change /TN "RS_T" /ST 04:00'))
    assert trigger_only.returncode == 0
    doubled = run_hook(SCHTASKS_GUARD, bash('schtasks //Create //TN "RS_T" //TR "wscript.exe //B \\"C:\\nowhere\\x.vbs\\"" //SC ONCE'))
    assert doubled.returncode == 2


# --------------------------------------------------------------- the .bat

def test_model_to_final_fallback_moves_its_own_marker_and_runs_through_run():
    text = open(os.path.join(SCRIPTS, "ModelToFinal.bat"), "rb").read().decode("utf-8")
    fallback = text[text.index(":unwrapFallback"):text.index(":unwrapBothFailed")]
    assert 'if "%RS_TARGET%" == "%RS_INSTANCE%" for %%A in' in fallback
    assert "expected_unwrap_adaptive_%RS_INSTANCE%_%final_name%.txt" in fallback
    assert 'call :run -unwrap "%UnwrapFallback%" || exit /b 1' in fallback
    assert "-delegateTo %RS_TARGET% -unwrap" not in fallback
    assert "lastError is sticky only while the instance is" in text


def test_launch_accepts_a_comma_separated_stage_list(tmp_path, capsys):
    # the comma is the stage grammar's separator, not a cmd metacharacter
    # (refused as one on the first live launch, 2026-09-06)
    charter = _ready(tmp_path)
    rc = rs_mod.main(["launch", "--charter", str(charter.path), "--stages", "georeference,batch",
                      "--task-name", "RS_T", "--start", "03:00"])
    assert rc == 0, capsys.readouterr().err
    out = capsys.readouterr().out
    assert '--stages "georeference,batch"' in (tmp_path / "results" / "_agent" / "launch").glob("*.cmd").__next__().read_text(encoding="utf-8")
    with pytest.raises(ValueError):
        rs_mod.write_launcher(charter, str(charter.path), ["align", "b&d"], "RS_T")
