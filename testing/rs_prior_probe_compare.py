"""Read-only deterministic comparison of immutable import-probe evidence.

Prints JSON; never launches RS or writes evidence. Exit 0 means all requested
cells have complete measurements and satisfy their explicit control contracts.
Exit 2 means missing/invalid evidence or a control mismatch. Neither authorizes
a scientific run: physical camera/world axes remain a separate open claim.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import ntpath
from pathlib import Path

POSITION = ('inputX', 'inputY', 'inputZ')
ORIENTATION = ('inputYaw', 'inputPitch', 'inputRoll')
ACCURACY = ('inputAccuracyX', 'inputAccuracyY', 'inputAccuracyZ',
            'inputAccuracyYaw', 'inputAccuracyPitch', 'inputAccuracyRoll')
FLAGS = ('inputIsPositionPrior', 'inputIsOrientationPrior', 'inputIsPriorAccuracy',
         'inputIsLatLong', 'inputIsOpkRotationPrior')
GROUPS = ('calibrationGroup', 'distortionGroup')
TOLERANCE = 0.00001  # Absolute report-rounding tolerance, in each field's units.


def sha256(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'Duplicate JSON key: {key}')
        result[key] = value
    return result


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'), object_pairs_hook=_pairs,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))


def identity(path):
    return ntpath.normcase(ntpath.normpath(str(path)))


def number(value):
    if isinstance(value, bool) or value is None or str(value).strip() == '':
        raise ValueError(f'Missing/non-numeric measurement: {value!r}')
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f'Nonfinite measurement: {value!r}')
    return result


def flag(value):
    value = str(value).lower()
    if value not in ('true', 'false', '1', '0'):
        raise ValueError(f'Invalid prior flag: {value!r}')
    return value in ('true', '1')


def group(value):
    # v02 no-prior control exposes uint32(-1); never count it as a group.
    numeric = number(value)
    if not numeric.is_integer() or numeric < -1 or numeric > 4294967295:
        raise ValueError(f'Invalid group id: {value!r}')
    return None if numeric in (-1, 4294967295) else int(numeric)


def matches(actual, expected, angular=False):
    if len(actual) != len(expected):
        return False
    return all(abs((a - b + 180) % 360 - 180 if angular else a - b) <= TOLERANCE
               for a, b in zip(actual, expected))


def partition(values):
    labels = {}
    return [None if value is None else labels.setdefault(value, len(labels)) for value in values]


def _raw_report(path):
    text = Path(path).read_text(encoding='utf-8-sig')
    if 'PROBE_SCHEMA=1' not in text or 'END_PROBE' not in text or '$(' in text:
        raise ValueError('Missing report boundary or unexpanded macros')
    # Field order is the frozen v02 template contract, independent of mutable harness code.
    fields = ('inputIsPositionPrior', 'inputIsOrientationPrior', 'inputIsPriorAccuracy',
              'inputIsLatLong', 'inputCS', *POSITION, *ORIENTATION, *ACCURACY, *GROUPS,
              'inputF', 'inputCalibrationPriorType', 'inputLensModel',
              'inputIsOpkRotationPrior', 'inputOmega', 'inputPhi', 'inputKappa')
    images, priors = {}, {}
    for line in text.splitlines():
        parts = line.strip().split('|')
        if parts[0] == 'IMAGE':
            if len(parts) != 6 or parts[1] in images or flag(parts[-1]):
                raise ValueError('Invalid, duplicate or aligned IMAGE row')
            images[parts[1]] = parts[2:5]
        elif parts[0] == 'PRIOR':
            if len(parts) != len(fields) + 2 or parts[1] in priors:
                raise ValueError('Invalid or duplicate PRIOR row')
            priors[parts[1]] = dict(zip(fields, parts[2:]))
    if not images or set(images) != set(priors):
        raise ValueError('Incomplete IMAGE/PRIOR coverage')
    rows = []
    for index, (directory, name, extension) in images.items():
        filename = ntpath.join(directory, name + (extension if extension.startswith('.') else '.' + extension))
        rows.append(dict(filename=filename, input_index=index, **priors[index]))
    return rows


def compare_cell(detail, evidence, cell, globals_):
    """Compare only manifest expectations; never trust readback.expected/verdict."""
    expected = {identity(row['image']): row for row in detail['expected']}
    if len(expected) != len(detail['expected']) or not expected:
        raise ValueError('Duplicate/empty expected image identities')
    stages = [item['stage'] for item in detail['reports']]
    if len(set(stages)) != len(stages) or set(evidence['reports']) != set(stages):
        raise ValueError('Report stage coverage differs from manifest')
    if evidence['cell'] != cell or evidence['alignment_performed'] is not False:
        raise ValueError('Cell identity/alignment policy mismatch')
    result = dict(cell=cell, stages={}, violations=[], open_claims=[])
    production = cell in ('production_calibration_csv', 'production_mask_control', 'production_mask_cold')
    global_accuracy = [globals_[key] for key in ('X', 'Y', 'Z', 'Yaw', 'Pitch', 'Roll')]

    def require(condition, stage, filename, claim):
        if not condition:
            result['violations'].append(dict(stage=stage, filename=filename, claim=claim))

    for stage in stages:
        rows = evidence['reports'][stage]
        indexed = {identity(row['filename']): row for row in rows}
        if len(indexed) != len(rows) or set(indexed) != set(expected):
            raise ValueError(f'{stage}: duplicate/missing/unexpected filenames')
        output = dict(rows=[], groups={}, production_requirements={})
        native = cell.startswith('native_xmp') or stage == 'explicit_xmp_reimport'
        csv_stage = stage in ('csv_first', 'csv_second', 'groups_then_csv_g1', 'rotation_setter')
        for key, sentinel in expected.items():
            row = indexed[key]
            flags = {field: flag(row[field]) for field in FLAGS}
            values = {name: [number(row[field]) for field in fields]
                      for name, fields in (('position', POSITION), ('orientation', ORIENTATION), ('accuracy', ACCURACY))}
            parsed_groups = {field: group(row[field]) for field in GROUPS}
            focal = number(row['inputF'])
            # Unknown numeric calibration enums are recorded, never silently mapped.
            enum = str(row['inputCalibrationPriorType'])
            if not enum.strip() or enum == '(null)' or not str(row['inputLensModel']).strip():
                raise ValueError(f'{stage}: missing calibration/lens evidence')
            candidates = {
                'position': {'CSV_FIRST': sentinel['csv_position'],
                             'CSV_SECOND': [x + 100 for x in sentinel['csv_position']],
                             'XMP': sentinel['xmp_position'], 'NO_PRIOR_DEFAULT': [0, 0, 0]},
                'orientation': {'CSV_FIRST': sentinel['csv_ypr'],
                                'CSV_SECOND': [x + 1 for x in sentinel['csv_ypr']],
                                'CLI_SETTER': sentinel['edit_ypr'], 'NO_PRIOR_DEFAULT': [180, 0, 180]},
                'accuracy': {'CSV': sentinel['csv_accuracy'], 'GLOBAL': global_accuracy,
                             'CLI_SETTER': sentinel['edit_accuracy']},
            }
            sources = {name: [source for source, target in options.items()
                              if matches(values[name], target, name == 'orientation')]
                       for name, options in candidates.items()}
            measurement = dict(filename=sentinel['image'], family=sentinel['family'], flags=flags,
                               values=values, matching_sentinels=sources, groups=parsed_groups,
                               raw_groups={field: row[field] for field in GROUPS}, focal=focal,
                               focal_matches=[label for label, value in (('CSV', sentinel['csv_focal']),
                                               ('XMP', sentinel['xmp_focal']), ('NO_PRIOR_DEFAULT', 0))
                                              if matches([focal], [value])],
                               calibration_prior=dict(raw=enum, interpretation=enum if enum in
                                   ('Unknown', 'Approximate', 'Fixed') else 'UNDOCUMENTED_ENUM'),
                               lens_model=row['inputLensModel'], coordinate_system=row['inputCS'],
                               reported_opk=[number(row[field]) for field in ('inputOmega', 'inputPhi', 'inputKappa')],
                               xmp_rotation_sentinel=sentinel.get('xmp_rotation'),
                               focal_to_xmp_sentinel_ratio=focal / sentinel['xmp_focal'])
            output['rows'].append(measurement)
            name = sentinel['image']
            baseline = stage == 'added' and not native
            if baseline:
                for field in ('inputIsPositionPrior', 'inputIsOrientationPrior', 'inputIsPriorAccuracy', 'inputIsOpkRotationPrior'):
                    require(not flags[field], stage, name, f'negative control {field}=false')
                require('GLOBAL' in sources['accuracy'], stage, name, 'negative control reports global accuracies')
                if cell != 'legacy_xmp_only' and not production:
                    require(all(value is None for value in parsed_groups.values()), stage, name, 'negative control groups unassigned')
            if csv_stage:
                target = 'CSV_SECOND' if stage == 'csv_second' else 'CSV_FIRST'
                for field in ('inputIsPositionPrior', 'inputIsOrientationPrior'):
                    require(flags[field], stage, name, f'{field}=true after CSV')
                require(not flags['inputIsLatLong'] and row['inputCS'] not in ('', '(null)'), stage, name, 'Cartesian coordinate system present')
                # Native XMP/CSV conflicts are measured precedence experiments,
                # not an assumed overwrite contract. Production delivery is below.
                if not cell.startswith('native_xmp_csv'):
                    require(target in sources['position'], stage, name, 'CSV position delivered')
                    require(('CLI_SETTER' if stage == 'rotation_setter' else target) in sources['orientation'], stage, name, 'YPR sentinel delivered')
                    require(('XMP' if production else 'CSV') in measurement['focal_matches'], stage, name, 'Authoritative focal delivered')
                require(bool(sources['accuracy']), stage, name, 'accuracy matches a complete known sentinel vector')
                if stage == 'rotation_setter':
                    require('CLI_SETTER' in sources['accuracy'], stage, name, 'CLI accuracy setters delivered')
            if stage == 'added' and (native or cell == 'legacy_xmp_only'):
                require('XMP' in measurement['focal_matches'], stage, name, 'XMP focal sentinel delivered without rescaling')
                require(str(row['inputLensModel']).lower() == 'division', stage, name, 'XMP division lens model delivered')
            if native and stage == 'added':
                require('XMP' in sources['position'], stage, name, 'native XMP numeric position imported')
                if not flags['inputIsPositionPrior'] or not (flags['inputIsOrientationPrior'] or flags['inputIsOpkRotationPrior']):
                    result['open_claims'].append('Native XMP numeric pose imported but active absolute prior flags not established')
                result['open_claims'].append('XMP matrix-to-reported-angle convention not established')
            if production:
                require('XMP' in measurement['focal_matches'], stage, name, 'Production calibration focal delivered')
                require(str(row['inputLensModel']).lower() == 'division', stage, name, 'Production division model delivered')
                require(parsed_groups['calibrationGroup'] == group(sentinel['xmp_calibration_group']), stage, name, 'Exact production calibration group')
                require(parsed_groups['distortionGroup'] == group(sentinel['xmp_distortion_group']), stage, name, 'Exact production lens group')
                if csv_stage:
                    require(flags['inputIsPriorAccuracy'] and 'CSV' in sources['accuracy'], stage, name, 'Production CSV accuracies active')
            if stage in ('cli_groups', 'edit_groups'):
                prefix = 'cli' if stage == 'cli_groups' else 'edit'
                require(parsed_groups['calibrationGroup'] == sentinel[prefix + '_calibration_group'], stage, name, 'explicit calibration group setter delivered')
                require(parsed_groups['distortionGroup'] == sentinel[prefix + '_distortion_group'], stage, name, 'explicit lens group setter delivered')
        for field in GROUPS:
            actual = [row['groups'][field] for row in output['rows']]
            output['groups'][field] = dict(values=actual, partition=partition(actual),
                all_assigned=all(value is not None for value in actual),
                physical_cameras_separate=all(value is not None for value in actual) and len(set(actual)) == len(expected))
            if (native or cell == 'legacy_xmp_only') and stage == 'added':
                require(output['groups'][field]['physical_cameras_separate'], stage, None,
                        f'XMP {field} preserves four physical camera groups')
        target = 'CSV_SECOND' if stage == 'csv_second' else 'CSV_FIRST'
        output['reported_pose_flags_active'] = all(row['flags']['inputIsPositionPrior'] and
            (row['flags']['inputIsOrientationPrior'] or row['flags']['inputIsOpkRotationPrior']) for row in output['rows'])
        if csv_stage:
            focal_authority = 'XMP' if cell.startswith('native_xmp_csv') or production else 'CSV'
            output['focal_authority'] = focal_authority
            output['production_requirements'] = dict(
                position_delivered=all(target in row['matching_sentinels']['position'] and row['flags']['inputIsPositionPrior'] for row in output['rows']),
                orientation_delivered=all(('CLI_SETTER' if stage == 'rotation_setter' else target) in row['matching_sentinels']['orientation'] and row['flags']['inputIsOrientationPrior'] for row in output['rows']),
                per_camera_accuracy_delivered=all(('CLI_SETTER' if stage == 'rotation_setter' else 'CSV') in row['matching_sentinels']['accuracy'] and row['flags']['inputIsPriorAccuracy'] for row in output['rows']),
                focal_delivered=all(focal_authority in row['focal_matches'] for row in output['rows']),
                calibration_separate=output['groups']['calibrationGroup']['physical_cameras_separate'],
                lens_separate=output['groups']['distortionGroup']['physical_cameras_separate'])
        result['stages'][stage] = output
    result['open_claims'] = sorted(set(result['open_claims']))
    result['control_contract'] = 'MISMATCH' if result['violations'] else 'MATCH'
    final_requirements = result['stages'][stages[-1]]['production_requirements']
    result['production_delivery'] = ('MATCH' if all(final_requirements.values()) else 'MISMATCH') if final_requirements else 'NOT_TESTED'
    return result


def compare(manifest, expected_sha256, cells=None):
    manifest = Path(manifest)
    if sha256(manifest) != expected_sha256:
        raise ValueError('Manifest hash mismatch')
    plan = load(manifest)
    if plan['alignment_allowed'] is not False:
        raise ValueError('Alignment policy mismatch')
    results = []
    for cell in cells or plan['cells']:
        if cell not in plan['cells']:
            raise ValueError(f'Unknown cell: {cell}')
        detail = plan['cell_details'][cell]
        path = Path(plan['root']) / cell / 'readback.json'
        try:
            for relative, digest in plan.get('artifact_hashes', {}).items():
                artifact = Path(plan['root']) / relative
                if not artifact.resolve().is_relative_to(Path(plan['root']).resolve()):
                    raise ValueError('Artifact escapes probe root')
                if artifact.parent == Path(plan['root']) or artifact.is_relative_to(Path(plan['root']) / cell):
                    if sha256(artifact) != digest:
                        raise ValueError(f'Pinned probe input changed: {relative}')
            evidence = load(path)
            hashes = {str(path): sha256(path)}
            for report in detail['reports']:
                raw = _raw_report(report['path'])
                # Ignore row order, never silently trust JSON detached from raw output.
                normalize = lambda rows: {identity(row['filename']): {**row, 'filename': identity(row['filename'])} for row in rows}
                if len(raw) != len(evidence['reports'][report['stage']]) or normalize(raw) != normalize(evidence['reports'][report['stage']]):
                    raise ValueError('Readback JSON differs from raw report')
                hashes[report['path']] = sha256(report['path'])
            if cell == 'report_control':
                builtin = Path(plan['root']) / cell / 'builtin_overview.html'
                if not builtin.is_file() or builtin.stat().st_size == 0:
                    raise ValueError('Missing shipped Overview positive control')
                hashes[str(builtin)] = sha256(builtin)
            item = compare_cell(detail, evidence, cell, dict(zip(('X', 'Y', 'Z', 'Yaw', 'Pitch', 'Roll'), (17, 19, 23, 29, 31, 37))))
            if cell in ('production_calibration_csv', 'production_mask_control', 'production_mask_cold'):
                from modules.prior_census import assert_input_priors
                contract = detail['production_contract']
                expected_path = contract['RS_INPUT_PRIOR_MANIFEST']
                if sha256(expected_path) != contract['RS_INPUT_PRIOR_SHA256']:
                    raise ValueError('Production census manifest hash mismatch')
                item['input_census'] = assert_input_priors(load(expected_path), contract['RS_INPUT_PRIOR_REPORT'])
                for key in ('RS_INPUT_PRIOR_MANIFEST', 'RS_INPUT_PRIOR_REPORT'):
                    hashes[contract[key]] = sha256(contract[key])
                if cell in ('production_mask_control', 'production_mask_cold'):
                    from testing.rs_prior_import_probe import verify_mask_exports
                    item['mask_evidence'] = verify_mask_exports(detail)
            item.update(evidence_status='COMPLETE', evidence_sha256=hashes)
        except FileNotFoundError as exc:
            item = dict(cell=cell, evidence_status='PENDING', error=str(exc))
        except (ValueError, KeyError, TypeError, OSError) as exc:
            item = dict(cell=cell, evidence_status='INVALID', error=str(exc))
        results.append(item)
    okay = all(row['evidence_status'] == 'COMPLETE' and row.get('control_contract') == 'MATCH' for row in results)
    return dict(schema_version=1, manifest=str(manifest), manifest_sha256=expected_sha256,
                absolute_tolerance=TOLERANCE, cells=results,
                comparison_status='COMPLETE_MATCH' if okay else 'BLOCKED',
                scientific_run_authorized=False,
                open_claims=['Physical camera/world axes and UTM grid-heading convention remain unverified'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--expected-plan-sha256', required=True)
    parser.add_argument('--cell', action='append')
    args = parser.parse_args()
    try:
        result = compare(args.manifest, args.expected_plan_sha256, args.cell)
    except (ValueError, KeyError, TypeError, OSError) as exc:
        result = dict(comparison_status='BLOCKED', scientific_run_authorized=False, error=str(exc))
    print(json.dumps(result, indent=2, allow_nan=False))
    return 0 if result['comparison_status'] == 'COMPLETE_MATCH' else 2


if __name__ == '__main__':
    raise SystemExit(main())
