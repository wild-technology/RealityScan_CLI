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


def test_neighbour_subset_picks_up_margin_neighbours_under_border_gate():
    """C is 5 m from B - inside the 10 m margin, but with no shared imagery
    and no true overlap. The legacy 'border' gate relates them; the default
    'overlap' gate (owner uniqueness criterion 2026-07-28) does not."""
    subset = merge_zones.neighbour_subset([A, B, C, D],
                                          component_analysis.component_key(B),
                                          LOG, pair_gate='border')
    assert keys(subset) == keys([A, B, C])

    subset = merge_zones.neighbour_subset([A, B, C, D],
                                          component_analysis.component_key(B),
                                          LOG)
    assert keys(subset) == keys([A, B]), (
        'a 5 m gap with zero shared images is a unique feature, not a '
        'merge candidate - merged5 cluster_1 is what ignoring this produced')


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


def test_fusion_shrinks_the_cluster_and_grows_the_bbox():
    """A fusion must strictly reduce the component count - the termination
    argument depends on it - and the fused extent must reach further than
    either input did, which is why some exhausted targets become revisitable.

    Which targets reopen is owned by test_targeted_reopen_only_touches_borderers;
    an earlier version of this test asserted clear-everything, the quadratic
    behaviour the 2026-07-27 review flagged.
    """
    current = [A, B, C, D]
    fused = comp('cluster_0', 'm_c0', A['camera_count'] + B['camera_count'],
                 [0.0, 0.0, 35.0, 20.0])
    subset_keys = {component_analysis.component_key(m) for m in (A, B)}
    current = [m for m in current
               if component_analysis.component_key(m) not in subset_keys] + [fused]

    assert len(current) == 3, 'four components fused down to three'
    # the fused extent now reaches C, which neither A nor B did alone.
    # Under the border gate (which this reopen semantic belongs to) C is a
    # neighbour of the fused extent; under the default overlap gate it is not,
    # because the fused box still only ABUTS C (5 m gap, no shared imagery).
    subset = merge_zones.neighbour_subset(
        current, component_analysis.component_key(fused), LOG,
        pair_gate='border')
    assert component_analysis.component_key(C) in keys(subset)


def test_cluster_scope_still_takes_everything():
    """The old behaviour must remain available for comparison."""
    subset = list([A, B, C, D])
    assert len(subset) == 4


# ------------------------------------------------- pair gate (owner criterion
# 2026-07-28: unique = no shared images AND no true spatial overlap)

def test_pair_related_by_shared_imagery():
    a = comp('z1', 'P', 4, (0, 0, 10, 10), images=['x1.jpg', 'x2.jpg'])
    b = comp('z4', 'Q', 4, (500, 500, 510, 510), images=['X2.JPG', 'y.jpg'])
    ok, why = merge_zones.pair_related(a, b)
    assert ok and 'shared' in why, 'case-insensitive shared imagery relates'


def test_pair_related_by_true_overlap_only():
    a = comp('z1', 'P', 4, (0.0, 0.0, 12.0, 10.0), images=['a.jpg'])
    b = comp('z1', 'Q', 4, (11.0, 1.0, 22.0, 9.0), images=['b.jpg'])
    ok, why = merge_zones.pair_related(a, b)
    assert ok and 'overlap' in why


def test_pair_not_related_when_merely_adjacent():
    """The merged5 cluster_1 failure shape: disjoint objects 5-20 m apart,
    zero shared imagery, chained into one scene and rigid-glued."""
    a = comp('z1', 'P', 4, (0.0, 0.0, 10.0, 10.0), images=['a.jpg'])
    b = comp('z1', 'Q', 4, (15.0, 0.0, 25.0, 10.0), images=['b.jpg'])
    ok, why = merge_zones.pair_related(a, b)
    assert not ok


def test_null_bbox_relates_conservatively():
    a = comp('z1', 'P', 4, None, images=['a.jpg'])
    b = comp('z1', 'Q', 4, (500, 500, 510, 510), images=['b.jpg'])
    ok, _why = merge_zones.pair_related(a, b)
    assert ok


def test_overlap_gate_splits_the_transitive_chain():
    """Border-gate clustering chained A-B-C into one cluster via transitive
    adjacency; the overlap gate must keep C separate (no sharing, 5 m gap)."""
    border = merge_zones.related_pairs([A, B, C, D], 'border')
    overlap = merge_zones.related_pairs([A, B, C, D], 'overlap')
    kb = {tuple(sorted(p)) for p in border}
    ko = {tuple(sorted(p)) for p in overlap}
    bc = tuple(sorted((component_analysis.component_key(B),
                       component_analysis.component_key(C))))
    ab = tuple(sorted((component_analysis.component_key(A),
                       component_analysis.component_key(B))))
    assert bc in kb and bc not in ko
    assert ab in kb and ab in ko, 'true overlap must relate under both gates'


def test_acceptance_verdict_is_the_wired_decision():
    """Drives merge_zones.acceptance_verdict - the function merge_cluster
    actually calls - across the real H2024 outcomes (final review must-fix:
    the loss-budget tests only reached attribute_result, so the accept
    wiring itself was unguarded)."""
    tol = merge_zones.loss_budget(4865, 0.0025)
    assert tol == 12

    # The hull: fused, exact attribution, 5-camera loss inside the budget.
    accept, rejection = merge_zones.acceptance_verdict(
        True, adopted_count=1, fused=True, confidence='exact',
        lost=5, tol=tol)
    assert accept and rejection is None

    # Loss over budget: rejected as shrink.
    accept, rejection = merge_zones.acceptance_verdict(
        True, adopted_count=1, fused=True, confidence='exact',
        lost=65, tol=tol)
    assert not accept and rejection == 'shrink'

    # Fused but ambiguous attribution: rejected on the attribution term.
    accept, rejection = merge_zones.acceptance_verdict(
        True, adopted_count=3, fused=True, confidence='ambiguous',
        lost=0, tol=tol)
    assert not accept and rejection == 'ambiguous_attribution'

    # Nothing fused (parents self-attributed): a clean no-op, no rejection.
    accept, rejection = merge_zones.acceptance_verdict(
        True, adopted_count=3, fused=False, confidence='exact',
        lost=0, tol=tol)
    assert not accept and rejection is None

    # Workflow failure never accepts regardless of arithmetic.
    accept, rejection = merge_zones.acceptance_verdict(
        False, adopted_count=1, fused=True, confidence='exact',
        lost=0, tol=tol)
    assert not accept


def test_effective_ladder_is_the_wired_mechanism_filter():
    """Drives merge_zones.effective_ladder_for - what merge_cluster consumes
    (final review: shared_graph_spans was only tested as a predicate)."""
    ladder = merge_zones.LADDERS['merge_first']
    p = comp('z1', 'P', 4, (0, 0, 10, 10), images=['a.jpg', 's.jpg'])
    q = comp('z4', 'Q', 4, (5, 0, 15, 10), images=['s.jpg'])
    r = comp('z4', 'R', 4, (8, 0, 18, 10), images=['c.jpg'])

    assert merge_zones.effective_ladder_for([p, q], ladder) == ladder, (
        'identity-connected subsets keep the full ladder')
    align_only = merge_zones.effective_ladder_for([p, q, r], ladder)
    assert align_only and all(s['mode'] == 'align' for s in align_only), (
        'a non-spanning subset must not see a merge rung - it can only glue')
    align_ladder = [s for s in ladder if s['mode'] == 'align']
    assert merge_zones.effective_ladder_for([r], align_ladder) == align_ladder


def test_merge_rungs_need_a_spanning_shared_graph():
    """merge fuses through camera identity, so it is only admitted when the
    shared-image graph reaches EVERY subset member. Any-pair sharing is not
    enough: in the real {z1_c2, z4_c1, z4_c2} cluster only one pair shared
    imagery while the third merely bbox-overlapped - a merge rung would have
    rigid-glued all three."""
    p = comp('z1', 'P', 4, (0, 0, 10, 10), images=['a.jpg', 's.jpg'])
    q = comp('z4', 'Q', 4, (5, 0, 15, 10), images=['s.jpg', 'b.jpg'])
    r = comp('z4', 'R', 4, (8, 0, 18, 10), images=['c.jpg'])

    assert merge_zones.shared_graph_spans([p, q]), 'P-Q are identity-connected'
    assert not merge_zones.shared_graph_spans([p, q, r]), (
        'R has no identity link - merge could only glue it')
    r['images'] = ['b.jpg', 'c.jpg']
    assert merge_zones.shared_graph_spans([p, q, r]), (
        'P-Q-R chain spans transitively through shared imagery')
    assert merge_zones.shared_graph_spans([p]), 'singleton trivially spans'




# ------------------------------------------- regressions from the 2026-07-27
# adversarial review of this session's own work (F:/_copylogs/merge_logic_review.md)

def test_symmetric_pair_is_attempted_once_not_twice():
    """A-B is one subset regardless of which one is the growth target.

    Without the attempted-subset memo a symmetric pair costs SIX attempts:
    target A yields {A, B}, then target B yields the identical set and the
    ladder runs all three rungs again on unchanged members.
    """
    pair = [A, B]
    sigs = set()
    for target in merge_zones.growth_order(pair):
        subset = merge_zones.neighbour_subset(pair, target, LOG)
        sigs.add(frozenset(component_analysis.component_key(m) for m in subset))
    assert len(sigs) == 1, 'both targets must resolve to the same subset signature'


def test_targeted_reopen_only_touches_borderers():
    """After a fusion, reopen the neighbours of the NEW component only.

    Clearing the whole exhausted set was quadratic: a target whose neighbour
    set did not change has already had every rung run against it.
    """
    fused = comp('cluster_0', 'm_c0', 180, [0.0, 0.0, 35.0, 20.0])
    current = [fused, C, D]
    new_keys = {component_analysis.component_key(fused)}
    exhausted = {component_analysis.component_key(C),
                 component_analysis.component_key(D)}

    touching = set()
    for entry in component_analysis.find_borders(current):
        a, b = entry['pair']
        if a in new_keys:
            touching.add(b)
        if b in new_keys:
            touching.add(a)
    exhausted -= (touching | new_keys)

    assert component_analysis.component_key(C) not in exhausted, \
        'C borders the fused extent and must be revisited'
    assert component_analysis.component_key(D) in exhausted, \
        'D is 340 m away - reopening it is wasted work'


def test_origin_map_resolves_transitively():
    """A second-round fusion must still name ORIGINAL input keys.

    The scale gate is keyed by original inputs. A round-two fusion's
    attribution names round-one SYNTHETIC keys, so a non-transitive map leaves
    the gate with no verdict - which it treats as 'unmeasured' and blocks.
    """
    origin_map = {'z1/A': ['z1/A'], 'z1/B': ['z1/B'], 'z2/C': ['z2/C']}

    # round one: A + B -> m_c0
    origins = []
    for s in ('z1/A', 'z1/B'):
        origins.extend(origin_map.get(s, [s]))
    origin_map['cluster_0/m_c0'] = sorted(set(origins))

    # round two: m_c0 + C -> m_c1, whose attribution names the SYNTHETIC key
    origins = []
    for s in ('cluster_0/m_c0', 'z2/C'):
        origins.extend(origin_map.get(s, [s]))
    origin_map['cluster_0/m_c1'] = sorted(set(origins))

    assert origin_map['cluster_0/m_c1'] == ['z1/A', 'z1/B', 'z2/C'], \
        'the chain must resolve back to original inputs, not synthetic keys'


def test_scale_gate_accepts_a_fused_component_with_sound_inputs():
    """The defect: every merged component was blocked as 'unmeasured'."""
    scales = {'z1/A': {'status': 'pass', 'explanation': 'scale 0.99'},
              'z1/B': {'status': 'pass', 'explanation': 'scale 1.01'}}
    fused_target = [{'key': 'cluster_0/m_c0', 'camera_count': 180,
                     'inputs': ['z1/A', 'z1/B']}]
    kept, blocked = merge_zones.apply_scale_gate(
        fused_target, scales, 0.90, 1.10, LOG)
    assert kept and not blocked, 'a fusion of two sound inputs must be modellable'


def test_scale_gate_still_blocks_a_fusion_containing_a_bad_input():
    scales = {'z1/A': {'status': 'pass', 'explanation': 'scale 0.99'},
              'z3/C': {'status': 'fail', 'explanation': 'scale 0.236'}}
    fused_target = [{'key': 'cluster_0/m_c0', 'camera_count': 180,
                     'inputs': ['z1/A', 'z3/C']}]
    kept, blocked = merge_zones.apply_scale_gate(
        fused_target, scales, 0.90, 1.10, LOG)
    assert not kept and blocked[0]['status'] == 'fail', \
        'the worst input must still decide'


# ---------------------------------------------------------------------------
# Fused-component identity must be unique across attempts (H2024 2026-07-28)
# ---------------------------------------------------------------------------
#
# peel_index restarts at 0 on every attempt, so naming a fusion
# `<tag>_m_c<peel_index>` gave BOTH accepted fusions in cluster_1 the identity
# `cluster_1/cluster_1_m_c0`. The next find_borders call raised
# "duplicate component identity" and killed a 1h47m run after two good fusions.


def fused_name(tag, attempt_no, peel_index):
    """The REAL naming helper merge_cluster uses - not a mirror. A mirror
    here kept passing while the driver could regress (final review,
    must-fix; the audit-#17 shape)."""
    return f'{merge_zones.fused_export_name(tag, attempt_no)}_c{peel_index}'


def test_two_fusions_in_one_cluster_get_distinct_identities():
    tag = 'cluster_1'
    first = comp(tag, fused_name(tag, 1, 0), 525, (0, 0, 10, 10))
    second = comp(tag, fused_name(tag, 5, 0), 400, (100, 100, 110, 110))
    keys = {component_analysis.component_key(first),
            component_analysis.component_key(second)}
    assert len(keys) == 2, f'both fusions collapsed to one identity: {keys}'
    # The real crash site: _validate runs inside find_borders.
    component_analysis.find_borders([first, second])


def test_the_old_scheme_would_still_be_caught():
    """Pin the guard itself, so a future rename cannot silently reintroduce it."""
    tag = 'cluster_1'
    dup_a = comp(tag, f'{tag}_m_c0', 525, (0, 0, 10, 10))
    dup_b = comp(tag, f'{tag}_m_c0', 400, (100, 100, 110, 110))
    with pytest.raises(ValueError, match='duplicate component identity'):
        component_analysis.find_borders([dup_a, dup_b])


# ---------------------------------------------------------------------------
# Bounded-loss attribution (owner decision 2026-07-28: 0.25% of input cameras)
# ---------------------------------------------------------------------------
#
# H2024's hull fused 4,860 of 4,865 cameras on every rung and was rejected all
# three times, because 4,860 is not an exact subset sum of {2241, 1407, 1217}.


HULL = [comp('zone_5', 'zone_5_c0', 2241, (0, 0, 100, 100)),
        comp('zone_2', 'zone_2_c0', 1407, (50, 0, 150, 100)),
        comp('zone_3', 'zone_3_c0', 1217, (100, 0, 200, 100))]
HULL_PEEL = [4860, 2241, 1407, 1217]
HULL_TOL = int(4865 * 0.0025)          # 12 cameras


def test_hull_fusion_is_invisible_without_a_loss_budget():
    """The regression this whole change exists to fix."""
    results, confidence = merge_zones.attribute_result(
        HULL, HULL_PEEL, LOG, loss_tolerance=0)
    fused = [r for r in results if len(r['inputs']) >= 2]
    assert not fused, 'exact-only must not see the lossy fusion'
    assert confidence == 'ambiguous'


def test_hull_fusion_is_adopted_within_the_budget():
    results, confidence = merge_zones.attribute_result(
        HULL, HULL_PEEL, LOG, loss_tolerance=HULL_TOL)
    assert confidence == 'exact', 'a single best lossy match is not ambiguous'
    fused = [r for r in results if len(r['inputs']) >= 2]
    assert len(fused) == 1, f'expected one fusion, got {fused}'
    assert fused[0]['camera_count'] == 4860
    assert sorted(fused[0]['inputs']) == [
        'zone_2/zone_2_c0', 'zone_3/zone_3_c0', 'zone_5/zone_5_c0']
    assert fused[0]['loss'] == 5, 'the accepted loss must be recorded'
    # The three parents survive in the scene and must read as residuals.
    assert sum(1 for r in results if r['residual']) == 3


def test_loss_beyond_the_budget_is_still_rejected():
    results, confidence = merge_zones.attribute_result(
        HULL, [4800, 2241, 1407, 1217], LOG, loss_tolerance=HULL_TOL)
    fused = [r for r in results if len(r['inputs']) >= 2]
    assert not fused, '65 cameras lost is well outside a 12-camera budget'
    assert confidence == 'ambiguous'


def test_exact_match_wins_over_a_lossy_one():
    """A tolerance must never change the answer on a case that was already exact."""
    inputs = [comp('z', 'A', 100, (0, 0, 10, 10)),
              comp('z', 'B', 60, (5, 0, 15, 10)),
              comp('z', 'C', 40, (10, 0, 20, 10))]
    # 160 is exactly A+B; A+B+C (200) is far outside the 10-camera budget, so
    # the exact candidate is the only one and must be taken with zero loss.
    results, _ = merge_zones.attribute_result(
        inputs, [160, 40], LOG, loss_tolerance=10)
    fused = [r for r in results if len(r['inputs']) >= 2][0]
    assert fused['camera_count'] == 160
    assert sorted(fused['inputs']) == ['z/A', 'z/B']
    assert fused['loss'] == 0, 'an exact match must report zero loss'


def test_tolerance_zero_is_the_old_behaviour():
    inputs = [comp('z', 'A', 78, (0, 0, 10, 10)),
              comp('z', 'B', 42, (5, 0, 15, 10))]
    results, confidence = merge_zones.attribute_result(
        inputs, [120, 78, 42], LOG, loss_tolerance=0)
    fused = [r for r in results if len(r['inputs']) >= 2]
    assert confidence == 'exact' and len(fused) == 1
    assert fused[0]['camera_count'] == 120 and fused[0]['loss'] == 0


# ---------------------------------------------------------------- audit #5
# --scale_min/--scale_max were accepted, persisted, and PRINTED as the band in
# EVALUATION_READY - and never reached the verdict. Tightening the gate was a
# silent no-op under a report claiming it was applied.


def test_operator_band_reaches_the_verdict(tmp_path, monkeypatch):
    from modules import scale_oracle

    captured = []
    real_verdict = scale_oracle.verdict

    def spy(stats, scale_min=scale_oracle.DEFAULT_SCALE_MIN,
            scale_max=scale_oracle.DEFAULT_SCALE_MAX):
        captured.append((scale_min, scale_max))
        return real_verdict(stats, scale_min, scale_max)

    monkeypatch.setattr(merge_zones.scale_oracle, 'verdict', spy)
    monkeypatch.setattr(merge_zones.scale_oracle, 'load_nav_positions',
                        lambda _p: {})
    monkeypatch.setattr(merge_zones.scale_oracle, 'scale_for_images',
                        lambda _i, _d, _n: {'median': 1.075, 'iqr_low': 1.05,
                                            'iqr_high': 1.11, 'cameras': 10})
    manifest = comp('z1', 'A', 10, (0, 0, 5, 5))
    manifest['rsalign'] = str(tmp_path / 'A.rsalign')
    (tmp_path / 'A.rsalign').write_bytes(b'x')

    out = merge_zones.measure_input_scales([manifest], 'unused.txt', LOG,
                                           scale_min=0.98, scale_max=1.02)
    assert captured == [(0.98, 1.02)], 'the operator band must reach verdict'
    assert out['z1/A']['status'] == 'fail', (
        '1.075 is inside the default band but OUTSIDE the tightened one - '
        'under the old wiring this passed silently')


if __name__ == '__main__':
    sys.exit(pytest.main([__file__, '-v']))
