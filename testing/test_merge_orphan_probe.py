"""Synthetic artifact replay only. These fixtures are NOT live RS evidence."""
import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import merge_zones as merge
from modules.source_inventory import source_fingerprint
from testing.test_merge_orphans import POLICY, scene, orphan, context


def bound(path):
    return {'path': str(path.resolve()), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


@pytest.fixture
def capture(tmp_path, monkeypatch):
    project = tmp_path / 'project'
    root = project / 'proc/tmp/probe'
    root.mkdir(parents=True)
    members, nav = scene()
    for name, x, y in [('inside.jpg', 2, 2), ('between.jpg', 8, 0), ('remote.jpg', 80, 80)]:
        orphan(nav, name, x, y)
    images = {}
    sources = []
    source = tmp_path / 'source'
    source.mkdir()
    for name in nav:
        path = root / name
        path.write_bytes(name.encode())
        images[name] = bound(path)
        original = source / name
        original.write_bytes(path.read_bytes())
        sources.append(bound(original))
    mask = root / 'between.jpg.mask.png'
    mask.write_bytes(b'synthetic mask')
    offered = ['inside.jpg', 'between.jpg']
    priors = {name: dict(zip(('x', 'y', 'z'), nav[name]['xyz'])) for name in nav}
    for prior in priors.values():
        prior.update(yaw=1, pitch=2, roll=3, accuracy=[1, 1, 1, 1, 1, 1],
                     position_prior=True, orientation_prior=True)
    expected = dict(policy=POLICY, epsg=32610, component_members=members, navigation=nav,
        orphan_ids=[*offered, 'remote.jpg'], images=images, masks={'between.jpg': bound(mask)},
        orphan_priors={n: priors[n] for n in offered}, source_files=sources,
        source_snapshots=[{'root': str(source), 'fingerprint': source_fingerprint(source)}])

    def rows(names):
        return [dict(path=images[n]['path'], priors=copy.deepcopy(priors[n]), feature_source=2 if n in offered else 1,
            mask_path=str(mask) if n == 'between.jpg' else None) for n in names]

    def component(names):
        return {'members': [dict(path=images[n]['path'], pose=[*nav[n]['xyz'], 1, 0, 0, 0, 1, 0, 0, 0, 1])
                            for n in names]}

    baseline = sum(members, [])
    before = dict(inputs=rows(baseline), components=[component(m) for m in members],
                  epsg=32610, vertical_datum=POLICY['vertical_datum'])
    prepared = copy.deepcopy(before)
    prepared['inputs'] = rows(baseline + offered)
    aligned = copy.deepcopy(prepared)
    aligned['components'] = [component(baseline + offered)]
    documents = dict(expected=expected, before=before, prepared=prepared, aligned=aligned)
    exe = tmp_path / 'RealityScan.exe'
    exe.write_bytes(b'SYNTHETIC TEST EXECUTABLE - NEVER EXECUTE')
    monkeypatch.setenv('RS_EXECUTABLE', str(exe))
    driver = Path(merge.__file__).resolve()
    scripts = driver.parent / 'modules/realityscan_interface/RS_CLI/Scripts'
    dependencies = [driver, scripts.parent.parent / 'realityscan_cli.py', exe]
    dependencies.extend(scripts / n for n in ('MergeZoneComponents.bat', 'startRealityScan.bat',
                                              'RuntimeAbortGuard.bat', 'SetVariables.bat'))
    manifest = dict(schema=1, selector_version=merge.ORPHAN_SELECTOR_VERSION,
                    dependencies=[bound(p) for p in dependencies], artifacts={})
    path = root / 'capture.json'

    def save():
        for key, document in documents.items():
            artifact = root / (key + '.json')
            artifact.write_text(json.dumps(document), encoding='utf-8')
            manifest['artifacts'][key] = bound(artifact)
        path.write_text(json.dumps(manifest), encoding='utf-8')

    save()
    return project, path, documents, manifest, save


def test_generate_and_replay_without_manual_checks(capture):
    project, path, _, _, _ = capture
    output = project / 'metadata/validation/orphan_import.json'
    result = merge.write_orphan_probe_evidence(path, output, project)
    assert result['status'] == 'passed'
    assert 'approved_by' not in output.read_text()
    assert merge.validate_orphan_probe_evidence(output, project, policy=POLICY) == result
    with pytest.raises(ValueError, match='new project-owned'):
        merge.write_orphan_probe_evidence(path, output, project)


@pytest.mark.parametrize('fault,failed', [
    ('component_prior', 'orphan_priors_only'),
    ('orphan_prior', 'orphan_priors_only'),
    ('component_pose', 'component_poses_preserved_before_align'),
    ('feature', 'separate_feature_modes'), ('mask', 'mask_selection_exact'),
    ('lost_camera', 'registration_identity_exact'),
    ('frame', 'output_frame_preserved'), ('remote', 'spatial_controls_exact'),
])
def test_measured_failures_override_forged_passed_status(capture, fault, failed):
    project, path, docs, manifest, save = capture
    prepared = docs['prepared']
    if fault == 'component_prior':
        prepared['inputs'][0]['priors']['x'] += 1
    elif fault == 'orphan_prior':
        prepared['inputs'][-1]['priors']['x'] = 0
    elif fault == 'component_pose':
        prepared['components'][0]['members'][0]['pose'][0] += 1
    elif fault == 'feature':
        prepared['inputs'][-1]['feature_source'] = 0
    elif fault == 'mask':
        prepared['inputs'][-1]['mask_path'] = None
    elif fault == 'lost_camera':
        docs['aligned']['components'][0]['members'].pop(0)
    elif fault == 'frame':
        docs['aligned']['epsg'] = 32611
    elif fault == 'remote':
        row = copy.deepcopy(prepared['inputs'][-1])
        row['path'] = docs['expected']['images']['remote.jpg']['path']
        row['mask_path'] = None
        prepared['inputs'].append(row)
    manifest.update(status='passed', approved_by='ignored', checks={failed: True})
    save()
    result = merge.replay_orphan_probe(path, project)
    assert result['status'] == 'failed' and failed in result['failures']


@pytest.mark.parametrize('fault', ['artifact', 'source', 'dependency', 'image', 'mask'])
def test_hash_bindings_detect_changed_bytes(capture, fault):
    project, path, docs, manifest, _ = capture
    record = {'artifact': manifest['artifacts']['prepared'],
              'source': docs['expected']['source_files'][0],
              'dependency': manifest['dependencies'][2],
              'image': docs['expected']['images']['inside.jpg'],
              'mask': docs['expected']['masks']['between.jpg']}[fault]
    Path(record['path']).write_bytes(b'changed')
    with pytest.raises(ValueError, match='content changed'):
        merge.replay_orphan_probe(path, project)


@pytest.mark.parametrize('field', ['feature_source', 'mask_path', 'priors'])
def test_missing_readback_cannot_be_filled_from_commands(capture, field):
    project, path, docs, _, save = capture
    docs['prepared']['inputs'][0].pop(field)
    save()
    with pytest.raises((ValueError, KeyError)):
        merge.replay_orphan_probe(path, project)


def test_cached_verdict_ignored_and_policy_or_executable_change_refused(capture, monkeypatch):
    project, path, docs, _, save = capture
    output = project / 'orphan_import.json'
    merge.write_orphan_probe_evidence(path, output, project)
    docs['prepared']['inputs'][-1]['feature_source'] = 0
    save()
    evidence = json.loads(output.read_text())
    evidence['capture_manifest'] = bound(path)  # Even re-pinning cannot hide the measured failure.
    output.write_text(json.dumps(evidence))
    with pytest.raises(ValueError, match='checks failed'):
        merge.validate_orphan_probe_evidence(output, project)
    with pytest.raises(ValueError, match='different policy'):
        merge.replay_orphan_probe(path, project, policy=dict(POLICY, component_features=0))
    with pytest.raises(ValueError, match='different UTM frame'):
        merge.replay_orphan_probe(path, project, epsg=32755)
    monkeypatch.delenv('RS_EXECUTABLE')
    with pytest.raises(ValueError, match='RS_EXECUTABLE'):
        merge.replay_orphan_probe(path, project)


def test_new_source_sidecar_is_detected(capture):
    project, path, docs, _, _ = capture
    source = Path(docs['expected']['source_snapshots'][0]['root'])
    (source / 'unexpected.xmp').write_text('unexpected sidecar')
    with pytest.raises(ValueError, match='source tree changed'):
        merge.replay_orphan_probe(path, project)


def test_probe_requires_inside_between_and_remote_controls(capture):
    project, path, docs, _, save = capture
    docs['expected']['navigation']['remote.jpg']['xyz'] = docs['expected']['navigation']['inside.jpg']['xyz']
    docs['expected']['orphan_priors']['remote.jpg'] = copy.deepcopy(docs['expected']['orphan_priors']['inside.jpg'])
    save()
    result = merge.replay_orphan_probe(path, project)
    assert result['status'] == 'failed'
    assert 'spatial_controls_exact' in result['failures']


def test_attempt_replays_nested_artifacts_before_any_write(tmp_path, monkeypatch):
    components, ctx = context(tmp_path)
    ctx.update(review_store=SimpleNamespace(selection=lambda: []), selection_hash='approved',
               project_root=str(tmp_path))
    ctx['policy'] = dict(ctx['policy'], cli_probe_evidence=str(tmp_path / 'proof.json'))
    ctx['fingerprint'] = dict(selection=None, navigation=None, policy_file=None, cli_probe=None,
                             cli_probe_replay='old')
    monkeypatch.setattr('modules.source_inventory.approval_token', lambda _: 'approved')
    def changed(*args, **kwargs):
        raise ValueError('orphan probe artifact content changed')
    monkeypatch.setattr(merge, 'validate_orphan_probe_evidence', changed)
    output = tmp_path / 'attempt'
    with pytest.raises(ValueError, match='artifact content changed'):
        merge.prepare_orphan_attempt(ctx, components, output)
    assert not output.exists()
