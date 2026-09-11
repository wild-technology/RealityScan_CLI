"""Pure offline regressions: physical lever arms, timestamp evidence and selection."""
from datetime import datetime, timedelta
import logging
import math
from pathlib import Path

import pytest
from PIL import Image

import geoall
from modules import camera_registry, prior_groups
from modules.file_metadata_parser import parse_timestamp, parse_timestamp_str
from modules.georeference.georeference_images import GeoreferenceImages


@pytest.fixture
def georef(monkeypatch):
    obj = GeoreferenceImages(logging.getLogger('offline-geometry'))
    monkeypatch.setattr(obj, '_initialize_loading_bar', lambda *args: None)
    monkeypatch.setattr(obj, '_update_loading_bar', lambda *args: None)
    monkeypatch.setattr(obj, '_finish_loading_bar', lambda *args: None)
    return obj


@pytest.mark.parametrize('angles,expected', [
    ((0, 0, 0), (3, 2, -4)),
    ((90, 0, 0), (2, -3, -4)),
    ((0, 90, 0), (3, 4, 2)),
    ((0, 0, 90), (-4, 2, -3)),
    ((90, 90, 90), (3, 4, 2)),
    ((0, -90, 0), (3, -4, -2)),
])
def test_frd_basis_and_noncommuting_rotations(angles, expected):
    h, p, r = angles
    assert geoall.apply_camera_position_offset(
        0, 0, 0, h, 2, 3, 4, pitch_deg=p, roll_deg=r) == pytest.approx(expected)


def test_rotation_preserves_lever_length_and_far_origin_precision():
    offset = geoall.apply_camera_position_offset(
        600000, 4500000, -1200, 137, .5, .2, .7, pitch_deg=27, roll_deg=-13)
    delta = [v - base for v, base in zip(offset, (600000, 4500000, -1200))]
    assert math.sqrt(sum(v*v for v in delta)) == pytest.approx(math.sqrt(.78), abs=1e-9)


@pytest.mark.parametrize('bad', [None, float('nan'), float('inf'), -float('inf')])
@pytest.mark.parametrize('axis', [0, 1, 2])
def test_no_fabricated_attitude(bad, axis):
    hpr = [0, 0, 0]
    hpr[axis] = bad
    assert geoall.apply_camera_position_offset(
        1, 2, 3, hpr[0], 1, 0, 1, pitch_deg=hpr[1], roll_deg=hpr[2]) == (None, None, None)


def test_absent_optional_attitude_is_not_level():
    assert geoall.apply_camera_position_offset(1, 2, 3, 0, 1, 0, 1) == (None, None, None)


def test_module_delegates_to_canonical(georef, monkeypatch):
    observed = []
    monkeypatch.setattr(geoall, 'apply_camera_position_offset',
                        lambda *args, **kwargs: observed.append(kwargs) or (4, 5, 6))
    assert georef._apply_camera_position_offset(
        0, 0, 0, 12, 1, 0, 1, pitch_deg=23, roll_deg=34) == (4, 5, 6)
    assert observed == [{'pitch_deg': 23, 'roll_deg': 34}]


@pytest.mark.parametrize('name', [
    'camlower_20240230T010203Z.jpeg', 'herc_20241301010203.jpg',
    'no-time.jpg', '20240101T000000Z/no-time.jpg',
    r'C:\20240101T000000Z\no-time.jpg',
    'herc_202401010102030.jpg',
    '20240101T000000Z_20240102T000000Z.jpg',
])
def test_bad_timestamp_is_none_everywhere(name, georef):
    assert parse_timestamp(name) is None
    assert parse_timestamp_str(name) is None
    assert geoall.parse_timestamp_from_filename(name) is None
    for mode in ('All', 'WCA2025', 'Zeuss'):
        assert georef._GeoreferenceImages__parse_timestamp_from_filename(name, mode) is None


@pytest.mark.parametrize('name', [
    '20240229T010203Z_HERC.jpg', 'cammid_20240229010203.jpeg',
    r'C:\20200101T000000Z\camupper_20240229T010203Z.jpg',
    'P123C456_20240229010203_herc.jpg',
])
def test_all_families_and_modes_share_valid_parser(name, georef):
    expected = datetime(2024, 2, 29, 1, 2, 3)
    assert parse_timestamp(name) == expected
    assert geoall.parse_timestamp_from_filename(name) == expected
    for mode in ('All', 'WCA2025', 'Zeuss'):
        assert georef._GeoreferenceImages__parse_timestamp_from_filename(name, mode) == expected


def test_real_epoch_is_valid_evidence():
    assert parse_timestamp('herc_19700101000000.jpg') == datetime(1970, 1, 1)


@pytest.mark.parametrize('pitch', [30, None, float('nan')])
def test_both_estimation_callers_pass_attitude_and_flag_gaps(pitch, georef, monkeypatch):
    now = datetime(2024, 1, 1)
    row = dict(TIME=now, LAT=1, LONG=2, DEPTH=-100,
               HEADING_MAG=0, PITCH=pitch, ROLL=20)
    image = dict(FILENAME='cammid_20240101T000000Z.jpg', FULL_PATH='unused', TIMESTAMP=now)
    monkeypatch.setattr(geoall, 'convert_to_utm', lambda *args: (100, 200))
    monkeypatch.setattr(georef, '_GeoreferenceImages__convert_to_utm', lambda *args: (100, 200))
    expected = geoall.apply_camera_position_offset(
        100, 200, -100, 0, 1, 0, 1, pitch_deg=pitch, roll_deg=20)
    standalone, stats = geoall.estimate_location([dict(image)], [row], {})
    module_image = dict(image)
    georef._GeoreferenceImages__estimate_location([module_image], [row], 'All')
    for result in (standalone[0], module_image):
        assert tuple(result[k] for k in ('UTM_X', 'UTM_Y', 'ALTITUDE_EST')) == pytest.approx(expected)
        assert result['POSITION_OFFSET_MISSING_ATTITUDE'] == ([] if pitch == 30 else ['PITCH'])
    assert stats['accepted_missing_orientation'] == georef.stats['accepted_missing_orientation']
    outside = dict(image, TIMESTAMP=now + timedelta(seconds=3))
    assert geoall.estimate_location([outside], [row], {})[0] == []
    georef._GeoreferenceImages__estimate_location([outside], [row], 'All')
    assert outside['ACCEPTED'] is False


def _image(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new('RGB', (3, 3)).save(path)
    return path


def test_declination_applies_once_to_lever_and_yaw(georef, monkeypatch, tmp_path):
    import csv
    now = datetime(2024, 1, 1)
    row = dict(TIME=now, LAT=1, LONG=2, DEPTH=-100,
               HEADING_MAG=10, PITCH=0, ROLL=0)
    image = dict(FILENAME='camupper_20240101T000000Z.jpg', FULL_PATH='unused', TIMESTAMP=now)
    georef.params = georef.get_parameters()
    georef.params['magnetic_declination_deg'].set_value(20)
    monkeypatch.setattr(geoall, 'convert_to_utm', lambda *args: (100, 200))
    monkeypatch.setattr(georef, '_GeoreferenceImages__convert_to_utm', lambda *args: (100, 200))
    standalone, _ = geoall.estimate_location([dict(image)], [row], {}, declination_deg=20)
    georef._GeoreferenceImages__estimate_location([image], [row], 'All')
    for result in (standalone[0], image):
        assert result['HEADING_MAG'] == 10
        assert result['DECLINATION_APPLIED_DEG'] == 20
        assert result['UTM_X'] == pytest.approx(100.5)
        assert result['UTM_Y'] == pytest.approx(200 + math.cos(math.radians(30)))
    georef.utm_zone = '10N'
    paths = [georef._GeoreferenceImages__generate_flight_log([image], str(tmp_path)),
             geoall.generate_flight_log(standalone, 'example', '10N', str(tmp_path), declination_deg=20)]
    for path in paths:
        with open(path) as stream:
            cells = list(csv.reader(stream, delimiter=';'))[1]
        assert float(cells[1]) == pytest.approx(100.5)
        assert float(cells[7]) == 30
    georef._GeoreferenceImages__estimate_location([image], [row], 'All')
    assert image['UTM_X'] == pytest.approx(100.5)


def test_masks_excluded_from_both_inventories_and_grouping(tmp_path, georef):
    picture = _image(tmp_path / 'camlower_20240101T000000Z.jpeg')
    _image(tmp_path / (picture.name + '.mask.png'))
    _image(tmp_path / '.mask' / (picture.stem + '.png'))
    _image(tmp_path / '_mask' / picture.name)
    assert len(geoall.read_image_filenames([str(tmp_path)])) == 1
    assert len(georef._GeoreferenceImages__read_image_filenames(str(tmp_path), 'All')) == 1
    assert prior_groups.count_images(str(tmp_path)) == 1
    selections = [c for c in prior_groups.commands_for_tree(str(tmp_path)) if c.startswith('-selectImage')]
    assert selections == [f'-selectImage "{picture}" union']


def test_masks_copied_even_when_geometry_already_staged(tmp_path):
    picture = _image(tmp_path / 'source' / 'camlower_20240101T000000Z.jpeg')
    image = dict(FULL_PATH=str(picture), FILENAME=picture.name, CAMERA_TYPE='CamLower')
    args = (image, 'example', str(tmp_path / 'target'))
    assert geoall._copy_single_image(args)['success']
    masks = [_image(picture.parent / (picture.name + '.mask.png')),
             _image(picture.parent / '.mask' / (picture.stem + '.png')),
             _image(picture.parent / '_mask' / picture.name)]
    result = geoall._copy_single_image(args)
    assert result['success'] and result['masks'] == 3 and not result['skipped']
    for mask in masks:
        target = tmp_path / 'target' / 'example' / 'CamLower' / mask.relative_to(picture.parent)
        assert target.read_bytes() == mask.read_bytes()
    target = tmp_path / 'target' / 'example' / 'CamLower' / picture.name
    target.write_bytes(b'x' * picture.stat().st_size)
    assert not geoall._copy_single_image(args)['success']
    assert target.read_bytes() == b'x' * picture.stat().st_size


def test_duplicate_basename_refused_before_staging(tmp_path, georef):
    name = 'camlower_20240101T000000Z.jpeg'
    _image(tmp_path / 'one' / name)
    _image(tmp_path / 'two' / name)
    with pytest.raises(ValueError, match='Duplicate flight-log'):
        georef._GeoreferenceImages__read_image_filenames(str(tmp_path), 'All')
    with pytest.raises(ValueError, match='Duplicate staged'):
        geoall.copy_matched_images([dict(FILENAME=name, CAMERA_TYPE='CamLower')] * 2,
                                  'example', str(tmp_path / 'target'))
    assert not (tmp_path / 'target').exists()


def test_exact_group_selection_resolves_overlap_and_ignores_parent_names(tmp_path):
    names = ['P123C0001_20240101000000_herc.jpg', 'herc_20240101000000.jpg',
             'camupper_20240101000000.jpg', 'camlower_20240101000000.jpg',
             'cammid_20240101000000.jpg', 'unknown.jpg']
    root = tmp_path / 'herc_camupper'
    for name in names:
        _image(root / name)
    commands = prior_groups.commands_for_tree(str(root))
    selected = set()
    assignments = {}
    for command in commands:
        if command == '-deselectAllImages':
            selected.clear()
        elif command.startswith('-selectImage '):
            path = command.removeprefix('-selectImage "').removesuffix('" union')
            assert Path(path).is_absolute() and Path(path).exists()
            selected.add(Path(path).name)
        elif command.startswith('-setPriorCalibrationGroup '):
            group = int(command.split()[-1])
            for name in selected:
                assert name not in assignments, 'overlap reassigned an image'
                assignments[name] = group
    for name in names[:-1]:
        fam = camera_registry.family(name)
        camera = camera_registry.CAMERAS[camera_registry.FAMILY_CAMERA[fam]]
        assert assignments[name] == int(camera.calibration_group)
    assert 'unknown.jpg' not in assignments
    dest = tmp_path / 'commands.txt'
    assert prior_groups.write_command_file(str(root), str(dest)) == 5
    assert dest.read_bytes().count(b'\r\n') == len(commands) + 1
    assert commands == prior_groups.commands_for_tree(str(root))


def test_generated_path_cmd_injection_refused_before_file_write(tmp_path):
    root = tmp_path / 'unsafe&folder'
    _image(root / 'herc_20240101000000.jpg')
    dest = tmp_path / 'commands.txt'
    with pytest.raises(ValueError, match='metacharacter'):
        prior_groups.write_command_file(str(root), str(dest))
    assert not dest.exists()
