#!/usr/bin/env python3
"""Unit tests for the metric-scale deliverable gate.

Regression cover for 2026-07-26: H2024 zone_3 solved 1,192 cameras at scale
0.236 (a quarter of true size), registration looked healthy at 82-93% per zone,
every zone reported Success=True, and the component would have been modelled
and shipped. `modules/scale_oracle.py` could have caught it but had no caller -
it lived in testing/ and gated nothing.

Numbers below are the real measured values from that night plus the sound
PD-6 H2023 values, so the tests fail if the band logic drifts away from the
cases it was built for.

Run:  py -3.13 -m pytest testing/test_scale_gate.py
"""

from __future__ import annotations

import logging
import os
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, REPO_ROOT)

import merge_zones  # noqa: E402
from modules import scale_oracle  # noqa: E402

LOG = logging.getLogger('test')

# measured 2026-07-26
HULL_SOUND = {'median': 0.982, 'iqr_low': 0.951, 'iqr_high': 1.029, 'cameras': 3738}
BOW_WIDE = {'median': 1.075, 'iqr_low': 0.961, 'iqr_high': 1.404, 'cameras': 656}
ZONE3_BROKEN = {'median': 0.236, 'iqr_low': 0.217, 'iqr_high': 0.253, 'cameras': 1192}
OLD_HULL_BROKEN = {'median': 0.175, 'iqr_low': 0.166, 'iqr_high': 0.187, 'cameras': 3026}


# ------------------------------------------------------------------- verdict

def test_sound_component_passes():
    status, why = scale_oracle.verdict(HULL_SOUND)
    assert status == 'pass'
    assert '0.982' in why


@pytest.mark.parametrize('stats', [ZONE3_BROKEN, OLD_HULL_BROKEN])
def test_collapsed_scale_fails(stats):
    """Both real collapses - H2024 zone_3 0.236 and H2023 hull 0.175."""
    status, why = scale_oracle.verdict(stats)
    assert status == 'fail'
    assert 'outside' in why


def test_unmeasurable_is_not_a_pass():
    """Silence must never be read as evidence of soundness."""
    status, _ = scale_oracle.verdict(None)
    assert status == 'unmeasured'


def test_wide_iqr_passes_but_is_called_out():
    """In band, but the spread means drift/fold rather than a scale error."""
    status, why = scale_oracle.verdict(BOW_WIDE)
    assert status == 'pass'
    assert 'wide' in why.lower()


def test_band_is_configurable():
    tight = scale_oracle.verdict(BOW_WIDE, scale_min=0.95, scale_max=1.05)
    assert tight[0] == 'fail', '1.075 is outside a +/-5% band'


# ---------------------------------------------------------------------- gate

def _scales(**kw):
    return {k: {'status': v[0], 'explanation': v[1]} for k, v in kw.items()}


def test_gate_blocks_failed_and_unmeasured_keeps_sound():
    scales = _scales(
        hull=('pass', 'scale 0.982'),
        bow=('pass', 'scale 1.075 wide'),
        zone3=('fail', 'scale 0.236 outside 0.90-1.10'),
        zone9=('unmeasured', 'no pose harvest on disk'),
    )
    targets = [{'key': k, 'camera_count': 100} for k in scales]
    kept, blocked = merge_zones.apply_scale_gate(targets, scales, 0.90, 1.10, LOG)

    assert [c['key'] for c in kept] == ['hull', 'bow']
    assert {b['key'] for b in blocked} == {'zone3', 'zone9'}
    assert {b['status'] for b in blocked} == {'fail', 'unmeasured'}


def test_worst_input_decides_for_a_fused_component():
    """A sound sibling must not launder a broken input through a fusion."""
    scales = _scales(good=('pass', 'scale 0.99'), bad=('fail', 'scale 0.236'))
    fused = [{'key': 'merged_0', 'camera_count': 500, 'inputs': ['good', 'bad']}]
    kept, blocked = merge_zones.apply_scale_gate(fused, scales, 0.90, 1.10, LOG)

    assert kept == []
    assert blocked[0]['status'] == 'fail'


def test_component_with_no_scale_record_is_blocked():
    kept, blocked = merge_zones.apply_scale_gate(
        [{'key': 'orphan', 'camera_count': 100}], {}, 0.90, 1.10, LOG)
    assert kept == []
    assert blocked[0]['status'] == 'unmeasured'


def test_all_blocked_is_reported_not_silently_empty(caplog):
    scales = _scales(only=('fail', 'scale 0.20'))
    with caplog.at_level(logging.ERROR):
        kept, blocked = merge_zones.apply_scale_gate(
            [{'key': 'only', 'camera_count': 100}], scales, 0.90, 1.10, LOG)
    assert kept == []
    assert len(blocked) == 1
    assert any('EVERY model target' in r.message for r in caplog.records)


def test_sound_only_set_is_untouched():
    scales = _scales(a=('pass', 'scale 1.00'), b=('pass', 'scale 0.98'))
    targets = [{'key': 'a', 'camera_count': 10}, {'key': 'b', 'camera_count': 20}]
    kept, blocked = merge_zones.apply_scale_gate(targets, scales, 0.90, 1.10, LOG)
    assert kept == targets and blocked == []


if __name__ == '__main__':
    sys.exit(pytest.main([__file__, '-v']))
