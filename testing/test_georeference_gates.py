#!/usr/bin/env python3
"""Georeference: acceptance gate, uncertainty knobs, zone pinning, priors.

Step 5/6/7 of the owner's chain. Every case below was reachable on a new
expedition and reported Success=True (audit 2026-08-07):

  - ZERO images matched the nav table (wrong nav CSV, wrong --g_type, a
    clock offset): the module wrote a header-only
    flight_log_UNKNOWN_UTM.txt and returned Success=True. That filename
    carries no zone tag, so downstream classified the cruise as a
    LOCAL/geocent campaign - the frame guard bypassed by its own naming
    convention.
  - a PARTIAL match (4% of the dive) was caught NOWHERE: batching zoned
    the survivors and align/merge/model all succeeded on a fraction.
  - the five accuracy figures were function locals in TWO files: step 6
    of the chain, "calculation/use of uncertainty", had no knob anywhere.
  - the UTM zone latched on the first row while every later row was
    converted in ITS OWN zone: a track crossing a boundary got a silent
    ~500 km easting jump inside a log claiming one zone.
  - an unknown/unmeasured mount produced a 0 deg tilt claimed at 10 deg
    confidence - the invention MOUNTS['wca_starboard'] = None exists to
    refuse.

Offline: real module, tempdir imagery, a synthetic nav CSV. No
RealityScan.

Run:  py -3.13 -m pytest testing/test_georeference_gates.py
"""
from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timedelta

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, REPO_ROOT)

pytest.importorskip('utm')
pytest.importorskip('PIL')

from PIL import Image  # noqa: E402

from module_base.parameter import Parameter  # noqa: E402
from modules.georeference.georeference_images import (  # noqa: E402
    PRIOR_ACCURACY_DEFAULTS, GeoreferenceImages)

QUIET = logging.getLogger('georef-test')
QUIET.addHandler(logging.NullHandler())
QUIET.propagate = False

BASE = datetime(2026, 8, 7, 12, 0, 0)


def _params(**overrides):
    """The parameter dict the orchestrator injects, defaults from the
    module's own get_parameters()."""
    module = GeoreferenceImages(QUIET)
    params = module.get_parameters()
    for name, value in overrides.items():
        if name in params:
            params[name].set_value(value)
        else:
            params[name] = Parameter(name, None, name, type(value), value,
                                     prompt_user=False)
    return params


def _module(**overrides):
    module = GeoreferenceImages(QUIET)
    module.params = _params(**overrides)
    return module


def _images(directory, names, start=BASE, step_s=1):
    directory.mkdir(parents=True, exist_ok=True)
    for i, name in enumerate(names):
        stamp = (start + timedelta(seconds=i * step_s)).strftime(
            '%Y%m%dT%H%M%SZ')
        Image.new('RGB', (4, 4)).save(directory / f'{name}_{stamp}.jpg')


def _nav(path, rows, start=BASE, lat=35.0, lon=139.0, step_s=1):
    lines = ['Timestamp,kalman_lat,kalman_long,kalman_depth,kalman_yaw_deg,'
             'kalman_pitch_deg,kalman_roll_deg']
    for i in range(rows):
        stamp = (start + timedelta(seconds=i * step_s)).strftime(
            '%Y-%m-%dT%H:%M:%SZ')
        lines.append(f'{stamp},{lat},{lon},10.0,90.0,0.0,0.0')
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return path


def _run(tmp_path, image_names, nav_rows=20, nav_start=BASE, **overrides):
    raw = tmp_path / 'raw_images'
    _images(raw, image_names)
    nav = _nav(tmp_path / 'nav.csv', nav_rows, start=nav_start)
    module = _module(geo_input_image_dir=str(raw),
                     geo_input_flight_log=str(nav),
                     geo_input_type='All',
                     output_dir=str(tmp_path), **overrides)
    return module, module.run(), raw


def _rows(path):
    with open(path, encoding='utf-8') as fh:
        lines = [ln.rstrip('\n') for ln in fh if ln.strip()]
    return lines[0], lines[1:]


# ------------------------------------------------------- acceptance gate

def test_zero_matches_fails_the_stage(tmp_path):
    """Images five years off the nav table = wrong nav file / clock
    offset. This returned Success=True with a header-only log."""
    raw = tmp_path / 'raw_images'
    _images(raw, ['P231C0001', 'P231C0002'],
            start=BASE.replace(year=2021))
    nav = _nav(tmp_path / 'nav.csv', 20)
    module = _module(geo_input_image_dir=str(raw),
                     geo_input_flight_log=str(nav),
                     geo_input_type='All', output_dir=str(tmp_path))
    result = module.run()
    assert result['Success'] is False
    assert 'matched' in result['Failure']
    assert result['Matched <=2s'] == 0


def test_zero_matches_never_writes_a_UTM_named_log(tmp_path):
    """flight_log_UNKNOWN_UTM.txt parses as "no zone tag", which every
    downstream consumer reads as a LOCAL-frame campaign - so the failure
    laundered itself into 'this cruise uses local:1 priors'."""
    raw = tmp_path / 'raw_images'
    _images(raw, ['P231C0001'], start=BASE.replace(year=2021))
    nav = _nav(tmp_path / 'nav.csv', 5)
    module = _module(geo_input_image_dir=str(raw),
                     geo_input_flight_log=str(nav),
                     geo_input_type='All', output_dir=str(tmp_path))
    module.run()
    produced = sorted(p.name for p in raw.iterdir() if p.suffix == '.txt')
    assert produced == ['flight_log_UNRESOLVED.txt']
    # The decisive property: it is OUTSIDE the discovery glob.
    from modules.flight_logs import find_flight_log
    assert find_flight_log(str(raw)) is None


def test_partial_match_below_the_floor_fails(tmp_path):
    """A nav table covering only the first few images: the survivors used
    to flow downstream looking like a complete dive."""
    raw = tmp_path / 'raw_images'
    _images(raw, [f'P231C{i:04d}' for i in range(10)])
    nav = _nav(tmp_path / 'nav.csv', 2)          # covers 2 of 10
    module = _module(geo_input_image_dir=str(raw),
                     geo_input_flight_log=str(nav),
                     geo_input_type='All', output_dir=str(tmp_path))
    result = module.run()
    assert result['Success'] is False
    assert 'floor' in result['Failure']
    assert result['Acceptance Rate %'] < 80.0


def test_the_floor_is_operator_settable(tmp_path):
    """Accepting a partial dive must be a DELIBERATE act, not the default."""
    raw = tmp_path / 'raw_images'
    _images(raw, [f'P231C{i:04d}' for i in range(10)])
    nav = _nav(tmp_path / 'nav.csv', 2)
    module = _module(geo_input_image_dir=str(raw),
                     geo_input_flight_log=str(nav),
                     geo_input_type='All', output_dir=str(tmp_path),
                     geo_min_accept_rate_pct=0.0)
    assert module.run()['Success'] is True


def test_a_complete_dive_still_succeeds(tmp_path):
    _module_, result, raw = _run(tmp_path, [f'P231C{i:04d}' for i in range(8)])
    assert result['Success'] is True
    assert result['Acceptance Rate %'] == 100.0
    assert os.path.basename(result['Output Flight Log']).endswith('_UTM.txt')
    assert 'UNKNOWN' not in result['Output Flight Log']


# ------------------------------------------------------ uncertainty knobs

def test_accuracies_are_parameters_and_are_prompted():
    """Step 6 of the chain had no knob at all - not a Parameter, not a
    flag, not a settings key. wildscan surfaces prompt_user params
    automatically, so prompt_user=True is what makes them reachable."""
    params = GeoreferenceImages(QUIET).get_parameters()
    for name, flag in (('geo_pos_accuracy_m', 'g_pos_accuracy'),
                       ('geo_alt_accuracy_m', 'g_alt_accuracy'),
                       ('geo_orientation_accuracy_deg',
                        'g_orientation_accuracy'),
                       ('geo_min_accept_rate_pct', 'g_min_accept_rate'),
                       ('magnetic_declination_deg', 'g_declination')):
        assert name in params, name
        assert params[name].cli_long == flag
        assert params[name].prompt_user is True, f'{name} is unreachable'


def test_accuracy_defaults_are_written_verbatim(tmp_path):
    _m, result, raw = _run(tmp_path, ['P231C0001', 'P231C0002'])
    _header, rows = _rows(result['Output Flight Log'])
    for row in rows:
        f = row.split(';')
        assert float(f[4]) == PRIOR_ACCURACY_DEFAULTS['pos_xy']
        assert float(f[5]) == PRIOR_ACCURACY_DEFAULTS['pos_xy']
        assert float(f[6]) == PRIOR_ACCURACY_DEFAULTS['alt']
        assert float(f[10]) == PRIOR_ACCURACY_DEFAULTS['yaw']
        assert float(f[12]) == PRIOR_ACCURACY_DEFAULTS['roll']


def test_accuracy_overrides_reach_the_flight_log(tmp_path):
    _m, result, raw = _run(tmp_path, ['P231C0001'],
                           geo_pos_accuracy_m=3.0,
                           geo_alt_accuracy_m=0.5,
                           geo_orientation_accuracy_deg=7.0)
    _header, rows = _rows(result['Output Flight Log'])
    fields = rows[0].split(';')
    assert float(fields[4]) == 3.0 and float(fields[5]) == 3.0
    assert float(fields[6]) == 0.5
    assert float(fields[10]) == 7.0 and float(fields[12]) == 7.0


def test_declination_reaches_the_yaw(tmp_path):
    """A named trajectory variable that was unreachable from every
    interactive path: prompt_user was False and geoall had no flag."""
    _m, plain, _raw = _run(tmp_path / 'a', ['P231C0001'])
    _m2, shifted, _raw2 = _run(tmp_path / 'b', ['P231C0001'],
                               magnetic_declination_deg=10.0)
    yaw_plain = float(_rows(plain['Output Flight Log'])[1][0].split(';')[7])
    yaw_shift = float(_rows(shifted['Output Flight Log'])[1][0].split(';')[7])
    assert round(yaw_shift - yaw_plain, 6) == 10.0


# ------------------------------------------------------- UTM zone pinning

def test_zone_is_pinned_across_a_zone_boundary():
    """utm.from_latlon with no force_zone re-picked the natural zone for
    every later row: measured 529,337 m of easting discontinuity inside
    one log."""
    module = _module()
    east_a, _n = module._GeoreferenceImages__convert_to_utm(35.0, 137.9)
    east_b, _n2 = module._GeoreferenceImages__convert_to_utm(35.0, 138.1)
    assert module.utm_zone == '53S'
    # Continuous frame: a 0.2 deg step is ~18 km, never ~529 km.
    assert abs(east_b - east_a) < 30_000
    assert module._utm_crossings == 1


def test_zone_is_pinned_across_the_equator():
    module = _module()
    _e, north_a = module._GeoreferenceImages__convert_to_utm(0.5, 137.0)
    _e2, north_b = module._GeoreferenceImages__convert_to_utm(-0.5, 137.0)
    assert module.utm_zone == '53N'
    assert abs(north_b - north_a) < 200_000, 'hemisphere flip re-introduced'


def test_a_single_zone_track_reports_no_crossings():
    module = _module()
    for lon in (139.0, 139.001, 139.002):
        module._GeoreferenceImages__convert_to_utm(35.0, lon)
    assert module._utm_crossings == 0


# --------------------------------------------------------- unmeasured mount

def test_unmeasured_mount_takes_the_house_convention():
    """Owner convention (2026-08-31): a camera family with NO measured mount
    is assumed to look 10 deg down and otherwise ride the vehicle attitude.

    This REPLACES the 2026-08-07 behaviour of writing no pitch prior at all.
    That audit removed a 0 deg tilt asserted at 10 deg accuracy; the half of
    its reasoning that survives is the accuracy, which is why the assumed
    tilt is claimed at 30 deg - no tighter than the loosest MEASURED mount.
    """
    module = _module()
    assert module._get_camera_pitch_offset('mystery_cam_0001.jpg') == 10.0
    assert module._get_camera_pitch_accuracy('mystery_cam_0001.jpg') == 30.0
    # Starboard is a KNOWN family whose mount has never been measured.
    assert module._get_camera_pitch_offset('S231C0001.jpg') == 10.0
    assert module._get_camera_pitch_accuracy('S231C0001.jpg') == 30.0
    # A MEASURED mount always wins over the assumption.
    # Owner correction 2026-08-14: cinema points directly forward; the
    # 45 deg down-look belongs to upper (wca_upper).
    assert module._get_camera_pitch_offset('C231C0001.jpg') == 0.0
    assert module._get_camera_pitch_offset('U231C0001.jpg') == 45.0
    assert module._get_camera_pitch_accuracy('U231C0001.jpg') == 15.0
    assert module._get_camera_pitch_accuracy('C231C0001.jpg') == 15.0
    assert module._get_camera_pitch_offset('P231C0001.jpg') == 0.0
    assert module._get_camera_pitch_accuracy('P231C0001.jpg') == 15.0


def test_voyis_families_never_take_the_assumed_mount():
    """Their poses come from the COLMAP bridge, so a vehicle-nav prior is the
    WRONG PIPELINE rather than a missing measurement. Falling back would mask
    a pipeline-selection error that the null in MOUNTS exists to surface."""
    module = _module()
    for stem in ('l_2024-01-01_10-00-00.jpg', 'r_2024-01-01_10-00-00.jpg',
                 'image_left_000123.tif'):
        assert module._get_camera_pitch_offset(stem) is None, stem
        assert module._get_camera_pitch_accuracy(stem) is None, stem


def test_the_assumption_can_be_switched_off(tmp_path):
    """A negative assumed pitch restores the 2026-08-07 behaviour exactly."""
    module = _module()
    module.params['geo_assumed_pitch_deg'].value = -1.0
    assert module._get_camera_pitch_offset('mystery_cam_0001.jpg') is None
    assert module._get_camera_pitch_accuracy('mystery_cam_0001.jpg') is None
    # and a measured mount is STILL untouched by the opt-out
    assert module._get_camera_pitch_offset('C231C0001.jpg') == 0.0
    assert module._get_camera_pitch_offset('U231C0001.jpg') == 45.0


def test_unmeasured_mount_rows_carry_the_assumed_pitch(tmp_path):
    """Yaw and roll still come from the nav table; the two MOUNT-derived
    fields now carry the assumption instead of going blank - and they must
    move together, since a pitch with an empty accuracy is a malformed row."""
    _m, result, _raw = _run(tmp_path, ['S231C0001', 'S231C0002'],
                            geo_min_accept_rate_pct=0.0)
    _header, rows = _rows(result['Output Flight Log'])
    assert rows, 'nothing was written'
    for row in rows:
        f = row.split(';')
        assert float(f[8]) == pytest.approx(80.0, abs=15.0), (
            f'assumed pitch not written as 90 + (vehicle_pitch - 10): {row}')
        assert float(f[11]) == 30.0, f'wrong assumed accuracy: {row}'
        assert f[7] != '' and f[9] != '', 'real nav yaw/roll were discarded'
    # The count still reports what had no MEASURED mount - the assumption
    # does not make the gap invisible.
    assert result['Rows Without Pitch Prior'] == len(rows)


def test_a_dive_of_only_unmeasured_cameras_is_refused(tmp_path):
    """"Add the family before trusting this run" has to be a refusal, not
    one suppressed warning."""
    _m, result, _raw = _run(tmp_path, ['mystery_a', 'mystery_b'])
    assert result['Success'] is False
    assert 'mount' in result['Failure']


def test_measured_cameras_are_unaffected(tmp_path):
    _m, result, _raw = _run(tmp_path, ['C231C0001', 'C231C0002'])
    assert result['Success'] is True
    assert result['Rows Without Pitch Prior'] == 0
    _header, rows = _rows(result['Output Flight Log'])
    for row in rows:
        f = row.split(';')
        assert f[8] != '' and f[11] == '15.000000'


# ---------------------------------------------------- format visibility

class _Capture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.messages: list[str] = []

    def emit(self, record):
        self.messages.append(record.getMessage())


def test_unprocessable_formats_are_reported_not_hidden(tmp_path):
    """A .tif dataset was 'present' to the workspace census and invisible
    here: 'extract done, 2 images' against 'georeferenced 1'.

    Its own handler, not caplog: the module logger under test deliberately
    does not propagate."""
    raw = tmp_path / 'raw_images'
    _images(raw, ['P231C0001'])
    Image.new('RGB', (4, 4)).save(raw / 'P231C0002_20260807T120100Z.tif')
    nav = _nav(tmp_path / 'nav.csv', 20)
    capture = _Capture()
    logger = logging.getLogger('georef-format-test')
    logger.propagate = False
    logger.setLevel(logging.WARNING)
    logger.addHandler(capture)
    module = GeoreferenceImages(logger)
    module.params = _params(geo_input_image_dir=str(raw),
                            geo_input_flight_log=str(nav),
                            geo_input_type='All', output_dir=str(tmp_path))
    try:
        result = module.run()
    finally:
        logger.removeHandler(capture)
    assert result['Files Skipped By Extension'] == 1
    assert any('.tif' in m and 'cannot process' in m
               for m in capture.messages), capture.messages


def test_a_mixed_rig_of_measured_and_unmeasured_cameras_still_runs(tmp_path):
    """The refusal is "EVERY image", not "any image".

    The gate first compared _unknown_camera_count - a mount-LOOKUP counter
    incremented three times per image (lever arm, pitch offset, pitch
    accuracy) - against files_listed, so it fired at a THIRD unmeasured
    cameras. Measured on this fixture: 2 Cinema + 1 Starboard returned
    Success=False with 'no image has a measured camera mount', which is
    false - the owner's rig carries Port, Cinema AND Starboard, and
    Starboard is the one with no measured mount
    (audit-verification 2026-08-07)."""
    for names in (['C231C0001', 'C231C0002', 'S231C0003'],
                  ['C231C0001', 'C231C0002', 'S231C0003', 'S231C0004'],
                  ['P231C0001', 'C231C0002', 'S231C0003']):
        _m, result, _raw = _run(tmp_path / '+'.join(names), names)
        assert result['Success'] is True, (names, result.get('Failure'))
        # ... and the unmeasured rows are still reported, not hidden.
        assert result['Rows Without Pitch Prior'] == \
            sum(1 for n in names if n.startswith('S'))
