"""Canonical CSV serialization and compatibility, without RealityScan execution."""
import csv
import logging
from pathlib import Path

import pytest

import geoall
from modules.georeference.georeference_images import GeoreferenceImages


def read_log(path):
    with open(path, newline='') as stream:
        return list(csv.reader(stream, delimiter=';'))


def module():
    value = GeoreferenceImages(logging.getLogger('flight-log-writer-offline'))
    value.params = value.get_parameters()
    value.utm_zone = '10N'
    value.declination_record = {'applied_deg': 0.0}
    return value


@pytest.mark.parametrize('name,pitch,accuracy', [
    ('camupper_fixture.jpeg', 20, 10),
    ('cammid_fixture.jpeg', 70, 10),
    ('camlower_fixture.jpeg', 80, 10),
    ('herc_fixture.jpg', 50, 40),
])
def test_entrypoints_share_14_columns_and_preserve_pose(tmp_path, name, pitch, accuracy):
    image = dict(FILENAME=name, CAMERA_TYPE='camera', ACCEPTED=True,
                 UTM_X=612345.1234567, UTM_Y=4567890.7654321, ALTITUDE_EST=-100.5,
                 HEADING_MAG=0.0, PITCH_VEHICLE=0.0, ROLL_VEHICLE=0.0)
    runner = module()
    module_path = runner._GeoreferenceImages__generate_flight_log(
        [image, dict(image, FILENAME='rejected.jpeg', ACCEPTED=False)], str(tmp_path))
    canonical_path = geoall.generate_flight_log([image], 'example', '10N', str(tmp_path))
    module_rows, canonical_rows = read_log(module_path), read_log(canonical_path)
    assert module_rows[0] == canonical_rows[0] == list(geoall.FLIGHT_LOG_COLUMNS)
    assert len(module_rows) == len(canonical_rows) == 2
    assert len(module_rows[1]) == len(canonical_rows[1]) == 14
    assert module_rows[1][0] == name
    assert canonical_rows[1][0] == f'camera/{name}'
    assert module_rows[1][1:] == canonical_rows[1][1:]
    assert module_rows[1][1:7] == ['612345.123457', '4567890.765432', '-100.500000',
                                  '5.000000', '5.000000', '1.000000']
    assert [float(v) for v in module_rows[1][7:13]] == [0, pitch, 0, 10, accuracy, 10]
    assert float(module_rows[1][13]) > 0  # Written compatibility value, not RS consumption.
    assert runner.stats['written_to_flight_log'] == 1


def test_unknown_camera_missing_values_and_quoted_paths(tmp_path):
    name = 'unknown;"fixture".jpeg'
    image = dict(FILENAME=name, CAMERA_TYPE='camera', ACCEPTED=True)
    runner = module()
    runner.params['geo_assumed_pitch_deg'].set_value(-1)
    module_rows = read_log(runner._GeoreferenceImages__generate_flight_log([image], str(tmp_path)))
    canonical_rows = read_log(geoall.generate_flight_log(
        [image], 'example', '10N', str(tmp_path), accuracies={'assumed_pitch': -1}))
    assert module_rows[1][0] == name
    assert canonical_rows[1][0] == f'camera/{name}'
    assert module_rows[1][1:] == canonical_rows[1][1:]
    assert len(module_rows[1]) == 14
    assert all(module_rows[1][i] == '' for i in (1, 2, 3, 7, 8, 9, 11, 13))


def test_both_entrypoints_use_canonical_serializer(tmp_path, monkeypatch):
    calls = []
    original = geoall.write_flight_log

    def capture(path, rows):
        calls.append(Path(path).name)
        return original(path, rows)

    monkeypatch.setattr(geoall, 'write_flight_log', capture)
    runner = module()
    runner.utm_zone = None
    module_path = runner._GeoreferenceImages__generate_flight_log([], str(tmp_path))
    canonical_path = geoall.generate_flight_log([], 'example', None, str(tmp_path))
    assert calls == ['flight_log_UNRESOLVED.txt', 'flight_log_example_UNRESOLVED.txt']
    assert read_log(module_path) == read_log(canonical_path) == [list(geoall.FLIGHT_LOG_COLUMNS)]


def test_module_focal_lookup_uses_canonical_lookup(monkeypatch):
    monkeypatch.setattr(geoall, 'get_camera_focal_length', lambda name: 123.0)
    assert module()._get_camera_focal_length('camupper_fixture.jpeg') == 123.0


def test_shared_writer_refuses_schema_drift(tmp_path):
    with pytest.raises(ValueError, match='14 columns'):
        geoall.write_flight_log(str(tmp_path / 'log.txt'), [['name', *([None] * 12)]])
