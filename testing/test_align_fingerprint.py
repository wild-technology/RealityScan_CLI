"""align_inputs.json - per-zone alignment-input fingerprint
(PRODUCT_READINESS must-fix 2). Content identity, material-change diffs,
nav-aware resume."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.align_fingerprint import (
    FINGERPRINT_NAME, build_fingerprint, diff_fingerprints,
    matches_current, read_fingerprint, write_fingerprint)


def _mk(tmp_path, name, content):
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return str(p)


def _inputs(tmp_path, nav="a;b;c\n1;2;3\n", settings="<x/>"):
    nav_p = _mk(tmp_path, "flight_log_run2.txt", nav)
    flp = _mk(tmp_path, "FlightLogParamsLocal.xml", "<local/>")
    ap = _mk(tmp_path, "AlignmentParams.xml", settings)
    return nav_p, flp, ap


def test_roundtrip_and_material_identity(tmp_path):
    nav, flp, ap = _inputs(tmp_path)
    fp = build_fingerprint(nav, flp, ap, 50)
    out = tmp_path / "zone_1"
    out.mkdir()
    write_fingerprint(str(out), fp)
    back = read_fingerprint(str(out))
    assert back["schema"] == 1
    assert back["flight_log"]["sha256"] == fp["flight_log"]["sha256"]
    # identical inputs -> no material diffs, resume matches
    fp2 = build_fingerprint(nav, flp, ap, 50)
    assert diff_fingerprints(back, fp2) == []
    assert matches_current(str(out), fp2)


def test_nav_content_change_is_material_and_blocks_resume(tmp_path):
    nav, flp, ap = _inputs(tmp_path)
    out = tmp_path / "zone_1"
    out.mkdir()
    write_fingerprint(str(out), build_fingerprint(nav, flp, ap, 50))
    # edit the nav IN PLACE (the two-frames incident class)
    with open(nav, "a", encoding="utf-8") as fh:
        fh.write("4;5;6\n")
    fp2 = build_fingerprint(nav, flp, ap, 50)
    changes = diff_fingerprints(read_fingerprint(str(out)), fp2)
    assert any("navigation flight log" in c for c in changes)
    assert not matches_current(str(out), fp2)


def test_settings_change_is_material(tmp_path):
    nav, flp, ap = _inputs(tmp_path)
    old = build_fingerprint(nav, flp, ap, 50)
    ap2 = _mk(tmp_path, "AlignmentParams_variant.xml", "<x overlap='Low'/>")
    new = build_fingerprint(nav, flp, ap2, 50)
    changes = diff_fingerprints(old, new)
    assert any("alignment settings" in c for c in changes)


def test_renamed_identical_nav_is_not_material(tmp_path):
    nav, flp, ap = _inputs(tmp_path)
    old = build_fingerprint(nav, flp, ap, 50)
    nav2 = _mk(tmp_path, "renamed_copy.txt", "a;b;c\n1;2;3\n")
    new = build_fingerprint(nav2, flp, ap, 50)
    assert diff_fingerprints(old, new) == []


def test_frame_change_is_called_out(tmp_path):
    flp = _mk(tmp_path, "flp.xml", "<t/>")
    ap = _mk(tmp_path, "ap.xml", "<x/>")
    untagged = _mk(tmp_path, "flight_log_UTM.txt", "n;x;y;a\n")
    tagged = _mk(tmp_path, "flight_log_53N_UTM.txt", "n;x;y;a\n")
    old = build_fingerprint(untagged, flp, ap, 50)
    new = build_fingerprint(tagged, flp, ap, 50)
    assert old["frame"] == "local_euclidean" and new["frame"] == "utm"
    assert any("FRAME changed" in c for c in diff_fingerprints(old, new))


def test_min_component_size_change_is_material(tmp_path):
    nav, flp, ap = _inputs(tmp_path)
    old = build_fingerprint(nav, flp, ap, 50)
    new = build_fingerprint(nav, flp, ap, 10)
    assert any("min_component_size" in c for c in diff_fingerprints(old, new))


def test_no_previous_fingerprint_means_no_diffs(tmp_path):
    nav, flp, ap = _inputs(tmp_path)
    fp = build_fingerprint(nav, flp, ap, 50)
    assert diff_fingerprints(None, fp) == []
    assert not matches_current(str(tmp_path), fp)  # nothing written yet


def test_write_is_atomic_shaped(tmp_path):
    nav, flp, ap = _inputs(tmp_path)
    out = tmp_path / "z"
    out.mkdir()
    p = write_fingerprint(str(out), build_fingerprint(nav, flp, ap, 50))
    assert os.path.basename(p) == FINGERPRINT_NAME
    assert not os.path.exists(p + ".tmp")
    json.load(open(p, encoding="utf-8"))
