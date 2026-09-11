"""Adversarial component-prior checks. All data and CLI calls are fixtures."""
from __future__ import annotations

import builtins
import json
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

from module_base.rs_module import RSModule
from modules import component_manifest, prior_census
from modules.realityscan_interface import realityscan_interface as interface


def _xmp(group=1, lens=1, focal=23.0):
    return (
        '<rdf:Description xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" '
        'xmlns:xcr="http://www.capturingreality.com/ns/xcr/1.1#" '
        f'xcr:CalibrationGroup="{group}" xcr:DistortionGroup="{lens}" '
        f'xcr:FocalLength35mm="{focal}">'
        '<xcr:Position>1 2 3</xcr:Position></rdf:Description>')


def _fixture(root, components=None, *, csv=False):
    if components is None:
        components = [[('ZEUSS_20250524T010000Z.jpg', 1, 1, 23.0)]]
    root.mkdir(parents=True, exist_ok=True)
    exports, manifests = [], []
    for index, entries in enumerate(components):
        name = f'zone_c{index}'
        export = root / f'{name}.rsalign'
        export.write_bytes(b'fixture component')
        images = [entry[0] for entry in entries]
        manifest = component_manifest.build_manifest('zone', name, str(export), images)
        exports.append(str(export))
        manifests.append(component_manifest.write_manifest(manifest))
        if csv:
            (root / 'identity').mkdir(exist_ok=True)
            (root / 'identity' / f'{name}.csv').write_text(
                '# registration fixture\n' + ''.join(f'{im},0,0,0\n' for im in images),
                encoding='utf-8')
    for index in range(1 if csv else len(components) + 1):
        harvest = root / f'identity_r{index}'
        harvest.mkdir()
        for entries in components[index:]:
            for image, group, lens, focal in entries:
                (harvest / (prior_census._image_key(image) + '.xmp')).write_text(
                    _xmp(group, lens, focal), encoding='utf-8')
    return SimpleNamespace(root=root, exports=exports, manifests=manifests)


def _check(fixture):
    return prior_census.assert_component_priors(
        str(fixture.root), fixture.exports, fixture.manifests, context='fixture zone')


def _pose(fixture, index=0):
    return next((fixture.root / f'identity_r{index}').glob('*.xmp'))


def _change_manifest(fixture, update, index=0):
    path = Path(fixture.manifests[index])
    data = json.loads(path.read_text(encoding='utf-8'))
    data.update(update)
    path.write_text(json.dumps(data), encoding='utf-8')


@pytest.mark.parametrize('damage', [
    lambda s: s.replace(' xcr:CalibrationGroup="1"', ''),
    lambda s: s.replace(' xcr:DistortionGroup="1"', ''),
    lambda s: s.replace('DistortionGroup="1"', 'DistortionGroup="-1"'),
    lambda s: s.replace('CalibrationGroup="1"', 'CalibrationGroup="-1"'),
    lambda s: s.replace('CalibrationGroup="1"', 'CalibrationGroup="-2"'),
    lambda s: s.replace('CalibrationGroup="1"', 'CalibrationGroup="invalid"'),
    lambda s: s.replace(' xcr:FocalLength35mm="23.0"', ''),
    lambda s: s.replace('23.0', 'NaN'),
    lambda s: s.replace('23.0', 'inf'),
    lambda s: s.replace('23.0', '0'),
    lambda s: s.replace('23.0', '-1'),
    lambda s: s.replace('<xcr:Position>1 2 3</xcr:Position>', ''),
    lambda s: s.replace('1 2 3', '1 NaN 3'),
    lambda s: s.replace('1 2 3', '1 2'),
    lambda s: s[:-5],
    lambda s: s.replace('http://www.capturingreality.com/ns/xcr/1.1#', 'urn:wrong'),
    lambda s: s.replace('</rdf:Description>',
                        '<xcr:CalibrationGroup>1</xcr:CalibrationGroup></rdf:Description>'),
    lambda s: '<!DOCTYPE test [<!ENTITY v "1">]>' + s,
])
def test_invalid_evidence_fails_closed(tmp_path, damage):
    fixture = _fixture(tmp_path / 'output')
    pose = _pose(fixture)
    pose.write_text(damage(pose.read_text(encoding='utf-8')), encoding='utf-8')
    with pytest.raises(prior_census.PriorsNotApplied):
        _check(fixture)


def test_unreadable_files_stay_in_census_and_fail(tmp_path, monkeypatch):
    fixture = _fixture(tmp_path / 'output', [[
        ('ZEUSS_a.jpg', 1, 1, 23), ('ZEUSS_b.jpg', 1, 1, 23)]])
    denied = _pose(fixture)
    real_open = builtins.open

    def selective_open(path, *args, **kwargs):
        if Path(path) == denied:
            raise PermissionError('audit denied read')
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(builtins, 'open', selective_open)
    stats = prior_census.census(str(fixture.root / 'identity_r0'))
    assert stats['cameras'] == 2
    assert stats['unreadable'] == 1
    with pytest.raises(prior_census.PriorsNotApplied, match='unreadable'):
        _check(fixture)


def test_unreadable_harvest_directory_fails(tmp_path, monkeypatch):
    fixture = _fixture(tmp_path / 'output')

    def denied(_path):
        raise PermissionError('audit denied directory')

    monkeypatch.setattr(prior_census.os, 'scandir', denied)
    with pytest.raises(prior_census.PriorsNotApplied, match='Cannot read harvest'):
        _check(fixture)


def test_missing_all_groups_does_not_pass_expected_count(tmp_path):
    fixture = _fixture(tmp_path / 'output')
    _pose(fixture).write_text('<rdf:Description xcr:FocalLength35mm="23"/>',
                              encoding='utf-8')
    with pytest.raises(prior_census.PriorsNotApplied, match='CalibrationGroup absent'):
        prior_census.assert_priors_landed(str(fixture.root / 'identity_r0'),
                                          expected_groups=4)


def test_components_can_have_different_camera_families_and_renumbered_groups(tmp_path):
    fixture = _fixture(tmp_path / '[output]', [
        [('ZEUSS_a.jpg', 0, 7, 23), ('ZEUSS_b.jpg', 0, 7, 23)],
        [('P001C0001.jpg', 0, 7, 16), ('P001C0002.jpg', 0, 7, 16)],
    ])
    result = _check(fixture)
    assert result['cameras'] == 4
    assert set(result['components']) == {'zone_c0', 'zone_c1'}
    assert result['components']['zone_c1']['harvest_dir'].endswith('identity_r1')


def test_aliases_of_same_optic_do_not_inflate_expected_groups(tmp_path):
    fixture = _fixture(tmp_path / 'output', [[
        ('camupper_a.jpg', 17, 22, 16), ('U001C0001.jpg', 17, 22, 16)]])
    assert _check(fixture)['cameras'] == 2


def test_equal_focal_wca_cameras_still_have_independent_groups(tmp_path):
    fixture = _fixture(tmp_path / 'output', [[
        ('ZEUSS_a.jpg', 10, 20, 23), ('P001C0001.jpg', 11, 21, 16),
        ('C001C0001.jpg', 12, 22, 16), ('U001C0001.jpg', 13, 23, 16)]])
    stats = _check(fixture)['components']['zone_c0']
    assert len(stats['groups']) == len(stats['distortion_groups']) == 4
    assert stats['distinct_focals'] == 2


@pytest.mark.parametrize('entries', [
    [('P001C0001.jpg', 2, 2, 16), ('C001C0001.jpg', 2, 3, 16)],
    [('P001C0001.jpg', 2, 2, 16), ('C001C0001.jpg', 3, 2, 16)],
    [('P001C0001.jpg', 2, 2, 16), ('P001C0002.jpg', 3, 2, 16)],
    [('P001C0001.jpg', 2, 2, 16), ('P001C0002.jpg', 2, 3, 16)],
    [('mystery_a.jpg', 2, 2, 16)],
])
def test_optical_membership_is_checked_not_just_group_count(tmp_path, entries):
    fixture = _fixture(tmp_path / 'output', [entries])
    with pytest.raises(prior_census.PriorsNotApplied, match='families share|split across|unknown camera'):
        _check(fixture)


def test_one_ungrouped_registered_camera_cannot_hide_below_tolerance(tmp_path):
    entries = [(f'ZEUSS_{i}.jpg', 1, 1, 23) for i in range(99)]
    entries.append(('ZEUSS_bad.jpg', -1, -1, 23))
    fixture = _fixture(tmp_path / 'output', [entries])
    with pytest.raises(prior_census.PriorsNotApplied, match='has no group'):
        _check(fixture)


def test_small_bad_component_cannot_hide_in_zone_focal_fraction(tmp_path):
    fixture = _fixture(tmp_path / 'output', [
        [(f'ZEUSS_{i}.jpg', 1, 1, 23) for i in range(200)],
        [(f'P001C{i:04d}.jpg', 2, 2, 12 + i) for i in range(30)],
    ])
    assert prior_census.census(str(fixture.root / 'identity_r0'))['distinct_focal_fraction'] < .25
    with pytest.raises(prior_census.PriorsNotApplied, match='component zone_c1.*distinct solved focal'):
        _check(fixture)


def test_bad_later_harvest_cannot_hide_behind_good_r0(tmp_path):
    fixture = _fixture(tmp_path / 'output', [
        [('ZEUSS_a.jpg', 1, 1, 23)], [('P001C0001.jpg', 2, 2, 16)]])
    _pose(fixture, 1).write_text(_xmp(2, -1, 16), encoding='utf-8')
    with pytest.raises(prior_census.PriorsNotApplied, match='component zone_c1'):
        _check(fixture)


def test_invalid_future_member_in_intermediate_harvest_is_not_ignored(tmp_path):
    fixture = _fixture(tmp_path / 'output', [
        [('ZEUSS_a.jpg', 1, 1, 23)], [('P001C0001.jpg', 2, 2, 16)],
        [('C001C0001.jpg', 3, 3, 16)]])
    (fixture.root / 'identity_r1' / 'c001c0001.xmp').write_text(
        _xmp(3, -1, 16), encoding='utf-8')
    with pytest.raises(prior_census.PriorsNotApplied, match='component zone_c2'):
        _check(fixture)


def test_empty_csv_cannot_bypass_missing_terminal_harvest(tmp_path):
    fixture = _fixture(tmp_path / 'output')
    (fixture.root / 'identity_r1').rmdir()
    (fixture.root / 'identity').mkdir()
    (fixture.root / 'identity' / 'zone_c0.csv').write_text('# no members\n', encoding='utf-8')
    with pytest.raises(prior_census.PriorsNotApplied, match='CSV membership'):
        _check(fixture)


@pytest.mark.parametrize('damage', ['missing_pose', 'extra_pose', 'missing_terminal',
                                   'missing_manifest', 'duplicate_export', 'duplicate_manifest',
                                   'bad_count', 'wrong_export', 'empty_export'])
def test_export_manifest_and_harvest_coverage(tmp_path, damage):
    fixture = _fixture(tmp_path / 'output')
    if damage == 'missing_pose':
        _pose(fixture).unlink()
    elif damage == 'extra_pose':
        (fixture.root / 'identity_r0' / 'zeuss_extra.xmp').write_text(_xmp(), encoding='utf-8')
    elif damage == 'missing_terminal':
        (fixture.root / 'identity_r1').rmdir()
    elif damage == 'missing_manifest':
        fixture.manifests.clear()
    elif damage == 'duplicate_export':
        fixture.exports.append(fixture.exports[0])
    elif damage == 'duplicate_manifest':
        fixture.manifests.append(fixture.manifests[0])
    elif damage == 'bad_count':
        _change_manifest(fixture, {'camera_count': 2})
    elif damage == 'wrong_export':
        _change_manifest(fixture, {'rsalign': str(tmp_path / 'other.rsalign')})
    else:
        Path(fixture.exports[0]).write_bytes(b'')
    with pytest.raises(prior_census.PriorsNotApplied):
        _check(fixture)


@pytest.mark.parametrize('images', [
    ['ZEUSS_a.jpg', 'zeuss_A.JPG'],
    ['first/ZEUSS_a.jpg', 'second/ZEUSS_a.jpg'],
    ['ZEUSS_a.jpg', 'ZEUSS_a.png'],
])
def test_duplicate_or_ambiguous_manifest_images_are_refused(tmp_path, images):
    fixture = _fixture(tmp_path / 'output')
    _change_manifest(fixture, {'images': images, 'camera_count': len(images)})
    with pytest.raises(prior_census.PriorsNotApplied, match='duplicate/ambiguous'):
        _check(fixture)


def test_shared_image_between_components_is_not_silently_attributed(tmp_path):
    fixture = _fixture(tmp_path / 'output', [
        [('ZEUSS_a.jpg', 1, 1, 23)], [('ZEUSS_a.jpg', 1, 1, 23)]])
    with pytest.raises(prior_census.PriorsNotApplied, match='duplicate/ambiguous'):
        _check(fixture)


def test_csv_identity_alone_is_explicitly_unmeasured(tmp_path):
    fixture = _fixture(tmp_path / 'output', csv=True)
    _pose(fixture).unlink()
    with pytest.raises(prior_census.PriorsNotApplied, match='CSV identity alone'):
        _check(fixture)


def test_csv_membership_with_complete_shared_pose_evidence(tmp_path):
    fixture = _fixture(tmp_path / 'output', [
        [('ZEUSS_a.jpg', 1, 1, 23)], [('P001C0001.jpg', 2, 2, 16)]], csv=True)
    assert _check(fixture)['cameras'] == 2


@pytest.mark.parametrize('rows', [
    'ZEUSS_other.jpg,0,0,0\n',
    'ZEUSS_a.jpg,0,0,0\nZEUSS_a.jpg,0,0,0\n',
    'ZEUSS_a.jpg,0,0,0\n,0,0,0\n',
])
def test_csv_identity_rows_must_agree_with_the_manifest(tmp_path, rows):
    fixture = _fixture(tmp_path / 'output', [[('ZEUSS_a.jpg', 1, 1, 23)]], csv=True)
    (fixture.root / 'identity' / 'zone_c0.csv').write_text(rows, encoding='utf-8')
    with pytest.raises(prior_census.PriorsNotApplied):
        _check(fixture)


def test_invalid_utf8_is_not_silently_replaced(tmp_path):
    fixture = _fixture(tmp_path / 'output')
    _pose(fixture).write_bytes(_xmp().encode('utf-8') + b'\xff')
    with pytest.raises(prior_census.PriorsNotApplied, match='unreadable'):
        _check(fixture)


def _alignment_fixture(tmp_path, monkeypatch, *, bad=False):
    # Bypass the runtime constructor entirely: no executable discovery, shared
    # marker/lock files, installation changes, subprocesses or RealityScan.
    module = object.__new__(interface.RealityScanAlignment)
    RSModule.__init__(module, 'offline calibration audit', logging.getLogger('prior-audit'))
    source = tmp_path / 'staged'
    source.mkdir()
    (source / 'ZEUSS_a.jpg').write_bytes(b'fixture')
    (source / 'P001C0001.jpg').write_bytes(b'unregistered fixture')
    output = tmp_path / 'results' / 'aligned_components' / 'zone'
    monkeypatch.setenv('RS_ALLOW_NO_FLIGHT_LOG', '1')
    monkeypatch.setenv('RS_LEGACY_XMP_IDENTITY', '0')
    for key in ('RS_SKIP_PRIOR_CENSUS', 'RS_ALIGN_POOL_DIR'):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(interface.align_fingerprint, 'build_fingerprint', lambda *a, **k: {})
    monkeypatch.setattr(interface.flightlog_format, 'install_all_managed', lambda **k: None)
    monkeypatch.setattr(interface.flightlog_format, 'assert_calibration_format_installed',
                        lambda *a, **k: None)
    # These tests isolate POST-alignment component evidence. The mandatory
    # fresh-input gate is exercised with real serializer/CSV/report fixtures
    # in test_native_prior_delivery.py, not bypassed in production.
    expected_input = tmp_path / 'expected_input.json'
    expected_input.write_text('{}')
    input_result = tmp_path / 'input_result.json'
    monkeypatch.setattr(interface, 'prepare_input_prior_contract', lambda *a, **k: {
        'RS_INPUT_PRIOR_MANIFEST': str(expected_input), 'RS_INPUT_PRIOR_SHA256': 'offline',
        'RS_INPUT_PRIOR_RESULT': str(input_result)})

    def fake_run(*args, **kwargs):
        input_result.write_text(json.dumps({'verdict': 'VERIFIED_INPUT_PRIORS', 'expected_sha256': 'offline'}))
        (output / 'zone.rsproj').write_bytes(b'fixture project')
        _fixture(output, [[('ZEUSS_a.jpg', 1, -1 if bad else 1, 23)]], csv=True)
        return SimpleNamespace(success=True)

    module.cli = SimpleNamespace(find_executable=lambda: None, run_batch_script=fake_run)
    return module, source, output


def test_interface_uses_registered_component_members_not_input_family_count(tmp_path, monkeypatch):
    module, source, output = _alignment_fixture(tmp_path, monkeypatch)
    components, scene = module._RealityScanAlignment__align_zone(
        str(source), str(output), 'zone', None, None)
    assert components['Success'] and scene['Success']
    assert components['Prior Census']['cameras'] == 1


def test_interface_returns_failed_census_with_evidence_detail(tmp_path, monkeypatch):
    module, source, output = _alignment_fixture(tmp_path, monkeypatch, bad=True)
    components, scene = module._RealityScanAlignment__align_zone(
        str(source), str(output), 'zone', None, None)
    assert not components['Success']
    assert scene['Success']  # Saved artifacts survive a failed verdict.
    assert 'DistortionGroup' in components['Prior Census Error']


def test_interface_unexpected_checker_exception_fails_closed(tmp_path, monkeypatch):
    module, source, output = _alignment_fixture(tmp_path, monkeypatch)

    def broken(*args, **kwargs):
        raise RuntimeError('injected census defect')

    monkeypatch.setattr(prior_census, 'assert_component_priors', broken)
    components, scene = module._RealityScanAlignment__align_zone(
        str(source), str(output), 'zone', None, None)
    assert components['Success'] is False
    assert scene['Success']
    assert components['Error'] == 'calibration prior census unavailable'
    assert components['Prior Census Error'] == 'RuntimeError: injected census defect'
