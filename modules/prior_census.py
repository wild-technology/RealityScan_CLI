"""Fail-closed calibration evidence checks for exported components.

A group count alone cannot prove prior delivery. Evidence must cover every
registered image and keep distinct optical groups separate. Solved focal
lengths are not required to equal manufacturer priors.
"""
from __future__ import annotations

import collections
import csv
import logging
import hashlib
import json
import math
import ntpath
import os
import re
from pathlib import Path
import xml.etree.ElementTree as ET

from . import camera_registry, component_manifest
from .image_exts import ALL_IMAGE_EXTS

logger = logging.getLogger(__name__)

UNGROUPED = -1
MAX_UNGROUPED_FRACTION = 0.10
MAX_DISTINCT_FOCAL_FRACTION = 0.25
MIN_CAMERAS_FOR_FOCAL_TEST = 30
_XCR_NAMESPACES = (
    'http://www.capturingreality.com/ns/xcr/1.1#',
    'http://www.capturingreality.com/ns/xcr/1.0/',
)


class PriorsNotApplied(RuntimeError):
    """Calibration evidence is incomplete, invalid, or contradicts the rig."""


INPUT_FIELDS = ('inputIsPositionPrior', 'inputIsOrientationPrior', 'inputIsPriorAccuracy',
                'inputIsLatLong', 'inputCS', 'inputX', 'inputY', 'inputZ',
                'inputYaw', 'inputPitch', 'inputRoll', 'inputAccuracyX', 'inputAccuracyY',
                'inputAccuracyZ', 'inputAccuracyYaw', 'inputAccuracyPitch', 'inputAccuracyRoll',
                'calibrationGroup', 'distortionGroup', 'inputF', 'inputLensModel',
                'inputCalibrationPriorType')
INPUT_REPORT_TEMPLATE = '''$Using("RealityScan.Report.IteratorsFunctionSet")
$Using("RealityScan.Report.SfmExportFunctionSet")
<!doctype html><html><body><pre>
INPUT_PRIORS=1
$IterateImages(
IMAGE|$(inputIndex)|$(inputImagePath)|$(inputImageName)|$(inputImageExt)|$(inputIsAligned)
$ExportImagePriors(inputIndex,
PRIOR|$(inputIndex)|''' + '|'.join('$(' + field + ')' for field in INPUT_FIELDS) + '''
)
)
END_INPUT_PRIORS
</pre></body></html>
'''


def _digest(path):
    with open(path, 'rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _full_key(path):
    return ntpath.normcase(ntpath.normpath(str(path)))


def _finite(value):
    if isinstance(value, bool) or value is None or str(value).strip() == '':
        raise PriorsNotApplied('Missing numeric prior measurement')
    try:
        value = float(value)
    except (TypeError, ValueError) as exc:
        raise PriorsNotApplied('Invalid numeric prior measurement') from exc
    if not math.isfinite(value):
        raise PriorsNotApplied('Nonfinite prior measurement')
    return value


def _boolean(value):
    value = str(value).lower()
    if value not in ('true', 'false', '1', '0'):
        raise PriorsNotApplied(f'Missing/invalid prior flag: {value!r}')
    return value in ('true', '1')


def build_input_prior_manifest(image_paths, flight_log, params_path):
    """Read-only contract for a fresh calibration-XMP + single-CSV scene.

    Call with the exact selected geometry images, never a source-wide inventory.
    Existing solved/export/continuation sidecars are refused here, not rewritten.
    """
    from .image_exts import is_geometry_image
    if not flight_log or not params_path:
        raise PriorsNotApplied('Fresh alignment requires a CSV flight log and explicit import parameters')
    parameters = ET.parse(params_path).getroot()
    entries = {}
    for entry in parameters.findall('entry'):
        key = entry.get('key')
        if key in entries:
            raise PriorsNotApplied(f'Duplicate flight-log parameter: {key}')
        entries[key] = entry.get('value')
    if entries.get('ifKGrp') != '0':
        raise PriorsNotApplied('Native calibration lane requires ifKGrp=0; automatic grouping collapses cameras')
    crs = entries.get('CoordinateSystemFlightLogType')
    if not crs or not (crs.startswith('epsg:') or crs == 'local:1 - Euclidean'):
        raise PriorsNotApplied('Explicit supported flight-log coordinate system required')
    images, basenames, hashes = {}, {}, set()
    for raw in image_paths:
        path = Path(raw).resolve()
        if not is_geometry_image(path) or not path.is_file() or path.stat().st_size == 0:
            raise PriorsNotApplied(f'Not a nonempty geometry image: {path}')
        key = _full_key(path)
        if key in images:
            raise PriorsNotApplied(f'Duplicate image path: {path}')
        camera = camera_registry.identify(path.name)
        if camera is None:
            raise PriorsNotApplied(f'Unknown camera: {path}')
        image_hash = _digest(path)
        if image_hash in hashes:
            raise PriorsNotApplied(f'Duplicate image content: {path}')
        hashes.add(image_hash)
        sidecar = path.with_suffix('.xmp')
        try:
            camera_registry.validate_calibration_xmp(sidecar.read_text(encoding='utf-8-sig'), camera)
        except (OSError, UnicodeError, ValueError, ET.ParseError) as exc:
            raise PriorsNotApplied(f'Invalid/missing native calibration sidecar {sidecar}: {exc}') from exc
        images[key] = dict(filename=str(path), image_sha256=image_hash, sidecar=str(sidecar),
                           sidecar_sha256=_digest(sidecar), camera=camera.key,
                           family=camera_registry.family(path.name), focal=camera.focal_length_35mm,
                           calibration_group=int(camera.calibration_group),
                           distortion_group=int(camera.lens_distortion_group), lens=camera.distortion_model)
        basenames.setdefault(path.name.casefold(), []).append(key)
    if not images:
        raise PriorsNotApplied('Empty input-prior image selection')
    rows = {}
    with open(flight_log, encoding='utf-8-sig', newline='') as stream:
        reader = csv.reader(stream, delimiter=';')
        header = next(reader, [])
        if len(header) not in (13, 14) or header[0].casefold() not in ('filename', 'name', 'image'):
            raise PriorsNotApplied('Expected the ordered 13/14-column pose-and-accuracy CSV')
        aliases = ({'x', 'xeast'}, {'y', 'ynorth'}, {'alt', 'altitude', 'z'},
                   {'xaccuracy'}, {'yaccuracy'}, {'altaccuracy', 'altitudeaccuracy', 'zaccuracy'},
                   {'yaw'}, {'pitch'}, {'roll'}, {'yawaccuracy'}, {'pitchaccuracy'}, {'rollaccuracy'})
        if any(re.sub('[^a-z]', '', name.casefold()) not in allowed
               for name, allowed in zip(header[1:13], aliases)):
            raise PriorsNotApplied('CSV header order does not match pose/accuracy import columns')
        for row in reader:
            if not row:
                continue
            if len(row) != len(header):
                raise PriorsNotApplied('Ragged input-prior CSV row')
            name = row[0].replace('\\', '/')
            direct = _full_key(Path(name).resolve())
            relative = _full_key((Path(flight_log).parent / name).resolve())
            candidates = [key for key in (direct, relative) if key in images]
            if not candidates:
                candidates = basenames.get(ntpath.basename(row[0]).casefold(), []) if '/' not in name else []
            if len(set(candidates)) != 1:
                raise PriorsNotApplied(f'CSV image missing/ambiguous/outside selection: {row[0]}')
            key = candidates[0]
            if key in rows:
                raise PriorsNotApplied(f'Duplicate CSV image: {row[0]}')
            values = [_finite(value) for value in row[1:13]]
            accuracy = values[3:6] + values[9:12]
            if any(value <= 0 for value in accuracy):
                raise PriorsNotApplied('All six prior accuracies must be positive')
            rows[key] = dict(position=values[:3], orientation=values[6:9], accuracy=accuracy)
    if set(rows) != set(images):
        raise PriorsNotApplied('CSV does not cover the exact geometry image selection')
    for key, row in rows.items():
        images[key].update(row)
    return dict(schema_version=1, lane='native_calibration_csv_pose_v1',
                images=[images[key] for key in sorted(images)], coordinate_system=crs,
                flight_log=str(Path(flight_log).resolve()), flight_log_sha256=_digest(flight_log),
                flight_log_params=str(Path(params_path).resolve()), params_sha256=_digest(params_path),
                effective_project_priors=camera_registry.effective_project_priors(),
                report_template_sha256=hashlib.sha256(INPUT_REPORT_TEMPLATE.encode('utf-8')).hexdigest(),
                physical_axis_verified=False)


def write_input_prior_contract(manifest, destination):
    """Create a NEW owned contract directory; never alter image/sidecar files."""
    root = Path(destination)
    root.mkdir(parents=True, exist_ok=False)
    path, template = root / 'expected.json', root / 'input_priors.html'
    with path.open('x', encoding='utf-8') as stream:
        json.dump(manifest, stream, indent=2, allow_nan=False)
    with template.open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(INPUT_REPORT_TEMPLATE)
    return dict(RS_INPUT_PRIOR_MANIFEST=str(path.resolve()), RS_INPUT_PRIOR_SHA256=_digest(path),
                RS_INPUT_PRIOR_TEMPLATE=str(template.resolve()),
                RS_INPUT_PRIOR_REPORT=str((root / 'readback.html').resolve()),
                RS_INPUT_PRIOR_RESULT=str((root / 'census.json').resolve()))


def assert_input_priors(manifest, report_path, *, verify_inputs=True):
    """Positive pre-alignment census; failure raises and must prevent -align."""
    if manifest.get('schema_version') != 1 or manifest.get('lane') != 'native_calibration_csv_pose_v1':
        raise PriorsNotApplied('Unsupported input-prior contract')
    expected = {_full_key(row['filename']): row for row in manifest['images']}
    if not expected or len(expected) != len(manifest['images']):
        raise PriorsNotApplied('Empty/duplicate input-prior identities')
    if verify_inputs:
        for path, digest in ((manifest['flight_log'], manifest['flight_log_sha256']),
                             (manifest['flight_log_params'], manifest['params_sha256'])):
            if _digest(path) != digest:
                raise PriorsNotApplied(f'Prior input changed: {path}')
        for row in expected.values():
            if _digest(row['filename']) != row['image_sha256'] or _digest(row['sidecar']) != row['sidecar_sha256']:
                raise PriorsNotApplied(f'Image/calibration input changed: {row["filename"]}')
    text = Path(report_path).read_text(encoding='utf-8-sig')
    if 'INPUT_PRIORS=1' not in text or 'END_INPUT_PRIORS' not in text or '$(' in text:
        raise PriorsNotApplied('Incomplete/unexpanded input-prior report')
    images, priors = {}, {}
    for line in text.splitlines():
        fields = line.strip().split('|')
        if fields[0] == 'IMAGE':
            if len(fields) != 6 or fields[1] in images or _boolean(fields[-1]):
                raise PriorsNotApplied('Invalid/duplicate/already-aligned image row')
            extension = fields[4] if fields[4].startswith('.') else '.' + fields[4]
            images[fields[1]] = _full_key(ntpath.join(fields[2], fields[3] + extension))
        elif fields[0] == 'PRIOR':
            if len(fields) != len(INPUT_FIELDS) + 2 or fields[1] in priors:
                raise PriorsNotApplied('Invalid/duplicate input prior row')
            priors[fields[1]] = dict(zip(INPUT_FIELDS, fields[2:]))
    if len(images) != len(expected) or set(images.values()) != set(expected) or set(images) != set(priors):
        raise PriorsNotApplied('Input report does not cover the exact selected images')
    problems, evidence = [], []
    for index, key in images.items():
        actual, wanted = priors[index], expected[key]
        issues = []
        for field in INPUT_FIELDS[:3]:
            if not _boolean(actual[field]):
                issues.append(field + ' is false')
        if _boolean(actual['inputIsLatLong']) or actual['inputCS'] != manifest['coordinate_system']:
            issues.append('coordinate system differs from CSV contract')
        for name, fields in (('position', ('inputX', 'inputY', 'inputZ')),
                             ('orientation', ('inputYaw', 'inputPitch', 'inputRoll')),
                             ('accuracy', INPUT_FIELDS[11:17])):
            measured = [_finite(actual[field]) for field in fields]
            errors = [abs((a - b + 180) % 360 - 180 if name == 'orientation' else a - b)
                      for a, b in zip(measured, wanted[name])]
            if any(error > 1e-5 for error in errors):
                issues.append(name + ' differs from CSV')
        for field, expected_field in (('calibrationGroup', 'calibration_group'), ('distortionGroup', 'distortion_group')):
            value = _finite(actual[field])
            if value in (-1, 4294967295) or value != wanted[expected_field]:
                issues.append(field + ' is unset/wrong')
        if abs(_finite(actual['inputF']) - wanted['focal']) > 1e-5:
            issues.append('focal differs from native calibration')
        if actual['inputLensModel'].lower() != wanted['lens'].lower():
            issues.append('lens model differs from native calibration')
        if not actual['inputCalibrationPriorType'].strip():
            issues.append('calibration prior type readback missing')
        evidence.append(dict(filename=wanted['filename'], measured=actual, issues=issues))
        problems.extend(f'{wanted["filename"]}: {issue}' for issue in issues)
    if problems:
        raise PriorsNotApplied('Input priors NOT applied: ' + '; '.join(problems))
    return dict(schema_version=1, verdict='VERIFIED_INPUT_PRIORS', cameras=len(expected),
                rows=evidence, report_sha256=_digest(report_path), physical_axis_verified=False)


def input_census_main(argv=None):
    """Canonical batch helper. All exceptions yield a durable failure result."""
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--input-manifest', required=True)
    parser.add_argument('--expected-sha256', required=True)
    parser.add_argument('--input-report', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args(argv)
    try:
        if _digest(args.input_manifest) != args.expected_sha256:
            raise PriorsNotApplied('Input-prior manifest hash mismatch')
        with open(args.input_manifest, encoding='utf-8') as stream:
            manifest = json.load(stream)
        result = assert_input_priors(manifest, args.input_report)
        result['expected_sha256'] = args.expected_sha256
        code = 0
    except Exception as exc:
        result = dict(verdict='INPUT_PRIORS_FAILED', error=f'{type(exc).__name__}: {exc}')
        code = 1
    # Exclusive creation preserves previous evidence; a failed write itself
    # raises/nonzero, so the caller cannot proceed to alignment.
    with open(args.output, 'x', encoding='utf-8') as stream:
        json.dump(result, stream, indent=2, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())
    print(json.dumps(result, allow_nan=False))
    return code


def _image_key(name: str) -> str:
    """The basename/stem identity the existing XMP harvest can represent."""
    if not isinstance(name, str) or not name.strip() or '\x00' in name:
        raise PriorsNotApplied('Invalid image identity in calibration evidence')
    base = name.replace('\\', '/').rsplit('/', 1)[-1]
    stem, ext = os.path.splitext(base)
    key = stem if ext.lower() in ALL_IMAGE_EXTS or ext.lower() == '.xmp' else base
    if not key or key in ('.', '..'):
        raise PriorsNotApplied(f'Invalid image identity: {name!r}')
    return key.casefold()


def _read_xmp(path: str) -> dict:
    record = dict(path=path, group=None, distortion_group=None, focal=None,
                  pose=False, unreadable=False, error=None)
    try:
        with open(path, encoding='utf-8-sig') as fh:
            text = fh.read()
    except (OSError, UnicodeError) as exc:
        record.update(unreadable=True, error=str(exc))
        return record
    try:
        if re.search(r'<!\s*(DOCTYPE|ENTITY)\b', text, re.IGNORECASE):
            raise ValueError('DTD/entity declarations are not pose evidence')
        # Legacy diagnostic callers supply RDF fragments with implicit prefixes.
        # Binding them on a wrapper preserves explicit document namespaces.
        text = re.sub(r'^\s*<\?xml\b.*?\?>', '', text, count=1, flags=re.DOTALL)
        root = ET.fromstring(
            '<evidence xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" '
            f'xmlns:xcr="{_XCR_NAMESPACES[0]}">{text}</evidence>')

        def value(name):
            tags = {f'{{{ns}}}{name}' for ns in _XCR_NAMESPACES}
            values = []
            for node in root.iter():
                values.extend(v.strip() for k, v in node.attrib.items() if k in tags)
                if node.tag in tags:
                    values.append((node.text or '').strip())
            if len(values) > 1:
                raise ValueError(f'Duplicate {name} properties')
            return values[0] if values else None

        for field, prop in (('group', 'CalibrationGroup'),
                            ('distortion_group', 'DistortionGroup')):
            raw = value(prop)
            if raw is not None:
                if not re.fullmatch(r'-?\d+', raw) or int(raw) < UNGROUPED:
                    raise ValueError(f'Invalid {prop}: {raw!r}')
                record[field] = int(raw)
        raw = value('FocalLength35mm')
        if raw is not None:
            focal = float(raw)
            if not math.isfinite(focal) or focal <= 0:
                raise ValueError('FocalLength35mm must be finite and positive')
            record['focal'] = focal
        raw = value('Position')
        if raw is not None:
            position = [float(v) for v in raw.split()]
            if len(position) != 3 or not all(math.isfinite(v) for v in position):
                raise ValueError('Position must contain three finite coordinates')
            record['pose'] = True
    except (ET.ParseError, ValueError) as exc:
        record['error'] = str(exc)
    return record


def _read_harvest(harvest_dir: str) -> dict[str, dict]:
    records = {}
    try:
        with os.scandir(harvest_dir) as entries:
            paths = sorted(e.path for e in entries if e.name.lower().endswith('.xmp'))
    except FileNotFoundError:
        return records
    except OSError as exc:
        raise PriorsNotApplied(f'Cannot read harvest {harvest_dir}: {exc}') from exc
    for path in paths:
        key = _image_key(path)
        if key in records:
            raise PriorsNotApplied(f'Ambiguous XMP identity {key!r} in {harvest_dir}')
        records[key] = _read_xmp(path)
    return records


def _summarize(harvest_dir: str, records: dict[str, dict]) -> dict:
    groups = collections.Counter(r['group'] if r['group'] is not None else 'absent'
                                 for r in records.values())
    dgroups = collections.Counter(
        r['distortion_group'] if r['distortion_group'] is not None else 'absent'
        for r in records.values())
    focals = [r['focal'] for r in records.values() if r['focal'] is not None]
    cameras = len(records)  # Unreadable files remain in the denominator.
    distinct = len({round(f, 2) for f in focals})
    return {
        'harvest_dir': harvest_dir, 'cameras': cameras,
        'unreadable': sum(r['unreadable'] for r in records.values()),
        'invalid_files': [r['path'] for r in records.values() if r['error']],
        'missing_poses': sum(not r['pose'] for r in records.values()),
        'missing_focals': cameras - len(focals),
        'groups': dict(groups), 'distortion_groups': dict(dgroups),
        'ungrouped': groups[UNGROUPED],
        'ungrouped_fraction': groups[UNGROUPED] / cameras if cameras else 0.0,
        'distinct_focals': distinct,
        'distinct_focal_fraction': distinct / cameras if cameras else 0.0,
        'focal_min': min(focals) if focals else None,
        'focal_max': max(focals) if focals else None,
    }


def census(harvest_dir: str) -> dict:
    """Report all XMPs, including unreadable files and missing fields."""
    return _summarize(harvest_dir, _read_harvest(harvest_dir))


def _assert_evidence(stats: dict, context: str,
                     expected_groups: int | None = None) -> None:
    if not stats['cameras']:
        raise PriorsNotApplied(
            f'{context}: no pose XMPs under {stats["harvest_dir"]}; calibration '
            'delivery CANNOT BE DETERMINED. CSV identity alone has no group evidence.')
    problems = []
    if stats['invalid_files']:
        problems.append(f'{len(stats["invalid_files"])} unreadable or invalid XMP(s): '
                        f'{stats["invalid_files"][:3]}')
    if stats['missing_poses'] or stats['missing_focals']:
        problems.append(f'missing pose/focal evidence on '
                        f'{stats["missing_poses"]}/{stats["missing_focals"]} image(s)')
    for field, label in (('groups', 'CalibrationGroup'),
                         ('distortion_groups', 'DistortionGroup')):
        groups = stats[field]
        if groups.get('absent', 0):
            problems.append(f'{label} absent on {groups["absent"]} image(s)')
        if groups.get(UNGROUPED, 0) / stats['cameras'] > MAX_UNGROUPED_FRACTION:
            problems.append(f'{label}=-1 exceeds {MAX_UNGROUPED_FRACTION:.0%}; '
                            'self-calibrated instead of grouped')
        if expected_groups is not None:
            seen = {g for g in groups if isinstance(g, int) and g >= 0}
            if len(seen) < expected_groups:
                problems.append(f'{label}: {len(seen)} groups for {expected_groups} '
                                'expected; cameras merged into one group or missing')
    if (stats['cameras'] >= MIN_CAMERAS_FOR_FOCAL_TEST
            and stats['distinct_focal_fraction'] > MAX_DISTINCT_FOCAL_FRACTION):
        problems.append(f'{stats["distinct_focals"]} distinct solved focal lengths '
                        f'across {stats["cameras"]} cameras: per-image self-calibration')
    if problems:
        raise PriorsNotApplied(f'{context}: calibration priors not verified: '
                              + '; '.join(problems))


def assert_priors_landed(harvest_dir: str, *, context: str = '',
                         expected_groups: int | None = None) -> dict:
    """Check one harvest; production callers use assert_component_priors.

    Standalone diagnostics retain the historical ungrouped tolerance. Component
    checks additionally require complete membership of each optical group.
    """
    stats = census(harvest_dir)
    _assert_evidence(stats, context or harvest_dir, expected_groups)
    return stats


def _assert_rig(records: dict[str, dict], images: dict[str, str], context: str) -> None:
    # Export IDs may be renumbered. Require a bijection to optical groups,
    # independently for calibration and lens groups, within each component.
    for observed_field, registry_field in (('group', 'calibration_group'),
                                           ('distortion_group', 'lens_distortion_group')):
        expected_to_seen = {}
        seen_to_expected = {}
        for key, image in images.items():
            camera = camera_registry.identify(image.replace('\\', '/').rsplit('/', 1)[-1])
            if camera is None:
                raise PriorsNotApplied(f'{context}: unknown camera family for {image!r}')
            expected = str(getattr(camera, registry_field))
            seen = records[key][observed_field]
            if seen is None or seen < 0:
                raise PriorsNotApplied(f'{context}: {image!r} has no {observed_field}')
            if expected in expected_to_seen and expected_to_seen[expected] != seen:
                raise PriorsNotApplied(f'{context}: optical {registry_field} {expected} '
                                      f'is split across {observed_field} IDs')
            if seen in seen_to_expected and seen_to_expected[seen] != expected:
                raise PriorsNotApplied(f'{context}: distinct camera families share '
                                      f'{observed_field} {seen}')
            expected_to_seen[expected] = seen
            seen_to_expected[seen] = expected


def assert_component_priors(output_folder: str, component_paths: list[str],
                            manifest_paths: list[str], *, context: str = '') -> dict:
    """Check every export, manifest and component-specific pose/group evidence.

    XMP successive-difference captures must include the terminal harvest. CSV
    manifests may use a shared r0 pose harvest if one was supplied; ordinary
    registration CSVs alone cannot prove calibration/lens delivery. Read-only.
    """
    where = context or output_folder

    def canonical(path):
        return os.path.normcase(os.path.abspath(path))

    components = {canonical(p): p for p in component_paths}
    if not components or len(components) != len(component_paths):
        raise PriorsNotApplied(f'{where}: missing or duplicate exported components')
    if len(manifest_paths) != len(components):
        raise PriorsNotApplied(f'{where}: manifest coverage does not match exported components')
    manifests = {}
    all_images = {}
    for path in manifest_paths:
        manifest = component_manifest.load_manifest(path)
        component_path = manifest.get('rsalign')
        if not isinstance(component_path, str) or canonical(component_path) not in components:
            raise PriorsNotApplied(f'{where}: manifest {path} names an unexpected component')
        key = canonical(component_path)
        if key in manifests or canonical(path) != canonical(
                component_manifest.manifest_path_for(components[key])):
            raise PriorsNotApplied(f'{where}: duplicate or misplaced manifest {path}')
        name = os.path.splitext(os.path.basename(components[key]))[0]
        if manifest.get('component') != name or os.path.getsize(components[key]) <= 0:
            raise PriorsNotApplied(f'{where}: invalid component identity/file {name}')
        images = manifest.get('images')
        count = manifest.get('camera_count')
        if (not isinstance(images, list) or not images or type(count) is not int
                or count != len(images)):
            raise PriorsNotApplied(f'{where}: invalid camera count/membership for {name}')
        members = {_image_key(image): image for image in images}
        if len(members) != len(images) or all_images.keys() & members.keys():
            raise PriorsNotApplied(f'{where}: duplicate/ambiguous image stems in {name}')
        all_images.update(members)
        manifests[key] = (name, members)

    cache = {}

    def harvest(index):
        if index not in cache:
            cache[index] = _read_harvest(os.path.join(output_folder, f'identity_r{index}'))
        return cache[index]

    def coverage(records, expected, label):
        missing = expected.keys() - records.keys()
        extra = records.keys() - expected.keys()
        if missing or extra:
            raise PriorsNotApplied(f'{where}: {label} evidence coverage: '
                                  f'{len(missing)} missing, {len(extra)} unexpected '
                                  f'({sorted(missing)[:3]}, {sorted(extra)[:3]})')

    initial = harvest(0)
    initial_dir = os.path.join(output_folder, 'identity_r0')
    if not initial:
        _assert_evidence(_summarize(initial_dir, initial), where)
    coverage(initial, all_images, 'identity_r0')
    indexed = {}
    for name, members in manifests.values():
        match = re.search(r'_c(\d+)$', name)
        if match is None or int(match.group(1)) in indexed:
            raise PriorsNotApplied(f'{where}: invalid component ordinal {name!r}')
        indexed[int(match.group(1))] = (name, members)
    if set(indexed) != set(range(len(indexed))):
        raise PriorsNotApplied(f'{where}: missing component ordinal in exported set')
    results = {}
    remaining = dict(all_images)
    for index, (name, members) in sorted(indexed.items()):
        directory = os.path.join(output_folder, f'identity_r{index}')
        csv_path = os.path.join(output_folder, 'identity', name + '.csv')
        csv_membership = os.path.isfile(csv_path)
        if csv_membership:
            with open(csv_path, encoding='utf-8-sig', newline='') as fh:
                csv_keys = [_image_key(row[0].strip()) for row in csv.reader(fh, strict=True)
                            if row and not row[0].lstrip().startswith('#')]
            if len(csv_keys) != len(members) or set(csv_keys) != set(members):
                raise PriorsNotApplied(f'{where}: CSV membership disagrees with {name}')
        if os.path.isdir(directory):
            records = harvest(index)
            coverage(records, remaining, f'identity_r{index}')
        elif csv_membership:
            records, directory = initial, initial_dir
        else:
            raise PriorsNotApplied(f'{where}: missing component harvest {directory}')
        # Every remaining component appears in this harvest. Validate each
        # separately: neither another component nor a later export can conceal
        # an unreadable/malformed record or a bad optical group at this lap.
        for pending_index, (pending_name, pending_members) in sorted(indexed.items()):
            if pending_index < index:
                continue
            subset = {key: records[key] for key in pending_members}
            stats = _summarize(directory, subset)
            component_context = f'{where}, component {pending_name}'
            _assert_evidence(stats, component_context)
            _assert_rig(subset, pending_members, component_context)
            if pending_index == index:
                results[name] = stats
        for key in members:
            del remaining[key]
        if not csv_membership:
            next_dir = os.path.join(output_folder, f'identity_r{index + 1}')
            if not os.path.isdir(next_dir):
                raise PriorsNotApplied(f'{where}: missing terminal/next harvest {next_dir}')
            coverage(harvest(index + 1), remaining, f'identity_r{index + 1}')
        if index:
            cache.pop(index, None)  # Retain r0 and at most the next lap, not the whole run.
    logger.info('Verified calibration evidence for %s: %d components, %d cameras',
                where, len(results), len(all_images))
    return {'components': results, 'cameras': len(all_images)}


if __name__ == '__main__':
    raise SystemExit(input_census_main())
