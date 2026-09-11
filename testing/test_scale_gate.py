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


def _xmp(zone, round_k, cams, scale=1.0):
    """One identity_r<K> harvest lap, in the shape AlignZone.bat's legacy
    branch leaves behind: stem-named sidecars carrying xcr:Position in the
    MODEL frame (rotated, shifted and scaled away from the nav, because the
    oracle compares distance ratios and never absolute placement).

    The other attributes are the ones a real zone-scene export carries
    (measured on the NA173 F2 peel, 2026-09-06); they are inert to the
    oracle and present so the fixture encodes the real file shape rather
    than a minimal one.
    """
    d = zone / f'identity_r{round_k}'
    d.mkdir(parents=True, exist_ok=True)
    for name, (x, y, z) in cams:
        mx, my = -(y - 8980000.0) * scale + 3.0, (x - 585000.0) * scale - 7.0
        mz = (z + 850.0) * scale
        (d / f'{name}.xmp').write_text(
            '<x:xmpmeta xmlns:x="adobe:ns:meta/">'
            '<rdf:RDF><rdf:Description '
            'xcr:Version="3" xcr:PosePrior="initial" '
            'xcr:CalibrationPrior="initial" xcr:CalibrationGroup="-1" '
            'xcr:DistortionGroup="-1" xcr:DistortionModel="perspective" '
            'xcr:Coordinates="absolute" xcr:ExportCoordinateSystemType="2">'
            f'<xcr:Position>{mx} {my} {mz}</xcr:Position>'
            '</rdf:Description></rdf:RDF></x:xmpmeta>',
            encoding='utf-8')
    return d


# ------------------------------------------- XMP identity lane (the default)
#
# The twins of the three CSV-lane cases below. Written 2026-09-06: the CSV
# lane had a complete on-disk set (known-good, known-bad, membership) while
# the DEFAULT lane - the destructive identity_r<K> harvest that runs whenever
# RS_LEGACY_XMP_IDENTITY is not "0" - had none, so the standing oracle rule
# (a known-good AND a known-bad before anything relies on it) was satisfied
# for the opt-in lane and not for the default one. modules/scale_oracle.py's
# successive-difference membership reader had no test at all.

def test_xmp_lane_measures_a_sound_component(tmp_path):
    """KNOWN-GOOD: a harvest whose spacing matches the nav reads 1.0."""
    cams = _line_cameras()
    zone = tmp_path / 'zone_1'
    _xmp(zone, 0, cams, scale=1.0)
    nav = scale_oracle.load_nav_positions(_nav(tmp_path / 'flight_log_57L_UTM.txt', cams))
    stats = scale_oracle.scale_for_images([f'{n}.jpg' for n, _ in cams], str(zone), nav)
    assert stats is not None and stats['cameras'] == 40
    assert scale_oracle.verdict(stats)[0] == 'pass'
    assert abs(stats['median'] - 1.0) < 1e-6


def test_xmp_lane_catches_a_collapse(tmp_path):
    """KNOWN-BAD: the real H2024 zone_3 collapse, read from a harvest."""
    cams = _line_cameras()
    zone = tmp_path / 'zone_1'
    _xmp(zone, 0, cams, scale=0.236)
    nav = scale_oracle.load_nav_positions(_nav(tmp_path / 'flight_log_57L_UTM.txt', cams))
    stats = scale_oracle.scale_for_images([f'{n}.jpg' for n, _ in cams], str(zone), nav)
    status, why = scale_oracle.verdict(stats)
    assert status == 'fail' and '0.236' in why


def test_xmp_lane_membership_is_successive_difference(tmp_path):
    """The DEFAULT lane's membership reader, previously untested.

    Lap 0 harvests every component still in the scene; the maximal one is
    then exported and deleted, so lap 1 holds what remains.
    members(c0) = stems(r0) - stems(r1), members(c1) = stems(r1).
    """
    cams = _line_cameras(80)
    zone = tmp_path / 'zone_1'
    _xmp(zone, 0, cams)                 # 80 stems: both components
    _xmp(zone, 1, cams[50:])            # 30 stems: c0 has been peeled off
    log = _nav(tmp_path / 'flight_log_57L_UTM.txt', cams)
    members = scale_oracle.component_members(str(zone))
    assert [len(m) for m in members] == [50, 30]
    rows = scale_oracle.report(str(zone), log)
    assert [r['component'] for r in rows] == [0, 1]


def test_xmp_lane_empty_harvest_is_unmeasured_not_a_pass(tmp_path):
    """An empty lap is the exhaustion terminal, never evidence of scale."""
    cams = _line_cameras()
    zone = tmp_path / 'zone_1'
    (zone / 'identity_r0').mkdir(parents=True)
    nav = scale_oracle.load_nav_positions(_nav(tmp_path / 'flight_log_57L_UTM.txt', cams))
    assert scale_oracle.scale_for_images([f'{n}.jpg' for n, _ in cams], str(zone), nav) is None
    assert scale_oracle.component_members(str(zone)) == []


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
    _xmp(zone, 0, cams, scale=0.5)    # an XMP lane at half scale beside the CSV
    stats = scale_oracle.scale_for_images([f'{n}.jpg' for n, _ in cams], str(zone), nav)
    assert abs(stats['median'] - 0.5) < 1e-6


# ---------------------------------------------------------------------------
# The scale verdict must not depend on the interpreter's hash seed
# ---------------------------------------------------------------------------
# scale_ratio built its candidate list by iterating a SET. Python randomises
# str hashing per process, so the list order - and therefore which pairs
# rng.sample drew - changed between invocations. The fixed seed=5 made this
# invisible: results were perfectly stable WITHIN a process and moved BETWEEN
# processes, so any repeatability check written the obvious way (call it five
# times in a loop) reports zero spread and proves nothing.
#
# MEASURED 2026-09-09 before the fix, NA165/H2060 zone_2 c0, identical inputs:
#     PYTHONHASHSEED=0   0.994725   PYTHONHASHSEED=1   0.995990
#     PYTHONHASHSEED=2   0.998415
# Two measurements of the same zone minutes apart reported 57.8% and 51.9% of
# cameras in band. This gate decides which components reach modelling, so a
# component near a band edge changed fate on nothing but the hash seed.
#
# The test therefore MUST cross a process boundary. An in-process assertion
# cannot detect the defect it is guarding against.

import subprocess  # noqa: E402

_PROBE = '\n'.join([
    'import sys, math, random',
    'sys.path.insert(0, %r)' % REPO_ROOT,
    'from modules.scale_oracle import scale_ratio',
    # Deterministic synthetic scene: 300 cameras on a jittered line, with a
    # scale that DRIFTS along the track (0.95 -> 1.12) rather than a uniform
    # factor.
    #
    # The drift is the whole point. A uniform scale makes every pairwise ratio
    # identical, so the median is insensitive to WHICH pairs get drawn - and
    # the first version of this fixture did exactly that: under the pre-fix
    # code the median came back 1.037000000000 under every hash seed, and only
    # the pair COUNT moved (3979 / 3969 / 3975). The test would then have been
    # catching the defect incidentally, through a bookkeeping number, instead
    # of through the quantity that decides a component's fate. Real components
    # drift; the fixture must too, or it does not exercise the failure.
    'rng = random.Random(11)',
    # Single %, not %%: only the sys.path line above goes through % formatting,
    # so every other entry here is a plain literal.
    'names = ["img_%05d_%s" % (i, "abcdefgh"[i % 8]) for i in range(300)]',
    'nav = {}',
    'solved = {}',
    'for i, n in enumerate(names):',
    '    x = i * 1.7 + rng.uniform(-0.3, 0.3)',
    '    y = rng.uniform(-2.0, 2.0)',
    '    z = rng.uniform(-0.5, 0.5)',
    '    s = 0.95 + 0.17 * (i / 299.0)',
    '    nav[n] = (x, y, z)',
    '    solved[n] = (x * s, y * s, z * s)',
    'st = scale_ratio(set(names), solved, nav)',
    'print("%.12f %d %d" % (st["median"], st["pairs"], st["cameras"]))',
])


def _probe_under(hashseed: str) -> str:
    import os as _os
    env = dict(_os.environ, PYTHONHASHSEED=hashseed)
    out = subprocess.run([sys.executable, '-c', _PROBE], capture_output=True,
                         text=True, env=env, timeout=180)
    assert out.returncode == 0, out.stderr
    return out.stdout.strip()


def test_scale_is_identical_across_interpreter_hash_seeds():
    """The defect, caught the only way it can be caught."""
    results = {hs: _probe_under(hs) for hs in ('0', '1', '2', '12345')}
    assert len(set(results.values())) == 1, (
        'scale_ratio depends on PYTHONHASHSEED - the candidate list is being '
        'built from an unsorted set again: %r' % results)


def test_the_probe_recovers_the_scale_it_was_given():
    """Guards the guard: if the fixture stopped exercising the real code path,
    the seed test above would pass on garbage.

    The scale drifts 0.95 -> 1.12 along the track, so the median depends on
    which pairs are drawn - which is precisely why the hash-seed test above
    has any power. Measured against the PRE-FIX code on this fixture the
    median moved 1.11828 / 1.12004 / 1.11884 / 1.11935 across four seeds; with
    a uniform-scale fixture it did not move at all.

    The band is deliberately loose. A per-POINT scale does not make the
    pairwise ratio the average of the two endpoint scales: for widely
    separated cameras the distance is dominated by the larger coordinate, so
    the ratio skews toward the high end of the drift (~1.119 here, just above
    the nominal 1.12 ceiling). Pinning a tight expectation would be pinning
    that geometric accident, not the behaviour under test."""
    median, pairs, cameras = _probe_under('0').split()
    assert 0.90 <= float(median) <= 1.30, median
    assert int(cameras) == 300
    assert int(pairs) > 1000


def test_scale_ratio_sorts_its_candidates():
    """Cheap structural belt so the reason survives a refactor that keeps the
    behaviour by accident."""
    import inspect
    from modules import scale_oracle
    src = inspect.getsource(scale_oracle.scale_ratio)
    assert 'sorted(' in src, (
        'scale_ratio no longer sorts its candidate list; the hash-seed '
        'dependence is back even if the subprocess test happens to pass')
