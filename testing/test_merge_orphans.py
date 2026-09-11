"""Offline pair geometry/dispatch tests. No claim of live CLI validation."""
import copy
import csv
import hashlib
import json
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

import merge_zones as merge

LOG = logging.getLogger(__name__)
POLICY = dict(horizontal_margin_m=0.5, vertical_margin_m=1.0, footprint_link_m=6.0,
              max_corridor_m=15.0, max_offered=20, vertical_datum='ellipsoidal_m', component_features=1)


def scene():
    members = [['a0.jpg', 'a1.jpg', 'a2.jpg', 'a3.jpg'], ['b0.jpg', 'b1.jpg', 'b2.jpg', 'b3.jpg']]
    nav = {}
    for names, x in zip(members, (500000, 500012)):
        for name, xy in zip(names, [(x, 0), (x, 4), (x + 4, 0), (x + 4, 4)]):
            nav[name] = dict(xyz=[xy[0], 4500000 + xy[1], -100], epsg=32610, vertical_datum='ellipsoidal_m')
    return members, nav


def orphan(nav, name, x, y, z=-100):
    nav[name] = dict(xyz=[500000 + x, 4500000 + y, z], epsg=32610, vertical_datum='ellipsoidal_m')


def test_within_between_outside_and_remote_island():
    members, nav = scene()
    for name, x, y in [('inside', 2, 2), ('between', 8, 0), ('outside', 8, 8), ('island', 80, 80)]:
        orphan(nav, name, x, y)
    result = merge.select_pair_orphans(members, nav, ['inside', 'between', 'outside', 'island'], epsg=32610, policy=POLICY)
    assert result['offered_ids'] == ['between', 'inside']
    assert result['excluded_ids'] == ['island', 'outside']
    assert result['spatial_reasons']['between'] == 'between_footprints'
    assert result['spatial_reasons']['inside'] == 'within_footprint_1'


def test_depth_not_global_depth_range_and_corridor_interpolates():
    members, nav = scene()
    for name in members[1]:
        nav[name]['xyz'][2] = -110
    orphan(nav, 'bridge', 8, 0, -105)
    orphan(nav, 'wrongdepth', 2, 2, -110)
    result = merge.select_pair_orphans(members, nav, ['bridge', 'wrongdepth'], epsg=32610, policy=POLICY)
    assert result['offered_ids'] == ['bridge']


def test_uncertainty_margin_explicit_and_unknown_orphans_remain_global():
    members, nav = scene()
    orphan(nav, 'near', -0.4, 2)
    candidates = ['near', 'missing']
    before = copy.deepcopy((members, nav, candidates))
    narrow = merge.select_pair_orphans(members, nav, candidates, epsg=32610,
                                       policy=dict(POLICY, horizontal_margin_m=0.1))
    wide = merge.select_pair_orphans(members, nav, candidates, epsg=32610, policy=POLICY)
    assert narrow['offered_ids'] == [] and wide['offered_ids'] == ['near']
    assert wide['spatial_reasons']['missing'] == 'unknown_navigation'
    assert (members, nav, candidates) == before


@pytest.mark.parametrize('fault', ['missing', 'nan', 'frame', 'datum', 'membership', 'three_components'])
def test_insufficient_component_evidence_refuses(fault):
    members, nav = scene()
    if fault == 'missing':
        del nav[members[0][0]]
    elif fault == 'nan':
        nav[members[0][0]]['xyz'][2] = float('nan')
    elif fault == 'frame':
        nav[members[0][0]]['epsg'] = 32611
    elif fault == 'datum':
        nav[members[0][0]]['vertical_datum'] = 'unknown'
    elif fault == 'membership':
        members[0] = members[0][:2]
    else:
        members.append(members[0])
    with pytest.raises(ValueError):
        merge.select_pair_orphans(members, nav, [], epsg=32610, policy=POLICY)


def test_curved_track_does_not_fill_global_hull_or_island_gap():
    a = [(x, 0) for x in range(7)] + [(6, y) for y in range(1, 7)] + [(x, 6) for x in range(6)]
    b = [(10, y) for y in range(3)]
    members, nav = [[], []], {}
    for index, points in enumerate((a, b)):
        for number, (x, y) in enumerate(points):
            name = f'{index}_{number}'
            members[index].append(name)
            orphan(nav, name, x, y)
    orphan(nav, 'hollow', 3, 3)
    orphan(nav, 'ontrack', 3.5, 0)
    result = merge.select_pair_orphans(members, nav, ['hollow', 'ontrack'], epsg=32610,
        policy=dict(POLICY, footprint_link_m=1.5))
    assert result['offered_ids'] == ['ontrack']


def test_corridor_length_and_offered_caps_are_bounded():
    members, nav = scene()
    orphan(nav, 'between', 8, 0)
    result = merge.select_pair_orphans(members, nav, ['between'], epsg=32610,
        policy=dict(POLICY, max_corridor_m=2))
    assert result['corridor_xyz'] is None and not result['offered_ids']
    orphan(nav, 'inside', 2, 2)
    result = merge.select_pair_orphans(members, nav, ['between', 'inside'], epsg=32610,
        policy=dict(POLICY, max_offered=1))
    assert result['refused'] and result['refusal'] == 'max_offered_exceeded'


def test_remote_component_island_does_not_sweep_global_bbox():
    members, nav = scene()
    members[0].append('far_registered')
    orphan(nav, 'far_registered', 100, 100)
    orphan(nav, 'bbox_only', 50, 50)
    orphan(nav, 'local', 2, 2)
    result = merge.select_pair_orphans(members, nav, ['bbox_only', 'local'], epsg=32610, policy=POLICY)
    assert result['offered_ids'] == ['local']


def test_legitimate_overlap_is_retained_and_order_does_not_change_corridor():
    members, nav = scene()
    orphan(nav, 'within', 2, 2)
    a = merge.select_pair_orphans(members, nav, ['within'], epsg=32610, policy=POLICY)
    b = merge.select_pair_orphans([list(reversed(m)) for m in members], nav, ['within'], epsg=32610, policy=POLICY)
    assert a == b
    for name in members[1]:
        nav[name]['xyz'][0] -= 10
    orphan(nav, 'overlap', 3, 2)
    result = merge.select_pair_orphans(members, nav, ['overlap'], epsg=32610, policy=POLICY)
    assert result['offered_ids'] == ['overlap']


def test_project_loader_binds_current_manifest_masks_and_membership(tmp_path, monkeypatch):
    from modules.source_inventory import SourceItem, SourceInventory, approval_token
    from modules.project_reviews import ReviewStore
    members, nav = scene()
    comps = [component(tmp_path, f'c{i}', names) for i, names in enumerate(members)]
    project = tmp_path / 'project'
    root = project / 'proc/selections/current/images'
    camera = root / 'cam'
    camera.mkdir(parents=True)
    (project / '.rovscan-owner.json').write_text(json.dumps({'project_id': 'project'}))
    names = sum(members, []) + ['within.jpg']
    orphan(nav, 'within.jpg', 2, 2)
    inventory = []
    images = []
    for name in names:
        path = camera / name
        path.write_bytes(name.encode())
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        inventory.append(SourceItem(str(tmp_path / 'source' / name), name, 'image', len(name), 1,
                                    camera='cam', sha256=sha, included=True))
        images.append({'path': str(path), 'sha256': sha})
    mask = camera / 'within.jpg.mask.png'
    mask.write_bytes(b'mask')
    sha = hashlib.sha256(mask.read_bytes()).hexdigest()
    inventory.append(SourceItem(str(tmp_path / 'source/mask.png'), 'mask.png', 'mask', 4, 1,
        camera='cam', sha256=sha, included=True, mask_for=str(tmp_path / 'source/within.jpg')))
    inventory = SourceInventory(inventory, source_root=tmp_path / 'source', fingerprint='a' * 64)
    log = root.parent / 'navigation/flight_log_10N_UTM.txt'
    log.parent.mkdir()
    with log.open('w', newline='') as stream:
        writer = csv.writer(stream, delimiter=';')
        writer.writerow(['filename', 'X (East)', 'Y (North)', 'Alt'] + [str(i) for i in range(10)])
        writer.writerows([[name, *map(str, nav[name]['xyz']), *(['1'] * 10)] for name in names])
    manifest = dict(schema=1, project_id='project', selection_hash=approval_token(inventory),
        quality_review_hash='b' * 64, spatial_review_hash='b' * 64, images_root=str(root),
        flight_log=str(log), flight_log_sha256=hashlib.sha256(log.read_bytes()).hexdigest(), epsg=32610,
        images=images, masks=[{'path': str(mask), 'sha256': sha}])
    selection = root.parent / 'selection.json'
    selection.write_text(json.dumps(manifest))
    policy = project / 'policy.json'
    policy.write_text(json.dumps(POLICY))
    monkeypatch.setattr(ReviewStore, 'selection', lambda self: inventory)
    monkeypatch.setattr(ReviewStore, 'require_approved', lambda *args: {'assessment_hash': 'b' * 64})
    context = merge.load_orphan_context(selection, policy, comps)
    assert context['registered'] == set(sum(members, []))
    assert not context['cli_ready']
    assert context['masks']['within.jpg']['sha256'] == sha
    proof = project / 'probe.json'
    proof.write_text(json.dumps({'status': 'passed', 'approved_by': 'SYNTHETIC TEST ONLY',
        'selector_version': merge.ORPHAN_SELECTOR_VERSION,
        'checks': {key: True for key in merge.orphan_probe_plan()['checks']}}))
    policy.write_text(json.dumps(dict(POLICY, cli_probe_evidence=str(proof))))
    with pytest.raises(ValueError, match='replayable schema 2'):
        merge.load_orphan_context(selection, policy, comps)
    # Full artifact replay is exercised separately; here isolate the loader's
    # current-manifest and before-write provenance wiring.
    monkeypatch.setattr(merge, 'validate_orphan_probe_evidence',
                        lambda *a, **kw: {'fingerprint': 'synthetic-replay'})
    probed = merge.load_orphan_context(selection, policy, comps)
    assert probed['cli_ready']
    proof.write_text('{}')
    with pytest.raises(ValueError, match='provenance changed'):
        merge.prepare_orphan_attempt(probed, comps, project / 'changed_attempt')
    assert not (project / 'changed_attempt').exists()
    policy.write_text(json.dumps(POLICY))
    manifest['masks'] = []
    selection.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='mask'):
        merge.load_orphan_context(selection, policy, comps)


def component(tmp_path, name, members):
    directory = tmp_path / name
    directory.mkdir()
    path = directory / (name + '.rsalign')
    path.write_bytes(b'offline component')
    (directory / 'identity').mkdir()
    registration = directory / 'identity' / (name + '.csv')
    with registration.open('w', newline='') as stream:
        stream.write(f'#cameras {len(members)}\n')
        csv.writer(stream).writerows([[m, 0, 0, 0] for m in members])
    return dict(zone=name, component=name, images=list(members), camera_count=len(members), rsalign=str(path))


def test_registration_file_is_required_and_manifest_must_agree(tmp_path):
    comp = component(tmp_path, 'c', ['a', 'b', 'c'])
    assert merge.measured_component_ids(comp) == ['a', 'b', 'c']
    comp['images'] = ['a', 'b', 'invented']
    with pytest.raises(ValueError, match='differs'):
        merge.measured_component_ids(comp)


def context(tmp_path, ready=True):
    members, nav = scene()
    comps = [component(tmp_path, f'c{i}', names) for i, names in enumerate(members)]
    source = tmp_path / 'selection'
    source.mkdir()
    images = {}
    for name, x, y in [('within.jpg', 2, 2), ('remote.jpg', 90, 90)]:
        path = source / name
        path.write_bytes(name.encode())
        images[name] = {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
        orphan(nav, name, x, y)
    mask = source / 'within.jpg.mask.png'
    mask.write_bytes(b'mask fixture')
    header = ['filename'] + [f'column{i}' for i in range(13)]
    rows = {name: [name, *map(str, nav[name]['xyz']), *(['0'] * 10)] for name in images}
    return comps, dict(policy=POLICY, epsg=32610, navigation=nav, images=images,
        masks={'within.jpg': {'path': str(mask), 'sha256': hashlib.sha256(mask.read_bytes()).hexdigest()}},
        rows=rows, header=header, registered=set(sum(members, [])), cli_ready=ready,
        probe_plan=merge.orphan_probe_plan(), flight_log='flight_log_10N_UTM.txt', zone=(10, 'N'))


def test_attempt_copies_only_offered_pixels_masks_and_priors(tmp_path):
    comps, ctx = context(tmp_path)
    before = {p: p.read_bytes() for p in (tmp_path / 'selection').iterdir()}
    evidence, payload = merge.prepare_orphan_attempt(ctx, comps, tmp_path / 'attempt_inputs')
    assert evidence['offered_ids'] == ['within.jpg']
    assert evidence['excluded_ids'] == ['remote.jpg']
    listed = Path(payload['list']).read_text().splitlines()
    assert len(listed) == 1 and Path(listed[0]).read_bytes() == b'within.jpg'
    rows = list(csv.reader(Path(payload['flight_log']).open(), delimiter=';'))
    assert len(rows) == 2 and rows[1][0] == listed[0]
    assert 'remote' not in Path(payload['flight_log']).read_text()
    assert Path(payload['masks']).read_text().startswith(listed[0] + '|')
    assert all(p.read_bytes() == content for p, content in before.items())
    assert 'remote.jpg' not in ctx['registered']


@pytest.mark.parametrize('ready,capacity,reason', [(False, 100, 'orphan_cli_probe_required'),
                                                (True, 0, 'orphan_scene_ceiling_exceeded')])
def test_unverified_cli_or_over_capacity_prepares_evidence_without_copies(tmp_path, ready, capacity, reason):
    comps, ctx = context(tmp_path, ready)
    evidence, payload = merge.prepare_orphan_attempt(ctx, comps, tmp_path / 'attempt_inputs', scene_capacity=capacity)
    assert payload is None and evidence['refusal'] == reason
    assert not (tmp_path / 'attempt_inputs/images').exists()
    assert (tmp_path / 'attempt_inputs/orphan_selection.json').exists()


def test_added_orphans_do_not_hide_loss_or_count_as_parent_components():
    comps = [dict(zone='z', component='a', images=['a', 'b', 'c'], camera_count=3),
             dict(zone='z', component='b', images=['d', 'e', 'f'], camera_count=3)]
    results, confidence = merge.attribute_result(comps, [6], LOG, loss_tolerance=1,
        peel_members=[['a', 'b', 'd', 'e', 'f', 'orphan']], offered_members=['orphan'])
    assert confidence == 'exact' and len(results[0]['inputs']) == 2
    assert results[0]['camera_count'] == 6 and results[0]['loss'] == 1
    assert results[0]['collapsed'] == 0 and results[0]['offered_registered'] == ['orphan']
    assert 'orphan' in results[0]['members']


def test_orphan_only_component_does_not_count_as_fusion():
    comp = dict(zone='z', component='a', images=['a', 'b', 'c'], camera_count=3)
    results, confidence = merge.attribute_result([comp], [3, 1], LOG,
        peel_members=[['a', 'b', 'c'], ['orphan']], offered_members=['orphan'])
    assert confidence == 'exact' and results[1]['residual']
    assert results[1]['inputs'] == []


def test_workflow_scoped_priors_cannot_overwrite_component_navigation(monkeypatch):
    captured = {}
    def call(*args):
        import os
        captured.update(os.environ)
        return SimpleNamespace(success=True)
    monkeypatch.delenv('RS_ALIGN_POOL_DIR', raising=False)
    monkeypatch.setenv('RS_MERGE_FLIGHT_LOG', 'stale_component_log')
    cli = SimpleNamespace(run_batch_script=call)
    payload = dict(has_orphans=True, component_features=1, list='offered.imagelist', masks='masks.txt',
                   root='owned/images', flight_log='orphans.txt', params='orphan_params.xml')
    merge.run_merge_workflow(cli, 'components', 'out', 'name', 'align', [], 'component_log', 'params',
                             '', '', True, LOG, orphan_inputs=payload)
    assert 'RS_MERGE_FLIGHT_LOG' not in captured
    assert captured['RS_MERGE_ORPHAN_LOG'] == 'orphans.txt'
    assert captured['RS_MERGE_COMPONENT_FEATURES'] == '1'
    merge.run_merge_workflow(cli, 'components', 'out', 'name', 'assemble', [], None, None, '', '', False, LOG)
    import os
    assert 'RS_MERGE_ORPHAN_LIST' not in os.environ


def test_batch_orders_separate_features_masks_and_orphan_only_log():
    text = (Path(merge.__file__).parent / 'modules/realityscan_interface/RS_CLI/Scripts/MergeZoneComponents.bat').read_text()
    assert text.index('-setFeatureSource %RS_MERGE_COMPONENT_FEATURES%') < text.index('-add "%RS_MERGE_ORPHAN_LIST%"')
    assert text.index('-importFlightLog "%RS_MERGE_ORPHAN_LOG%"') < text.index('-setImagesLayer "%%J" mask')
    assert text.index('-setImagesLayer "%%J" mask') < text.index('-setFeatureSource 2')
    assert 'if defined RS_MERGE_FLIGHT_LOG goto :argfail' in text
    assert text.index('-setImagesLayer "%%J" mask') < text.index('-editInputSelection "inpMaskOpts=3"')
    assert 'call :run -selectAllImages || goto :fail\n    call :run -editInputSelection "inpMaskOpts=3"' in text


def test_project_batch_refuses_missing_occlusion_binding_before_settings_or_boot():
    text = (Path(merge.__file__).parent / 'modules/realityscan_interface/RS_CLI/Scripts/MergeZoneComponents.bat').read_text()
    for key in ('RS_OCCLUSION_MANIFEST', 'RS_OCCLUSION_MANIFEST_SHA256'):
        guard = f'if defined RS_SELECTION_MANIFEST if not defined {key} goto :occlusionRefused'
        assert text.index(guard) < text.index('call "%~dp0SetVariables.bat"')
        assert text.index(guard) < text.index('mkdir "%output_dir%"')
    assert 'echo ERROR: project merge requires approved RS_OCCLUSION_MANIFEST' in text


def test_pair_attempt_wires_scoped_orphans_and_keeps_export_directory_empty(tmp_path, monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    comps, ctx = context(tmp_path)
    for comp in comps:
        comp['bbox_utm'] = [0, 0, 20, 20]
    monkeypatch.delenv('RS_ALIGN_POOL_DIR', raising=False)
    monkeypatch.setattr(merge, 'snapshot_rs_log', lambda *a: None)
    monkeypatch.setattr(merge, 'rs_finalizing_counts', lambda *a: {})
    monkeypatch.setattr(merge.camera_registry, 'sanitize_and_census', lambda *a: (0, 0, 0))
    monkeypatch.setattr(merge.component_manifest, 'bbox_from_flight_log', lambda *a: [0, 0, 20, 20])
    calls = []
    def workflow(cli, complist, out, name, *args, orphan_inputs=None, **kwargs):
        assert list(Path(out).iterdir()) == []
        assert not Path(complist).is_relative_to(out)
        assert orphan_inputs and 'remote.jpg' not in Path(orphan_inputs['list']).read_text()
        assert len(Path(complist).read_text().splitlines()) == 2
        names = comps[0]['images'] + comps[1]['images'] + ['within.jpg']
        (Path(out) / f'{name}_c0.rsalign').write_bytes(b'mocked fusion')
        (Path(out) / 'identity_r0').mkdir()
        for index in range(len(names)):
            (Path(out) / 'identity_r0' / f'{index}.xmp').write_text('mocked position')
        (Path(out) / 'identity').mkdir()
        with (Path(out) / 'identity' / f'{name}_c0.csv').open('w', newline='') as stream:
            stream.write(f'#cameras {len(names)}\n')
            csv.writer(stream).writerows([[item, 0, 0, 0] for item in names])
        calls.append(out)
        return SimpleNamespace(success=True, errors=[])
    monkeypatch.setattr(merge, 'run_merge_workflow', workflow)
    report = merge.merge_cluster(None, comps, 0, str(tmp_path), str(tmp_path / 'ownedzones'),
        merge.LADDERS['merge_first'], 1, 'logs', LOG, orphan_context=ctx)
    assert len(calls) == 1 and report['converged']
    assert report['attempts'][0]['orphans']['offered_ids'] == ['within.jpg']
    assert report['attempts'][0]['cameras_lost'] == 0
    assert 'within.jpg' in ctx['registered'] and 'remote.jpg' not in ctx['registered']
    assert 'outside_pair_support=1' in caplog.text
    assert 'excluded remain available globally' in caplog.text
    assert report['attempts'][0]['orphans']['spatial_reasons']['remote.jpg'] == 'outside_pair_support'


def test_refused_pair_logs_reason_and_retains_global_orphans(tmp_path, monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    comps, ctx = context(tmp_path, ready=False)
    for comp in comps:
        comp['bbox_utm'] = [0, 0, 20, 20]
    before = set(ctx['registered'])
    monkeypatch.delenv('RS_ALIGN_POOL_DIR', raising=False)
    monkeypatch.setattr(merge, 'run_merge_workflow', lambda *a, **k: pytest.fail('refused dispatch ran'))
    report = merge.merge_cluster(None, comps, 0, str(tmp_path), str(tmp_path / 'ownedzones'),
        merge.LADDERS['merge_first'], 1, 'logs', LOG, orphan_context=ctx)
    assert not report['converged']
    assert ctx['registered'] == before
    assert 'orphan dispatch REFUSED: orphan_cli_probe_required' in caplog.text
    assert report['attempts'][0]['orphans']['excluded_ids'] == ['remote.jpg']
