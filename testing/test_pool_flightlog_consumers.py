"""
Flight-log consumers must normalize the filename column to a BASENAME.

CLAUDE.md states "Consumers match by NORMALIZED BASENAME", and in pool layout
the zone flight log's filename column is a full canonical path by design
(FLIGHTLOG_ARCHITECTURE: it carries the same paths as the .imagelist). Three
consumers did not normalize, and each failed differently on NA165/H2060
(2026-08-31):

  component_manifest.bbox_from_flight_log -> every component bbox_utm null
      (covered in test_component_manifest_bbox.py)
  merge_zones.build_union_flight_log      -> ZERO-rows refusal, merge aborted
  scale_oracle.load_nav_positions         -> every component scale UNMEASURED

The first two fail loudly. The third is the dangerous one: it degrades to a
warning per component and the run continues.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import merge_zones
from modules.scale_oracle import load_nav_positions

HEADER = ("filename;X (East);Y (North);Alt;X Accuracy;Y Accuracy;Alt Accuracy;"
          "Yaw;Pitch;Roll;Yaw Accuracy;Pitch Accuracy;Roll Accuracy")
POOL = r"C:\pool\preprocessed_images"
NAMES = ["a.jpg", "b.jpg", "c.jpg"]


def _log(tmp_path, first_col, name="flight_log_2L_UTM.txt"):
    p = tmp_path / name
    lines = [HEADER]
    for i, col in enumerate(first_col):
        lines.append(f"{col};{100.0+i};{200.0+i};{-650.0-i};10;10;1;0;60;0;15;30;15")
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


# --------------------------------------------------------------- scale oracle

def test_nav_positions_keyed_by_basename_stem_for_full_paths(tmp_path):
    p = _log(tmp_path, [os.path.join(POOL, n) for n in NAMES])
    nav = load_nav_positions(str(p))
    assert set(nav) == {"a", "b", "c"}, "pool full paths must key on basename stem"
    assert nav["a"] == (100.0, 200.0, -650.0)


def test_nav_positions_bare_names_unchanged(tmp_path):
    p = _log(tmp_path, NAMES)
    assert set(load_nav_positions(str(p))) == {"a", "b", "c"}


def test_nav_positions_forward_slashes(tmp_path):
    p = _log(tmp_path, [f"C:/pool/imgs/{n}" for n in NAMES])
    assert set(load_nav_positions(str(p))) == {"a", "b", "c"}


# ----------------------------------------------------------- union flight log

def _union(tmp_path, first_col, only):
    images_root = tmp_path / "single_scene" / "zone_all"
    images_root.mkdir(parents=True)
    _log(images_root, first_col)
    out = tmp_path / "merged" / "cluster_0"
    out.mkdir(parents=True)
    import logging
    return merge_zones.build_union_flight_log(
        str(tmp_path / "single_scene"), str(out), logging.getLogger("t"),
        only_basenames=only, tag="test")


def test_union_log_matches_full_path_rows(tmp_path):
    # The failure this fixes: 1 zone log, N requested images, 0 matched.
    log_path, _params = _union(
        tmp_path, [os.path.join(POOL, n) for n in NAMES],
        only={"a.jpg", "b.jpg"})
    body = [l for l in open(log_path, encoding="utf-8").read().splitlines()[1:] if l.strip()]
    assert len(body) == 2, "pool full-path rows must match requested basenames"


def test_union_log_bare_names_unchanged(tmp_path):
    log_path, _params = _union(tmp_path, NAMES, only={"a.jpg", "c.jpg"})
    body = [l for l in open(log_path, encoding="utf-8").read().splitlines()[1:] if l.strip()]
    assert len(body) == 2


def test_union_log_still_refuses_when_nothing_matches(tmp_path):
    # The ZERO-rows guard must survive the fix - it is what stopped an
    # ungeoreferenced merge from shipping with workflow_success true.
    import pytest
    with pytest.raises(ValueError, match="ZERO rows"):
        _union(tmp_path, [os.path.join(POOL, n) for n in NAMES],
               only={"nothing_like_it.jpg"})
