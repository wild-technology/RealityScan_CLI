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


# ------------------------------------------------- CSV identity lane (D1)
#
# The CSV capture (RS_LEGACY_XMP_IDENTITY=0) writes identity/<comp>.csv with
# x, y, z per camera instead of an identity_r0 XMP harvest. The oracle uses
# distance RATIOS only, so the export's frame is irrelevant; before
# 2026-09-06 it read the harvest alone and every CSV-lane component came
# back UNMEASURED (NA173 F2: the merge's scale gate passed vacuously).

def _line_cameras(n=40, step=5.0):
    return [(f'cam_{i:03d}', (585000.0 + i * step, 8980000.0 + 0.3 * i, -850.0))
            for i in range(n)]


def _nav(path, cams):
    lines = ['filename;X (East);Y (North);Alt']
    lines += [f'{name}.jpg;{x};{y};{z}' for name, (x, y, z) in cams]
    path.write_text(chr(10).join(lines) + chr(10), encoding='utf-8')
    return str(path)


def _csv(zone, comp, cams, scale=1.0):
    """Model-frame positions: rotated 90 deg, shifted, scaled by `scale`."""
    d = zone / 'identity'
    d.mkdir(parents=True, exist_ok=True)
    rows = [f'#cameras {len(cams)}', '#name,x,y,z,yaw,pitch,roll,focal,k1,k2']
    for name, (x, y, z) in cams:
        mx, my = -(y - 8980000.0) * scale + 3.0, (x - 585000.0) * scale - 7.0
        rows.append(f'{name}.jpg,{mx},{my},{(z + 850.0) * scale},0,0,0,2660,-0.39,0')
    (d / f'{comp}.csv').write_text(chr(10).join(rows) + chr(10), encoding='utf-8')


def test_csv_lane_measures_a_sound_component(tmp_path):
    cams = _line_cameras()
    zone = tmp_path / 'zone_1'
    _csv(zone, 'zone_1_c0', cams, scale=1.0)
    nav = scale_oracle.load_nav_positions(_nav(tmp_path / 'flight_log_57L_UTM.txt', cams))
    stats = scale_oracle.scale_for_images([f'{n}.jpg' for n, _ in cams], str(zone), nav)
    assert stats is not None and stats['cameras'] == 40
    assert scale_oracle.verdict(stats)[0] == 'pass'
    assert abs(stats['median'] - 1.0) < 1e-6


def test_csv_lane_catches_a_collapse(tmp_path):
    cams = _line_cameras()
    zone = tmp_path / 'zone_1'
    _csv(zone, 'zone_1_c0', cams, scale=0.236)
    nav = scale_oracle.load_nav_positions(_nav(tmp_path / 'flight_log_57L_UTM.txt', cams))
    stats = scale_oracle.scale_for_images([f'{n}.jpg' for n, _ in cams], str(zone), nav)
    status, why = scale_oracle.verdict(stats)
    assert status == 'fail' and '0.236' in why


def test_csv_lane_report_treats_each_csv_as_one_component(tmp_path):
    cams = _line_cameras(80)
    zone = tmp_path / 'zone_1'
    _csv(zone, 'zone_1_c0', cams[:50])
    _csv(zone, 'zone_1_c1', cams[50:])
    log = _nav(tmp_path / 'flight_log_57L_UTM.txt', cams)
    members = scale_oracle.component_members(str(zone))
    assert [len(m) for m in members] == [50, 30]
    rows = scale_oracle.report(str(zone), log)
    assert [r['component'] for r in rows] == [0, 1]


def test_xmp_harvest_still_wins_and_nothing_is_still_unmeasured(tmp_path):
    cams = _line_cameras()
    zone = tmp_path / 'zone_1'
    nav = scale_oracle.load_nav_positions(_nav(tmp_path / 'flight_log_57L_UTM.txt', cams))
    assert scale_oracle.scale_for_images([f'{n}.jpg' for n, _ in cams], str(zone), nav) is None
    _csv(zone, 'zone_1_c0', cams, scale=1.0)
    harvest = zone / 'identity_r0'
    harvest.mkdir()
    for name, (x, y, z) in cams:      # an XMP lane at half scale beside the CSV
        (harvest / f'{name}.xmp').write_text(
            f'<x:xmpmeta><rdf:Description xcr:Position="{x * 0.5} {y * 0.5} {z * 0.5}"/></x:xmpmeta>',
            encoding='utf-8')
    stats = scale_oracle.scale_for_images([f'{n}.jpg' for n, _ in cams], str(zone), nav)
    assert abs(stats['median'] - 0.5) < 1e-6
