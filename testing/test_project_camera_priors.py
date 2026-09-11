"""Project contracts and their consumers; fresh offline workers, no RS calls."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from modules import camera_registry


def _write(tmp_path, data):
    path = tmp_path / 'camera_priors.json'
    path.write_text(json.dumps(data), encoding='utf-8')
    return path


@pytest.mark.parametrize('extra', [
    {'families': {'misspelled': {'pitch': 1}}},
    {'families': {'zeuss': {'roll': 1}}},
    {'families': {'zeuss': {'pitch': True}}},
    {'families': {'zeuss': {'pitch': 181}}},
    {'families': {'zeuss': {'p_acc': 0}}},
    {'families': {'zeuss': {'fwd': 1001}}},
    {'families': {'zeuss': {'lat': float('nan')}}},
    {'families': {'zeuss': {'down': float('inf')}}},
    {'families': {'zeuss': {'fwd': 10**400}}},
    {'families': {'voyis_left_staged': {'pitch': 0}}},
    {'defaults': {'position_accuracy_m': {'alt': 0}}},
    {'defaults': {'orientation_accuracy_deg': {'pitch': 20}}},
    {'defaults': {'orientation_accuracy_deg': {'yaw': 181}}},
    {'navigation': {'clock_offset_seconds': 86401}},
    {'navigation': {'max_match_seconds': -1}},
    {'navigation': {'max_match_seconds': 3601}},
    {'navigation': {'max_match_seconds': '2'}},
    {'navigation': {'typo': 2}},
    {'orientation_weight': 3},
    {'schema_version': True},
    {'schema_version': 2},
    {'unknown': {}},
])
def test_project_contract_rejects_bad_fields_and_numbers(tmp_path, extra):
    data = dict(schema_version=1, orientation_weight=2)
    data.update(extra)
    path = _write(tmp_path, data)
    with pytest.raises(ValueError):
        camera_registry.load_project_priors(str(path))


@pytest.mark.parametrize('raw', [
    '{"schema_version":1,"orientation_weight":2,"orientation_weight":2}',
    '{"schema_version":1,"orientation_weight":2,"families":{"zeuss":{"pitch":1,"pitch":2}}}',
    '{"schema_version":1}', '[]', '{',
])
def test_malformed_duplicate_or_incomplete_contract_fails(tmp_path, raw):
    path = tmp_path / 'priors.json'
    path.write_text(raw)
    with pytest.raises(ValueError):
        camera_registry.load_project_priors(str(path))


def test_absolute_readable_file_required(tmp_path):
    for path in ('', 'relative.json', str(tmp_path / 'missing.json'), str(tmp_path)):
        with pytest.raises(ValueError):
            camera_registry.load_project_priors(path)


def test_loader_validation_has_no_global_side_effect(tmp_path):
    before = camera_registry.mount_defaults()
    path = _write(tmp_path, {'schema_version': 1, 'orientation_weight': 2,
                            'families': {'zeuss': {'pitch': 35}}})
    loaded = camera_registry.load_project_priors(str(path))
    assert loaded['families']['zeuss']['pitch'] == 35
    assert len(loaded['sha256']) == 64
    assert camera_registry.mount_defaults() == before


def test_numeric_boundaries_are_accepted(tmp_path):
    path = _write(tmp_path, {
        'schema_version': 1, 'orientation_weight': 2,
        'families': {'legacy_cammid': {'fwd': -1000, 'lat': 1000, 'pitch': -180, 'p_acc': 180}},
        'navigation': {'clock_offset_seconds': -86400, 'max_match_seconds': 0},
    })
    assert camera_registry.load_project_priors(str(path))['navigation']['max_match_seconds'] == 0


@pytest.mark.parametrize('pitch', [0, 40, 89.999, 90])
def test_zeuss_mount_downward_range_does_not_bound_uncertainty(tmp_path, pitch):
    path = _write(tmp_path, {
        'schema_version': 1, 'orientation_weight': 2,
        'families': {'zeuss': {'pitch': pitch, 'p_acc': 120}},
    })
    mount = camera_registry.load_project_priors(str(path))['families']['zeuss']
    assert mount == {'pitch': pitch, 'p_acc': 120}


@pytest.mark.parametrize('pitch', [-180, -.001, 90.001, 180])
def test_zeuss_project_mount_rejects_upward_or_past_nadir(tmp_path, pitch):
    path = _write(tmp_path, {
        'schema_version': 1, 'orientation_weight': 2,
        'families': {'zeuss': {'pitch': pitch, 'p_acc': 40}},
    })
    with pytest.raises(ValueError, match=r'zeuss\.pitch'):
        camera_registry.load_project_priors(str(path))


@pytest.mark.parametrize('pitch', [-180, -1, 91, 180])
def test_zeuss_mechanical_range_is_not_imposed_on_other_families(tmp_path, pitch):
    path = _write(tmp_path, {
        'schema_version': 1, 'orientation_weight': 2,
        'families': {'legacy_cammid': {'pitch': pitch}},
    })
    assert camera_registry.load_project_priors(str(path))['families']['legacy_cammid']['pitch'] == pitch


def _worker(script, path=None, args=()):
    env = dict(os.environ)
    env.pop('RS_CAMERA_PRIORS_FILE', None)
    if path is not None:
        env['RS_CAMERA_PRIORS_FILE'] = str(path)
    return subprocess.run([sys.executable, '-B', '-c', script, *map(str, args)],
                          cwd=Path(__file__).resolve().parents[1], env=env,
                          capture_output=True, text=True, timeout=30)


def test_invalid_file_fails_at_process_startup(tmp_path):
    result = _worker('from modules import camera_registry', tmp_path / 'missing.json')
    assert result.returncode != 0 and 'Cannot load project priors' in result.stderr


def test_startup_snapshot_effective_fallback_and_defensive_copies(tmp_path):
    path = _write(tmp_path, {'schema_version': 1, 'orientation_weight': 2,
                            'families': {'zeuss': {'pitch': 35}}})
    result = _worker('''
import json, os
from modules import camera_registry as c
from modules.georeference.georeference_images import MOUNTS
before = c.effective_project_priors()
os.environ['RS_CAMERA_PRIORS_FILE'] = 'invalid-later-change'
mutated = c.mount_defaults()
mutated['zeuss']['pitch'] = -99
assert c.effective_project_priors() == before
assert MOUNTS['zeuss']['pitch'] == 35
assert MOUNTS['zeuss']['p_acc'] == 40
assert MOUNTS['legacy_cammid']['pitch'] == 20
assert MOUNTS['legacy_camupper']['p_acc'] == 10
print(json.dumps(before))
''', path)
    assert result.returncode == 0, result.stderr
    effective = json.loads(result.stdout)
    assert effective['source'] == str(path)
    assert effective['orientation_weight'] == 2


def test_new_project_defaults_ignore_ambient_campaign_and_are_defensive(tmp_path):
    path = _write(tmp_path, {
        'schema_version': 1, 'orientation_weight': 2,
        'families': {'zeuss': {'pitch': 35, 'p_acc': 21, 'fwd': 2}},
        'defaults': {'position_accuracy_m': {'x': 7},
                     'orientation_accuracy_deg': {'yaw': 12}},
    })
    result = _worker('''
from modules import camera_registry as c
assert c.project_priors_active()
effective = c.effective_project_priors()
mounts = c.baked_mount_defaults()
priors = c.baked_prior_defaults()
assert mounts['zeuss'] == {'fwd': .5, 'lat': 0, 'down': .5, 'pitch': 40, 'p_acc': 40}
assert priors['position_accuracy_m'] == {'x': 5, 'y': 5, 'alt': 1}
assert priors['orientation_accuracy_deg'] == {'yaw': 10, 'roll': 10}
assert c.mount_defaults()['zeuss']['pitch'] == 35
assert c.prior_defaults()['position_accuracy_m']['x'] == 7
assert c.prior_defaults()['orientation_accuracy_deg']['yaw'] == 12
mounts['zeuss']['pitch'] = 88
priors['position_accuracy_m']['x'] = 999
priors['assumed_mount']['excluded_families'].clear()
assert c.baked_mount_defaults()['zeuss']['pitch'] == 40
assert c.baked_prior_defaults()['position_accuracy_m']['x'] == 5
assert c.baked_prior_defaults()['assumed_mount']['excluded_families']
assert c.effective_project_priors() == effective
''', path)
    assert result.returncode == 0, result.stderr


def test_baked_api_does_not_hide_malformed_ambient_contract(tmp_path):
    path = tmp_path / 'malformed.json'
    path.write_text('{', encoding='utf-8')
    result = _worker('from modules.camera_registry import baked_mount_defaults', path)
    assert result.returncode != 0 and 'Cannot load project priors' in result.stderr


def test_project_values_reach_both_flight_logs_and_matching_once(tmp_path):
    path = _write(tmp_path, {
        'schema_version': 1, 'orientation_weight': 2,
        'families': {'zeuss': {'pitch': 35, 'p_acc': 21, 'fwd': 2}},
        'defaults': {'position_accuracy_m': {'x': 7, 'y': 8, 'alt': 2},
                     'orientation_accuracy_deg': {'yaw': 12, 'roll': 13}},
        'navigation': {'clock_offset_seconds': 5.5, 'max_match_seconds': .25},
    })
    result = _worker('''
import csv, io, logging, sys
from contextlib import redirect_stdout
from datetime import datetime, timedelta
from pathlib import Path
import geoall
from modules.georeference.georeference_images import GeoreferenceImages
from modules.file_metadata_parser import navigation_match_timestamp, parse_timestamp
root = Path(sys.argv[1])
g = GeoreferenceImages(logging.getLogger('offline-project'))
g.params = g.get_parameters()
g.params['geo_pos_accuracy_m'].set_value(99)
g.params['geo_orientation_accuracy_deg'].set_value(99)
g._initialize_loading_bar = lambda *args: None
g._update_loading_bar = lambda *args: None
g._finish_loading_bar = lambda *args: None
g._GeoreferenceImages__convert_to_utm = lambda *args: (100, 200)
geoall.convert_to_utm = lambda *args: (100, 200)
raw = datetime(2024, 1, 1)
assert parse_timestamp('herc_20240101000000.jpg') == raw
assert navigation_match_timestamp(raw) == raw + timedelta(seconds=5.5)
row = dict(TIME=raw + timedelta(seconds=5.5), LAT=45, LONG=-123, DEPTH=-100,
           HEADING_MAG=0, PITCH=10, ROLL=20)
image = dict(FILENAME='herc_20240101000000.jpg', FULL_PATH='unused', TIMESTAMP=raw)
with redirect_stdout(io.StringIO()):
    for repeat in range(2):
        g._GeoreferenceImages__estimate_location([image], [row], 'All')
        assert image['ACCEPTED'] and image['TIMESTAMP'] == raw
        assert image['MATCH_TIMESTAMP'] == row['TIME']
    matched, stats = geoall.estimate_location([image], [row], {})
    again, _ = geoall.estimate_location(matched, [row], {})
    assert len(again) == 1 and again[0]['TIMESTAMP'] == raw
    expected = geoall.apply_camera_position_offset(100, 200, -100, 0, 2, 0, .5,
                                                  pitch_deg=10, roll_deg=20)
    assert tuple(image[k] for k in ('UTM_X','UTM_Y','ALTITUDE_EST')) == expected
    assert tuple(matched[0][k] for k in ('UTM_X','UTM_Y','ALTITUDE_EST')) == expected
    g.utm_zone = '10N'
    module_log = g._GeoreferenceImages__generate_flight_log([image], str(root))
    standalone_log = geoall.generate_flight_log(matched, 'example', '10N', str(root),
                                                accuracies={'pos_xy':99,'yaw':99})
    for log in (module_log, standalone_log):
        with open(log) as f:
            cells = list(csv.reader(f, delimiter=';'))[1]
        assert [float(cells[i]) for i in (4,5,6,10,11,12)] == [7,8,2,12,21,13]
        assert float(cells[8]) == 65  # Existing Euler formula preserved.
    outside = dict(image, TIMESTAMP=raw + timedelta(seconds=.3))
    g._GeoreferenceImages__estimate_location([outside], [row], 'All')
    assert not outside['ACCEPTED']
    assert geoall.estimate_location([outside], [row], {})[0] == []
    boundary = dict(image, TIMESTAMP=raw + timedelta(seconds=.25))
    g._GeoreferenceImages__estimate_location([boundary], [row], 'All')
    assert boundary['ACCEPTED']
    assert len(geoall.estimate_location([boundary], [row], {})[0]) == 1
print('project-consumers-ok')
''', path, (tmp_path,))
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == 'project-consumers-ok'


def test_no_file_preserves_registry_defaults():
    result = _worker('''
from modules import camera_registry as c
assert not c.project_priors_active()
assert c.mount_defaults()['zeuss']['pitch'] == 40
assert c.mount_defaults()['zeuss']['p_acc'] == 40
assert c.navigation_defaults() == {'clock_offset_seconds': 0, 'max_match_seconds': 2}
''')
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize('seconds', [-86400, -.5, 0, 86400])
def test_clock_sign_fraction_and_day_rollover(tmp_path, seconds):
    path = _write(tmp_path, {'schema_version': 1, 'orientation_weight': 2,
                            'navigation': {'clock_offset_seconds': seconds}})
    result = _worker('''
import sys
from datetime import datetime, timedelta
from modules.file_metadata_parser import navigation_match_timestamp
raw = datetime(2024, 1, 1)
assert navigation_match_timestamp(raw) == raw + timedelta(seconds=float(sys.argv[1]))
assert raw == datetime(2024, 1, 1)
''', path, (seconds,))
    assert result.returncode == 0, result.stderr
