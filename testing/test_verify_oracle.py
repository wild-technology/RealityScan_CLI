"""modules.verify - the workspace oracle.

The oracle is the thing every other check now trusts, so it gets the
treatment CLAUDE.md demands of any detector: verified against a
known-good AND a known-bad case before anything relies on it. The
known-bad cases here are the ones a camera-count census reports as
healthy - disagreeing nav between zones, a missing fingerprint, a
component whose measured scale is not metric.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.verify import (EXIT_CODES, SCALE_MAX, SCALE_MIN, format_text,
                            main, verify_workspace)


# --------------------------------------------------------------- fixtures

def _zone(ws, name, *, cameras=3, nav_sha="aaa", settings_sha="zzz",
          frame="utm", fingerprint=True):
    """One aligned zone: images, a component, its manifest, its fingerprint."""
    batched = ws / "batched_images_by_zone" / name
    batched.mkdir(parents=True, exist_ok=True)
    for i in range(cameras):
        (batched / f"IMG_{i}.jpg").write_bytes(b"x")

    aligned = ws / "aligned_components" / name
    aligned.mkdir(parents=True, exist_ok=True)
    (aligned / f"{name}_c0.rsalign").write_bytes(b"x")
    (aligned / f"{name}_c0.rsalign.manifest.json").write_text(json.dumps(
        {"schema": 1, "zone": name, "component": f"{name}_c0",
         "camera_count": cameras}), encoding="utf-8")
    if fingerprint:
        (aligned / "align_inputs.json").write_text(json.dumps(
            {"schema": 1, "frame": frame,
             "flight_log": {"sha256": nav_sha},
             "align_settings": {"sha256": settings_sha},
             "flight_log_params": {"sha256": "ppp"},
             "min_component_size": 10}), encoding="utf-8")


def _workspace(tmp_path, zones=("zone_1", "zone_2"), **kw):
    ws = tmp_path / "ws"
    raw = ws / "raw_images"
    raw.mkdir(parents=True)
    for i in range(6):
        (raw / f"IMG_{i}.jpg").write_bytes(b"x")
    (raw / "flight_log_54N_UTM.txt").write_text(
        "hdr\n" + "\n".join(f"r{i}" for i in range(6)), encoding="utf-8")
    (ws / "batched_images_by_zone").mkdir(parents=True, exist_ok=True)
    (ws / "batched_images_by_zone" / "batch_inputs.json").write_text(
        '{"schema": 1}', encoding="utf-8")
    for z in zones:
        _zone(ws, z, **kw)
    return ws


# ------------------------------------------------------------ known-good

def test_healthy_workspace_is_ok(tmp_path):
    ws = _workspace(tmp_path)
    out = verify_workspace(str(ws))
    assert out["verdict"] == "ok", out["blocking"]
    assert out["blocking"] == []
    assert out["counts"]["zones_aligned"] == 2
    assert out["counts"]["zones_without_fingerprint"] == 0
    assert out["provenance"]["frame_unanimous"] is True
    # The started stages are required by default; nothing pending is.
    assert "align" in out["required"]
    assert "merge" not in out["required"]


def test_missing_workspace_is_absent(tmp_path):
    out = verify_workspace(str(tmp_path / "nope"))
    assert out["verdict"] == "absent"
    assert out["exists"] is False
    assert out["blocking"]


# ------------------------------------------------------------- known-bad

def test_disagreeing_nav_between_zones_blocks(tmp_path):
    """The case a camera-count census calls healthy."""
    ws = _workspace(tmp_path, zones=())
    _zone(ws, "zone_1", nav_sha="aaa")
    _zone(ws, "zone_2", nav_sha="bbb")
    out = verify_workspace(str(ws))
    assert out["verdict"] == "blocked"
    assert any("navigation flight log DIFFERS" in b for b in out["blocking"])
    # ... and the census itself still reports the align stage as done,
    # which is exactly why this check cannot live in the census.
    assert out["stages"]["align"]["status"] == "done"


def test_disagreeing_settings_between_zones_blocks(tmp_path):
    ws = _workspace(tmp_path, zones=())
    _zone(ws, "zone_1", settings_sha="one")
    _zone(ws, "zone_2", settings_sha="two")
    out = verify_workspace(str(ws))
    assert out["verdict"] == "blocked"
    assert any("alignment settings XML DIFFERS" in b for b in out["blocking"])


def test_mixed_frames_block(tmp_path):
    ws = _workspace(tmp_path, zones=())
    _zone(ws, "zone_1", frame="utm")
    _zone(ws, "zone_2", frame="local_euclidean")
    out = verify_workspace(str(ws))
    assert out["verdict"] == "blocked"
    assert any("COORDINATE FRAMES DISAGREE" in b for b in out["blocking"])
    assert out["provenance"]["frame_unanimous"] is False


def test_component_without_fingerprint_blocks(tmp_path):
    ws = _workspace(tmp_path, zones=())
    _zone(ws, "zone_1")
    _zone(ws, "zone_2", fingerprint=False)
    out = verify_workspace(str(ws))
    assert out["verdict"] == "blocked"
    assert any("no align_inputs.json" in b for b in out["blocking"])
    assert out["provenance"]["zones_without_fingerprint"] == ["zone_2"]


def test_non_metric_scale_blocks(tmp_path):
    """A merged component whose MEASURED scale is outside the band."""
    ws = _workspace(tmp_path)
    merge = ws / "merged"
    merge.mkdir()
    (merge / "EVALUATION_READY.txt").write_text("ok", encoding="utf-8")
    (merge / "merge_report.json").write_text(json.dumps({
        "clusters": [{"final_components": [
            {"key": "c/hull", "camera_count": 100}]}],
        "input_scales": {"c/hull": {"median": 0.24, "status": "fail"}},
    }), encoding="utf-8")
    out = verify_workspace(str(ws))
    assert out["verdict"] == "blocked"
    assert any("not metric" in b for b in out["blocking"])


def test_unmeasured_scale_is_counted_not_blocked(tmp_path):
    """Asserting a scale nobody measured is the fault being guarded
    against - so an absent measurement is reported, never judged."""
    ws = _workspace(tmp_path)
    merge = ws / "merged"
    merge.mkdir()
    (merge / "EVALUATION_READY.txt").write_text("ok", encoding="utf-8")
    (merge / "merge_report.json").write_text(json.dumps({
        "clusters": [{"final_components": [
            {"key": "c/hull", "camera_count": 100}]}]}), encoding="utf-8")
    out = verify_workspace(str(ws))
    assert out["counts"]["scale_unmeasured"] == 1
    assert not any("metric" in b for b in out["blocking"])


def test_scale_band_edges_are_inclusive(tmp_path):
    ws = _workspace(tmp_path)
    merge = ws / "merged"
    merge.mkdir()
    (merge / "EVALUATION_READY.txt").write_text("ok", encoding="utf-8")
    (merge / "merge_report.json").write_text(json.dumps({
        "clusters": [{"final_components": [
            {"key": "c/lo", "camera_count": 10},
            {"key": "c/hi", "camera_count": 10}]}],
        "input_scales": {"c/lo": {"median": SCALE_MIN},
                         "c/hi": {"median": SCALE_MAX}},
    }), encoding="utf-8")
    out = verify_workspace(str(ws))
    assert not any("metric" in b for b in out["blocking"]), out["blocking"]


def test_blocked_stage_blocks_even_when_not_required(tmp_path):
    """A DETECTED silent-success failure does not become acceptable by
    not being required this run."""
    ws = _workspace(tmp_path)
    # A header-only flight log = "nothing matched the nav table".
    (ws / "raw_images" / "flight_log_54N_UTM.txt").write_text(
        "hdr\n", encoding="utf-8")
    out = verify_workspace(str(ws), require=["align"])
    assert "georeference" not in out["required"]
    assert out["verdict"] == "blocked"
    assert any(b.startswith("georeference:") for b in out["blocking"])


# ------------------------------------------------------------- interface

def test_require_reports_incomplete(tmp_path):
    ws = _workspace(tmp_path)
    out = verify_workspace(str(ws), require=["align", "merge"])
    assert out["verdict"] == "incomplete"
    assert any(i.startswith("merge:") for i in out["incomplete"])


def test_unknown_stage_is_named(tmp_path):
    ws = _workspace(tmp_path)
    try:
        verify_workspace(str(ws), require=["nope"])
    except ValueError as exc:
        assert "nope" in str(exc)
    else:
        raise AssertionError("an unknown stage must raise")


def test_exit_codes_match_verdicts(tmp_path, capsys):
    ws = _workspace(tmp_path)
    assert main(["--workspace", str(ws)]) == EXIT_CODES["ok"]
    assert main(["--workspace", str(ws), "--require", "merge"]) \
        == EXIT_CODES["incomplete"]
    assert main(["--workspace", str(tmp_path / "nope")]) \
        == EXIT_CODES["absent"]
    capsys.readouterr()


def test_json_output_is_parseable_and_written(tmp_path, capsys):
    ws = _workspace(tmp_path)
    out_file = tmp_path / "verify.json"
    main(["--workspace", str(ws), "--json", "--out", str(out_file)])
    printed = json.loads(capsys.readouterr().out)
    assert printed["schema"] == 1
    assert json.loads(out_file.read_text(encoding="utf-8")) == printed


def test_text_output_is_ascii(tmp_path):
    """The cp1252 console crashes on non-ASCII (Windows trap registry)."""
    ws = _workspace(tmp_path, zones=())
    _zone(ws, "zone_1", frame="utm")
    _zone(ws, "zone_2", frame="local_euclidean")
    text = format_text(verify_workspace(str(ws)))
    text.encode("ascii")
