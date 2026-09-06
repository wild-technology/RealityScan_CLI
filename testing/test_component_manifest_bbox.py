"""
bbox_from_flight_log must match a zone flight log whose filename column holds
FULL PATHS.

That is the pool layout's normal shape (FLIGHTLOG_ARCHITECTURE: a zone flight
log carries the same canonical paths as the .imagelist), and the matcher used
to compare the whole path against a set of basenames and stems, which can
never match. Every pool-mode component therefore got bbox_utm = null, and null
means "unknown extent" to component_analysis, which borders such a component
against everything and degrades merge planning.

Observed live on NA165/H2060, 2026-08-31: 20 of 20 components null.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.component_manifest import bbox_from_flight_log

HEADER = ("filename;X (East);Y (North);Alt;X Accuracy;Y Accuracy;Alt Accuracy;"
          "Yaw;Pitch;Roll;Yaw Accuracy;Pitch Accuracy;Roll Accuracy")
POOL = r"C:\pool\preprocessed_images"


def _write(tmp_path, first_col_values):
    log = tmp_path / "flight_log_2L_UTM.txt"
    lines = [HEADER]
    for i, col in enumerate(first_col_values):
        lines.append(f"{col};{100.0 + i};{200.0 + i};-650.0;"
                     f"10;10;1;0;60;0;15;30;15")
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(log)


def test_full_path_rows_match_basename_members(tmp_path):
    names = ["a.jpg", "b.jpg", "c.jpg"]
    log = _write(tmp_path, [os.path.join(POOL, n) for n in names])
    bbox = bbox_from_flight_log(log, names)
    assert bbox is not None, "pool-mode full-path rows must match basenames"
    assert bbox == [100.0, 200.0, 102.0, 202.0]


def test_bare_name_rows_still_match(tmp_path):
    # Copy layout: the column is already a bare name. Unchanged behaviour.
    names = ["a.jpg", "b.jpg"]
    log = _write(tmp_path, names)
    assert bbox_from_flight_log(log, names) == [100.0, 200.0, 101.0, 201.0]


def test_forward_slash_paths_match(tmp_path):
    names = ["a.jpg", "b.jpg"]
    log = _write(tmp_path, [f"C:/pool/preprocessed_images/{n}" for n in names])
    assert bbox_from_flight_log(log, names) == [100.0, 200.0, 101.0, 201.0]


def test_extension_mismatch_still_matches_by_stem(tmp_path):
    log = _write(tmp_path, [os.path.join(POOL, "a.jpg")])
    # member recorded without extension, as the identity harvest yields stems
    assert bbox_from_flight_log(log, ["a"]) == [100.0, 200.0, 100.0, 200.0]


def test_case_insensitive(tmp_path):
    log = _write(tmp_path, [os.path.join(POOL, "AbC.JPG")])
    assert bbox_from_flight_log(log, ["abc.jpg"]) == [100.0, 200.0, 100.0, 200.0]


def test_no_member_matches_returns_none(tmp_path):
    log = _write(tmp_path, [os.path.join(POOL, "a.jpg")])
    assert bbox_from_flight_log(log, ["nothing_like_it.jpg"]) is None


def test_missing_log_returns_none(tmp_path):
    assert bbox_from_flight_log(str(tmp_path / "absent.txt"), ["a.jpg"]) is None
