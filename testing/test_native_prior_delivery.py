"""Actual production serializer and input census; no RealityScan execution."""
import copy
import csv
import json
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

from modules import camera_registry as registry, prior_census as census, align_fingerprint


@pytest.fixture
def inputs(tmp_path):
    images = []
    for i, prefix in enumerate(('camupper', 'cammid', 'camlower', 'herc')):
        path = tmp_path / (prefix + '_probe.jpeg')
        path.write_bytes(f'unique geometry {i}'.encode())
        path.with_suffix('.xmp').write_text(registry.calibration_xmp(registry.identify(path.name)))
        images.append(path)
    params = tmp_path / 'params.xml'
    params.write_text('<Configuration><entry key="ifKGrp" value="0"/>'
                      '<entry key="CoordinateSystemFlightLogType" value="local:1 - Euclidean"/></Configuration>')
    csv_path = tmp_path / 'flight_log.txt'
    with csv_path.open('w', newline='') as stream:
        writer = csv.writer(stream, delimiter=';')
        writer.writerow(['filename', 'X', 'Y', 'Alt', 'XAccuracy', 'YAccuracy', 'AltAccuracy',
                         'Yaw', 'Pitch', 'Roll', 'YawAccuracy', 'PitchAccuracy', 'RollAccuracy', 'FocalLength'])
        for i, path in enumerate(images):
            writer.writerow([str(path), 101+i, 203+i, -307-i, 5, 5, 1, 11+i, 22+i, 33+i,
                             10, 40 if i == 3 else 10, 10, 999])  # CSV focal is deliberately not authority.
    return images, csv_path, params


def manifest(inputs):
    return census.build_input_prior_manifest(*inputs)


def report_text(contract):
    lines = ['INPUT_PRIORS=1']
    for index, row in enumerate(contract['images']):
        path = Path(row['filename'])
        lines.append(f'IMAGE|{index}|{path.parent}|{path.stem}|{path.suffix}|False')
        values = dict(inputIsPositionPrior='True', inputIsOrientationPrior='True', inputIsPriorAccuracy='True',
                      inputIsLatLong='False', inputCS=contract['coordinate_system'],
                      calibrationGroup=str(row['calibration_group']), distortionGroup=str(row['distortion_group']),
                      inputF=str(row['focal']), inputLensModel=row['lens'], inputCalibrationPriorType='20642')
        for keys, name in ((('inputX','inputY','inputZ'), 'position'),
                           (('inputYaw','inputPitch','inputRoll'), 'orientation'),
                           (census.INPUT_FIELDS[11:17], 'accuracy')):
            values.update(zip(keys, map(str, row[name])))
        lines.append(f'PRIOR|{index}|' + '|'.join(values[field] for field in census.INPUT_FIELDS))
    return '\n'.join(lines + ['END_INPUT_PRIORS'])


def test_actual_serializer_native_attributes_no_pose(inputs):
    for image in inputs[0]:
        camera = registry.identify(image.name)
        content = registry.calibration_xmp(camera)
        root = ET.fromstring(content)
        attributes = next(node.attrib for node in root.iter() if node.tag.endswith('Description'))
        ns = '{http://www.capturingreality.com/ns/xcr/1.1#}'
        assert attributes[ns + 'CalibrationPrior'] == 'initial'
        assert float(attributes[ns + 'FocalLength35mm']) == camera.focal_length_35mm
        assert attributes[ns + 'DistortionGroup'] == camera.lens_distortion_group
        assert all(token not in content for token in ('Camera:', 'Position', 'Rotation', 'PosePrior'))
        registry.validate_calibration_xmp(content, camera)


@pytest.mark.parametrize('change', ['focal', 'group', 'lens', 'pose', 'malformed', 'legacy'])
def test_strict_calibration_validation_preserves_bad_and_solved_files(inputs, change):
    image = inputs[0][0]
    sidecar = image.with_suffix('.xmp')
    content = sidecar.read_text()
    if change == 'focal':
        content = content.replace('FocalLength35mm="16"', 'FocalLength35mm="576"')
    elif change == 'group':
        content = content.replace('CalibrationGroup="4"', 'CalibrationGroup="1"')
    elif change == 'lens':
        content = content.replace('division', 'brown3')
    elif change == 'pose':
        content = content.replace('xcr:Version=', 'xcr:PosePrior="locked" xcr:Version=')
    elif change == 'legacy':
        content = content.replace('ns/xcr/1.1#', 'ns/xcr/1.0/')
    else:
        content = 'broken XML'
    sidecar.write_text(content)
    with pytest.raises(census.PriorsNotApplied):
        manifest(inputs)
    assert sidecar.read_text() == content


@pytest.mark.parametrize('change', ['missing_xmp', 'mask', 'duplicate_path', 'duplicate_bytes', 'grouping', 'outside_csv', 'missing_csv', 'nan'])
def test_invalid_contract_refused(inputs, change):
    images, log, params = inputs
    if change == 'missing_xmp':
        images[0].with_suffix('.xmp').unlink()
    elif change == 'mask':
        mask = images[0].with_name(images[0].name + '.mask.png')
        mask.write_bytes(b'mask')
        images.append(mask)
    elif change == 'duplicate_path':
        images.append(images[0])
    elif change == 'duplicate_bytes':
        images[1].write_bytes(images[0].read_bytes())
    elif change == 'grouping':
        params.write_text(params.read_text().replace('value="0"', 'value="1"'))
    elif change == 'outside_csv':
        log.write_text(log.read_text().replace(str(images[0]), 'outside.jpeg'))
    elif change == 'missing_csv':
        lines = log.read_text().splitlines()
        log.write_text('\n'.join(lines[:-1]))
    else:
        log.write_text(log.read_text().replace(';101;', ';NaN;'))
    with pytest.raises(census.PriorsNotApplied):
        manifest(inputs)


def test_positive_actual_serializer_census_and_cli(inputs, tmp_path):
    contract = manifest(inputs)
    channels = census.write_input_prior_contract(contract, tmp_path / 'contract')
    report = Path(channels['RS_INPUT_PRIOR_REPORT'])
    report.write_text(report_text(contract))
    value = census.assert_input_priors(contract, report)
    assert value['verdict'] == 'VERIFIED_INPUT_PRIORS' and value['cameras'] == 4
    assert value['physical_axis_verified'] is False
    assert census.input_census_main(['--input-manifest', channels['RS_INPUT_PRIOR_MANIFEST'],
        '--expected-sha256', channels['RS_INPUT_PRIOR_SHA256'], '--input-report', str(report),
        '--output', channels['RS_INPUT_PRIOR_RESULT']]) == 0
    assert json.loads(Path(channels['RS_INPUT_PRIOR_RESULT']).read_text())['expected_sha256'] == channels['RS_INPUT_PRIOR_SHA256']


@pytest.mark.parametrize('field,value', [('inputIsPositionPrior','False'), ('inputIsOrientationPrior','False'),
    ('inputIsPriorAccuracy','False'), ('inputX','0'), ('inputYaw','0'), ('inputAccuracyPitch','10'),
    ('calibrationGroup','4294967295'), ('distortionGroup','0'), ('inputF','576'), ('inputLensModel','brown3')])
def test_bad_readback_cannot_reach_alignment(inputs, tmp_path, field, value):
    contract = manifest(inputs)
    text = report_text(contract)
    lines = text.splitlines()
    # Mutate Zeuss for per-camera pitch uncertainty (40 versus fixed 10).
    zeuss_index = next(i for i,row in enumerate(contract['images']) if row['family'] == 'zeuss')
    line_index = 2 + zeuss_index * 2
    parts = lines[line_index].split('|')
    parts[2 + census.INPUT_FIELDS.index(field)] = value
    lines[line_index] = '|'.join(parts)
    report = tmp_path / 'bad.html'
    report.write_text('\n'.join(lines))
    with pytest.raises(census.PriorsNotApplied):
        census.assert_input_priors(contract, report)


def test_changed_inputs_and_unhandled_errors_fail_closed(inputs, tmp_path, monkeypatch):
    contract = manifest(inputs)
    channels = census.write_input_prior_contract(contract, tmp_path / 'contract')
    report = Path(channels['RS_INPUT_PRIOR_REPORT'])
    report.write_text(report_text(contract))
    inputs[0][0].write_bytes(b'changed')
    with pytest.raises(census.PriorsNotApplied, match='changed'):
        census.assert_input_priors(contract, report)
    monkeypatch.setattr(census, 'assert_input_priors', lambda *args: (_ for _ in ()).throw(RuntimeError('unexpected')))
    assert census.input_census_main(['--input-manifest', channels['RS_INPUT_PRIOR_MANIFEST'],
        '--expected-sha256', channels['RS_INPUT_PRIOR_SHA256'], '--input-report', str(report),
        '--output', channels['RS_INPUT_PRIOR_RESULT']]) == 1
    assert 'unexpected' in Path(channels['RS_INPUT_PRIOR_RESULT']).read_text()


def test_gate_order_single_csv_and_continuation_scope():
    repo = Path(__file__).resolve().parents[1]
    batch = (repo / 'modules/realityscan_interface/RS_CLI/Scripts/AlignZone.bat').read_text()
    assert batch.count('call :run -importFlightLog ') == 1
    assert batch.index('if defined RS_GEOREG_ONLY') < batch.index('if not defined RS_INPUT_PRIOR_MANIFEST')
    assert batch.index('call :run -importFlightLog ') < batch.index('call :run -exportReport "%RS_INPUT_PRIOR_REPORT%"')
    assert batch.index('-m modules.prior_census') < batch.index('call :run -align ')
    assert 'if errorlevel 1 ( popd & goto :fail )' in batch
    mask_setting = 'call :run -editInputSelection "inpMaskOpts=3" || goto :fail'
    assert batch.count(mask_setting) == 1
    assert batch.index(':imagesAdded\n') < batch.index(mask_setting) < batch.index('call :run -importFlightLog ')
    assert 'call :run -selectAllImages || goto :fail\n' + mask_setting in batch


def test_exact_input_contract_is_material_fingerprint(inputs, monkeypatch):
    monkeypatch.setattr(align_fingerprint, '_repo_sha', lambda: 'offline')
    contract = manifest(inputs)
    args = (str(inputs[1]), str(inputs[2]), None, 50)
    first = align_fingerprint.build_fingerprint(*args, input_prior_contract=contract)
    changed = copy.deepcopy(contract)
    changed['images'][0]['image_sha256'] = 'different'
    second = align_fingerprint.build_fingerprint(*args, input_prior_contract=changed)
    assert any('exact pre-alignment' in item for item in align_fingerprint.diff_fingerprints(first, second))
