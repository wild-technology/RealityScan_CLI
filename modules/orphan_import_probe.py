"""Automated, bounded orphan import experiment; no manual capture/pass JSON.

Commands (all paths absolute; run from repository):
  python -m modules.orphan_import_probe plan --project-root ROOT
    --selection-manifest SELECTION --policy POLICY --component A --component B
    --install-dir INSTALL --instance DEDICATED --run-name UNIQUE --reserve-gib N
  python -m modules.orphan_import_probe prepare [same arguments]
  python -m modules.orphan_import_probe record --manifest PRINTED_PATH
    --expected-sha256 PRINTED_HASH --execute
  python -m modules.orphan_import_probe verify --manifest PRINTED_PATH
    --expected-sha256 PRINTED_HASH

Only record launches, through RealityScanCLI. The reviewed manifest pins two
original component locations, approved selection/policy, and three deterministic
controls. The original-camera budget is explicit or derived as twice the
approved selection size. Production uses import/readback only; --import-only
selects that scope for standalone calls. No source XMP,
installation repair, runtime edits, or reuse of an occupied instance. Failed
attempts are retained; choose a fresh run-name. Plan/prepare do not launch RS.

Native readback: IterateImages/ExportImagePriors; ComponentInfo/ExportCameras;
exportMasks decoded pixels. GetProperty(aligFeaturesMode) is a HYPOTHESIS for
selected-input readback, tested by 0/2 controls with independent reselection.
If unobservable, report incomplete and stop before align. Exported masks prove
attachment/content, not the per-stage mask-use switch. Vertical datum remains
the approved declaration; EPSG and camera coordinates are read back. Unsupported
macros, image aliases, mask names or frames fail closed, never invent values.

Primary references: https://rshelp.capturingreality.com/en-US/appbasics/
reports_fav_{images,cameras,components,basic}.htm and allcommands.htm.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from contextvars import ContextVar
import copy
import csv
import hashlib
import html
import json
import logging
import math
import os
from pathlib import Path
import re
import shutil
import threading
from uuid import uuid4

import merge_zones as merge
from modules.component_manifest import load_manifest
from modules import camera_registry
from modules.source_inventory import file_hash as _file_hash, source_fingerprint as _source_fingerprint
from modules.realityscan_interface.realityscan_cli import RealityScanCLI, RunControl, assert_bat_safe
from modules.project_runtime import OwnershipUnconfirmed
from modules.prior_census import INPUT_FIELDS

# Use the production prior report fields, retaining the original diagnostic
# ordering and OPK controls used by the prior-import experiment.
PRIOR_FIELDS = tuple(k for k in INPUT_FIELDS if k not in ('inputLensModel', 'inputCalibrationPriorType')) + (
    'inputCalibrationPriorType', 'inputLensModel', 'inputIsOpkRotationPrior', 'inputOmega', 'inputPhi', 'inputKappa')


def write_text(path, text, crlf=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8', newline='\r\n' if crlf else '\n') as stream:
        stream.write(text.rstrip('\n') + '\n')

REPO = Path(merge.__file__).resolve().parent
SCRIPTS = REPO / 'modules/realityscan_interface/RS_CLI/Scripts'
_CANCELLED = ContextVar('orphan_probe_cancelled', default=None)
_PROGRESS = ContextVar('orphan_probe_progress', default=None)
_CONTROL = ContextVar('orphan_probe_control', default=None)
_ENVIRONMENT = ContextVar('orphan_probe_environment', default=None)
STAGES = ('before', 'prepared', 'aligned')
LIMITS = [
    'Mask export verifies attachment and pixel content only when approved masks are supplied; it does not verify feature exclusion or polarity.',
    'Vertical datum is owner-declared; no independent vertical-datum validation.',
    'Feature GetProperty readback is accepted only after independent 0/2 reselection controls.',
    'The tiny successful scene does not establish reconstruction quality on other imagery.',
    'Empty mask-export Configuration compatibility is probed, not assumed; supplied masks require pixel readback.',
    'inpMaskOpts=3 is explicitly dispatched; effective alignment/meshing exclusion remains unverified.',
]


@contextmanager
def execution_context(*, cancelled=None, progress=None, control=None, environment=None):
    """Per-call callbacks; never replace global hashing/executor functions."""
    def requested():
        return ((control is not None and control.cancellation_requested)
                or (cancelled is not None and cancelled()))
    cancel_token = _CANCELLED.set(requested)
    progress_token = _PROGRESS.set(progress)
    control_token = _CONTROL.set(control)
    environment_token = _ENVIRONMENT.set(dict(environment) if environment is not None else None)
    try:
        checkpoint()
        yield
    finally:
        _CANCELLED.reset(cancel_token)
        _PROGRESS.reset(progress_token)
        _CONTROL.reset(control_token)
        _ENVIRONMENT.reset(environment_token)


def checkpoint():
    control = _CONTROL.get()
    if control is not None and control.cancellation_requested:
        raise InterruptedError('Orphan import evidence cancelled by controller')
    callback = _CANCELLED.get()
    if callback is not None and callback():
        raise InterruptedError('Orphan import evidence cancelled; unpublished artifacts retained')


def file_hash(path):
    return _file_hash(Path(path), cancelled=_CANCELLED.get())


def source_fingerprint(path):
    return _source_fingerprint(path, cancelled=_CANCELLED.get())


def component_paths(root):
    """Census every export, including exports lacking a manifest (which refuse)."""
    checkpoint()
    paths = []
    for directory, dirs, files in os.walk(safe(root), followlinks=False):
        checkpoint()
        for name in dirs:
            if Path(directory, name).is_symlink() or Path(directory, name).is_junction():
                raise ValueError('Component census cannot traverse redirected directories')
        for name in files:
            if name.lower().endswith('.rsalign'):
                paths.append(safe(Path(directory, name)))
    return sorted(paths)


def component_census(project_root, components_root):
    project, root = safe(project_root), safe(components_root)
    if not root.is_relative_to(project / 'proc') or not root.is_dir():
        raise ValueError('Aligned component root must be an existing project-owned proc directory')
    components, members, dependencies, input_paths = [], [], [], []
    paths = component_paths(root)
    if len(paths) < 2:
        raise ValueError('alignment_required: at least two measured aligned components required')
    for path in paths:
        checkpoint()
        if not path.is_relative_to(root):
            raise ValueError('Redirected component export')
        item = load_manifest(str(path))
        if safe(item['rsalign']) != path:
            raise ValueError('Component was relocated from its original export location')
        ids = merge.measured_component_ids(item)
        if not ids or len(ids) != len(set(ids)):
            raise ValueError('Component membership empty or duplicated')
        registration = path.parent / 'identity' / (path.stem + '.csv')
        with registration.open(encoding='utf-8-sig', newline='') as stream:
            next(stream)
            image_paths = {}
            for row in csv.reader(stream):
                checkpoint()
                if not row or row[0].startswith('#'):
                    continue
                image = safe(row[0])
                if not image.is_relative_to(project / 'proc'):
                    raise ValueError('Component inputs must retain original project-owned paths')
                image_paths[merge._orphan_id(image)] = str(image)
        input_paths.append(image_paths)
        components.append(item)
        members.append(sorted(ids))
        dependencies.extend([path, Path(str(path) + '.manifest.json'),
                             path.parent / 'identity' / (path.stem + '.csv')])
    return dict(root=str(root), paths=list(map(str, paths)), components=components, input_paths=input_paths,
                members=members, registered=sorted(set().union(*map(set, members))),
                dependencies=[bound(p) for p in sorted(set(dependencies))])


def check_census(plan):
    if list(map(str, component_paths(plan['census']['root']))) != plan['census']['paths']:
        raise ValueError('Aligned component census changed; rebuild orphan evidence')
    check(plan['census']['dependencies'])


def choose_controls(spatial, context):
    """Choose importable controls deterministically without changing the global pool."""
    reasons = spatial['spatial_reasons']
    rejected = {}
    usable = []
    for identity, reason in sorted(reasons.items()):
        checkpoint()
        if not (reason.startswith('within_footprint_') or reason == 'between_footprints'):
            continue
        if camera_registry.identify(identity) is None:
            rejected[identity] = 'unknown_calibration'
            continue
        try:
            row = context['rows'][identity]
            if len(row) != 14 or not all(math.isfinite(float(value)) for value in row[1:]):
                raise ValueError('incomplete')
        except (KeyError, TypeError, ValueError):
            rejected[identity] = 'incomplete_or_nonfinite_priors'
            continue
        usable.append(identity)
    inside = next((n for n in usable if reasons[n].startswith('within_footprint_')), None)
    corridors = [n for n in usable if reasons[n] == 'between_footprints']
    corridor = next((n for n in corridors if n in context['masks']), next(iter(corridors), None))
    remote = next((n for n, r in sorted(reasons.items()) if r == 'outside_pair_support'), None)
    return [inside, corridor, remote], rejected


def bound(path):
    path = Path(path).resolve()
    return {'path': str(path), 'sha256': file_hash(path)}


def safe(path):
    path = Path(path)
    if not path.is_absolute():
        raise ValueError('Probe paths must be absolute')
    path = path.resolve()
    assert_bat_safe([str(path)], 'orphan probe')
    if not str(path).isascii() or any(c in str(path) for c in '|\r\n\t\''):
        raise ValueError('Unsupported probe path characters')
    return path


def check(records):
    for record in records:
        checkpoint()
        if bound(safe(record['path'])) != record:
            raise ValueError('Probe dependency/artifact changed: ' + record['path'])


def template(body, sets=('IteratorsFunctionSet', 'SfmExportFunctionSet', 'ComponentFunctionSet')):
    return '\n'.join('$Using("RealityScan.Report.' + name + '")' for name in sets) + (
        '\n<!doctype html><html><body><pre>\nORPHAN_NATIVE=1\n' + body + '\nEND_ORPHAN\n</pre></body></html>')


STATE_TEMPLATE = template('''$IterateImages(
IMAGE|$(inputIndex)|$(inputImagePath)|$(inputImageName)|$(inputImageExt)
$ExportImagePriors(inputIndex,
PRIOR|$(inputIndex)|''' + '|'.join('$(' + key + ')' for key in PRIOR_FIELDS) + '''
)
)
$IterateComponents(
$ComponentInfo("$(componentGUID)",
COMPONENT|$(componentGUID)|$(componentCameraCount)|$(coordSystemName)|$(isGeoreferenced)
$ExportCameras(
CAMERA|$(componentGUID)|$(originalFile)|$(x:.16g)|$(y:.16g)|$(z:.16g)|''' +
    '|'.join('$(' + key + ':.16g)' for key in ('R00', 'R01', 'R02', 'R10', 'R11', 'R12', 'R20', 'R21', 'R22')) + '''
)
)
)''')
FEATURE_TEMPLATE = template('FEATURE|$GetProperty("aligFeaturesMode", "MISSING")', ('ConfigExportFunctionSet',))


def build_plan(project_root, selection_manifest, policy, component, install_dir, instance, run_name, reserve_gib,
               *, components_root, max_original_cameras=None, import_only=False, cache_dir=None):
    project, selection, policy_path, install = map(safe, (project_root, selection_manifest, policy, install_dir))
    if (not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,63}', instance)
            or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}', run_name)):
        raise ValueError('Dedicated instance and simple fresh run-name required')
    if not math.isfinite(reserve_gib) or reserve_gib < 1:
        raise ValueError('Explicit reserve of at least 1 GiB required')
    if max_original_cameras is not None and (type(max_original_cameras) is not int or max_original_cameras < 1):
        raise ValueError('Explicit original-camera budget must be a positive integer')
    if len(component) != 2:
        raise ValueError('Exactly two original component paths required')
    census = component_census(project, components_root)
    if len(set(map(str, map(safe, component)))) != 2 or not set(map(str, map(safe, component))) <= set(census['paths']):
        raise ValueError('Probe pair must be two distinct members of the full aligned census')
    components = []
    component_images = {}
    dependencies = [Path(__file__).resolve(), Path(merge.__file__).resolve(),
        REPO / 'modules/prior_census.py', REPO / 'modules/realityscan_interface/realityscan_cli.py',
        REPO / 'modules/camera_registry.py', REPO / 'modules/cameras.json',
        Path(merge.METADATA_DIR) / 'FlightLogParams.xml', install / 'RealityScan.exe', install / 'flightlogs.xml']
    dependencies += [SCRIPTS / n for n in ('MergeZoneComponents.bat', 'SetVariables.bat',
                                          'startRealityScan.bat', 'RuntimeAbortGuard.bat')]
    # Inspect, never repair/install; source Help is pinned with the recorder.
    help_names = ('images', 'cameras', 'components', 'basic')
    dependencies += [install / ('Help/en-US/appbasics/reports_fav_' + n + '.htm') for n in help_names]
    for name in component:
        path = safe(name)
        if not path.is_relative_to(project / 'proc'):
            raise ValueError('Tiny components must remain in original project-owned proc export locations')
        item = load_manifest(str(path))
        if safe(item['rsalign']) != path:
            raise ValueError('Component was relocated from its original manifest location')
        merge.measured_component_ids(item)
        registration = path.parent / 'identity' / (path.stem + '.csv')
        with registration.open(encoding='utf-8-sig', newline='') as stream:
            next(stream)
            for row in csv.reader(stream):
                image = safe(row[0])
                if not image.is_relative_to(project / 'proc'):
                    raise ValueError('Component registration must prove project-owned image paths before import')
                identity = merge._orphan_id(image)
                prior_path = component_images.setdefault(identity, str(image))
                if prior_path != str(image):
                    raise ValueError('Probe cannot alias multiple component image paths to one identity')
        components.append(item)
        dependencies += [path, Path(str(path) + '.manifest.json'), path.parent / 'identity' / (path.stem + '.csv')]
    ctx = merge.load_orphan_context(selection, policy_path, census['components'], recording_probe=True,
                                    cancelled=_CANCELLED.get(), env=_ENVIRONMENT.get())
    if max_original_cameras is None:
        max_original_cameras = 2 * len(ctx['images'])
    if safe(ctx['project_root']) != project:
        raise ValueError('Selection belongs to another project')
    members = [merge.measured_component_ids(c) for c in components]
    original = set().union(*map(set, members))
    if sum(c['camera_count'] for c in components) > max_original_cameras:
        raise ValueError('Probe exceeds the explicit original-camera budget')
    spatial = merge.select_pair_orphans(members, ctx['navigation'], set(ctx['images']) - set(census['registered']),
                                       epsg=ctx['epsg'], policy=ctx['policy'])
    if spatial.get('refused') or spatial.get('refusal'):
        raise ValueError('Pair refused: ' + str(spatial.get('refusal')))
    reasons = spatial['spatial_reasons']
    controls, rejected_controls = choose_controls(spatial, ctx)
    if any(n is None for n in controls):
        raise ValueError('Probe requires an inside, a corridor and a remote control in approved selection; '
                         + str(rejected_controls))
    calibration_profiles = {}
    for name in controls[:2]:
        camera = camera_registry.identify(name)
        if camera is None:
            raise ValueError('Offered probe orphan has no native calibration profile: ' + name)
        calibration_profiles[name] = camera_registry.calibration_xmp(camera)
    if ctx['policy']['max_offered'] < 2:
        raise ValueError('Approved offered cap cannot accommodate probe controls')
    root = project / 'proc/validation/orphan_import' / run_name
    if root.exists():
        raise ValueError('Probe root exists; use a fresh run-name')
    chosen = original | set(controls)
    images = {n: ctx['images'][n] for n in sorted(chosen)}
    for name, path in component_images.items():
        if file_hash(path) != images[name]['sha256']:
            raise ValueError('Original component image differs from approved selection')
    masks = {n: ctx['masks'][n] for n in sorted(chosen & ctx['masks'].keys())}
    if ctx.get('occlusion') is not None:
        dependencies += [Path(ctx['occlusion']['manifest']['path']), REPO / 'modules/project_occlusion.py',
                         REPO / 'modules/temporal_occlusion.py']
    dependencies += [selection, policy_path, Path(ctx['flight_log'])]
    dependencies += [Path(r['path']) for r in list(images.values()) + list(masks.values())]
    dependencies += [Path(p) for p in component_images.values()]
    estimated = sum(Path(r['path']).stat().st_size for r in list(images.values()) + list(masks.values()))
    if shutil.disk_usage(project).free < reserve_gib * 1024**3 + estimated * 4 + 64 * 1024**2:
        raise ValueError('Insufficient storage after explicit reserve')
    return dict(schema=1, project_root=str(project), root=str(root), selection_manifest=str(selection),
        policy_file=str(policy_path), policy=ctx['policy'], epsg=ctx['epsg'], components=components, census=census,
        environment=_ENVIRONMENT.get(),
        spatial_reasons={**{n: 'registered_in_alignment' for n in census['registered']}, **reasons},
        rejected_controls=rejected_controls,
        members=members, component_images=component_images, controls=controls, offered=controls[:2], images=images, masks=masks,
        calibration_profiles=calibration_profiles, occlusion=ctx.get('occlusion'),
        navigation={n: ctx['navigation'][n] for n in sorted(chosen)},
        rows={n: ctx['rows'][n] for n in controls[:2]}, header=ctx['header'],
        flight_log=ctx['flight_log'], zone=ctx['zone'], instance=instance, install_dir=str(install),
        reserve_gib=reserve_gib, cache=str(safe(cache_dir) if cache_dir else project / 'proc/tmp/cache'), limits=LIMITS,
        max_original_cameras=max_original_cameras, import_only=import_only,
        dependencies=[bound(p) for p in sorted(set(dependencies))] + census['dependencies'],
        runtime_ids={stage: uuid4().hex for stage in STAGES})


def prepare(plan):
    checkpoint()
    root, project = safe(plan['root']), safe(plan['project_root'])
    if root.exists() or not root.is_relative_to(project / 'proc/validation/orphan_import'):
        raise ValueError('Fresh project-owned probe root required')
    check_census(plan)
    check(plan['dependencies'])
    # Recheck current approvals immediately before writing copies.
    current = merge.load_orphan_context(plan['selection_manifest'], plan['policy_file'], plan['census']['components'],
                                        recording_probe=True, cancelled=_CANCELLED.get(), env=plan.get('environment'))
    if current.get('occlusion') != plan.get('occlusion'):
        raise ValueError('Approved occlusion decision changed before probe preparation')
    checkpoint()
    root.mkdir(parents=True, exist_ok=False)
    inputs_dir = root / 'inputs'
    inputs_dir.mkdir()
    plan = copy.deepcopy(plan)
    plan['inputs'] = merge.stage_orphan_inputs(plan, plan['offered'], inputs_dir)
    for name, body in (('state.html', STATE_TEMPLATE), ('feature.html', FEATURE_TEMPLATE),
                       ('mask_export.xml', '<Configuration />')):
        write_text(root / name, body)
    plan['artifacts'] = [bound(p) for p in sorted(root.rglob('*')) if p.is_file()]
    manifest = root / 'probe.json'
    write_text(manifest, json.dumps(plan, indent=2))
    return bound(manifest)


def load_plan(manifest, expected_sha256):
    checkpoint()
    manifest = safe(manifest)
    if file_hash(manifest) != expected_sha256:
        raise ValueError('Reviewed probe manifest hash changed')
    plan = json.loads(manifest.read_text(encoding='utf-8'))
    if plan['schema'] != 1 or manifest != safe(plan['root']) / 'probe.json':
        raise ValueError('Invalid probe manifest location/schema')
    if not safe(plan['root']).is_relative_to(safe(plan['project_root']) / 'proc/validation/orphan_import'):
        raise ValueError('Probe escaped durable project validation directory')
    if sum(c['camera_count'] for c in plan['components']) > plan['max_original_cameras']:
        raise ValueError('Probe camera ceiling exceeded')
    check(plan['dependencies'] + plan['artifacts'])
    check_census(plan)
    return plan


def lines(path):
    text = html.unescape(Path(path).read_text(encoding='utf-8-sig'))
    if 'ORPHAN_NATIVE=1' not in text or 'END_ORPHAN' not in text or '$(' in text or '$Get' in text:
        raise ValueError('Missing or unexpanded native report')
    return [line.strip().split('|') for line in text.splitlines() if '|' in line]


def boolean(value):
    if value.casefold() not in ('true', 'false', '0', '1'):
        raise ValueError('Missing native boolean')
    return value.casefold() in ('true', '1')


def numbers(values):
    result = [float(v) for v in values]
    if not all(math.isfinite(v) for v in result):
        raise ValueError('Nonfinite native measurement')
    return result


def frame(value):
    from pyproj import CRS
    match = re.match(r'^epsg:(\d+)\b', value, re.I)
    return CRS.from_user_input('EPSG:' + match[1] if match else value).to_epsg()


def read_state(path, plan, expected_ids):
    images, priors, components, frames = {}, {}, {}, set()
    for row in lines(path):
        tag, *v = row
        if tag == 'IMAGE':
            if len(v) != 4 or v[0] in images:
                raise ValueError('Duplicate/malformed native input')
            images[v[0]] = safe(Path(v[1]) / (v[2] + (v[3] if v[3].startswith('.') else '.' + v[3])))
        elif tag == 'PRIOR':
            if len(v) != len(PRIOR_FIELDS) + 1 or v[0] in priors:
                raise ValueError('Duplicate/malformed native priors')
            priors[v[0]] = dict(zip(PRIOR_FIELDS, v[1:]))
        elif tag == 'COMPONENT':
            if len(v) != 4 or v[0] in components or not boolean(v[3]):
                raise ValueError('Unmeasured/unreferenced component')
            frames.add(frame(v[2]))
            components[v[0]] = {'count': int(v[1]), 'members': []}
        elif tag == 'CAMERA':
            if len(v) != 14 or v[0] not in components:
                raise ValueError('Camera without measured component')
            components[v[0]]['members'].append({'path': str(safe(v[1])), 'pose': numbers(v[2:])})
    if set(images) != set(priors) or frames != {plan['epsg']}:
        raise ValueError('Native inputs/priors/frame incomplete')
    result, seen = [], set()
    for index, path in images.items():
        name = merge._orphan_id(path)
        if (name in seen or name not in expected_ids or not path.is_relative_to(safe(plan['project_root']) / 'proc')
                or file_hash(path) != plan['images'][name]['sha256']):
            raise ValueError('Native input duplicate, remote, redirected or content changed')
        seen.add(name)
        p = priors[index]
        if boolean(p['inputIsLatLong']) or frame(p['inputCS']) != plan['epsg']:
            raise ValueError('Native input has wrong UTM frame')
        xyz_ypr = numbers([p['input' + k] for k in ('X', 'Y', 'Z', 'Yaw', 'Pitch', 'Roll')])
        prior = dict(zip(('x', 'y', 'z', 'yaw', 'pitch', 'roll'), xyz_ypr))
        prior.update(accuracy=numbers([p['inputAccuracy' + k] for k in ('X', 'Y', 'Z', 'Yaw', 'Pitch', 'Roll')]),
                     position_prior=boolean(p['inputIsPositionPrior']), orientation_prior=boolean(p['inputIsOrientationPrior']))
        calibration = {k: p[k] for k in ('calibrationGroup', 'distortionGroup', 'inputF',
                                         'inputLensModel', 'inputCalibrationPriorType')}
        result.append(dict(path=str(path), priors=prior, calibration=calibration,
                           feature_source=None, mask_path=None))
    if seen != set(expected_ids):
        raise ValueError('Native input membership differs from planned controls')
    paths = {r['path'] for r in result}
    for component in components.values():
        if (len(component['members']) != component['count'] or not component['members']
                or len({r['path'] for r in component['members']}) != component['count']
                or any(r['path'] not in paths for r in component['members'])):
            raise ValueError('Native camera census incomplete or duplicated')
        del component['count']
    return dict(inputs=result, components=list(components.values()), epsg=next(iter(frames)),
                vertical_datum=plan['policy']['vertical_datum'], vertical_datum_source='approved_declaration')


def read_feature(path):
    values = [row[1] for row in lines(path) if len(row) == 2 and row[0] == 'FEATURE']
    if len(values) != 1 or values[0] not in ('0', '1', '2'):
        raise ValueError('Feature source unobservable: GetProperty missing/non-numeric')
    return int(values[0])


def read_masks(directory, snapshot, expected):
    """Require unambiguous exported image names AND exact decoded pixels."""
    import cv2
    import numpy as np
    rows = {merge._orphan_id(r['path']): r for r in snapshot['inputs']}
    if not Path(directory).is_dir():
        raise ValueError('Mask export directory is missing')
    found = set()
    for path in sorted(Path(directory).rglob('*')):
        if not path.is_file():
            continue
        candidates = [n for n in rows if path.name.casefold() in
                      (n + '.mask.png', Path(n).stem + '.mask.png', Path(n).stem + '.png')]
        if len(candidates) != 1 or candidates[0] in found or candidates[0] not in expected:
            raise ValueError('Unknown, duplicate or ambiguous exported mask attachment')
        name = candidates[0]
        a = cv2.imdecode(np.frombuffer(path.read_bytes(), dtype=np.uint8), cv2.IMREAD_UNCHANGED)
        b = cv2.imdecode(np.frombuffer(Path(expected[name]['path']).read_bytes(), dtype=np.uint8), cv2.IMREAD_UNCHANGED)
        if a is None or b is None or a.shape != b.shape or a.dtype != b.dtype or not np.array_equal(a, b):
            raise ValueError('Exported mask pixels differ from planned mask')
        rows[name]['mask_path'] = expected[name]['path']
        found.add(name)
    if found != set(expected) & set(rows):
        raise ValueError('Missing exported masks; attachment unproven')


def feature_commands(paths, directory, root, *, controls=False):
    commands = []
    def read(path, name):
        commands.extend(['-deselectAllImages', f'-selectImage "{path}"',
                         f'-exportReport "{directory / (name + ".html")}" "{root / "feature.html"}" true'])
    if controls:
        a, b = paths[0], paths[-1]
        for path, value in ((a, 0), (b, 2)):
            commands += ['-deselectAllImages', f'-selectImage "{path}"', f'-setFeatureSource {value}']
        # No intervening setter: reject a global/last-written configuration value.
        for path, name in ((a, 'control_a0'), (b, 'control_b2'), (a, 'control_a0_again'), (b, 'control_b2_again')):
            read(path, name)
    else:
        for index, path in enumerate(paths):
            read(path, f'feature_{index}')
    return commands


def batch_text(commands):
    canonical = (SCRIPTS / 'MergeZoneComponents.bat').read_text(encoding='utf-8')
    tail = ':run\n' + canonical.rsplit('\n:run\n', 1)[1]
    tail = tail.replace('%~dp0RuntimeAbortGuard.bat', str(SCRIPTS / 'RuntimeAbortGuard.bat'))
    return '\n'.join(['@echo off', 'setlocal', f'call "{SCRIPTS / "SetVariables.bat"}"',
        'if errorlevel 1 exit /b 1', 'set "ErrorsFile=%ErrorPath%\\errors_%RS_INSTANCE%.txt"',
        f'call "{SCRIPTS / "RuntimeAbortGuard.bat"}" || exit /b 1223',
        f'call "{SCRIPTS / "startRealityScan.bat"}"', 'if errorlevel 1 exit /b 1',
        *[f'call :run {cmd} || goto :fail' for cmd in commands],
        f'call "{SCRIPTS / "RuntimeAbortGuard.bat"}" || exit /b 1223',
        '%RealityScan% -delegateTo %RS_INSTANCE% -quit', 'if errorlevel 1 exit /b 1', 'exit /b 0', ':fail',
        'echo ERROR: orphan probe failed; preserve all evidence.', 'exit /b 1', tail])


def run_stage(plan, stage, commands):
    """Only subprocess surface is RealityScanCLI; never attach to existing instances."""
    checkpoint()
    progress = _PROGRESS.get()
    if progress is not None:
        progress({'phase': 'native_' + stage, 'root': plan['root']})
    root = safe(plan['root'])
    if plan.get('occlusion') is not None:
        if merge.load_project_occlusion(plan['selection_manifest'], env=plan.get('environment')) != plan['occlusion']:
            raise ValueError('Approved occlusion decision changed before native probe stage')
    check(plan['dependencies'] + plan['artifacts'])
    check_census(plan)
    if shutil.disk_usage(root).free < plan['reserve_gib'] * 1024**3 + 64 * 1024**2:
        raise ValueError('Storage reserve unavailable before stage')
    directory = root / stage
    directory.mkdir(exist_ok=False)
    (directory / 'masks').mkdir()
    batch = directory / 'record.bat'
    write_text(batch, batch_text(commands), crlf=True)
    run_id = plan['runtime_ids'][stage]
    if not re.fullmatch('[0-9a-f]{32}', run_id):
        raise ValueError('Invalid runtime identity')
    runtime = safe(plan['project_root']) / 'proc/tmp' / run_id
    runtime.mkdir(parents=True, exist_ok=False)
    environment = dict(RS_RUN_ID=run_id, RS_RUNTIME_ROOT=str(runtime), RS_CONTROL_FILE=str(runtime / 'control.json'),
        RS_EVENT_FILE=str(runtime / 'runtime.jsonl'), RS_ERRORS_DIR=str(runtime / 'markers'),
        RS_INSTANCE=plan['instance'], RS_EXECUTABLE=str(safe(plan['install_dir']) / 'RealityScan.exe'),
        RS_CACHE_DIR=plan['cache'], RS_HEADLESS='1', RS_REQUIRE_NEW_INSTANCE='1',
        RS_NO_SETTINGS_INHERITANCE='1', RS_NO_INTERACTIVE='1')
    environment = {**(plan.get('environment') or {}), **environment}
    if os.environ.get('RS_ORPHAN_EVIDENCE_CHILD') == '1':
        # All native phases report under the controller's one attributed child.
        parent = os.environ.get('RS_RUN_ID', '')
        if not re.fullmatch('[0-9a-f]{32}', parent):
            raise ValueError('Invalid controller runtime identity')
        parent_root = safe(plan['project_root']) / 'proc/tmp' / parent
        expected = dict(RS_RUNTIME_ROOT=str(parent_root), RS_CONTROL_FILE=str(parent_root / 'control.json'),
                        RS_EVENT_FILE=str(parent_root / 'runtime.jsonl'), RS_ERRORS_DIR=str(parent_root / 'markers'))
        if any(safe(os.environ.get(k, '')) != safe(v) for k, v in expected.items()):
            raise ValueError('Controller runtime channels are not bound to the project attempt')
        environment.update(expected, RS_RUN_ID=parent)
    old = {key: os.environ.get(key) for key in environment}
    logger = logging.getLogger('orphan-probe.' + run_id)
    handler = logging.FileHandler(directory / 'driver.log', mode='x', encoding='utf-8')
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    external_control = _CONTROL.get()
    control = RunControl()
    stopped = threading.Event()
    cancelled = _CANCELLED.get()
    failures = []
    def monitor():
        while not stopped.wait(0.1):
            try:
                if external_control is not None:
                    requested, mode = (external_control.snapshot() if hasattr(external_control, 'snapshot') else
                                       (external_control.cancellation_requested, external_control.mode))
                    if requested:
                        control.request_cancel(getattr(external_control, 'reason', 'controller'), mode=mode)
                        continue  # Keep polling to propagate after_step -> abort_current upgrades.
                if cancelled is not None and cancelled():
                    raise InterruptedError('Orphan evidence cancelled during native stage')
            except Exception as exc:
                failures.append(exc)
                control.request_cancel(str(exc), mode='abort_current')
                return
    watcher = threading.Thread(target=monitor, name='orphan-evidence-cancel', daemon=True)
    try:
        checkpoint()
        os.environ.update(environment)
        cli = RealityScanCLI(logger, instance_name=plan['instance'])
        runtime_record = dict(stage='merge', probe_phase=stage, needs_realityscan=True,
                              env=environment, probe_manifest=str(root / 'probe.json'))
        write_text(directory / 'runtime_record.json', json.dumps(runtime_record, indent=2))
        watcher.start()
        try:
            result = cli.run_batch_script(str(batch), [], str(directory / 'logs'), control=control)
        except BaseException as exc:
            error = OwnershipUnconfirmed('Native probe execution escaped without confirmed ownership release',
                                         record=runtime_record, log_path=str(directory / 'driver.log'))
            error.runtime_cli, error.runtime_run_id = cli, None
            error.runtime_record_path = str(directory / 'runtime_record.json')
            raise error from exc
        if result.ownership_retained:
            runtime_record['native_run_id'] = result.run_id
            error = OwnershipUnconfirmed('Orphan proof retained native ownership; reconcile before another operation',
                                         record=runtime_record, log_path=getattr(result, 'log_path', None))
            error.runtime_cli, error.runtime_run_id = cli, result.run_id
            error.runtime_record_path = str(directory / 'runtime_record.json')
            raise error
        if failures:
            raise failures[0]
        checkpoint()
        if not result.success:
            raise RuntimeError('Orphan probe stage failed or retained instance ownership')
    finally:
        stopped.set()
        if watcher.ident is not None:
            watcher.join()
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        handler.close()
        logger.removeHandler(handler)


def capture_commands(root, stage, *, expected_masks):
    directory = root / stage
    commands = ['-deselectAllImages', f'-exportReport "{directory / "state.html"}" "{root / "state.html"}" true']
    # Native exportMasks fails when no layer exists (observed import probe v03).
    # Absence is checked on the empty export directory, not by dispatching export.
    if expected_masks:
        commands.append(f'-exportMasks "{directory / "masks"}" "{root / "mask_export.xml"}"')
    return commands + [f'-save "{directory / "scene.rsproj"}"']


def expected_prior(plan, name):
    v = numbers(plan['rows'][name][1:])
    p = dict(zip(('x', 'y', 'z'), v[:3]))
    p.update(accuracy=v[3:6] + v[9:12], yaw=v[6], pitch=v[7], roll=v[8],
             position_prior=True, orientation_prior=True)
    return p


def verify_prepared(plan, baseline, prepared):
    """Check import safety before authorizing even the tiny alignment."""
    before_priors = {r['path']: r['priors'] for r in baseline['inputs']}
    after_priors = {r['path']: r['priors'] for r in prepared['inputs']}
    component_key = lambda c: tuple(sorted(r['path'] for r in c['members']))
    measured = sorted([sorted(merge._orphan_id(r['path']) for r in c['members']) for c in baseline['components']])
    if measured != sorted([sorted(c) for c in plan['members']]):
        raise ValueError('Native baseline component membership differs from measured input exports')
    if (sorted(baseline['components'], key=component_key) != sorted(prepared['components'], key=component_key)
            or any(after_priors.get(path) != prior for path, prior in before_priors.items())):
        raise ValueError('Orphan import changed original priors/poses; alignment refused')
    for row in prepared['inputs']:
        name = merge._orphan_id(row['path'])
        if name in plan['offered'] and row['priors'] != expected_prior(plan, name):
            raise ValueError('Orphan prior readback differs from selected navigation; alignment refused')
        if name in plan['offered']:
            camera = camera_registry.identify(name)
            measured = row['calibration']
            groups = numbers([measured['calibrationGroup'], measured['distortionGroup']])
            focal = numbers([measured['inputF']])[0]
            if (camera is None or groups != [int(camera.calibration_group), int(camera.lens_distortion_group)]
                    or abs(focal - camera.focal_length_35mm) > 1e-5
                    or measured['inputLensModel'].lower() != camera.distortion_model.lower()
                    or not measured['inputCalibrationPriorType'].strip()):
                raise ValueError('Orphan native calibration not delivered; alignment refused')
        else:
            original = next(r['calibration'] for r in baseline['inputs'] if r['path'] == row['path'])
            if row['calibration'] != original:
                raise ValueError('Orphan import changed original calibration; alignment refused')


def normalize(plan):
    root = safe(plan['root'])
    original = set().union(*map(set, plan['members']))
    snapshots = {}
    for stage in STAGES:
        ids = original if stage == 'before' else original | set(plan['offered'])
        snapshot = read_state(root / stage / 'state.html', plan, ids)
        read_masks(root / stage / 'masks', snapshot, plan['masks'])
        if stage != 'before':
            for index, row in enumerate(sorted(snapshot['inputs'], key=lambda r: r['path'])):
                row['feature_source'] = read_feature(root / stage / f'feature_{index}.html')
        snapshots[stage] = snapshot
    values = [read_feature(root / 'prepared' / (name + '.html')) for name in
              ('control_a0', 'control_b2', 'control_a0_again', 'control_b2_again')]
    if values != [0, 2, 0, 2]:
        raise ValueError('Feature source is not independently observable per selected input')
    verify_prepared(plan, snapshots['before'], snapshots['prepared'])
    expected = dict(policy=plan['policy'], epsg=plan['epsg'], component_members=plan['members'],
        navigation=plan['navigation'], orphan_ids=plan['controls'], images=copy.deepcopy(plan['images']),
        masks=plan['masks'], source_files=plan['source_files'], source_snapshots=plan['source_snapshots'], orphan_priors={})
    for row in snapshots['prepared']['inputs']:
        name = merge._orphan_id(row['path'])
        expected['images'][name]['path'] = row['path']
    for name in plan['offered']:
        expected['orphan_priors'][name] = expected_prior(plan, name)
    return dict(expected=expected, **snapshots)


def record(manifest, expected_sha256):
    checkpoint()
    plan = load_plan(manifest, expected_sha256)
    root = safe(plan['root'])
    if any((root / stage).exists() for stage in STAGES) or (root / 'attempt.json').exists():
        raise ValueError('Probe already attempted; use fresh run-name, never overwrite evidence')
    ctx = merge.load_orphan_context(plan['selection_manifest'], plan['policy_file'], plan['census']['components'],
                                    recording_probe=True, cancelled=_CANCELLED.get(), env=plan.get('environment'))
    if ctx['policy'] != plan['policy'] or ctx.get('occlusion') != plan.get('occlusion'):
        raise ValueError('Approved geometry or occlusion decision changed')
    if shutil.disk_usage(root).free < plan['reserve_gib'] * 1024**3 + 64 * 1024**2:
        raise ValueError('Storage reserve unavailable')
    # Watch the selected source tree, not an entire expedition. Import does not export XMP.
    selection = json.loads(Path(plan['selection_manifest']).read_text(encoding='utf-8'))
    source = safe(selection['images_root'])
    plan['source_files'] = list(plan['images'].values()) + list(plan['masks'].values())
    plan['source_files'] += [bound(p) for p in plan['component_images'].values()]
    roots = {source, *(safe(p).parent for p in plan['component_images'].values())}
    plan['source_snapshots'] = [{'root': str(p), 'fingerprint': source_fingerprint(p)} for p in sorted(roots)]
    write_text(root / 'attempt.json', json.dumps(plan, indent=2))
    original = set().union(*map(set, plan['members']))
    commands = ['-newScene'] + [f'-importComponent "{c["rsalign"]}"' for c in plan['components']]
    for identity in sorted(original & plan['masks'].keys()):
        commands += ['-deselectAllImages', f'-selectImage "{plan["component_images"][identity]}"',
                     f'-setImagesLayer "{plan["masks"][identity]["path"]}" mask']
    commands += ['-selectAllImages', '-editInputSelection "inpMaskOpts=3"', '-deselectAllImages']
    run_stage(plan, 'before', commands + capture_commands(root, 'before', expected_masks=original & plan['masks'].keys()))
    checkpoint()
    baseline = read_state(root / 'before/state.html', plan, original)
    paths = [r['path'] for r in baseline['inputs']]
    offered_paths = Path(plan['inputs']['list']).read_text().splitlines()
    all_paths = sorted(paths + offered_paths)
    commands = [f'-load "{root / "before/scene.rsproj"}"', '-set "ifKGrp=0"', '-selectAllImages',
                f'-setFeatureSource {plan["policy"]["component_features"]}', '-deselectAllImages',
                f'-add "{plan["inputs"]["list"]}"',
                f'-importFlightLog "{plan["inputs"]["flight_log"]}" "{plan["inputs"]["params"]}"']
    for pair in Path(plan['inputs']['masks']).read_text().splitlines():
        image, mask = pair.split('|')
        commands += ['-deselectAllImages', f'-selectImage "{image}"', f'-setImagesLayer "{mask}" mask']
    commands += feature_commands([paths[0], offered_paths[0]], root / 'prepared', root, controls=True)
    # Restore the exact approved modes after the diagnostic contrast.
    for group, mode in ((paths, plan['policy']['component_features']), (offered_paths, 2)):
        commands += ['-deselectAllImages'] + [f'-selectImage "{p}" union' for p in group]
        commands += [f'-setFeatureSource {mode}']
    commands += ['-enableAlignment true']
    commands += ['-selectAllImages', '-editInputSelection "inpMaskOpts=3"', '-deselectAllImages']
    commands += feature_commands(all_paths, root / 'prepared', root)
    expected_masks = (original | set(plan['offered'])) & plan['masks'].keys()
    run_stage(plan, 'prepared', commands + capture_commands(root, 'prepared', expected_masks=expected_masks))
    checkpoint()
    prepared = read_state(root / 'prepared/state.html', plan, original | set(plan['offered']))
    read_masks(root / 'prepared/masks', prepared, plan['masks'])
    verify_prepared(plan, baseline, prepared)
    try:
        values = [read_feature(root / 'prepared' / (n + '.html')) for n in
                  ('control_a0', 'control_b2', 'control_a0_again', 'control_b2_again')]
        if values != [0, 2, 0, 2]:
            raise ValueError('GetProperty does not distinguish independent inputs')
        for index, path in enumerate(all_paths):
            mode = read_feature(root / 'prepared' / f'feature_{index}.html')
            if mode != (2 if merge._orphan_id(path) in plan['offered'] else plan['policy']['component_features']):
                raise ValueError('Prepared feature mode differs from requested mode')
    except ValueError as exc:
        result = dict(status='incomplete', unavailable=['feature_source'], reason=str(exc), limits=LIMITS,
                      alternative_readback='Native priors/poses and exported mask pixels are retained; alignment was not run.')
        write_text(root / 'readback.json', json.dumps(result, indent=2))
        return result
    if plan.get('import_only'):
        native = [bound(p) for stage in ('before', 'prepared') for p in sorted((root / stage).rglob('*'))
                  if p.is_file() and (p.suffix.lower() in ('.html', '.png', '.bat') or p.name == 'scene.rsproj')]
        write_text(root / 'import_capture.json', json.dumps({'native': native,
                    'attempt': bound(root / 'attempt.json')}, indent=2))
        result = verify(manifest, expected_sha256)
        checkpoint()
        if result.get('status') == 'passed':
            write_text(root / 'orphan_import.json', json.dumps(dict(schema=3, recording_manifest=bound(manifest)), indent=2))
        return result
    commands = [f'-load "{root / "prepared/scene.rsproj"}"', '-selectAllImages',
                '-editInputSelection "inpMaskOpts=3"', '-deselectAllImages', '-align',
                '-selectAllImages', '-editInputSelection "inpMaskOpts=3"', '-deselectAllImages']
    run_stage(plan, 'aligned', commands + feature_commands(all_paths, root / 'aligned', root) +
              capture_commands(root, 'aligned', expected_masks=expected_masks))
    checkpoint()
    documents = normalize(plan)
    artifacts = {}
    for name, document in documents.items():
        path = root / (name + '.json')
        write_text(path, json.dumps(document, indent=2))
        artifacts[name] = bound(path)
    native = [bound(p) for stage in STAGES for p in sorted((root / stage).rglob('*'))
              if p.is_file() and (p.suffix.lower() in ('.html', '.png', '.bat') or p.name == 'scene.rsproj')]
    capture = dict(schema=1, selector_version=merge.ORPHAN_SELECTOR_VERSION, artifacts=artifacts,
                   dependencies=plan['dependencies'] + native + [bound(root / 'attempt.json'), bound(manifest)])
    write_text(root / 'capture.json', json.dumps(capture, indent=2))
    result = verify(manifest, expected_sha256)
    checkpoint()
    if result.get('status') == 'passed':
        evidence = dict(schema=3, recording_manifest=bound(manifest))
        write_text(root / 'orphan_import.json', json.dumps(evidence, indent=2))
    return result


def verify(manifest, expected_sha256, *, policy=None, epsg=None):
    """No writes/RS. Regenerate normalized measurements from native artifacts."""
    original = load_plan(manifest, expected_sha256)
    if original.get('occlusion') is not None:
        environment = _ENVIRONMENT.get()
        if environment is None:
            environment = (os.environ if os.environ.get('RS_PROJECT_FILE') or os.environ.get('RS_SELECTION_MANIFEST')
                           else original.get('environment'))
        if merge.load_project_occlusion(original['selection_manifest'], env=environment) != original['occlusion']:
            raise ValueError('Native probe occlusion approval changed; evidence is stale')
    root = safe(original['root'])
    plan = json.loads((root / 'attempt.json').read_text(encoding='utf-8'))
    if any(plan[key] != value for key, value in original.items()):
        raise ValueError('Recording differs from reviewed plan')
    if plan.get('import_only') and (root / 'import_capture.json').exists():
        capture = json.loads((root / 'import_capture.json').read_text(encoding='utf-8'))
        check(capture['native'] + [capture['attempt']] + plan['source_files'])
        for snapshot in plan['source_snapshots']:
            if source_fingerprint(snapshot['root']) != snapshot['fingerprint']:
                raise ValueError('Probe source tree changed')
        if epsg is not None and plan['epsg'] != epsg:
            raise ValueError('Probe UTM frame changed')
        if policy is not None and any(plan['policy'][k] != policy[k] for k in merge.ORPHAN_POLICY_SCHEMA['required']):
            raise ValueError('Probe geometry/features policy changed')
        ids = set().union(*map(set, plan['members']))
        before = read_state(root / 'before/state.html', plan, ids)
        prepared = read_state(root / 'prepared/state.html', plan, ids | set(plan['offered']))
        verify_prepared(plan, before, prepared)
        for stage, state in (('before', before), ('prepared', prepared)):
            read_masks(root / stage / 'masks', state, plan['masks'])
        values = [read_feature(root / 'prepared' / (n + '.html')) for n in
                  ('control_a0', 'control_b2', 'control_a0_again', 'control_b2_again')]
        if values != [0, 2, 0, 2]:
            raise ValueError('Feature source not independently observable')
        for index, item in enumerate(sorted(prepared['inputs'], key=lambda r: r['path'])):
            expected = 2 if merge._orphan_id(item['path']) in plan['offered'] else plan['policy']['component_features']
            if read_feature(root / 'prepared' / f'feature_{index}.html') != expected:
                raise ValueError('Prepared feature source differs from approved value')
        return dict(status='passed', scope='import_readback_only', project_root=plan['project_root'],
                    native_recording=True, fingerprint={'recording_manifest': bound(manifest),
                    'native_capture': bound(root / 'import_capture.json')},
                    limits=LIMITS + ['No alignment was performed; reconstruction retention remains a merge-stage check.'])
    if not (root / 'aligned').exists():
        ids = set().union(*map(set, plan['members']))
        before = read_state(root / 'before/state.html', plan, ids)
        prepared = read_state(root / 'prepared/state.html', plan, ids | set(plan['offered']))
        verify_prepared(plan, before, prepared)
        read_masks(root / 'prepared/masks', prepared, plan['masks'])
        unavailable = []
        try:
            values = [read_feature(root / 'prepared' / (n + '.html')) for n in
                      ('control_a0', 'control_b2', 'control_a0_again', 'control_b2_again')]
            if values != [0, 2, 0, 2]:
                unavailable.append('feature_source')
        except ValueError:
            unavailable.append('feature_source')
        return dict(status='incomplete', project_root=plan['project_root'],
                    measured=['input_identity', 'priors', 'component_pose_preservation', 'mask_pixels'],
                    unavailable=unavailable + ([] if plan.get('import_only') else ['alignment_retention']), limits=LIMITS)
    documents = normalize(plan)
    for name, value in documents.items():
        if json.loads((root / (name + '.json')).read_text(encoding='utf-8')) != value:
            raise ValueError('Normalized probe evidence differs from native recordings')
    result = merge.replay_orphan_probe(root / 'capture.json', original['project_root'], policy=policy,
        epsg=epsg, executable=str(safe(original['install_dir']) / 'RealityScan.exe'))
    result.update(project_root=original['project_root'], limits=LIMITS, native_recording=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    actions = parser.add_subparsers(dest='action', required=True)
    for name in ('plan', 'prepare'):
        action = actions.add_parser(name)
        for key in ('project-root', 'selection-manifest', 'policy', 'install-dir', 'instance', 'run-name', 'components-root'):
            action.add_argument('--' + key, required=True)
        action.add_argument('--component', required=True, action='append')
        action.add_argument('--reserve-gib', required=True, type=float)
        action.add_argument('--max-original-cameras', type=int)
        action.add_argument('--import-only', action='store_true')
        action.add_argument('--cache-dir')
    for name in ('record', 'verify'):
        action = actions.add_parser(name)
        action.add_argument('--manifest', required=True)
        action.add_argument('--expected-sha256', required=True)
        if name == 'record':
            action.add_argument('--execute', required=True, action='store_true')
    args = vars(parser.parse_args())
    action = args.pop('action')
    args.pop('execute', None)
    try:
        if action in ('plan', 'prepare'):
            result = build_plan(**args)
            if action == 'prepare':
                result = prepare(result)
        else:
            result = globals()[action](**args)
        print(json.dumps(result, indent=2, allow_nan=False))
        return 0 if result.get('status') not in ('failed', 'incomplete') else 2
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
        print(json.dumps({'status': 'refused', 'reason': str(exc)}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
