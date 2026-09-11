"""Offline harness safety and report-parser controls; never invoke RS."""
import json
import os
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
from PIL import Image

from testing import rs_prior_import_probe as probe


@pytest.mark.parametrize('failure', [None, 'missing', 'wrong_pixels', 'duplicate', 'unknown', 'source_changed'])
def test_mask_export_requires_exact_attachment_pixels(tmp_path, failure):
    mask = tmp_path / 'camupper_probe.jpg.mask.png'
    Image.new('L', (8, 8), 255).save(mask)
    exported = tmp_path / 'exported'
    exported.mkdir()
    target = exported / mask.name
    target.write_bytes(mask.read_bytes())
    detail = dict(mask_export=str(exported), masks=[dict(image=str(tmp_path / 'camupper_probe.jpg'),
                                                       path=str(mask), sha256=probe.digest(mask))])
    if failure == 'missing':
        target.unlink()
    elif failure == 'wrong_pixels':
        Image.new('L', (8, 8), 0).save(target)
    elif failure == 'duplicate':
        (exported / 'camupper_probe.png').write_bytes(target.read_bytes())
    elif failure == 'unknown':
        target.rename(exported / 'foreign.png')
    elif failure == 'source_changed':
        Image.new('L', (8, 8), 0).save(mask)
    if failure:
        with pytest.raises(ValueError):
            probe.verify_mask_exports(detail)
    else:
        evidence = probe.verify_mask_exports(detail)
        assert evidence['verdict'] == 'VERIFIED_MASK_ATTACHMENT_PIXELS'
        assert evidence['option_readback'].startswith('UNOBSERVABLE')
        assert not evidence['feature_exclusion_verified'] and not evidence['meshing_verified']


def test_cold_folder_control_has_no_prior_explicit_attachment(plan):
    cold = probe.build_plan(plan['project_root'], plan['source_root'], plan['install_dir'],
                            plan['instance'], 'cold-v05', 1,
                            cells=['report_control', 'production_mask_cold'])
    result = probe.prepare(cold)
    prepared = json.loads(Path(result['manifest']).read_text())
    detail = prepared['cell_details']['production_mask_cold']
    commands = detail['commands']
    assert detail['mask_attachment_mode'] == 'cold_folder_only'
    assert detail['mask_positive_export'] is None
    assert commands.count('-newScene') == 1
    assert sum(cmd.startswith('-addFolder ') for cmd in commands) == 1
    assert sum(cmd.startswith('-exportMasks ') for cmd in commands) == 1
    assert not any(cmd.startswith(('-setImageLayer ', '-setImagesLayer ', '-add ')) for cmd in commands)
    assert commands.index('-set "appIncSubdirs=true"') < next(i for i,c in enumerate(commands) if c.startswith('-addFolder '))
    assert len(detail['masks']) == 4 and detail['production_contract']
    assert not (Path(prepared['root']) / 'explicit_mask_positive').exists()
    control_commands = '\n'.join(prepared['cell_details']['report_control']['commands'])
    assert all(row['image'] not in control_commands for row in detail['expected'])
    assert prepared['runtime_channels']['report_control']['RS_RUN_ID'] != prepared['runtime_channels']['production_mask_cold']['RS_RUN_ID']


def test_mask_control_uses_actual_production_priors_and_explicit_both(plan):
    result = probe.prepare(plan)
    prepared = json.loads(Path(result['manifest']).read_text())
    detail = prepared['cell_details']['production_mask_control']
    commands = detail['commands']
    option = '-editInputSelection "inpMaskOpts=3"'
    assert commands[commands.index(option) - 1] == '-selectAllImages'
    add_folder = f'-addFolder "{Path(prepared["root"]) / "production_mask_control"}"'
    folder_index = commands.index(add_folder)
    assert commands.index('-set "appIncSubdirs=true"') < folder_index < commands.index(option, folder_index)
    assert sum(command.startswith('-setImagesLayer ') for command in commands) == 4
    exports = [i for i, command in enumerate(commands) if command.startswith('-exportMasks ')]
    assert len(exports) == 2 and exports[0] < folder_index < exports[1]
    assert commands[exports[0] + 1] == '-newScene'
    assert not Path(detail['mask_positive_export']).is_relative_to(Path(prepared['root']) / 'production_mask_control')
    assert sum(command.startswith('-importFlightLog ') for command in commands) == 1
    assert any(command.startswith('-exportMasks ') for command in commands)
    assert len(detail['masks']) == 4
    contract = json.loads(Path(detail['production_contract']['RS_INPUT_PRIOR_MANIFEST']).read_text())
    assert len(contract['images']) == 4
    assert detail['mask_export_params_status'] == 'UNVERIFIED_EMPTY_CONFIGURATION'
    assert not any(command == '-align' for command in commands)


@pytest.fixture
def plan(tmp_path):
    source, project, install = (tmp_path / name for name in ('source', 'project', 'install'))
    source.mkdir()
    project.mkdir()
    for i, name in enumerate(('camupper_a.jpg', 'cammid_a.jpeg', 'camlower_a.jpg', 'herc_a.jpg')):
        Image.new('RGB', (8, 8), (i * 60, 20, 30)).save(source / name)
    for path in ('Help/en-US/appbasics', 'Help/en-US/tools', 'Reports'):
        (install / path).mkdir(parents=True, exist_ok=True)
    (install / 'Help/en-US/appbasics/reports_fav_images.htm').write_text(' '.join(probe.PRIOR_FIELDS))
    (install / 'Help/en-US/appbasics/reports_fav_sets.htm').write_text('ExportImagePriors IterateImages')
    (install / 'Help/en-US/tools/xmpalign.htm').write_text('fixture')
    (install / 'Reports/Overview.html').write_text('fixture')
    for name in ('Help/en-US/appbasics/allcommands.htm', 'Help/en-US/tools/imglayers.htm',
                 'Help/en-US/tools/mask.htm', 'masklayer.xml'):
        (install / name).write_text('offline dependency fixture')
    fields = ''.join(f'<{name} index="{i}"/>' for i, name in enumerate(probe.FORMAT_FIELDS))
    (install / 'flightlogs.xml').write_text(
        f'<formats><format id="{probe.FORMAT_GUID}" reader="RealityScan.Import.CSVFlightLog">'
        f'<parser allowedSeparators=";">{fields}</parser></format></formats>')
    return probe.build_plan(project, source, install, 'ProbeOffline', 'probe-test', 1)


def test_plan_is_read_only_and_preparation_is_owned(plan):
    root = Path(plan['root'])
    assert not root.exists()
    result = probe.prepare(plan)
    assert Path(result['manifest']).parent == root
    assert len(plan['source_references']) == 4
    for ref in plan['source_references']:
        assert probe.digest(ref['source']) == ref['sha256']
    for path, expected in plan['dependency_hashes'].items():
        assert probe.digest(path) == expected
    manifest = json.loads(Path(result['manifest']).read_text())
    for detail in manifest['cell_details'].values():
        batch = Path(detail['batch']).read_bytes()
        assert b'\r\n' in batch and b'\n' not in batch.replace(b'\r\n', b'')
        assert '-align' not in batch.decode() and '-exportXMP' not in batch.decode()
        assert 'startRealityScan.bat' in batch.decode()
        assert len(detail['expected']) == 4
        for row in detail['expected']:
            assert Path(row['image']).is_relative_to(root)
    with pytest.raises(ValueError, match='existing/unowned'):
        probe.prepare(plan)


def test_missing_install_format_refuses_without_repair(plan):
    xml = Path(plan['install_dir']) / 'flightlogs.xml'
    xml.write_text('<formats/>')
    with pytest.raises(ValueError, match='missing/ambiguous'):
        probe.check_install(Path(plan['install_dir']))
    assert xml.read_text() == '<formats/>'


def test_report_control_uses_identifier_argument_and_builtin_first(plan):
    """Regression for live 20567: numeric arguments cannot use text expansion."""
    result = probe.prepare(plan)
    manifest = json.loads(Path(result['manifest']).read_text())
    template = (Path(plan['root']) / 'priors.html').read_text()
    assert '$ExportImagePriors(inputIndex,' in template
    assert '$ExportImagePriors($(inputIndex),' not in template
    # Text output still requires the expansion form, including the row identity.
    assert 'PRIOR|$(inputIndex)|' in template
    commands = manifest['cell_details']['report_control']['commands']
    exports = [command for command in commands if command.startswith('-exportReport ')]
    assert len(exports) == 2
    assert 'builtin_overview.html' in exports[0] and 'Overview.html' in exports[0]
    assert 'added.html' in exports[1] and 'priors.html' in exports[1]
    batch = Path(manifest['cell_details']['report_control']['batch']).read_text()
    assert batch.index('builtin_overview.html') < batch.index('added.html')


def test_source_change_between_plan_and_prepare_refused(plan):
    Path(plan['source_references'][0]['source']).write_bytes(b'changed')
    with pytest.raises(ValueError, match='Source changed'):
        probe.prepare(plan)
    assert not Path(plan['root']).exists()


def report_text(expected):
    lines = ['PROBE_SCHEMA=1']
    for i, row in enumerate(expected):
        path = Path(row['image'])
        lines.append(f'IMAGE|{i}|{path.parent}|{path.stem}|{path.suffix}|false')
        values = {key: '0' for key in probe.PRIOR_FIELDS}
        values.update(inputYaw=str(row['csv_ypr'][0]), inputPitch=str(row['csv_ypr'][1]),
                      inputRoll=str(row['csv_ypr'][2]), calibrationGroup='-1', distortionGroup='-1')
        lines.append(f'PRIOR|{i}|' + '|'.join(values[key] for key in probe.PRIOR_FIELDS))
    return '\n'.join(lines + ['END_PROBE'])


def test_readback_requires_actual_complete_filename_rows(plan):
    result = probe.prepare(plan)
    manifest = json.loads(Path(result['manifest']).read_text())
    cell = manifest['cell_details']['csv_i1_g0']
    report = Path(cell['reports'][0]['path'])
    text = report_text(cell['expected'])
    report.write_text(text)
    rows = probe.read_report(report, cell['expected'])
    assert len(rows) == 4 and rows[0]['inputYaw'] == '11'
    assert rows[0]['filename'] == cell['expected'][0]['image']
    for broken in (text.replace('IMAGE|0|', 'IMAGE|1|'), text + '\n$(unexpanded)',
                   text.replace('camupper_probe', 'wrong'), text.replace('|false', '|true')):
        report.write_text(broken)
        with pytest.raises(ValueError):
            probe.read_report(report, cell['expected'])


def test_review_hash_and_artifact_changes_refused_before_launcher(plan):
    result = probe.prepare(plan)
    with pytest.raises(ValueError, match='manifest hash'):
        probe.run(result['manifest'], '0' * 64, 'report_control')
    artifact = Path(plan['root']) / 'priors.html'
    artifact.write_text('tampered')
    with pytest.raises(ValueError, match='Probe input changed'):
        probe.run(result['manifest'], result['sha256'], 'report_control')


def test_matrix_sentinels_are_proper_rotations():
    import numpy as np
    for matrix in probe.rotation_sentinels():
        matrix = np.array(matrix)
        assert matrix @ matrix.T == pytest.approx(np.eye(3))
        assert np.linalg.det(matrix) == pytest.approx(1)


def test_v03_production_cell_uses_actual_serializer_and_census(plan):
    result = probe.prepare(plan)
    saved = json.loads(Path(result['manifest']).read_text())
    detail = saved['cell_details']['production_calibration_csv']
    contract = detail['production_contract']
    expected = json.loads(Path(contract['RS_INPUT_PRIOR_MANIFEST']).read_text())
    assert expected['lane'] == 'native_calibration_csv_pose_v1'
    assert len(expected['images']) == 4
    for row in expected['images']:
        content = Path(row['sidecar']).read_text()
        assert content.strip() == probe.camera_registry.calibration_xmp(probe.camera_registry.identify(Path(row['filename']).name)).strip()
        assert 'PosePrior' not in content and 'Position' not in content and 'Rotation' not in content
    assert len([cmd for cmd in detail['commands'] if cmd.startswith('-importFlightLog ')]) == 1
    commands = detail['commands']
    crs_id = expected['coordinate_system'].split(' ', 1)[0]
    added = max(i for i, cmd in enumerate(commands) if cmd.startswith('-add '))
    project_crs = commands.index(f'-setProjectCoordinateSystem "{crs_id}"')
    output_crs = commands.index(f'-setOutputCoordinateSystem "{crs_id}"')
    settings = commands.index('-set "sfmEnableCameraPrior=true"')
    csv = next(i for i, cmd in enumerate(commands) if cmd.startswith('-importFlightLog '))
    assert added < project_crs < output_crs < settings < csv
    assert all(i > added for i, cmd in enumerate(commands) if cmd.startswith('-set '))
    assert detail['production_alignment_settings']['sfmCameraPriorWeightOrientation'] == '2.0'
    assert detail['sentinel_global_overrides'] == probe.GLOBALS
    script = Path(detail['batch']).read_text()
    assert '-m modules.prior_census' in script and '-align' not in script
    assert 'if errorlevel 1 ( popd & goto :fail )' in script
    assert str(probe.REPO / 'modules/prior_census.py') in saved['dependency_hashes']


def test_minimal_v03_plan_selects_controls_only(plan):
    minimal = probe.build_plan(plan['project_root'], plan['source_root'], plan['install_dir'],
                              plan['instance'], 'minimal-v03', 1,
                              cells=['report_control', 'production_calibration_csv'])
    assert minimal['cells'] == ['report_control', 'production_calibration_csv']
    assert len(minimal['runtime_channels']) == 2
    with pytest.raises(ValueError, match='beginning with report_control'):
        probe.build_plan(plan['project_root'], plan['source_root'], plan['install_dir'],
                         plan['instance'], 'invalid-v03', 1, cells=['production_calibration_csv'])


def test_runtime_channels_planned_per_cell_without_creating_them(plan):
    ids = set()
    for cell in plan['cells']:
        channels = probe.cell_channels(plan, cell)
        run_id = channels['RS_RUN_ID']
        assert UUID(run_id).hex == run_id and run_id not in ids
        ids.add(run_id)
        root = Path(plan['project_root']) / 'proc/tmp' / run_id
        assert channels['RS_RUNTIME_ROOT'] == str(root)
        assert channels['RS_CONTROL_FILE'] == str(root / 'control.json')
        assert channels['RS_EVENT_FILE'] == str(root / 'runtime.jsonl')
        assert channels['RS_ERRORS_DIR'] == str(root / 'markers')
        assert root.is_absolute() and not root.exists()
    result = probe.prepare(plan)
    saved = json.loads(Path(result['manifest']).read_text())
    assert saved['runtime_channels'] == plan['runtime_channels']
    assert all(not Path(row['RS_RUNTIME_ROOT']).exists() for row in saved['runtime_channels'].values())


@pytest.mark.parametrize('defect', ['duplicate', 'foreign_control', 'foreign_markers', 'existing'])
def test_unsafe_runtime_plan_refused_before_preparation(plan, defect):
    channels = plan['runtime_channels']['report_control']
    if defect == 'duplicate':
        plan['runtime_channels']['csv_i0_g0'] = dict(channels)
    elif defect == 'foreign_control':
        channels['RS_CONTROL_FILE'] = str(Path(plan['source_root']) / 'control.json')
    elif defect == 'foreign_markers':
        channels['RS_ERRORS_DIR'] = str(Path(plan['source_root']) / 'markers')
    else:
        Path(channels['RS_RUNTIME_ROOT']).mkdir(parents=True)
    with pytest.raises(ValueError):
        probe.prepare(plan)
    assert not Path(plan['root']).exists()


@pytest.mark.parametrize('failure', ['constructor', 'workflow', 'result', 'readback', None])
def test_runtime_channels_and_durable_exception_log_before_cli(plan, monkeypatch, failure):
    from modules.realityscan_interface import realityscan_cli as runtime
    result = probe.prepare(plan)
    detail = plan['cell_details']['report_control']
    channels = plan['runtime_channels']['report_control']
    log_path = Path(detail['python_log'])
    configure = runtime.RealityScanCLI._configure_channels
    before_env = {key: os.environ.get(key) for key in channels}

    class OfflineCLI:
        def __init__(self, logger, instance_name):
            assert log_path.is_file()
            assert 'runtime_channels=' in log_path.read_text()
            assert instance_name == plan['instance']
            assert {key: os.environ[key] for key in channels} == channels
            # Exercise the actual canonical path validator without a CLI instance,
            # child process, marker, lock, or RealityScan launch.
            run = SimpleNamespace(environment=dict(os.environ), run_id='offline-child')
            configure(self, run)
            assert run.parent_run_id == channels['RS_RUN_ID']
            assert run.control_file == channels['RS_CONTROL_FILE']
            assert run.event_file == channels['RS_EVENT_FILE']
            self.logger = logger
            logger.info('offline constructor evidence')
            if failure == 'constructor':
                raise RuntimeError('constructor sentinel error')

        def run_batch_script(self, batch, args, logs):
            self.logger.info('offline workflow evidence')
            if failure == 'workflow':
                raise RuntimeError('workflow sentinel error')
            if failure != 'readback':
                Path(detail['reports'][0]['path']).write_text(report_text(detail['expected']))
                (Path(plan['root']) / 'report_control/builtin_overview.html').write_text('offline control')
            return SimpleNamespace(success=failure != 'result', ownership_retained=False)

    monkeypatch.setattr(runtime, 'RealityScanCLI', OfflineCLI)
    if failure:
        with pytest.raises((RuntimeError, FileNotFoundError)):
            probe.run(result['manifest'], result['sha256'], 'report_control')
        text = log_path.read_text()
        assert 'Unhandled probe failure' in text and 'Traceback (most recent call last)' in text
        if failure in ('constructor', 'workflow'):
            assert f'{failure} sentinel error' in text
    else:
        evidence = probe.run(result['manifest'], result['sha256'], 'report_control')
        assert evidence['verdict'] == 'READBACK_ONLY_REQUIRES_SENTINEL_COMPARISON'
        assert 'Readback recorded' in log_path.read_text()
    assert {key: os.environ.get(key) for key in channels} == before_env
    attempt = json.loads((Path(plan['root']) / 'report_control/run_attempt.json').read_text())
    assert attempt['runtime_channels'] == channels
    before_log = log_path.read_bytes()
    with pytest.raises((ValueError, FileExistsError)):
        probe.run(result['manifest'], result['sha256'], 'report_control')
    assert log_path.read_bytes() == before_log
