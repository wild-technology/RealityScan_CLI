#!/usr/bin/env python3
"""Pins the rig mount table and its family resolution (review M4/M5).

Three bugs motivated this, all found 2026-07-26:

M5  The georeferencer matched literal cruise digits ('p231c', 'c231c'), so the
    next cruise's 'C245C0007_*.jpg' fell through to a ZERO lever arm and a 0 deg
    pitch offset - Cinema losing its 45 deg down-look - asserted at 10 deg
    confidence, with one suppressed warning for the whole run. WCA Starboard
    ('S231C*') fell through even for the CURRENT cruise.

M4  geoall.py - which CLAUDE.md hard rule 6 and the README call the CANONICAL
    georeferencer - had no WCA branch at all and claimed 3 deg orientation
    accuracy where the module claimed 15. Same rig, two answers.

A design trap this test guards: geometry belongs to the FILENAME FAMILY, not to
the physical camera. Legacy 'camlower' and WCA 'C###C' are the SAME Cinema unit
mounted 35 deg apart, so keying geometry off camera_registry.identify() would
silently rewrite every legacy dataset.

Values below are the ones in force on 2026-07-26. If a change is intended,
change them here deliberately - that is the point.

Run:  py -3.13 -m pytest testing/test_rig_mounts.py
"""

from __future__ import annotations

import json
import logging
import os
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, REPO_ROOT)

import geoall  # noqa: E402
from modules import camera_registry  # noqa: E402
from modules.georeference.georeference_images import (  # noqa: E402
    MOUNTS,
    GeoreferenceImages,
)

# family -> (lever arm (fwd, lat, down), pitch offset deg, pitch accuracy deg)
EXPECTED = {
    'zeuss': ((0.5, 0.0, 0.5), 30.0, 30.0),
    'legacy_camupper': ((1.0, 0.0, 0.0), 70.0, 10.0),
    'legacy_cammid': ((1.0, 0.0, 1.0), 20.0, 10.0),
    'legacy_camlower': ((1.0, 0.0, 1.0), 10.0, 5.0),
    'wca_port': ((1.0, 0.0, 1.0), 0.0, 15.0),
    'wca_cinema': ((1.0, 0.0, 0.0), 45.0, 15.0),
}

SAMPLE = {
    'zeuss': 'zeuss_0001.jpg',
    'legacy_camupper': 'camupper_0001.jpg',
    'legacy_cammid': 'cammid_0001.jpg',
    'legacy_camlower': 'camlower_0001.jpg',
    'wca_port': 'P231C0003_20231103235906_edt.jpg',
    'wca_cinema': 'C231C0003_20231103235906_edt.jpg',
}


@pytest.fixture()
def geo():
    logging.disable(logging.CRITICAL)
    return GeoreferenceImages(logging.getLogger('test'))


# ------------------------------------------------------------------- families

@pytest.mark.parametrize('filename,expected', [
    ('camupper_1.jpg', 'legacy_camupper'),
    ('cammid_1.jpg', 'legacy_cammid'),
    ('camlower_1.jpg', 'legacy_camlower'),
    ('zeuss_1.jpg', 'zeuss'),
    ('dive_herc_1.jpg', 'zeuss'),
    ('P231C0003_x.jpg', 'wca_port'),
    ('C231C0003_x.jpg', 'wca_cinema'),
    ('S231C0003_x.jpg', 'wca_starboard'),
    # M5: cruise digits vary and must NOT decide the family
    ('P245C0007_x.jpg', 'wca_port'),
    ('C245C0007_x.jpg', 'wca_cinema'),
    ('c9999c0001_x.jpg', 'wca_cinema'),
    ('unrecognised.jpg', None),
])
def test_family_resolution(filename, expected):
    assert camera_registry.family(filename) == expected


def test_anchored_wca_beats_a_herc_substring():
    """'herc' used to be tested first, unanchored, and would have won."""
    assert camera_registry.family('P231C0003_herc.jpg') == 'wca_port'


def test_family_and_camera_are_separate_concepts():
    """Same physical camera, two mounts 35 deg apart - the design trap."""
    assert camera_registry.identify('camlower_1.jpg').key == 'cinema'
    assert camera_registry.identify('C231C0003_x.jpg').key == 'cinema'
    assert MOUNTS['legacy_camlower']['pitch'] == 10.0
    assert MOUNTS['wca_cinema']['pitch'] == 45.0


def test_every_family_maps_to_a_known_camera():
    for fam in camera_registry.FAMILY_CAMERA.values():
        assert fam in camera_registry.CAMERAS


def test_every_family_has_a_mount_entry():
    """A family with no MOUNTS key would silently get zeros."""
    for fam in camera_registry.FAMILY_CAMERA:
        assert fam in MOUNTS, f'{fam} has no MOUNTS entry'


# -------------------------------------------------------------------- values

@pytest.mark.parametrize('family,expected', EXPECTED.items())
def test_mount_values_are_pinned(family, expected):
    lever, pitch, p_acc = expected
    m = MOUNTS[family]
    assert (m['fwd'], m['lat'], m['down']) == lever
    assert m['pitch'] == pitch
    assert m['p_acc'] == p_acc


@pytest.mark.parametrize('family,filename', SAMPLE.items())
def test_georeference_resolves_each_family(geo, family, filename):
    lever, pitch, p_acc = EXPECTED[family]
    assert geo._get_camera_offsets(filename) == lever
    assert geo._get_camera_pitch_offset(filename) == pitch
    assert geo._get_camera_pitch_accuracy(filename) == p_acc


def test_port_sits_one_metre_below_cinema(geo):
    """The validated relationship. Two metrically-sound solves put C above P by
    +1.12 m and +1.03 m; the 0.22 m / 0.00 m figures in FINDINGS came from the
    0.175-scale hull and are scale-corrupted."""
    _, _, port_down = geo._get_camera_offsets('P231C0003_x.jpg')
    _, _, cinema_down = geo._get_camera_offsets('C231C0003_x.jpg')
    assert port_down - cinema_down == pytest.approx(1.0)


def test_next_cruise_digits_get_real_geometry(geo):
    """M5 regression: this used to be a zero lever arm at 10 deg confidence."""
    assert geo._get_camera_offsets('C245C0007_x.jpg') == (1.0, 0.0, 0.0)
    assert geo._get_camera_pitch_offset('C245C0007_x.jpg') == 45.0
    assert geo._get_camera_pitch_accuracy('C245C0007_x.jpg') == 15.0


def test_unmeasured_starboard_is_counted_not_silently_zeroed(geo):
    """Starboard's mount was never measured; the run must say so."""
    before = geo._unknown_camera_count
    assert geo._get_camera_offsets('S231C0003_x.jpg') == (0.0, 0.0, 0.0)
    assert geo._unknown_camera_count > before
    assert MOUNTS['wca_starboard'] is None, 'do not invent starboard geometry'


def test_unknown_family_is_counted(geo):
    before = geo._unknown_camera_count
    geo._get_camera_offsets('totally_unknown.jpg')
    assert geo._unknown_camera_count > before


# ------------------------------------------------------- geoall parity (M4)

@pytest.mark.parametrize('family,filename', SAMPLE.items())
def test_geoall_matches_the_module(geo, family, filename):
    """geoall is documented canonical; it must not disagree with the module."""
    assert geoall.get_camera_offsets(filename) == geo._get_camera_offsets(filename)
    assert geoall.get_camera_pitch_offset(filename) == geo._get_camera_pitch_offset(filename)
    # Pitch ACCURACY was the one column the M4/M5 unification missed: geoall
    # kept a stale prefix chain that gave WCA 10.0 against the module's 15.0
    # and Zeuss 10.0 against 30.0 - a 3x-overconfident prior on the mount
    # with the least ground truth, and PD-0 shows over-tight orientation
    # accuracy FRAGMENTS the solve (audit #6, 2026-07-28).
    assert geoall.get_camera_pitch_accuracy(filename) == \
        geo._get_camera_pitch_accuracy(filename)


@pytest.mark.parametrize('filename', ['S231C0003_x.jpg', 'mystery_cam.jpg'])
def test_geoall_fallback_matches_the_module_for_unmapped_families(geo, filename):
    """Starboard (mount None) and unknown families must fall back to the SAME
    figure in both implementations - the parity requirement does not stop at
    the mapped families (final review: geoall briefly used 15 vs 10)."""
    assert geoall.get_camera_pitch_accuracy(filename) == \
        geo._get_camera_pitch_accuracy(filename)


def test_geoall_covers_wca_at_all(geo):
    """geoall had NO WCA branch, so Cinema lost its 45 deg down-look."""
    assert geoall.get_camera_pitch_offset('C231C0003_x.jpg') == 45.0
    assert geoall.get_camera_offsets('P231C0003_x.jpg') == (1.0, 0.0, 1.0)


def test_geoall_orientation_accuracy_is_the_measured_value():
    """3 deg FRAGMENTS the solve (PD-0); 15 deg is the measured figure."""
    src = open(os.path.join(REPO_ROOT, 'geoall.py'), encoding='utf-8').read()
    assert 'yaw_acc = 15.0' in src
    assert 'roll_acc = 15.0' in src
    assert 'yaw_acc = 3.0' not in src


# ------------------------------------------------- cameras.json parity (belt)
# camera_registry already hard-fails the import if cameras.json diverges from
# its retained legacy tables (the brace); these tests are the belt on top -
# they re-read the JSON independently and compare it against the RUNTIME
# tables, including the MOUNTS copy that still lives in the georeference
# module (migration step (c+) has not rewired it yet).

CAMERAS_JSON = os.path.join(REPO_ROOT, 'modules', 'cameras.json')


def _cameras_json() -> dict:
    with open(CAMERAS_JSON, encoding='utf-8') as f:
        return json.load(f)


def test_cameras_json_families_match_runtime_family_camera():
    data = _cameras_json()
    parsed = {f['family']: f['camera'] for f in data['families']}
    assert parsed == camera_registry.FAMILY_CAMERA


def test_cameras_json_mounts_match_the_runtime_mounts_table():
    """families[].mount must be a byte-for-byte port of MOUNTS, null
    included (null means WARN, never zeros - the Starboard rule)."""
    data = _cameras_json()
    parsed = {}
    for entry in data['families']:
        mount = entry['mount']
        if mount is not None:
            mount = {k: v for k, v in mount.items() if not k.startswith('_')}
        parsed[entry['family']] = mount
    assert parsed == MOUNTS


def test_cameras_json_cameras_match_runtime_registry():
    data = _cameras_json()
    for key, cam in camera_registry.CAMERAS.items():
        spec = data['cameras'][key]
        assert cam == camera_registry.Camera(
            key,
            spec['calibration_group'],
            spec['calibration_prior'],
            spec['focal_length_35mm'],
            spec['lens_distortion_group'],
            spec['lens_distortion_prior'],
            spec['distortion_model'],
        ), f'cameras.json diverges at cameras[{key!r}]'


def test_cameras_json_patterns_resolve_like_the_runtime_matcher():
    """The JSON regexes ARE the runtime matcher now; pin the behavior via
    the sample filenames rather than trusting the wiring."""
    data = _cameras_json()
    import re as _re
    matchers = [(_re.compile(f['pattern'], _re.IGNORECASE), f['family'])
                for f in data['families']]

    def json_family(name: str) -> str | None:
        low = name.lower()
        for pattern, fam in matchers:
            if pattern.search(low):
                return fam
        return None

    for fam, filename in SAMPLE.items():
        assert json_family(filename) == fam == camera_registry.family(filename)
    assert json_family('S231C0003_x.jpg') == 'wca_starboard'
    assert json_family('unrecognised.jpg') is None


def test_cameras_json_defaults_match_the_flight_log_literals():
    """defaults port the accuracy literals still hardcoded in the two
    flight-log writers; keep them equal until migration step (c+)."""
    data = _cameras_json()
    d = data['defaults']
    pos, ori = d['position_accuracy_m'], d['orientation_accuracy_deg']
    for path in (os.path.join(REPO_ROOT, 'modules', 'georeference',
                              'georeference_images.py'),
                 os.path.join(REPO_ROOT, 'geoall.py')):
        src = open(path, encoding='utf-8').read()
        assert f"pos_x_acc = {pos['x']}" in src, path
        assert f"pos_y_acc = {pos['y']}" in src, path
        assert f"alt_acc = {pos['alt']}" in src, path
        assert f"yaw_acc = {ori['yaw']}" in src, path
        assert f"roll_acc = {ori['roll']}" in src, path
    # The unknown-mount pitch fallback, shared by both implementations
    assert geoall.get_camera_pitch_accuracy('mystery_cam.jpg') == \
        d['unknown_mount_pitch_accuracy_deg']


def test_cameras_json_voyis_entries_are_data_only():
    """The UNVERIFIED voyis eyes must stay out of the runtime CAMERAS table
    until a family references them (RealityScan has no stereo-rig support;
    the rigs section is DATA-ONLY)."""
    data = _cameras_json()
    assert data['cameras']['voyis_left']['calibration_group'] == '5'
    assert data['cameras']['voyis_right']['calibration_group'] == '6'
    assert 'voyis_left' not in camera_registry.CAMERAS
    assert 'voyis_right' not in camera_registry.CAMERAS
    rig = data['rigs']['on2026_voyis']
    assert rig['frame'] == 'local_euclidean'
    assert rig['axes'] is None, 'ENU-vs-NED is an OPEN owner decision'
    assert rig['stereo_baseline_m'] is None, 'unmeasured on ON2026 - keep null'
    assert (rig['position_accuracy_m'], rig['orientation_accuracy_deg']) == \
        (0.02, 90.0)


if __name__ == '__main__':
    sys.exit(pytest.main([__file__, '-v']))
