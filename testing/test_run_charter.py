"""modules.run_charter - the run contract as data, and its guards.

docs/AGENT_OPERATIONS.md's touch rules used to hold only while an agent
remembered them. These tests are the proof they now hold mechanically:
source data is read-only forever, protected paths are never touched,
outputs go under the results root, and the agent drives only its own
RealityScan instance.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from module_base.settings_store import SettingsStore, inheritance_refused
from modules.run_charter import (CHARTER_ENV, NO_INHERIT_ENV, CharterError,
                                 CharterViolation, REPO_ROOT, active_charter,
                                 guard_instance, guard_write, load_charter,
                                 main, parse_charter)


def _charter_dict(tmp_path, **overrides):
    data = {
        "schema": 1,
        "campaign": "ON2026",
        "dive": "RH0042",
        "locations": {
            "originals": [str(tmp_path / "src")],
            "nav": [str(tmp_path / "nav" / "flight_log.txt")],
            "results_root": str(tmp_path / "results"),
            "agent_workspace": str(tmp_path / "results" / "_agent"),
            "protected": [{"path": str(tmp_path / "results" / "final"),
                           "why": "delivered to the client"}],
        },
        "ownership": {"rs_instance": "RSAGENT",
                      "rs_cache_dir": str(tmp_path / "cache"),
                      "user_instances": ["RS1"]},
        "pipeline": {"stages": ["batch", "align"], "answers": {}},
        "signed_off": {"by": "owner", "date": "2026-08-31"},
    }
    data.update(overrides)
    return data


def _write(tmp_path, data=None, name="RUN_CHARTER.json"):
    path = tmp_path / name
    path.write_text(json.dumps(data or _charter_dict(tmp_path), indent=2),
                    encoding="utf-8")
    return path


# ------------------------------------------------------------ validation

def test_valid_charter_round_trips(tmp_path):
    charter = load_charter(_write(tmp_path))
    assert charter.label == "ON2026_RH0042"
    assert charter.rs_instance == "RSAGENT"
    assert charter.is_signed()
    assert len(charter.read_only_paths) == 3


def test_unsupported_schema_is_refused(tmp_path):
    with pytest.raises(CharterError, match="schema"):
        parse_charter(_charter_dict(tmp_path, schema=99))


def test_missing_results_root_is_refused(tmp_path):
    data = _charter_dict(tmp_path)
    del data["locations"]["results_root"]
    with pytest.raises(CharterError, match="results_root"):
        parse_charter(data)


def test_results_root_inside_source_is_refused(tmp_path):
    """Outputs under the originals would make every write a source write."""
    data = _charter_dict(tmp_path)
    data["locations"]["results_root"] = str(tmp_path / "src" / "out")
    # Move the agent workspace along with it, so this isolates the
    # source-containment check rather than the workspace-containment one.
    data["locations"]["agent_workspace"] = str(tmp_path / "src" / "out"
                                               / "_agent")
    with pytest.raises(CharterError, match="inside the read-only source"):
        parse_charter(data)


def test_agent_workspace_must_live_under_results(tmp_path):
    data = _charter_dict(tmp_path)
    data["locations"]["agent_workspace"] = str(tmp_path / "elsewhere")
    with pytest.raises(CharterError, match="agent_workspace"):
        parse_charter(data)


def test_agent_workspace_defaults_under_results(tmp_path):
    data = _charter_dict(tmp_path)
    del data["locations"]["agent_workspace"]
    charter = parse_charter(data)
    assert charter.agent_workspace.endswith("_agent")


def test_malformed_blocks_are_named(tmp_path):
    for key, value, match in (
            ("protected", ["not-an-object"], "protected"),
            ("originals", [1, 2], "originals"),
    ):
        data = _charter_dict(tmp_path)
        data["locations"][key] = value
        with pytest.raises(CharterError, match=match):
            parse_charter(data)
    data = _charter_dict(tmp_path)
    data["pipeline"] = {"answers": []}
    with pytest.raises(CharterError, match="pipeline.answers"):
        parse_charter(data)


def test_missing_file_is_named(tmp_path):
    with pytest.raises(CharterError, match="not found"):
        load_charter(tmp_path / "nope.json")


# ---------------------------------------------------------- write guards

def test_write_guard_allows_results_and_repo(tmp_path):
    charter = parse_charter(_charter_dict(tmp_path))
    charter.assert_writable(tmp_path / "results" / "aligned" / "z.json")
    charter.assert_writable(REPO_ROOT / "modules" / "verify.py")


@pytest.mark.parametrize("relative,expected", [
    (("src", "IMG_0001.jpg"), "SOURCE DATA"),
    (("nav", "flight_log.txt"), "NAV"),
    (("results", "final", "hull.obj"), "PROTECTED"),
    (("somewhere_else", "x.txt"), "outside every writable root"),
])
def test_write_guard_refuses(tmp_path, relative, expected):
    charter = parse_charter(_charter_dict(tmp_path))
    target = tmp_path.joinpath(*relative)
    assert expected in (charter.why_forbidden(target) or "")
    with pytest.raises(CharterViolation):
        charter.assert_writable(target)


def test_protection_wins_over_containment(tmp_path):
    """A protected tree nested INSIDE the results root stays protected."""
    charter = parse_charter(_charter_dict(tmp_path))
    protected = tmp_path / "results" / "final" / "deliverable.obj"
    assert "PROTECTED" in charter.why_forbidden(protected)


def test_write_guard_is_case_insensitive(tmp_path):
    """NTFS is case-insensitive; a case-sensitive prefix test would wave
    the same tree through under a different spelling."""
    charter = parse_charter(_charter_dict(tmp_path))
    shouty = str(tmp_path / "SRC" / "IMG.JPG").upper()
    assert charter.why_forbidden(shouty) is not None


# ------------------------------------------------------- instance guards

def test_instance_guard(tmp_path):
    charter = parse_charter(_charter_dict(tmp_path))
    charter.assert_instance("RSAGENT")
    with pytest.raises(CharterViolation, match="USER-OWNED"):
        charter.assert_instance("RS1")
    with pytest.raises(CharterViolation, match="not the charter's instance"):
        charter.assert_instance("RS7")


# ----------------------------------------------------------- environment

def test_charter_env_pins_the_strict_lane(tmp_path):
    charter = load_charter(_write(tmp_path))
    env = charter.env()
    assert env[NO_INHERIT_ENV] == "1"
    assert env["RS_INSTANCE"] == "RSAGENT"
    assert env[CHARTER_ENV] == str(charter.path)


def test_active_charter_and_module_guards(tmp_path, monkeypatch):
    path = _write(tmp_path)
    monkeypatch.delenv(CHARTER_ENV, raising=False)
    assert active_charter() is None
    guard_write(tmp_path / "anywhere")           # no charter -> no-op
    guard_instance("RS_WHATEVER")

    monkeypatch.setenv(CHARTER_ENV, str(path))
    assert active_charter().rs_instance == "RSAGENT"
    guard_write(tmp_path / "results" / "ok.txt")
    with pytest.raises(CharterViolation):
        guard_write(tmp_path / "src" / "IMG.jpg")
    with pytest.raises(CharterViolation):
        guard_instance("RS1")


def test_set_but_broken_charter_raises(tmp_path, monkeypatch):
    """The dangerous state: an agent that believes it is constrained
    while nothing is checking."""
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    monkeypatch.setenv(CHARTER_ENV, str(bad))
    with pytest.raises(CharterError):
        active_charter()


# ------------------------------------------- settings-inheritance refusal

def test_strict_mode_refuses_stored_answers(tmp_path, monkeypatch, capsys):
    """The cross-campaign incident: last run's path silently reused."""
    store_path = tmp_path / "rs_settings.json"
    store_path.write_text(json.dumps(
        {"merge": {"components_root": "M:/OLD_CAMPAIGN/aligned"}}),
        encoding="utf-8")

    monkeypatch.delenv(NO_INHERIT_ENV, raising=False)
    assert inheritance_refused() is False
    lenient = SettingsStore(str(store_path))
    assert lenient.ask("merge", "components_root", None, None) \
        == "M:/OLD_CAMPAIGN/aligned"

    monkeypatch.setenv(NO_INHERIT_ENV, "1")
    assert inheritance_refused() is True
    strict = SettingsStore(str(store_path))
    with pytest.raises(ValueError, match=NO_INHERIT_ENV):
        strict.ask("merge", "components_root", None, None)
    assert "REFUSING stored default" in capsys.readouterr().out

    # An explicit value and a code-supplied fallback both still work -
    # the hazard is history answering a prompt, not defaults existing.
    assert strict.ask("merge", "components_root", "M:/NEW", None) == "M:/NEW"
    assert strict.ask("merge", "min_size", None, 50) == 50


def test_strict_mode_leaves_plain_get_alone(tmp_path, monkeypatch):
    """`get` is how code reads machine constants on purpose; only PROMPTS
    are gated."""
    store_path = tmp_path / "rs_settings.json"
    store_path.write_text(json.dumps({"realityscan": {"cache_dir": "E:/c"}}),
                          encoding="utf-8")
    monkeypatch.setenv(NO_INHERIT_ENV, "1")
    assert SettingsStore(str(store_path)).get("realityscan", "cache_dir") \
        == "E:/c"


# ------------------------------------------------------------------- cli

def test_cli_init_validate_and_check(tmp_path, capsys):
    out = tmp_path / "new" / "RUN_CHARTER.json"
    assert main(["--init", str(out)]) == 0
    assert out.is_file()
    assert main(["--init", str(out)]) == 2          # never overwrite
    capsys.readouterr()

    path = _write(tmp_path)
    assert main(["--validate", str(path)]) == 0
    assert main(["--check", str(path), "--path",
                 str(tmp_path / "src" / "x.jpg")]) == 2
    assert main(["--check", str(path), "--instance", "RSAGENT"]) == 0
    capsys.readouterr()


def test_cli_validate_warns_when_unsigned(tmp_path, capsys):
    data = _charter_dict(tmp_path)
    data["signed_off"] = {}
    assert main(["--validate", str(_write(tmp_path, data))]) == 1
    assert "NOT SIGNED OFF" in capsys.readouterr().out
