"""Prepare/review/run tiny RS 2.2 import-only experiments. Never align.

``plan`` reads only; ``prepare`` creates a NEW owned directory below the given
project's proc/tmp. ``run`` is for the owner's scheduler, requires the reviewed
manifest hash, and launches only through RealityScanCLI. No install repair.
See rs_prior_import_probe.md for evidence limits and the cell matrix.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import math
import os
from pathlib import Path
import re
import shutil
import sys
from uuid import UUID, uuid4
import xml.etree.ElementTree as ET

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from modules import camera_registry, prior_census
from modules.flightlog_format import _parse as parse_installed_xml
from modules.image_exts import is_geometry_image
from modules.realityscan_interface.realityscan_cli import assert_bat_safe

FAMILIES = ('legacy_camupper', 'legacy_cammid', 'legacy_camlower', 'zeuss')
SCRIPTS = REPO / 'modules/realityscan_interface/RS_CLI/Scripts'
FORMAT_GUID = '{D1F2A3B4-5C6D-4E7F-8A9B-0C1D2E3F4A5B}'
FORMAT_FIELDS = ('Image', 'X', 'Y', 'Altitude', 'XAccuracy', 'YAccuracy',
                 'AltitudeAccuracy', 'Yaw', 'Pitch', 'Roll', 'YawAccuracy',
                 'PitchAccuracy', 'RollAccuracy', 'FocalLength')
PRIOR_FIELDS = ('inputIsPositionPrior', 'inputIsOrientationPrior',
                'inputIsPriorAccuracy', 'inputIsLatLong', 'inputCS',
                'inputX', 'inputY', 'inputZ', 'inputYaw', 'inputPitch', 'inputRoll',
                'inputAccuracyX', 'inputAccuracyY', 'inputAccuracyZ',
                'inputAccuracyYaw', 'inputAccuracyPitch', 'inputAccuracyRoll',
                'calibrationGroup', 'distortionGroup', 'inputF',
                'inputCalibrationPriorType', 'inputLensModel',
                'inputIsOpkRotationPrior', 'inputOmega', 'inputPhi', 'inputKappa')
GLOBALS = dict(zip(('X', 'Y', 'Z', 'Yaw', 'Pitch', 'Roll'), (17, 19, 23, 29, 31, 37)))
CELLS = (
    'report_control', 'csv_i0_g0', 'csv_i1_g0', 'csv_i1_g1',
    'native_xmp_only', 'legacy_xmp_only', 'native_xmp_csv_g0',
    'native_xmp_csv_g1', 'csv_then_explicit_xmp', 'group_controls',
    'rotation_cli_control',
    'production_calibration_csv',
    'production_mask_control',
    'production_mask_cold',
)
REPORT_TEMPLATE = '''$Using("RealityScan.Report.IteratorsFunctionSet")
$Using("RealityScan.Report.SfmExportFunctionSet")
<!doctype html><html><head><meta charset="UTF-8"></head><body><pre>
PROBE_SCHEMA=1
$IterateImages(
IMAGE|$(inputIndex)|$(inputImagePath)|$(inputImageName)|$(inputImageExt)|$(inputIsAligned)
$ExportImagePriors(inputIndex,
PRIOR|$(inputIndex)|''' + '|'.join('$(' + field + ')' for field in PRIOR_FIELDS) + '''
)
)
END_PROBE
</pre></body></html>
'''


def digest(path):
    with open(path, 'rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def safe_path(path):
    value = Path(path).resolve()
    assert_bat_safe([str(value)], 'prior import probe')
    if any(ord(c) < 32 for c in str(value)):
        raise ValueError('Control character in probe path')
    return value


def check_install(install):
    """Read-only structural check; do NOT call the repairing format assertion."""
    root = parse_installed_xml(str(install / 'flightlogs.xml'))
    formats = [node for node in root.findall('format') if node.get('id') == FORMAT_GUID]
    if len(formats) != 1 or formats[0].get('reader') != 'RealityScan.Import.CSVFlightLog':
        raise ValueError('Required RUMI format missing/ambiguous; probe never repairs the install')
    parser = formats[0].find('parser')
    if parser is None or ';' not in parser.get('allowedSeparators', ''):
        raise ValueError('Installed CSV parser does not support semicolon sentinels')
    for index, field in enumerate(FORMAT_FIELDS):
        nodes = parser.findall(field)
        if len(nodes) != 1 or nodes[0].get('index') != str(index):
            raise ValueError(f'Installed format has incompatible {field} column')
    help_text = (install / 'Help/en-US/appbasics/reports_fav_images.htm').read_text(encoding='utf-8')
    if any(field not in help_text for field in PRIOR_FIELDS):
        raise ValueError('Installed Help does not document all required prior readback fields')
    sets = (install / 'Help/en-US/appbasics/reports_fav_sets.htm').read_text(encoding='utf-8')
    if 'ExportImagePriors' not in sets or 'IterateImages' not in sets:
        raise ValueError('Installed report function sets are unsupported')
    paths = [install / 'flightlogs.xml', install / 'Reports/Overview.html',
             install / 'Help/en-US/appbasics/reports_fav_images.htm',
             install / 'Help/en-US/appbasics/reports_fav_sets.htm',
             install / 'Help/en-US/appbasics/allcommands.htm',
             install / 'Help/en-US/tools/imglayers.htm', install / 'Help/en-US/tools/mask.htm',
             install / 'masklayer.xml',
             install / 'Help/en-US/tools/xmpalign.htm', SCRIPTS / 'AlignZone.bat',
             SCRIPTS / 'SetVariables.bat', SCRIPTS / 'startRealityScan.bat',
             SCRIPTS / 'RuntimeAbortGuard.bat', Path(__file__).resolve(),
             REPO / 'modules/realityscan_interface/realityscan_cli.py']
    paths += [REPO / 'modules/camera_registry.py', REPO / 'modules/cameras.json',
              REPO / 'modules/prior_census.py', REPO / 'modules/image_exts.py',
              REPO / 'modules/flightlog_format.py', SCRIPTS.parent / 'Metadata/AlignmentParams.xml']
    return {str(path): digest(path) for path in paths}


def source_images(source_root):
    """Select one deterministic physical-image reference per requested family."""
    chosen = {}
    for root, dirs, files in os.walk(source_root):
        dirs.sort(key=str.casefold)
        for name in sorted(files, key=str.casefold):
            path = Path(root) / name
            if not is_geometry_image(path) or path.suffix.lower() not in ('.jpg', '.jpeg', '.png'):
                continue
            family = camera_registry.family(name)
            if family in FAMILIES and family not in chosen:
                chosen[family] = path.resolve()
        if len(chosen) == len(FAMILIES):
            break
    if set(chosen) != set(FAMILIES):
        raise ValueError(f'Missing physical-image families: {sorted(set(FAMILIES) - set(chosen))}')
    from PIL import Image
    result = []
    for family in FAMILIES:
        path = chosen[family]
        if not path.is_relative_to(source_root):
            raise ValueError('Image reference escapes the declared source root')
        with Image.open(path) as image:
            width, height = image.size
            image.verify()
        result.append(dict(family=family, source=str(path), sha256=digest(path),
                           size=path.stat().st_size, extension=path.suffix.lower(),
                           width=width, height=height))
    if len({row['sha256'] for row in result}) != 4:
        raise ValueError('Selected camera references contain duplicate image content')
    return result


def build_plan(project_root, source_root, install_dir, instance, run_name, reserve_gib=50, cells=None):
    project, source, install = map(safe_path, (project_root, source_root, install_dir))
    if not project.is_dir() or not source.is_dir():
        raise ValueError('Project and source roots must already exist')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}', run_name):
        raise ValueError('run-name must be a simple unique directory name')
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,63}', instance):
        raise ValueError('An explicit dedicated instance name is required')
    if not math.isfinite(reserve_gib) or reserve_gib < 1:
        raise ValueError('reserve-gib must be finite and at least 1')
    root = safe_path(project / 'proc/tmp' / run_name)
    if not root.is_relative_to(project / 'proc/tmp') or root.is_relative_to(source):
        raise ValueError('Probe root must be owned project proc/tmp, outside source')
    if root.exists():
        raise ValueError(f'Probe destination already exists; choose a new run-name: {root}')
    selected_cells = list(CELLS if cells is None else cells)
    if (not selected_cells or len(set(selected_cells)) != len(selected_cells) or
            any(cell not in CELLS for cell in selected_cells) or selected_cells[0] != 'report_control'):
        raise ValueError('Select unique known cells beginning with report_control')
    references = source_images(source)
    installed = check_install(install)
    channels = {}
    for cell in selected_cells:
        run_id = uuid4().hex
        runtime = safe_path(project / 'proc/tmp' / run_id)
        channels[cell] = dict(RS_RUN_ID=run_id, RS_RUNTIME_ROOT=str(runtime),
                              RS_CONTROL_FILE=str(runtime / 'control.json'),
                              RS_EVENT_FILE=str(runtime / 'runtime.jsonl'),
                              RS_ERRORS_DIR=str(runtime / 'markers'))
    needed = sum(row['size'] for row in references) * len(selected_cells) + 64 * 1024**2
    mask_cells = sum(cell in ('production_mask_control', 'production_mask_cold') for cell in selected_cells)
    needed += mask_cells * sum(row['width'] * row['height'] * 10 for row in references)
    if shutil.disk_usage(project).free < needed + reserve_gib * 1024**3:
        raise ValueError('Insufficient space after source copies and required reserve')
    return dict(schema_version=1, project_root=str(project), source_root=str(source),
                root=str(root), install_dir=str(install), instance=instance,
                cache=str(project / 'proc/tmp/cache'), reserve_gib=reserve_gib,
                source_references=references, dependency_hashes=installed,
                cells=selected_cells, runtime_channels=channels, estimated_copy_bytes=needed,
                alignment_allowed=False, source_writes_allowed=False)


def cell_channels(plan, cell):
    """Validate the manifest's channels against the canonical runtime layout."""
    channels = plan['runtime_channels'][cell]
    run_id = channels['RS_RUN_ID']
    if not isinstance(run_id, str) or UUID(run_id).hex != run_id:
        raise ValueError('Runtime run id must be a canonical UUID hex string')
    runtime = safe_path(Path(plan['project_root']) / 'proc/tmp' / run_id)
    expected = dict(RS_RUN_ID=run_id, RS_RUNTIME_ROOT=str(runtime),
                    RS_CONTROL_FILE=str(runtime / 'control.json'),
                    RS_EVENT_FILE=str(runtime / 'runtime.jsonl'),
                    RS_ERRORS_DIR=str(runtime / 'markers'))
    if channels != expected or runtime.is_relative_to(safe_path(plan['source_root'])):
        raise ValueError('Invalid planned runtime channels')
    return dict(channels)


def sentinels(index):
    return dict(csv_position=[101 + index * 10, 203 + index * 10, -307 - index * 10],
                csv_ypr=[[11, 22, 33], [41, -12, 7], [-61, 32, -17], [131, 42, 23]][index],
                csv_accuracy=[1.11 + index / 10, 2.22 + index / 10, 3.33 + index / 10,
                              4.44 + index, 5.55 + index, 6.66 + index],
                csv_focal=23 if index == 3 else 16,
                xmp_position=[1001 + index * 10, 2003 + index * 10, -3007 - index * 10],
                xmp_focal=[31, 37, 43, 47][index],
                xmp_calibration_group=101 + index, xmp_distortion_group=201 + index,
                cli_calibration_group=301 + index, cli_distortion_group=401 + index,
                edit_calibration_group=501 + index, edit_distortion_group=601 + index,
                edit_ypr=[-21 - index, 34 + index, -47 - index],
                edit_accuracy=[7.11 + index, 8.22 + index, 9.33 + index,
                               10.44 + index, 11.55 + index, 12.66 + index])


def rotation_sentinels():
    """Proper matrices, NOT an asserted RS/world/camera frame convention."""
    def multiply(a, b):
        return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]
    c, s = math.cos, math.sin
    x, y, z = map(math.radians, (30, 20, 40))
    rx = [[1, 0, 0], [0, c(x), -s(x)], [0, s(x), c(x)]]
    ry = [[c(y), 0, s(y)], [0, 1, 0], [-s(y), 0, c(y)]]
    rz = [[c(z), -s(z), 0], [s(z), c(z), 0], [0, 0, 1]]
    return [[[1, 0, 0], [0, 1, 0], [0, 0, 1]], rx, ry, multiply(rz, multiply(ry, rx))]


def native_xmp(values, matrix):
    xcr = 'http://www.capturingreality.com/ns/xcr/1.1#'
    ET.register_namespace('x', 'adobe:ns:meta/')
    ET.register_namespace('rdf', 'http://www.w3.org/1999/02/22-rdf-syntax-ns#')
    ET.register_namespace('xcr', xcr)
    root = ET.Element('{adobe:ns:meta/}xmpmeta')
    rdf = ET.SubElement(root, '{http://www.w3.org/1999/02/22-rdf-syntax-ns#}RDF')
    attributes = dict(Version='3', PosePrior='initial', Coordinates='absolute',
                      CalibrationPrior='initial', CalibrationGroup=str(values['xmp_calibration_group']),
                      DistortionGroup=str(values['xmp_distortion_group']), DistortionModel='division',
                      FocalLength35mm=str(values['xmp_focal']),
                      Rotation=' '.join(f'{item:.15g}' for row in matrix for item in row))
    node = ET.SubElement(rdf, '{http://www.w3.org/1999/02/22-rdf-syntax-ns#}Description',
                         {f'{{{xcr}}}{key}': value for key, value in attributes.items()})
    ET.SubElement(node, f'{{{xcr}}}Position').text = ' '.join(map(str, values['xmp_position']))
    return ET.tostring(root, encoding='unicode')


def flight_params(inheritance, grouping):
    root = ET.Element('Configuration', id='{93DBD041-AE1C-4631-89BC-D9430FCED843}')
    entries = dict(ifuuInhEn='true', ifCSopt='1', gpsLogFileFormat=FORMAT_GUID,
                   CoordinateSystemFlightLog='+proj=geocent +ellps=WGS84 +no_defs',
                   CoordinateSystemFlightLogType='local:1 - Euclidean',
                   ifKGrp=str(grouping), ifuuInh=str(inheritance), ifKmode='0x0',
                   csvFLIgn='true', csvFLSep='1')
    for key, value in entries.items():
        ET.SubElement(root, 'entry', key=key, value=value)
    return ET.tostring(root, encoding='unicode')


def legacy_xmp(values):
    """Frozen original calibration-only serializer, independent of later fixes."""
    return f'''<x:xmpmeta xmlns:x="adobe:ns:meta/">
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
<rdf:Description xmlns:Camera="http://www.capturingreality.com/ns/camera/1.0/" xmlns:xcr="http://www.capturingreality.com/ns/xcr/1.0/">
<Camera:CalibrationGroup>{values['xmp_calibration_group']}</Camera:CalibrationGroup>
<Camera:CalibrationPrior>Approximate</Camera:CalibrationPrior>
<xcr:FocalLength35mm>{values['xmp_focal']}</xcr:FocalLength35mm>
<Camera:LensDistortionGroup>{values['xmp_distortion_group']}</Camera:LensDistortionGroup>
<Camera:LensDistortionPrior>Approximate</Camera:LensDistortionPrior>
<Camera:DistortionModel>division</Camera:DistortionModel>
</rdf:Description></rdf:RDF></x:xmpmeta>'''


def write_text(path, text, crlf=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8', newline='\r\n' if crlf else '\n') as stream:
        stream.write(text.rstrip('\n') + '\n')


def prepare(plan):
    """Materialize reviewed inputs only; this function cannot launch RS."""
    root = safe_path(plan['root'])
    project, source = map(safe_path, (plan['project_root'], plan['source_root']))
    if not root.is_relative_to(project / 'proc/tmp') or root.is_relative_to(source) or root.exists():
        raise ValueError('Refused existing/unowned probe root')
    for path, expected in plan['dependency_hashes'].items():
        if digest(path) != expected:
            raise ValueError(f'Dependency changed after planning: {path}')
    for ref in plan['source_references']:
        if digest(ref['source']) != ref['sha256']:
            raise ValueError('Source changed after planning')
    if shutil.disk_usage(project).free < plan['estimated_copy_bytes'] + plan['reserve_gib'] * 1024**3:
        raise ValueError('Storage reserve no longer available')
    channel_ids = []
    for cell in plan['cells']:
        channels = cell_channels(plan, cell)
        channel_ids.append(channels['RS_RUN_ID'])
        if Path(channels['RS_RUNTIME_ROOT']).exists():
            raise ValueError('Planned runtime directory already exists; replan')
    if len(set(channel_ids)) != len(channel_ids):
        raise ValueError('Each probe cell requires a unique runtime run id')
    root.mkdir(parents=True, exist_ok=False)
    template = root / 'priors.html'
    write_text(template, REPORT_TEMPLATE)
    canonical = (SCRIPTS / 'AlignZone.bat').read_text(encoding='utf-8')
    run_tail = ':run\n' + canonical.rsplit('\n:run\n', 1)[1]
    run_tail = run_tail.replace('%~dp0RuntimeAbortGuard.bat', str(SCRIPTS / 'RuntimeAbortGuard.bat'))
    plan['cell_details'] = {}
    for cell in plan['cells']:
        directory = root / cell
        directory.mkdir()
        images, expectations, masks = [], [], []
        production = cell in ('production_calibration_csv', 'production_mask_control', 'production_mask_cold')
        native = cell.startswith('native_xmp')
        for index, ref in enumerate(plan['source_references']):
            name = ('camupper_', 'cammid_', 'camlower_', 'herc_')[index] + 'probe' + ref['extension']
            image = directory / name
            shutil.copy2(ref['source'], image)
            if digest(image) != ref['sha256']:
                raise ValueError('Owned image copy differs from source')
            values = sentinels(index)
            values.update(image=str(image), family=ref['family'], source=ref['source'],
                          xmp_rotation=rotation_sentinels()[index])
            if production:
                camera = camera_registry.identify(image.name)
                values.update(xmp_focal=camera.focal_length_35mm,
                              xmp_calibration_group=camera.calibration_group,
                              xmp_distortion_group=camera.lens_distortion_group)
            expectations.append(values)
            images.append(image)
            if native or cell == 'csv_then_explicit_xmp':
                target = image.with_suffix('.xmp') if native else directory / 'detached' / (image.stem + '.xmp')
                write_text(target, native_xmp(values, values['xmp_rotation']))
            elif cell == 'legacy_xmp_only':
                write_text(image.with_suffix('.xmp'), legacy_xmp(values))
            elif production:
                write_text(image.with_suffix('.xmp'), camera_registry.calibration_xmp(camera_registry.identify(image.name)))
            if cell in ('production_mask_control', 'production_mask_cold'):
                from PIL import Image
                # Distinct, full-resolution binary masks are owned probe inputs,
                # never inherited from the source image tree.
                with Image.open(image) as original:
                    mask = Image.new('L', original.size, 255)
                width, height = mask.size
                mask.paste(0, (0, 0, max(1, width * (index + 1) // 5), height))
                mask_path = Path(str(image) + '.mask.png')
                mask.save(mask_path)
                masks.append(dict(image=str(image), path=str(mask_path), sha256=digest(mask_path)))
        for second in (False, True):
            rows = [';'.join(FORMAT_FIELDS)]
            for values in expectations:
                position = [v + (100 if second else 0) for v in values['csv_position']]
                ypr = [v + (1 if second else 0) for v in values['csv_ypr']]
                row = [values['image'], *position, *values['csv_accuracy'][:3], *ypr,
                       *values['csv_accuracy'][3:], values['csv_focal']]
                rows.append(';'.join(map(str, row)))
            write_text(directory / ('second.csv' if second else 'first.csv'), '\n'.join(rows))
        inheritance = 0 if cell == 'csv_i0_g0' else 1
        grouping = 1 if cell.endswith('g1') or cell == 'group_controls' else 0
        params = directory / 'flight_params.xml'
        write_text(params, flight_params(inheritance, grouping))
        production_contract = None
        if production:
            expected_inputs = prior_census.build_input_prior_manifest(images, directory / 'first.csv', params)
            production_contract = prior_census.write_input_prior_contract(expected_inputs, directory / 'input_priors')
        commands, reports = ['-newScene'], []
        global_commands = [f'-set "sfmCameraPriorAccuracy{key}={value}"' for key, value in GLOBALS.items()]
        global_commands += ['-set "sfmCameraPriorWeightOrientation=2"', '-set "sfmCameraPriorWeight=10"']
        if not production:
            commands += global_commands
        if cell in ('production_mask_control', 'production_mask_cold'):
            # Installed imglayers Help requires geometry and layers loaded
            # together. v03 individual geometry-only -add calls produced
            # err:33640 (no Mask layer), so exercise AlignZone's actual folder
            # import rather than assuming adjacent files are discovered.
            commands += ['-set "appIncSubdirs=true"', f'-addFolder "{directory}"']
        else:
            commands += [f'-add "{image}"' for image in images]
        production_settings = {}
        if production:
            # Match native fresh-input policy; invocation alone is not readback
            # evidence of mask attachment or of an observable per-input option.
            commands += ['-selectAllImages', '-editInputSelection "inpMaskOpts=3"']
            # Import, project and output scopes are distinct. Pin the latter
            # two to the exact identifier declared by the real input contract.
            crs_id = expected_inputs['coordinate_system'].split(' ', 1)[0]
            commands += [f'-setProjectCoordinateSystem "{crs_id}"',
                         f'-setOutputCoordinateSystem "{crs_id}"']
            settings_path = SCRIPTS.parent / 'Metadata/AlignmentParams.xml'
            for entry in ET.parse(settings_path).getroot().findall('entry'):
                key, value = entry.get('key', ''), entry.get('value', '')
                if not re.fullmatch(r'[A-Za-z][A-Za-z0-9]*', key) or key.startswith('app') or not value or key in production_settings:
                    raise ValueError('Invalid/duplicate/app-global production alignment setting')
                assert_bat_safe(value)
                production_settings[key] = value
                commands.append(f'-set "{key}={value}"')
            if not production_settings:
                raise ValueError('Production alignment settings are empty')
            # Deliberately distinctive defaults are the accuracy negative
            # control; the per-input CSV vector must supersede them.
            commands += global_commands

        def report(stage):
            target = directory / (stage + '.html')
            commands.append(f'-exportReport "{target}" "{template}" true')
            reports.append(dict(stage=stage, path=str(target)))

        if cell == 'report_control':
            commands.append(f'-exportReport "{directory / "builtin_overview.html"}" '
                            f'"{Path(plan["install_dir"]) / "Reports/Overview.html"}" true')
        report('added')
        if 'csv' in cell or cell == 'rotation_cli_control' or production:
            commands.append(f'-importFlightLog "{directory / "first.csv"}" "{params}"')
            report('csv_first')
        if cell.startswith('native_xmp_csv'):
            commands.append(f'-importFlightLog "{directory / "second.csv"}" "{params}"')
            report('csv_second')
        if cell == 'csv_then_explicit_xmp':
            for image in images:
                commands.append(f'-addImageWithCalibration "{image}" "{directory / "detached" / (image.stem + ".xmp")}"')
            report('explicit_xmp_reimport')
        if cell == 'group_controls':
            for style in ('cli', 'edit'):
                for values in expectations:
                    commands += ['-deselectAllImages', f'-selectImage "{values["image"]}"']
                    if style == 'cli':
                        commands += [f'-setPriorCalibrationGroup {values["cli_calibration_group"]}',
                                     f'-setPriorLensGroup {values["cli_distortion_group"]}']
                    else:
                        commands += [f'-editInputSelection "inpCalibrationGroup={values["edit_calibration_group"]}"',
                                     f'-editInputSelection "inpLensGroup={values["edit_distortion_group"]}"']
                report(style + '_groups')
            commands.append(f'-importFlightLog "{directory / "first.csv"}" "{params}"')
            report('groups_then_csv_g1')
        if cell == 'rotation_cli_control':
            for values in expectations:
                commands += ['-deselectAllImages', f'-selectImage "{values["image"]}"',
                             '-editInputSelection "inpPose=2"', '-editInputSelection "inpPriorAccuracyInh=1"']
                settings = dict(zip(('inpRx', 'inpRy', 'inpRz'), values['edit_ypr']))
                settings.update(zip(('inpuTx', 'inpuTy', 'inpuTz', 'inpuRx', 'inpuRy', 'inpuRz'), values['edit_accuracy']))
                commands += [f'-editInputSelection "{key}={value}"' for key, value in settings.items()]
            report('rotation_setter')
        if production_contract:
            commands.append(f'-exportReport "{production_contract["RS_INPUT_PRIOR_REPORT"]}" "{production_contract["RS_INPUT_PRIOR_TEMPLATE"]}" true')
        mask_export = None
        mask_positive_export = None
        if masks:
            mask_export = str(directory / 'exported_masks')
            Path(mask_export).mkdir()
            # Compatibility hypothesis, as in the separate merge probe. Export
            # failure is a failed control, never proof of missing attachment.
            mask_params = directory / 'mask_export.xml'
            write_text(mask_params, '<Configuration />')
            # Positive export MUST precede the naming/discovery experiment.
            # Keep its output outside the recursively imported cell folder.
            if cell == 'production_mask_control':
                positive_root = root / 'explicit_mask_positive'
                positive_root.mkdir()
                mask_positive_export = str(positive_root / 'exported_masks')
                Path(mask_positive_export).mkdir()
                positive = ['-newScene'] + [f'-add "{image}"' for image in images]
                for row in masks:
                    positive += ['-deselectAllImages', f'-selectImage "{row["image"]}"',
                                 f'-setImagesLayer "{row["path"]}" mask']
                positive += ['-selectAllImages', '-editInputSelection "inpMaskOpts=3"',
                             f'-save "{positive_root / "explicit_masks.rsproj"}"',
                             f'-exportMasks "{mask_positive_export}" "{mask_params}"']
                commands = positive + commands
            commands += ['-selectAllImages', f'-exportMasks "{mask_export}" "{mask_params}"']
        commands += ['-deselectAllImages', f'-save "{directory / "readback.rsproj"}"']
        script = '\n'.join([
            '@echo off', 'setlocal', f'call "{SCRIPTS / "SetVariables.bat"}"',
            'if errorlevel 1 exit /b 1', 'set "ErrorsFile=%ErrorPath%\\errors_%RS_INSTANCE%.txt"',
            f'call "{SCRIPTS / "RuntimeAbortGuard.bat"}" || exit /b 1223',
            f'call "{SCRIPTS / "startRealityScan.bat"}"', 'if errorlevel 1 exit /b 1',
            *[f'call :run {command} || goto :fail' for command in commands],
            *([f'pushd "{REPO}" || goto :fail',
               f'"%RS_PYTHON%" -B -m modules.prior_census --input-manifest "{production_contract["RS_INPUT_PRIOR_MANIFEST"]}" --expected-sha256 "{production_contract["RS_INPUT_PRIOR_SHA256"]}" --input-report "{production_contract["RS_INPUT_PRIOR_REPORT"]}" --output "{production_contract["RS_INPUT_PRIOR_RESULT"]}"',
               'if errorlevel 1 ( popd & goto :fail )', 'popd'] if production_contract else []),
            f'call "{SCRIPTS / "RuntimeAbortGuard.bat"}" || exit /b 1223',
            '%RealityScan% -delegateTo %RS_INSTANCE% -quit', 'exit /b 0', ':fail',
            'echo ERROR: probe command failed; no scientific conclusion.', 'exit /b 1', run_tail,
        ])
        batch = directory / 'import_probe.bat'
        write_text(batch, script, crlf=True)
        plan['cell_details'][cell] = dict(batch=str(batch), reports=reports, expected=expectations,
                                          commands=commands, python_log=str(directory / 'driver.log'),
                                          production_contract=production_contract,
                                          masks=masks, mask_export=mask_export,
                                          mask_positive_export=mask_positive_export,
                                          mask_attachment_mode=('cold_folder_only' if cell == 'production_mask_cold' else
                                                                'explicit_then_fresh_scene_folder' if masks else 'not_tested'),
                                          production_alignment_settings=production_settings,
                                          sentinel_global_overrides=GLOBALS if production else {},
                                          mask_option_readback='UNOBSERVABLE_NO_DOCUMENTED_REPORT_VARIABLE',
                                          mask_export_params_status='UNVERIFIED_EMPTY_CONFIGURATION' if masks else 'NOT_TESTED')
    plan['artifact_hashes'] = {str(path.relative_to(root)): digest(path)
                              for path in sorted(root.rglob('*')) if path.is_file()}
    manifest = root / 'probe.json'
    write_text(manifest, json.dumps(plan, indent=2))
    return dict(manifest=str(manifest), sha256=digest(manifest), cells=list(plan['cells']))


def read_report(path, expected):
    """Do not convert missing macros, files or rows into successful evidence."""
    text = Path(path).read_text(encoding='utf-8-sig')
    if 'PROBE_SCHEMA=1' not in text or 'END_PROBE' not in text or '$(' in text or '$Iterate' in text:
        raise ValueError('Report missing or macros did not expand')
    images, priors = {}, {}
    for line in text.splitlines():
        fields = line.strip().split('|')
        if fields[0] == 'IMAGE':
            if len(fields) != 6 or fields[1] in images:
                raise ValueError('Malformed/duplicate image report row')
            images[fields[1]] = fields[2:]
        elif fields[0] == 'PRIOR':
            if len(fields) != len(PRIOR_FIELDS) + 2 or fields[1] in priors:
                raise ValueError('Malformed/duplicate prior report row')
            priors[fields[1]] = dict(zip(PRIOR_FIELDS, fields[2:]))
    if len(images) != 4 or set(images) != set(priors):
        raise ValueError('Incomplete input/prior coverage; exactly four inputs required')
    expected_paths = {str(Path(row['image']).resolve()).casefold() for row in expected}
    found, result = set(), []
    for index, (directory, name, extension, aligned) in images.items():
        filename = name + (extension if extension.startswith('.') else '.' + extension)
        full = str((Path(directory) / filename).resolve())
        if full.casefold() not in expected_paths or full.casefold() in found:
            raise ValueError('Report image identity mismatch')
        if aligned.lower() not in ('0', 'false'):
            raise ValueError('Unexpected alignment state in import-only probe')
        found.add(full.casefold())
        result.append(dict(filename=full, input_index=index, **priors[index]))
    if found != expected_paths:
        raise ValueError('Report omitted an input filename')
    return result


def verify(manifest, cell):
    plan = json.loads(Path(manifest).read_text(encoding='utf-8'))
    detail = plan['cell_details'][cell]
    reports = {item['stage']: read_report(item['path'], detail['expected']) for item in detail['reports']}
    missing = []
    for stage, rows in reports.items():
        if stage in ('csv_first', 'csv_second', 'rotation_setter'):
            for row in rows:
                for field in ('inputX', 'inputY', 'inputZ', 'inputYaw', 'inputPitch', 'inputRoll',
                              'inputAccuracyX', 'inputAccuracyY', 'inputAccuracyZ',
                              'inputAccuracyYaw', 'inputAccuracyPitch', 'inputAccuracyRoll',
                              'calibrationGroup', 'distortionGroup'):
                    try:
                        valid = math.isfinite(float(row[field]))
                    except ValueError:
                        valid = False
                    if not valid:
                        missing.append(dict(stage=stage, filename=row['filename'], field=field, raw=row[field]))
    if cell == 'report_control':
        builtin = Path(plan['root']) / cell / 'builtin_overview.html'
        if not builtin.is_file() or builtin.stat().st_size == 0:
            raise ValueError('Shipped Overview report positive control is missing/empty')
    if cell in ('production_calibration_csv', 'production_mask_control', 'production_mask_cold'):
        contract = detail['production_contract']
        with open(contract['RS_INPUT_PRIOR_RESULT'], encoding='utf-8') as stream:
            result = json.load(stream)
        if result.get('verdict') != 'VERIFIED_INPUT_PRIORS' or result.get('expected_sha256') != contract['RS_INPUT_PRIOR_SHA256']:
            raise ValueError('Production input census failed or refers to another contract')
    mask_evidence = verify_mask_exports(detail) if cell in ('production_mask_control', 'production_mask_cold') else None
    production = cell in ('production_calibration_csv', 'production_mask_control', 'production_mask_cold')
    return dict(cell=cell, alignment_performed=False, reports=reports,
                mask_evidence=mask_evidence,
                missing_measurements=missing,
                expected=detail['expected'], global_accuracy=GLOBALS,
                verdict=('INCOMPLETE_READBACK' if missing else
                         'VERIFIED_PRODUCTION_IMPORT' if production else 'READBACK_ONLY_REQUIRES_SENTINEL_COMPARISON'),
                open_claim='Import readback alone does not establish physical camera/world axis semantics')


def verify_mask_exports(detail, *, export_dir=None):
    """Require exact image association and decoded pixels, not command success."""
    from PIL import Image
    expected = detail['masks']
    directory = Path(detail['mask_export'] if export_dir is None else export_dir)
    if not directory.is_dir() or not expected:
        raise ValueError('Mask attachment control requires masks and an export directory')
    found = set()
    evidence = []
    for path in sorted(directory.rglob('*')):
        if not path.is_file():
            continue
        candidates = [row for row in expected if path.name.casefold() in {
            Path(row['image']).name.casefold() + '.mask.png',
            Path(row['image']).stem.casefold() + '.mask.png',
            Path(row['image']).stem.casefold() + '.png'}]
        if len(candidates) != 1 or candidates[0]['image'] in found:
            raise ValueError('Unknown, duplicate or ambiguous exported mask attachment')
        row = candidates[0]
        if digest(row['path']) != row['sha256']:
            raise ValueError('Planned mask changed')
        with Image.open(row['path']) as original, Image.open(path) as exported:
            if original.size != exported.size or original.convert('RGBA').tobytes() != exported.convert('RGBA').tobytes():
                raise ValueError('Exported mask pixels differ from planned mask')
        found.add(row['image'])
        evidence.append(dict(image=row['image'], exported=str(path), sha256=digest(path)))
    if found != {row['image'] for row in expected}:
        raise ValueError('Missing exported masks; attachment unproven')
    result = dict(verdict='VERIFIED_MASK_ATTACHMENT_PIXELS', images=evidence,
                  attachment_mode=detail.get('mask_attachment_mode', 'not_recorded'),
                  option_readback='UNOBSERVABLE_NO_DOCUMENTED_REPORT_VARIABLE',
                  feature_exclusion_verified=False, meshing_verified=False)
    if export_dir is None and detail.get('mask_positive_export'):
        result['explicit_attachment_positive_control'] = verify_mask_exports(
            detail, export_dir=detail['mask_positive_export'])
    return result


def run(manifest, expected_sha256, cell):
    """OWNER/SCHEDULER ONLY: pin reviewed artifacts, then use the sole launcher."""
    manifest = safe_path(manifest)
    if digest(manifest) != expected_sha256:
        raise ValueError('Reviewed manifest hash mismatch')
    plan = json.loads(manifest.read_text(encoding='utf-8'))
    root = safe_path(plan['root'])
    if manifest != root / 'probe.json' or not root.is_relative_to(safe_path(plan['project_root']) / 'proc/tmp'):
        raise ValueError('Manifest is not in its owned project probe root')
    if cell not in CELLS or plan['alignment_allowed'] is not False:
        raise ValueError('Unknown cell or invalid alignment policy')
    for name, expected in plan['artifact_hashes'].items():
        path = safe_path(root / name)
        if not path.is_relative_to(root) or digest(path) != expected:
            raise ValueError(f'Probe input changed: {name}')
    for path, expected in plan['dependency_hashes'].items():
        if digest(path) != expected:
            raise ValueError(f'Probe dependency changed: {path}')
    detail = plan['cell_details'][cell]
    if cell != 'report_control':
        verify(manifest, 'report_control')
    if any(Path(item['path']).exists() for item in detail['reports']):
        raise ValueError('Probe cell already has reports; refusing to overwrite evidence')
    if shutil.disk_usage(root).free < plan['reserve_gib'] * 1024**3 + 64 * 1024**2:
        raise ValueError('Insufficient free space to preserve the approved reserve')
    channels = cell_channels(plan, cell)
    log_path = safe_path(detail['python_log'])
    if log_path != root / cell / 'driver.log':
        raise ValueError('Python log must be in this owned cell directory')
    if Path(channels['RS_RUNTIME_ROOT']).exists() or log_path.exists():
        raise ValueError('Runtime directory/log already exists; refusing to overwrite evidence')
    write_text(root / cell / 'run_attempt.json', json.dumps(
        {'reviewed_sha256': expected_sha256, 'runtime_channels': channels, 'python_log': str(log_path)}))
    handler = logging.FileHandler(log_path, mode='x', encoding='utf-8')
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s %(message)s'))
    logger = logging.getLogger('prior-import-probe.' + channels['RS_RUN_ID'])
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    environment = dict(channels, RS_NO_SETTINGS_INHERITANCE='1', RS_NO_INTERACTIVE='1',
                       RS_EXECUTABLE=str(Path(plan['install_dir']) / 'RealityScan.exe'),
                       RS_INSTANCE=plan['instance'], RS_CACHE_DIR=plan['cache'], RS_HEADLESS='1',
                       RS_REQUIRE_NEW_INSTANCE='1')
    previous = {key: os.environ.get(key) for key in environment}
    try:
        logger.info('Probe %s manifest=%s sha256=%s runtime_channels=%s',
                    cell, manifest, expected_sha256, json.dumps(channels, sort_keys=True))
        handler.flush()
        os.fsync(handler.stream.fileno())
        Path(channels['RS_RUNTIME_ROOT']).mkdir(parents=True, exist_ok=False)
        os.environ.update(environment)
        from modules.realityscan_interface.realityscan_cli import RealityScanCLI
        cli = RealityScanCLI(logger, instance_name=plan['instance'])
        result = cli.run_batch_script(detail['batch'], [], str(root / cell / 'logs'))
        logger.info('RealityScanCLI result: %s', result)
        if not result.success or result.ownership_retained:
            raise RuntimeError(f'RealityScanCLI probe workflow failed: {result}')
        evidence = verify(manifest, cell)
        write_text(root / cell / 'readback.json', json.dumps(evidence, indent=2))
        logger.info('Readback recorded: %s', evidence['verdict'])
        return evidence
    except BaseException:
        logger.exception('Unhandled probe failure; retain runtime channels and all evidence')
        raise
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        handler.flush()
        os.fsync(handler.stream.fileno())
        logger.removeHandler(handler)
        handler.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest='action', required=True)
    for action in ('plan', 'prepare'):
        command = actions.add_parser(action)
        for name in ('project-root', 'source-root', 'install-dir', 'instance', 'run-name'):
            command.add_argument('--' + name, required=True)
        command.add_argument('--reserve-gib', type=float, default=50)
        command.add_argument('--cells', nargs='+', choices=CELLS)
    for action in ('verify', 'run'):
        command = actions.add_parser(action)
        command.add_argument('--manifest', required=True)
        command.add_argument('--cell', choices=CELLS, required=True)
        if action == 'run':
            command.add_argument('--expected-plan-sha256', required=True)
            command.add_argument('--execute', action='store_true', required=True)
    args = vars(parser.parse_args())
    action = args.pop('action')
    args.pop('execute', None)
    if action in ('plan', 'prepare'):
        value = build_plan(**args)
        if action == 'prepare':
            value = prepare(value)
    elif action == 'verify':
        value = verify(**args)
    else:
        args['expected_sha256'] = args.pop('expected_plan_sha256')
        value = run(**args)
    print(json.dumps(value, indent=2))


if __name__ == '__main__':
    main()
