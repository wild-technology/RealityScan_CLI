#!/usr/bin/env python3
"""Fresh-user / hostile-input guards on the user-facing surface.

Everything here was reachable by a new operator on a new expedition and
produced either a raw traceback or a plausible-looking wrong answer
(audit 2026-08-07):

  modules/flight_logs.py
    - two logs of DIFFERENT UTM zones in one directory: discovery picked
      the lexicographically first and georeferenced the other cruise's
      imagery ~2,000 km away, silently
    - zone 99 band 'Z' produced '+proj=utm +zone=99' / 'epsg:32699' with
      exit code 0, and any unknown band fell into the NORTHERN branch, so
      a southern typo became a northern CRS
    - a missing template raised FileNotFoundError from open(); a DIRECTORY
      raised PermissionError; a bare relative output name raised WinError 3

  module_base/settings_store.py
    - a hand-edited section holding a scalar/null crashed EVERY driver at
      startup (the corrupt-file quarantine never fired: the JSON parses)
    - prompt()/prompt_bool() used bare input(), so any non-TTY run died
      with EOFError although ask() had been guarded for exactly this
    - a stored empty instance_name was exported verbatim as RS_INSTANCE=''

  modules/camera_registry.py
    - the parity brace demanded a byte-for-byte reproduction of the
      retired tables, so ADDING a camera to cameras.json was a hard
      ImportError that bricked main.py, wildscan and the standalone
      drivers together - while the module docstring calls that file the
      place owner per-rig settings live

Offline: no RealityScan, no repo state touched (every fixture is a
tempdir, every store is a temp path).

Run:  py -3.13 -m pytest testing/test_input_hardening.py
"""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, REPO_ROOT)

from module_base.settings_store import (DEFAULT_INSTANCE_NAME,  # noqa: E402
                                        SettingsStore, realityscan_env)
from modules.flight_logs import (assert_one_zone, crs_for_flight_log,  # noqa: E402
                                 epsg_for_utm_zone, find_flight_log,
                                 params_template_frame, validate_utm_zone,
                                 write_flight_log_params)

METADATA = os.path.join(REPO_ROOT, 'modules', 'realityscan_interface',
                        'RS_CLI', 'Metadata')
UTM_TEMPLATE = os.path.join(METADATA, 'FlightLogParams.xml')

HEADER = 'filename;X (East);Y (North);Alt\n'


def _log(directory, name, rows=1):
    path = directory / name
    path.write_text(HEADER + ''.join(f'img_{i}.jpg;1;2;3\n'
                                     for i in range(rows)), encoding='utf-8')
    return path


# ------------------------------------------------------ mixed-zone refusal

def test_two_logs_of_different_zones_refuse_to_resolve(tmp_path):
    _log(tmp_path, 'flight_log_NA001_57L_UTM.txt')
    _log(tmp_path, 'flight_log_NA002_53N_UTM.txt')
    with pytest.raises(ValueError) as exc:
        find_flight_log(str(tmp_path))
    message = str(exc.value)
    # Both offenders must be named - "one of them is wrong" is useless.
    assert 'flight_log_NA001_57L_UTM.txt' in message
    assert 'flight_log_NA002_53N_UTM.txt' in message
    assert '57L' in message and '53N' in message


def test_tagged_and_untagged_logs_are_a_frame_disagreement(tmp_path):
    """An untagged name means LOCAL frame downstream, so mixing it with a
    zone-tagged log is a frame conflict, not merely a zone one."""
    _log(tmp_path, 'flight_log_53N_UTM.txt')
    _log(tmp_path, 'flight_log_UTM.txt')
    with pytest.raises(ValueError, match='no zone tag'):
        find_flight_log(str(tmp_path))


def test_several_logs_of_the_SAME_zone_still_resolve(tmp_path):
    """The guard must not break the ordinary multi-dive-one-zone case."""
    _log(tmp_path, 'flight_log_NA001_53N_UTM.txt')
    _log(tmp_path, 'flight_log_NA002_53N_UTM.txt')
    picked = find_flight_log(str(tmp_path))
    assert os.path.basename(picked) == 'flight_log_NA001_53N_UTM.txt'
    assert assert_one_zone([picked], str(tmp_path)) == (53, 'N')


def test_all_untagged_logs_resolve_as_local_frame(tmp_path):
    _log(tmp_path, 'flight_log_UTM.txt')
    assert find_flight_log(str(tmp_path)) is not None
    assert assert_one_zone([str(tmp_path / 'flight_log_UTM.txt')], 'x') is None


# ------------------------------------------------------ CRS zone validation

@pytest.mark.parametrize('zone,band', [
    (99, 'Z'),    # neither is real; 'Z' silently became NORTHERN
    (0, 'N'), (61, 'N'), (-1, 'S'),
    (53, 'I'), (53, 'O'),   # I and O are never MGRS bands
    (53, '9'), (53, ''),
])
def test_impossible_utm_zones_are_refused(zone, band):
    with pytest.raises(ValueError, match='invalid UTM zone'):
        validate_utm_zone(zone, band)
    with pytest.raises(ValueError, match='invalid UTM zone'):
        epsg_for_utm_zone(zone, band)


def test_impossible_zone_never_reaches_a_params_file(tmp_path):
    out = tmp_path / 'FlightLogParams_99Z.xml'
    with pytest.raises(ValueError, match='invalid UTM zone'):
        write_flight_log_params(UTM_TEMPLATE, str(out), 99, 'Z')
    assert not out.exists(), 'a bogus CRS was written to disk'


def test_real_zones_still_write(tmp_path):
    out = write_flight_log_params(
        UTM_TEMPLATE, str(tmp_path / 'p.xml'), 53, 'N')
    assert 'epsg:32653' in open(out, encoding='utf-8').read()
    out_s = write_flight_log_params(
        UTM_TEMPLATE, str(tmp_path / 'ps.xml'), 57, 'L')
    text = open(out_s, encoding='utf-8').read()
    assert '+south' in text and 'epsg:32757' in text


def test_crs_for_flight_log():
    assert crs_for_flight_log('flight_log_53N_UTM.txt') == 'EPSG:32653'
    assert crs_for_flight_log('flight_log_NA167_H2075_57L_UTM.txt') == \
        'EPSG:32757'
    assert crs_for_flight_log('flight_log_UTM.txt') is None
    assert crs_for_flight_log(None) is None


# ------------------------------------------------------- template handling

def test_missing_template_names_itself(tmp_path):
    missing = str(tmp_path / 'nope.xml')
    with pytest.raises(FileNotFoundError) as exc:
        params_template_frame(missing)
    assert 'nope.xml' in str(exc.value)
    assert 'FlightLogParams' in str(exc.value)


def test_directory_as_template_is_a_named_error(tmp_path):
    """Raw open() on a directory raises PermissionError on Windows, which
    tells the operator nothing about what the pipeline wanted."""
    with pytest.raises(FileNotFoundError, match='not a file'):
        params_template_frame(str(tmp_path))


def test_bare_relative_output_name_does_not_explode(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    out = write_flight_log_params(UTM_TEMPLATE, 'FlightLogParams_53N.xml',
                                  53, 'N')
    assert os.path.isfile(out)


# ------------------------------------------------------------- settings store

@pytest.mark.parametrize('payload', [
    '{"realityscan": "RS1"}',
    '{"realityscan": null}',
    '{"realityscan": ["RS1"]}',
    '{"batch": "oops"}',
    '{"batch": 3}',
])
def test_non_object_sections_are_dropped_not_fatal(tmp_path, payload, capsys):
    path = tmp_path / 'rs_settings.json'
    path.write_text(payload, encoding='utf-8')
    store = SettingsStore(str(path))
    # Reads fall back, writes work, and the run continues.
    assert store.get('realityscan', 'instance_name', 'RS1') == 'RS1'
    store.set('batch', 'min_zone_size', 300)
    assert store.get('batch', 'min_zone_size') == 300
    # ... and the operator is told which keys were discarded.
    assert 'ignoring non-object settings section' in capsys.readouterr().out


def test_good_sections_survive_beside_a_bad_one(tmp_path):
    path = tmp_path / 'rs_settings.json'
    path.write_text(json.dumps({'realityscan': 'bad',
                                'batch': {'min_zone_size': 300}}),
                    encoding='utf-8')
    store = SettingsStore(str(path))
    assert store.get('batch', 'min_zone_size') == 300


def test_prompt_is_eof_safe(tmp_path, monkeypatch):
    path = tmp_path / 'rs_settings.json'
    path.write_text(json.dumps({'geoall': {'image_base_dir': 'D:/stored'}}),
                    encoding='utf-8')
    monkeypatch.setattr('sys.stdin', io.StringIO(''))
    store = SettingsStore(str(path))
    assert store.prompt('geoall', 'image_base_dir', 'Folder') == 'D:/stored'


def test_prompt_bool_is_eof_safe(tmp_path, monkeypatch):
    path = tmp_path / 'rs_settings.json'
    path.write_text(json.dumps({'x': {'flag': True}}), encoding='utf-8')
    monkeypatch.setattr('sys.stdin', io.StringIO(''))
    assert SettingsStore(str(path)).prompt_bool('x', 'flag', 'Flag?') is True


def test_prompt_without_a_default_fails_with_a_named_error(tmp_path,
                                                           monkeypatch):
    """No stored value and no TTY: a NAMED ValueError beats an EOFError
    traceback out of input()."""
    monkeypatch.setattr('sys.stdin', io.StringIO(''))
    store = SettingsStore(str(tmp_path / 'rs_settings.json'))
    with pytest.raises(ValueError, match='Non-interactive run'):
        store.prompt('geoall', 'never_set', 'Folder containing images')


def test_empty_stored_instance_name_falls_back(tmp_path):
    path = tmp_path / 'rs_settings.json'
    path.write_text(json.dumps({'realityscan': {'instance_name': ''}}),
                    encoding='utf-8')
    env = realityscan_env(SettingsStore(str(path)))
    assert env['RS_INSTANCE'] == DEFAULT_INSTANCE_NAME


# ------------------------------------------------------ geoall runs headless

def test_geoall_help_does_not_prompt():
    """geoall ignored argv entirely and prompted unconditionally, so
    `geoall.py --help` was an EOFError traceback - in the file the docs
    call the canonical georeferencer."""
    proc = subprocess.run(
        [sys.executable, os.path.join(REPO_ROOT, 'geoall.py'), '--help'],
        stdin=subprocess.DEVNULL, capture_output=True, text=True,
        cwd=REPO_ROOT)
    assert proc.returncode == 0, proc.stderr
    assert 'Traceback' not in proc.stderr
    for flag in ('--declination', '--pos-accuracy', '--alt-accuracy',
                 '--orientation-accuracy', '--image-base-dir'):
        assert flag in proc.stdout


# -------------------------------------------------- camera registry parity

_PROBE_SEQ = [0]


def _registry_with(tmp_path, mutate):
    """Import a COPY of camera_registry beside a MUTATED cameras.json.

    The module resolves cameras.json relative to its own __file__, so a
    verbatim copy in a tempdir picks up the mutated data with no patching.
    It is registered in sys.modules under a unique name because
    @dataclass resolves annotations through sys.modules[cls.__module__].
    """
    import importlib.util
    import shutil

    data = json.load(open(os.path.join(REPO_ROOT, 'modules', 'cameras.json'),
                          encoding='utf-8'))
    mutate(data)
    (tmp_path / 'cameras.json').write_text(json.dumps(data), encoding='utf-8')
    module_path = tmp_path / 'camera_registry_probe.py'
    shutil.copyfile(os.path.join(REPO_ROOT, 'modules', 'camera_registry.py'),
                    module_path)

    _PROBE_SEQ[0] += 1
    name = f'camera_registry_probe_{_PROBE_SEQ[0]}'
    spec = importlib.util.spec_from_file_location(name, str(module_path))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(name, None)
    return module


NEW_FAMILY = {'family': 'voyis_new', 'camera': 'voyis_new',
              'pattern': r'^vn\d+_'}
NEW_CAMERA = {'voyis_new': {
    'calibration_group': '9', 'calibration_prior': 'Approximate',
    'focal_length_35mm': 21.0, 'lens_distortion_group': '9',
    'lens_distortion_prior': 'Approximate', 'distortion_model': 'brown3'}}


def test_a_new_expedition_camera_can_be_added(tmp_path):
    """Adding a family + camera to cameras.json must WORK. It used to be
    `ImportError: cameras.json parity: cameras['voyis_new'] diverges from
    the legacy table` - a hard stop on every entry point at once."""
    def mutate(data):
        data['cameras'].update(NEW_CAMERA)
        data['families'] = list(data['families']) + [NEW_FAMILY]

    registry = _registry_with(tmp_path, mutate)
    assert registry.family('VN0001_20260807T120000Z.jpg') == 'voyis_new'
    camera = registry.identify('VN0001_20260807T120000Z.jpg')
    assert camera is not None and camera.key == 'voyis_new'
    # ... and every legacy family still resolves exactly as before.
    assert registry.family('P231C0001.jpg') == 'wca_port'
    assert registry.family('camlower_20231104020854.jpg') == 'legacy_camlower'


def test_changing_a_legacy_camera_is_still_a_hard_error(tmp_path):
    """The brace must still catch a DRIFT - only additions are allowed."""
    def mutate(data):
        data['cameras']['port']['focal_length_35mm'] = 99.0   # was 16.0

    with pytest.raises(ImportError, match=r"cameras\['port'\]"):
        _registry_with(tmp_path, mutate)


def test_removing_a_legacy_family_is_still_a_hard_error(tmp_path):
    def mutate(data):
        data['families'] = [f for f in data['families']
                            if f['family'] != 'wca_cinema']

    with pytest.raises(ImportError, match='wca_cinema'):
        _registry_with(tmp_path, mutate)


def test_removing_a_legacy_camera_is_still_a_hard_error(tmp_path):
    """The subset check must catch a DELETION, not only a value change -
    'may be extended but never removed'."""
    def mutate(data):
        del data['cameras']['port']

    with pytest.raises(ImportError, match='MISSING'):
        _registry_with(tmp_path, mutate)


def test_reordering_the_legacy_families_is_still_a_hard_error(tmp_path):
    """family() matches MOST SPECIFIC FIRST; an unanchored 'herc' token
    once ran first and would have beaten an anchored WCA prefix."""
    def mutate(data):
        data['families'] = list(reversed(data['families']))

    with pytest.raises(ImportError, match='relative order'):
        _registry_with(tmp_path, mutate)


def test_get_and_set_survive_an_in_process_non_dict_section(tmp_path):
    """_load normalises the FILE; get()/set() are the defence behind it.

    A section can still become a non-dict in memory (a driver assigning
    `store._data['batch'] = None`, or a test double), and both accessors
    assumed a dict - `AttributeError: 'NoneType' object has no attribute
    'get'` out of whichever driver touched it first
    (audit-verification 2026-08-07: the shape guard shipped with no test;
    only the file-level normalisation was covered)."""
    store = SettingsStore(str(tmp_path / 'rs_settings.json'))
    for broken in (None, 'RS1', ['RS1'], 7):
        store._data['realityscan'] = broken
        assert store.get('realityscan', 'instance_name', 'RS1') == 'RS1'
        store.set('realityscan', 'instance_name', 'RS2')
        assert store.get('realityscan', 'instance_name') == 'RS2'
    # The repaired section is what lands on disk.
    reloaded = SettingsStore(str(tmp_path / 'rs_settings.json'))
    assert reloaded.get('realityscan', 'instance_name') == 'RS2'


def test_realityscan_env_survives_a_non_dict_section(tmp_path):
    """realityscan_env is the single resolution point every driver calls
    at startup, so a broken section there is a whole-pipeline outage."""
    store = SettingsStore(str(tmp_path / 'rs_settings.json'))
    store._data['realityscan'] = 'RS1'
    env = realityscan_env(store)
    assert env['RS_INSTANCE'] == 'RS1'
