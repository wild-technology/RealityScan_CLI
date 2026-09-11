"""Synthetic native report fixtures. No RS launch and no field-validation claim."""
import copy
import csv
import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

import merge_zones as merge
from testing import rs_merge_orphan_probe as probe
from testing.test_merge_orphans import POLICY, scene, orphan, component


@pytest.fixture
def planned(tmp_path, monkeypatch):
    camera_profile = probe.camera_registry.identify('cammid_001.jpg')
    monkeypatch.setattr(probe.camera_registry, 'identify', lambda _: camera_profile)
    project = tmp_path / 'project'
    camera = project / 'proc/selections/current/images/cam'
    camera.mkdir(parents=True)
    members, nav = scene()
    for name, x, y in [('inside.jpg', 2, 2), ('between.jpg', 8, 0), ('remote.jpg', 80, 80)]:
        orphan(nav, name, x, y)
    images = {}
    for index, name in enumerate(nav):
        path = camera / name
        Image.new('RGB', (16, 16), (index * 10, 0, 0)).save(path)
        images[name] = probe.bound(path)
    mask = camera / 'between.jpg.mask.png'
    Image.fromarray(np.pad(np.full((8, 8), 255, np.uint8), 4)).save(mask)
    masks = {'between.jpg': probe.bound(mask)}
    root = camera.parent.parent
    selection = root / 'selection.json'
    selection.write_text(json.dumps({'images_root': str(camera.parent)}))
    policy = project / 'policy.json'
    policy.write_text(json.dumps(POLICY))
    log = root / 'navigation/flight_log_10N_UTM.txt'
    log.parent.mkdir()
    rows = {n: [n, *map(str, nav[n]['xyz']), *(['1'] * 10)] for n in nav}
    header = ['filename', 'X (East)', 'Y (North)', 'Alt'] + [str(i) for i in range(10)]
    with log.open('w', newline='') as stream:
        writer = csv.writer(stream, delimiter=';')
        writer.writerow(header)
        writer.writerows(rows.values())
    components = []
    for index, names in enumerate(members):
        comp = component(project / 'proc', f'c{index}', names)
        registration = Path(comp['rsalign']).parent / 'identity' / (Path(comp['rsalign']).stem + '.csv')
        with registration.open('w', newline='') as stream:
            stream.write(f'#cameras {len(names)}\n')
            csv.writer(stream).writerows([[images[n]['path'], 0, 0, 0] for n in names])
        Path(comp['rsalign'] + '.manifest.json').write_text(json.dumps(dict(comp, schema=1)))
        components.append(comp)
    ctx = dict(policy=POLICY, epsg=32610, navigation=nav, images=images, masks=masks,
        rows=rows, header=header, flight_log=str(log), zone=(10, 'N'), project_root=str(project))
    monkeypatch.setattr(merge, 'load_orphan_context', lambda *a, **kw: copy.deepcopy(ctx))
    install = tmp_path / 'install'
    install.mkdir()
    for name in ('RealityScan.exe', 'flightlogs.xml'):
        (install / name).write_text('SYNTHETIC - NEVER EXECUTE')
    for name in ('images', 'cameras', 'components', 'basic'):
        path = install / f'Help/en-US/appbasics/reports_fav_{name}.htm'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('synthetic pinned Help fixture')
    monkeypatch.setattr(probe, 'RealityScanCLI', lambda *a, **kw: pytest.fail('RS launcher reached'))
    args = dict(project_root=str(project), selection_manifest=str(selection), policy=str(policy),
                components_root=str(project / 'proc'),
                component=[c['rsalign'] for c in components], install_dir=str(install),
                instance='OrphanProbeTest', run_name='tiny', reserve_gib=1)
    return probe.build_plan(**args), args


def raw_state(plan, stage, ids):
    result = ['ORPHAN_NATIVE=1']
    image_paths = {n: plan['images'][n]['path'] for n in ids}
    if stage != 'before':
        image_paths.update({Path(p).name: p for p in Path(plan['inputs']['list']).read_text().splitlines()})
    for index, name in enumerate(sorted(ids)):
        path = Path(image_paths[name])
        p = {key: '0' for key in probe.PRIOR_FIELDS}
        p.update(inputIsPositionPrior='true', inputIsOrientationPrior='true', inputIsLatLong='false', inputCS='epsg:32610')
        camera = probe.camera_registry.identify(name)
        p.update(calibrationGroup=camera.calibration_group, distortionGroup=camera.lens_distortion_group,
                 inputF=str(camera.focal_length_35mm), inputLensModel=camera.distortion_model,
                 inputCalibrationPriorType='20642')
        for key, value in zip(('X', 'Y', 'Z'), plan['navigation'][name]['xyz']):
            p['input' + key] = str(value)
        for key in ('Yaw', 'Pitch', 'Roll'):
            p['input' + key] = '1'
        for key in ('X', 'Y', 'Z', 'Yaw', 'Pitch', 'Roll'):
            p['inputAccuracy' + key] = '1'
        result.append(f'IMAGE|{index}|{path.parent}|{path.stem}|{path.suffix}')
        result.append(f'PRIOR|{index}|' + '|'.join(p[k] for k in probe.PRIOR_FIELDS))
    members = [sorted(ids)] if stage == 'aligned' else plan['members']
    for index, names in enumerate(members):
        result.append(f'COMPONENT|c{index}|{len(names)}|epsg:32610|true')
        for name in names:
            pose = [*plan['navigation'][name]['xyz'], 1, 0, 0, 0, 1, 0, 0, 0, 1]
            result.append(f'CAMERA|c{index}|{image_paths[name]}|' + '|'.join(map(str, pose)))
    return '\n'.join(result + ['END_ORPHAN'])


def fake_recorder(monkeypatch, *, feature='correct', corrupt_pose=False, corrupt_focal=False):
    calls = []
    def run(plan, stage, commands):
        calls.append((stage, commands))
        root = Path(plan['root'])
        directory = root / stage
        directory.mkdir()
        masks = directory / 'masks'
        masks.mkdir()
        ids = set().union(*map(set, plan['members']))
        if stage != 'before':
            ids.update(plan['offered'])
        text = raw_state(plan, stage, ids)
        if corrupt_pose and stage == 'prepared':
            text = text.replace('|500000|', '|500001|')
        if corrupt_focal and stage == 'prepared':
            rows = text.splitlines()
            for i, row in enumerate(rows):
                fields = row.split('|')
                if fields[0] == 'PRIOR':
                    offset = 2 + probe.PRIOR_FIELDS.index('inputF')
                    fields[offset] = str(float(fields[offset]) * 36)
                    rows[i] = '|'.join(fields)
            text = '\n'.join(rows)
        (directory / 'state.html').write_text(text)
        (directory / 'scene.rsproj').write_bytes(b'synthetic scene')
        probe.write_text(directory / 'record.bat', probe.batch_text(commands), crlf=True)
        for name in set(plan['masks']) & ids:
            (masks / (name + '.mask.png')).write_bytes(Path(plan['masks'][name]['path']).read_bytes())
        paths = sorted([plan['images'][n]['path'] for n in ids if n not in plan['offered']] +
                       (Path(plan['inputs']['list']).read_text().splitlines() if stage != 'before' else []))
        if stage != 'before':
            for index, path in enumerate(paths):
                value = 2 if Path(path).name in plan['offered'] else plan['policy']['component_features']
                (directory / f'feature_{index}.html').write_text(f'ORPHAN_NATIVE=1\nFEATURE|{value}\nEND_ORPHAN')
        if stage == 'prepared':
            for name, value in [('control_a0', 0), ('control_b2', 2), ('control_a0_again', 0), ('control_b2_again', 2)]:
                if feature == 'missing':
                    value = 'MISSING'
                elif feature == 'global':
                    value = 2
                (directory / (name + '.html')).write_text(f'ORPHAN_NATIVE=1\nFEATURE|{value}\nEND_ORPHAN')
    monkeypatch.setattr(probe, 'run_stage', run)
    return calls


def test_plan_prepare_are_offline_bounded_and_use_shared_spatial_selector(planned):
    plan, _ = planned
    assert plan['controls'] == ['inside.jpg', 'between.jpg', 'remote.jpg']
    assert not Path(plan['root']).exists()
    result = probe.prepare(plan)
    prepared = probe.load_plan(result['path'], result['sha256'])
    assert len(Path(prepared['inputs']['list']).read_text().splitlines()) == 2
    assert 'remote' not in Path(prepared['inputs']['flight_log']).read_text()
    assert Path(plan['root'], 'mask_export.xml').read_text().strip() == '<Configuration />'
    with pytest.raises(ValueError, match='Fresh'):
        probe.prepare(plan)


def test_automated_native_record_and_replay_no_manual_verdict(planned, monkeypatch):
    plan, _ = planned
    manifest = probe.prepare(plan)
    calls = fake_recorder(monkeypatch)
    result = probe.record(manifest['path'], manifest['sha256'])
    assert result['status'] == 'passed'
    assert [s for s, _ in calls] == ['before', 'prepared', 'aligned']
    assert sum(cmd == '-align' for _, commands in calls for cmd in commands) == 1
    commands = calls[1][1]
    assert commands.index('-set "ifKGrp=0"') < next(i for i, c in enumerate(commands) if c.startswith('-add '))
    assert '-editInputSelection "inpMaskOpts=3"' in commands
    aligned_commands = calls[2][1]
    use = '-editInputSelection "inpMaskOpts=3"'
    assert aligned_commands.index(use) < aligned_commands.index('-align')
    assert use in aligned_commands[aligned_commands.index('-align') + 1:]
    assert probe.verify(manifest['path'], manifest['sha256'])['status'] == 'passed'
    evidence = Path(plan['root']) / 'orphan_import.json'
    assert 'approved_by' not in evidence.read_text()
    assert merge.validate_orphan_probe_evidence(evidence, plan['project_root'], policy=POLICY, epsg=32610)['native_recording']
    # A forged normalized pass is rejected on replay from original native reports.
    normalized = Path(plan['root']) / 'prepared.json'
    data = json.loads(normalized.read_text())
    data['inputs'][0]['feature_source'] = 2
    normalized.write_text(json.dumps(data))
    with pytest.raises(ValueError, match='differs from native'):
        probe.verify(manifest['path'], manifest['sha256'])


@pytest.mark.parametrize('feature', ['missing', 'global'])
def test_unobservable_features_stop_before_align(planned, monkeypatch, feature):
    plan, _ = planned
    manifest = probe.prepare(plan)
    calls = fake_recorder(monkeypatch, feature=feature)
    result = probe.record(manifest['path'], manifest['sha256'])
    assert result['status'] == 'incomplete' and result['unavailable'] == ['feature_source']
    assert [s for s, _ in calls] == ['before', 'prepared']
    assert not Path(plan['root'], 'orphan_import.json').exists()
    assert probe.verify(manifest['path'], manifest['sha256'])['status'] == 'incomplete'


def test_changed_original_pose_stops_before_align(planned, monkeypatch):
    plan, _ = planned
    manifest = probe.prepare(plan)
    calls = fake_recorder(monkeypatch, corrupt_pose=True)
    with pytest.raises(ValueError, match='priors/poses'):
        probe.record(manifest['path'], manifest['sha256'])
    assert [s for s, _ in calls] == ['before', 'prepared']


def test_plan_pins_bytes_and_tiny_original_locations(planned):
    plan, args = planned
    manifest = probe.prepare(plan)
    Path(plan['policy_file']).write_text('{}')
    with pytest.raises(ValueError, match='changed'):
        probe.load_plan(manifest['path'], manifest['sha256'])
    with pytest.raises(ValueError, match='Exactly two'):
        probe.build_plan(**dict(args, component=[]))


def test_generated_batch_guards_mutations_and_never_waits_after_quit():
    text = probe.batch_text(['-newScene'])
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if '%RealityScan% -delegateTo' in line or 'call "' in line and 'startRealityScan.bat' in line:
            assert 'RuntimeAbortGuard.bat" || exit /b 1223' in lines[i - 1]
    assert 'call :run -quit' not in text
    assert '-waitCompleted' in text


def test_mask_comparison_requires_exact_identity_pixels_and_coverage(tmp_path):
    expected = tmp_path / 'expected.png'
    Image.new('L', (8, 8), 255).save(expected)
    folder = tmp_path / 'export'
    folder.mkdir()
    snapshot = {'inputs': [{'path': str(tmp_path / 'camera.jpg'), 'mask_path': None}]}
    records = {'camera.jpg': probe.bound(expected)}
    with pytest.raises(ValueError, match='Missing exported'):
        probe.read_masks(folder, snapshot, records)
    Image.new('L', (8, 8), 0).save(folder / 'camera.jpg.mask.png')
    with pytest.raises(ValueError, match='pixels differ'):
        probe.read_masks(folder, snapshot, records)
    (folder / 'camera.jpg.mask.png').write_bytes(expected.read_bytes())
    probe.read_masks(folder, snapshot, records)
    assert snapshot['inputs'][0]['mask_path'] == str(expected)


def test_record_cli_requires_explicit_execution_switch(monkeypatch):
    monkeypatch.setattr('sys.argv', ['probe', 'record', '--manifest', 'x', '--expected-sha256', 'a' * 64])
    with pytest.raises(SystemExit) as exc:
        probe.main()
    assert exc.value.code == 2


def test_mask_free_probe_does_not_require_retired_source_masks(planned, monkeypatch):
    _, args = planned
    original_loader = merge.load_orphan_context
    def without_masks(*a, **kw):
        context = original_loader(*a, **kw)
        context['masks'] = {}
        return context
    monkeypatch.setattr(merge, 'load_orphan_context', without_masks)
    plan = probe.build_plan(**args)
    assert plan['masks'] == {}
    manifest = probe.prepare(plan)
    fake_recorder(monkeypatch)
    result = probe.record(manifest['path'], manifest['sha256'])
    assert result['status'] == 'passed'
    assert 'feature exclusion or polarity' in result['limits'][0]
    assert Path(plan['root'], 'inputs/masks.txt').read_text() == ''


def test_native_calibration_failure_stops_before_alignment(planned, monkeypatch):
    plan, _ = planned
    manifest = probe.prepare(plan)
    calls = fake_recorder(monkeypatch, corrupt_focal=True)
    with pytest.raises(ValueError, match='calibration'):
        probe.record(manifest['path'], manifest['sha256'])
    assert [s for s, _ in calls] == ['before', 'prepared']


def test_unknown_orphan_calibration_refuses_before_copies(planned):
    plan, _ = planned
    plan['calibration_profiles'][plan['offered'][0]] = None
    directory = Path(plan['project_root']) / 'proc/unknown_calibration'
    directory.mkdir()
    with pytest.raises(ValueError, match='no approved native calibration'):
        merge.stage_orphan_inputs(plan, plan['offered'], directory)
    assert list(directory.iterdir()) == []


def test_probe_refuses_changed_occlusion_before_preparing_copies(planned):
    plan, _ = planned
    plan['occlusion'] = {'decision': 'old approved mask decision'}
    with pytest.raises(ValueError, match='occlusion decision changed'):
        probe.prepare(plan)
    assert not Path(plan['root']).exists()
