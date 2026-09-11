"""Sensor-record integrity controls; temporary fixtures, no navigation run."""
from datetime import datetime, timezone
import json

import pandas as pd
import pytest

from processors.usbl_sdyn import (
    COLUMNS, SdynRejected, parse_sdyn_line, parse_sdyn_file, process_data,
)


def sentence(**changes):
    fields = dict(clock='235959.785', lat='1809.78203', ns='N', lon='14307.87325',
                  ew='E', quality='2', satellites='00', accuracy='10.1', depth='-605.234',
                  unit='M', geoid='0.0', geoid_unit='M', age='0.0', beacon='0001')
    fields.update(changes)
    body = 'GPGGA,' + ','.join(fields.values())
    checksum = 0
    for byte in body.encode('ascii'):
        checksum ^= byte
    return f'${body}*{checksum:02X}'


def prefixed(stamp='2025-05-22T00:00:00.281Z', **changes):
    return f'SDYN\t{stamp}\tSONARDYNE\t{sentence(**changes)}'


def test_real_midnight_record_uses_previous_day_despite_filename(tmp_path):
    path = tmp_path / '20250522_0000.SDYN'
    path.write_text('SDYN\t2025-05-22T00:00:00.281Z\tSONARDYNE\t'
                    '$GPGGA,235959.785,1809.78203,N,14307.87325,E,2,00,10.1,-605.234,M,0.0,M,0.0,0001*54\n')
    stats = {}
    frame = parse_sdyn_file(path, stats=stats)
    assert frame.iloc[0].Timestamp == pd.Timestamp('2025-05-21T23:59:59.785Z')
    assert list(frame.columns) == COLUMNS
    assert stats['prefix_utc'] == stats['accepted'] == stats['lines_seen'] == 1


@pytest.mark.parametrize('name', ['unrelated.SDYN', '19990101_0000.SDYN'])
def test_full_prefix_supports_renamed_files_and_multiday_records(tmp_path, name):
    path = tmp_path / name
    path.write_text(prefixed() + '\n' + prefixed('2025-05-24T01:02:03.600Z', clock='010203.200') + '\n')
    frame = parse_sdyn_file(path)
    assert frame.Timestamp.tolist() == [pd.Timestamp('2025-05-21T23:59:59.785Z'),
                                       pd.Timestamp('2025-05-24T01:02:03.200Z')]


def test_next_day_fix_and_equivalent_explicit_utc_offset():
    record, basis = parse_sdyn_line(prefixed('2025-05-23T23:59:59.900+00:00', clock='000000.100'))
    assert record['Timestamp'] == pd.Timestamp('2025-05-24T00:00:00.100Z')
    assert basis == 'prefix_utc'


@pytest.mark.parametrize('timestamp', ['bad', '2025-05-22T00:00:00', '2025-05-22T00:00:00-04:00',
                                      '2025-02-30T00:00:00Z'])
def test_malformed_prefix_never_falls_back_to_valid_filename(timestamp):
    with pytest.raises(SdynRejected, match='invalid_prefix_utc'):
        parse_sdyn_line(prefixed(timestamp), file_start=datetime(2025, 5, 22, tzinfo=timezone.utc))


def test_clock_disagreement_rejected():
    with pytest.raises(SdynRejected, match='prefix_fix_time_disagreement'):
        parse_sdyn_line(prefixed(clock='120000.000'))


@pytest.mark.parametrize('change,reason', [
    ({'quality': '0'}, 'invalid_fix_quality'), ({'quality': '9'}, 'unsupported_fix_quality'),
    ({'beacon': '0002'}, 'excluded_atalanta'), ({'beacon': '9999'}, 'unsupported_beacon'),
    ({'lat': '1860.000'}, 'coordinate_out_of_range'), ({'lat': '9000.01'}, 'coordinate_out_of_range'),
    ({'lon': '18000.01'}, 'coordinate_out_of_range'), ({'ns': 'Q'}, 'invalid_hemisphere'),
    ({'accuracy': 'nan'}, 'nonfinite_numeric_field'), ({'accuracy': '0'}, 'nonpositive_accuracy'),
    ({'depth': 'inf'}, 'nonfinite_numeric_field'), ({'clock': '236000.0'}, 'invalid_fix_time'),
    ({'unit': 'F'}, 'unsupported_sdyn_layout'), ({'geoid': '1'}, 'unsupported_sdyn_layout'),
])
def test_invalid_fields_have_stable_reasons(change, reason):
    with pytest.raises(SdynRejected, match=reason):
        parse_sdyn_line(prefixed(**change))


def test_valid_quality_integer_clock_and_lowercase_checksum():
    text = prefixed('2025-05-22T12:00:00Z', clock='120000', quality='1', lat='0000.0', lon='00000.0')
    text = text[:-2] + text[-2:].lower()
    record, _ = parse_sdyn_line(text)
    assert record['Latitude'] == record['Longitude'] == 0
    assert record['Timestamp'].hour == 12


@pytest.mark.parametrize('suffix,reason', [('', 'missing_checksum'), ('*', 'malformed_checksum'),
                                         ('*XYZ', 'malformed_checksum'), ('*000', 'malformed_checksum'),
                                         ('*00', 'checksum_mismatch'), ('*54trailing', 'malformed_checksum')])
def test_checksum_is_required_exact_and_valid(suffix, reason):
    text = prefixed().split('*')[0] + suffix
    with pytest.raises(SdynRejected, match=reason):
        parse_sdyn_line(text)


def test_line_accounting_examples_bounded_and_legacy_counted(tmp_path):
    path = tmp_path / '20250521_2359.SDYN'
    path.write_text('\n'.join([prefixed(), sentence()] + [prefixed(quality='0')] * 8 + ['garbage', '']) + '\n')
    stats = {}
    frame = parse_sdyn_file(path, stats=stats)
    assert len(frame) == 2
    assert stats['lines_seen'] == stats['accepted'] + sum(stats['reasons'].values())
    assert stats['legacy_filename'] == stats['prefix_utc'] == 1
    assert stats['reasons']['invalid_fix_quality'] == 8
    assert len(stats['examples']['invalid_fix_quality']) == 5


def test_all_rejected_stage_persists_reasons(tmp_path):
    root, output = tmp_path / 'raw', tmp_path / 'output'
    logs = root / 'raw/datalog'
    logs.mkdir(parents=True)
    (logs / 'anything.SDYN').write_text(prefixed(quality='0') + '\n')
    output.mkdir()
    (output / 'all_dive_summaries.csv').write_text('expedition,dive,Launch Time,Recovery Time\n'
        'NA1,H1,2025-05-21T00:00:00Z,2025-05-23T00:00:00Z\n')
    process_data(root, output_dir=output)
    report = json.loads((output / 'reports/usbl_sdyn.json').read_text())
    assert report['status'] == 'error'
    assert report['metrics']['parse_accounting']['reasons']['invalid_fix_quality'] == 1
    assert not (output / 'H1').exists()


def test_extreme_quality_field_is_rejected_without_aborting_file(tmp_path):
    path = tmp_path / 'records.SDYN'
    path.write_text(prefixed(quality='9' * 5000) + '\n' + prefixed() + '\n')
    stats = {}
    assert len(parse_sdyn_file(path, stats=stats)) == 1
    assert stats['reasons']['unsupported_fix_quality'] == 1


def test_leading_zero_known_quality_and_calendar_boundary():
    record, _ = parse_sdyn_line(prefixed('0001-01-01T00:00:00Z', clock='000000.0', quality='002'))
    assert record['Timestamp'].year == 1
