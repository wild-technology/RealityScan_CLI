"""Merge-scene camera ceiling (C-20260802-01) - the pure verdict that
refuses over-envelope merge attempts BEFORE RealityScan time is spent.
The recorded incident: a ~44k-camera scene died at 319.5 GB commit after
5.6 unattended hours; a 34,105-camera scene fit at 262 GB.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from merge_zones import (MAX_MERGE_SCENE_CAMERAS, scene_ceiling_verdict)


def _m(cams):
    return {'camera_count': cams}


def test_default_ceiling_reflects_the_measured_envelope():
    assert MAX_MERGE_SCENE_CAMERAS == 34_000


def test_under_ceiling_is_not_refused():
    refuse, total = scene_ceiling_verdict([_m(29_302), _m(4_442)], 34_000)
    assert not refuse and total == 33_744


def test_the_recorded_oom_scene_is_refused():
    # attempt 2 of 2026-08-01: fused core + 5 zone components = ~43.8k cams
    subset = [_m(29_302), _m(4_442), _m(2_846), _m(2_347), _m(2_260), _m(2_650)]
    refuse, total = scene_ceiling_verdict(subset, 34_000)
    assert refuse and total == 43_847


def test_exactly_at_ceiling_launches():
    refuse, _ = scene_ceiling_verdict([_m(34_000)], 34_000)
    assert not refuse


def test_missing_counts_are_treated_as_zero_not_a_crash():
    refuse, total = scene_ceiling_verdict(
        [{'camera_count': None}, {}, _m(10)], 34_000)
    assert not refuse and total == 10
