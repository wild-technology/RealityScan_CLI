"""Pure offline comparator cases: no logging, shared markers, or RS fixtures."""
import copy
import json
from pathlib import Path

import pytest

from testing import rs_prior_probe_compare as compare


GLOBALS = dict(zip(('X', 'Y', 'Z', 'Yaw', 'Pitch', 'Roll'), (17, 19, 23, 29, 31, 37)))


def fixture(cell='csv_i1_g0', stages=('csv_first',)):
    expected, rows = [], []
    for i, family in enumerate(('upper', 'mid', 'lower', 'zeuss')):
        sentinel = dict(image=f'C:\\owned\\{family}.jpeg', family=family,
                        csv_position=[101 + i, 203 + i, -307 - i], csv_ypr=[11 + i, 22 + i, 33 + i],
                        csv_accuracy=[1.11 + i, 2.22 + i, 3.33 + i, 4.44 + i, 5.55 + i, 6.66 + i],
                        csv_focal=23 if i == 3 else 16, xmp_position=[1001 + i, 2003 + i, -3007 - i],
                        xmp_focal=31 + i, xmp_calibration_group=101 + i, xmp_distortion_group=201 + i,
                        cli_calibration_group=301 + i, cli_distortion_group=401 + i,
                        edit_calibration_group=501 + i, edit_distortion_group=601 + i,
                        edit_ypr=[-21 - i, 34 + i, -47 - i], edit_accuracy=[7 + i, 8 + i, 9 + i, 10 + i, 11 + i, 12 + i])
        expected.append(sentinel)
        row = dict(filename=sentinel['image'], input_index=str(i), inputCS='local:1 - Euclidean',
                   inputCalibrationPriorType='20640', inputLensModel='perspective',
                   inputF=str(sentinel['csv_focal']), calibrationGroup=str(101 + i), distortionGroup=str(201 + i),
                   inputOmega='0', inputPhi='0', inputKappa='0')
        row.update({key: 'True' for key in compare.FLAGS})
        row.update(inputIsLatLong='False', inputIsOpkRotationPrior='False')
        for fields, key in ((compare.POSITION, 'csv_position'), (compare.ORIENTATION, 'csv_ypr'), (compare.ACCURACY, 'csv_accuracy')):
            row.update(zip(fields, map(str, sentinel[key])))
        rows.append(row)
    detail = dict(expected=expected, reports=[dict(stage=stage, path='unused') for stage in stages])
    evidence = dict(cell=cell, alignment_performed=False, reports={stage: copy.deepcopy(rows) for stage in stages})
    return detail, evidence


def result(detail, evidence):
    return compare.compare_cell(detail, evidence, evidence['cell'], GLOBALS)


def test_known_csv_sentinels_and_undocumented_enum_are_distinct():
    detail, evidence = fixture()
    value = result(detail, evidence)
    assert value['control_contract'] == 'MATCH'
    assert value['production_delivery'] == 'MATCH'
    row = value['stages']['csv_first']['rows'][0]
    assert row['calibration_prior'] == dict(raw='20640', interpretation='UNDOCUMENTED_ENUM')
    assert row['matching_sentinels'] == dict(position=['CSV_FIRST'], orientation=['CSV_FIRST'], accuracy=['CSV'])


@pytest.mark.parametrize('cell', ['production_calibration_csv', 'production_mask_control', 'production_mask_cold'])
@pytest.mark.parametrize('bad', [None, 'group', 'focal', 'accuracy_flag'])
@pytest.mark.parametrize('group_type', [int, str])
def test_production_uses_exact_xmp_calibration_and_active_csv(cell, bad, group_type):
    detail, evidence = fixture(cell, ('added', 'csv_first'))
    for expected in detail['expected']:
        for key in ('xmp_calibration_group', 'xmp_distortion_group'):
            expected[key] = group_type(expected[key])
    for stage, rows in evidence['reports'].items():
        for row, expected in zip(rows, detail['expected']):
            row.update(inputF=str(expected['xmp_focal']), inputLensModel='division')
            if stage == 'added':
                row.update({key: 'False' for key in compare.FLAGS})
                row.update(zip(compare.ACCURACY, map(str, GLOBALS.values())))
    row = evidence['reports']['csv_first'][0]
    if bad == 'group':
        row['calibrationGroup'] = '999'
    elif bad == 'focal':
        row['inputF'] = str(detail['expected'][0]['csv_focal'])
    elif bad == 'accuracy_flag':
        row['inputIsPriorAccuracy'] = 'False'
    value = result(detail, evidence)
    assert value['control_contract'] == ('MISMATCH' if bad else 'MATCH')
    assert value['stages']['csv_first']['focal_authority'] == 'XMP'


def test_negative_control_flags_do_not_claim_default_values_are_priors():
    detail, evidence = fixture('report_control', ('added',))
    for row in evidence['reports']['added']:
        row.update({key: 'False' for key in compare.FLAGS})
        row.update(zip(compare.POSITION, ['0'] * 3))
        row.update(zip(compare.ORIENTATION, ['180', '-0', '180']))
        row.update(zip(compare.ACCURACY, map(str, GLOBALS.values())))
        row.update(calibrationGroup='4294967295', distortionGroup='-1', inputCS='(null)')
    value = result(detail, evidence)
    assert value['control_contract'] == 'MATCH'
    assert value['production_delivery'] == 'NOT_TESTED'
    stage = value['stages']['added']
    assert stage['groups']['calibrationGroup']['partition'] == [None] * 4
    assert stage['rows'][0]['matching_sentinels']['orientation'] == ['NO_PRIOR_DEFAULT']
    assert stage['rows'][0]['flags']['inputIsOrientationPrior'] is False


@pytest.mark.parametrize('field', ['inputIsPositionPrior', 'inputIsOrientationPrior'])
def test_correct_numeric_csv_with_false_flag_is_not_delivery(field):
    detail, evidence = fixture()
    evidence['reports']['csv_first'][0][field] = 'False'
    value = result(detail, evidence)
    assert value['control_contract'] == 'MISMATCH'
    assert value['production_delivery'] == 'MISMATCH'


@pytest.mark.parametrize('value', ['', 'NaN', 'Infinity', '(null)', None, True])
def test_missing_nonfinite_measurements_never_pass(value):
    detail, evidence = fixture('native_xmp_only', ('added',))
    evidence['reports']['added'][0]['inputX'] = value
    with pytest.raises(ValueError):
        result(detail, evidence)


def test_second_csv_increments_only_position_and_ypr():
    detail, evidence = fixture('native_xmp_csv_g0', ('csv_first', 'csv_second'))
    for row, sentinel in zip(evidence['reports']['csv_second'], detail['expected']):
        row.update(zip(compare.POSITION, map(str, [x + 100 for x in sentinel['csv_position']])))
        row.update(zip(compare.ORIENTATION, map(str, [x + 1 for x in sentinel['csv_ypr']])))
        row['inputF'] = str(sentinel['xmp_focal'])
    value = result(detail, evidence)
    assert value['production_delivery'] == 'MATCH'
    sources = value['stages']['csv_second']['rows'][0]['matching_sentinels']
    assert sources == dict(position=['CSV_SECOND'], orientation=['CSV_SECOND'], accuracy=['CSV'])
    evidence['reports']['csv_second'] = copy.deepcopy(evidence['reports']['csv_first'])
    assert result(detail, evidence)['production_delivery'] == 'MISMATCH'


def test_angular_wrap_and_report_rounding_only():
    assert compare.matches([371, 22, -327], [11, 22, 33], angular=True)
    assert compare.matches([1.111111], [1.111111111])
    assert not compare.matches([1.11], [1.111])


def test_global_inheritance_is_measured_but_not_per_camera_delivery():
    detail, evidence = fixture('csv_i0_g0')
    for row in evidence['reports']['csv_first']:
        row.update(zip(compare.ACCURACY, map(str, GLOBALS.values())))
        row['inputIsPriorAccuracy'] = 'False'
    value = result(detail, evidence)
    assert value['control_contract'] == 'MATCH'
    assert value['production_delivery'] == 'MISMATCH'
    assert value['stages']['csv_first']['rows'][0]['matching_sentinels']['accuracy'] == ['GLOBAL']
    evidence['reports']['csv_first'][0]['inputAccuracyX'] = '1.11'
    assert result(detail, evidence)['control_contract'] == 'MISMATCH'


@pytest.mark.parametrize('groups', [['4294967295'] * 4, ['3'] * 4, ['1', '1', '1', '2']])
def test_finite_ungrouped_and_shared_optics_are_production_mismatches(groups):
    detail, evidence = fixture('csv_i1_g1')
    for row, group in zip(evidence['reports']['csv_first'], groups):
        row['calibrationGroup'] = group
    value = result(detail, evidence)
    assert value['production_delivery'] == 'MISMATCH'
    assert not value['stages']['csv_first']['production_requirements']['calibration_separate']


def test_native_xmp_groups_allow_relabeling_but_not_merging():
    detail, evidence = fixture('native_xmp_only', ('added',))
    for i, (row, sentinel) in enumerate(zip(evidence['reports']['added'], detail['expected'])):
        row.update(zip(compare.POSITION, map(str, sentinel['xmp_position'])))
        row.update(inputF=str(sentinel['xmp_focal']), calibrationGroup=str(i), distortionGroup=str(i + 90), inputLensModel='division')
    value = result(detail, evidence)
    assert value['control_contract'] == 'MATCH'
    assert value['open_claims'] == ['XMP matrix-to-reported-angle convention not established']
    for row in evidence['reports']['added']:
        row.update(inputIsPositionPrior='False', inputIsOrientationPrior='False')
    inactive = result(detail, evidence)
    assert inactive['control_contract'] == 'MATCH'  # Numeric calibration/pose import, not activity.
    assert inactive['production_delivery'] == 'NOT_TESTED'
    assert inactive['stages']['added']['reported_pose_flags_active'] is False
    assert any('active absolute prior flags not established' in claim for claim in inactive['open_claims'])
    evidence['reports']['added'][0]['distortionGroup'] = '91'
    assert result(detail, evidence)['control_contract'] == 'MISMATCH'


def test_legacy_focal_rescaling_and_unset_groups_are_explicit_mismatches():
    detail, evidence = fixture('legacy_xmp_only', ('added',))
    for row, sentinel in zip(evidence['reports']['added'], detail['expected']):
        row.update({key: 'False' for key in compare.FLAGS})
        row.update(zip(compare.ACCURACY, map(str, GLOBALS.values())))
        row.update(inputF=str(36 * sentinel['xmp_focal']), calibrationGroup='4294967295', distortionGroup='4294967295')
    value = result(detail, evidence)
    assert value['control_contract'] == 'MISMATCH'
    assert all(row['focal_to_xmp_sentinel_ratio'] == 36 for row in value['stages']['added']['rows'])


@pytest.mark.parametrize('stage,prefix', [('cli_groups', 'cli'), ('edit_groups', 'edit')])
def test_explicit_group_setter_sentinels(stage, prefix):
    detail, evidence = fixture('group_controls', (stage,))
    for row, sentinel in zip(evidence['reports'][stage], detail['expected']):
        row['calibrationGroup'] = str(sentinel[prefix + '_calibration_group'])
        row['distortionGroup'] = str(sentinel[prefix + '_distortion_group'])
    assert result(detail, evidence)['control_contract'] == 'MATCH'
    evidence['reports'][stage][0]['distortionGroup'] = '-1'
    assert result(detail, evidence)['control_contract'] == 'MISMATCH'


def test_rotation_setter_sentinels_include_all_six_accuracies():
    detail, evidence = fixture('rotation_cli_control', ('rotation_setter',))
    for row, sentinel in zip(evidence['reports']['rotation_setter'], detail['expected']):
        row.update(zip(compare.ORIENTATION, map(str, sentinel['edit_ypr'])))
        row.update(zip(compare.ACCURACY, map(str, sentinel['edit_accuracy'])))
    assert result(detail, evidence)['production_delivery'] == 'MATCH'
    evidence['reports']['rotation_setter'][0]['inputAccuracyRoll'] = '6.66'
    assert result(detail, evidence)['control_contract'] == 'MISMATCH'


@pytest.mark.parametrize('defect', ['duplicate', 'missing', 'foreign', 'stage', 'flag'])
def test_identity_coverage_and_invalid_flags_refused(defect):
    detail, evidence = fixture()
    rows = evidence['reports']['csv_first']
    if defect == 'duplicate':
        rows.append(copy.deepcopy(rows[0]))
    elif defect == 'missing':
        rows.pop()
    elif defect == 'foreign':
        rows[0]['filename'] = 'C:\\foreign.jpeg'
    elif defect == 'stage':
        evidence['reports']['unexpected'] = []
    else:
        rows[0]['inputIsPositionPrior'] = ''
    with pytest.raises(ValueError):
        result(detail, evidence)


def write_evidence(tmp_path):
    detail, evidence = fixture()
    directory = tmp_path / 'csv_i1_g0'
    directory.mkdir()
    report = directory / 'csv_first.html'
    detail['reports'][0]['path'] = str(report)
    fields = ('inputIsPositionPrior', 'inputIsOrientationPrior', 'inputIsPriorAccuracy', 'inputIsLatLong',
              'inputCS', *compare.POSITION, *compare.ORIENTATION, *compare.ACCURACY, *compare.GROUPS,
              'inputF', 'inputCalibrationPriorType', 'inputLensModel', 'inputIsOpkRotationPrior',
              'inputOmega', 'inputPhi', 'inputKappa')
    lines = ['PROBE_SCHEMA=1']
    for row in evidence['reports']['csv_first']:
        directory_name, filename = compare.ntpath.split(row['filename'])
        stem, extension = compare.ntpath.splitext(filename)
        lines.append(f'IMAGE|{row["input_index"]}|{directory_name}|{stem}|{extension}|False')
        lines.append(f'PRIOR|{row["input_index"]}|' + '|'.join(row[field] for field in fields))
    report.write_text('\n'.join(lines + ['END_PROBE']))
    readback = directory / 'readback.json'
    readback.write_text(json.dumps(evidence))
    manifest = tmp_path / 'probe.json'
    manifest.write_text(json.dumps(dict(root=str(tmp_path), alignment_allowed=False, cells=['csv_i1_g0'],
                                         cell_details={'csv_i1_g0': detail})))
    return manifest, readback, report


def test_machine_evidence_pins_actual_raw_reports_and_refuses_stale_json(tmp_path):
    manifest, readback, report = write_evidence(tmp_path)
    digest = compare.sha256(manifest)
    output = compare.compare(manifest, digest)
    assert output['comparison_status'] == 'COMPLETE_MATCH'
    assert output['scientific_run_authorized'] is False
    assert output['cells'][0]['evidence_sha256'][str(report)] == compare.sha256(report)
    evidence = json.loads(readback.read_text())
    evidence['reports']['csv_first'][0]['inputYaw'] = '99'
    readback.write_text(json.dumps(evidence))
    output = compare.compare(manifest, digest)
    assert output['comparison_status'] == 'BLOCKED'
    assert output['cells'][0]['evidence_status'] == 'INVALID'


def test_pending_invalid_json_and_wrong_hash_cannot_pass(tmp_path):
    manifest, readback, _ = write_evidence(tmp_path)
    digest = compare.sha256(manifest)
    readback.unlink()
    assert compare.compare(manifest, digest)['cells'][0]['evidence_status'] == 'PENDING'
    readback.write_text('{"cell": 1, "cell": 2}')
    assert compare.compare(manifest, digest)['cells'][0]['evidence_status'] == 'INVALID'
    with pytest.raises(ValueError, match='hash mismatch'):
        compare.compare(manifest, '0' * 64)
