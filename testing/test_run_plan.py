"""modules.run_plan - the run plan, headless.

The plan is only worth anything if the commands in it actually run, so
these tests check the two ways a generated plan has historically been
wrong: an argv main.py's own parser rejects (exit 2 before a single stage
runs), and an answer the operator supplied that reaches no command at all.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.run_charter import parse_charter
from modules.run_plan import (ALL_STAGES, Session, build_plan, format_text, main,
                              session_from_charter,
                           unreached_answers, validate_command)


def _charter_dict(tmp_path, stages, answers):
    return {
        "schema": 1, "campaign": "ON2026", "dive": "RH0042",
        "locations": {
            "originals": [str(tmp_path / "src")], "nav": [],
            "results_root": str(tmp_path / "results"),
            "agent_workspace": str(tmp_path / "results" / "_agent"),
            "protected": [],
        },
        "ownership": {"rs_instance": "RSAGENT",
                      "rs_cache_dir": str(tmp_path / "cache"),
                      "user_instances": ["RS1"]},
        "pipeline": {"stages": stages, "answers": answers},
        "signed_off": {"by": "owner", "date": "2026-08-31"},
    }


def _charter(tmp_path, stages=("batch", "align"), answers=None):
    data = _charter_dict(tmp_path, list(stages), dict(answers or {}))
    path = tmp_path / "RUN_CHARTER.json"
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    charter = parse_charter(data, path)
    charter.path = path
    return charter


# ---------------------------------------------------------------- charter

def test_session_comes_entirely_from_the_charter(tmp_path):
    charter = _charter(tmp_path, answers={"b_input": "X"})
    session = session_from_charter(charter)
    assert session.expedition == "ON2026"
    assert session.results_root == str(tmp_path / "results")
    assert session.enabled == ["batch", "align"]
    assert session.answers == {"b_input": "X"}
    assert session.continue_automatically is True


def test_charter_env_overrides_stored_machine_constants(tmp_path):
    charter = _charter(tmp_path)
    plan = build_plan(session_from_charter(charter), charter)
    env = plan["commands"][0]["env"]
    assert env["RS_INSTANCE"] == "RSAGENT"
    assert env["RS_NO_SETTINGS_INHERITANCE"] == "1"
    assert env["RS_RUN_CHARTER"] == str(charter.path)


def test_unsigned_charter_warns(tmp_path):
    charter = _charter(tmp_path)
    charter.signed_off = {}
    plan = build_plan(session_from_charter(charter), charter)
    assert any("NOT SIGNED OFF" in w for w in plan["warnings"])


# --------------------------------------------------------------- validity

def test_generated_command_parses(tmp_path):
    charter = _charter(tmp_path, answers={"b_input": str(tmp_path),
                                          "r_min_component_size": "50"})
    plan = build_plan(session_from_charter(charter), charter)
    chain = plan["commands"][0]
    assert chain["parses"] is True
    assert "--b_input" in chain["argv"]
    assert "--r_min_component_size" in chain["argv"]
    assert plan["warnings"] == []


def test_validate_command_rejects_an_unknown_flag():
    argv = ["python", "main.py", "--not_a_real_flag", "x"]
    assert validate_command(argv, ["batch"]) is not None


def test_misnamed_answers_are_reported_not_dropped(tmp_path):
    """build_commands filters the answer set against the flags main.py
    accepts - right for the portal, silent data loss for a charter."""
    charter = _charter(tmp_path, answers={"batch_input_image_dir": "X",
                                          "b_input": str(tmp_path)})
    session = session_from_charter(charter)
    plan = build_plan(session, charter)
    assert any("silently dropped" in w and "batch_input_image_dir" in w
               for w in plan["warnings"])
    # The correctly-named answer is NOT reported - it reached the argv.
    assert unreached_answers(session, plan["commands"]) \
        == ["batch_input_image_dir"]


def test_camera_records_are_not_reported_as_dropped(tmp_path):
    """cam_* answers are records the portal deliberately never forwards."""
    session = Session(results_root=str(tmp_path), enabled=["batch"],
                      answers={"cam_Z_name": "Zeuss"})
    assert unreached_answers(session, [{"argv": ["python", "main.py"]}]) == []


def test_empty_answers_are_not_reported_as_dropped(tmp_path):
    session = Session(results_root=str(tmp_path), enabled=["batch"],
                      answers={"b_input": "   "})
    assert unreached_answers(session, [{"argv": ["python", "main.py"]}]) == []


# ----------------------------------------------------------------- shape

def test_every_stage_selection_plans(tmp_path):
    """A plan for each stage individually, and for all of them together."""
    for stages in [[s] for s in ALL_STAGES] + [list(ALL_STAGES)]:
        charter = _charter(tmp_path, stages=stages)
        plan = build_plan(session_from_charter(charter), charter)
        assert plan["stages"] == stages
        for cmd in plan["commands"]:
            assert cmd["argv"] and isinstance(cmd["argv"], list)
            assert cmd["cwd"]
            assert cmd.get("parses") is not False, cmd.get("parse_error")


def test_unknown_stage_is_named(tmp_path):
    charter = _charter(tmp_path, stages=["nope"])
    with pytest.raises(ValueError, match="nope"):
        build_plan(session_from_charter(charter), charter)


def test_missing_results_root_is_named(tmp_path):
    session = Session(enabled=["batch"])
    with pytest.raises(ValueError, match="results root"):
        build_plan(session)


def test_empty_selection_warns(tmp_path):
    session = Session(results_root=str(tmp_path), enabled=[])
    assert any("no stages selected" in w
               for w in build_plan(session)["warnings"])


def test_text_output_is_ascii(tmp_path):
    charter = _charter(tmp_path, stages=list(ALL_STAGES))
    format_text(build_plan(session_from_charter(charter), charter)) \
        .encode("ascii")


# ------------------------------------------------------------------- cli

def test_cli_emits_parseable_json(tmp_path, capsys):
    charter_path = tmp_path / "RUN_CHARTER.json"
    charter_path.write_text(json.dumps(
        _charter_dict(tmp_path, ["batch", "align"], {})), encoding="utf-8")
    out_file = tmp_path / "plan.json"
    assert main(["--charter", str(charter_path), "--json",
                 "--out", str(out_file)]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["schema"] == 1
    assert json.loads(out_file.read_text(encoding="utf-8")) == printed


def test_cli_validate_fails_on_dropped_answers(tmp_path, capsys):
    charter_path = tmp_path / "RUN_CHARTER.json"
    charter_path.write_text(json.dumps(_charter_dict(
        tmp_path, ["batch"], {"batch_input_image_dir": "X"})),
        encoding="utf-8")
    assert main(["--charter", str(charter_path), "--validate"]) == 1
    assert "silently dropped" in capsys.readouterr().out


def test_cli_refuses_charter_and_workspace_together(tmp_path, capsys):
    charter_path = tmp_path / "RUN_CHARTER.json"
    charter_path.write_text(json.dumps(
        _charter_dict(tmp_path, ["batch"], {})), encoding="utf-8")
    assert main(["--charter", str(charter_path),
                 "--workspace", str(tmp_path)]) == 2
    assert "mutually exclusive" in capsys.readouterr().err


def test_cli_workspace_mode(tmp_path, capsys):
    assert main(["--workspace", str(tmp_path / "ws"),
                 "--stages", "merge", "--json"]) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["charter"] is None
    assert plan["stages"] == ["merge"]
