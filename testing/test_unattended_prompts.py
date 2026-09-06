"""Prompts never self-answer in silence and never block unattended.

PRODUCT_READINESS must-fix 11/12, closed 2026-09-05: under RS_NO_INTERACTIVE
or an active charter, every prompt path either takes a value it is allowed
to take and SAYS so, or fails naming the flag. ``input()`` is patched to
raise so any prompt that still blocks is a test failure, not a hang.
"""
from __future__ import annotations

import builtins
import logging
import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import main as main_mod  # noqa: E402
from module_base.settings_store import SettingsStore, unattended  # noqa: E402
from module_base.parameter import Parameter  # noqa: E402


@pytest.fixture
def no_input(monkeypatch):
    def _boom(*_a, **_k):
        raise AssertionError("input() was called on an unattended run")
    monkeypatch.setattr(builtins, "input", _boom)


@pytest.fixture
def log(caplog):
    """A fresh, propagating logger at INFO. test_rig_mounts leaves
    logging.disable(CRITICAL) armed for the rest of the session, so caplog
    alone saw nothing and these tests were order-dependent (2026-09-05)."""
    logging.disable(logging.NOTSET)
    name = "rs.test.unattended"
    logger = logging.getLogger(name)
    logger.propagate = True
    logger.setLevel(logging.INFO)
    caplog.set_level(logging.INFO, logger=name)
    return logger


def _store(tmp_path, data=None):
    store = SettingsStore(str(tmp_path / "s.json"))
    for section, key, value in data or []:
        store.set(section, key, value)
    return store


def test_unattended_is_declared_not_guessed(monkeypatch):
    assert not unattended()
    monkeypatch.setenv("RS_NO_INTERACTIVE", "1")
    assert unattended()
    monkeypatch.delenv("RS_NO_INTERACTIVE")
    monkeypatch.setenv("RS_RUN_CHARTER", "/x/RUN_CHARTER.json")
    assert unattended()


def test_ask_unattended_announces_a_stored_value(tmp_path, monkeypatch, no_input, capsys):
    monkeypatch.setenv("RS_NO_INTERACTIVE", "1")
    store = _store(tmp_path, [("merge", "min_size", 70)])
    assert store.ask("merge", "min_size", None, 50) == 70
    assert "UNATTENDED: merge.min_size = 70 (stored answer)" in capsys.readouterr().out


def test_ask_unattended_announces_a_code_default(tmp_path, monkeypatch, no_input, capsys):
    monkeypatch.setenv("RS_NO_INTERACTIVE", "1")
    assert _store(tmp_path).ask("merge", "min_size", None, 50) == 50
    assert "(code default)" in capsys.readouterr().out


def test_ask_unattended_with_nothing_fails_by_name(tmp_path, monkeypatch, no_input):
    monkeypatch.setenv("RS_NO_INTERACTIVE", "1")
    with pytest.raises(ValueError, match="merge.components_root"):
        _store(tmp_path).ask("merge", "components_root", None, None)


def test_charter_lane_refuses_stored_and_takes_code_default(tmp_path, monkeypatch, no_input, capsys):
    monkeypatch.setenv("RS_RUN_CHARTER", str(tmp_path / "c.json"))
    monkeypatch.setenv("RS_NO_SETTINGS_INHERITANCE", "1")
    store = _store(tmp_path, [("merge", "min_size", 70)])
    assert store.ask("merge", "min_size", None, 50) == 50
    out = capsys.readouterr().out
    assert "REFUSING stored default merge.min_size=70" in out


def test_prompt_and_prompt_bool_unattended(tmp_path, monkeypatch, no_input, capsys):
    monkeypatch.setenv("RS_NO_INTERACTIVE", "1")
    store = _store(tmp_path)
    assert store.prompt("geoall", "output_dir", "Output dir", "/tmp/out") == "/tmp/out"
    assert store.prompt_bool("geoall", "verbose", "Verbose", True) is True
    assert "UNATTENDED" in capsys.readouterr().out
    with pytest.raises(ValueError, match="UNATTENDED"):
        store.prompt("geoall", "image_base_dir", "Images")


def test_rs_settings_path_env_relocates_the_store(tmp_path, monkeypatch):
    target = tmp_path / "elsewhere" / "rs_settings.json"
    target.parent.mkdir()
    monkeypatch.setenv("RS_SETTINGS_PATH", str(target))
    store = SettingsStore()
    store.set("a", "b", 1)
    assert target.is_file()
    assert SettingsStore(str(target)).get("a", "b") == 1


# ------------------------------------------------------------- main.py

def _params():
    return {
        "output_dir": Parameter("Output Directory", "o", "output_dir", str, None,
                                "Path to the output directory", True),
        "g_type": Parameter("Data type", "g_t", "g_type", str, None,
                            "Zeuss/WCA/WCA2025/All", True),
        "overlap": Parameter("Overlap", "b_o", "b_overlap_percent", float, 20.0,
                             "Overlap percent", True),
    }


def test_main_unattended_fails_by_flag_when_required_and_unanswered(tmp_path, monkeypatch, no_input, caplog, log):
    monkeypatch.setenv("RS_NO_INTERACTIVE", "1")
    params = _params()
    with pytest.raises(SystemExit) as exc:
        main_mod.parse_arguments(["main.py", "--output_dir", str(tmp_path)],
                                 params, log)
    assert exc.value.code == 2
    assert "--g_type" in caplog.text and "UNATTENDED" in caplog.text


def test_main_unattended_takes_declared_default_and_announces_stored(tmp_path, monkeypatch, no_input, caplog, log):
    monkeypatch.setenv("RS_NO_INTERACTIVE", "1")
    store = SettingsStore()                      # conftest points this at tmp
    store.set("main", "g_type", "WCA")
    params = _params()
    main_mod.parse_arguments(["main.py", "--output_dir", str(tmp_path)],
                             params, log)
    assert params["g_type"].get_value() == "WCA"
    assert params["g_type"].is_explicit()
    assert params["overlap"].get_value() == 20.0
    assert not params["overlap"].is_explicit()
    assert "stored answer" in caplog.text and "declared default" in caplog.text


def test_main_charter_lane_refuses_stored_answer(tmp_path, monkeypatch, no_input, caplog, log):
    monkeypatch.setenv("RS_RUN_CHARTER", str(tmp_path / "c.json"))
    monkeypatch.setenv("RS_NO_SETTINGS_INHERITANCE", "1")
    SettingsStore().set("main", "g_type", "WCA")
    with pytest.raises(SystemExit) as exc:
        main_mod.parse_arguments(["main.py", "--output_dir", str(tmp_path)],
                                 _params(), log)
    assert exc.value.code == 2 and "--g_type" in caplog.text


def test_main_no_interactive_skips_the_between_stage_gate(monkeypatch):
    monkeypatch.setenv("RS_NO_INTERACTIVE", "yes")
    assert main_mod._no_interactive()


def test_inquirer_is_not_imported_at_module_level():
    source = open(os.path.join(REPO, "main.py"), encoding="utf-8").read()
    head = source.split("def initialize_modules")[0]
    assert "import inquirer" not in head


# ------------------------------------------------------- small scripts

def test_batcher_default_honours_the_inheritance_refusal(tmp_path, monkeypatch):
    from modules.image_batcher.batch_directory import BatchDirectory
    module = BatchDirectory(logging.getLogger("t"))
    module.settings = SettingsStore(str(tmp_path / "s.json"))
    module.settings.set("batch", "min_zone_size", 300)
    assert module._stored_default("min_zone_size", 1000, None) == 300
    monkeypatch.setenv("RS_NO_SETTINGS_INHERITANCE", "1")
    assert module._stored_default("min_zone_size", 1000, None) == 1000
    assert module._stored_default("min_zone_size", 1000, 2000) == 2000


def test_decimator_yes_copies_and_eof_cancels(tmp_path, monkeypatch, capsys):
    import decimator
    src = tmp_path / "src"
    src.mkdir()
    for i in range(10):
        (src / f"img_{i:02d}.jpg").write_bytes(b"x")
    dest = tmp_path / "dest"
    assert decimator.main(["--source", str(src), "--dest", str(dest),
                           "--keep", "50", "--yes"]) == 0
    assert len(list(dest.iterdir())) == 5
    dest2 = tmp_path / "dest2"

    def _eof(*_a, **_k):
        raise EOFError
    monkeypatch.setattr(builtins, "input", _eof)
    assert decimator.main(["--source", str(src), "--dest", str(dest2),
                           "--keep", "50"]) == 1
    assert not dest2.exists()
    assert "no --yes" in capsys.readouterr().out


def test_timestamp_rename_yes_renames_and_eof_cancels(tmp_path, monkeypatch, capsys):
    import timestamp_rename
    from PIL import Image
    d = tmp_path / "imgs"
    d.mkdir()
    Image.new("RGB", (2, 2)).save(d / "cammid_20250524T103743Z.jpg")

    def _eof(*_a, **_k):
        raise EOFError
    monkeypatch.setattr(builtins, "input", _eof)
    timestamp_rename.process_directory(str(d))
    assert (d / "cammid_20250524T103743Z.jpg").exists()
    assert "cancelled" in capsys.readouterr().out
    timestamp_rename.process_directory(str(d), assume_yes=True)
    assert (d / "20250524T103743Z_cammid.jpg").exists()


def test_geoall_has_no_hardcoded_data_paths_and_names_the_missing_flags(capsys):
    import geoall
    assert geoall.DEFAULT_IMAGE_BASE_DIR is None
    assert geoall.DEFAULT_ROV_DATA_DIR is None
    assert geoall.DEFAULT_OUTPUT_DIR is None
    assert geoall.main([]) == 2
    out = capsys.readouterr().out
    assert "--image-base-dir" in out and "--rov-data-dir" in out
