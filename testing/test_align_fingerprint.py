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


# ---------------------------------------------------------------------------
# B20 - a workflow-script change must be MATERIAL
# ---------------------------------------------------------------------------
# The fingerprint hashed AlignmentParams.xml but not the code that applies it.
# Observed 2026-09-09: zone_3 was re-aligned immediately after AlignZone.bat
# gained the B19 -update step - which alters the geometry of every component it
# touches - and the run announced "Re-run with IDENTICAL inputs". Two zones
# aligned either side of a .bat edit compared as the same run.
#
# repo_sha is deliberately still NOT material: it moves on every commit,
# including docs and tests, and a metrology warning that fires constantly is
# one operators learn to ignore.

def test_workflow_scripts_are_fingerprinted(tmp_path):
    nav, flp, ap = _inputs(tmp_path)
    fp = build_fingerprint(nav, flp, ap, 50)
    ws = fp.get("workflow_scripts")
    assert isinstance(ws, dict) and ws, "workflow scripts not fingerprinted"
    # AlignZone.bat is the one that actually produces a zone.
    assert ws.get("AlignZone.bat"), "AlignZone.bat not hashed"


def test_a_changed_workflow_script_is_material_and_named(tmp_path):
    """The whole point of B20: the diff must fire, and say WHICH script."""
    import copy
    nav, flp, ap = _inputs(tmp_path)
    new = build_fingerprint(nav, flp, ap, 50)
    old = copy.deepcopy(new)
    old["workflow_scripts"]["AlignZone.bat"] = "0" * 64
    changes = diff_fingerprints(old, new)
    assert changes, "a .bat edit compared as identical - B20 is back"
    assert any("AlignZone.bat" in c for c in changes), changes


def test_legacy_fingerprint_without_the_field_is_not_a_change(tmp_path):
    """Upgrading the code must not retroactively invalidate zones on disk.

    A fingerprint written before this field existed has no 'workflow_scripts'
    key. Treating that absence as a change would declare every previously
    aligned zone incomparable - a false alarm about data that is fine, and the
    fastest way to make the whole check get ignored.
    """
    import copy
    nav, flp, ap = _inputs(tmp_path)
    new = build_fingerprint(nav, flp, ap, 50)
    legacy = copy.deepcopy(new)
    legacy.pop("workflow_scripts")
    assert diff_fingerprints(legacy, new) == []


def test_repo_sha_alone_is_still_not_material(tmp_path):
    """Recorded, not compared - unchanged by the B20 fix."""
    import copy
    nav, flp, ap = _inputs(tmp_path)
    new = build_fingerprint(nav, flp, ap, 50)
    old = copy.deepcopy(new)
    old["repo_sha"] = "a" * 40
    assert diff_fingerprints(old, new) == []
