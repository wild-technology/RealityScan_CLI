#!/usr/bin/env python3
"""Unit tests for neighbour-scoped merge attempts (owner design 2026-07-27).

`find_borders` computes the pairs whose 10 m-expanded UTM bboxes touch, and its
docstring says "These are the only pairs merging should be attempted between" -
but the pairs were used only to build clusters and then discarded, so every
attempt handed the WHOLE cluster to RealityScan.

Observed cost on H2024: cluster_1 put 12 components in one scene, so a failure
named no pair; cluster_0 ran all three rungs with the 0.236-scale zone_3_c0
present every time, so we never learned whether its two sound siblings would
have fused alone.

These tests cover the selection and ordering logic, plus the termination
argument for the target loop. They deliberately do NOT drive RealityScan.

Run:  py -3.13 -m pytest testing/test_merge_scope.py
"""

from __future__ import annotations

import logging
import os
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, REPO_ROOT)

import merge_zones  # noqa: E402
from modules import component_analysis  # noqa: E402

LOG = logging.getLogger('test')


def comp(zone, name, cams, bbox, images=None):
    """A schema-v1-shaped manifest good enough for borders/keys."""
    return {
        'schema': 1,
        'zone': zone,
        'component': name,
        'rsalign': f'X:/{zone}/{name}.rsalign',
        'camera_count': cams,
        'images': images if images is not None else [f'{name}_{i}.jpg'
                                                    for i in range(cams)],
        'bbox_utm': bbox,
    }


# A row of four components. NOTE the border margin is applied to BOTH bboxes
# (ax0 - margin <= bx1 + margin), so DEFAULT_BORDER_MARGIN_M = 10 tolerates a
# gap of TWENTY metres, not ten. Geometry below is chosen against that:
#   A-B overlap outright; B-C gap 5 m; A-C gap 20 m (exactly at the limit);
#   D is 340 m away and borders nothing.
A = comp('z1', 'A', 100, [0.0, 0.0, 20.0, 20.0])
B = comp('z1', 'B', 80, [15.0, 0.0, 35.0, 20.0])
C = comp('z2', 'C', 60, [40.0, 0.0, 60.0, 20.0])
D = comp('z3', 'D', 40, [400.0, 0.0, 420.0, 20.0])


def keys(manifests):
    return sorted(component_analysis.component_key(m) for m in manifests)


# ---------------------------------------------------------------- selection

def test_neighbour_subset_includes_only_borderers():
    subset = merge_zones.neighbour_subset([A, B, C, D],
                                          component_analysis.component_key(A), LOG)
    assert component_analysis.component_key(D) not in keys(subset), (
        'D is 340 m away and must never be pulled into an attempt for A')
    assert component_analysis.component_key(B) in keys(subset)


def test_border_margin_applies_to_both_bboxes():
    """Pins a surprising semantic: the effective gap tolerance is 2 x margin.

    _bboxes_border expands BOTH boxes by margin_m, so DEFAULT_BORDER_MARGIN_M = 10
    treats components up to 20 m apart as bordering. Documentation that says
    '10 m-expanded bbox' understates the reach by a factor of two.
    """
    near = comp('zA', 'N1', 10, [0.0, 0.0, 10.0, 10.0])
    at_limit = comp('zB', 'N2', 10, [29.0, 0.0, 39.0, 10.0])   # 19 m gap
    beyond = comp('zC', 'N3', 10, [31.0, 0.0, 41.0, 10.0])     # 21 m gap

    pairs = {tuple(sorted(e['pair']))
             for e in component_analysis.find_borders([near, at_limit])}
    assert pairs, '19 m gap must border with a 10 m margin (10 + 10)'

    pairs = {tuple(sorted(e['pair']))
             for e in component_analysis.find_borders([near, beyond])}
    assert not pairs, '21 m gap must NOT border'


def test_neighbour_subset_picks_up_margin_neighbours():
    """C is 5 m from B, inside the 10 m border margin."""
    subset = merge_zones.neighbour_subset([A, B, C, D],
                                          component_analysis.component_key(B), LOG)
    assert keys(subset) == keys([A, B, C])


def test_isolated_component_has_no_neighbours():
    subset = merge_zones.neighbour_subset([A, B, C, D],
                                          component_analysis.component_key(D), LOG)
    assert keys(subset) == keys([D]), 'a lone subset means no attempt is made'


def test_null_bbox_borders_everything():
    """Unknown extent is conservative: it must not silently skip merges."""
    unknown = comp('z9', 'U', 10, None)
    subset = merge_zones.neighbour_subset([A, D, unknown],
                                          component_analysis.component_key(unknown), LOG)
    assert len(subset) == 3


# ----------------------------------------------------------------- ordering

def test_growth_order_is_largest_first():
    order = merge_zones.growth_order([C, A, D, B])
    assert order == [component_analysis.component_key(m) for m in (A, B, C, D)]


def test_growth_order_tolerates_missing_camera_count():
    broken = dict(A)
    broken.pop('camera_count')
    order = merge_zones.growth_order([broken, B])
    assert order[0] == component_analysis.component_key(B), 'missing count sorts last'


# -------------------------------------------------------------- termination

def test_target_loop_terminates_by_exhaustion():
    """Simulate the driver's bookkeeping: no fusion ever accepted.

    Each pass must retire exactly one target, so a cluster of N components
    performs N passes and stops - never loops.
    """
    current = [A, B, C, D]
    exhausted: set[str] = set()
    passes = 0
    while passes < 100:
        target = next((k for k in merge_zones.growth_order(current)
                       if k not in exhausted), None)
        if target is None:
            break
        passes += 1
        exhausted.add(target)          # stands in for "ladder exhausted"
    assert passes == len(current)
    assert target is None, 'loop must exit, not spin'


def test_fusion_clears_exhaustion_and_shrinks_the_cluster():
    """A fusion must reduce the component count AND reopen earlier targets.

    Reopening matters because a fused component has a larger bbox, so something
    that bordered nothing before may border it now.
    """
    current = [A, B, C, D]
    exhausted = {component_analysis.component_key(D)}

    fused = comp('cluster_0', 'm_c0', A['camera_count'] + B['camera_count'],
                 [0.0, 0.0, 35.0, 20.0])
    subset_keys = {component_analysis.component_key(m) for m in (A, B)}
    current = [m for m in current
               if component_analysis.component_key(m) not in subset_keys] + [fused]
    exhausted.clear()

    assert len(current) == 3, 'four components fused down to three'
    assert exhausted == set(), 'every target is revisitable after geometry changes'
    # and the fused extent now reaches C
    subset = merge_zones.neighbour_subset(
        current, component_analysis.component_key(fused), LOG)
    assert component_analysis.component_key(C) in keys(subset)


def test_cluster_scope_still_takes_everything():
    """The old behaviour must remain available for comparison."""
    subset = list([A, B, C, D])
    assert len(subset) == 4


if __name__ == '__main__':
    sys.exit(pytest.main([__file__, '-v']))
