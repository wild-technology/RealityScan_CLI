"""modules.preflight - the missing-data oracle.

Every ``missing`` entry is a question the OWNER must answer; the tests pin
that the oracle asks (never infers) for each intake gap, that a complete
charter is READY, and that a fact making the run unsafe is BLOCKING.
"""
from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.preflight import Preflight, main, preflight_charter  # noqa: E402
from modules.run_charter import TEMPLATE, parse_charter  # noqa: E402

KNOWN = ["P231C0001_20250705T020039Z.jpg", "P231C0002_20250705T020040Z.jpg",
         "C231C0001_20250705T020039Z.jpg"]


def _dataset(tmp_path, *, unknown_camera=False):
    originals = tmp_path / "originals"
    originals.mkdir()
    for name in KNOWN:
        (originals / name).write_bytes(b"jpg")
    if unknown_camera:
        (originals / "XYZ_0001.jpg").write_bytes(b"jpg")
    nav = tmp_path / "nav" / "H2060_final_datatable.csv"
    nav.parent.mkdir()
    nav.write_text("t,x,y\n", encoding="utf-8")
    return originals, nav


def _charter(tmp_path, originals, nav, *, stages=("georeference", "batch", "align"),
             answers=None, signed=True, budget=True, instance="RSAGENT",
             cache="cache", frame="utm:54N", protected=True, path=None):
    data = {
        "schema": 1, "campaign": "NA165", "dive": "H2060",
        "locations": {
            "originals": [str(originals)], "nav": [str(nav)],
            "results_root": str(tmp_path / "results"),
            "agent_workspace": str(tmp_path / "results" / "_agent"),
            "protected": ([{"path": str(tmp_path / "keep"), "why": "prior deliverables"}]
                          if protected else []),
        },
        "ownership": {"rs_instance": instance,
                      "rs_cache_dir": str(tmp_path / cache) if cache else "",
                      "user_instances": ["RS1"]},
        "budget": ({"expected_hours": 4, "memory_peak_gb": 64,
                    "disk_delta_gb": 10, "free_disk_gb_now": 500,
                    "abort_criteria": "disk < 50 GB"} if budget else
                   {"expected_hours": 0, "memory_peak_gb": 0, "disk_delta_gb": 0,
                    "abort_criteria": "<disk floor / silence window / memory line>"}),
        "science": {"frame": frame, "align_settings_xml": "",
                    "min_component_size": 50, "notes": "explicit"},
        "pipeline": {"stages": list(stages),
                     # b_input is a REAL requirement for georeference+batch
                     # without preprocess (batch's input is handed over
                     # in-process only from Extract or Preprocess); the
                     # oracle's first run against this fixture caught its
                     # absence - exactly the gap it exists to catch.
                     "answers": dict(answers if answers is not None else {
                         "g_input": str(originals), "g_flight_log": str(nav),
                         "g_type": "WCA", "b_input": str(originals)})},
        "signed_off": ({"by": "owner", "date": "2026-09-05", "quote": "go"}
                       if signed else {"by": "", "date": "", "quote": ""}),
    }
    p = path or (tmp_path / "RUN_CHARTER.json")
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return parse_charter(data, p)


def _keys(report):
    return [m["key"] for m in report["missing"]]


def test_complete_charter_is_ready(tmp_path):
    originals, nav = _dataset(tmp_path)
    report = preflight_charter(_charter(tmp_path, originals, nav))
    assert report["missing"] == [], report["missing"]
    assert report["blocking"] == [], report["blocking"]
    assert report["verdict"] == "ready"
    assert report["plan_commands"] == 1          # one chained main.py command
    assert any("every required answer" in c for c in report["checked"])


def test_template_charter_asks_every_intake_question(tmp_path):
    data = json.loads(json.dumps(TEMPLATE))
    data["locations"]["results_root"] = str(tmp_path / "out")
    data["locations"]["agent_workspace"] = str(tmp_path / "out" / "_agent")
    p = tmp_path / "RUN_CHARTER.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    report = preflight_charter(parse_charter(data, p))
    keys = _keys(report)
    for expected in ("signed_off", "locations.originals", "locations.nav",
                     "ownership.rs_instance", "ownership.rs_cache_dir",
                     "budget", "budget.abort_criteria", "science.frame"):
        assert expected in keys, (expected, keys)
    assert report["verdict"] == "not_ready"
    # every missing entry carries the question to ask, verbatim
    assert all(m["question"].strip() and m["why"].strip() for m in report["missing"])


def test_unsigned_charter_asks_for_signoff_only(tmp_path):
    originals, nav = _dataset(tmp_path)
    report = preflight_charter(_charter(tmp_path, originals, nav, signed=False))
    assert _keys(report) == ["signed_off"]


def test_missing_source_path_is_a_question_not_an_inference(tmp_path):
    originals, nav = _dataset(tmp_path)
    charter = _charter(tmp_path, originals, nav)
    charter.originals = [str(tmp_path / "does_not_exist")]
    report = preflight_charter(charter)
    assert "locations.originals" in _keys(report)
    assert "does not exist" in next(m for m in report["missing"]
                                    if m["key"] == "locations.originals")["question"]


def test_wildcard_or_owner_instance_is_refused(tmp_path):
    originals, nav = _dataset(tmp_path)
    report = preflight_charter(_charter(tmp_path, originals, nav, instance="*"))
    assert "ownership.rs_instance" in _keys(report)
    report = preflight_charter(_charter(tmp_path, originals, nav, instance="RS1"))
    assert any("USER" in b or "owner instance" in b for b in report["blocking"])


def test_realityscan_stage_needs_a_budget_but_a_prep_stage_does_not(tmp_path):
    originals, nav = _dataset(tmp_path)
    report = preflight_charter(_charter(tmp_path, originals, nav, budget=False))
    assert "budget" in _keys(report) and "budget.abort_criteria" in _keys(report)
    # b_input reaches no command in a georeference-only plan, and an
    # answer the owner wrote must never be dropped in silence - so the
    # prep-only charter carries only the answers that plan consumes.
    prep_only = _charter(tmp_path, originals, nav, budget=False,
                         stages=("georeference",), frame="",
                         answers={"g_input": str(originals),
                                  "g_flight_log": str(nav), "g_type": "WCA"})
    report = preflight_charter(prep_only)
    assert "budget" not in _keys(report)
    assert "science.frame" not in _keys(report)   # only align needs a frame
    assert report["verdict"] == "ready", report


def test_required_answer_missing_or_invalid_is_asked_with_the_modules_own_prompt(tmp_path):
    originals, nav = _dataset(tmp_path)
    charter = _charter(tmp_path, originals, nav,
                       answers={"g_input": str(tmp_path / "nowhere"),
                                "g_flight_log": str(nav),
                                "b_input": str(originals)})
    report = preflight_charter(charter)
    keys = _keys(report)
    assert "pipeline.answers.g_type" in keys          # required, absent
    assert "pipeline.answers.g_input" in keys         # present but not a directory
    bad = next(m for m in report["missing"] if m["key"] == "pipeline.answers.g_input")
    assert "is not a directory" in bad["question"]
    assert "georeference" in bad["why"]


def test_unknown_camera_prefix_is_a_question_never_an_assumed_mount(tmp_path):
    originals, nav = _dataset(tmp_path, unknown_camera=True)
    report = preflight_charter(_charter(tmp_path, originals, nav))
    assert "cameras.xyz" in _keys(report)
    q = next(m for m in report["missing"] if m["key"] == "cameras.xyz")
    assert "nothing is invented" in q["question"]
    assert report["verdict"] == "not_ready"


def test_known_cameras_pass_and_are_listed_as_checked(tmp_path):
    originals, nav = _dataset(tmp_path)
    report = preflight_charter(_charter(tmp_path, originals, nav))
    assert any("camera family 'wca_port'" in c for c in report["checked"])
    assert not any(k.startswith("cameras.") for k in _keys(report))


def test_frame_disagreement_between_log_tag_and_science_blocks(tmp_path):
    originals, nav = _dataset(tmp_path)
    tagged = tmp_path / "flight_log_54N_UTM.txt"
    tagged.write_text("x\n", encoding="utf-8")
    charter = _charter(tmp_path, originals, nav, stages=("align",), frame="local_euclidean",
                       answers={"r_input": str(originals), "r_flight_log": str(tagged)})
    report = preflight_charter(charter)
    assert any("frames disagree" in b for b in report["blocking"])


def test_empty_or_unknown_stage_list_is_asked(tmp_path):
    originals, nav = _dataset(tmp_path)
    report = preflight_charter(_charter(tmp_path, originals, nav, stages=()))
    assert "pipeline.stages" in _keys(report)
    report = preflight_charter(_charter(tmp_path, originals, nav, stages=("bogus",)))
    assert "pipeline.stages" in _keys(report)


def test_cli_exit_codes_and_json(tmp_path, capsys):
    originals, nav = _dataset(tmp_path)
    charter = _charter(tmp_path, originals, nav)
    assert main(["--charter", str(charter.path), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["verdict"] == "ready"
    unsigned = _charter(tmp_path, originals, nav, signed=False,
                        path=tmp_path / "unsigned.json")
    assert main(["--charter", str(unsigned.path)]) == 1
    out = capsys.readouterr().out
    assert "ASK THE OWNER" in out and "signed_off" in out
    assert out.isascii()
    bad = tmp_path / "bad.json"
    bad.write_text("{}", encoding="utf-8")
    assert main(["--charter", str(bad)]) == 2


def test_report_is_read_only(tmp_path):
    originals, nav = _dataset(tmp_path)
    charter = _charter(tmp_path, originals, nav)
    before = sorted(str(p) for p in tmp_path.rglob("*"))
    Preflight(charter).run()
    assert sorted(str(p) for p in tmp_path.rglob("*")) == before


def test_an_answer_that_reaches_no_command_blocks(tmp_path):
    """An owner-written answer that no planned command consumes is named
    and BLOCKS - the run must never proceed pretending it was applied."""
    originals, nav = _dataset(tmp_path)
    charter = _charter(tmp_path, originals, nav, stages=("georeference",),
                       frame="", answers={"g_input": str(originals),
                                          "g_flight_log": str(nav),
                                          "g_type": "WCA",
                                          "b_input": str(originals)})
    report = preflight_charter(charter)
    assert any("silently dropped" in b and "b_input" in b for b in report["blocking"])
    assert report["verdict"] == "not_ready"


# ------------------------------------- modules, scripts, metadata, hooks

def test_repo_metadata_and_scripts_pass_for_every_realityscan_stage(tmp_path):
    """The shipped presets and workflows are the ones the check validates -
    a regression guard on the repo itself."""
    originals, nav = _dataset(tmp_path)
    for stage in ("align", "merge", "model", "export"):
        answers = {"r_input": str(originals)} if stage == "align" else {}
        report = preflight_charter(_charter(tmp_path, originals, nav,
                                            stages=(stage,), answers=answers,
                                            frame="utm:54N"))
        assert not [b for b in report["blocking"]
                    if "metadata" in b or "workflow script" in b
                    or "format file" in b], (stage, report["blocking"])
        assert any("metadata preset" in c for c in report["checked"]), stage
        assert any("workflow script" in c for c in report["checked"]), stage


def test_missing_or_invalid_metadata_preset_blocks(tmp_path, monkeypatch):
    import modules.preflight as pf
    meta = tmp_path / "Metadata"
    meta.mkdir()
    monkeypatch.setattr(pf, "METADATA_DIR", str(meta))
    originals, nav = _dataset(tmp_path)
    charter = _charter(tmp_path, originals, nav, stages=("export",))
    report = preflight_charter(charter)
    assert sum("metadata preset missing" in b for b in report["blocking"]) == 3
    (meta / "ModelExportParamsOBJ_NiraParts.xml").write_text("<Configuration><entry key='x'", encoding="utf-8")
    report = preflight_charter(charter)
    assert any("metadata preset invalid" in b for b in report["blocking"])


def test_alignment_preset_with_app_key_or_wrong_frame_blocks(tmp_path, monkeypatch):
    import modules.preflight as pf
    import shutil
    meta = tmp_path / "Metadata"
    shutil.copytree(pf.METADATA_DIR, meta)
    monkeypatch.setattr(pf, "METADATA_DIR", str(meta))
    (meta / "AlignmentParams.xml").write_text(
        '<Configuration><entry key="sfmMaxFeaturesPerImage" value="1"/>'
        '<entry key="appQuitOnError" value="true"/></Configuration>', encoding="utf-8")
    # swap the two frame templates: each now declares the other's frame
    utm = (meta / "FlightLogParams.xml").read_text(encoding="utf-8")
    local = (meta / "FlightLogParamsLocal.xml").read_text(encoding="utf-8")
    (meta / "FlightLogParams.xml").write_text(local, encoding="utf-8")
    (meta / "FlightLogParamsLocal.xml").write_text(utm, encoding="utf-8")
    originals, nav = _dataset(tmp_path)
    report = preflight_charter(_charter(tmp_path, originals, nav, stages=("align",),
                                        answers={"r_input": str(originals)}))
    blocking = "\n".join(report["blocking"])
    assert "app-global key" in blocking and "appQuitOnError" in blocking
    assert "declares frame 'local_euclidean', expected 'utm'" in blocking
    assert "declares frame 'utm', expected 'local_euclidean'" in blocking


def test_unknown_format_guid_blocks(tmp_path, monkeypatch):
    import modules.preflight as pf
    import shutil
    meta = tmp_path / "Metadata"
    shutil.copytree(pf.METADATA_DIR, meta)
    monkeypatch.setattr(pf, "METADATA_DIR", str(meta))
    path = meta / "RegistrationExportParams.xml"
    text = path.read_text(encoding="utf-8").replace("E7C3B1A9", "00000000")
    path.write_text(text, encoding="utf-8")
    originals, nav = _dataset(tmp_path)
    report = preflight_charter(_charter(tmp_path, originals, nav, stages=("align",),
                                        answers={"r_input": str(originals)}))
    assert any("calibration.xml does not define" in b for b in report["blocking"])


def test_missing_python_module_blocks(tmp_path, monkeypatch):
    import modules.preflight as pf
    monkeypatch.setitem(pf.STAGE_IMPORTS, "georeference",
                        ("modules.georeference.georeference_images",
                         "no_such_module_rs_preflight"))
    originals, nav = _dataset(tmp_path)
    report = preflight_charter(_charter(tmp_path, originals, nav,
                                        stages=("georeference",), frame=""))
    assert any("no_such_module_rs_preflight" in b and "does not import" in b
               for b in report["blocking"])


def test_lf_workflow_script_blocks(tmp_path, monkeypatch):
    import modules.preflight as pf
    import shutil
    scripts = tmp_path / "Scripts"
    shutil.copytree(pf.SCRIPTS_DIR, scripts)
    monkeypatch.setattr(pf, "SCRIPTS_DIR", str(scripts))
    bat = scripts / "GenerateModel.bat"
    bat.write_bytes(bat.read_bytes().replace(b"\r\n", b"\n"))
    originals, nav = _dataset(tmp_path)
    report = preflight_charter(_charter(tmp_path, originals, nav, stages=("model",)))
    assert any("not CRLF" in b and "GenerateModel.bat" in b for b in report["blocking"])
