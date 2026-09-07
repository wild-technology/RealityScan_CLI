#!/usr/bin/env python3
"""Guards added for the NA165/H2060 owner directives (2026-09-06).

Each test here pins a behaviour that did NOT exist before, and each one
corresponds to a fault recorded in BUGS.md. They are grouped in one file
because they were introduced together and share a rationale: the run was about
to get bigger zones, sidecars on by default, and a required flight log, and
none of those changes were safe while the failures below were silent.

No RealityScan, no network: everything here is pure logic or a stubbed CLI.

Run:  python -m pytest testing/test_directive_guards_2026_09.py
"""
from __future__ import annotations

import datetime as dt
import logging
import os
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, REPO_ROOT)

from module_base.parameter import Parameter  # noqa: E402
from modules import declination as decl  # noqa: E402
from modules import flight_logs  # noqa: E402
from modules.image_batcher.batch_directory import BatchDirectory  # noqa: E402

QUIET = logging.getLogger('directive-test')
QUIET.addHandler(logging.NullHandler())
QUIET.propagate = False


# --------------------------------------------------------------------------
# B1 - the flight log is REQUIRED, and "a file exists" is not the test
# --------------------------------------------------------------------------

def _write_log(path, rows=1, columns=14):
    header = ';'.join(['filename', 'X (East)', 'Y (North)', 'Alt',
                       'X Accuracy', 'Y Accuracy', 'Alt Accuracy',
                       'Yaw', 'Pitch', 'Roll', 'Yaw Accuracy',
                       'Pitch Accuracy', 'Roll Accuracy', 'FocalLength'])
    header = ';'.join(header.split(';')[:columns])
    lines = [header]
    for i in range(rows):
        lines.append(';'.join([f'img_{i}.jpg'] + ['0'] * (columns - 1)))
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return str(path)


def test_absent_flight_log_raises_rather_than_returning_none(tmp_path):
    with pytest.raises(flight_logs.FlightLogMissing) as exc:
        flight_logs.require_flight_log(str(tmp_path), context='the align stage')
    assert 'the align stage' in str(exc.value)


def test_header_only_flight_log_is_refused(tmp_path):
    """A header-only log is a REACHABLE production state (pool layout writes
    one when no row resolves), and it imports cleanly while georeferencing
    nothing. Existence checks pass it; this must not."""
    _write_log(tmp_path / 'flight_log_2L_UTM.txt', rows=0)
    with pytest.raises(flight_logs.FlightLogMissing) as exc:
        flight_logs.require_flight_log(str(tmp_path))
    assert '0 data row' in str(exc.value)


def test_column_count_mismatch_is_refused(tmp_path):
    """13 columns against the 14-column {D1F2A3B4} format. RealityScan does
    not error on this - it silently drops the trailing columns, which is the
    entire reason the format gate exists. The prior run's leftover log on this
    dive was exactly this shape."""
    _write_log(tmp_path / 'flight_log_2L_UTM.txt', rows=3, columns=13)
    with pytest.raises(flight_logs.FlightLogMissing) as exc:
        flight_logs.require_flight_log(str(tmp_path), expect_columns=14)
    assert '13 columns' in str(exc.value)
    assert 'silently' in str(exc.value)


def test_a_good_flight_log_is_returned(tmp_path):
    written = _write_log(tmp_path / 'flight_log_2L_UTM.txt', rows=5)
    assert flight_logs.require_flight_log(
        str(tmp_path), expect_columns=14) == written


def test_describe_reads_shape_without_judging_it(tmp_path):
    _write_log(tmp_path / 'flight_log_2L_UTM.txt', rows=7, columns=14)
    info = flight_logs.describe_flight_log(
        str(tmp_path / 'flight_log_2L_UTM.txt'))
    assert info['rows'] == 7 and info['columns'] == 14
    assert info['zone'] == (2, 'L')


# --------------------------------------------------------------------------
# B2 - zone sizing resolves in ONE place, and the dead band is impossible
# --------------------------------------------------------------------------

class _Store:
    """SettingsStore-shaped double: `get` only, per the documented contract."""

    def __init__(self, data=None):
        self.data = data or {}
        self.written = {}

    def get(self, section, key, fallback=None):
        return self.data.get(section, {}).get(key, fallback)

    def set(self, section, key, value):
        self.written.setdefault(section, {})[key] = value


def _batcher(store=None, **values):
    module = BatchDirectory(QUIET)
    module.settings = store or _Store()
    params = {}
    for name, value in values.items():
        p = Parameter(name, None, name, type(value), value, prompt_user=False)
        p.set_value(value)
        params[name] = p
    module.params = params
    return module


@pytest.mark.parametrize('min_size,max_size,expected_min', [
    (5000, 8000, 4000),   # the directive's own numbers: 2*5000 > 8000
    (4000, 8000, 4000),   # the boundary case - allowed, unchanged
    (1000, 4000, 1000),   # the historical pair - no band
])
def test_dead_band_is_closed_by_coercion(min_size, max_size, expected_min):
    """2*min > max makes sub-minimum zones a STABLE FIXED POINT: they cannot
    merge (sum exceeds max) and cannot split (each is under max)."""
    module = _batcher()
    _t, got_min, got_max = module._coerce_zone_sizing(6500, min_size, max_size)
    assert got_min == expected_min
    assert 2 * got_min <= got_max


def test_target_is_clamped_into_the_band():
    module = _batcher()
    assert module._coerce_zone_sizing(99999, 4000, 8000)[0] == 8000
    assert module._coerce_zone_sizing(10, 4000, 8000)[0] == 4000


def test_inverted_min_max_is_swapped_not_obeyed():
    module = _batcher()
    _t, lo, hi = module._coerce_zone_sizing(6500, 8000, 4000)
    assert lo < hi


def test_declared_defaults_are_the_directive_values():
    """'Baked into code' means the declaration, not a stored answer."""
    params = BatchDirectory(QUIET).get_parameters()
    assert params['batch_target_images_per_zone'].get_default_value() == 6500
    assert params['batch_max_zone_size'].get_default_value() == 8000
    assert params['batch_min_zone_size'].get_default_value() == 4000
    assert params['batch_xmp_priors'].get_default_value() is True
    # And the declared triple must itself be free of the dead band.
    assert 2 * params['batch_min_zone_size'].get_default_value() \
        <= params['batch_max_zone_size'].get_default_value()


def test_xmp_priors_is_in_the_reuse_fingerprint():
    """Flipping it changes what is on disk inside the zone tree, and
    __copy_files skips destinations that already exist BY NAME - so without
    this the flag silently reuses a tree built without sidecars."""
    module = _batcher(batch_target_images_per_zone=6500,
                      batch_min_zone_size=4000, batch_max_zone_size=8000,
                      batch_initial_overlap_percent=20.0,
                      batch_density_weight=0.3, batch_kde_bandwidth=0.0,
                      batch_overlap_max_distance_m=0.0, batch_use_z=False,
                      batch_zone_layout='copy', batch_xmp_priors=True)
    module._BatchDirectory__get_input_dir = lambda: None
    fingerprint = module._input_fingerprint('')
    assert 'batch_xmp_priors' in fingerprint['params']


# --------------------------------------------------------------------------
# B3 - declination is estimated, but applied only when the source is magnetic
# --------------------------------------------------------------------------

def test_gyrocompass_heading_is_detected_from_the_column_name():
    """ROVDataConcat's kalman_yaw_deg is Octans-derived and already TRUE
    north. This is the branch that stops +12.19 deg of pure error being added
    to every yaw prior on this dive."""
    assert decl.heading_reference(columns=['Timestamp', 'kalman_yaw_deg']) == 'true'


def test_octans_filename_also_identifies_a_true_heading():
    assert decl.heading_reference(
        nav_path='NA165_H2060_pitch_roll_heading_octans.csv') == 'true'


def test_unknown_source_does_not_get_a_silent_correction():
    assert decl.heading_reference(nav_path='something.csv') == 'unknown'


def test_true_heading_applies_zero_but_still_records_the_estimate():
    out = decl.resolve(lat=-14.211, lon=-169.046,
                       when=dt.datetime(2024, 9, 18),
                       columns=['kalman_yaw_deg'], logger_=QUIET)
    assert out['applied_deg'] == 0.0
    assert out['reference'] == 'true'
    assert out['source'] == 'gyrocompass-true'
    # The estimate is still computed and recorded, so the decision is auditable.
    if out['estimated_deg'] is not None:
        assert 10.0 < out['estimated_deg'] < 14.0


def test_an_explicit_operator_value_always_wins():
    out = decl.resolve(lat=-14.211, lon=-169.046,
                       when=dt.datetime(2024, 9, 18),
                       columns=['kalman_yaw_deg'], operator_value=3.5,
                       logger_=QUIET)
    assert out['applied_deg'] == 3.5
    assert out['source'] == 'operator'


def test_epoch_selection_is_by_date_not_by_library_default():
    """WMM releases are valid for five years and pygeomag RAISES outside that
    window. A 2024 dive must select WMM_2020 even though WMM_2025 ships as the
    library default - getting this wrong is a hard failure, not a small error."""
    assert decl.coefficient_file_for(2024.71).endswith('WMM_2020.COF')
    assert decl.coefficient_file_for(2026.10).endswith('WMM_2025.COF')
    with pytest.raises(decl.DeclinationUnavailable):
        decl.coefficient_file_for(1999.0)


def test_missing_model_is_reported_not_silently_zeroed(monkeypatch):
    """0.0 is a legitimate declination, so it must never double as 'could not
    compute'."""
    monkeypatch.setitem(sys.modules, 'pygeomag', None)
    with pytest.raises(decl.DeclinationUnavailable):
        decl.wmm_declination(-14.211, -169.046, dt.datetime(2024, 9, 18))
